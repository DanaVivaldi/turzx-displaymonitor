"""Temperature unit (°C / °F). Everything inside the program stays in °C (colour thresholds, the red background, sensors): values are converted
only when they are turned into text, so `temperature_unit: fahrenheit` never changes a limit or a colour."""
import re

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def norm(unit) -> str:
    """'F' for fahrenheit / f / °F, otherwise 'C'."""
    return "F" if str(unit or "").strip().lower().lstrip("°") in ("f", "fahrenheit") else "C"


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def convert(c, unit):
    """A temperature in °C -> the chosen unit (None stays None)."""
    return c if c is None or norm(unit) == "C" else c_to_f(c)


def delta(d, unit):
    """A temperature DIFFERENCE (no +32 offset)."""
    return d * 9.0 / 5.0 if norm(unit) == "F" else d


def symbol(unit) -> str:
    return "°F" if norm(unit) == "F" else "°C"


def swap_symbol(text: str, unit) -> str:
    """Literal '°C' in a label / format string -> '°F'."""
    return text.replace("°C", "°F") if norm(unit) == "F" and "°C" in text else text


def convert_numbers(text: str, unit) -> str:
    """'61 63 60' (a string of °C readings) -> '142 145 140'."""
    if norm(unit) == "C":
        return text
    return NUMBER.sub(lambda m: f"{c_to_f(float(m.group())):.{1 if '.' in m.group() else 0}f}", text)


def is_temperature_key(key: str) -> bool:
    """Snapshot keys whose value is a temperature in °C (not a percentage that merely shares the colour scheme)."""
    k = str(key)
    if k.endswith(("_pct", "_load")):
        return False
    return "temp" in k or k.startswith(("mb_t", "disk_max_")) or k in ("gpu_hotspot", "weather_feels")
