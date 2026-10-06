"""Generates the procedural background pictures shipped in themes/img/ (original artwork, no third-party images).

    python tools/make_backgrounds.py

Every picture is 960x640 (2x the screen) and deterministic (fixed seeds). Re-run it after editing a recipe.
"""
import math
import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

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


CY, BL, VI, PK = (0, 205, 255), (35, 95, 255), (150, 70, 255), (210, 80, 255)


def _glow(layer, r1=3, r2=14, k1=0.9, k2=1.1):
    a = layer.filter(ImageFilter.GaussianBlur(r1)); b = layer.filter(ImageFilter.GaussianBlur(r2))
    out = ImageChops.add(layer, a.point(lambda v: int(v * k1)))
    return ImageChops.add(out, b.point(lambda v: int(v * k2)))


def neon():
    """Blue / cyan / violet: angular cuts, hex grid and circuit traces (gaming-hardware flavour, no brand marks)."""
    rng = np.random.default_rng(690)
    # --- base: deep navy -> indigo diagonal gradient
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = np.clip((xx / W) * 0.45 + (yy / H) * 0.55, 0, 1)
    stops = [(0.0, (4, 10, 34)), (0.45, (8, 20, 78)), (0.8, (28, 16, 92)), (1.0, (40, 14, 104))]
    base = np.stack([np.interp(t, [p for p, _ in stops], [c[i] for _, c in stops]) for i in range(3)], -1)

    # soft colour clouds
    cl = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(cl)
    for (x, y, r, col, a) in [(120, 520, 260, VI, .55), (860, 90, 280, CY, .40), (500, 330, 300, BL, .35), (880, 560, 220, PK, .35), (60, 80, 180, BL, .45)]:
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(c * a) for c in col))
    cl = cl.filter(ImageFilter.GaussianBlur(90))
    base = np.clip(base + np.asarray(cl, np.float32) * 0.55, 0, 255)
    img = Image.fromarray(base.astype(np.uint8))

    # --- hex grid, fading towards the top-right
    hexl = Image.new("L", (W, H), 0); hd = ImageDraw.Draw(hexl)
    s = 34; hh = s * math.sqrt(3)
    for row in range(-1, int(H / hh) + 2):
        for col in range(-1, int(W / (1.5 * s)) + 2):
            cx = col * 1.5 * s; cy = row * hh + (hh / 2 if col % 2 else 0)
            pts = [(cx + s * math.cos(math.radians(60 * i)), cy + s * math.sin(math.radians(60 * i))) for i in range(6)]
            hd.line(pts + [pts[0]], fill=255, width=1)
    fade = np.clip(((xx / W) * 0.9 + (1 - yy / H) * 0.5) - 0.35, 0, 1) ** 1.2
    hexl = Image.fromarray((np.asarray(hexl, np.float32) * fade * 0.30).astype(np.uint8))
    img = ImageChops.add(img, Image.merge("RGB", [hexl.point(lambda v: int(v * c / 255)) for c in (110, 190, 255)]))

    # --- big angular slashes (ROG-style cuts)
    def poly(layer_draw, pts, fill=None, line=None, w=2):
        if fill: layer_draw.polygon(pts, fill=fill)
        if line: layer_draw.line(pts + [pts[0]], fill=line, width=w)

    fill = Image.new("RGB", (W, H)); fd = ImageDraw.Draw(fill)
    edge = Image.new("RGB", (W, H)); ed = ImageDraw.Draw(edge)
    slashes = [  # (points, fill colour, edge colour)
        ([(-40, 470), (560, 160), (700, 160), (100, 520)], (26, 70, 190), CY),
        ([(260, 700), (820, 330), (1000, 330), (440, 700)], (70, 36, 170), VI),
        ([(560, -40), (780, -40), (560, 120), (480, 120)], (20, 80, 200), BL),
        ([(-40, 120), (200, -40), (300, -40), (-40, 210)], (60, 30, 150), PK),
    ]
    for pts, f, e in slashes:
        poly(fd, pts, fill=tuple(int(c * .55) for c in f))
        poly(ed, pts, line=e, w=2)
    img = ImageChops.add(img, fill.filter(ImageFilter.GaussianBlur(1)))
    img = ImageChops.add(img, _glow(edge, 2, 10, .8, 1.0))
    # thin parallel accent lines in the same 'ROG' direction
    acc = Image.new("RGB", (W, H)); ad = ImageDraw.Draw(acc)
    for i, (x0, col) in enumerate([(300, CY), (330, BL), (360, VI)]):
        ad.line([(x0 + 90, 700), (x0 + 700, 120 - i * 0)], fill=tuple(int(c * .55) for c in col), width=1)
    img = ImageChops.add(img, _glow(acc, 2, 8, .6, .7))

    # --- circuit traces with nodes
    tr = Image.new("RGB", (W, H)); td = ImageDraw.Draw(tr)
    def trace(x, y, steps, col):
        pts = [(x, y)]
        for dx, dy in steps:
            x += dx; y += dy; pts.append((x, y))
        td.line(pts, fill=col, width=2)
        td.ellipse((x - 5, y - 5, x + 5, y + 5), outline=col, width=2)
        td.ellipse((pts[0][0] - 3, pts[0][1] - 3, pts[0][0] + 3, pts[0][1] + 3), fill=col)
    c1 = tuple(int(c * .85) for c in CY); c2 = tuple(int(c * .85) for c in VI); c3 = tuple(int(c * .8) for c in BL)
    trace(40, 600, [(120, 0), (60, -60), (0, -90)], c1)
    trace(40, 560, [(70, 0), (40, -40), (0, -70), (60, -60)], c3)
    trace(20, 612, [(200, 0), (50, -50), (140, 0)], c2)
    trace(920, 40, [(-110, 0), (-60, 60), (0, 80)], c1)
    trace(920, 80, [(-60, 0), (-40, 40), (0, 60), (-60, 60)], c2)
    trace(940, 28, [(-190, 0), (-50, 50), (-120, 0)], c3)
    trace(900, 610, [(-90, 0), (-50, -50), (0, -60)], c3)
    img = ImageChops.add(img, _glow(tr, 1, 7, .9, .8))

    # --- vignette, scanline texture, grain
    a = np.asarray(img, np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    a *= (1 - 0.5 * np.clip(d - 0.4, 0, 1))[..., None]
    a *= (1 - 0.06 * (yy % 4 < 1))[..., None]
    a += rng.normal(0, 2.0, a.shape)
    save(a, "neon.jpg")


if __name__ == "__main__":
    for fn in (nebula, grid, carbon, sunset, aurora, neon):
        fn()
