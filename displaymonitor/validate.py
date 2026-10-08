"""Configuration sanity: a typo in config.yaml must never stop the program.

Every numeric setting is parsed, range-checked and, when it is wrong, replaced by a safe value with a warning in the log.
`display_settings()` is the single place that knows what the panel can take (tile must divide both 320 and 480, ...).
"""
from __future__ import annotations

import logging
from math import gcd

log = logging.getLogger(__name__)
HW_W, HW_H = 320, 480
MODES = ("normal", "slow")
MIN_TX_BUDGET = 1024                 # = txsched.MIN_BUDGET (kept here so validate.py has no dependency on the driver)
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

    def keep(name, default):
        """What to use when `name` is unusable: the current value (a hot reload) - but only if the key is present in the file.
        A key that was REMOVED from the file goes back to its default."""
        return fb.get(name, default) if name in cfg else default
    out = {
        "rotate": int(number(cfg.get("rotate"), keep("rotate", 1), 1, 3, int, "display.rotate", w)),
        "brightness": int(round(number(cfg.get("brightness"), keep("brightness", 100), 0, 100, float, "display.brightness", w))),
        "max_block_px": int(number(cfg.get("max_block_px"), keep("max_block_px", 12800), 320, 51200, int, "display.max_block_px", w)),
        "flood_bytes": int(number(cfg.get("flood_bytes"), keep("flood_bytes", 2_200_000), 0, 20_000_000, int, "display.flood_bytes", w)),
        "refresh_band": int(number(cfg.get("refresh_band"), keep("refresh_band", 8), 0, HW_H, int, "display.refresh_band", w)),
        "band_budget": int(number(cfg.get("band_budget"), keep("band_budget", 24_000), 0, 10_000_000, int, "display.band_budget", w)),
        "merge_gap": int(number(cfg.get("merge_gap"), keep("merge_gap", 4), 0, 160, int, "display.merge_gap", w)),
        "reset_on_connect": bool(cfg.get("reset_on_connect", keep("reset_on_connect", False))),
        "bulk_px": int(number(cfg.get("bulk_px"), keep("bulk_px", 6000), 100, 153_600, int, "display.bulk_px", w)),
    }
    mode = str(cfg.get("mode", keep("mode", "normal")) or "normal").lower()
    if mode not in MODES:
        w.append(f"display.mode: {mode!r} is not one of {', '.join(MODES)}, using {keep('mode', 'normal')}")
        mode = keep("mode", "normal")
    out["mode"] = mode
    slow = cfg.get("slow") if isinstance(cfg.get("slow"), dict) else {}
    fbs_all = fb.get("slow", {})

    def fbs_get(name, default):
        return fbs_all.get(name, default) if name in slow else default
    if cfg.get("slow") not in (None, {}) and not isinstance(cfg.get("slow"), dict):
        w.append("display.slow must be a mapping, using the defaults")
    out["slow"] = {
        "noncritical_s": number(slow.get("noncritical_s"), fbs_get("noncritical_s", 10.0), 1.0, 600.0, float, "display.slow.noncritical_s", w),
        "band_every": int(number(slow.get("band_every"), fbs_get("band_every", 5), 1, 1000, int, "display.slow.band_every", w)),
        "rotate_s": number(slow.get("rotate_s"), fbs_get("rotate_s", 30.0), 5.0, 86400.0, float, "display.slow.rotate_s", w),
    }
    # bytes per refresh cycle: 0 = unlimited (the normal mode's default), the slow mode defaults to ~0.25 s of link time
    default_budget = 0 if mode == "normal" else 40_960
    out["tx_budget"] = int(number(cfg.get("tx_budget_bytes"), keep("tx_budget", default_budget) if "tx_budget_bytes" in cfg else default_budget,
                                  0, 50_000_000, int, "display.tx_budget_bytes", w))
    if 0 < out["tx_budget"] < MIN_TX_BUDGET:
        w.append(f"display.tx_budget_bytes: {out['tx_budget']} is below the smallest usable budget, using {MIN_TX_BUDGET} (one full-width row)")
        out["tx_budget"] = MIN_TX_BUDGET
    out["device"] = cfg.get("device")                     # absent = the default profile
    if out["rotate"] == 2:
        w.append("display.rotate: 2 is not supported (the panel is kept in portrait), using 1")
        out["rotate"] = 1
    tile = number(cfg.get("tile"), keep("tile", 2), 1, HW_W, int, "display.tile", w)
    if int(tile) not in TILES:
        w.append(f"display.tile: {int(tile)} does not divide 320 and 480 (allowed: {', '.join(map(str, TILES))}), using {keep('tile', 2)}")
        tile = keep("tile", 2)
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


# -- structure of config.yaml / pages.yaml ------------------------------------------------------------
class ConfigError(ValueError):
    """config.yaml / pages.yaml is unreadable or has the wrong shape. The message says what and where."""


DICT_SECTIONS = ("display", "theme", "layout", "sensors", "network", "night", "away", "web", "updates", "weather")


def check_config(cfg) -> dict:
    """config.yaml must be a mapping whose sections are mappings (`alerts` may also be the older list). Returns it, or raises ConfigError."""
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"config.yaml must be a mapping of settings at the top level, found {type(cfg).__name__}")
    for key in DICT_SECTIONS:
        if cfg.get(key) is not None and not isinstance(cfg[key], dict):
            raise ConfigError(f"config.yaml: '{key}' must be a mapping, found {type(cfg[key]).__name__}")
    if cfg.get("alerts") is not None and not isinstance(cfg["alerts"], (dict, list)):
        raise ConfigError(f"config.yaml: 'alerts' must be a mapping or a list, found {type(cfg['alerts']).__name__}")
    return cfg


def check_pages(data) -> dict:
    """pages.yaml: {pages: [ {id, ring?, cards?}, ... ]} with at least one page and unique ids. Returns it, or raises ConfigError."""
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list) or not data["pages"]:
        raise ConfigError("pages.yaml must contain a non-empty 'pages:' list")
    seen = set()
    for i, p in enumerate(data["pages"], 1):
        if not isinstance(p, dict) or p.get("id") in (None, ""):
            raise ConfigError(f"pages.yaml: page #{i} must be a mapping with an 'id'")
        if str(p["id"]) in seen:
            raise ConfigError(f"pages.yaml: duplicate page id '{p['id']}'")
        seen.add(str(p["id"]))
        if p.get("cards") is not None and (not isinstance(p["cards"], list) or not all(isinstance(c, dict) for c in p["cards"])):
            raise ConfigError(f"pages.yaml: page '{p['id']}': 'cards' must be a list of mappings")
        if p.get("ring") is not None and not isinstance(p["ring"], dict):
            raise ConfigError(f"pages.yaml: page '{p['id']}': 'ring' must be a mapping")
    return data
