"""Dữ liệu sức khỏe (lấy từ vòng tay giả lập), mặt đồng hồ và ảnh nền tùy chỉnh."""

import asyncio
import base64
import datetime as dt
import json
import struct

import pytest
from aiohttp.test_utils import TestClient, TestServer

from miband6 import health as H
from miband6 import protocol as P
from miband6 import watchface as WF
from miband6.config import Store
from miband6.device import MiBand6, MiBandError
from miband6.healthdb import HealthDB
from miband6.simulator import FakeBand
from miband6.web.server import BandService, build_app

KEY_HEX = "8f2b1c0a77d94e3fa5c1b2e3d4f50617"
KEY = bytes.fromhex(KEY_HEX)
JSON = {"Content-Type": "application/json"}
TZ = dt.timezone(dt.timedelta(hours=7))


# ---------------------------------------------------------------- giao thức, giải mã


def test_fetch_commands():
    since = dt.datetime(2026, 11, 3, 10, 20, tzinfo=TZ)
    cmd = P.fetch_start(P.FETCH_ACTIVITY, since)
    local = since.astimezone()
    assert cmd[:2] == bytes([0x01, 0x01]) and cmd[2] | (cmd[3] << 8) == local.year
    assert list(cmd[4:8]) == [local.month, local.day, local.hour, local.minute]
    length, start = P.decode_fetch_start(bytes.fromhex("10 01 01 00 10 00 00 ea 07 0b 03 0a 14 00 1c"))
    assert length == 4096 and start == since
    with pytest.raises(ValueError):
        P.decode_fetch_start(bytes([0x10, 0x01, 0x04]))
    assert P.is_fetch_done(bytes([0x10, 0x02, 0x01])) is True
    assert P.is_fetch_done(bytes([0x10, 0x02, 0x04])) is False
    assert P.is_fetch_done(bytes([0x10, 0x01, 0x01])) is None


def test_decoders():
    start = dt.datetime(2026, 11, 3, 0, 0, tzinfo=TZ)
    rows = H.decode_activity(start, bytes([1, 50, 30, 80, 0, 0, 0, 0, 120, 10, 0, 55, 0, 40, 60, 10]))
    assert rows[1][0] - rows[0][0] == 60 and rows[0][3] == 30 and H.sleep_stage(rows[1]) == "deep"
    with pytest.raises(ValueError):
        H.decode_activity(start, bytes(7))
    assert H.decode_stress_auto(start, bytes([0xFF, 30, 0xFF, 70])) == [(int(start.timestamp()) + 60, 30),
                                                                        (int(start.timestamp()) + 180, 70)]
    assert H.decode_stress_manual((1234).to_bytes(4, "little") + bytes([45])) == [(1234, 45)]
    spo2 = bytes([2]) + (1000).to_bytes(4, "little") + bytes([97 + 128]) + bytes(60) \
        + (2000).to_bytes(4, "little") + bytes([95]) + bytes(60)
    assert H.decode_spo2(spo2) == [(1000, 97, True), (2000, 95, False)]
    pai = bytes([5]) + (5000).to_bytes(4, "little") + bytes([28]) + bytes(31) \
        + struct.pack("<fffhhhff", 1, 2, 3, 10, 20, 5, 12.5, 88.0) + bytes(39)
    old = bytes(102)   # bản ghi loại 0 (trước khi khôi phục gốc) bị bỏ qua
    (rec,) = H.decode_pai(old + pai)
    assert rec["ts"] == 5000 and rec["today"] == 12.5 and rec["total"] == 88.0 and rec["time_high"] == 5


def test_sport_summary_v2():
    from miband6.simulator import DemoHealth

    st = dt.datetime(2026, 11, 1, 18, 5, tzinfo=TZ)
    raw = DemoHealth._summary(1, st, 32, 5200, 330, 5600, 141, 170)
    w = H.decode_sport_summary(raw, st)
    assert (w["type"], w["end"] - w["start"], w["distance"], w["calories"], w["steps"]) == (1, 32 * 60, 5200, 330, 5600)
    assert (w["avg_hr"], w["max_hr"]) == (141, 170)


def test_sleep_sessions_merge_short_wakes():
    base = 1_800_000_000
    s = lambda m, deep=0, rem=0: (base + 60 * m, 120, 0, 0, 55, 40, deep, rem)  # noqa: E731
    awake = lambda m: (base + 60 * m, 1, 0, 10, 70, 0, 0, 0)  # noqa: E731
    samples = [s(m, deep=60) for m in range(30)] + [awake(m) for m in range(30, 40)] \
        + [s(m, rem=70) for m in range(40, 70)] + [awake(m) for m in range(70, 200)] + [s(m) for m in range(200, 210)]
    (sess,) = H.sleep_sessions(samples)   # giấc 10 phút ở cuối quá ngắn nên bị bỏ
    assert (sess["deep"], sess["rem"], sess["awake"], sess["minutes"]) == (30, 30, 10, 60)
    assert [st[2] for st in sess["stages"]] == ["deep", "awake", "rem"]


# ---------------------------------------------------------------- lấy dữ liệu từ vòng tay


@pytest.mark.parametrize("mode", ["classic", "2021"])
async def test_fetch_keeps_data_on_band(mode):
    fake = FakeBand(KEY, mode)
    band = MiBand6("x", KEY, mode, client=fake)
    await band.connect()
    since = dt.datetime.now().astimezone() - dt.timedelta(days=30)
    start, data = await band.fetch_data(P.FETCH_ACTIVITY, since)
    assert start == fake.health.start and len(data) == 1440 * 8   # một ngày mỗi lượt
    start, data = await band.fetch_data(P.FETCH_SPORTS_SUMMARY, since)
    assert H.decode_sport_summary(data, start)["type"] in (1, 3, 4)
    future = dt.datetime.now().astimezone() + dt.timedelta(days=1)
    assert await band.fetch_data(P.FETCH_SPO2, future) == (None, b"")
    assert fake.fetch_acks == 0   # không bao giờ xác nhận: Mi Fitness vẫn nhận được dữ liệu


@pytest.mark.parametrize("mode", ["classic", "2021"])
async def test_upload_watchface(mode):
    fake = FakeBand(KEY, mode)
    band = MiBand6("x", KEY, mode, client=fake)
    await band.connect()
    face = b"UIHH\x01" + bytes(13) + b"\x11\x22\x33\x44" + bytes(range(256)) * 50
    progress = []
    await band.upload_watchface(face, lambda sent, total: progress.append(sent))
    assert fake.installed_watchface == face and progress[-1] == len(face)
    assert P.watchface_prepare(face) in fake.config_commands
    with pytest.raises(ValueError):
        await band.upload_watchface(b"HMDIAL" + bytes(100))
    fake.fw_chunk = 0
    with pytest.raises(MiBandError):
        await band.upload_watchface(face)


# ---------------------------------------------------------------- ảnh nền thành mặt đồng hồ


def test_wallpaper_face_structure():
    bg = bytes([200, 100, 50, 255]) * (152 * 486)
    digits = [(40, 60, bytes([255, 255, 255, 128]) * (40 * 60))] * 10
    data = WF.wallpaper_face(bg, (76, 243, bytes(76 * 243 * 4)), digits, (36, 40), (36, 104))
    P.check_watchface(data)
    params, images = WF.parse(data)
    assert params[2][1] == {1: 0, 2: 0, 3: 0} and params[2][3][3] == 1
    assert params[3][1][2] == {1: 76, 2: 40, 3: 2, 4: 10} and params[3][2][1][2] == 104
    assert len(images) == 12 and images[0][:2] == b"BM"
    assert int.from_bytes(images[0][4:6], "little") == 152 and int.from_bytes(images[0][6:8], "little") == 486
    alpha, color = images[2][16], int.from_bytes(images[2][17:19], "big")
    assert alpha == 127 and color == 0xFFFF   # trắng, trong suốt một nửa (0 = đặc)
    bare = WF.wallpaper_face(bg, (10, 10, bytes(400)), [], None, None)
    assert 3 not in WF.parse(bare)[0]
    with pytest.raises(ValueError):
        WF.wallpaper_face(bytes(10), (10, 10, bytes(400)), [], None, None)


# ---------------------------------------------------------------- qua server web


@pytest.fixture
async def client(tmp_path):
    service = BandService(Store(tmp_path / "cfg.json"), demo=True)
    async with TestClient(TestServer(build_app(service), host="127.0.0.1")) as c:
        c.service = service
        yield c


async def post(c, path, data=None):
    return await c.post(path, data=json.dumps(data or {}), headers=JSON)


async def connected(c):
    r = await post(c, "/api/scan")
    addr = (await r.json())["devices"][0]["address"]
    r = await post(c, "/api/connect", {"address": addr, "key": KEY_HEX, "protocol": "auto"})
    assert r.status == 200
    return c.service.band._client


async def wait_sync(service, timeout=15.0):
    for _ in range(int(timeout / 0.05)):
        if service.health_status.get("state") in ("done", "error") and not (
                service._health_task and not service._health_task.done()):
            return service.health_status
        await asyncio.sleep(0.05)
    raise AssertionError(f"đồng bộ chưa xong: {service.health_status}")


async def test_health_sync_and_summary(client):
    fake = await connected(client)
    status = await wait_sync(client.service)   # tự đồng bộ sau khi kết nối
    assert status["state"] == "done" and not status["errors"] and status["last_sync"]
    today = dt.date.today().isoformat()
    body = await (await client.get(f"/api/health?date={today}")).json()
    h = body["health"]
    assert h["has_data"] and len(h["steps_days"]) >= 10
    assert len(h["workouts"]) == 3 and h["pai"]["latest"]["total"] > 0 and h["spo2_recent"]
    assert h["day"]["sleep"]["minutes"] > 300 and h["day"]["hr"]
    assert sum(h["day"]["steps_hourly"]) == h["day"]["steps"]
    assert any(d["minutes"] > 300 for d in h["sleep_days"])
    assert fake.fetch_acks == 0

    # lần sau chỉ hỏi phần mới
    requests_before = len(fake.fetch_requests)
    await post(client, "/api/health/sync")
    await asyncio.sleep(0.05)
    await wait_sync(client.service)
    newer = fake.fetch_requests[requests_before:]
    activity = [since for kind, since in newer if kind == P.FETCH_ACTIVITY]
    assert activity and activity[0] > dt.datetime.now().astimezone() - dt.timedelta(minutes=5)
    again = (await (await client.get(f"/api/health?date={today}")).json())["health"]
    assert again["steps_days"] == h["steps_days"] and len(again["workouts"]) == 3

    r = await client.get("/api/health?date=not-a-date")
    assert r.status == 400


async def test_health_db_survives_restart(tmp_path):
    db = HealthDB(tmp_path / "h.sqlite3")
    db.add_activity([(1_800_000_000, 1, 0, 12, 70, 0, 0, 0)])
    db.set_last("activity", 1_800_000_060)
    db.close()
    db = HealthDB(tmp_path / "h.sqlite3")
    assert db.last("activity") == 1_800_000_060 and db.daily_steps()[0]["steps"] == 12


async def test_install_watchface_and_preview(client):
    fake = await connected(client)
    face = b"UIHH\x01" + bytes(13) + b"\x01\x02\x03\x04" + bytes(range(256)) * 20
    png = b"\x89PNG\r\n\x1a\n" + bytes(32)
    r = await post(client, "/api/watchface", {"name": "cat.bin", "file": base64.b64encode(face).decode(),
                                              "preview": "data:image/png;base64," + base64.b64encode(png).decode()})
    assert r.status == 200, await r.text()
    assert fake.installed_watchface == face
    wf = (await r.json())["state"]["watchface"]
    assert wf["name"] == "cat.bin" and wf["preview"]
    r = await client.get("/api/watchface/preview")
    assert r.status == 200 and r.content_type == "image/png" and await r.read() == png

    r = await post(client, "/api/watchface", {"file": base64.b64encode(b"nope" * 20).decode()})
    assert r.status == 400 and "UIHH" in (await r.json())["error"]
    r = await post(client, "/api/watchface/preview", {"image": base64.b64encode(b"GIF89a" + bytes(10)).decode()})
    assert r.status == 200
    r = await post(client, "/api/watchface/preview", {"image": base64.b64encode(b"not an image").decode()})
    assert r.status == 400
    r = await post(client, "/api/watchface/preview", {"image": None})
    assert not (await r.json())["state"]["watchface"]["preview"]
    assert (await client.get("/api/watchface/preview")).status == 404


async def test_wallpaper_endpoint(client):
    fake = await connected(client)
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    img = lambda w, h: {"w": w, "h": h, "rgba": b64(bytes([30, 60, 90, 255]) * (w * h))}  # noqa: E731
    r = await post(client, "/api/wallpaper", {
        "background": img(152, 486), "preview": img(76, 243), "digits": [img(44, 64)] * 10,
        "hours": [32, 40], "minutes": [32, 108], "image": "data:image/png;base64," + b64(b"\x89PNG" + bytes(20)),
    })
    assert r.status == 200, await r.text()
    params, images = WF.parse(fake.installed_watchface)
    assert (params[3][2][1][1], params[3][2][1][2]) == (32, 108)   # hàng phút, chữ số hàng chục
    assert len(images) == 12
    r = await post(client, "/api/wallpaper", {"background": img(100, 100), "preview": img(10, 10)})
    assert r.status == 400


def test_preview_extracted_from_bin():
    bg = bytes([10, 120, 200, 255]) * (152 * 486)
    data = WF.wallpaper_face(bg, (76, 243, bytes([250, 20, 20, 255]) * (76 * 243)), [], None, None)
    shot = WF.preview_png(data)
    assert shot.startswith(b"\x89PNG")
    w, h, rgba = WF.decode_image(WF.parse(data)[1][1])
    assert (w, h) == (76, 243) and rgba[:4] == bytes([248, 20, 16, 255])
    # ảnh 8 bit có bảng màu, màu số 2 là màu trong suốt
    indexed = b"BM" + b"".join(v.to_bytes(2, "little") for v in (0x64, 2, 1, 2, 8, 2, 2)) \
        + bytes([255, 0, 0, 0, 0, 0, 255, 0]) + bytes([0, 1])
    assert WF.decode_image(indexed) == (2, 1, bytes([255, 0, 0, 255, 0, 0, 255, 0]))
    assert WF.preview_png(b"UIHH\x01" + bytes(100)) is None


async def test_inspect_and_auto_preview(client):
    fake = await connected(client)
    bg = bytes([10, 120, 200, 255]) * (152 * 486)
    face = WF.wallpaper_face(bg, (76, 243, bytes([250, 20, 20, 255]) * (76 * 243)), [], None, None)
    b64 = base64.b64encode(face).decode()
    body = await (await post(client, "/api/watchface/inspect", {"file": b64})).json()
    assert body["size"] == len(face) and body["preview"].startswith("data:image/png;base64,")
    r = await post(client, "/api/watchface/inspect", {"file": base64.b64encode(b"nope" * 10).decode()})
    assert r.status == 400
    # cài không kèm ảnh xem trước: dùng ảnh có sẵn trong tệp
    r = await post(client, "/api/watchface", {"name": "blue.bin", "file": b64})
    assert (await r.json())["state"]["watchface"]["preview"] and fake.installed_watchface == face
    shot = await (await client.get("/api/watchface/preview")).read()
    assert shot == WF.preview_png(face)
