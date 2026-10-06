"""Black-screen diagnosis: walks through brightness / CLEAR / orientation combinations, each step labelled on screen.
Run:  .venv\\Scripts\\python.exe tools\\diag_ladder.py [hold_seconds]
Watch the display and note the label of the first step that lights up.
"""
import sys, time
import numpy as np
import serial
from serial.tools.list_ports import comports
from PIL import Image, ImageDraw, ImageFont

HOLD = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
FONT = ImageFont.truetype(r"C:\Windows\Fonts\bahnschrift.ttf", 40)


def hdr(cmd, x=0, y=0, ex=0, ey=0):
    return bytes([x >> 2, ((x & 3) << 6) | (y >> 4), ((y & 15) << 4) | (ex >> 6), ((ex & 63) << 2) | (ey >> 8), ey & 255, cmd])


def find():
    for p in comports():
        if p.serial_number == "USB35INCHIPSV2" or (p.vid == 0x1A86 and p.pid == 0x5722):
            return p.device


def rgb565(img):
    a = np.asarray(img, dtype=np.uint16)
    return (((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)).astype("<u2")


def label_frame(w, h, text):
    img = Image.new("RGB", (w, h), (255, 255, 255)); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, h - 1), outline=(255, 0, 0), width=6)
    d.multiline_text((w // 2, h // 2), text, font=FONT, fill=(0, 0, 0), anchor="mm", align="center")
    return rgb565(img)


class Lcd:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=1, write_timeout=10, rtscts=True)
        self.s.dtr = True

    def w(self, b):
        self.s.write(b); self.s.flush()

    def orient(self, o, w, h):
        pkt = bytearray(16); pkt[5] = 121; pkt[6] = o + 100
        pkt[7], pkt[8], pkt[9], pkt[10] = w >> 8, w & 255, h >> 8, h & 255
        self.w(bytes(pkt))

    def frame(self, f):
        h, w = f.shape
        rows = max(1, 12800 // w)
        for y in range(0, h, rows):
            bh = min(rows, h - y)
            self.s.write(hdr(197, 0, y, w - 1, y + bh - 1)); self.s.write(np.ascontiguousarray(f[y:y + bh]).tobytes())
        self.s.flush()


def main():
    port = find()
    print("port", port, flush=True)
    lcd = Lcd(port)
    steps = []
    steps.append(("S1  CLEAR, bright=0", lambda: (lcd.w(hdr(109)), lcd.w(hdr(110, 0)), lcd.w(hdr(102)))))
    steps.append(("S2  CLEAR, bright=255", lambda: (lcd.w(hdr(110, 255)), lcd.w(hdr(102)))))
    steps.append(("S3  CLEAR, bright=128", lambda: (lcd.w(hdr(110, 128)), lcd.w(hdr(102)))))

    def frame_step(ori, bright):
        landscape = ori in (2, 3)
        w, h = (480, 320) if landscape else (320, 480)

        def run():
            lcd.w(hdr(109)); lcd.orient(ori, w, h); time.sleep(0.05); lcd.w(hdr(110, bright)); time.sleep(0.05)
            lcd.frame(label_frame(w, h, f"S ori={ori}\nbright={bright}"))
        return run
    for ori, b in ((0, 0), (0, 255), (2, 0), (3, 0), (1, 0), (0, 200)):
        steps.append((f"S  ori={ori} bright={b}  (frame)", frame_step(ori, b)))
    for i, (name, fn) in enumerate(steps, 1):
        print(f"[{i}/{len(steps)}] {name}", flush=True)
        fn()
        time.sleep(HOLD)
    lcd.s.close()
    print("done", flush=True)


main()
