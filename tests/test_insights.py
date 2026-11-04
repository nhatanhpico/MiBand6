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


def _at(date: str, hour: float) -> float:
    d = dt.date.fromisoformat(date)
    return dt.datetime.combine(d, dt.time()).timestamp() + hour * 3600


def _readings(value, end="2026-11-03", hours=72, every=0.5, auto=True):
    """Số đo căng thẳng đều đặn trong `hours` giờ trước 12 giờ trưa ngày `end`."""
    as_of = _at(end, 12)
    return [(int(as_of - h * 3600), value, auto) for h in [i * every for i in range(int(hours / every))]], as_of


def _mind(nights, readings, as_of, date="2026-11-03", circ=None, days=None):
    days = days or _days(end=date)
    stress = I.stress_evidence(readings, as_of, date, days)
    k = len(nights) - 1
    return I.mental_state(nights, days, circ, stress=stress, rhr=I.night_rhr(nights, k), date=date)


def test_mental_state():
    nights = _nights([240] * 30, start_date="2026-10-05", minutes=480)   # đêm cuối thức dậy 3/11
    calm = _mind(nights, *_readings(20))
    assert calm["state"] == "calm" and calm["strain"] < 30 and calm["confidence"] == "high"
    assert calm["stress"]["avg"] == 20 and calm["stress"]["label"] == "Thư giãn"
    worn = _nights([240] * 30, start_date="2026-10-05", minutes=300)
    worn[-1]["hr"] = 70
    tense = _mind(worn, *_readings(75), circ={"cpd": 2.5, "sjl": 150, "strain": 80})
    assert tense["state"] == "overloaded" and tense["strain"] > 60 and tense["tension"] == 100
    assert tense["factors"][0]["level"] >= tense["factors"][-1]["level"]   # yếu tố nặng nhất lên đầu
    assert I.mental_state([], [], None) is None


def test_relaxed_band_stress_is_not_reported_as_stress():
    """Người dùng đo trên vòng tay thấy thư giãn (2 số đo hôm nay: 34 đo tay, 18 tự đo) nhưng nhịp tim khi ngủ đêm qua
    +8: trước đây chỉ có nhịp tim nghỉ trong nhóm "căng" (vì ít hơn 6 số đo tự động mỗi ngày) nên báo "Căng thẳng",
    mức căng 100. Giờ mức căng theo đúng số đo của vòng tay; nhịp tim tăng được báo riêng là dấu hiệu thể chất."""
    nights = _nights([240] * 30, start_date="2026-10-06", minutes=402)   # ngủ 6 giờ 42 phút, đêm cuối thức dậy 4/11
    for n in nights:
        n["hr"] = 58
    nights[-1]["hr"] = 66
    date = "2026-11-04"
    readings = [(int(_at(date, 11)), 34, False), (int(_at(date, 12)), 18, True)]
    m = _mind(nights, readings, _at(date, 12.5), date=date, circ={"cpd": 1.6, "sjl": 70, "strain": 52})
    assert m["state"] not in ("tense", "overloaded") and m["tension"] < 25
    assert m["stress"]["avg"] == 26 and m["stress"]["today_n"] == 2 and m["stress"]["manual"] == 1
    assert m["confidence"] == "medium"
    rhr = next(f for f in m["factors"] if f["key"] == "rhr")
    assert rhr["level"] == 100 and "+8" in rhr["text"]
    assert any("dấu hiệu thể chất" in n for n in m["notes"])
    assert any("Theo dõi căng thẳng" in n for n in m["notes"]) is False   # đã có số đo tự động
    only_manual = _mind(nights, readings[:1], _at(date, 12.5), date=date)
    assert any("Chỉ có số đo căng thẳng đo tay" in n for n in only_manual["notes"])


def test_resting_hr_alone_never_means_stress():
    nights = _nights([240] * 30, start_date="2026-10-05", minutes=460)
    for n in nights:
        n["hr"] = 58
    nights[-1]["hr"] = 70
    m = _mind(nights, [], _at("2026-11-03", 12))
    assert m["state"] not in ("tense", "overloaded") and m["tension"] <= 45 and m["confidence"] == "low"
    assert any("chưa có số đo căng thẳng" in n.lower() for n in m["notes"])
    # vòng tay đo thấy căng (trung bình 70) và nhịp tim nghỉ cũng tăng: củng cố
    tense = _mind(nights, *_readings(70))
    assert tense["state"] == "tense" and tense["tension"] > round(100 * tense["stress"]["risk"])


def test_mental_state_ignores_old_nights_and_weights_recent_readings():
    nights = _nights([240] * 20, start_date="2026-10-05", minutes=240)   # đêm cuối 24/10: quá cũ để nói về hôm nay
    readings, as_of = _readings(20, hours=24)
    old = [(ts - 48 * 3600, 90, True) for ts, _v, _a in readings]       # 2-3 ngày trước rất căng, hôm qua thư giãn
    m = _mind(nights, readings + old, as_of, circ={"cpd": 0.5, "sjl": 0, "strain": 10})
    assert not any(f["key"] in ("sleep", "rhr") for f in m["factors"])
    assert 20 < m["stress"]["avg"] < 55                                   # số đo gần đây nặng hơn: không phải 55
    assert I.stress_evidence(old, as_of + 30 * 3600, "2026-11-04") is None   # ngoài cửa sổ 72 giờ


def test_stress_relative_to_personal_baseline():
    days = _days(stress=25, end="2026-11-03")
    readings, as_of = _readings(45)
    base = I.stress_evidence(readings, as_of, "2026-11-03", days)
    alone = I.stress_evidence(readings, as_of, "2026-11-03")
    assert base["usual"] == 25 and base["risk"] > alone["risk"]          # cao hơn hẳn mức thường của chính bạn
    assert alone["usual"] is None and alone["label"] == "Bình thường"


# ---------------------------------------------------------------- tín hiệu cơ thể, kế hoạch ngủ


def _hr_nights(hrs, start_date="2026-10-01"):
    nights = _nights([240] * len(hrs), start_date=start_date)
    for n, hr in zip(nights, hrs):
        n["hr"] = hr
    return nights


def test_body_signals_flag_multi_night_rise():
    base = [58, 59, 57, 58, 60, 58, 57, 59, 58, 58]
    date = lambda nights: nights[-1]["date"]   # noqa: E731
    good = _hr_nights(base + [58, 59, 58])
    assert I.body_signals(good, date(good))["status"] == "good"
    one = _hr_nights(base + [58, 58, 65])
    b = I.body_signals(one, date(one))
    assert b["status"] == "ok" and b["last"]["high"] and b["last"]["dev"] == 7
    two = _hr_nights(base + [65, 58, 64])
    assert I.body_signals(two, date(two))["status"] == "watch"
    three = _hr_nights(base + [64, 65, 66])
    alert = I.body_signals(three, date(three))
    assert alert["status"] == "alert" and alert["streak"] == 3
    gap = _hr_nights(base + [64, 65, 66])
    del gap[-2]                                   # thiếu một đêm ở giữa: không phải "liền"
    assert I.body_signals(gap, date(gap))["streak"] == 1
    assert I.body_signals(_hr_nights(base[:5]), "2026-10-05") is None   # chưa đủ mức nền


def test_body_signals_use_personal_model_explanation():
    nights = _hr_nights([58] * 12 + [64])
    nights[-1]["features"] = {"late": 3.0}
    model = {"active": True, "resid_sd": 1.5, "nights": 30, "need": 21, "excluded": 0, "mae": 1.0, "mae_null": 1.5,
             "gain": 0.33, "r2": 0.4, "effects": [{"key": "late", "per_unit": 1.8, "t": 4.2}],
             "predictions": {nights[-1]["date"]: {"expected": 5.4, "contrib": {"late": 5.4}}}}
    b = I.body_signals(nights, nights[-1]["date"], model)
    last = b["last"]
    assert last["dev"] == 6 and last["unexplained"] == 0.6 and not last["high"] and b["status"] == "good"
    assert last["causes"] == ["đi ngủ muộn hơn thường lệ 3 giờ 0 phút: +5,4 nhịp/phút"]
    assert b["model"]["effects"] == ["Đi ngủ muộn hơn 1 giờ: +1,8 nhịp/phút"]


def test_sleep_plan_counts_back_from_usual_wake_time():
    d0 = dt.date(2026, 10, 5)   # thứ Hai
    nights = _nights([240] * 28, start_date="2026-10-05", minutes=450)
    for n in nights:   # ngày làm: 22:50-06:30 (ngủ 7 giờ 30 phút, thức 10 phút); ngày nghỉ (ngủ 510 phút) dậy 09:00
        n["awake"] = 10
        n["mid"] = 6.5 * 60 - (n["minutes"] + 10) / 2 if dt.date.fromisoformat(n["date"]).weekday() < 5 else 9 * 60 - 260
    date = (d0 + dt.timedelta(days=24)).isoformat()   # thứ Năm 29/10: mai là ngày làm việc
    plan = I.sleep_plan(nights[:25], date)
    assert plan["wake"] == "06:30" and plan["extra"] == 0 and plan["sleep"] == 450 and not plan["free"]
    assert plan["bedtime"] == "22:35"   # 06:30 - 7 giờ 30 phút - 10 phút thức - 15 phút thiếp đi
    short = [dict(n) for n in nights[:25]]
    for n in short[-4:]:
        n["minutes"] = 330   # thiếu 2 giờ mỗi đêm 4 đêm: nợ 480 phút, bù 1/3 tối đa 60 phút
    plan = I.sleep_plan(short, date)
    assert plan["debt"] == 480 and plan["extra"] == 60 and plan["sleep"] == 510
    assert plan["capped"]   # lên giường trước 22:00 sớm hơn giờ ngủ quen thuộc quá 1 giờ: giữ ở mức đó
    assert I.sleep_plan(nights[:3], date) is None


def test_sleep_balance_counts_completed_naps_once_without_changing_main_sleep(tmp_path):
    from miband6.healthdb import HealthDB

    db = HealthDB(tmp_path / "health.sqlite3")
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]

    def add_sleep(day, hour, minutes, finished=True):
        start = H.day_bounds(day)[0] + hour * 3600
        rows = [(start + i * 60, H.KIND_LIGHT_SLEEP, 0, 0, 58, 0, 0, 0) for i in range(minutes)]
        if finished:
            rows.append((start + minutes * 60, H.KIND_ACTIVITY, 0, 0, 70, 0, 0, 0))
        db.add_activity(rows)

    for day in dates:
        add_sleep(day, 0, 360)

    def balance(result):
        return next(p for p in result["readiness"]["parts"] if p["key"] == "sleep_balance")

    baseline = db.insights(dates[-1])
    add_sleep(dates[2], 13, 30)
    add_sleep(dates[2], 16, 19)
    add_sleep(dates[3], 7, 40, finished=False)
    result = db.insights(dates[-1])
    # Only the third day's finished 30-minute nap counts. The morning snapshot predates afternoon sleep.
    assert balance(baseline)["value"] == "80% nhu cầu"
    assert balance(result)["value"] == "82% nhu cầu"
    assert "5 giờ 30 phút" in balance(result)["detail"]
    assert balance(db.insights(dates[2]))["value"] == "80% nhu cầu"
    assert result["last_night"] == baseline["last_night"]
    db.close()


def test_weekly_debt_excludes_old_nights_and_does_not_invent_missing_sleep():
    nights = [{"date": "2026-01-01", "minutes": 280},
              {"date": "2026-01-03", "minutes": 400, "naps": [(1, 30)]},
              {"date": "2026-01-09", "minutes": 440, "naps": [(2, 90)]}]
    assert I._weekly_sleep_debt(nights, 450, "2026-01-09") == 20
    assert I._weekly_sleep_debt(nights, 450, "2026-01-10") == 0


def test_edwards_trimp_includes_the_exact_lower_edge_of_each_zone():
    for zone, boundary in enumerate((100, 120, 140, 160, 180), start=1):
        assert I.edwards_trimp(boundary - 1, 200) == zone - 1
        assert I.edwards_trimp(boundary, 200) == zone


def _sleep_rows(start, minutes, hr_of):
    rows = [(start + k * 60, H.KIND_LIGHT_SLEEP, 0, 0, hr_of(k), 0, 0, 0) for k in range(minutes)]
    rows.append((start + minutes * 60, H.KIND_ACTIVITY, 0, 0, 70, 0, 0, 0))
    return rows


def test_personal_model_learns_bedtime_effect_from_band_data(tmp_path):
    """Dữ liệu vòng tay 40 đêm: đi ngủ muộn hơn mỗi giờ thì nhịp tim khi ngủ cao hơn 2 nhịp/phút. Mô hình cá nhân
    phải học được điều đó (qua cả đường healthdb -> đặc trưng -> mô hình), và giải thích đêm cuối đi ngủ muộn."""
    import random

    from miband6.healthdb import HealthDB

    db = HealthDB(tmp_path / "h.sqlite3")
    rnd = random.Random(7)
    d0 = dt.date(2026, 9, 1)
    for i in range(40):
        late = 2.5 if i == 39 else rnd.uniform(-1.5, 1.5)   # giờ, so với 23:00
        start = H.day_bounds((d0 + dt.timedelta(days=i)).isoformat())[0] - 3600 + int(late * 3600)
        hr = round(55 + 2.0 * late + rnd.gauss(0, 0.5))
        db.add_activity(_sleep_rows(start, 420, lambda k, hr=hr: hr))
    ins = db.insights((d0 + dt.timedelta(days=39)).isoformat())
    model, last = ins["body"]["model"], ins["body"]["last"]
    assert model["active"] and model["nights"] >= 21 and model["gain"] >= 30
    assert any(e.startswith("Đi ngủ muộn hơn 1 giờ: +") for e in model["effects"])
    assert last["dev"] >= 4 and abs(last["unexplained"]) < 2.5 and not last["high"]   # giải thích được: không báo
    assert last["causes"] and last["causes"][0].startswith("đi ngủ muộn hơn thường lệ")
    db.close()


def test_night_heart_rate_needs_enough_readings(tmp_path):
    from miband6.healthdb import HealthDB, MIN_NIGHT_HR

    db = HealthDB(tmp_path / "h.sqlite3")
    day = "2026-01-05"
    start = H.day_bounds(day)[0]
    db.add_activity(_sleep_rows(start, 420, lambda k: 58 if k % 60 == 0 else 255))   # đo mỗi giờ: 7 số đo
    assert 420 // 60 < MIN_NIGHT_HR and db.insights(day)["last_night"]["hr"] is None
    db.add_activity(_sleep_rows(start, 420, lambda k: 58 if k % 30 == 0 else 255))   # mỗi 30 phút: 14 số đo
    assert db.insights(day)["last_night"]["hr"] == 58
    db.close()


def test_personal_model_learns_from_history_beyond_the_window(tmp_path):
    """Lịch sử dài hơn cửa sổ 60 ngày của insights được lưu gọn theo ngày (bảng daily) và lấp dần từng đoạn, nên mô hình
    cá nhân học được từ cả 4 tháng dữ liệu chứ không chỉ 2 tháng gần nhất."""
    import random

    from miband6 import healthdb as HDB
    from miband6.healthdb import HealthDB

    db = HealthDB(tmp_path / "h.sqlite3")
    rnd = random.Random(5)
    d0 = dt.date(2026, 5, 1)
    days = 120
    for i in range(days):
        late = rnd.uniform(-1.5, 1.5)
        start = H.day_bounds((d0 + dt.timedelta(days=i)).isoformat())[0] - 3600 + int(late * 3600)
        hr = round(55 + 2.0 * late + rnd.gauss(0, 0.5))
        db.add_activity(_sleep_rows(start, 420, lambda k, hr=hr: hr))
    last = (d0 + dt.timedelta(days=days - 1)).isoformat()
    first = db.insights(last)["body"]["model"]
    assert first["nights"] < days - 5                # lần đầu: cửa sổ 60 ngày cộng một đoạn lịch sử vừa lấp
    for _ in range(3):
        model = db.insights(last)["body"]["model"]
    stored = db.db.execute("SELECT COUNT(*), MIN(date) FROM daily WHERE version = ?", (HDB.DAILY_VERSION,)).fetchone()
    # mọi ngày đã trọn đều được lưu, từ ngày có dữ liệu đầu tiên (tối 30/4, giấc ngủ của đêm thức dậy 1/5)
    assert stored[0] >= days - 2 and stored[1] == (d0 - dt.timedelta(days=1)).isoformat()
    assert model["nights"] >= days - 15 > 60 and model["active"]
    curve = {c["days"]: c["status"] for c in model["curve"]}
    assert curve == {7: "too_few", 30: "ok", 90: "ok", 180: "need_more", 365: "need_more"}
    assert model["since"] <= (d0 + dt.timedelta(days=10)).isoformat()
    db.close()
