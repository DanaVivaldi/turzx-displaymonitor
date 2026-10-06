"""Optional weather (Open-Meteo: free, no account, no API key).

Off by default. Enable in config.yaml:

    weather:
      enabled: true
      latitude: 43.7
      longitude: 13.2
      city: "Senigallia"      # only a label for your pages: {weather_city}

A background thread fetches the current conditions every `refresh_min` minutes (30 by default). It never blocks the display loop,
retries with exponential backoff (5, 10, 20, 40, 80 s) so it survives a network that is still coming up at boot, and keeps the last good
reading in logs/weather.json so the screen never shows a stale 0 degrees after a restart (idea from the TuringMonitor project).
Nothing else is ever sent: the only request is a GET to api.open-meteo.com with your coordinates (see docs/CONFIGURATION.md).
"""
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "logs", "weather.json")
URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> short text
WMO = {
    "en": {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
           55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
           66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Showers",
           81: "Showers", 82: "Violent showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm", 96: "Thunderstorm, hail",
           99: "Thunderstorm, hail"},
    "it": {0: "Sereno", 1: "Prevalentemente sereno", 2: "Parzialmente nuvoloso", 3: "Coperto", 45: "Nebbia", 48: "Nebbia gelata",
           51: "Pioggerella", 53: "Pioggerella", 55: "Pioggerella intensa", 56: "Pioggerella gelata", 57: "Pioggerella gelata",
           61: "Pioggia debole", 63: "Pioggia", 65: "Pioggia forte", 66: "Pioggia gelata", 67: "Pioggia gelata", 71: "Neve debole",
           73: "Neve", 75: "Neve forte", 77: "Granelli di neve", 80: "Rovesci", 81: "Rovesci", 82: "Rovesci violenti",
           85: "Rovesci di neve", 86: "Rovesci di neve", 95: "Temporale", 96: "Temporale con grandine", 99: "Temporale con grandine"},
}


class Weather:
    def __init__(self, cfg: dict, lang: str = "en"):
        self.cfg = cfg or {}
        self.lang = lang if lang in WMO else "en"
        self.refresh_s = max(5, float(self.cfg.get("refresh_min", 30))) * 60
        self._data: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._stamp = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled")) and "latitude" in self.cfg and "longitude" in self.cfg

    def start(self):
        if not self.enabled:
            return
        self._load_cache()
        self._thread = threading.Thread(target=self._loop, name="weather", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def snapshot(self) -> dict:
        with self._lock:
            data = dict(self._data)
            if data:
                data["weather_age_min"] = (time.time() - self._stamp) / 60
            return data

    # -- internals ------------------------------------------------------------------------------
    def _publish(self, current: dict, stamp: float):
        code = int(current.get("weather_code", -1))
        data = {
            "weather_temp": current.get("temperature_2m"), "weather_feels": current.get("apparent_temperature"),
            "weather_humidity": current.get("relative_humidity_2m"), "weather_wind": current.get("wind_speed_10m"),
            "weather_code": code, "weather_desc": WMO[self.lang].get(code, "?"), "weather_city": self.cfg.get("city", ""),
            "weather_age_min": None,
        }
        with self._lock:
            self._data = data
            self._stamp = stamp

    def _load_cache(self):
        try:
            with open(CACHE, encoding="utf-8") as f:
                c = json.load(f)
            self._publish(c["current"], float(c["stamp"]))
            log.info("weather: restored the last reading from %s", CACHE)
        except (OSError, ValueError, KeyError):
            pass

    def _fetch(self) -> dict:
        q = urllib.parse.urlencode({
            "latitude": self.cfg["latitude"], "longitude": self.cfg["longitude"], "timezone": "auto",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        })
        req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "turzx-displaymonitor"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["current"]

    def _loop(self):
        delay = 0.0
        while not self._stop.wait(delay):
            for attempt, wait in enumerate((0, 5, 10, 20, 40, 80)):       # exponential backoff
                if self._stop.wait(wait):
                    return
                try:
                    cur = self._fetch()
                    self._publish(cur, time.time())
                    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                    with open(CACHE, "w", encoding="utf-8") as f:
                        json.dump({"stamp": time.time(), "current": cur}, f)
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning("weather fetch failed (attempt %d): %s", attempt + 1, e)
            delay = self.refresh_s
