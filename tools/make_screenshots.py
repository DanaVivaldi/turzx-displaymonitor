"""Regenerates EVERY image of the repository (docs/img/*.png) with invented data:

  * one screenshot per page   -> docs/img/NN_<page>.png
  * the grid of all pages     -> docs/img/all_pages.png   (the picture at the top of the README)
  * the theme gallery         -> docs/img/themes.png

Each screenshot uses a different pair of logos to show that the two bottom logos can be swapped. ONLY the shipped, public-domain
library (logos/, see logos/LOGOS.md) is used, never your own assets/logos/, so the published images contain nothing else.
The marks still belong to their owners (nominative use, see THIRD_PARTY_NOTICES.md).

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
from displaymonitor import render as render_mod  # noqa: E402
from displaymonitor.render import Renderer  # noqa: E402

render_mod.SHIPPED_ONLY = True          # ignore assets/logos: the screenshots may only show the shipped public-domain logos

# (left logo, right logo) per page / per theme: an arbitrary mix of vendors, on purpose
PAGE_LOGOS = {
    "overview": ("intel", "asus"), "cpu": ("ryzen", "msi"), "gpu": ("geforce", "gigabyte"), "motherboard": ("amd", "asrock"),
    "disks": ("intel-core", "rog-classic"), "memory": ("radeon", "zotac"), "network": ("nvidia", "nzxt"), "system": ("intel-arc", "evga"),
}
THEME_LOGOS = {
    "aurora": ("ryzen", "msi"), "default": ("intel", "asus"), "ember": ("intel-core", "gigabyte"),
    "grid": ("amd", "corsair"), "nebula": ("geforce", "msi"), "sunset": ("radeon", "asrock"),
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

    # the Italian language pack (used by README.it.md)
    cfg_it, pages_it = load_config(examples=True, lang="it")
    snap_it = demo_snapshot("it")
    shots_it = []
    for i, p in enumerate(pages_it["pages"]):
        left, right = PAGE_LOGOS.get(p["id"], (None, None))
        shots_it.append(Renderer({"logos": [left, right]}, {"header": False}).render(p, snap_it, i, len(pages_it["pages"])))
    montage(shots_it).save(os.path.join(out, "all_pages_it.png"))
    print("all_pages_it.png")

    names = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(ROOT, "themes", "*.yaml")))
    ths = []
    for n in names:
        left, right = THEME_LOGOS.get(n, ("intel", "rog"))
        ths.append(Renderer({"preset": n, "logos": [left, right]}, {"header": False}).render(plist[0], snap, 0, len(plist)))
    montage(ths, labels=names, label_h=22).save(os.path.join(out, "themes.png"))
    print("themes.png:", ", ".join(names))


if __name__ == "__main__":
    main()
