"""Measures how fast the display swallows pixels (portrait mode, 320x480, blocks of <= 12 800 px).

  python tools/bench_bandwidth.py

Sends a full frame and rectangles of several sizes and prints ms per item and KB/s.
On the tested unit (V2 firmware) the throughput is a constant ~165 KB/s whatever the write strategy, baud rate or
flow control, i.e. a full frame (307 KB) takes ~1.8 s. See docs/PROTOCOL.md.
The screen shows gradients while it runs. Do not interrupt it (Ctrl+C mid-bitmap needs the recovery flood).
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from displaymonitor.display import CMD_BITMAP, HW_H, HW_W, Display, _header  # noqa: E402


def gradient(seed: int) -> np.ndarray:
    x = np.linspace(0, 31, HW_W, dtype=np.uint16)[None, :]
    y = np.linspace(0, 63, HW_H, dtype=np.uint16)[:, None]
    return (((x + seed) % 32) << 11 | y << 5 | ((x * 2 + seed) % 32)).astype("<u2")


def send(lcd: Display, frame, x, y, w, h):
    rows = max(1, lcd.max_px // w)
    n = 0
    for y0 in range(y, y + h, rows):
        bh = min(rows, y + h - y0)
        data = np.ascontiguousarray(frame[y0:y0 + bh, x:x + w]).tobytes()
        lcd._ser.write(_header(CMD_BITMAP, x, y0, x + w - 1, y0 + bh - 1))
        lcd._ser.write(data)
        n += len(data)
    lcd._ser.flush()
    return n


def main():
    lcd = Display({"reset_on_connect": False})
    if not lcd.connect():
        raise SystemExit("display not found")
    try:
        frame = gradient(0)
        print(f"{'item':<22}{'ms/item':>10}{'KB/s':>10}")
        for name, (w, h), reps in (("full frame 320x480", (HW_W, HW_H), 4), ("rect 128x64", (128, 64), 10),
                                   ("rect 32x32", (32, 32), 40), ("rect 16x16", (16, 16), 60), ("rect 8x8", (8, 8), 100)):
            t0, total = time.perf_counter(), 0
            for i in range(reps):
                total += send(lcd, gradient(i), (i * 13) % (HW_W - w + 1), (i * 7) % (HW_H - h + 1), w, h)
            dt = time.perf_counter() - t0
            print(f"{name:<22}{1000 * dt / reps:>10.1f}{total / dt / 1024:>10.0f}")
    finally:
        lcd.disconnect()


if __name__ == "__main__":
    main()
