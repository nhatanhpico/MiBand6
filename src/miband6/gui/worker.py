"""Chạy vòng lặp asyncio (bleak) trong một luồng riêng và chuyển kết quả về luồng giao diện Qt."""

from __future__ import annotations

import asyncio
import threading
import traceback
from typing import Any, Awaitable, Callable

from PySide6.QtCore import QObject, Signal


class BleWorker(QObject):
    event = Signal(str, object)      # sự kiện từ vòng tay (pin, bước, nhịp tim…)
    log = Signal(str)                # dòng nhật ký
    _done = Signal(int, object)      # (mã tác vụ, kết quả)
    _failed = Signal(int, object)    # (mã tác vụ, Exception)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble-loop", daemon=True)
        self._thread.start()
        self._callbacks: dict[int, tuple[Callable | None, Callable | None]] = {}
        self._next = 0
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # các hàm này được gọi từ luồng BLE; tín hiệu Qt tự chuyển sang luồng giao diện
    def emit_event(self, kind: str, data: Any) -> None:
        self.event.emit(kind, data)

    def emit_log(self, msg: str) -> None:
        self.log.emit(msg)

    def submit(
        self,
        make_coro: Callable[[], Awaitable[Any]],
        on_ok: Callable[[Any], None] | None = None,
        on_err: Callable[[Exception], None] | None = None,
    ) -> int:
        self._next += 1
        tid = self._next
        self._callbacks[tid] = (on_ok, on_err)

        async def runner():
            try:
                res = await make_coro()
            except Exception as e:  # noqa: BLE001
                self.log.emit("".join(traceback.format_exception_only(type(e), e)).strip())
                self._failed.emit(tid, e)
            else:
                self._done.emit(tid, res)

        asyncio.run_coroutine_threadsafe(runner(), self.loop)
        return tid

    def _on_done(self, tid: int, res: Any) -> None:
        ok, _ = self._callbacks.pop(tid, (None, None))
        if ok:
            ok(res)

    def _on_failed(self, tid: int, err: Exception) -> None:
        _, bad = self._callbacks.pop(tid, (None, None))
        if bad:
            bad(err)

    def shutdown(self, final: Callable[[], Awaitable[Any]] | None = None, timeout: float = 4.0) -> None:
        if final is not None:
            fut = asyncio.run_coroutine_threadsafe(final(), self.loop)
            try:
                fut.result(timeout)
            except Exception:
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)
