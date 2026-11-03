"""Server web chạy trên máy tính: điều khiển Mi Band 6 qua Bluetooth, giao diện mở trong trình duyệt.

    uv run miband6-web            # mở http://localhost:8766 trong trình duyệt
    uv run miband6-web --demo     # vòng tay giả lập, không dùng Bluetooth
    uv run miband6-web --lan      # cho thiết bị khác trong mạng Wi-Fi truy cập (cần mã truy cập)
    miband6-web --app             # do ứng dụng macOS (macos/) gọi: không mở trình duyệt, báo địa chỉ qua stdout
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import dataclasses
import datetime as dt
import json
import os
import secrets
import signal
import socket
import sys
import tempfile
import time
import webbrowser
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from .. import health as H
from .. import protocol as P
from .. import watchface as WF
from .. import geo
from .. import weather as W
from ..config import Store
from ..envfile import env_settings, load_env
from ..i18n import get_lang, set_lang, tr
from ..device import (PROTOCOL_2021, PROTOCOL_AUTO, PROTOCOL_CLASSIC, AuthError, AuthTimeout, MiBand6, MiBandError,
                      explain_ble_error, scan)
from ..healthdb import HealthDB, db_path
from .. import xiaomi_cloud as XC
from ..xiaomi_cloud import LoginError, SessionExpired, fetch_gps_file
from .cloud import CloudSync

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8766
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SERVER_ID = "miband6-manager"          # /api/meta trả về, để nhận ra server này đang chạy sẵn trên cổng
READY_PREFIX = "MIBAND6_READY"         # dòng stdout báo địa chỉ cho ứng dụng macOS (chế độ --app)
RECONNECT_DELAYS = (2, 5, 10, 20, 30, 60)   # giây chờ trước mỗi lần tự kết nối lại; lần sau cùng lặp mãi
# lịch tự đồng bộ (Cài đặt ứng dụng): giá trị mặc định và các lựa chọn hợp lệ; 0 = chỉ khi người dùng bấm
SYNC_DEFAULTS = {"band_minutes": 30, "cloud_hours": 1, "renew_hours": 0, "retry_max": 60}
SYNC_CHOICES = {"band_minutes": (0, 15, 30, 60, 120), "cloud_hours": (0, 1, 3, 6, 12, 24),
                "renew_hours": (0, 12, 24, 168), "retry_max": (10, 30, 60, 300)}
CLOUD_TICK = 60                        # giây giữa hai lần kiểm tra lịch đồng bộ Mi Fitness / gia hạn phiên
MAX_AUTH_FAILURES = 3                  # vòng tay từ chối xác thực ngần này lần liền thì thôi tự kết nối lại
FIRST_SYNC_DAYS = 30                   # lần đồng bộ đầu tiên lấy tối đa chừng này ngày (vòng tay giữ cỡ đó)
BACKFILL_DAYS = 3 * 365                # một lần duy nhất: hỏi vòng tay mọi dữ liệu cũ hơn lần đầu, tới chừng này ngày
CLOUD_PROFILE_EVERY = 12 * 3600        # tự lấy lại hồ sơ Mi Fitness (nếu còn phiên đăng nhập) sau chừng này giây
WEATHER_EVERY = 3600                   # giây giữa hai lần gửi thời tiết khi đang kết nối
IP_PLACE_TTL = 6 * 3600                # dùng lại vị trí theo IP trong chừng này giây
CLOUD_WORKOUTS_OVERLAP = 2 * 86400     # lấy lùi lại chừng này giây so với lần trước (buổi tập đồng bộ lên trễ)
MAX_UPLOAD = 12 * 1024 * 1024          # cỡ tối đa của yêu cầu (tệp mặt đồng hồ + ảnh, dạng base64)
IMAGE_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}


def demo_track(w: dict) -> list:
    """Lộ trình giả lập cho chế độ xem thử: vòng quanh trung tâm TP.HCM, mỗi buổi một chỗ khác, mỗi 5 giây một điểm."""
    import math

    duration = max(600, int(w.get("active_seconds") or 1800))
    n = duration // 5
    seed = (w["start"] // 60) % 997
    ride = w.get("mf_proto") == 23
    lat0 = 10.7765 + 0.012 * math.sin(seed)
    lon0 = 106.6955 + 0.015 * math.cos(seed * 1.7)
    size = (0.011 if ride else 0.0045) * (0.8 + 0.4 * ((seed % 7) / 6))
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n * (1 if ride else 2)   # chạy: hai vòng; đạp xe: một vòng lớn
        r = size + 0.0008 * math.sin((3 + seed % 4) * a)
        out.append([w["start"] + 5 * i, round(lat0 + r * math.sin(a), 6), round(lon0 + 1.25 * r * math.cos(a), 6)])
    return out


def jsonable(o):
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {k: jsonable(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, (dt.datetime, dt.date, dt.time)):
        return o.isoformat()
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(x) for x in o]
    if isinstance(o, bytes):
        return o.hex()
    return o


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _time(value, default: str) -> dt.time:
    s = str(value or default)
    try:
        h, m = s.split(":")[:2]
        return dt.time(int(h), int(m))
    except (ValueError, TypeError) as e:
        raise ApiError(tr('Giờ không hợp lệ: {s}', s=s)) from e


def _hhmm(t: dt.time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


class BandService:
    """Giữ trạng thái vòng tay và đẩy sự kiện tới mọi trình duyệt đang mở."""

    def __init__(self, store: Store, demo: bool = False, env_key: str | None = None,
                 env_address: str | None = None, env_protocol: str | None = None, login_factory=None):
        self.store = store
        self.demo = demo
        self.env_key = env_key            # auth key từ .env: chỉ ở phía server, không gửi ra trình duyệt
        self.env_address = env_address
        self.env_protocol = env_protocol
        set_lang(self.settings.get("ui_lang", "vi"))
        if str(self.profile.get("alias") or "").isdigit():
            self.profile.pop("alias")   # bản trước đã chép nhầm mã tài khoản Xiaomi làm tên
        self.band: MiBand6 | None = None
        self.scan_cache: dict[str, tuple[object, str]] = {}
        self.busy = False
        self.clients: set[web.WebSocketResponse] = set()
        self.logs: deque[str] = deque(maxlen=3000)
        self.live: dict = {}
        self.device_meta: dict = {}
        self._tasks: set[asyncio.Task] = set()
        self._stop_beep = True
        # Giữ kết nối: True sau khi kết nối thành công, False khi người dùng bấm Ngắt kết nối
        self.want_connected = False
        self.reconnect: dict | None = None      # {"attempt": n, "at": epoch, "error"?} khi đang chờ hoặc đang thử nối lại
        self.reconnect_stopped: dict | None = None   # {"message", "at"}: tự kết nối lại đã dừng (key bị từ chối…)
        self.reconnect_delays = RECONNECT_DELAYS
        self._reconnect_task: asyncio.Task | None = None
        # dữ liệu sức khỏe lấy từ vòng tay (SQLite theo từng vòng tay) và cài mặt đồng hồ
        self.auto_health = True
        self.auto_cloud = not demo   # tự đồng bộ Mi Fitness sau khi kết nối (tắt ở chế độ xem thử)
        self._track_jobs: dict[int, asyncio.Future] = {}   # lộ trình đang tải, theo giờ bắt đầu buổi tập
        self._track_failed: set[int] = set()               # tải hỏng trong lần chạy này: không tự thử lại
        self._prefetch_task: asyncio.Task | None = None
        self._insight_cache: dict = {}
        self._geo_task: asyncio.Task | None = None
        self.health_status: dict = {"state": "idle"}
        self.weather_status: dict = {"state": "idle"}
        self._ip_place: tuple[float, W.Place] | None = None
        self._health_task: asyncio.Task | None = None
        self._dbs: dict[str, HealthDB] = {}
        self.watchface_busy = False
        self.cloud = CloudSync(self, demo=demo, **({"login_factory": login_factory} if login_factory else {}))

    # ------------------------------------------------------------ tiện ích
    @property
    def settings(self) -> dict:
        return self.store.data.setdefault("settings", {})

    @property
    def profile(self) -> dict:
        return self.store.data.setdefault("profile", {})

    @property
    def connected(self) -> bool:
        return bool(self.band and self.band.is_connected and self.band.authenticated)

    @property
    def keep_connected(self) -> bool:
        return bool(self.settings.get("keep_connected", True))

    def _spawn(self, coro) -> None:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def push(self, msg: dict) -> None:
        data = json.dumps(jsonable(msg), ensure_ascii=False)
        for ws in list(self.clients):
            if ws.closed:
                self.clients.discard(ws)
            else:
                self._spawn(self._send(ws, data))

    async def _send(self, ws, data: str) -> None:
        try:
            await ws.send_str(data)
        except Exception:  # noqa: BLE001
            self.clients.discard(ws)

    def log(self, line: str) -> None:
        entry = f"{dt.datetime.now():%H:%M:%S}  {line}"
        self.logs.append(entry)
        self.push({"type": "log", "line": entry})

    def state(self) -> dict:
        devices = [
            {"address": a, "name": d.get("name", ""), "protocol": d.get("protocol", PROTOCOL_AUTO),
             "auth_key": "" if self.env_key else d.get("auth_key", "")}
            for a, d in self.store.data.get("devices", {}).items()
        ]
        if self.env_address and not any(d["address"] == self.env_address for d in devices):
            devices.append({"address": self.env_address, "name": P.MI_BAND6_NAME,
                            "protocol": self.env_protocol or PROTOCOL_AUTO, "auth_key": ""})
        return {
            "connected": self.connected,
            "busy": self.busy,
            "demo": self.demo,
            "device": self.device_meta if self.connected else None,
            "live": self.live if self.connected else {},
            "settings": self.settings,
            "settings_provenance": {
                "source": "local_requested", "readback_supported": False,
                "device_readback": ["alarms"], "known_fields": sorted(self.settings),
            },
            "profile": self.profile,
            "saved_devices": devices,
            "last_device": self.store.data.get("last_device") or self.env_address,
            "env_key": bool(self.env_key),
            "reconnect": None if self.connected else self.reconnect,
            "reconnect_stopped": None if self.connected else self.reconnect_stopped,
            "health": self.health_status,
            "weather": {**self.weather_status, **self.weather_settings()},
            "sync": {**self.sync_settings(), "cloud_last": self._cloud_last()},
            "account": self.cloud_account(),
            "watchface": self.settings.get("watchface"),
            "cloud": self.cloud.status,
        }

    def push_state(self) -> None:
        self.push({"type": "state", "state": self.state()})

    def require(self) -> MiBand6:
        if not self.connected:
            raise ApiError(tr('Chưa kết nối vòng tay.'), 409)
        return self.band

    # ------------------------------------------------------------ sự kiện từ vòng tay
    def on_event(self, kind: str, data) -> None:
        if kind == "disconnected":
            self._stop_beep = True
            self._cancel_health()
            if self.busy:  # rớt giữa lúc đang kết nối: lỗi đã được báo qua kết quả của lần kết nối đó
                return
            reconnecting = self.want_connected and self.keep_connected and self._start_reconnect()
            self.push({"type": "disconnected", "reconnecting": reconnecting})
            self.push_state()
            return
        self.live[kind] = data
        self.push({"type": kind, "data": data})
        if kind == "device_event":
            self.log(tr('Sự kiện: {name}', name=tr(P.DEVICE_EVENTS[data]) if data in P.DEVICE_EVENTS else f"{data:#04x}"))
            if data == P.EVENT_FIND_PHONE_START:
                if self.settings.get("find_sound", True) and sys.platform == "darwin":
                    self._spawn(self._beep_loop())
            elif data == P.EVENT_FIND_PHONE_STOP:
                self._stop_beep = True

    async def _beep_loop(self) -> None:
        self._stop_beep = False
        end = asyncio.get_running_loop().time() + 30
        while not self._stop_beep and asyncio.get_running_loop().time() < end:
            try:
                proc = await asyncio.create_subprocess_exec("afplay", "/System/Library/Sounds/Glass.aiff")
                await proc.wait()
            except OSError:
                return
            await asyncio.sleep(0.4)

    def stop_beep(self) -> None:
        self._stop_beep = True

    # ------------------------------------------------------------ quét và kết nối
    async def do_scan(self, show_all: bool) -> list[dict]:
        if self.busy:
            raise ApiError(tr('Đang kết nối, thử lại sau.'), 409)
        if self.demo:
            from ..simulator import DemoDevice

            await asyncio.sleep(1.0)
            results = [(DemoDevice(), -54, True, DemoDevice.name)]
        else:
            try:
                results = await scan(8.0, show_all)
            except Exception as e:  # noqa: BLE001
                if known := explain_ble_error(e):
                    raise ApiError(*known) from e
                raise ApiError(
                    tr('Không quét được Bluetooth ({e}). Kiểm tra Bluetooth đã bật và Terminal đã có quyền Bluetooth.', e=e), 503
                ) from e
        self.scan_cache = {dev.address: (dev, name) for dev, _rssi, _b, name in results}
        return [{"name": name or "", "address": dev.address, "rssi": rssi, "is_band": is_band}
                for dev, rssi, is_band, name in results]

    async def connect(self, address: str, key_text: str, proto: str) -> str:
        """Kết nối khi người dùng bấm Kết nối; thay cho vòng tự kết nối lại nếu nó đang chờ."""
        if self.busy:
            raise ApiError(tr('Đang kết nối, chờ một chút.'), 409)
        self._cancel_reconnect()
        self.reconnect_stopped = None
        self.want_connected = False
        return await self._connect(address, key_text, proto)

    async def _connect(self, address: str, key_text: str, proto: str) -> str:
        if self.busy:
            raise ApiError(tr('Đang kết nối, chờ một chút.'), 409)
        if not address:
            raise ApiError(tr('Hãy quét và chọn vòng tay trước.'))
        if proto not in (PROTOCOL_AUTO, PROTOCOL_CLASSIC, PROTOCOL_2021):
            raise ApiError(tr('Kiểu xác thực không hợp lệ.'))
        from_env = not key_text.strip() and bool(self.env_key)
        if not key_text.strip() and not self.env_key:
            raise ApiError(tr('Nhập auth key, hoặc đặt MIBAND6_AUTH_KEY trong tệp .env.'))
        try:
            key = P.parse_auth_key(self.env_key if from_env else key_text)
        except ValueError as e:
            raise ApiError((tr('MIBAND6_AUTH_KEY trong .env không hợp lệ: ') if from_env else "") + str(e)) from e
        from_env = from_env or (self.env_key is not None and key == P.parse_auth_key(self.env_key))
        saved = self.store.data.get("devices", {}).get(address, {})
        target, name = self.scan_cache.get(address, (address, saved.get("name") or P.MI_BAND6_NAME))
        self.busy = True
        self.push_state()
        used = None
        try:
            if self.band:
                await self.band.disconnect()
            client = None
            if self.demo:
                from .. import simulator

                client = simulator.FakeBand(key, "both")
                client.hr_delay = 6.0
            self.band = MiBand6(target, key, proto, on_event=self.on_event, log=self.log, client=client, name=name)
            used = await self.band.connect()
        except AuthTimeout as e:   # vòng tay không trả lời bước xác thực: thử lại sau, không phải key sai
            raise ApiError(str(e), 504) from e
        except AuthError as e:     # 401 chỉ khi vòng tay nói key sai: tự kết nối lại dừng sau MAX_AUTH_FAILURES lần
            raise ApiError(str(e), 401 if e.rejected else 502) from e
        except (asyncio.TimeoutError, TimeoutError) as e:
            raise ApiError(tr('Không kết nối được: vòng tay không trả lời. Vòng tay có thể đang nối với điện thoại (Mi Fitness), ở xa máy Mac, hoặc đang khởi động lại.'), 502) from e
        except Exception as e:  # noqa: BLE001
            if known := explain_ble_error(e):
                raise ApiError(*known) from e
            raise ApiError(tr('Không kết nối được: {e}', e=str(e) or type(e).__name__), 502) from e
        finally:
            self.busy = False
            if used is None:
                self.push_state()
        self.want_connected = True
        self.reconnect_stopped = None
        self.device_meta = {"name": name, "address": address, "protocol": used}
        self.live = {}
        # key từ .env không bị chép vào config.json (và xóa key cũ đã lưu ở đó)
        self.store.remember_device(address, name, "" if from_env else key_text.strip(), used)
        self.push_state()
        self._spawn(self._after_connect())
        return used

    async def _after_connect(self) -> None:
        band = self.band
        if self.profile.get("pending_sync"):
            try:
                await self._write_profile()
                self.log(tr('Đã ghi hồ sơ lấy từ Mi Fitness vào vòng tay.'))
            except Exception as e:  # noqa: BLE001
                self.log(tr('Lỗi khi ghi hồ sơ: {e}', e=e))
        for job in (band.refresh_all, band.request_alarms):
            try:
                await job()
            except Exception as e:  # noqa: BLE001
                self.log(tr('Lỗi khi đọc dữ liệu: {e}', e=e))
        if self.auto_cloud:
            self._spawn(self._cloud_background())
        if self.weather_settings()["enabled"]:
            self._spawn(self._periodic_weather(band))
        if self.auto_health and self.band is band and self.connected:
            self.start_health_sync()
            self._spawn(self._periodic_health(band))

    async def _cloud_background(self, on_connect: bool = True) -> None:
        """Nếu đã đăng nhập Xiaomi (phiên đã lưu), tự lấy hồ sơ và các buổi tập mới từ Mi Fitness theo lịch ở
        Cài đặt ứng dụng: sau mỗi lần kết nối vòng tay, và định kỳ khi server chạy (_periodic_cloud).

        Chạy nền, không hiện mã QR; chưa đăng nhập hoặc lịch là "chỉ khi bấm" thì không làm gì. Lịch sử buổi tập chỉ
        lấy phần từ lần trước (lùi lại CLOUD_WORKOUTS_OVERLAP), lần đầu thì lấy cả lịch sử."""
        hours = self.sync_settings()["cloud_hours"]
        if not hours:
            return
        now = time.time()
        jobs: list[tuple[str, int | None]] = []
        if now - float(self.profile.get("cloud_at") or 0) > CLOUD_PROFILE_EVERY:
            jobs.append(("profile", None))
        db = self.health_db()
        last = db.last("cloud_workouts") if db else None
        if db and now - (last or 0) > hours * 3600:
            jobs.append(("workouts", last - CLOUD_WORKOUTS_OVERLAP if last else None))
        for job, since in jobs:
            while self.cloud.running:   # người dùng đang đồng bộ tay: chờ xong
                await asyncio.sleep(2)
            if on_connect and not self.connected:
                return
            self.cloud.start(write=True, interactive=False, job=job, since=since)
            await self.cloud.wait()

    async def _periodic_cloud(self) -> None:
        """Suốt khi server chạy: lấy dữ liệu Mi Fitness và gia hạn phiên đăng nhập theo lịch (Cài đặt ứng dụng)."""
        while True:
            await asyncio.sleep(CLOUD_TICK)
            try:
                await self._cloud_background(on_connect=False)
                hours = self.sync_settings()["renew_hours"]
                info = XC.XiaomiLogin.session_info()
                if hours and info and info["can_renew"] and time.time() - info["saved"] >= hours * 3600:
                    await self.renew_session()
            except ApiError:
                pass
            except Exception as e:  # noqa: BLE001 - lỗi mạng…: thử lại lần sau
                self.log(tr('Không tự đồng bộ được với Mi Fitness: {e}', e=str(e) or type(e).__name__))

    # ------------------------------------------------------------ lịch đồng bộ, tài khoản Mi Fitness
    def sync_settings(self) -> dict:
        cur = self.settings.get("sync") or {}
        return {k: cur[k] if cur.get(k) in SYNC_CHOICES[k] else v for k, v in SYNC_DEFAULTS.items()}

    def set_sync_settings(self, values: dict) -> None:
        cur = self.sync_settings()
        for k, v in values.items():
            if k not in SYNC_CHOICES:
                continue
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = None
            if v not in SYNC_CHOICES[k]:
                raise ApiError(tr('Lựa chọn không hợp lệ.'))
            cur[k] = v
        self.settings["sync"] = cur
        self.store.save()

    def _cloud_last(self) -> int | None:
        db = self.health_db()
        return db.last("cloud_workouts") if db else None

    def cloud_account(self) -> dict:
        """Trạng thái phiên đăng nhập Xiaomi đã lưu (không gọi mạng)."""
        if self.demo:
            return {"logged_in": False, "saved": None, "can_renew": False}
        info = XC.XiaomiLogin.session_info()
        return {"logged_in": bool(info), "saved": info and info["saved"], "can_renew": bool(info and info["can_renew"])}

    async def renew_session(self) -> dict:
        """Đổi passToken lấy token mới ngay (như Mi Fitness làm khi token hết hạn), không cần quét QR."""
        login = XC.XiaomiLogin()
        if self.demo or not await asyncio.to_thread(login.load):
            raise ApiError(tr('Chưa đăng nhập Mi Fitness.'), 409)
        if not await asyncio.to_thread(login.renew):
            raise ApiError(tr('Không gia hạn được phiên này; hãy đăng nhập lại.'), 409)
        self.log(tr('Đã gia hạn phiên đăng nhập Mi Fitness.'))
        self.push_state()
        return self.cloud_account()

    # ------------------------------------------------------------ thời tiết
    def weather_settings(self) -> dict:
        w = self.settings.get("weather") or {}
        return {"enabled": w.get("enabled", True), "place": w.get("place")}

    def set_weather_settings(self, enabled: bool | None = None, place: dict | None | bool = False) -> None:
        """place: dict (thành phố đã chọn), None (tự động theo IP), False (giữ nguyên)."""
        w = self.weather_settings()
        if enabled is not None:
            w["enabled"] = bool(enabled)
        if place is not False:
            if place is not None:
                lat, lon = float(place["lat"]), float(place["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ApiError(tr('Tọa độ không hợp lệ.'))
                place = {"name": str(place.get("name") or "?")[:60], "lat": lat, "lon": lon,
                         "detail": str(place.get("detail") or "")[:80]}
            w["place"] = place
        self.settings["weather"] = w
        self.store.save()
        self.push_state()
        if w["enabled"] and self.connected:
            self._spawn(self._sync_weather_quiet())

    async def _weather_place(self) -> W.Place:
        chosen = self.weather_settings()["place"]
        if chosen:
            return W.Place(chosen["name"], chosen["lat"], chosen["lon"], chosen.get("detail", ""))
        if self.demo:
            return W.demo().place
        if self._ip_place and time.time() - self._ip_place[0] < IP_PLACE_TTL:
            return self._ip_place[1]
        place = await asyncio.to_thread(W.locate_by_ip)
        self._ip_place = (time.time(), place)
        return place

    def _band_lang(self) -> str:
        return "vi" if str(self.settings.get("language") or "").lower().startswith("vi") else "en"

    async def sync_weather(self) -> dict:
        """Lấy thời tiết nơi đang ở (hoặc thành phố đã chọn) rồi gửi tới vòng tay."""
        band = self.require()
        self.weather_status = {**self.weather_status, "state": "running"}
        self.push({"type": "weather", "status": self.state()["weather"]})
        try:
            place = await self._weather_place()
            data = W.demo(place) if self.demo else await asyncio.to_thread(W.fetch, place)
            lang = self._band_lang()
            await band.send_weather(W.packets(data, lang, fahrenheit=self.settings.get("metric") is False))
        except ApiError:
            raise
        except Exception as e:  # noqa: BLE001 - lỗi mạng, mất kết nối…
            self.weather_status = {**self.weather_status, "state": "error", "error": str(e) or type(e).__name__}
            self.push({"type": "weather", "status": self.state()["weather"]})
            raise ApiError(tr('Không gửi được thời tiết: {e}', e=str(e) or type(e).__name__), 502) from e
        summary = data.summary(lang)
        self.weather_status = {"state": "done", "at": int(time.time()), "now": summary}
        self.log(tr('Đã gửi thời tiết tới vòng tay: {place}, {temp}°, {text}.', place=summary["place"],
                    temp=summary["temp"], text=summary["text"]))
        self.push({"type": "weather", "status": self.state()["weather"]})
        return self.state()["weather"]

    async def _sync_weather_quiet(self) -> None:
        try:
            await self.sync_weather()
        except ApiError as e:
            self.log(tr('Không gửi được thời tiết: {e}', e=e))

    async def _periodic_weather(self, band: MiBand6) -> None:
        """Gửi thời tiết ngay khi kết nối, rồi mỗi WEATHER_EVERY giây khi vẫn kết nối và còn bật."""
        while self.band is band and self.connected and self.weather_settings()["enabled"]:
            await self._sync_weather_quiet()
            await asyncio.sleep(WEATHER_EVERY)

    async def search_places(self, query: str) -> list[dict]:
        query = query.strip()
        if len(query) < 2:
            return []
        lang = get_lang()
        if self.demo:
            demo = [W.Place("Hà Nội", 21.0285, 105.8542, "Việt Nam"), W.Place("TP. Hồ Chí Minh", 10.7765, 106.7009, "Việt Nam"),
                    W.Place("Đà Nẵng", 16.0544, 108.2022, "Việt Nam")]
            return [p.as_dict() for p in demo if query.lower() in p.name.lower()]
        try:
            return [p.as_dict() for p in await asyncio.to_thread(W.search_places, query, lang)]
        except Exception as e:  # noqa: BLE001
            raise ApiError(tr('Không tìm được địa điểm: {e}', e=str(e) or type(e).__name__), 502) from e

    # ------------------------------------------------------------ dữ liệu sức khỏe
    def health_db(self) -> HealthDB | None:
        address = self.device_meta.get("address") or self.store.data.get("last_device") or self.env_address
        if not address:
            return None
        if address not in self._dbs:
            self._dbs[address] = HealthDB(db_path(self.store.path.parent, address))
        return self._dbs[address]

    def _set_health(self, **status) -> None:
        db = self.health_db()
        self.health_status = {**status, "last_sync": db.last("last_sync") if db else None}
        self.push({"type": "health", "status": self.health_status})

    def start_health_sync(self) -> dict:
        self.require()
        if not (self._health_task and not self._health_task.done()):
            self._health_task = asyncio.ensure_future(self._sync_health(self.band))
        return self.health_status

    def _cancel_health(self) -> None:
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        if self.health_status.get("state") == "running":
            self.health_status = {**self.health_status, "state": "idle"}

    async def _periodic_health(self, band: MiBand6) -> None:
        """Lấy dữ liệu mới từ vòng tay theo lịch ở Cài đặt ứng dụng (0: chỉ khi bấm Đồng bộ)."""
        waited = 0
        while True:
            await asyncio.sleep(60)
            if self.band is not band or not self.connected:
                return
            waited += 60
            every = self.sync_settings()["band_minutes"]
            if every and waited >= every * 60:
                waited = 0
                self.start_health_sync()

    HEALTH_JOBS = (
        ("activity", P.FETCH_ACTIVITY),
        ("stress_auto", P.FETCH_STRESS_AUTO),
        ("stress_manual", P.FETCH_STRESS_MANUAL),
        ("spo2", P.FETCH_SPO2),
        ("pai", P.FETCH_PAI),
        ("workouts", P.FETCH_SPORTS_SUMMARY),
    )

    @staticmethod
    def _health_label(name: str) -> str:
        return {"activity": tr('bước chân, nhịp tim và giấc ngủ'), "stress_auto": tr('căng thẳng'),
                "stress_manual": tr('căng thẳng'), "spo2": "SpO2", "pai": "PAI",
                "workouts": tr('các buổi tập')}.get(name, name)

    async def _sync_health(self, band: MiBand6) -> None:
        """Lấy dữ liệu mới từ vòng tay cho từng loại; dữ liệu vẫn còn trên vòng tay cho Mi Fitness."""
        db = self.health_db()
        errors = []
        for name, kind in self.HEALTH_JOBS:
            label = self._health_label(name)
            self._set_health(state="running", step=label)
            try:
                await self._sync_one(band, db, name, kind)
                if db.last(f"{name}_backfill") is None:
                    self._set_health(state="running", step=tr('{label} (dữ liệu cũ)', label=label))
                    await self._backfill_one(band, db, name, kind)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - vòng tay không có loại dữ liệu này, mất gói…
                errors.append(label)
                self.log(tr('Không lấy được {label}: {e}', label=label, e=e or type(e).__name__))
                if not self.connected:
                    break
        if self.connected and not errors:
            db.set_last("last_sync", int(time.time()))
        self._set_health(state="error" if errors else "done",
                         errors=sorted(set(errors)))
        self._insight_cache.clear()  # partial syncs may still have committed useful new samples
        self.push({"type": "health_data"})

    async def _backfill_one(self, band: MiBand6, db: HealthDB, name: str, kind: int) -> None:
        """Một lần duy nhất: lấy phần vòng tay còn giữ nhưng cũ hơn dữ liệu đã có (lần đầu chỉ lấy 30 ngày)."""
        stop = db.last(f"{name}_backfill_stop") or db.first(name) or db.last(name) or time.time()
        db.set_last(f"{name}_backfill_stop", int(stop))
        since_ts = db.last(f"{name}_backfill_cursor") or time.time() - BACKFILL_DAYS * 86400
        for _ in range(200):
            if since_ts >= stop:
                break
            start, data = await band.fetch_data(kind, dt.datetime.fromtimestamp(since_ts).astimezone())
            if start is None or not data or start.timestamp() >= stop:
                break
            nxt = self._store_health(db, name, start, data)
            if nxt is None or nxt <= since_ts:
                break
            since_ts = nxt
            db.set_last(f"{name}_backfill_cursor", int(nxt))
        else:
            raise RuntimeError("History page limit reached; backfill will resume on the next sync")
        db.set_last(f"{name}_backfill", int(time.time()))

    async def _sync_one(self, band: MiBand6, db: HealthDB, name: str, kind: int) -> None:
        now = time.time()
        last = db.last(name)
        # The wire request has minute precision. Replay two minutes to recover
        # late spot readings and the band's still-changing latest activity minute.
        # Primary keys make replay idempotent; never move a checkpoint backwards.
        since_ts = last - 120 if last is not None else now - FIRST_SYNC_DAYS * 86400
        if name == "pai" and last is not None:
            since_ts = last - 86400   # bản ghi PAI của hôm nay được vòng tay cập nhật suốt ngày
        for _ in range(80):   # mỗi lượt vòng tay chỉ gửi một phần; lặp tới khi hết dữ liệu mới
            start, data = await band.fetch_data(kind, dt.datetime.fromtimestamp(since_ts).astimezone())
            if start is None or not data:
                return
            nxt = self._store_health(db, name, start, data)
            if nxt is None or nxt <= since_ts:
                return
            db.set_last(name, max(db.last(name) or nxt, nxt))
            since_ts = nxt
            if since_ts >= now:
                return
        raise RuntimeError("History page limit reached; remaining data will resume on the next sync")

    @staticmethod
    def _store_health(db: HealthDB, name: str, start: dt.datetime, data: bytes) -> int | None:
        """Lưu một lượt dữ liệu; trả về mốc thời gian để lượt sau hỏi tiếp."""
        if name == "activity":
            rows = H.decode_activity(start, data)
            db.add_activity(rows)
            return rows[-1][0] + 60 if rows else None
        if name == "stress_auto":
            db.add_stress(H.decode_stress_auto(start, data), auto=True)
            return int(start.timestamp()) + 60 * len(data)
        if name == "workouts":
            db.add_workout(H.decode_sport_summary(data, start))
            return int(start.timestamp()) + 60
        if name == "stress_manual":
            rows = H.decode_stress_manual(data)
            db.add_stress(rows, auto=False)
        elif name == "spo2":
            rows = H.decode_spo2(data)
            db.add_spo2(rows)
        elif name == "pai":
            rows = H.decode_pai(data)
            db.add_pai(rows)
            rows = [(r["ts"],) for r in rows]
        else:
            return None
        # Spot readings carry seconds, but fetch requests do not. Advance to the
        # next minute, then overlap on the next sync rather than skipping 60 seconds.
        return (max(r[0] for r in rows) // 60 + 1) * 60 if rows else None

    def import_cloud_workouts(self, records: list[dict]) -> str:
        """Lưu buổi tập lấy từ tài khoản Mi Fitness (gộp với buổi vòng tay đã ghi)."""
        db = self.health_db()
        if db is None:
            raise LoginError(tr('Kết nối vòng tay một lần trước khi lấy lịch sử buổi tập.'))
        rows = [w for w in (H.workout_from_cloud(v) for v in records) if w]
        added = db.add_cloud_workouts(rows)
        db.set_last("cloud_workouts", int(time.time()))
        self.push({"type": "health_data"})
        self.prefetch_tracks()
        return tr('Đã lấy {n} buổi tập từ Mi Fitness, {new} buổi mới.', n=len(rows), new=added)

    async def workout_track(self, start: int) -> list:
        """Lộ trình GPS của một buổi tập (tải từ Mi Fitness lần đầu, sau đó dùng bản đã lưu trên máy).
        Nhiều yêu cầu cùng một buổi tập (người dùng bấm, tải sẵn chạy nền) dùng chung một lần tải."""
        db = self.health_db()
        cached = db.track(start) if db else None
        if cached is not None:
            return cached
        job = self._track_jobs.get(start)
        if job is None:
            job = self._track_jobs[start] = asyncio.ensure_future(self._download_track(start))
            job.add_done_callback(lambda _f: self._track_jobs.pop(start, None))
        return await asyncio.shield(job)

    async def _download_track(self, start: int) -> list:
        db = self.health_db()
        w = db.workout(start) if db else None
        if w is None:
            raise ApiError(tr('Không tìm thấy buổi tập này.'), 404)
        cached = db.track(start)
        if cached is not None:
            return cached
        if not H.has_gps(w):
            raise ApiError(tr('Buổi tập này không có lộ trình GPS.'), 404)
        if self.demo:
            points = demo_track(w)
        else:
            login = self.cloud.factory()
            if not await asyncio.to_thread(login.load):
                raise ApiError(tr('Đăng nhập Mi Fitness trước: bấm Lấy lịch sử từ Mi Fitness ở thẻ Tập luyện.'), 409)
            try:
                plain = await asyncio.to_thread(fetch_gps_file, login, w["mf_sid"], w["mf_time"], w.get("mf_tz") or 0,
                                                w["mf_proto"], w.get("mf_region") or "sg")
                try:
                    points = H.decode_gps_file(plain) if plain else []
                except ValueError:
                    # giữ tệp (đã giải mã, chỉ trên máy này) để sửa bộ đọc cho phiên bản tệp mới
                    keep = self.store.path.parent / "health" / "gps-unread" / f"{start}.bin"
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    keep.write_bytes(plain)
                    keep.chmod(0o600)
                    self.log(tr('Tệp lộ trình chưa đọc được đã lưu tại {path}.', path=keep))
                    raise
            except SessionExpired as e:
                raise ApiError(tr('Phiên đăng nhập Mi Fitness đã hết hạn: bấm Lấy lịch sử từ Mi Fitness để đăng nhập lại.'), 409) from e
            except Exception as e:  # noqa: BLE001 - lỗi mạng, tệp lạ…
                self.log(tr('Không lấy được lộ trình: {e}', e=e or type(e).__name__))
                raise ApiError(tr('Không lấy được lộ trình: {e}', e=e or type(e).__name__), 502) from e
        db.set_track(start, points)
        self.push({"type": "tracks"})
        return points

    def prefetch_tracks(self) -> None:
        """Tải sẵn ở chế độ nền lộ trình của mọi buổi tập có GPS chưa có trên máy, để mở bản đồ tức thì
        (máy chủ tệp của Xiaomi có thể mất cả phút mới trả lời)."""
        if self._prefetch_task and not self._prefetch_task.done():
            return
        self._prefetch_task = asyncio.ensure_future(self._prefetch_tracks())

    async def _prefetch_tracks(self) -> None:
        db = self.health_db()
        if db is None:
            return
        have = set(db.tracks())
        todo = [w["start"] for w in db.gps_workouts() if w["start"] not in have and w["start"] not in self._track_failed]
        if not todo:
            return
        limit = asyncio.Semaphore(3)
        stop = asyncio.Event()

        async def one(start: int) -> None:
            async with limit:
                if stop.is_set():
                    return
                try:
                    await self.workout_track(start)
                except ApiError as e:
                    if e.status == 409:   # chưa đăng nhập / phiên hết hạn: dừng, không hỏi QR khi chạy nền
                        stop.set()
                    else:
                        self._track_failed.add(start)

        await asyncio.gather(*(one(s) for s in todo))

    def all_tracks(self) -> dict:
        """Mọi lộ trình đã có trên máy (rút gọn) cho bản đồ "những nơi đã đến"; tải nốt phần còn thiếu ở nền."""
        db = self.health_db()
        if db is None:
            return {"routes": [], "pending": 0}
        stored = db.tracks()
        routes, pending = [], 0
        lang = get_lang()
        for w in db.gps_workouts():
            points = stored.get(w["start"])
            if points is None:
                pending += w["start"] not in self._track_failed
                continue
            if len(points) >= 2:
                routes.append({"start": w["start"], "kind": H.route_kind(w), "points": H.simplify_track(points),
                               "area": geo.area_key(points[0][1], points[0][2], lang)})
        known = db.places([r["area"] for r in routes])
        missing = sorted({r["area"] for r in routes} - set(known))
        for r in routes:
            r["place"] = known.get(r.pop("area"))
        if pending:
            self.prefetch_tracks()
        if missing:
            self.geocode_places(missing)
        return {"routes": routes, "pending": pending, "places_pending": len(missing)}

    def geocode_places(self, keys: list[str]) -> None:
        """Tra tên thành phố, quốc gia cho các vùng lộ trình chưa có (chạy nền, 1 yêu cầu/giây, lưu lại)."""
        if self._geo_task and not self._geo_task.done():
            return
        self._geo_task = asyncio.ensure_future(self._geocode(keys))

    async def _geocode(self, keys: list[str]) -> None:
        db = self.health_db()
        if db is None:
            return
        for n, key in enumerate(keys, 1):
            lat, lon, lang = geo.parse_key(key)
            try:
                place = geo.demo_place(lat, lon, lang) if self.demo else await asyncio.to_thread(geo.reverse, lat, lon, lang)
            except Exception as e:  # noqa: BLE001 - mất mạng…: thử lại lần sau mở bản đồ
                self.log(tr('Không tra được tên nơi của lộ trình: {e}', e=str(e) or type(e).__name__))
                break
            db.set_place(key, place)
            if n % 5 == 0 or n == len(keys):
                self.push({"type": "tracks"})

    def rem_estimate(self) -> bool:
        """REM ước tính từ nhịp tim (Cài đặt ứng dụng → Giấc ngủ REM); mặc định bật."""
        return self.settings.get("rem_mode", "estimate") == "estimate"

    def health_summary(self, date: str) -> dict | None:
        db = self.health_db()
        if not db:
            return None
        rem = self.rem_estimate()
        summary = db.summary(date, rem=rem)
        summary["analysis"] = db.analysis(goal=int(self.profile.get("goal") or 8000), rem=rem)
        key = (date, db.last("last_sync"), db.last("cloud_workouts"), rem, get_lang(), self.profile.get("birth"))
        if self._insight_cache.get("key") != key:   # tính lại khi có dữ liệu mới, đổi ngày, đổi ngôn ngữ…
            self._insight_cache = {"key": key, "value": db.insights(date, self.profile, rem=rem)}
        summary["insights"] = self._insight_cache["value"]
        summary["rem_mode"] = self.settings.get("rem_mode", "estimate")
        return summary

    # ------------------------------------------------------------ mặt đồng hồ
    @property
    def watchface_dir(self) -> Path:
        return self.store.path.parent / "watchface"

    async def install_watchface(self, name: str, data: bytes, preview: bytes | None) -> str:
        band = self.require()
        if self.watchface_busy:
            raise ApiError(tr('Đang cài một mặt đồng hồ, chờ xong đã.'), 409)
        try:
            P.check_watchface(data)
        except ValueError as e:
            raise ApiError(str(e)) from e
        self._cancel_health()   # nhường kênh Bluetooth cho việc cài; lần đồng bộ sau sẽ lấy tiếp
        self.watchface_busy = True
        last_pct = [-1]

        def progress(sent: int, total: int) -> None:
            pct = sent * 100 // total
            if pct != last_pct[0]:
                last_pct[0] = pct
                self.push({"type": "watchface_progress", "data": {"sent": sent, "total": total}})

        self.push({"type": "watchface_progress", "data": {"sent": 0, "total": len(data)}})
        try:
            await band.upload_watchface(data, progress)
        except MiBandError as e:
            raise ApiError(str(e), 502) from e
        except asyncio.TimeoutError as e:
            raise ApiError(tr('Vòng tay không phản hồi khi cài mặt đồng hồ.'), 504) from e
        finally:
            self.watchface_busy = False
        self.watchface_dir.mkdir(parents=True, exist_ok=True)
        (self.watchface_dir / "current.bin").write_bytes(data)
        if preview is None:
            preview = WF.preview_png(data, self.face_status())   # vẽ từ các ảnh trong tệp, nếu đọc được
        info = {"name": name[:120], "size": len(data), "installed": int(time.time()), "preview": False}
        if preview is not None:
            (self.watchface_dir / "preview").write_bytes(preview)
            info.update(preview=True, version=int(time.time()))
        elif (self.watchface_dir / "preview").exists():
            (self.watchface_dir / "preview").unlink()
        self.settings["watchface"] = info
        self.store.save()
        self.push_state()
        return tr('Đã cài mặt đồng hồ lên vòng tay.')

    def face_status(self) -> dict:
        """Số liệu để vẽ mặt đồng hồ trong tệp .bin: giờ máy, kiểu giờ đã lưu, pin, bước, nhịp tim thật nếu có."""
        battery, activity = self.live.get("battery"), self.live.get("activity")
        pulse = self.live.get("heart_rate")
        return WF.face_status(
            time_24h=self.settings.get("time_24h") is not False, metric=self.settings.get("metric") is not False,
            battery=getattr(battery, "level", None), steps=getattr(activity, "steps", None),
            calories=getattr(activity, "calories", None), meters=getattr(activity, "meters", None),
            pulse=pulse if isinstance(pulse, int) else None, goal=int(self.profile.get("goal") or 8000))

    def set_watchface_preview(self, preview: bytes | None) -> None:
        """Ảnh xem trước của mặt đồng hồ đang dùng (vòng tay không cho đọc mặt đồng hồ hiện tại)."""
        info = dict(self.settings.get("watchface") or {})
        path = self.watchface_dir / "preview"
        if preview is None:
            path.unlink(missing_ok=True)
            info["preview"] = False
        else:
            self.watchface_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(preview)
            info.update(preview=True, version=int(time.time()))
        self.settings["watchface"] = info
        self.store.save()
        self.push_state()

    # ------------------------------------------------------------ giữ kết nối
    def start(self) -> None:
        """Gọi khi server vừa chạy: tự kết nối với vòng tay đã nhớ nếu đang bật Giữ kết nối, và tải sẵn lộ trình."""
        if not self.demo:
            self.prefetch_tracks()
            self._spawn(self._periodic_cloud())
        if self.keep_connected and self._reconnect_target():
            self.want_connected = True
            self._start_reconnect(first_delay=False)

    def _reconnect_target(self) -> tuple[str, str, str] | None:
        """(địa chỉ, auth key, giao thức) của vòng tay kết nối gần nhất, hoặc None nếu chưa đủ để tự kết nối."""
        address = self.store.data.get("last_device") or self.env_address
        if not address:
            return None
        saved = self.store.data.get("devices", {}).get(address, {})
        key = saved.get("auth_key") or ""
        if not key and not self.env_key:
            return None
        return address, key, saved.get("protocol") or self.env_protocol or PROTOCOL_AUTO

    def _start_reconnect(self, first_delay: bool = True) -> bool:
        if self._reconnect_task and not self._reconnect_task.done():
            return True
        if not self._reconnect_target():
            return False
        # đặt ngay để state() đẩy đi liền sau đó đã có thông tin chờ nối lại
        self.reconnect = {"attempt": 1, "at": time.time() + (self.reconnect_delays[0] if first_delay else 0)}
        self._reconnect_task = asyncio.ensure_future(self._reconnect_loop(first_delay))
        return True

    def _cancel_reconnect(self) -> None:
        task, self._reconnect_task = self._reconnect_task, None
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self.reconnect = None

    def reconnect_now(self) -> bool:
        """Thử nối lại ngay, bỏ qua thời gian chờ (ứng dụng macOS gọi khi máy vừa thức dậy)."""
        if self.connected or self.busy or not (self.want_connected and self.keep_connected):
            return False
        self._cancel_reconnect()
        self.reconnect_stopped = None
        started = self._start_reconnect(first_delay=False)
        self.push_state()
        return started

    async def _reconnect_loop(self, first_delay: bool) -> None:
        attempt = auth_failures = 0
        error: str | None = None   # lý do lần thử trước thất bại, hiện kèm lúc chờ (Bluetooth tắt, vòng tay bận…)

        def stop(message: str) -> None:
            self.log(tr('Ngừng tự kết nối lại: {e}', e=message))
            self.reconnect_stopped = {"message": message, "at": int(time.time())}

        try:
            while not self.connected:
                target = self._reconnect_target()
                if target is None:
                    return
                delays = self.reconnect_delays
                if delays is RECONNECT_DELAYS:   # lịch mặc định: giới hạn thời gian chờ theo Cài đặt ứng dụng
                    cap = self.sync_settings()["retry_max"]
                    delays = tuple(d for d in delays if d < cap) + (cap,)
                delay = delays[min(attempt, len(delays) - 1)] if (attempt or first_delay) else 0
                attempt += 1
                self.reconnect = {"attempt": attempt, "at": time.time() + delay, "error": error}
                self.push_state()
                await asyncio.sleep(delay)
                if self.connected:
                    return
                self.log(tr('Đang tự kết nối với vòng tay (lần {n})…', n=attempt))
                try:
                    await self._connect(*target)
                except ApiError as e:
                    if e.status == 400:  # auth key hoặc địa chỉ đã lưu không hợp lệ: thử nữa cũng vô ích
                        stop(str(e))
                        return
                    # chỉ đếm lần vòng tay nói key sai (401); không trả lời bước xác thực (504) thì cứ thử tiếp
                    auth_failures = auth_failures + 1 if e.status == 401 else 0
                    if auth_failures >= MAX_AUTH_FAILURES:
                        stop(tr('vòng tay từ chối xác thực {n} lần liền.', n=auth_failures))
                        return
                    error = str(e)
                    self.log(tr('Chưa kết nối lại được: {e}', e=e))
                else:
                    self.log(tr('Đã tự kết nối lại với vòng tay.'))
                    return
        finally:
            if self._reconnect_task is asyncio.current_task():
                self._reconnect_task = None
                self.reconnect = None
                self.push_state()

    # ------------------------------------------------------------ hồ sơ từ Mi Fitness
    async def _write_profile(self) -> None:
        band, pr = self.require(), self.profile
        birth = dt.date.fromisoformat(str(pr.get("birth") or "2000-01-01"))
        await band.set_user_info(str(pr.get("alias") or "user"), birth, int(pr.get("gender", 0)),
                                 int(pr.get("height", 170)), float(pr.get("weight", 60)))
        if pr.get("goal"):
            await band.set_step_goal(int(pr["goal"]))
        pr.pop("pending_sync", None)
        self.store.save()

    async def apply_cloud_profile(self, values: dict, write: bool = True) -> str:
        """Lưu hồ sơ lấy từ Mi Fitness; ghi vào vòng tay ngay nếu đang kết nối, nếu không thì khi kết nối."""
        if "alias" not in values and str(self.profile.get("alias") or "").isdigit():
            self.profile.pop("alias")   # bản trước đã chép nhầm mã tài khoản Xiaomi làm tên
        self.profile.update(values)
        self.profile["pending_sync"] = True
        self.profile["cloud_at"] = int(time.time())
        self.store.save()
        message = tr('Đã lấy hồ sơ từ Mi Fitness. Hồ sơ sẽ được ghi vào vòng tay khi kết nối.')
        if write and self.connected:
            await self._write_profile()
            message = tr('Đã lấy hồ sơ từ Mi Fitness và ghi vào vòng tay.')
        self.push_state()
        return message

    async def disconnect(self) -> None:
        """Người dùng chủ động ngắt: không tự kết nối lại nữa (kể cả khi đang chờ nối lại)."""
        self.want_connected = False
        self.reconnect_stopped = None
        self._cancel_reconnect()
        self._cancel_health()
        if self.band:
            await self.band.disconnect()
        self.live = {}
        self.push_state()

    def set_keep_connected(self, on: bool) -> None:
        self.settings["keep_connected"] = on
        self.store.save()
        if not on:
            self._cancel_reconnect()
        elif self.want_connected and not self.connected and not self.busy:
            self._start_reconnect(first_delay=False)

    # ------------------------------------------------------------ cài đặt
    async def apply(self, section: str, b: dict) -> str:
        band = self.require()
        st, pr = self.settings, self.profile
        if section == "profile":
            birth = dt.date.fromisoformat(str(b["birth"]))
            alias = str(b.get("alias") or "user").strip()[:32] or "user"
            gender, height, weight = int(b["gender"]), int(b["height"]), float(b["weight"])
            if gender not in (0, 1, 2) or not 100 <= height <= 230 or not 20 <= weight <= 250:
                raise ApiError(tr('Hồ sơ có giá trị ngoài khoảng cho phép.'))
            await band.set_user_info(alias, birth, gender, height, weight)
            pr.update(alias=alias, birth=birth.isoformat(), gender=gender, height=height, weight=weight)
            pr.pop("pending_sync", None)
            msg = tr('Đã lưu hồ sơ vào vòng tay.')
        elif section == "goal":
            goal, notify = int(b["goal"]), bool(b.get("notify"))
            if not 1000 <= goal <= 60000:
                raise ApiError(tr('Mục tiêu phải từ 1.000 đến 60.000 bước.'))
            await band.set_step_goal(goal)
            await band.write_config(P.goal_notification(notify))
            pr.update(goal=goal, goal_notify=notify)
            msg = tr('Đã lưu mục tiêu vào vòng tay.')
        elif section == "wear":
            left = bool(b.get("left"))
            await band.set_wear_location(left)
            pr["wear_left"] = left
            msg = tr('Đã lưu tay đeo vào vòng tay.')
        elif section == "formats":
            lang, h24, datef, metric = str(b["language"]), bool(b["time_24h"]), str(b["date_format"]), bool(b["metric"])
            if lang not in P.LANGUAGES or datef not in P.DATE_FORMATS:
                raise ApiError(tr('Ngôn ngữ hoặc kiểu ngày không hợp lệ.'))
            for cmd in (P.language(lang), P.time_format_24h(h24), P.date_format(datef), P.distance_unit(metric)):
                await band.write_config(cmd)
            st.update(language=lang, time_24h=h24, date_format=datef, metric=metric)
            msg = tr('Đã lưu ngôn ngữ và định dạng vào vòng tay.')
        elif section == "lift":
            mode = str(b["mode"])
            a, z = _time(b.get("from"), "07:00"), _time(b.get("to"), "23:00")
            sens = bool(b.get("sensitive"))
            if mode not in (P.LIFT_OFF, P.LIFT_ON, P.LIFT_SCHEDULED):
                raise ApiError(tr('Chế độ không hợp lệ.'))
            await band.write_config(P.lift_wrist(mode, a, z))
            await band.write_config(P.lift_wrist_sensitive(sens))
            st.update(lift=mode, lift_from=_hhmm(a), lift_to=_hhmm(z), lift_sensitive=sens)
            msg = tr('Đã lưu cài đặt nâng tay vào vòng tay.')
        elif section == "night":
            mode = str(b["mode"])
            a, z = _time(b.get("from"), "19:00"), _time(b.get("to"), "07:00")
            if mode not in (P.NIGHT_OFF, P.NIGHT_SUNSET, P.NIGHT_SCHEDULED):
                raise ApiError(tr('Chế độ không hợp lệ.'))
            await band.write_config(P.night_mode(mode, a, z))
            st.update(night=mode, night_from=_hhmm(a), night_to=_hhmm(z))
            msg = tr('Đã lưu chế độ ban đêm vào vòng tay.')
        elif section == "password":
            on, pin = bool(b.get("on")), str(b.get("pin") or "")
            try:
                cmd = P.password(on, pin)
            except ValueError as e:
                raise ApiError(str(e)) from e
            await band.write_config(cmd)
            st.update(pw_on=on, pw=pin)
            msg = tr('Đã lưu mật khẩu vào vòng tay.')
        elif section == "menu":
            if b.get("kind") == "shortcuts":
                items = [str(x) for x in b.get("items") or [] if x in P.SHORTCUTS_ALL]
                await band.set_shortcuts(items)
                st["shortcuts"] = items
                msg = tr('Đã lưu phím tắt vào vòng tay.')
            else:
                items = P.arrange_display_items([str(x) for x in b.get("items") or []])
                await band.set_display_items(items)
                st["display_items"] = items
                msg = tr('Đã lưu bố cục ứng dụng vào vòng tay.')
        elif section == "hr":
            iv = int(b.get("interval", 0))
            th = int(b.get("threshold", 120))
            if iv not in P.HR_INTERVALS or th not in P.HR_ALERT_THRESHOLDS:
                raise ApiError(tr('Giá trị nhịp tim không hợp lệ.'))
            sl, ac, al, stv = (bool(b.get(k)) for k in ("sleep", "activity", "alert", "stress"))
            await band.set_hr_interval(iv)
            await band.set_hr_sleep_assist(sl)
            await band.write_config(P.hr_activity_monitoring(ac))
            await band.write_config(P.hr_alert(al, th))
            await band.write_config(P.stress_monitoring(stv))
            st.update(hr_interval=iv, hr_sleep=sl, hr_activity=ac, hr_alert=al, hr_threshold=th, stress=stv)
            msg = tr('Đã lưu cài đặt nhịp tim vào vòng tay.')
        elif section == "idle":
            on, minutes = bool(b.get("on")), int(b.get("minutes", 60))
            if not 15 <= minutes <= 180:
                raise ApiError(tr('Thời gian ngồi yên phải từ 15 đến 180 phút.'))
            a, z = _time(b.get("from"), "08:00"), _time(b.get("to"), "22:00")
            lunch = bool(b.get("lunch"))
            la, lz = _time(b.get("lunch_from"), "12:00"), _time(b.get("lunch_to"), "13:30")
            await band.write_config(P.inactivity_warnings(on, minutes, a, z, lunch, la, lz))
            st.update(idle_on=on, idle_minutes=minutes, idle_from=_hhmm(a), idle_to=_hhmm(z),
                      idle_lunch=lunch, idle_lunch_from=_hhmm(la), idle_lunch_to=_hhmm(lz))
            msg = tr('Đã lưu nhắc vận động vào vòng tay.')
        elif section == "dnd":
            mode = str(b["mode"])
            a, z = _time(b.get("from"), "23:00"), _time(b.get("to"), "07:00")
            lift = bool(b.get("lift"))
            if mode not in (P.DND_OFF, P.DND_AUTO, P.DND_SCHEDULED):
                raise ApiError(tr('Chế độ không hợp lệ.'))
            await band.write_config(P.do_not_disturb(mode, a, z, lift))
            st.update(dnd=mode, dnd_from=_hhmm(a), dnd_to=_hhmm(z), dnd_lift=lift)
            msg = tr('Đã lưu Không làm phiền vào vòng tay.')
        else:
            raise ApiError(tr('Mục cài đặt không tồn tại.'), 404)
        self.store.save()
        return msg

    async def save_alarms(self, items: list[dict]) -> None:
        band = self.require()
        alarms = []
        for i, a in enumerate(items[: P.MAX_ALARMS]):
            hour, minute, days = int(a.get("hour", 7)), int(a.get("minute", 0)), int(a.get("days", 0))
            if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= days < 128):
                raise ApiError(tr('Báo thức {n} có giờ không hợp lệ.', n=i + 1))
            alarms.append(P.Alarm(slot=i, enabled=bool(a.get("enabled")), hour=hour, minute=minute,
                                  days=days, in_use=bool(a.get("in_use"))))
        for a in alarms:
            await band.set_alarm(a)
        self.settings["alarms"] = [dataclasses.asdict(a) for a in alarms]
        self.live["alarms"] = [a for a in alarms if a.in_use]
        self.store.save()


# ================================================================ HTTP


def build_app(service: BandService, lan_token: str | None = None) -> web.Application:
    @web.middleware
    async def guard(request: web.Request, handler):
        host = request.host or ""
        hostname = urlparse(f"//{host}").hostname or ""
        if lan_token is None and hostname not in LOCAL_HOSTS:
            return web.json_response({"error": tr('Chỉ truy cập được từ chính máy này (localhost).')}, status=403)
        origin = request.headers.get("Origin")
        if origin and origin != "null" and urlparse(origin).netloc != host:
            return web.json_response({"error": tr('Yêu cầu từ trang web khác bị chặn.')}, status=403)
        if lan_token is not None:
            given = request.query.get("token") or request.cookies.get("mb6_token") or request.headers.get("X-Token")
            if not given or not secrets.compare_digest(given, lan_token):
                return web.Response(status=401, content_type="text/html", charset="utf-8",
                                    text=tr("<p style='font:16px sans-serif'>Cần mã truy cập. Mở đúng đường dẫn có <code>?token=…</code> mà server in ra trong Terminal.</p>"))
        if request.method == "POST" and request.path.startswith("/api/") and request.content_type != "application/json":
            return web.json_response({"error": tr('Cần gửi dữ liệu JSON.')}, status=415)
        try:
            resp = await handler(request)
        except ApiError as e:
            return web.json_response({"error": str(e)}, status=e.status)
        except (KeyError, ValueError, TypeError) as e:
            return web.json_response({"error": tr('Dữ liệu gửi lên không hợp lệ: {e}', e=e)}, status=400)
        except web.HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            service.log(tr('Lỗi: {e}', e=e))
            return web.json_response({"error": str(e) or type(e).__name__}, status=500)
        if lan_token is not None and request.query.get("token") and isinstance(resp, web.StreamResponse) \
                and not resp.prepared:
            resp.set_cookie("mb6_token", lan_token, httponly=True, samesite="Strict", max_age=30 * 86400)
        return resp

    app = web.Application(middlewares=[guard], client_max_size=MAX_UPLOAD)
    r = app.router
    S = service

    async def body(req) -> dict:
        try:
            data = await req.json()
        except ValueError as e:
            raise ApiError(tr('JSON không hợp lệ.')) from e
        if not isinstance(data, dict):
            raise ApiError(tr('JSON phải là một đối tượng.'))
        return data

    def ok(**kw):
        return web.json_response(jsonable({"ok": True, **kw}))

    async def index(_):
        version = str(int(max(f.stat().st_mtime for f in STATIC.iterdir())))
        html = (STATIC / "index.html").read_text("utf-8").replace("{{v}}", version)
        return web.Response(text=html, content_type="text/html", charset="utf-8",
                            headers={"Cache-Control": "no-cache"})

    async def meta(_):
        return ok(
            languages=P.LANGUAGES, date_formats=P.DATE_FORMATS, icons=P.NOTIFICATION_ICONS,
            menu_labels=P.MENU_LABELS, display_all=P.DISPLAY_ITEMS_ALL, display_default=P.DISPLAY_ITEMS_DEFAULT,
            menu_always_visible=P.MENU_ALWAYS_VISIBLE,
            shortcuts_all=P.SHORTCUTS_ALL, shortcuts_default=P.SHORTCUTS_DEFAULT, hr_intervals=P.HR_INTERVALS,
            hr_thresholds=P.HR_ALERT_THRESHOLDS, max_alarms=P.MAX_ALARMS, platform=sys.platform,
            server=SERVER_ID,
        )

    async def state(_):
        return ok(state=S.state())

    async def scan_h(req):
        b = await body(req)
        return ok(devices=await S.do_scan(bool(b.get("show_all"))))

    async def connect_h(req):
        b = await body(req)
        used = await S.connect(str(b.get("address") or ""), str(b.get("key") or ""), str(b.get("protocol") or PROTOCOL_AUTO))
        return ok(protocol=used, state=S.state())

    async def disconnect_h(_):
        await S.disconnect()
        return ok(state=S.state())

    async def reconnect_h(_):
        return ok(started=S.reconnect_now(), state=S.state())

    async def refresh_h(_):
        await S.require().refresh_all()
        return ok(live=S.live)

    async def time_h(_):
        band = S.require()
        await band.set_time()
        return ok(band_time=await band.read_time())

    async def hr_measure(_):
        band = S.require()
        try:
            bpm = await band.measure_heart_rate()
        except asyncio.TimeoutError as e:
            raise ApiError(tr('Không đo được. Đeo vòng sát cổ tay hơn rồi thử lại.'), 504) from e
        return ok(bpm=bpm)

    async def hr_live(req):
        on = bool((await body(req)).get("on"))
        await S.require().realtime_heart_rate(on)
        return ok(on=on)

    async def settings_h(req):
        return ok(message=await S.apply(req.match_info["section"], await body(req)), state=S.state())

    async def alarms_get(_):
        return ok(alarms=await S.require().request_alarms())

    async def alarms_post(req):
        await S.save_alarms(list((await body(req)).get("alarms") or []))
        return ok(message=tr('Đã lưu báo thức vào vòng tay.'))

    async def notify_h(req):
        b = await body(req)
        title, text = str(b.get("title") or ""), str(b.get("body") or "")
        if not (title or text):
            raise ApiError(tr('Nhập tiêu đề hoặc nội dung trước khi gửi.'))
        icon = int(b.get("icon", 11))
        if icon not in P.NOTIFICATION_ICONS.values():
            icon = 11
        await S.require().send_notification(title, text, str(b.get("app") or tr('Máy tính'))[:32], icon)
        return ok(message=tr('Đã gửi thông báo.'))

    async def call_h(req):
        await S.require().incoming_call(str((await body(req)).get("name") or tr('Không rõ'))[:64])
        return ok(message=tr('Đã gửi cuộc gọi.'))

    async def call_stop(_):
        await S.require().stop_call()
        return ok(message=tr('Đã kết thúc cuộc gọi.'))

    async def find_h(req):
        on = bool((await body(req)).get("on"))
        await S.require().find_band(on)
        return ok(message=tr('Vòng tay đang rung.') if on else tr('Đã dừng rung.'))

    def b64(value) -> bytes:
        text = str(value or "")
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        try:
            return base64.b64decode(text, validate=True)
        except ValueError as e:
            raise ApiError(tr('Tệp gửi lên bị hỏng, chọn lại tệp.')) from e

    def image(value) -> bytes:
        data = b64(value)
        if len(data) > 3 * 1024 * 1024:
            raise ApiError(tr('Ảnh xem trước quá lớn (tối đa 3 MB).'))
        if not any(data.startswith(m) for m in IMAGE_TYPES):
            raise ApiError(tr('Ảnh xem trước phải là PNG, JPEG hoặc GIF.'))
        return data

    async def health_get(req):
        date = req.query.get("date") or dt.date.today().isoformat()
        try:
            dt.date.fromisoformat(date)
        except ValueError as e:
            raise ApiError(tr('Ngày không hợp lệ.')) from e
        return ok(health=S.health_summary(date), status=S.health_status)

    async def health_sync(_):
        return ok(status=S.start_health_sync())

    async def track_get(req):
        try:
            start = int(req.match_info["start"])
        except ValueError as e:
            raise ApiError(tr('Không tìm thấy buổi tập này.'), 404) from e
        return ok(points=await S.workout_track(start))

    async def tracks_get(_):
        return ok(**S.all_tracks())

    async def weather_post(req):
        b = await body(req)
        S.set_weather_settings(b.get("enabled") if "enabled" in b else None, b["place"] if "place" in b else False)
        return ok(state=S.state())

    async def weather_sync(_):
        return ok(weather=await S.sync_weather())

    async def weather_search(req):
        return ok(places=await S.search_places(req.query.get("q", "")))

    async def watchface_inspect(req):
        """Kiểm tra tệp .bin và trả ảnh xem trước bên trong nó (để mô phỏng trước khi cài)."""
        data = b64((await body(req)).get("file"))
        try:
            P.check_watchface(data)
        except ValueError as e:
            raise ApiError(str(e)) from e
        status = S.face_status()

        def inspect() -> dict:
            def url(shot) -> str:
                return "data:image/png;base64," + base64.b64encode(WF.png(*shot)).decode()

            layers = WF.scene(data, status)
            if not layers:   # không vẽ được từ các lớp: dùng ảnh xem trước nhúng sẵn, nếu có
                shot = WF.embedded_preview(data)
                return {"preview": url(shot) if shot else None, "rendered": False, "animation": None}
            screen = (WF.SCREEN_W, WF.SCREEN_H)
            animation = {
                "below": url((*screen, layers["below"])),
                "above": url((*screen, layers["above"])) if layers["above"] else None,
                "items": [{"x": a["x"], "y": a["y"], "interval": a["interval"], "frames": [url(f) for f in a["frames"]]}
                          for a in layers["animations"]],
            } if layers["animations"] else None
            return {"preview": url(WF.flatten(layers)), "rendered": True, "animation": animation}

        return ok(size=len(data), **await asyncio.to_thread(inspect))

    async def watchface_post(req):
        b = await body(req)
        data = b64(b.get("file"))
        preview = image(b["preview"]) if b.get("preview") else None
        message = await S.install_watchface(str(b.get("name") or "watchface.bin"), data, preview)
        return ok(message=message, state=S.state())

    def rgba(value, max_w: int, max_h: int) -> tuple[int, int, bytes]:
        if not isinstance(value, dict):
            raise ApiError(tr('Thiếu dữ liệu ảnh.'))
        w, h = int(value.get("w", 0)), int(value.get("h", 0))
        if not (0 < w <= max_w and 0 < h <= max_h):
            raise ApiError(tr('Kích thước ảnh không hợp lệ.'))
        return w, h, b64(value.get("rgba"))

    async def wallpaper_post(req):
        """Tạo mặt đồng hồ từ ảnh nền đã cắt sẵn trên trình duyệt (152x486) rồi cài lên vòng tay."""
        b = await body(req)
        _w, _h, background = rgba(b.get("background"), WF.SCREEN_W, WF.SCREEN_H)
        preview = rgba(b.get("preview"), WF.SCREEN_W, WF.SCREEN_H)
        digits = [rgba(d, WF.SCREEN_W, 200) for d in b.get("digits") or []]
        hours = tuple(int(v) for v in b["hours"]) if b.get("hours") else None
        minutes = tuple(int(v) for v in b["minutes"]) if b.get("minutes") else None
        try:
            data = WF.wallpaper_face(background, preview, digits, hours, minutes)
        except ValueError as e:
            raise ApiError(tr('Không tạo được mặt đồng hồ: {e}', e=e)) from e
        shot = image(b["image"]) if b.get("image") else None
        message = await S.install_watchface(tr('Ảnh nền tùy chỉnh'), data, shot)
        return ok(message=message, state=S.state())

    async def watchface_preview_get(_):
        path = S.watchface_dir / "preview"
        if not path.is_file():
            raise web.HTTPNotFound()
        data = path.read_bytes()
        ctype = next((t for magic, t in IMAGE_TYPES.items() if data.startswith(magic)), "application/octet-stream")
        return web.Response(body=data, content_type=ctype, headers={"Cache-Control": "no-cache"})

    async def watchface_preview_post(req):
        b = await body(req)
        S.set_watchface_preview(image(b["image"]) if b.get("image") else None)
        return ok(state=S.state())

    async def find_phone_stop(_):
        S.stop_beep()
        return ok()

    async def prefs_h(req):
        b = await body(req)
        if "find_sound" in b:
            S.settings["find_sound"] = bool(b["find_sound"])
        if b.get("lang") in ("vi", "en"):
            S.settings["ui_lang"] = set_lang(b["lang"])
        if isinstance(b.get("sync"), dict):
            S.set_sync_settings(b["sync"])
        if b.get("rem_mode") in ("estimate", "off"):
            S.settings["rem_mode"] = b["rem_mode"]
            S._insight_cache = {}
            S.push({"type": "health_data"})
        S.store.save()
        if "keep_connected" in b:
            S.set_keep_connected(bool(b["keep_connected"]))
        S.push_state()  # trình duyệt khác và thanh menu của ứng dụng macOS cũng thấy thay đổi
        return ok(state=S.state())

    async def cloud_sync(req):
        b = await body(req)
        return ok(cloud=S.cloud.start(bool(b.get("write", True)), bool(b.get("fresh")), job=str(b.get("job") or "profile")))

    async def cloud_status(_):
        return ok(cloud=S.cloud.status)

    async def cloud_cancel(_):
        return ok(cloud=S.cloud.cancel())

    async def cloud_forget(_):
        S.cloud.forget()
        S.push_state()
        return ok(cloud=S.cloud.status, account=S.cloud_account())

    async def cloud_account_get(_):
        return ok(account=S.cloud_account())

    async def cloud_renew(_):
        return ok(account=await S.renew_session())

    async def forget_h(req):
        S.store.forget_device(str((await body(req)).get("address") or ""))
        return ok(state=S.state())

    async def log_get(_):
        return ok(lines=list(S.logs))

    async def log_clear(_):
        S.logs.clear()
        return ok()

    async def events(req):
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(req)
        S.clients.add(ws)
        await ws.send_str(json.dumps(jsonable({"type": "hello", "state": S.state(), "logs": list(S.logs)[-400:]}),
                                     ensure_ascii=False))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            S.clients.discard(ws)
        return ws

    r.add_get("/", index)
    r.add_static("/static/", STATIC, append_version=True)
    r.add_get("/api/meta", meta)
    r.add_get("/api/state", state)
    r.add_get("/api/events", events)
    r.add_get("/api/log", log_get)
    r.add_get("/api/alarms", alarms_get)
    r.add_post("/api/scan", scan_h)
    r.add_post("/api/connect", connect_h)
    r.add_post("/api/disconnect", disconnect_h)
    r.add_post("/api/reconnect", reconnect_h)
    r.add_post("/api/refresh", refresh_h)
    r.add_post("/api/time/sync", time_h)
    r.add_post("/api/hr/measure", hr_measure)
    r.add_post("/api/hr/live", hr_live)
    r.add_post("/api/settings/{section}", settings_h)
    r.add_post("/api/alarms", alarms_post)
    r.add_post("/api/notify", notify_h)
    r.add_post("/api/call", call_h)
    r.add_post("/api/call/stop", call_stop)
    r.add_post("/api/find", find_h)
    r.add_post("/api/find-phone/stop", find_phone_stop)
    r.add_post("/api/prefs", prefs_h)
    r.add_post("/api/devices/forget", forget_h)
    r.add_post("/api/log/clear", log_clear)
    r.add_get("/api/health", health_get)
    r.add_post("/api/health/sync", health_sync)
    r.add_get("/api/workouts/{start}/track", track_get)
    r.add_get("/api/tracks", tracks_get)
    r.add_post("/api/weather", weather_post)
    r.add_post("/api/weather/sync", weather_sync)
    r.add_get("/api/weather/search", weather_search)
    r.add_post("/api/watchface", watchface_post)
    r.add_post("/api/watchface/inspect", watchface_inspect)
    r.add_post("/api/wallpaper", wallpaper_post)
    r.add_get("/api/watchface/preview", watchface_preview_get)
    r.add_post("/api/watchface/preview", watchface_preview_post)
    r.add_get("/api/cloud", cloud_status)
    r.add_post("/api/cloud/sync", cloud_sync)
    r.add_post("/api/cloud/cancel", cloud_cancel)
    r.add_post("/api/cloud/forget", cloud_forget)
    r.add_get("/api/cloud/account", cloud_account_get)
    r.add_post("/api/cloud/renew", cloud_renew)

    async def on_shutdown(_app):
        S.want_connected = False
        S._cancel_reconnect()
        for ws in list(S.clients):
            await ws.close()
        if S.band and S.band.is_connected:
            try:
                await asyncio.wait_for(S.band.disconnect(), 4)
            except Exception:  # noqa: BLE001
                pass

    app.on_shutdown.append(on_shutdown)
    return app


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


async def running_server(port: int) -> str | None:
    """Địa chỉ của một server Quản lý Mi Band 6 đang chạy sẵn trên cổng này (ví dụ ứng dụng macOS), nếu có."""
    from aiohttp import ClientError, ClientSession, ClientTimeout

    try:
        async with ClientSession(timeout=ClientTimeout(total=2)) as s:
            async with s.get(f"http://127.0.0.1:{port}/api/meta") as r:
                data = await r.json(content_type=None)
    except (ClientError, asyncio.TimeoutError, ValueError, OSError):
        return None
    return f"http://localhost:{port}/" if isinstance(data, dict) and data.get("server") == SERVER_ID else None


async def _watch_parent(stop: asyncio.Event) -> None:
    """Chế độ --app: ứng dụng macOS bị tắt đột ngột thì server cũng thoát để nhả kết nối Bluetooth."""
    parent = os.getppid()
    while not stop.is_set():
        if os.getppid() != parent:
            stop.set()
            return
        await asyncio.sleep(2)


def _announce(port: int) -> None:
    print(f"{READY_PREFIX} http://127.0.0.1:{port}/", flush=True)


async def serve(args) -> None:
    env_path = load_env(args.env)
    if env_path and not args.demo:
        # phiên đăng nhập Xiaomi được lưu cả vào .env này; chép phiên đang có vào nếu .env chưa có
        XC.ENV_FILE = env_path
        login = XC.XiaomiLogin()
        if not os.environ.get(XC.ENV_SESSION) and login.load():
            login.save()
    env_key, env_address, env_protocol = env_settings()
    if env_key:
        try:
            P.parse_auth_key(env_key)
        except ValueError as e:
            print(tr('Cảnh báo: MIBAND6_AUTH_KEY trong {path} không hợp lệ ({e}); bỏ qua.', path=env_path or '.env', e=e))
            env_key = None
    if env_protocol not in (None, PROTOCOL_AUTO, PROTOCOL_CLASSIC, PROTOCOL_2021):
        print(tr('Cảnh báo: MIBAND6_PROTOCOL={env_protocol} không hợp lệ; dùng auto.', env_protocol=env_protocol))
        env_protocol = None
    stop = asyncio.Event()
    with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):  # Windows không có SIGTERM
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    watcher = asyncio.ensure_future(_watch_parent(stop)) if args.app else None

    # Chỉ một server được giữ vòng tay (vòng tay nhận một kết nối): nếu đã có server chạy sẵn thì dùng nó.
    if not (args.lan or args.demo) and (existing := await running_server(args.port)):
        if not args.app:
            print(tr('Quản lý Mi Band 6 đã chạy sẵn tại {url} (có thể là ứng dụng macOS). Mở giao diện đó thay vì chạy thêm một server.', url=existing))
            if not args.no_browser:
                webbrowser.open(existing)
            return
        # ứng dụng macOS: hiện giao diện của server đang chạy, khi server đó tắt thì tự chạy server của mình
        _announce(args.port)
        while not stop.is_set() and await running_server(args.port):
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), 3)
        if stop.is_set():
            return

    store = Store(Path(tempfile.gettempdir()) / "miband6-demo-config.json") if args.demo else Store()
    service = BandService(store, demo=args.demo, env_key=env_key, env_address=env_address, env_protocol=env_protocol)
    token = secrets.token_urlsafe(16) if args.lan else None
    app = build_app(service, token)
    runner = web.AppRunner(app)
    await runner.setup()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    port = args.port
    for _ in range(20):
        try:
            site = web.TCPSite(runner, host, port)
            await site.start()
            break
        except OSError:
            port += 1
    else:
        raise SystemExit(tr('Không tìm được cổng trống để chạy server.'))

    q = f"?token={token}" if token else ""
    local_url = f"http://localhost:{port}/{q}"
    print(tr('Quản lý Mi Band 6 đang chạy') + (tr(' (chế độ xem thử, vòng tay giả lập)') if args.demo else ""))
    print(tr('  Trên máy này:  {local_url}', local_url=local_url))
    if token:
        print(tr('  Trong mạng Wi-Fi: http://{ip}:{port}/{q}', ip=lan_ip(), port=port, q=q))
        print(tr('  Ai có đường dẫn kèm mã này đều điều khiển được vòng tay; đừng chia sẻ nó.'))
    if env_key:
        print(tr('  Auth key: đọc từ {path} (không lưu vào config.json)', path=env_path or tr('biến môi trường')))
    print(tr('Nhấn Ctrl+C để tắt server.'))
    if args.app:
        _announce(port)
    elif not args.no_browser:
        webbrowser.open(local_url)
    service.start()
    try:
        await stop.wait()
    finally:
        if watcher:
            watcher.cancel()
        await runner.cleanup()


def main() -> None:
    try:
        set_lang(Store().data.get("settings", {}).get("ui_lang", "vi"))
    except OSError:
        pass
    ap = argparse.ArgumentParser(prog="miband6-web", description=tr('Server web quản lý Mi Band 6 qua Bluetooth.'))
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--demo", action="store_true", help=tr('Dùng vòng tay giả lập, không cần Bluetooth'))
    ap.add_argument("--lan", action="store_true", help=tr('Cho thiết bị khác trong mạng truy cập (có mã bảo vệ)'))
    ap.add_argument("--no-browser", action="store_true", help=tr('Không tự mở trình duyệt'))
    ap.add_argument("--env", metavar="TỆP", help=tr('Tệp .env chứa MIBAND6_AUTH_KEY (mặc định: .env trong thư mục dự án)'))
    ap.add_argument("--app", action="store_true", help=argparse.SUPPRESS)  # do ứng dụng macOS gọi
    args = ap.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print(tr('\nĐã tắt server.'))


if __name__ == "__main__":
    main()
