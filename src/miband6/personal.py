"""Nhật ký cá nhân do người dùng tự ghi (vòng tay không đo được): chu kỳ kinh nguyệt (nữ) và xuất tinh (nam).

Hàm thuần: nhận các ngày đã ghi (YYYY-MM-DD) và các đêm ngủ (healthdb dựng), trả trạng thái, dự đoán và so sánh.
Ngưỡng và nguồn: docs/suc-khoe.md (giữ hai nơi khớp nhau). Dữ liệu chỉ lưu trên máy tính (SQLite của vòng tay).

Chu kỳ kinh nguyệt
- Các ngày có kinh cách nhau tối đa PERIOD_GAP ngày không ghi là một kỳ kinh. Độ dài chu kỳ là khoảng cách giữa hai
  ngày bắt đầu; lấy trung vị 6 chu kỳ gần nhất trong khoảng CYCLE_MIN–CYCLE_MAX ngày, nên quên ghi một tháng (chu kỳ
  56 ngày) không làm lệch dự đoán. Chưa có chu kỳ nào thì dùng 28 ngày.
- Rụng trứng ước tính LUTEAL_DAYS ngày trước kỳ kinh kế tiếp (pha hoàng thể khá ổn định quanh 14 ngày, Lenton 1984);
  cửa sổ dễ thụ thai là 5 ngày trước tới 1 ngày sau rụng trứng (Wilcox 1995). Chỉ là dự đoán theo lịch: không dùng để
  tránh thai, chu kỳ không đều thì càng kém chính xác.
- Pha hoàng thể làm nhịp tim nghỉ tăng khoảng 2–3 nhịp/phút so với pha nang noãn (Shilaih 2017). Mức sẵn sàng trừ phần
  tăng này trước khi so với mức nền, để chu kỳ bình thường không bị báo là "chưa hồi phục". Có từ 5 đêm ở mỗi pha thì
  dùng mức chênh của chính bạn (giới hạn 0–LUTEAL_RHR_MAX), chưa đủ thì LUTEAL_RHR.

Xuất tinh
- Tần suất, lần gần nhất, và giấc ngủ của đêm ngay sau ngày có ghi so với các đêm khác. Đây là tương quan trên dữ liệu
  của chính bạn, không phải nhân quả. Điểm sẵn sàng không đổi theo nhật ký này: chưa có bằng chứng hoạt động tình dục
  đêm trước làm giảm thể lực hôm sau (tổng quan Zavorsky 2019); nhiều người tự thấy dễ ngủ hơn sau cực khoái
  (Lastella 2019, tự báo cáo).

Chiều cao, cân nặng theo thời gian
- Thay đổi 30 / 90 ngày (so với lần ghi gần nhất trước mốc đó), tốc độ kg/tuần (hồi quy tuyến tính các lần ghi trong
  90 ngày, cần cách nhau từ 14 ngày) và thay đổi trong 6 tháng (so với lần ghi cũ nhất trong 183 ngày, cách từ 28 ngày).
- Nên chú ý khi thay đổi từ 5% trong khoảng 6 tháng (mốc sụt cân không chủ ý đáng kể, cũng dùng cho tăng cân), khi
  giảm nhanh hơn 1 kg/tuần (khuyến nghị giảm cân an toàn 0,5–1 kg/tuần), hoặc tăng từ 0,5 kg/tuần; đang thiếu cân mà
  vẫn giảm thì Cần lưu ý.
"""

from __future__ import annotations

import datetime as dt
import statistics

from . import health as H
from .i18n import get_lang, tr

PERIOD_GAP = 2            # ngày không ghi tối đa giữa hai ngày có kinh của cùng một kỳ
CYCLE_MIN, CYCLE_MAX = 18, 50
DEFAULT_CYCLE = 28
DEFAULT_PERIOD = 5
LUTEAL_DAYS = 14
LUTEAL_RHR = 2.0          # nhịp/phút: mức tăng nhịp tim nghỉ thường gặp ở pha hoàng thể
LUTEAL_RHR_MAX = 6.0
MIN_PHASE_NIGHTS = 5      # đêm mỗi pha để tính mức chênh của riêng bạn
MIN_COMPARE_NIGHTS = 3    # đêm mỗi nhóm để so sánh giấc ngủ
PREDICT_DAYS = 70         # dự đoán kỳ kinh, cửa sổ dễ thụ thai cho chừng này ngày tới

SEX_MALE, SEX_FEMALE = "male", "female"


def max_hr_override(value: object) -> int | None:
    """Chỉ nhận số nguyên trong khoảng nhịp tim ứng dụng hỗ trợ."""
    return value if type(value) is int and H.valid_hr(value) else None


def sex_of(profile: dict | None) -> str | None:
    """Giới tính trong hồ sơ (0 nam, 1 nữ như ô Giới tính của Cài đặt vòng tay → Hồ sơ); "Khác" hay chưa chọn: None."""
    g = (profile or {}).get("gender")
    try:
        g = int(g)
    except (TypeError, ValueError):
        return None
    return {0: SEX_MALE, 1: SEX_FEMALE}.get(g)


def age_of(profile: dict | None, on: dt.date) -> float | None:
    birth = (profile or {}).get("birth")
    if not birth:
        return None
    try:
        return (on - dt.date.fromisoformat(str(birth))).days / 365.25
    except ValueError:
        return None


def _d(s: str | dt.date) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(s)


def _iso(d: dt.date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------- chu kỳ kinh nguyệt


def periods(days: list[str]) -> list[tuple[dt.date, dt.date, bool]]:
    """Các kỳ kinh (ngày bắt đầu, ngày cuối đã ghi, chỉ ghi một ngày?) từ các ngày có kinh."""
    out: list[list] = []
    for d in sorted({_d(x) for x in days}):
        if out and (d - out[-1][1]).days <= PERIOD_GAP + 1:
            out[-1][1] = d
        else:
            out.append([d, d])
    return [(a, b, a == b) for a, b in out]


def _cycle_length(ps: list[tuple]) -> tuple[int, list[int]]:
    starts = [p[0] for p in ps]
    lengths = [(b - a).days for a, b in zip(starts, starts[1:])]
    usable = [n for n in lengths if CYCLE_MIN <= n <= CYCLE_MAX][-6:]
    return (round(statistics.median(usable)) if usable else DEFAULT_CYCLE), usable


def _period_length(ps: list[tuple], today: dt.date) -> int:
    # kỳ đang diễn ra (ngày ghi cuối còn sát hôm nay) chưa biết dài bao nhiêu; kỳ chỉ ghi ngày đầu không cho biết độ dài
    done = [(b - a).days + 1 for a, b, single in ps if not single and (today - b).days > PERIOD_GAP]
    return max(2, min(10, round(statistics.median(done[-6:])))) if done else DEFAULT_PERIOD


def phase_on(d: dt.date, ps: list[tuple], cycle: int, period_len: int) -> str | None:
    """"menstrual" | "follicular" | "ovulation" | "luteal" của ngày d, hoặc None nếu không đoán được (trước kỳ đầu tiên
    đã ghi, chu kỳ đó quá ngắn / quá dài vì quên ghi, hoặc đã quá ngày dự đoán mà chưa ghi kỳ mới)."""
    i = next((k for k in range(len(ps) - 1, -1, -1) if ps[k][0] <= d), None)
    if i is None:
        return None
    start, end, single = ps[i]
    last_day = start + dt.timedelta(days=period_len - 1) if single else end
    if d <= last_day:
        return "menstrual"
    nxt = ps[i + 1][0] if i + 1 < len(ps) else start + dt.timedelta(days=cycle)
    if not CYCLE_MIN <= (nxt - start).days <= CYCLE_MAX or d >= nxt:
        return None
    ovulation = nxt - dt.timedelta(days=LUTEAL_DAYS)
    if abs((d - ovulation).days) <= 1:
        return "ovulation"
    return "follicular" if d < ovulation else "luteal"


def luteal_rhr_offset(nights: list[dict], ps: list[tuple], cycle: int, period_len: int) -> tuple[float, bool]:
    """Nhịp tim khi ngủ pha hoàng thể cao hơn pha nang noãn bao nhiêu: (mức chênh, có phải của riêng bạn không)."""
    luteal, follicular = [], []
    for n in nights:
        if not n.get("hr"):
            continue
        phase = phase_on(_d(n["date"]), ps, cycle, period_len)
        if phase == "luteal":
            luteal.append(n["hr"])
        elif phase == "follicular":
            follicular.append(n["hr"])
    if len(luteal) >= MIN_PHASE_NIGHTS and len(follicular) >= MIN_PHASE_NIGHTS:
        gap = statistics.mean(luteal) - statistics.mean(follicular)
        return round(max(0.0, min(LUTEAL_RHR_MAX, gap)), 1), True
    return LUTEAL_RHR, False


def cycle_status(days: list[str], today: dt.date, nights: list[dict] | None = None) -> dict | None:
    """Trạng thái chu kỳ vào ngày `today` từ các ngày có kinh đã ghi, kèm dự đoán cho PREDICT_DAYS ngày tới."""
    ps = [p for p in periods(days) if p[0] <= today]
    if not ps:
        return None
    cycle, usable = _cycle_length(ps)
    plen = _period_length(ps, today)
    start = ps[-1][0]
    next_start = start + dt.timedelta(days=cycle)
    late = max(0, (today - next_start).days)
    ovulation = next_start - dt.timedelta(days=LUTEAL_DAYS)
    offset, personal = luteal_rhr_offset(nights or [], ps, cycle, plen)

    predicted_period, predicted_fertile = [], []
    first = next_start if not late else today + dt.timedelta(days=1)
    k = 0
    while True:
        s = first + dt.timedelta(days=k * cycle)
        if (s - today).days > PREDICT_DAYS:
            break
        predicted_period += [_iso(s + dt.timedelta(days=j)) for j in range(plen)]
        ov = s - dt.timedelta(days=LUTEAL_DAYS)   # rụng trứng của chu kỳ kết thúc ở s (k = 0: chu kỳ hiện tại)
        predicted_fertile += [_iso(ov + dt.timedelta(days=j)) for j in range(-5, 2) if ov + dt.timedelta(days=j) >= today]
        k += 1
    return {
        "day": (today - start).days + 1, "phase": phase_on(today, ps, cycle, plen) if not late else None,
        "cycle_length": cycle, "period_length": plen, "cycles": len(usable),
        "irregular": len(usable) >= 3 and max(usable) - min(usable) > 7,
        "last_start": _iso(start), "next_start": _iso(next_start), "days_to_next": max(0, (next_start - today).days),
        "late": late, "ovulation": _iso(ovulation),
        "fertile": [_iso(ovulation - dt.timedelta(days=5)), _iso(ovulation + dt.timedelta(days=1))],
        "predicted_period": predicted_period, "predicted_fertile": predicted_fertile,
        "rhr_offset": offset, "rhr_offset_personal": personal,
    }


def adjust_luteal_hr(nights: list[dict], days: list[str]) -> float | None:
    """Đặt n["hr_adj"] (nhịp tim khi ngủ đã trừ phần tăng của pha hoàng thể) cho các đêm ở pha hoàng thể; mức sẵn
    sàng và trạng thái tinh thần so nhịp tim nghỉ bằng giá trị này. Trả mức đã trừ, hoặc None nếu chưa ghi chu kỳ."""
    if not days or not nights:
        return None
    last = _d(nights[-1]["date"])
    ps = [p for p in periods(days) if p[0] <= last]
    if not ps:
        return None
    cycle, _ = _cycle_length(ps)
    plen = _period_length(ps, last)
    offset, _ = luteal_rhr_offset(nights, ps, cycle, plen)
    for n in nights:
        if n.get("hr") and phase_on(_d(n["date"]), ps, cycle, plen) == "luteal":
            n["hr_adj"] = n["hr"] - offset
    return offset


# ---------------------------------------------------------------- xuất tinh


def _sleep_group(nights: list[dict]) -> dict:
    def bedtime(n: dict) -> float:   # phút tính từ 12 giờ trưa, để 23:30 và 00:30 gần nhau
        t = dt.datetime.fromtimestamp(n["start"])
        return ((t.hour * 60 + t.minute) - 720) % 1440
    hrs = [n["hr"] for n in nights if n.get("hr")]
    bed = statistics.mean(bedtime(n) for n in nights) + 720
    return {"n": len(nights), "minutes": round(statistics.mean(n["minutes"] for n in nights)),
            "deep_pct": round(statistics.mean(n["deep"] * 100 / n["minutes"] for n in nights), 1),
            "awake": round(statistics.mean(n.get("awake", 0) for n in nights)),
            "hr": round(statistics.mean(hrs), 1) if hrs else None,
            "bedtime": f"{int(bed // 60) % 24:02d}:{int(bed % 60):02d}"}


def ejaculation_stats(events: dict[str, int], nights: list[dict], today: dt.date) -> dict:
    """Tần suất và giấc ngủ của đêm ngay sau ngày có ghi (đêm thức dậy hôm sau) so với các đêm khác."""
    logged = {_d(d): c for d, c in events.items() if c > 0 and _d(d) <= today}
    dates = sorted(logged)
    last = dates[-1] if dates else None

    def count(days: int) -> int:
        return sum(c for d, c in logged.items() if 0 <= (today - d).days < days)

    after, other = [], []
    for n in nights:
        if not n.get("minutes"):
            continue
        (after if _d(n["date"]) - dt.timedelta(days=1) in logged else other).append(n)
    enough = len(after) >= MIN_COMPARE_NIGHTS and len(other) >= MIN_COMPARE_NIGHTS
    return {
        "last": _iso(last) if last else None, "days_since": (today - last).days if last else None,
        "count_7": count(7), "count_30": count(30), "per_week": round(count(28) / 4, 1),
        "sleep": {"after": _sleep_group(after), "other": _sleep_group(other)} if enough else None,
        "nights_after": len(after), "need": MIN_COMPARE_NIGHTS,
    }


# ---------------------------------------------------------------- chiều cao, cân nặng theo thời gian

WEIGHT_CHANGE_PCT = 5.0   # % trong khoảng 6 tháng
WEIGHT_FAST_LOSS = -1.0   # kg/tuần
WEIGHT_FAST_GAIN = 0.5    # kg/tuần


def _human(d: dt.date) -> str:
    return d.strftime("%b %-d, %Y") if get_lang() == "en" else f"{d.day}/{d.month}/{d.year}"


def _change(last: tuple, ref: tuple) -> dict:
    return {"since": _iso(ref[0]), "kg": round(last[1] - ref[1], 1), "pct": round((last[1] - ref[1]) * 100 / ref[1], 1)}


def body_trend(entries: list[dict], today: dt.date) -> dict | None:
    """Cân nặng, chiều cao, BMI mới nhất và xu hướng cân nặng từ các lần ghi (HealthDB.body_history), tới ngày `today`."""
    pts = sorted((_d(e["date"]), float(e["weight"]), e.get("height")) for e in entries
                 if e.get("weight") and _d(e["date"]) <= today)
    if not pts:
        return None
    last = pts[-1]
    heights = [h for _d0, _w, h in pts if h]
    height = heights[-1] if heights else None
    bmi = H.body_mass_index(height, last[1])

    def change(days: int) -> dict | None:
        ref = [p for p in pts if p[0] <= today - dt.timedelta(days=days)]
        return _change(last, ref[-1]) if ref else None

    recent = [p for p in pts if (today - p[0]).days <= 90]
    rate = None
    if len(recent) >= 2 and (recent[-1][0] - recent[0][0]).days >= 14:
        xs = [(p[0] - recent[0][0]).days / 7 for p in recent]
        ys = [p[1] for p in recent]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        rate = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs), 2)
    half = [p for p in pts if (today - p[0]).days <= 183]
    six = _change(last, half[0]) if half and (last[0] - half[0][0]).days >= 28 else None

    status, notes = "good", []
    if six and six["pct"] <= -WEIGHT_CHANGE_PCT:
        status = "watch"
        notes.append(tr('Giảm {p}% cân nặng từ {since}: nếu không cố ý giảm cân, nên hỏi ý kiến bác sĩ.',
                        p=f"{-six['pct']:.0f}", since=_human(half[0][0])))
    elif six and six["pct"] >= WEIGHT_CHANGE_PCT:
        status = "watch"
        notes.append(tr('Tăng {p}% cân nặng từ {since}.', p=f"{six['pct']:.0f}", since=_human(half[0][0])))
    if rate is not None and rate <= WEIGHT_FAST_LOSS:
        status = "watch"
        notes.append(tr('Đang giảm khoảng {r} kg mỗi tuần, nhanh hơn mức an toàn 0,5–1 kg/tuần.', r=f"{-rate:.1f}"))
    elif rate is not None and rate >= WEIGHT_FAST_GAIN:
        status = "watch"
        notes.append(tr('Đang tăng khoảng {r} kg mỗi tuần.', r=f"{rate:.1f}"))
    if bmi is not None and bmi < 18.5 and rate is not None and rate < -0.1:
        status = "alert"
        notes.append(tr('Đang thiếu cân mà cân nặng vẫn giảm.'))
    if not notes and rate is not None:
        notes.append(tr('Cân nặng ổn định.') if abs(rate) < 0.2 else
                     tr('Thay đổi khoảng {r} kg mỗi tuần, trong mức an toàn.', r=f"{rate:+.1f}"))
    if len(heights) >= 2 and heights[-1] - heights[0] >= 1:
        notes.append(tr('Chiều cao tăng {d} cm từ lần ghi đầu.', d=f"{heights[-1] - heights[0]:.0f}"))
    bmi_status, bmi_label = H.bmi_class(bmi) if bmi is not None else (None, None)
    return {
        "date": _iso(last[0]), "weight": last[1], "height": height, "bmi": bmi, "bmi_status": bmi_status,
        "bmi_label": bmi_label, "change_30": change(30), "change_90": change(90), "change_6m": six, "rate": rate,
        "status": status, "notes": notes, "entries": len(pts),
    }
