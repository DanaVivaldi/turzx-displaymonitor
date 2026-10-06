"""Renders the Overview page of every shipped theme preset (themes/*.yaml) with invented data, in the compact layout,
into one labelled montage, docs/img/themes.png.

    python tools/make_gallery.py            # all shipped presets
    python tools/make_gallery.py nebula ember
"""
import glob
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from displaymonitor.app import load_config  # noqa: E402
from displaymonitor.demo import demo_snapshot  # noqa: E402
from displaymonitor.render import Renderer  # noqa: E402


def main():
    cfg, pages = load_config(examples=True)
    names = sys.argv[1:] or sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "themes", "*.yaml")))
    snap = demo_snapshot("en")
    shots = []
    for name in names:
        r = Renderer({"preset": name}, {"header": False})
        im = r.render(pages["pages"][0], snap, 0, len(pages["pages"]))
        shots.append((name, im))
        print("rendered", name)
    cols, w, h, gap, label = 2, 480, 320, 8, 22
    rows = (len(shots) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * (h + label) + (rows + 1) * gap), (24, 26, 34))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for i, (name, im) in enumerate(shots):
        x, y = gap + (i % cols) * (w + gap), gap + (i // cols) * (h + label + gap)
        sheet.paste(im, (x, y + label))
        d.text((x + 4, y + 2), name, fill=(235, 240, 250), font=font)
    sheet.save(os.path.join(ROOT, "docs", "img", "themes.png"))
    print("montage written", sheet.size)


if __name__ == "__main__":
    main()
