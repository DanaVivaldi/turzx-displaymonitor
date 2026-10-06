"""Regenerates EVERY image of the repository (docs/img/*.png) with invented data:

  * one screenshot per page   -> docs/img/NN_<page>.png
  * the grid of all pages     -> docs/img/all_pages.png   (the picture at the top of the README)
  * the theme gallery         -> docs/img/themes.png

Each screenshot uses a different pair of logos from your logo library (assets/logos/, see docs/THEMING.md) to show that the two
bottom logos can be swapped. Logos that are not in the library are simply left out. The repository ships no logo files: the
screenshots show a few vendor logos only to illustrate the feature (the marks belong to their owners).

    python tools/make_screenshots.py
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

# (left logo, right logo) per page / per theme: an arbitrary mix of vendors, on purpose
PAGE_LOGOS = {
    "overview": ("intel", "rog"), "cpu": ("amd", "rog"), "gpu": ("intel", "msi"), "motherboard": ("amd", "aorus"),
    "disks": ("intel", "nzxt"), "memory": ("amd", "msi"), "network": ("intel", "aorus"), "system": ("amd", "rog"),
}
THEME_LOGOS = {
    "aurora": ("amd", "msi"), "default": ("intel", "rog"), "ember": ("intel", "aorus"),
    "grid": ("amd", "nzxt"), "nebula": ("intel", "msi"), "sunset": ("amd", "rog"),
}


def montage(images, labels=None, cols=2, w=480, h=320, gap=8, label_h=0):
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * (h + label_h) + (rows + 1) * gap), (24, 26, 34))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for i, im in enumerate(images):
        x, y = gap + (i % cols) * (w + gap), gap + (i // cols) * (h + label_h + gap)
        sheet.paste(im, (x, y + label_h))
        if labels:
            d.text((x + 4, y + 2), labels[i], fill=(235, 240, 250), font=font)
    return sheet


def main():
    cfg, pages = load_config(examples=True)
    snap = demo_snapshot("en")
    out = os.path.join(ROOT, "docs", "img")
    os.makedirs(out, exist_ok=True)
    plist = pages["pages"]
    shots = []
    for i, p in enumerate(plist):
        left, right = PAGE_LOGOS.get(p["id"], (None, None))
        im = Renderer({"logos": [left, right]}, {"header": False}).render(p, snap, i, len(plist))
        im.save(os.path.join(out, f"{i + 1:02d}_{p['id']}.png"))
        shots.append(im)
        print(f"{i + 1:02d}_{p['id']:<12} logos: {left} + {right}")
    montage(shots).save(os.path.join(out, "all_pages.png"))
    print("all_pages.png")

    names = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(ROOT, "themes", "*.yaml")))
    ths = []
    for n in names:
        left, right = THEME_LOGOS.get(n, ("intel", "rog"))
        ths.append(Renderer({"preset": n, "logos": [left, right]}, {"header": False}).render(plist[0], snap, 0, len(plist)))
    montage(ths, labels=names, label_h=22).save(os.path.join(out, "themes.png"))
    print("themes.png:", ", ".join(names))


if __name__ == "__main__":
    main()
