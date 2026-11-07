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
from .. import health as H
from ..xiaomi_cloud import (LoginError, SessionExpired, XiaomiLogin, fetch_profile, fetch_sleep_reports,
                            fetch_sport_records, profile_for_band)

ACTIVE = ("checking", "login", "fetching")
JOBS = ("profile", "workouts")
CLOUD_HISTORY_DAYS = 5 * 365   # lịch sử buổi tập lấy từ Mi Fitness


def NO_PROFILE() -> str:  # noqa: N802
    return tr('Đã đăng nhập nhưng không đọc được hồ sơ từ Mi Fitness. Chi tiết có trong Nhật ký Bluetooth ở mục Thiết bị.')

DEMO_PROFILE = {"name": "Demo", "birth": "1995-06-15", "sex": "male", "height": 172, "weight": 64.5,
                "daily_step_goal": 9000}


def demo_sport_records() -> list[dict]:
    """Vài buổi tập kiểu tài khoản Mi Fitness cho chế độ xem thử (cũ hơn dữ liệu của vòng tay giả lập)."""
    now = int(time.time())
    out = []
    for i, (kind, minutes, dist, cal, steps, hr) in enumerate([(1, 28, 4600, 290, 4900, 148), (6, 55, 17000, 410, 0, 131),
                                                               (308, 40, 0, 210, 0, 118), (1, 35, 5600, 350, 6000, 152)]):
        start = now - (20 + 9 * i) * 86400 - 6 * 3600
        out.append({"start_time": start, "end_time": start + minutes * 60, "duration": minutes * 60, "sport_type": kind,
                    "distance": dist, "calories": cal, "steps": steps, "avg_hrm": hr, "max_hrm": hr + 22, "timezone": 28,
                    "time": start + minutes * 60, "proto_type": {1: 22, 6: 23}.get(kind, 30),
                    "_sid": "demo", "_region": "sg"})
    return out


def demo_sleep_reports(db) -> list[dict]:
    """Báo cáo giấc ngủ kiểu Mi Fitness cho chế độ xem thử, dựng từ các đêm của vòng tay giả lập."""
    if db is None:
        return []
    now = int(time.time())
    out = []
    for s in db.sleep_sessions(now - 30 * 86400, now):
        if s["minutes"] < 180 or s.get("ongoing"):
            continue
        minutes = s["minutes"] - 3
        deep = round(minutes * 0.14)
        out.append({"start": s["start"] + 120, "end": s["end"] - 60, "minutes": minutes, "deep": deep, "rem": 0,
                    "light": minutes - deep, "awake": s["awake"], "score": 70, "date": H.local_date(s["end"])})
    return out


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
        self.job = "profile"
        self.since: int | None = None     # lịch sử buổi tập: chỉ lấy từ thời điểm này (None: cả lịch sử)
        self.sleep_from: int | None = None   # báo cáo giấc ngủ: lấy từ thời điểm này (cùng lượt với buổi tập)
        self.interactive = True

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def _set(self, **status) -> None:
        self._seq += 1
        self.status = {**status, "job": self.job, "seq": self._seq}
        self.service.push({"type": "cloud", "status": self.status})

    def start(self, write: bool = True, fresh: bool = False, interactive: bool = True, job: str = "profile",
              since: int | None = None) -> dict:
        """job: "profile" (hồ sơ, ghi vào vòng tay) hoặc "workouts" (lịch sử buổi tập).

        interactive=False: chạy ngầm khi kết nối vòng tay; chỉ dùng phiên đăng nhập đã lưu, không hiện mã QR.
        Người dùng bấm đồng bộ trong lúc một lượt chạy ngầm: dừng lượt ngầm, chạy lượt của người dùng."""
        if self.running:
            if self.interactive or not interactive:
                return self.status
            self._cancel.set()
            self._task.cancel()
        if fresh:
            self.factory.forget()
        self.job = job if job in JOBS else "profile"
        self.since = since
        self.sleep_from = self._sleep_from() if self.job == "workouts" else None
        self.interactive = interactive
        self._cancel = threading.Event()
        if interactive:
            self._set(state="checking")
        self._task = asyncio.ensure_future(self._run(write, interactive))
        return self.status

    def _sleep_from(self) -> int:
        """Báo cáo giấc ngủ cần lấy: lần đầu từ ngày cũ nhất có dữ liệu vòng tay, sau đó từ lần trước lùi 3 ngày (Mi
        Fitness còn cập nhật báo cáo vài ngày gần nhất). Tính ở đây vì HealthDB chỉ dùng được trên luồng chính."""
        db = self.service.health_db()
        last = db.last("mf_sleep") if db else None
        if last:
            return last - 3 * 86400
        first = db.first("activity") if db else None
        return int(first or time.time()) - 86400

    async def wait(self) -> None:
        """Chờ lượt đang chạy xong (không ném lỗi nếu lượt đó bị hủy)."""
        if self._task is not None:
            await asyncio.wait([self._task])

    def cancel(self) -> dict:
        self._cancel.set()
        if self.running:
            self._task.cancel()
        self._set(state="idle")
        return self.status

    def forget(self) -> None:
        self.cancel()
        self.factory.forget()

    async def _run(self, write: bool, interactive: bool = True) -> None:
        try:
            raw = await (self._demo() if self.demo else self._fetch(interactive))
            if raw is None or self._cancel.is_set():
                return
            if self.job == "workouts":
                message = self.service.import_cloud_workouts(raw)
                self._set(state="done", message=message)
                return
            # chỉ tên các trường (không có giá trị) để chẩn đoán khi thiếu thông tin, ví dụ biệt danh
            self.service.log("Mi Fitness: " + tr('hồ sơ có các trường {fields}', fields=", ".join(sorted(map(str, raw)))))
            values = profile_for_band(raw)
            if not values:
                raise LoginError(tr('Tài khoản Mi Fitness chưa có thông tin hồ sơ.'))
            message = await self.service.apply_cloud_profile(values, write, interactive=interactive)
            self._set(state="done", profile=values, message=message)
        except asyncio.CancelledError:
            pass
        except LoginError as e:
            if not interactive:
                self._log_background(e)
            elif not self._cancel.is_set():
                self._set(state="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - lỗi mạng, máy chủ trả dữ liệu lạ…
            if not interactive:
                self._log_background(e)
            elif not self._cancel.is_set():
                self._set(state="error", error=tr('Không đồng bộ được với Mi Fitness: {e}', e=e))

    def _log_background(self, e: Exception) -> None:
        if self.job == "workouts":
            self.service.log(tr('Không tự lấy được buổi tập từ Mi Fitness: {e}', e=e))
        else:
            self.service.log(tr('Không tự lấy được hồ sơ Mi Fitness: {e}', e=e))

    async def _demo(self):
        await asyncio.sleep(0.6)
        self._set(state="fetching")
        await asyncio.sleep(0.6)
        if self.job == "workouts":
            return {"workouts": demo_sport_records(), "sleep": demo_sleep_reports(self.service.health_db())}
        return dict(DEMO_PROFILE)

    def _download(self, login):
        """Gọi API của việc đang làm; trả về (dữ liệu, nhật ký)."""
        if self.job == "workouts":
            end = int(time.time())
            records, trail = fetch_sport_records(login, self.since or end - CLOUD_HISTORY_DAYS * 86400, end)
            try:   # cùng lượt: báo cáo giấc ngủ (để so và hiệu chỉnh thuật toán giấc ngủ); lỗi thì vẫn giữ buổi tập
                sleep, more = fetch_sleep_reports(login, self.sleep_from or end - 30 * 86400, end)
            except SessionExpired:
                raise
            except Exception as e:  # noqa: BLE001
                sleep, more = None, [f"sleep: {type(e).__name__}"]
            return {"workouts": records, "sleep": sleep}, trail + more
        return fetch_profile(login)

    def _checked(self, raw, trail: list[str]):
        if self.job == "workouts":
            self._log(trail)
            return raw
        if raw is None:
            self._log(trail)
            raise LoginError(NO_PROFILE())
        return raw

    async def _fetch(self, interactive: bool = True):
        login = self.factory()
        if await asyncio.to_thread(login.load):
            try:
                if interactive:
                    self._set(state="fetching")
                raw, trail = await asyncio.to_thread(self._download, login)
            except SessionExpired:
                self.factory.forget()
                self.service.push_state()   # Cài đặt ứng dụng hiện "Chưa đăng nhập"
                login = self.factory()
            else:
                return self._checked(raw, trail)
        if not interactive:
            return None
        self._set(state="checking")
        q = await asyncio.to_thread(login.start_qr)
        self._set(state="login", qr="data:image/png;base64," + base64.b64encode(q["qr"]).decode(),
                  url=q["login_url"], expires=int(time.time() + q["timeout"]))
        await asyncio.to_thread(login.wait_qr, q, None, self._cancel)
        await asyncio.to_thread(login.save)
        # trạng thái tài khoản nằm trong state(): đẩy ngay, không thì Cài đặt ứng dụng vẫn hiện "Chưa đăng nhập"
        self.service.push_state()
        self._set(state="fetching")
        raw, trail = await asyncio.to_thread(self._download, login)
        return self._checked(raw, trail)

    def _log(self, trail: list[str]) -> None:
        for line in trail:
            self.service.log("Mi Fitness: " + line)
