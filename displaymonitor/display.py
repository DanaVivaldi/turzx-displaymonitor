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
        self.rot_k = int(cfg.get("rotate", 1))           # np.rot90 steps: 1 or 3 depending on how the panel is mounted
        self.brightness = int(cfg.get("brightness", 200))
        self.tile = int(cfg.get("tile", 2))
        self.gap_tiles = int(cfg.get("merge_gap", 4)) // self.tile
        self.band = int(cfg.get("refresh_band", 8))      # rows resent every frame to heal corrupted pixels (0 = off)
        self.max_px = int(cfg.get("max_block_px", 12800))
        self.reset_on_connect = bool(cfg.get("reset_on_connect", False))   # RESET (101) showed no visible effect: off
        self.flood_bytes = int(cfg.get("flood_bytes", 2_200_000))
        self.needs_flood = False      # set when the last session may have ended mid-bitmap (hard kill, link error)
        self._band_y = 0
        self._ser = None
        self._prev = None
        self.last_bytes = 0
        self.last_rects = 0

    def configure(self, cfg: dict):
        """Apply display settings changed in config.yaml while running (hot reload)."""
        self.rot_k = int(cfg.get("rotate", self.rot_k))
        self.tile = int(cfg.get("tile", self.tile))
        self.gap_tiles = int(cfg.get("merge_gap", 4)) // self.tile
        self.band = int(cfg.get("refresh_band", self.band))
        self.max_px = int(cfg.get("max_block_px", self.max_px))
        if "brightness" in cfg and int(cfg["brightness"]) != self.brightness:
            self.set_brightness(int(cfg["brightness"]))
        self.invalidate()                       # rotation / tile changes: redraw everything

    # -- connection -----------------------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._ser is not None

    @staticmethod
    def find_port():
        for p in comports():
            if p.serial_number == SERIAL_ID or (p.vid == VID and p.pid == PID):
                return p.device
        return None

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
            self._write(_header(CMD_BRIGHTNESS, self.brightness, 0, 0, 0))
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
            self._ser.write(zeros)
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

    def _write(self, data: bytes):
        self._ser.write(data)
        self._ser.flush()

    # -- drawing --------------------------------------------------------------------------------
    def set_brightness(self, value: int):
        self.brightness = max(0, min(255, int(value)))
        if self.connected:
            try:
                self._write(_header(CMD_BRIGHTNESS, self.brightness, 0, 0, 0))
            except (serial.SerialException, OSError):
                self.disconnect()

    def invalidate(self):
        self._prev = None

    def show(self, frame: np.ndarray) -> bool:
        """frame: (320, 480) landscape RGB565. Sends only what changed. Returns False if the link dropped."""
        if not self.connected:
            return False
        try:
            hw = np.ascontiguousarray(np.rot90(frame, self.rot_k))      # (480, 320) portrait panel
            prev = self._prev
            rects = [(0, 0, HW_W, HW_H)] if prev is None else self._diff(prev, hw)
            if prev is not None and self.band:     # self-healing: also resend one band per frame, cycling over the screen
                rects.append((0, self._band_y, HW_W, self.band))
                self._band_y = (self._band_y + self.band) % HW_H
            self.last_rects, self.last_bytes = len(rects), 0
            for (x, y, w, h) in rects:
                self._send_rect(hw, x, y, w, h)
            self._ser.flush()
            self._prev = hw
            return True
        except (serial.SerialException, OSError) as e:
            log.warning("display link lost: %s", e)
            self.needs_flood = True        # we may have dropped mid-bitmap
            self.disconnect()
            return False

    def _diff(self, prev, cur):
        t = self.tile
        d = (prev != cur).reshape(HW_H // t, t, HW_W // t, t).any(axis=(1, 3))
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

    def _send_rect(self, hw, x, y, w, h):
        rows = max(1, self.max_px // w)            # keep every bitmap command <= max_px pixels
        for y0 in range(y, y + h, rows):
            bh = min(rows, y + h - y0)
            data = np.ascontiguousarray(hw[y0:y0 + bh, x:x + w]).tobytes()
            self._ser.write(_header(CMD_BITMAP, x, y0, x + w - 1, y0 + bh - 1))
            self._ser.write(data)
            self.last_bytes += len(data)
