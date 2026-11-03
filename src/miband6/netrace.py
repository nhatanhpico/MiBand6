"""Kết nối TCP "đua" nhiều địa chỉ cùng lúc (Happy Eyeballs, RFC 8305) cho requests / urllib3.

Máy chủ tệp của Xiaomi (alsgp0.fds.api.xiaomi.com) trả về ba địa chỉ IP; từ một số mạng, hai địa chỉ không trả lời.
requests thử lần lượt từng địa chỉ theo thứ tự DNS và chờ mỗi địa chỉ chết khoảng 30 giây, nên mỗi lần tải mất tới
60 giây. Ở đây mọi địa chỉ được thử gần như cùng lúc (cách nhau ATTEMPT_DELAY giây, như trình duyệt), địa chỉ trả
lời trước được dùng và được nhớ để lần sau thử nó trước tiên.
"""

from __future__ import annotations

import errno
import os
import selectors
import socket
import threading
import time

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util.timeout import _DEFAULT_TIMEOUT

ATTEMPT_DELAY = 0.25   # giây giữa hai lần thử địa chỉ kế tiếp (RFC 8305 khuyên 250 ms)
WINNER_TTL = 600       # nhớ địa chỉ trả lời nhanh trong chừng này giây
_winners: dict[tuple[str, int], tuple[tuple, float]] = {}
_lock = threading.Lock()


def _ordered(host: str, port: int, infos: list) -> list:
    """Địa chỉ thắng lần trước lên đầu; còn lại xen kẽ IPv6 / IPv4 như RFC 8305 mục 4."""
    with _lock:
        hit = _winners.get((host, port))
    first = []
    if hit and hit[1] > time.monotonic():
        first = [i for i in infos if i[4] == hit[0]]
    rest = [i for i in infos if i not in first]
    v6 = [i for i in rest if i[0] == socket.AF_INET6]
    v4 = [i for i in rest if i[0] != socket.AF_INET6]
    mixed = []
    for k in range(max(len(v6), len(v4))):
        mixed += v6[k:k + 1] + v4[k:k + 1]
    return first + mixed


def race_connect(address: tuple[str, int], timeout=_DEFAULT_TIMEOUT, source_address=None, socket_options=None,
                 attempt_delay: float = ATTEMPT_DELAY) -> socket.socket:
    """Như urllib3.util.connection.create_connection nhưng thử các địa chỉ song song; trả socket đầu tiên nối được."""
    host, port = address
    if host.startswith("["):
        host = host.strip("[]")
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos:
        raise OSError("getaddrinfo returns an empty list")
    infos = _ordered(host, port, infos)
    has_timeout = timeout is not _DEFAULT_TIMEOUT and timeout is not None
    deadline = time.monotonic() + timeout if has_timeout else None
    sel = selectors.DefaultSelector()
    pending: list[socket.socket] = []
    errors: list[OSError] = []
    idx = 0
    next_at = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise TimeoutError("timed out")
            if idx < len(infos) and (now >= next_at or not pending):
                family, socktype, proto, _name, sockaddr = infos[idx]
                idx += 1
                sock = None
                try:
                    sock = socket.socket(family, socktype, proto)
                    for opt in socket_options or ():
                        sock.setsockopt(*opt)
                    if source_address:
                        sock.bind(source_address)
                    sock.setblocking(False)
                    rc = sock.connect_ex(sockaddr)
                    if rc not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                        raise OSError(rc, os.strerror(rc))
                    sel.register(sock, selectors.EVENT_WRITE, sockaddr)
                    pending.append(sock)
                except OSError as e:
                    errors.append(e)
                    if sock is not None:
                        sock.close()
                next_at = time.monotonic() + attempt_delay
                continue
            if not pending:
                raise errors[-1] if errors else OSError(f"cannot connect to {host}:{port}")
            waits = []
            if deadline is not None:
                waits.append(deadline - now)
            if idx < len(infos):
                waits.append(next_at - now)
            for key, _events in sel.select(max(0.0, min(waits)) if waits else None):
                sock = key.fileobj
                sel.unregister(sock)
                pending.remove(sock)
                err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err:
                    errors.append(OSError(err, os.strerror(err)))
                    sock.close()
                    continue
                sock.setblocking(True)
                if has_timeout:
                    sock.settimeout(timeout)
                with _lock:
                    _winners[(host, port)] = (key.data, time.monotonic() + WINNER_TTL)
                return sock
    finally:
        for sock in pending:   # các lần thử còn dang dở (đã có socket thắng hoặc đã hết giờ)
            sock.close()
        sel.close()


class _RacingConnectionMixin:
    def _new_conn(self) -> socket.socket:
        try:
            return race_connect((self._dns_host, self.port), self.timeout, source_address=self.source_address,
                                socket_options=self.socket_options)
        except socket.gaierror as e:
            raise NameResolutionError(self.host, self, e) from e
        except TimeoutError as e:
            raise ConnectTimeoutError(self, f"Connection to {self.host} timed out. (connect timeout={self.timeout})") from e
        except OSError as e:
            raise NewConnectionError(self, f"Failed to establish a new connection: {e}") from e


class RacingHTTPConnection(_RacingConnectionMixin, HTTPConnection):
    pass


class RacingHTTPSConnection(_RacingConnectionMixin, HTTPSConnection):
    pass


class RacingHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = RacingHTTPConnection


class RacingHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = RacingHTTPSConnection


class RacingAdapter(HTTPAdapter):
    """Gắn vào requests.Session: mọi kết nối mới của phiên đó dùng race_connect."""

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": RacingHTTPConnectionPool, "https": RacingHTTPSConnectionPool}
