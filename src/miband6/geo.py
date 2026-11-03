"""Tên thành phố, quốc gia của một tọa độ (để lọc bản đồ "những nơi đã đến").

Dùng dịch vụ Nominatim của OpenStreetMap (https://nominatim.org): miễn phí, không cần khóa, giới hạn 1 yêu cầu mỗi
giây và yêu cầu ghi rõ ứng dụng trong User-Agent. Tọa độ được làm tròn tới 0,01 độ (khoảng 1 km) trước khi gửi, và
kết quả được lưu trên máy (mỗi vùng chỉ hỏi một lần).
"""

from __future__ import annotations

import threading
import time

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
UA = "MiBand6Manager/1.0 (open-source desktop app for Xiaomi Mi Band 6)"
MIN_INTERVAL = 1.1   # giây giữa hai yêu cầu (chính sách của Nominatim: tối đa 1 yêu cầu/giây)
_lock = threading.Lock()
_last = 0.0


def area_key(lat: float, lon: float, lang: str) -> str:
    """Khóa lưu kết quả: vùng khoảng 1 km và ngôn ngữ của tên."""
    return f"{lang}:{lat:.2f},{lon:.2f}"


def parse_key(key: str) -> tuple[float, float, str]:
    lang, coords = key.split(":", 1)
    lat, lon = coords.split(",")
    return float(lat), float(lon), lang


def place_from_nominatim(d: dict) -> dict | None:
    a = d.get("address") or {}
    country = a.get("country")
    if not country:
        return None
    city = (a.get("city") or a.get("town") or a.get("municipality") or a.get("village") or a.get("county")
            or a.get("state_district") or a.get("state") or d.get("name") or country)
    return {"city": city, "country": country, "cc": (a.get("country_code") or "").upper()}


def reverse(lat: float, lon: float, lang: str) -> dict | None:
    """{city, country, cc} của vùng quanh tọa độ, hoặc None nếu ở ngoài lãnh thổ quốc gia nào (biển…)."""
    import requests

    global _last
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(NOMINATIM, params={"format": "jsonv2", "lat": f"{lat:.2f}", "lon": f"{lon:.2f}",
                                                "zoom": 10, "addressdetails": 1, "accept-language": lang},
                             headers={"User-Agent": UA}, timeout=15)
        finally:
            _last = time.monotonic()
    r.raise_for_status()
    return place_from_nominatim(r.json())


def demo_place(lat: float, lon: float, lang: str) -> dict:
    """Nơi giả lập cho chế độ xem thử (không gọi mạng)."""
    district = "1" if lat < 10.78 else "3" if lon < 106.70 else "Bình Thạnh"
    city = f"Quận {district}" if district != "Bình Thạnh" else "Bình Thạnh"
    return {"city": city, "country": "Việt Nam" if lang == "vi" else "Vietnam", "cc": "VN"}
