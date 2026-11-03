# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Desktop app for controlling a Xiaomi Mi Smart Band 6 over Bluetooth LE without a phone. A Python server (aiohttp + bleak) owns the BLE connection; the UI is a plain HTML/CSS/JS page served to the browser. The same server and UI also ship as a native macOS app (`macos/`, see below). The README, UI strings, code comments, and docstrings are in Vietnamese. Keep that convention when you edit existing code.

## Commands

Everything runs through `uv`. Python is 3.12 (`.python-version`), and `requires-python >=3.10`.

```bash
uv run miband6-web                 # start server, opens http://localhost:8766
uv run miband6-web --demo          # simulated band (FakeBand), no Bluetooth; config goes to a temp file
uv run miband6-web --no-browser    # don't auto-open browser (also: --port N, --lan, --env PATH)
uv run miband6-cli scan            # quick BLE check without the UI
uv run miband6-cli info -v         # reads address/key from .env
uv run --extra desktop miband6-app # legacy Qt desktop app
./macos/build.sh                   # build dist/Mi Band 6.app (self-contained: bundles Python 3.12 + deps)
./macos/build.sh --dev             # small app that runs this checkout's .venv and source (no rebuild after edits)
open "dist/Mi Band 6.app" --args --demo   # native app with the simulated band

uv run pytest                                              # full suite (~12s, no hardware needed)
uv run pytest tests/test_device.py                         # one file
uv run pytest tests/test_device.py::test_classic_auth_and_reads   # one test
uv run python tests/i18n_strings.py                        # list UI strings missing an English translation

uv run tools/mifitness_key.py      # fetch auth key from Xiaomi cloud (must run inside the project env; imports miband6.xiaomi_cloud)
```

pytest runs with `asyncio_mode = "auto"`, so `async def test_*` functions need no decorator. No linter or formatter is configured.

## Architecture

Layered from pure to I/O. Each layer only calls the one below it:

1. **`protocol.py`**: UUIDs, constants, and pure functions that build and decode packets. There is no Bluetooth code here, so this is where new band commands get encoded and unit-tested. It also holds the option tables (`MENU_LABELS`, `NOTIFICATION_ICONS`, `DEVICE_EVENTS`, `LANGUAGES`, ...) that `/api/meta` sends to the frontend.
2. **`crypto.py`**: AES-128-ECB for auth, a hand-written ECDH over NIST B-163 (sect163r2) in tiny-ECDH's little-endian layout (tests check it against OpenSSL), and `ChunkedEncoder2021`/`ChunkedDecoder2021` for the "2021" chunked transport (endpoints `0x0082` auth and `0x0090` compat, with CRC32 and sequence numbers when encrypted).
3. **`device.py`**: the async `MiBand6` class. It takes an optional `client=` that replaces `BleakClient`; this is how the simulator plugs in.
4. **`web/server.py`**: `BandService` holds the single band connection, the persisted `Store`, and the open WebSocket clients. `build_app()` defines the REST routes and the `guard` middleware.
5. **`web/static/`**: `index.html`, `app.js`, `style.css`. There is no build step. The server replaces `{{v}}` in `index.html` with a cache-busting version.

### Two auth protocols

The band uses either **classic** auth (AES challenge on char `0x0009`) or **2021** auth (ECDH key exchange over chunked chars `0x0016`/`0x0017`). `PROTOCOL_AUTO` tries classic first, then 2021, and the protocol that worked is remembered per device. Once 2021 auth succeeds, config commands must travel **encrypted through endpoint `0x0090`** instead of the plain characteristic. For that reason, new device operations should go through `write_config`, `write_chunked`, `write_user_settings`, or `_hr_control`. These pick the transport and hold `self._lock`; calling `_write` directly bypasses both.

### Keeping the connection (auto-reconnect)

`BandService` reconnects by itself when `settings.keep_connected` is on (default true). `want_connected` becomes true after any successful connect and false when the user disconnects. An unexpected `disconnected` event (ignored while `busy`, since the connect call reports that failure) starts `_reconnect_loop`, which retries the last device (`_reconnect_target()`: saved key or `.env` key, and the protocol that worked) with `RECONNECT_DELAYS` backoff. It stops on a 400 error or after `MAX_AUTH_FAILURES` consecutive 401s. `service.start()` (called from `serve()`, not the constructor, so tests aren't affected) auto-connects on startup. `POST /api/reconnect` skips the wait (the macOS app calls it on wake). `state()` includes `reconnect: {attempt, at}` while waiting. Tests shorten waits with `service.reconnect_delays` and simulate a drop with `FakeBand.drop()`.

Only one server should hold the band. `serve()` probes the port first (`running_server()` checks `/api/meta` for `server == SERVER_ID`). A plain `miband6-web` then opens the running server's UI and exits. In `--app` mode it announces the existing server and takes over when that server goes away.

### Event flow

Band notifications reach `MiBand6._on_*` handlers, which call `on_event(kind, data)`. That goes to `BandService.on_event`, which stores the value in `service.live[kind]` and pushes `{"type": kind, "data": ...}` to every WebSocket client at `/api/events`. `jsonable()` serializes the protocol dataclasses. The browser receives a full `state()` snapshot in the `hello` message and again after each state change.

### Settings

`POST /api/settings/{section}` is dispatched in `BandService.apply()`. Each branch validates the input, writes it to the band, and then saves it to `Store` (`~/Library/Application Support/MiBand6Manager/config.json`). Most settings (profile, app layout, ...) **cannot be read back from the band**, so `Store` is the source of truth for what the UI displays. To add a setting, you usually touch `protocol.py` (encoder), `apply()` (a new section), and `app.js`/`index.html`.

### Simulator and tests

`simulator.FakeBand` mimics the `BleakClient` API and plays the band's side of both auth protocols. It independently checks CRC and sequence numbers on encrypted 2021 packets. It records `writes`, `config_commands` (already decrypted), and `chunked_payloads` so tests can assert on them. `tests/test_device.py` drives `MiBand6` directly against it. `tests/test_web.py` drives the full HTTP API through `BandService(..., demo=True)`. A new command that expects a reply from the band needs a matching branch in `FakeBand`.

### Auth key handling

The key comes either from the UI or from `MIBAND6_AUTH_KEY` in `.env` (`envfile.py`; existing env vars are not overridden). A key from `.env` is never sent to the browser (`state()` blanks it) and never written to `config.json`. `.env` is gitignored.

### HTTP security (`guard` middleware)

By default the server accepts only localhost Host headers. With `--lan` it binds to `0.0.0.0` and requires a random token (query param, cookie, or `X-Token` header). Requests with a cross-origin `Origin` header are rejected. Every `POST /api/*` must use `Content-Type: application/json`. Handlers raise `ApiError(msg, status)` to return JSON errors.

### Mi Fitness cloud

`xiaomi_cloud.py` implements Xiaomi QR/password login and the Mi Fitness API (devices, user profile). Two places use it: `web/cloud.py` (`CloudSync`, a background profile sync whose result is applied via `BandService.apply_cloud_profile` and written to the band now or on the next connect through `pending_sync`) and `tools/mifitness_key.py`. The login session is cached in `~/Library/Caches/MiBand6Manager/xiaomi-session.json`.

## i18n

Vietnamese source strings are the translation keys. `web/static/i18n/en.json` is the single English catalog, used by both the server (`i18n.tr()`) and the browser (`t()` in `app.js`). `tests/test_i18n.py` **fails** in any of these cases:
- a UI string has no English entry,
- `en.json` has an entry that nothing uses anymore,
- `{placeholder}` names differ between the source string and its translation.

The collector (`tests/i18n_strings.py`) only finds strings in these forms:
- text and `placeholder`/`aria-label`/`title`/`data-empty` attributes in `index.html`,
- `t("…")` in `app.js` (double quotes only),
- `t("…")` in `macos/Sources/*.swift` (keep `{placeholder}` style, never Swift `\(…)` interpolation inside the key),
- `tr('…')` in Python where the first argument is a string literal (not an f-string or a variable),
- the label dicts in `protocol.py`.

When you add or change a user-facing string, write it in Vietnamese in one of those forms and update `en.json` in the same change.

## macOS app (`macos/`)

A Swift shell compiled with plain `swiftc` (no Xcode project) by `macos/build.sh`. It runs `Contents/Resources/run-server`, a launcher script generated by build.sh that `exec`s the bundled or `.venv` Python with `-m miband6.web.server --app`. `exec` matters: Python must stay a direct child of the app so macOS attributes Bluetooth (TCC) to the app, whose `Info.plist` has `NSBluetoothAlwaysUsageDescription`. `--app` mode prints `MIBAND6_READY <url>` on stdout, stops on SIGTERM, and exits if its parent dies. All output goes to `~/Library/Logs/MiBand6Manager/server.log`.

- `ServerProcess.swift`: spawns and supervises the server (restart with backoff; SIGTERM then SIGKILL on quit).
- `BandEvents.swift`: its own WebSocket to `/api/events` plus REST calls for the menu bar.
- `WebWindow.swift`: `WKWebView` window that shows the web UI. External links open in the browser; downloads go to ~/Downloads.
- `AppDelegate.swift`: status item and menu, activation policy (Dock icon only while the window is open), wake → `/api/reconnect`, notifications, launch at login via `SMAppService`.
- UI strings use `t("…")` in Swift with the same Vietnamese-key `en.json` (fetched from the server). `tests/i18n_strings.py` collects them, so the i18n rules above apply to Swift too.

The bundled build is a snapshot: Python/JS changes need `./macos/build.sh` again (or use `--dev`). Signing is ad-hoc unless `MIBAND6_SIGN_IDENTITY` is set, so macOS may ask for Bluetooth permission again after each rebuild. `dist/` and `macos/build/` are gitignored.

## Legacy desktop GUI

`gui/` is the older PySide6 app (optional `desktop` extra). It is still covered by `tests/test_gui_demo.py`, which runs offscreen, and PySide6 is in the `dev` dependency group. The web app is the primary interface.
