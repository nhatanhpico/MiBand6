"""Server web chạy trên máy tính: điều khiển Mi Band 6 qua Bluetooth, giao diện mở trong trình duyệt.

    uv run miband6-web            # mở http://localhost:8766 trong trình duyệt
    uv run miband6-web --demo     # vòng tay giả lập, không dùng Bluetooth
    uv run miband6-web --lan      # cho thiết bị khác trong mạng Wi-Fi truy cập (cần mã truy cập)
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import secrets
import socket
import sys
import tempfile
import webbrowser
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from .. import protocol as P
from ..config import Store
from ..envfile import env_settings, load_env
from ..i18n import set_lang, tr
from ..device import PROTOCOL_2021, PROTOCOL_AUTO, PROTOCOL_CLASSIC, AuthError, MiBand6, scan
from .cloud import CloudSync

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8766
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


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
        self.band: MiBand6 | None = None
        self.scan_cache: dict[str, tuple[object, str]] = {}
        self.busy = False
        self.clients: set[web.WebSocketResponse] = set()
        self.logs: deque[str] = deque(maxlen=3000)
        self.live: dict = {}
        self.device_meta: dict = {}
        self._tasks: set[asyncio.Task] = set()
        self._stop_beep = True
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
            "profile": self.profile,
            "saved_devices": devices,
            "last_device": self.store.data.get("last_device") or self.env_address,
            "env_key": bool(self.env_key),
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
            self.push({"type": "disconnected"})
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
                raise ApiError(
                    tr('Không quét được Bluetooth ({e}). Kiểm tra Bluetooth đã bật và Terminal đã có quyền Bluetooth.', e=e), 503
                ) from e
        self.scan_cache = {dev.address: (dev, name) for dev, _rssi, _b, name in results}
        return [{"name": name or "", "address": dev.address, "rssi": rssi, "is_band": is_band}
                for dev, rssi, is_band, name in results]

    async def connect(self, address: str, key_text: str, proto: str) -> str:
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
        try:
            if self.band:
                await self.band.disconnect()
            client = None
            if self.demo:
                from ..simulator import FakeBand

                client = FakeBand(key, "both")
                client.hr_delay = 6.0
            self.band = MiBand6(target, key, proto, on_event=self.on_event, log=self.log, client=client, name=name)
            used = await self.band.connect()
        except AuthError as e:
            raise ApiError(str(e), 401) from e
        except Exception as e:  # noqa: BLE001
            raise ApiError(tr('Không kết nối được: {e}', e=e), 502) from e
        finally:
            self.busy = False
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
        self.profile.update(values)
        self.profile["pending_sync"] = True
        self.store.save()
        message = tr('Đã lấy hồ sơ từ Mi Fitness. Hồ sơ sẽ được ghi vào vòng tay khi kết nối.')
        if write and self.connected:
            await self._write_profile()
            message = tr('Đã lấy hồ sơ từ Mi Fitness và ghi vào vòng tay.')
        self.push_state()
        return message

    async def disconnect(self) -> None:
        if self.band:
            await self.band.disconnect()
        self.live = {}
        self.push_state()

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

    app = web.Application(middlewares=[guard])
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

    async def find_phone_stop(_):
        S.stop_beep()
        return ok()

    async def prefs_h(req):
        b = await body(req)
        if "find_sound" in b:
            S.settings["find_sound"] = bool(b["find_sound"])
        if b.get("lang") in ("vi", "en"):
            S.settings["ui_lang"] = set_lang(b["lang"])
        S.store.save()
        return ok(state=S.state())

    async def cloud_sync(req):
        b = await body(req)
        return ok(cloud=S.cloud.start(bool(b.get("write", True)), bool(b.get("fresh"))))

    async def cloud_status(_):
        return ok(cloud=S.cloud.status)

    async def cloud_cancel(_):
        return ok(cloud=S.cloud.cancel())

    async def cloud_forget(_):
        S.cloud.forget()
        return ok(cloud=S.cloud.status)

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
    r.add_get("/api/cloud", cloud_status)
    r.add_post("/api/cloud/sync", cloud_sync)
    r.add_post("/api/cloud/cancel", cloud_cancel)
    r.add_post("/api/cloud/forget", cloud_forget)

    async def on_shutdown(_app):
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


async def serve(args) -> None:
    env_path = load_env(args.env)
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
    if not args.no_browser:
        webbrowser.open(local_url)
    try:
        await asyncio.Event().wait()
    finally:
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
    args = ap.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print(tr('\nĐã tắt server.'))


if __name__ == "__main__":
    main()
