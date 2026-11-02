"""Kiểm thử đọc auth key từ tệp .env."""

import json
import os

from aiohttp.test_utils import TestClient, TestServer

from miband6.config import Store
from miband6.envfile import ENV_KEY, load_env, parse_env, write_env_value
from miband6.web.server import BandService, build_app

KEY = "8f2b1c0a77d94e3fa5c1b2e3d4f50617"
JSON = {"Content-Type": "application/json"}


def test_parse_env_formats():
    env = parse_env('''
# chú thích
MIBAND6_AUTH_KEY=0x8f2b1c0a77d94e3fa5c1b2e3d4f50617
export MIBAND6_ADDRESS="AB-CD"   
MIBAND6_PROTOCOL=2021 # kiểu mới
EMPTY=
bad line
''')
    assert env == {"MIBAND6_AUTH_KEY": "0x8f2b1c0a77d94e3fa5c1b2e3d4f50617", "MIBAND6_ADDRESS": "AB-CD",
                   "MIBAND6_PROTOCOL": "2021", "EMPTY": ""}


def test_load_env_does_not_override(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text(f"{ENV_KEY}={KEY}\nOTHER=1\n")
    monkeypatch.setenv("OTHER", "keep")
    monkeypatch.delenv(ENV_KEY, raising=False)
    assert load_env(p) == p
    assert os.environ[ENV_KEY] == KEY and os.environ["OTHER"] == "keep"


def test_write_env_value_replaces_line(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# đầu\nMIBAND6_AUTH_KEY=old\nX=1\n")
    write_env_value(p, ENV_KEY, KEY)
    assert p.read_text() == f"# đầu\nMIBAND6_AUTH_KEY={KEY}\nX=1\n"
    assert oct(p.stat().st_mode)[-3:] == "600"


async def test_server_uses_env_key_and_never_exposes_it(tmp_path):
    store = Store(tmp_path / "cfg.json")
    service = BandService(store, demo=True, env_key="0x" + KEY.upper())
    async with TestClient(TestServer(build_app(service), host="127.0.0.1")) as c:
        st = (await (await c.get("/api/state")).json())["state"]
        assert st["env_key"] is True
        r = await c.post("/api/scan", data="{}", headers=JSON)
        addr = (await r.json())["devices"][0]["address"]
        r = await c.post("/api/connect", data=json.dumps({"address": addr, "key": ""}), headers=JSON)
        assert r.status == 200, await r.text()
        body = await r.text()
        assert KEY not in body.lower()
        saved = json.loads((tmp_path / "cfg.json").read_text())
        assert saved["devices"][addr]["auth_key"] == ""   # key trong .env không bị chép vào config.json


async def test_server_requires_key_without_env(tmp_path):
    service = BandService(Store(tmp_path / "cfg.json"), demo=True)
    async with TestClient(TestServer(build_app(service), host="127.0.0.1")) as c:
        r = await c.post("/api/connect", data=json.dumps({"address": "x", "key": ""}), headers=JSON)
        assert r.status == 400 and ".env" in (await r.json())["error"]
