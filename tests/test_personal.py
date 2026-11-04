"""Nhật ký riêng: chu kỳ kinh nguyệt (nữ), xuất tinh (nam), và các chỉ số theo hồ sơ (tuổi, giới tính, BMI)."""

import datetime as dt

from miband6 import health as H
from miband6 import insights as I
from miband6 import personal as PS

D = dt.date.fromisoformat


def _period(start: str, days: int = 5) -> list[str]:
    return [(D(start) + dt.timedelta(days=i)).isoformat() for i in range(days)]


def test_periods_group_days_and_tolerate_short_gaps():
    days = _period("2026-09-01", 4) + ["2026-09-07"] + _period("2026-09-29", 5)   # ngày 5-6 quên ghi
    ps = PS.periods(days)
    assert [(a.isoformat(), b.isoformat()) for a, b, _ in ps] == [("2026-09-01", "2026-09-07"), ("2026-09-29", "2026-10-03")]


def test_cycle_status_predicts_next_period_and_fertile_window():
    days = _period("2026-08-04") + _period("2026-09-01") + _period("2026-09-29")   # chu kỳ 28 ngày
    st = PS.cycle_status(days, D("2026-10-10"))
    assert st["cycle_length"] == 28 and st["period_length"] == 5 and st["cycles"] == 2
    assert st["day"] == 12 and st["next_start"] == "2026-10-27" and st["days_to_next"] == 17
    assert st["ovulation"] == "2026-10-13" and st["fertile"] == ["2026-10-08", "2026-10-14"]
    assert st["phase"] == "follicular" and not st["late"]
    assert "2026-10-27" in st["predicted_period"] and "2026-10-12" in st["predicted_fertile"]
    assert PS.cycle_status(days, D("2026-10-13"))["phase"] == "ovulation"
    assert PS.cycle_status(days, D("2026-10-20"))["phase"] == "luteal"
    assert PS.cycle_status(days, D("2026-10-01"))["phase"] == "menstrual"
    late = PS.cycle_status(days, D("2026-10-30"))
    assert late["late"] == 3 and late["phase"] is None and late["days_to_next"] == 0


def test_forgotten_month_does_not_skew_cycle_length():
    days = _period("2026-06-01") + _period("2026-06-30") + _period("2026-08-27") + _period("2026-09-25")
    st = PS.cycle_status(days, D("2026-10-01"))
    assert st["cycle_length"] == 29          # 29, (58 bỏ vì quá dài), 29
    assert PS.cycle_status([], D("2026-10-01")) is None


def _nights(start: str, n: int, hr) -> list[dict]:
    return [{"date": (D(start) + dt.timedelta(days=i)).isoformat(), "hr": hr(i), "minutes": 450, "deep": 90, "awake": 10,
             "start": 1_790_000_000 + i * 86400} for i in range(n)]


def test_luteal_rise_in_resting_hr_is_removed_before_readiness():
    days = _period("2026-08-04") + _period("2026-09-01") + _period("2026-09-29")
    phase = lambda d: PS.phase_on(D(d), PS.periods(days), 28, 5)   # noqa: E731
    nights = _nights("2026-08-10", 70, lambda i: 58)
    for n in nights:                                                 # pha hoàng thể: nhịp tim khi ngủ +3
        n["hr"] += 3 if phase(n["date"]) == "luteal" else 0
    offset = PS.adjust_luteal_hr(nights, days)
    assert offset == 3.0                                             # mức chênh của riêng người này
    luteal = [n for n in nights if phase(n["date"]) == "luteal"]
    assert luteal and all(n["hr_adj"] == 58 for n in luteal)
    # đêm pha hoàng thể không bị coi là "nhịp tim nghỉ cao hơn thường lệ"
    upto = nights[: nights.index(luteal[-1]) + 1]
    part = I._rhr_part(upto, upto[-1])
    assert part["score"] == 100 and "hoàng thể" in part["detail"]


def test_luteal_offset_falls_back_to_typical_value():
    days = _period("2026-09-29")
    nights = _nights("2026-10-01", 5, lambda i: 60)
    assert PS.luteal_rhr_offset(nights, PS.periods(days), 28, 5) == (PS.LUTEAL_RHR, False)


def test_ejaculation_stats_compare_following_nights():
    nights = _nights("2026-09-01", 40, lambda i: 60)
    events = {}
    for i in range(0, 40, 5):                                        # mỗi 5 ngày một lần; đêm sau ngủ dài hơn 30 phút
        day = D("2026-09-01") + dt.timedelta(days=i)
        events[day.isoformat()] = 1
        for n in nights:
            if D(n["date"]) == day + dt.timedelta(days=1):
                n["minutes"] += 30
    st = PS.ejaculation_stats(events, nights, D("2026-10-10"))
    assert st["last"] == "2026-10-06" and st["days_since"] == 4
    assert st["count_30"] == 6 and st["per_week"] == round(5 / 4, 1)   # 5 lần trong 28 ngày
    assert st["sleep"]["after"]["n"] == 8 and st["sleep"]["after"]["minutes"] == 480
    assert st["sleep"]["other"]["minutes"] == 450
    sparse = PS.ejaculation_stats({"2026-10-01": 1}, nights, D("2026-10-10"))
    assert sparse["sleep"] is None and sparse["nights_after"] == 1


def test_profile_shapes_hr_max_sleep_need_and_bmi():
    assert I.hr_max(30) == 187 and round(I.hr_max(30, "female"), 1) == 179.6     # Tanaka / Gulati
    assert I.sleep_need(16) == 540 and I.sleep_need(30) == I.sleep_need(None) == 450
    teen, _ = I.sleep_score({"minutes": 480, "awake": 10, "deep": 80}, None, 540)
    adult, _ = I.sleep_score({"minutes": 480, "awake": 10, "deep": 80}, None, 450)
    assert teen < adult                                                            # 8 giờ là thiếu ở tuổi 16
    assert H.body_mass_index(170, 65) == 22.5 and H.bmi_class(22.5)[0] == "good"
    assert H.bmi_class(24)[0] == "ok" and H.bmi_class(31)[0] == "alert" and H.bmi_class(17)[0] == "watch"
    assert H.body_mass_index(None, 65) is None and H.body_mass_index(170, "x") is None
    assert PS.sex_of({"gender": 1}) == "female" and PS.sex_of({"gender": "0"}) == "male"
    assert PS.sex_of({"gender": 2}) is None and PS.sex_of({}) is None


def _weights(start: str, values: list[float], step: int = 7, height: float = 176) -> list[dict]:
    return [{"date": (D(start) + dt.timedelta(days=i * step)).isoformat(), "weight": w, "height": height}
            for i, w in enumerate(values)]


def test_body_trend_change_rate_and_bmi():
    entries = _weights("2026-08-01", [60, 60.2, 60.1, 60.3, 60.2, 60.4, 60.3, 60.5, 60.4, 60.6, 60.5, 60.7, 60.6, 60.8])
    t = PS.body_trend(entries, D("2026-11-01"))
    assert t["weight"] == 60.8 and t["height"] == 176 and t["bmi"] == 19.6 and t["bmi_status"] == "good"
    assert t["change_30"]["kg"] == 0.4 and t["change_90"]["kg"] == 0.8   # so với 26/9 (60,4) và 1/8 (60)
    assert 0 < t["rate"] < 0.2 and t["status"] == "good"
    assert PS.body_trend([], D("2026-11-01")) is None


def test_body_trend_flags_fast_and_large_changes():
    fast = PS.body_trend(_weights("2026-09-01", [70, 68.5, 67, 65.5, 64]), D("2026-09-29"))
    assert fast["rate"] <= -1 and fast["status"] == "watch" and any("0,5–1" in n or "0.5–1" in n for n in fast["notes"])
    lost = PS.body_trend(_weights("2026-05-01", [70, 69, 68, 67, 66], step=30), D("2026-09-01"))
    assert lost["change_6m"]["pct"] <= -5 and lost["status"] == "watch"
    thin = PS.body_trend(_weights("2026-09-01", [52, 51.5, 51, 50.5], height=170), D("2026-09-22"))
    assert thin["bmi"] < 18.5 and thin["status"] == "alert"


def test_weight_trend_appears_in_analysis():
    trend = PS.body_trend(_weights("2026-09-01", [60, 60.5, 61, 61.5, 62]), D("2026-10-01"))
    a = H.analyze([], [], 8000, None, [], [], 0, 0, None, body={"age": 25, "height": 176, "weight": 62, "trend": trend})
    item = next(i for i in a["items"] if i["key"] == "weight")
    assert item["value"].startswith("62") and "+" in item["value"]
