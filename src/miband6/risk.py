"""Ước tính nguy cơ bệnh bằng mô hình máy học (cây tăng cường độ dốc) học từ NHANES 2009-2012.

Hàm thuần, Python thuần: mô hình nằm trong risk_models.json (tools/train_risk_models.py tạo), ứng dụng chỉ đi theo
các cây, không cần thư viện máy học nên gói ứng dụng macOS không lớn thêm. Ngưỡng và cách tính: docs/suc-khoe.md
(giữ hai nơi khớp nhau).

- Đầu vào: tuổi, giới tính, chiều cao, BMI (hồ sơ); nhịp tim lúc nghỉ, giờ ngủ mỗi đêm, số ngày vận động vừa/mạnh mỗi
  tuần (vòng tay, healthdb.risk_inputs). Thiếu số đo của vòng tay thì dùng trung vị cùng giới của dữ liệu học và ghi rõ.
- Đầu ra: xác suất hiện đang mắc (không phải nguy cơ trong 10 năm), hiệu chỉnh cho người châu Á; so với người cùng
  tuổi, giới, chiều cao có BMI 22, ngủ 7-8 giờ, vận động 5 ngày/tuần và nhịp tim lúc nghỉ ở mức trung vị; các yếu tố
  thay đổi được làm nguy cơ khác mức đó bao nhiêu (đổi riêng từng yếu tố về mức so sánh, tính lại).
- Đây là liên hệ thống kê trong dữ liệu dân số, không phải chẩn đoán hay quan hệ nhân quả.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .health import group_dec
from .i18n import tr

MODEL_PATH = Path(__file__).with_name("risk_models.json")
MIN_AGE, MAX_AGE = 18, 80          # mô hình học trên người lớn 18-80 tuổi (NHANES ghi 80 cho mọi người từ 80)
RANGES = {"height": (120, 210), "bmi": (13, 70), "pulse": (35, 150), "sleep": (2, 12), "active": (0, 7)}
MODIFIABLE = ("bmi", "pulse", "sleep", "active")
FACTOR_MIN = 0.005                 # yếu tố làm nguy cơ khác mức so sánh dưới 0,5 điểm % thì không liệt kê
# chỉ liệt kê yếu tố làm nguy cơ cao hơn khi giá trị nằm ngoài khoảng lành mạnh: BMI bình thường cho người châu Á,
# ngủ 7-9 giờ, vận động từ 5 ngày/tuần, nhịp tim lúc nghỉ tới 75. Trong khoảng đó (hay khi mô hình cho thấy "có lợi"
# một cách khó tin, như ngủ 5 giờ làm giảm nguy cơ tăng huyết áp) thì không coi là yếu tố cần thay đổi.
HEALTHY = {"bmi": (18.5, 23.0), "sleep": (7.0, 9.0), "active": (5, 7), "pulse": (35, 75)}

# trạng thái theo xác suất: (dưới ngưỡng -> trạng thái); ngưỡng là lựa chọn của ứng dụng, quanh tỉ lệ mắc trong dân số
LEVELS = {
    "diabetes": ((0.05, "good"), (0.10, "ok"), (0.25, "watch"), (1.01, "alert")),
    "hypertension": ((0.10, "good"), (0.20, "ok"), (0.35, "watch"), (1.01, "alert")),
}


@lru_cache(maxsize=1)
def models() -> dict | None:
    """Tệp mô hình đã xuất, hoặc None nếu chưa có (chưa chạy tools/train_risk_models.py)."""
    try:
        return json.loads(MODEL_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _tree(nodes: list, x: list) -> float:
    k = 0
    while True:
        feature, threshold, left, right, missing_left, value = nodes[k]
        if feature < 0:
            return value
        v = x[feature]
        if v is None or v != v:
            k = left if missing_left else right
        else:
            k = left if v <= threshold else right


def probability(model: dict, x: list, asian: bool = True) -> float:
    """Xác suất của một người (x theo thứ tự đặc trưng của tệp mô hình; None = thiếu)."""
    z = model["baseline"] + sum(_tree(t, x) for t in model["trees"])
    if asian:
        z += model["asian_offset"]
    return 1 / (1 + math.exp(-z))


def _pct(p: float) -> str:
    return f"{group_dec(p * 100, 0 if p >= 0.1 else 1)}%"


def _titles() -> dict:
    return {"diabetes": tr('Tiểu đường'), "hypertension": tr('Tăng huyết áp')}


def _what() -> dict:
    return {"diabetes": tr('Khả năng hiện đã mắc tiểu đường (được bác sĩ chẩn đoán), chủ yếu là type 2.'),
            "hypertension": tr('Khả năng huyết áp đo lúc nghỉ từ 140/90 mmHg trở lên.')}


def _advice(key: str, status: str, age: float) -> str:
    if key == "diabetes":
        text = (tr('Nên xét nghiệm đường huyết lúc đói hoặc HbA1c sớm.') if status in ("watch", "alert") else
                tr('Nên xét nghiệm đường huyết lúc đói hoặc HbA1c định kỳ (ADA khuyên từ 35 tuổi, sớm hơn nếu BMI từ 23 kèm yếu tố nguy cơ).'))
        return text
    if status in ("watch", "alert"):
        return tr('Nên đo huyết áp (máy đo tại nhà hoặc ở cơ sở y tế) vài lần ở các ngày khác nhau.')
    return (tr('Nên đo huyết áp ít nhất mỗi năm.') if age >= 40 else
            tr('Nên đo huyết áp 3-5 năm một lần nếu bình thường, mỗi năm khi có yếu tố nguy cơ.'))


def _factor_text(key: str, value: float, ref: float, delta: float) -> str:
    d = "+" + group_dec(delta * 100, 1)
    if key == "bmi":
        return tr('BMI {v} (so với {r}): {d} điểm %', v=group_dec(value, 1), r=group_dec(ref, 0), d=d)
    if key == "pulse":
        return tr('Nhịp tim lúc nghỉ {v} nhịp/phút (so với {r}): {d} điểm %', v=round(value), r=round(ref), d=d)
    if key == "sleep":
        return tr('Ngủ {v} giờ mỗi đêm (so với {r}): {d} điểm %', v=group_dec(value, 1), r=group_dec(ref, 1), d=d)
    return tr('Vận động {v} ngày mỗi tuần (so với {r}): {d} điểm %', v=round(value), r=round(ref), d=d)


def assess(inputs: dict) -> dict:
    """Ước tính nguy cơ từ inputs {age, sex ("male" | "female"), height, weight, pulse, sleep, active} (giá trị của vòng
    tay có thể None). Trả {"available": False, "missing": [...]} khi thiếu thông tin hồ sơ, hoặc mô hình chưa có."""
    data = models()
    missing = [k for k in ("age", "sex", "height", "weight") if inputs.get(k) in (None, "")]
    if data is None:
        return {"available": False, "missing": [], "reason": "no_model"}
    if missing:
        return {"available": False, "missing": missing, "reason": "profile"}
    age = float(inputs["age"])
    if age < MIN_AGE:
        return {"available": False, "missing": [], "reason": "age"}
    sex = inputs["sex"]
    height = float(inputs["height"])
    bmi = float(inputs["weight"]) / (height / 100) ** 2
    values = {"age": min(age, MAX_AGE), "male": 1.0 if sex == "male" else 0.0, "height": height, "bmi": bmi}
    estimated = []
    for key in ("pulse", "sleep", "active"):
        v = inputs.get(key)
        if v is None:
            v = data["impute"][key][sex]
            estimated.append(key)
        values[key] = float(v)
    for key, (lo, hi) in RANGES.items():
        values[key] = min(hi, max(lo, values[key]))
    order = data["features"]
    ref = {**values, "bmi": data["reference"]["bmi"], "sleep": data["reference"]["sleep"],
           "active": data["reference"]["active"], "pulse": data["reference"]["pulse"][sex]}
    vec = lambda v: [v[f] for f in order]   # noqa: E731
    out = []
    for key, model in data["models"].items():
        p = probability(model, vec(values))
        p_ref = probability(model, vec(ref))
        status = next(s for limit, s in LEVELS[key] if p < limit)
        factors = []
        for f in MODIFIABLE:
            lo, hi = HEALTHY[f]
            if f in estimated or lo <= values[f] <= hi:
                continue
            delta = p - probability(model, vec({**values, f: ref[f]}))
            if delta >= FACTOR_MIN:
                factors.append({"key": f, "delta": round(delta, 4), "text": _factor_text(f, values[f], ref[f], delta)})
        factors.sort(key=lambda r: -abs(r["delta"]))
        ratio = p / p_ref if p_ref > 0 else None
        if ratio is not None and ratio >= 1.25:
            compare = tr('Gấp {r} lần người cùng tuổi, giới có các chỉ số ở mức lành mạnh ({p}).',
                         r=group_dec(ratio, 1), p=_pct(p_ref))
        elif ratio is not None and ratio <= 0.8:
            compare = tr('Thấp hơn người cùng tuổi, giới có các chỉ số ở mức lành mạnh ({p}).', p=_pct(p_ref))
        elif status in ("watch", "alert"):   # cao mà gần bằng người lành mạnh cùng tuổi: chủ yếu do tuổi
            compare = tr('Gần bằng người cùng tuổi, giới có các chỉ số ở mức lành mạnh ({p}): nguy cơ cao chủ yếu do tuổi, nên vẫn cần kiểm tra định kỳ.',
                         p=_pct(p_ref))
        else:
            compare = tr('Gần bằng người cùng tuổi, giới có các chỉ số ở mức lành mạnh ({p}).', p=_pct(p_ref))
        m = model["metrics"]
        level = {"good": tr('Thấp'), "ok": tr('Vừa'), "watch": tr('Cao'), "alert": tr('Rất cao')}[status]
        out.append({"key": key, "title": _titles()[key], "what": _what()[key], "risk": round(p, 4),
                    "risk_text": _pct(p), "reference": round(p_ref, 4), "ratio": None if ratio is None else round(ratio, 2),
                    "status": status, "level": level, "compare": compare, "advice": _advice(key, status, age),
                    "factors": factors,
                    "metrics": {"auc": m["auc"], "auc_ci": m["auc_ci"], "asian_auc": m["asian_auc"],
                                "train_n": m["train_n"], "test_n": m["test_n"]}})
    return {"available": True, "conditions": out, "estimated": estimated,
            "inputs": {"age": int(values["age"]), "sex": sex, "height": round(height), "bmi": round(bmi, 1),
                       "pulse": round(values["pulse"]), "sleep": round(values["sleep"], 1), "active": round(values["active"]),
                       "days": inputs.get("days")},
            "model": {"data": data["data"]["name"], "adults": data["data"]["adults"],
                      "asian_adults": data["data"]["asian_adults"], "trained": data["trained"]}}
