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
    rows = H.decode_activity(start, bytes([1, 50, 30, 80, 0, 0, 0, 0, 0xFB, 10, 0, 55, 0, 40, 60, 10]))
    assert rows[1][0] - rows[0][0] == 60 and rows[0][3] == 30 and rows[0][4] == 80
    assert H.effective_kinds(rows) == [H.KIND_ACTIVITY, H.KIND_DEEP_SLEEP]
    assert H.sleep_stage(rows[1], H.KIND_DEEP_SLEEP) == "deep" and H.sleep_stage(rows[0], H.KIND_ACTIVITY) is None
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


BASE = 1_800_000_000


def minute(m, kind, level=0, deep=0x80, rem=0, hr=60):
    """Một phút dữ liệu kiểu Mi Band 6: (ts, loại, cường độ, bước, nhịp tim, byte "ngủ", ngủ sâu, REM)."""
    return (BASE + 60 * m, kind, 0, 0, hr, level, deep, rem)


def test_sleep_uses_state_markers_like_gadgetbridge():
    # mốc chỉ ở phút đổi trạng thái; 0xF0 / 0x50 (4 bit thấp = 0) là "không đổi", 0xFA là "bỏ qua"
    samples = [minute(0, 0x11)] + [minute(m, 0x50) for m in range(1, 10)] \
        + [minute(10, 0xFB)] + [minute(m, 0xF0) for m in range(11, 40)] \
        + [minute(40, 0x11)] + [minute(m, 0x50) for m in range(41, 50)] \
        + [minute(50, 0xF9)] + [minute(m, 0xFA if m % 7 == 0 else 0xF0) for m in range(51, 80)] \
        + [minute(80, 0x6C)] + [minute(m, 0x50) for m in range(81, 200)] + [minute(m, 0xF9) for m in range(200, 210)]
    (sess,) = H.sleep_sessions(samples)   # giấc 10 phút ở cuối quá ngắn nên bị bỏ
    assert (sess["deep"], sess["light"], sess["awake"], sess["minutes"]) == (30, 30, 10, 60)
    assert [st[2] for st in sess["stages"]] == ["deep", "awake", "light"]
    # phút "không đổi" ở đầu khoảng: dùng trạng thái trước khoảng đó
    assert H.sleep_sessions([minute(m, 0xF0) for m in range(40)], previous=H.KIND_LIGHT_SLEEP)[0]["light"] == 40


def test_sleep_edges_follow_sleep_level_not_late_markers():
    """Mẫu giống một đêm thật: vòng tay ghi mốc ngủ / thức trễ ~11 phút; byte "ngủ" cho thấy giờ thật
    (vòng tay hiện "ngủ lúc 1:34, dậy 7:42, 6 giờ 8 phút")."""
    fall, wake = 94, 462   # phút kể từ 00:00: 01:34 và 07:42
    rows = []
    for m in range(60, 500):
        if m < fall:
            rows.append(minute(m, 0x50, level=max(0, 9 - (fall - m))))
        elif m < fall + 11:
            rows.append(minute(m, 0x50 if m < fall + 9 else 0xD0, level=10 + 4 * (m - fall)))
        elif m == fall + 11:
            rows.append(minute(m, 0xDB, level=56))              # mốc ngủ sâu trễ 11 phút
        elif m < wake:
            marker = m == fall + 63
            rows.append(minute(m, 0xF9 if marker else 0xF0, level=55, deep=0x80 | 40))
        elif m == wake:
            rows.append(minute(m, 0xF0, level=38))              # phút chuyển tiếp: đang tỉnh
        elif m < wake + 12:
            rows.append(minute(m, 0xF0 if m < wake + 3 else 0x70, level=max(0, 24 - 3 * (m - wake))))
        elif m == wake + 12:
            rows.append(minute(m, 0x6C))                        # mốc thức dậy trễ 12 phút
        else:
            rows.append(minute(m, 0x11 if m == wake + 13 else 0x50))
    (sess,) = H.sleep_sessions(rows, previous=H.KIND_ACTIVITY)
    assert sess["start"] == BASE + 60 * fall and sess["end"] == BASE + 60 * wake
    assert sess["minutes"] == wake - fall == 368 and sess["deep"] + sess["light"] == 368
    assert sess["deep"] == 52 and sess["stages"][0][2] == "light"   # 11 phút đầu (trước mốc trễ) là ngủ nông
    # vòng tay không có byte "ngủ" (toàn 0): giữ nguyên mốc
    plain = [(t, k, i, s, hr, 0, d, r) for (t, k, i, s, hr, _l, d, r) in rows]
    (sess,) = H.sleep_sessions(plain, previous=H.KIND_ACTIVITY)
    assert sess["start"] == BASE + 60 * (fall + 11) and sess["end"] == BASE + 60 * (wake + 12)


def row(m, kind, level=0, hr=60, intensity=0, steps=0, deep=0x80, rem=0):
    return (BASE + 60 * m, kind, intensity, steps, hr, level, deep, rem)


def test_off_wrist_band_on_table_is_not_sleep():
    """Đêm 4/11/2026 thật: trước khi ngủ và sau khi dậy vòng tay nằm trên bàn (vòng ghi "không đeo" từng phút, không
    có nhịp tim) nên byte "ngủ" vẫn tăng như đang ngủ; lúc đeo vào vòng ghi một mốc ngủ sâu dù đang đi lại.
    Trước đây giấc ngủ bị kéo sớm 27 phút và thêm 11 phút "ngủ" lúc 9:57-10:08."""
    fall, wake = 100, 400
    rows = [row(m, 0x50, hr=70) for m in range(60)]
    rows += [row(m, 0x73, level=min(60, 3 * (m - 60)), hr=255) for m in range(60, 80)]          # trên bàn
    rows += [row(80, 0xFB, level=58, hr=75, intensity=40)]                                      # đeo vào: mốc ngủ sâu
    rows += [row(m, 0x50, level=60 - 6 * (m - 80), hr=80, intensity=40) for m in range(81, 90)]  # mức cũ đang giảm
    rows += [row(m, 0x50, level=m - 91, hr=72) for m in range(90, fall)]                         # nằm, chưa ngủ (< 9)
    rows += [row(m, 0x50, level=9 + 5 * (m - fall), hr=66) for m in range(fall, fall + 11)]
    rows += [row(fall + 11, 0xF9, level=58)]                                                    # mốc ngủ nông trễ
    rows += [row(m, 0xF0, level=58, deep=0x80 | (30 + 2 * (m % 30))) for m in range(fall + 12, wake)]
    rows += [row(wake, 0xF0, level=38)] + [row(m, 0xF0, level=max(0, 24 - 3 * (m - wake))) for m in range(wake + 1, wake + 12)]
    rows += [row(wake + 12, 0x6C, hr=75)] + [row(m, 0x50, hr=75) for m in range(wake + 13, 430)]
    rows += [row(m, 0x73, level=min(57, 3 * (m - 430)), hr=255) for m in range(430, 451)]       # lại trên bàn
    rows += [row(451, 0x8B, level=42, hr=86, intensity=96, steps=78)]                          # đeo vào rồi đi luôn
    rows += [row(m, 0x11, hr=95, intensity=120, steps=100) for m in range(452, 470)]
    (sess,) = H.sleep_sessions(rows, previous=H.KIND_ACTIVITY)
    assert sess["start"] == BASE + 60 * fall and sess["end"] == BASE + 60 * wake
    assert sess["awake"] == 0 and sess["minutes"] == wake - fall
    assert 0.10 * 300 <= sess["deep"] <= 0.20 * 300 and sess["stage_source"] == "default"   # theo tỉ lệ mặc định


def test_off_wrist_state_ends_with_a_heart_rate():
    rows = [row(0, 0x73, hr=255), row(1, 0x50, hr=255), row(2, 0x50, hr=72), row(3, 0x50, hr=255), row(4, 0xF3, hr=255)]
    assert H.off_wrist(rows) == [True, True, False, False, True]
    assert H.off_wrist([row(0, 0x50, hr=255)], previous=H.KIND_NOT_WORN) == [True]


def rem_night(bouts=((200, 12), (300, 6))):
    """Đêm kiểu firmware mới (byte REM có bit 7): ngủ phút 30-400, các đợt thức (phút đầu, độ dài) nhịp tim tăng 20,
    cử động, byte REM ở mức sàn 17; một đoạn REM (byte REM 70) ở phút 250-269; điểm ngủ sâu tăng dần khi nằm yên."""
    awake = {m for a, n in bouts for m in range(a, a + n)}
    rows = [row(m, 0x50, hr=72) for m in range(20)]
    rows += [row(m, 0x50, level=9 + 4 * (m - 20), hr=66) for m in range(20, 30)]
    for m in range(30, 400):
        kind = 0xF9 if m == 30 else 0xF0
        if m in awake:
            rows.append(row(m, kind, level=40, hr=80, intensity=30 if m % 3 == 0 else 0, deep=0x80 | 30, rem=0x80 | 17))
        else:
            rem_block = 250 <= m < 270   # REM: nhịp tim cao hơn nền một chút, nên không thể là ngủ sâu
            rows.append(row(m, kind, level=58, hr=66 if rem_block else 60, deep=0x80 | (33 + (m % 45) * 3 // 2),
                            rem=0x80 | (70 if rem_block else 35 + (m * 3) % 15)))
    rows += [row(400, 0xF0, level=38, hr=70)]   # phút chuyển tiếp: byte "ngủ" đang tụt, tính là đã dậy
    rows += [row(m, 0xF0, level=20, hr=75) for m in range(401, 405)]
    rows += [row(m, 0x6C if m == 410 else 0x50, hr=78) for m in range(405, 420)]
    return rows


def test_wake_bout_inside_sleep():
    """Thức 12 phút (như 8:29-8:41 đêm 4/11) là "thức"; đợt 6 phút (thường không nhớ) vẫn tính là ngủ nông."""
    (sess,) = H.sleep_sessions(rem_night(), previous=H.KIND_ACTIVITY)
    # thiếp đi lúc byte "ngủ" bắt đầu đợt tăng cuối (từ 9, phút 20), không phải mốc trễ của vòng tay (phút 30)
    assert sess["start"] == BASE + 60 * 20 and sess["end"] == BASE + 60 * 400
    assert sess["awake"] == 12 and [BASE + 200 * 60, BASE + 212 * 60, "awake"] in sess["stages"]
    assert sess["rem"] == 20 and [BASE + 250 * 60, BASE + 270 * 60, "rem"] in sess["stages"]   # byte REM > 55
    assert sess["minutes"] == 380 - 12


def test_stages_follow_mi_fitness_report_or_learned_shares():
    ref = [{"start": BASE + 21 * 60, "end": BASE + 402 * 60, "minutes": 378, "deep": 40, "light": 320, "rem": 18,
            "awake": 0, "score": 71}]
    (sess,) = H.sleep_sessions(rem_night(), previous=H.KIND_ACTIVITY, reference=ref)
    assert sess["stage_source"] == "mifitness" and sess["reference"]["score"] == 71
    assert abs(sess["deep"] - 40) <= 5 and abs(sess["rem"] - 18) <= 3 and sess["awake"] == 12
    (sess,) = H.sleep_sessions(rem_night(), previous=H.KIND_ACTIVITY, calib={"deep_share": 0.2, "rem_share": 0.05})
    assert sess["stage_source"] == "calibrated" and "reference" not in sess
    assert abs(sess["deep"] - 0.2 * 368) <= 5 and abs(sess["rem"] - 0.05 * 368) <= 4
    # giấc ngắn (ngủ trưa) không chia giai đoạn, như Mi Fitness
    nap = [row(m, 0x50, level=9 + 4 * m, hr=66) for m in range(10)] \
        + [row(m, 0xF9 if m == 10 else 0xF0, level=58, deep=0x80 | (20 + m % 30)) for m in range(10, 50)] \
        + [row(m, 0x6C if m == 50 else 0x50, hr=75) for m in range(50, 70)]
    (sess,) = H.sleep_sessions(nap, previous=H.KIND_ACTIVITY)
    assert sess["minutes"] >= 40 and sess["deep"] == 0 and sess["rem"] == 0


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
    # tiêu đề của Mi Band 6 (tiêu đề Mi Band 5 làm Mi Band 6 thật bị treo): dấu 3E 00 3E 00, 1F 22 11 00, mã 148
    assert len(data) > 87 and data[:6] == b"UIHH\x01\x00" and data[11] == 1
    assert data[14:18] == bytes.fromhex("3e003e00") and data[20:26] == bytes.fromhex("00001f221100")
    assert data[32] == 0 and set(data[26:32]) == {0xFF} and set(data[33:79]) == {0xFF}
    assert int.from_bytes(data[79:83], "little") == 148
    params, images = WF.parse(data)
    assert params[2] == {1: {1: 0, 2: 0, 3: 0}}   # chỉ ảnh nền, không có ảnh xem trước
    assert params[3][1][2] == {1: 76, 2: 40, 3: 1, 4: 10} and params[3][2][1][2] == 104 and params[3][11] == 0
    assert len(images) == 11 and images[0][:2] == b"BM"
    assert [int.from_bytes(images[0][i:i + 2], "little") for i in range(2, 16, 2)] == [100, 152, 486, 456, 24, 0, 0]
    alpha, color = images[1][16], int.from_bytes(images[1][17:19], "big")
    assert alpha == 127 and color == 0xFFFF   # trắng, trong suốt một nửa (0 = đặc)
    bare = WF.wallpaper_face(bg, (10, 10, bytes(400)), [], None, None)
    assert 3 not in WF.parse(bare)[0]
    assert bare[12:14] + bare[18:20] != data[12:14] + data[18:20]   # mỗi mặt đồng hồ một mã riêng
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
    # 3 buổi trong 30 ngày + 1 buổi cũ hơn, lấy ở lượt "dữ liệu cũ" chạy một lần
    assert len(h["workouts"]) == 4 and h["pai"]["latest"]["total"] > 0 and h["spo2_recent"]
    assert all(w["source"] == "band" for w in h["workouts"])
    db = client.service.health_db()
    assert db.last("workouts_backfill") and db.last("activity_backfill")
    # giả lập ngủ 23:20–06:50: trước lúc dậy, giấc của hôm nay còn đang ngủ nên chưa tính; xem đêm của hôm qua
    woke = dt.datetime.now().time() >= dt.time(7, 30)
    night_day = today if woke else (dt.date.today() - dt.timedelta(days=1)).isoformat()
    night = (await (await client.get(f"/api/health?date={night_day}")).json())["health"]["day"]
    assert night["sleep"]["minutes"] > 300 and not night["sleep"]["ongoing"] and night["hr"]
    if not woke:
        assert h["day"]["sleep"] is None   # giấc đang ngủ dở không thành "đêm qua" chỉ vài phút
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
    assert again["steps_days"] == h["steps_days"] and len(again["workouts"]) == 4

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
    assert len(images) == 11
    r = await post(client, "/api/wallpaper", {"background": img(100, 100), "preview": img(10, 10)})
    assert r.status == 400


def test_preview_extracted_from_bin():
    bg = bytes([10, 120, 200, 255]) * (152 * 486)
    data = WF.wallpaper_face(bg, (76, 243, bytes([250, 20, 20, 255]) * (76 * 243)), [], None, None)
    shot = WF.preview_png(data)
    assert shot.startswith(b"\x89PNG")
    w, h, rgba = WF.decode_image(WF.parse(data)[1][0])   # không có ảnh xem trước riêng: dùng ảnh nền
    assert (w, h) == (152, 486) and rgba[:4] == bytes([8, 120, 200, 255])
    # ảnh 8 bit có bảng màu, màu số 2 là màu trong suốt
    indexed = b"BM" + b"".join(v.to_bytes(2, "little") for v in (0x64, 2, 1, 2, 8, 2, 2)) \
        + bytes([255, 0, 0, 0, 0, 0, 255, 0]) + bytes([0, 1])
    assert WF.decode_image(indexed) == (2, 1, bytes([255, 0, 0, 255, 0, 0, 255, 0]))
    assert WF.preview_png(b"UIHH\x01" + bytes(100)) is None


def _solid(w, h, rgb):
    return WF.image_24bit(w, h, bytes([*rgb, 255]) * (w * h))


def _pixel(shot, x, y):
    w, _h, rgba = shot
    return tuple(rgba[(y * w + x) * 4:(y * w + x) * 4 + 4])


DIGIT = [(8 * (d + 1), 248, 0) for d in range(10)]   # màu riêng mỗi chữ số, giữ nguyên qua RGB565


def _layered_face(hands=None):
    """Mặt đồng hồ kiểu tệp tải về: nền, chữ số giờ, số pin canh phải, ảnh động 3 khung, ảnh xem trước có hình mờ."""
    images = [_solid(152, 486, (0, 0, 0))] + [_solid(10, 20, c) for c in DIGIT]
    first = len(images)
    images += [_solid(152, 40, (0, 0, 8 * (k + 1))) for k in range(3)]
    images.append(_solid(76, 243, (248, 0, 248)))
    params = {
        WF.BACKGROUND: {WF.BG_IMAGE: {1: 0, 2: 0, 3: 0}, WF.BG_PREVIEW_EN: {1: 0, 2: 0, 3: first + 3}},
        WF.TIME: {WF.TIME_HOURS: {1: {1: 10, 2: 50, 3: 1, 4: 10}, 2: {1: 20, 2: 50, 3: 1, 4: 10}}},
        9: {1: {1: {1: 40, 2: 100, 3: 100, 4: 120, 5: 4, 6: 2, 7: 0, 8: 1, 9: 10}}},
        11: {1: {1: {1: 0, 2: 200, 3: first, 4: 3}, 2: 4, 3: 99, 4: 0}},
    }
    if hands:
        params[10] = hands
    return WF.build(params, images)


def test_render_face_from_layers():
    face = _layered_face()
    st = WF.face_status(dt.datetime(2025, 2, 15, 21, 41), battery=60)
    layers = WF.scene(face, st)
    [anim] = layers["animations"]
    assert (anim["x"], anim["y"], anim["interval"], len(anim["frames"])) == (0, 200, 80, 3)   # tốc độ 4 → tối thiểu 80 ms
    assert layers["above"] is None
    shot = WF.render(face, st)
    assert _pixel(shot, 12, 52) == (*DIGIT[2], 255) and _pixel(shot, 22, 52) == (*DIGIT[1], 255)   # "21"
    # "60" canh phải trong khung x 40-100: rộng 10 + 2 + 10, bắt đầu ở x = 78; giữa theo chiều dọc: y = 100
    assert _pixel(shot, 79, 101) == (*DIGIT[6], 255) and _pixel(shot, 91, 101) == (*DIGIT[0], 255)
    assert _pixel(shot, 77, 101) == (0, 0, 0, 255)
    assert _pixel(shot, 5, 205) == (0, 0, 8, 255)   # khung đầu của ảnh động
    # kiểu 12 giờ: 21 giờ hiện "09"
    shot12 = WF.render(face, WF.face_status(dt.datetime(2025, 2, 15, 21, 41), time_24h=False))
    assert _pixel(shot12, 12, 52) == (*DIGIT[0], 255) and _pixel(shot12, 22, 52) == (*DIGIT[9], 255)
    # vẽ được thì không dùng ảnh xem trước nhúng (thường là ảnh nhỏ có hình mờ)
    assert WF.preview_png(face, st) == WF.png(*shot)
    assert WF.embedded_preview(face)[:2] == (76, 243)


def test_render_analog_hand():
    hand = {2: {2: 0xFF0000, 3: {1: 76, 2: 243}, 4: [{1: 0, 2: -2}, {1: 40, 2: -2}, {1: 40, 2: 2}, {1: 0, 2: 2}]}}
    face = _layered_face(hand)
    at = lambda minute: WF.render(face, WF.face_status(dt.datetime(2025, 2, 15, 10, minute)))  # noqa: E731
    assert _pixel(at(15), 100, 243) == (255, 0, 0, 255) and _pixel(at(15), 76, 220) != (255, 0, 0, 255)
    assert _pixel(at(0), 76, 220) == (255, 0, 0, 255)   # phút 0: kim chỉ lên


def test_decode_compressed_image_and_signed_params():
    img = b"BM" + struct.pack("<5HI", 0x65, 3, 2, 6, 16, 10) + struct.pack("<3H2H", 1, 1, 2, 0xF800, 0x001F)
    w, h, rgba = WF.decode_image(img)
    assert (w, h) == (3, 2) and rgba[16:24] == bytes([248, 0, 0, 255, 0, 0, 248, 255]) and rgba[:16] == bytes(16)
    assert WF.decode_image(b"BM" + struct.pack("<5HI", 0x65, 60000, 60000, 2, 16, 0)) is None   # cỡ vô lý
    assert WF.decode_params(WF.encode_params({1: -5, 2: {1: 3}})) == {1: -5, 2: {1: 3}}
    assert WF.scene(b"UIHH\x01" + bytes(100)) is None


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


async def test_inspect_returns_animation_layers(client):
    body = await (await post(client, "/api/watchface/inspect",
                             {"file": base64.b64encode(_layered_face()).decode()})).json()
    assert body["rendered"] and body["preview"].startswith("data:image/png;base64,")
    anim = body["animation"]
    assert anim["below"].startswith("data:image/png") and anim["above"] is None
    assert [(i["x"], i["y"], i["interval"], len(i["frames"])) for i in anim["items"]] == [(0, 200, 80, 3)]


def test_analysis_rules():
    now = BASE + 20 * 86400
    nights = [{"date": f"d{i}", "minutes": 300, "deep": 30, "awake": 0, "start": BASE + i * 86400 - 3600,
               "hr": 60 if i < 7 else 68} for i in range(14)]
    a = H.analyze(nights, [{"date": f"d{i}", "steps": 3000} for i in range(7)], 8000, {"total": 120},
                  [(1, 88), (2, 97)], [70] * 10, 40, 1, last_data=now - 3600, now=now)
    status = {i["key"]: i["status"] for i in a["items"]}
    assert status == {"sleep": "alert", "deep": "ok", "bedtime": "good", "rhr": "watch", "steps": "watch",
                      "active": "watch", "pai": "good", "spo2": "alert", "stress": "watch"}
    assert sum(a["counts"].values()) == len(a["items"])
    good = H.analyze([{"date": "d", "minutes": 480, "deep": 90, "awake": 5, "start": BASE, "hr": 55}],
                     [{"date": "d", "steps": 9000}], 8000, None, [], [], 200, 3, last_data=now - 10 * 86400, now=now)
    status = {i["key"]: i["status"] for i in good["items"]}
    assert status["sleep"] == status["steps"] == status["active"] == status["rhr"] == "good"
    assert status["fresh"] == "watch" and "pai" not in status   # dữ liệu cũ; chưa có PAI thì không nhận xét


async def test_health_api_includes_analysis(client):
    await connected(client)
    await wait_sync(client.service)
    h = (await (await client.get(f"/api/health?date={dt.date.today().isoformat()}")).json())["health"]
    keys = {i["key"] for i in h["analysis"]["items"]}
    assert {"sleep", "deep", "rhr", "steps", "active", "pai", "spo2", "stress"} <= keys
    sleep = next(i for i in h["analysis"]["items"] if i["key"] == "sleep")
    assert sleep["status"] == "good"   # giả lập ngủ 23:20–06:50 mỗi đêm


def test_cloud_workouts_merge_with_band(tmp_path):
    db = HealthDB(tmp_path / "h.sqlite3")
    db.add_workout({"type": 5, "start": 1_800_000_000, "end": 1_800_003_600, "calories": 300})
    rows = [H.workout_from_cloud(v) for v in (
        {"start_time": 1_800_000_090, "end_time": 1_800_003_600, "sport_type": 308, "duration": 3500},   # cùng buổi
        {"start_time": 1_799_000_000, "end_time": 1_799_001_800, "sport_type": 308, "duration": 1800, "calories": 150},
        {"start_time": 1_798_000_000, "sport_type": 1, "duration": 1200, "distance": 3000, "avg_hrm": 0},
        {"sport_type": 1},   # không có giờ bắt đầu: bỏ
    )]
    assert rows[3] is None and rows[2]["end"] == 1_798_001_200 and rows[2]["avg_hr"] is None
    assert db.add_cloud_workouts([r for r in rows if r]) == 2
    assert db.add_cloud_workouts([r for r in rows if r]) == 0   # lấy lại không nhân đôi
    w = db.summary("2027-01-15")["workouts"]
    assert [x["source"] for x in w] == ["band", "mifitness", "mifitness"]
    assert w[0]["mf_type"] == 308 and w[1]["type"] == 5   # mã 308 của Mi Fitness học được là "tập tự do"
    # buổi vòng tay tới sau buổi Mi Fitness cùng giờ: thay bằng bản của vòng tay, giữ mã Mi Fitness
    db.add_workout({"type": 1, "start": 1_798_000_030, "end": 1_798_001_230, "distance": 3100})
    w = db.summary("2027-01-15")["workouts"]
    assert len(w) == 3 and w[-1]["source"] == "band" and w[-1]["mf_type"] == 1 and w[-1]["distance"] == 3100


def test_fetch_sport_records_pages():
    from miband6 import xiaomi_cloud as X

    pages = {None: {"code": 0, "result": {"sport_records": [{"time": 2, "value": '{"start_time": 2}'},
                                                            {"time": 3, "value": "{}", "deleted": True}],
                                           "has_more": True, "next_key": "k2"}},
             "k2": {"code": 0, "result": {"sport_records": [{"time": 1, "value": {"start_time": 1}}], "has_more": False}}}
    calls = []

    class Login:
        class requests:  # noqa: N801
            class exceptions:  # noqa: N801
                RequestException = OSError

        def request(self, host, path, plain, method="POST", region="sg", **_):
            req = json.loads(plain["data"])
            calls.append((host, path, method, req))
            return 200, pages[req.get("next_key")]

    records, trail = X.fetch_sport_records(Login(), 100, 200)
    assert [r["start_time"] for r in records] == [2, 1] and records[0]["_region"] == "sg" and records[0]["_sid"] is None
    assert calls[0][:3] == ("sg.hlth.io.mi.com", "/app/v1/data/get_sport_records_by_time", "GET")
    assert calls[0][3]["start_time"] == 99 and calls[1][3]["next_key"] == "k2"

    class Expired(Login):
        def request(self, *a, **kw):
            return 401, None

    with pytest.raises(X.SessionExpired):
        X.fetch_sport_records(Expired(), 100, 200)


def test_sleep_reports_from_mi_fitness(tmp_path):
    from miband6 import xiaomi_cloud as X

    report = {"sleep_score": 74, "segment_details": [
        {"bedtime": 1_800_000_000, "wake_up_time": 1_800_028_380, "duration": 473, "sleep_deep_duration": 53,
         "sleep_light_duration": 371, "sleep_rem_duration": 49, "sleep_awake_duration": 1},
        {"bedtime": 1_800_050_000, "wake_up_time": 1_800_052_220, "duration": 37}]}   # ngủ trưa: không chia giai đoạn
    night, nap = X.sleep_segments(report)
    assert (night["minutes"], night["deep"], night["rem"], night["score"]) == (473, 53, 49, 74)
    assert nap["deep"] is None and nap["score"] is None
    pages = {None: {"code": 0, "result": {"data_list": [{"time": 1_800_057_600, "value": json.dumps(report)},
                                                        {"time": 1, "value": "{}", "deleted": True}],
                                          "has_more": True, "next_key": "k2"}},
             "k2": {"code": 0, "result": {"data_list": [], "has_more": False}}}
    calls = []

    class Login:
        class requests:  # noqa: N801
            class exceptions:  # noqa: N801
                RequestException = OSError

        def request(self, host, path, plain, method="POST", region="sg", **_):
            req = json.loads(plain["data"])
            calls.append((path, method, req))
            return 200, pages[req.get("next_key")]

    rows, _trail = X.fetch_sleep_reports(Login(), 1_799_900_000, 1_800_060_000)
    assert len(rows) == 2 and rows[0]["date"] == "2027-01-16"
    assert calls[0][:2] == ("/app/v1/data/get_aggregated_fitness_data_by_time", "GET")
    assert calls[0][2]["tag"] == "daily_report" and calls[0][2]["key"] == "sleep" and calls[1][2]["next_key"] == "k2"

    db = HealthDB(tmp_path / "h.sqlite3")
    assert db.add_cloud_sleep(rows) == 2 and db.add_cloud_sleep(rows) == 0   # lấy lại không nhân đôi
    assert [r["minutes"] for r in db.sleep_reference(1_800_000_000, 1_800_000_060)] == [473]
    assert db.sleep_calibration() is None   # cần ít nhất 5 đêm
    for i in range(1, 6):
        db.add_cloud_sleep([{**night, "start": night["start"] - i * 86400, "end": night["end"] - i * 86400,
                             "deep": 60 + i, "rem": 0}])
    cal = db.sleep_calibration()
    assert cal["nights"] == 6 and abs(cal["deep_share"] - 63 / 473) < 0.002 and cal["rem_share"] == round(49 / 473, 4)


async def test_cloud_workouts_job_demo(client):
    await connected(client)
    await wait_sync(client.service)
    r = await post(client, "/api/cloud/sync", {"job": "workouts"})
    assert r.status == 200 and (await r.json())["cloud"]["job"] == "workouts"
    for _ in range(100):
        st = client.service.cloud.status
        if st["state"] == "done":
            break
        await asyncio.sleep(0.05)
    assert st["state"] == "done" and st["job"] == "workouts" and "4" in st["message"]
    h = (await (await client.get(f"/api/health?date={dt.date.today().isoformat()}")).json())["health"]
    assert sum(1 for w in h["workouts"] if w["source"] == "mifitness") == 4
    # cùng lượt: báo cáo giấc ngủ của Mi Fitness, để so và hiệu chỉnh thuật toán giấc ngủ
    assert client.service.health_db().last("mf_sleep")
    check = h["sleep_check"]
    assert check["validation"]["nights"] >= 5 and check["validation"]["start"] <= 3
    assert check["calibration"]["nights"] >= 5
    assert h["day"]["sleep"]["stage_source"] == "mifitness" and h["day"]["sleep"]["reference"]["score"] == 70
    assert {"changes", "counts", "highlights", "today"} <= set(h["trends"])



def gps_file(points, version=2):
    """Tệp lộ trình kiểu Mi Fitness: tiêu đề 8 byte, 1 byte cờ hợp lệ, rồi các điểm."""
    head = struct.pack("<IbBBB", 1_800_000_000, 28, version, 22, 0)
    if version == 1:
        body = b"".join(struct.pack("<Iff", t, lon, lat) for t, lat, lon in points)
        return head + bytes([0b11100000]) + body
    body = b"".join(struct.pack("<IfffH", t, lon, lat, 5.0, 0x51) for t, lat, lon in points)
    return head + bytes([0b11111100]) + body


def test_decode_gps_file():
    pts = [(100, 10.7765, 106.6955), (101, 10.7766, 106.6957), (102, 0.0, 0.0), (103, 95.0, 1.0)]
    for version in (1, 2):
        track = H.decode_gps_file(gps_file(pts, version))
        assert [p[0] for p in track] == [100, 101] and abs(track[0][1] - 10.7765) < 1e-5   # bỏ điểm (0,0) và sai
    with pytest.raises(ValueError):
        H.decode_gps_file(struct.pack("<IbBBB", 1, 0, 9, 22, 0) + bytes(20))   # phiên bản chưa biết, không dò được điểm
    # phiên bản 3 (như tệp thật: 26 byte, thêm độ cao và một float32); phiên bản 4 chưa biết: cỡ điểm dò từ dữ liệu
    run = [(1_800_000_000 + i, 10.7765 + i * 1e-5, 106.6955 + i * 2e-5) for i in range(200)]
    for version, extra in ((3, struct.pack("<ff", 107.5, 0.0)), (4, struct.pack("<fff", 107.5, 0.0, 1.0))):
        head = struct.pack("<IbBBB", 1_800_000_000, 28, version, 22, 0) + bytes([0xFE])
        body = b"".join(struct.pack("<IfffH", t_, lon, lat, 5.0, 113) + extra for t_, lat, lon in run)
        track = H.decode_gps_file(head + body)
        assert len(track) == 200 and track[0][0] == 1_800_000_000 and abs(track[-1][1] - (10.7765 + 199e-5)) < 1e-5
    with pytest.raises(ValueError):
        H.decode_gps_file(b"abc")


def test_gps_file_name_and_decrypt():
    import base64 as b64
    import hashlib

    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    from miband6 import xiaomi_cloud as X

    name = X.gps_file_suffix("abc", 1_800_000_000, 28, 22)
    key_part, sid_part = name.split("_", 1) if name.count("_") == 1 else (name[:8], name[9:])
    assert b64.urlsafe_b64decode(key_part + "==") == struct.pack("<Ib", 1_800_000_000, 28) + bytes([0x80 | 22 << 2 | 2])
    assert sid_part == b64.urlsafe_b64encode(hashlib.sha1(b"abc").digest()).rstrip(b"=").decode()
    key = bytes(range(16))
    plain = gps_file([(100, 10.0, 106.0)])
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(key), modes.CBC(X.FDS_IV)).encryptor()
    cipher = enc.update(padder.update(plain) + padder.finalize()) + enc.finalize()
    body = json.dumps(b64.urlsafe_b64encode(cipher).rstrip(b"=").decode()).encode()
    assert X.decrypt_fds(body, b64.urlsafe_b64encode(key).decode()) == plain


async def test_workout_track_endpoint_demo(client):
    await connected(client)
    await wait_sync(client.service)
    await post(client, "/api/cloud/sync", {"job": "workouts"})
    for _ in range(100):
        if client.service.cloud.status["state"] == "done":
            break
        await asyncio.sleep(0.05)
    h = (await (await client.get(f"/api/health?date={dt.date.today().isoformat()}")).json())["health"]
    with_gps = [w for w in h["workouts"] if w["gps"]]
    assert len(with_gps) == 3 and all("mf_sid" not in w for w in h["workouts"])   # chạy và đạp xe ngoài trời
    r = await client.get(f"/api/workouts/{with_gps[0]['start']}/track")
    pts = (await r.json())["points"]
    assert r.status == 200 and len(pts) > 100 and pts[0][0] == with_gps[0]["start"]
    assert client.service.health_db().track(with_gps[0]["start"]) == pts   # lưu lại, lần sau không tải nữa
    no_gps = next(w for w in h["workouts"] if not w["gps"])
    assert (await client.get(f"/api/workouts/{no_gps['start']}/track")).status == 404
    assert (await client.get("/api/workouts/123/track")).status == 404


async def test_all_tracks_prefetched_in_background(client):
    """Bản đồ "những nơi đã đến": lấy lịch sử xong thì lộ trình được tải sẵn ở nền; /api/tracks trả mọi lộ trình."""
    await connected(client)
    await wait_sync(client.service)
    await post(client, "/api/cloud/sync", {"job": "workouts"})
    for _ in range(200):
        await asyncio.sleep(0.05)
        body = await (await client.get("/api/tracks")).json()
        if body["routes"] and not body["pending"] and not body["places_pending"]:
            break
    assert len(body["routes"]) == 3 and body["pending"] == 0 and body["places_pending"] == 0
    # tên nơi (giả lập ở chế độ xem thử) để lọc theo thành phố / quốc gia
    assert all(r["place"] and r["place"]["cc"] == "VN" and r["place"]["city"] for r in body["routes"])
    kinds = sorted(r["kind"] for r in body["routes"])
    assert set(kinds) <= {"run", "ride"} and "ride" in kinds
    assert all(2 <= len(r["points"]) <= 601 and len(r["points"][0]) == 2 for r in body["routes"])


def test_route_kind_and_simplify():
    assert H.route_kind({"type": 1}) == "run" and H.route_kind({"type": 3}) == "walk"
    assert H.route_kind({"type": 4}) == "ride" and H.route_kind({"mf_type": 6, "mf_proto": 23}) == "ride"
    assert H.route_kind({"mf_type": 1, "mf_proto": 22}) == "run"
    pts = [[i, 10.0 + i * 1e-6, 106.0] for i in range(1000)]   # 1000 điểm cách nhau ~0,1 m
    short = H.simplify_track(pts)
    assert short[0] == [10.0, 106.0] and short[-1] == [pts[-1][1], 106.0] and len(short) < 20
    long = H.simplify_track([[i, 10.0 + i * 1e-3, 106.0] for i in range(5000)])
    assert len(long) <= 601


# ---------------------------------------------------------------- thời tiết


def test_weather_packets():
    from miband6 import weather as W

    w = W.demo()
    pk = W.packets(w, "en")
    assert [p[0] for p in pk] == [2, 4, 1, 8, 64, 16]   # hiện tại, AQI, dự báo, địa điểm, gió/độ ẩm, mặt trời
    cur = pk[0]
    assert int.from_bytes(cur[1:5], "little") == w.time and cur[5] == 28 and cur[6] == 1 and cur[7] == 31
    assert cur[8:].rstrip(b"\0") == b"Partly cloudy"
    assert pk[1][6:8] == (72).to_bytes(2, "little") and pk[1][8:].rstrip(b"\0") == b"Moderate"
    fc = pk[2]
    assert fc[6] == 7 and fc[7:11] == bytes([1, 1, 33, 25])          # 7 ngày; hôm nay: mã, mã, cao, thấp
    assert pk[3] == b"\x08" + "TP. Hồ Chí Minh".encode() + b"\0"
    assert pk[4][6:].split(b"\0")[:2] == [b"2", b"68%"]             # gió cấp Beaufort, độ ẩm
    assert pk[5][6:] == bytes([5, 52, 17, 31])
    vi = W.packets(w, "vi")[0]
    assert vi[8:].rstrip(b"\0").decode() == "Có mây"
    f = W.packets(w, "en", fahrenheit=True)[0]
    assert f[7] == 89                                               # 31,4 °C = 88,5 °F
    assert W.huami_condition(95) == 4 and W.huami_condition(45) == 18 and W.huami_condition(1234) == 0
    long = P.weather_location("x" * 100)
    assert len(long) == 1 + P.WEATHER_TEXT_MAX + 1
    cut = P.weather_location("ồ" * 30)                               # không cắt giữa ký tự nhiều byte
    assert cut[1:-1].decode("utf-8") and cut[-1] == 0


async def test_weather_sent_on_connect_and_settings(client):
    fake = await connected(client)
    for _ in range(100):
        if client.service.weather_status.get("state") == "done":
            break
        await asyncio.sleep(0.05)
    weather = [d for t, d in fake.chunked_payloads if t == 1]
    assert [d[0] for d in weather] == [2, 4, 1, 8, 64, 16]
    st = (await (await client.get("/api/state")).json())["state"]["weather"]
    assert st["state"] == "done" and st["enabled"] and st["place"] is None and st["now"]["temp"] == 31
    # chọn thành phố: gửi lại ngay, tên địa điểm mới
    places = (await (await client.get("/api/weather/search?q=n%E1%BB%99i")).json())["places"]
    assert places[0]["name"] == "Hà Nội"
    fake.chunked_payloads.clear()
    r = await post(client, "/api/weather", {"place": places[0]})
    assert (await r.json())["state"]["weather"]["place"]["name"] == "Hà Nội"
    for _ in range(100):
        if any(t == 1 and d[0] == 8 for t, d in fake.chunked_payloads):
            break
        await asyncio.sleep(0.05)
    assert (1, b"\x08" + "Hà Nội".encode() + b"\0") in fake.chunked_payloads
    r = await post(client, "/api/weather", {"place": {"name": "x", "lat": 200, "lon": 0}})
    assert r.status == 400
    r = await post(client, "/api/weather/sync", {})
    assert r.status == 200 and (await r.json())["weather"]["now"]["place"] == "Hà Nội"
    await post(client, "/api/weather", {"enabled": False, "place": None})
    st = (await (await client.get("/api/state")).json())["state"]["weather"]
    assert st["enabled"] is False and st["place"] is None


async def test_health_insights_and_settings(client):
    await connected(client)
    await wait_sync(client.service)
    today = dt.date.today().isoformat()
    h = (await (await client.get(f"/api/health?date={today}")).json())["health"]
    ins = h["insights"]
    assert set(ins) >= {"readiness", "readiness_history", "mental", "intensity", "circadian", "rem_estimated"}
    assert ins["intensity"] and 0 <= ins["intensity"]["ratio"] <= 100 and len(ins["intensity"]["days"]) == 7
    assert ins["circadian"] and ins["circadian"]["chronotype_clock"].count(":") == 1
    assert h["rem_mode"] == "estimate"
    # tắt REM: giấc ngủ không còn phút REM
    r = await post(client, "/api/prefs", {"rem_mode": "off"})
    assert (await r.json())["state"]["settings"]["rem_mode"] == "off"
    h2 = (await (await client.get(f"/api/health?date={today}")).json())["health"]
    assert all(d["rem"] == 0 for d in h2["sleep_days"]) and h2["rem_mode"] == "off"
    # lịch đồng bộ: chỉ nhận các lựa chọn có sẵn
    r = await post(client, "/api/prefs", {"sync": {"band_minutes": 15, "cloud_hours": 0, "retry_max": 300}})
    sync = (await r.json())["state"]["sync"]
    assert (sync["band_minutes"], sync["cloud_hours"], sync["retry_max"], sync["renew_hours"]) == (15, 0, 300, 0)
    assert (await post(client, "/api/prefs", {"sync": {"band_minutes": 7}})).status == 400
    acct = (await (await client.get("/api/cloud/account")).json())["account"]
    assert acct == {"logged_in": False, "saved": None, "can_renew": False}
    assert (await post(client, "/api/cloud/renew", {})).status == 409


async def test_workout_without_route_has_no_map_button(client):
    """Tệp lộ trình tải về trống (đi bộ không bật GPS điện thoại…): bảng hiện "Không có GPS" thay cho nút Bản đồ."""
    await connected(client)
    await wait_sync(client.service)
    await post(client, "/api/cloud/sync", {"job": "workouts"})
    for _ in range(100):
        if client.service.cloud.status["state"] == "done":
            break
        await asyncio.sleep(0.05)
    url = f"/api/health?date={dt.date.today().isoformat()}"
    with_gps = [w for w in (await (await client.get(url)).json())["health"]["workouts"] if w["gps"]]
    assert len(with_gps) == 3
    client.service.health_db().set_track(with_gps[0]["start"], [])   # lộ trình không có điểm nào
    after = {w["start"]: w["gps"] for w in (await (await client.get(url)).json())["health"]["workouts"]}
    assert after[with_gps[0]["start"]] is False and sum(after.values()) == 2
