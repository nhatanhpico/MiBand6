#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.26", "pandas>=2.1", "scikit-learn>=1.6,<2", "pyreadr>=0.5"]
# ///
"""Huấn luyện các mô hình ước tính nguy cơ bệnh của ứng dụng (src/miband6/risk_models.json).

Chạy (máy Mac M1 trở lên hay bất kỳ máy nào có uv; uv tự cài thư viện cho riêng script này, ứng dụng không cần chúng):

    uv run tools/train_risk_models.py            # tải dữ liệu nếu chưa có, huấn luyện, ghi mô hình và in báo cáo
    uv run tools/train_risk_models.py --check    # chỉ huấn luyện và đánh giá, không ghi tệp

Dữ liệu: NHANES 2009-2012 (Khảo sát Sức khỏe và Dinh dưỡng Quốc gia Hoa Kỳ, CDC; dữ liệu công, phạm vi công cộng),
bản đã ghép sẵn trong gói R "NHANES" (Pruim, ProjectMOSAIC). Tệp được kiểm SHA-256 để lần huấn luyện nào cũng dùng
đúng một dữ liệu. Chỉ người lớn từ 18 tuổi, bỏ người đang mang thai.

Đặc trưng: chỉ những gì ứng dụng có (hồ sơ và vòng tay): tuổi, giới tính, chiều cao, BMI, nhịp tim lúc nghỉ (NHANES:
mạch 60 giây khi ngồi nghỉ), số giờ ngủ mỗi đêm, số ngày vận động vừa/mạnh mỗi tuần.

Bệnh: chỉ những bệnh đoán được đủ tốt từ các đặc trưng đó (AUC kiểm chứng >= 0,70):
- tiểu đường: đã được bác sĩ chẩn đoán;
- tăng huyết áp: huyết áp đo trong buổi khám >= 140/90 mmHg (định nghĩa của WHO, Bộ Y tế).
Đã thử và bỏ (AUC kiểm chứng < 0,70): cholesterol toàn phần cao (~0,67), HDL thấp (~0,69), sàng lọc trầm cảm PHQ-2
(~0,64).

Phương pháp
- Cây tăng cường độ dốc (scikit-learn HistGradientBoostingClassifier) có ràng buộc đơn điệu: nguy cơ không giảm khi
  tuổi, BMI, nhịp tim lúc nghỉ tăng và không tăng khi vận động nhiều ngày hơn; giấc ngủ, chiều cao, giới không ràng
  buộc. Siêu tham số chọn bằng kiểm chứng chéo 5 lớp (log loss) trên chu kỳ 2009-2010.
- Kiểm chứng theo thời gian: học trên 2009-2010, đánh giá trên 2011-2012 (AUC kèm khoảng tin cậy 95% bootstrap,
  Brier, độ dốc / hệ số chặn hiệu chuẩn), riêng người châu Á (chỉ chu kỳ 2011-2012 tách riêng nhóm này).
- Mô hình cuối học trên cả hai chu kỳ. Hiệu chỉnh cho người châu Á: dự đoán kiểm chứng chéo (out-of-fold) của mọi
  người, rồi tìm độ dịch logit sao cho nhóm người châu Á khớp tỉ lệ thật (hồi quy logistic chỉ hệ số chặn, có offset),
  co về 0 theo sai số chuẩn (James-Stein dương) để độ dịch không rõ khác 0 gần như không được dùng. Ứng dụng dùng độ
  dịch này, như ngưỡng BMI cho người châu Á của nó.
- Xuất các cây ra JSON; ứng dụng tính bằng Python thuần (miband6.risk). Script kiểm tra xác suất tính bằng
  miband6.risk khớp predict_proba của scikit-learn.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "miband6" / "risk_models.json"
DATA_URL = "https://raw.githubusercontent.com/ProjectMOSAIC/NHANES/master/data/NHANESraw.rda"
DATA_SHA256 = "f93a21ad0e492f5bc492ac5b96ac81cdb9171b190ac149981f6ce8f9ebdea2e4"
CACHE = Path.home() / ".cache" / "miband6-train"

FEATURES = ["age", "male", "height", "bmi", "pulse", "sleep", "active"]
CONDITIONS = {   # khóa -> ràng buộc đơn điệu theo đặc trưng (+1 tăng, -1 giảm)
    "diabetes": {"age": 1, "bmi": 1, "pulse": 1, "active": -1},
    "hypertension": {"age": 1, "bmi": 1, "pulse": 1, "active": -1},
}
GRID = [{"learning_rate": lr, "max_depth": depth, "min_samples_leaf": leaf}
        for lr in (0.03, 0.06) for depth in (2, 3) for leaf in (50, 100)]
SEED = 20261104
# hồ sơ "lành mạnh" cùng tuổi, giới, chiều cao để so: BMI giữa khoảng bình thường cho người châu Á (18,5-22,9),
# ngủ 7-8 giờ, vận động 5 ngày/tuần (~150 phút WHO); nhịp tim lúc nghỉ lấy trung vị của người châu Á cùng giới
REFERENCE = {"bmi": 22.0, "sleep": 7.5, "active": 5}


def fetch(path: Path | None) -> Path:
    if path:
        return path
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / "NHANESraw.rda"
    if not target.exists():
        print(f"Tải {DATA_URL}", file=sys.stderr)
        with urllib.request.urlopen(DATA_URL, timeout=120) as r:
            target.write_bytes(r.read())
    return target


def load(path: Path) -> pd.DataFrame:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != DATA_SHA256:
        sys.exit(f"Dữ liệu khác bản đã kiểm ({digest}); kiểm tra nguồn rồi cập nhật DATA_SHA256 nếu đúng.")
    raw = pyreadr.read_r(str(path))["NHANESraw"]
    num = lambda c: pd.to_numeric(raw[c], errors="coerce")   # noqa: E731
    active = num("PhysActiveDays").clip(upper=7)
    active = active.where(raw["PhysActive"] != "No", 0.0).where(raw["PhysActive"].notna())
    d = pd.DataFrame({
        "year": raw["SurveyYr"].astype(str), "age": num("Age"), "male": (raw["Gender"] == "male").astype(float),
        "height": num("Height"), "bmi": num("BMI"), "pulse": num("Pulse"), "sleep": num("SleepHrsNight"),
        "active": active, "asian": (raw["Race3"] == "Asian"), "pregnant": raw["PregnantNow"].astype(str) == "Yes",
        "diabetes": raw["Diabetes"].map({"Yes": 1.0, "No": 0.0}).astype(float),
        "sbp": num("BPSysAve"), "dbp": num("BPDiaAve"),
    })
    d["hypertension"] = np.where(d.sbp.notna() & d.dbp.notna(), ((d.sbp >= 140) | (d.dbp >= 90)).astype(float), np.nan)
    return d[(d.age >= 18) & ~d.pregnant].reset_index(drop=True)


def model(params: dict, mono: dict, max_iter: int = 800, early: bool = True) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=max_iter, l2_regularization=1.0, early_stopping=early, validation_fraction=0.15 if early else None,
        n_iter_no_change=40, monotonic_cst=[mono.get(f, 0) for f in FEATURES], random_state=SEED, **params)


def cv_select(X: pd.DataFrame, y: np.ndarray, mono: dict) -> tuple[dict, int, float]:
    """Siêu tham số có log loss kiểm chứng chéo nhỏ nhất, và số cây (trung vị số cây khi dừng sớm)."""
    folds = list(StratifiedKFold(5, shuffle=True, random_state=SEED).split(X, y))
    best = None
    for params in GRID:
        losses, iters = [], []
        for tr, va in folds:
            m = model(params, mono).fit(X.iloc[tr], y[tr])
            losses.append(log_loss(y[va], m.predict_proba(X.iloc[va])[:, 1]))
            iters.append(m.n_iter_)
        score = float(np.mean(losses))
        if best is None or score < best[2]:
            best = (params, int(np.median(iters)), score)
    return best


def auc_ci(y: np.ndarray, p: np.ndarray, n: int = 1000) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    out = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            out.append(roc_auc_score(y[i], p[i]))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calibration(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Độ dốc và hệ số chặn hiệu chuẩn (hồi quy logistic y ~ a + b logit(p)); lý tưởng b = 1, a = 0."""
    z, a, b = logit(p), 0.0, 1.0
    for _ in range(50):   # Newton
        q = 1 / (1 + np.exp(-(a + b * z)))
        g = np.array([np.sum(y - q), np.sum((y - q) * z)])
        w = q * (1 - q)
        h = np.array([[np.sum(w), np.sum(w * z)], [np.sum(w * z), np.sum(w * z * z)]])
        step = np.linalg.solve(h, g)
        a, b = a + step[0], b + step[1]
        if np.abs(step).max() < 1e-10:
            break
    return float(b), float(a)


def offset(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Độ dịch logit d để sigmoid(logit(p) + d) khớp y (hợp lý cực đại), kèm sai số chuẩn."""
    z, d = logit(p), 0.0
    for _ in range(50):
        q = 1 / (1 + np.exp(-(z + d)))
        step = np.sum(y - q) / np.sum(q * (1 - q))
        d += step
        if abs(step) < 1e-12:
            break
    q = 1 / (1 + np.exp(-(z + d)))
    return float(d), float(1 / math.sqrt(np.sum(q * (1 - q))))


def export_trees(m: HistGradientBoostingClassifier) -> tuple[float, list]:
    """[(đặc trưng | -1, ngưỡng, trái, phải, thiếu thì sang trái, giá trị)] cho từng cây; đi trái khi x <= ngưỡng."""
    trees = []
    for (pred,) in m._predictors:
        nodes = []
        for n in pred.nodes:
            leaf = bool(n["is_leaf"])
            nodes.append([-1 if leaf else int(n["feature_idx"]), 0.0 if leaf else round(float(n["num_threshold"]), 6),
                          int(n["left"]), int(n["right"]), int(n["missing_go_to_left"]), round(float(n["value"]), 9)])
        trees.append(nodes)
    return round(float(m._baseline_prediction.ravel()[0]), 9), trees


def train(d: pd.DataFrame, key: str, mono: dict) -> dict:
    data = d[d[key].notna()].reset_index(drop=True)
    X, y = data[FEATURES], data[key].to_numpy()
    dev, test = (data.year == "2009_10").to_numpy(), (data.year == "2011_12").to_numpy()
    params, n_iter, cv_loss = cv_select(X[dev], y[dev], mono)
    # kiểm chứng theo thời gian: học trên 2009-2010, đánh giá trên 2011-2012
    held = model(params, mono, n_iter, early=False).fit(X[dev], y[dev])
    p = held.predict_proba(X[test])[:, 1]
    yt, asian_t = y[test], data.asian.to_numpy()[test]
    slope, intercept = calibration(yt, p)
    # mô hình cuối: cả hai chu kỳ; độ dịch cho người châu Á từ dự đoán out-of-fold
    final = model(params, mono, n_iter, early=False).fit(X, y)
    oof = np.zeros(len(y))
    for tr, va in StratifiedKFold(5, shuffle=True, random_state=SEED).split(X, y):
        oof[va] = model(params, mono, n_iter, early=False).fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[va])[:, 1]
    asian = data.asian.to_numpy()
    raw_shift, shift_se = offset(y[asian], oof[asian])
    # co độ dịch về 0 theo sai số chuẩn (dạng James-Stein dương): độ dịch không rõ khác 0 thì gần như không dùng
    shift = raw_shift * max(0.0, 1 - shift_se ** 2 / raw_shift ** 2) if raw_shift else 0.0
    baseline, trees = export_trees(final)
    metrics = {
        "auc": round(roc_auc_score(yt, p), 3), "auc_ci": [round(v, 3) for v in auc_ci(yt, p)],
        "brier": round(brier_score_loss(yt, p), 4), "calibration_slope": round(slope, 2),
        "calibration_intercept": round(intercept, 2), "test_n": int(test.sum()), "test_cases": int(yt.sum()),
        "asian_auc": round(roc_auc_score(yt[asian_t], p[asian_t]), 3), "asian_test_n": int(asian_t.sum()),
        "asian_observed": round(float(y[asian].mean()), 3), "asian_predicted": round(float(oof[asian].mean()), 3),
        "asian_offset_raw": round(raw_shift, 3), "asian_offset_se": round(shift_se, 3),
        "train_n": int(len(y)), "train_cases": int(y.sum()),
        "prevalence": round(float(y.mean()), 3), "cv_log_loss": round(cv_loss, 4),
    }
    return {"baseline": baseline, "asian_offset": round(shift, 4), "params": {**params, "trees": n_iter},
            "monotonic": mono, "metrics": metrics, "trees": trees, "_final": final, "_X": X}


def main() -> None:
    ap = argparse.ArgumentParser(description="Huấn luyện mô hình nguy cơ bệnh từ NHANES 2009-2012.")
    ap.add_argument("--data", type=Path, help="tệp NHANESraw.rda đã có (mặc định: tải về ~/.cache/miband6-train)")
    ap.add_argument("--check", action="store_true", help="chỉ huấn luyện và đánh giá, không ghi risk_models.json")
    args = ap.parse_args()
    d = load(fetch(args.data))
    asians = d[d.asian]
    reference = {**REFERENCE, "pulse": {s: round(float(asians[asians.male == m].pulse.median()), 1)
                                        for s, m in (("male", 1.0), ("female", 0.0))}}
    impute = {f: {s: round(float(d[d.male == m][f].median()), 1) for s, m in (("male", 1.0), ("female", 0.0))}
              for f in ("pulse", "sleep", "active")}
    out = {"format": 1, "trained": dt.date.today().isoformat(), "features": FEATURES, "reference": reference,
           "impute": impute, "algorithm": "HistGradientBoostingClassifier (scikit-learn), monotonic constraints",
           "data": {"name": "NHANES 2009-2012", "adults": int(len(d)), "asian_adults": int(d.asian.sum()),
                    "url": DATA_URL, "sha256": DATA_SHA256}, "models": {}}
    for key, mono in CONDITIONS.items():
        res = train(d, key, mono)
        m = res["metrics"]
        print(f"{key:13s} AUC {m['auc']} ({m['auc_ci'][0]}-{m['auc_ci'][1]}) Brier {m['brier']} "
              f"calibration slope {m['calibration_slope']} intercept {m['calibration_intercept']} | "
              f"Asian AUC {m['asian_auc']} (n={m['asian_test_n']}) observed {m['asian_observed']} "
              f"predicted {m['asian_predicted']} offset {m['asian_offset_raw']}±{m['asian_offset_se']} "
              f"-> {res['asian_offset']} | "
              f"{res['params']} | {len(res['trees'])} trees, train n={m['train_n']} cases={m['train_cases']}")
        out["models"][key] = {k: v for k, v in res.items() if not k.startswith("_")}
        # ứng dụng tính lại đúng xác suất của scikit-learn
        sys.path.insert(0, str(ROOT / "src"))
        from miband6 import risk as R

        X = res["_X"].sample(n=min(2000, len(res["_X"])), random_state=SEED)
        ours = np.array([R.probability(out["models"][key], [None if v != v else float(v) for v in row], asian=False)
                         for row in X.to_numpy()])
        theirs = res["_final"].predict_proba(X)[:, 1]
        gap = float(np.abs(ours - theirs).max())
        print(f"{'':13s} miband6.risk vs scikit-learn: max |Δp| = {gap:.2e}")
        if gap > 1e-6:
            sys.exit("Xuất cây sai: xác suất của miband6.risk khác scikit-learn.")
    if not args.check:
        OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n", "utf-8")
        print(f"Đã ghi {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
