"""Mức sẵn sàng, trạng thái tinh thần, cường độ vận động, nhịp sinh học (insights.py) và ước tính REM (health.py)."""

import datetime as dt

from miband6 import health as H
from miband6 import insights as I


# ---------------------------------------------------------------- REM ước tính từ nhịp tim


def _night(hr_of_minute, minutes=420, deep_until=90, start=1_800_000_000):
    """Một giấc giả: sâu `deep_until` phút đầu rồi nông; nhịp tim theo hàm của phút."""
    stages = [[start, start + deep_until * 60, "deep"], [start + deep_until * 60, start + minutes * 60, "light"]]
    sess = {"start": start, "end": start + minutes * 60, "deep": deep_until, "light": minutes - deep_until, "rem": 0,
            "awake": 0, "minutes": minutes, "stages": stages}
    by_ts = {}
    for i in range(minutes):
        hr = hr_of_minute(i)
        by_ts[start + 60 * i] = (start + 60 * i, 9, 0, 0, hr if hr else 255, 0, 0, 0)
    return sess, by_ts


def test_rem_found_where_heart_rate_rises():
    blocks = [(150, 170), (240, 265), (330, 360)]   # ba giai đoạn REM: nhịp tim tăng 8 nhịp/phút
    sess, by_ts = _night(lambda i: 58 + (8 if any(a <= i < b for a, b in blocks) else 0) + (i % 3) - 1)
    assert H.estimate_rem(sess, by_ts)
    rem_minutes = {(a - sess["start"]) // 60 + k for a, b, kind in sess["stages"] if kind == "rem" for k in range((b - a) // 60)}
    planted = {m for a, b in blocks for m in range(a, b)}
    assert len(rem_minutes & planted) >= 0.8 * len(planted)          # tìm thấy phần lớn REM thật
    assert len(rem_minutes - planted) <= 0.25 * len(rem_minutes)     # ít báo nhầm
    assert sess["rem"] == len(rem_minutes) and sess["deep"] + sess["light"] + sess["rem"] == sess["minutes"]
    assert sess["rem_estimated"] and min(rem_minutes) >= H.REM_LATENCY
    assert sess["rem"] <= H.REM_MAX_SHARE * sess["minutes"]


def test_rem_needs_heart_rate_every_minute():
    sess, by_ts = _night(lambda i: 60 if i % 10 == 0 else None)       # đo 10 phút một lần
    assert not H.estimate_rem(sess, by_ts) and sess["rem"] == 0 and "rem_estimated" not in sess
    short, by_ts = _night(lambda i: 60, minutes=120)
    assert not H.estimate_rem(short, by_ts)


# ---------------------------------------------------------------- nhịp sinh học


def _nights(mids, start_date="2026-10-05", minutes=450):
    d0 = dt.date.fromisoformat(start_date)
    return [{"date": (d0 + dt.timedelta(days=i)).isoformat(), "mid": m, "minutes": minutes + (60 if (d0 + dt.timedelta(days=i)).weekday() >= 5 else 0),
             "awake": 0, "deep": 60, "rem": 0, "hr": 60} for i, m in enumerate(mids)]


def test_social_jetlag_and_chronotype():
    # 2026-10-05 là thứ Hai; ngày thức dậy thứ Bảy/Chủ nhật giữa giấc muộn hơn 2 giờ
    d0 = dt.date(2026, 10, 5)
    mids = [240 + (120 if (d0 + dt.timedelta(days=i)).weekday() >= 5 else 0) for i in range(28)]
    c = I.circadian(_nights(mids))
    assert c["msw"] == 240 and c["msf"] == 360 and c["sjl"] == 120
    # ngày nghỉ ngủ dài hơn 60 phút: MSFsc = MSF - (SDf - SDweek)/2 = 360 - (510 - 467.14)/2 ≈ 338.6
    assert abs(c["chronotype"] - 339) <= 1 and c["chronotype_clock"] == "05:39"
    assert c["level"] in ("moderate", "high") and c["strain"] > 30
    steady = I.circadian(_nights([240] * 28, minutes=450))
    assert steady["sjl"] == 0 and steady["cpd"] < 0.6 and steady["strain"] < 30 and steady["level"] == "low"


def test_sleep_regularity_index():
    day = 86400
    t0 = 1_800_000_000 - 1_800_000_000 % day
    covered = set(range(t0, t0 + 10 * day, 60))
    regular = {t for t in covered if (t - t0) % day < 8 * 3600}           # ngủ đúng giờ mỗi ngày
    assert I.sleep_regularity(regular, covered, t0, t0 + 10 * day) == 100
    shifted = {t for t in covered if ((t - t0) % day - ((t - t0) // day % 2) * 4 * 3600) % day < 8 * 3600}
    sri = I.sleep_regularity(shifted, covered, t0, t0 + 10 * day)
    assert 30 < sri < 60                                                   # lệch 4 giờ cách ngày
    assert I.sleep_regularity(regular, set(range(t0, t0 + 2 * day, 60)), t0, t0 + 2 * day) is None   # quá ít dữ liệu


# ---------------------------------------------------------------- mức sẵn sàng, cường độ, tinh thần


def _days(n=40, trimp=100, stress=30, end="2026-11-02"):
    d1 = dt.date.fromisoformat(end)
    return [{"date": (d1 - dt.timedelta(days=n - 1 - i)).isoformat(), "steps": 9000, "wear": 900, "light": 120,
             "moderate": 30, "vigorous": 10, "trimp": trimp, "stress": stress, "stress_n": 50, "stress_high": 2}
            for i in range(n)]


def test_readiness_baseline_and_caps():
    nights = _nights([240] * 30, start_date="2026-10-04")
    for n in nights:
        n.update(hr=58, hr_low_at=0.4, minutes=460)
    good = I.readiness(nights, _days(), hrmax=190)
    assert good["score"] >= 85 and good["verdict"] == "train_hard" and good["status"] == "good"
    assert {p["key"] for p in good["parts"]} >= {"rhr", "sleep", "stress_balance"}
    assert "152-190" in good["plan"]                                       # vùng 4-5 theo nhịp tim tối đa 190
    sick = [dict(n) for n in nights]
    sick[-1].update(hr=68, minutes=300, hr_low_at=0.9)                     # nhịp tim nghỉ +10, ngủ 5 giờ
    bad = I.readiness(sick, _days())
    assert bad["score"] <= 59 and bad["verdict"] in ("easy", "rest")
    rhr = next(p for p in bad["parts"] if p["key"] == "rhr")
    assert rhr["score"] < 40 and "+10" in rhr["value"]
    assert I.readiness([], _days()) is None
    assert I.readiness_progress(nights[:3]) == {"nights": 3, "need": 8}


def test_recovery_time_after_hard_workout():
    nights = _nights([240] * 30, start_date="2026-10-04")
    for n in nights:
        n.update(hr=58, hr_low_at=0.4, minutes=460)
    now = 1_800_000_000
    # buổi tập nặng (TRIMP 450, gấp 4,5 lần tải thường ngày 100) kết thúc 20 giờ trước
    tired = I.readiness(nights, _days(), fatigue={"hours": [(now - 20 * 3600, 450.0)], "now": now}, hrmax=190)
    rec = next(p for p in tired["parts"] if p["key"] == "recovery_time")
    # mệt mỏi 450 e^(-20/36) = 258 so với mức ổn định 100 x 36/24 = 150: còn 36 ln(258/150) ≈ 19,5 giờ
    assert 18 <= rec["hours"] <= 21 and tired["recovery_hours"] == rec["hours"]
    assert tired["verdict"] == "train" and tired["score"] <= 79             # còn hồi phục: không tập nặng, điểm khớp lời khuyên
    rested = I.readiness(nights, _days(), fatigue={"hours": [(now - 5 * 86400, 450.0)], "now": now})
    assert next(p for p in rested["parts"] if p["key"] == "recovery_time")["hours"] == 0
    # tải đều đặn mỗi giờ đúng bằng mức thường ngày: không cần thêm thời gian hồi phục
    steady = [(now - h * 3600, 100 / 24) for h in range(1, 24 * 14)]
    assert I.recovery_hours(steady, now, 100) < 1


def test_load_spike_alone_does_not_force_an_easy_day():
    """Tuần qua tải gấp 3 lần thường lệ (ví dụ đổi chu kỳ đo nhịp tim, hay bắt đầu tập lại) nhưng ngủ tốt, nhịp tim nghỉ
    bình thường: cân bằng vận động thấp chỉ góp theo trọng số, không tự kéo điểm xuống 59 ("nên tập nhẹ")."""
    nights = _nights([240] * 30, start_date="2026-10-04")
    for n in nights:
        n.update(hr=58, hr_low_at=0.4, minutes=460)
    days = _days(trimp=60)
    for d in days[-7:]:
        d["trimp"] = 300
    r = I.readiness(nights, days, hrmax=190)
    acwr = next(p for p in r["parts"] if p["key"] == "activity_balance")
    assert acwr["score"] < 40
    assert r["score"] > 59 and r["verdict"] in ("train", "train_hard")
    # còn một thành phần cơ thể rất thấp (nhịp tim nghỉ tăng mạnh) thì vẫn bị giới hạn như trước
    nights[-1].update(hr=70)
    assert I.readiness(nights, days, hrmax=190)["score"] <= 59


def test_low_coverage_days_are_left_out_of_load_baseline():
    """Ngày đo nhịp tim thưa (tải bị đếm thiếu) không làm mức nền tải thấp đi, nên một ngày tập bình thường không thành
    "quá tải" chỉ vì trước đó đo thưa."""
    days = _days(trimp=100)
    for d in days[:-7]:
        d.update(trimp=10, hr_coverage=0.1)      # 3 tuần trước đo mỗi 30 phút: TRIMP chỉ còn 1/10
    parts = {p["key"]: p for p in I._load_parts(days)}
    assert parts == {}                            # chỉ còn 7 ngày đủ dữ liệu: chưa đủ mức nền, không đoán
    for d in days[:-7]:
        d.update(trimp=100, hr_coverage=0.9)
    acwr = next(p for p in I._load_parts(days) if p["key"] == "activity_balance")
    assert acwr["value"] == "1.00" and acwr["score"] == 100


def test_activity_intensity_ratio():
    a = I.activity_intensity(_days())
    assert a["ratio"] == round((30 + 10) / 160 * 100) and a["equivalent"] == 7 * (30 + 2 * 10) and a["level"] == "good"
    lazy = _days()
    for d in lazy:
        d.update(moderate=0, vigorous=0)
    assert I.activity_intensity(lazy)["level"] == "low"


def test_mental_state():
    calm = I.mental_state(_nights([240] * 30, minutes=480), _days(stress=20), None)
    assert calm["state"] in ("calm", "balanced") and calm["strain"] < 30
    worn = _nights([240] * 30, minutes=300)
    worn[-1]["hr"] = 70
    tense = I.mental_state(worn, _days(stress=75), {"cpd": 2.5, "sjl": 150, "strain": 80})
    assert tense["state"] == "overloaded" and tense["strain"] > 60
    assert tense["factors"][0]["level"] >= tense["factors"][-1]["level"]   # yếu tố nặng nhất lên đầu
    assert I.mental_state([], [], None) is None
