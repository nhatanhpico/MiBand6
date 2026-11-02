import datetime as dt
import os

import pytest

from miband6 import crypto
from miband6 import protocol as P


# ----------------------------------------------------------------- auth key
def test_parse_auth_key_variants():
    k = "0x" + "a1" * 16
    assert P.parse_auth_key(k) == bytes([0xA1] * 16)
    assert P.parse_auth_key("A1:" * 15 + "A1") == bytes([0xA1] * 16)
    with pytest.raises(ValueError):
        P.parse_auth_key("abc")
    with pytest.raises(ValueError):
        P.parse_auth_key("zz" * 16)


def test_auth_commands():
    assert P.auth_request_random() == bytes([0x82, 0x00, 0x02, 0x01, 0x00])
    assert P.auth_send_encrypted(b"\x11" * 16)[:2] == bytes([0x83, 0x00])


# ----------------------------------------------------------------- thời gian
def test_current_time_roundtrip():
    tz = dt.timezone(dt.timedelta(hours=8))
    t = dt.datetime(2026, 11, 2, 21, 28, 5, tzinfo=tz)
    raw = P.encode_current_time(t)
    assert raw == bytes([0xEA, 0x07, 11, 2, 21, 28, 5, 1, 0, 0, 32])
    back = P.decode_current_time(raw)
    assert back == t


def test_negative_timezone():
    tz = dt.timezone(dt.timedelta(hours=-5))
    raw = P.encode_current_time(dt.datetime(2026, 1, 4, 8, 0, 0, tzinfo=tz))
    assert raw[7] == 7  # Chủ nhật
    assert raw[10] == (-20) & 0xFF


# ----------------------------------------------------------------- dữ liệu
def test_decode_steps_and_battery():
    raw = bytes([0x0C]) + (12345).to_bytes(4, "little") + (9000).to_bytes(4, "little") + (432).to_bytes(4, "little")
    a = P.decode_steps(raw)
    assert (a.steps, a.meters, a.calories) == (12345, 9000, 432)
    b = P.decode_battery(bytes([0x0F, 55, 1]))
    assert b.level == 55 and b.charging
    assert P.decode_heart_rate(bytes([0, 71])) == 71


def test_user_info_matches_gadgetbridge_layout():
    raw = P.user_info("mi1", dt.date(2005, 4, 24), P.GENDER_MALE, 172, 60)
    assert raw[:12] == bytes([0x4F, 0, 0, 0xD5, 0x07, 4, 24, 0, 172, 0, 0xE0, 0x2E])
    # "mi1".hashCode() trong Java = 109*31*31 + 105*31 + 49 = 108053
    assert int.from_bytes(raw[12:16], "little") == 108053
    assert len(raw) == 16


def test_goal_and_formats():
    assert P.fitness_goal(8000) == bytes([0x10, 0, 0, 0x40, 0x1F, 0, 0])
    assert P.date_format("dd/MM/yyyy") == bytes([6, 30, 0]) + b"dd/MM/yyyy"
    assert P.time_format_24h(True) == bytes([6, 2, 0, 1])
    assert P.language("vi_VN") == bytes([6, 0x17, 0]) + b"vi_VN"
    assert P.distance_unit(True) == bytes([6, 3, 0, 0])


def test_dnd_and_inactivity():
    assert P.do_not_disturb(P.DND_OFF) == bytes([0x09, 0x82])
    assert P.do_not_disturb(P.DND_SCHEDULED, dt.time(23, 0), dt.time(7, 30)) == bytes([0x09, 0x81, 23, 0, 7, 30])
    assert P.do_not_disturb(P.DND_AUTO, lift_wrist_unlock=True) == bytes([0x09, 0x03])
    off = P.inactivity_warnings(False)
    assert off == bytes([0x08, 0x00, 0x3C, 0x00, 0x04, 0x00, 0x15, 0x00, 0, 0, 0, 0])
    on = P.inactivity_warnings(True, 45, dt.time(8, 0), dt.time(20, 0), True, dt.time(12, 0), dt.time(13, 30))
    assert on == bytes([0x08, 0x01, 45, 0x00, 8, 0, 12, 0, 13, 30, 20, 0])


def test_alarm_command_and_decode():
    a = P.Alarm(slot=3, enabled=True, hour=6, minute=45, days=P.DAY_BITS[0] | P.DAY_BITS[4])
    assert P.alarm_command(a) == bytes([0x02, 0x83, 6, 45, 0x11])
    once = P.Alarm(slot=1, enabled=True, hour=7, minute=0, days=0)
    assert P.alarm_command(once)[4] == 128
    payload = bytes([2, 0x80 | 3, 6, 45, 0x11, 0x01, 7, 0, 128])
    al = P.decode_alarms_with_times(payload)
    assert [(x.slot, x.enabled, x.hour, x.minute, x.days) for x in al] == [(3, True, 6, 45, 0x11), (1, False, 7, 0, 0)]


def test_config_reassembler_multi_chunk():
    r = P.ConfigReassembler()
    assert r.feed(bytes([0x80, 0x01, 0x00, 0x00, 0x01, 0, 0, 0, 1, 2])) is None
    assert r.feed(bytes([0x80, 0x01, 0x40, 0x01, 3, 4])) is None
    assert r.feed(bytes([0x80, 0x01, 0x80, 0x02, 5])) == (0x01, bytes([1, 2, 3, 4, 5]))


def test_menu_items_starts_with_watchface():
    raw = P.menu_items(["hr", "weather", "bogus"], shortcuts=False)
    assert raw == bytes([0x1E, 0, 0, 0xFF, 0x12, 1, 0, 0xFF, 0x02, 2, 0, 0xFF, 0x04])
    assert P.menu_items(["music"], shortcuts=True)[3] == 0xFD


def test_display_items_with_more_folder():
    raw = P.display_items(["hr", "weather"], ["music", "settings"])
    # mặt đồng hồ, 2 mục chính, "Thêm" (0x07), rồi các mục trong "Thêm"
    assert raw == bytes([0x1E, 0, 0, 0xFF, 0x12, 1, 0, 0xFF, 0x02, 2, 0, 0xFF, 0x04,
                         3, 0, 0xFF, 0x07, 4, 0, 0xFF, 0x0B, 5, 0, 0xFF, 0x13])
    # tối đa 15 mục chính, phần dư sang "Thêm"; Cài đặt không bao giờ bị ẩn; bỏ trùng
    main, more = P.arrange_display_items(P.DISPLAY_ITEMS_ALL, ["hr", "bogus"])
    assert len(main) == P.MENU_MAIN_MAX and main[0] == "status"
    assert more[0] == P.DISPLAY_ITEMS_ALL[15] and "hr" not in more and "bogus" not in more
    main, more = P.arrange_display_items(["hr"], [])
    assert more == ["settings"]
    # không có mục nào trong "Thêm" thì không gửi mục "Thêm"
    assert 0x07 not in P.display_items(["hr", "settings"], [])[1::4][3::4]
    assert P.display_items(["hr", "settings"], []) == P.menu_items(["hr", "settings"], False)


def test_notification_payload():
    raw = P.notification_payload("Chào", "Xin chào bạn", "Zalo", icon=13)
    assert raw[:7] == bytes([0xFA, 0, 0, 0, 0, 1, 13])
    assert raw.endswith(b"\x00Zalo\x00")
    assert "Chào\0Xin chào bạn".encode() in raw
    sms = P.notification_payload("Mẹ", "Về ăn cơm", icon=-1)
    assert sms[:6] == bytes([0x05, 0, 0, 0, 0, 1]) and sms.endswith(b"\x00 \x00")
    long = P.notification_payload("T", "ữ" * 400)
    long.decode("utf-8", "strict") if False else None
    body = long[7:-len(b"\x00MiBand6\x00")]
    body.decode("utf-8")  # không bị cắt giữa ký tự
    assert len(body) <= P.NOTIFICATION_MAX - 7


def test_chunked_old_flags():
    data = bytes(range(40))
    chunks = P.chunked_old(0, data)
    assert [c[1] for c in chunks] == [0x00, 0x40, 0x80]
    assert b"".join(c[3:] for c in chunks) == data
    single = P.chunked_old(2, b"abc")
    assert single == [bytes([0, 0xC2, 0]) + b"abc"]


# ----------------------------------------------------------------- ECDH
def test_ecdh_group_order_and_curve():
    assert crypto._on_curve(crypto._GX, crypto._GY)
    assert crypto._scalar_mul(crypto._ORDER, (crypto._GX, crypto._GY)) is None


def test_gadgetbridge_sample_public_key_is_on_curve():
    rp = bytes.fromhex(
        "e6016aba1de7ac0f0c7f0ff7e2243e6662b5e03b01000000"
        "ad8a4bedc76a1efde7725cc662b54835513e3d5705000000"
    )
    x = int.from_bytes(rp[:24], "little")
    y = int.from_bytes(rp[24:], "little")
    assert crypto._on_curve(x, y)


def test_ecdh_shared_secret_symmetric():
    a, b = crypto.ecdh_generate_private(), crypto.ecdh_generate_private()
    pa, pb = crypto.ecdh_public_key(a), crypto.ecdh_public_key(b)
    assert len(pa) == 48
    assert crypto.ecdh_shared_secret(a, pb) == crypto.ecdh_shared_secret(b, pa)
    with pytest.raises(ValueError):
        crypto.ecdh_shared_secret(a, bytes(48))


def test_chunked_2021_roundtrip_encrypted():
    key = os.urandom(16)
    enc, dec = crypto.ChunkedEncoder2021(), crypto.ChunkedDecoder2021()
    enc.set_encryption(0x01020304, key)
    dec.set_encryption(key)
    msg = bytes(range(70))
    chunks = enc.encode(crypto.ENDPOINT_COMPAT, msg, encrypt=True)
    assert len(chunks) > 1
    assert chunks[0][:2] == bytes([0x03, 0x09]) and chunks[-1][1] & 0x06 == 0x06
    assert all(len(c) <= 20 for c in chunks)
    out = None
    for c in chunks:
        _, r = dec.decode(c)
        out = r or out
    assert out == (crypto.ENDPOINT_COMPAT, msg)
    assert enc.seq == 0x01020305


def test_chunked_2021_plain_single():
    enc, dec = crypto.ChunkedEncoder2021(), crypto.ChunkedDecoder2021()
    chunks = enc.encode(crypto.ENDPOINT_AUTH, b"\x10\x05\x01", encrypt=False)
    assert chunks == [bytes([0x03, 0x07, 0x00, 0x01, 0x00, 3, 0, 0, 0, 0x82, 0x00, 0x10, 0x05, 0x01])]
    assert dec.decode(chunks[0])[1] == (0x82, b"\x10\x05\x01")
