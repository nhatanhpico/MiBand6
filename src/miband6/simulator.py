"""Vòng tay giả lập: đóng vai Mi Band 6 phía thiết bị.

Dùng cho kiểm thử tự động và cho chế độ xem thử giao diện (miband6-app --demo).
"""

from __future__ import annotations

import asyncio
import os
import random

from miband6 import crypto
from miband6 import protocol as P


class FakeChar:
    def __init__(self, uuid, service):
        self.uuid = uuid
        self.service_uuid = service


class FakeService:
    def __init__(self, uuid, chars):
        self.uuid = uuid
        self.characteristics = [FakeChar(c, uuid) for c in chars]


class FakeBand:
    """mode: 'classic' (chỉ nhận xác thực cũ), '2021' (chỉ nhận xác thực mới), 'both'."""

    def __init__(self, key: bytes, mode: str = "classic", with_2021_chars: bool = True):
        self.key = key
        self.mode = mode
        miband = [P.CHAR_CONFIG, P.CHAR_BATTERY, P.CHAR_STEPS, P.CHAR_USER_SETTINGS,
                  P.CHAR_DEVICE_EVENT, P.CHAR_CHUNKED, P.CHAR_CURRENT_TIME]
        if with_2021_chars:
            miband += [P.CHAR_CHUNKED_2021_WRITE, P.CHAR_CHUNKED_2021_READ]
        self.services = [
            FakeService(P.SVC_MIBAND, miband),
            FakeService(P.SVC_MIBAND2, [P.CHAR_AUTH]),
            FakeService(P.SVC_HEART_RATE, [P.CHAR_HR_MEASUREMENT, P.CHAR_HR_CONTROL]),
            FakeService(P.SVC_DEVICE_INFO, list(P.DEVICE_INFO_CHARS.values())),
            FakeService(P.SVC_ALERT_NOTIFICATION, [P.CHAR_NEW_ALERT]),
            FakeService(P.SVC_IMMEDIATE_ALERT, [P.CHAR_ALERT_LEVEL]),
        ]
        self.is_connected = False
        self.disconnected_callback = None   # MiBand6 gắn vào, như BleakClient(disconnected_callback=…)
        self.callbacks = {}
        self.writes: list[tuple[str, bytes]] = []
        self.config_commands: list[bytes] = []   # lệnh cấu hình đã giải mã
        self.chunked_payloads: list[tuple[int, bytes]] = []
        self.authenticated = False
        self.hr_delay = 0.1
        self._hr_live = False
        self.verified_encrypted = 0
        self._random = None
        self._session = None
        self._expected_seq = None
        self._rx = crypto.ChunkedDecoder2021()
        self._tx = crypto.ChunkedEncoder2021()
        self._old_chunk = bytearray()
        self.alarms = [P.Alarm(0, True, 6, 30, 0b0011111), P.Alarm(2, False, 9, 0, 0)]
        self.values = {
            P.CHAR_BATTERY: bytes([0x0F, 87, 0x00, 0xEA, 0x07, 10, 30, 21, 5, 0, 4,
                                   0xEA, 0x07, 10, 30, 21, 5, 0, 4, 100]),
            P.CHAR_STEPS: bytes([0x0C]) + (6543).to_bytes(4, "little") + (4810).to_bytes(4, "little") + (231).to_bytes(4, "little"),
            P.CHAR_CURRENT_TIME: bytes([0xEA, 0x07, 11, 2, 21, 30, 0, 1, 0, 0, 32]),
            P.DEVICE_INFO_CHARS["firmware"]: b"1.0.6.16",
            P.DEVICE_INFO_CHARS["hardware"]: b"V0.80.19.2.9",
            P.DEVICE_INFO_CHARS["serial"]: b"39857/12345678",
            P.DEVICE_INFO_CHARS["software"]: b"0.0.0.1",
        }

    # ---- API giống BleakClient -------------------------------------------------
    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def start_notify(self, ch, cb):
        self.callbacks[ch.uuid] = cb

    async def read_gatt_char(self, ch):
        if ch.uuid not in self.values:
            raise RuntimeError("not readable")
        return bytearray(self.values[ch.uuid])

    async def write_gatt_char(self, ch, data, response=None):
        data = bytes(data)
        self.writes.append((ch.uuid, data))
        u = ch.uuid
        if u == P.CHAR_AUTH:
            self._classic(data)
        elif u == P.CHAR_CHUNKED_2021_WRITE:
            self._chunk_2021(data)
        elif u == P.CHAR_CHUNKED_2021_READ:
            pass  # ack
        elif u == P.CHAR_CONFIG:
            self._config(data)
        elif u == P.CHAR_CHUNKED:
            self._chunk_old(data)
        elif u == P.CHAR_HR_CONTROL:
            loop = asyncio.get_running_loop()
            if data == P.HR_START_MANUAL:
                loop.call_later(0.05, self._notify, P.CHAR_HR_MEASUREMENT, bytes([0, 0]))
                loop.call_later(self.hr_delay, self._notify, P.CHAR_HR_MEASUREMENT, bytes([0, 72]))
            elif data == P.HR_START_CONTINUOUS:
                self._hr_live = True
                loop.call_later(1.0, self._hr_tick)
            elif data == P.HR_STOP_CONTINUOUS:
                self._hr_live = False

    # ---- nội bộ ---------------------------------------------------------------
    def _hr_tick(self):
        if not (self._hr_live and self.is_connected):
            return
        self._notify(P.CHAR_HR_MEASUREMENT, bytes([0, random.randint(66, 84)]))
        asyncio.get_running_loop().call_later(1.0, self._hr_tick)

    def _notify(self, uuid, data):
        cb = self.callbacks.get(uuid)
        if cb:
            cb(None, bytearray(data))

    def _later(self, uuid, data):
        asyncio.get_running_loop().call_soon(self._notify, uuid, data)

    def _classic(self, data):
        if data[0] == 0x82:
            if self.mode == "2021":
                # firmware mới: từ chối kiểu cũ
                self._later(P.CHAR_AUTH, bytes([0x10, 0x82, 0x04]))
                return
            self._random = os.urandom(16)
            self._later(P.CHAR_AUTH, bytes([0x10, 0x82, 0x01]) + self._random)
        elif data[0] == 0x83:
            ok = crypto.aes_ecb_encrypt(self._random, self.key) == data[2:18]
            self.authenticated = ok
            self._later(P.CHAR_AUTH, bytes([0x10, 0x83, 0x01 if ok else 0x04]))

    def _send_2021(self, endpoint, payload, encrypt=False):
        for c in self._tx.encode(endpoint, payload, encrypt):
            # đánh dấu cần ack để kiểm thử nhánh gửi ack
            c = bytearray(c)
            self._later(P.CHAR_CHUNKED_2021_READ, bytes(c))

    def _verify_encrypted(self, data):
        """Kiểm tra độc lập: giải mã, so CRC32 và số thứ tự như firmware thật làm."""
        flags, handle = data[1], data[3]
        if flags & 0x01:
            self._raw = bytearray(data[11:])
            self._raw_len = int.from_bytes(data[5:9], "little")
        else:
            self._raw += data[5:]
        if flags & 0x02 and flags & 0x08:
            key = bytes(k ^ handle for k in self._session)
            plain = crypto.aes_ecb_decrypt(bytes(self._raw), key)
            n = self._raw_len
            assert crypto.crc32(plain[:n + 4]) == int.from_bytes(plain[n + 4:n + 8], "little"), "CRC sai"
            seq = int.from_bytes(plain[n:n + 4], "little")
            assert seq == self._expected_seq, f"seq {seq} != {self._expected_seq}"
            self._expected_seq += 1
            self.verified_encrypted += 1

    def _chunk_2021(self, data):
        if self._session is not None and self.authenticated:
            self._verify_encrypted(data)
        _, res = self._rx.decode(data)
        if res is None:
            return
        endpoint, payload = res
        if endpoint == crypto.ENDPOINT_AUTH:
            if payload[0] == 0x04:
                if self.mode == "classic":
                    self._send_2021(endpoint, bytes([0x10, 0x04, 0x25]))
                    return
                their_pub = payload[4:52]
                self._priv = crypto.ecdh_generate_private()
                my_pub = crypto.ecdh_public_key(self._priv)
                shared = crypto.ecdh_shared_secret(self._priv, their_pub)
                self._session = bytes(shared[8 + i] ^ self.key[i] for i in range(16))
                self._expected_seq = int.from_bytes(shared[0:4], "little")
                self._random = os.urandom(16)
                self._send_2021(endpoint, bytes([0x10, 0x04, 0x01]) + self._random + my_pub)
            elif payload[0] == 0x05:
                e1, e2 = payload[1:17], payload[17:33]
                ok = (e1 == crypto.aes_ecb_encrypt(self._random, self.key)
                      and e2 == crypto.aes_ecb_encrypt(self._random, self._session))
                self.authenticated = ok
                if ok:
                    self._rx.set_encryption(self._session)
                    self._tx.set_encryption(0, self._session)
                self._send_2021(endpoint, bytes([0x10, 0x05, 0x01 if ok else 0x25]))
        elif endpoint == crypto.ENDPOINT_COMPAT:
            if payload[:1] == b"\x01":
                self._config(payload[1:], via_2021=True)
            elif payload[:2] == b"\x00\x00":
                self.chunked_payloads.append((payload[2] & 0x0F, payload[4:]))

    def _chunk_old(self, data):
        flags = data[1]
        if data[2] == 0:
            self._old_chunk = bytearray()
        self._old_chunk += data[3:]
        if flags & 0x80:
            self.chunked_payloads.append((flags & 0x0F, bytes(self._old_chunk)))

    def _config(self, cmd, via_2021=False):
        self.config_commands.append(cmd)
        if cmd == P.REQUEST_ALARMS:
            body = bytes([len(self.alarms)])
            for a in self.alarms:
                body += bytes([(0x80 if a.enabled else 0) | a.slot, a.hour, a.minute, a.days or P.ONCE])
            resp = bytes([0x80, 0x01, 0xC0, 0x00, 0x01, 0x00, 0x00, 0x00]) + body
            if via_2021:
                self._send_2021(crypto.ENDPOINT_COMPAT, b"\x00" + resp, encrypt=True)
            else:
                self._later(P.CHAR_CONFIG, resp)
        else:
            ack = bytes([0x10, cmd[0], 0x01])
            if via_2021:
                self._send_2021(crypto.ENDPOINT_COMPAT, b"\x00" + ack, encrypt=True)
            else:
                self._later(P.CHAR_CONFIG, ack)

    def press_find_phone(self):
        self._notify(P.CHAR_DEVICE_EVENT, bytes([P.EVENT_FIND_PHONE_START]))

    def drop(self):
        """Giả lập vòng tay mất kết nối (ra khỏi vùng phủ sóng, máy Mac ngủ…)."""
        self.is_connected = False
        self._hr_live = False
        if self.disconnected_callback:
            self.disconnected_callback(self)


class DemoDevice:
    """Thay cho BLEDevice khi chạy chế độ xem thử."""

    name = "Mi Smart Band 6 (demo)"
    address = "00000000-DEMO-0000-0000-000000000006"
