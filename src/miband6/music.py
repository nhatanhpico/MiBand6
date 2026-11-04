"""Bridge the band's music screen to the macOS player selected by the user."""

import asyncio
import json

from . import protocol as P


_POLL_SECONDS = 5
_PLAYER_IDS = {"music": "com.apple.Music", "spotify": "com.spotify.client"}
# Fixed script and allowlisted arguments. Query the running process before sending
# any Apple event, so opening the music screen never launches an idle player.
_SCRIPT = """
ObjC.import("AppKit");
function run(args) {
    const [id, action] = args;
    const running = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(id);
    if (!running.js.length) return JSON.stringify({});
    const app = Application(id);
    switch (action) {
        case "play": app.play(); break;
        case "pause": app.pause(); break;
        case "next": app.nextTrack(); break;
        case "previous": app.previousTrack(); break;
        case "volume_up": app.soundVolume = Math.min(100, app.soundVolume() + 5); break;
        case "volume_down": app.soundVolume = Math.max(0, app.soundVolume() - 5); break;
    }
    const state = app.playerState();
    const volume = app.soundVolume();
    if (state === "stopped") return JSON.stringify({volume});
    const track = app.currentTrack;
    return JSON.stringify({playing: state === "playing", title: track.name(), artist: track.artist(), volume});
}
"""


async def _player_packet(player: str, action: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/osascript", "-l", "JavaScript", "-e", _SCRIPT, _PLAYER_IDS[player], action,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    if proc.returncode:
        raise RuntimeError(stderr.decode(errors="replace").strip())
    state = json.loads(stdout)
    return P.music_info(state.get("playing", False), state.get("artist", ""), state.get("title", ""), state.get("volume"))


class MusicBridge:
    """Serialize button presses and refresh metadata only while the screen is open."""

    def __init__(self, on_update, on_error):
        self._send = on_update
        self._error = on_error
        self._task = None
        self._queue = None
        self._sending = None
        self._open = False

    def stop(self):
        if self._task and self._sending is not self._task:
            self._task.cancel()
        self._task = None
        self._queue = None
        self._open = False

    def handle(self, action: str, player: str):
        if action == "close" or player not in _PLAYER_IDS:
            self.stop()
            return
        if action not in P.MUSIC_ACTIONS.values():
            return
        if action == "open":
            self._open = True
        if self._task is None or self._task.done():
            self._queue = asyncio.Queue()
            self._task = asyncio.create_task(self._run(player, self._queue))
        self._queue.put_nowait(action)

    async def _run(self, player, queue):
        previous = None
        try:
            while self._queue is queue:
                try:
                    action = await asyncio.wait_for(queue.get(), timeout=_POLL_SECONDS)
                except asyncio.TimeoutError:
                    action = "refresh"
                if self._queue is not queue:
                    return
                if action == "open":
                    await asyncio.sleep(0.1)  # firmware ignores metadata immediately after opening
                packet = await _player_packet(player, action)
                if action == "open" or packet != previous:
                    # Finish the fragmented BLE write even if the screen closes midway.
                    owner = self._sending = asyncio.current_task()
                    try:
                        await self._send(packet)
                    finally:
                        if self._sending is owner:
                            self._sending = None
                    previous = packet
                if not self._open and queue.empty():
                    return
        except Exception as exc:
            if self._queue is queue:
                self._error(str(exc) or type(exc).__name__)
