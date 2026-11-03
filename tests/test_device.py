import asyncio
import os

import pytest

from miband6.simulator import FakeBand
from miband6 import protocol as P
from miband6.device import AuthError, MiBand6, PROTOCOL_2021, PROTOCOL_AUTO, PROTOCOL_CLASSIC

KEY = bytes.fromhex("8f2b1c0a77d94e3fa5c1b2e3d4f50617")


def make(band, protocol=PROTOCOL_AUTO, key=KEY):
    events = []
    logs = []
    dev = MiBand6("AA-BB", key, protocol, on_event=lambda k, d: events.append((k, d)),
                  log=logs.append, client=band, name="Mi Smart Band 6")
    return dev, events, logs


async def test_classic_auth_and_reads():
    band = FakeBand(KEY, "classic")
    dev, events, _ = make(band)
    assert await dev.connect() == PROTOCOL_CLASSIC
    assert band.authenticated
    # giờ được đồng bộ ngay sau khi xác thực
    assert any(u == P.CHAR_CURRENT_TIME for u, _ in band.writes)
    await dev.refresh_all()
    kinds = {k: d for k, d in events}
    assert kinds["battery"].level == 87
    assert kinds["activity"].steps == 6543
    assert kinds["device_info"].firmware == "1.0.6.16"
    assert kinds["band_time"].hour == 21


async def test_classic_wrong_key():
    band = FakeBand(KEY, "classic", with_2021_chars=False)
    dev, _, _ = make(band, key=os.urandom(16))
    with pytest.raises(AuthError):
        await dev.connect()
    assert not band.is_connected


async def test_2021_auth_and_encrypted_config():
    band = FakeBand(KEY, "2021")
    dev, events, _ = make(band, PROTOCOL_2021)
    assert await dev.connect() == PROTOCOL_2021
    assert band.authenticated
    await dev.write_config(P.time_format_24h(True))
    await dev.write_config(P.language("vi_VN"))
    await asyncio.sleep(0.05)
    assert band.config_commands[-2:] == [P.time_format_24h(True), P.language("vi_VN")]
    assert band.verified_encrypted == 2
    alarms = await dev.request_alarms()
    assert [(a.slot, a.hour, a.minute) for a in alarms] == [(0, 6, 30), (2, 9, 0)]
    await dev.send_notification("Xin chào", "Tin nhắn thử từ máy Mac", "Test", 11)
    await dev.set_display_items(["hr", "weather"])
    await asyncio.sleep(0.05)
    assert band.chunked_payloads[0] == (0, P.notification_payload("Xin chào", "Tin nhắn thử từ máy Mac", "Test", 11))
    assert band.chunked_payloads[1] == (2, P.display_items(["hr", "weather"]))


async def test_2021_wrong_key():
    band = FakeBand(KEY, "2021")
    dev, _, _ = make(band, PROTOCOL_2021, key=os.urandom(16))
    with pytest.raises(AuthError):
        await dev.connect()


async def test_auto_falls_back_to_2021():
    band = FakeBand(KEY, "2021")
    dev, _, logs = make(band, PROTOCOL_AUTO)
    assert await dev.connect() == PROTOCOL_2021
    assert any("2021" in line for line in logs)


async def test_classic_config_alarms_and_chunked():
    band = FakeBand(KEY, "classic")
    dev, _, _ = make(band)
    await dev.connect()
    alarm = P.Alarm(slot=4, enabled=True, hour=5, minute=55, days=P.DAY_BITS[5])
    await dev.set_alarm(alarm)
    assert band.config_commands[-1] == P.alarm_command(alarm)
    alarms = await dev.request_alarms()
    assert len(alarms) == 2
    await dev.send_notification("A" * 10, "B" * 100)
    assert band.chunked_payloads[-1] == (0, P.notification_payload("A" * 10, "B" * 100))
    await dev.set_step_goal(10000)
    assert (P.CHAR_USER_SETTINGS, P.fitness_goal(10000)) in band.writes


async def test_heart_rate_and_find():
    band = FakeBand(KEY, "classic")
    dev, events, _ = make(band)
    await dev.connect()
    bpm = await dev.measure_heart_rate(timeout=2)
    assert bpm == 72
    await dev.find_band(True)
    assert band.writes[-1] == (P.CHAR_NEW_ALERT, P.incoming_call("Tìm vòng tay"))
    await dev.find_band(False)
    assert band.writes[-1] == (P.CHAR_NEW_ALERT, P.STOP_CALL)


async def test_find_phone_event_is_acknowledged():
    band = FakeBand(KEY, "classic")
    dev, events, _ = make(band)
    await dev.connect()
    band.press_find_phone()
    await asyncio.sleep(0.05)
    assert ("device_event", P.EVENT_FIND_PHONE_START) in events
    assert band.config_commands[-1] == P.ACK_FIND_PHONE



async def test_saved_address_uses_peripheral_known_to_macos(monkeypatch):
    """Mở lại ứng dụng khi macOS còn giữ kết nối: nối thẳng thiết bị hệ thống trả về thay vì quét theo địa chỉ."""
    import bleak

    from miband6 import device as D

    known = object()
    seen = []

    class Client:
        def __init__(self, target, **kw):
            seen.append(target)
            self.is_connected = False

        async def connect(self):
            raise OSError("stop here")

    async def fake_known(address):
        return known if address == "DC9516B3-5FF3-9052-C620-C72D7B6B4C83" else None

    monkeypatch.setattr(D, "known_peripheral", fake_known)
    monkeypatch.setattr(bleak, "BleakClient", Client)
    for address, expected in (("DC9516B3-5FF3-9052-C620-C72D7B6B4C83", known), ("11111111-2222-3333-4444-555555555555", None)):
        band = D.MiBand6(address, bytes(16))
        with pytest.raises(OSError):
            await band._open(1.0)
        assert seen[-1] is (known if expected else address)
