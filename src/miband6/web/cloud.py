"""Đồng bộ hồ sơ người dùng từ tài khoản Mi Fitness (đăng nhập Xiaomi bằng mã QR).

Vòng tay không cho đọc ngược hồ sơ qua Bluetooth, nên chiều cao, cân nặng, ngày sinh, giới tính và
mục tiêu bước được lấy từ tài khoản Mi Fitness rồi ghi vào vòng tay.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time

from ..i18n import tr
from ..xiaomi_cloud import LoginError, SessionExpired, XiaomiLogin, fetch_profile, profile_for_band

ACTIVE = ("checking", "login", "fetching")


def NO_PROFILE() -> str:  # noqa: N802
    return tr('Đã đăng nhập nhưng không đọc được hồ sơ từ Mi Fitness. Chi tiết có trong Nhật ký Bluetooth ở mục Thiết bị.')

DEMO_PROFILE = {"name": "Demo", "birth": "1995-06-15", "sex": "male", "height": 172, "weight": 64.5,
                "daily_step_goal": 9000}


class CloudSync:
    """Một lượt đồng bộ chạy nền; trạng thái được đẩy tới trình duyệt qua WebSocket (kiểu "cloud")."""

    def __init__(self, service, login_factory=XiaomiLogin, demo: bool = False):
        self.service = service
        self.factory = login_factory
        self.demo = demo
        self.status: dict = {"state": "idle", "seq": 0}
        self._seq = 0
        self._task: asyncio.Task | None = None
        self._cancel = threading.Event()

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def _set(self, **status) -> None:
        self._seq += 1
        self.status = {**status, "seq": self._seq}
        self.service.push({"type": "cloud", "status": self.status})

    def start(self, write: bool = True, fresh: bool = False) -> dict:
        if self.running:
            return self.status
        if fresh:
            self.factory.forget()
        self._cancel = threading.Event()
        self._set(state="checking")
        self._task = asyncio.ensure_future(self._run(write))
        return self.status

    def cancel(self) -> dict:
        self._cancel.set()
        if self.running:
            self._task.cancel()
        self._set(state="idle")
        return self.status

    def forget(self) -> None:
        self.cancel()
        self.factory.forget()

    async def _run(self, write: bool) -> None:
        try:
            raw = await (self._demo() if self.demo else self._fetch())
            if self._cancel.is_set():
                return
            values = profile_for_band(raw)
            if not values:
                raise LoginError(tr('Tài khoản Mi Fitness chưa có thông tin hồ sơ.'))
            message = await self.service.apply_cloud_profile(values, write)
            self._set(state="done", profile=values, message=message)
        except asyncio.CancelledError:
            pass
        except LoginError as e:
            if not self._cancel.is_set():
                self._set(state="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - lỗi mạng, máy chủ trả dữ liệu lạ…
            if not self._cancel.is_set():
                self._set(state="error", error=tr('Không đồng bộ được với Mi Fitness: {e}', e=e))

    async def _demo(self) -> dict:
        await asyncio.sleep(0.6)
        self._set(state="fetching")
        await asyncio.sleep(0.6)
        return dict(DEMO_PROFILE)

    async def _fetch(self) -> dict:
        login = self.factory()
        if await asyncio.to_thread(login.load):
            try:
                self._set(state="fetching")
                raw, trail = await asyncio.to_thread(fetch_profile, login)
            except SessionExpired:
                self.factory.forget()
                login = self.factory()
            else:
                if raw is None:
                    self._log(trail)
                    raise LoginError(NO_PROFILE())
                return raw
        self._set(state="checking")
        q = await asyncio.to_thread(login.start_qr)
        self._set(state="login", qr="data:image/png;base64," + base64.b64encode(q["qr"]).decode(),
                  url=q["login_url"], expires=int(time.time() + q["timeout"]))
        await asyncio.to_thread(login.wait_qr, q, None, self._cancel)
        await asyncio.to_thread(login.save)
        self._set(state="fetching")
        raw, trail = await asyncio.to_thread(fetch_profile, login)
        if raw is None:
            self._log(trail)
            raise LoginError(NO_PROFILE())
        return raw

    def _log(self, trail: list[str]) -> None:
        for line in trail:
            self.service.log("Mi Fitness: " + line)
