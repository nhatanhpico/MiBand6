"""Mô hình thể lực cá nhân và gợi ý buổi tập tiếp theo (coach.py)."""

import pytest

from miband6 import coach as C

NOW = 1_800_000_000
DAY = 86400


def athlete_windows(vo2max: float, hrmax: float, rest: float, speeds: list[float], noise: float = 0.0) -> list[list]:
    """Các phút chạy đều của một người có VO2max cho trước (quan hệ %HRR ~ %VO2R)."""
    out = []
    for i, v in enumerate(speeds):
        vo2 = C.acsm_vo2(v, 0.0, True)
        hrr = (vo2 - 3.5) / (vo2max - 3.5)
        out.append([v, rest + hrr * (hrmax - rest) + noise * ((-1) ** i), 0.0])
    return out


def test_acsm_equations():
    assert C.acsm_vo2(2.5, 0, True) == pytest.approx(33.5)       # chạy 9 km/h
    assert C.acsm_vo2(1.4, 0, False) == pytest.approx(11.9)      # đi bộ 5 km/h
    assert C.acsm_vo2(2.5, 0.05, True) > C.acsm_vo2(2.5, 0, True)


def test_fitness_learns_vo2max_from_workouts():
    w = [{"start": NOW - 3 * DAY, "kind": "run",
          "windows": athlete_windows(46.0, 195, 55, [2.4 + 0.05 * i for i in range(20)], noise=2.0)}]
    f = C.fitness(w, 195, 55, 25, "male", NOW)
    assert f["method"] == "workouts" and f["vo2max"] == pytest.approx(46.0, abs=2.5) and f["minutes"] == 20
    assert f["low"] <= f["vo2max"] <= f["high"] and f["level"] == "good"
    # buổi quá cũ, đạp xe, phút nhịp tim quá thấp: không dùng; chưa đủ phút thì ước tính thô theo nhịp tim nghỉ
    old = [{**w[0], "start": NOW - 200 * DAY}, {"start": NOW, "kind": "ride", "windows": w[0]["windows"]},
           {"start": NOW, "kind": "walk", "windows": [[1.0, 60, 0.0]] * 20}]
    rough = C.fitness(old, 195, 55, 25, "male", NOW)
    assert rough["method"] == "resting_hr" and rough["vo2max"] == pytest.approx(15.3 * 195 / 55, abs=0.1)
    assert C.fitness(w, 195, None, 25, "male", NOW) is None


def test_fitness_trend_and_levels():
    w = [{"start": NOW - (40 - 8 * i) * DAY, "kind": "run",
          "windows": athlete_windows(40.0 + 2 * i, 195, 55, [2.5 + 0.05 * k for k in range(10)])} for i in range(4)]
    f = C.fitness(w, 195, 55, 25, "male", NOW)
    assert f["trend"] > 2 and f["workouts"] == 4
    assert C.vo2_level(30, 25, "female") == "fair" and C.vo2_level(55, 25, "male") == "superior"
    assert C.vo2_level(40, None, "male") is None


def test_pace_for_heart_rate():
    fit = {"vo2max": 46.0}
    easy, hard = C.pace_for_hr(130, fit, 195, 55, True), C.pace_for_hr(170, fit, 195, 55, True)
    assert hard < easy and 240 < hard < 400 and 330 < easy < 600   # pace (giây/km): nhịp tim cao thì chạy nhanh hơn
    assert C.pace_for_hr(70, fit, 195, 55, True) is None


def history(n: int, kind: str = "run", minutes: float = 30, hard_every: int = 0, rpe: int | None = None) -> list[dict]:
    out = []
    for i in range(n):
        start = NOW - (n - i) * 2 * DAY
        hard = hard_every and i % hard_every == 0
        out.append({"start": start, "kind": kind, "type": 1, "mf_type": None, "minutes": minutes, "distance": 5000,
                    "zones": [0, 1200, 300, 600 if hard else 0, 0], "trimp": 60, "rpe": None, "windows": []})
    if rpe and out:
        out[-1]["rpe"] = rpe
    return out


def load_days(acute: float, chronic: float) -> list[dict]:
    return [{"date": f"d{i}", "trimp": chronic if i < 21 else acute, "wear": 900, "hr_coverage": 0.9} for i in range(28)]


def ready(verdict: str, score: int, hours: float = 0.0) -> dict:
    return {"verdict": verdict, "score": score, "label": "x", "parts": [{"key": "recovery_time", "hours": hours}]}


def test_suggest_rest_and_easy_days():
    s = C.suggest(history(6), ready("rest", 30), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["kind"] == "rest" and s["minutes"] == 0 and s["status"] == "alert"
    s = C.suggest(history(6), ready("train", 70, hours=20), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["kind"] == "easy" and s["zone"] == 2 and s["minutes"] == 20 and any("20" in r for r in s["reasons"])
    s = C.suggest(history(6), ready("train", 70), load_days(120, 60), 195, 55, 25, "male", NOW)   # ACWR 2
    assert s["kind"] == "easy" and s["acwr"] == pytest.approx(1.6, abs=0.1)


def test_suggest_quality_sessions():
    s = C.suggest(history(6), ready("train_hard", 90), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["kind"] == "intervals" and s["plan"]["repeats"]["count"] == 5 and s["hr"] == [156, 176]
    assert s["minutes"] == 15 + 5 * 5 and s["sport"] == "run"
    s = C.suggest(history(6, hard_every=1), ready("train_hard", 90), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["kind"] in ("endurance", "long")   # vừa có buổi nặng 2 ngày trước, 35% thời gian ở vùng 4-5
    s = C.suggest(history(6), ready("train", 70), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["kind"] == "tempo" and s["plan"]["main"]["zone"] == 3
    s = C.suggest(history(6, rpe=5), ready("train_hard", 90), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["kind"] == "easy"   # buổi gần nhất "rất nặng"


def test_suggest_walker_and_new_user():
    s = C.suggest(history(5, kind="walk", minutes=40), ready("train_hard", 90), load_days(60, 60), 195, 55, 60, "female", NOW)
    assert s["sport"] == "walk" and s["kind"] in ("long", "endurance") and s["zone"] == 2   # không gợi ý biến tốc khi đi bộ
    s = C.suggest([], None, [], 195, None, None, None, NOW)
    assert s["kind"] == "endurance" and s["sport"] == "walk" and s["minutes"] == 40 and s["pace"] is None


def test_suggest_gives_pace_from_personal_fitness():
    h = history(6)
    h[-1]["windows"] = athlete_windows(46.0, 195, 55, [2.4 + 0.05 * i for i in range(20)])
    s = C.suggest(h, ready("train", 70, hours=20), load_days(60, 60), 195, 55, 25, "male", NOW)
    assert s["fitness"]["method"] == "workouts" and s["pace"] and s["pace"][0] < s["pace"][1]
    assert s["distance"] == pytest.approx(s["minutes"] * 60 / ((s["pace"][0] + s["pace"][1]) / 2), abs=0.1)


def habit_history(weekdays: tuple[int, ...], weeks: int = 8) -> list[dict]:
    """Các buổi tập lúc 18:00 vào những thứ cho trước (0 = thứ Hai) trong `weeks` tuần trước NOW."""
    import datetime as dt

    today = dt.date.fromtimestamp(NOW)
    out = []
    for k in range(weeks * 7, 0, -1):
        d = today - dt.timedelta(days=k)
        if d.weekday() in weekdays:
            start = int(dt.datetime.combine(d, dt.time(18)).timestamp())
            out.append({"start": start, "kind": "run", "type": 1, "mf_type": None, "minutes": 30, "distance": 5000,
                        "zones": [0, 1200, 600, 0, 0], "trimp": 60, "rpe": None, "windows": []})
    return out


def check_plan(plan: list[dict]) -> None:
    """Quy tắc chung: 7 ngày, có ngày nghỉ, buổi nặng cách nhau >= 2 ngày, sau buổi nặng không tập nặng, <= 3 ngày liền."""
    assert len(plan) == 7 and plan[0]["today"] and not any(d["today"] for d in plan[1:])
    assert any(d["kind"] == "rest" for d in plan)
    hard = [i for i, d in enumerate(plan) if d["intensity"] == "hard"]
    assert len(hard) <= 2 and all(b - a >= 2 for a, b in zip(hard, hard[1:]))
    for i in hard:
        if i + 1 < 7:
            assert plan[i + 1]["kind"] in ("rest", "easy")
    run = best = 0
    for d in plan:
        run = run + 1 if d["kind"] != "rest" else 0
        best = max(best, run)
    assert best <= 3


def test_week_plan_follows_training_habits():
    import datetime as dt

    h = habit_history((0, 2, 4))   # thứ Hai, Tư, Sáu
    plan = C.week_plan(h, "endurance", 30, "run", 30, 30, NOW)
    check_plan(plan)
    trained = {dt.date.fromisoformat(d["date"]).weekday() for d in plan[1:] if d["kind"] != "rest"}
    assert trained <= {0, 2, 4} and len(trained) == (2 if plan[0]["kind"] != "rest" and dt.date.fromtimestamp(NOW).weekday() in (0, 2, 4) else 3)
    assert sum(d["intensity"] == "hard" for d in plan) == 1   # 3 buổi mỗi tuần: một buổi nặng
    assert any(d["kind"] == "long" for d in plan)
    assert all(d["minutes"] == 0 for d in plan if d["kind"] == "rest") and plan[0]["minutes"] == 30


def test_week_plan_rules_for_busy_and_rest_days():
    busy = habit_history((0, 1, 2, 3, 4, 5))   # 6 buổi mỗi tuần
    plan = C.week_plan(busy, "intervals", 40, "run", 30, 45, NOW)
    check_plan(plan)
    assert plan[0]["intensity"] == "hard" and plan[1]["kind"] in ("rest", "easy")
    assert sum(d["intensity"] == "hard" for d in plan) == 2
    # buổi nặng hôm qua: ngày mai mới được nặng lại; hôm nay nghỉ
    plan = C.week_plan(busy, "rest", 0, "run", 30, 45, NOW, hard_days_ago=1)
    check_plan(plan)
    assert plan[0]["kind"] == "rest" and plan[0]["minutes"] == 0
    # tải tăng quá nhanh: bớt một buổi
    calm = C.week_plan(busy, "easy", 20, "run", 30, 45, NOW, acwr=1.6)
    assert sum(d["kind"] != "rest" for d in calm) == 5


def test_week_plan_for_walkers_and_new_users():
    plan = C.week_plan(habit_history((1, 3, 6)), "endurance", 40, "walk", 40, 40, NOW)
    check_plan(plan)
    assert not any(d["intensity"] == "hard" for d in plan)   # đi bộ: không có buổi biến tốc / tempo
    new = C.week_plan([], "endurance", 40, "walk", 40, 40, NOW)
    check_plan(new)
    assert sum(d["kind"] != "rest" for d in new) == 3
    s = C.suggest([], None, [], 195, None, None, None, NOW)
    assert len(s["week_plan"]) == 7 and s["week_plan"][0]["kind"] == s["kind"]
