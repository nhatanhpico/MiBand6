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
