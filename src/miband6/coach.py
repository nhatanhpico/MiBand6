"""Gợi ý buổi tập tiếp theo và mô hình thể lực cá nhân. Hàm thuần, không I/O.

Mô hình thể lực (học từ chính các buổi tập của bạn): từ các phút chạy / đi bộ đều nhịp (tệp từng giây của Mi Fitness,
hoặc lộ trình GPS + nhịp tim từng phút của vòng tay), tốc độ được đổi ra mức tiêu thụ oxy theo phương trình ACSM
(đi bộ: VO2 = 0,1 S + 1,8 S G + 3,5; chạy: VO2 = 0,2 S + 0,9 S G + 3,5; S: m/phút, G: độ dốc), rồi so với nhịp tim đã
dùng bao nhiêu phần khoảng nhịp tim dự trữ (%HRR ~ %VO2R, Swain & Leutholtz 1997) để suy ra VO2max của mỗi phút.
Trung vị (ưu tiên buổi gần đây) là ước tính của bạn; cùng quan hệ đó cho pace ứng với từng vùng nhịp tim. Chưa có buổi
nào dùng được thì ước tính thô theo nhịp tim tối đa / nhịp tim nghỉ (Uth và cộng sự 2004).

Gợi ý (thuật toán, ngưỡng ghi trong docs/suc-khoe.md): mức sẵn sàng hôm nay, thời gian hồi phục, tỉ lệ tải 7 / 28 ngày
(ACWR), số ngày từ buổi nặng gần nhất, tỉ lệ thời gian ở vùng 4-5 (tập phân cực ~80/20), cảm nhận (RPE) của buổi gần
nhất và thói quen tập (môn, thời lượng thường ngày) chọn loại buổi, thời lượng, vùng nhịp tim và pace.
"""

from __future__ import annotations

import datetime as dt
import math

from .i18n import tr
from .workouts import sport_kind, zone_bounds

WARMUP = 300               # giây đầu mỗi buổi bỏ qua (nhịp tim chưa theo kịp tốc độ)
WINDOW = 60                # giây mỗi cửa sổ
MIN_WINDOW_SAMPLES = 50
STEADY_CV = 0.2            # biến thiên tốc độ trong cửa sổ tối đa
HRR_RANGE = (0.4, 0.95)    # chỉ dùng phút có nhịp tim đủ cao so với lúc nghỉ (ước tính ổn định hơn)
MIN_WINDOWS = 8            # số phút tối thiểu để tin mô hình học từ buổi tập
FITNESS_DAYS = 90          # chỉ học từ các buổi trong chừng này ngày (thể lực thay đổi theo thời gian)
HALF_LIFE_DAYS = 30        # buổi cũ hơn có trọng số thấp hơn
VO2_RANGE = (15.0, 85.0)

HARD_ZONE_SECONDS = 600    # >= 10 phút ở vùng 4-5 là buổi nặng
HARD_SHARE_MAX = 0.2       # tập phân cực: khoảng 20% thời gian ở cường độ cao
ACWR_HIGH = 1.5
ACWR_SAFE = 1.3
ACWR_LOW = 0.8
REST_RECOVERY_H = 36
EASY_RECOVERY_H = 12
DEFAULT_MINUTES = {"run": 30, "walk": 40, "ride": 45, "other": 30}
MIN_MINUTES, MAX_MINUTES = 15, 120
RUN_SLOWEST = 600          # giây/km: chậm hơn 10'/km là tốc độ đi bộ

# Mức VO2max (ml/kg/phút) theo tuổi, giới: ngưỡng của kém / trung bình / khá / tốt / rất tốt (bảng chuẩn của Cooper
# Institute, theo Heyward 2006). Dưới ngưỡng đầu: rất kém.
VO2_NORMS = {
    "male": ((29, (33.0, 36.5, 42.5, 46.5, 52.5)), (39, (31.5, 35.5, 41.0, 45.0, 49.5)), (49, (30.2, 33.6, 39.0, 43.8, 48.1)),
             (59, (26.1, 31.0, 35.8, 41.0, 45.4)), (200, (20.5, 26.1, 32.3, 36.5, 44.3))),
    "female": ((29, (23.6, 29.0, 33.0, 37.0, 41.1)), (39, (22.8, 27.0, 31.5, 35.7, 40.1)), (49, (21.0, 24.5, 29.0, 32.9, 37.0)),
               (59, (20.2, 22.8, 27.0, 31.5, 35.8)), (200, (17.5, 20.2, 24.5, 30.3, 31.5))),
}
VO2_LEVELS = ("very_poor", "poor", "fair", "good", "excellent", "superior")


def acsm_vo2(speed_mps: float, grade: float = 0.0, running: bool = True) -> float:
    """Mức tiêu thụ oxy (ml/kg/phút) khi đi bộ / chạy ở tốc độ, độ dốc cho trước (phương trình ACSM)."""
    s = speed_mps * 60
    g = max(-0.15, min(0.15, grade))
    if running:
        return 0.2 * s + 0.9 * s * max(0.0, g) + 3.5
    return 0.1 * s + 1.8 * s * max(0.0, g) + 3.5


def _is_running(kind: str, speed: float) -> bool:
    """Chạy hay đi bộ cho phương trình ACSM: theo loại buổi, trừ đoạn đi bộ trong buổi chạy và đoạn chạy khi đi bộ."""
    if speed >= 2.2:
        return True
    if speed < 1.7:
        return False
    return kind == "run"


def steady_windows(samples: list[list] | None, track_dist: list[list] | None, minutes: list[list],
                   alt: list[list] | None, start: int, end: int) -> list[list]:
    """Các phút chạy / đi bộ đều nhịp: [[tốc độ (m/s), nhịp tim, độ dốc]], bỏ WARMUP giây đầu.

    samples: tệp từng giây (decode_record_file); track_dist: [[ts, quãng đường cộng dồn]] từ GPS khi không có tệp
    từng giây; minutes: [[ts, nhịp tim, bước]] của vòng tay."""
    alt_at = {int(ts): a for ts, a in alt or []}
    out = []

    def grade(t0: int, t1: int, run: float) -> float:
        a0, a1 = alt_at.get(int(t0)), alt_at.get(int(t1))
        return (a1 - a0) / run if a0 is not None and a1 is not None and run > 20 else 0.0

    sec = [s for s in samples or [] if s[2] is not None]
    if len(sec) >= 600:
        t_first = sec[0][0]
        for i in range(0, len(sec) - WINDOW, WINDOW):
            win = sec[i:i + WINDOW]
            if win[0][0] - t_first < WARMUP or win[-1][0] - win[0][0] > WINDOW + 5:   # khởi động, hoặc có tạm dừng
                continue
            hrs = [s[1] for s in win if s[1]]
            if len(hrs) < MIN_WINDOW_SAMPLES or max(hrs) - min(hrs) > 15:
                continue
            parts = [(b[2] - a[2]) / max(1, b[0] - a[0]) for a, b in zip(win[::10], win[10::10])]
            mean = sum(parts) / len(parts) if parts else 0
            if mean < 0.8 or mean > 7 or (math.sqrt(sum((p - mean) ** 2 for p in parts) / len(parts)) / mean) > STEADY_CV:
                continue
            run = win[-1][2] - win[0][2]
            out.append([round(run / max(1, win[-1][0] - win[0][0]), 3), round(sum(hrs) / len(hrs), 1),
                        round(grade(win[0][0], win[-1][0], run), 3)])
        return out
    if not track_dist or len(track_dist) < 30:
        return out
    # lộ trình GPS + nhịp tim từng phút của vòng tay
    for ts, hr, _st in minutes:
        if not hr or ts < start + WARMUP or ts + WINDOW > end:
            continue
        seg = [p for p in track_dist if ts <= p[0] <= ts + WINDOW]
        if len(seg) < 6 or seg[-1][0] - seg[0][0] < WINDOW * 0.7:
            continue
        run = seg[-1][1] - seg[0][1]
        speed = run / (seg[-1][0] - seg[0][0])
        if 0.8 <= speed <= 7:
            out.append([round(speed, 3), hr, round(grade(seg[0][0], seg[-1][0], run), 3)])
    return out


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    pairs = sorted(pairs)
    half = sum(w for _v, w in pairs) / 2
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def vo2_level(vo2max: float, age: float | None, sex: str | None) -> str | None:
    if age is None or sex not in VO2_NORMS:
        return None
    cuts = next(c for top, c in VO2_NORMS[sex] if age <= top)
    return VO2_LEVELS[sum(1 for c in cuts if vo2max >= c)]


def fitness(workouts: list[dict], hrmax: float, rest_hr: float | None, age: float | None, sex: str | None,
            now: float) -> dict | None:
    """Ước tính VO2max của riêng bạn. workouts: [{"start", "kind", "windows": [[tốc độ, nhịp tim, độ dốc]]}].

    Trả về {"vo2max", "low", "high", "method": "workouts" | "resting_hr", "minutes", "workouts", "level", "trend"} hoặc
    None nếu chưa có cả nhịp tim nghỉ."""
    if not rest_hr or hrmax <= rest_hr + 20:
        return None
    est: list[tuple[float, float]] = []
    per_workout: list[tuple[int, float]] = []
    used = 0
    for w in workouts:
        if w.get("kind") not in ("run", "walk") or now - w["start"] > FITNESS_DAYS * 86400:
            continue
        mine = []
        for speed, hr, grade in w.get("windows") or []:
            hrr = (hr - rest_hr) / (hrmax - rest_hr)
            if not HRR_RANGE[0] <= hrr <= HRR_RANGE[1]:
                continue
            vo2 = acsm_vo2(speed, grade, _is_running(w["kind"], speed))
            v = 3.5 + (vo2 - 3.5) / hrr
            if VO2_RANGE[0] <= v <= VO2_RANGE[1]:
                mine.append(v)
        if mine:
            used += 1
            weight = 0.5 ** ((now - w["start"]) / 86400 / HALF_LIFE_DAYS)
            est += [(v, weight) for v in mine]
            per_workout.append((w["start"], sorted(mine)[len(mine) // 2]))
    out: dict
    if len(est) >= MIN_WINDOWS:
        vals = sorted(v for v, _w in est)

        def q(p: float) -> float:
            return vals[min(len(vals) - 1, int(p * len(vals)))]

        out = {"vo2max": round(_weighted_median(est), 1), "low": round(q(0.25), 1), "high": round(q(0.75), 1),
               "method": "workouts", "minutes": len(est), "workouts": used}
        per_workout.sort()
        if len(per_workout) >= 4:
            half = len(per_workout) // 2
            old = sorted(v for _t, v in per_workout[:half])[half // 2]
            new = sorted(v for _t, v in per_workout[half:])[(len(per_workout) - half) // 2]
            out["trend"] = round(new - old, 1)
    else:
        v = 15.3 * hrmax / rest_hr   # Uth và cộng sự 2004: ước tính thô khi chưa có buổi tập dùng được
        out = {"vo2max": round(max(VO2_RANGE[0], min(VO2_RANGE[1], v)), 1), "low": None, "high": None,
               "method": "resting_hr", "minutes": len(est), "workouts": used}
    out["level"] = vo2_level(out["vo2max"], age, sex)
    return out


def pace_for_hr(hr: float, fit: dict, hrmax: float, rest_hr: float, running: bool) -> int | None:
    """Pace (giây/km) ở mức nhịp tim cho trước theo mô hình thể lực (đường bằng); None nếu ngoài khoảng dùng được."""
    hrr = (hr - rest_hr) / (hrmax - rest_hr)
    if hrr <= 0.2:
        return None
    vo2 = 3.5 + hrr * (fit["vo2max"] - 3.5)
    speed = (vo2 - 3.5) / (0.2 if running else 0.1) / 60   # m/s
    if speed < 0.6:
        return None
    if not running and speed > 2.3:      # đi bộ nhanh hơn ~8 km/h là đã chạy
        return None
    return int(round(1000 / speed))


# ---------------------------------------------------------------- gợi ý buổi tập tiếp theo

KINDS = ("rest", "easy", "endurance", "long", "tempo", "intervals")
KIND_ZONE = {"rest": 1, "easy": 2, "endurance": 2, "long": 2, "tempo": 3, "intervals": 4}
KIND_STATUS = {"rest": "alert", "easy": "watch", "endurance": "ok", "long": "ok", "tempo": "good", "intervals": "good"}


def rpe_label(n: int) -> str:
    """Cảm nhận sau buổi tập (thang 1-5 như "Trải nghiệm tập luyện" của Mi Fitness)."""
    return {1: tr('Rất nhẹ nhàng'), 2: tr('Nhẹ nhàng'), 3: tr('Vừa sức'), 4: tr('Nặng'), 5: tr('Rất nặng')}[n]


def _median(xs: list[float]) -> float | None:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def _part(readiness: dict | None, key: str) -> dict | None:
    return next((p for p in (readiness or {}).get("parts") or [] if p.get("key") == key), None)


def suggest(history: list[dict], readiness: dict | None, days: list[dict], hrmax: float, rest_hr: float | None,
            age: float | None, sex: str | None, now: float) -> dict:
    """Buổi tập nên làm tiếp theo.

    history: các buổi tập gần đây (mới nhất sau cùng) {"start", "kind", "minutes", "distance", "zones" (giây ở vùng
    1-5), "trimp", "rpe", "windows", "type", "mf_type"}; readiness: insights.readiness của hôm nay (hoặc None);
    days: các ngày (insights) có "trimp", "wear", "hr_coverage" để tính tải 7 / 28 ngày."""
    from .insights import _load_day   # cùng điều kiện ngày dùng được cho tải như mức sẵn sàng

    reasons: list[str] = []
    recent = [w for w in history if now - w["start"] <= 28 * 86400]
    week = [w for w in history if now - w["start"] <= 7 * 86400]
    # môn hay tập nhất trong 30 ngày (bỏ "khác"), mặc định đi bộ
    counts: dict[str, int] = {}
    for w in recent:
        if w["kind"] != "other":
            counts[w["kind"]] = counts.get(w["kind"], 0) + 1
    sport = max(counts, key=lambda k: (counts[k], k == "run")) if counts else "walk"
    same = [w for w in recent if w["kind"] == sport]
    typical = _median([w["minutes"] for w in same[-6:]]) or DEFAULT_MINUTES[sport]
    longest = max([w["minutes"] for w in same] or [typical])
    sample = same[-1] if same else None

    # tải 7 / 28 ngày (như thành phần Cân bằng vận động của điểm sẵn sàng)
    month = [d["trimp"] for d in days[-28:] if _load_day(d)]
    weekly = [d["trimp"] for d in days[-7:] if _load_day(d)]
    acwr = (sum(weekly) / len(weekly)) / (sum(month) / len(month)) if len(month) >= 14 and len(weekly) >= 4 \
        and sum(month) / len(month) >= 5 else None
    rec = _part(readiness, "recovery_time")
    recovery = rec.get("hours", 0.0) if rec else 0.0
    verdict = (readiness or {}).get("verdict")
    hard = [w for w in history if sum((w.get("zones") or [0] * 5)[3:]) >= HARD_ZONE_SECONDS or (w.get("rpe") or 0) >= 4]
    hard_days = (now - hard[-1]["start"]) / 86400 if hard else None
    zone_total = sum(sum(w.get("zones") or []) for w in week)
    hard_share = sum(sum((w.get("zones") or [0] * 5)[3:]) for w in week) / zone_total if zone_total >= 600 else None
    last = history[-1] if history else None
    last_rpe = last.get("rpe") if last and now - last["start"] <= 3 * 86400 else None

    if readiness:
        reasons.append(tr('Điểm sẵn sàng hôm nay {s}/100: {label}.', s=readiness["score"], label=readiness["label"].lower()))
    if recovery >= 1:
        reasons.append(tr('Cơ thể còn cần khoảng {h} giờ để hồi phục sau các buổi tập gần đây.', h=int(round(recovery))))
    if acwr is not None and acwr > ACWR_SAFE:
        reasons.append(tr('Tải 7 ngày gấp {r} lần mức 4 tuần của bạn: tăng tải quá nhanh dễ chấn thương.', r=f"{acwr:.1f}"))
    elif acwr is not None and acwr < ACWR_LOW:
        reasons.append(tr('Tải 7 ngày thấp hơn mức 4 tuần của bạn: có thể tăng dần, không quá 10% mỗi tuần.'))
    if hard_days is not None and hard_days < 7:
        reasons.append(tr('Buổi nặng gần nhất cách đây {d} ngày.', d=int(hard_days)))
    elif history:
        reasons.append(tr('Chưa có buổi nặng nào trong 7 ngày qua.'))
    if hard_share is not None and hard_share > HARD_SHARE_MAX:
        reasons.append(tr('{p}% thời gian tập 7 ngày qua ở vùng 4-5; tập phân cực giữ khoảng 20%.', p=int(round(hard_share * 100))))
    if last_rpe and last_rpe >= 4:
        reasons.append(tr('Buổi gần nhất bạn thấy "{label}".', label=rpe_label(last_rpe).lower()))

    # chọn loại buổi
    if verdict == "rest" or recovery >= REST_RECOVERY_H:
        kind = "rest"
    elif verdict == "easy" or recovery >= EASY_RECOVERY_H or (acwr is not None and acwr > ACWR_HIGH) or last_rpe == 5:
        kind = "easy"
    else:
        fresh_hard = hard_days is None or hard_days >= 3
        balanced = hard_share is None or hard_share < HARD_SHARE_MAX
        safe = acwr is None or acwr <= ACWR_SAFE
        long_ago = not any(w["minutes"] >= 1.25 * typical for w in same if now - w["start"] <= 6 * 86400)
        if verdict == "train_hard" and fresh_hard and balanced and safe and sport != "walk":
            kind = "intervals"
        elif verdict in ("train", "train_hard", None) and (hard_days is None or hard_days >= 2) and balanced and safe \
                and sport != "walk" and history:
            kind = "tempo"
        elif long_ago and safe and (acwr is None or acwr < 1.2) and history:
            kind = "long"
        else:
            kind = "endurance"
        if last_rpe and last_rpe >= 4 and kind in ("intervals", "tempo"):
            kind = "endurance"

    # thời lượng
    factor = {"rest": 0.0, "easy": 0.7, "endurance": 1.0, "long": 1.3, "tempo": 1.0, "intervals": 1.0}[kind]
    minutes = typical * factor
    if kind == "long":
        minutes = min(minutes, longest * 1.1 + 5)
    if acwr is not None and acwr < ACWR_LOW and kind in ("endurance", "long"):
        minutes *= 1.1
    minutes = 0 if kind == "rest" else int(5 * round(max(MIN_MINUTES, min(MAX_MINUTES, minutes)) / 5))
    zone = KIND_ZONE[kind]
    bounds = zone_bounds(hrmax)
    hr_low, hr_high = bounds[zone - 1]
    plan = None
    if kind == "tempo":
        main = max(10, int(5 * round((minutes - 15) / 5)))
        plan = {"warmup": 10, "main": {"minutes": main, "zone": 3}, "cooldown": 5}
        minutes = 15 + main
    elif kind == "intervals":
        reps = 4 if typical < 30 else 5 if typical < 45 else 6
        plan = {"warmup": 10, "repeats": {"count": reps, "work": 3, "work_zone": 4, "rest": 2, "rest_zone": 1}, "cooldown": 5}
        minutes = 15 + reps * 5
        hr_low, hr_high = bounds[3]

    fit = fitness(history, hrmax, rest_hr, age, sex, now)
    pace = None
    if fit and rest_hr and sport in ("run", "walk") and kind != "rest":
        fast = pace_for_hr(hr_high, fit, hrmax, rest_hr, sport == "run")
        if sport == "run" and fast and fast > RUN_SLOWEST and kind in ("easy", "endurance", "long"):
            sport = "walk"   # cả đầu nhanh của vùng cũng chỉ là tốc độ đi bộ
            reasons.append(tr('Vùng 2 của bạn tương ứng tốc độ đi bộ nhanh: đi bộ nhanh giữ nhịp tim đúng vùng dễ hơn chạy chậm.'))
        running = sport == "run"
        slow, fast = pace_for_hr(hr_low, fit, hrmax, rest_hr, running), pace_for_hr(hr_high, fit, hrmax, rest_hr, running)
        if running and slow:
            slow = min(slow, RUN_SLOWEST)
        if fast and not running and not slow:
            slow = pace_for_hr(hr_low + 0.5 * (hr_high - hr_low), fit, hrmax, rest_hr, running)
        if slow and fast:
            pace = [fast, max(fast, slow)]
    distance = round(minutes * 60 / ((pace[0] + pace[1]) / 2), 1) if pace and minutes else None
    moderate_week = sum(sum((w.get("zones") or [0] * 5)[2:]) for w in week) // 60
    return {"kind": kind, "sport": sport, "type": (sample or {}).get("type"), "mf_type": (sample or {}).get("mf_type"),
            "status": KIND_STATUS[kind], "minutes": minutes, "zone": zone, "hr": [hr_low, hr_high], "pace": pace,
            "distance": distance, "plan": plan, "reasons": reasons, "fitness": fit,
            "week": {"workouts": len(week), "minutes": int(sum(w["minutes"] for w in week)), "moderate": moderate_week},
            "acwr": round(acwr, 2) if acwr is not None else None, "recovery": round(recovery, 1),
            "week_plan": week_plan(history, kind, minutes, sport, typical, longest, now, acwr, hard_days)}


# ---------------------------------------------------------------- kế hoạch 7 ngày

PLAN_DAYS = 7
HABIT_WEEKS = 8                 # thói quen tập theo thứ trong tuần: học từ chừng này tuần gần nhất
HARD_KINDS = ("tempo", "intervals")
INTENSITY = {"rest": "rest", "easy": "light", "endurance": "moderate", "long": "moderate", "tempo": "hard",
             "intervals": "hard"}
DEFAULT_HABIT = (0.6, 0.2, 0.6, 0.2, 0.6, 0.3, 0.5)   # chưa có lịch sử: thứ Hai, Tư, Sáu, Chủ nhật
MAX_STREAK = 3                  # tối đa chừng này ngày tập liền nhau
HARD_GAP_DAYS = 2               # hai buổi nặng cách nhau ít nhất 48 giờ


def usual_days(history: list[dict], now: float, weeks: int = HABIT_WEEKS) -> list[float]:
    """Thói quen tập theo thứ (0 = thứ Hai): phần các tuần gần đây có tập vào thứ đó."""
    seen: list[set[int]] = [set() for _ in range(7)]
    for w in history:
        age = (now - w["start"]) / 86400
        if 0 <= age < weeks * 7:
            seen[dt.date.fromtimestamp(w["start"]).weekday()].add(int(age // 7))
    return [len(x) / weeks for x in seen]


def _minutes_for(kind: str, typical: float, longest: float) -> int:
    if kind == "rest":
        return 0
    if kind == "tempo":
        return 15 + max(10, int(5 * round((typical - 15) / 5)))
    if kind == "intervals":
        return 15 + (4 if typical < 30 else 5 if typical < 45 else 6) * 5
    m = typical * {"easy": 0.7, "endurance": 1.0, "long": 1.3}[kind]
    if kind == "long":
        m = min(m, longest * 1.1 + 5)
    return int(5 * round(max(MIN_MINUTES, min(MAX_MINUTES, m)) / 5))


def week_plan(history: list[dict], today_kind: str, today_minutes: int, sport: str, typical: float, longest: float,
              now: float, acwr: float | None = None, hard_days_ago: float | None = None) -> list[dict]:
    """Hôm nay và 6 ngày tới: ngày nào tập nặng, vừa, nhẹ, ngày nào nghỉ.

    Hôm nay theo gợi ý của điểm sẵn sàng; các ngày sau theo thói quen tập (những thứ bạn hay tập trong 8 tuần qua, số
    buổi mỗi tuần), tối đa 2 buổi nặng mỗi tuần (tập phân cực), hai buổi nặng cách nhau ít nhất 48 giờ và cách buổi nặng
    gần nhất, sau buổi nặng là buổi nhẹ, một buổi dài mỗi tuần, ít nhất một ngày nghỉ, không tập quá 3 ngày liền. Kế hoạch
    tính lại mỗi ngày (điểm sẵn sàng của các ngày sau chưa biết)."""
    today = dt.date.fromtimestamp(now)
    habit = usual_days(history, now)
    if not any(habit):
        habit = list(DEFAULT_HABIT)
    month = [w for w in history if now - w["start"] <= 28 * 86400]
    per_week = len(month) / 4
    sessions = max(3, min(6, round(per_week))) if per_week >= 1 else 3
    if acwr is not None and acwr > ACWR_SAFE:
        sessions = max(2, sessions - 1)
    hard_max = 0 if sport == "walk" else 1 if sessions <= 3 else 2
    days = [today + dt.timedelta(days=i) for i in range(PLAN_DAYS)]
    train = {0} if today_kind != "rest" else set()

    def streak_ok(i: int, chosen: set[int]) -> bool:
        run = 1
        for step in (-1, 1):
            j = i + step
            while 0 <= j < PLAN_DAYS and j in chosen:
                run += 1
                j += step
        return run <= MAX_STREAK

    order = sorted(range(1, PLAN_DAYS), key=lambda i: (-habit[days[i].weekday()], i))
    for i in order:   # những thứ bạn hay tập nhất trước, không quá 3 ngày liền
        if len(train) >= sessions:
            break
        if streak_ok(i, train):
            train.add(i)
    if len(train) >= PLAN_DAYS:   # luôn chừa ít nhất một ngày nghỉ
        train.discard(min(train - {0}, key=lambda i: habit[days[i].weekday()]))

    kinds = ["rest"] * PLAN_DAYS
    kinds[0] = today_kind
    hard = [0] if today_kind in HARD_KINDS else []
    last_hard = 0 if hard else (-int(hard_days_ago) if hard_days_ago is not None and hard_days_ago < 7 else None)
    for i in sorted(train - {0}, key=lambda i: (-habit[days[i].weekday()], i)):
        if len(hard) >= hard_max:
            break
        if all(abs(i - h) >= HARD_GAP_DAYS for h in hard) and (last_hard is None or i - last_hard >= HARD_GAP_DAYS):
            hard.append(i)
    for n, i in enumerate(sorted(h for h in hard if h)):
        kinds[i] = "intervals" if n == 0 and hard_max == 2 else "tempo"
    # buổi dài: ngày tập (không nặng, không sát buổi nặng) mà bạn hay tập nhất, ưu tiên cuối tuần
    rest_days = [i for i in sorted(train - {0} - set(hard))]
    long_pick = sorted(rest_days, key=lambda i: (any(abs(i - h) == 1 for h in hard), -(days[i].weekday() >= 5),
                                                 -habit[days[i].weekday()], i))
    has_long = today_kind == "long"
    for i in rest_days:
        kinds[i] = "easy" if (i - 1 in hard or (i - 1 == 0 and today_kind in HARD_KINDS)) else "endurance"
    if long_pick and not has_long:
        kinds[long_pick[0]] = "long"
    out = []
    for i, d in enumerate(days):
        kind = kinds[i]
        out.append({"date": d.isoformat(), "kind": kind, "intensity": INTENSITY[kind], "zone": KIND_ZONE[kind],
                    "minutes": today_minutes if i == 0 else _minutes_for(kind, typical, longest), "today": i == 0})
    return out


def workout_stats(w: dict, samples: list[list] | None, track_dist: list[list] | None, alt: list[list] | None,
                  minutes: list[list], hrmax: float) -> dict:
    """Số liệu của một buổi tập cho gợi ý và mô hình thể lực."""
    from .workouts import hr_points, trimp, zone_seconds

    start, end = int(w["start"]), int(w.get("end") or w["start"])
    hr, each = hr_points(samples, minutes, start, end, w.get("avg_hr"))
    zones = zone_seconds(hr, each, hrmax)
    kind = sport_kind(w)
    return {"start": start, "kind": kind, "type": w.get("type"), "mf_type": w.get("mf_type"),
            "minutes": round((w.get("active_seconds") or max(0, end - start)) / 60, 1), "distance": w.get("distance"),
            "zones": zones, "trimp": trimp(zones), "rpe": w.get("rpe"),
            "windows": steady_windows(samples, track_dist, minutes, alt, start, end) if kind in ("run", "walk") else []}
