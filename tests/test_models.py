"""Mô hình cá nhân (models.py): hồi quy ridge thuần Python, kiểm chứng chéo bỏ-một, chỉ dùng khi tốt hơn mức nền."""

import random

import pytest

from miband6 import models as M


def test_ridge_without_penalty_recovers_exact_relation():
    xs = [[i, (i * 7) % 5, (i * 3) % 4] for i in range(20)]
    ys = [2.0 + 0.5 * a - 1.5 * b + 0.25 * c for a, b, c in xs]
    fit = M.ridge_fit(xs, ys, lam=0.0)
    assert fit["intercept"] == pytest.approx(2.0) and fit["coef"] == pytest.approx([0.5, -1.5, 0.25])
    assert M.predict(fit, [10, 1, 2]) == pytest.approx(2.0 + 5 - 1.5 + 0.5)
    # đặc trưng không đổi trong dữ liệu học: hệ số 0, không lỗi chia cho 0
    flat = M.ridge_fit([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]], [1.0, 2.0, 3.0], lam=0.0)
    assert flat["coef"] == pytest.approx([1.0, 0.0])


def _nights(n, effect=lambda x: 0.0, noise=1.0, seed=3):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        x = {"load": rnd.uniform(-1, 1.5), "evening": rnd.choice([0, 0, 0, 0.6]), "late": rnd.gauss(0, 0.8),
             "short": rnd.gauss(0, 0.7)}
        rows.append({"date": f"2026-09-{i + 1:02d}", "x": x, "y": effect(x) + rnd.gauss(0, noise)})
    return rows


def test_learns_personal_effects_and_explains_a_late_night():
    rows = _nights(45, lambda x: 1.8 * x["late"] + 1.2 * x["load"], noise=0.8)
    target = {"date": "2026-11-04", "x": {"late": 2.0, "load": 0.0}}
    m = M.rhr_model(rows, [target])
    assert m["active"] and m["nights"] == 45 and m["gain"] >= 0.3 and m["mae"] < m["mae_null"]
    effects = {e["key"]: e["per_unit"] for e in m["effects"]}
    assert effects["late"] == pytest.approx(1.8, abs=0.35) and effects["load"] == pytest.approx(1.2, abs=0.35)
    assert "evening" not in effects   # không có ảnh hưởng thật: không báo
    pred = m["predictions"]["2026-11-04"]
    assert pred["expected"] == pytest.approx(3.6, abs=0.8) and pred["contrib"]["late"] == pytest.approx(3.6, abs=0.8)


def test_stays_off_when_nothing_is_predictable():
    m = M.rhr_model(_nights(45, noise=2.0), [{"date": "x", "x": {"late": 3}}])
    assert not m["active"] and m["predictions"] == {} and m["effects"] == []
    assert m["gain"] < M.MIN_GAIN


def test_needs_enough_nights_and_ignores_sick_nights():
    assert M.rhr_model(_nights(10, lambda x: 2 * x["late"]))["active"] is False
    rows = _nights(40, lambda x: 1.5 * x["late"], noise=0.5)
    rows[5]["y"] += 25      # một đêm ốm / say rượu: không dùng để học
    m = M.rhr_model(rows)
    assert m["excluded"] == 1 and m["active"]
    assert {e["key"]: e["per_unit"] for e in m["effects"]}["late"] == pytest.approx(1.5, abs=0.3)
    assert M.rhr_model([{"date": "d", "x": {}, "y": None}] * 30)["nights"] == 0


def test_robust_statistics():
    assert M.median([3, 1, 2]) == 2 and M.median([4, 1, 2, 3]) == 2.5
    assert M.robust_sd([58, 58, 59, 57, 58, 90]) == pytest.approx(1.4826 * 0.5)   # một giá trị lạ không kéo lệch
    assert M.robust_sd([]) == 0.0


def test_fast_leave_one_out_matches_refitting():
    rows = _nights(60, lambda x: 1.5 * x["late"] + 0.8 * x["load"], noise=0.7)
    xs, ys = [M._row(r["x"]) for r in rows], [r["y"] for r in rows]
    fast = M.loo_residuals(xs, ys)
    slow = [ys[i] - M.predict(M.ridge_fit(xs[:i] + xs[i + 1:], ys[:i] + ys[i + 1:]), xs[i]) for i in range(len(ys))]
    # một lần học thay cho 60 lần: chỉ khác ở chỗ chuẩn hóa theo cả dữ liệu
    assert max(abs(a - b) for a, b in zip(fast, slow)) < 0.05
    assert abs(sum(map(abs, fast)) - sum(map(abs, slow))) / sum(map(abs, slow)) < 0.01


def test_learning_curve_reports_each_history_length():
    import datetime as dt

    rows = _nights(200, lambda x: 1.8 * x["late"] + 1.0 * x["load"], noise=0.8, seed=11)
    d0 = dt.date(2026, 1, 1)
    for i, r in enumerate(rows):
        r["date"] = (d0 + dt.timedelta(days=i)).isoformat()
    curve = {c["days"]: c for c in M.learning_curve(rows)}
    assert curve[7]["status"] == "too_few"           # 1 tuần: dưới 21 đêm, không học được
    assert curve[365]["status"] == "need_more"       # mới có hơn 6 tháng dữ liệu
    ok = [curve[d] for d in (30, 90, 180)]
    assert all(c["status"] == "ok" and c["tests"] == M.CURVE_TESTS for c in ok)
    assert ok[0]["nights"] == 30 and ok[2]["nights"] == 180
    assert ok[2]["mae"] <= ok[0]["mae"] and all(c["mae"] < c["mae_null"] for c in ok)   # có ích, nhiều dữ liệu hơn không tệ hơn
    assert M.learning_curve([]) == [{"days": d, "status": "need_more"} for d in M.CURVE_WINDOWS]
