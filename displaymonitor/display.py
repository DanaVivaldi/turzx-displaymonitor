"""Driver for the TURZX / Turing 3.5" USB display (Rev A protocol, V2 firmware, serial CDC).

What we learned (docs/STUDIO.md + reference projects Tedd.TuringScreen / TelemetryForge / turing-smart-screen-python):
  * bandwidth is a hard ~165 KB/s -> steady state sends only changed rectangles;
  * the firmware's own rotation modes are fragile (a 30-column wrap appeared after switching orientation),
    so the panel is kept in PORTRAIT (320x480) and the landscape picture is rotated in software;
  * a single bitmap command must stay small: every rectangle is split into blocks of <= 12 800 pixels;
  * after a hard kill mid-bitmap the firmware keeps waiting for pixels and misparses the next commands:
    on connect we flush a full frame of zero bytes, send RESET (101), wait for the port, then do the HELLO handshake.
"""
import logging
import time

import numpy as np
import serial
from serial.tools.list_ports import comports

from . import devices, txsched, validate

log = logging.getLogger(__name__)

W, H = 480, 320                  # logical (landscape) frame handed to show()
HW_W, HW_H = 320, 480            # physical panel, portrait
CMD_HELLO, CMD_RESET, CMD_SCREEN_ON, CMD_BRIGHTNESS, CMD_ORIENTATION, CMD_BITMAP = 69, 101, 109, 110, 121, 197
VID, PID, SERIAL_ID = 0x1A86, 0x5722, "USB35INCHIPSV2"


def _header(cmd, x, y, ex, ey):
    return bytes([x >> 2, ((x & 3) << 6) | (y >> 4), ((y & 15) << 4) | (ex >> 6),
                  ((ex & 63) << 2) | (ey >> 8), ey & 255, cmd])


def rgb565(img) -> np.ndarray:
    """PIL RGB image -> (H, W) little-endian uint16 RGB565."""
    a = np.asarray(img, dtype=np.uint16)
    return (((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)).astype("<u2")


class Display:
    def __init__(self, cfg: dict):
        st, warnings = validate.display_settings(cfg)
        validate.warn_all(warnings)
        self.profile, dw = devices.parse_profile(st["device"])         # which USB device is "the display"
        validate.warn_all(dw)
        self._warned: set = set()
        self.rot_k = st["rotate"]                        # np.rot90 steps: 1 or 3 depending on how the panel is mounted
        self.brightness = st["brightness"]               # percent, 100 = brightest
        self.tile = st["tile"]
        self.gap_tiles = st["merge_gap"] // self.tile
        self.band = st["refresh_band"]                   # rows resent every frame to heal corrupted pixels (0 = off) ...
        self.band_budget = st["band_budget"]             # ... but only while the frame's own changes are smaller than this many bytes
        self.max_px = st["max_block_px"]
        self.reset_on_connect = st["reset_on_connect"]   # RESET (101) showed no visible effect: off
        self.flood_bytes = st["flood_bytes"]
        self.mode, self.slow = st["mode"], st["slow"]    # normal | slow (see docs/CONFIGURATION.md)
        self.tx_budget = st["tx_budget"]                 # bytes per refresh cycle, 0 = unlimited
        self.bulk_px = st["bulk_px"]                     # rectangles larger than this many pixels are "bulk" (backgrounds), sent after the data
        self.needs_flood = False      # set when the last session may have ended mid-bitmap (hard kill, link error)
        self._band_y = 0
        self._cycle = 0
        self._ser = None
        self._prev = None             # what the panel is believed to show: a region is copied in only after its bytes were written
        self._pending_bytes = 0       # bytes of the newest frame still waiting to be sent (always derived from diff(_prev, newest frame))
        self.last_bytes = 0
        self.last_wire = 0            # last_bytes + the headers: what the budget counts
        self.last_rects = 0
        self.last_ms = 0.0            # time spent sending the last frame
        self.band_skipped = 0         # frames whose healing band was left out (panel busy / budget used / slow-mode cadence)
        self.tx = txsched.new_metrics()

    def _settings(self) -> dict:
        return {"rotate": self.rot_k, "brightness": self.brightness, "tile": self.tile, "merge_gap": self.gap_tiles * self.tile,
                "refresh_band": self.band, "band_budget": self.band_budget, "max_block_px": self.max_px,
                "flood_bytes": self.flood_bytes, "reset_on_connect": self.reset_on_connect, "bulk_px": self.bulk_px,
                "mode": self.mode, "slow": self.slow, "tx_budget": self.tx_budget, "device": None}

    def configure(self, cfg: dict):
        """Apply display settings changed in config.yaml while running (hot reload). A wrong value keeps the current one.
        Brightness is owned by App (night schedule), so it is left alone here."""
        keep = self._settings()
        st, warnings = validate.display_settings(cfg, keep)
        validate.warn_all(warnings)
        self.rot_k, self.tile, self.band, self.band_budget, self.max_px = st["rotate"], st["tile"], st["refresh_band"], st["band_budget"], st["max_block_px"]
        self.gap_tiles = st["merge_gap"] // self.tile
        self.mode, self.slow, self.tx_budget, self.bulk_px = st["mode"], st["slow"], st["tx_budget"], st["bulk_px"]
        profile, dw = devices.parse_profile(st["device"])
        validate.warn_all(dw)
        if profile != self.profile:
            self.profile, self._warned = profile, set()
            if self._ser is not None:                   # another display was asked for: reconnect on the next cycle
                self.disconnect()
        self.invalidate()                       # rotation / tile changes: redraw everything

    # -- connection -----------------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._ser is not None

    def find_port(self):
        """The port of the display described by `display.device` (default: VID 1A86, PID 5722 / serial USB35INCHIPSV2), or None.
        Only ports whose USB ids match are ever opened."""
        return devices.choose(comports(), self.profile, self._warned)

    def _open(self, port):
        ser = serial.Serial(port, 115200, timeout=1, write_timeout=10, rtscts=True)
        ser.dtr = True
        ser.reset_input_buffer()
        self._ser = ser

    def connect(self) -> bool:
        port = self.find_port()
        if not port:
            return False
        try:
            self._open(port)
            if self.needs_flood:
                self._flood()
                self.needs_flood = False
            if self.reset_on_connect:
                self._resync_and_reset()
                port = self.find_port()
                if not port:
                    raise serial.SerialException("display did not come back after reset")
                self._open(port)
            self._write(_header(CMD_SCREEN_ON, 0, 0, 0, 0))
            time.sleep(0.05)
            pkt = bytearray(16)  # orientation: ONE write, otherwise the parser desyncs. Always PORTRAIT 320x480.
            pkt[5], pkt[6] = CMD_ORIENTATION, 0 + 100
            pkt[7], pkt[8], pkt[9], pkt[10] = HW_W >> 8, HW_W & 255, HW_H >> 8, HW_H & 255
            self._write(bytes(pkt))
            time.sleep(0.05)
            self._write(_header(CMD_BRIGHTNESS, self.raw_brightness(), 0, 0, 0))
            time.sleep(0.05)
        except (serial.SerialException, OSError) as e:
            log.warning("cannot initialise display on %s: %s", port, e)
            self.needs_flood = True
            self.disconnect()
            return False
        self._prev = None  # force a full redraw
        log.info("display connected on %s", port)
        return True

    def _flood(self):
        """Complete whatever bitmap the firmware is still waiting for.

        After a hard kill the firmware keeps swallowing bytes as pixels of the interrupted bitmap. A bad header can
        declare up to 1023x1023 px (2 MB), so we push ~2.2 MB of zeros; zeros are harmless 'command 0' headers once the
        firmware is back in sync, at any alignment. Verified on the real unit (tools/diag_recover.py): ~13 s.
        """
        log.warning("previous session ended abnormally: flushing the display's pending bitmap (~%.0f s)...",
                    self.flood_bytes / 165_000)
        zeros, sent = bytes(65536), 0
        while sent < self.flood_bytes:
            self._write_all(zeros)
            sent += len(zeros)
        self._ser.flush()

    def _resync_and_reset(self):
        """Optional hard reset of the firmware, then wait for the port to return (off by default)."""
        self._write(_header(CMD_RESET, 0, 0, 0, 0))
        time.sleep(0.2)
        self.disconnect()
        t0, gone = time.time(), False
        while time.time() - t0 < 12:
            if self.find_port() is None:
                gone = True
            elif gone or time.time() - t0 >= 5:  # re-enumerated, or never visibly left: give it time then go on
                break
            time.sleep(0.25)
        time.sleep(0.5)
        log.info("display reset (left bus: %s, %.1fs)", gone, time.time() - t0)

    def _handshake(self):
        """TelemetryForge style: HELLO x6, wait, drain. V2/UsbMonitor firmwares answer; original Turing 3.5 stays silent."""
        self._ser.reset_input_buffer()
        self._write(bytes([CMD_HELLO] * 6))
        time.sleep(0.12)
        reply = self._ser.read(self._ser.in_waiting or 0)
        self._ser.reset_input_buffer()
        log.info("HELLO reply: %s", reply.hex() if reply else "(none)")

    def disconnect(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self._prev = None

    WRITE_STALL_S = 2.0           # a port that accepts no byte at all for this long is treated as a lost link

    def _write_all(self, data: bytes):
        """Write every byte: serial.write() may accept only part of its input (it returns how many). A short write that went
        unnoticed would desynchronise the firmware's command parser, so the loop repeats until all of it is out, and gives up
        (OSError, handled as a link loss) if the port stops accepting bytes."""
        view = memoryview(data)
        off, stalled = 0, None
        while off < len(view):
            n = self._ser.write(view[off:])
            if n is None:                                  # a port object that does not report a count: take it as complete
                return
            if n > 0:
                off, stalled = off + min(n, len(view) - off), None
                continue
            now = time.time()
            stalled = stalled or now
            if now - stalled > self.WRITE_STALL_S:
                raise OSError(f"serial write stalled after {off} of {len(view)} bytes")
            time.sleep(0.005)

    def _write(self, data: bytes):
        self._write_all(data)
        self._ser.flush()

    # -- drawing --------------------------------------------------------------------------------
    @staticmethod
    def _clamp_pct(value) -> int:
        return max(0, min(100, int(round(float(value)))))

    def raw_brightness(self) -> int:
        """Percent -> the firmware's value. Verified on the tested unit: the scale is INVERTED (0 = brightest, 255 = darkest)."""
        return int(round(255 - self.brightness * 2.55))

    def set_brightness(self, percent):
        """0-100 %, 100 = brightest."""
        self.brightness = self._clamp_pct(percent)
        if self.connected:
            try:
                self._write(_header(CMD_BRIGHTNESS, self.raw_brightness(), 0, 0, 0))
            except (serial.SerialException, OSError):
                self.disconnect()

    def invalidate(self):
        self._prev = None

    def show(self, frame: np.ndarray, critical: bool = False) -> bool:
        """frame: (320, 480) landscape RGB565, the newest picture. Sends part of what differs from what the panel shows, within the
        byte budget (see txsched.py); the rest stays pending and is recomputed against the next frame, so the panel converges on the
        latest frame without a backlog. `critical` (the "Ciao" screen, night black ...) sends everything now, budget or not.
        Returns False if the link dropped."""
        if not self.connected:
            return False
        tx = self.tx
        try:
            t0 = time.time()
            hw = np.ascontiguousarray(np.rot90(frame, self.rot_k))      # (480, 320) portrait panel
            prev = self._prev
            self._cycle += 1
            tx["cycles"] = self._cycle
            self.last_rects, self.last_bytes, self.last_wire = 0, 0, 0
            if prev is None or critical:                                 # full refresh: unbudgeted, then `_prev` is the whole frame
                if prev is not None and self._pending_bytes:
                    tx["coalesced"] += 1
                tx["critical"] += 1
                blocks = [(txsched.CRITICAL, b) for b in txsched.split_rect((0, 0, HW_W, HW_H), self.max_px)]
                self._send_blocks(hw, blocks, None)
                self._ser.flush()
                self._prev = hw.copy()
                self._pending_bytes, sent, rest, budget = 0, self.last_wire, [], 0
            else:
                budget = max(self.tx_budget, txsched.MIN_BUDGET) if self.tx_budget > 0 else 0
                if self._pending_bytes:                                  # the previous frame was not fully out: this one replaces it
                    tx["coalesced"] += 1
                if budget > 0:                                           # budgeted: separate the content from the subtle / large changes
                    data, bulk = self._diff_classes(prev, hw)
                    blocks = txsched.blocks_for(data, bulk, self.max_px)
                    changed = sum(txsched.rect_bytes(r) for r in data + bulk)
                else:                                                    # unlimited (normal mode): exactly the merged rectangles of old, top to bottom
                    rects = self._diff(prev, hw)
                    blocks = [(txsched.DATA, b) for r in rects for b in txsched.split_rect(r, self.max_px)]
                    changed = sum(txsched.rect_bytes(r) for r in rects)
                chosen, rest = txsched.take(blocks, budget)
                self._send_blocks(hw, chosen, prev)                      # `prev` gains each block only after it was written
                sent = self.last_wire
                self._pending_bytes = sum(txsched.wire_bytes(b) for _, b in rest)      # on the wire: headers included, like the budget
                if self.band:                                            # self-healing band: lowest priority, only with spare capacity
                    band_bytes = txsched.wire_bytes((0, 0, HW_W, self.band))
                    slow_skip = self.mode == "slow" and self._cycle % max(1, self.slow["band_every"]) != 0
                    if (not rest and not slow_skip and changed <= self.band_budget and (budget <= 0 or sent + band_bytes <= budget)):
                        blk = (0, self._band_y, HW_W, self.band)
                        self._send_blocks(hw, [(txsched.HEALING, blk)], prev)
                        self._band_y = (self._band_y + self.band) % HW_H
                    else:
                        self.band_skipped += 1
                self._ser.flush()
            tx.update(budget=budget, sent=self.last_wire, pending=self._pending_bytes,
                      used=(self.last_wire / budget if budget else None), latency_s=txsched.latency_estimate(self._pending_bytes))
            self.last_ms = (time.time() - t0) * 1000
            return True
        except (serial.SerialException, OSError) as e:
            log.warning("display link lost: %s", e)
            self.needs_flood = True        # we may have dropped mid-bitmap: nothing about the panel's content is trusted any more
            self._pending_bytes = 0
            self.disconnect()              # (also forgets `_prev`, so the next connect starts with a full refresh)
            return False

    def _changed_tiles(self, prev, cur):
        t = self.tile
        return (prev != cur).reshape(HW_H // t, t, HW_W // t, t).any(axis=(1, 3))

    def _rects_from_mask(self, d):
        """Boolean tile mask -> rectangles (row spans merged downwards, spans closer than merge_gap joined)."""
        t = self.tile
        rects, open_ = [], {}
        for ty in range(HW_H // t):
            idx = np.flatnonzero(d[ty])
            spans = []
            if idx.size:
                cut = np.flatnonzero(np.diff(idx) > self.gap_tiles + 1)
                starts = np.concatenate(([idx[0]], idx[cut + 1]))
                ends = np.concatenate((idx[cut], [idx[-1]]))
                spans = [(int(s) * t, (int(e) + 1) * t) for s, e in zip(starts, ends)]
            keep = set(spans)
            for key in [k for k in open_ if k not in keep]:
                y0, y1 = open_.pop(key)
                rects.append((key[0], y0, key[1] - key[0], y1 - y0))
            for sp in spans:
                if sp in open_:
                    open_[sp][1] = (ty + 1) * t
                else:
                    open_[sp] = [ty * t, (ty + 1) * t]
        for key, (y0, y1) in open_.items():
            rects.append((key[0], y0, key[1] - key[0], y1 - y0))
        rects.sort(key=lambda r: (r[1], r[0]))
        return rects

    def _diff(self, prev, cur):
        """Every rectangle where `cur` differs from `prev`."""
        return self._rects_from_mask(self._changed_tiles(prev, cur))

    STRONG = 48                                   # per-channel change (0..255 scale) from which a tile counts as "content", not "tint"

    def _diff_classes(self, prev, cur):
        """(data, bulk) rectangles. A tile that changed by a lot (a digit, a bar) is data when its rectangle is small; the subtle
        changes (a background tint step: a few levels per pixel) and anything large are bulk and go out after the data - even when
        the data sits inside the tinted area, because the two are separate rectangles (the strong tiles are cut out of the weak ones)."""
        changed = self._changed_tiles(prev, cur)
        if not changed.any():
            return [], []
        a, b = prev.astype(np.int16), cur.astype(np.int16)
        mag = np.maximum.reduce([np.abs((a >> 11) - (b >> 11)) * 8, np.abs(((a >> 5) & 63) - ((b >> 5) & 63)) * 4, np.abs((a & 31) - (b & 31)) * 8])
        t = self.tile
        strong = (mag >= self.STRONG).reshape(HW_H // t, t, HW_W // t, t).any(axis=(1, 3)) & changed
        data, bulk = [], self._rects_from_mask(changed & ~strong)
        for r in self._rects_from_mask(strong):
            (data if r[2] * r[3] <= self.bulk_px else bulk).append(r)
        # Tile-level rectangles still contain rows that are already right once a piece of them has been sent: cut each one down to
        # the pixels that really differ, so a tiny budget never re-sends what the panel has (and always moves forward).
        trim = lambda rects: [t for t in (self._trim(prev, cur, r) for r in rects) if t]      # noqa: E731
        return trim(data), trim(bulk)

    @staticmethod
    def _trim(prev, cur, rect):
        """The bounding box of the pixels of `rect` where `cur` differs from `prev`, or None."""
        x, y, w, h = rect
        diff = prev[y:y + h, x:x + w] != cur[y:y + h, x:x + w]
        rows, cols = np.flatnonzero(diff.any(axis=1)), np.flatnonzero(diff.any(axis=0))
        if rows.size == 0:
            return None
        return (x + int(cols[0]), y + int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))

    def _send_blocks(self, hw, blocks, prev):
        """Write the blocks [(priority, (x, y, w, h))] (each already <= max_block_px). When `prev` is given, a block's pixels are copied into
        it only after both of its writes returned: an error leaves `prev` untouched for that block (and the caller resets it)."""
        for _prio, (x, y, w, h) in blocks:
            data = np.ascontiguousarray(hw[y:y + h, x:x + w]).tobytes()
            self._write_all(_header(CMD_BITMAP, x, y, x + w - 1, y + h - 1))
            self._write_all(data)
            if prev is not None:
                prev[y:y + h, x:x + w] = hw[y:y + h, x:x + w]
            self.last_bytes += len(data)
            self.last_wire += txsched.HEADER_BYTES + len(data)
            self.last_rects += 1
