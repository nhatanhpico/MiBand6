"""Ước tính nguy cơ bệnh bằng mô hình máy học (risk.py, risk_models.json do tools/train_risk_models.py tạo)."""

import datetime as dt

import pytest

from miband6 import health as H
from miband6 import risk as R

ADULT = {"age": 45, "sex": "male", "height": 170, "weight": 72, "pulse": 72, "sleep": 7.5, "active": 4}


def _risk(key, **change):
    return next(c for c in R.assess({**ADULT, **change})["conditions"] if c["key"] == key)


def test_tree_walk_follows_thresholds_and_missing_values():
    # một cây: x0 <= 1.5 sang trái (lá 1.0), lớn hơn sang phải; thiếu x0 thì sang phải (lá -1.0)
    model = {"baseline": 0.5, "asian_offset": 0.25,
             "trees": [[[0, 1.5, 1, 2, 0, 0.0], [-1, 0.0, 0, 0, 0, 1.0], [-1, 0.0, 0, 0, 0, -1.0]]]}
    sig = lambda z: 1 / (1 + 2.718281828459045 ** -z)   # noqa: E731
    assert R.probability(model, [1.5], asian=False) == pytest.approx(sig(1.5))      # đúng ngưỡng: sang trái
    assert R.probability(model, [2.0], asian=False) == pytest.approx(sig(-0.5))
    assert R.probability(model, [None], asian=False) == pytest.approx(sig(-0.5))
    assert R.probability(model, [1.0]) == pytest.approx(sig(1.75))                  # cộng độ dịch cho người châu Á


def test_shipped_models_are_validated():
    data = R.models()
    assert data["features"] == ["age", "male", "height", "bmi", "pulse", "sleep", "active"]
    assert set(data["models"]) == {"diabetes", "hypertension"}
    for m in data["models"].values():
        metrics = m["metrics"]
        assert metrics["auc"] >= 0.70 and metrics["asian_auc"] >= 0.70   # chỉ giữ bệnh đoán được đủ tốt
        assert 0.8 <= metrics["calibration_slope"] <= 1.2 and metrics["test_n"] > 1000
        assert len(m["trees"]) == m["params"]["trees"]
    assert data["data"]["sha256"] and data["data"]["adults"] > 10000


def test_needs_a_complete_adult_profile():
    assert R.assess({**ADULT, "sex": None}) == {"available": False, "missing": ["sex"], "reason": "profile"}
    assert R.assess({**ADULT, "height": None, "weight": None})["missing"] == ["height", "weight"]
    assert R.assess({**ADULT, "age": 16})["reason"] == "age"
    a = R.assess(ADULT)
    assert a["available"] and a["inputs"]["bmi"] == 24.9 and a["estimated"] == []
    assert all(0 < c["risk"] < 1 and c["status"] in ("good", "ok", "watch", "alert") for c in a["conditions"])


@pytest.mark.parametrize("key", ["diabetes", "hypertension"])
def test_risk_moves_the_plausible_way(key):
    """Ràng buộc đơn điệu khi huấn luyện: không bao giờ giảm khi tuổi, BMI, nhịp tim lúc nghỉ tăng, không tăng khi vận
    động nhiều ngày hơn."""
    def series(field, values, scale=1.0):
        return [_risk(key, **{field: v * scale})["risk"] for v in values]

    for field, values in (("age", range(20, 81, 5)), ("pulse", range(50, 111, 5))):
        s = series(field, values)
        assert all(b >= a - 1e-12 for a, b in zip(s, s[1:])) and s[-1] > s[0]
    s = series("weight", range(17, 41), 1.7 ** 2)    # BMI 17-40
    assert all(b >= a - 1e-12 for a, b in zip(s, s[1:])) and s[-1] > s[0]
    s = series("active", range(0, 8))
    assert all(b <= a + 1e-12 for a, b in zip(s, s[1:]))


def test_factors_are_only_unhealthy_values_that_raise_risk():
    heavy = _risk("diabetes", age=60, weight=95, pulse=85, active=0)   # BMI 32,9
    keys = [f["key"] for f in heavy["factors"]]
    assert keys[0] == "bmi" and set(keys) <= {"bmi", "pulse", "active", "sleep"}
    assert all(f["delta"] > 0 for f in heavy["factors"])
    assert heavy["ratio"] > 1.25 and heavy["compare"].startswith("Gấp")
    fit = _risk("diabetes", weight=60, pulse=62, active=6)                # BMI 20,8: không có gì cần thay đổi
    assert fit["factors"] == []
    # ngủ 5 giờ: dù mô hình có thể cho là "có lợi" với một bệnh nào đó, không bao giờ được liệt kê là có lợi
    for c in R.assess({**ADULT, "sleep": 5})["conditions"]:
        assert all(f["delta"] > 0 for f in c["factors"])


def test_missing_band_values_use_the_average_and_are_never_factors():
    a = R.assess({**ADULT, "pulse": None, "sleep": None, "active": None})
    assert a["estimated"] == ["pulse", "sleep", "active"]
    assert a["inputs"]["pulse"] == R.models()["impute"]["pulse"]["male"]
    assert all(f["key"] == "bmi" for c in a["conditions"] for f in c["factors"])


def test_asian_calibration_raises_diabetes_risk():
    """Người châu Á mắc tiểu đường nhiều hơn mức BMI của họ cho thấy: độ dịch học từ nhóm người châu Á của NHANES."""
    data = R.models()
    model = data["models"]["diabetes"]
    x = [ADULT["age"], 1.0, 170.0, 24.9, 72.0, 7.5, 4.0]
    assert model["asian_offset"] > 0.2
    assert R.probability(model, x) > R.probability(model, x, asian=False)


def test_band_inputs_from_minute_data():
    from miband6.healthdb import HealthDB, RISK_MIN_REST

    day = dt.date(2026, 3, 2)
    t0 = H.day_bounds(day.isoformat())[0]
    rows = []
    for m in range(8 * 60, 20 * 60):           # 08:00-20:00: ngồi yên nhịp tim 70, mỗi giờ đi bộ 10 phút nhịp tim 110
        walking = m % 60 < 10
        rows.append((t0 + m * 60, 1, 0, 100 if walking else 0, 110 if walking else 70, 0, 0, 0))
    by_ts = {r[0]: r for r in rows}
    t1 = t0 + 86400
    days = [{"date": (day - dt.timedelta(days=6 - i)).isoformat(), "wear": 900, "moderate": 15 if i % 2 else 0,
             "vigorous": 0} for i in range(7)]
    nights = [{"date": (day - dt.timedelta(days=i)).isoformat(), "minutes": 420, "awake": 20} for i in (2, 1, 0)]
    out = HealthDB._risk_inputs({"height": 170, "weight": 70}, 40.0, "male", rows, by_ts, [], set(), [], nights, days,
                                day, t1, partial=False)
    assert out["pulse"] == 70                  # đi bộ và 5 phút sau đó bị bỏ, chỉ còn lúc ngồi yên
    assert out["sleep"] == pytest.approx(7 + 20 / 60) and out["active"] == 3
    few = HealthDB._risk_inputs({}, None, None, rows[:RISK_MIN_REST], by_ts, [], set(), [], nights[:2], days[:2],
                                day, t1, partial=False)
    assert few["pulse"] is None and few["sleep"] is None and few["active"] is None
