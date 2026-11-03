"""Dựng tệp mặt đồng hồ Mi Band 6 (.bin dạng UIHH) từ ảnh nền tùy chọn và các chữ số giờ.

Hàm thuần, dễ kiểm thử. Định dạng theo mô tả của cộng đồng (dự án watchface-js, mẫu "UIHH_MIBAND"):

    tiêu đề 87 byte  |  mục lục tham số  |  tham số  |  bảng vị trí ảnh  |  các ảnh

- Tham số mã hóa kiểu protobuf: khóa (id << 3, hoặc | 2 nếu là nhóm con) rồi giá trị varint.
- Mỗi ảnh: "BM" + tiêu đề 16 byte, rồi điểm ảnh 24 bit: 1 byte độ trong suốt (0 = đặc) và
  màu RGB565 xếp BGR, big-endian.
"""

from __future__ import annotations

SCREEN_W, SCREEN_H = 152, 486
HEADER = bytes.fromhex(
    "554948480100ffffffffff01b5e53d003d0030270000ab860900ffffffffffff00ff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffff0000000000000000"
)
PARAM_BUFFER_POS = len(HEADER) - 8     # cỡ tham số lớn nhất (vòng tay bỏ qua tham số lớn hơn)
PARAM_INFO_SIZE_POS = len(HEADER) - 4  # cỡ phần mục lục tham số

# id tham số (mẫu UIHH_MIBAND)
BACKGROUND, TIME = 2, 3
BG_IMAGE, BG_PREVIEW_EN, BG_PREVIEW_CN, BG_PREVIEW_CN2 = 1, 3, 4, 5
TIME_HOURS, TIME_MINUTES = 1, 2
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
    head = b"BM" + b"".join(v.to_bytes(2, "little") for v in (0x1B, width, height, width * 3, 24, 0, 0))
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
    header = bytearray(HEADER)
    header[PARAM_BUFFER_POS:PARAM_BUFFER_POS + 4] = max((len(b) for b in blobs), default=0).to_bytes(4, "little")
    header[PARAM_INFO_SIZE_POS:PARAM_INFO_SIZE_POS + 4] = len(info_blob).to_bytes(4, "little")
    return bytes(header) + info_blob + b"".join(blobs) + bytes(table) + b"".join(images)


def wallpaper_face(background: bytes, preview: tuple[int, int, bytes], digits: list[tuple[int, int, bytes]],
                   hours_xy: tuple[int, int] | None, minutes_xy: tuple[int, int] | None) -> bytes:
    """Mặt đồng hồ "ảnh nền": nền 152x486 (RGBA) và giờ, phút xếp chồng (mỗi hàng hai chữ số).

    digits: 10 ảnh chữ số 0-9 cùng cỡ (rộng, cao, RGBA); hours_xy/minutes_xy: góc trên trái của hàng
    giờ / phút, hoặc None để không hiện giờ."""
    if len(background) != SCREEN_W * SCREEN_H * 4:
        raise ValueError("ảnh nền phải đúng 152x486")
    images = [image_24bit(SCREEN_W, SCREEN_H, background), image_24bit(*preview)]
    bg_img = {1: 0, 2: 0, 3: 0}
    pv_img = {1: 0, 2: 0, 3: 1}
    params: dict[int, dict] = {BACKGROUND: {BG_IMAGE: bg_img, BG_PREVIEW_EN: pv_img, BG_PREVIEW_CN: pv_img,
                                            BG_PREVIEW_CN2: pv_img}}
    if hours_xy and minutes_xy:
        if len(digits) != 10 or len({(w, h) for w, h, _ in digits}) != 1:
            raise ValueError("cần 10 ảnh chữ số cùng kích thước")
        first = len(images)
        images += [image_24bit(*d) for d in digits]
        w = digits[0][0]

        def row(x: int, y: int) -> dict:
            return {DIGIT_TENS: {1: x, 2: y, 3: first, 4: 10}, DIGIT_ONES: {1: x + w, 2: y, 3: first, 4: 10}}

        params[TIME] = {TIME_HOURS: row(*hours_xy), TIME_MINUTES: row(*minutes_xy)}
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
        if key & 2:
            size, pos = read_varint(data, pos)
            value = decode_params(data[pos:pos + size])
            pos += size
        else:
            value, pos = read_varint(data, pos)
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
    pos = len(HEADER)
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


# ---------------------------------------------------------------- ảnh xem trước của tệp .bin có sẵn


def decode_image(img: bytes) -> tuple[int, int, bytes] | None:
    """(rộng, cao, RGBA) của một ảnh trong tệp mặt đồng hồ; None nếu là kiểu chưa hỗ trợ (ảnh nén)."""
    import struct

    if len(img) < 16 or img[:2] != b"BM":
        return None
    fmt, w, h, row, bpp, ncolors, transparent = struct.unpack_from("<7H", img, 2)
    if fmt in (0x65, 0xFFFF) or not w or not h:
        return None
    out = bytearray(w * h * 4)
    if ncolors:
        if bpp not in (1, 2, 4, 8):
            return None
        palette = [bytes([img[16 + i * 4], img[17 + i * 4], img[18 + i * 4], 0 if i == transparent - 1 else 255])
                   for i in range(ncolors)]
        base = 16 + ncolors * 4
        per = 8 // bpp
        mask = (1 << bpp) - 1
        for y in range(h):
            for x in range(w):
                if bpp < 8:
                    byte = img[base + y * row + x // per]
                    ci = (byte >> (8 - ((x % per) + 1) * bpp)) & mask
                else:
                    ci = img[base + y * row + x]
                if ci < ncolors:
                    out[(y * w + x) * 4:(y * w + x) * 4 + 4] = palette[ci]
        return w, h, bytes(out)
    if bpp not in (16, 24, 32):
        return None
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


def png(width: int, height: int, rgba: bytes) -> bytes:
    """Mã hóa RGBA thành PNG (để trình duyệt hiện ảnh xem trước)."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def preview_png(data: bytes) -> bytes | None:
    """Ảnh xem trước (hoặc ảnh nền) lưu trong một tệp mặt đồng hồ Mi Band 6, dạng PNG; None nếu không đọc được."""
    try:
        params, images = parse(data)
        bg = params.get(BACKGROUND) or {}
        for key in (BG_PREVIEW_EN, BG_PREVIEW_CN, BG_IMAGE):
            ref = bg.get(key)
            if isinstance(ref, dict) and 0 <= ref.get(3, 0) < len(images):
                decoded = decode_image(images[ref.get(3, 0)])
                if decoded:
                    return png(*decoded)
    except (ValueError, IndexError, KeyError, TypeError):
        pass
    return None
