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
        self.db.execute("INSERT OR REPLACE INTO workouts VALUES (?, ?)", (w["start"], json.dumps(w)))
        self.db.commit()

    # ------------------------------------------------------------ đọc
    def samples(self, t0: int, t1: int) -> list[tuple]:
        return self.db.execute("SELECT * FROM activity WHERE ts >= ? AND ts < ? ORDER BY ts", (t0, t1)).fetchall()

    def daily_steps(self) -> list[dict]:
        """Tổng bước mỗi ngày có dữ liệu (theo giờ địa phương), cũ tới mới."""
        rows = self.db.execute(
            "SELECT date(ts, 'unixepoch', 'localtime') AS d, SUM(steps), COUNT(*) FROM activity GROUP BY d ORDER BY d"
        ).fetchall()
        return [{"date": d, "steps": s or 0, "minutes": n} for d, s, n in rows]

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
        sessions = H.sleep_sessions(self.samples(w0 + 12 * 3600, t1))
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
        workouts = [json.loads(r[0]) for r in
                    self.db.execute("SELECT data FROM workouts ORDER BY start DESC LIMIT 100").fetchall()]
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
