"""Tóm tắt sức khỏe kiểu Mi Fitness: chỉ số nào vừa thay đổi rõ, tuần này so với tuần trước, hôm nay so với thường lệ.

Hàm thuần: nhận chuỗi giá trị theo ngày / tuần (HealthDB.trends dựng), trả các thẻ kèm lời giải thích đã dịch.
Ngưỡng và cách tính: docs/suc-khoe.md (giữ hai nơi khớp nhau).

- Thay đổi gần đây: trong 30 ngày (hoặc 26 tuần), tìm điểm chia "gần đây / trước đó" làm hai mức trung bình khác nhau rõ
  nhất (kiểm định t Welch lớn nhất, như phát hiện điểm đổi mức trung bình một lần). Chỉ báo khi |t| >= T_MIN và mức
  chênh đủ lớn để có ý nghĩa (MIN_CHANGE của từng chỉ số). Mi Fitness hiện kiểu "3 ngày qua so với 27 ngày trước đó",
  "8 ngày / 22 ngày", "5 tuần / 21 tuần": cùng một cửa sổ, chia ở điểm đổi.
- Nổi bật: trung bình 7 ngày qua so với 7 ngày trước đó; độ đều đặn giờ thức dậy (độ lệch chuẩn 7 ngày).
- Hôm nay so với thường lệ: bước chân, năng lượng cộng dồn tới giờ này so với trung vị cùng giờ của 28 ngày trước.
"""

from __future__ import annotations

import math

from .i18n import tr

T_MIN = 2.5               # |t| tối thiểu để coi là thay đổi (cao hơn 2 vì thử nhiều điểm chia)
MIN_RECENT = 3            # phần "gần đây" ít nhất ngần này ngày / tuần có dữ liệu
MIN_BASE = 7              # phần "trước đó" ít nhất ngần này ngày (tuần: MIN_BASE_WEEKS)
MIN_BASE_WEEKS = 4
DAYS = 30
WEEKS = 26
REGULAR_WAKE = 30         # độ lệch chuẩn giờ thức dậy (phút): đều đặn nếu không quá ngần này
IRREGULAR_WAKE = 60
USUAL_DAYS = 28
USUAL_BAND = 0.25         # hôm nay lệch quá 25% (và quá USUAL_MIN) so với thường lệ: cao hơn / thấp hơn

GOOD, WATCH, NEUTRAL = "good", "watch", "neutral"

# chỉ số -> (đơn vị, mức chênh tối thiểu, chiều tốt: +1 tăng là tốt, -1 giảm là tốt)
METRICS = {
    "sleep": ("min", 20, +1),
    "bedtime": ("clock", 20, -1),
    "deep": ("pct", 2, +1),
    "sleep_hr": ("bpm", 2, -1),
    "steps": ("steps", 500, +1),
    "calories": ("kcal", 20, +1),
    "active": ("min", 5, +1),
    "stress": ("score", 4, -1),
}
USUAL_MIN = {"steps": 300, "calories": 15}


def _name(key: str) -> str:
    return {
        "sleep": tr('Thời gian ngủ chính'), "bedtime": tr('Giờ đi ngủ'), "deep": tr('Tỉ lệ ngủ sâu'),
        "sleep_hr": tr('Nhịp tim khi ngủ'), "steps": tr('Bước chân'), "calories": tr('Năng lượng vận động'),
        "active": tr('Vận động vừa và mạnh'), "stress": tr('Căng thẳng'), "wake": tr('Giờ thức dậy'),
    }[key]


def _mean(v: list[float]) -> float:
    return sum(v) / len(v)


def _var(v: list[float]) -> float:
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return sum((x - m) ** 2 for x in v) / (len(v) - 1)


def _hm(minutes: float) -> str:
    minutes = int(round(abs(minutes)))
    return tr('{h} giờ {m} phút', h=minutes // 60, m=minutes % 60) if minutes >= 60 else tr('{m} phút', m=minutes)


def _clock(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _int(n: float) -> str:
    from .health import group_int
    return group_int(n)


def fmt(key: str, value: float) -> str:
    """Giá trị của chỉ số kèm đơn vị, theo ngôn ngữ giao diện."""
    unit = METRICS[key][0] if key in METRICS else "min"
    if unit == "clock":
        return _clock(value)
    if unit == "min":
        return _hm(value)
    if unit == "pct":
        return f"{value:.0f}%"
    if unit == "bpm":
        return tr('{n} nhịp/phút', n=int(round(value)))
    if unit == "steps":
        return tr('{n} bước', n=_int(value))
    if unit == "kcal":
        return f"{_int(value)} kcal"
    return f"{value:.0f}"


def _delta(key: str, d: float) -> str:
    unit = METRICS[key][0]
    if unit in ("clock", "min"):
        return _hm(d)
    if unit == "pct":
        return tr('{n} điểm %', n=f"{abs(d):.0f}")
    return fmt(key, abs(d))


def _status(key: str, d: float, recent: float, need: int) -> str:
    if key == "sleep" and d > 0 and recent > need + 120:
        return NEUTRAL   # ngủ dài hơn nhưng đã quá nhiều: không phải tin tốt
    if key == "sleep" and d < 0 and recent >= need:
        return NEUTRAL   # ngủ ít đi nhưng vẫn đủ
    return GOOD if d * METRICS[key][2] > 0 else WATCH


def change_point(values: list[float | None], min_recent: int = MIN_RECENT, min_base: int = MIN_BASE) -> dict | None:
    """Điểm chia chuỗi (cũ tới mới) thành "trước đó" / "gần đây" có hai trung bình khác nhau rõ nhất (t Welch lớn nhất).
    Trả {recent_n, base_n, recent, base, t, split}: split là vị trí phần tử đầu của phần gần đây trong `values`."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    best = None
    for k in range(min_recent, min(len(pts) - min_base, len(pts) // 2) + 1):   # phần gần đây không dài hơn phần trước
        recent = [v for _, v in pts[-k:]]
        base = [v for _, v in pts[:-k]]
        se = math.sqrt(_var(recent) / len(recent) + _var(base) / len(base))
        diff = _mean(recent) - _mean(base)
        if se == 0:
            if diff == 0:
                continue
            se = 1e-9
        t = diff / se
        if best is None or abs(t) > abs(best["t"]):
            best = {"recent_n": k, "base_n": len(base), "recent": _mean(recent), "base": _mean(base), "t": t,
                    "split": pts[-k][0]}
    return best


def _series(points: list[tuple[str, float | None]], split: int | None = None) -> list[dict]:
    return [{"label": label, "value": None if v is None else round(v, 1), "recent": split is not None and i >= split}
            for i, (label, v) in enumerate(points)]


def detect(key: str, points: list[tuple[str, float | None]], need: int, weekly: bool = False) -> dict | None:
    """Thẻ "thay đổi" của một chỉ số nếu có thay đổi rõ (xem change_point, T_MIN, METRICS)."""
    cp = change_point([v for _l, v in points], MIN_RECENT, MIN_BASE_WEEKS if weekly else MIN_BASE)
    if cp is None or abs(cp["t"]) < T_MIN:
        return None
    d = cp["recent"] - cp["base"]
    if abs(d) < METRICS[key][1]:
        return None
    n = cp["recent_n"]
    if key == "bedtime":
        text = (tr('Trong {n} ngày qua, bạn đi ngủ muộn hơn {t} so với trước đó.', n=n, t=_hm(d)) if d > 0
                else tr('Trong {n} ngày qua, bạn đi ngủ sớm hơn {t} so với trước đó.', n=n, t=_hm(d)))
    elif weekly:
        text = (tr('Trong {n} tuần qua, {what} trung bình mỗi ngày tăng {d}.', n=n, what=_name(key).lower(), d=_delta(key, d))
                if d > 0 else
                tr('Trong {n} tuần qua, {what} trung bình mỗi ngày giảm {d}.', n=n, what=_name(key).lower(), d=_delta(key, d)))
    else:
        text = (tr('Trong {n} ngày qua, {what} tăng {d}.', n=n, what=_name(key).lower(), d=_delta(key, d)) if d > 0
                else tr('Trong {n} ngày qua, {what} giảm {d}.', n=n, what=_name(key).lower(), d=_delta(key, d)))
    return {"key": key, "title": _name(key), "status": _status(key, d, cp["recent"], need), "text": text,
            "scope": "weeks" if weekly else "days", "recent_n": n, "base_n": cp["base_n"],
            "recent": round(cp["recent"], 1), "base": round(cp["base"], 1), "recent_text": fmt(key, cp["recent"]),
            "base_text": fmt(key, cp["base"]), "unit": METRICS[key][0], "t": round(cp["t"], 1),
            "series": _series(points, cp["split"])}


def week_over_week(key: str, points: list[tuple[str, float | None]], need: int) -> dict | None:
    """Trung bình 7 ngày qua so với 7 ngày trước đó (cần ít nhất 4 ngày có dữ liệu mỗi bên)."""
    last = points[-14:]
    recent = [v for _l, v in last[-7:] if v is not None]
    base = [v for _l, v in last[:-7] if v is not None]
    if len(recent) < 4:
        return None
    r = _mean(recent)
    item = {"key": key, "title": _name(key), "recent": round(r, 1), "recent_text": fmt(key, r), "unit": METRICS[key][0],
            "series": _series(last, len(last) - 7), "base": None, "base_text": None, "status": NEUTRAL}
    if key == "bedtime":
        item["text"] = tr('Giờ đi ngủ trung bình 7 ngày qua là {t}.', t=_clock(r))
    else:
        item["text"] = tr('Trung bình mỗi ngày trong 7 ngày qua: {v}.', v=fmt(key, r))
    if len(base) >= 4:
        b = _mean(base)
        d = r - b
        item.update(base=round(b, 1), base_text=fmt(key, b))
        if abs(d) >= METRICS[key][1] / 2:
            item["status"] = _status(key, d, r, need)
            if key == "bedtime":
                item["text"] += " " + (tr('Muộn hơn tuần trước {t}.', t=_hm(d)) if d > 0 else tr('Sớm hơn tuần trước {t}.', t=_hm(d)))
            else:
                item["text"] += " " + (tr('Tăng {d} so với tuần trước.', d=_delta(key, d)) if d > 0
                                       else tr('Giảm {d} so với tuần trước.', d=_delta(key, d)))
        else:
            item["text"] += " " + tr('Gần như không đổi so với tuần trước.')
    return item


def wake_regularity(points: list[tuple[str, float | None]]) -> dict | None:
    """Giờ thức dậy 7 ngày qua đều hay không: độ lệch chuẩn (phút) quanh trung bình."""
    last = points[-7:]
    vals = [v for _l, v in last if v is not None]
    if len(vals) < 4:
        return None
    sd = math.sqrt(_var(vals))
    m, t = int(round(sd)), _clock(_mean(vals))
    if sd <= REGULAR_WAKE:
        status, text = GOOD, tr('Giờ thức dậy 7 ngày qua đều đặn (lệch ±{m} phút quanh {t}).', m=m, t=t)
    elif sd <= IRREGULAR_WAKE:
        status, text = NEUTRAL, tr('Giờ thức dậy 7 ngày qua khá đều (lệch ±{m} phút quanh {t}).', m=m, t=t)
    else:
        status, text = WATCH, tr('Giờ thức dậy 7 ngày qua chưa đều (lệch ±{m} phút quanh {t}); dậy cùng giờ mỗi ngày giúp nhịp sinh học ổn định.',
                                 m=m, t=t)
    return {"key": "wake", "title": _name("wake"), "status": status, "text": text, "unit": "clock",
            "recent": round(_mean(vals), 1), "recent_text": _clock(_mean(vals)), "sd": round(sd),
            "series": _series(last)}


def vs_usual(key: str, today: list[float], usual: list[list[float]], upto: int) -> dict | None:
    """Giá trị cộng dồn hôm nay tới mốc `upto` (số khoảng 15 phút đã qua) so với trung vị các ngày trước cùng mốc.

    today: cộng dồn 96 mốc 15 phút của hôm nay; usual: các ngày trước, mỗi ngày 96 mốc cộng dồn."""
    if len(usual) < 7 or upto <= 0:
        return None
    med = []
    for q in range(96):
        col = sorted(day[q] for day in usual)
        med.append(col[len(col) // 2])
    now, typical = today[upto - 1], med[upto - 1]
    gap = now - typical
    if abs(gap) <= max(USUAL_MIN[key], USUAL_BAND * typical):
        verdict, text = "par", tr('{what} hôm nay ngang với thường lệ.', what=_name(key))
    elif gap > 0:
        verdict, text = "above", tr('{what} hôm nay cao hơn thường lệ.', what=_name(key))
    else:
        verdict, text = "below", tr('{what} hôm nay thấp hơn thường lệ.', what=_name(key))
    return {"key": key, "title": _name(key), "verdict": verdict, "text": text, "now": round(now), "usual": round(typical),
            "now_text": fmt(key, now), "usual_text": fmt(key, typical), "upto": upto,
            "today": [round(v) for v in today[:upto]], "usual_curve": [round(v) for v in med],
            "status": GOOD if verdict == "above" else WATCH if verdict == "below" else NEUTRAL}


def summary(daily: dict[str, list[tuple[str, float | None]]], weekly: dict[str, list[tuple[str, float | None]]],
            wake: list[tuple[str, float | None]], today: dict, need: int) -> dict:
    """Tóm tắt sức khỏe. daily / weekly: {chỉ số: [(nhãn ngày / tuần, giá trị hoặc None), ...]} cũ tới mới;
    wake: giờ thức dậy (phút từ 0 giờ) theo đêm; today: {chỉ số: (hôm nay, các ngày trước, mốc)} cho vs_usual."""
    changes = [c for c in (detect(k, pts[-DAYS:], need) for k, pts in daily.items()) if c]
    seen = {c["key"] for c in changes}
    changes += [c for c in (detect(k, pts[-WEEKS:], need, weekly=True) for k, pts in weekly.items() if k not in seen) if c]
    changes.sort(key=lambda c: (c["status"] != WATCH, -abs(c["t"])))
    highlights = [h for h in (week_over_week(k, pts, need) for k, pts in daily.items()) if h]
    reg = wake_regularity(wake)
    if reg:
        highlights.insert(min(3, len(highlights)), reg)
    usual = [u for u in (vs_usual(k, *v) for k, v in today.items()) if u]
    counts = {"watch": sum(c["status"] == WATCH for c in changes), "good": sum(c["status"] == GOOD for c in changes)}
    return {"changes": changes, "counts": counts, "highlights": highlights, "today": usual}
