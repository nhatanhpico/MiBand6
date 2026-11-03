"""Chỉ số tổng hợp từ dữ liệu vòng tay: mức sẵn sàng, trạng thái tinh thần (ước tính), tỉ lệ cường độ vận động,
lệch múi giờ xã hội và áp lực nhịp sinh học. Hàm thuần: nhận số liệu theo đêm / theo ngày (healthdb.insights dựng),
trả kết quả kèm từng thành phần và lời giải thích. Ngưỡng và nguồn: docs/suc-khoe.md (giữ hai nơi khớp nhau).

Phương pháp
- Mức sẵn sàng: các thành phần như Oura Readiness (nhịp tim nghỉ, chỉ số hồi phục, giấc ngủ đêm qua, cân bằng giấc
  ngủ 14 ngày, vận động hôm trước, cân bằng vận động, cân bằng HRV); mỗi thành phần so với mức nền cá nhân nhiều tuần
  như HRV4Training (trung bình, độ lệch chuẩn). Oura không công bố trọng số; trọng số ở đây là lựa chọn của ứng dụng.
  Điều chỉnh cho Mi Band 6: không có HRV thô và nhiệt độ da, nên "cân bằng HRV" dùng chỉ số căng thẳng của vòng tay
  (vòng tay tính nó từ HRV), không có thành phần nhiệt độ.
- Tải vận động: TRIMP theo vùng nhịp tim của Edwards (phút ở 50-60/60-70/70-80/80-90/90-100% nhịp tim tối đa nhân
  1..5), nhịp tim tối đa 208 - 0,7 x tuổi (Tanaka 2001); tỉ lệ tải cấp 7 ngày / tải mạn 28 ngày (ACWR, Gabbett 2016).
  Mỗi số đo nhịp tim tính cho khoảng tới số đo kế tiếp (tối đa HR_HOLD), để tải không phụ thuộc chu kỳ đo; mức nền
  tải chỉ dùng ngày đeo đủ lâu và có nhịp tim gần hết thời gian đeo (_load_day).
- Cường độ: nhịp bước CADENCE-Adults (>= 100 bước/phút ~ vừa, >= 130 ~ mạnh); trong buổi tập dùng nhịp tim dự trữ
  (ACSM: >= 40% vừa, >= 60% mạnh). Phút mạnh tính gấp đôi khi so với 150 phút/tuần (WHO).
- Lệch múi giờ xã hội (SJL): |MSF - MSW|, giờ giữa giấc ngày nghỉ / ngày làm (MCTQ; Wittmann 2006, Roenneberg 2012);
  chronotype MSFsc = MSF - (SDf - SDweek)/2 khi ngày nghỉ ngủ bù.
- Độ lệch pha tổng hợp (CPD, Fischer-Vetter-Roenneberg 2016): mỗi đêm sqrt(lệch so với chronotype^2 + lệch so với đêm
  trước^2). Chỉ số đều đặn giấc ngủ (SRI, Phillips 2017): -100 + 200 x xác suất cùng trạng thái ngủ/thức cách nhau 24 giờ.
- Trạng thái tinh thần: ước tính có giải thích, không phải chẩn đoán. Dựa trên các yếu tố nghiên cứu cho thấy liên quan
  tới tâm trạng: căng thẳng (HRV), thiếu ngủ / thời gian thức dài và lệch nhịp sinh học (nghiên cứu 2.602 bác sĩ nội trú,
  PLOS Digital Health 2024; dịch pha nhịp sinh học dự báo giai đoạn khí sắc, npj Digital Medicine 2024), nhịp tim nghỉ
  tăng, ít vận động.
"""

from __future__ import annotations

import datetime as dt
import math

from .i18n import tr

SLEEP_NEED = 450          # phút: 7,5 giờ, giữa khoảng khuyến nghị 7-9 giờ
BASELINE_NIGHTS = 30      # số đêm làm mức nền nhịp tim nghỉ
MIN_BASELINE = 7          # cần ít nhất chừng này đêm / ngày để so với mức nền
FREE_WEEKDAYS = (5, 6)    # thức dậy thứ Bảy, Chủ nhật: đêm trước ngày nghỉ (đêm thứ Sáu, thứ Bảy)

# trọng số các thành phần của mức sẵn sàng (chuẩn hóa lại theo thành phần có dữ liệu)
READINESS_WEIGHTS = {"rhr": 0.18, "recovery": 0.08, "sleep": 0.20, "sleep_balance": 0.14,
                     "recovery_time": 0.15, "activity_balance": 0.10, "stress_balance": 0.15}


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    """Nội suy tuyến tính theo các điểm (x, y) tăng dần; ngoài khoảng thì lấy giá trị đầu/cuối."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def _hm(minutes: float) -> str:
    minutes = int(round(abs(minutes)))
    return tr('{h} giờ {m} phút', h=minutes // 60, m=minutes % 60) if minutes >= 60 else tr('{m} phút', m=minutes)


def _clock(minutes: float) -> str:
    """Phút tính từ nửa đêm (có thể âm) -> "hh:mm"."""
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def hr_max(age: float | None, sex: str | None = None) -> float:
    """Nhịp tim tối đa ước tính: nữ theo Gulati 2010 (206 - 0,88 x tuổi, đo trên 5.437 phụ nữ), còn lại theo Tanaka,
    Monahan, Seals 2001 (208 - 0,7 x tuổi). Chưa có ngày sinh thì coi 30 tuổi."""
    age = age if age else 30
    return 206 - 0.88 * age if sex == "female" else 208 - 0.7 * age


def sleep_need(age: float | None) -> int:
    """Nhu cầu ngủ (phút) theo khuyến nghị theo tuổi của National Sleep Foundation / AASM: 6-13 tuổi 9-11 giờ, 14-17 tuổi
    8-10 giờ, người lớn 7-9 giờ (từ 65 tuổi 7-8 giờ); lấy giữa khoảng."""
    if age is not None and age < 14:
        return 600
    if age is not None and age < 18:
        return 540
    return SLEEP_NEED


def edwards_trimp(hr: float, hrmax: float) -> int:
    """Hệ số vùng nhịp tim của Edwards cho một phút (0 nếu dưới 50% nhịp tim tối đa)."""
    pct = hr / hrmax
    return 0 if pct < 0.5 else min(5, int((pct - 0.5) * 10) + 1)


# ---------------------------------------------------------------- mức sẵn sàng


def _part(key: str, title: str, score: float, value: str, detail: str) -> dict:
    return {"key": key, "title": title, "score": int(round(max(0.0, min(100.0, score)))), "value": value, "detail": detail}


def _hr(n: dict) -> float:
    """Nhịp tim khi ngủ dùng để so với mức nền: đã trừ phần tăng của pha hoàng thể nếu có ghi chu kỳ (personal.py)."""
    return n.get("hr_adj", n["hr"])


def _rhr_part(nights: list[dict], night: dict) -> dict | None:
    base = [_hr(n) for n in nights[-BASELINE_NIGHTS - 1:-1] if n.get("hr")]
    if not night.get("hr") or len(base) < MIN_BASELINE:
        return None
    mean, sd = _mean(base), max(_sd(base) or 0, 1.5)
    z = (_hr(night) - mean) / sd
    score = _interp(z, [(0.5, 100), (1.5, 75), (2.5, 50), (3.5, 25), (5, 10)])
    diff = _hr(night) - mean
    detail = tr('Nhịp tim khi ngủ đêm qua so với mức nền {n} đêm ({base} nhịp/phút).', n=len(base), base=int(round(mean)))
    if "hr_adj" in night:
        detail += " " + tr('Đang ở pha hoàng thể của chu kỳ: đã trừ {d} nhịp/phút nhịp tim tăng theo chu kỳ trước khi so.',
                           d=f"{night['hr'] - night['hr_adj']:.1f}".rstrip("0").rstrip("."))
    if z >= 1.5:
        detail += " " + tr('Cao hơn thường lệ: cơ thể có thể chưa hồi phục (mệt, căng thẳng, rượu bia, sắp ốm).')
    value = tr('{n} nhịp/phút', n=int(round(night["hr"]))) + (f" ({diff:+.0f})" if abs(diff) >= 1 else "")
    return _part("rhr", tr('Nhịp tim nghỉ'), score, value, detail)


def _recovery_part(night: dict) -> dict | None:
    frac = night.get("hr_low_at")
    if frac is None:
        return None
    score = _interp(frac, [(0.5, 100), (0.75, 60), (1.0, 40)])
    return _part("recovery", tr('Chỉ số hồi phục'), score, tr('{p}% đêm', p=int(round(frac * 100))),
                 tr('Nhịp tim chạm mức thấp nhất ở khoảng {p}% thời gian ngủ; thấp nhất trong nửa đầu đêm là cơ thể hồi phục tốt.',
                    p=int(round(frac * 100))))


def sleep_score(night: dict, chronotype: float | None, need: int = SLEEP_NEED) -> tuple[float, list[str]]:
    """Điểm giấc ngủ một đêm (0-100) và các lưu ý: thời lượng (so với nhu cầu theo tuổi), hiệu quả, ngủ sâu, giờ ngủ
    so với chronotype."""
    notes = []
    shift = need - SLEEP_NEED   # đường điểm thời lượng dịch theo nhu cầu ngủ (người lớn 7,5 giờ)
    dur = _interp(night["minutes"], [(0, 0)] + [(m + shift, v) for m, v in (
        (240, 20), (300, 45), (360, 70), (420, 95), (450, 100), (540, 100), (600, 90), (720, 70))])
    in_bed = night["minutes"] + night.get("awake", 0)
    eff = night["minutes"] / in_bed if in_bed else 1
    eff_s = _interp(eff, [(0.70, 40), (0.80, 65), (0.85, 80), (0.90, 95), (0.95, 100)])
    deep = night.get("deep", 0) * 100 / night["minutes"] if night["minutes"] else 0
    deep_s = _interp(deep, [(0, 30), (5, 55), (10, 80), (13, 95), (16, 100)])
    parts = [(dur, 0.5), (eff_s, 0.15), (deep_s, 0.15)]
    if chronotype is not None and night.get("mid") is not None:
        off = abs(night["mid"] - chronotype)
        parts.append((_interp(off, [(30, 100), (60, 85), (120, 60), (180, 40)]), 0.2))
        if off >= 90:
            notes.append(tr('ngủ lệch {t} so với giờ quen thuộc', t=_hm(off)))
    if night["minutes"] < need - 30:
        notes.append(tr('ngủ {t}, dưới {h} giờ', t=_hm(night["minutes"]), h=(need - 30) // 60))
    if eff < 0.85:
        notes.append(tr('thức giấc nhiều ({p}% thời gian trên giường là ngủ)', p=int(round(eff * 100))))
    total = sum(s * w for s, w in parts) / sum(w for _s, w in parts)
    return total, notes


def _sleep_part(night: dict, chronotype: float | None, need: int = SLEEP_NEED) -> dict:
    score, notes = sleep_score(night, chronotype, need)
    detail = tr('Thời lượng, độ liền mạch, ngủ sâu và giờ ngủ của đêm qua.')
    if notes:
        detail += " " + tr('Lưu ý: {notes}.', notes="; ".join(notes))
    return _part("sleep", tr('Giấc ngủ đêm qua'), score, _hm(night["minutes"]), detail)


def _sleep_balance_part(nights: list[dict], need: int = SLEEP_NEED) -> dict | None:
    recent = nights[-14:]
    if len(recent) < 3:
        return None
    weights = [i + 1 for i in range(len(recent))]   # đêm gần đây nặng hơn
    ratio = sum(min(1.1, n["minutes"] / need) * w for n, w in zip(recent, weights)) / sum(weights)
    debt = sum(max(0, need - n["minutes"]) for n in recent[-7:])
    score = _interp(ratio, [(0.6, 20), (0.75, 50), (0.85, 70), (0.95, 90), (1.0, 100)])
    detail = tr('Ngủ {n} đêm gần đây so với nhu cầu khoảng {t} mỗi đêm ở tuổi của bạn (đêm gần nặng hơn).',
                n=len(recent), t=_hm(need))
    if debt >= 60:
        detail += " " + tr('Nợ ngủ 7 đêm qua: {t}.', t=_hm(debt))
    return _part("sleep_balance", tr('Cân bằng giấc ngủ'), score, tr('{p}% nhu cầu', p=int(round(ratio * 100))), detail)


FATIGUE_TAU = 36.0        # giờ: hằng số suy giảm của mệt mỏi do tập (mô hình thể lực - mệt mỏi kiểu Banister)
MIN_DAILY_LOAD = 30.0     # TRIMP: sàn của tải thường ngày, để vài phút đi bộ không thành "quá tải" với người ít tập
HR_HOLD = 600             # giây: một số đo nhịp tim đại diện tối đa 10 phút tới số đo kế tiếp (healthdb.insights)
LOAD_MIN_WEAR = 600       # phút đeo vòng tối thiểu để một ngày vào mức nền tải vận động
LOAD_MIN_COVERAGE = 0.6   # phần thời gian đeo vòng có nhịp tim (theo HR_HOLD) tối thiểu cho mức nền tải


def _load_day(d: dict) -> bool:
    """Ngày dùng được cho mức nền tải: đeo đủ lâu và có nhịp tim gần hết thời gian đeo. Ngày đo mỗi 30 phút hay tắt đo
    nhịp tim bị đếm thiếu tải, nên bỏ ra thay vì coi là ngày nghỉ."""
    return d.get("wear", 0) >= LOAD_MIN_WEAR and d.get("hr_coverage", 1.0) >= LOAD_MIN_COVERAGE


def recovery_hours(hourly: list[tuple[int, float]], now: float, daily_load: float) -> float:
    """Số giờ còn lại để hồi phục sau các buổi tập gần đây.

    Mỗi giờ có tải (TRIMP) cộng vào "mệt mỏi" A, mờ dần theo e^(-t/FATIGUE_TAU). Với tải đều đặn C mỗi ngày, A ổn
    định quanh C x FATIGUE_TAU / 24; đã hồi phục khi A về tới mức đó. Còn lại: FATIGUE_TAU x ln(A / mức ổn định).
    Tải trong hôm nay cũng được tính, nên điểm giảm ngay sau một buổi tập (như Apple Watch)."""
    fatigue = sum(load * math.exp(-(now - ts) / 3600 / FATIGUE_TAU) for ts, load in hourly if ts <= now)
    steady = max(daily_load, MIN_DAILY_LOAD) * FATIGUE_TAU / 24
    return 0.0 if fatigue <= steady else min(96.0, FATIGUE_TAU * math.log(fatigue / steady))


def _load_parts(days: list[dict], fatigue: dict | None = None) -> list[dict]:
    """Thời gian hồi phục (mệt mỏi từ tải gần đây) và cân bằng vận động (tải cấp / tải mạn) từ TRIMP."""
    out = []
    month = [d["trimp"] for d in days[-28:] if _load_day(d)]
    week = [d["trimp"] for d in days[-7:] if _load_day(d)]
    if len(month) < MIN_BASELINE:
        return out
    chronic = _mean(month) or 0
    acute = _mean(week) or 0
    if fatigue is not None:
        hours = recovery_hours(fatigue["hours"], fatigue["now"], chronic)
        score = _interp(hours, [(0, 100), (6, 92), (12, 80), (24, 60), (36, 45), (48, 35), (72, 15)])
        if hours >= 1:
            detail = tr('Từ tải vận động các ngày gần đây (TRIMP), cơ thể cần thêm khoảng {h} giờ để hồi phục.',
                        h=int(round(hours)))
        else:
            detail = tr('Đã hồi phục sau các buổi tập gần đây.')
        y = days[-1] if days and _load_day(days[-1]) else None
        if y and chronic >= 5 and y["trimp"] > 2 * chronic:
            detail += " " + tr('Hôm qua tải gấp {r} lần thường lệ.', r=f"{y['trimp'] / chronic:.1f}")
        value = tr('{h} giờ', h=int(round(hours))) if hours >= 1 else tr('Đã hồi phục')
        part = _part("recovery_time", tr('Thời gian hồi phục'), score, value, detail)
        part["hours"] = round(hours, 1)
        out.append(part)
    if chronic >= 5 and len(month) >= 14 and len(week) >= 4:
        acwr = acute / chronic
        score = _interp(acwr, [(0.3, 70), (0.5, 80), (0.8, 100), (1.3, 100), (1.5, 75), (2.0, 45), (2.5, 35)])
        detail = tr('Tải 7 ngày so với 28 ngày (ACWR); khoảng 0,8-1,3 là cân bằng, trên 1,5 dễ quá sức.')
        out.append(_part("activity_balance", tr('Cân bằng vận động'), score, f"{acwr:.2f}", detail))
    return out


def _stress_part(days: list[dict]) -> dict | None:
    recent = [d for d in days[-2:] if d.get("stress_n", 0) >= 6]
    base = [d["stress"] for d in days[-31:-2] if d.get("stress_n", 0) >= 6]
    if not recent or len(base) < MIN_BASELINE:
        return None
    cur = _mean([d["stress"] for d in recent])
    mean, sd = _mean(base), max(_sd(base) or 0, 3)
    z = (cur - mean) / sd
    score = _interp(z, [(0, 100), (1, 80), (2, 55), (3, 35)])
    if cur >= 60:
        score = min(score, 70)
    detail = tr('Chỉ số căng thẳng của vòng tay (tính từ HRV) 2 ngày gần nhất so với mức nền {n} ngày ({b}).',
                n=len(base), b=int(round(mean)))
    if z >= 1:
        detail += " " + tr('Cao hơn thường lệ: hệ thần kinh đang chịu nhiều áp lực.')
    return _part("stress_balance", tr('Cân bằng căng thẳng (HRV)'), score, f"{cur:.0f}", detail)


VERDICTS = (   # (điểm từ, khóa, trạng thái màu) - như các mức của Apple Watch Readiness / Garmin Training Readiness
    (80, "train_hard", "good"), (60, "train", "ok"), (40, "easy", "watch"), (0, "rest", "alert"))


def _zones(hrmax: float) -> dict:
    """Vùng nhịp tim theo % nhịp tim tối đa: vùng 1 50-60%, 2 60-70%, 3 70-80%, 4 80-90%, 5 90-100%."""
    return {k: int(round(hrmax * k / 100)) for k in (50, 60, 70, 80, 90, 100)}


def readiness(nights: list[dict], days: list[dict], chronotype: float | None = None, fatigue: dict | None = None,
              hrmax: float | None = None, need: int = SLEEP_NEED) -> dict | None:
    """Điểm sẵn sàng hằng ngày (0-100) và lời khuyên tập hay nghỉ, cho ngày của đêm cuối trong `nights`.

    days: các ngày trước đó (ngày cuối là hôm qua); fatigue: {"hours": [(giờ, TRIMP)], "now": thời điểm tính} cho
    thời gian hồi phục; hrmax: nhịp tim tối đa để gợi ý vùng nhịp tim."""
    if not nights:
        return None
    night = nights[-1]
    parts = [p for p in (_rhr_part(nights, night), _recovery_part(night), _sleep_part(night, chronotype, need),
                         _sleep_balance_part(nights, need), _stress_part(days)) if p]
    parts += _load_parts(days, fatigue)
    have = {p["key"] for p in parts}
    if len(parts) < 3 or not ({"rhr", "sleep"} & have):
        return None
    order = list(READINESS_WEIGHTS)
    parts.sort(key=lambda p: order.index(p["key"]))
    score = sum(p["score"] * READINESS_WEIGHTS[p["key"]] for p in parts) / sum(READINESS_WEIGHTS[p["key"]] for p in parts)
    # Như Oura: một thành phần cơ thể rất thấp kéo điểm xuống, không để "sẵn sàng tập". Cân bằng vận động (ACWR) chỉ
    # góp theo trọng số: nó là xu hướng tải theo tuần, khả năng dự báo còn tranh cãi (Impellizzeri 2020), và nhảy vọt
    # khi lịch đeo vòng / chu kỳ đo thay đổi, không nên một mình biến ngày khỏe thành ngày "nên tập nhẹ".
    low = [p for p in parts if p["score"] < 40 and p["key"] != "activity_balance"]
    if low:
        score = min(score, 59)
    score = int(round(score))
    verdict = next(v for v in VERDICTS if score >= v[0])
    rec = next((p for p in parts if p["key"] == "recovery_time"), None)
    rhr = next((p for p in parts if p["key"] == "rhr"), None)
    caps = []   # giới hạn lời khuyên dù điểm cao: còn đang hồi phục, nhịp tim nghỉ tăng mạnh
    if rec and rec["hours"] >= 24 or rhr and rhr["score"] < 40:
        caps.append("easy")
    elif rec and rec["hours"] >= 12:
        caps.append("train")
    rank = [v[1] for v in VERDICTS]
    if caps and rank.index(caps[0]) > rank.index(verdict[1]):
        verdict = next(v for v in VERDICTS if v[1] == caps[0])
        score = min(score, {"train": 79, "easy": 59}[caps[0]])   # điểm khớp lời khuyên (như Garmin: còn hồi phục thì điểm thấp)
    key, status = verdict[1], verdict[2]
    z = _zones(hrmax or hr_max(None))
    labels = {"train_hard": tr('Sẵn sàng tập nặng'), "train": tr('Sẵn sàng tập luyện'), "easy": tr('Nên tập nhẹ'),
              "rest": tr('Nên nghỉ ngơi')}
    plans = {
        "train_hard": tr('Ngày tốt để tập cường độ cao: chạy nhanh, interval, tập sức mạnh nặng. Nhịp tim có thể lên vùng 4-5 ({lo}-{hi} nhịp/phút).',
                         lo=z[80], hi=z[100]),
        "train": tr('Tập như kế hoạch ở cường độ vừa (vùng 2-3, khoảng {lo}-{hi} nhịp/phút); hạn chế bài rất nặng.',
                    lo=z[60], hi=z[80]),
        "easy": tr('Chỉ nên vận động nhẹ: đi bộ, đạp xe chậm, yoga, giãn cơ (dưới {hi} nhịp/phút).', hi=z[70]),
        "rest": tr('Hôm nay nên nghỉ: ngủ sớm, đi lại nhẹ nhàng, uống đủ nước. Tập nặng lúc này dễ quá sức.'),
    }
    weakest = min(parts, key=lambda p: p["score"])
    advice = {
        "rhr": tr('Nhịp tim nghỉ cao hơn thường lệ: ưu tiên nghỉ ngơi, uống đủ nước, tránh tập nặng hôm nay.'),
        "recovery": tr('Cơ thể hồi phục chậm trong đêm: tránh ăn khuya, rượu bia và tập nặng sát giờ ngủ.'),
        "sleep": tr('Giấc ngủ đêm qua chưa tốt: cân nhắc ngủ sớm hơn tối nay hoặc chợp mắt ngắn buổi chiều.'),
        "sleep_balance": tr('Đang thiếu ngủ nhiều đêm: ngủ đủ 7-9 giờ trong vài đêm tới để trả nợ ngủ.'),
        "recovery_time": tr('Cơ thể còn đang hồi phục sau các buổi tập gần đây: để thêm thời gian trước buổi nặng tiếp theo.'),
        "activity_balance": tr('Tải vận động tuần này lệch nhiều so với thường lệ: tăng hoặc giảm từ từ.'),
        "stress_balance": tr('Căng thẳng cao hơn thường lệ: dành thời gian thư giãn, hít thở chậm, đi bộ nhẹ.'),
    }
    why = advice[weakest["key"]] if weakest["score"] < 80 else tr('Các chỉ số đều ổn: hôm nay phù hợp để vận động như kế hoạch.')
    return {"score": score, "verdict": key, "status": status, "label": labels[key], "plan": plans[key], "advice": why,
            "recovery_hours": rec["hours"] if rec else None, "date": night["date"], "parts": parts,
            "zones": z}


def readiness_progress(nights: list[dict]) -> dict:
    """Khi chưa đủ dữ liệu: đã có bao nhiêu đêm có nhịp tim khi ngủ trong 30 đêm gần đây (cần MIN_BASELINE + 1)."""
    have = sum(1 for n in nights[-BASELINE_NIGHTS - 1:] if n.get("hr"))
    return {"nights": have, "need": MIN_BASELINE + 1}


# ---------------------------------------------------------------- cường độ vận động


def activity_intensity(days: list[dict]) -> dict | None:
    """Tỉ lệ cường độ vận động 7 ngày: phút vừa + mạnh trên tổng phút vận động (nhẹ + vừa + mạnh)."""
    week = days[-7:]
    light = sum(d.get("light", 0) for d in week)
    moderate = sum(d.get("moderate", 0) for d in week)
    vigorous = sum(d.get("vigorous", 0) for d in week)
    active = light + moderate + vigorous
    if active < 30:
        return None
    ratio = (moderate + vigorous) / active
    equivalent = moderate + 2 * vigorous   # WHO: 1 phút mạnh tương đương 2 phút vừa
    level = "good" if ratio >= 0.25 else "ok" if ratio >= 0.10 else "low"
    if level == "good":
        detail = tr('Phần lớn thời gian vận động có cường độ đủ để tốt cho tim mạch.')
    elif level == "ok":
        detail = tr('Có vận động vừa và mạnh nhưng phần lớn là đi lại nhẹ; thêm vài đoạn đi bộ nhanh 10 phút mỗi ngày.')
    else:
        detail = tr('Gần như toàn bộ là vận động nhẹ; đi bộ nhanh (từ 100 bước/phút) giúp tăng tỉ lệ này.')
    detail += " " + tr('Tương đương {n} phút vận động vừa mỗi tuần (khuyến nghị 150).', n=equivalent)
    return {"ratio": round(ratio * 100), "light": light, "moderate": moderate, "vigorous": vigorous,
            "equivalent": equivalent, "level": level, "detail": detail,
            "days": [{"date": d["date"], "light": d.get("light", 0), "moderate": d.get("moderate", 0),
                      "vigorous": d.get("vigorous", 0)} for d in week]}


# ---------------------------------------------------------------- nhịp sinh học


def sleep_regularity(asleep: set[int], covered: set[int], t0: int, t1: int) -> float | None:
    """SRI (Phillips 2017) trên các phút [t0, t1): so trạng thái ngủ/thức mỗi phút với 24 giờ sau, chỉ khi cả hai phút
    đều có dữ liệu (đeo vòng). Trả None nếu quá ít cặp phút để tin được (dưới 3 ngày)."""
    same = total = 0
    for t in range(t0 - t0 % 60, t1 - 86400, 60):
        u = t + 86400
        if t in covered and u in covered:
            total += 1
            same += (t in asleep) == (u in asleep)
    if total < 3 * 1440:
        return None
    return -100 + 200 * same / total


def circadian(nights: list[dict], sri: float | None = None) -> dict | None:
    """Lệch múi giờ xã hội, chronotype (MSFsc), độ lệch pha tổng hợp (CPD) và áp lực nhịp sinh học (0-100)."""
    recent = nights[-28:]
    work = [n for n in recent if dt.date.fromisoformat(n["date"]).weekday() not in FREE_WEEKDAYS]
    free = [n for n in recent if dt.date.fromisoformat(n["date"]).weekday() in FREE_WEEKDAYS]
    out: dict = {"nights": [{"date": n["date"], "mid": round(n["mid"]), "free": n in free,
                             "start": round(n["mid"] - n["minutes"] / 2 - n.get("awake", 0) / 2),
                             "end": round(n["mid"] + n["minutes"] / 2 + n.get("awake", 0) / 2)} for n in recent]}
    if len(recent) < 5:
        return None
    msw = _mean([n["mid"] for n in work]) if len(work) >= 2 else None
    msf = _mean([n["mid"] for n in free]) if len(free) >= 1 else None
    chronotype = msf if msf is not None else _mean([n["mid"] for n in recent])
    sjl = None
    if msw is not None and msf is not None:
        sdw = _mean([n["minutes"] for n in work])
        sdf = _mean([n["minutes"] for n in free])
        sdweek = (5 * sdw + 2 * sdf) / 7
        chronotype = msf - (sdf - sdweek) / 2 if sdf > sdw else msf   # MSFsc
        sjl = abs(msf - msw)
    cpd_values = []
    for prev, cur in zip(recent[-15:], recent[-14:]):
        gap = (dt.date.fromisoformat(cur["date"]) - dt.date.fromisoformat(prev["date"])).days
        if gap == 1:
            cpd_values.append(math.hypot(cur["mid"] - chronotype, cur["mid"] - prev["mid"]) / 60)
    cpd = _mean(cpd_values) if len(cpd_values) >= 3 else None
    parts = []
    if sjl is not None:
        parts.append((min(1.0, sjl / 120) * 100, 0.35))
    if cpd is not None:
        parts.append((min(1.0, max(0.0, (cpd - 0.5) / 2.0)) * 100, 0.35))
    if sri is not None:
        parts.append((min(1.0, max(0.0, (85 - sri) / 45)) * 100, 0.30))
    if not parts:
        return None
    strain = int(round(sum(s * w for s, w in parts) / sum(w for _s, w in parts)))
    level = "low" if strain < 30 else "moderate" if strain < 60 else "high"
    notes = []
    if sjl is not None:
        notes.append(tr('Ngày nghỉ giữa giấc ngủ lệch {t} so với ngày làm việc.', t=_hm(sjl)) if sjl >= 30
                     else tr('Giờ ngủ ngày nghỉ và ngày làm gần như giống nhau.'))
    if cpd is not None and cpd >= 1.5:
        notes.append(tr('Giờ ngủ thay đổi nhiều giữa các đêm liên tiếp.'))
    if sri is not None and sri < 60:
        notes.append(tr('Lịch ngủ - thức không đều (SRI thấp).'))
    if level == "low":
        notes.append(tr('Nhịp sinh học ổn định; giữ giờ ngủ, giờ dậy như hiện tại, kể cả cuối tuần.'))
    else:
        notes.append(tr('Giữ giờ dậy cố định mỗi ngày (chênh không quá 1 giờ, cả cuối tuần) và ra ánh sáng buổi sáng.'))
    out.update({
        "sjl": None if sjl is None else round(sjl), "msw": None if msw is None else round(msw),
        "msf": None if msf is None else round(msf), "chronotype": round(chronotype),
        "chronotype_clock": _clock(chronotype), "cpd": None if cpd is None else round(cpd, 2),
        "sri": None if sri is None else round(sri), "strain": strain, "level": level,
        "label": {"low": tr('Thấp'), "moderate": tr('Vừa'), "high": tr('Cao')}[level], "notes": notes,
        "work_nights": len(work), "free_nights": len(free),
    })
    return out


# ---------------------------------------------------------------- trạng thái tinh thần (ước tính)


def mental_state(nights: list[dict], days: list[dict], circ: dict | None, need: int = SLEEP_NEED) -> dict | None:
    """Ước tính trạng thái tinh thần hiện tại từ các yếu tố sinh lý liên quan tới tâm trạng. Không phải chẩn đoán."""
    factors = []   # (khóa, mức rủi ro 0-1, trọng số, nhóm "tension" | "fatigue", mô tả)
    stress_days = [d for d in days[-3:] if d.get("stress_n", 0) >= 6]
    if stress_days:
        avg = _mean([d["stress"] for d in stress_days])
        high = sum(d.get("stress_high", 0) for d in stress_days) / max(1, sum(d["stress_n"] for d in stress_days))
        risk = min(1.0, max(0.0, (avg - 25) / 50) + high * 0.5)
        factors.append(("stress", risk, 0.35, "tension",
                        tr('căng thẳng trung bình {v} trong {n} ngày, {p}% số đo ở mức cao', v=int(round(avg)),
                           n=len(stress_days), p=int(round(high * 100)))))
    recent = nights[-3:]
    if recent:
        avg = _mean([n["minutes"] for n in recent])
        debt = sum(max(0, need - n["minutes"]) for n in nights[-7:])
        risk = min(1.0, max(0.0, (need - avg) / 150) + min(0.4, debt / 900))
        factors.append(("sleep", risk, 0.25, "fatigue",
                        tr('ngủ trung bình {t} mỗi đêm ({n} đêm), nợ ngủ 7 ngày {d}', t=_hm(avg), n=len(recent), d=_hm(debt))))
    if circ and (circ.get("cpd") is not None or circ.get("sjl") is not None):
        cpd = circ.get("cpd") or 0
        sjl = (circ.get("sjl") or 0) / 60
        risk = min(1.0, max(cpd - 0.5, 0) / 2.0 * 0.6 + min(sjl / 2, 1) * 0.4)
        factors.append(("circadian", risk, 0.15, "fatigue",
                        tr('áp lực nhịp sinh học {s}/100', s=circ.get("strain", 0))))
    base = [_hr(n) for n in nights[-BASELINE_NIGHTS - 1:-1] if n.get("hr")]
    if len(base) >= MIN_BASELINE and nights and nights[-1].get("hr"):
        z = (_hr(nights[-1]) - _mean(base)) / max(_sd(base) or 0, 1.5)
        factors.append(("rhr", min(1.0, max(0.0, z / 2.5)), 0.15, "tension",
                        tr('nhịp tim nghỉ {d} nhịp/phút so với thường lệ', d=f"{_hr(nights[-1]) - _mean(base):+.0f}")))
    week = days[-7:]
    if week:
        mvpa = sum(d.get("moderate", 0) + 2 * d.get("vigorous", 0) for d in week)
        factors.append(("activity", min(1.0, max(0.0, (150 - mvpa) / 150)), 0.10, "fatigue",
                        tr('{n} phút vận động vừa/mạnh 7 ngày qua (vận động giúp cải thiện tâm trạng)', n=mvpa)))
    keys = {f[0] for f in factors}
    if len(factors) < 3 or not ({"stress", "sleep"} & keys):
        return None
    strain = int(round(100 * sum(r * w for _k, r, w, _g, _d in factors) / sum(w for _k, _r, w, _g, _d in factors)))

    def group(name: str) -> float:
        rows = [(r, w) for _k, r, w, g, _d in factors if g == name]
        return sum(r * w for r, w in rows) / sum(w for _r, w in rows) if rows else 0.0

    tension, fatigue = group("tension"), group("fatigue")
    if tension >= 0.5 and fatigue >= 0.5:
        state = "overloaded"
    elif tension >= 0.5:
        state = "tense"
    elif fatigue >= 0.5:
        state = "fatigued"
    elif tension < 0.25 and fatigue < 0.3:
        state = "calm"
    else:
        state = "balanced"
    labels = {"calm": tr('Thư thái'), "balanced": tr('Cân bằng'), "tense": tr('Căng thẳng'),
              "fatigued": tr('Mệt mỏi'), "overloaded": tr('Quá tải')}
    texts = {
        "calm": tr('Ít căng thẳng, ngủ đủ: thời điểm tốt cho việc cần tập trung hoặc sáng tạo.'),
        "balanced": tr('Không có dấu hiệu đáng lo; giữ nhịp ngủ, vận động như hiện tại.'),
        "tense": tr('Cơ thể đang ở trạng thái căng (căng thẳng hoặc nhịp tim nghỉ cao): nghỉ ngắn, hít thở chậm, đi bộ nhẹ có thể giúp.'),
        "fatigued": tr('Dấu hiệu mệt mỏi do thiếu ngủ hoặc lệch giờ ngủ: ưu tiên ngủ đủ và đều giờ vài ngày tới.'),
        "overloaded": tr('Vừa căng thẳng vừa thiếu ngủ: dễ cáu gắt, khó tập trung. Giảm bớt việc nếu được, ngủ sớm, và nói chuyện với người thân nếu kéo dài.'),
    }
    stress_n = sum(d.get("stress_n", 0) for d in stress_days)
    confidence = "high" if stress_n >= 40 and len(recent) >= 3 else "medium" if len(factors) >= 4 else "low"
    top = sorted(factors, key=lambda f: f[1] * f[2], reverse=True)
    return {"state": state, "label": labels[state], "text": texts[state], "strain": strain,
            "tension": round(tension * 100), "fatigue": round(fatigue * 100), "confidence": confidence,
            "confidence_label": {"high": tr('cao'), "medium": tr('trung bình'), "low": tr('thấp')}[confidence],
            "factors": [{"key": k, "level": round(r * 100), "text": d} for k, r, _w, _g, d in top]}
