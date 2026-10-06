"""Configuration handling, alerts, hot-reload helpers, weather decoding."""
from displaymonitor.app import alert_active, config_signature, enabled_pages, load_config
from displaymonitor.sensors import rate_str, uptime_str
from displaymonitor.weather import WMO, Weather


def test_example_config_loads():
    cfg, pages = load_config(examples=True)
    assert cfg["display"]["rotate"] in (1, 3)
    ids = [p["id"] for p in pages["pages"]]
    assert ids[0] == "overview" and len(ids) == len(set(ids))


def test_alert_expressions_are_safe_and_none_tolerant():
    assert alert_active("cpu_temp is not None and cpu_temp >= 85", {"cpu_temp": 90})
    assert not alert_active("cpu_temp is not None and cpu_temp >= 85", {"cpu_temp": 40})
    assert not alert_active("cpu_temp >= 85", {})                   # missing sensor: no alert, no crash
    assert not alert_active("__import__('os').getcwd()", {})        # no builtins


def test_pages_requiring_a_disabled_feature_are_hidden():
    cfg, pages = load_config(examples=True)
    off = [p["id"] for p in enabled_pages(pages, cfg)]
    on = [p["id"] for p in enabled_pages(pages, {**cfg, "weather": {"enabled": True}})]
    assert "weather" not in off and "weather" in on


def test_config_signature_is_a_stable_tuple():
    a = config_signature()
    assert isinstance(a, tuple) and a == config_signature() and len(a) >= 2


def test_formatting_helpers():
    assert rate_str(500) == ("500", "B/s") and rate_str(1500) == ("1.5", "KB/s") and rate_str(2_500_000)[1] == "MB/s"
    assert uptime_str(3 * 86400 + 5 * 3600) == "3d 05h" and uptime_str(3 * 86400 + 5 * 3600, "it") == "3g 05h"
    assert uptime_str(4500) == "1h 15m"


def test_weather_is_off_by_default_and_codes_are_translated():
    assert Weather({}).enabled is False and Weather({}).snapshot() == {}
    assert Weather({"enabled": True}).enabled is False             # needs coordinates too
    assert WMO["en"][0] == "Clear" and WMO["it"][95] == "Temporale"
    w = Weather({"enabled": True, "latitude": 1, "longitude": 2, "city": "X"}, "it")
    w._publish({"temperature_2m": 20.5, "weather_code": 3}, 0.0)
    snap = w.snapshot()
    assert snap["weather_temp"] == 20.5 and snap["weather_desc"] == "Coperto" and snap["weather_city"] == "X"
