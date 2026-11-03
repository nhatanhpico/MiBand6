"""Hằng số và các hàm dựng/giải mã gói tin cho Mi Smart Band 6.

Giao thức Huami được cộng đồng dịch ngược (tham khảo: dự án Gadgetbridge).
Mọi hàm ở đây là hàm thuần (không đụng tới Bluetooth) để dễ kiểm thử.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from .i18n import tr

# ---------------------------------------------------------------------------
# UUID
# ---------------------------------------------------------------------------


def _std(short: str) -> str:
    return f"0000{short.lower()}-0000-1000-8000-00805f9b34fb"


def _huami(short: str) -> str:
    return f"0000{short.lower()}-0000-3512-2118-0009af100700"


SVC_MIBAND = _std("fee0")
SVC_MIBAND2 = _std("fee1")
SVC_HEART_RATE = _std("180d")
SVC_DEVICE_INFO = _std("180a")
SVC_ALERT_NOTIFICATION = _std("1811")
SVC_IMMEDIATE_ALERT = _std("1802")

CHAR_CONFIG = _huami("0003")
CHAR_BATTERY = _huami("0006")
CHAR_STEPS = _huami("0007")
CHAR_USER_SETTINGS = _huami("0008")
CHAR_AUTH = _huami("0009")
CHAR_DEVICE_EVENT = _huami("0010")
CHAR_CHUNKED_2021_WRITE = _huami("0016")
CHAR_CHUNKED_2021_READ = _huami("0017")
CHAR_CHUNKED = _huami("0020")

CHAR_CURRENT_TIME = _std("2a2b")
CHAR_HR_MEASUREMENT = _std("2a37")
CHAR_HR_CONTROL = _std("2a39")
CHAR_NEW_ALERT = _std("2a46")
CHAR_ALERT_LEVEL = _std("2a06")

DEVICE_INFO_CHARS = {
    "manufacturer": _std("2a29"),
    "model": _std("2a24"),
    "serial": _std("2a25"),
    "hardware": _std("2a27"),
    "firmware": _std("2a26"),
    "software": _std("2a28"),
}

MI_BAND6_NAME = "Mi Smart Band 6"


def looks_like_miband6(name: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    return "band 6" in n or "miband6" in n.replace(" ", "")


# ---------------------------------------------------------------------------
# Auth key
# ---------------------------------------------------------------------------


def parse_auth_key(text: str) -> bytes:
    """Nhận auth key dạng 32 ký tự hex (có thể có tiền tố 0x, khoảng trắng, dấu ':')."""
    s = (text or "").strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    s = "".join(ch for ch in s if ch not in " :-\t")
    if len(s) != 32:
        raise ValueError(tr('Auth key phải gồm đúng 32 ký tự hex (16 byte).'))
    try:
        return bytes.fromhex(s)
    except ValueError as e:
        raise ValueError(tr('Auth key chỉ được chứa ký tự 0-9 và a-f.')) from e


# ---------------------------------------------------------------------------
# Xác thực kiểu cũ (char 0x0009)
# ---------------------------------------------------------------------------

AUTH_RESPONSE = 0x10
AUTH_SUCCESS = 0x01
AUTH_FAIL = 0x04
AUTH_REQUEST_RANDOM = 0x02
AUTH_SEND_ENCRYPTED = 0x03
CRYPT_FLAGS = 0x80  # Mi Band 4/5/6
AUTH_FLAGS = 0x00


def auth_request_random() -> bytes:
    return bytes([CRYPT_FLAGS | AUTH_REQUEST_RANDOM, AUTH_FLAGS, 0x02, 0x01, 0x00])


def auth_send_encrypted(encrypted_random: bytes) -> bytes:
    return bytes([CRYPT_FLAGS | AUTH_SEND_ENCRYPTED, AUTH_FLAGS]) + bytes(encrypted_random)


# ---------------------------------------------------------------------------
# Thời gian (Current Time 0x2A2B)
# ---------------------------------------------------------------------------


def encode_current_time(now: _dt.datetime | None = None) -> bytes:
    if now is None:
        now = _dt.datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    offset = now.utcoffset() or _dt.timedelta(0)
    tz_quarters = int(offset.total_seconds() // 900)
    return bytes(
        [
            now.year & 0xFF,
            (now.year >> 8) & 0xFF,
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second,
            now.isoweekday(),  # Thứ Hai = 1 ... Chủ nhật = 7
            0,
            0,
            tz_quarters & 0xFF,
        ]
    )


def decode_current_time(data: bytes) -> _dt.datetime | None:
    data = bytes(data)
    if len(data) < 7:
        return None
    year = data[0] | (data[1] << 8)
    try:
        t = _dt.datetime(year, data[2], data[3], data[4], data[5], data[6])
    except ValueError:
        return None
    if len(data) >= 11:
        q = data[10] - 256 if data[10] > 127 else data[10]
        t = t.replace(tzinfo=_dt.timezone(_dt.timedelta(minutes=15 * q)))
    return t


# ---------------------------------------------------------------------------
# Pin, bước chân, nhịp tim
# ---------------------------------------------------------------------------


@dataclass
class BatteryInfo:
    level: int
    charging: bool
    last_charge: _dt.datetime | None = None
    last_charge_level: int | None = None


def _raw_datetime(b: bytes) -> _dt.datetime | None:
    if len(b) < 7:
        return None
    year = b[0] | (b[1] << 8)
    if not 2015 <= year <= 2100:
        return None
    try:
        return _dt.datetime(year, b[2], b[3], b[4], b[5], b[6])
    except ValueError:
        return None


def decode_battery(data: bytes) -> BatteryInfo | None:
    data = bytes(data)
    if len(data) < 2:
        return None
    level = data[1]
    charging = len(data) >= 3 and data[2] == 1
    last_charge = None
    if len(data) >= 18:
        # Gadgetbridge đọc ở vị trí 10; một số bản ghi cho thấy vị trí 11
        last_charge = _raw_datetime(data[10:17]) or _raw_datetime(data[11:18])
    last_level = data[19] if len(data) >= 20 else None
    return BatteryInfo(level, charging, last_charge, last_level)


@dataclass
class ActivityInfo:
    steps: int
    meters: int | None = None
    calories: int | None = None


def decode_steps(data: bytes) -> ActivityInfo | None:
    data = bytes(data)
    if len(data) < 3:
        return None
    if len(data) >= 13:
        steps = int.from_bytes(data[1:5], "little")
        meters = int.from_bytes(data[5:9], "little")
        calories = int.from_bytes(data[9:13], "little")
        return ActivityInfo(steps, meters, calories)
    return ActivityInfo(data[1] | (data[2] << 8))


def decode_heart_rate(data: bytes) -> int | None:
    data = bytes(data)
    if len(data) < 2:
        return None
    if data[0] & 0x01:  # định dạng uint16
        return data[1] | (data[2] << 8) if len(data) >= 3 else None
    return data[1]


HR_STOP_MANUAL = bytes([0x15, 0x02, 0x00])
HR_START_MANUAL = bytes([0x15, 0x02, 0x01])
HR_STOP_CONTINUOUS = bytes([0x15, 0x01, 0x00])
HR_START_CONTINUOUS = bytes([0x15, 0x01, 0x01])
HR_PING = bytes([0x16])


def hr_sleep_assist(enable: bool) -> bytes:
    return bytes([0x15, 0x00, 0x01 if enable else 0x00])


HR_INTERVALS = [0, 1, 5, 10, 30]  # phút; 0 = tắt


def hr_measurement_interval(minutes: int) -> bytes:
    return bytes([0x14, minutes & 0xFF])


# ---------------------------------------------------------------------------
# Hồ sơ người dùng (char 0x0008)
# ---------------------------------------------------------------------------

GENDER_MALE, GENDER_FEMALE, GENDER_OTHER = 0, 1, 2


def java_string_hash(s: str) -> int:
    """String.hashCode() của Java (tính trên các đơn vị UTF-16)."""
    units = s.encode("utf-16-be")
    h = 0
    for i in range(0, len(units), 2):
        h = (31 * h + int.from_bytes(units[i:i + 2], "big")) & 0xFFFFFFFF
    return h


def user_info(
    alias: str,
    birth: _dt.date,
    gender: int,
    height_cm: int,
    weight_kg: float,
) -> bytes:
    uid = java_string_hash(alias or "user")
    weight = int(round(weight_kg * 200))
    return bytes(
        [
            0x4F,
            0,
            0,
            birth.year & 0xFF,
            (birth.year >> 8) & 0xFF,
            birth.month,
            birth.day,
            gender,
            height_cm & 0xFF,
            (height_cm >> 8) & 0xFF,
            weight & 0xFF,
            (weight >> 8) & 0xFF,
        ]
    ) + uid.to_bytes(4, "little")


def fitness_goal(steps: int) -> bytes:
    steps = max(0, min(int(steps), 0xFFFF))
    return bytes([0x10, 0x00, 0x00, steps & 0xFF, (steps >> 8) & 0xFF, 0, 0])


WEAR_LEFT = bytes([0x20, 0x00, 0x00, 0x02])
WEAR_RIGHT = bytes([0x20, 0x00, 0x00, 0x82])

# ---------------------------------------------------------------------------
# Lệnh cấu hình (char 0x0003, hoặc endpoint 0x0090 ở giao thức mới)
# ---------------------------------------------------------------------------

ENDPOINT_DISPLAY = 0x06


def time_format_24h(enable: bool) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x02, 0x00, 0x01 if enable else 0x00])


DATE_FORMATS = ["dd/MM/yyyy", "dd.MM.yyyy", "MM/dd/yyyy"]


def date_format(fmt: str) -> bytes:
    if fmt not in DATE_FORMATS:
        raise ValueError(tr('Định dạng ngày không hỗ trợ: {fmt}', fmt=fmt))
    return bytes([ENDPOINT_DISPLAY, 30, 0x00]) + fmt.encode("ascii")


def distance_unit(metric: bool) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x03, 0x00, 0x00 if metric else 0x01])


LANGUAGES = {
    "vi_VN": "Tiếng Việt",
    "en_US": "English",
    "zh_TW": "繁體中文",
    "zh_CN": "简体中文",
    "th_TH": "ไทย",
    "id_ID": "Bahasa Indonesia",
    "ar_SA": "العربية",
    "cs_CZ": "Čeština",
    "de_DE": "Deutsch",
    "el_GR": "Ελληνικά",
    "es_ES": "Español",
    "fr_FR": "Français",
    "he_IL": "עברית",
    "it_IT": "Italiano",
    "nl_NL": "Nederlands",
    "pl_PL": "Polski",
    "pt_PT": "Português",
    "ro_RO": "Română",
    "ru_RU": "Русский",
    "tr_TR": "Türkçe",
    "uk_UA": "Українська",
}


def language(locale: str) -> bytes:
    b = locale.encode("ascii")
    if len(b) != 5:
        raise ValueError(tr('Mã ngôn ngữ phải có dạng xx_YY'))
    return bytes([ENDPOINT_DISPLAY, 0x17, 0x00]) + b


LIFT_OFF, LIFT_ON, LIFT_SCHEDULED = "off", "on", "scheduled"


def lift_wrist(mode: str, start: _dt.time | None = None, end: _dt.time | None = None) -> bytes:
    if mode == LIFT_OFF:
        return bytes([ENDPOINT_DISPLAY, 0x05, 0x00, 0x00])
    if mode == LIFT_ON:
        return bytes([ENDPOINT_DISPLAY, 0x05, 0x00, 0x01, 0, 0, 0, 0])
    if mode == LIFT_SCHEDULED:
        start = start or _dt.time(0, 0)
        end = end or _dt.time(0, 0)
        return bytes([ENDPOINT_DISPLAY, 0x05, 0x00, 0x01, start.hour, start.minute, end.hour, end.minute])
    raise ValueError(mode)


def lift_wrist_sensitive(sensitive: bool) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x23, 0x00, 0x01 if sensitive else 0x00])


NIGHT_OFF, NIGHT_SUNSET, NIGHT_SCHEDULED = "off", "sunset", "scheduled"


def night_mode(mode: str, start: _dt.time | None = None, end: _dt.time | None = None) -> bytes:
    if mode == NIGHT_OFF:
        return bytes([0x1A, 0x00])
    if mode == NIGHT_SUNSET:
        return bytes([0x1A, 0x02])
    if mode == NIGHT_SCHEDULED:
        start = start or _dt.time(16, 0)
        end = end or _dt.time(7, 0)
        return bytes([0x1A, 0x01, start.hour, start.minute, end.hour, end.minute])
    raise ValueError(mode)


DND_OFF, DND_AUTO, DND_SCHEDULED = "off", "auto", "scheduled"


def do_not_disturb(
    mode: str,
    start: _dt.time | None = None,
    end: _dt.time | None = None,
    lift_wrist_unlock: bool = False,
) -> bytes:
    if mode == DND_OFF:
        data = bytearray([0x09, 0x82])
    elif mode == DND_AUTO:
        data = bytearray([0x09, 0x83])
    elif mode == DND_SCHEDULED:
        start = start or _dt.time(1, 0)
        end = end or _dt.time(6, 0)
        data = bytearray([0x09, 0x81, start.hour, start.minute, end.hour, end.minute])
    else:
        raise ValueError(mode)
    if lift_wrist_unlock and mode != DND_OFF:
        data[1] &= ~0x80 & 0xFF
    return bytes(data)


def inactivity_warnings(
    enable: bool,
    threshold_min: int = 60,
    start: _dt.time = _dt.time(6, 0),
    end: _dt.time = _dt.time(22, 0),
    dnd: bool = False,
    dnd_start: _dt.time = _dt.time(12, 0),
    dnd_end: _dt.time = _dt.time(14, 0),
) -> bytes:
    data = bytearray([0x08, 0x01 if enable else 0x00, 0x3C, 0x00, 0x04, 0x00, 0x15, 0x00, 0, 0, 0, 0])
    if not enable:
        return bytes(data)
    data[2] = max(1, min(threshold_min, 255))
    data[4], data[5] = start.hour, start.minute
    if dnd:
        data[6], data[7] = dnd_start.hour, dnd_start.minute
        data[8], data[9] = dnd_end.hour, dnd_end.minute
        data[10], data[11] = end.hour, end.minute
    else:
        data[6], data[7] = end.hour, end.minute
    return bytes(data)


def goal_notification(enable: bool) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x06, 0x00, 0x01 if enable else 0x00])


def hr_activity_monitoring(enable: bool) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x22, 0x00, 0x01 if enable else 0x00])


HR_ALERT_THRESHOLDS = list(range(100, 155, 5))


def hr_alert(enable: bool, threshold: int = 120) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x1A, 0x00, 0x01 if enable else 0x00, threshold & 0xFF])


def stress_monitoring(enable: bool) -> bytes:
    return bytes([0xFE, 0x06, 0x00, 0x01 if enable else 0x00])


def password(enable: bool, pin: str) -> bytes:
    if not (len(pin) == 6 and pin.isdigit()):
        raise ValueError(tr('Mật khẩu phải gồm 6 chữ số'))
    return bytes([ENDPOINT_DISPLAY, 0x21, 0x00, 0x01 if enable else 0x00]) + pin.encode("ascii") + b"\x00"


def disconnect_notification(enable: bool) -> bytes:
    return bytes([ENDPOINT_DISPLAY, 0x0C, 0x00, 0x01 if enable else 0x00, 0, 0, 0, 0])


ACK_FIND_PHONE = bytes([ENDPOINT_DISPLAY, 0x14, 0x00, 0x00])

# ---------------------------------------------------------------------------
# Báo thức
# ---------------------------------------------------------------------------

MAX_ALARMS = 10
DAY_BITS = [1, 2, 4, 8, 16, 32, 64]  # Thứ Hai ... Chủ nhật
ONCE = 128


@dataclass
class Alarm:
    slot: int
    enabled: bool = False
    hour: int = 7
    minute: int = 0
    days: int = 0  # bitmask DAY_BITS; 0 = một lần
    in_use: bool = True
    snooze: bool = True


def alarm_command(a: Alarm) -> bytes:
    action = 0
    if a.enabled and a.in_use:
        action = 0x80
        if not a.snooze:
            action |= 0x40
    days = 0
    if a.in_use:
        days = a.days if a.days else ONCE
    return bytes([0x02, (action | (a.slot & 0x0F)) & 0xFF, a.hour, a.minute, days])


REQUEST_ALARMS = bytes([0xFF, 0x01, 0x00, 0x00, 0x00])


def decode_alarms_with_times(payload: bytes) -> list[Alarm]:
    """Giải mã phản hồi 'báo thức kèm giờ' đã ghép (byte 0 là loại, sau đó mỗi báo thức 4 byte)."""
    payload = bytes(payload)
    out: list[Alarm] = []
    n = (len(payload) - 1) // 4
    for i in range(n):
        off = 1 + i * 4
        flags = payload[off]
        days = payload[off + 3]
        out.append(
            Alarm(
                slot=flags & 0x0F,
                enabled=bool(flags & 0x80),
                hour=payload[off + 1],
                minute=payload[off + 2],
                days=0 if days == ONCE else days & 0x7F,
                in_use=True,
                snooze=not bool(flags & 0x40),
            )
        )
    return out


class ConfigReassembler:
    """Ghép các phản hồi nhiều gói trên characteristic cấu hình (dạng 0x80 0x01 ...)."""

    def __init__(self):
        self.buf: bytearray | None = None
        self.type = 0

    def feed(self, value: bytes) -> tuple[int, bytes] | None:
        value = bytes(value)
        if len(value) < 4 or value[0] != 0x80 or value[1] != 0x01:
            return None
        flag = value[2]
        if flag in (0x00, 0xC0):
            self.buf = bytearray(value[8:])
            self.type = value[4]
            if flag == 0xC0:
                return self._done()
        elif self.buf is not None and flag in (0x40, 0x80):
            self.buf += value[4:]
            if flag == 0x80:
                return self._done()
        return None

    def _done(self):
        out = (self.type, bytes(self.buf or b""))
        self.buf = None
        return out


# ---------------------------------------------------------------------------
# Màn hình / menu
# ---------------------------------------------------------------------------

MENU_IDS = {
    "status": 0x01,
    "hr": 0x02,
    "workout": 0x03,
    "weather": 0x04,
    "notifications": 0x06,
    # 0x07 là mục "Thêm" của Mi Band 3/5. Mi Band 6 không có thư mục này (Gadgetbridge cũng
    # không gửi), nên không đưa vào đây để không bao giờ gửi nhầm cho vòng tay.
    "dnd": 0x08,
    "alarm": 0x09,
    "takephoto": 0x0A,
    "music": 0x0B,
    "stopwatch": 0x0C,
    "timer": 0x0D,
    "findphone": 0x0E,
    "mutephone": 0x0F,
    "nfc": 0x10,
    "alipay": 0x11,
    "watchface": 0x12,
    "settings": 0x13,
    "activity": 0x14,
    "eventreminder": 0x15,
    "pai": 0x19,
    "worldclock": 0x1A,
    "stress": 0x1C,
    "period": 0x1D,
    "sleep": 0x23,
    "spo2": 0x24,
    "breathing": 0x33,
    "pomodoro": 0x38,
    "flashlight": 0x43,
}

MENU_LABELS = {
    "status": "Trạng thái",
    "hr": "Nhịp tim",
    "workout": "Tập luyện",
    "weather": "Thời tiết",
    "notifications": "Thông báo",
    "dnd": "Không làm phiền",
    "alarm": "Báo thức",
    "takephoto": "Chụp ảnh",
    "music": "Nhạc",
    "stopwatch": "Bấm giờ",
    "timer": "Hẹn giờ",
    "findphone": "Tìm điện thoại",
    "mutephone": "Tắt tiếng điện thoại",
    "settings": "Cài đặt",
    "activity": "Hoạt động",
    "eventreminder": "Nhắc sự kiện",
    "pai": "PAI",
    "sleep": "Giấc ngủ",
    "worldclock": "Giờ thế giới",
    "stress": "Căng thẳng",
    "period": "Chu kỳ",
    "spo2": "SpO₂",
    "breathing": "Hít thở",
    "flashlight": "Đèn pin",
    "pomodoro": "Pomodoro",
    "alipay": "Alipay",
    "nfc": "NFC",
}

DISPLAY_ITEMS_ALL = [
    "status", "hr", "workout", "weather", "notifications", "alarm", "takephoto",
    "pomodoro", "music", "stopwatch", "timer", "findphone", "mutephone", "settings",
    "activity", "eventreminder", "pai", "sleep", "worldclock", "stress", "period",
    "spo2", "breathing", "flashlight", "alipay", "nfc",
]
# Bố cục gần với mặc định của vòng tay. Mi Band 6 xếp mọi ứng dụng trong một danh sách
# (không có thư mục "Thêm"); mục không có trong danh sách sẽ bị ẩn.
DISPLAY_ITEMS_DEFAULT = [
    "status", "hr", "pai", "notifications", "spo2", "stress", "workout", "weather",
    "breathing", "sleep", "alarm", "eventreminder", "music", "takephoto", "stopwatch",
    "timer", "findphone", "mutephone", "worldclock", "flashlight", "pomodoro", "period",
    "activity", "settings",
]
MENU_ALWAYS_VISIBLE = "settings"

SHORTCUTS_ALL = [
    "status", "hr", "workout", "weather", "notifications", "dnd", "alarm", "takephoto",
    "music", "stopwatch", "timer", "findphone", "mutephone", "eventreminder", "pai",
    "sleep", "worldclock", "stress", "period", "spo2", "breathing", "flashlight",
    "alipay", "nfc",
]
SHORTCUTS_DEFAULT = ["notifications", "weather", "music"]


def arrange_display_items(items: list[str]) -> list[str]:
    """Chuẩn hóa bố cục: bỏ mục lạ/trùng, luôn giữ Cài đặt."""
    out: list[str] = []
    for k in items:
        if k in DISPLAY_ITEMS_ALL and k not in out:
            out.append(k)
    if MENU_ALWAYS_VISIBLE not in out:
        out.append(MENU_ALWAYS_VISIBLE)
    return out


def display_items(items: list[str]) -> bytes:
    """Menu ứng dụng: mặt đồng hồ rồi các mục theo thứ tự. Mục không có trong danh sách sẽ bị ẩn."""
    return menu_items(arrange_display_items(items), shortcuts=False)


def menu_items(items: list[str], shortcuts: bool) -> bytes:
    """Lệnh sắp xếp menu (gửi qua kênh chunked loại 2). Mặt đồng hồ luôn đứng đầu."""
    menu_type = 0xFD if shortcuts else 0xFF
    keys = ["watchface"] + [k for k in items if k in MENU_IDS and k != "watchface"]
    out = bytearray([0x1E])
    for idx, key in enumerate(keys):
        out += bytes([idx, 0x00, menu_type, MENU_IDS[key]])
    return bytes(out)


# ---------------------------------------------------------------------------
# Thông báo & cuộc gọi
# ---------------------------------------------------------------------------

ALERT_CUSTOM_HUAMI = 0xFA
ALERT_SMS = 0x05
ALERT_EMAIL = 0x01
ALERT_INCOMING_CALL = 0x03

NOTIFICATION_ICONS = {
    "Ứng dụng chung": 11,
    "Tin nhắn SMS": -1,
    "Email": 34,
    "Lịch": 21,
    "Messenger": 22,
    "Facebook": 3,
    "Instagram": 12,
    "Telegram": 25,
    "WhatsApp": 7,
    "LINE": 24,
    "Zalo / chat": 13,
    "Thời tiết": 35,
    "Báo thức": 10,
}

NOTIFICATION_MAX = 230


def _truncate_utf8(b: bytes, limit: int) -> bytes:
    if len(b) <= limit:
        return b
    return b[:limit].decode("utf-8", "ignore").encode("utf-8")


def notification_payload(title: str, body: str, app_name: str = "MiBand6", icon: int = 11) -> bytes:
    """Gói thông báo văn bản cho Mi Band 4/5/6 (gửi qua kênh chunked loại 0)."""
    message = (title or "")[:32] + "\0" + ((body or "")[:512] or " ")
    raw = message.encode("utf-8")
    if icon < 0:
        category, prefix = ALERT_SMS, bytearray([ALERT_SMS, 0, 0, 0, 0, 1])
        suffix = b"\0 \0"
    else:
        category, prefix = ALERT_CUSTOM_HUAMI, bytearray([ALERT_CUSTOM_HUAMI, 0, 0, 0, 0, 1, icon & 0xFF])
        suffix = ("\0" + (app_name or "UNKNOWN") + "\0").encode("utf-8")
    del category
    raw = _truncate_utf8(raw, NOTIFICATION_MAX - len(prefix))
    return bytes(prefix) + raw + suffix


def incoming_call(name: str) -> bytes:
    return bytes([ALERT_INCOMING_CALL, 0x01]) + _truncate_utf8((name or "").encode("utf-8"), 255)


STOP_CALL = bytes([ALERT_INCOMING_CALL, 0x00])


def chunked_old(type_: int, data: bytes, mtu: int = 23) -> list[bytes]:
    """Chia gói cho characteristic 0x0020 (kênh chunked cũ)."""
    data = bytes(data)
    max_len = mtu - 6
    chunks = []
    remaining = len(data)
    count = 0
    while remaining > 0:
        n = min(remaining, max_len)
        flags = 0
        if remaining <= max_len:
            flags |= 0x80
            if count == 0:
                flags |= 0x40
        elif count > 0:
            flags |= 0x40
        start = count * max_len
        chunks.append(bytes([0x00, flags | type_, count & 0xFF]) + data[start:start + n])
        remaining -= n
        count += 1
    return chunks


def chunked_2021_compat(type_: int, data: bytes) -> bytes:
    """Nội dung gửi qua endpoint 0x0090 thay cho kênh chunked cũ khi dùng giao thức mới."""
    return bytes([0x00, 0x00, 0xC0 | type_, 0x00]) + bytes(data)


# ---------------------------------------------------------------------------
# Sự kiện từ vòng tay (char 0x0010)
# ---------------------------------------------------------------------------

DEVICE_EVENTS = {
    0x01: "Đã ngủ",
    0x02: "Đã thức dậy",
    0x03: "Đạt mục tiêu bước chân",
    0x04: "Nhấn nút",
    0x06: "Tháo vòng khỏi tay",
    0x07: "Từ chối cuộc gọi",
    0x08: "Tìm điện thoại: bắt đầu",
    0x09: "Bỏ qua cuộc gọi",
    0x0A: "Bật/tắt báo thức",
    0x0B: "Nhấn giữ nút",
    0x0F: "Tìm điện thoại: dừng",
    0x10: "Chế độ im lặng",
    0x14: "Bắt đầu tập luyện",
    0x1A: "Báo thức thay đổi",
    0xFE: "Điều khiển nhạc",
}

EVENT_FIND_PHONE_START = 0x08
EVENT_FIND_PHONE_STOP = 0x0F
EVENT_CALL_REJECT = 0x07
EVENT_CALL_IGNORE = 0x09
EVENT_ALARM_TOGGLED = 0x0A
EVENT_ALARM_CHANGED = 0x1A


@dataclass
class DeviceInfo:
    name: str = ""
    address: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    hardware: str = ""
    firmware: str = ""
    software: str = ""
    protocol: str = ""
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lấy dữ liệu sức khỏe lưu trên vòng tay (Gadgetbridge: AbstractFetchOperation)
#
#   → 0x0004  01 <loại> <từ lúc: năm(2) tháng ngày giờ phút> 00 <múi giờ>
#   ← 0x0004  10 01 01 <số byte(4)> <mốc bắt đầu: năm(2) tháng ngày giờ phút giây> [múi giờ]
#   → 0x0004  02
#   ← 0x0005  <số thứ tự gói> <dữ liệu…>   (nhiều gói)
#   ← 0x0004  10 02 01 [crc32]
#
# Không gửi lệnh xác nhận 03: lệnh đó khiến vòng tay coi dữ liệu là đã đồng bộ, và Mi Fitness
# sẽ không nhận được nữa. Lần sau chỉ cần hỏi từ mốc thời gian đã lấy tới.
# ---------------------------------------------------------------------------

CHAR_FETCH = _huami("0004")
CHAR_ACTIVITY_DATA = _huami("0005")

FETCH_ACTIVITY = 0x01        # mỗi phút 8 byte: loại, cường độ, bước, nhịp tim, ?, ngủ, ngủ sâu, REM
FETCH_SPORTS_SUMMARY = 0x05  # tóm tắt một buổi tập mỗi lần lấy
FETCH_PAI = 0x0D
FETCH_STRESS_MANUAL = 0x12
FETCH_STRESS_AUTO = 0x13
FETCH_SPO2 = 0x25
FETCH_CMD_START = 0x01
FETCH_CMD_DATA = 0x02


def _tz_quarters(t: _dt.datetime) -> int:
    offset = t.utcoffset() or _dt.timedelta(0)
    return int(offset.total_seconds() // 900)


def fetch_start(data_type: int, since: _dt.datetime) -> bytes:
    """Lệnh bắt đầu lấy dữ liệu loại `data_type` từ thời điểm `since` (làm tròn xuống phút)."""
    since = since.astimezone()  # giờ địa phương của máy, như Gadgetbridge
    return bytes([FETCH_CMD_START, data_type, since.year & 0xFF, since.year >> 8, since.month, since.day,
                  since.hour, since.minute, 0, _tz_quarters(since) & 0xFF])


def decode_fetch_start(data: bytes) -> tuple[int, _dt.datetime | None]:
    """Phản hồi lệnh bắt đầu: (số byte vòng tay sẽ gửi, mốc thời gian của byte đầu tiên).

    ValueError nếu vòng tay từ chối."""
    data = bytes(data)
    if len(data) < 3 or data[0] != 0x10 or data[1] != FETCH_CMD_START:
        raise ValueError(tr('Phản hồi lấy dữ liệu không hợp lệ: {data}', data=data.hex(" ")))
    if data[2] != 0x01:
        raise ValueError(tr('Vòng tay từ chối lấy dữ liệu (mã {code:#04x}).', code=data[2]))
    if len(data) < 14:
        return 0, None
    length = int.from_bytes(data[3:7], "little")
    year = data[7] | (data[8] << 8)
    try:
        start = _dt.datetime(year, data[9], data[10], data[11], data[12], data[13])
    except ValueError:
        return length, None
    if len(data) >= 15:
        q = data[14] - 256 if data[14] > 127 else data[14]
        start = start.replace(tzinfo=_dt.timezone(_dt.timedelta(minutes=15 * q)))
    else:
        start = start.astimezone()
    return length, start


def is_fetch_done(data: bytes) -> bool | None:
    """Phản hồi lệnh 02: True khi gửi xong, False khi lỗi, None nếu không phải phản hồi này."""
    data = bytes(data)
    if len(data) >= 3 and data[0] == 0x10 and data[1] == FETCH_CMD_DATA:
        return data[2] == 0x01
    return None


# ---------------------------------------------------------------------------
# Cài mặt đồng hồ (Gadgetbridge: UpdateFirmwareOperation2020, MiBand6FirmwareInfo)
#
#   (mặt đồng hồ UIHH) → lệnh cấu hình 39 00 <cỡ tệp(4)> <tệp[18:22]>
#   → 1531 d0                       ← 10 d0 01 .. <cỡ khối(2)>
#   → 1531 d2 <thông tin tệp>        ← 10 d2 01
#   → 1531 d3 01                     ← 10 d3 01
#   → 1532 <một khối dữ liệu>        ← 10 d4 <đã nhận(4)>   (lặp tới hết tệp)
#   → 1531 d5                        ← 10 d5 01
#   → 1531 d6                        ← 10 d6 01
# ---------------------------------------------------------------------------

SVC_FIRMWARE = _huami("1530")
CHAR_FW_CONTROL = _huami("1531")
CHAR_FW_DATA = _huami("1532")
FW_REQUEST_PARAMS = 0xD0
FW_SEND_INFO = 0xD2
FW_START_TRANSFER = 0xD3
FW_PROGRESS = 0xD4
FW_COMPLETE = 0xD5
FW_FINALIZE = 0xD6
FW_TYPE_WATCHFACE = 8
FW_ERR_LOW_BATTERY = 0x22
FW_ERR_FREE_SPACE = 0x47
WATCHFACE_MAX_SIZE = 4 * 1024 * 1024


def check_watchface(data: bytes) -> None:
    """ValueError nếu không phải tệp mặt đồng hồ Mi Band 6 (định dạng UIHH, như Gadgetbridge kiểm tra)."""
    if len(data) < 32 or not data.startswith(b"UIHH") or data[4] not in (1, 2):
        raise ValueError(tr('Tệp không phải mặt đồng hồ Mi Band 6 (cần tệp .bin bắt đầu bằng "UIHH").'))
    if len(data) > WATCHFACE_MAX_SIZE:
        raise ValueError(tr('Tệp mặt đồng hồ quá lớn.'))


def watchface_prepare(data: bytes) -> bytes:
    """Lệnh cấu hình báo trước kích thước và mã của mặt đồng hồ UIHH."""
    return bytes([0x39, 0x00]) + len(data).to_bytes(4, "little") + bytes(data[18:22])


def firmware_info(fw_type: int, data: bytes, chunk_length: int) -> bytes:
    import zlib

    size = len(data).to_bytes(4, "little")
    crc = (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little")
    return (bytes([FW_SEND_INFO, fw_type]) + size + crc + (chunk_length & 0xFFFF).to_bytes(2, "little")
            + bytes([0, 0, 1]) + size)   # cập nhật ở tiền cảnh, chỉ số 0, tổng 1 tệp, tổng kích thước


# ---------------------------------------------------------------- thời tiết (kênh chunked, loại 1)
# Theo HuamiSupport.onSendWeather của Gadgetbridge: mỗi gói mở đầu bằng 1 byte loại, phần lớn kèm thời điểm
# (uint32) và múi giờ tính theo 15 phút (int8). Chữ là UTF-8 kết thúc bằng byte 0. Mi Band 6 nhận cả gói
# gió/độ ẩm và giờ mặt trời mọc/lặn.
CHUNKED_WEATHER = 1
WEATHER_FORECAST, WEATHER_CURRENT, WEATHER_AQI, WEATHER_LOCATION, WEATHER_SUN, WEATHER_WIND_HUMIDITY = 1, 2, 4, 8, 16, 64
WEATHER_MAX_DAYS = 7          # hôm nay + 6 ngày tới (Gadgetbridge cắt dự báo ở 6 ngày)
WEATHER_TEXT_MAX = 40         # byte UTF-8 tối đa cho một chuỗi (tên địa điểm, mô tả)


def _wtext(text: str) -> bytes:
    raw = (text or "").encode("utf-8")[:WEATHER_TEXT_MAX]
    return raw.decode("utf-8", "ignore").encode("utf-8") + b"\x00"   # không cắt giữa một ký tự nhiều byte


def _wstamp(kind: int, ts: int, tz_quarters: int) -> bytes:
    return bytes([kind]) + int(ts).to_bytes(4, "little") + (tz_quarters & 0xFF).to_bytes(1, "little")


def _i8(v: float) -> bytes:
    return (max(-128, min(127, round(v))) & 0xFF).to_bytes(1, "little")


def weather_current(ts: int, tz_quarters: int, condition: int, temp: float, text: str) -> bytes:
    return _wstamp(WEATHER_CURRENT, ts, tz_quarters) + bytes([condition & 0xFF]) + _i8(temp) + _wtext(text)


def weather_aqi(ts: int, tz_quarters: int, aqi: int, text: str) -> bytes:
    return _wstamp(WEATHER_AQI, ts, tz_quarters) + (int(aqi) & 0xFFFF).to_bytes(2, "little") + _wtext(text)


def weather_forecast(ts: int, tz_quarters: int, days: list[tuple[int, float, float, str]]) -> bytes:
    """days: [(mã thời tiết, cao nhất, thấp nhất, mô tả)], ngày đầu là hôm nay."""
    days = days[:WEATHER_MAX_DAYS]
    out = _wstamp(WEATHER_FORECAST, ts, tz_quarters) + bytes([len(days)])
    for code, high, low, text in days:
        out += bytes([code & 0xFF, code & 0xFF]) + _i8(high) + _i8(low) + _wtext(text)
    return out


def weather_location(name: str) -> bytes:
    return bytes([WEATHER_LOCATION]) + _wtext(name)


def weather_wind_humidity(ts: int, tz_quarters: int, wind: str, humidity: str) -> bytes:
    return _wstamp(WEATHER_WIND_HUMIDITY, ts, tz_quarters) + _wtext(wind) + _wtext(humidity)


def weather_sun(ts: int, tz_quarters: int, sunrise: tuple[int, int], sunset: tuple[int, int]) -> bytes:
    return _wstamp(WEATHER_SUN, ts, tz_quarters) + bytes([sunrise[0], sunrise[1], sunset[0], sunset[1]])
