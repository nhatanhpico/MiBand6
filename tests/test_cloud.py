"""Đồng bộ hồ sơ từ Mi Fitness: phân tích hồ sơ, gọi API (giả lập) và luồng đăng nhập QR trên server web."""

import asyncio
import datetime as dt
import json
import threading

import pytest
from aiohttp.test_utils import TestClient, TestServer

from miband6 import protocol as P
from miband6 import xiaomi_cloud as X
from miband6.config import Store
from miband6.web.server import BandService, build_app

KEY = "8f2b1c0a77d94e3fa5c1b2e3d4f50617"
JSON = {"Content-Type": "application/json"}
RAW = {"id": 1, "name": "Nhật Anh", "birth": "1999-05-24", "sex": "male", "height": 168, "weight": 58.4,
       "daily_step_goal": 10000, "regular_goal_list": [{"field": 1, "target": 10000}]}


def test_profile_for_band_maps_fields():
    assert X.profile_for_band(RAW) == {"alias": "Nhật Anh", "birth": "1999-05-24", "gender": 0, "height": 168,
                                       "weight": 58.4, "goal": 10000}
    out = X.profile_for_band({"sex": "female", "birth": 19900102, "height": "171.6", "weight": 0,
                              "regular_goal_list": [{"field": 2, "target": 600}, {"field": 1, "target": 7000}]})
    assert out == {"birth": "1990-01-02", "gender": 1, "height": 172, "goal": 7000}
    # giá trị lạ hoặc ngoài khoảng: bỏ qua, không đoán
    assert X.profile_for_band({"sex": 1, "height": 20, "weight": 900, "birth": "abc", "daily_step_goal": 5}) == {}
    assert X.profile_for_band({"birth": "2001-07"})["birth"] == "2001-07-01"


class FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeRequests:
    """Thay cho thư viện requests: máy chủ chỉ chấp nhận GET ký bằng đường dẫn rút gọn."""

    class exceptions:  # noqa: N801
        RequestException = OSError
        Timeout = TimeoutError

    def __init__(self, login, status_other=200):
        self.login, self.calls, self.status_other = login, [], status_other

    def _answer(self, method, url, params, data):
        p = params or data
        self.calls.append((method, url, dict(p)))
        nonce = p["_nonce"]
        key = X.signed_nonce(self.login.ssecurity, nonce)
        expect = X.stream_params("/user/get_miot_user_profile", {}, self.login.ssecurity, nonce, "GET")
        if method == "GET" and p.get("signature") == expect["signature"]:
            body = json.dumps({"code": 0, "message": "ok", "result": RAW}).encode()
        else:
            if self.status_other != 200:
                return FakeResp(self.status_other)
            body = json.dumps({"code": 3, "message": "sign err"}).encode()
        import base64
        return FakeResp(200, base64.b64encode(X.rc4(base64.b64decode(key), body)).decode())

    def get(self, url, params=None, **_):
        return self._answer("GET", url, params, None)

    def post(self, url, params=None, data=None, **_):
        return self._answer("POST", url, params, data)


def make_login():
    login = X.XiaomiLogin.__new__(X.XiaomiLogin)
    import base64
    login.ssecurity = base64.b64encode(b"k" * 16).decode()
    login.service_token, login.user_id, login.c_user_id = "tok", "123", "cu"
    return login


def test_fetch_profile_finds_working_request():
    login = make_login()
    login.requests = FakeRequests(login)
    raw, trail = X.fetch_profile(login, ["sg"])
    assert raw == RAW
    method, url, params = login.requests.calls[-1]
    assert method == "GET" and url == "https://sg.hlth.io.mi.com/healthapp/user/get_miot_user_profile"
    assert set(params) == {"rc4_hash__", "signature", "_nonce"}
    assert trail[-1].endswith("OK")


def test_fetch_profile_expired_session():
    login = make_login()
    login.requests = FakeRequests(login, status_other=401)
    login.ssecurity = __import__("base64").b64encode(b"x" * 16).decode()
    login.requests.login = make_login()  # chữ ký không khớp -> mọi lần gọi đều 401
    with pytest.raises(X.SessionExpired):
        X.fetch_profile(login, ["sg", ""])


class FakeLogin:
    """Đăng nhập Xiaomi giả: không có phiên lưu sẵn, quét QR xong là đăng nhập được."""

    saved = None
    scanned = threading.Event()
    forgotten = 0

    def __init__(self):
        self.ssecurity = None

    def load(self):
        return FakeLogin.saved is not None

    def save(self):
        FakeLogin.saved = True

    @classmethod
    def forget(cls):
        cls.saved = None
        cls.forgotten += 1

    def start_qr(self):
        return {"qr": b"\x89PNG fake", "login_url": "https://account.xiaomi.com/login?x", "lp": "lp", "timeout": 60}

    def wait_qr(self, q, timeout=None, cancel=None):
        while not FakeLogin.scanned.wait(0.05):
            if cancel is not None and cancel.is_set():
                raise X.LoginError("cancelled")


@pytest.fixture
async def client(tmp_path, monkeypatch):
    FakeLogin.saved, FakeLogin.forgotten = None, 0
    FakeLogin.scanned = threading.Event()
    monkeypatch.setattr("miband6.web.cloud.fetch_profile", lambda login, regions=None: (dict(RAW), ["ok"]))
    service = BandService(Store(tmp_path / "cfg.json"), demo=True, login_factory=FakeLogin)
    service.cloud.demo = False  # dùng luồng thật với FakeLogin, vòng tay vẫn là giả lập
    async with TestClient(TestServer(build_app(service), host="127.0.0.1")) as c:
        c.service = service
        yield c


async def post(c, path, data=None):
    return await c.post(path, data=json.dumps(data or {}), headers=JSON)


async def wait_state(c, state, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        st = (await (await c.get("/api/cloud")).json())["cloud"]
        if st["state"] == state:
            return st
        await asyncio.sleep(0.03)
    raise AssertionError(f"không tới trạng thái {state}: {st}")


async def test_qr_login_then_profile_written_on_connect(client):
    r = await post(client, "/api/cloud/sync", {"write": True})
    assert r.status == 200
    st = await wait_state(client, "login")
    assert st["qr"].startswith("data:image/png;base64,") and st["url"].startswith("https://account.xiaomi.com")
    FakeLogin.scanned.set()
    st = await wait_state(client, "done")
    assert st["profile"]["height"] == 168 and "khi kết nối" in st["message"]
    assert FakeLogin.saved
    state = (await (await client.get("/api/state")).json())["state"]
    assert state["profile"]["pending_sync"] and state["profile"]["birth"] == "1999-05-24"

    # kết nối vòng tay: hồ sơ chờ được ghi ngay
    r = await post(client, "/api/scan", {})
    addr = (await r.json())["devices"][0]["address"]
    r = await post(client, "/api/connect", {"address": addr, "key": KEY, "protocol": "auto"})
    assert r.status == 200
    await asyncio.sleep(0.3)
    band = client.service.band._client
    written = [d for _u, d in band.writes]
    assert P.user_info("Nhật Anh", dt.date(1999, 5, 24), 0, 168, 58.4) in written
    assert P.fitness_goal(10000) in written
    assert "pending_sync" not in client.service.profile


async def test_saved_session_and_connected_band(client):
    r = await post(client, "/api/scan", {})
    addr = (await r.json())["devices"][0]["address"]
    await post(client, "/api/connect", {"address": addr, "key": KEY, "protocol": "auto"})
    FakeLogin.saved = True  # đã đăng nhập từ trước: không cần quét QR
    await post(client, "/api/cloud/sync", {})
    st = await wait_state(client, "done")
    assert "ghi vào vòng tay" in st["message"]
    band = client.service.band._client
    assert P.fitness_goal(10000) in [d for _u, d in band.writes]


async def test_cancel_and_relogin(client):
    await post(client, "/api/cloud/sync", {})
    await wait_state(client, "login")
    r = await post(client, "/api/cloud/cancel")
    assert (await r.json())["cloud"]["state"] == "idle"
    await asyncio.sleep(0.15)
    assert (await (await client.get("/api/cloud")).json())["cloud"]["state"] == "idle"
    FakeLogin.saved = True
    await post(client, "/api/cloud/sync", {"fresh": True})
    assert FakeLogin.forgotten == 1
    await wait_state(client, "login")  # phiên cũ bị bỏ nên phải quét lại
    await post(client, "/api/cloud/cancel")


async def test_demo_mode(tmp_path):
    service = BandService(Store(tmp_path / "cfg.json"), demo=True)
    async with TestClient(TestServer(build_app(service), host="127.0.0.1")) as c:
        await post(c, "/api/cloud/sync", {})
        st = await wait_state(c, "done")
        assert st["profile"]["goal"] == 9000


def test_profile_name_never_uses_account_id():
    assert "alias" not in X.profile_for_band({"name": "6761359519", "height": 176})
    assert X.profile_for_band({"name": "6761359519", "nickname": "nhatanh245"})["alias"] == "nhatanh245"
    assert X.profile_for_band({"name": "Nhật Anh", "nick_name": "  "})["alias"] == "Nhật Anh"



def test_session_saved_to_env_and_renewed(tmp_path, monkeypatch):
    """Phiên lưu cả trong .env; token hết hạn thì đổi passToken lấy token mới rồi gửi lại, không cần quét QR."""
    import base64

    env = tmp_path / ".env"
    env.write_text("MIBAND6_AUTH_KEY=abc\n")
    monkeypatch.setattr(X, "cache_path", lambda: tmp_path / "cache" / "session.json")
    monkeypatch.setattr(X, "ENV_FILE", env)
    monkeypatch.delenv(X.ENV_SESSION, raising=False)
    login = X.XiaomiLogin(seed="t")
    login.ssecurity, login.service_token = base64.b64encode(b"k" * 16).decode(), "tok"
    login.user_id, login.c_user_id, login.pass_token = "123", "cu", "pt"
    login.save()
    line = next(l for l in env.read_text().splitlines() if l.startswith(X.ENV_SESSION + "="))
    assert "MIBAND6_AUTH_KEY=abc" in env.read_text() and len(line) > 40
    # tệp cache bị xóa (macOS dọn cache): vẫn đọc được phiên từ .env
    (tmp_path / "cache" / "session.json").unlink()
    again = X.XiaomiLogin(seed="other")
    assert again.load() and again.pass_token == "pt" and again.device_id == login.device_id

    calls = []

    class Resp:
        def __init__(self, status, text=""):
            self.status_code, self.text = status, text

    class Requests:
        class exceptions:  # noqa: N801
            RequestException = OSError

        def get(self, url, params=None, cookies=None, **kw):
            calls.append(url)
            if "serviceLogin" in url:
                assert cookies["passToken"] == "pt" and cookies["userId"] == "123"
                return Resp(200, '&&&START&&&{"ssecurity": "%s", "location": "https://sts/x", "passToken": "pt2"}'
                            % base64.b64encode(b"n" * 16).decode())
            return Resp(401 if again.service_token == "tok" else 404)

    again.requests = Requests()

    def fake_fetch(location, nonce=None):
        again.service_token = "tok2"

    again._fetch_service_token = fake_fetch
    status, _ = again.request("sg.hlth.io.mi.com", "/app/v1/x", {"data": "{}"}, method="GET")
    assert status == 404 and again.service_token == "tok2" and again.pass_token == "pt2"
    assert sum("serviceLogin" in c for c in calls) == 1   # chỉ đổi một lần
    X.XiaomiLogin.forget()
    assert X.ENV_SESSION + "=\n" in env.read_text() and X.ENV_SESSION not in __import__("os").environ



async def test_background_cloud_sync_after_connect(tmp_path):
    """Sau khi kết nối: tự lấy buổi tập Mi Fitness ở chế độ nền; lần kết nối lại trong vòng 1 giờ thì không lấy nữa."""
    import asyncio

    import datetime

    from miband6.config import Store
    from miband6.web.server import BandService

    service = BandService(Store(tmp_path / "config.json"), demo=True)
    service.auto_health = False
    service.auto_cloud = True
    service.profile["cloud_at"] = __import__("time").time()   # hồ sơ vừa lấy: chỉ còn việc lấy buổi tập
    starts = []
    real_start = service.cloud.start

    def spy(*a, **kw):
        starts.append((kw.get("job"), kw.get("interactive"), kw.get("since")))
        return real_start(*a, **kw)

    service.cloud.start = spy
    for _ in range(2):
        await service.connect("AA:BB:CC:DD:EE:FF", "0x" + "11" * 16, "auto")
        for _ in range(100):
            await asyncio.sleep(0.05)
            if not service.cloud.running and service.health_db().last("cloud_workouts"):
                break
        await service.disconnect()
    assert starts == [("workouts", False, None)]
    db = service.health_db()
    assert db.last("cloud_workouts") and any(w.get("source") == "mifitness" for w in db.summary(datetime.date.today().isoformat())["workouts"])
