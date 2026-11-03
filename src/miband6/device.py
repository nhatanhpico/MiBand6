"""Lớp kết nối bất đồng bộ tới Mi Smart Band 6 qua Bluetooth LE (dùng bleak)."""

from __future__ import annotations

import asyncio
import datetime as _dt
from typing import Any, Callable

from . import crypto
from . import protocol as P
from .i18n import tr

PROTOCOL_AUTO = "auto"
PROTOCOL_CLASSIC = "classic"
PROTOCOL_2021 = "2021"

EventCallback = Callable[[str, Any], None]
LogCallback = Callable[[str], None]


class AuthError(Exception):
    """Vòng tay từ chối auth key hoặc không phản hồi bước xác thực."""


class MiBandError(Exception):
    pass


def _hex(b: bytes) -> str:
    return bytes(b).hex(" ")


async def scan(timeout: float = 8.0, show_all: bool = False):
    """Quét thiết bị BLE. Trả về list (BLEDevice, rssi, có_phải_mi_band6)."""
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        is_band = P.looks_like_miband6(name) or P.SVC_MIBAND in [u.lower() for u in (adv.service_uuids or [])]
        if show_all or is_band:
            out.append((dev, adv.rssi, is_band, name))
    out.sort(key=lambda t: (not t[2], -(t[1] or -999)))
    return out


class MiBand6:
    def __init__(
        self,
        device: Any,
        auth_key: bytes,
        protocol: str = PROTOCOL_AUTO,
        on_event: EventCallback | None = None,
        log: LogCallback | None = None,
        client: Any = None,
        name: str = "",
    ):
        if len(auth_key) != 16:
            raise ValueError(tr('auth key phải dài 16 byte'))
        self.device = device
        self.auth_key = bytes(auth_key)
        self.protocol_pref = protocol
        self.protocol_used: str | None = None
        self.on_event = on_event or (lambda kind, data: None)
        self.log = log or (lambda msg: None)
        self.name = name or getattr(device, "name", "") or ""
        self._client = client
        self._chars: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._auth_q: asyncio.Queue = asyncio.Queue()
        self._enc = crypto.ChunkedEncoder2021()
        self._dec = crypto.ChunkedDecoder2021()
        self._config_rx = P.ConfigReassembler()
        self._alarms_future: asyncio.Future | None = None
        self._hr_future: asyncio.Future | None = None
        self._hr_ping_task: asyncio.Task | None = None
        self._find_task: asyncio.Task | None = None
        self._notifying: set[str] = set()
        self._closing = False
        self.authenticated = False
        # client thay thế (vòng tay giả lập) cũng báo khi rớt kết nối, giống disconnected_callback của BleakClient
        if client is not None and hasattr(client, "disconnected_callback"):
            client.disconnected_callback = self._on_disconnect

    # ------------------------------------------------------------------ helpers

    def _emit(self, kind: str, data: Any = None) -> None:
        try:
            self.on_event(kind, data)
        except Exception as e:  # không để lỗi giao diện làm hỏng luồng BLE
            self.log(tr('Lỗi xử lý sự kiện {kind}: {e}', kind=kind, e=e))

    def _index_characteristics(self) -> None:
        self._chars.clear()
        for svc in self._client.services:
            for ch in svc.characteristics:
                key = str(ch.uuid).lower()
                # ưu tiên bản đầu tiên; ghi thêm khóa có service để tra cứu chính xác
                self._chars.setdefault(key, ch)
                self._chars[f"{str(svc.uuid).lower()}/{key}"] = ch

    def has(self, uuid: str, service: str | None = None) -> bool:
        return self._char(uuid, service) is not None

    def _char(self, uuid: str, service: str | None = None):
        if service:
            return self._chars.get(f"{service.lower()}/{uuid.lower()}")
        return self._chars.get(uuid.lower())

    def _require(self, uuid: str, service: str | None = None):
        ch = self._char(uuid, service)
        if ch is None:
            raise MiBandError(tr('Vòng tay không có characteristic {uuid}', uuid=uuid))
        return ch

    async def _write(self, uuid: str, data: bytes, service: str | None = None, response: bool | None = None) -> None:
        ch = self._require(uuid, service)
        self.log(f"→ {uuid[4:8]}  {_hex(data)}")
        await self._client.write_gatt_char(ch, bytes(data), response=response)

    async def _read(self, uuid: str, service: str | None = None) -> bytes:
        ch = self._require(uuid, service)
        data = bytes(await self._client.read_gatt_char(ch))
        self.log(tr('← {uuid}  {data}  (đọc)', uuid=uuid[4:8], data=_hex(data)))
        return data

    async def _notify(self, uuid: str, handler, service: str | None = None) -> bool:
        ch = self._char(uuid, service)
        if ch is None:
            return False
        key = f"{service or ''}/{uuid}"
        if key in self._notifying:
            return True

        def _cb(_sender, data: bytearray, _uuid=uuid, _h=handler):
            data = bytes(data)
            self.log(f"← {_uuid[4:8]}  {_hex(data)}")
            try:
                _h(data)
            except Exception as e:
                self.log(tr('Lỗi xử lý thông báo {uuid}: {e}', uuid=_uuid[4:8], e=e))

        await self._client.start_notify(ch, _cb)
        self._notifying.add(key)
        return True

    # --------------------------------------------------------------- kết nối

    @property
    def is_connected(self) -> bool:
        return bool(self._client is not None and self._client.is_connected)

    def _on_disconnect(self, _client) -> None:
        self.authenticated = False
        self._notifying.clear()
        if not self._closing:
            self.log(tr('Vòng tay đã ngắt kết nối.'))
            self._emit("disconnected", None)

    async def _open(self, timeout: float) -> None:
        if self._client is None:
            from bleak import BleakClient

            self._client = BleakClient(self.device, disconnected_callback=self._on_disconnect, timeout=timeout)
        self._notifying.clear()
        self.log(tr('Đang kết nối Bluetooth…'))
        await self._client.connect()
        self._index_characteristics()
        self.log(tr('Đã kết nối GATT ({n} mục).', n=len(self._chars)))

    async def connect(self, timeout: float = 20.0) -> str:
        """Kết nối + xác thực. Trả về giao thức đã dùng ('classic' hoặc '2021')."""
        self._closing = False
        await self._open(timeout)
        has_2021 = self.has(P.CHAR_CHUNKED_2021_WRITE) and self.has(P.CHAR_CHUNKED_2021_READ)
        order = {
            PROTOCOL_CLASSIC: [PROTOCOL_CLASSIC],
            PROTOCOL_2021: [PROTOCOL_2021],
        }.get(self.protocol_pref, [PROTOCOL_CLASSIC, PROTOCOL_2021] if has_2021 else [PROTOCOL_CLASSIC])

        last_err: Exception | None = None
        for i, proto in enumerate(order):
            if i > 0:
                self.log(tr('Thử lại bằng giao thức xác thực mới (2021)…'))
                if not self.is_connected:
                    await self._open(timeout)
            try:
                if proto == PROTOCOL_CLASSIC:
                    await self._auth_classic(timeout=6.0 if len(order) > 1 else 12.0)
                else:
                    if not has_2021:
                        raise AuthError(tr('Firmware này không có kênh giao thức mới (0x0016/0x0017).'))
                    await self._auth_2021(timeout=12.0)
                self.protocol_used = proto
                self.authenticated = True
                break
            except (AuthError, asyncio.TimeoutError) as e:
                last_err = e
                self.log(tr('Xác thực {proto} thất bại: {e}', proto=proto, e=e or tr('hết thời gian chờ')))
        if not self.authenticated:
            await self.disconnect()
            if isinstance(last_err, asyncio.TimeoutError):
                raise AuthError(tr('Vòng tay không phản hồi bước xác thực. Kiểm tra vòng tay có đang kết nối với điện thoại không.'))
            raise AuthError(str(last_err) if last_err else tr('Xác thực thất bại'))

        self.log(tr('Xác thực thành công (giao thức {protocol_used}).', protocol_used=self.protocol_used))
        await self._after_auth()
        return self.protocol_used

    async def disconnect(self) -> None:
        self._closing = True
        for t in (self._hr_ping_task, self._find_task):
            if t:
                t.cancel()
        if self._client is not None and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception as e:
                self.log(tr('Lỗi khi ngắt kết nối: {e}', e=e))
        self.authenticated = False
        self._notifying.clear()

    # -------------------------------------------------------------- xác thực

    def _drain_auth_queue(self):
        while not self._auth_q.empty():
            self._auth_q.get_nowait()

    async def _auth_classic(self, timeout: float) -> None:
        self._drain_auth_queue()
        await self._notify(P.CHAR_AUTH, self._auth_q.put_nowait)
        await self._write(P.CHAR_AUTH, P.auth_request_random())
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            v = await asyncio.wait_for(self._auth_q.get(), remaining)
            if len(v) < 3 or v[0] != P.AUTH_RESPONSE:
                continue
            step = v[1] & 0x0F
            if step == P.AUTH_REQUEST_RANDOM:
                if v[2] != P.AUTH_SUCCESS or len(v) < 19:
                    raise AuthError(tr('Vòng tay từ chối yêu cầu số ngẫu nhiên (mã {code:#04x}).', code=v[2]))
                enc = crypto.aes_ecb_encrypt(v[3:19], self.auth_key)
                await self._write(P.CHAR_AUTH, P.auth_send_encrypted(enc))
            elif step == P.AUTH_SEND_ENCRYPTED:
                if v[2] == P.AUTH_SUCCESS:
                    return
                raise AuthError(tr('Auth key không đúng (vòng tay từ chối).'))

    async def _auth_2021(self, timeout: float) -> None:
        self._drain_auth_queue()
        self._enc = crypto.ChunkedEncoder2021()
        self._dec = crypto.ChunkedDecoder2021()
        await self._notify(P.CHAR_AUTH, lambda d: None)
        await self._notify(P.CHAR_CHUNKED_2021_READ, self._on_chunked_2021)
        priv = crypto.ecdh_generate_private()
        pub = crypto.ecdh_public_key(priv)
        await self._send_2021(crypto.ENDPOINT_AUTH, bytes([0x04, 0x02, 0x00, 0x02]) + pub, encrypt=False)
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            p = await asyncio.wait_for(self._auth_q.get(), remaining)
            if len(p) < 3 or p[0] != 0x10:
                continue
            if p[1] == 0x04:
                if p[2] != 0x01 or len(p) < 67:
                    raise AuthError(tr('Vòng tay từ chối trao đổi khóa (mã {code:#04x}).', code=p[2]))
                remote_random = p[3:19]
                remote_pub = p[19:67]
                shared = crypto.ecdh_shared_secret(priv, remote_pub)
                seq = int.from_bytes(shared[0:4], "little")
                session = bytes(shared[8 + i] ^ self.auth_key[i] for i in range(16))
                self._enc.set_encryption(seq, session)
                self._dec.set_encryption(session)
                e1 = crypto.aes_ecb_encrypt(remote_random, self.auth_key)
                e2 = crypto.aes_ecb_encrypt(remote_random, session)
                await self._send_2021(crypto.ENDPOINT_AUTH, bytes([0x05]) + e1 + e2, encrypt=False)
            elif p[1] == 0x05:
                if p[2] == 0x01:
                    return
                raise AuthError(tr('Auth key không đúng (vòng tay từ chối, mã {code:#04x}).', code=p[2]))

    def _on_chunked_2021(self, data: bytes) -> None:
        needs_ack, result = self._dec.decode(data)
        if needs_ack:
            asyncio.ensure_future(self._safe_write(P.CHAR_CHUNKED_2021_READ, self._dec.ack()))
        if result is None:
            return
        endpoint, payload = result
        self.log(f"   [2021] endpoint {endpoint:#06x}: {_hex(payload)}")
        if endpoint == crypto.ENDPOINT_AUTH:
            self._auth_q.put_nowait(payload)
        elif endpoint == crypto.ENDPOINT_COMPAT and payload:
            self._on_config(payload[1:])

    async def _safe_write(self, uuid: str, data: bytes) -> None:
        try:
            await self._write(uuid, data)
        except Exception as e:
            self.log(tr('Lỗi ghi {uuid}: {e}', uuid=uuid[4:8], e=e))

    async def _send_2021(self, endpoint: int, data: bytes, encrypt: bool) -> None:
        for chunk in self._enc.encode(endpoint, data, encrypt):
            await self._write(P.CHAR_CHUNKED_2021_WRITE, chunk)

    # ------------------------------------------------- sau khi xác thực

    async def _after_auth(self) -> None:
        await self._notify(P.CHAR_CONFIG, self._on_config)
        await self._notify(P.CHAR_BATTERY, self._on_battery)
        await self._notify(P.CHAR_DEVICE_EVENT, self._on_device_event)
        await self._notify(P.CHAR_STEPS, self._on_steps)
        try:
            await self.set_time()
        except Exception as e:
            self.log(tr('Không đặt được giờ: {e}', e=e))

    def _on_config(self, data: bytes) -> None:
        r = self._config_rx.feed(data)
        if r is not None:
            type_, payload = r
            if type_ == 0x01:
                alarms = P.decode_alarms_with_times(payload)
                if self._alarms_future and not self._alarms_future.done():
                    self._alarms_future.set_result(alarms)
                self._emit("alarms", alarms)
            return
        if len(data) >= 3 and data[0] == 0x10 and data[2] != 0x01:
            self.log(tr('Vòng tay báo lỗi cho lệnh {cmd:#04x} (mã {code:#04x}).', cmd=data[1], code=data[2]))

    def _on_battery(self, data: bytes) -> None:
        info = P.decode_battery(data)
        if info:
            self._emit("battery", info)

    def _on_steps(self, data: bytes) -> None:
        info = P.decode_steps(data)
        if info:
            self._emit("activity", info)

    def _on_hr(self, data: bytes) -> None:
        bpm = P.decode_heart_rate(data)
        if bpm is None:
            return
        if bpm > 0 and self._hr_future and not self._hr_future.done():
            self._hr_future.set_result(bpm)
        if bpm > 0:
            self._emit("heart_rate", bpm)

    def _on_device_event(self, data: bytes) -> None:
        if not data:
            return
        code = data[0]
        self._emit("device_event", code)
        if code == P.EVENT_FIND_PHONE_START:
            asyncio.ensure_future(self._quiet(self.write_config(P.ACK_FIND_PHONE)))
        elif code in (P.EVENT_CALL_REJECT, P.EVENT_CALL_IGNORE) and self._find_task:
            asyncio.ensure_future(self._quiet(self.find_band(False)))
        elif code in (P.EVENT_ALARM_TOGGLED, P.EVENT_ALARM_CHANGED):
            asyncio.ensure_future(self._quiet(self.request_alarms()))

    async def _quiet(self, coro) -> None:
        try:
            await coro
        except Exception as e:
            self.log(tr('Lỗi: {e}', e=e))

    # -------------------------------------------------------- kênh ghi chung

    async def write_config(self, data: bytes) -> None:
        """Ghi lệnh cấu hình (0x0003 hoặc endpoint 0x0090 khi dùng giao thức mới)."""
        async with self._lock:
            if self.protocol_used == PROTOCOL_2021:
                await self._send_2021(crypto.ENDPOINT_COMPAT, b"\x01" + bytes(data), encrypt=True)
            else:
                await self._write(P.CHAR_CONFIG, data)

    async def write_chunked(self, type_: int, data: bytes) -> None:
        async with self._lock:
            if self.protocol_used == PROTOCOL_2021:
                await self._send_2021(crypto.ENDPOINT_COMPAT, P.chunked_2021_compat(type_, data), encrypt=True)
            else:
                for c in P.chunked_old(type_, data):
                    await self._write(P.CHAR_CHUNKED, c)

    async def write_user_settings(self, data: bytes) -> None:
        async with self._lock:
            await self._write(P.CHAR_USER_SETTINGS, data)

    async def _hr_control(self, *cmds: bytes) -> None:
        async with self._lock:
            for c in cmds:
                await self._write(P.CHAR_HR_CONTROL, c, service=P.SVC_HEART_RATE)

    # ----------------------------------------------------------------- đọc

    async def read_device_info(self) -> P.DeviceInfo:
        info = P.DeviceInfo(name=self.name, address=str(getattr(self.device, "address", self.device)))
        info.protocol = self.protocol_used or ""
        for field_name, uuid in P.DEVICE_INFO_CHARS.items():
            if self.has(uuid):
                try:
                    raw = await self._read(uuid)
                    setattr(info, field_name, raw.decode("utf-8", "ignore").strip("\x00 "))
                except Exception as e:
                    self.log(tr('Không đọc được {field_name}: {e}', field_name=field_name, e=e))
        self._emit("device_info", info)
        return info

    async def read_battery(self) -> P.BatteryInfo | None:
        info = P.decode_battery(await self._read(P.CHAR_BATTERY))
        if info:
            self._emit("battery", info)
        return info

    async def read_activity(self) -> P.ActivityInfo | None:
        info = P.decode_steps(await self._read(P.CHAR_STEPS))
        if info:
            self._emit("activity", info)
        return info

    async def read_time(self) -> _dt.datetime | None:
        t = P.decode_current_time(await self._read(P.CHAR_CURRENT_TIME))
        self._emit("band_time", t)
        return t

    async def refresh_all(self) -> None:
        await self.read_device_info()
        for fn in (self.read_battery, self.read_activity, self.read_time):
            try:
                await fn()
            except Exception as e:
                self.log(tr('Lỗi khi đọc: {e}', e=e))

    # ------------------------------------------------------------- cài đặt

    async def set_time(self, when: _dt.datetime | None = None) -> None:
        async with self._lock:
            await self._write(P.CHAR_CURRENT_TIME, P.encode_current_time(when))

    async def set_user_info(self, alias: str, birth: _dt.date, gender: int, height_cm: int, weight_kg: float) -> None:
        await self.write_user_settings(P.user_info(alias, birth, gender, height_cm, weight_kg))

    async def set_step_goal(self, steps: int) -> None:
        await self.write_user_settings(P.fitness_goal(steps))

    async def set_wear_location(self, left: bool) -> None:
        await self.write_user_settings(P.WEAR_LEFT if left else P.WEAR_RIGHT)

    async def set_hr_interval(self, minutes: int) -> None:
        await self._hr_control(P.hr_measurement_interval(minutes))

    async def set_hr_sleep_assist(self, enable: bool) -> None:
        await self._hr_control(P.hr_sleep_assist(enable))

    async def set_display_items(self, items: list[str]) -> None:
        """Các ứng dụng hiện trên vòng tay theo thứ tự; mục không có trong danh sách sẽ bị ẩn."""
        await self.write_chunked(2, P.display_items(items))

    async def set_shortcuts(self, items: list[str]) -> None:
        await self.write_chunked(2, P.menu_items(items, shortcuts=True))

    # ------------------------------------------------------------ nhịp tim

    async def measure_heart_rate(self, timeout: float = 40.0) -> int:
        if not await self._notify(P.CHAR_HR_MEASUREMENT, self._on_hr, service=P.SVC_HEART_RATE):
            raise MiBandError(tr('Không tìm thấy dịch vụ nhịp tim'))
        loop = asyncio.get_running_loop()
        self._hr_future = loop.create_future()
        await self._hr_control(P.HR_STOP_CONTINUOUS, P.HR_STOP_MANUAL, P.HR_START_MANUAL)
        try:
            return await asyncio.wait_for(self._hr_future, timeout)
        finally:
            self._hr_future = None

    async def realtime_heart_rate(self, enable: bool) -> None:
        if self._hr_ping_task:
            self._hr_ping_task.cancel()
            self._hr_ping_task = None
        if enable:
            await self._notify(P.CHAR_HR_MEASUREMENT, self._on_hr, service=P.SVC_HEART_RATE)
            await self._hr_control(P.HR_STOP_MANUAL, P.HR_START_CONTINUOUS)
            self._hr_ping_task = asyncio.ensure_future(self._hr_ping_loop())
        else:
            await self._hr_control(P.HR_STOP_CONTINUOUS)

    async def _hr_ping_loop(self) -> None:
        try:
            while self.is_connected:
                await asyncio.sleep(12)
                await self._hr_control(P.HR_PING)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log(tr('Dừng đo nhịp tim liên tục: {e}', e=e))

    # ----------------------------------------------------- thông báo, tìm

    async def send_notification(self, title: str, body: str, app_name: str = "MiBand6", icon: int = 11) -> None:
        payload = P.notification_payload(title, body, app_name, icon)
        if self.has(P.CHAR_CHUNKED) or self.protocol_used == PROTOCOL_2021:
            await self.write_chunked(0, payload)
        else:  # dự phòng: dịch vụ Alert Notification chuẩn
            async with self._lock:
                await self._write(P.CHAR_NEW_ALERT, bytes([P.ALERT_SMS, 1]) + payload[6:])

    async def incoming_call(self, name: str) -> None:
        async with self._lock:
            await self._write(P.CHAR_NEW_ALERT, P.incoming_call(name), service=P.SVC_ALERT_NOTIFICATION)

    async def stop_call(self) -> None:
        async with self._lock:
            await self._write(P.CHAR_NEW_ALERT, P.STOP_CALL, service=P.SVC_ALERT_NOTIFICATION)

    async def find_band(self, start: bool, label: str | None = None) -> None:
        """Mi Band 6 rung khi có 'cuộc gọi đến' — cách Gadgetbridge dùng để tìm vòng."""
        if self._find_task:
            self._find_task.cancel()
            self._find_task = None
        if start:
            await self.incoming_call(label or tr('Tìm vòng tay'))
            self._find_task = asyncio.ensure_future(self._find_timeout())
        else:
            await self.stop_call()

    async def _find_timeout(self) -> None:
        try:
            await asyncio.sleep(30)
            self._find_task = None
            await self.stop_call()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------- báo thức

    async def request_alarms(self, timeout: float = 6.0) -> list[P.Alarm]:
        self._alarms_future = asyncio.get_running_loop().create_future()
        await self.write_config(P.REQUEST_ALARMS)
        try:
            return await asyncio.wait_for(self._alarms_future, timeout)
        finally:
            self._alarms_future = None

    async def set_alarm(self, alarm: P.Alarm) -> None:
        await self.write_config(P.alarm_command(alarm))
