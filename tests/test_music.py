import asyncio
import sys

import pytest

from miband6 import music, protocol as P
from miband6.device import MiBand6
from miband6.simulator import FakeBand


@pytest.mark.parametrize("protocol", ["classic", "2021"])
async def test_music_events_and_metadata_on_each_transport(protocol):
    key = bytes(range(16))
    band = FakeBand(key, protocol)
    events = []
    device = MiBand6("test", key, protocol, client=band, on_event=lambda k, v: events.append((k, v)))
    await device.connect()
    for raw in (b"\xfe", b"\xfe\x02", b"\xfe\xe0", b"\xfe\x03", b"\xfe\xe1"):
        band._notify(P.CHAR_DEVICE_EVENT, raw)
    await asyncio.sleep(0)
    assert [v for k, v in events if k == "music"] == ["open", "next", "close"]
    packet = P.music_info(True, "Ban nhạc", "A\0B", 43)
    await device.write_chunked(P.CHUNKED_MUSIC, packet)
    assert band.chunked_payloads[-1] == (3, b"\x4b\x01\0\0\0" + "Ban nhạc\0A B\0".encode() + b"+")
    await device.disconnect()


def test_music_optional_fields_and_text_limits():
    assert P.music_info(False, "", "") == bytes.fromhex("01 00 00 00 00")
    title = "a" + "🎵" * 100
    packet = P.music_info(True, "", title)
    assert packet[:5] == bytes.fromhex("09 01 00 00 00")
    assert packet[5:-1].decode() == title[:20]
    assert packet[-1] == 0


async def test_controls_are_ordered_and_stopping_discards_queued_controls(monkeypatch):
    calls = []
    sent = []
    started, release = asyncio.Event(), asyncio.Event()

    async def player(player, action):
        calls.append((player, action))
        return action.encode()

    async def send(packet):
        if packet == b"previous":
            started.set()
            await release.wait()
        sent.append(packet)

    monkeypatch.setattr(music, "_player_packet", player)
    bridge = music.MusicBridge(send, pytest.fail)
    for action in ("open", "next", "previous", "pause"):
        bridge.handle(action, "spotify")
    await asyncio.wait_for(started.wait(), 2)
    pending = bridge._task
    bridge.handle("close", "spotify")
    release.set()
    await pending
    assert calls == [("spotify", "open"), ("spotify", "next"), ("spotify", "previous")]
    assert sent == [b"open", b"next", b"previous"]


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS scripting environment")
async def test_mac_automation_with_absent_player(monkeypatch):
    # Exercise the actual script without sending Apple Events to a user's player.
    monkeypatch.setitem(music._PLAYER_IDS, "test", "invalid.miband6.test.missing-player")
    assert await music._player_packet("test", "play") == P.music_info(False, "", "")


async def test_music_screen_refreshes_on_change_and_stops_on_close(monkeypatch):
    reads = []
    sent = []
    changed = asyncio.Event()

    async def player(player, action):
        reads.append(action)
        return b"first" if len(reads) < 3 else b"changed"

    async def send(packet):
        sent.append(packet)
        if packet == b"changed":
            changed.set()

    monkeypatch.setattr(music, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(music, "_player_packet", player)
    bridge = music.MusicBridge(send, pytest.fail)
    bridge.handle("open", "music")
    await asyncio.wait_for(changed.wait(), 2)
    task = bridge._task
    bridge.stop()
    await asyncio.gather(task, return_exceptions=True)
    assert sent == [b"first", b"changed"]
    assert reads == ["open", "refresh", "refresh"]
