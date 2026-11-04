"""Chi tiết một buổi tập: đọc tệp dữ liệu từng giây và độ cao GPS của Mi Fitness, rồi dựng các số liệu như trang buổi
tập của Mi Fitness (nhịp tim và vùng nhịp tim, tốc độ / pace từng km, nhịp bước, sải chân, độ cao, tải tập luyện).

Hàm thuần, không I/O. Nguồn dữ liệu theo thứ tự ưu tiên: tệp từng giây của Mi Fitness (buổi chạy, đi bộ, đạp xe ngoài
trời có GPS), lộ trình GPS, số liệu từng phút của vòng tay (nhịp tim, bước chân) trong giờ tập.

Bố cục tệp từng giây theo bảng của dự án mifit (MIT, (c) 2026 Jenwein), viết lại từ bộ đọc của ứng dụng Mi Fitness:
kiểu 22 (bước chân ngoài trời: chạy, đi bộ…) phiên bản 1-8, kiểu 23 (đạp xe ngoài trời) phiên bản 1-5. Phiên bản mới
hơn chưa có bảng chắc chắn: thử vài bố cục ứng viên và chỉ nhận khi tổng quãng đường, bước chân, thời lượng khớp với
bản tóm tắt của chính buổi tập đó.
"""

from __future__ import annotations

import math
import struct

RECORD_FILE = 0   # loại tệp trên máy chủ: dữ liệu từng giây
GPS_FILE = 2      # lộ trình GPS
RECORD_PROTOS = (22, 23)

# ---------------------------------------------------------------- tệp dữ liệu từng giây

# (tên các giá trị con từ cao xuống thấp, số byte, (bit đầu, số bit) của từng giá trị con hoặc None: cả giá trị,
#  từ phiên bản, tới phiên bản)
_W = (None,)
_ALT1 = (("km", "rising", "alt_change"), 1, ((7, 1), (6, 1), (0, 6)))
RUN_FIELDS = (
    (("calories", "steps"), 1, ((4, 4), (0, 4)), 1, None),
    (("hr",), 1, _W, 1, None),
    (*_ALT1, 1, 8),
    (("distance",), 1, _W, 1, 8),
    (("stride",), 1, _W, 2, None),
    (("impact", "contact", "flight"), 4, ((26, 6), (13, 13), (0, 13)), 4, None),
    (("contact_ratio",), 1, _W, 5, None),
    (("cadence",), 1, _W, 5, None),
    (("pace",), 2, _W, 5, None),
    (("eq_pace",), 2, _W, 6, None),
    (("power",), 2, _W, 6, None),
    (("v_ratio",), 2, _W, 8, None),
    (("v_amp",), 2, _W, 8, None),
)
RIDE_FIELDS = (
    (("calories", "count"), 1, ((4, 4), (0, 4)), 1, None),
    (("hr",), 1, _W, 1, None),
    (*_ALT1, 1, 5),
    (("distance",), 1, _W, 1, 5),
    (("speed",), 2, _W, 3, None),
    (("cadence",), 1, _W, 3, None),
)
# đầu mỗi đoạn (giữa hai lần tạm dừng): độ cao đầu, số điểm, thời điểm bắt đầu, loại đoạn, tổng quãng đường, thời
# lượng, bước chân, pace (chạy) / tổng thời gian, tốc độ (đạp xe)
RUN_SEGMENT = ("<f", "<I", "<I", "<B", "<I", "<I", "<I", "<H")    # 27 byte
RIDE_SEGMENT = ("<f", "<I", "<I", "<B", "<I", "<I", "<H")         # 23 byte
VALIDITY = {22: {1: 2, 2: 3, 3: 3, 4: 3, 5: 5, 6: 6, 7: 6, 8: 7, 9: 7}, 23: {1: 2, 2: 2, 3: 3, 4: 3, 5: 3, 6: 3, 7: 4}}
KNOWN = {22: 8, 23: 5}           # phiên bản mới nhất có bảng chắc chắn
DIST_PER_M = {22: 10, 23: 1}     # quãng đường mỗi giây: dm (kiểu 22), m (kiểu 23)
SPEED_PER_MPS = 36               # tốc độ (đạp xe): 0,1 km/h


def _fields_for(table: tuple, version: int) -> list[tuple]:
    return [f for f in table if f[3] <= version and (f[4] is None or version <= f[4])]


def _candidates(proto: int, version: int) -> list[tuple[list[tuple], int]]:
    """Các bố cục (danh sách trường, số đơn vị quãng đường mỗi mét) để thử cho một phiên bản."""
    table = RUN_FIELDS if proto == 22 else RIDE_FIELDS
    if version <= KNOWN[proto]:
        return [(_fields_for(table, version), DIST_PER_M[proto])]
    # phiên bản mới: độ cao 4 byte và quãng đường 2 byte thay cho hai trường 1 byte (đặt tại chỗ hoặc thêm ở cuối),
    # quãng đường có thể là dm hoặc cm
    base = _fields_for(table, KNOWN[proto])
    alt4 = (("alt4",), 4, _W, version, None)
    dist2 = (("distance",), 2, _W, version, None)
    keep = [f for f in base if f[0][0] not in ("km", "distance")]
    hr_at = next(i for i, f in enumerate(keep) if f[0] == ("hr",))
    in_place = keep[:hr_at + 1] + [alt4, dist2] + keep[hr_at + 1:]
    appended = keep + [alt4, dist2]
    out = []
    for fields in (in_place, appended):
        for per_m in (100, 10) if proto == 22 else (100, 10, 1):
            out.append((fields, per_m))
    return out


class _Reader:
    def __init__(self, data: bytes, pos: int):
        self.data, self.pos = data, pos

    @property
    def left(self) -> int:
        return len(self.data) - self.pos

    def read(self, code: str):
        size = struct.calcsize(code)
        if size > self.left:
            raise ValueError("hết tệp")
        (v,) = struct.unpack_from(code, self.data, self.pos)
        self.pos += size
        return v

    def uint(self, size: int) -> int:
        if size > self.left:
            raise ValueError("hết tệp")
        v = int.from_bytes(self.data[self.pos:self.pos + size], "little")
        self.pos += size
        return v


def _decode_with(plain: bytes, proto: int, validity: bytes, fields: list[tuple], per_m: int) -> list[list]:
    """Các điểm (mỗi giây một điểm) theo một bố cục: [ts, nhịp tim, quãng đường cộng dồn (m), bước cộng dồn, nhịp bước,
    pace (giây/km), tốc độ (m/s), sải chân (cm)]. ValueError nếu tệp không hợp bố cục."""
    if len(fields) > 2 * len(validity):
        raise ValueError("cờ hợp lệ ngắn hơn bảng trường")
    present = []
    for k, f in enumerate(fields):
        nib = validity[k // 2] >> 4 if k % 2 == 0 else validity[k // 2] & 0x0F
        if nib & 8:   # trường có mặt; 4 / 2 / 1: giá trị con cao / giữa / thấp hợp lệ
            present.append((f, tuple(bool(nib & b) for b in (4, 2, 1)[:len(f[0])])))
    point = sum(f[1] for f, _v in present)
    seg = RUN_SEGMENT if proto == 22 else RIDE_SEGMENT
    head = sum(struct.calcsize(c) for c in seg)
    r = _Reader(plain, 8 + len(validity))
    out: list[list] = []
    dist = steps = 0
    while r.left >= head:
        vals = [r.read(c) for c in seg]
        count, resume = vals[1], vals[2]
        if count and not point:
            raise ValueError("đoạn có điểm nhưng không có trường nào")
        if count * point > r.left or len(out) + count > 200_000:
            raise ValueError("đoạn khai nhiều điểm hơn tệp")
        for i in range(count):
            p = {}
            for f, valid in present:
                v = r.uint(f[1])
                for name, bits, ok in zip(f[0], f[2], valid):
                    if ok:
                        p[name] = v if bits is None else (v >> bits[0]) & ((1 << bits[1]) - 1)
            d_m = None
            if "distance" in p:
                dist += p["distance"]
                d_m = dist / per_m
            s_now = None
            if proto == 22 and "steps" in p:
                steps += p["steps"]
                s_now = steps
            out.append([resume + i, p.get("hr") or None, d_m, s_now, p.get("cadence") if proto == 22 else None,
                        (p.get("pace") or None) if proto == 22 else None,
                        p["speed"] / SPEED_PER_MPS if proto == 23 and "speed" in p else None,
                        p.get("stride") or None])
    return out


def _fits(samples: list[list], expect: dict | None) -> bool:
    """Bố cục đúng thì tổng quãng đường, bước chân và số giây khớp với bản tóm tắt của buổi tập (nếu có số để so)."""
    if not samples:
        return False
    hrs = [s[1] for s in samples if s[1]]
    if hrs and sum(1 for h in hrs if 30 <= h <= 230) < 0.9 * len(hrs):
        return False
    if not expect:
        return True
    ok = True
    want = expect.get("distance") or 0
    got = samples[-1][2]
    if want >= 200:
        ok &= got is not None and abs(got - want) <= max(30, 0.06 * want)
    want = expect.get("steps") or 0
    got = samples[-1][3]
    if want >= 200 and got is not None:
        ok &= abs(got - want) <= max(30, 0.06 * want)
    want = expect.get("active_seconds") or 0
    if want >= 120:
        ok &= abs(len(samples) - want) <= max(30, 0.15 * want)
    return ok


def decode_record_file(plain: bytes, expect: dict | None = None) -> list[list]:
    """Tệp dữ liệu từng giây của Mi Fitness (đã giải mã) -> [[ts, nhịp tim, quãng đường cộng dồn (m), bước cộng dồn,
    nhịp bước, pace (giây/km), tốc độ (m/s), sải chân (cm)], ...]; giá trị không có là None.

    expect: bản tóm tắt buổi tập (distance, steps, active_seconds) để kiểm tra; với phiên bản chưa có bảng chắc chắn
    thì đó là cách duy nhất chọn bố cục. ValueError nếu không đọc được."""
    if len(plain) < 8:
        raise ValueError("tệp quá ngắn")
    _ts, _tz, version, proto, mode = struct.unpack_from("<IbBBB", plain)
    if mode != 0:
        raise ValueError(f"tệp được nén hoặc mã hóa thêm (chế độ {mode})")
    if proto not in RECORD_PROTOS or version not in VALIDITY[proto]:
        raise ValueError(f"chưa có bố cục cho kiểu {proto} phiên bản {version}")
    validity = plain[8:8 + VALIDITY[proto][version]]
    if len(validity) < VALIDITY[proto][version]:
        raise ValueError("tệp hết giữa cờ hợp lệ")
    known = version <= KNOWN[proto]
    for fields, per_m in _candidates(proto, version):
        try:
            samples = _decode_with(plain, proto, validity, fields, per_m)
        except ValueError:
            continue
        if _fits(samples, expect) or (known and _fits(samples, None)):
            return samples
    raise ValueError(f"không đọc được tệp kiểu {proto} phiên bản {version}")


# ---------------------------------------------------------------- độ cao trong tệp GPS

GPS_ALT_OFFSET = {3: 18}   # phiên bản 3: độ cao float32 (m) ngay sau các trường của phiên bản 2


def gps_altitudes(plain: bytes) -> list[list] | None:
    """[[ts, độ cao (m)], ...] từ tệp lộ trình GPS (đã giải mã) phiên bản có độ cao; None nếu tệp không có hoặc số đọc
    được không giống độ cao thật (ngoài -500..9000 m hoặc nhảy quá 15 m mỗi điểm)."""
    if not plain or len(plain) < 9:
        return None
    _ts, _tz, version, _proto, mode = struct.unpack_from("<IbBBB", plain)
    if mode != 0 or version not in GPS_ALT_OFFSET:
        return None
    size, off = 26, GPS_ALT_OFFSET[version]
    out = []
    for pos in range(9, len(plain) - size + 1, size):
        ts = struct.unpack_from("<I", plain, pos)[0]
        alt = struct.unpack_from("<f", plain, pos + off)[0]
        if not (alt == alt and -500 <= alt <= 9000):
            return None
        out.append([ts, round(alt, 1)])
    if len(out) < 2:
        return None
    jumps = sorted(abs(b[1] - a[1]) for a, b in zip(out, out[1:]))
    if jumps[len(jumps) // 2] > 15:
        return None
    return out


# ---------------------------------------------------------------- dựng trang chi tiết

ZONE_PCT = (50, 60, 70, 80, 90, 100)   # vùng 1-5 theo % nhịp tim tối đa, như insights._zones
ZONE_WEIGHT = (1, 2, 3, 4, 5)          # hệ số Edwards: TRIMP = phút trong vùng x hệ số
LOAD_LEVELS = ((40, "light"), (90, "moderate"), (180, "hard"), (10_000, "very_hard"))
SERIES_POINTS = 360                    # điểm tối đa của mỗi biểu đồ gửi cho trình duyệt
PACE_WINDOW = 30                       # giây: tốc độ tính trên cửa sổ trượt này
GRADE_FLAT = 0.02                      # độ dốc dưới 2%: đường bằng
RIDE_TYPES = (4, 8)                    # mã loại bài tập đạp xe của vòng tay
RUN_TYPES = (1, 2, 6, 7, 9, 11)        # chạy ngoài trời, máy chạy bộ, chạy địa hình…
WALK_TYPES = (3, 10, 15, 16)


def sport_kind(w: dict) -> str:
    """"run", "walk", "ride" hoặc "other" để chọn cách hiển thị (pace hay tốc độ) và mô hình thể lực."""
    t, mf, proto = w.get("type"), w.get("mf_type"), w.get("mf_proto")
    if proto == 23 or t in RIDE_TYPES or mf == 6:
        return "ride"
    if t in WALK_TYPES or (t is None and mf in (2, 3)):
        return "walk"
    if t in RUN_TYPES or (t is None and mf in (1, 4, 5)) or proto == 22:
        return "run"
    return "other"


def zone_of(hr: float, hrmax: float) -> int:
    """Vùng 1-5 theo % nhịp tim tối đa; 0 nếu dưới 50%."""
    pct = 100 * hr / hrmax
    for z in range(5, 0, -1):
        if pct >= ZONE_PCT[z - 1]:
            return z
    return 0


def zone_bounds(hrmax: float) -> list[list[int]]:
    return [[int(round(hrmax * ZONE_PCT[z] / 100)), int(round(hrmax * ZONE_PCT[z + 1] / 100))] for z in range(5)]


def _downsample(points: list[list], n: int = SERIES_POINTS) -> list[list]:
    """Giảm còn tối đa n điểm bằng trung bình từng nhóm (giữ điểm đầu, cuối)."""
    if len(points) <= n:
        return points
    step = len(points) / n
    out = []
    for i in range(n):
        chunk = points[int(i * step):max(int(i * step) + 1, int((i + 1) * step))]
        out.append([chunk[len(chunk) // 2][0], round(sum(p[1] for p in chunk) / len(chunk), 1)])
    return out


def _haversine(a: list, b: list) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[1], a[2], b[1], b[2]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


def track_distance(track: list[list]) -> list[list]:
    """[[ts, quãng đường cộng dồn (m)], ...] từ lộ trình GPS [[ts, vĩ độ, kinh độ], ...]; bỏ bước nhảy vô lý (> 15 m/s)."""
    out, total = [], 0.0
    for a, b in zip([None] + track[:-1], track):
        if a is not None:
            d = _haversine(a, b)
            if d <= 15 * max(1, b[0] - a[0]):
                total += d
        out.append([b[0], total])
    return out


def _speed_series(dist: list[list]) -> list[list]:
    """Tốc độ (m/s) theo cửa sổ trượt PACE_WINDOW giây trên chuỗi [ts, quãng đường cộng dồn]."""
    out, j = [], 0
    for i, (ts, d) in enumerate(dist):
        while dist[j][0] < ts - PACE_WINDOW:
            j += 1
        dt_ = ts - dist[j][0]
        if dt_ >= PACE_WINDOW / 2:
            out.append([ts, max(0.0, (d - dist[j][1]) / dt_)])
    return out


def _splits(dist: list[list], hr: list[list], moving: bool) -> list[dict]:
    """Từng km: thời gian, pace và nhịp tim trung bình; km cuối chưa trọn ghi quãng đường lẻ (như "<2" của Mi Fitness).
    moving: dist có một điểm mỗi giây chạy (tệp từng giây) thì đếm điểm, không thì lấy chênh lệch thời điểm."""
    if not dist or dist[-1][1] < 50:
        return []
    out, k, last_i = [], 1, 0

    def seconds(i0: int, i1: int) -> float:
        return (i1 - i0) if moving else dist[i1][0] - dist[i0][0]

    def hr_avg(t0: int, t1: int) -> int | None:
        vals = [v for ts, v in hr if t0 <= ts <= t1]
        return int(round(sum(vals) / len(vals))) if vals else None

    for i, (ts, d) in enumerate(dist):
        while d >= k * 1000:
            sec = seconds(last_i, i)
            out.append({"km": k, "seconds": int(round(sec)), "pace": int(round(sec)), "hr": hr_avg(dist[last_i][0], ts),
                        "partial": False})
            last_i, k = i, k + 1
    rest = dist[-1][1] - (k - 1) * 1000
    if rest >= 50:
        sec = seconds(last_i, len(dist) - 1)
        out.append({"km": round((k - 1) + rest / 1000, 2), "seconds": int(round(sec)),
                    "pace": int(round(sec * 1000 / rest)), "hr": hr_avg(dist[last_i][0], dist[-1][0]), "partial": True})
    return out


def _altitude(alt: list[list], dist: list[list] | None) -> dict | None:
    """Độ cao thấp nhất, cao nhất, tổng lên / xuống (bỏ dao động dưới 1 m) và thời gian lên dốc / bằng / xuống dốc."""
    if not alt or len(alt) < 5:
        return None
    vals = [a[1] for a in alt]
    smooth = [sorted(vals[max(0, i - 2):i + 3])[len(vals[max(0, i - 2):i + 3]) // 2] for i in range(len(vals))]
    gain = loss = 0.0
    ref = smooth[0]
    for v in smooth[1:]:
        if v - ref >= 1:
            gain += v - ref
            ref = v
        elif ref - v >= 1:
            loss += ref - v
            ref = v
    terrain = {"up": 0, "flat": 0, "down": 0}
    if dist:
        d_at = dict((int(ts), d) for ts, d in dist)
        pts = [(alt[i][0], smooth[i]) for i in range(len(alt))]
        for (t0, a0), (t1, a1) in zip(pts[::10], pts[10::10]):
            d0, d1 = d_at.get(int(t0)), d_at.get(int(t1))
            span = t1 - t0
            if d0 is None or d1 is None or span <= 0:
                continue
            run = d1 - d0
            grade = (a1 - a0) / run if run > 5 else 0.0
            terrain["up" if grade > GRADE_FLAT else "down" if grade < -GRADE_FLAT else "flat"] += span
    return {"min": round(min(smooth)), "max": round(max(smooth)), "gain": int(round(gain)), "loss": int(round(loss)),
            "series": _downsample([[a[0], s] for a, s in zip(alt, smooth)]),
            "terrain": terrain if sum(terrain.values()) else None}


MISMATCH_BPM = 25   # nhịp tim từng phút lệch quá xa nhịp tim trung bình của buổi tập: không phải số đo của buổi đó


def hr_points(samples: list[list] | None, minutes: list[list], start: int, end: int,
              avg_hr: float | None = None) -> tuple[list[list], int]:
    """Nhịp tim trong giờ tập: từng giây (tệp Mi Fitness) nếu có, không thì từng phút của vòng tay. Trả về (điểm, số
    giây mỗi điểm đại diện). Số từng phút lệch hẳn nhịp tim trung bình của bản tóm tắt (vòng tay không đeo, giờ lệch…)
    thì bỏ, không vẽ một biểu đồ sai."""
    sec = [[s[0], s[1]] for s in samples or [] if s[1]]
    if len(sec) >= 60:
        return sec, 1
    pts = [[ts, hr] for ts, hr, _st in minutes if hr and start - 30 <= ts < end]   # phút bắt đầu trước lúc kết thúc
    if pts and avg_hr and abs(sum(v for _t, v in pts) / len(pts) - avg_hr) > MISMATCH_BPM:
        return [], 60
    return pts, 60


def zone_seconds(hr: list[list], each: int, hrmax: float) -> list[int]:
    out = [0] * 5
    for _ts, v in hr:
        z = zone_of(v, hrmax)
        if z:
            out[z - 1] += each
    return out


def trimp(zones: list[int]) -> float:
    """TRIMP kiểu Edwards: phút trong mỗi vùng x hệ số vùng (1-5)."""
    return round(sum(s / 60 * w for s, w in zip(zones, ZONE_WEIGHT)), 1)


def load_level(t: float) -> str:
    return next(name for top, name in LOAD_LEVELS if t < top)


def detail(w: dict, samples: list[list] | None, track: list[list] | None, alt: list[list] | None,
           minutes: list[list], hrmax: float, rpe: int | None = None) -> dict:
    """Trang chi tiết một buổi tập.

    w: bản tóm tắt (vòng tay và/hoặc Mi Fitness); samples: decode_record_file; track: [[ts, vĩ độ, kinh độ]];
    alt: gps_altitudes; minutes: [[ts, nhịp tim, bước]] từng phút của vòng tay quanh giờ tập; hrmax: nhịp tim tối đa."""
    start = int(w["start"])
    end = int(w.get("end") or start)
    kind = sport_kind(w)
    sources = []
    if w.get("source") == "band" or w.get("version") is not None:
        sources.append("band")
    if w.get("mf_sid") or w.get("source") == "mifitness":
        sources.append("mifitness")
    if samples:
        sources.append("detail")
    if track:
        sources.append("gps")

    # quãng đường theo thời gian: tệp từng giây, không thì lộ trình GPS
    dist = [[s[0], s[2]] for s in samples or [] if s[2] is not None]
    moving = len(dist) >= 30
    if not moving and track and len(track) >= 2:
        dist = track_distance(track)
    duration = int(w.get("active_seconds") or (len(samples) if samples else 0) or max(0, end - start))
    distance = w.get("distance") or (round(dist[-1][1]) if dist else None)
    if not distance or distance < 50:
        distance = None
    steps = w.get("steps") or (samples[-1][3] if samples and samples[-1][3] else None) \
        or (sum(st for ts, _hr, st in minutes if start <= ts < end) or None)

    hr, each = hr_points(samples, minutes, start, end, w.get("avg_hr"))
    vals = [v for _ts, v in hr]
    zones = zone_seconds(hr, each, hrmax) if vals else [0] * 5
    load = trimp(zones)
    hr_info = None
    if vals or w.get("avg_hr"):
        hr_info = {"avg": w.get("avg_hr") or int(round(sum(vals) / len(vals))), "max": w.get("max_hr") or max(vals or [0]) or None,
                   "min": min(vals) if vals else None, "series": _downsample([[ts - start, v] for ts, v in hr]),
                   "source": "detail" if each == 1 else "band", "zones": zones, "bounds": zone_bounds(hrmax)}

    out: dict = {"start": start, "end": end, "kind": kind, "duration": duration, "distance": distance,
                 "calories": w.get("calories"), "steps": steps, "hr": hr_info, "sources": sources, "rpe": rpe,
                 "load": {"trimp": load, "level": load_level(load)} if vals else None,
                 "gps": bool(track) or bool(w.get("gps"))}
    if distance and duration:
        out["pace"] = int(round(duration * 1000 / distance))   # giây mỗi km
        out["speed"] = round(distance / duration * 3.6, 1)     # km/h
    speed = _speed_series(dist) if len(dist) >= 30 else []
    if speed:
        if kind == "ride":
            out["speed_series"] = _downsample([[ts - start, round(v * 3.6, 1)] for ts, v in speed])
            out["max_speed"] = round(max(v for _t, v in speed) * 3.6, 1)
        else:
            moving_speed = [[ts, v] for ts, v in speed if v >= 0.5]
            if moving_speed:
                out["pace_series"] = _downsample([[ts - start, round(min(1800.0, 1000 / v))] for ts, v in moving_speed])
                out["max_pace"] = int(round(1000 / max(v for _t, v in moving_speed)))
        out["splits"] = _splits(dist, hr, moving)
    # nhịp bước: tệp từng giây (Mi Fitness tính cả giây 0), không thì bước mỗi phút của vòng tay
    cad = [[s[0], s[4]] for s in samples or [] if s[4] is not None]
    if len(cad) >= 60:
        out["cadence"] = {"avg": int(round(sum(v for _t, v in cad) / len(cad))), "max": max(v for _t, v in cad),
                          "series": _downsample([[ts - start, v] for ts, v in cad])}
    elif kind in ("run", "walk") and steps and duration >= 60:
        avg = steps / (duration / 60)
        per_min = [[ts - start, st] for ts, _hr, st in minutes if start <= ts < end and st]
        # bước từng phút của vòng tay chỉ dùng khi khớp với bản tóm tắt (cùng một buổi tập)
        fits = per_min and abs(sum(v for _t, v in per_min) / len(per_min) - avg) <= 0.35 * avg
        out["cadence"] = {"avg": int(round(avg)), "max": max(v for _t, v in per_min) if fits else None,
                          "series": per_min if fits else None}
    if steps and distance and kind in ("run", "walk"):
        stride = [[s[0] - start, s[7]] for s in samples or [] if s[7]]
        out["stride"] = {"avg": int(round(distance * 100 / steps)), "max": max(v for _t, v in stride) if stride else None,
                         "series": _downsample(stride) if len(stride) >= 60 else None}
    altitude = _altitude(alt, dist if moving or dist else None)
    if altitude:
        altitude["series"] = [[ts - start, v] for ts, v in altitude["series"]]
        out["altitude"] = altitude
    return out


# ---------------------------------------------------------------- dữ liệu giả lập cho chế độ xem thử


def demo_record(w: dict) -> list[list]:
    """Dữ liệu từng giây giả lập khớp bản tóm tắt (chế độ xem thử): khởi động chậm, giữa buổi đều, nước rút cuối."""
    duration = max(300, int(w.get("active_seconds") or 1800))
    distance = float(w.get("distance") or 0)
    steps_total = float(w.get("steps") or 0)
    ride = w.get("mf_proto") == 23
    avg_hr = float(w.get("avg_hr") or 135)
    out, dist, steps = [], 0.0, 0.0
    shape = [0.75 + 0.25 * min(1, i / 240) + (0.12 if i > duration - 120 else 0) + 0.04 * math.sin(i / 37)
             for i in range(duration)]
    norm = sum(shape)
    for i in range(duration):
        dist += distance * shape[i] / norm
        steps += steps_total * shape[i] / norm
        hr = avg_hr * (0.82 + 0.18 * min(1, i / 300)) + (14 if i > duration - 120 else 0) + 3 * math.sin(i / 23)
        speed = distance * shape[i] / norm
        cadence = None if ride else int(round(steps_total * shape[i] / norm * 60))
        pace = None if ride or speed <= 0 else int(round(1000 / speed))
        out.append([int(w["start"]) + i, int(round(hr)), round(dist, 1), None if ride else int(steps), cadence, pace,
                    round(speed, 2) if ride else None, None if ride or not cadence else
                    int(round(speed * 60 / max(1, cadence) * 100))])
    return out


def demo_altitude(track: list[list]) -> list[list]:
    """Độ cao giả lập theo lộ trình (chế độ xem thử): một dốc thoải giữa đường."""
    n = len(track)
    return [[p[0], round(85 + 12 * math.sin(math.pi * i / max(1, n - 1)) + 2 * math.sin(i / 9), 1)]
            for i, p in enumerate(track)]
