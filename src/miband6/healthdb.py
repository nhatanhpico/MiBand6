"""Lưu dữ liệu sức khỏe đã lấy từ vòng tay (SQLite, mỗi vòng tay một tệp) và tổng hợp để hiển thị.

Vòng tay vẫn giữ dữ liệu của nó (ứng dụng không gửi lệnh xác nhận), nên đây chỉ là bản sao
trên máy tính; mỗi lần đồng bộ chỉ lấy phần mới hơn mốc đã lưu trong bảng `sync`.
"""

from __future__ import annotations

import datetime as dt
import time
import json
import zlib
import re
import sqlite3
from pathlib import Path

from . import health as H
from . import models as M
from . import personal as PS
from . import risk as R
from . import telemetry as T

RECOVERY_MIN_HR_COVERAGE = 0.70  # phần số phút ngủ có số đo nhịp tim hợp lệ
MIN_NIGHT_HR = 10                # số đo nhịp tim tối thiểu lúc ngủ để tính nhịp tim khi ngủ của một đêm
RISK_DAYS = 30                   # mô hình nguy cơ (risk.py): số ngày gần nhất cho nhịp tim lúc nghỉ, giờ ngủ, vận động
                                 # (dài hơn thì số "thường ngày" ổn định hơn, như câu hỏi "thường" của khảo sát)
RISK_MIN_REST = 30               # ... cần số đo lúc ngồi yên ban ngày trong ít nhất ngần này khoảng 10 phút
RISK_HOURS = (8, 22)             # ... chỉ số đo ban ngày (giờ địa phương), như mạch đo khi ngồi nghỉ của NHANES
# Lịch sử gọn theo ngày (bảng daily) cho mô hình cá nhân: mỗi ngày đã trọn một dòng (đêm chính, tải vận động...), để mô
# hình học từ nhiều tháng mà không phải tính lại từ dữ liệu từng phút. Đổi cách tính đêm / ngày thì tăng DAILY_VERSION
# (lịch sử cũ được tính lại dần). Mỗi lần insights lấp thêm tối đa HISTORY_CHUNK ngày cũ hơn chưa lưu.
DAILY_VERSION = 1
HISTORY_DAYS = 365
HISTORY_CHUNK = 45
NIGHT_KEYS = ("date", "hr", "hr_n", "minutes", "awake", "start", "end", "mid", "evening")
DAY_KEYS = ("date", "trimp", "wear", "hr_coverage", "light", "moderate", "vigorous", "steps")

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
CREATE TABLE IF NOT EXISTS mf_sleep (start INTEGER PRIMARY KEY, end INTEGER, date TEXT, minutes INTEGER, deep INTEGER,
                                     light INTEGER, rem INTEGER, awake INTEGER, score INTEGER);
CREATE TABLE IF NOT EXISTS live_hr (ts INTEGER PRIMARY KEY, total INTEGER, n INTEGER, lo INTEGER, hi INTEGER);
CREATE TABLE IF NOT EXISTS daily (date TEXT PRIMARY KEY, version INTEGER, night TEXT, day TEXT);
CREATE TABLE IF NOT EXISTS workout_files (start INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE IF NOT EXISTS workout_rpe (start INTEGER PRIMARY KEY, rpe INTEGER, at INTEGER);
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
        self._model_cache: tuple | None = None   # (khóa dữ liệu học, mô hình): chỉ học lại khi có đêm mới
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

    # ------------------------------------------------------------ báo cáo giấc ngủ của Mi Fitness
    def add_cloud_sleep(self, rows: list[dict]) -> int:
        """Lưu các giấc ngủ trong báo cáo ngày của Mi Fitness (xiaomi_cloud.fetch_sleep_reports). Giấc trùng giờ bắt đầu
        (±3 phút) thì thay bằng bản mới. Trả về số giấc mới."""
        added = 0
        with self.db:
            for r in rows:
                old = self.db.execute("SELECT start FROM mf_sleep WHERE start BETWEEN ? AND ?",
                                      (r["start"] - 180, r["start"] + 180)).fetchone()
                if old:
                    self.db.execute("DELETE FROM mf_sleep WHERE start = ?", (old[0],))
                else:
                    added += 1
                self.db.execute("INSERT INTO mf_sleep VALUES (?,?,?,?,?,?,?,?,?)",
                                (r["start"], r["end"], r.get("date"), r.get("minutes"), r.get("deep"), r.get("light"),
                                 r.get("rem"), r.get("awake"), r.get("score")))
            self.db.execute("INSERT OR REPLACE INTO sync VALUES ('mf_sleep', ?)", (int(time.time()),))
        return added

    def sleep_reference(self, t0: int, t1: int) -> list[dict]:
        """Giấc ngủ của Mi Fitness chồng lên [t0, t1)."""
        cols = ("start", "end", "date", "minutes", "deep", "light", "rem", "awake", "score")
        rows = self.db.execute(f"SELECT {', '.join(cols)} FROM mf_sleep WHERE end > ? AND start < ? ORDER BY start",
                               (t0, t1)).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    CALIB_NIGHTS = 60   # số đêm Mi Fitness gần nhất dùng để học tỉ lệ ngủ sâu / REM

    def sleep_calibration(self) -> dict | None:
        """Tỉ lệ ngủ sâu, REM (trung vị) trong các đêm dài >= 3 giờ Mi Fitness đã chia giai đoạn: dùng cho các đêm chưa có
        báo cáo của Mi Fitness. REM chỉ tính các đêm Mi Fitness có REM (vòng tay mới ghi REM từ firmware 11/2026)."""
        rows = self.db.execute("SELECT minutes, deep, rem FROM mf_sleep WHERE minutes >= 180 AND deep > 0 "
                               "ORDER BY start DESC LIMIT ?", (self.CALIB_NIGHTS,)).fetchall()
        if len(rows) < 5:
            return None
        deep = sorted(d / m for m, d, _r in rows)
        rem = sorted(r / m for m, _d, r in rows if r)
        return {"deep_share": round(deep[len(deep) // 2], 4), "rem_share": round(rem[len(rem) // 2], 4) if rem else None,
                "nights": len(rows)}

    def sleep_validation(self, days: int = 60) -> dict | None:
        """Độ khớp của thuật toán giấc ngủ với báo cáo Mi Fitness, các đêm >= 3 giờ trong `days` ngày gần nhất: sai lệch
        tuyệt đối trung bình (phút) của giờ ngủ, giờ dậy, thời lượng, ngủ sâu, REM. Tính như khi chưa có Mi Fitness
        (không dùng số của đêm đó, không hiệu chỉnh), để con số là độ chính xác thật của riêng thuật toán."""
        last = self.db.execute("SELECT MAX(end) FROM mf_sleep").fetchone()[0]
        if not last:
            return None
        t0 = last - days * 86400
        refs = [r for r in self.sleep_reference(t0, last + 1) if (r["minutes"] or 0) >= 180]
        if not refs:
            return None
        sessions = H.sleep_sessions(self.samples(t0 - 43200, last + 43200), self.kind_before(t0 - 43200))
        errs: dict[str, list[float]] = {k: [] for k in ("start", "end", "minutes", "deep", "rem")}
        for ref in refs:
            ours = H._matching(sessions, ref["start"], ref["end"])
            if not ours:
                continue
            errs["start"].append(abs(ours["start"] - ref["start"]) / 60)
            errs["end"].append(abs(ours["end"] - ref["end"]) / 60)
            errs["minutes"].append(abs(ours["minutes"] - ref["minutes"]))
            if ref["deep"]:
                errs["deep"].append(abs(ours["deep"] - ref["deep"]))
            if ref["rem"]:
                errs["rem"].append(abs(ours["rem"] - ref["rem"]))
        if not errs["start"]:
            return None
        return {"nights": len(errs["start"]), "of": len(refs),
                **{k: round(sum(v) / len(v), 1) if v else None for k, v in errs.items()}}

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

    # ------------------------------------------------------------ chi tiết buổi tập

    def workout_files(self, start: int) -> dict | None:
        """Tệp chi tiết đã tải của một buổi tập: {"samples": dữ liệu từng giây hoặc None, "alt": độ cao hoặc None,
        "status": {...}, "at": lúc tải}; None nếu chưa tải."""
        row = self.db.execute("SELECT data FROM workout_files WHERE start = ?", (start,)).fetchone()
        return json.loads(zlib.decompress(row[0])) if row else None

    def set_workout_files(self, start: int, data: dict) -> None:
        blob = zlib.compress(json.dumps(data, separators=(",", ":")).encode())
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO workout_files VALUES (?, ?)", (start, blob))
            self.db.execute("INSERT OR REPLACE INTO sync VALUES ('workout_files', ?)", (int(time.time()),))

    def has_workout_files(self) -> set[int]:
        return {r[0] for r in self.db.execute("SELECT start FROM workout_files")}

    def rpe(self, start: int) -> int | None:
        """Cảm nhận sau buổi tập (1-5) người dùng đã chọn; buổi tập gộp lại (giờ bắt đầu lệch tới 3 phút) vẫn tìm thấy."""
        row = self.db.execute("SELECT rpe FROM workout_rpe WHERE start BETWEEN ? AND ? ORDER BY ABS(start - ?) LIMIT 1",
                              (start - 180, start + 180, start)).fetchone()
        return row[0] if row else None

    def set_rpe(self, start: int, value: int | None) -> None:
        with self.db:
            self.db.execute("DELETE FROM workout_rpe WHERE start BETWEEN ? AND ?", (start - 180, start + 180))
            if value:
                self.db.execute("INSERT INTO workout_rpe VALUES (?, ?, ?)", (start, int(value), int(time.time())))
            self.db.execute("INSERT OR REPLACE INTO sync VALUES ('rpe', ?)", (int(time.time()),))

    def workout_minutes(self, w: dict) -> list[list]:
        """Số liệu từng phút của vòng tay quanh giờ tập: [[ts, nhịp tim hoặc None, bước]]."""
        start, end = int(w["start"]), int(w.get("end") or w["start"])
        return [[s[0], s[4] if H.valid_hr(s[4]) else None, s[3]] for s in self.samples(start - start % 60, end + 60)]

    def workout_detail(self, start: int, hrmax: float) -> dict | None:
        """Trang chi tiết một buổi tập (workouts.detail) từ mọi nguồn đã có trên máy."""
        from . import workouts as WK

        w = self.workout(start)
        if w is None:
            return None
        files = self.workout_files(start) or {}
        return WK.detail(w, files.get("samples"), self.track(start), files.get("alt"), self.workout_minutes(w), hrmax,
                         self.rpe(start))

    def _coach_history(self, now: float, hrmax: float, days: int = 60) -> list[dict]:
        """Số liệu các buổi tập gần đây (cũ tới mới) cho gợi ý buổi tập và mô hình thể lực."""
        from . import coach as C
        from . import workouts as WK

        out = []
        for (data,) in self.db.execute("SELECT data FROM workouts WHERE start >= ? AND start <= ? ORDER BY start",
                                       (int(now - days * 86400), int(now))):
            w = json.loads(data)
            files = self.workout_files(w["start"]) or {}
            samples = files.get("samples")
            track = None if samples else self.track(w["start"])
            stats = C.workout_stats({**w, "rpe": self.rpe(w["start"])}, samples,
                                    WK.track_distance(track) if track and len(track) >= 2 else None, files.get("alt"),
                                    self.workout_minutes(w), hrmax)
            out.append(stats)
        return out

    def first(self, name: str) -> int | None:
        """Thời điểm cũ nhất đã lưu của một loại dữ liệu (để lấy bù phần cũ hơn)."""
        query = {
            "activity": "SELECT MIN(ts) FROM activity", "stress_auto": "SELECT MIN(ts) FROM stress WHERE auto = 1",
            "stress_manual": "SELECT MIN(ts) FROM stress WHERE auto = 0", "spo2": "SELECT MIN(ts) FROM spo2",
            "pai": "SELECT MIN(ts) FROM pai", "workouts": "SELECT MIN(start) FROM workouts WHERE data LIKE '%\"band\"%'",
        }.get(name)
        return self.db.execute(query).fetchone()[0] if query else None

    # ------------------------------------------------------------ nhịp tim trực tiếp (theo dõi liên tục)
    def add_live_hr(self, ts: int, total: int, n: int, lo: int, hi: int) -> None:
        """Một phút số đo nhịp tim trực tiếp đã gộp (ts: đầu phút; tổng, số lần đo, thấp nhất, cao nhất); phút đã có thì
        cộng thêm. Vòng tay gửi số đo này qua Bluetooth mỗi vài giây khi bật Theo dõi liên tục, trước khi nó vào dữ liệu
        theo phút được đồng bộ sau."""
        with self.db:
            self.db.execute("INSERT INTO live_hr VALUES (?,?,?,?,?) ON CONFLICT(ts) DO UPDATE SET total = total + excluded.total,"
                            " n = n + excluded.n, lo = MIN(lo, excluded.lo), hi = MAX(hi, excluded.hi)",
                            (ts - ts % 60, total, n, lo, hi))

    def live_hr(self, t0: int, t1: int) -> dict[int, int]:
        """{đầu phút: nhịp tim trung bình} của số đo trực tiếp trong [t0, t1)."""
        return {ts: round(total / n) for ts, total, n in
                self.db.execute("SELECT ts, total, n FROM live_hr WHERE ts >= ? AND ts < ? AND n > 0", (t0, t1))}

    # ------------------------------------------------------------ đọc
    def samples(self, t0: int, t1: int) -> list[tuple]:
        """Các phút vòng tay đã ghi. Phút không có nhịp tim (vòng tay đo theo chu kỳ) mà lúc đó đang theo dõi trực tiếp thì
        lấy trung bình số đo trực tiếp của phút đó: cùng một cảm biến, chỉ là chưa vào dữ liệu theo phút."""
        rows = self.db.execute("SELECT * FROM activity WHERE ts >= ? AND ts < ? ORDER BY ts", (t0, t1)).fetchall()
        live = self.live_hr(t0, t1)
        if live:
            rows = [r if H.valid_hr(r[4]) or r[0] not in live else r[:4] + (live[r[0]],) + r[5:] for r in rows]
        return rows

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
        sessions = H.sleep_sessions(samples, self.kind_before(t0), rem=rem, calib=self.sleep_calibration(),
                                    reference=self.sleep_reference(t0, t1))
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
        every = self.sleep_sessions(w0, t1, rem=rem, samples=samples)
        sessions = [s for s in every if not s["ongoing"]]
        by_ts = {s[0]: s for s in samples}
        nights: dict[str, dict] = {}
        hrs: dict[str, list[int]] = {}
        for sess in sessions:   # mọi giấc kết thúc trong một ngày cộng lại, như biểu đồ giấc ngủ
            day = H.local_date(sess["end"])
            n = nights.setdefault(day, {"date": day, "minutes": 0, "deep": 0, "awake": 0, "start": sess["start"]})
            for k in ("minutes", "deep", "awake"):
                n[k] += sess[k]
            n["start"] = min(n["start"], sess["start"])
            # nhịp tim khi ngủ: chỉ các phút đang ngủ, như mức sẵn sàng (không gồm các lần thức giữa đêm)
            hrs.setdefault(day, []).extend(by_ts[ts][4] for a, b, k in sess["stages"] if k != "awake"
                                           for ts in range(a, b, 60) if ts in by_ts and H.valid_hr(by_ts[ts][4]))
        for day, n in nights.items():
            v = sorted(hrs.get(day, []))
            n["hr"] = v[len(v) // 2] if len(v) >= MIN_NIGHT_HR else None
        steps = [d for d in self.daily_steps() if first.isoformat() <= d["date"] < today and d["worn"] >= 600]
        week0 = H.day_bounds((d0 - dt.timedelta(days=7)).isoformat())[0]
        workouts = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM workouts WHERE start >= ?", (week0,))]
        active = {s[0] for s in samples if s[0] >= week0 and s[3] >= H.BRISK_STEPS}
        busy: set[int] = set()   # trong buổi tập và ngay sau đó: nhịp tim cao là bình thường
        for w in workouts:
            active.update(range(w["start"] - w["start"] % 60, w["end"], 60))
            busy.update(range(w["start"] - w["start"] % 60, int(w.get("end") or w["start"]) + H.REST_AFTER_WORKOUT * 60, 60))
        asleep = {ts for s in every for ts in range(s["start"], s["end"], 60)}
        hr_events = H.rest_hr_events(samples, asleep, busy, since=week0)
        pai = self.db.execute("SELECT total FROM pai ORDER BY ts DESC LIMIT 1").fetchone()
        spo2 = self.db.execute("SELECT ts, value FROM spo2 WHERE ts >= ? ORDER BY ts", (t1 - 30 * 86400,)).fetchall()
        # căng thẳng: mọi số đo của vòng tay, cả đo tay (nhiều người chỉ đo tay, không bật tự đo)
        stress = [r[0] for r in self.db.execute("SELECT value FROM stress WHERE ts >= ?", (week0,))]
        spo2 = [r for r in spo2 if T.assess("spo2", r[1])["usable"]]
        stress = [v for v in stress if T.assess("stress", v)["usable"]]
        last = self.db.execute("SELECT MAX(ts) FROM activity").fetchone()[0]
        body = {"age": age, "height": (profile or {}).get("height"), "weight": (profile or {}).get("weight"),
                "trend": PS.body_trend(self.body_history(), d0)}
        return H.analyze(sorted(nights.values(), key=lambda n: n["date"]), steps, goal,
                         {"total": pai[0]} if pai else None, spo2, stress, len(active), len(workouts), last,
                         sleep_need=I.sleep_need(age), body=body, hr_events=hr_events)

    INSIGHT_DAYS = 60   # ngày dữ liệu dùng cho mức sẵn sàng, nhịp sinh học… (mức nền nhiều tuần)

    def _collect(self, first: dt.date, last: dt.date, profile: dict | None, rem: bool = True) -> dict:
        """Mỗi đêm (giấc dài nhất theo ngày thức dậy) và mỗi ngày (bước, phút vận động theo cường độ, TRIMP, căng thẳng)
        từ first tới last, dựng từ dữ liệu từng phút; cùng các thứ insights cần thêm (mẫu, giấc ngủ, phút tháo vòng...)."""
        from . import insights as I

        t0 = H.day_bounds((first - dt.timedelta(days=1)).isoformat())[0] + 12 * 3600
        _, t1 = H.day_bounds(last.isoformat())
        samples = self.samples(t0, t1)
        by_ts = {s[0]: s for s in samples}
        sessions = self.sleep_sessions(t0, t1, rem=rem, samples=samples)

        # ---- mỗi đêm: giấc dài nhất kết thúc trong ngày (giấc còn đang ngủ chưa phải một đêm)
        by_day: dict[str, list[dict]] = {}
        for sess in sessions:
            day = H.local_date(sess["end"])
            if not sess["ongoing"] and first.isoformat() <= day <= last.isoformat():
                by_day.setdefault(day, []).append(sess)
        nights = []
        for day, finished in sorted(by_day.items()):
            main = max(finished, key=lambda s: s["minutes"])
            night = self._night(main, by_ts, day)
            night["rem_estimated"] = main.get("rem_estimated", False)
            night["naps"] = [(s["end"], s["minutes"]) for s in finished if s is not main]
            nights.append(night)

        age, sex = PS.age_of(profile, last), PS.sex_of(profile)

        # ---- mỗi ngày
        hrmax = PS.max_hr_override((profile or {}).get("max_hr_override")) or I.hr_max(age, sex)
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
        for i in range((last - first).days + 1):
            day = (first + dt.timedelta(days=i)).isoformat()
            d = days.get(day, self._blank_day(day))
            d["stress"] = d["stress_sum"] / d["stress_n"] if d["stress_n"] else None
            d["hr_coverage"] = round(min(1.0, d["hr_minutes"] / d["wear"]), 3) if d["wear"] else 0.0
            day_list.append(d)

        for n in nights:   # tải vận động trong 4 giờ trước khi ngủ (đặc trưng của mô hình nhịp tim khi ngủ)
            n["evening"] = round(sum(load for ts, load in hourly.items() if n["start"] - 4 * 3600 <= ts < n["start"]), 1)
        return {"t0": t0, "t1": t1, "samples": samples, "by_ts": by_ts, "sessions": sessions, "nights": nights,
                "days": day_list, "hourly": hourly, "off_wrist": off_wrist, "workouts": workouts, "hrmax": hrmax}

    def insights(self, date: str | None = None, profile: dict | None = None, rem: bool = True) -> dict:
        """Mức sẵn sàng, trạng thái tinh thần, cường độ vận động và nhịp sinh học tính tới ngày `date` (insights.py).

        Dựng từ dữ liệu từng phút của INSIGHT_DAYS ngày (_collect). Mô hình cá nhân còn học từ lịch sử dài hơn (tới
        HISTORY_DAYS ngày) đã lưu gọn theo ngày trong bảng daily."""
        from . import insights as I

        date = date or dt.date.today().isoformat()
        d0 = dt.date.fromisoformat(date)
        first = d0 - dt.timedelta(days=self.INSIGHT_DAYS - 1)
        w = self._collect(first, d0, profile, rem)
        t0, t1, samples, by_ts, sessions = w["t0"], w["t1"], w["samples"], w["by_ts"], w["sessions"]
        nights, day_list, hourly, off_wrist, workouts, hrmax = (w["nights"], w["days"], w["hourly"], w["off_wrist"],
                                                                 w["workouts"], w["hrmax"])
        data_until = self.db.execute("SELECT MAX(ts) FROM activity WHERE ts < ?", (t1,)).fetchone()[0]
        if data_until:   # ngày đã trọn (đã có dữ liệu của ngày sau): lưu gọn để mô hình cá nhân học lâu dài
            self._store_daily(nights, day_list, H.local_date(data_until))
        self._extend_history(first, profile, rem)
        past_nights, past_days = self._history(first)

        # ---- hồ sơ: tuổi, giới tính (nhịp tim tối đa, nhu cầu ngủ) và nhật ký chu kỳ (nhịp tim nghỉ pha hoàng thể)
        age, sex = PS.age_of(profile, d0), PS.sex_of(profile)
        need = I.sleep_need(age)
        period_days = list(self.journal("period")) if sex == PS.SEX_FEMALE else []
        all_nights = past_nights + nights
        PS.adjust_luteal_hr(all_nights, period_days)

        # ---- chỉ số đều đặn giấc ngủ: 14 ngày gần nhất, chỉ các phút có đeo vòng (vòng tay ghi cả khi tháo ra)
        s0 = H.day_bounds((d0 - dt.timedelta(days=13)).isoformat())[0]
        asleep = {t for sess in sessions for a, b, k in sess["stages"] if k != "awake" for t in range(a, b, 60) if t >= s0}
        sri = I.sleep_regularity(asleep, {ts for ts in by_ts if ts >= s0 and ts not in off_wrist}, s0, t1)

        circ = I.circadian(nights, sri)
        chronotype = circ["chronotype"] if circ else None
        hours = sorted(hourly.items())
        today = dt.date.today().isoformat()

        # ---- mô hình nhịp tim khi ngủ của riêng bạn (models.py): học từ mọi đêm đã lưu (tới HISTORY_DAYS ngày) trừ
        # RECENT_NIGHTS đêm gần nhất; dữ liệu càng dài thì mô hình càng có nhiều đêm để học
        self._night_features(all_nights, past_days + day_list)
        rows = []
        for k, n in enumerate(all_nights):
            base = I.rhr_baseline(all_nights[:k])
            rows.append({"date": n["date"], "x": n["features"],
                         "y": I._hr(n) - base["median"] if n.get("hr") and base else None})
        model = self._personal_model(rows, d0)
        last_k = len(nights) - 1 if nights and (d0 - dt.date.fromisoformat(nights[-1]["date"])).days <= 1 else None
        rhr = I.night_rhr(nights, last_k, model) if last_k is not None else None

        # ---- căng thẳng 72 giờ qua: cả số đo tự động lẫn đo tay (đúng những gì vòng tay hiện cho người dùng)
        as_of = min(time.time(), t1 - 1)
        readings = [r for r in self.db.execute("SELECT ts, value, auto FROM stress WHERE ts > ? AND ts <= ?",
                                               (as_of - I.STRESS_WINDOW, as_of)) if T.assess("stress", r[1])["usable"]]
        stress = I.stress_evidence(readings, as_of, date, day_list)
        risk = R.assess(self._risk_inputs(profile or {}, age, sex, samples, by_ts, sessions, off_wrist, workouts,
                                          nights, day_list, d0, t1, date == today))

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
            "mental": I.mental_state(nights, day_list, circ, need, stress=stress, rhr=rhr, date=date,
                                     partial=date == today),
            "body": I.body_signals(nights, date, model),
            "sleep_plan": I.sleep_plan(nights, date, need, as_of) if date == today else None,
            "data_until": data_until,
            "risk": risk,
            "profile": {"age": None if age is None else int(age), "sex": sex, "hr_max": round(hrmax),
                        "sleep_need": need},
            "cycle": PS.cycle_status(period_days, d0, nights) if sex == PS.SEX_FEMALE else None,
            "ejaculation": (PS.ejaculation_stats(self.journal("ejaculation"), nights, d0)
                            if sex == PS.SEX_MALE else None),
            "intensity": I.activity_intensity([d for d in day_list if d["date"] <= date]),
            "coach": self._coach(date == today, ready, past_days + day_list, all_nights, hrmax, age, sex),
            "circadian": circ,
            "rem_estimated": any(n.get("rem_estimated") for n in nights),
            "sampling": {"load_method": "time_weighted", "hr_hold_seconds": I.HR_HOLD,
                         "load_min_wear_minutes": I.LOAD_MIN_WEAR, "load_min_hr_coverage": I.LOAD_MIN_COVERAGE,
                         "recovery_min_hr_coverage": RECOVERY_MIN_HR_COVERAGE, "recovery_window_seconds": 300},
        }

    # ------------------------------------------------------------ tóm tắt sức khỏe (trends.py)
    def _activity_days(self, t0: int, t1: int, weight: float, stride: float) -> dict[str, dict]:
        """Mỗi ngày trong [t0, t1): bước, năng lượng vận động (ước tính, personal.active_kcal), phút vận động vừa / mạnh
        (nhịp bước >= BRISK_STEPS hoặc trong buổi tập), số phút đeo vòng."""
        days = {}
        for d, steps, run, brisk, wear in self.db.execute(
                "SELECT date(ts, 'unixepoch', 'localtime') AS d, SUM(steps), SUM(CASE WHEN steps >= ? THEN steps ELSE 0 END),"
                " SUM(CASE WHEN steps >= ? THEN 1 ELSE 0 END),"
                " SUM(CASE WHEN (kind & 15) IN (?, ?) AND NOT (hr BETWEEN 30 AND 220) THEN 0 ELSE 1 END)"
                " FROM activity WHERE ts >= ? AND ts < ? GROUP BY d",
                (PS.RUN_CADENCE, H.BRISK_STEPS, *H.OFF_WRIST, t0, t1)):
            days[d] = {"steps": steps or 0, "calories": PS.active_kcal(steps or 0, run or 0, weight, stride),
                       "active": brisk or 0, "wear": wear or 0}
        for (data,) in self.db.execute("SELECT data FROM workouts WHERE start >= ? AND start < ?", (t0, t1)):
            w = json.loads(data)
            end = int(w.get("end") or w["start"])
            d = days.get(H.local_date(w["start"]))
            if d is None or end <= w["start"]:
                continue
            steps, run, brisk = self.db.execute(
                "SELECT COALESCE(SUM(steps), 0), COALESCE(SUM(CASE WHEN steps >= ? THEN steps ELSE 0 END), 0),"
                " COALESCE(SUM(CASE WHEN steps >= ? THEN 1 ELSE 0 END), 0) FROM activity WHERE ts >= ? AND ts < ?",
                (PS.RUN_CADENCE, H.BRISK_STEPS, w["start"], end)).fetchone()
            d["active"] += max(0, (end - w["start"]) // 60 - brisk)
            if w.get("calories"):   # buổi tập có số năng lượng của vòng tay / Mi Fitness: dùng thay phần ước tính
                d["calories"] += max(0.0, w["calories"] - PS.active_kcal(steps, run, weight, stride))
        return days

    def _quarter_curves(self, date: str, weight: float, stride: float) -> dict[str, tuple]:
        """Bước chân, năng lượng vận động cộng dồn theo từng 15 phút của ngày `date` và USUAL_DAYS ngày trước (chỉ ngày
        đeo vòng đủ lâu) cho trends.vs_usual."""
        from . import trends as TR

        d0 = dt.date.fromisoformat(date)
        t0 = H.day_bounds((d0 - dt.timedelta(days=TR.USUAL_DAYS)).isoformat())[0]
        _, t1 = H.day_bounds(date)
        per: dict[str, dict[str, list[float]]] = {}
        for d, q, steps, run in self.db.execute(
                "SELECT date(ts, 'unixepoch', 'localtime') AS d,"
                " CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) * 4"
                " + CAST(strftime('%M', ts, 'unixepoch', 'localtime') AS INTEGER) / 15 AS q,"
                " SUM(steps), SUM(CASE WHEN steps >= ? THEN steps ELSE 0 END) FROM activity"
                " WHERE ts >= ? AND ts < ? GROUP BY d, q", (PS.RUN_CADENCE, t0, t1)):
            day = per.setdefault(d, {"steps": [0.0] * 96, "calories": [0.0] * 96})
            day["steps"][q] += steps or 0
            day["calories"][q] += PS.active_kcal(steps or 0, run or 0, weight, stride)
        full = {d["date"] for d in self.daily_steps() if d["worn"] >= 600}

        def cum(v: list[float]) -> list[float]:
            out, s = [], 0.0
            for x in v:
                s += x
                out.append(s)
            return out

        now = dt.datetime.now()
        upto = now.hour * 4 + now.minute // 15 + 1 if date == now.date().isoformat() else 96
        out = {}
        for key in ("steps", "calories"):
            today = cum(per.get(date, {}).get(key, [0.0] * 96))
            usual = [cum(v[key]) for d, v in per.items() if d != date and d in full]
            out[key] = (today, usual, upto)
        return out

    def trends(self, date: str | None = None, profile: dict | None = None, insights: dict | None = None) -> dict:
        """Tóm tắt sức khỏe kiểu Mi Fitness tới ngày `date` (trends.summary): chỉ số vừa thay đổi rõ (30 ngày, 26 tuần),
        7 ngày qua so với tuần trước, hôm nay so với thường lệ. Giấc ngủ theo ngày thức dậy (giấc dài nhất); bước chân,
        năng lượng, phút vận động chỉ tính ngày đã trọn và đeo vòng >= 10 giờ."""
        from . import insights as I
        from . import trends as TR

        date = date or dt.date.today().isoformat()
        d0 = dt.date.fromisoformat(date)
        sex = PS.sex_of(profile)
        weight = PS.body_weight((profile or {}).get("weight"))
        stride = PS.stride_m((profile or {}).get("height"), sex)
        need = (insights or {}).get("profile", {}).get("sleep_need") or I.sleep_need(PS.age_of(profile, d0))
        first = d0 - dt.timedelta(days=TR.DAYS - 1)
        days = [(first + dt.timedelta(days=i)).isoformat() for i in range(TR.DAYS)]
        _, t1 = H.day_bounds(date)

        # giấc ngủ: giấc dài nhất theo ngày thức dậy
        t0 = H.day_bounds((first - dt.timedelta(days=1)).isoformat())[0] + 12 * 3600
        samples = self.samples(t0, t1)
        by_ts = {s[0]: s for s in samples}
        nights: dict[str, dict] = {}
        for sess in self.sleep_sessions(t0, t1, samples=samples):
            day = H.local_date(sess["end"])
            if not sess["ongoing"] and (day not in nights or sess["minutes"] > nights[day]["minutes"]):
                nights[day] = sess

        def clock(ts: int, around_midnight: bool) -> float:
            t = dt.datetime.fromtimestamp(ts)
            m = t.hour * 60 + t.minute
            return m - 1440 if around_midnight and m >= 720 else m

        def night_hr(sess: dict) -> float | None:
            hrs = sorted(by_ts[t][4] for a, b, k in sess["stages"] if k != "awake" for t in range(a, b, 60)
                         if t in by_ts and H.valid_hr(by_ts[t][4]))
            return hrs[len(hrs) // 2] if len(hrs) >= MIN_NIGHT_HR else None

        def night(day: str, fn):
            s = nights.get(day)
            return fn(s) if s and s["minutes"] >= 180 else None

        daily: dict[str, list] = {
            "sleep": [(d, night(d, lambda s: s["minutes"])) for d in days],
            "bedtime": [(d, night(d, lambda s: clock(s["start"], True))) for d in days],
            "deep": [(d, night(d, lambda s: s["deep"] * 100 / s["minutes"] if s["deep"] else None)) for d in days],
            "sleep_hr": [(d, night(d, night_hr)) for d in days],
        }
        wake = [(d, night(d, lambda s: clock(s["end"], False))) for d in days]

        # vận động: ngày đã trọn, đeo vòng >= 10 giờ
        today = dt.date.today().isoformat()
        a0 = H.day_bounds((d0 - dt.timedelta(days=7 * TR.WEEKS + 7)).isoformat())[0]
        act = self._activity_days(a0, t1, weight, stride)

        def act_val(day: str, key: str):
            d = act.get(day)
            return d[key] if d and d["wear"] >= 600 and day < today else None

        for key in ("steps", "calories", "active"):
            daily[key] = [(d, act_val(d, key)) for d in days]
        stress: dict[str, list[int]] = {}
        for ts, value in self.db.execute("SELECT ts, value FROM stress WHERE auto = 1 AND ts >= ? AND ts < ?",
                                         (H.day_bounds(days[0])[0], t1)):
            if T.assess("stress", value)["usable"]:
                stress.setdefault(H.local_date(ts), []).append(value)
        daily["stress"] = [(d, sum(stress[d]) / len(stress[d]) if len(stress.get(d, [])) >= 12 else None) for d in days]

        # theo tuần (thứ Hai - Chủ nhật), chỉ các tuần đã trọn có >= 4 ngày dữ liệu
        monday = d0 - dt.timedelta(days=d0.weekday())
        weekly: dict[str, list] = {k: [] for k in ("steps", "calories", "active")}
        for w in range(TR.WEEKS, 0, -1):
            start = monday - dt.timedelta(days=7 * w)
            week = [(start + dt.timedelta(days=i)).isoformat() for i in range(7)]
            for key in weekly:
                vals = [v for v in (act_val(d, key) for d in week) if v is not None]
                weekly[key].append((start.isoformat(), sum(vals) / len(vals) if len(vals) >= 4 else None))

        curves = self._quarter_curves(date, weight, stride)
        out = TR.summary(daily, weekly, wake, curves, need)
        out["date"] = date
        return out

    def _coach(self, today: bool, ready: dict | None, days: list[dict], nights: list[dict], hrmax: float,
               age: float | None, sex: str | None) -> dict | None:
        """Gợi ý buổi tập tiếp theo (chỉ cho hôm nay) và ước tính thể lực từ các buổi tập của bạn (coach.py)."""
        from . import coach as C
        from . import insights as I

        if not today:
            return None
        now = time.time()
        base = I.rhr_baseline(nights, adjusted=False)
        return C.suggest(self._coach_history(now, hrmax), ready, days, hrmax, base["median"] if base else None,
                         age, sex, now)

    @staticmethod
    def _last_night(nights: list[dict], chronotype: float | None, need: int) -> dict:
        """Đêm của ngày đang xem: điểm giấc ngủ (cùng cách tính với thành phần "Giấc ngủ đêm qua" của mức sẵn sàng) và
        nhịp tim khi ngủ so với mức nền, có cả khi chưa đủ dữ liệu để tính mức sẵn sàng."""
        from . import insights as I

        night = nights[-1]
        score, notes = I.sleep_score(night, chronotype, need)
        base = I.rhr_baseline(nights[:-1], adjusted=False)   # cùng mức nền với điểm sẵn sàng (trung vị)
        return {"date": night["date"], "score": int(round(score)), "notes": notes, "hr": night.get("hr"),
                "hr_baseline": round(base["median"]) if base else None}

    # ------------------------------------------------------------ lịch sử dài cho mô hình cá nhân (bảng daily)
    def _store_daily(self, nights: list[dict], day_list: list[dict], complete_before: str) -> None:
        """Lưu gọn các ngày đã trọn (trước complete_before): đêm chính kết thúc trong ngày (nếu có) và số liệu của ngày."""
        by_date = {n["date"]: n for n in nights}
        rows = []
        for d in day_list:
            if d["date"] >= complete_before:
                continue
            n = by_date.get(d["date"])
            night = json.dumps({k: n.get(k) for k in NIGHT_KEYS}) if n else None
            rows.append((d["date"], DAILY_VERSION, night, json.dumps({k: d.get(k) for k in DAY_KEYS})))
        if rows:
            with self.db:
                self.db.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?)", rows)

    def _history(self, first: dt.date) -> tuple[list[dict], list[dict]]:
        """Các đêm và ngày đã lưu trước `first` (tối đa HISTORY_DAYS ngày tính tới `first`), cũ tới mới; ngày không có
        dòng nào thì là ngày trống (không đeo vòng), để danh sách ngày liền nhau."""
        since = first - dt.timedelta(days=HISTORY_DAYS - self.INSIGHT_DAYS)
        rows = self.db.execute("SELECT date, night, day FROM daily WHERE version = ? AND date >= ? AND date < ? ORDER BY date",
                               (DAILY_VERSION, since.isoformat(), first.isoformat())).fetchall()
        if not rows:
            return [], []
        nights = [json.loads(n) for _d, n, _day in rows if n]
        stored = {d: json.loads(day) for d, _n, day in rows}
        start = dt.date.fromisoformat(rows[0][0])
        days = []
        for i in range((first - start).days):
            key = (start + dt.timedelta(days=i)).isoformat()
            days.append({**self._blank_day(key), "hr_coverage": 0.0, **stored.get(key, {})})
        return nights, days

    def _extend_history(self, first: dt.date, profile: dict | None, rem: bool) -> None:
        """Lấp tối đa HISTORY_CHUNK ngày chưa lưu trước cửa sổ insights: trước hết khoảng trống ngay trước cửa sổ (ứng
        dụng không mở một thời gian), rồi các ngày cũ hơn, tới ngày có dữ liệu đầu tiên hoặc HISTORY_DAYS ngày."""
        oldest = self.db.execute("SELECT MIN(ts) FROM activity").fetchone()[0]
        if oldest is None:
            return
        floor = max(dt.date.fromisoformat(H.local_date(oldest)), first - dt.timedelta(days=HISTORY_DAYS - self.INSIGHT_DAYS))
        newest = self.db.execute("SELECT MAX(date) FROM daily WHERE version = ? AND date < ?",
                                 (DAILY_VERSION, first.isoformat())).fetchone()[0]
        if newest and dt.date.fromisoformat(newest) < first - dt.timedelta(days=1):
            start = max(floor, dt.date.fromisoformat(newest) + dt.timedelta(days=1))
            end = min(first - dt.timedelta(days=1), start + dt.timedelta(days=HISTORY_CHUNK - 1))
        else:
            have = self.db.execute("SELECT MIN(date) FROM daily WHERE version = ?", (DAILY_VERSION,)).fetchone()[0]
            end = min(dt.date.fromisoformat(have), first) - dt.timedelta(days=1) if have else first - dt.timedelta(days=1)
            start = max(floor, end - dt.timedelta(days=HISTORY_CHUNK - 1))
        if end < start:
            return
        w = self._collect(start, end, profile, rem)
        self._store_daily(w["nights"], w["days"], (end + dt.timedelta(days=1)).isoformat())

    def _personal_model(self, rows: list[dict], d0: dt.date) -> dict:
        """Mô hình nhịp tim khi ngủ (models.rhr_model) học từ mọi đêm trừ RECENT_NIGHTS đêm gần nhất, kèm đường học
        (models.learning_curve: sai số khi chỉ có 1 tuần, 1 tháng, 3, 6 tháng, 1 năm dữ liệu). Chỉ học lại khi dữ liệu
        học đổi (thường là mỗi ngày một đêm mới)."""
        from . import insights as I

        recent = [(d0 - dt.date.fromisoformat(r["date"])).days < I.RECENT_NIGHTS for r in rows]
        train = [r for r, new in zip(rows, recent) if not new]
        targets = [r for r, new in zip(rows, recent) if new]
        key = tuple((r["date"], None if r["y"] is None else round(r["y"], 3), tuple(sorted(r["x"].items())))
                    for r in rows) + (tuple(new for new in recent),)
        if self._model_cache and self._model_cache[0] == key:
            return self._model_cache[1]
        model = M.rhr_model(train, targets)
        model["curve"] = M.learning_curve(train)
        dated = [r["date"] for r in train if r["y"] is not None]
        model["since"] = dated[0] if dated else None
        self._model_cache = (key, model)
        return model

    @staticmethod
    def _risk_inputs(profile: dict, age: float | None, sex: str | None, samples: list[tuple], by_ts: dict,
                     sessions: list[dict], off_wrist: set[int], workouts: list[dict], nights: list[dict],
                     day_list: list[dict], d0: dt.date, t1: int, partial: bool) -> dict:
        """Đầu vào cho risk.assess: hồ sơ, và từ vòng tay (None khi chưa đủ dữ liệu):
        - pulse: nhịp tim lúc ngồi yên ban ngày RISK_DAYS ngày qua (lúc thức, đeo vòng, tối đa REST_STEPS bước trong phút
          đó và REST_STILL phút trước, không trong buổi tập hay ngay sau đó), gần với mạch đo khi ngồi nghỉ của NHANES.
          Lấy trung vị từng khoảng 10 phút rồi trung vị các khoảng: một lúc theo dõi trực tiếp bên máy tính (mỗi phút
          một số đo) chỉ được tính theo thời gian của nó, không lấn át những giờ vòng tay đo 10-30 phút một lần;
        - sleep: số giờ trung bình của giấc chính (cả lúc thức giữa giấc) trong RISK_DAYS ngày, cần 3 đêm;
        - active: số ngày trung bình mỗi tuần có từ 10 phút vận động vừa/mạnh, trong 4 tuần đã trọn (các ngày đeo vòng
          từ 10 giờ; cần 3 ngày, quy về 7 ngày);
        - days: số ngày dữ liệu thật sự có trong khoảng đó."""
        since = t1 - RISK_DAYS * 86400
        asleep = {ts for s in sessions if s["end"] > since for ts in range(s["start"], s["end"], 60)}
        busy: set[int] = set()
        for w in workouts:
            busy.update(range(w["start"] - w["start"] % 60, int(w.get("end") or w["start"]) + H.REST_AFTER_WORKOUT * 60, 60))
        rest: dict[int, list[int]] = {}   # khoảng 10 phút -> các số đo lúc ngồi yên
        for s in samples:
            ts = s[0]
            if ts < since or not H.valid_hr(s[4]) or ts in asleep or ts in busy or ts in off_wrist:
                continue
            if sum(by_ts[t][3] for t in range(ts - 60 * H.REST_STILL, ts + 60, 60) if t in by_ts) > H.REST_STEPS:
                continue
            if RISK_HOURS[0] <= dt.datetime.fromtimestamp(ts).hour < RISK_HOURS[1]:
                rest.setdefault(ts // 600, []).append(s[4])
        recent = [n for n in nights if (d0 - dt.date.fromisoformat(n["date"])).days < RISK_DAYS]
        week = [d for d in (day_list[-29:-1] if partial else day_list[-28:]) if d["wear"] >= 600]
        active = sum(1 for d in week if d["moderate"] + d["vigorous"] >= 10)
        return {"age": age, "sex": sex, "height": profile.get("height"), "weight": profile.get("weight"),
                "pulse": M.median([M.median(v) for v in rest.values()]) if len(rest) >= RISK_MIN_REST else None,
                "sleep": sum(n["minutes"] + n.get("awake", 0) for n in recent) / 60 / len(recent) if len(recent) >= 3 else None,
                "active": round(active * 7 / len(week)) if len(week) >= 3 else None,
                "days": sum(1 for d in day_list[-RISK_DAYS:] if d["wear"] >= 600)}

    @staticmethod
    def _night_features(nights: list[dict], day_list: list[dict]) -> None:
        """Đặt n["features"] cho mô hình nhịp tim khi ngủ (models.rhr_model); 0 hoặc thiếu = như thường lệ.

        load: TRIMP hôm trước trừ trung bình 28 ngày đủ dữ liệu tải trước đó (/ 100); evening: TRIMP trong 4 giờ trước
        lúc ngủ (/ 100); late: giờ ngủ muộn hơn trung vị 14 đêm trước (giờ); short: ngủ ngắn hơn trung vị đó (giờ)."""
        from . import insights as I

        index = {d["date"]: i for i, d in enumerate(day_list)}
        midnight = {n["date"]: H.day_bounds(n["date"])[0] for n in nights}
        for k, n in enumerate(nights):
            x: dict[str, float] = {}
            i = index.get((dt.date.fromisoformat(n["date"]) - dt.timedelta(days=1)).isoformat())
            if i is not None and I._load_day(day_list[i]):
                month = [d["trimp"] for d in day_list[max(0, i - 28):i] if I._load_day(d)]
                if len(month) >= I.MIN_BASELINE:
                    x["load"] = (day_list[i]["trimp"] - sum(month) / len(month)) / 100
            x["evening"] = (n.get("evening") or 0) / 100
            prior = nights[max(0, k - 14):k]
            if len(prior) >= 5:
                usual_start = M.median([(m["start"] - midnight[m["date"]]) / 60 for m in prior])
                x["late"] = ((n["start"] - midnight[n["date"]]) / 60 - usual_start) / 60
                x["short"] = (M.median([m["minutes"] for m in prior]) - n["minutes"]) / 60
            n["features"] = x

    @staticmethod
    def _blank_day(day: str) -> dict:
        return {"date": day, "steps": 0, "wear": 0, "light": 0, "moderate": 0, "vigorous": 0, "trimp": 0,
                "hr_minutes": 0.0, "stress_sum": 0, "stress_n": 0, "stress_high": 0}

    @staticmethod
    def _night(sess: dict, by_ts: dict, day: str) -> dict:
        """Tóm tắt một đêm: thời lượng, các giai đoạn, nhịp tim khi ngủ, lúc nhịp tim thấp nhất, giờ giữa giấc."""
        asleep = [t for a, b, k in sess["stages"] if k != "awake" for t in range(a, b, 60)]
        pts = [(t, by_ts[t][4]) for t in asleep if t in by_ts and H.valid_hr(by_ts[t][4])]
        hrs = sorted(hr for _, hr in pts)
        # nhịp tim khi ngủ chỉ tính khi có đủ số đo (đo mỗi 30 phút vẫn có ~14 số đo một đêm 7 giờ)
        night = {"date": day, "minutes": sess["minutes"], "deep": sess["deep"], "rem": sess["rem"],
                 "awake": sess["awake"], "start": sess["start"], "end": sess["end"],
                 "hr": hrs[len(hrs) // 2] if len(hrs) >= MIN_NIGHT_HR else None, "hr_n": len(hrs), "hr_low_at": None,
                 "mid": ((sess["start"] + sess["end"]) / 2 - H.day_bounds(day)[0]) / 60}
        if len(pts) >= 30 and len(pts) / len(asleep) >= RECOVERY_MIN_HR_COVERAGE:
            # chỉ số hồi phục (như Oura): lúc trung bình 5 phút của nhịp tim xuống thấp nhất, tính theo phần đêm đã qua
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
        # số đo trực tiếp của các phút vòng tay chưa đồng bộ (đang theo dõi liên tục): hiện ngay, đánh dấu 1 ở cuối
        have = {s[0] for s in day}
        live = [[ts, v, 1] for ts, v in sorted(self.live_hr(t0, t1).items()) if ts not in have]
        hr = sorted(hr + live)
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
                "hr_live": len(live),
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
