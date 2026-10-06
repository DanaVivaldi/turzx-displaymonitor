# TURZX 3.5" USB display — device notes

What was **measured on one real unit** while writing this project (USB `1A86:5722`, serial `USB35INCHIPSV2`, V2 firmware,
Windows 11). Things marked *(upstream)* come from other projects' documentation and were not re‑verified here.
Everything is reproducible with the scripts in `tools/`.

## Identification and transport

* USB CDC serial device (Windows: "USB Serial Device (COMx)", built‑in `usbser` driver on Windows 10/11).
* VID `0x1A86`, PID `0x5722`, USB serial number string `USB35INCHIPSV2`. The COM number changes: always look the port up by VID/PID.
* Opened at 115200 baud with DTR asserted. The baud rate is irrelevant: throughput is identical at 115200, 1 M and 12 M baud,
  with or without RTS/CTS, with one big write, header + payload writes or 3 840‑byte chunks.
* After power‑up the firmware draws a portrait splash ("PLEASE RUN THE APP / WWW.TURZX.COM") until the first command arrives.

## Command packet (the "Rev A" protocol, *(upstream)* documented by turing-smart-screen-python)

Every command starts with 6 bytes carrying four 10‑bit coordinates and the command byte:

```
byte0 = x  >> 2
byte1 = ((x  & 3)  << 6) | (y  >> 4)
byte2 = ((y  & 15) << 4) | (ex >> 6)
byte3 = ((ex & 63) << 2) | (ey >> 8)
byte4 = ey & 255
byte5 = command
```

| Command | Value | Notes |
|---|---|---|
| `SCREEN_ON` | 109 | coordinates unused |
| `SET_BRIGHTNESS` | 110 | the level goes in `x`. Raw 0‑255. *(upstream says 0 = brightest.)* The value 200 looked clearly visible on the tested unit |
| `SET_ORIENTATION` | 121 | a **16‑byte** packet: the 6‑byte header, then `orientation+100`, `width_hi, width_lo, height_hi, height_lo`, zero padding. **Must be one single write**, otherwise the parser desynchronises and the screen stays black |
| `DISPLAY_BITMAP` | 197 | header with `x, y, ex, ey`, followed by `(ex‑x+1)·(ey‑y+1)` pixels |
| `HELLO` | 69 | six bytes of 69. The tested (original Turing) firmware does **not** answer; UsbMonitor firmwares do |
| `RESET` | 101 | accepted, but had no visible effect on the tested unit (the USB device did not re‑enumerate) |

Pixels are **RGB565 little‑endian** (`r5 g6 b5`), row by row.

## Bandwidth: a hard ~165 KB/s

Measured with `tools/bench_bandwidth.py` (portrait mode, blocks ≤ 12 800 px):

| Item | Time | Throughput |
|---|---|---|
| full frame 320×480 (307 KB) | **≈ 1.8 s** | 165 KB/s |
| rectangle 128×64 | 96 ms | 166 KB/s |
| rectangle 32×32 | 12 ms | 165 KB/s |
| rectangle 16×16 | 3.2 ms | 159 KB/s |
| rectangle 8×8 | 0.9 ms | 136 KB/s |

The cost per command is ~0.13 ms of overhead plus ~6 ms per KB of pixels (1 / 165 KB/s). It does not depend on how the bytes are written, so the only lever is **sending less**:
the driver diffs every frame in 2×2 px tiles, merges neighbouring tiles into rectangles and sends only those. For a realistic dashboard
(36 changing value fields) 2 px tiles gave 5.9 fps, 8 px tiles 4.2 fps, 16 px tiles 2.2 fps, a full frame 0.56 fps.

## Keep every bitmap command small

With the vendor‑style approach of sending a whole 153 600‑pixel frame as one bitmap, and with large rectangles, we saw
stripes and patches of corrupted pixels that then stayed on screen (a diff‑based driver never repaints what it believes is already correct).
After limiting every `DISPLAY_BITMAP` to **≤ 12 800 pixels** (the limit used by [Tedd.TuringScreen](https://github.com/tedd/Tedd.TuringScreen);
rectangles are split into row blocks) and switching to software rotation the picture was clean. We did not isolate which of the two changes
removed the corruption. As a belt‑and‑braces measure the driver also resends one 8‑row band per frame, cycling over the whole panel.

## Do not use the firmware's rotation

Orientation modes 2 (landscape) and 3 (reverse landscape) work, but:

* after switching from 2 to 3 **without power‑cycling** the framebuffer was cyclically shifted by 30 columns
  (image column *c* appeared at screen column *(c‑30) mod 480*). After a fresh power‑up, orientation 3 had no offset;
* Tedd.TuringScreen documents the same class of "memory wrapping artifacts" and rotates in software.

So the panel is always kept in **portrait 320×480** (orientation 0) and the landscape frame is rotated with `numpy.rot90`
(`display.rotate: 1` or `3`, depending on how the display is mounted; on the tested unit the native portrait "up" points to the viewer's right).

## The "black screen" state and how to leave it

If the host dies **in the middle of a bitmap** (process killed, crash, power loss while the display stays powered) the firmware keeps waiting for the
missing pixels and swallows everything that follows as pixel data. It then misparses whatever comes next: the screen turns black and
ignores `SCREEN_ON`, `CLEAR`, brightness and orientation commands, and a `RESET`. Unplugging the cable fixes it.

**Recovery without unplugging** (verified with `tools/diag_recover.py`): write ≈ **2.2 MB of zero bytes**, then initialise normally.
Zero bytes complete the pending payload and, once the parser is back in sync, are harmless "command 0" headers at any alignment.
The amount matters: a bad header can declare up to 1023×1023 pixels (2 MB). Flooding takes ≈ 13 s at 165 KB/s.

DisplayMonitor does this automatically: it writes `logs/running.flag` at start and removes it on an orderly exit; if the flag is still there at the next start
(or after any write error) it floods before initialising. Always stop it with `python -m displaymonitor --send quit` or the tray's *Quit*.

## Diagnostic tools

| Script | Purpose |
|---|---|
| `tools/bench_bandwidth.py` | reproduces the bandwidth table above |
| `tools/diag_ladder.py` | walks through brightness / CLEAR / orientation combinations with on‑screen labels (black‑screen diagnosis) |
| `tools/diag_recover.py` | simulates a hard kill (huge declared bitmap, abrupt close) and tries the flood recovery |
| `tools/dump_sensors.ps1` | lists every sensor LibreHardwareMonitor sees |

Stop DisplayMonitor before running them: only one program can own the COM port.
