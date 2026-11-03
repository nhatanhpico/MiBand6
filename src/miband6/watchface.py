"""Dựng tệp mặt đồng hồ Mi Band 6 (.bin dạng UIHH) từ ảnh nền tùy chọn và các chữ số giờ.

Hàm thuần, dễ kiểm thử. Định dạng theo mô tả của cộng đồng (watchface-js, mẫu "UIHH_MIBAND") và bộ dựng
mặt đồng hồ Mi Band 6 đã chạy trên vòng tay thật của dự án pixel-watchface:

    tiêu đề 87 byte  |  mục lục tham số  |  tham số  |  bảng vị trí ảnh  |  các ảnh

- Tiêu đề phải là của Mi Band 6: byte 14-17 là 3E 00 3E 00 và byte 22-25 là 1F 22 11 00 (Mi Band 5 dùng
  3D 00 3D 00 / E0 7F 05 00), byte 12-13 và 18-19 là mã riêng của mặt đồng hồ, rồi mã thiết bị 148 (Mi Band 6)
  và cỡ mục lục tham số. Tiêu đề mẫu của watchface-js là của Mi Band 5: Mi Band 6 nhận tệp nhưng bị treo khi vẽ.
- Tham số mã hóa kiểu protobuf: khóa (id << 3, hoặc | 2 nếu là nhóm con) rồi giá trị varint.
- Mỗi ảnh: "BM", 100, rộng, cao, số byte mỗi hàng, số bit, số màu, màu trong suốt (uint16), rồi điểm ảnh
  24 bit: 1 byte độ trong suốt (0 = đặc) và màu RGB565 xếp BGR, big-endian.
"""

from __future__ import annotations

import datetime as _dt
import math
import struct

SCREEN_W, SCREEN_H = 152, 486
BAND_ID = 148                # mã thiết bị Mi Band 6 trong tiêu đề (Mi Band 5: 146)
HEADER_SIZE = 87
DEVICE_POS = HEADER_SIZE - 8           # mã thiết bị (watchface-js gọi là "cỡ tham số lớn nhất")
PARAM_INFO_SIZE_POS = HEADER_SIZE - 4  # cỡ phần mục lục tham số
MAX_PARAM = BAND_ID          # tham số lớn hơn số ở DEVICE_POS bị vòng tay bỏ qua: giữ mỗi tham số nhỏ hơn
IMAGE_FORMAT = 100           # trường thứ hai của tiêu đề ảnh, như bộ dựng đã chạy trên Mi Band 6


def band6_header(face_id: bytes, info_size: int) -> bytes:
    """Tiêu đề 87 byte của mặt đồng hồ Mi Band 6; face_id: 4 byte mã riêng của mặt đồng hồ."""
    head = (b"UIHH\x01\x00" + b"\xff" * 5 + b"\x01" + face_id[:2] + bytes.fromhex("3e003e00") + face_id[2:4]
            + b"\x00\x00" + bytes.fromhex("1f221100") + b"\xff" * 6 + b"\x00")
    head += b"\xff" * (DEVICE_POS - len(head))
    return head + BAND_ID.to_bytes(4, "little") + info_size.to_bytes(4, "little")

# id tham số (mẫu UIHH_MIBAND)
BACKGROUND, TIME = 2, 3
BG_IMAGE, BG_PREVIEW_EN, BG_PREVIEW_CN, BG_PREVIEW_CN2 = 1, 3, 4, 5
TIME_HOURS, TIME_MINUTES, TIME_DRAWING_ORDER = 1, 2, 11
DIGIT_TENS, DIGIT_ONES = 1, 2


def varint(value: int) -> bytes:
    value &= (1 << 64) - 1   # số âm: bù hai 64 bit như protobuf
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_params(tree: dict) -> bytes:
    """{id: số | {id: …} | [giá trị, …]} → nhị phân; khóa xếp tăng dần như bản gốc."""
    out = bytearray()
    for key in sorted(tree):
        values = tree[key] if isinstance(tree[key], list) else [tree[key]]
        for v in values:
            if isinstance(v, dict):
                child = encode_params(v)
                out += varint((key << 3) | 2) + varint(len(child)) + child
            else:
                out += varint(key << 3) + varint(int(v))
    return bytes(out)


def image_24bit(width: int, height: int, rgba: bytes) -> bytes:
    """Ảnh 24 bit có kênh trong suốt từ điểm ảnh RGBA (mỗi điểm 4 byte, từ trái sang, trên xuống)."""
    if len(rgba) != width * height * 4:
        raise ValueError(f"ảnh {width}x{height} cần {width * height * 4} byte RGBA, nhận {len(rgba)}")
    head = b"BM" + b"".join(v.to_bytes(2, "little") for v in (IMAGE_FORMAT, width, height, width * 3, 24, 0, 0))
    px = bytearray(width * height * 3)
    for i in range(width * height):
        r, g, b, a = rgba[i * 4:i * 4 + 4]
        color = ((b & 0xF8) << 8) | ((g & 0xFC) << 3) | ((r & 0xF8) >> 3)
        px[i * 3] = 0xFF - a
        px[i * 3 + 1] = color >> 8
        px[i * 3 + 2] = color & 0xFF
    return head + bytes(px)


def build(parameters: dict[int, dict], images: list[bytes]) -> bytes:
    """Ghép tệp .bin: `parameters` theo id tham số cấp cao, `images` là các ảnh đã mã hóa."""
    blobs = []
    info: dict = {}
    pos = 0
    for key in sorted(parameters):
        blob = encode_params(parameters[key])
        info[key] = {1: pos, 2: len(blob)}
        blobs.append(blob)
        pos += len(blob)
    info[1] = {1: pos, 2: len(images)}
    info_blob = encode_params(info)
    table = bytearray()
    offset = 0
    for img in images:
        table += offset.to_bytes(4, "little")
        offset += len(img)
    if any(len(b) > MAX_PARAM for b in blobs):
        raise ValueError(f"tham số dài hơn {MAX_PARAM} byte, vòng tay sẽ bỏ qua")
    body = info_blob + b"".join(blobs) + bytes(table) + b"".join(images)
    import hashlib

    face_id = hashlib.sha1(body).digest()[:4]   # mã riêng mỗi mặt đồng hồ (bộ dựng gốc dùng số ngẫu nhiên)
    return band6_header(face_id, len(info_blob)) + body


def wallpaper_face(background: bytes, preview: tuple[int, int, bytes], digits: list[tuple[int, int, bytes]],
                   hours_xy: tuple[int, int] | None, minutes_xy: tuple[int, int] | None) -> bytes:
    """Mặt đồng hồ "ảnh nền": nền 152x486 (RGBA) và giờ, phút xếp chồng (mỗi hàng hai chữ số).

    digits: 10 ảnh chữ số 0-9 cùng cỡ (rộng, cao, RGBA); hours_xy/minutes_xy: góc trên trái của hàng
    giờ / phút, hoặc None để không hiện giờ. `preview` không được đưa vào tệp: bộ dựng đã chạy trên Mi Band 6
    không có ảnh xem trước, và ảnh xem trước cỡ lạ là một chỗ có thể làm vòng tay treo (giữ tham số để tương thích)."""
    del preview
    if len(background) != SCREEN_W * SCREEN_H * 4:
        raise ValueError("ảnh nền phải đúng 152x486")
    images = [image_24bit(SCREEN_W, SCREEN_H, background)]
    params: dict[int, dict] = {BACKGROUND: {BG_IMAGE: {1: 0, 2: 0, 3: 0}}}
    if hours_xy and minutes_xy:
        if len(digits) != 10 or len({(w, h) for w, h, _ in digits}) != 1:
            raise ValueError("cần 10 ảnh chữ số cùng kích thước")
        first = len(images)
        images += [image_24bit(*d) for d in digits]
        w = digits[0][0]

        def row(x: int, y: int) -> dict:
            return {DIGIT_TENS: {1: x, 2: y, 3: first, 4: 10}, DIGIT_ONES: {1: x + w, 2: y, 3: first, 4: 10}}

        params[TIME] = {TIME_HOURS: row(*hours_xy), TIME_MINUTES: row(*minutes_xy), TIME_DRAWING_ORDER: 0}
    return build(params, images)


# ---------------------------------------------------------------- đọc lại (kiểm thử, chẩn đoán)


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, pos


def decode_params(data: bytes) -> dict:
    out: dict = {}
    pos = 0
    while pos < len(data):
        key, pos = read_varint(data, pos)
        if key & 7 == 5:   # số thực 4 byte
            value = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        elif key & 2:
            size, pos = read_varint(data, pos)
            value = decode_params(data[pos:pos + size])
            pos += size
        else:
            value, pos = read_varint(data, pos)
            if value >= 1 << 63:   # số có dấu 64 bit (tọa độ âm của kim đồng hồ, …)
                value -= 1 << 64
        k = key >> 3
        if k in out:
            out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [value]
        else:
            out[k] = value
    return out


def parse(data: bytes) -> tuple[dict, list[bytes]]:
    """(tham số theo id, các ảnh đã mã hóa) của một tệp do `build` tạo."""
    if not data.startswith(b"UIHH"):
        raise ValueError("không phải tệp UIHH")
    info_size = int.from_bytes(data[PARAM_INFO_SIZE_POS:PARAM_INFO_SIZE_POS + 4], "little")
    pos = HEADER_SIZE
    info = decode_params(data[pos:pos + info_size])
    pos += info_size
    meta = info.pop(1)   # {1: cỡ phần tham số, 2: số ảnh}
    total, count = meta[1], meta[2]
    params = {k: decode_params(data[pos + v.get(1, 0):pos + v.get(1, 0) + v[2]]) for k, v in info.items()}
    pos += total
    offsets = [int.from_bytes(data[pos + 4 * i:pos + 4 * i + 4], "little") for i in range(count)]
    pos += 4 * count
    ends = offsets[1:] + [len(data) - pos]
    return params, [data[pos + a:pos + b] for a, b in zip(offsets, ends)]




# ---------------------------------------------------------------- đọc ảnh trong tệp .bin có sẵn

MAX_PIXELS = 1 << 20   # ảnh lớn hơn thế này chắc chắn là tệp hỏng (màn hình chỉ 152x486)


def image_size(img: bytes) -> tuple[int, int] | None:
    """(rộng, cao) đọc từ tiêu đề ảnh, không giải mã điểm ảnh."""
    if len(img) < 16 or img[:2] != b"BM":
        return None
    if int.from_bytes(img[2:4], "little") == 0xFFFF:
        return struct.unpack_from("<2I", img, 4) if len(img) >= 24 else None
    return struct.unpack_from("<2H", img, 4)


def decode_image(img: bytes) -> tuple[int, int, bytes] | None:
    """(rộng, cao, RGBA) của một ảnh trong tệp mặt đồng hồ; None nếu là kiểu chưa hỗ trợ hoặc ảnh hỏng."""
    if len(img) < 16 or img[:2] != b"BM":
        return None
    fmt, w, h, row, bpp, ncolors, transparent = struct.unpack_from("<7H", img, 2)
    if fmt == 0x65:
        return _decode_compressed(img)
    if fmt == 0xFFFF:
        return _decode_32bit(img)
    if not w or not h or w * h > MAX_PIXELS:
        return None
    if ncolors:
        base = 16 + ncolors * 4
        if bpp not in (1, 2, 4, 8) or row * 8 < w * bpp or base + row * h > len(img):
            return None
        palette = [bytes((img[16 + i * 4], img[17 + i * 4], img[18 + i * 4], 0 if i == transparent - 1 else 255))
                   for i in range(min(ncolors, 256))]
        palette += [bytes(4)] * (256 - len(palette))   # chỉ số ngoài bảng màu: trong suốt
        per, mask = 8 // bpp, (1 << bpp) - 1
        # mỗi byte ảnh → RGBA của (8 / bpp) điểm ảnh trong byte đó, từ bit cao xuống
        table = [b"".join(palette[(byte >> (8 - (k + 1) * bpp)) & mask] for k in range(per)) for byte in range(256)]
        return w, h, b"".join(b"".join(map(table.__getitem__, img[base + y * row:base + (y + 1) * row]))[:w * 4]
                              for y in range(h))
    if bpp not in (16, 24, 32) or row * 8 < w * bpp or 16 + row * h > len(img):
        return None
    out = bytearray(w * h * 4)
    step = bpp // 8
    for y in range(h):
        for x in range(w):
            p = 16 + y * row + x * step
            if step == 4:
                r, g, b, a = img[p], img[p + 1], img[p + 2], img[p + 3]
            else:
                if step == 3:
                    a, v = img[p], (img[p + 1] << 8) | img[p + 2]
                else:
                    a, v = 0, img[p] | (img[p + 1] << 8)
                if fmt == 0x13:   # 4:4:4:4 ABGR
                    a, b, g, r = (v & 0xF000) >> 8, (v & 0x0F00) >> 4, v & 0x00F0, (v & 0x000F) << 4
                elif fmt in (0x1C, 0x09):   # 5:6:5 RGB
                    r, g, b = (v & 0xF800) >> 8, (v & 0x07E0) >> 3, (v & 0x001F) << 3
                else:   # 5:6:5 BGR
                    b, g, r = (v & 0xF800) >> 8, (v & 0x07E0) >> 3, (v & 0x001F) << 3
            i = (y * w + x) * 4
            out[i:i + 4] = bytes([r, g, b, 0xFF - a])   # trong tệp, 0 là đặc
    return w, h, bytes(out)


def _decode_compressed(img: bytes) -> tuple[int, int, bytes] | None:
    """Ảnh nén (kiểu 0x65): các khối (y, x, số điểm) rồi điểm ảnh RGB565; chỗ không có khối là trong suốt."""
    _fmt, w, h, _row, bpp = struct.unpack_from("<5H", img, 2)
    if bpp != 16 or not w or not h or w * h > MAX_PIXELS:
        return None
    out = bytearray(w * h * 4)
    pos, end = 16, min(16 + int.from_bytes(img[12:16], "little"), len(img))
    while pos + 6 <= end:
        y, x, n = struct.unpack_from("<3H", img, pos)
        pos += 6
        for _ in range(n):
            if pos + 2 > end:
                break
            v = img[pos] | (img[pos + 1] << 8)
            pos += 2
            if x < w and y < h:
                i = (y * w + x) * 4
                out[i:i + 4] = bytes(((v & 0xF800) >> 8, (v & 0x07E0) >> 3, (v & 0x001F) << 3, 255))
            x += 1
    return w, h, bytes(out)


def _decode_32bit(img: bytes) -> tuple[int, int, bytes] | None:
    """Ảnh 32 bit (kiểu 0xFFFF): tiêu đề 24 byte rồi RGBA thường (không đảo độ trong suốt)."""
    if len(img) < 24:
        return None
    w, h, bpp = struct.unpack_from("<3I", img, 4)
    if bpp != 32 or not w or not h or w * h > MAX_PIXELS or 24 + w * h * 4 > len(img):
        return None
    return w, h, bytes(img[24:24 + w * h * 4])


def png(width: int, height: int, rgba: bytes) -> bytes:
    """Mã hóa RGBA thành PNG (để trình duyệt hiện ảnh xem trước)."""
    import zlib

    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- vẽ mặt đồng hồ như vòng tay vẽ
#
# Theo previewGenerator của watchface-js: mỗi phần tử (giờ, ngày, pin, ảnh động…) được vẽ từ các ảnh trong
# tệp, theo đúng thứ tự và cách canh lề vòng tay dùng, với một bộ số liệu mẫu (`face_status`). Nhờ vậy khung
# mô phỏng hiện đúng mặt đồng hồ, kể cả khi ảnh xem trước nhúng trong tệp chỉ là ảnh nhỏ có hình mờ của
# công cụ tạo ra nó, hoặc thiếu phần ảnh động.

ANIMATION_MIN_MS = 80   # vòng tay thật không đổi khung nhanh hơn khoảng 80 ms


def face_status(now: _dt.datetime | None = None, *, time_24h: bool = True, metric: bool = True,
                battery: int | None = None, steps: int | None = None, goal: int | None = None,
                calories: int | None = None, meters: int | None = None, pulse: int | None = None) -> dict:
    """Số liệu để vẽ mặt đồng hồ: giờ theo `now`, số liệu thật nếu có, còn lại là số mẫu."""
    now = now or _dt.datetime.now()
    steps = 6543 if steps is None else steps
    calories = 245 if calories is None else calories
    pulse = 72 if pulse is None else pulse or None   # 0: chưa đo được
    km = (meters if meters is not None else 4200) / 1000
    distance = km if metric else km / 1.609344
    return {
        "hours": now.hour, "minutes": now.minute, "seconds": now.second, "time_24h": time_24h,
        "year": now.year, "month": now.month, "day": now.day, "weekday": now.isoweekday(),
        "steps": steps, "steps_pct": min(100, steps * 100 // max(goal or 8000, 1)),
        "calories": calories, "calories_pct": min(100, calories * 100 // 400),
        "pulse": pulse, "heart_pct": min(100, (pulse or 0) * 100 // 180),
        "distance": f"{distance:.1f}", "metric": metric, "pai": 42,
        "battery": 60 if battery is None else max(0, min(100, battery)),
        "dnd": True, "lock": False, "bluetooth": True,
        "weather": 1, "temp": 26, "temp_day": 31, "temp_night": 24, "humidity": 65, "wind": 3, "uvi": 4,
        "alarm": (7, 0), "alarm_on": True,
    }


def _node(value) -> dict:
    """Một nhánh tham số; nhánh lặp lại (danh sách) thì lấy phần tử đầu."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, dict) else {}


def _int(value, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _round(v: float) -> int:
    return math.floor(v + 0.5)   # như Math.round


def _align(lo: int, hi: int, size: int, flags: int) -> int:
    """Vị trí trong khung [lo, hi]: cờ 2 sát đầu, 4 sát cuối, còn lại ở giữa; không vượt ra trước lo."""
    if flags & 2:
        pos = lo
    elif flags & 4:
        pos = hi - size
    else:
        pos = _round((lo + hi) / 2 - size / 2)
    return max(pos, lo)


class _Painter:
    """Đổi tham số của mặt đồng hồ thành danh sách lệnh vẽ: ("img", ảnh, x, y), ("anim", …), ("hand", …)."""

    def __init__(self, images: list[bytes]):
        self.images = images
        self.ops: list[tuple] = []

    def size(self, index) -> tuple[int, int] | None:
        if not isinstance(index, int) or not 0 <= index < len(self.images):
            return None
        return image_size(self.images[index])

    def image(self, index, x, y) -> None:
        if self.size(index):
            self.ops.append(("img", index, _int(x), _int(y)))

    def single(self, p) -> None:   # Image: X, Y, ImageIndex
        p = _node(p)
        if 3 in p:
            self.image(p[3], p.get(1), p.get(2))

    def pick(self, p, k: int) -> None:   # ImageRange: ảnh thứ k
        p = _node(p)
        if 3 in p and 0 <= k < _int(p.get(4), 1):
            self.image(_int(p[3]) + k, p.get(1), p.get(2))

    def scale(self, p, pct: int) -> None:   # ImageRange theo phần trăm
        p = _node(p)
        self.pick(p, _round(pct / 100 * (_int(p.get(4), 1) - 1)))

    def linear(self, p, pct: int) -> None:   # các đoạn ảnh StartImageIndex + i tại từng tọa độ
        p = _node(p)
        segments = [_node(s) for s in (p.get(2) if isinstance(p.get(2), list) else [p.get(2)]) if s]
        if 1 not in p or not segments:
            return
        for i in range(_round(pct / 100 * (len(segments) - 1)) + 1):
            self.image(_int(p[1]) + i, segments[i].get(1), segments[i].get(2))

    def onoff(self, p, on: bool) -> None:   # StatusImage: tọa độ, ảnh bật, ảnh tắt
        p = _node(p)
        at = _node(p.get(1))
        key = 2 if on else 3
        if key in p:
            self.image(p[key], at.get(1), at.get(2))

    def digits(self, num: dict, text: str, point=None, minus=None) -> list:
        base, count = num.get(8), _int(num.get(9), 10)
        if not isinstance(base, int):   # phần tử không có trong mặt đồng hồ này
            return []
        ids = []
        for ch in text:
            if ch.isdigit():
                ids.append(base + int(ch) if int(ch) < count else None)
            else:
                ids.append(point if ch == "." else minus if ch == "-" else None)
        return ids

    def text(self, ids: list, num) -> None:   # Number: khung, canh lề, khoảng cách, bộ chữ số
        num = _node(num)
        items = [(i, self.size(i)) for i in ids]
        items = [(i, s) for i, s in items if s]
        if not items:
            return
        sx, sy, flags = _int(num.get(6)), _int(num.get(7)), _int(num.get(5))
        width = sum(w for _, (w, _) in items) + sx * (len(items) - 1)
        x = _align(_int(num.get(1)), _int(num.get(3)), width, flags)
        for k, (i, (w, h)) in enumerate(items):
            self.image(i, x, _align(_int(num.get(2)), _int(num.get(4)), h, flags >> 3) + k * sy)
            x += w + sx

    def number(self, p, value, *, prefix=None, suffix=None, nodata=None, point=None, minus=None,
               km=None, miles=None, pos_suffix=None, metric=True) -> None:
        """Số kèm tiền tố, hậu tố (id trường trong nhánh `p`); value None: ảnh "không có dữ liệu" nếu có."""
        p = _node(p)
        num = _node(p.get(1))
        if not num:
            return
        if value is None:
            if nodata not in p:
                return
            ids = [p[nodata]]
        else:
            ids = self.digits(num, str(value), p.get(point), p.get(minus))
        if prefix in p:
            ids.insert(0, p[prefix])
        for key in (suffix, km if metric else miles):
            if key in p:
                ids.append(p[key])
        self.text(ids, num)
        if pos_suffix in p:
            self.single(p[pos_suffix])

    def joined(self, p, values: list[str], *, delimiter, minus=None, suffix=None, all_suffix=None) -> None:
        """Nhiều số trên một dòng, cách nhau bằng ảnh `delimiter` (ngày một dòng, nhiệt độ ngày/đêm, báo thức)."""
        p = _node(p)
        num = _node(p.get(1))
        if not num:
            return
        ids: list = []
        for k, v in enumerate(values):
            if k:
                if all_suffix in p and p[all_suffix] and suffix in p:
                    ids.append(p[suffix])
                ids.append(p.get(delimiter))
            ids += self.digits(num, v, minus=p.get(minus))
        if suffix in p:
            ids.append(p[suffix])
        self.text(ids, num)

    def run(self, params: dict, st: dict) -> None:
        """Thứ tự vẽ như previewGenerator của watchface-js (mẫu UIHH_MIBAND)."""
        g = lambda *path: _get(params, path)  # noqa: E731
        hours = st["hours"] if st["time_24h"] else (st["hours"] % 12 or 12)
        metric = st["metric"]
        self.single(g(BACKGROUND, BG_IMAGE))
        for key, value in ((1, hours), (2, st["minutes"]), (3, st["seconds"])):
            pair = _node(g(TIME, key))
            if pair:
                self.pick(pair.get(1), value // 10)
                self.pick(pair.get(2), value % 10)
        self.single(g(TIME, 5))
        self.single(g(TIME, 6))
        self.number(g(4, 1), st["steps"], prefix=2, suffix=3)
        self.number(g(4, 3), st["calories"], suffix=2)
        self.number(g(4, 4), st["pulse"], prefix=2, nodata=3, suffix=4)
        self.number(g(4, 5), st["distance"], km=2, point=3, miles=4, metric=metric)
        self.number(g(4, 6), st["pai"])
        mdy = _node(g(5, 1))
        month = f"{st['month']:02d}" if mdy.get(4) else str(st["month"])
        day = f"{st['day']:02d}" if mdy.get(5) else str(st["day"])
        separate = _node(mdy.get(1))
        self.text(self.digits(_node(separate.get(1)), month), separate.get(1))
        self.pick(separate.get(2) or separate.get(3), st["month"] - 1)
        self.text(self.digits(_node(separate.get(4)), day), separate.get(4))
        self.joined(mdy.get(2), [month, day], delimiter=2)
        self.joined(mdy.get(3), [str(st["year"]), month, day], delimiter=2)
        ampm = _node(g(5, 2))
        if ampm and not st["time_24h"]:
            self.image(ampm.get(6 if st["hours"] >= 12 else 5), ampm.get(7) or ampm.get(1), ampm.get(8) or ampm.get(2))
        self.pick(g(5, 4) or g(5, 5) or g(5, 6), st["weekday"] - 1)
        self.pick(g(6, 1, 2), st["weather"] - 1)
        self.number(g(6, 2, 1), st["temp"], minus=2, suffix=3)
        self.number(g(6, 2, 2, 1, 1), st["temp_day"], minus=2, suffix=3)
        self.number(g(6, 2, 2, 1, 2), st["temp_night"], minus=2, suffix=3)
        self.joined(g(6, 2, 2, 2), [str(st["temp_day"]), str(st["temp_night"])], delimiter=3, minus=2, suffix=5,
                    all_suffix=4)
        self.number(g(6, 4), st["humidity"], suffix=2, pos_suffix=3)
        self.number(g(6, 5), st["wind"], suffix=2, pos_suffix=5)
        self.number(g(6, 6, 1), st["uvi"], suffix=2)
        self.scale(g(7, 2), st["steps_pct"])
        self.linear(g(7, 3), st["steps_pct"])
        for key, name in ((1, "dnd"), (2, "lock"), (3, "bluetooth")):
            self.onoff(g(8, key), st[name])
        self.number(g(9, 1), st["battery"], prefix=3, suffix=4)
        self.scale(g(9, 2), st["battery"])
        self.linear(g(9, 3), st["battery"])
        other = g(11, 1)
        for anim in other if isinstance(other, list) else [other]:
            anim = _node(anim)
            frames = _node(anim.get(1))
            if 3 in frames and _int(frames.get(4)) > 0:
                self.ops.append(("anim", _int(frames.get(1)), _int(frames.get(2)), _int(frames[3]),
                                 _int(frames[4]), max(_int(anim.get(2)), ANIMATION_MIN_MS)))
        self.scale(g(12, 2), st["heart_pct"])
        self.linear(g(12, 3), st["heart_pct"])
        self.scale(g(15, 2), st["calories_pct"])
        self.linear(g(15, 3), st["calories_pct"])
        self.single(g(14, st["weekday"]))
        alarm = _node(g(18))
        self.joined(alarm, [f"{st['alarm'][0]:02d}", f"{st['alarm'][1]:02d}"], delimiter=2)
        self.single(alarm.get(3 if st["alarm_on"] else 4))
        for key, name in ((1, "dnd"), (2, "lock"), (3, "bluetooth")):
            self.onoff(g(20, key), st[name])
        for key, value, total in ((1, st["hours"] % 12 + st["minutes"] / 60, 12), (2, st["minutes"], 60),
                                  (3, st["seconds"], 60)):
            hand = _node(g(10, key))
            shape = [_node(s) for s in (hand.get(4) if isinstance(hand.get(4), list) else [hand.get(4)]) if s]
            if len(shape) >= 2:
                center = _node(hand.get(3))
                self.ops.append(("hand", (_int(center.get(1)), _int(center.get(2))),
                                 [(_int(s.get(1)), _int(s.get(2))) for s in shape], _int(hand.get(2)) & 0xFFFFFF,
                                 bool(hand.get(1)), 2 * math.pi * value / total - math.pi / 2))
                self.single(hand.get(5))


def _get(tree, path: tuple):
    for key in path:
        tree = _node(tree).get(key)
        if tree is None:
            return None
    return tree


class _Layer:
    """Một lớp RGBA cỡ màn hình để ghép ảnh."""

    def __init__(self, fill: bytes = bytes(4)):
        self.px = bytearray(fill * (SCREEN_W * SCREEN_H))
        self.drawn = False

    def blit(self, w: int, h: int, rgba: bytes, x: int, y: int) -> None:
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, SCREEN_W), min(y + h, SCREEN_H)
        if x0 >= x1 or y0 >= y1:
            return
        self.drawn = True
        px, n = self.px, x1 - x0
        opaque, clear = b"\xff" * n, bytes(n)
        for sy in range(y0 - y, y1 - y):
            s = (sy * w + x0 - x) * 4
            src = rgba[s:s + n * 4]
            d = ((sy + y) * SCREEN_W + x0) * 4
            alpha = src[3::4]
            if alpha == opaque:
                px[d:d + n * 4] = src
            elif alpha != clear:
                for i in range(n):
                    a = src[i * 4 + 3]
                    if not a:
                        continue
                    j = d + i * 4
                    if a == 255:
                        px[j:j + 4] = src[i * 4:i * 4 + 4]
                        continue
                    below = px[j + 3] * (255 - a) // 255
                    out = a + below
                    for c in range(3):
                        px[j + c] = (src[i * 4 + c] * a + px[j + c] * below) // out
                    px[j + 3] = out

    def dot(self, x: int, y: int, rgb: int) -> None:
        if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
            i = (y * SCREEN_W + x) * 4
            self.px[i:i + 4] = bytes(((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF, 255))
            self.drawn = True

    def polygon(self, pts: list[tuple[float, float]], rgb: int, border: bool) -> None:
        if border:
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
                steps = max(1, _round(max(abs(bx - ax), abs(by - ay))))
                for k in range(steps + 1):
                    self.dot(_round(ax + (bx - ax) * k / steps), _round(ay + (by - ay) * k / steps), rgb)
            return
        top = max(0, math.floor(min(p[1] for p in pts)))
        bottom = min(SCREEN_H - 1, math.ceil(max(p[1] for p in pts)))
        for y in range(top, bottom + 1):
            yc = y + 0.5
            xs = sorted(ax + (yc - ay) * (bx - ax) / (by - ay)
                        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1])
                        if (ay <= yc < by) or (by <= yc < ay))
            for a, b in zip(xs[::2], xs[1::2]):
                for x in range(math.ceil(a - 0.5), math.floor(b - 0.5) + 1):
                    self.dot(x, y, rgb)


def scene(data: bytes, status: dict | None = None) -> dict | None:
    """Các lớp để vẽ mặt đồng hồ trong tệp như vòng tay vẽ, hoặc None nếu không đọc được.

    {"below": RGBA 152x486 các phần vẽ trước ảnh động, "above": RGBA phần vẽ sau ảnh động hoặc None,
     "animations": [{"x", "y", "interval" (ms mỗi khung), "frames": [(rộng, cao, RGBA), …]}]}"""
    try:
        params, images = parse(data)
        painter = _Painter(images)
        painter.run(params, status or face_status())
        decoded: dict[int, tuple | None] = {}

        def image(i: int):
            if i not in decoded:
                decoded[i] = decode_image(images[i]) if 0 <= i < len(images) else None
            return decoded[i]

        below, above, animations = _Layer(b"\x00\x00\x00\xff"), None, []
        layer = below
        for op in painter.ops:
            if op[0] == "img":
                shot = image(op[1])
                if shot:
                    layer.blit(*shot, op[2], op[3])
            elif op[0] == "anim":
                _kind, x, y, first, count, interval = op
                frames = [f for f in (image(first + k) for k in range(count)) if f]
                if frames:
                    animations.append({"x": x, "y": y, "interval": interval, "frames": frames})
                    if above is None:
                        layer = above = _Layer()
            else:
                _kind, (cx, cy), shape, rgb, border, angle = op
                cos, sin = math.cos(angle), math.sin(angle)
                layer.polygon([(cx + px * cos - py * sin, cy + px * sin + py * cos) for px, py in shape], rgb, border)
    except (ValueError, IndexError, KeyError, TypeError, struct.error, OverflowError):
        return None
    if not below.drawn and not animations:
        return None
    return {"below": bytes(below.px), "above": bytes(above.px) if above and above.drawn else None,
            "animations": animations}


def flatten(layers: dict) -> tuple[int, int, bytes]:
    """Ghép các lớp của `scene` thành một ảnh tĩnh 152x486 (khung đầu của ảnh động)."""
    out = _Layer()
    out.px[:] = layers["below"]
    for anim in layers["animations"]:
        out.blit(*anim["frames"][0], anim["x"], anim["y"])
    if layers["above"]:
        out.blit(SCREEN_W, SCREEN_H, layers["above"], 0, 0)
    return SCREEN_W, SCREEN_H, bytes(out.px)


def render(data: bytes, status: dict | None = None) -> tuple[int, int, bytes] | None:
    """Mặt đồng hồ trong tệp vẽ thành một ảnh tĩnh 152x486, hoặc None nếu không đọc được."""
    layers = scene(data, status)
    return flatten(layers) if layers else None


def embedded_preview(data: bytes) -> tuple[int, int, bytes] | None:
    """Ảnh xem trước nhúng trong tệp (thường là ảnh thu nhỏ cho danh sách mặt đồng hồ), hoặc ảnh nền."""
    try:
        params, images = parse(data)
        bg = _node(params.get(BACKGROUND))
        for key in (BG_PREVIEW_EN, BG_PREVIEW_CN, BG_IMAGE):
            ref = _node(bg.get(key))
            if ref and 0 <= _int(ref.get(3)) < len(images):
                decoded = decode_image(images[_int(ref.get(3))])
                if decoded:
                    return decoded
    except (ValueError, IndexError, KeyError, TypeError, struct.error):
        pass
    return None


def preview_png(data: bytes, status: dict | None = None) -> bytes | None:
    """Ảnh PNG của mặt đồng hồ trong tệp: vẽ từ các lớp ảnh, nếu không được thì ảnh xem trước nhúng sẵn."""
    shot = render(data, status) or embedded_preview(data)
    return png(*shot) if shot else None
