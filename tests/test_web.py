"""Kiểm thử server web với vòng tay giả lập (không cần Bluetooth)."""

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from miband6 import protocol as P
from miband6.config import Store
from miband6.web.server import BandService, build_app

KEY = "8f2b1c0a77d94e3fa5c1b2e3d4f50617"
JSON = {"Content-Type": "application/json"}


@pytest.fixture
async def client(tmp_path):
    service = BandService(Store(tmp_path / "cfg.json"), demo=True)
    app = build_app(service)
    async with TestClient(TestServer(app, host="127.0.0.1")) as c:
        c.service = service
        yield c


async def post(c, path, data=None, **kw):
    return await c.post(path, data=json.dumps(data or {}), headers={**JSON, **kw.pop("headers", {})}, **kw)


async def connect(c):
    r = await post(c, "/api/scan", {"show_all": False})
    devices = (await r.json())["devices"]
    r = await post(c, "/api/connect", {"address": devices[0]["address"], "key": KEY, "protocol": "auto"})
    assert r.status == 200, await r.text()
    return await r.json()


async def test_index_and_meta(client):
    r = await client.get("/")
    html = await r.text()
    assert r.status == 200 and "Tổng quan" in html and "{{v}}" not in html
    r = await client.get("/static/app.js")
    assert r.status == 200
    meta = await (await client.get("/api/meta")).json()
    assert meta["max_alarms"] == 10 and "vi_VN" in meta["languages"]


async def test_connect_flow_and_settings(client):
    body = await connect(client)
    assert body["protocol"] == "classic" and body["state"]["connected"]
    band = client.service.band._client
    await asyncio.sleep(0.2)  # đọc dữ liệu chạy nền sau khi kết nối
    st = (await (await client.get("/api/state")).json())["state"]
    assert st["live"]["battery"]["level"] == 87
    assert st["live"]["activity"]["steps"] == 6543
    assert st["live"]["device_info"]["firmware"] == "1.0.6.16"
    assert st["saved_devices"][0]["auth_key"] == KEY

    r = await post(client, "/api/settings/formats",
                   {"language": "vi_VN", "time_24h": True, "date_format": "dd/MM/yyyy", "metric": True})
    assert (await r.json())["message"].startswith("Đã lưu")
    assert P.language("vi_VN") in band.config_commands
    r = await post(client, "/api/settings/dnd", {"mode": "scheduled", "from": "22:30", "to": "06:45", "lift": False})
    assert r.status == 200 and band.config_commands[-1] == P.do_not_disturb(P.DND_SCHEDULED, *map(
        lambda s: __import__("datetime").time(*map(int, s.split(":"))), ("22:30", "06:45")))
    r = await post(client, "/api/settings/menu", {"kind": "apps", "main": ["hr", "bogus", "weather"], "more": ["music"]})
    assert r.status == 200
    assert band.chunked_payloads[-1] == (2, P.menu_items(["hr", "weather", "more", "music", "settings"], False))
    saved = (await r.json())["state"]["settings"]
    assert saved["display_main"] == ["hr", "weather"] and saved["display_more"] == ["music", "settings"]
    r = await post(client, "/api/settings/goal", {"goal": 9000, "notify": True})
    assert (await r.json())["state"]["profile"]["goal"] == 9000

    alarms = (await (await client.get("/api/alarms")).json())["alarms"]
    assert [(a["slot"], a["hour"], a["minute"]) for a in alarms] == [(0, 6, 30), (2, 9, 0)]
    rows = [{"in_use": i == 1, "enabled": True, "hour": 5, "minute": 15, "days": 1} for i in range(10)]
    r = await post(client, "/api/alarms", {"alarms": rows})
    assert r.status == 200
    assert band.config_commands[-9] == P.alarm_command(P.Alarm(1, True, 5, 15, 1))

    r = await post(client, "/api/notify", {"title": "Chào", "body": "Thử", "app": "Mac", "icon": 13})
    assert r.status == 200 and band.chunked_payloads[-1] == (0, P.notification_payload("Chào", "Thử", "Mac", 13))
    r = await post(client, "/api/find", {"on": True})
    assert band.writes[-1] == (P.CHAR_NEW_ALERT, P.incoming_call("Tìm vòng tay"))
    r = await post(client, "/api/disconnect")
    assert not (await r.json())["state"]["connected"]


async def test_validation_errors(client):
    r = await post(client, "/api/settings/formats", {"language": "vi_VN"})
    assert r.status == 409  # chưa kết nối
    await connect(client)
    r = await post(client, "/api/settings/formats", {"language": "xx_YY", "time_24h": 1, "date_format": "x", "metric": 1})
    assert r.status == 400
    r = await post(client, "/api/settings/password", {"on": True, "pin": "12ab"})
    assert r.status == 400 and "6 chữ số" in (await r.json())["error"]
    r = await post(client, "/api/settings/nope", {})
    assert r.status == 404
    r = await post(client, "/api/connect", {"address": "x", "key": "short"})
    assert r.status == 400


async def test_wrong_key_is_401(client):
    r = await post(client, "/api/scan", {})
    addr = (await r.json())["devices"][0]["address"]
    client.service.demo = True
    # vòng tay giả lập chấp nhận mọi key nó được tạo cùng; ép sai bằng cách thay simulator
    from miband6 import simulator

    real = simulator.FakeBand

    class WrongKeyBand(real):
        def __init__(self, key, mode="both", with_2021_chars=True):
            super().__init__(bytes(16), mode, with_2021_chars)

    simulator.FakeBand = WrongKeyBand
    try:
        r = await post(client, "/api/connect", {"address": addr, "key": KEY, "protocol": "auto"})
    finally:
        simulator.FakeBand = real
    assert r.status == 401


async def test_websocket_pushes_events(client):
    ws = await client.ws_connect("/api/events")
    hello = json.loads((await ws.receive()).data)
    assert hello["type"] == "hello" and hello["state"]["connected"] is False
    await connect(client)
    kinds = set()
    for _ in range(40):
        try:
            msg = await asyncio.wait_for(ws.receive(), 2)
        except asyncio.TimeoutError:
            break
        kinds.add(json.loads(msg.data)["type"])
        if {"state", "battery", "activity", "log"} <= kinds:
            break
    assert {"state", "battery", "activity", "log"} <= kinds
    await ws.close()


async def test_security_guards(client):
    # POST không phải JSON (cách trang web lạ gửi ngầm) bị chặn
    r = await client.post("/api/find", data='{"on": true}', headers={"Content-Type": "text/plain"})
    assert r.status == 415
    # Origin khác bị chặn, kể cả WebSocket
    r = await post(client, "/api/scan", headers={"Origin": "https://evil.example"})
    assert r.status == 403
    r = await client.get("/api/events", headers={"Origin": "https://evil.example", "Connection": "Upgrade",
                                                 "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
                                                 "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
    assert r.status == 403
    # Host lạ (DNS rebinding) bị chặn
    r = await client.get("/api/state", headers={"Host": "attacker.example:8766"})
    assert r.status == 403


async def test_lan_mode_requires_token(tmp_path):
    service = BandService(Store(tmp_path / "cfg.json"), demo=True)
    app = build_app(service, lan_token="secret-token")
    async with TestClient(TestServer(app, host="127.0.0.1")) as c:
        r = await c.get("/api/state", headers={"Host": "192.168.1.20:8766"})
        assert r.status == 401
        r = await c.get("/?token=secret-token", headers={"Host": "192.168.1.20:8766"})
        assert r.status == 200 and "mb6_token" in r.cookies
        r = await c.get("/api/state", headers={"Host": "192.168.1.20:8766", "X-Token": "secret-token"})
        assert r.status == 200
