"""Which serial port is the display? Identification by USB ids, never by "whatever is plugged in".

The default is exactly what was always used: VID 0x1A86, PID 0x5722 or the serial number USB35INCHIPSV2. It can be narrowed or
changed in config.yaml (`display.device`):

    display:
      device:
        profile: turzx-rev-a   # the only protocol implemented (see docs/PROTOCOL.md); anything else is refused
        vid: 0x1a86            # a clone with other USB ids that speaks the same protocol: put its ids here
        pid: 0x5722
        serial: ""             # only the display with this exact serial number
        port: ""               # only this port (COM3, /dev/ttyACM0): it must STILL match the ids, a port is never opened on trust
        index: 0               # several compatible displays and no serial / port: which one (0 = first, sorted by port name)

The protocol cannot be verified on the wire (this firmware stays silent to a HELLO), so a port is opened only when its USB ids match the profile.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROFILES = ("turzx-rev-a",)
DEFAULT_VID, DEFAULT_PID, DEFAULT_SERIAL = 0x1A86, 0x5722, "USB35INCHIPSV2"


def _usb_id(value, default: int, name: str, warnings: list) -> int:
    """0x1a86, '0x1a86', '1a86' or 6790 -> int in 0..0xFFFF."""
    if value in (None, ""):
        return default
    try:
        v = value if isinstance(value, int) and not isinstance(value, bool) else int(str(value).strip(), 16)
        if not 0 <= v <= 0xFFFF:
            raise ValueError
        return v
    except (TypeError, ValueError):
        warnings.append(f"display.device.{name}: {value!r} is not a USB id (hex, 0..FFFF), using {default:#06x}")
        return default


def parse_profile(cfg) -> tuple[dict, list[str]]:
    """The `display.device` section -> {profile, vid, pid, serial, port, index, custom_ids} (+ warnings). Never raises."""
    w: list[str] = []
    c = cfg if isinstance(cfg, dict) else {}
    if cfg not in (None, {}) and not isinstance(cfg, dict):
        w.append("display.device must be a mapping, using the defaults")
    profile = str(c.get("profile") or PROFILES[0])
    if profile not in PROFILES:
        w.append(f"display.device.profile: {profile!r} is not supported (only {', '.join(PROFILES)}), using {PROFILES[0]}")
        profile = PROFILES[0]
    vid = _usb_id(c.get("vid"), DEFAULT_VID, "vid", w)
    pid = _usb_id(c.get("pid"), DEFAULT_PID, "pid", w)
    try:
        index = max(0, int(c.get("index", 0) or 0))
    except (TypeError, ValueError):
        w.append(f"display.device.index: {c.get('index')!r} is not a number, using 0")
        index = 0
    return {"profile": profile, "vid": vid, "pid": pid, "serial": str(c.get("serial") or "").strip(),
            "port": str(c.get("port") or "").strip(), "index": index,
            "custom_ids": (vid, pid) != (DEFAULT_VID, DEFAULT_PID)}, w


def compatible(ports, prof: dict) -> list:
    """The serial ports whose USB ids match the profile (and the serial number, when one is configured), sorted by device name."""
    out = []
    for p in ports:
        ids_ok = (getattr(p, "vid", None) == prof["vid"] and getattr(p, "pid", None) == prof["pid"])
        known_serial = (not prof["custom_ids"]) and getattr(p, "serial_number", None) == DEFAULT_SERIAL
        if not (ids_ok or known_serial):
            continue
        if prof["serial"] and getattr(p, "serial_number", None) != prof["serial"]:
            continue
        out.append(p)
    return sorted(out, key=lambda p: str(p.device))


def choose(ports, prof: dict, warn_once: set | None = None) -> str | None:
    """The device name to open, or None. A configured `port` is honoured only if it is one of the compatible ports."""
    cands = compatible(ports, prof)
    if prof["port"]:
        match = [p for p in cands if str(p.device).lower() == prof["port"].lower()]
        if not match and cands and warn_once is not None and ("port", prof["port"]) not in warn_once:
            warn_once.add(("port", prof["port"]))
            log.warning("display.device.port %s is not a compatible display (found: %s): not opened",
                        prof["port"], ", ".join(str(p.device) for p in cands))
        return str(match[0].device) if match else None
    if not cands:
        return None
    if len(cands) > 1 and warn_once is not None and ("multi", len(cands)) not in warn_once:
        warn_once.add(("multi", len(cands)))
        log.warning("%d compatible displays found (%s): using #%d; choose with display.device.serial / port / index",
                    len(cands), ", ".join(str(p.device) for p in cands), min(prof["index"], len(cands) - 1))
    return str(cands[min(prof["index"], len(cands) - 1)].device)
