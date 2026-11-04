"""Mô hình cá nhân học từ dữ liệu cũ của chính người dùng. Hàm thuần, không cần thư viện ngoài, chạy trên máy.

Mô hình nhịp tim khi ngủ (rhr_model)
- Nhịp tim khi ngủ tăng vì nhiều lý do đã biết: tập nặng hôm trước, tập sát giờ ngủ, đi ngủ muộn, ngủ ngắn. Mô hình
  học xem với riêng bạn mỗi lý do làm tăng bao nhiêu, để phần còn lại ("không giải thích được") mới là tín hiệu đáng
  chú ý (sắp ốm, căng thẳng, rượu bia...). insights.body_signals và insights.mental_state dùng phần này.
- Mục tiêu: độ lệch nhịp tim khi ngủ của mỗi đêm so với mức nền của nó (trung vị tối đa 30 đêm trước,
  insights.rhr_baseline). Đặc trưng (0 = đêm bình thường của bạn): tải vận động hôm trước so với thường lệ
  (TRIMP / 100), tải trong 4 giờ trước khi ngủ (TRIMP / 100), đi ngủ muộn hơn thường lệ (giờ), ngủ ngắn hơn thường
  lệ (giờ).
- Hồi quy ridge: hệ số chặn không bị phạt, phạt RIDGE trên đặc trưng đã chuẩn hóa (ít đêm, các yếu tố liên quan
  nhau: đi ngủ muộn thường cũng ngủ ngắn). Các đêm lệch quá OUTLIER_SD độ lệch chuẩn bền vững (thường là đêm ốm) không
  dùng để học.
- Kiểm chứng chéo bỏ-một (LOO): mỗi đêm được dự đoán bằng mô hình học từ các đêm còn lại (tính một lần qua đường chéo
  ma trận mũ, nên học từ cả năm dữ liệu vẫn nhanh). Mô hình chỉ được dùng khi có từ MIN_TRAIN đêm và sai số tuyệt đối
  trung bình LOO nhỏ hơn mô hình chỉ có hệ số chặn ít nhất MIN_GAIN; nếu không, ứng dụng chỉ so với mức nền như trước.
  Mức ảnh hưởng của từng yếu tố chỉ được báo khi |t| >= EFFECT_T.
- Học từ bao lâu (learning_curve): dữ liệu càng dài thì càng nhiều đêm để học. Để thấy điều đó có thật với từng người,
  mỗi đêm trong CURVE_TESTS đêm gần nhất được dự đoán bằng mô hình chỉ học từ 1 tuần, 1 tháng, 3, 6 tháng hay 1 năm
  dữ liệu trước nó (không nhìn trước), rồi so sai số.
"""

from __future__ import annotations

import datetime as dt
import math

FEATURES = ("load", "evening", "late", "short")
MIN_TRAIN = 21            # số đêm học tối thiểu
RIDGE = 4.0               # hệ số phạt trên đặc trưng đã chuẩn hóa
MIN_GAIN = 0.05           # LOO MAE phải nhỏ hơn mô hình chỉ có hệ số chặn ít nhất 5%
OUTLIER_SD = 3.5          # bỏ khỏi dữ liệu học các đêm lệch quá ngần này độ lệch chuẩn bền vững
RESID_SD_FLOOR = 1.5      # nhịp/phút: độ lệch chuẩn sai số dự đoán không nhỏ hơn
EFFECT_T = 2.0            # chỉ báo mức ảnh hưởng của một yếu tố khi hệ số khác 0 rõ (|t| >= ngần này)
CURVE_WINDOWS = (7, 30, 90, 180, 365)   # ngày dữ liệu học thử: 1 tuần, 1 tháng, 3 tháng, 6 tháng, 1 năm
CURVE_TESTS = 30          # số đêm gần nhất dùng để đo sai số của từng độ dài
CURVE_MIN_TESTS = 5       # cần dự đoán được ít nhất ngần này đêm thì mới báo sai số


def median(values: list[float]) -> float:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def robust_sd(values: list[float]) -> float:
    """Độ lệch chuẩn ước tính bền vững: 1,4826 x trung vị độ lệch tuyệt đối (bằng độ lệch chuẩn khi phân phối chuẩn)."""
    if not values:
        return 0.0
    m = median(values)
    return 1.4826 * median([abs(v - m) for v in values])


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Giải a x = b (khử Gauss có chọn trụ); a đối xứng xác định dương nên luôn giải được."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("ma trận suy biến")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def ridge_fit(xs: list[list[float]], ys: list[float], lam: float = RIDGE) -> dict:
    """y ~ a + sum(b_j x_j). Đặc trưng được chuẩn hóa (trung bình 0, độ lệch chuẩn 1) trước khi phạt lam; hệ số trả về
    theo đơn vị gốc. Đặc trưng không đổi trong dữ liệu học có hệ số 0."""
    n, p = len(xs), len(xs[0])
    mean = [sum(r[j] for r in xs) / n for j in range(p)]
    sd = [math.sqrt(sum((r[j] - mean[j]) ** 2 for r in xs) / n) for j in range(p)]
    z = [[(r[j] - mean[j]) / sd[j] if sd[j] > 1e-9 else 0.0 for j in range(p)] for r in xs]
    ym = sum(ys) / n
    gram = [[sum(z[i][j] * z[i][k] for i in range(n)) for k in range(p)] for j in range(p)]
    # đặc trưng không đổi: cột toàn 0, giữ hệ thống giải được (hệ số của nó luôn là 0)
    a = [[gram[j][k] + ((lam if sd[j] > 1e-9 else 1.0) if j == k else 0.0) for k in range(p)] for j in range(p)]
    beta = _solve(a, [sum(z[i][j] * (ys[i] - ym) for i in range(n)) for j in range(p)])
    coef = [beta[j] / sd[j] if sd[j] > 1e-9 else 0.0 for j in range(p)]
    return {"intercept": ym - sum(coef[j] * mean[j] for j in range(p)), "coef": coef, "sd": sd, "mean": mean,
            "gram": gram, "a": a, "beta": beta}


def predict(fit: dict, x: list[float]) -> float:
    return fit["intercept"] + sum(c * v for c, v in zip(fit["coef"], x))


def _t_values(fit: dict, xs: list[list[float]], ys: list[float]) -> list[float]:
    """t của từng hệ số: hệ số / sai số chuẩn, với Var(beta) ~ s^2 A^-1 Z'Z A^-1 (A = Z'Z + lam I) của ridge."""
    n, p = len(xs), len(fit["coef"])
    resid = [y - predict(fit, x) for x, y in zip(xs, ys)]
    s2 = sum(e * e for e in resid) / max(1, n - p - 1)
    inv = [_solve(fit["a"], [1.0 if i == k else 0.0 for i in range(p)]) for k in range(p)]   # cột của A^-1
    out = []
    for j in range(p):
        if fit["sd"][j] <= 1e-9:
            out.append(0.0)
            continue
        var = s2 * sum(inv[j][r] * fit["gram"][r][c] * inv[j][c] for r in range(p) for c in range(p))
        out.append(fit["beta"][j] / math.sqrt(var) if var > 0 else 0.0)
    return out


def _row(x: dict) -> list[float]:
    return [float(x.get(k) or 0.0) for k in FEATURES]


def _clean(rows: list[dict]) -> list[dict]:
    """Bỏ các đêm lệch quá OUTLIER_SD độ lệch chuẩn bền vững (thường là đêm ốm, say rượu) khỏi dữ liệu học."""
    ys = [r["y"] for r in rows]
    if not ys:
        return []
    centre, spread = median(ys), max(robust_sd(ys), 1.0)
    return [r for r in rows if abs(r["y"] - centre) <= OUTLIER_SD * spread]


def loo_residuals(xs: list[list[float]], ys: list[float], lam: float = RIDGE) -> list[float]:
    """Sai số kiểm chứng chéo bỏ-một của ridge, tính bằng một lần học: e_i / (1 - h_ii), với h_ii = 1/n + z_i' A^-1 z_i
    (chuẩn hóa theo cả dữ liệu, như cách tính GCV thường dùng)."""
    fit = ridge_fit(xs, ys, lam)
    n, p = len(xs), len(xs[0])
    inv = [_solve(fit["a"], [1.0 if i == k else 0.0 for i in range(p)]) for k in range(p)]   # A^-1 (đối xứng)
    out = []
    for x, y in zip(xs, ys):
        z = [(x[j] - fit["mean"][j]) / fit["sd"][j] if fit["sd"][j] > 1e-9 else 0.0 for j in range(p)]
        h = 1 / n + sum(z[r] * inv[r][c] * z[c] for r in range(p) for c in range(p))
        out.append((y - predict(fit, x)) / (1 - h))
    return out


def learning_curve(rows: list[dict], windows: tuple = CURVE_WINDOWS, tests: int = CURVE_TESTS) -> list[dict]:
    """Sai số dự đoán khi chỉ học từ `days` ngày dữ liệu ngay trước mỗi đêm cần đoán, trên tối đa `tests` đêm gần
    nhất. Mỗi độ dài: {"days", "status": "ok" | "need_more" (lịch sử chưa dài tới đó) | "too_few" (ít hơn MIN_TRAIN đêm
    để học), "mae", "mae_null" (chỉ dùng mức nền), "nights" (số đêm học, trung vị), "tests"}."""
    rows = [r for r in rows if r.get("y") is not None]
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    span = (dates[-1] - dates[0]).days if dates else 0
    out = []
    for days in windows:
        if span < days:
            out.append({"days": days, "status": "need_more"})
            continue
        errors, nulls, sizes = [], [], []
        for k in range(max(0, len(rows) - tests), len(rows)):
            train = _clean([rows[i] for i in range(k) if 0 < (dates[k] - dates[i]).days <= days])
            if len(train) < MIN_TRAIN:
                continue
            ys = [r["y"] for r in train]
            fit = ridge_fit([_row(r["x"]) for r in train], ys)
            errors.append(abs(rows[k]["y"] - predict(fit, _row(rows[k]["x"]))))
            nulls.append(abs(rows[k]["y"] - sum(ys) / len(ys)))
            sizes.append(len(train))
        if len(errors) < CURVE_MIN_TESTS:
            out.append({"days": days, "status": "too_few"})
            continue
        out.append({"days": days, "status": "ok", "mae": round(sum(errors) / len(errors), 2),
                    "mae_null": round(sum(nulls) / len(nulls), 2), "nights": int(median(sizes)), "tests": len(errors)})
    return out


def rhr_model(train: list[dict], targets: list[dict] | None = None) -> dict:
    """Học mô hình nhịp tim khi ngủ từ `train` và giải thích các đêm `targets`.

    Mỗi đêm: {"date", "y": độ lệch so với mức nền (nhịp/phút), "x": {đặc trưng: giá trị hoặc None (= như thường lệ)}}.
    Trả {"active", "nights", "excluded", "need", "mae", "mae_null", "gain", "r2", "resid_sd", "effects",
    "predictions": {ngày: {"expected", "contrib": {đặc trưng: nhịp/phút}}}}; effects/predictions chỉ có khi active."""
    rows = [r for r in train if r.get("y") is not None]
    out: dict = {"active": False, "nights": len(rows), "excluded": 0, "need": MIN_TRAIN, "effects": [],
                 "predictions": {}}
    if len(rows) < MIN_TRAIN:
        return out
    keep = _clean(rows)
    out.update(nights=len(keep), excluded=len(rows) - len(keep))
    if len(keep) < MIN_TRAIN:
        return out
    xs, ys = [_row(r["x"]) for r in keep], [r["y"] for r in keep]
    errors = loo_residuals(xs, ys)   # kiểm chứng chéo bỏ-một
    n, ym = len(ys), sum(ys) / len(ys)
    null_errors = [(y - ym) * n / (n - 1) for y in ys]   # bỏ-một của mô hình chỉ có hệ số chặn
    mae = sum(abs(e) for e in errors) / len(errors)
    mae_null = sum(abs(e) for e in null_errors) / len(null_errors)
    total = sum((y - sum(ys) / len(ys)) ** 2 for y in ys)
    r2 = 1 - sum(e * e for e in errors) / total if total > 0 else 0.0
    gain = 1 - mae / mae_null if mae_null > 0 else 0.0
    out.update(mae=round(mae, 2), mae_null=round(mae_null, 2), gain=round(gain, 3), r2=round(max(0.0, r2), 3),
               resid_sd=round(max(robust_sd(errors), RESID_SD_FLOOR), 2))
    if gain < MIN_GAIN:
        return out
    fit = ridge_fit(xs, ys)
    t = _t_values(fit, xs, ys)
    out["active"] = True
    out["effects"] = [{"key": k, "per_unit": round(c, 2), "t": round(tv, 1)}
                      for k, c, tv in zip(FEATURES, fit["coef"], t) if abs(tv) >= EFFECT_T and abs(c) >= 0.2]
    for r in targets or []:
        x = _row(r["x"])
        contrib = {k: round(c * v, 1) for k, c, v in zip(FEATURES, fit["coef"], x) if abs(c * v) >= 0.05}
        out["predictions"][r["date"]] = {"expected": round(predict(fit, x), 1), "contrib": contrib}
    return out
