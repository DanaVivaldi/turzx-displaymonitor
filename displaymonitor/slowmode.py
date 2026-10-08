"""`display.mode: slow` - keep the panel's traffic for what matters.

On a slow link every pixel that changes costs time. In slow mode the readings that drive the red tint and the CPU / GPU / RAM
numbers stay live, while everything else (network rates and sparklines, per-thread squares, disks, processes, uptime, ping,
motherboard probes, weather ...) is only refreshed every `display.slow.noncritical_s` seconds. Between refreshes the renderer is
simply given the previous values, so nothing changes on screen and nothing is sent. No extra polling and no animation: it is a
filter on the snapshot the renderer already receives.
"""
from __future__ import annotations

CRITICAL_PREFIXES = ("cpu_load", "cpu_temp", "cpu_power", "cpu_clock", "gpu_load", "gpu_temp", "gpu_hotspot", "gpu_vram", "gpu_power",
                     "mem_", "vmem_pct", "ram_temp", "hw_", "update_available")
CRITICAL_EXACT = frozenset({"time", "date", "cpu_name", "gpu_short", "mb_name", "language"})


def is_critical(key: str) -> bool:
    k = str(key)
    return k in CRITICAL_EXACT or k.startswith(CRITICAL_PREFIXES)


class SlowFilter:
    def __init__(self, noncritical_s: float = 10.0):
        self.noncritical_s = float(noncritical_s)
        self._held: dict = {}
        self._t: float | None = None

    def apply(self, snap: dict, now: float) -> dict:
        """The snapshot to draw: critical keys live, the rest as of the last refresh."""
        if self._t is None or now - self._t >= self.noncritical_s:
            self._t = now
            self._held = {k: v for k, v in snap.items() if not is_critical(k)}
        out = dict(self._held)
        out.update({k: v for k, v in snap.items() if is_critical(k)})
        return out
