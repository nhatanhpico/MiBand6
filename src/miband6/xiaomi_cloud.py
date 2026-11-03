"""Đăng nhập tài khoản Xiaomi và gọi API đám mây của Mi Fitness (chỉ đọc).

Dùng cho: lấy auth key (tools/mifitness_key.py) và đồng bộ hồ sơ người dùng vào vòng tay (server web).
Tham khảo giao thức: huami-token (MIT), Xiaomi-cloud-tokens-extractor (MIT), ghi chú của mifit (MIT).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

from .i18n import tr

SID = "miothealth"  # dịch vụ của Mi Fitness
ACCOUNT = "https://account.xiaomi.com"
UA = (
    "Mozilla/5.0 (Linux; Android 12; Pixel 4 Build/SP1A.210812.016.C1; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.200 Mobile Safari/537.36"
)
APP_UA = "Android-12-9.8.348i-google-Pixel 4"
HEALTH_PATH = "/app/v1/source/get_source_list"
# Tài khoản Việt Nam nằm ở cụm Singapore ("sg"); máy chủ gốc và các vùng khác để dự phòng.
REGIONS = ["sg", "", "de", "us", "i2", "ru", "in"]
KEY_FIELDS = ["encrypt_key", "encryptKey", "auth_key", "authKey", "huamiAuthKey", "token"]
HEX32 = re.compile(r"^(?:0x)?([0-9a-fA-F]{32})$")
ENV_SESSION = "MIBAND6_XIAOMI_SESSION"   # phiên đăng nhập lưu thêm trong .env (nếu dùng .env)
ENV_FILE: Path | None = None              # server đặt khi khởi động: tệp .env đang dùng


class LoginError(Exception):
    pass


class SessionExpired(LoginError):
    """Phiên đăng nhập đã lưu không còn được máy chủ chấp nhận."""


# ============================================================ mật mã API Mi Fitness


def rc4(key: bytes, data: bytes, drop: int = 1024) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray(len(data))
    for n in range(-drop, len(data)):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        if n >= 0:
            out[n] = data[n] ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


class RC4Stream:
    """RC4 bỏ 1024 byte đầu, giữ trạng thái giữa các lần mã hóa (kiểu 'stream' của huami-token)."""

    def __init__(self, key: bytes):
        self.s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + self.s[i] + key[i % len(key)]) & 0xFF
            self.s[i], self.s[j] = self.s[j], self.s[i]
        self.i = self.j = 0
        self.crypt(bytes(1024))

    def crypt(self, data: bytes) -> bytes:
        s, out = self.s, bytearray(len(data))
        for n, b in enumerate(data):
            self.i = (self.i + 1) & 0xFF
            self.j = (self.j + s[self.i]) & 0xFF
            s[self.i], s[self.j] = s[self.j], s[self.i]
            out[n] = b ^ s[(s[self.i] + s[self.j]) & 0xFF]
        return bytes(out)


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def make_nonce() -> str:
    return b64(secrets.token_bytes(8) + struct.pack(">i", int(time.time() * 1000) // 60000))


def signed_nonce(ssecurity: str, nonce: str) -> str:
    return b64(hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce)).digest())


def sha1_sign(method: str, path: str, params: list[tuple[str, str]], key: str) -> str:
    parts = [method.upper(), path, *(f"{k}={v}" for k, v in params), key]
    return b64(hashlib.sha1("&".join(parts).encode()).digest())


def stream_params(path: str, plain: dict[str, str], ssecurity: str, nonce: str, method: str = "POST") -> dict[str, str]:
    """Tham số mã hóa kiểu huami-token: một dòng RC4 liên tục qua các giá trị đã sắp xếp."""
    key = signed_nonce(ssecurity, nonce)
    items = dict(sorted(plain.items()))
    items["rc4_hash__"] = sha1_sign(method, path, sorted(items.items()), key)
    cipher = RC4Stream(base64.b64decode(key))
    enc = {k: b64(cipher.crypt(items[k].encode())) for k in sorted(items)}
    enc["signature"] = sha1_sign(method, path, sorted(enc.items()), key)
    enc["_nonce"] = nonce
    return enc


def mihome_params(path: str, plain: dict[str, str], ssecurity: str, nonce: str, method: str = "POST") -> dict[str, str]:
    """Tham số mã hóa kiểu Mi Home: mỗi giá trị một dòng RC4 riêng, giữ thứ tự chèn."""
    key = signed_nonce(ssecurity, nonce)
    items = dict(plain)
    items["rc4_hash__"] = sha1_sign(method, path, list(items.items()), key)
    enc = {k: b64(rc4(base64.b64decode(key), v.encode())) for k, v in items.items()}
    enc["signature"] = sha1_sign(method, path, list(enc.items()), key)
    enc["ssecurity"] = ssecurity
    enc["_nonce"] = nonce
    return enc


def decrypt_body(body: str, ssecurity: str, nonce: str) -> dict:
    raw = rc4(base64.b64decode(signed_nonce(ssecurity, nonce)), base64.b64decode(body.strip().strip('"')))
    return json.loads(raw.decode("utf-8"))


# ============================================================ đăng nhập Xiaomi


def parse_json(text: str) -> dict:
    prefix = "&&&START&&&"
    if text.startswith(prefix):
        text = text[len(prefix):]
    try:
        return json.loads(text)
    except ValueError as e:
        raise LoginError(tr('Xiaomi trả về dữ liệu không đọc được: {text}', text=repr(text[:120]))) from e


def with_client_sign(location: str, nonce, ssecurity: str) -> str:
    """Thêm clientSign = base64(SHA1('nonce=<nonce>&<ssecurity>')) như app Xiaomi."""
    if nonce is None or "clientSign=" in location:
        return location
    sign = b64(hashlib.sha1(f"nonce={nonce}&{ssecurity}".encode()).digest())
    sep = "&" if "?" in location else "?"
    return f"{location}{sep}clientSign={urllib.parse.quote(sign)}"


def open_file(path: Path) -> None:
    opener = {"darwin": ["open"], "win32": ["cmd", "/c", "start", ""]}.get(sys.platform, ["xdg-open"])
    try:
        subprocess.Popen([*opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def cache_path() -> Path:
    base = Path.home() / ("Library/Caches" if sys.platform == "darwin" else ".cache")
    return base / "MiBand6Manager" / "xiaomi-session.json"


class XiaomiLogin:
    def __init__(self, seed: str | None = None):
        import requests

        self.requests = requests
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.5"})
        self.device_id = "an_" + hashlib.md5((seed or secrets.token_hex(8)).encode()).hexdigest()
        for dom in ("xiaomi.com", "mi.com"):
            self.s.cookies.set("deviceId", self.device_id, domain=dom)
        self.ssecurity: str | None = None
        self.service_token: str | None = None
        self.user_id: str | None = None
        self.c_user_id: str | None = None
        self.pass_token: str | None = None   # để đổi lấy serviceToken mới khi token cũ hết hạn, không cần quét QR
        self._renewed = False

    # ---------------------------------------------------- lưu phiên để khỏi quét lại
    def _session_data(self) -> dict:
        return dict(ssecurity=self.ssecurity, service_token=self.service_token, user_id=self.user_id,
                    c_user_id=self.c_user_id, pass_token=self.pass_token, device_id=self.device_id, saved=time.time())

    def save(self) -> None:
        """Lưu phiên (chỉ tài khoản của bạn đọc được): tệp trong thư mục cache, và trong .env nếu đang dùng .env."""
        data = self._session_data()
        p = cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
        os.chmod(p, 0o600)
        encoded = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
        os.environ[ENV_SESSION] = encoded
        if ENV_FILE is not None:
            from .envfile import write_env_value

            try:
                write_env_value(ENV_FILE, ENV_SESSION, encoded)
            except OSError:
                pass

    def load(self) -> bool:
        """Phiên đã lưu (tệp cache, nếu không có thì từ biến môi trường / .env). Không giới hạn tuổi: token
        bị từ chối thì request() tự đổi passToken lấy token mới, không được thì mới phải đăng nhập lại."""
        d = None
        try:
            d = json.loads(cache_path().read_text())
        except (OSError, ValueError):
            raw = os.environ.get(ENV_SESSION)
            if raw:
                try:
                    d = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
                except (ValueError, TypeError):
                    d = None
        if not isinstance(d, dict) or not d.get("service_token") or not d.get("ssecurity"):
            return False
        self.ssecurity, self.service_token = d["ssecurity"], d["service_token"]
        self.user_id, self.c_user_id = d.get("user_id"), d.get("c_user_id")
        self.pass_token = d.get("pass_token")
        if d.get("device_id"):
            self.device_id = d["device_id"]
            for dom in ("xiaomi.com", "mi.com"):
                self.s.cookies.set("deviceId", self.device_id, domain=dom)
        return True

    @staticmethod
    def forget() -> None:
        """Đăng xuất: xóa phiên ở tệp cache và trong .env."""
        try:
            cache_path().unlink()
        except OSError:
            pass
        os.environ.pop(ENV_SESSION, None)
        if ENV_FILE is not None and ENV_FILE.is_file():
            from .envfile import write_env_value

            try:
                write_env_value(ENV_FILE, ENV_SESSION, "")
            except OSError:
                pass

    def renew(self) -> bool:
        """Đổi passToken lấy serviceToken mới (như app Mi Fitness làm khi token bị từ chối), không cần quét QR.

        Theo mô tả của dự án mifit: GET serviceLogin kèm cookie userId, passToken, deviceId; kết quả giống lúc
        quét QR xong (ssecurity, location) rồi lấy serviceToken ở location. Lưu lại phiên mới nếu thành công."""
        if getattr(self, "_renewed", False) or not (getattr(self, "pass_token", None) and self.user_id):
            return False
        self._renewed = True
        try:
            r = self.requests.get(f"{ACCOUNT}/pass/serviceLogin", params={"sid": SID, "_json": "true"},
                                  cookies={"userId": str(self.user_id), "passToken": self.pass_token,
                                           "deviceId": self.device_id},
                                  headers={"User-Agent": UA}, allow_redirects=False, timeout=20)
            data = parse_json(r.text)
            if not data.get("ssecurity") or not data.get("location"):
                return False
            self.pass_token = data.get("passToken") or self.pass_token
            self._finish(data)
        except (LoginError, self.requests.exceptions.RequestException):
            return False
        self.save()
        return True

    # ---------------------------------------------------- chung
    def _cookie(self, name: str, prefer: str = "io.mi.com") -> str | None:
        found = [c for c in self.s.cookies if c.name == name and c.value]
        found.sort(key=lambda c: prefer not in (c.domain or ""))
        return found[0].value if found else None

    def _service_login(self) -> dict:
        r = self.s.get(f"{ACCOUNT}/pass/serviceLogin", params={"_json": "true", "sid": SID, "_locale": "en_US"})
        d = parse_json(r.text)
        if not (d.get("_sign") and d.get("qs") and d.get("callback")):
            raise LoginError(tr('Không lấy được tham số đăng nhập (mã {code}).', code=d.get('code')))
        return d

    def _finish(self, data: dict) -> None:
        self.pass_token = data.get("passToken") or self.pass_token
        self.ssecurity = data.get("ssecurity")
        self.user_id = str(data.get("userId") or "") or None
        self.c_user_id = data.get("cUserId")
        location = data.get("location")
        if not self.ssecurity or not location:
            raise LoginError(tr('Xiaomi không trả về khóa phiên (ssecurity).'))
        self._fetch_service_token(location, data.get("nonce"))

    def _fetch_service_token(self, location: str, nonce=None) -> None:
        # Thử như app (không clientSign) trước, rồi có clientSign.
        for url in dict.fromkeys([location, with_client_sign(location, nonce, self.ssecurity or "")]):
            self.s.get(url, allow_redirects=True)
            self.service_token = self._cookie("serviceToken")
            if self.service_token:
                break
        self.c_user_id = self.c_user_id or self._cookie("cUserId")
        self.user_id = self.user_id or self._cookie("userId")
        self.pass_token = self.pass_token or self._cookie("passToken", prefer="account.xiaomi.com")
        if not self.service_token:
            raise LoginError(tr('Không nhận được serviceToken sau khi đăng nhập.'))
        if not self.c_user_id:
            raise LoginError(tr('Không nhận được cUserId sau khi đăng nhập.'))

    # ---------------------------------------------------- QR / trình duyệt
    def start_qr(self) -> dict:
        """Xin mã QR đăng nhập. Trả về qr (ảnh PNG), login_url, lp (địa chỉ chờ), timeout (giây)."""
        d = self._service_login()
        r = self.s.get(
            f"{ACCOUNT}/longPolling/loginUrl",
            params={
                "_qrsize": "480", "qs": d["qs"], "callback": d["callback"], "_hasLogo": "false",
                "sid": SID, "serviceParam": "", "_locale": "vi_VN", "_dc": str(int(time.time() * 1000)),
            },
            timeout=20,
        )
        q = parse_json(r.text)
        if not q.get("qr") or not q.get("lp"):
            raise LoginError(tr('Không tạo được mã QR đăng nhập (mã {code}).', code=q.get("code")))
        return {"qr": self.s.get(q["qr"], timeout=20).content, "login_url": q.get("loginUrl", ""),
                "lp": q["lp"], "timeout": float(q.get("timeout") or 300)}

    def wait_qr(self, q: dict, timeout: float | None = None, cancel: threading.Event | None = None) -> None:
        """Chờ người dùng quét mã QR và đăng nhập, rồi lấy serviceToken."""
        deadline = time.time() + (timeout or q["timeout"])
        while True:
            if cancel is not None and cancel.is_set():
                raise LoginError(tr('Đã hủy đăng nhập.'))
            if time.time() > deadline:
                raise LoginError(tr('Hết thời gian chờ quét mã QR.'))
            try:
                r = self.s.get(q["lp"], timeout=min(10, max(1, deadline - time.time())))
            except self.requests.exceptions.Timeout:
                continue
            if r.status_code == 200:
                break
            time.sleep(1)
        self._finish(parse_json(r.text))

    def login_qr(self, timeout: float | None = None) -> None:
        q = self.start_qr()
        qr_path = Path(tempfile.gettempdir()) / "xiaomi-login-qr.png"
        qr_path.write_bytes(q["qr"])
        open_file(qr_path)
        print("Đăng nhập tài khoản Xiaomi (tài khoản dùng trong Mi Fitness) bằng MỘT trong hai cách:\n")
        print("  1. Quét mã QR vừa mở (ảnh lưu tại", qr_path, ")")
        print("     bằng camera điện thoại, rồi đăng nhập trên trang hiện ra.")
        print("  2. Hoặc mở đường dẫn này trong trình duyệt và đăng nhập:")
        print("     " + q["login_url"])
        print("\nNếu Xiaomi hỏi mã xác minh hay bắt xác nhận đăng nhập, cứ làm theo trên trang đó.")
        wait = timeout or q["timeout"]
        shown = f"{int(wait // 60)} phút" if wait >= 60 else f"{int(wait)} giây"
        print(f"Đang chờ đăng nhập (tối đa {shown})…", flush=True)
        self.wait_qr(q, wait)

    # ---------------------------------------------------- mật khẩu (+ xác minh 2 bước)
    def login_password(self, user: str, password: str) -> None:
        d = self._service_login()
        payload = {
            "qs": d["qs"], "callback": d["callback"], "_json": "true", "_sign": d["_sign"], "user": user,
            "hash": hashlib.md5(password.encode()).hexdigest().upper(), "sid": SID, "_locale": "en_US",
        }
        url = f"{ACCOUNT}/pass/serviceLoginAuth2"
        resp = parse_json(self.s.post(url, data=payload).text)
        if resp.get("captchaUrl"):
            payload["captCode"] = self._ask_captcha(resp["captchaUrl"])
            resp = parse_json(self.s.post(url, data=payload).text)
            if resp.get("code") == 87001:
                raise LoginError("Mã captcha sai.")
        code = resp.get("code")
        if code == 70016:
            raise LoginError("Sai tài khoản hoặc mật khẩu.")
        if code not in (0, None):
            raise LoginError(f"Xiaomi từ chối đăng nhập: {resp.get('description') or resp.get('desc') or code}")
        if resp.get("ssecurity") and resp.get("location"):
            self._finish(resp)
        elif resp.get("notificationUrl"):
            self._two_factor(resp["notificationUrl"])
        else:
            raise LoginError("Xiaomi không trả về khóa phiên. Thử đăng nhập bằng QR (chạy không kèm --password).")

    def _ask_captcha(self, captcha_url: str) -> str:
        if captcha_url.startswith("/"):
            captcha_url = ACCOUNT + captcha_url
        path = Path(tempfile.gettempdir()) / "xiaomi-captcha.png"
        path.write_bytes(self.s.get(captcha_url).content)
        open_file(path)
        print(f"Xiaomi yêu cầu captcha (ảnh đã mở, lưu tại {path}).")
        return input("Nhập chữ trong ảnh (phân biệt hoa thường): ").strip()

    def _two_factor(self, notification_url: str) -> None:
        print("Xiaomi yêu cầu xác minh 2 bước cho lần đăng nhập này.")
        self.s.get(notification_url)
        context = urllib.parse.parse_qs(urllib.parse.urlparse(notification_url).query)["context"][0]
        base = {"sid": SID, "context": context, "_locale": "en_US"}
        options: list[int] = []
        try:
            info = parse_json(self.s.get(f"{ACCOUNT}/identity/list", params=base).text)
            options = [int(o) for o in info.get("options") or []]
        except (LoginError, ValueError, TypeError):
            pass
        kind = "Email"
        if 4 in options and 8 not in options:
            kind = "Phone"
        elif 4 in options and 8 in options:
            choice = input("Gửi mã xác minh qua (1) email hay (2) tin nhắn SMS? [1]: ").strip()
            kind = "Phone" if choice == "2" else "Email"
        flag = "8" if kind == "Email" else "4"
        ick = self._cookie("ick", prefer="xiaomi.com") or ""
        r = self.s.post(
            f"{ACCOUNT}/identity/auth/send{kind}Ticket",
            params={**base, "_dc": str(int(time.time() * 1000)), "mask": "0"},
            data={"retry": "0", "icode": "", "_json": "true", "ick": ick},
        )
        try:
            sent = parse_json(r.text)
            if sent.get("code") not in (0, None):
                print("  Xiaomi báo:", sent.get("tips") or sent.get("description") or sent.get("code"))
        except LoginError:
            pass
        where = "email" if kind == "Email" else "điện thoại"
        ticket = input(f"Nhập mã xác minh Xiaomi vừa gửi tới {where} của bạn: ").strip()
        r = self.s.post(
            f"{ACCOUNT}/identity/auth/verify{kind}",
            params={**base, "_flag": flag, "_json": "true", "mask": "0"},
            data={"_flag": flag, "ticket": ticket, "trust": "true", "_json": "true", "ick": ick},
        )
        if r.status_code != 200:
            raise LoginError(f"Xác minh thất bại (HTTP {r.status_code}).")
        finish = None
        try:
            v = parse_json(r.text)
            if v.get("code") not in (0, None):
                raise LoginError(f"Mã xác minh không đúng: {v.get('tips') or v.get('description') or v.get('code')}")
            finish = v.get("location")
        except LoginError as e:
            if "không đúng" in str(e):
                raise
            m = re.search(r"https://account\.xiaomi\.com/identity/result/check\?[^\"']+", r.text)
            finish = r.headers.get("Location") or (m.group(0) if m else None)
        if not finish:
            finish = self.s.get(f"{ACCOUNT}/identity/result/check", params=base, allow_redirects=False).headers.get("Location")
        if not finish:
            raise LoginError("Không hoàn tất được bước xác minh. Thử đăng nhập bằng QR.")
        end_url = finish
        if "identity/result/check" in finish:
            end_url = self.s.get(finish, allow_redirects=False).headers.get("Location") or ""
        if not end_url:
            raise LoginError("Không tìm thấy bước kết thúc đăng nhập. Thử đăng nhập bằng QR.")
        r = self.s.get(end_url, allow_redirects=False)
        if r.status_code == 200 and "Tips" in r.text:
            r = self.s.get(end_url, allow_redirects=False)
        try:
            pragma = json.loads(r.headers.get("extension-pragma") or "{}")
        except ValueError:
            pragma = {}
        self.ssecurity = pragma.get("ssecurity")
        if not self.ssecurity:
            raise LoginError("Xiaomi không trả về khóa phiên sau xác minh. Thử đăng nhập bằng QR.")
        sts = r.headers.get("Location")
        if not sts:
            m = re.search(r"https://sts[^\"'\s]+", r.text)
            sts = m.group(0) if m else None
        if not sts:
            raise LoginError("Không tìm thấy địa chỉ lấy serviceToken. Thử đăng nhập bằng QR.")
        self._fetch_service_token(sts, pragma.get("nonce"))

    # ---------------------------------------------------- gọi API Mi Fitness
    def request(self, host: str, path: str, plain: dict[str, str] | None = None, *, method: str = "POST",
                sign_path: str | None = None, variant: str = "stream", region: str = "sg") -> tuple[int, dict | None]:
        """Gọi một API của Mi Fitness. Trả về (mã HTTP, nội dung đã giải mã hoặc None)."""
        nonce = make_nonce()
        build = stream_params if variant == "stream" else mihome_params
        params = build(sign_path or path, dict(plain or {}), self.ssecurity, nonce, method)
        url = f"https://{host}{path}"
        if variant == "stream":
            cookies = {"cUserId": self.c_user_id, "serviceToken": self.service_token, "locale": "en_us"}
            headers = {"User-Agent": APP_UA, "Accept-Encoding": "gzip", "region_tag": region or "sg"}
        else:
            cookies = {"userId": str(self.user_id or ""), "cUserId": self.c_user_id, "serviceToken": self.service_token,
                       "yetAnotherServiceToken": self.service_token, "locale": "en_GB", "channel": "MI_APP_STORE"}
            headers = {"User-Agent": APP_UA, "Accept-Encoding": "identity", "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4"}
        if method == "GET":
            r = self.requests.get(url, params=params, cookies=cookies, headers=headers, timeout=20)
        elif variant == "stream":
            r = self.requests.post(url, data=params, cookies=cookies, headers=headers, timeout=20)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = self.requests.post(url, params=params, cookies=cookies, headers=headers, timeout=20)
        if r.status_code == 401 and self.renew():
            # token hết hạn: đã đổi passToken lấy token mới, gửi lại một lần (ký lại bằng khóa phiên mới)
            return self.request(host, path, plain, method=method, sign_path=sign_path, variant=variant, region=region)
        if r.status_code != 200:
            return r.status_code, None
        try:
            return 200, decrypt_body(r.text, self.ssecurity, nonce)
        except (ValueError, UnicodeDecodeError):
            try:
                return 200, json.loads(r.text)
            except ValueError:
                return 200, None

    def call_health(self, host: str, variant: str, region: str) -> tuple[int, dict | None]:
        plain = {"data": json.dumps({"page_size": 50, "status": 1}, separators=(",", ":"))}
        return self.request(host, HEALTH_PATH, plain, variant=variant, region=region)


# ============================================================ phân tích danh sách thiết bị


def _key_of(value) -> str | None:
    if isinstance(value, str):
        m = HEX32.match(value.strip())
        if m:
            return m.group(1).lower()
    return None


def device_from_record(rec: dict) -> list[dict]:
    """Một bản ghi thiết bị (cloud hoặc tệp iPhone) → các key 32 hex tìm được trong đó."""
    detail = rec.get("detail") or {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            detail = {}
    if not isinstance(detail, dict):
        detail = {}
    out, seen = [], set()
    for src in (detail, rec):
        for f in KEY_FIELDS:
            k = _key_of(src.get(f))
            if k and k not in seen:
                seen.add(k)
                out.append({
                    "name": str(rec.get("name") or detail.get("name") or "Không rõ").strip(),
                    "model": str(rec.get("model") or detail.get("model") or ""),
                    "mac": str(detail.get("mac") or rec.get("mac") or rec.get("randomMac") or ""),
                    "key": k,
                    "field": f,
                })
    return out


def parse_source_list(res: dict | None) -> list[dict]:
    out = []
    for src in ((res or {}).get("result") or {}).get("list") or []:
        if isinstance(src, dict):
            out += device_from_record(src)
    return out


def describe_source(src: dict) -> str:
    """Mô tả một bản ghi thiết bị chỉ bằng tên trường (không in giá trị, trừ tên/model)."""
    detail = src.get("detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            detail = {"<chuỗi>": len(detail)}
    dk = sorted(detail.keys()) if isinstance(detail, dict) else []
    return (f"{str(src.get('name', '?')).strip()} [{src.get('model', '')}] "
            f"trường: {', '.join(sorted(k for k in src if k != 'detail'))}; detail: {', '.join(dk) or '—'}")


def fetch_devices(login: XiaomiLogin, regions: list[str]) -> tuple[list[dict], list[str], bool]:
    """Trả về (thiết bị, nhật ký từng lần gọi, có máy chủ nào trả code 0 không)."""
    trail: list[str] = []
    answered = False
    variants = ["stream", "mihome"]
    for region in regions:
        host = f"{region}.hlth.io.mi.com" if region else "hlth.io.mi.com"
        for variant in variants:
            try:
                status, res = login.call_health(host, variant, region)
            except login.requests.exceptions.RequestException as e:
                trail.append(f"{host} ({variant}): lỗi mạng {type(e).__name__}")
                continue
            if res is None:
                trail.append(f"{host} ({variant}): HTTP {status}")
                continue
            code = res.get("code")
            if code != 0:
                trail.append(f"{host} ({variant}): HTTP 200, mã {code} {str(res.get('message') or '')[:60]}")
                continue
            answered = True
            raw_list = [x for x in ((res.get("result") or {}).get("list") or []) if isinstance(x, dict)]
            devices = parse_source_list(res)
            trail.append(f"{host} ({variant}): HTTP 200, mã 0, {len(raw_list)} thiết bị")
            for src in raw_list:
                trail.append("      " + describe_source(src))
            variants = [variant]  # kiểu mã hóa đã được chấp nhận
            if devices:
                return devices, trail, answered
            break
    return [], trail, answered


# ============================================================ hồ sơ người dùng

PROFILE_PATH = "/healthapp/user/get_miot_user_profile"
# Đường dẫn dùng để ký: app Mi Fitness bỏ tiền tố "healthapp" (giữ dấu "/"); thử cả đường dẫn đầy đủ để dự phòng.
PROFILE_ATTEMPTS = [
    ("GET", "/user/get_miot_user_profile"),
    ("POST", "/user/get_miot_user_profile"),
    ("GET", PROFILE_PATH),
    ("POST", PROFILE_PATH),
]
PROFILE_FIELDS = ("height", "weight", "birth", "sex", "daily_step_goal", "regular_goal_list")


def _looks_like_profile(res: dict | None) -> bool:
    return bool(res) and res.get("code") == 0 and isinstance(res.get("result"), dict) \
        and any(k in res["result"] for k in PROFILE_FIELDS)


def fetch_profile(login: XiaomiLogin, regions: list[str] | None = None) -> tuple[dict | None, list[str]]:
    """Đọc hồ sơ (chiều cao, cân nặng, ngày sinh, giới tính, mục tiêu) từ tài khoản Mi Fitness.

    Trả về (hồ sơ hoặc None, nhật ký từng lần gọi). Ném SessionExpired nếu mọi lần gọi ở vùng đầu
    tiên đều bị từ chối vì phiên đăng nhập (HTTP 401).
    """
    trail: list[str] = []
    for n, region in enumerate(regions or REGIONS):
        host = f"{region}.hlth.io.mi.com" if region else "hlth.io.mi.com"
        statuses = []
        for variant in ("stream", "mihome"):
            for method, sign_path in PROFILE_ATTEMPTS:
                try:
                    status, res = login.request(host, PROFILE_PATH, None, method=method, sign_path=sign_path,
                                                variant=variant, region=region)
                except login.requests.exceptions.RequestException as e:
                    trail.append(f"{host} {method} {sign_path} ({variant}): {type(e).__name__}")
                    statuses.append(0)
                    continue
                statuses.append(status)
                if _looks_like_profile(res):
                    trail.append(f"{host} {method} {sign_path} ({variant}): OK")
                    return res["result"], trail
                detail = f"HTTP {status}" if res is None else f"code {res.get('code')} {str(res.get('message') or '')[:50]}"
                trail.append(f"{host} {method} {sign_path} ({variant}): {detail}")
        if n == 0 and statuses and all(s == 401 for s in statuses):
            raise SessionExpired(tr('Phiên đăng nhập Xiaomi đã hết hạn.'))
    return None, trail


SPORT_RECORDS_PATH = "/app/v1/data/get_sport_records_by_time"


def fetch_sport_records(login: XiaomiLogin, start_s: int, end_s: int, regions: list[str] | None = None,
                        max_pages: int = 60) -> tuple[list[dict], list[str]]:
    """Các buổi tập lưu trên tài khoản Mi Fitness bắt đầu trong [start_s, end_s] (mới tới cũ).

    Mỗi phần tử là trường "value" đã giải mã của một bản ghi. Định dạng yêu cầu theo mô tả của dự án mifit
    (GET ký như các API khác, phân trang bằng next_key). Ném SessionExpired nếu vùng đầu tiên trả 401."""
    trail: list[str] = []
    for n, region in enumerate(regions or REGIONS):
        host = f"{region}.hlth.io.mi.com" if region else "hlth.io.mi.com"
        records: list[dict] = []
        next_key = None
        answered = False
        for page in range(max_pages):
            req = {"start_time": start_s - 1, "end_time": end_s, "reverse": True, "limit": 50}
            if next_key:
                req["next_key"] = next_key
            try:
                status, res = login.request(host, SPORT_RECORDS_PATH, {"data": json.dumps(req, separators=(",", ":"))},
                                            method="GET", region=region)
            except login.requests.exceptions.RequestException as e:
                trail.append(f"{host} {SPORT_RECORDS_PATH}: {type(e).__name__}")
                break
            if status == 401 and n == 0 and page == 0:
                raise SessionExpired(tr('Phiên đăng nhập Xiaomi đã hết hạn.'))
            if not isinstance(res, dict) or res.get("code", 0) != 0:
                detail = f"HTTP {status}" if res is None else f"code {res.get('code')} {str(res.get('message') or '')[:50]}"
                trail.append(f"{host} {SPORT_RECORDS_PATH}: {detail}")
                break
            answered = True
            body = res["result"] if isinstance(res.get("result"), dict) else res
            for entry in body.get("sport_records") or []:
                if not isinstance(entry, dict) or entry.get("deleted"):
                    continue
                value = entry.get("value")
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        continue
                if isinstance(value, dict):
                    # mã nguồn (sid) và vùng máy chủ: cần để tải lộ trình GPS; chỉ lưu trên máy
                    records.append({**value, "_sid": entry.get("sid"), "_region": region})
            if not body.get("has_more") or not body.get("next_key") or body.get("next_key") == next_key:
                break
            next_key = body["next_key"]
        if answered:
            trail.append(f"{host} {SPORT_RECORDS_PATH}: {len(records)}")
        if records:
            return records, trail
    return [], trail


GPS_LINK_PATH = "/healthapp/service/gen_download_url"
GPS_LINK_SIGN = "/service/gen_download_url"
FDS_IV = b"1234567887654321"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    core = text.strip().rstrip("=")
    return base64.urlsafe_b64decode(core + "=" * (-len(core) % 4))


def gps_file_suffix(sid: str, report_time: int, tz15: int, proto: int, file_type: int = 2) -> str:
    """Tên tệp chi tiết buổi tập trên máy chủ: base64url(thời điểm, múi giờ, kiểu) _ base64url(sha1(sid))."""
    flags = ((1 << 7) + (proto << 2) + file_type) & 0xFF
    key = struct.pack("<Ib", report_time, tz15) + bytes([flags])
    return f"{_b64url(key)}_{_b64url(hashlib.sha1(sid.encode('utf-8')).digest())}"


def decrypt_fds(body: bytes, key_b64: str) -> bytes:
    """Giải mã tệp tải từ kho tệp của Xiaomi: base64url (có thể nằm trong chuỗi JSON), AES-CBC, IV cố định."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    text = body.decode("ascii").strip()
    if text.startswith('"'):
        text = json.loads(text)
    data = _b64url_decode(text)
    key = _b64url_decode(key_b64)
    if not data or len(data) % 16 or len(key) not in (16, 24, 32):
        raise ValueError(tr('Tệp lộ trình không giải mã được.'))
    dec = Cipher(algorithms.AES(key), modes.CBC(FDS_IV)).decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def fetch_gps_file(login: XiaomiLogin, sid: str, report_time: int, tz15: int, proto: int,
                   region: str = "sg") -> bytes | None:
    """Tệp lộ trình GPS (đã giải mã) của một buổi tập trong tài khoản Mi Fitness; None nếu buổi đó không có.

    Cách gọi theo mô tả của dự án mifit: một yêu cầu ký lấy đường dẫn tải và khóa, rồi tải tệp (không kèm
    cookie). Ném SessionExpired nếu phiên đăng nhập hết hạn."""
    suffix = gps_file_suffix(sid, report_time, tz15, proto)
    host = f"{region}.hlth.io.mi.com" if region else "hlth.io.mi.com"
    data = {"did": sid, "items": [{"timestamp": report_time, "suffix": suffix}]}
    status, res = login.request(host, GPS_LINK_PATH, {"data": json.dumps(data, separators=(",", ":"))},
                                method="GET", sign_path=GPS_LINK_SIGN, region=region)
    if status == 401:
        raise SessionExpired(tr('Phiên đăng nhập Xiaomi đã hết hạn.'))
    if not isinstance(res, dict) or res.get("code", 0) != 0 or not isinstance(res.get("result"), dict):
        detail = f"HTTP {status}" if res is None else f"code {res.get('code')}"
        raise LoginError(tr('Máy chủ Mi Fitness không trả đường dẫn tải lộ trình ({detail}).', detail=detail))
    entry = res["result"].get(f"{suffix}_{report_time}")
    if not isinstance(entry, dict) or not entry.get("obj_key") or not isinstance(entry.get("url"), str):
        return None   # buổi tập không có tệp lộ trình
    r = login.requests.get(entry["url"], timeout=30, allow_redirects=False)
    if r.status_code != 200:
        raise LoginError(tr('Không tải được tệp lộ trình (HTTP {status}).', status=r.status_code))
    return decrypt_fds(r.content, entry["obj_key"])


def _date(value) -> dt.date | None:
    if isinstance(value, (int, float)) and value > 0:
        if 19000101 <= value <= 21001231:  # dạng yyyymmdd
            value = str(int(value))
        else:
            try:
                return dt.datetime.fromtimestamp(value / 1000 if value > 1e11 else value).date()
            except (OverflowError, OSError, ValueError):
                return None
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d{4})[-/.]?(\d{1,2})(?:[-/.]?(\d{1,2}))?", value)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def _number(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def profile_for_band(raw: dict) -> dict:
    """Hồ sơ Mi Fitness → giá trị cho vòng tay: alias, birth, gender, height, weight, goal (chỉ trường hợp lệ)."""
    out: dict = {}
    # trường "name" của hồ sơ sức khỏe thường là mã tài khoản Xiaomi (dãy số) khi người dùng chưa đặt tên:
    # ưu tiên biệt danh, và không bao giờ dùng một dãy số làm tên
    for key in ("nickname", "nick_name", "nickName", "name"):
        name = str(raw.get(key) or "").strip()
        if name and not name.isdigit():
            out["alias"] = name[:32]
            break
    birth = _date(raw.get("birth") or raw.get("birthday"))
    if birth and dt.date(1900, 1, 1) <= birth <= dt.date.today():
        out["birth"] = birth.isoformat()
    sex = str(raw.get("sex") if raw.get("sex") is not None else raw.get("gender", "")).strip().lower()
    gender = {"male": 0, "m": 0, "man": 0, "female": 1, "f": 1, "woman": 1, "other": 2}.get(sex)
    if gender is not None:  # mã số lạ: giữ nguyên giới tính đang có
        out["gender"] = gender
    height = _number(raw.get("height"))
    if height and 100 <= height <= 230:
        out["height"] = int(round(height))
    weight = _number(raw.get("weight"))
    if weight and 20 <= weight <= 250:
        out["weight"] = round(weight, 1)
    goal = _number(raw.get("daily_step_goal"))
    if not goal:
        for g in raw.get("regular_goal_list") or []:
            if isinstance(g, dict) and str(g.get("field")) == "1":
                goal = _number(g.get("target"))
                break
    if goal and 1000 <= goal <= 60000:
        out["goal"] = int(goal)
    return out
