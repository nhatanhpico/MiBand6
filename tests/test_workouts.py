"""Chi tiết buổi tập (workouts.py): đọc tệp dữ liệu từng giây, độ cao GPS của Mi Fitness, dựng trang chi tiết."""

import struct

import pytest

from miband6 import workouts as W

T0 = 1_800_000_000


def nibbles(values: list[int]) -> bytes:
    """Cờ hợp lệ: mỗi trường một nửa byte, nửa cao trước."""
    values = values + [0] * (len(values) % 2)
    return bytes((values[i] << 4) | values[i + 1] for i in range(0, len(values), 2))


def run_file(segments: list[tuple[int, int]], version: int = 8, hr: int = 150, dist_unit: int = 25,
             steps: int = 3, cadence: int = 180, pace: int = 400, stride: int = 83) -> bytes:
    """Tệp kiểu 22 (chạy ngoài trời): segments = [(thời điểm bắt đầu, số giây)]. Phiên bản 8 theo bảng của mifit; phiên
    bản 9 thử bố cục "độ cao 4 byte + quãng đường 2 byte (cm) ngay sau nhịp tim"."""
    head = struct.pack("<IbBBB", T0, 28, version, 22, 0)
    if version == 8:
        # calo/bước, nhịp tim, (độ cao 1 byte: không có), quãng đường, sải chân, (3 trường không có), nhịp bước, pace, …
        flags = nibbles([0xE, 0xC, 0x0, 0xC, 0xC, 0, 0, 0xC, 0xC, 0, 0, 0, 0])
    else:
        flags = nibbles([0xE, 0xC, 0xC, 0xC, 0xC, 0, 0, 0xC, 0xC, 0, 0, 0, 0])
    body = b""
    for start, n in segments:
        body += struct.pack("<fIIBIIIH", 90.0, n, start, 0, 0, n, 0, pace)
        for _ in range(n):
            p = bytes([(1 << 4) | steps, hr])
            p += bytes([dist_unit]) if version == 8 else struct.pack("<iH", 9000, dist_unit)
            p += bytes([stride, cadence]) + struct.pack("<H", pace)
            body += p
    return head + flags + body


def test_record_file_run_v8_with_pause():
    plain = run_file([(T0, 300), (T0 + 400, 300)])   # dừng 100 giây giữa buổi
    s = W.decode_record_file(plain, {"distance": 1500, "steps": 1800, "active_seconds": 600})
    assert len(s) == 600 and s[0][0] == T0 and s[300][0] == T0 + 400   # mỗi giây một điểm, chỗ dừng là khoảng trống
    ts, hr, dist, steps, cad, pace, speed, stride = s[-1]
    assert hr == 150 and dist == pytest.approx(1500) and steps == 1800 and cad == 180 and pace == 400
    assert speed is None and stride == 83
    # không có bản tóm tắt vẫn đọc được (bố cục đã biết chắc)
    assert len(W.decode_record_file(plain)) == 600


def test_record_file_newer_version_picks_layout_by_summary():
    plain = run_file([(T0, 600)], version=9, dist_unit=250)   # 2,5 m/s, quãng đường theo cm
    s = W.decode_record_file(plain, {"distance": 1500, "steps": 1800, "active_seconds": 600})
    assert len(s) == 600 and s[-1][2] == pytest.approx(1500) and s[-1][3] == 1800 and s[-1][1] == 150
    with pytest.raises(ValueError):   # tổng không khớp với bố cục nào: không đoán bừa
        W.decode_record_file(plain, {"distance": 5000, "steps": 1800, "active_seconds": 600})


def test_record_file_ride_v5_and_bad_files():
    head = struct.pack("<IbBBB", T0, 28, 5, 23, 0)
    flags = nibbles([0xC, 0xC, 0x0, 0xC, 0xC, 0x0])   # calo, nhịp tim, quãng đường (m), tốc độ (0,1 km/h)
    body = struct.pack("<fIIBIIH", 12.0, 120, T0, 0, 0, 120, 0)
    body += b"".join(bytes([1 << 4, 140, 7]) + struct.pack("<H", 252) for _ in range(120))   # 7 m/s
    s = W.decode_record_file(head + flags + body, {"distance": 840, "active_seconds": 120})
    assert len(s) == 120 and s[-1][2] == 840 and s[0][6] == pytest.approx(7.0) and s[0][3] is None and s[0][4] is None
    with pytest.raises(ValueError):
        W.decode_record_file(b"short")
    with pytest.raises(ValueError):   # kiểu dữ liệu chưa có bố cục
        W.decode_record_file(struct.pack("<IbBBB", T0, 28, 1, 30, 0) + bytes(40))
    with pytest.raises(ValueError):   # đoạn khai nhiều điểm hơn tệp
        W.decode_record_file(run_file([(T0, 100)])[:-50])


def test_gps_altitudes_v3():
    def gps(alts):
        head = struct.pack("<IbBBB", T0, 28, 3, 22, 0) + bytes([0xFE])
        return head + b"".join(struct.pack("<IfffHff", T0 + i, 106.7, 10.8, 5.0, 0x51, a, 0.0) for i, a in enumerate(alts))
    alt = W.gps_altitudes(gps([85.0 + i * 0.1 for i in range(50)]))
    assert len(alt) == 50 and alt[0] == [T0, 85.0] and alt[-1][1] == pytest.approx(89.9)
    assert W.gps_altitudes(gps([1e7] * 10)) is None          # không giống độ cao thật
    assert W.gps_altitudes(gps([0.0, 500.0] * 10)) is None   # nhảy quá xa mỗi giây
    v2 = struct.pack("<IbBBB", T0, 28, 2, 22, 0) + bytes([0xFC]) + struct.pack("<IfffH", T0, 106.7, 10.8, 5.0, 0)
    assert W.gps_altitudes(v2) is None                       # phiên bản 2 không có độ cao


def test_zones_and_load():
    assert W.zone_of(95, 190) == 1 and W.zone_of(140, 190) == 3 and W.zone_of(180, 190) == 5 and W.zone_of(80, 190) == 0
    assert W.zone_bounds(200)[1] == [120, 140]
    assert W.trimp([600, 600, 0, 0, 0]) == 30.0 and W.load_level(30) == "light" and W.load_level(200) == "very_hard"


def test_detail_from_mi_fitness_files():
    w = {"start": T0, "end": T0 + 1800, "active_seconds": 1800, "distance": 4200, "steps": 5400, "calories": 300,
         "avg_hr": 145, "max_hr": 172, "mf_proto": 22, "mf_sid": "x", "source": "mifitness", "mf_type": 1}
    samples = W.demo_record(w)
    track = [[T0 + i, 10.8 + i * 2e-5, 106.7] for i in range(1800)]
    alt = W.demo_altitude(track)
    d = W.detail(w, samples, track, alt, [], hrmax=195)
    assert d["kind"] == "run" and d["distance"] == 4200 and d["pace"] == round(1800 * 1000 / 4200)
    assert d["hr"]["source"] == "detail" and sum(d["hr"]["zones"]) == pytest.approx(1800, abs=5)
    assert [s["km"] for s in d["splits"]][:4] == [1, 2, 3, 4] and d["splits"][-1]["partial"]
    assert d["splits"][-1]["km"] == pytest.approx(4.2, abs=0.01)
    assert sum(s["seconds"] for s in d["splits"]) == pytest.approx(1800, abs=3)
    assert d["cadence"]["avg"] == pytest.approx(180, abs=3) and d["stride"]["avg"] == round(4200 * 100 / 5400)
    a = d["altitude"]
    assert a["min"] >= 80 and a["max"] <= 100 and a["gain"] > 5 and a["loss"] > 5
    assert sum(a["terrain"].values()) > 1500 and a["terrain"]["up"] > 0 and a["terrain"]["down"] > 0
    assert len(d["pace_series"]) <= W.SERIES_POINTS and d["max_pace"] < d["pace"]
    assert d["load"]["trimp"] > 0 and set(d["sources"]) >= {"mifitness", "detail", "gps"}


def test_detail_from_band_minutes_only():
    w = {"start": T0, "end": T0 + 1200, "active_seconds": 1200, "type": 8, "calories": 120, "source": "band",
         "version": 515}
    minutes = [[T0 + 60 * i, 120 + i, 0] for i in range(20)]
    d = W.detail(w, None, None, None, minutes, hrmax=190)
    assert d["kind"] == "ride" and d["hr"]["source"] == "band" and d["hr"]["min"] == 120 and d["hr"]["max"] == 139
    assert sum(d["hr"]["zones"]) == 1200 and "splits" not in d and d["distance"] is None and d["sources"] == ["band"]


def test_track_distance_ignores_jumps():
    track = [[T0, 10.0, 106.0], [T0 + 1, 10.00001, 106.0], [T0 + 2, 11.0, 106.0], [T0 + 3, 10.00002, 106.0]]
    d = W.track_distance(track)
    assert d[1][1] == pytest.approx(1.11, abs=0.05) and d[2][1] == d[1][1]   # nhảy 110 km trong 1 giây: bỏ
