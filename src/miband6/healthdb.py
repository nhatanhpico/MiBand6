"""Lưu dữ liệu sức khỏe đã lấy từ vòng tay (SQLite, mỗi vòng tay một tệp) và tổng hợp để hiển thị.

Vòng tay vẫn giữ dữ liệu của nó (ứng dụng không gửi lệnh xác nhận), nên đây chỉ là bản sao
trên máy tính; mỗi lần đồng bộ chỉ lấy phần mới hơn mốc đã lưu trong bảng `sync`.
"""

from __future__ import annotations

import datetime as dt
import time
import json
import re
import sqlite3
from pathlib import Path

from . import health as H
from . import personal as PS
from . import telemetry as T

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (ts INTEGER PRIMARY KEY, kind INTEGER, intensity INTEGER, steps INTEGER,
                                     hr INTEGER, sleep INTEGER, deep INTEGER, rem INTEGER);
CREATE TABLE IF NOT EXISTS pai (ts INTEGER PRIMARY KEY, utc_offset INTEGER, low REAL, moderate REAL, high REAL,
                                time_low INTEGER, time_moderate INTEGER, time_high INTEGER, today REAL, total REAL);
CREATE TABLE IF NOT EXISTS stress (ts INTEGER, auto INTEGER, value INTEGER, PRIMARY KEY (ts, auto));
CREATE TABLE IF NOT EXISTS spo2 (ts INTEGER PRIMARY KEY, value INTEGER, auto INTEGER);
CREATE TABLE IF NOT EXISTS workouts (start INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS sync (name TEXT PRIMARY KEY, value INTEGER);
CREATE TABLE IF NOT EXISTS tracks (start INTEGER PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS places (key TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS journal (date TEXT NOT NULL, kind TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 1,
                                    PRIMARY KEY (date, kind));
CREATE TABLE IF NOT EXISTS body (date TEXT PRIMARY KEY, height REAL, weight REAL, source TEXT);
"""

JOURNAL_KINDS = ("period", "ejaculation")   # nhật ký người dùng tự ghi (personal.py); chỉ lưu trên máy


def db_path(base: Path, address: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", address or "band")[:80]
    return base / "health" / f"{safe}.sqlite3"


class HealthDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        try:
            path.chmod(0o600)   # dữ liệu sức khỏe: chỉ người dùng hiện tại đọc được
        except OSError:
            pass

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ mốc đồng bộ
    def last(self, name: str) -> int | None:
        row = self.db.execute("SELECT value FROM sync WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def set_last(self, name: str, value: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO sync VALUES (?, ?)", (name, int(value)))
        self.db.commit()

    # ------------------------------------------------------------ ghi
    def add_activity(self, rows: list[tuple]) -> None:
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?,?,?,?)", rows)

    def add_pai(self, rows: list[dict]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO pai VALUES (:ts,:utc_offset,:low,:moderate,:high,"
                ":time_low,:time_moderate,:time_high,:today,:total)", rows)

    def add_stress(self, rows: list[tuple[int, int]], auto: bool) -> None:
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO stress VALUES (?,?,?)", [(ts, int(auto), v) for ts, v in rows])

    def add_spo2(self, rows: list[tuple[int, int, bool]]) -> None:
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO spo2 VALUES (?,?,?)", [(ts, v, int(a)) for ts, v, a in rows])

    def add_workout(self, w: dict) -> None:
        """Buổi tập lấy từ vòng tay; nếu đã có bản từ Mi Fitness cùng lúc bắt đầu thì thay bằng bản này."""
        old = self._workout_near(w["start"])
        if old is not None:
            self.db.execute("DELETE FROM workouts WHERE start = ?", (old["start"],))
            w = {**w, **{k: v for k, v in old.items() if k.startswith("mf_")}}
        self.db.execute("INSERT OR REPLACE INTO workouts VALUES (?, ?)", (w["start"], json.dumps({"source": "band", **w})))
        self.db.commit()

    def _workout_near(self, start: int, slack: int = 180) -> dict | None:
        row = self.db.execute("SELECT data FROM workouts WHERE start BETWEEN ? AND ? ORDER BY ABS(start - ?) LIMIT 1",
                              (start - slack, start + slack, start)).fetchone()
        return json.loads(row[0]) if row else None

    def add_cloud_workouts(self, rows: list[dict]) -> int:
        """Buổi tập lấy từ tài khoản Mi Fitness. Trùng giờ bắt đầu (±3 phút) với buổi vòng tay đã ghi thì giữ bản
        của vòng tay, chỉ ghi thêm mã loại bài tập của Mi Fitness. Trả về số buổi mới."""
        added = 0
        for w in rows:
            old = self._workout_near(w["start"])
            if old is None:
                self.db.execute("INSERT OR REPLACE INTO workouts VALUES (?, ?)", (w["start"], json.dumps(w)))
                added += 1
            elif old.get("source") == "mifitness":
                self.db.execute("UPDATE workouts SET data = ? WHERE start = ?", (json.dumps({**old, **w, "start": old["start"]}), old["start"]))
            else:
                extra = {k: v for k, v in w.items() if k.startswith("mf_")}
                self.db.execute("UPDATE workouts SET data = ? WHERE start = ?", (json.dumps({**old, **extra}), old["start"]))
        self.db.commit()
        return added

    def workout(self, start: int) -> dict | None:
        row = self.db.execute("SELECT data FROM workouts WHERE start = ?", (start,)).fetchone()
        return json.loads(row[0]) if row else None

    def gps_workouts(self) -> list[dict]:
        """Các buổi tập có lộ trình GPS trong Mi Fitness, mới nhất trước."""
        rows = self.db.execute("SELECT data FROM workouts ORDER BY start DESC").fetchall()
        return [w for w in (json.loads(r[0]) for r in rows) if H.has_gps(w)]

    def tracks(self) -> dict[int, list]:
        """Mọi lộ trình đã lưu trên máy: {giờ bắt đầu buổi tập: điểm}."""
        return {start: json.loads(data) for start, data in self.db.execute("SELECT start, data FROM tracks")}

    def places(self, keys: list[str]) -> dict[str, dict | None]:
        """Tên nơi đã tra (geo.area_key -> {city, country, cc} hoặc None nếu vùng đó không thuộc quốc gia nào)."""
        out: dict[str, dict | None] = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for key, data in self.db.execute(f"SELECT key, data FROM places WHERE key IN ({marks})", chunk):
                out[key] = json.loads(data)
        return out

    def set_place(self, key: str, place: dict | None) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO places VALUES (?, ?)", (key, json.dumps(place)))

    # ------------------------------------------------------------ nhật ký cá nhân (người dùng tự ghi)
    def journal(self, kind: str) -> dict[str, int]:
        """{ngày: giá trị} của một loại nhật ký (period: 1 = có kinh; ejaculation: số lần trong ngày)."""
        return dict(self.db.execute("SELECT date, value FROM journal WHERE kind = ? AND value > 0 ORDER BY date", (kind,)))

    def set_journal(self, kind: str, date: str, value: int) -> None:
        """Ghi (value > 0) hoặc xóa (value = 0) một ngày; đánh dấu mốc "journal" để tính lại các chỉ số."""
        if kind not in JOURNAL_KINDS:
            raise ValueError(kind)
        dt.date.fromisoformat(date)
        with self.db:
            if value > 0:
                self.db.execute("INSERT OR REPLACE INTO journal VALUES (?, ?, ?)", (date, kind, int(value)))
            else:
                self.db.execute("DELETE FROM journal WHERE date = ? AND kind = ?", (date, kind))
            self.db.execute("INSERT OR REPLACE INTO sync VALUES ('journal', ?)", (time.time_ns() // 1000,))

    # ------------------------------------------------------------ chiều cao, cân nặng theo thời gian
    def body_history(self) -> list[dict]:
        """Các lần ghi chiều cao (cm), cân nặng (kg), cũ tới mới; source: app (Hồ sơ / ghi tay), mifitness, profile."""
        return [{"date": d, "height": h, "weight": w, "source": src}
                for d, h, w, src in self.db.execute("SELECT date, height, weight, source FROM body ORDER BY date")]

    def add_body(self, date: str, height: float | None, weight: float, source: str) -> bool:
        """Ghi số đo của một ngày (ghi đè ngày đó; thiếu chiều cao thì lấy lần ghi trước). Bỏ qua nếu giống hệt lần ghi
        gần nhất trước ngày đó (đồng bộ Mi Fitness lặp lại không tạo thêm điểm). Trả True nếu có ghi."""
        dt.date.fromisoformat(date)
        prev = self.db.execute("SELECT date, height, weight FROM body WHERE date <= ? ORDER BY date DESC LIMIT 1",
                               (date,)).fetchone()
        if height is None:
            height = prev[1] if prev else None
        if prev and prev[0] != date and prev[1] == height and prev[2] == weight:
            return False
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO body VALUES (?, ?, ?, ?)", (date, height, weight, source))
            self.db.execute("INSERT OR REPLACE INTO sync VALUES ('body', ?)", (time.time_ns() // 1000,))
        return True

    def delete_body(self, date: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM body WHERE date = ?", (date,))
            self.db.execute("INSERT OR REPLACE INTO sync VALUES ('body', ?)", (time.time_ns() // 1000,))

    def track(self, start: int) -> list | None:
        row = self.db.execute("SELECT data FROM tracks WHERE start = ?", (start,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_track(self, start: int, points: list) -> None:
        self.db.execute("INSERT OR REPLACE INTO tracks VALUES (?, ?)", (start, json.dumps(points)))
        self.db.commit()

    def first(self, name: str) -> int | None:
        """Thời điểm cũ nhất đã lưu của một loại dữ liệu (để lấy bù phần cũ hơn)."""
        query = {
            "activity": "SELECT MIN(ts) FROM activity", "stress_auto": "SELECT MIN(ts) FROM stress WHERE auto = 1",
            "stress_manual": "SELECT MIN(ts) FROM stress WHERE auto = 0", "spo2": "SELECT MIN(ts) FROM spo2",
            "pai": "SELECT MIN(ts) FROM pai", "workouts": "SELECT MIN(start) FROM workouts WHERE data LIKE '%\"band\"%'",
        }.get(name)
        return self.db.execute(query).fetchone()[0] if query else None

    # ------------------------------------------------------------ đọc
    def samples(self, t0: int, t1: int) -> list[tuple]:
        return self.db.execute("SELECT * FROM activity WHERE ts >= ? AND ts < ? ORDER BY ts", (t0, t1)).fetchall()

    def kind_before(self, ts: int) -> int | None:
        """Loại hoạt động (4 bit thấp) của mốc trạng thái gần nhất trước `ts`."""
        row = self.db.execute("SELECT kind & 15 FROM activity WHERE ts < ? AND (kind & 15) NOT IN (0, 10) "
                              "ORDER BY ts DESC LIMIT 1", (ts,)).fetchone()
        return row[0] if row else None

    def sleep_sessions(self, t0: int, t1: int, rem: bool = False, samples: list[tuple] | None = None) -> list[dict]:
        """Các giấc ngủ trong [t0, t1), mỗi giấc có "ongoing": còn đang ngủ, tức giấc kéo tới phút mới nhất đã đồng bộ
        (vòng tay chưa ghi lúc thức dậy). Giấc dở dang không phải "đêm qua": như Mi Fitness, chỉ tính khi đã dậy;
        đồng bộ lúc nửa đêm mà tính nó thì đêm qua chỉ còn vài chục phút, kéo lệch điểm ngủ, mức sẵn sàng và phân tích.
        samples: self.samples(t0, t1) nếu đã lấy sẵn."""
        samples = self.samples(t0, t1) if samples is None else samples
        sessions = H.sleep_sessions(samples, self.kind_before(t0), rem=rem)
        last = self.db.execute("SELECT MAX(ts) FROM activity").fetchone()[0]
        for sess in sessions:
            sess["ongoing"] = last is not None and sess["end"] >= last + 60
        return sessions

    def daily_steps(self) -> list[dict]:
        """Tổng bước mỗi ngày có dữ liệu (theo giờ địa phương), cũ tới mới.

        minutes: số bản ghi (vòng tay ghi cả khi tháo ra); worn: số phút đeo vòng (health.worn). Vòng tay ghi
        "không đeo" / "đang sạc" ở từng phút, nên đếm theo loại hoạt động thô là đủ."""
        rows = self.db.execute(
            "SELECT date(ts, 'unixepoch', 'localtime') AS d, SUM(steps), COUNT(*),"
            " SUM(CASE WHEN (kind & 15) IN (?, ?) AND NOT (hr BETWEEN 30 AND 220) THEN 0 ELSE 1 END)"
            " FROM activity GROUP BY d ORDER BY d", H.OFF_WRIST
        ).fetchall()
        return [{"date": d, "steps": s or 0, "minutes": n, "worn": w or 0} for d, s, n, w in rows]

    def analysis(self, goal: int = 8000, today: str | None = None, rem: bool = False, profile: dict | None = None) -> dict:
        """Nhận xét tình trạng hiện tại từ 14 ngày gần nhất (xem health.analyze); hồ sơ cho nhu cầu ngủ theo tuổi và BMI."""
        from . import insights as I

        today = today or dt.date.today().isoformat()
        d0 = dt.date.fromisoformat(today)
        age = PS.age_of(profile, d0)
        first = d0 - dt.timedelta(days=13)
        w0 = H.day_bounds((first - dt.timedelta(days=1)).isoformat())[0] + 12 * 3600
        _, t1 = H.day_bounds(today)
        samples = self.samples(w0, t1)
        sessions = [s for s in self.sleep_sessions(w0, t1, rem=rem, samples=samples) if not s["ongoing"]]
        by_ts = {s[0]: s for s in samples}
        nights: dict[str, dict] = {}
        hrs: dict[str, list[int]] = {}
        for sess in sessions:   # mọi giấc kết thúc trong một ngày cộng lại, như biểu đồ giấc ngủ
            day = H.local_date(sess["end"])
            n = nights.setdefault(day, {"date": day, "minutes": 0, "deep": 0, "awake": 0, "start": sess["start"]})
            for k in ("minutes", "deep", "awake"):
                n[k] += sess[k]
            n["start"] = min(n["start"], sess["start"])
            hrs.setdefault(day, []).extend(by_ts[ts][4] for ts in range(sess["start"], sess["end"], 60)
                                           if ts in by_ts and H.valid_hr(by_ts[ts][4]))
        for day, n in nights.items():
            v = sorted(hrs.get(day, []))
            n["hr"] = v[len(v) // 2] if v else None
        steps = [d for d in self.daily_steps() if first.isoformat() <= d["date"] < today and d["worn"] >= 600]
        week0 = H.day_bounds((d0 - dt.timedelta(days=7)).isoformat())[0]
        workouts = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM workouts WHERE start >= ?", (week0,))]
        active = {s[0] for s in samples if s[0] >= week0 and s[3] >= H.BRISK_STEPS}
        for w in workouts:
            active.update(range(w["start"] - w["start"] % 60, w["end"], 60))
        pai = self.db.execute("SELECT total FROM pai ORDER BY ts DESC LIMIT 1").fetchone()
        spo2 = self.db.execute("SELECT ts, value FROM spo2 WHERE ts >= ? ORDER BY ts", (t1 - 30 * 86400,)).fetchall()
        stress = [r[0] for r in self.db.execute("SELECT value FROM stress WHERE ts >= ? AND auto = 1", (week0,))]
        spo2 = [r for r in spo2 if T.assess("spo2", r[1])["usable"]]
        stress = [v for v in stress if T.assess("stress", v)["usable"]]
        last = self.db.execute("SELECT MAX(ts) FROM activity").fetchone()[0]
        body = {"age": age, "height": (profile or {}).get("height"), "weight": (profile or {}).get("weight"),
                "trend": PS.body_trend(self.body_history(), d0)}
        return H.analyze(sorted(nights.values(), key=lambda n: n["date"]), steps, goal,
                         {"total": pai[0]} if pai else None, spo2, stress, len(active), len(workouts), last,
                         sleep_need=I.sleep_need(age), body=body)

    INSIGHT_DAYS = 60   # ngày dữ liệu dùng cho mức sẵn sàng, nhịp sinh học… (mức nền nhiều tuần)

    def insights(self, date: str | None = None, profile: dict | None = None, rem: bool = True) -> dict:
        """Mức sẵn sàng, trạng thái tinh thần, cường độ vận động và nhịp sinh học tính tới ngày `date` (insights.py).

        Dựng từ dữ liệu từng phút: mỗi đêm (giấc dài nhất theo ngày thức dậy) và mỗi ngày (bước, phút vận động theo
        cường độ, TRIMP, căng thẳng)."""
        from . import insights as I

        date = date or dt.date.today().isoformat()
        d0 = dt.date.fromisoformat(date)
        first = d0 - dt.timedelta(days=self.INSIGHT_DAYS - 1)
        t0 = H.day_bounds((first - dt.timedelta(days=1)).isoformat())[0] + 12 * 3600
        _, t1 = H.day_bounds(date)
        samples = self.samples(t0, t1)
        by_ts = {s[0]: s for s in samples}
        sessions = self.sleep_sessions(t0, t1, rem=rem, samples=samples)

        # ---- mỗi đêm: giấc dài nhất kết thúc trong ngày (giấc còn đang ngủ chưa phải một đêm)
        mains: dict[str, dict] = {}
        for sess in sessions:
            if sess["ongoing"]:
                continue
            day = H.local_date(sess["end"])
            if first.isoformat() <= day <= date and (day not in mains or sess["minutes"] > mains[day]["minutes"]):
                mains[day] = sess
        nights = [self._night(mains[day], by_ts, day) for day in sorted(mains)]

        # ---- hồ sơ: tuổi, giới tính (nhịp tim tối đa, nhu cầu ngủ) và nhật ký chu kỳ (nhịp tim nghỉ pha hoàng thể)
        age, sex = PS.age_of(profile, d0), PS.sex_of(profile)
        need = I.sleep_need(age)
        period_days = list(self.journal("period")) if sex == PS.SEX_FEMALE else []
        PS.adjust_luteal_hr(nights, period_days)

        # ---- mỗi ngày
        hrmax = I.hr_max(age, sex)
        rests = [n["hr"] for n in nights[-14:] if n.get("hr")]
        rest = sorted(rests)[len(rests) // 2] if rests else 60
        workouts = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM workouts WHERE start >= ? AND start < ?", (t0, t1))]
        in_workout: set[int] = set()
        for w in workouts:
            in_workout.update(range(w["start"] - w["start"] % 60, int(w.get("end") or w["start"]), 60))
        kinds = H.effective_kinds(samples, self.kind_before(t0))
        off_wrist = {s[0] for s, k in zip(samples, kinds) if not H.worn(s, k)}
        days: dict[str, dict] = {}
        hourly: dict[int, float] = {}   # TRIMP theo từng giờ: cho thời gian hồi phục
        hr_points = [(s[0], s[4]) for s in samples if H.valid_hr(s[4])]
        # Tải theo thời gian: mỗi số đo nhịp tim đại diện cho khoảng tới số đo kế tiếp, tối đa I.HR_HOLD giây và không
        # qua phút đã tháo vòng. Chu kỳ đo trong lịch sử thay đổi (mỗi phút, mỗi 10 phút…): chỉ cộng phút có số đo thì
        # ngày đo mỗi 10 phút trông nhẹ hơn chừng 10 lần, làm sai mức nền tải và thời gian hồi phục.
        for i, (ts, bpm) in enumerate(hr_points):
            span = min((hr_points[i + 1][0] if i + 1 < len(hr_points) else ts + 60) - ts, I.HR_HOLD)
            hold = 60
            while hold < span and ts + hold not in off_wrist:
                hold += 60
            minutes = hold / 60
            day = H.local_date(ts)
            d = days.setdefault(day, self._blank_day(day))
            d["hr_minutes"] += minutes
            load = I.edwards_trimp(bpm, hrmax) * minutes
            d["trimp"] += load
            if load:
                hourly[ts - ts % 3600 + 1800] = hourly.get(ts - ts % 3600 + 1800, 0) + load
        for s, kind in zip(samples, kinds):
            ts, steps = s[0], s[3]
            day = H.local_date(ts)
            d = days.setdefault(day, self._blank_day(day))
            d["steps"] += steps
            if not H.worn(s, kind):
                continue
            d["wear"] += 1
            level = 0   # 0 nghỉ, 1 nhẹ, 2 vừa, 3 mạnh
            if steps >= 130:
                level = 3
            elif steps >= 100:
                level = 2
            elif steps >= 20:
                level = 1
            if ts in in_workout and H.valid_hr(s[4]):
                reserve = (s[4] - rest) / max(1, hrmax - rest)
                level = max(level, 3 if reserve >= 0.6 else 2 if reserve >= 0.4 else 1 if reserve >= 0.2 else 0)
            if level:
                d[("light", "moderate", "vigorous")[level - 1]] += 1
        for ts, value in self.db.execute("SELECT ts, value FROM stress WHERE auto = 1 AND ts >= ? AND ts < ?", (t0, t1)):
            if not T.assess("stress", value)["usable"]:
                continue
            day = H.local_date(ts)
            d = days.setdefault(day, self._blank_day(day))
            d["stress_sum"] += value
            d["stress_n"] += 1
            d["stress_high"] += value >= 80
        day_list = []
        for i in range(self.INSIGHT_DAYS):
            day = (first + dt.timedelta(days=i)).isoformat()
            d = days.get(day, self._blank_day(day))
            d["stress"] = d["stress_sum"] / d["stress_n"] if d["stress_n"] else None
            d["hr_coverage"] = round(min(1.0, d["hr_minutes"] / d["wear"]), 3) if d["wear"] else 0.0
            day_list.append(d)

        # ---- chỉ số đều đặn giấc ngủ: 14 ngày gần nhất
        s0 = H.day_bounds((d0 - dt.timedelta(days=13)).isoformat())[0]
        asleep = {t for sess in sessions for a, b, k in sess["stages"] if k != "awake" for t in range(a, b, 60) if t >= s0}
        sri = I.sleep_regularity(asleep, {ts for ts in by_ts if ts >= s0}, s0, t1)

        circ = I.circadian(nights, sri)
        chronotype = circ["chronotype"] if circ else None
        hours = sorted(hourly.items())
        today = dt.date.today().isoformat()

        def ready_on(k: int) -> dict | None:
            """Điểm sẵn sàng của đêm thứ k: hôm nay tính tới lúc này (buổi tập trong ngày làm điểm giảm), ngày trước
            tính lúc 8 giờ sáng."""
            day = nights[k]["date"]
            now = time.time() if day == today else H.day_bounds(day)[0] + 8 * 3600
            return I.readiness(nights[:k + 1], [d for d in day_list if d["date"] < day], chronotype,
                               fatigue={"hours": hours, "now": now}, hrmax=hrmax, need=need)

        has_night = bool(nights and nights[-1]["date"] == date)
        ready = ready_on(len(nights) - 1) if has_night else None
        history = []
        for k in range(max(0, len(nights) - 14), len(nights)):
            r = ready_on(k)
            if r:
                history.append({"date": nights[k]["date"], "score": r["score"], "verdict": r["verdict"]})
        return {
            "readiness": ready, "readiness_history": history,
            "readiness_progress": None if ready else I.readiness_progress(nights),
            "readiness_night": has_night,
            "last_night": self._last_night(nights, chronotype, need) if has_night else None,
            "mental": I.mental_state(nights, day_list, circ, need),
            "profile": {"age": None if age is None else int(age), "sex": sex, "hr_max": round(hrmax),
                        "sleep_need": need},
            "cycle": PS.cycle_status(period_days, d0, nights) if sex == PS.SEX_FEMALE else None,
            "ejaculation": (PS.ejaculation_stats(self.journal("ejaculation"), nights, d0)
                            if sex == PS.SEX_MALE else None),
            "intensity": I.activity_intensity([d for d in day_list if d["date"] <= date]),
            "circadian": circ,
            "rem_estimated": any(s.get("rem_estimated") for s in mains.values()),
            "sampling": {"load_method": "time_weighted", "hr_hold_seconds": I.HR_HOLD,
                         "load_min_wear_minutes": I.LOAD_MIN_WEAR, "load_min_hr_coverage": I.LOAD_MIN_COVERAGE,
                         "recovery_window_seconds": 300},
        }

    @staticmethod
    def _last_night(nights: list[dict], chronotype: float | None, need: int) -> dict:
        """Đêm của ngày đang xem: điểm giấc ngủ (cùng cách tính với thành phần "Giấc ngủ đêm qua" của mức sẵn sàng) và
        nhịp tim khi ngủ so với mức nền, có cả khi chưa đủ dữ liệu để tính mức sẵn sàng."""
        from . import insights as I

        night = nights[-1]
        score, notes = I.sleep_score(night, chronotype, need)
        base = [n["hr"] for n in nights[-I.BASELINE_NIGHTS - 1:-1] if n.get("hr")]
        baseline = round(sum(base) / len(base)) if len(base) >= I.MIN_BASELINE else None
        return {"date": night["date"], "score": int(round(score)), "notes": notes, "hr": night.get("hr"),
                "hr_baseline": baseline}

    @staticmethod
    def _blank_day(day: str) -> dict:
        return {"date": day, "steps": 0, "wear": 0, "light": 0, "moderate": 0, "vigorous": 0, "trimp": 0,
                "hr_minutes": 0.0, "stress_sum": 0, "stress_n": 0, "stress_high": 0}

    @staticmethod
    def _night(sess: dict, by_ts: dict, day: str) -> dict:
        """Tóm tắt một đêm: thời lượng, các giai đoạn, nhịp tim khi ngủ, lúc nhịp tim thấp nhất, giờ giữa giấc."""
        asleep = [t for a, b, k in sess["stages"] if k != "awake" for t in range(a, b, 60)]
        hrs = [by_ts[t][4] for t in asleep if t in by_ts and H.valid_hr(by_ts[t][4])]
        night = {"date": day, "minutes": sess["minutes"], "deep": sess["deep"], "rem": sess["rem"],
                 "awake": sess["awake"], "start": sess["start"], "end": sess["end"],
                 "hr": sorted(hrs)[len(hrs) // 2] if hrs else None, "hr_low_at": None,
                 "mid": ((sess["start"] + sess["end"]) / 2 - H.day_bounds(day)[0]) / 60}
        if len(hrs) >= 0.5 * len(asleep) and len(hrs) >= 30:
            # chỉ số hồi phục (như Oura): lúc trung bình 5 phút của nhịp tim xuống thấp nhất, tính theo phần đêm đã qua
            pts = [(t, by_ts[t][4]) for t in asleep if t in by_ts and H.valid_hr(by_ts[t][4])]
            best = None
            for i in range(len(pts) - 4):
                window = pts[i:i + 5]
                if any(b[0] - a[0] != 60 for a, b in zip(window, window[1:])):
                    continue   # năm số đo rời rạc không phải cửa sổ năm phút
                avg = sum(v for _t, v in window) / 5
                if best is None or avg < best[0]:
                    best = (avg, pts[i + 2][0])
            if best:
                night["hr_low_at"] = (best[1] - sess["start"]) / max(60, sess["end"] - sess["start"])
        return night

    def summary(self, date: str, sleep_days: int = 14, rem: bool = False,
                hr_interval_minutes: int | None = None) -> dict:
        """Mọi số liệu trang Sức khỏe cần cho ngày `date` (YYYY-MM-DD) và các ngày gần đó."""
        t0, t1 = H.day_bounds(date)
        day = self.samples(t0, t1)
        hr = [[s[0], s[4]] for s in day if H.valid_hr(s[4])]
        hourly = [0] * 24
        for s in day:
            hourly[dt.datetime.fromtimestamp(s[0]).hour] += s[3]

        # giấc ngủ: tính trên khoảng rộng rồi gán mỗi giấc cho ngày thức dậy (như Mi Fitness)
        first = dt.date.fromisoformat(date) - dt.timedelta(days=sleep_days - 1)
        w0, _ = H.day_bounds((first - dt.timedelta(days=1)).isoformat())
        sessions = [s for s in self.sleep_sessions(w0 + 12 * 3600, t1, rem=rem) if not s["ongoing"]]
        by_day: dict[str, list[dict]] = {}
        for sess in sessions:
            by_day.setdefault(H.local_date(sess["end"]), []).append(sess)
        sleep_history = []
        for i in range(sleep_days):
            d = (first + dt.timedelta(days=i)).isoformat()
            ss = by_day.get(d, [])
            sleep_history.append({"date": d, **{k: sum(s[k] for s in ss) for k in ("minutes", "deep", "light", "rem", "awake")}})
        today_sessions = by_day.get(date, [])
        main = max(today_sessions, key=lambda s: s["minutes"], default=None)

        stress = self.db.execute("SELECT ts, value, auto FROM stress WHERE ts >= ? AND ts < ? ORDER BY ts",
                                 (t0, t1)).fetchall()
        spo2_day = self.db.execute("SELECT ts, value, auto FROM spo2 WHERE ts >= ? AND ts < ? ORDER BY ts",
                                   (t0, t1)).fetchall()
        spo2_recent = self.db.execute("SELECT ts, value, auto FROM spo2 ORDER BY ts DESC LIMIT 30").fetchall()
        # Unknown cadence stays unknown; historical settings changes cannot be inferred.
        end = max(t0, min(t1, int(time.time())))
        cadence = hr_interval_minutes * 60 if hr_interval_minutes and hr_interval_minutes > 0 else None
        quality = {
            "activity": {"source": "band_processed_motion", "sampling": T.sampling(
                [s[0] for s in day], t0, end, expected_interval_seconds=60)},
            "hr": T.series_quality("hr", [(s[0], s[4]) for s in day], t0, end, cadence),
            "stress": T.series_quality("stress", stress, t0, end),
            "spo2": T.series_quality("spo2", spo2_day, t0, end),
        }
        stress = [r for r in stress if T.assess("stress", r[1])["usable"]]
        spo2_day = [r for r in spo2_day if T.assess("spo2", r[1])["usable"]]
        spo2_recent = [r for r in spo2_recent if T.assess("spo2", r[1])["usable"]]
        pai_rows = self.db.execute("SELECT ts, today, total, time_low, time_moderate, time_high FROM pai "
                                   "WHERE ts < ? ORDER BY ts DESC LIMIT 60", (t1,)).fetchall()
        pai_by_day: dict[str, dict] = {}
        for ts, today, total, tl, tm, th in reversed(pai_rows):   # bản ghi sau cùng của mỗi ngày
            pai_by_day[H.local_date(ts)] = {"date": H.local_date(ts), "ts": ts, "today": round(today, 1),
                                            "total": round(total, 1), "time_low": tl, "time_moderate": tm,
                                            "time_high": th}
        pai_days = list(pai_by_day.values())[-14:]
        workouts = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM workouts ORDER BY start DESC").fetchall()]
        # loại bài tập của Mi Fitness dùng mã khác vòng tay: học cách đổi mã từ các buổi có cả hai
        mf_to_band = {w["mf_type"]: w["type"] for w in workouts if w.get("type") is not None and w.get("mf_type") is not None}
        empty_tracks = {r[0] for r in self.db.execute("SELECT start FROM tracks WHERE json_array_length(data) < 2")}
        for w in workouts:
            if w.get("type") is None and w.get("mf_type") in mf_to_band:
                w["type"] = mf_to_band[w["mf_type"]]
            # có nút Bản đồ khi buổi tập có lộ trình trong Mi Fitness và tệp lộ trình (nếu đã tải) không trống
            w["gps"] = H.has_gps(w) and w["start"] not in empty_tracks
            for k in ("mf_sid", "mf_region", "mf_time", "mf_tz"):   # chỉ dùng phía server để tải lộ trình
                w.pop(k, None)
        return {
            "date": date,
            "quality": quality,
            "has_data": bool(self.db.execute("SELECT 1 FROM activity LIMIT 1").fetchone()),
            "steps_days": self.daily_steps(),
            "day": {
                "steps": sum(s[3] for s in day),
                "steps_hourly": hourly,
                "hr": hr,
                "stress": [list(r) for r in stress],
                "spo2": [list(r) for r in spo2_day],
                "sleep": main,
                "naps": [s for s in today_sessions if s is not main],
            },
            "sleep_days": sleep_history,
            "pai": {"latest": pai_days[-1] if pai_days else None, "days": pai_days},
            "spo2_recent": [list(r) for r in spo2_recent],
            "workouts": workouts,
        }
