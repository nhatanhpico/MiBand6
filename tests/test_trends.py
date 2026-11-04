"""Tóm tắt sức khỏe kiểu Mi Fitness (trends.py): thay đổi gần đây, 7 ngày qua, hôm nay so với thường lệ."""

import datetime as dt

import pytest

from miband6 import trends as TR
from miband6.i18n import set_lang


@pytest.fixture(autouse=True)
def _vi():
    set_lang("vi")
    yield
    set_lang("vi")


def days(values):
    d0 = dt.date(2026, 10, 1)
    return [((d0 + dt.timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


def noisy(base, n, spread):
    return [base + spread * ((i * 7) % 5 - 2) for i in range(n)]


def test_change_point_finds_recent_shift():
    pts = days(noisy(450, 27, 10) + [370, 375, 372])   # 3 đêm gần đây ngủ ít hơn ~1 giờ 18 phút
    c = TR.detect("sleep", pts, need=450)
    assert c["recent_n"] == 3 and c["base_n"] == 27 and c["status"] == "watch"
    assert c["text"].startswith("Trong 3 ngày qua, thời gian ngủ chính giảm 1 giờ 1") and c["base_n"] == 27
    assert [p["recent"] for p in c["series"]].count(True) == 3
    assert TR.detect("sleep", days(noisy(450, 30, 10)), need=450) is None   # chỉ dao động: không báo
    # thay đổi rõ nhưng quá nhỏ để có ý nghĩa: không báo
    assert TR.detect("steps", days([8000 + (i % 2) for i in range(22)] + [8200] * 8), need=450) is None
    up = TR.detect("steps", days(noisy(7000, 22, 300) + noisy(8500, 8, 300)), need=450)
    assert up["status"] == "good" and up["recent_n"] in (7, 8) and "tăng" in up["text"]


def test_bedtime_and_english_text():
    later = TR.detect("bedtime", days(noisy(60, 20, 10) + noisy(110, 10, 10)), need=450)
    assert later["status"] == "watch" and later["recent_n"] in (9, 10, 11)
    assert later["text"] == f"Trong {later['recent_n']} ngày qua, bạn đi ngủ muộn hơn {later['recent_text'] and TR._hm(later['recent'] - later['base'])} so với trước đó."
    set_lang("en")
    c = TR.detect("sleep", days(noisy(450, 27, 10) + [370, 375, 372]), need=450)
    assert c["text"].startswith("Over the past 3 days, main sleep duration decreased by 1 h 1")


def test_weekly_change():
    weeks = [(f"w{i}", v) for i, v in enumerate(noisy(5600, 21, 150) + noisy(8300, 5, 150))]
    c = TR.detect("steps", weeks, need=450, weekly=True)
    assert c["scope"] == "weeks" and c["recent_n"] == 5 and c["text"].startswith("Trong 5 tuần qua")


def test_highlights_and_regular_wake():
    h = TR.week_over_week("sleep", days([470] * 7 + [440] * 7), need=420)
    assert h["recent"] == 440 and h["base"] == 470 and h["status"] == "neutral"   # ít đi nhưng vẫn đủ giấc
    assert h["text"] == "Trung bình mỗi ngày trong 7 ngày qua: 7 giờ 20 phút. Giảm 30 phút so với tuần trước."
    assert TR.week_over_week("steps", days([None] * 11 + [9000] * 3), need=450) is None   # thiếu dữ liệu
    assert TR.wake_regularity(days([560, 570, 565, 555, 575, 560, 568]))["status"] == "good"
    assert TR.wake_regularity(days([480, 620, 500, 640, 470, 650, 600]))["status"] == "watch"


def test_today_vs_usual():
    usual = [[min(q, 40) * 100.0 for q in range(96)] for _ in range(10)]   # 4.000 bước tới 10 giờ, rồi đứng yên
    par = TR.vs_usual("steps", [min(q, 40) * 105.0 for q in range(96)], usual, upto=41)
    assert par["verdict"] == "par" and par["usual"] == 4000 and len(par["today"]) == 41
    assert TR.vs_usual("steps", [q * 200.0 for q in range(96)], usual, upto=41)["verdict"] == "above"
    assert TR.vs_usual("steps", [q * 20.0 for q in range(96)], usual, upto=41)["verdict"] == "below"
    assert TR.vs_usual("steps", [0.0] * 96, usual[:3], upto=41) is None   # cần ít nhất 7 ngày để so


def test_summary_counts():
    out = TR.summary({"sleep": days(noisy(450, 27, 10) + [370, 375, 372]),
                      "steps": days(noisy(7000, 22, 300) + noisy(8500, 8, 300))},
                     {"steps": []}, days([560] * 7), {}, need=450)
    assert out["counts"] == {"watch": 1, "good": 1} and out["changes"][0]["key"] == "sleep"   # cần chú ý lên trước
    assert any(h["key"] == "wake" for h in out["highlights"])
