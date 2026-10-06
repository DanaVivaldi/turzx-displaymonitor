"""Dynamic temperature alarm: when a component goes above its limit the whole screen becomes an alarm with its details.

Configured in config.yaml:

    alerts:
      temperature:
        enabled: true
        threshold: 85          # °C, for every component ...
        thresholds: {gpu: 80}  # ... unless overridden here (cpu | gpu | ram | disk | mb)
        hysteresis: 3          # the alarm ends once the temperature is `hysteresis` °C below its limit
        min_show_s: 15         # ... and never before it has been shown this long
        rotate_s: 6            # several components too hot: they take turns on screen
        wake: true             # backlight to 100 % while the alarm is shown (even during the night schedule)
      pages: []                # the older "show this page when ..." rules (see alert_active in app.py)
"""
from __future__ import annotations

COMPONENTS = ("cpu", "gpu", "ram", "disk", "mb")

TEXT = {
    "en": {"title": "OVERHEATING", "cpu": "CPU", "gpu": "GPU", "ram": "MEMORY", "disk": "DISK", "mb": "MOTHERBOARD",
           "over": "+{d:.0f}°C above the limit", "limit": "limit {t:.0f}°C",
           "load": "Load", "power": "Power", "clock": "Clock", "coremax": "Hottest core", "hotspot": "Hot spot", "fan": "Fan",
           "vram": "VRAM", "modules": "Modules", "usage": "In use", "kind": "Type", "used": "Space used", "life": "Health",
           "others": "Other disks", "probes": "Probes", "fans": "Fans", "vcore": "Vcore", "temp": "Temperature"},
    "it": {"title": "SURRISCALDAMENTO", "cpu": "CPU", "gpu": "GPU", "ram": "MEMORIA", "disk": "DISCO", "mb": "SCHEDA MADRE",
           "over": "+{d:.0f}°C sopra il limite", "limit": "limite {t:.0f}°C",
           "load": "Carico", "power": "Potenza", "clock": "Frequenza", "coremax": "Core più caldo", "hotspot": "Hot spot", "fan": "Ventola",
           "vram": "VRAM", "modules": "Moduli", "usage": "In uso", "kind": "Tipo", "used": "Spazio usato", "life": "Salute",
           "others": "Altri dischi", "probes": "Sonde", "fans": "Ventole", "vcore": "Vcore", "temp": "Temperatura"},
}


def _v(x, fmt: str, unit: str = "") -> str:
    return "--" if x is None else format(x, fmt) + unit


def _candidates(snap: dict, tr: dict) -> dict:
    """component -> (temperature, device name, detail rows) for every component that currently has a reading."""
    out = {}
    t = snap.get("cpu_temp") if snap.get("cpu_temp") is not None else snap.get("cpu_temp_max")
    if t is not None:
        rows = [(tr["load"], _v(snap.get("cpu_load"), ".0f", "%")), (tr["power"], _v(snap.get("cpu_power"), ".0f", " W")),
                (tr["clock"], _v(snap.get("cpu_clock"), ".2f", " GHz"))]
        if snap.get("cpu_temp_max") is not None and snap.get("cpu_temp_max") != t:
            rows.append((tr["coremax"], _v(snap["cpu_temp_max"], ".0f", "°C")))
        out["cpu"] = (t, str(snap.get("cpu_name") or "CPU"), rows)
    t = snap.get("gpu_temp")
    if t is not None:
        fan = _v(snap.get("gpu_fan"), ".0f", " rpm") if snap.get("gpu_fan") is not None else _v(snap.get("gpu_fan_pct"), ".0f", "%")
        rows = [(tr["load"], _v(snap.get("gpu_load"), ".0f", "%")), (tr["hotspot"], _v(snap.get("gpu_hotspot"), ".0f", "°C")),
                (tr["power"], _v(snap.get("gpu_power"), ".0f", " W")), (tr["fan"], fan),
                (tr["vram"], _v(snap.get("gpu_vram_pct"), ".0f", "%"))]
        out["gpu"] = (t, str(snap.get("gpu_short") or "GPU"), rows)
    t = snap.get("ram_temp")
    if t is not None:
        rows = [(tr["modules"], (snap.get("ram_temps_str") or "--") + "°C"), (tr["usage"], _v(snap.get("mem_pct"), ".0f", "%"))]
        if snap.get("mem_used") is not None and snap.get("mem_total") is not None:
            rows.append((tr["used"], f"{snap['mem_used']:.1f} / {snap['mem_total']:.0f} GB"))
        out["ram"] = (t, "DDR", rows)
    disks = [d for d in (snap.get("disks") or []) if d.get("temp") is not None]
    if disks:
        d = max(disks, key=lambda x: x["temp"])
        rows = [(tr["kind"], str(d.get("kind") or "--")), (tr["used"], _v(d.get("used_pct"), ".0f", "%")),
                (tr["life"], _v(d.get("life"), ".0f", "%")), (tr["others"], str(len(disks) - 1))]
        out["disk"] = (d["temp"], str(d.get("name") or tr["disk"]), rows)
    t = snap.get("mb_t_max")
    if t is not None:
        probes = " ".join(f"{snap[k]:.0f}" for k in sorted(snap) if k.startswith("mb_t") and k != "mb_t_max" and snap.get(k) is not None)
        rows = [(tr["probes"], (probes or "--") + "°C"), (tr["fans"], str(snap.get("mb_fan_count", "--"))),
                (tr["vcore"], _v(snap.get("mb_vcore"), ".3f", " V"))]
        out["mb"] = (t, str(snap.get("mb_name") or tr["mb"]), rows)
    return out


class TempAlarm:
    """Evaluates the alarm on every frame and remembers what was shown (hysteresis, minimum duration, rotation)."""

    def __init__(self, cfg: dict | None = None, lang: str = "en"):
        self.active: set[str] = set()
        self._since = 0.0
        self._last: list[dict] = []
        self._held: set[str] = set()
        self.configure(cfg, lang)

    def configure(self, cfg, lang: str = "en"):
        """`cfg` is the whole `alerts:` section of config.yaml (a list = only the older page rules, no temperature alarm)."""
        section = cfg.get("temperature") if isinstance(cfg, dict) else None
        c = section if isinstance(section, dict) else {}
        self.enabled = isinstance(section, dict) and bool(c.get("enabled", True))
        self.default = float(c.get("threshold", 85))
        self.limits = {k: float(v) for k, v in (c.get("thresholds") or {}).items()}
        self.hyst = float(c.get("hysteresis", 3))
        self.min_show = float(c.get("min_show_s", 15))
        self.rotate_s = max(1.0, float(c.get("rotate_s", 6)))
        self.wake = bool(c.get("wake", True))
        self.tr = TEXT.get(lang, TEXT["en"])
        if not self.enabled:
            self.active.clear()
            self._held.clear()
            self._last = []

    def limit(self, comp: str) -> float:
        return self.limits.get(comp, self.default)

    def update(self, snap: dict, now: float) -> dict | None:
        """The alarm to show right now (a dict for Renderer.render_alert), or None."""
        if not self.enabled:
            return None
        cands = _candidates(snap, self.tr)
        for comp, (temp, _name, _rows) in cands.items():
            lim = self.limit(comp)
            if temp >= lim or (comp in self.active and temp >= lim - self.hyst):
                if not self.active:
                    self._since = now
                self.active.add(comp)
            else:
                self.active.discard(comp)
        for comp in [c for c in self.active if c not in cands]:
            self.active.discard(comp)
        showing = set(self.active)
        if not showing and self._held and now - self._since < self.min_show:
            showing = {c for c in self._held if c in cands}          # cooled down, but still inside the minimum display time
        self._held = showing
        alarms = []
        for comp in showing:
            temp, name, rows = cands[comp]
            lim = self.limit(comp)
            alarms.append({"comp": comp, "label": self.tr[comp], "name": name, "temp": temp, "limit": lim,
                           "excess": temp - lim, "rows": rows, "title": self.tr["title"],
                           "over": self.tr["over"].format(d=max(0.0, temp - lim)), "limit_text": self.tr["limit"].format(t=lim)})
        alarms.sort(key=lambda a: -a["excess"])
        self._last = alarms
        if not alarms:
            return None
        n = len(self._last)
        pick = int(now // self.rotate_s) % n if n > 1 else 0
        return {**self._last[pick], "pos": pick + 1, "count": n}
