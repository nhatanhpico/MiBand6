"""Mật mã dùng cho Mi Band 6.

- AES-128-ECB (không padding) cho bước xác thực.
- ECDH trên đường cong NIST B-163 (sect163r2) cho "giao thức xác thực mới"
  mà các firmware Mi Band 6 đời sau yêu cầu.  Khóa được mã hóa theo định
  dạng của thư viện tiny-ECDH mà vòng tay dùng: mỗi tọa độ là 24 byte
  little-endian (6 từ 32-bit), khóa công khai = x || y (48 byte).
"""

from __future__ import annotations

import os
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ---------------------------------------------------------------------------
# AES
# ---------------------------------------------------------------------------


def aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    if len(data) % 16:
        raise ValueError("AES-ECB cần dữ liệu là bội số của 16 byte")
    enc = Cipher(algorithms.AES(bytes(key)), modes.ECB()).encryptor()
    return enc.update(bytes(data)) + enc.finalize()


def aes_ecb_decrypt(data: bytes, key: bytes) -> bytes:
    if len(data) % 16:
        raise ValueError("AES-ECB cần dữ liệu là bội số của 16 byte")
    dec = Cipher(algorithms.AES(bytes(key)), modes.ECB()).decryptor()
    return dec.update(bytes(data)) + dec.finalize()


def crc32(data: bytes) -> int:
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# GF(2^163) và đường cong B-163:  y^2 + xy = x^3 + a*x^2 + b,  a = 1
# ---------------------------------------------------------------------------

def _words(ws: list[int]) -> int:
    """Ghép các từ 32-bit little-endian (thứ tự như trong tiny-ECDH) thành số nguyên."""
    return sum(w << (32 * i) for i, w in enumerate(ws))


_M = 163
_F = _words([0x000000C9, 0, 0, 0, 0, 0x00000008])  # x^163 + x^7 + x^6 + x^3 + 1
_B = _words([0x4A3205FD, 0x512F7874, 0x1481EB10, 0xB8C953CA, 0x0A601907, 0x00000002])
_GX = _words([0xE8343E36, 0xD4994637, 0xA0991168, 0x86A2D57E, 0xF0EBA162, 0x00000003])
_GY = _words([0x797324F1, 0xB11C5C0C, 0xA2CDD545, 0x71A0094F, 0xD51FBC6C, 0x00000000])
_ORDER = _words([0xA4234C33, 0x77E70C12, 0x000292FE, 0, 0, 0x00000004])
_ORDER_BITS = _ORDER.bit_length()  # 163

COORD_BYTES = 24
PRIVATE_KEY_BYTES = 24
PUBLIC_KEY_BYTES = 48


def _reduce(x: int) -> int:
    while x.bit_length() > _M:
        x ^= _F << (x.bit_length() - 1 - _M)
    return x


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
    return _reduce(r)


def _sqr(a: int) -> int:
    return _mul(a, a)


def _inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("nghịch đảo của 0")
    u, v = a, _F
    g1, g2 = 1, 0
    while u != 1:
        j = u.bit_length() - v.bit_length()
        if j < 0:
            u, v = v, u
            g1, g2 = g2, g1
            j = -j
        u ^= v << j
        g1 ^= g2 << j
    return _reduce(g1)


_Point = "tuple[int, int] | None"  # None = điểm vô cực


def _double(p):
    if p is None:
        return None
    x, y = p
    if x == 0:
        return None
    lam = _mul(_inv(x), y) ^ x
    x3 = _sqr(lam) ^ lam ^ 1
    y3 = _sqr(x) ^ _mul(lam ^ 1, x3)
    return (x3, y3)


def _add(p, q):
    if q is None:
        return p
    if p is None:
        return q
    x1, y1 = p
    x2, y2 = q
    if x1 == x2:
        if y1 == y2:
            return _double(p)
        return None
    lam = _mul(_inv(x1 ^ x2), y1 ^ y2)
    x3 = _sqr(lam) ^ lam ^ x1 ^ x2 ^ 1
    y3 = _mul(lam, x1 ^ x3) ^ x3 ^ y1
    return (x3, y3)


def _scalar_mul(k: int, p):
    r = None
    for i in range(k.bit_length() - 1, -1, -1):
        r = _double(r)
        if (k >> i) & 1:
            r = _add(r, p)
    return r


def _on_curve(x: int, y: int) -> bool:
    lhs = _sqr(y) ^ _mul(x, y)
    rhs = _mul(_sqr(x), x) ^ _sqr(x) ^ _B
    return lhs == rhs


def _int_le(b: bytes) -> int:
    return int.from_bytes(bytes(b), "little")


def _le(x: int, n: int = COORD_BYTES) -> bytes:
    return x.to_bytes(n, "little")


def _point_bytes(p) -> bytes:
    if p is None:
        return bytes(PUBLIC_KEY_BYTES)
    return _le(p[0]) + _le(p[1])


def _clamp_private(priv: bytes) -> int:
    k = _int_le(priv)
    # tiny-ECDH xóa các bit >= (bậc - 1) để bảo đảm 1 <= k < n
    return k & ((1 << (_ORDER_BITS - 1)) - 1)


def ecdh_generate_private(rng=os.urandom) -> bytes:
    while True:
        priv = rng(PRIVATE_KEY_BYTES)
        # tiny-ECDH từ chối khóa quá nhỏ (kiểm tra trước khi xóa bit cao)
        if _int_le(priv).bit_length() >= _M // 2:
            return priv


def ecdh_public_key(priv: bytes) -> bytes:
    if _int_le(priv).bit_length() < _M // 2:
        raise ValueError("khóa riêng quá nhỏ")
    return _point_bytes(_scalar_mul(_clamp_private(priv), (_GX, _GY)))


def ecdh_shared_secret(priv: bytes, remote_public: bytes) -> bytes:
    if len(remote_public) < PUBLIC_KEY_BYTES:
        raise ValueError("khóa công khai của vòng tay quá ngắn")
    x = _int_le(remote_public[:COORD_BYTES])
    y = _int_le(remote_public[COORD_BYTES:PUBLIC_KEY_BYTES])
    if (x == 0 and y == 0) or not _on_curve(x, y):
        raise ValueError("khóa công khai của vòng tay không nằm trên đường cong B-163")
    return _point_bytes(_scalar_mul(_clamp_private(priv), (x, y)))


# ---------------------------------------------------------------------------
# Truyền theo khối "Huami 2021" (characteristic 0x0016 ghi / 0x0017 đọc)
# ---------------------------------------------------------------------------

ENDPOINT_AUTH = 0x0082
ENDPOINT_COMPAT = 0x0090


def _padded_len(n: int) -> int:
    n += 8
    return n + (-n % 16)


class ChunkedEncoder2021:
    """Chia dữ liệu thành các gói cho characteristic 0x0016 (chế độ extended flags)."""

    def __init__(self, mtu: int = 23):
        self.mtu = mtu
        self.handle = 0
        self.session_key: bytes | None = None
        self.seq = 0

    def set_encryption(self, seq: int, session_key: bytes) -> None:
        self.seq = seq & 0xFFFFFFFF
        self.session_key = bytes(session_key)

    def encode(self, endpoint: int, data: bytes, encrypt: bool) -> list[bytes]:
        if encrypt and self.session_key is None:
            raise RuntimeError("chưa có khóa phiên để mã hóa")
        self.handle = (self.handle + 1) & 0xFF
        data = bytes(data)
        length = len(data)
        if encrypt:
            msg_key = bytes(k ^ self.handle for k in self.session_key)
            buf = bytearray(_padded_len(length))
            buf[:length] = data
            buf[length:length + 4] = self.seq.to_bytes(4, "little")
            self.seq = (self.seq + 1) & 0xFFFFFFFF
            buf[length + 4:length + 8] = crc32(buf[:length + 4]).to_bytes(4, "little")
            data = aes_ecb_encrypt(bytes(buf), msg_key)

        chunks: list[bytes] = []
        remaining = len(data)
        count = 0
        header = 11
        while remaining > 0:
            max_len = self.mtu - 3 - header
            n = min(remaining, max_len)
            chunk = bytearray(header + n)
            flags = 0x08 if encrypt else 0
            if count == 0:
                flags |= 0x01
                chunk[5:9] = length.to_bytes(4, "little")
                chunk[9:11] = (endpoint & 0xFFFF).to_bytes(2, "little")
            if remaining <= max_len:
                flags |= 0x06
            chunk[0] = 0x03
            chunk[1] = flags
            chunk[2] = 0
            chunk[3] = self.handle
            chunk[4] = count & 0xFF
            start = len(data) - remaining
            chunk[header:] = data[start:start + n]
            chunks.append(bytes(chunk))
            remaining -= n
            header = 5
            count += 1
        return chunks


class ChunkedDecoder2021:
    """Ghép các gói nhận từ characteristic 0x0017. Trả về (endpoint, payload) khi đủ."""

    def __init__(self):
        self.session_key: bytes | None = None
        self._reset()
        self.last_handle = 0
        self.last_count = 0

    def _reset(self):
        self._handle = None
        self._endpoint = 0
        self._length = 0
        self._buf = bytearray()

    def set_encryption(self, session_key: bytes) -> None:
        self.session_key = bytes(session_key)

    def decode(self, data: bytes) -> tuple[bool, tuple[int, bytes] | None]:
        """Trả về (cần_ack, kết_quả_hoặc_None)."""
        data = bytes(data)
        if len(data) < 2 or data[0] != 0x03:
            return False, None
        flags = data[1]
        encrypted = bool(flags & 0x08)
        first = bool(flags & 0x01)
        last = bool(flags & 0x02)
        needs_ack = bool(flags & 0x04)
        i = 3  # bỏ qua byte header mở rộng
        handle = data[i]
        i += 1
        if self._handle is not None and self._handle != handle:
            return False, None
        self.last_handle = handle
        self.last_count = data[i]
        i += 1
        if first:
            self._length = int.from_bytes(data[i:i + 4], "little")
            i += 4
            self._endpoint = int.from_bytes(data[i:i + 2], "little")
            i += 2
            self._handle = handle
            self._buf = bytearray()
        self._buf += data[i:]
        if not last:
            return needs_ack, None
        buf = bytes(self._buf)
        endpoint, length = self._endpoint, self._length
        self._reset()
        if encrypted:
            if self.session_key is None:
                return needs_ack, None
            msg_key = bytes(k ^ handle for k in self.session_key)
            buf = aes_ecb_decrypt(buf[: len(buf) - len(buf) % 16], msg_key)[:length]
        return needs_ack, (endpoint, buf)

    def ack(self) -> bytes:
        return bytes([0x04, 0x00, self.last_handle, 0x01, self.last_count])
