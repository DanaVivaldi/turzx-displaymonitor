"""Red background tint: the background turns red as the CPU / GPU / RAM temperatures or utilisation climb.

    alerts:
      tint:
        enabled: true
        temp: [75, 95]     # °C (cpu, gpu, ram): no red at the first value, full red at the second
        load: [85, 100]    # % utilisation (cpu, gpu, ram)
        strength: 0.5      # how red the background gets at full (0..1)
        steps: 6           # the red comes in this many levels: every change redraws the whole screen (about 2 s on this link),
                           # so it is quantised and smoothed instead of following every spike

The tint only changes the colours of the background: no text, no layout, nothing else on screen moves.
"""
from __future__ import annotations

TEMP_KEYS = ("cpu_temp", "gpu_temp", "ram_temp")
LOAD_KEYS = ("cpu_load", "gpu_load", "mem_pct")


def _norm(v, lo: float, hi: float) -> float:
    if v is None or hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (float(v) - lo) / (hi - lo)))


class Tint:
    def __init__(self, cfg=None):
        self.level = 0                     # the quantised level currently shown (0..steps)
        self._smooth = 0.0
        self._t = None
        self.configure(cfg)

    def configure(self, cfg):
        """`cfg` is the whole `alerts:` section; a plain list (the older page rules) means no tint."""
        section = cfg.get("tint") if isinstance(cfg, dict) else None
        c = section if isinstance(section, dict) else {}
        self.enabled = isinstance(section, dict) and bool(c.get("enabled", True))
        self.temp = tuple(float(x) for x in c.get("temp", (75, 95)))
        self.load = tuple(float(x) for x in c.get("load", (85, 100)))
        self.strength = max(0.0, min(1.0, float(c.get("strength", 0.5))))
        self.steps = max(1, int(c.get("steps", 6)))
        if not self.enabled:
            self.level, self._smooth = 0, 0.0

    def target(self, snap: dict) -> float:
        """The hottest / busiest of the six readings, 0..1."""
        t = max((_norm(snap.get(k), *self.temp) for k in TEMP_KEYS), default=0.0)
        u = max((_norm(snap.get(k), *self.load) for k in LOAD_KEYS), default=0.0)
        return max(t, u)

    def update(self, snap: dict, now: float) -> int:
        """Smooth the target (quick to redden, slow to cool) and return the quantised level 0..steps."""
        if not self.enabled:
            return 0
        dt = 1.0 if self._t is None else max(0.0, min(5.0, now - self._t))
        self._t = now
        tgt = self.target(snap)
        rate = 0.45 if tgt > self._smooth else 0.12          # per second
        self._smooth += (tgt - self._smooth) * min(1.0, rate * dt)
        want = self._smooth * self.steps
        if abs(want - self.level) >= 0.6:                    # hysteresis: a level changes only when clearly past it
            self.level = int(round(want))
        return self.level

    @property
    def alpha(self) -> float:
        """How much red to mix into the background right now (0 = none)."""
        return self.level / self.steps * self.strength if self.enabled else 0.0
