"""Builds docs/img/all_pages.png (grid of every page) from the demo screenshots.
Run:  python -m displaymonitor --demo   then   python tools/make_montage.py
"""
import glob
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = sorted(glob.glob(os.path.join(ROOT, "docs", "img", "0*.png")))
cols, w, h, gap = 2, 480, 320, 8
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * h + (rows + 1) * gap), (24, 26, 34))
for i, f in enumerate(files):
    sheet.paste(Image.open(f), (gap + (i % cols) * (w + gap), gap + (i // cols) * (h + gap)))
out = os.path.join(ROOT, "docs", "img", "all_pages.png")
sheet.save(out)
print("written", out, sheet.size)
