"""Giải mã dữ liệu sức khỏe lấy từ vòng tay và tính các con số để hiển thị.

Hàm thuần (không đụng Bluetooth hay tệp), dễ kiểm thử. Định dạng theo Gadgetbridge:
FetchActivityOperation, FetchPaiOperation, FetchSpo2NormalOperation, FetchStress*Operation,
HuamiActivitySummaryParser và HuamiExtendedSampleProvider (cách nhận ra giấc ngủ).
"""

from __future__ import annotations

import datetime as dt
import struct

SAMPLE_SIZE = 8          # Mi Band 6: mỗi phút 8 byte
KIND_SLEEP = 120         # vòng tay đánh dấu phút đang ngủ
KIND_NOT_WORN = 115
KIND_CHARGING = 118
SLEEP_GAP_MINUTES = 45   # thức giấc ngắn hơn ngần này vẫn tính là cùng một giấc
MIN_SLEEP_MINUTES = 20   # giấc ngắn hơn ngần này bỏ qua (thường là ngồi yên)


def _ts(t: dt.datetime) -> int:
    return int(t.timestamp())


def valid_hr(bpm: int) -> bool:
    return 30 <= bpm <= 220   # 0 và 255: phút đó không đo


# ---------------------------------------------------------------- giải mã


def decode_activity(start: dt.datetime, data: bytes) -> list[tuple]:
    """Mỗi phút một mẫu: (ts, loại, cường độ, bước, nhịp tim, ngủ, ngủ sâu, REM)."""
    if len(data) % SAMPLE_SIZE:
        raise ValueError(f"độ dài dữ liệu hoạt động {len(data)} không chia hết cho {SAMPLE_SIZE}")
    base = _ts(start)
    out = []
    for i in range(0, len(data), SAMPLE_SIZE):
        kind, intensity, steps, hr, _unknown, sleep, deep, rem = data[i:i + SAMPLE_SIZE]
        out.append((base + 60 * (i // SAMPLE_SIZE), kind, intensity, steps, hr, sleep, deep, rem))
    return out


def decode_pai(data: bytes) -> list[dict]:
    """Bản ghi PAI 102 byte: điểm PAI hôm nay, tổng 7 ngày, số phút ở từng mức nhịp tim."""
    if len(data) % 102:
        raise ValueError(f"độ dài dữ liệu PAI {len(data)} không chia hết cho 102")
    out = []
    for off in range(0, len(data), 102):
        rec = data[off:off + 102]
        kind = rec[0]
        if kind == 0:   # dữ liệu cũ trước khi khôi phục cài đặt gốc
            continue
        if kind != 5:
            raise ValueError(f"loại PAI lạ: {kind}")
        ts = int.from_bytes(rec[1:5], "little")
        tz = rec[5] - 256 if rec[5] > 127 else rec[5]
        low, moderate, high = struct.unpack_from("<fff", rec, 37)
        t_low, t_moderate, t_high = struct.unpack_from("<hhh", rec, 49)
        today, total = struct.unpack_from("<ff", rec, 55)
        out.append({"ts": ts, "utc_offset": tz * 900, "low": low, "moderate": moderate, "high": high,
                    "time_low": t_low, "time_moderate": t_moderate, "time_high": t_high,
                    "today": today, "total": total})
    return out


def decode_stress_auto(start: dt.datetime, data: bytes) -> list[tuple[int, int]]:
    """Mỗi phút một byte (0xff: không đo): [(ts, mức căng thẳng 0-100)]."""
    base = _ts(start)
    return [(base + 60 * i, b) for i, b in enumerate(data) if b != 0xFF]


def decode_stress_manual(data: bytes) -> list[tuple[int, int]]:
    """Lần đo tay 5 byte: thời điểm (4) + mức căng thẳng."""
    if len(data) % 5:
        raise ValueError(f"độ dài dữ liệu căng thẳng {len(data)} không chia hết cho 5")
    return [(int.from_bytes(data[i:i + 4], "little"), data[i + 4]) for i in range(0, len(data), 5)]


def decode_spo2(data: bytes) -> list[tuple[int, int, bool]]:
    """Phiên bản (1 byte, =2) rồi mỗi lần đo 65 byte: [(ts, SpO2 %, đo tự động?)]."""
    if not data:
        return []
    if (len(data) - 1) % 65:
        raise ValueError(f"độ dài dữ liệu SpO2 {len(data)} không hợp lệ")
    if data[0] != 2:
        raise ValueError(f"phiên bản dữ liệu SpO2 lạ: {data[0]}")
    out = []
    for off in range(1, len(data), 65):
        ts = int.from_bytes(data[off:off + 4], "little")
        raw = data[off + 4]
        auto = raw > 127
        out.append((ts, raw - 128 if auto else raw, auto))
    return out


def decode_sport_summary(data: bytes, start: dt.datetime) -> dict:
    """Tóm tắt một buổi tập. `start` lấy từ phản hồi lấy dữ liệu (như Gadgetbridge, đáng tin hơn
    thời điểm ghi trong bản ghi khi có giờ mùa hè)."""
    version, kind, t0, t1 = struct.unpack_from("<hHII", data, 0)
    pos = 12 + 12   # bỏ kinh độ, vĩ độ, độ cao gốc
    out = {"version": version, "type": kind, "start": _ts(start), "end": _ts(start) + max(0, t1 - t0)}
    try:
        if version >= 512:
            if version == 519:
                pos = 0x8C
            elif version == 516:
                pos += 4
            steps, active = struct.unpack_from("<ii", data, pos)
            pos += 8 + 16
            calories, distance = struct.unpack_from("<ff", data, pos)
            pos += 8 + 5 * 4 + 3 * 4 + 3 * 4 + 3 * 4 + 3 * 4 + 4 + 4
            avg_hr, _pace, _stride, max_hr = struct.unpack_from("<hhhh", data, pos)
        else:
            (distance,) = struct.unpack_from("<f", data, pos)
            pos += 5 * 4 + 4 * 4
            steps, active, calories = struct.unpack_from("<iif", data, pos)
            pos += 12 + 4 * 4 + 4 + 28
            (avg_hr,) = struct.unpack_from("<h", data, pos)
            max_hr = 0
        out.update(steps=max(0, steps), active_seconds=max(0, active), calories=round(max(0.0, calories)),
                   distance=round(max(0.0, distance)), avg_hr=avg_hr if valid_hr(avg_hr) else None,
                   max_hr=max_hr if valid_hr(max_hr) else None)
    except struct.error:
        pass   # bản ghi ngắn hơn dự kiến: vẫn giữ loại và thời gian
    return out


# ---------------------------------------------------------------- giấc ngủ


def sleep_stage(sample: tuple) -> str | None:
    """'deep' | 'rem' | 'light' cho phút đang ngủ, None nếu thức (ngưỡng như Gadgetbridge)."""
    _ts_, kind, _i, _s, _hr, _sleep, deep, rem = sample
    if kind != KIND_SLEEP:
        return None
    if rem & 127 > 55:
        return "rem"
    if deep & 127 > 42:
        return "deep"
    return "light"


def sleep_sessions(samples: list[tuple]) -> list[dict]:
    """Gom các phút ngủ liền nhau thành từng giấc; khoảng thức ngắn ở giữa tính là 'thức'."""
    sessions: list[dict] = []
    cur: dict | None = None
    last_sleep_ts = None
    for s in samples:
        stage = sleep_stage(s)
        if stage is None:
            continue
        ts = s[0]
        if cur is None or ts - last_sleep_ts > SLEEP_GAP_MINUTES * 60:
            cur = {"start": ts, "end": ts + 60, "deep": 0, "light": 0, "rem": 0, "awake": 0, "stages": []}
            sessions.append(cur)
        elif ts - last_sleep_ts > 60:
            gap = (ts - last_sleep_ts) // 60 - 1
            cur["awake"] += gap
            cur["stages"].append([last_sleep_ts + 60, ts, "awake"])
        cur[stage] += 1
        cur["end"] = ts + 60
        stages = cur["stages"]
        if stages and stages[-1][2] == stage and stages[-1][1] == ts:
            stages[-1][1] = ts + 60
        else:
            stages.append([ts, ts + 60, stage])
        last_sleep_ts = ts
    out = []
    for sess in sessions:
        sess["minutes"] = sess["deep"] + sess["light"] + sess["rem"]
        if sess["minutes"] >= MIN_SLEEP_MINUTES:
            out.append(sess)
    return out


def local_date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).date().isoformat()


def day_bounds(date: str) -> tuple[int, int]:
    d = dt.date.fromisoformat(date)
    start = dt.datetime.combine(d, dt.time()).astimezone()
    end = dt.datetime.combine(d + dt.timedelta(days=1), dt.time()).astimezone()
    return int(start.timestamp()), int(end.timestamp())
