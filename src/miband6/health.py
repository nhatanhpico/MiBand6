"""Giải mã dữ liệu sức khỏe lấy từ vòng tay và tính các con số để hiển thị.

Hàm thuần (không đụng Bluetooth hay tệp), dễ kiểm thử. Định dạng theo Gadgetbridge:
FetchActivityOperation, FetchPaiOperation, FetchSpo2NormalOperation, FetchStress*Operation,
HuamiActivitySummaryParser và HuamiExtendedSampleProvider (cách nhận ra giấc ngủ).
"""

from __future__ import annotations

import datetime as dt
import struct

SAMPLE_SIZE = 8          # Mi Band 6: mỗi phút 8 byte

# Loại hoạt động: chỉ 4 bit thấp của byte đầu có nghĩa (Gadgetbridge: MiBand2SampleProvider, HuamiConst).
# Vòng tay chỉ ghi khi trạng thái đổi; các phút giữa mang 0 (không đổi) hoặc 10 (bỏ qua).
KIND_NO_CHANGE = 0
KIND_ACTIVITY = 1
KIND_RUNNING = 2
KIND_NOT_WORN = 3
KIND_BIKE = 4
KIND_CHARGING = 6
KIND_LIGHT_SLEEP = 9
KIND_IGNORE = 10
KIND_DEEP_SLEEP = 11
KIND_WAKE_UP = 12

SLEEP_GAP_MINUTES = 45   # thức giấc ngắn hơn ngần này vẫn tính là cùng một giấc
MIN_SLEEP_MINUTES = 20   # giấc ngắn hơn ngần này bỏ qua (thường là ngồi yên)
# Vòng tay ghi mốc ngủ / thức trễ chừng 10 phút; byte "ngủ" (byte thứ 6) cho thấy lúc thật sự ngủ / dậy:
ONSET_LEVEL = 10         # phút trước mốc ngủ có byte "ngủ" từ ngần này trở lên: đã ngủ
WAKE_LEVEL = 30          # phút cuối giấc có byte "ngủ" dưới ngần này: đã dậy
EDGE_MINUTES = 30        # chỉ chỉnh mỗi đầu giấc tối đa ngần này phút


def _ts(t: dt.datetime) -> int:
    return int(t.timestamp())


def valid_hr(bpm: int) -> bool:
    return 30 <= bpm <= 220   # 0 và 255: phút đó không đo


OFF_WRIST = (KIND_NOT_WORN, KIND_CHARGING)


def worn(sample: tuple, kind: int | None) -> bool:
    """Phút có đeo vòng: loại hoạt động thật (effective_kinds) không phải "không đeo" / "đang sạc", hoặc có nhịp tim
    hợp lệ (vòng tay chỉ đo được nhịp tim khi đang đeo).

    Vòng tay ghi một bản ghi cho mọi phút, kể cả khi tháo ra: đếm bản ghi không cho biết có đeo hay không."""
    return valid_hr(sample[4]) or kind not in OFF_WRIST


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


def workout_from_cloud(v: dict) -> dict | None:
    """Một buổi tập từ tài khoản Mi Fitness (trường "value" đã giải mã) theo dạng của decode_sport_summary.

    Tên trường theo mô tả của dự án mifit; mã loại bài tập (sport_type) của Mi Fitness khác mã của vòng tay."""
    def num(key: str) -> int | None:
        try:
            x = int(float(v.get(key) or 0))
        except (TypeError, ValueError):
            return None
        return x if x > 0 else None

    start = num("start_time")
    if not start:
        return None
    duration = num("duration")
    tz = v.get("timezone")
    return {"source": "mifitness", "mf_type": num("sport_type"), "start": start,
            # để tải tệp lộ trình GPS sau này (chạy, đạp xe ngoài trời): thời điểm báo cáo, múi giờ, kiểu dữ liệu, nguồn
            "mf_time": num("time"), "mf_tz": tz if isinstance(tz, int) else None, "mf_proto": num("proto_type"),
            "mf_sid": v.get("_sid"), "mf_region": v.get("_region"),
            "end": num("end_time") or start + (duration or 0), "active_seconds": duration,
            "distance": num("distance"), "calories": num("calories"), "steps": num("steps"),
            "avg_hr": num("avg_hrm") if valid_hr(num("avg_hrm") or 0) else None,
            "max_hr": num("max_hrm") if valid_hr(num("max_hrm") or 0) else None}


GPS_PROTOS = (22, 23)    # kiểu dữ liệu buổi tập của Mi Fitness có lộ trình GPS: chạy, đạp xe ngoài trời


def has_gps(w: dict) -> bool:
    return w.get("mf_proto") in GPS_PROTOS and bool(w.get("mf_sid")) and bool(w.get("mf_time"))


def route_kind(w: dict) -> str:
    """Loại lộ trình để tô màu trên bản đồ: "run", "walk" hoặc "ride"."""
    kind, mf = w.get("type"), w.get("mf_type")
    if w.get("mf_proto") == 23 or kind in (4, 8) or mf == 6:
        return "ride"
    if kind in (3, 10, 15) or (kind is None and mf in (2, 3)):
        return "walk"
    return "run"


def simplify_track(points: list, min_step: float = 8e-5, max_points: int = 600) -> list:
    """[[ts, lat, lon], …] -> [[lat, lon], …] gọn cho bản đồ tổng (bỏ điểm cách điểm trước dưới ~9 m)."""
    out: list = []
    for _ts, lat, lon in points:
        if not out or abs(lat - out[-1][0]) + abs(lon - out[-1][1]) >= min_step:
            out.append([lat, lon])
    if points and out[-1] != [points[-1][1], points[-1][2]]:
        out.append([points[-1][1], points[-1][2]])
    if len(out) > max_points:
        step = len(out) / max_points
        out = [out[int(i * step)] for i in range(max_points)] + [out[-1]]
    return out


GPS_POINT_SIZE = {1: 12, 2: 18, 3: 26}   # byte mỗi điểm theo phiên bản tệp lộ trình


def _gps_ok(lat: float, lon: float) -> bool:
    return lat == lat and lon == lon and abs(lat) <= 90 and abs(lon) <= 180 and (lat, lon) != (0.0, 0.0)


def _gps_points(plain: bytes, start: int, size: int) -> list[list]:
    """Đọc các điểm cỡ `size` byte, mỗi điểm mở đầu bằng thời điểm (uint32), kinh độ, vĩ độ (float32)."""
    out = []
    for pos in range(start, len(plain) - size + 1, size):
        ts, lon, lat = struct.unpack_from("<Iff", plain, pos)
        if _gps_ok(lat, lon):
            out.append([ts, round(lat, 6), round(lon, 6)])
    return out


def _gps_layout_score(plain: bytes, start: int, size: int, header_ts: int) -> float:
    """Mức hợp lý khi coi mỗi điểm dài `size` byte: thời điểm tăng dần từng chút, tọa độ liền mạch."""
    body = len(plain) - start
    if size < 12 or body < size or body % size:
        return 0.0
    n = min(body // size, 300)
    pts = [struct.unpack_from("<Iff", plain, start + i * size) for i in range(n)]
    good_pos = sum(1 for _t, lon, lat in pts if _gps_ok(lat, lon))
    steps = [b[0] - a[0] for a, b in zip(pts, pts[1:])]
    good_steps = sum(1 for d in steps if 0 <= d <= 120)
    jumps = sum(1 for a, b in zip(pts, pts[1:]) if _gps_ok(a[2], a[1]) and _gps_ok(b[2], b[1])
                and abs(a[2] - b[2]) < 0.01 and abs(a[1] - b[1]) < 0.01)
    near = 1.0 if pts and abs(pts[0][0] - header_ts) < 3 * 86400 else 0.5
    if n == 1:
        return near * good_pos
    return near * (good_pos / n + good_steps / (n - 1) + jumps / (n - 1)) / 3


def decode_gps_file(plain: bytes) -> list[list]:
    """Tệp lộ trình GPS của Mi Fitness (đã giải mã): [[ts, vĩ độ, kinh độ], ...].

    Tiêu đề 8 byte (thời điểm, múi giờ, phiên bản, kiểu dữ liệu, chế độ lưu), 1 byte cờ hợp lệ, rồi các
    điểm cỡ cố định mở đầu bằng thời điểm (uint32), kinh độ, vĩ độ (float32). Phiên bản 1-2 theo bố cục mô tả
    trong dự án mifit (phiên bản 2 thêm độ chính xác float32 và một uint16). Phiên bản 3 (Mi Fitness 2026,
    kiểm tra trên tệp thật) thêm độ cao float32 và một float32 nữa (HDOP?), mỗi điểm 26 byte. Phiên bản mới hơn
    nữa: cỡ mỗi điểm được dò từ chính dữ liệu (thời điểm tăng dần, tọa độ liền mạch). ValueError nếu không đọc
    được."""
    if len(plain) < 8:
        raise ValueError("tệp GPS quá ngắn")
    header_ts, _tz, version, _proto, mode = struct.unpack_from("<IbBBB", plain)
    if mode != 0:
        raise ValueError(f"tệp GPS được nén hoặc mã hóa thêm (chế độ {mode})")
    if version in GPS_POINT_SIZE:
        flags = plain[8]
        if not (flags & 0x80 and flags & 0x40 and flags & 0x20):   # thời điểm, kinh độ, vĩ độ không hợp lệ
            return []
        return _gps_points(plain, 9, GPS_POINT_SIZE[version])
    best = (0.0, 0, 0)
    for flags_len in (1, 2, 3, 4):
        for size in range(18, 65, 2):
            score = _gps_layout_score(plain, 8 + flags_len, size, header_ts)
            if score > best[0]:
                best = (score, flags_len, size)
    if best[0] < 0.9:
        raise ValueError(f"chưa đọc được tệp GPS phiên bản {version} ({len(plain)} byte)")
    return _gps_points(plain, 8 + best[1], best[2])


# ---------------------------------------------------------------- giấc ngủ


def effective_kinds(samples: list[tuple], previous: int | None = None) -> list[int | None]:
    """Loại hoạt động thật của từng phút: 4 bit thấp; phút "không đổi"/"bỏ qua" giữ loại của phút trước."""
    out: list[int | None] = []
    last = previous
    for s in samples:
        k = s[1] & 0x0F
        if k not in (KIND_NO_CHANGE, KIND_IGNORE):
            last = k
        out.append(last)
    return out


def sleep_stage(sample: tuple, kind: int | None) -> str | None:
    """'deep' | 'light' | 'rem' cho phút đang ngủ (theo loại hoạt động đã tính), None nếu thức."""
    if kind not in (KIND_LIGHT_SLEEP, KIND_DEEP_SLEEP):
        return None
    if sample[7] & 127 > 55:   # vòng tay nào ghi REM thì dùng (Mi Band 6 thường để 0)
        return "rem"
    return "deep" if kind == KIND_DEEP_SLEEP else "light"


def sleep_sessions(samples: list[tuple], previous: int | None = None, rem: bool = False) -> list[dict]:
    """Gom các phút ngủ thành từng giấc; khoảng thức ngắn ở giữa tính là 'thức'.

    samples liền nhau theo phút (ts tăng dần); previous: loại hoạt động trước mẫu đầu tiên.
    rem: ước tính REM từ nhịp tim (estimate_rem) cho giấc vòng tay không ghi REM."""
    kinds = effective_kinds(samples, previous)
    stages = [sleep_stage(s, k) for s, k in zip(samples, kinds)]

    # chỉnh hai đầu theo byte "ngủ": lùi lúc bắt đầu, cắt phần cuối đã tỉnh (vòng tay ghi mốc trễ)
    i = 0
    while i < len(samples):
        if stages[i] is None or (i and stages[i - 1] is not None):
            i += 1
            continue
        j = i   # i: phút ngủ đầu tiên của một đoạn
        while i - j < EDGE_MINUTES and j > 0 and stages[j - 1] is None \
                and samples[j - 1][0] == samples[j][0] - 60 and samples[j - 1][5] >= ONSET_LEVEL:
            j -= 1
        for k in range(j, i):
            stages[k] = "light"
        i += 1
    for i in range(len(samples) - 1, -1, -1):
        if stages[i] is None or (i + 1 < len(samples) and stages[i + 1] is not None):
            continue
        j = i   # i: phút ngủ cuối cùng của một đoạn; j lùi về đầu đoạn
        while j > 0 and stages[j - 1] is not None:
            j -= 1
        levels = sorted(samples[k][5] for k in range(j, i + 1))
        if levels[len(levels) // 2] < WAKE_LEVEL:
            continue   # vòng tay không ghi byte "ngủ" cho giấc này: giữ nguyên mốc
        k = i
        while i - k < EDGE_MINUTES and stages[k] is not None and samples[k][5] < WAKE_LEVEL:
            stages[k] = None
            k -= 1
        if k < i and k > j:
            stages[k] = None   # phút chuyển tiếp (byte "ngủ" đang tụt) tính là đã dậy, như vòng tay hiển thị

    sessions: list[dict] = []
    cur: dict | None = None
    last_ts = None
    for s, stage in zip(samples, stages):
        if stage is None:
            continue
        ts = s[0]
        if cur is None or ts - last_ts > SLEEP_GAP_MINUTES * 60:
            cur = {"start": ts, "end": ts + 60, "deep": 0, "light": 0, "rem": 0, "awake": 0, "stages": []}
            sessions.append(cur)
        elif ts - last_ts > 60:
            cur["awake"] += (ts - last_ts) // 60 - 1
            cur["stages"].append([last_ts + 60, ts, "awake"])
        cur[stage] += 1
        cur["end"] = ts + 60
        st = cur["stages"]
        if st and st[-1][2] == stage and st[-1][1] == ts:
            st[-1][1] = ts + 60
        else:
            st.append([ts, ts + 60, stage])
        last_ts = ts
    out = []
    by_ts = {s[0]: s for s in samples} if rem else {}
    for sess in sessions:
        sess["minutes"] = sess["deep"] + sess["light"] + sess["rem"]
        if sess["minutes"] >= MIN_SLEEP_MINUTES:
            if rem and not sess["rem"]:
                estimate_rem(sess, by_ts)
            out.append(sess)
    return out


# ---------------------------------------------------------------- ước tính REM từ nhịp tim
# Mi Band 6 không ghi REM (byte REM luôn 0) và Mi Fitness cũng không tính REM cho vòng này (REM = 0 mọi đêm).
# Vòng tay chỉ phân biệt ngủ sâu / ngủ nông theo cử động; REM nằm lẫn trong "ngủ nông". Khi ngủ REM, cơ thể gần
# như bất động nhưng nhịp tim tăng so với nền NREM và dao động nhiều hơn (Somers 1993; Walch 2019). Thuật toán:
#   1. chỉ xét giấc >= 3 giờ có nhịp tim ở >= 80% số phút (bật "Hỗ trợ giấc ngủ" để vòng tay đo mỗi phút);
#   2. nền NREM = phân vị 30% của nhịp tim (trung vị 3 phút) trong cửa sổ 61 phút quanh mỗi phút;
#   3. phút "ngủ nông" ít cử động, sau ít nhất REM_LATENCY phút từ lúc ngủ, có nhịp tim cao hơn nền REM_ELEVATION nhịp
#      (hoặc dao động trong 9 phút >= REM_VOLATILITY lần trung vị của đêm và cao hơn nền nửa mức đó) là ứng viên REM;
#   4. nối các đoạn cách nhau <= REM_MERGE phút (khoảng giữa toàn ngủ nông), bỏ đoạn < REM_MIN phút;
#   5. REM quá REM_MAX_SHARE thời gian ngủ thì tăng dần ngưỡng (người lớn khỏe thường 20-25% REM).
REM_MIN_SLEEP = 180
REM_MIN_COVERAGE = 0.8
REM_LATENCY = 60
REM_ELEVATION = 4.0
REM_VOLATILITY = 1.6
REM_MAX_INTENSITY = 25
REM_MERGE = 10
REM_MIN = 6
REM_MAX_SHARE = 0.30


def _rolling(values: list, half: int, fn) -> list:
    out = []
    for i in range(len(values)):
        w = [v for v in values[max(0, i - half):i + half + 1] if v is not None]
        out.append(fn(w) if w else None)
    return out


def _median(w: list) -> float:
    w = sorted(w)
    n = len(w)
    return w[n // 2] if n % 2 else (w[n // 2 - 1] + w[n // 2]) / 2


def _pstdev(w: list) -> float:
    if len(w) < 3:
        return 0.0
    m = sum(w) / len(w)
    return (sum((v - m) ** 2 for v in w) / len(w)) ** 0.5


def estimate_rem(sess: dict, by_ts: dict) -> bool:
    """Tách REM khỏi "ngủ nông" của một giấc theo nhịp tim (xem chú thích ở trên). Sửa sess tại chỗ:
    stages, light, rem, và đặt sess["rem_estimated"] = True. Trả False nếu không đủ dữ liệu."""
    if sess["minutes"] < REM_MIN_SLEEP:
        return False
    mins = list(range(sess["start"], sess["end"], 60))
    label = {}
    for a, b, k in sess["stages"]:
        for t in range(a, b, 60):
            label[t] = k
    raw = [by_ts[t][4] if t in by_ts and valid_hr(by_ts[t][4]) else None for t in mins]
    if sum(v is not None for v in raw) < REM_MIN_COVERAGE * len(raw):
        return False
    hr = raw[:]   # nối chỗ trống ngắn (<= 5 phút) bằng nội suy tuyến tính
    i = 0
    while i < len(hr):
        if hr[i] is not None:
            i += 1
            continue
        j = i
        while j < len(hr) and hr[j] is None:
            j += 1
        if i > 0 and j < len(hr) and j - i <= 5:
            for k in range(i, j):
                hr[k] = hr[i - 1] + (hr[j] - hr[i - 1]) * (k - i + 1) / (j - i + 1)
        i = j
    smooth = _rolling(hr, 1, _median)
    floor = _rolling(smooth, 30, lambda w: sorted(w)[int((len(w) - 1) * 0.3)])
    vol = _rolling(raw, 4, _pstdev)
    vmed = _median([v for v in vol if v]) if any(vol) else 1.0
    still = [(by_ts[t][2] if t in by_ts else 0) <= REM_MAX_INTENSITY for t in mins]
    elev = [None if smooth[i] is None or floor[i] is None else smooth[i] - floor[i] for i in range(len(mins))]

    def pick(threshold: float) -> list[list[int]]:
        ok = [label.get(t) == "light" and t - sess["start"] >= REM_LATENCY * 60 and still[i] and elev[i] is not None
              and (elev[i] >= threshold or ((vol[i] or 0) >= REM_VOLATILITY * vmed and elev[i] >= threshold / 2))
              for i, t in enumerate(mins)]
        runs: list[list[int]] = []
        for i, flag in enumerate(ok):
            if not flag:
                continue
            if runs and i - runs[-1][1] <= REM_MERGE and all(label.get(mins[k]) == "light" for k in range(runs[-1][1], i)):
                runs[-1][1] = i + 1
            else:
                runs.append([i, i + 1])
        return [r for r in runs if r[1] - r[0] >= REM_MIN]

    threshold = REM_ELEVATION
    runs = pick(threshold)
    while sum(b - a for a, b in runs) > REM_MAX_SHARE * sess["minutes"] and threshold < 15:
        threshold += 1
        runs = pick(threshold)
    for a, b in runs:
        for k in range(a, b):
            label[mins[k]] = "rem"
    stages: list[list] = []
    for t in mins:
        k = label.get(t)
        if k is None:
            continue
        if stages and stages[-1][2] == k and stages[-1][1] == t:
            stages[-1][1] = t + 60
        else:
            stages.append([t, t + 60, k])
    rem = sum(b - a for a, b in runs)
    sess["stages"] = stages
    sess["rem"] = rem
    sess["light"] -= rem
    sess["rem_estimated"] = True
    return True


def local_date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts).date().isoformat()


def day_bounds(date: str) -> tuple[int, int]:
    d = dt.date.fromisoformat(date)
    start = dt.datetime.combine(d, dt.time()).astimezone()
    end = dt.datetime.combine(d + dt.timedelta(days=1), dt.time()).astimezone()
    return int(start.timestamp()), int(end.timestamp())


# ---------------------------------------------------------------- phân tích sức khỏe

GOOD, OK, WATCH, ALERT, NONE = "good", "ok", "watch", "alert", "none"
BRISK_STEPS = 100        # bước/phút: đi bộ nhanh trở lên được tính là vận động vừa


def body_mass_index(height_cm: float | None, weight_kg: float | None) -> float | None:
    try:
        h, w = float(height_cm) / 100, float(weight_kg)
    except (TypeError, ValueError):
        return None
    return round(w / (h * h), 1) if 1.0 <= h <= 2.5 and 20 <= w <= 300 else None


def bmi_class(bmi: float) -> tuple[str, str]:
    """(trạng thái, nhãn) theo ngưỡng BMI cho người châu Á của WHO (Lancet 2004): người Việt có nguy cơ tim mạch,
    tiểu đường ở BMI thấp hơn ngưỡng 25/30 chung."""
    from .i18n import tr

    if bmi < 18.5:
        return WATCH, tr('thiếu cân')
    if bmi < 23:
        return GOOD, tr('bình thường')
    if bmi < 25:
        return OK, tr('thừa cân')
    if bmi < 30:
        return WATCH, tr('béo phì độ I')
    return ALERT, tr('béo phì độ II')


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _hm(minutes: float) -> str:
    from .i18n import tr

    minutes = int(round(minutes))
    return tr('{h} giờ {m} phút', h=minutes // 60, m=minutes % 60)


def _clock_spread(starts: list[int]) -> float:
    """Độ lệch chuẩn (phút) của giờ đi ngủ, tính quanh nửa đêm (23:30 và 00:30 cách nhau 60 phút)."""
    mins = []
    for ts in starts:
        t = dt.datetime.fromtimestamp(ts)
        m = t.hour * 60 + t.minute
        mins.append(m - 1440 if m >= 12 * 60 else m)
    mean = sum(mins) / len(mins)
    return (sum((m - mean) ** 2 for m in mins) / len(mins)) ** 0.5


def group_dec(x: float, digits: int = 1) -> str:
    """Số thập phân theo ngôn ngữ giao diện: 22,4 (tiếng Việt), 22.4 (tiếng Anh)."""
    from .i18n import get_lang

    text = f"{x:.{digits}f}"
    return text if get_lang() == "en" else text.replace(".", ",")


def group_int(n: float) -> str:
    """Số nguyên có dấu tách nghìn theo ngôn ngữ giao diện: 21.430 (tiếng Việt), 21,430 (tiếng Anh)."""
    from .i18n import get_lang

    text = f"{int(round(n)):,}"
    return text if get_lang() == "en" else text.replace(",", ".")


def analyze(nights: list[dict], steps_days: list[dict], goal: int, pai: dict | None,
            spo2: list[tuple], stress: list[int], active_minutes: int, workouts: int, last_data: int | None,
            now: float | None = None, sleep_need: int = 450, body: dict | None = None) -> dict:
    """Nhận xét sức khỏe từ dữ liệu gần đây, theo khuyến nghị chung cho người lớn (không phải chẩn đoán).

    nights: các đêm gần nhất (cũ tới mới) {date, minutes, deep, awake, start, hr};
    steps_days: tổng bước các ngày đã trọn (cũ tới mới); spo2: [(ts, %)] 30 ngày; stress: các số đo 7 ngày;
    active_minutes: phút vận động vừa/mạnh 7 ngày; workouts: số buổi tập 7 ngày; sleep_need: nhu cầu ngủ theo tuổi
    (phút, insights.sleep_need); body: {age, height (cm), weight (kg)} từ hồ sơ, cho BMI."""
    from .i18n import tr

    now = now or dt.datetime.now().timestamp()
    items: list[dict] = []

    def add(key: str, status: str, title: str, value: str, detail: str) -> None:
        items.append({"key": key, "status": status, "title": title, "value": value, "detail": detail})

    # giấc ngủ: 7 đêm gần nhất có dữ liệu
    recent = [n for n in nights if n["minutes"]][-7:]
    if recent:
        avg = _avg([n["minutes"] for n in recent])
        lo, hi = sleep_need - 30, sleep_need + 120   # người lớn: 7–9 giờ (khoảng khuyến nghị theo tuổi)
        short = sum(1 for n in recent if n["minutes"] < lo - 60)
        status = GOOD if lo <= avg <= hi else WATCH if avg >= lo - 60 else ALERT
        if sleep_need == 450:
            detail = tr('Trung bình {n} đêm gần nhất. Người lớn nên ngủ 7–9 giờ mỗi đêm.', n=len(recent))
        else:
            detail = tr('Trung bình {n} đêm gần nhất. Ở tuổi của bạn nên ngủ {lo}–{hi} giờ mỗi đêm.', n=len(recent),
                        lo=lo // 60, hi=hi // 60)
        if avg > hi:
            detail += " " + tr('Ngủ nhiều hơn khuyến nghị.')
        if short:
            detail += " " + tr('{k} đêm ngủ dưới {h} giờ.', k=short, h=(lo - 60) // 60)
        add("sleep", status, tr('Thời gian ngủ'), _hm(avg), detail)
        deep = _avg([n["deep"] / n["minutes"] * 100 for n in recent])
        add("deep", GOOD if deep >= 13 else OK if deep >= 10 else WATCH, tr('Ngủ sâu'), f"{deep:.0f}%",
            tr('Phần giấc ngủ là ngủ sâu; thường khoảng 13–23%. Ngủ đủ giờ, đều đặn giúp tăng ngủ sâu.'))
        if len(recent) >= 3:
            spread = _clock_spread([n["start"] for n in recent])
            add("bedtime", GOOD if spread <= 45 else OK if spread <= 90 else WATCH, tr('Giờ đi ngủ đều đặn'),
                tr('lệch ±{m} phút', m=int(round(spread))),
                tr('Giờ đi ngủ chênh nhau càng ít thì nhịp sinh học càng ổn định; nên giữ trong khoảng ±45 phút.'))
    else:
        add("sleep", NONE, tr('Thời gian ngủ'), "—", tr('Chưa có dữ liệu giấc ngủ. Đeo vòng khi ngủ rồi đồng bộ.'))

    # nhịp tim khi ngủ (gần với nhịp tim nghỉ)
    hrs = [n["hr"] for n in nights if n.get("hr")]
    if hrs:
        cur = _avg(hrs[-7:])
        prev = _avg(hrs[-14:-7])
        status = GOOD if 40 <= cur <= 75 else OK if cur <= 80 else WATCH
        detail = tr('Nhịp tim trung bình khi ngủ, gần với nhịp tim nghỉ; thường 40–75 nhịp/phút ở người khỏe.')
        if prev and cur - prev >= 5:
            status = WATCH
            detail += " " + tr('Cao hơn tuần trước {d} nhịp/phút; có thể do mệt, thiếu ngủ, căng thẳng hoặc sắp ốm.',
                               d=int(round(cur - prev)))
        add("rhr", status, tr('Nhịp tim nghỉ'), tr('{n} nhịp/phút', n=int(round(cur))), detail)

    # bước chân: 7 ngày đã trọn gần nhất
    week = steps_days[-7:]
    if week:
        avg = _avg([d["steps"] for d in week])
        met = sum(1 for d in week if d["steps"] >= goal)
        prev = _avg([d["steps"] for d in steps_days[-14:-7]])
        status = GOOD if avg >= goal else OK if avg >= goal * 0.6 else WATCH
        detail = tr('Trung bình {n} ngày; đạt mục tiêu {goal} bước {met}/{n} ngày.', n=len(week),
                    goal=group_int(goal), met=met)
        if prev:
            change = (avg - prev) / prev * 100
            if abs(change) >= 10:
                detail += " " + (tr('Tăng {p}% so với tuần trước.', p=int(round(change))) if change > 0
                                 else tr('Giảm {p}% so với tuần trước.', p=int(round(-change))))
        add("steps", status, tr('Bước chân'), tr('{n} bước/ngày', n=group_int(avg)), detail)

    # vận động vừa/mạnh: WHO khuyến nghị 150 phút mỗi tuần
    add("active", GOOD if active_minutes >= 150 else OK if active_minutes >= 75 else WATCH, tr('Vận động'),
        tr('{n} phút/tuần', n=active_minutes),
        tr('Phút đi bộ nhanh (từ {s} bước/phút) và tập luyện trong 7 ngày; nên đạt 150 phút mỗi tuần. {w} buổi tập.',
           s=BRISK_STEPS, w=workouts))

    if pai:
        total = pai["total"]
        add("pai", GOOD if total >= 100 else OK if total >= 50 else WATCH, "PAI", f"{total:.0f}",
            tr('Giữ PAI từ 100 trở lên giúp giảm nguy cơ bệnh tim mạch; tăng bằng các hoạt động làm tim đập nhanh.'))

    if spo2:
        values = [v for _ts, v in spo2]
        low = min(values)
        status = GOOD if low >= 95 else OK if low >= 92 else WATCH if low >= 90 else ALERT
        detail = tr('Trung bình {avg}%, thấp nhất {low}% trong {n} lần đo 30 ngày qua; bình thường từ 95% trở lên.',
                    avg=int(round(_avg(values))), low=low, n=len(values))
        if low < 90:
            detail += " " + tr('Có lần đo dưới 90%: đo lại khi ngồi yên, đeo vòng sát tay; nếu thường thấp hoặc khó thở, hãy hỏi ý kiến bác sĩ.')
        add("spo2", status, "SpO2", f"{int(round(_avg(values)))}%", detail)

    if stress:
        avg = _avg(stress)
        high = sum(1 for v in stress if v >= 80) * 100 / len(stress)
        status = GOOD if avg < 40 else OK if avg < 60 else WATCH
        add("stress", status, tr('Căng thẳng'), f"{avg:.0f}",
            tr('Trung bình 7 ngày (0–39 thư giãn, 40–59 bình thường, 60–79 trung bình, 80+ cao); {p}% số đo ở mức cao.',
               p=int(round(high))))

    bmi = body_mass_index((body or {}).get("height"), (body or {}).get("weight"))
    if bmi is not None and ((body or {}).get("age") or 18) >= 18:   # dưới 18 tuổi BMI phải so theo bách phân vị tuổi
        status, label = bmi_class(bmi)
        add("bmi", status, tr('Chỉ số BMI'), f"{group_dec(bmi)} · {label}",
            tr('Cân nặng / chiều cao² theo hồ sơ. Ngưỡng cho người châu Á (WHO 2004): 18,5–22,9 là bình thường, từ 23 là thừa cân, từ 25 là béo phì. BMI không phân biệt cơ và mỡ.'))

    trend = (body or {}).get("trend")
    if trend and (trend["change_30"] or trend["change_90"] or trend["rate"] is not None):
        ch = trend["change_30"] or trend["change_90"]
        value = f"{group_dec(trend['weight'])} kg"
        if ch:
            value += f" ({'+' if ch['kg'] > 0 else '−' if ch['kg'] < 0 else '±'}{group_dec(abs(ch['kg']))})"
        first = [tr('Thay đổi so với {n} ngày trước, theo các lần ghi cân nặng.', n=30 if trend["change_30"] else 90)] if ch else []
        add("weight", trend["status"], tr('Cân nặng'), value, " ".join(first + trend["notes"]))

    if last_data and now - last_data > 2 * 86400:
        add("fresh", WATCH, tr('Dữ liệu'), tr('cũ'), tr('Dữ liệu mới nhất đã hơn 2 ngày; kết nối và đồng bộ để phân tích chính xác.'))

    counts = {s: sum(1 for i in items if i["status"] == s) for s in (GOOD, OK, WATCH, ALERT)}
    return {"items": items, "counts": counts}
