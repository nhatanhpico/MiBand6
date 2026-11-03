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

### Health data, watch faces, wallpapers

- **Fetch** (`MiBand6.fetch_data`, chars `0x0004` control / `0x0005` data, own `_fetch_lock`, not `self._lock`): `01 <type> <since>` → `10 01 01 <len> <start>` → `02` → numbered packets → `10 02 01`. **Never send the `03` ack**: it marks data as synced on the band and Mi Fitness would lose it. Instead `BandService._sync_health` keeps a per-type "since" in `HealthDB` (`sync` table) and repeats rounds until no new data. Decoders are pure functions in `health.py`; storage and summaries are in `healthdb.py` (one SQLite file per band under `<config dir>/health/`). `FakeBand.health` (`simulator.DemoHealth`) serves 10 days of synthetic data and counts `fetch_acks` (tests assert 0).
- **Watch face upload** (`MiBand6.upload_watchface`, `0x1531`/`0x1532`, Gadgetbridge `UpdateFirmwareOperation2020`): Mi Band 6 accepts only `UIHH` files; a `0x39` config command (via `write_config`, so it's encrypted in 2021 mode) precedes `d0/d2/d3`, then chunks acked by `d4 <offset>`, then `d5`, `d6`.
- **Watch face tab** (`#settings/face`): one simulator canvas (`#simScreen`, true 152×486) shows the photo being edited, a chosen `.bin` drawn from its own layers, or the face installed through the app. Every image sent to the server is re-rendered from that canvas, so large photos never hit the 3 MB limit. `.bin` rendering (`watchface.scene`/`render`) follows watchface-js's `previewGenerator` (UIHH_MIBAND parameter ids, Number alignment flags, status values from `face_status`; `BandService.face_status` fills in time, battery, steps, HR). `/api/watchface/inspect` returns a still `preview` plus `animation` (`below`/`above` PNG layers and per-animation frames, interval ≥ 80 ms) that `simAnimate` plays with requestAnimationFrame. The embedded preview image is only a fallback: files from BandStudio embed a small watermarked thumbnail without the animation.
- **Wallpaper**: the browser crops the picture to 152×486 and renders digit images; `/api/wallpaper` sends raw RGBA to `watchface.wallpaper_face`, which builds a UIHH file (87-byte header template, protobuf-style varint parameters, `BM` images with 24-bit RGB565 + inverted alpha) per the watchface-js format description. The 87-byte header must be Mi Band 6's (`watchface.band6_header`: `3E 00 3E 00` at 14–17, `1F 22 11 00` at 22–25, a per-face id at 12–13/18–19, device id 148 at 79, param-info size at 83), as in pixel-watchface's encoder that runs on real bands. watchface-js's shared `UIHH_MIBAND` header is Mi Band 5's: a real Mi Band 6 accepted such a file (`d5 01`, `d6 01`) and then froze drawing it. Images use format field 100; no preview images are embedded.
- **Sleep decoding** (`health.sleep_sessions`): Mi Band 6 is read the way Gadgetbridge's `MiBand2SampleProvider` does it, not `HuamiExtendedSampleProvider`. Only the low nibble of each sample's kind byte matters (9 light, 11 deep, 12 wake-up, 1 activity), it is written only when the state changes, and 0 ("no change") / 10 ("ignore") carry the previous state forward (`effective_kinds`; pass `previous=` from `HealthDB.kind_before`). The band writes these markers ~11 min late; session edges are pulled back using the per-minute "sleep" byte (`ONSET_LEVEL`, `WAKE_LEVEL`, max `EDGE_MINUTES`), which reproduces the times the band itself shows. `simulator.DemoHealth` encodes nights the same way, and `tests/test_health.py` holds a synthetic copy of a real night.
- **Backfill and Mi Fitness workouts**: `_backfill_one` runs once per data type (flag `<name>_backfill` in the `sync` table) to fetch anything the band still holds older than the first 30-day sync. `CloudSync` has a second job, `job="workouts"` (`POST /api/cloud/sync {"job": "workouts"}`), which reads `xiaomi_cloud.fetch_sport_records` (endpoint per the mifit project) and stores rows via `HealthDB.add_cloud_workouts`. Band and cloud rows within ±3 min are merged (the band wins, keeping `mf_type`). Mi Fitness sport codes differ from the band's, and `summary()` learns the mapping from merged rows.
- **Route maps** open in the in-page `#mapDialog` (the user asked for no extra windows). Maps exist only in the macOS app: the map area is a native `MKMapView` (`macos/Sources/NativeMap.swift`, a subview of the `WKWebView`). `app.js` detects `window.webkit.messageHandlers.nativeMap` and posts `show`/`routes`/`rect`/`hide`/`export` with the map's visible CSS rect and `[[lat, lon]]` routes; `ResizeObserver`/resize/dialog scroll keep the rect in sync, a click on a route calls back `window.nativeMapClick(id)`, and `export` renders an `MKMapSnapshotter` image (routes drawn with `snapshot.point(for:)`, whose origin is bottom-left) plus a footer, saves it to ~/Downloads and opens `NSSharingServicePicker`. In a browser the map area shows a notice whose button opens `miband6://open?page=health/map:<start|all>` (Info.plist `CFBundleURLTypes`, `AppDelegate.application(_:open:)`, `WebWindowController.open(page:)`; `route()` turns `#health/map:…` into `openMapFromHash`). Both use `openMap(w)` for one workout, `openAllMaps()` for "places you've been" (`GET /api/tracks` → simplified routes with `kind` run/walk/ride from `health.route_kind`). `BandService.prefetch_tracks` downloads missing routes in the background (3 at a time, on start and after a Mi Fitness import); `workout_track` shares one in-flight download per workout and pushes a `tracks` event when one is stored. Xiaomi's FDS host resolves to three IPs and two of them don't answer from some networks; `netrace.RacingAdapter` (Happy Eyeballs: attempts 250 ms apart, the winner remembered for 10 min) brings a download from ~60 s to ~1 s, used by `xiaomi_cloud._fds_session()`. Route places for the city/country filter come from Nominatim (`geo.py`, coordinates rounded to 0.01°, 1 request/s) and are cached in the `places` table keyed by `geo.area_key`; `/api/tracks` returns `place` per route and `places_pending`.
- **Weather** (`weather.py`, encoders in `protocol.py`): Open-Meteo forecast + air quality for a chosen city or an IP-based location (`ipapi.co`, fallback `ipwho.is`), turned into Gadgetbridge's six chunked type-1 packets (current, AQI, forecast, location, wind/humidity, sunrise/sunset) and sent with `MiBand6.send_weather`. `BandService._periodic_weather` sends on connect and every `WEATHER_EVERY`; settings live in `settings["weather"]` (`POST /api/weather`, `/api/weather/sync`, `GET /api/weather/search`). Demo mode uses `weather.demo()` and a fixed place list, never the network.
- **GPS routes**: Mi Fitness (not the band) stores routes for outdoor runs and rides (`proto_type` 22/23). `fetch_sport_records` keeps each record's `sid` and region. `GET /api/workouts/{start}/track` makes a signed `gen_download_url` request (`xiaomi_cloud.fetch_gps_file`), downloads the file, decrypts it (AES-CBC, fixed IV) and decodes it (`health.decode_gps_file`: versions 1–3 have fixed point sizes in `GPS_POINT_SIZE`, v3 = 26 bytes checked on real files; newer versions are sized by `_gps_layout_score`, and an unreadable file is kept under `health/gps-unread/`). The result is cached in the `tracks` table. `mf_sid` and similar fields never leave the server (`summary()` strips them and exposes `gps`). The map in `app.js` draws OpenStreetMap tiles, darkened with a CSS filter, plus an SVG route; it uses no library and no API key (CARTO now requires one).
- **Readiness, mental state, Activity Intensity Ratio, circadian strain** (`insights.py`, pure; `HealthDB.insights` builds per-night and per-day aggregates over 60 days, `BandService.health_summary` caches the result per date/sync/REM/language): a Daily Readiness Score (first card on the Health page; Oura/Garmin/Apple-style contributors against personal baselines, band stress replaces HRV, no temperature) with a train-hard/train/easy/rest verdict and HR-zone plan; recovery time from a Banister-style fatigue model over hourly TRIMP (`recovery_hours`, τ = 36 h, today's workouts count, history evaluated at 08:00), Edwards TRIMP + ACWR over worn days only, CADENCE-Adults cadence thresholds, MCTQ social jetlag and MSFsc, Fischer CPD, Phillips SRI. Thresholds are documented in `docs/suc-khoe.md` and must stay in sync.
- **REM** is estimated (`health.estimate_rem`, called from `sleep_sessions(rem=True)`): Mi Band 6 never records REM and Mi Fitness reports REM 0 for it. Needs ≥80% heart-rate coverage (band "sleep assist" = `hr_sleep_assist`); setting `settings["rem_mode"]` ("estimate" | "off", `/api/prefs`).
- **Health analysis** (`health.analyze`, fed by `HealthDB.analysis`, returned as `health.analysis` by `GET /api/health`): rule-based items with statuses good/ok/watch/alert and translated text; thresholds are documented in `docs/suc-khoe.md` and must stay in sync with the code.
- The band can't report settings or the active watch face. The UI shows sections never written by this app as "Chưa đồng bộ" with nothing pre-selected (`SYNC_KEYS`/`markSync` in `app.js`), and refuses to save while a field is still unknown.

### Reconnecting after a restart (macOS)

A saved address is only a string. Given a string, bleak scans for the device, but macOS often keeps the band's link open after the app quits, and a connected band doesn't advertise. `MiBand6._open` therefore asks CoreBluetooth first (`device.known_peripheral`: `retrievePeripheralsWithIdentifiers`, falling back to `retrieveConnectedPeripheralsWithServices` FEE0/FEE1). It passes bleak a `BLEDevice` whose `details` is `(CBPeripheral, CentralManagerDelegate)`, which bleak connects without scanning. `scan()` also appends system-connected bands (`connected_bands`).

### Event flow

Band notifications reach `MiBand6._on_*` handlers, which call `on_event(kind, data)`. That goes to `BandService.on_event`, which stores the value in `service.live[kind]` and pushes `{"type": kind, "data": ...}` to every WebSocket client at `/api/events`. `jsonable()` serializes the protocol dataclasses. The browser receives a full `state()` snapshot in the `hello` message and again after each state change.

### App settings vs band settings

Two pages: `#settings` ("Band settings": sub-tabs profile/display/face/apps/health, everything written to the band) and `#app` ("App settings": language, sync schedule, Mi Fitness account, connection, weather, REM estimation; nothing written to the band). The macOS app menu opens them with ⌘, and ⇧⌘, (`openAppSettings`/`openBandSettings` → `WebWindowController.open(page:)`). Keep that split when adding settings.

`settings["sync"]` (`SYNC_DEFAULTS`/`SYNC_CHOICES`): `band_minutes` (`_periodic_health`), `cloud_hours` (`_cloud_background`, also run by `_periodic_cloud` every `CLOUD_TICK` while the server runs), `renew_hours` (proactive passToken renewal; `/api/cloud/renew`, `/api/cloud/account`), `retry_max` (caps the default `RECONNECT_DELAYS`). Saved through `POST /api/prefs {sync: {...}}`; `state()` carries `sync` and `account`. The interface language lives here too (the sidebar no longer has it). UI text is not selectable (`user-select: none` on `body`, inputs excepted).

### Settings

`POST /api/settings/{section}` is dispatched in `BandService.apply()`. Each branch validates the input, writes it to the band, and then saves it to `Store` (`~/Library/Application Support/MiBand6Manager/config.json`). Most settings (profile, app layout, ...) **cannot be read back from the band**, so `Store` is the source of truth for what the UI displays. To add a setting, you usually touch `protocol.py` (encoder), `apply()` (a new section), and `app.js`/`index.html`.

### Simulator and tests

`simulator.FakeBand` mimics the `BleakClient` API and plays the band's side of both auth protocols. It independently checks CRC and sequence numbers on encrypted 2021 packets. It records `writes`, `config_commands` (already decrypted), and `chunked_payloads` so tests can assert on them. `tests/test_device.py` drives `MiBand6` directly against it. `tests/test_web.py` drives the full HTTP API through `BandService(..., demo=True)`. A new command that expects a reply from the band needs a matching branch in `FakeBand`.

### Auth key handling

The key comes either from the UI or from `MIBAND6_AUTH_KEY` in `.env` (`envfile.py`; existing env vars are not overridden). A key from `.env` is never sent to the browser (`state()` blanks it) and never written to `config.json`. `.env` is gitignored.

### HTTP security (`guard` middleware)

By default the server accepts only localhost Host headers. With `--lan` it binds to `0.0.0.0` and requires a random token (query param, cookie, or `X-Token` header). Requests with a cross-origin `Origin` header are rejected. Every `POST /api/*` must use `Content-Type: application/json`. Handlers raise `ApiError(msg, status)` to return JSON errors.

### Mi Fitness cloud

`xiaomi_cloud.py` implements Xiaomi QR/password login and the Mi Fitness API (devices, user profile). Two places use it: `web/cloud.py` (`CloudSync`, a background profile sync whose result is applied via `BandService.apply_cloud_profile` and written to the band now or on the next connect through `pending_sync`) and `tools/mifitness_key.py`. The login session (service token, ssecurity, passToken, device id) is cached in `~/Library/Caches/MiBand6Manager/xiaomi-session.json` and mirrored into the `.env` the server loaded as `MIBAND6_XIAOMI_SESSION` (base64 JSON; `serve()` sets `xiaomi_cloud.ENV_FILE`, not in `--demo`). Sessions don't expire by age: on HTTP 401, `XiaomiLogin.request` calls `renew()` once (passToken → `serviceLogin` → new service token, per mifit's renew notes) and retries. After each connect, `BandService._cloud_background` runs non-interactive `CloudSync` jobs (profile every `CLOUD_PROFILE_EVERY`, workouts every `sync.cloud_hours` from the `cloud_workouts` sync mark minus an overlap; `_periodic_cloud` repeats this while the server runs); it never shows a QR code and is off in demo mode (`service.auto_cloud`). A user-started sync cancels a running background one.

## i18n

Switching language does **not** reload the page: `setLanguage()` loads the catalog if needed, `translateDom()` re-translates text nodes and attributes in both directions (`sourceOf` remembers each node's Vietnamese source in `DOM_SRC`, falling back to a reverse catalog), and `rerenderLanguage()` redraws the parts that mix text with numbers or dates (state, alarms, charts on the visible page, labelled `<option>`s via `relabelOptions`). Text written by the server (health analysis) is re-fetched after `/api/prefs` switches the server language. Anything new that formats translated text with numbers needs a hook in `rerenderLanguage()`.

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
