"""Experiment: can the display be recovered from an interrupted bitmap WITHOUT replugging?

Stage 1  normal init + a labelled frame                                  -> screen shows 'STAGE 1 OK'
Stage 2  header declaring a HUGE bitmap (1024x1024), a bit of data, then the port is closed abruptly
         (this is what a hard kill leaves behind)                         -> screen shows garbage / freezes
Stage 3  reopen, flood N MB of zero bytes (swallowed as the missing pixels), re-init, draw 'STAGE 3 RECOVERED'
Usage: diag_recover.py [flood_megabytes]   (default 2.2)
"""
import os, sys, time
import numpy as np
import serial
from serial.tools.list_ports import comports
from PIL import Image, ImageDraw, ImageFont

FLOOD_MB = float(sys.argv[1]) if len(sys.argv) > 1 else 2.2
FONT = ImageFont.truetype(r"C:\Windows\Fonts\bahnschrift.ttf", 44)


def hdr(cmd, x=0, y=0, ex=0, ey=0):
    return bytes([x >> 2, ((x & 3) << 6) | (y >> 4), ((y & 15) << 4) | (ex >> 6), ((ex & 63) << 2) | (ey >> 8), ey & 255, cmd])


def find():
    for p in comports():
        if p.serial_number == "USB35INCHIPSV2" or (p.vid == 0x1A86 and p.pid == 0x5722):
            return p.device


def open_port():
    s = serial.Serial(find(), 115200, timeout=1, write_timeout=30, rtscts=True)
    s.dtr = True
    return s


def rgb565(img):
    a = np.asarray(img, dtype=np.uint16)
    return (((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)).astype("<u2")


def init_and_frame(s, text, color):
    s.write(hdr(109)); s.flush(); time.sleep(0.05)
    pkt = bytearray(16); pkt[5] = 121; pkt[6] = 100; pkt[7:11] = bytes([320 >> 8, 320 & 255, 480 >> 8, 480 & 255])
    s.write(bytes(pkt)); s.flush(); time.sleep(0.05)
    s.write(hdr(110, 200)); s.flush(); time.sleep(0.05)
    img = Image.new("RGB", (320, 480), color); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 319, 479), outline=(255, 255, 255), width=8)
    d.multiline_text((160, 240), text, font=FONT, fill=(255, 255, 255), anchor="mm", align="center")
    f = rgb565(img)
    for y in range(0, 480, 40):                       # blocks of 40 rows = 12 800 px
        s.write(hdr(197, 0, y, 319, y + 39)); s.write(np.ascontiguousarray(f[y:y + 40]).tobytes())
    s.flush()


def main():
    s = open_port(); print("stage 1: init + frame", flush=True)
    init_and_frame(s, "STAGE 1\nOK", (0, 90, 0))
    time.sleep(5)

    print("stage 2: declare a 1024x1024 bitmap, send a little data, close abruptly", flush=True)
    s.write(hdr(197, 0, 0, 1023, 1023)); s.write(os.urandom(200_000)); s.flush()
    s.close()
    time.sleep(6)

    print(f"stage 3: reopen, flood {FLOOD_MB} MB of zeros, re-init", flush=True)
    s = open_port()
    zeros = bytes(65536); sent = 0; t0 = time.time()
    while sent < FLOOD_MB * 1_000_000:
        s.write(zeros); sent += len(zeros)
        if int(sent / 65536) % 8 == 0:
            print(f"  flooded {sent/1e6:.2f} MB  ({time.time()-t0:.0f}s)", flush=True)
    s.flush()
    init_and_frame(s, "STAGE 3\nRECOVERED", (0, 60, 160))
    print("done", flush=True)
    s.close()


main()
