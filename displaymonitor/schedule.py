"""Night schedule: dim the display (or switch it off) between two times of day."""
import datetime


def _minutes(value) -> int:
    """'23:00' -> 1380. YAML reads an unquoted 23:00 as the sexagesimal integer 1380 (= minutes), so an int is taken as minutes."""
    if isinstance(value, int):
        return value
    h, m = str(value).strip().split(":")[:2]
    return int(h) * 60 + int(m)


def night_active(cfg: dict | None, now: datetime.datetime | None = None) -> bool:
    """True inside the `night: {enabled, from, to}` window. The window may wrap over midnight (23:00 -> 07:00)."""
    cfg = cfg or {}
    if not cfg.get("enabled"):
        return False
    try:
        a, b = _minutes(cfg.get("from", "23:00")), _minutes(cfg.get("to", "07:00"))
    except (ValueError, TypeError):
        return False
    if a == b:
        return False
    n = now or datetime.datetime.now()
    cur = n.hour * 60 + n.minute
    return a <= cur < b if a < b else (cur >= a or cur < b)


def night_brightness(cfg: dict | None) -> int:
    """Backlight % during the night window: 0 for mode 'off', else `brightness` (default 10)."""
    cfg = cfg or {}
    if str(cfg.get("mode", "dim")) == "off":
        return 0
    return max(0, min(100, int(cfg.get("brightness", 10))))
