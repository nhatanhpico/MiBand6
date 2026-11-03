"""Thời tiết cho vòng tay: lấy từ Open-Meteo (miễn phí, không cần khóa) rồi dựng các gói gửi qua Bluetooth.

- Vị trí: thành phố người dùng chọn (tìm bằng API geocoding của Open-Meteo), hoặc tự động theo địa chỉ IP
  (ipapi.co, dự phòng ipwho.is). Chỉ tọa độ được gửi tới Open-Meteo.
- Mã thời tiết WMO của Open-Meteo được đổi sang mã biểu tượng của vòng tay Huami theo bảng của Gadgetbridge
  (HuamiWeatherConditions). Mô tả gửi theo ngôn ngữ của vòng tay (tiếng Việt hoặc tiếng Anh).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import protocol as P

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
IP_LOCATORS = ("https://ipapi.co/json/", "https://ipwho.is/")
UA = "MiBand6Manager (https://github.com/) weather"

# mã biểu tượng của vòng tay (Gadgetbridge HuamiWeatherConditions) -> (tiếng Việt, tiếng Anh)
CONDITIONS = {
    0: ("Trời quang", "Clear"), 1: ("Có mây", "Partly cloudy"), 2: ("Nhiều mây", "Cloudy"),
    3: ("Mưa rào", "Showers"), 4: ("Dông", "Thunderstorm"), 5: ("Mưa đá", "Hail"), 6: ("Mưa tuyết", "Sleet"),
    7: ("Mưa nhỏ", "Light rain"), 8: ("Mưa", "Rain"), 9: ("Mưa to", "Heavy rain"), 10: ("Mưa rất to", "Very heavy rain"),
    11: ("Mưa cực lớn", "Extreme rain"), 12: ("Mưa xối xả", "Torrential rain"), 13: ("Tuyết và nắng", "Snow and sun"),
    14: ("Tuyết nhẹ", "Light snow"), 15: ("Tuyết", "Snow"), 16: ("Tuyết dày", "Heavy snow"),
    17: ("Bão tuyết", "Blizzard"), 18: ("Sương mù", "Fog"), 19: ("Mưa phùn", "Drizzle"), 20: ("Gió mưa", "Wind and rain"),
}
AQI_LEVELS = ((50, "Tốt", "Good"), (100, "Trung bình", "Moderate"), (150, "Kém", "Unhealthy for sensitive groups"),
              (200, "Xấu", "Unhealthy"), (300, "Rất xấu", "Very unhealthy"), (10_000, "Nguy hại", "Hazardous"))


def huami_condition(wmo: int) -> int:
    """Mã thời tiết WMO (Open-Meteo) -> mã biểu tượng của vòng tay, theo cách Gadgetbridge đổi mã OpenWeatherMap."""
    table = {
        0: 0, 1: 1, 2: 1, 3: 2, 45: 18, 48: 18,
        51: 19, 53: 19, 55: 19, 56: 19, 57: 19,
        61: 7, 63: 8, 65: 9, 66: 8, 67: 9,
        71: 14, 73: 15, 75: 16, 77: 14,
        80: 7, 81: 8, 82: 9, 85: 6, 86: 6,
        95: 4, 96: 5, 99: 5,
    }
    return table.get(int(wmo), 0)


def condition_text(code: int, lang: str) -> str:
    vi, en = CONDITIONS.get(code, CONDITIONS[0])
    return vi if lang == "vi" else en


def aqi_text(aqi: int | None, lang: str) -> str:
    if aqi is None or aqi < 0:
        return ""
    for limit, vi, en in AQI_LEVELS:
        if aqi <= limit:
            return vi if lang == "vi" else en
    return ""


def beaufort(kmh: float) -> int:
    for level, limit in enumerate((1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118)):
        if kmh < limit:
            return level
    return 12


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    detail: str = ""     # tỉnh / quốc gia, để phân biệt các nơi trùng tên

    def as_dict(self) -> dict:
        return {"name": self.name, "lat": self.lat, "lon": self.lon, "detail": self.detail}


@dataclass
class Weather:
    place: Place
    time: int                  # thời điểm số liệu (giây)
    tz_seconds: int            # độ lệch múi giờ của nơi đó
    code: int                  # mã biểu tượng vòng tay
    temp: float
    humidity: int | None = None
    wind_kmh: float | None = None
    aqi: int | None = None
    days: list[tuple[int, float, float]] = field(default_factory=list)   # (mã, cao nhất, thấp nhất), từ hôm nay
    sunrise: tuple[int, int] | None = None
    sunset: tuple[int, int] | None = None

    def summary(self, lang: str) -> dict:
        today = self.days[0] if self.days else (self.code, self.temp, self.temp)
        return {"place": self.place.name, "temp": round(self.temp), "text": condition_text(self.code, lang),
                "code": self.code, "high": round(today[1]), "low": round(today[2]), "humidity": self.humidity,
                "aqi": self.aqi, "time": self.time}


def packets(w: Weather, lang: str = "en", fahrenheit: bool = False) -> list[bytes]:
    """Các gói gửi vòng tay, theo thứ tự Gadgetbridge: hiện tại, chất lượng không khí, dự báo, địa điểm,
    gió/độ ẩm, mặt trời mọc/lặn."""
    conv = (lambda c: c * 9 / 5 + 32) if fahrenheit else (lambda c: c)
    tzq = w.tz_seconds // 900
    text = condition_text(w.code, lang)
    days = w.days or [(w.code, w.temp, w.temp)]
    forecast = [(w.code if i == 0 else code, conv(hi), conv(lo), text if i == 0 else condition_text(code, lang))
                for i, (code, hi, lo) in enumerate(days)]
    out = [
        P.weather_current(w.time, tzq, w.code, conv(w.temp), text),
        P.weather_aqi(w.time, tzq, w.aqi if w.aqi is not None else -1, aqi_text(w.aqi, lang)),
        P.weather_forecast(w.time, tzq, forecast),
        P.weather_location(w.place.name),
    ]
    if w.wind_kmh is not None or w.humidity is not None:
        out.append(P.weather_wind_humidity(w.time, tzq, str(beaufort(w.wind_kmh or 0)),
                                           f"{w.humidity}%" if w.humidity is not None else ""))
    if w.sunrise and w.sunset:
        out.append(P.weather_sun(w.time, tzq, w.sunrise, w.sunset))
    return out


# ---------------------------------------------------------------- mạng (gọi trong luồng riêng)


def _get(url: str, params: dict | None = None, timeout: float = 15) -> dict:
    import requests

    r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def locate_by_ip() -> Place:
    """Vị trí gần đúng theo địa chỉ IP của mạng đang dùng."""
    last = None
    for url in IP_LOCATORS:
        try:
            d = _get(url, timeout=10)
        except Exception as e:  # noqa: BLE001 - thử dịch vụ khác
            last = e
            continue
        lat, lon = d.get("latitude"), d.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            region = d.get("region") or ""
            country = d.get("country_name") or d.get("country") or ""
            return Place(str(d.get("city") or region or country or "?"), float(lat), float(lon),
                         ", ".join(x for x in (region, country) if x))
    raise OSError(f"không xác định được vị trí: {last}")


def search_places(query: str, lang: str = "en", count: int = 6) -> list[Place]:
    d = _get(GEOCODE_URL, {"name": query, "count": count, "language": lang, "format": "json"})
    out = []
    for r in d.get("results") or []:
        detail = ", ".join(x for x in (r.get("admin1"), r.get("country")) if x)
        out.append(Place(str(r.get("name")), float(r["latitude"]), float(r["longitude"]), detail))
    return out


def _hm(iso: str | None) -> tuple[int, int] | None:
    if not iso:
        return None
    t = dt.datetime.fromisoformat(iso)
    return t.hour, t.minute


def fetch(place: Place) -> Weather:
    d = _get(FORECAST_URL, {
        "latitude": place.lat, "longitude": place.lon, "timezone": "auto", "forecast_days": P.WEATHER_MAX_DAYS,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
    })
    cur, daily = d["current"], d.get("daily") or {}
    days = [(huami_condition(c), hi, lo) for c, hi, lo in
            zip(daily.get("weather_code") or [], daily.get("temperature_2m_max") or [], daily.get("temperature_2m_min") or [])
            if hi is not None and lo is not None]
    aqi = None
    try:
        a = _get(AIR_URL, {"latitude": place.lat, "longitude": place.lon, "current": "us_aqi"}, timeout=10)
        aqi = a.get("current", {}).get("us_aqi")
        aqi = int(aqi) if aqi is not None else None
    except Exception:  # noqa: BLE001 - không có chất lượng không khí thì thôi
        aqi = None
    return Weather(
        place=place, time=int(dt.datetime.now(dt.timezone.utc).timestamp()), tz_seconds=int(d.get("utc_offset_seconds") or 0),
        code=huami_condition(cur.get("weather_code") or 0), temp=float(cur.get("temperature_2m") or 0),
        humidity=int(cur["relative_humidity_2m"]) if cur.get("relative_humidity_2m") is not None else None,
        wind_kmh=float(cur["wind_speed_10m"]) if cur.get("wind_speed_10m") is not None else None,
        aqi=aqi, days=days,
        sunrise=_hm((daily.get("sunrise") or [None])[0]), sunset=_hm((daily.get("sunset") or [None])[0]),
    )


def demo(place: Place | None = None) -> Weather:
    """Thời tiết giả lập (chế độ xem thử, kiểm thử): không gọi mạng."""
    place = place or Place("TP. Hồ Chí Minh", 10.7765, 106.7009, "Việt Nam")
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    return Weather(place, now, 7 * 3600, 1, 31.4, 68, 11.0, 72,
                   [(1, 33, 25), (8, 32, 25), (3, 31, 24), (2, 32, 25), (0, 33, 25), (7, 31, 24), (1, 32, 25)],
                   (5, 52), (17, 31))
