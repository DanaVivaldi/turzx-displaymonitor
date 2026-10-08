"""Configuration sanity: a typo in config.yaml must never stop the program.

Every numeric setting is parsed, range-checked and, when it is wrong, replaced by a safe value with a warning in the log.
`display_settings()` is the single place that knows what the panel can take (tile must divide both 320 and 480, ...).
"""
from __future__ import annotations

import logging
from math import gcd

log = logging.getLogger(__name__)
HW_W, HW_H = 320, 480
TILES = tuple(t for t in range(1, gcd(HW_W, HW_H) + 1) if HW_W % t == 0 and HW_H % t == 0)      # 1, 2, 4, 5, 8, 10, 16, 20, 32, 40, 80, 160


def number(value, default, lo, hi, kind=float, name="value", warnings: list | None = None):
    """`value` as a number in [lo, hi]; anything else gives `default` (and a warning)."""
    try:
        if isinstance(value, bool):
            raise ValueError("a boolean is not a number")
        v = kind(float(value)) if kind is int else float(value)
    except (TypeError, ValueError):
        if value is not None and warnings is not None:
            warnings.append(f"{name}: {value!r} is not a number, using {default}")
        return default
    if v != v or v < lo or v > hi:                       # NaN or out of range
        if warnings is not None:
            warnings.append(f"{name}: {v} is outside {lo}..{hi}, using {default}")
        return default
    return v


def display_settings(cfg: dict | None, fallback: dict | None = None) -> tuple[dict, list[str]]:
    """The `display:` section with every value checked. `fallback` supplies the values to keep when one is invalid (a hot reload)."""
    cfg, fb, w = dict(cfg or {}), dict(fallback or {}), []
    out = {
        "rotate": int(number(cfg.get("rotate"), fb.get("rotate", 1), 1, 3, int, "display.rotate", w)),
        "brightness": int(round(number(cfg.get("brightness"), fb.get("brightness", 100), 0, 100, float, "display.brightness", w))),
        "max_block_px": int(number(cfg.get("max_block_px"), fb.get("max_block_px", 12800), 320, 51200, int, "display.max_block_px", w)),
        "flood_bytes": int(number(cfg.get("flood_bytes"), fb.get("flood_bytes", 2_200_000), 0, 20_000_000, int, "display.flood_bytes", w)),
        "refresh_band": int(number(cfg.get("refresh_band"), fb.get("refresh_band", 8), 0, HW_H, int, "display.refresh_band", w)),
        "band_budget": int(number(cfg.get("band_budget"), fb.get("band_budget", 24_000), 0, 10_000_000, int, "display.band_budget", w)),
        "merge_gap": int(number(cfg.get("merge_gap"), fb.get("merge_gap", 4), 0, 160, int, "display.merge_gap", w)),
        "reset_on_connect": bool(cfg.get("reset_on_connect", fb.get("reset_on_connect", False))),
    }
    if out["rotate"] == 2:
        w.append("display.rotate: 2 is not supported (the panel is kept in portrait), using 1")
        out["rotate"] = 1
    tile = number(cfg.get("tile"), fb.get("tile", 2), 1, HW_W, int, "display.tile", w)
    if int(tile) not in TILES:
        w.append(f"display.tile: {int(tile)} does not divide 320 and 480 (allowed: {', '.join(map(str, TILES))}), using {fb.get('tile', 2)}")
        tile = fb.get("tile", 2)
    out["tile"] = int(tile)
    return out, w


def top_level(cfg: dict | None) -> tuple[dict, list[str]]:
    """refresh_s, rotate_s, peek_s: positive numbers the main loop divides / sleeps by."""
    cfg, w = cfg or {}, []
    return {
        "refresh_s": number(cfg.get("refresh_s"), 1.0, 0.1, 60.0, float, "refresh_s", w),
        "rotate_s": number(cfg.get("rotate_s"), 0.0, 0.0, 86400.0, float, "rotate_s", w),
        "peek_s": number(cfg.get("peek_s"), 30.0, 1.0, 86400.0, float, "peek_s", w),
    }, w


def warn_all(warnings: list[str]):
    for msg in warnings:
        log.warning("config: %s", msg)
