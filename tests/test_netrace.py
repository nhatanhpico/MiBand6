"""Kết nối "đua" nhiều địa chỉ: một địa chỉ không trả lời không được làm chậm kết nối (máy chủ tệp của Xiaomi)."""

import socket
import threading
import time

import requests

from miband6 import netrace


def _server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok")
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return srv, port


def test_race_skips_dead_address(monkeypatch):
    srv, port = _server()
    dead = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", port))   # TEST-NET-1: không ai trả lời
    good = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [dead, dead, good])
    netrace._winners.clear()
    t = time.monotonic()
    sock = netrace.race_connect(("files.example", port), timeout=10)
    assert sock.getpeername() == ("127.0.0.1", port) and time.monotonic() - t < 2
    sock.close()
    assert netrace._winners[("files.example", port)][0] == ("127.0.0.1", port)
    # lần sau địa chỉ đã thắng được thử đầu tiên
    assert netrace._ordered("files.example", port, [dead, good])[0] == good
    # qua requests
    s = requests.Session()
    s.mount("http://", netrace.RacingAdapter())
    t = time.monotonic()
    r = s.get(f"http://files.example:{port}/x", timeout=(10, 5))
    assert r.text == "ok" and time.monotonic() - t < 2
    srv.close()


def test_race_timeout_and_failures(monkeypatch):
    dead = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 9))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [dead])
    netrace._winners.clear()
    t = time.monotonic()
    try:
        netrace.race_connect(("nowhere.example", 9), timeout=0.6)
    except OSError as e:   # hết giờ (TimeoutError) hoặc mạng báo không tới được ngay
        assert time.monotonic() - t < 2, e
    else:
        raise AssertionError("phải lỗi")


def test_nominatim_place_parsing():
    from miband6 import geo

    hcm = {"address": {"city": "Thành phố Hồ Chí Minh", "country": "Việt Nam", "country_code": "vn"}}
    assert geo.place_from_nominatim(hcm) == {"city": "Thành phố Hồ Chí Minh", "country": "Việt Nam", "cc": "VN"}
    town = {"address": {"county": "Hsinchu County", "state": "Taiwan", "country": "Taiwan", "country_code": "tw"}}
    assert geo.place_from_nominatim(town)["city"] == "Hsinchu County"
    assert geo.place_from_nominatim({"error": "Unable to geocode"}) is None   # giữa biển
    key = geo.area_key(10.776543, 106.695512, "vi")
    assert key == "vi:10.78,106.70" and geo.parse_key(key) == (10.78, 106.7, "vi")
