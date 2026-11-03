"""Vòng tay giả lập: đóng vai Mi Band 6 phía thiết bị.

Dùng cho kiểm thử tự động và cho chế độ xem thử giao diện (miband6-app --demo).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import random
import struct
import zlib

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
                  P.CHAR_DEVICE_EVENT, P.CHAR_CHUNKED, P.CHAR_CURRENT_TIME, P.CHAR_FETCH, P.CHAR_ACTIVITY_DATA]
        if with_2021_chars:
            miband += [P.CHAR_CHUNKED_2021_WRITE, P.CHAR_CHUNKED_2021_READ]
        self.services = [
            FakeService(P.SVC_MIBAND, miband),
            FakeService(P.SVC_MIBAND2, [P.CHAR_AUTH]),
            FakeService(P.SVC_HEART_RATE, [P.CHAR_HR_MEASUREMENT, P.CHAR_HR_CONTROL]),
            FakeService(P.SVC_DEVICE_INFO, list(P.DEVICE_INFO_CHARS.values())),
            FakeService(P.SVC_ALERT_NOTIFICATION, [P.CHAR_NEW_ALERT]),
            FakeService(P.SVC_IMMEDIATE_ALERT, [P.CHAR_ALERT_LEVEL]),
            FakeService(P.SVC_FIRMWARE, [P.CHAR_FW_CONTROL, P.CHAR_FW_DATA]),
        ]
        self.mtu_size = 247
        self.health = DemoHealth()
        self.fetch_requests: list[tuple[int, dt.datetime]] = []
        self.fetch_acks = 0               # lệnh 03: ứng dụng không bao giờ được gửi
        self._fetch_pending: bytes = b""
        self.fw_chunk = 4096
        self.fw_info: bytes | None = None
        self._fw_rx = bytearray()
        self.installed_watchface: bytes | None = None
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
        elif u == P.CHAR_FETCH:
            self._fetch_command(data)
        elif u == P.CHAR_FW_CONTROL:
            self._fw_command(data)
        elif u == P.CHAR_FW_DATA:
            self._fw_data(data)
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

    # ---- dữ liệu sức khỏe -------------------------------------------------------
    def _fetch_command(self, data):
        loop = asyncio.get_running_loop()
        if data[0] == P.FETCH_CMD_START:
            year = data[2] | (data[3] << 8)
            since = dt.datetime(year, data[4], data[5], data[6], data[7]).astimezone()
            self.fetch_requests.append((data[1], since))
            start, payload = self.health.fetch(data[1], since)
            self._fetch_pending = payload
            start = start or since
            q = P._tz_quarters(start) & 0xFF
            resp = bytes([0x10, 0x01, 0x01]) + len(payload).to_bytes(4, "little") + bytes(
                [start.year & 0xFF, start.year >> 8, start.month, start.day, start.hour, start.minute, start.second, q])
            loop.call_soon(self._notify, P.CHAR_FETCH, resp)
        elif data[0] == P.FETCH_CMD_DATA:
            payload, self._fetch_pending = self._fetch_pending, b""
            for n, i in enumerate(range(0, len(payload), 240)):
                loop.call_soon(self._notify, P.CHAR_ACTIVITY_DATA, bytes([n & 0xFF]) + payload[i:i + 240])
            loop.call_soon(self._notify, P.CHAR_FETCH, bytes([0x10, 0x02, 0x01]))
        elif data[0] == 0x03:
            self.fetch_acks += 1

    # ---- cài mặt đồng hồ --------------------------------------------------------
    def _fw_command(self, data):
        loop = asyncio.get_running_loop()
        reply = lambda *b: loop.call_soon(self._notify, P.CHAR_FW_CONTROL, bytes([0x10, *b]))  # noqa: E731
        cmd = data[0]
        if cmd == P.FW_REQUEST_PARAMS:
            reply(cmd, 0x01, 0x00, self.fw_chunk & 0xFF, self.fw_chunk >> 8)
        elif cmd == P.FW_SEND_INFO:
            self.fw_info = bytes(data)
            self._fw_rx = bytearray()
            reply(cmd, 0x01)
        elif cmd == P.FW_START_TRANSFER:
            reply(cmd, 0x01)
        elif cmd == P.FW_COMPLETE:
            size = int.from_bytes(self.fw_info[2:6], "little")
            crc = int.from_bytes(self.fw_info[6:10], "little")
            ok = len(self._fw_rx) == size and zlib.crc32(self._fw_rx) & 0xFFFFFFFF == crc
            reply(cmd, 0x01 if ok else 0x02)
        elif cmd == P.FW_FINALIZE:
            self.installed_watchface = bytes(self._fw_rx)
            reply(cmd, 0x01)

    def _fw_data(self, data):
        self._fw_rx += data
        size = int.from_bytes(self.fw_info[2:6], "little")
        if len(self._fw_rx) % self.fw_chunk == 0 or len(self._fw_rx) >= size:
            n = len(self._fw_rx)
            asyncio.get_running_loop().call_soon(
                self._notify, P.CHAR_FW_CONTROL, bytes([0x10, P.FW_PROGRESS]) + n.to_bytes(4, "little"))

    def press_find_phone(self):
        self._notify(P.CHAR_DEVICE_EVENT, bytes([P.EVENT_FIND_PHONE_START]))

    def drop(self):
        """Giả lập vòng tay mất kết nối (ra khỏi vùng phủ sóng, máy Mac ngủ…)."""
        self.is_connected = False
        self._hr_live = False
        if self.disconnected_callback:
            self.disconnected_callback(self)


class DemoHealth:
    """Dữ liệu sức khỏe giả lập cho 10 ngày gần nhất: ngủ đêm, đi bộ ban ngày, PAI, căng thẳng, SpO2, buổi tập.

    Mỗi lần lấy chỉ trả tối đa một ngày dữ liệu theo phút, như vòng tay thật cần nhiều lượt."""

    DAYS = 10

    def __init__(self, now: dt.datetime | None = None):
        now = (now or dt.datetime.now().astimezone()).replace(second=0, microsecond=0)
        self.now = now
        self.start = (now - dt.timedelta(days=self.DAYS)).replace(hour=0, minute=0)
        rnd = random.Random(6)
        self.activity = bytearray()
        self.stress = bytearray()
        # Như Mi Band 6 thật: 4 bit thấp của byte đầu là mốc trạng thái (9 ngủ nông, 11 ngủ sâu, 12 thức dậy,
        # 1 hoạt động), chỉ ghi khi đổi trạng thái và trễ chừng 11 phút; các phút khác mang 0 (không đổi).
        # Byte thứ 6 ("ngủ") tăng lúc thiếp đi và tụt khi tỉnh dậy. Giấc thật: 23:20 tới 06:50.
        fall, wake = 23 * 60 + 20, 6 * 60 + 50
        t = self.start
        state = None
        while t < now:
            m = t.hour * 60 + t.minute
            since_fall = (m - fall) % 1440   # phút kể từ lúc thiếp đi (đêm qua)
            asleep = since_fall < (wake - fall) % 1440
            lag = (m - 11 - fall) % 1440 < (wake - fall) % 1440   # trạng thái vòng tay ghi (trễ 11 phút)
            cycle = since_fall % 90
            deep = lag and cycle < 25 and since_fall < 300
            want = (11 if deep else 9) if lag else 1
            marker = want != state
            state = want
            if asleep or lag:
                level = 55 if asleep else 38 if m == wake else max(0, 25 - 3 * ((m - wake) % 1440))   # byte "ngủ"
                kind = (0xF0 | want) if marker else 0xF0
                hr = 52 + rnd.randint(0, 8)
                self.activity += bytes([kind if lag else 0x50, 0, 0, hr, 0, level, 0x80 | (60 if deep else 35), 0])
                self.stress.append(0xFF)
            else:
                onset = (fall - m) % 1440 <= 10   # 10 phút trước khi ngủ: byte "ngủ" bắt đầu tăng
                walking = (m // 20) % 4 == 0 and 7 * 60 < m < 21 * 60
                steps = rnd.randint(70, 115) if walking else rnd.choice([0, 0, 0, rnd.randint(1, 30)])
                hr = rnd.randint(95, 120) if walking else rnd.randint(62, 82)
                kind = (0x10 | (12 if (m - wake) % 1440 == 11 else 1)) if marker else 0x50
                level = max(0, 9 - (fall - m) % 1440) if onset else 0   # dưới ngưỡng thiếp đi
                self.activity += bytes([kind, min(255, steps * 2), steps, hr, 0, level, 0x80, 0])
                self.stress.append(rnd.randint(15, 70) if m % 5 == 0 else 0xFF)
            t += dt.timedelta(minutes=1)
        days = [(self.start + dt.timedelta(days=i)) for i in range(self.DAYS + 1)]
        self.pai = b""
        total = 40.0
        for i, d in enumerate(days):
            today = 8.0 + (i * 7) % 15
            total = min(150.0, total * 0.92 + today)
            rec = bytes([5]) + int(d.replace(hour=12).timestamp()).to_bytes(4, "little") + bytes([32]) + bytes(31)
            rec += struct.pack("<fffhhhff", 2.0, today * 0.6, today * 0.4, 30, 25, 6, today, total) + bytes(39)
            self.pai += rec
        self.spo2 = [(int(d.replace(hour=7, minute=10).timestamp()), 96 + i % 3, True) for i, d in enumerate(days[:-1])]
        self.spo2.append((int((now - dt.timedelta(hours=2)).timestamp()), 98, False))
        self.stress_manual = [(int((now - dt.timedelta(hours=3)).timestamp()), 34)]
        self.workouts = []
        for i, (kind, minutes, dist, cal, steps) in enumerate([(1, 32, 5200, 330, 5600), (3, 45, 3400, 180, 4700),
                                                                (4, 50, 15800, 420, 0)]):
            st = (now - dt.timedelta(days=2 * i + 1)).replace(hour=18, minute=5)
            self.workouts.append((st, self._summary(kind, st, minutes, dist, cal, steps, 132 + i * 5, 164)))
        old = (now - dt.timedelta(days=45)).replace(hour=7, minute=30)   # cũ hơn lần đồng bộ đầu (30 ngày)
        self.workouts.append((old, self._summary(5, old, 60, 0, 380, 300, 118, 150)))

    @staticmethod
    def _summary(kind, start, minutes, distance, calories, steps, avg_hr, max_hr) -> bytes:
        t0 = int(start.timestamp())
        head = struct.pack("<hHII", 515, kind, t0, t0 + minutes * 60) + bytes(12)
        body = struct.pack("<ii", steps, minutes * 60) + bytes(16) + struct.pack("<ff", calories, distance)
        body += bytes(5 * 4 + 3 * 4 + 3 * 4 + 3 * 4 + 3 * 4 + 4 + 4) + struct.pack("<hhhh", avg_hr, 360, 90, max_hr)
        return head + body + bytes(28)

    def fetch(self, kind: int, since: dt.datetime) -> tuple[dt.datetime | None, bytes]:
        if kind in (P.FETCH_ACTIVITY, P.FETCH_STRESS_AUTO):
            first = max(0, int((since - self.start).total_seconds() // 60))
            size = 8 if kind == P.FETCH_ACTIVITY else 1   # byte mỗi phút
            data = self.activity if kind == P.FETCH_ACTIVITY else self.stress
            chunk = data[first * size:(first + 1440) * size]
            return (self.start + dt.timedelta(minutes=first), bytes(chunk)) if chunk else (None, b"")
        if kind == P.FETCH_PAI:
            recs = [self.pai[i:i + 102] for i in range(0, len(self.pai), 102)]
            recs = [r for r in recs if int.from_bytes(r[1:5], "little") >= since.timestamp()]
            return (since, b"".join(recs)) if recs else (None, b"")
        if kind == P.FETCH_SPO2:
            recs = [r for r in self.spo2 if r[0] >= since.timestamp()]
            if not recs:
                return None, b""
            return since, bytes([2]) + b"".join(ts.to_bytes(4, "little") + bytes([v + 128 if auto else v]) + bytes(60)
                                                for ts, v, auto in recs)
        if kind == P.FETCH_STRESS_MANUAL:
            recs = [r for r in self.stress_manual if r[0] >= since.timestamp()]
            return (since, b"".join(ts.to_bytes(4, "little") + bytes([v]) for ts, v in recs)) if recs else (None, b"")
        if kind == P.FETCH_SPORTS_SUMMARY:
            for st, raw in sorted(self.workouts):
                if st >= since:
                    return st, raw
        return None, b""


class DemoDevice:
    """Thay cho BLEDevice khi chạy chế độ xem thử."""

    name = "Mi Smart Band 6 (demo)"
    address = "00000000-DEMO-0000-0000-000000000006"
