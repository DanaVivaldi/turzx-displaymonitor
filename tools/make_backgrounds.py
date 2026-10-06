"""Generates the procedural background pictures shipped in themes/img/ (original artwork, no third-party images).

    python tools/make_backgrounds.py

Every picture is 960x640 (2x the screen) and deterministic (fixed seeds). Re-run it after editing a recipe.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "themes", "img")
W, H = 960, 640


def vgrad(top, bottom, stops=None):
    """Vertical gradient (list of (pos, rgb) stops, or just top/bottom colours)."""
    stops = stops or [(0.0, top), (1.0, bottom)]
    y = np.linspace(0, 1, H)[:, None]
    out = np.zeros((H, W, 3), dtype=np.float32)
    for c in range(3):
        out[..., c] = np.interp(y[:, 0], [p for p, _ in stops], [col[c] for _, col in stops])[:, None]
    return out


def vignette(arr, strength=0.55):
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    return arr * (1 - strength * np.clip(d - 0.35, 0, 1)[..., None])


def blobs(arr, rng, colors, n, rmin, rmax, alpha):
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        col = colors[rng.integers(len(colors))]
        r = rng.integers(rmin, rmax)
        x, y = rng.integers(0, W), rng.integers(0, H)
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(c * alpha) for c in col))
    layer = layer.filter(ImageFilter.GaussianBlur(70))
    return np.clip(arr + np.asarray(layer, dtype=np.float32), 0, 255)


def stars(arr, rng, n, bright=(120, 255)):
    for _ in range(n):
        x, y = rng.integers(0, W), rng.integers(0, H)
        v = rng.integers(*bright)
        r = 1 if rng.random() > 0.15 else 2
        arr[max(0, y - r + 1):y + r, max(0, x - r + 1):x + r] = np.clip(arr[max(0, y - r + 1):y + r, max(0, x - r + 1):x + r] + v * 0.6, 0, 255)
    return arr


def save(arr, name):
    os.makedirs(OUT, exist_ok=True)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(os.path.join(OUT, name), quality=88, optimize=True)
    print("wrote", name)


def nebula():
    rng = np.random.default_rng(7)
    a = vgrad((6, 8, 30), (14, 8, 38))
    a = blobs(a, rng, [(40, 70, 190), (120, 40, 170), (30, 120, 170)], 9, 120, 260, 0.55)
    a = stars(a, rng, 420)
    save(vignette(a, 0.6), "nebula.jpg")


def grid():
    a = vgrad((4, 10, 28), (6, 22, 44), [(0, (4, 10, 28)), (0.55, (8, 20, 44)), (1, (4, 14, 30))])
    img = Image.fromarray(a.astype(np.uint8)); d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 64):
        d.line((x, 0, x, H), fill=(40, 190, 255, 26), width=1)
    for y in range(0, H, 64):
        d.line((0, y, W, y), fill=(40, 190, 255, 26), width=1)
    for x in range(0, W, 192):
        for y in range(0, H, 192):
            d.line((x - 8, y, x + 8, y), fill=(60, 220, 255, 70)); d.line((x, y - 8, x, y + 8), fill=(60, 220, 255, 70))
    glow = Image.new("RGB", (W, H), (0, 0, 0)); ImageDraw.Draw(glow).ellipse((-100, 330, 560, 760), fill=(10, 70, 110))
    a = np.clip(np.asarray(img, dtype=np.float32) + np.asarray(glow.filter(ImageFilter.GaussianBlur(90)), dtype=np.float32), 0, 255)
    save(vignette(a, 0.5), "grid.jpg")


def carbon():
    rng = np.random.default_rng(3)
    tile = np.zeros((16, 16), dtype=np.float32)
    tile[:8, :8] = 1.0; tile[8:, 8:] = 1.0                      # basket weave
    tile = tile * 0.55 + 0.25
    yy, xx = np.mgrid[0:H, 0:W]
    weave = np.tile(tile, (H // 16 + 1, W // 16 + 1))[:H, :W]
    shade = (np.sin(xx / 110.0 + yy / 170.0) * 0.5 + 0.5) * 0.35 + 0.65       # soft diagonal sheen
    base = (weave * shade * 34)[..., None] * np.array([1.0, 0.95, 0.95])
    glow = Image.new("RGB", (W, H), (0, 0, 0)); ImageDraw.Draw(glow).ellipse((-220, 360, 520, 900), fill=(120, 50, 10))
    a = np.clip(base + np.asarray(glow.filter(ImageFilter.GaussianBlur(110)), dtype=np.float32) * 0.8, 0, 255)
    save(vignette(a, 0.5), "carbon.jpg")


def sunset():
    a = vgrad(None, None, [(0, (14, 8, 40)), (0.45, (70, 20, 90)), (0.7, (190, 60, 90)), (0.88, (255, 150, 70)), (1, (60, 20, 40))])
    sun = Image.new("RGB", (W, H), (0, 0, 0)); ImageDraw.Draw(sun).ellipse((560, 330, 860, 630), fill=(255, 190, 110))
    a = np.clip(a + np.asarray(sun.filter(ImageFilter.GaussianBlur(60)), dtype=np.float32) * 0.6, 0, 255)
    img = Image.fromarray(a.astype(np.uint8)); d = ImageDraw.Draw(img)
    rng = np.random.default_rng(11)
    for layer, (base_y, amp, col) in enumerate([(470, 70, (40, 16, 56)), (540, 55, (24, 10, 36)), (600, 40, (12, 6, 20))]):
        pts = [(0, H)]
        ph = rng.random() * 6
        for x in range(0, W + 20, 20):
            pts.append((x, base_y + amp * math.sin(x / (120 + 40 * layer) + ph) + amp * 0.5 * math.sin(x / 47 + ph * 2)))
        pts.append((W, H))
        d.polygon(pts, fill=col)
    save(vignette(np.asarray(img, dtype=np.float32), 0.45), "sunset.jpg")


def aurora():
    rng = np.random.default_rng(21)
    a = vgrad((3, 8, 22), (6, 20, 34))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for k, (col, y0, amp) in enumerate([((30, 255, 150), 190, 70), ((60, 170, 255), 250, 55), ((150, 70, 255), 150, 45)]):
        wave = y0 + amp * np.sin(xx / 170.0 + k * 1.7) + 25 * np.sin(xx / 53.0 + k)
        band = np.exp(-((yy - wave) / (38 + 12 * k)) ** 2)
        a += band[..., None] * np.array(col, dtype=np.float32) * 0.42 * (0.6 + 0.4 * np.sin(xx / 90.0 + k)[..., None])
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))
    a = stars(np.asarray(img, dtype=np.float32), rng, 300)
    save(vignette(a, 0.55), "aurora.jpg")


if __name__ == "__main__":
    for fn in (nebula, grid, carbon, sunset, aurora):
        fn()
