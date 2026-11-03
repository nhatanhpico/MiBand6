"""Lưu dữ liệu sức khỏe đã lấy từ vòng tay (SQLite, mỗi vòng tay một tệp) và tổng hợp để hiển thị.

Vòng tay vẫn giữ dữ liệu của nó (ứng dụng không gửi lệnh xác nhận), nên đây chỉ là bản sao
trên máy tính; mỗi lần đồng bộ chỉ lấy phần mới hơn mốc đã lưu trong bảng `sync`.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

from . import health as H

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
"""


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
        self.db.executemany("INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?,?,?,?)", rows)
        self.db.commit()

    def add_pai(self, rows: list[dict]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO pai VALUES (:ts,:utc_offset,:low,:moderate,:high,"
            ":time_low,:time_moderate,:time_high,:today,:total)", rows)
        self.db.commit()

    def add_stress(self, rows: list[tuple[int, int]], auto: bool) -> None:
        self.db.executemany("INSERT OR REPLACE INTO stress VALUES (?,?,?)", [(ts, int(auto), v) for ts, v in rows])
        self.db.commit()

    def add_spo2(self, rows: list[tuple[int, int, bool]]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO spo2 VALUES (?,?,?)", [(ts, v, int(a)) for ts, v, a in rows])
        self.db.commit()

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

    def daily_steps(self) -> list[dict]:
        """Tổng bước mỗi ngày có dữ liệu (theo giờ địa phương), cũ tới mới."""
        rows = self.db.execute(
            "SELECT date(ts, 'unixepoch', 'localtime') AS d, SUM(steps), COUNT(*) FROM activity GROUP BY d ORDER BY d"
        ).fetchall()
        return [{"date": d, "steps": s or 0, "minutes": n} for d, s, n in rows]

    def analysis(self, goal: int = 8000, today: str | None = None) -> dict:
        """Nhận xét tình trạng hiện tại từ 14 ngày gần nhất (xem health.analyze)."""
        today = today or dt.date.today().isoformat()
        d0 = dt.date.fromisoformat(today)
        first = d0 - dt.timedelta(days=13)
        w0 = H.day_bounds((first - dt.timedelta(days=1)).isoformat())[0] + 12 * 3600
        _, t1 = H.day_bounds(today)
        samples = self.samples(w0, t1)
        sessions = H.sleep_sessions(samples, self.kind_before(w0))
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
        steps = [d for d in self.daily_steps() if first.isoformat() <= d["date"] < today and d["minutes"] >= 600]
        week0 = H.day_bounds((d0 - dt.timedelta(days=7)).isoformat())[0]
        workouts = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM workouts WHERE start >= ?", (week0,))]
        active = {s[0] for s in samples if s[0] >= week0 and s[3] >= H.BRISK_STEPS}
        for w in workouts:
            active.update(range(w["start"] - w["start"] % 60, w["end"], 60))
        pai = self.db.execute("SELECT total FROM pai ORDER BY ts DESC LIMIT 1").fetchone()
        spo2 = self.db.execute("SELECT ts, value FROM spo2 WHERE ts >= ? ORDER BY ts", (t1 - 30 * 86400,)).fetchall()
        stress = [r[0] for r in self.db.execute("SELECT value FROM stress WHERE ts >= ? AND auto = 1", (week0,))]
        last = self.db.execute("SELECT MAX(ts) FROM activity").fetchone()[0]
        return H.analyze(sorted(nights.values(), key=lambda n: n["date"]), steps, goal,
                         {"total": pai[0]} if pai else None, spo2, stress, len(active), len(workouts), last)

    def summary(self, date: str, sleep_days: int = 14) -> dict:
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
        sessions = H.sleep_sessions(self.samples(w0 + 12 * 3600, t1), self.kind_before(w0 + 12 * 3600))
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
        for w in workouts:
            if w.get("type") is None and w.get("mf_type") in mf_to_band:
                w["type"] = mf_to_band[w["mf_type"]]
            w["gps"] = H.has_gps(w)
            for k in ("mf_sid", "mf_region", "mf_time", "mf_tz"):   # chỉ dùng phía server để tải lộ trình
                w.pop(k, None)
        return {
            "date": date,
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
