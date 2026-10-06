"""Adds a logo to the library (assets/logos/NAME.png) so it can be picked from the tray menu or used in config.yaml.

    python tools/import_logo.py downloaded_logo.png --name amd
    python tools/import_logo.py logo.jpg --name asus --remove-bg          # make the flat background transparent
    python tools/import_logo.py black_logo.png --name msi --white          # dark logo on transparent -> white (for dark themes)

Options
  --name NAME       library name (default: the file name). Use it as `theme.logos: [NAME, ...]` or from the tray.
  --remove-bg [T]   make the background transparent: the colour found along the picture's border is removed, T = tolerance 0-255 (default 30)
  --white           paint every visible pixel white (keeps the transparency): for dark/black logos
  --height PX       maximum stored height (default 160; the screen shows them 22 px high at 3x supersampling = 66 px)

The logo is trimmed to its visible pixels. Brand logos are trademarks: use the ones the vendor publishes for that purpose.
"""
import argparse
import os
import re
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO_DIR = os.path.join(ROOT, "assets", "logos")


def remove_background(im: Image.Image, tol: float) -> Image.Image:
    a = np.asarray(im.convert("RGBA")).astype(np.float32)
    border = np.concatenate([a[0, :, :3], a[-1, :, :3], a[:, 0, :3], a[:, -1, :3]])     # the 1 px frame of the picture
    bg = np.median(border, axis=0)
    dist = np.sqrt(((a[..., :3] - bg) ** 2).sum(axis=2))
    soft = np.clip((dist - tol) / max(tol * 0.6, 1.0), 0, 1)              # soft edge instead of a hard cut
    a[..., 3] = np.minimum(a[..., 3], soft * 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def trim(im: Image.Image, margin: int = 2) -> Image.Image:
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        return im
    l, t, r, b = box
    return im.crop((max(0, l - margin), max(0, t - margin), min(im.width, r + margin), min(im.height, b + margin)))


def main():
    ap = argparse.ArgumentParser(description="Add a logo to assets/logos/")
    ap.add_argument("source", help="image file (png/jpg/webp/...)")
    ap.add_argument("--name", help="name in the library (default: file name)")
    ap.add_argument("--remove-bg", nargs="?", const=30.0, type=float, metavar="TOL", help="make the border colour transparent")
    ap.add_argument("--white", action="store_true", help="paint visible pixels white")
    ap.add_argument("--height", type=int, default=160, help="maximum stored height in px")
    a = ap.parse_args()

    im = Image.open(a.source).convert("RGBA")
    if a.remove_bg is not None:
        im = remove_background(im, a.remove_bg)
    im = trim(im)
    if a.white:
        arr = np.asarray(im).copy()
        arr[..., :3] = 255
        im = Image.fromarray(arr, "RGBA")
    if im.height > a.height:
        im = im.resize((max(1, round(im.width * a.height / im.height)), a.height), Image.LANCZOS)
    name = re.sub(r"[^a-z0-9_-]+", "-", (a.name or os.path.splitext(os.path.basename(a.source))[0]).lower()).strip("-") or "logo"
    os.makedirs(LOGO_DIR, exist_ok=True)
    out = os.path.join(LOGO_DIR, name + ".png")
    im.save(out, optimize=True)
    print(f"saved {out}  ({im.width}x{im.height})")
    print(f"use it:  theme: {{logos: [{name}, ...]}}   or pick '{name}' in the tray menu (Left logo / Right logo)")


if __name__ == "__main__":
    sys.exit(main())
