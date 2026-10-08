"""Page renderer: turns a page description (config/pages.yaml) + a sensor snapshot into a 480x320 image.

Layout (same for every page): a ring on the left, up to three cards on the right, page dots at the bottom.
Two variants (config `layout.header`): with a top bar (logos / title / clock), or compact (no bar: bigger ring,
cards stretched over the full height, logos at the ring's lower corners).
Everything is drawn at 3x and downsampled for smooth edges.
"""
import logging
import os
import re
import string

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import units

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 3
W, H = 480, 320
CARD_X0, CARD_X1, CARD_IN0, CARD_IN1 = 236, 468, 248, 458

# Everything below can be overridden in config.yaml `theme:` or in a preset file (themes/NAME.yaml, see docs/THEMING.md).
DEFAULT_THEME = {
    # colours: "#RRGGBB" or [r, g, b]
    "bg": (6, 10, 40), "panel": (12, 24, 74), "edge": (12, 84, 156), "track": (16, 36, 96),
    "cyan": (47, 208, 255), "cyan_dark": (14, 70, 120), "blue": (40, 110, 230),
    "magenta": (232, 40, 128), "amber": (255, 176, 32),
    "white": (240, 248, 255), "dim": (127, 164, 214),
    # level colours, low -> high (default: cyan, green, yellow, orange, red)
    "heat": [(47, 208, 255), (64, 224, 96), (255, 214, 0), (255, 138, 0), (240, 36, 48)],
    # thresholds shared by temperatures (°C) and utilisation (%): white below the 1st, green up to the 2nd,
    # then yellow -> orange -> red reaching red at the 3rd
    "scale": (50, 60, 100),
    "logos": (),                      # optional [left_logo.png, right_logo.png]; none shipped (trademarks)
    # background picture (optional): any image; fitted to the 480x320 screen
    "background": None,               # path relative to the project folder (or absolute)
    "background_fit": "cover",        # cover (fill + crop) | contain (fit + bars) | stretch
    "background_focus": (0.5, 0.5),   # which part of the image survives a "cover" crop (x, y in 0..1)
    "background_dim": 0.0,            # 0..1: how much the picture is pushed towards `bg` (keeps text readable)
    "background_blur": 0.0,           # px
    "panel_opacity": 1.0,             # cards: 1 = solid, lower = the background shows through
    "ring_backdrop": 0.0,             # 0..1: dark translucent disc behind the ring
    "text_shadow": False,             # dark drop shadow behind every text (helps on bright / busy pictures)
    "glow": True,                     # soft glow behind the ring
    "glow_color": (20, 40, 120),
    "disc": [(46, 12, 80), (88, 16, 104), (130, 22, 124)],   # the three rings of the centre disc, outside -> inside
    # fonts: TrueType files. The default is Windows' Bahnschrift (variable font, real bold); others get a synthetic bold.
    "font": r"C:\Windows\Fonts\bahnschrift.ttf",
    "font_bold": None,
}
COLOR_KEYS = ("bg", "panel", "edge", "track", "cyan", "cyan_dark", "blue", "magenta", "amber", "white", "dim", "glow_color")
FONT_FALLBACKS = (r"C:\Windows\Fonts\bahnschrift.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
                  "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf",
                  "/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf")


def to_rgb(v):
    """'#RRGGBB' / '#RGB' / [r, g, b] -> (r, g, b)."""
    if isinstance(v, str):
        s = v.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    return tuple(int(x) for x in v[:3])


def load_preset(name: str) -> dict:
    """themes live in config/themes/NAME.yaml (yours, git-ignored) or themes/NAME.yaml (shipped)."""
    for base in (os.path.join(ROOT, "config", "themes"), os.path.join(ROOT, "themes")):
        path = os.path.join(base, f"{name}.yaml")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    log.warning("theme preset '%s' not found (looked in config/themes and themes)", name)
    return {}


def resolve_theme(theme_cfg: dict | None) -> dict:
    th = dict(DEFAULT_THEME)
    cfg = dict(theme_cfg or {})
    preset = cfg.pop("preset", None)
    if preset:
        th.update(load_preset(str(preset)))
    th.update(cfg)                                    # explicit config.yaml values win over the preset
    for k in COLOR_KEYS:
        th[k] = to_rgb(th[k])
    th["heat"] = [to_rgb(c) for c in th["heat"]]
    th["disc"] = [to_rgb(c) for c in th["disc"]]
    th["scale"] = tuple(th["scale"])
    th["logos"] = tuple(th.get("logos") or ())      # each: an image path or {text: "AMD", color: "#ed1c24"}
    th["background_focus"] = tuple(th.get("background_focus") or (0.5, 0.5))
    return th


def project_path(p) -> str:
    p = str(p)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


LOGO_DIR = os.path.join(ROOT, "assets", "logos")           # your own logos (git-ignored): they win over the shipped ones
SHIPPED_LOGO_DIR = os.path.join(ROOT, "logos")              # the shipped library (public-domain logos, see logos/LOGOS.md)
SHIPPED_ONLY = False                                         # tools/make_screenshots.py sets it: ignore your own logos
LOGO_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _logo_dirs() -> list[str]:
    return [SHIPPED_LOGO_DIR] if SHIPPED_ONLY else [LOGO_DIR, SHIPPED_LOGO_DIR]


def list_logos() -> list[str]:
    """Names (file name without extension) of the logo library: assets/logos/ (yours) plus logos/ (shipped)."""
    names = set()
    for d in _logo_dirs():
        try:
            names |= {os.path.splitext(f)[0] for f in os.listdir(d) if f.lower().endswith(LOGO_EXTS)}
        except OSError:
            pass
    return sorted(names)


def resolve_logo(spec) -> str | None:
    """'amd' -> assets/logos/amd.png, else logos/amd.png ; anything that looks like a path (assets/x.png, an absolute path)
    is used as is ; 'none' / '' -> None."""
    s = str(spec).strip()
    if not s or s.lower() in ("none", "null", "-"):
        return None
    if any(c in s for c in "/\\") or os.path.splitext(s)[1].lower() in LOGO_EXTS:
        return project_path(s)
    for d in _logo_dirs():
        for ext in LOGO_EXTS:
            p = os.path.join(d, s + ext)
            if os.path.exists(p):
                return p
    log.warning("logo '%s' not found in assets/logos/ or logos/", s)
    return None
    if any(c in s for c in "/\\") or os.path.splitext(s)[1].lower() in LOGO_EXTS:
        return project_path(s)
    for ext in LOGO_EXTS:
        p = os.path.join(LOGO_DIR, s + ext)
        if os.path.exists(p):
            return p
    log.warning("logo '%s' not found in assets/logos/", s)
    return None


def sc(v):
    return int(round(v * S))


def box(x0, y0, x1, y1):
    return (sc(x0), sc(y0), sc(x1), sc(y1))


class SafeFormatter(string.Formatter):
    """str.format that never raises: missing/None values render as '--'. With unit 'F' temperatures are converted from °C."""

    def __init__(self, unit="C"):
        self.unit = units.norm(unit)

    def get_field(self, field_name, args, kwargs):
        try:
            obj, key = super().get_field(field_name, args, kwargs)
        except (KeyError, IndexError, AttributeError, TypeError):
            return None, field_name
        if self.unit == "F" and obj is not None and units.is_temperature_key(re.split(r"[.\[]", field_name)[0]):
            if isinstance(obj, (int, float)) and not isinstance(obj, bool):
                obj = units.c_to_f(obj)
            elif isinstance(obj, str):
                obj = units.convert_numbers(obj, "F")
        return obj, key

    def get_value(self, key, args, kwargs):
        return kwargs.get(key) if isinstance(key, str) else None

    def format_field(self, value, spec):
        if value is None:
            return "--"
        try:
            return super().format_field(value, spec)
        except (ValueError, TypeError):
            return str(value)


_FORMATTERS = {"C": SafeFormatter("C"), "F": SafeFormatter("F")}


def fmt(text, snap, unit="C"):
    u = units.norm(unit)
    return _FORMATTERS[u].vformat(units.swap_symbol(str(text), u), (), snap)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Renderer:
    def __init__(self, theme_cfg: dict | None = None, layout_cfg: dict | None = None, unit: str = "C"):
        self.unit = units.norm(unit)          # temperature unit shown (the snapshot stays in °C)
        self.t = resolve_theme(theme_cfg)
        self._fonts = {}
        self._font_path = self._find_font(self.t["font"])
        lc = layout_cfg or {}
        self.header = bool(lc.get("header", False))   # compact layout by default (see docs/THEMING.md)
        self.clock = bool(lc.get("clock", True))        # compact layout: date + time at the top-left of the ring
        self.logo_h = float(lc.get("logo_h", 22))
        self.logo_max_w = float(lc.get("logo_max_w", 90 if self.header else 46))   # wide logos shrink to fit the corner
        self._k = 1.0                       # vertical stretch of the card being drawn (compact layout)
        if self.header:                     # title + clock bar on top, logos in the top corners
            self.ring_c, self.rs = (118, 200), 1.0
            self.cards_top, self.cards_bottom, self.legend_y, self.stretch = 54, 300, 50, False
        else:                               # compact: no header; bigger ring, stretched cards, logos at the ring's lower corners
            self.ring_c, self.rs = (122, 182), float(lc.get("ring_scale", 1.15))
            self.cards_top, self.cards_bottom, self.legend_y, self.stretch = 10, 300, 8, True
        self._bg_cache = {}
        self._bg = self._background_for(None)
        self.update_text = None           # set by the app: shown small at the bottom-right when a newer version exists

    # -- helpers --------------------------------------------------------------------------------
    @staticmethod
    def _find_font(path) -> str:
        for cand in (path,) + FONT_FALLBACKS:
            if cand and os.path.exists(project_path(cand)):
                return project_path(cand)
        log.warning("no TrueType font found: using Pillow's built-in one (set theme.font to a .ttf file for a better look)")
        return ""

    def font(self, px, bold=False):
        key = (px, bold)
        entry = self._fonts.get(key)
        if entry is None:
            faux = False
            if bold and self.t.get("font_bold") and os.path.exists(project_path(self.t["font_bold"])):
                f = ImageFont.truetype(project_path(self.t["font_bold"]), sc(px))
            else:
                f = ImageFont.truetype(self._font_path, sc(px)) if self._font_path else ImageFont.load_default(size=sc(px))
                if bold:
                    try:
                        f.set_variation_by_name("Bold")      # variable fonts (Bahnschrift) have a real bold
                    except Exception:  # noqa: BLE001
                        faux = True                           # static fonts: thicken with a thin stroke
            entry = self._fonts[key] = (f, faux)
        return entry[0]

    def _faux_bold(self, px, bold) -> bool:
        self.font(px, bold)
        return self._fonts[(px, bold)][1]

    def color(self, name_or_rgb, default=None):
        if isinstance(name_or_rgb, (list, tuple)):
            return tuple(name_or_rgb)
        return self.t.get(name_or_rgb, default or self.t["white"])

    def heat(self, frac):
        """0..1 -> azzurro / verde / giallo / arancione / rosso (smooth blend between the five stops)."""
        stops = self.t["heat"]
        frac = max(0.0, min(1.0, frac)) * (len(stops) - 1)
        i = min(int(frac), len(stops) - 2)
        return lerp(stops[i], stops[i + 1], frac - i)

    @staticmethod
    def is_temp_key(key) -> bool:
        """Temperatures and % utilisation share one scheme (see temp_color)."""
        k = str(key)
        if "temp" in k or k.startswith(("mb_t", "disk_max_")) or k == "gpu_hotspot":
            return True
        usage = k.endswith(("_load", "_pct")) and "fan" not in k and not k.startswith("net_")
        return usage or k == "used_pct"

    def temp_color(self, v, bar=False):
        """Colour of a temperature (°C) / utilisation (%) value, thresholds in theme.scale = (white_below, green_until, red_at):
        text is white below the first threshold, green up to the second, then yellow -> orange -> red up to the third.
        Bars use green instead of white in the lowest band."""
        white_below, green_until, red_at = self.t["scale"]
        _, green, yellow, orange, red = self.t["heat"]
        if v < white_below:
            return green if bar else self.t["white"]
        if v < green_until:
            return green
        f = min(1.0, (v - green_until) / max(1e-9, red_at - green_until))
        return lerp(yellow, orange, f * 2) if f < 0.5 else lerp(orange, red, (f - 0.5) * 2)

    def level(self, spec, snap, base, temp_aware=True):
        """Color for a spec: base color, amber at `warn`, magenta at `crit` (judged on spec['value']).
        Temperature values (text) follow the white/yellow/orange/red temperature scheme instead."""
        if not isinstance(spec, dict) or "value" not in spec:
            return base
        v = snap.get(spec["value"])
        if v is None:
            return self.t["dim"]
        if temp_aware and self.is_temp_key(spec["value"]):
            return self.temp_color(v)
        if "crit" in spec and v >= spec["crit"]:
            return self.t["magenta"]
        if "warn" in spec and v >= spec["warn"]:
            return self.t["amber"]
        return base

    def text_of(self, spec, snap, default_color):
        if isinstance(spec, dict):
            col = self.color(spec["color"]) if "color" in spec else default_color
            return self.fmt(spec.get("text", ""), snap), self.level(spec, snap, col)
        return self.fmt(spec, snap), default_color

    def fmt(self, text, snap):
        return fmt(text, snap, self.unit)

    def draw_text(self, d, x, y, s, px, fill, anchor="la", bold=False):
        s = units.swap_symbol(s, self.unit)                   # literal "°C" in legends and titles
        stroke = sc(px * 0.035) if bold and self._faux_bold(px, bold) else 0
        font = self.font(px, bold)
        if self.t.get("text_shadow"):                     # dark drop shadow: keeps small text readable on busy pictures
            off = sc(0.9)
            d.text((sc(x) + off, sc(y) + off), s, font=font, fill=(0, 0, 0), anchor=anchor, stroke_width=stroke, stroke_fill=(0, 0, 0))
        d.text((sc(x), sc(y)), s, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=fill)

    def text_w(self, s, px):
        return self.font(px).getlength(units.swap_symbol(s, self.unit)) / S

    def slot_w(self, s, px):
        """Width reserved for a value so that what follows it never moves when its digit count changes: every digit is measured
        as the font's widest one and the first integer is padded to 3 digits for a percentage (up to 100) or 2 for anything else."""
        font = self.font(px)
        digit = max("0123456789", key=lambda c: font.getlength(c))
        m = re.search(r"\d+", s)
        if not m:
            return self.text_w(s, px)
        want = 3 if ("%" in s or "°F" in s) else 2
        pad = digit * max(0, want - len(m.group()))
        ref = s[:m.start()] + pad + re.sub(r"\d", digit, s[m.start():])
        return max(self.text_w(ref, px), self.text_w(s, px))

    # -- static background (built once) ---------------------------------------------------------
    def _background_picture(self):
        """The optional theme.background picture, fitted to the 3x canvas, blurred and dimmed; None if unusable."""
        t = self.t
        if not t.get("background"):
            return None
        try:
            im = Image.open(project_path(t["background"])).convert("RGB")
        except OSError as e:
            log.warning("cannot open background %s: %s", t["background"], e)
            return None
        tw, th = W * S, H * S
        fit = str(t.get("background_fit", "cover")).lower()
        fx, fy = t["background_focus"]
        if fit == "stretch":
            im = im.resize((tw, th), Image.LANCZOS)
        elif fit == "contain":
            k = min(tw / im.width, th / im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
            canvas = Image.new("RGB", (tw, th), t["bg"])
            canvas.paste(im, ((tw - im.width) // 2, (th - im.height) // 2))
            im = canvas
        else:                                           # cover: fill the screen, crop what does not fit
            k = max(tw / im.width, th / im.height)
            nw, nh = max(tw, int(round(im.width * k))), max(th, int(round(im.height * k)))
            im = im.resize((nw, nh), Image.LANCZOS)
            left, top = int((nw - tw) * min(1, max(0, fx))), int((nh - th) * min(1, max(0, fy)))
            im = im.crop((left, top, left + tw, top + th))
        if t.get("background_blur"):
            im = im.filter(ImageFilter.GaussianBlur(sc(float(t["background_blur"]))))
        dim = float(t.get("background_dim") or 0.0)
        if dim > 0:
            im = Image.blend(im, Image.new("RGB", im.size, t["bg"]), min(1.0, dim))
        return im

    def set_logos(self, left, right):
        """Change the two logos at run time (tray menu / --send logo:...): the static background is rebuilt."""
        self.t["logos"] = (left, right)
        self._bg_cache = {}
        self._bg = self._background_for(None)

    def _load_logo(self, spec):
        """A logo spec is an image path, or a text badge {text, color} (no image file needed). Returns an RGBA image
        `logo_h` px high (at 3x), or None."""
        if not spec:
            return None
        if isinstance(spec, dict):
            text = str(spec.get("text", "")).strip()
            if not text:
                return None
            col = to_rgb(spec.get("color", self.t["white"]))
            h = int(sc(self.logo_h))
            font = self.font(self.logo_h * 0.58, bold=True)
            w = int(font.getlength(text) + 0.85 * h)
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(h * 0.22), fill=(*self.t["bg"], 170), outline=(*col, 255), width=sc(1.3))
            d.text((w / 2, h / 2 + sc(0.3)), text, font=font, fill=col, anchor="mm")
            return im
        path = resolve_logo(spec)
        if not path:
            return None
        try:
            lg = Image.open(path).convert("RGBA")
        except OSError as e:
            log.warning("cannot open logo %s: %s", spec, e)
            return None
        k = min(self.logo_h / lg.height, self.logo_max_w / lg.width)        # fit both the height and the width budget
        return lg.resize((max(1, int(lg.width * k * S)), max(1, int(lg.height * k * S))), Image.LANCZOS)

    def _background_for(self, logos, decor=True):
        """Static background (picture, glow, brackets, logos). `logos` = a page's own pair, or None for the theme's pair; cached.
        decor=False leaves out the ring's glow, backdrop and disc (the message and alarm screens)."""
        key = (tuple(str(x) if not isinstance(x, dict) else repr(sorted(x.items())) for x in logos) if logos else None, decor)
        if key not in self._bg_cache:
            self._bg_cache[key] = self._build_background(logos, decor)
        return self._bg_cache[key]

    def _build_background(self, page_logos=None, decor=True):
        t = self.t
        img = self._background_picture() or Image.new("RGB", (W * S, H * S), t["bg"])
        cx, cy = self.ring_c
        rs = self.rs
        if decor and t.get("glow", True):
            glow = Image.new("RGB", img.size, (0, 0, 0))
            g = 120 * rs
            glow_box = box(8, 60, 228, 300) if self.header else box(cx - g, cy - g, cx + g, cy + g)
            ImageDraw.Draw(glow).ellipse(glow_box, fill=t["glow_color"])
            glow = glow.filter(ImageFilter.GaussianBlur(sc(40)))
            img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.55)
        if decor and float(t.get("ring_backdrop") or 0) > 0:      # dark translucent disc behind the ring (readability on photos)
            ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
            br = 92 * rs + 10 * rs
            ImageDraw.Draw(ov).ellipse(box(cx - br, cy - br, cx + br, cy + br),
                                       fill=(*t["bg"], int(255 * min(1.0, float(t["ring_backdrop"])))))
            img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(img)
        for (x, y, dx, dy) in ((4, 4, 1, 1), (W - 4, 4, -1, 1), (4, H - 4, 1, -1), (W - 4, H - 4, -1, -1)):
            d.line([sc(x), sc(y + 22 * dy), sc(x), sc(y), sc(x + 22 * dx), sc(y)], fill=t["edge"], width=sc(1.5))
        if self.header:
            d.line([sc(14), sc(44), sc(W - 14), sc(44)], fill=t["edge"], width=sc(1))
        # optional logos (theme.logos: [left, right], paths relative to the project folder; none are shipped).
        # With the header: top corners. Compact layout: the two lower corners of the ring's bounding box.
        logos = list(page_logos if page_logos else (t.get("logos") or ())) + [None, None]
        ring_r = 92 * rs
        if self.header:
            left_x, right_x, top_y = 14, W - 14, 9
        else:
            left_x, right_x, top_y = cx - ring_r, cx + ring_r, 298
        for spec, x, right in ((logos[0], left_x, False), (logos[1], right_x, True)):
            lg = self._load_logo(spec)
            if lg is not None:             # header layout: top-aligned at top_y ; compact layout: bottom-aligned on y = top_y
                y0 = sc(top_y) if self.header else sc(top_y) - lg.height
                img.paste(lg, (sc(x) - (lg.width if right else 0), y0), lg)
        if not decor:
            return img
        # core disc with magenta glow (static)
        disc = Image.new("RGB", img.size, (0, 0, 0))
        dd = ImageDraw.Draw(disc)
        for r, c in zip((52, 41, 28), t["disc"]):
            r *= rs
            dd.ellipse(box(cx - r, cy - r, cx + r, cy + r), fill=c)
        disc = disc.filter(ImageFilter.GaussianBlur(sc(8 * rs)))
        m = Image.new("L", img.size, 0)
        mr = 53 * rs
        ImageDraw.Draw(m).ellipse(box(cx - mr, cy - mr, cx + mr, cy + mr), fill=255)
        img.paste(disc, (0, 0), m)
        return img

    # -- page -----------------------------------------------------------------------------------
    def render(self, page: dict, snap: dict, index: int, total: int) -> Image.Image:
        t = self.t
        img = self._background_for(page.get("logos")).copy()      # a page may carry its own two logos
        cards = page.get("cards", [])
        hs = [c.get("h", 70) for c in cards]
        gap, k = 8.0, 1.0
        if self.stretch and cards:            # compact layout: stretch the cards over the whole height
            avail = self.cards_bottom - self.cards_top - gap * (len(cards) - 1)
            k = max(1.0, min(1.3, avail / sum(hs)))
            if len(cards) > 1:
                gap += min(6.0, max(0.0, avail - k * sum(hs)) / (len(cards) - 1))
        geo, y = [], self.cards_top
        for card, h in zip(cards, hs):
            geo.append((card, y, h * k))
            y += h * k + gap
        # card panels first (they may be translucent, which needs an alpha composite)
        opacity = max(0.0, min(1.0, float(t.get("panel_opacity", 1.0))))
        if opacity < 1.0:
            ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(ov)
            for _, cy0, ch in geo:
                od.rounded_rectangle(box(CARD_X0, cy0, CARD_X1, cy0 + ch), radius=sc(8), fill=(*t["panel"], int(255 * opacity)),
                                     outline=(*t["edge"], 255), width=sc(1))
            img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(img)
        if opacity >= 1.0:
            for _, cy0, ch in geo:
                d.rounded_rectangle(box(CARD_X0, cy0, CARD_X1, cy0 + ch), radius=sc(8), fill=t["panel"], outline=t["edge"], width=sc(1))
        legend_x = 14
        if self.header:
            self.draw_text(d, W / 2, 20, str(page.get("title", "")), 15, t["white"], "mm")
            self.draw_text(d, W / 2, 36, f"{snap.get('date', '')}  ·  {snap.get('time', '')}", 11, t["dim"], "mm")
        elif self.clock:                      # compact layout: date + time above the ring's left side, legend to its right
            self.draw_text(d, 14, 5, str(snap.get("time", "")), 30, t["white"], "la", bold=True)
            self.draw_text(d, 15, 40, str(snap.get("date", "")), 13, t["dim"], "la", bold=True)
        if page.get("ring"):
            self._ring(d, page["ring"], snap)
            if page["ring"].get("legend"):
                items = page["ring"]["legend"]
                if not self.header:               # compact: right-aligned, ending just before the cards
                    width = 22 + max((self.font(13, True).getlength(str(i.get("text", ""))) / S for i in items), default=0)
                    legend_x = CARD_X0 - 6 - width
                self._legend(d, items, x=legend_x, y=self.legend_y)
        for card, cy0, ch in geo:
            self._k = k
            self._card(d, card, cy0, ch, snap)
        self._k = 1.0
        # page dots + counter
        for i in range(total):
            x = W / 2 - total * 7 + i * 14 + 7
            d.ellipse(box(x - 3, 309, x + 3, 315), fill=t["cyan"] if i == index else t["track"])
        self.draw_text(d, 14, 312, f"{index + 1} / {total}", 9.5, t["dim"], "lm")
        if snap.get("update_available"):
            self.draw_text(d, W - 12, 312, f"update v{snap['update_available']}", 9.5, t["cyan"], "rm")
        return img.resize((W, H), Image.LANCZOS)

    # -- full-screen messages -------------------------------------------------------------------
    def _glow_text(self, img, xy, text, px, fill, glow, anchor="mm", bold=True, blur=7, strength=1.0):
        """Text with a soft coloured halo; `img` is the 3x canvas. Returns the new canvas."""
        layer = Image.new("RGB", img.size, (0, 0, 0))
        ld = ImageDraw.Draw(layer)
        font = self.font(px, bold)
        stroke = sc(px * 0.035) if bold and self._faux_bold(px, bold) else 0
        ld.text((sc(xy[0]), sc(xy[1])), text, font=font, fill=glow, anchor=anchor, stroke_width=stroke, stroke_fill=glow)
        layer = layer.filter(ImageFilter.GaussianBlur(sc(blur)))
        if strength != 1.0:
            layer = layer.point(lambda v: min(255, int(v * strength)))
        img = Image.blend(img, Image.composite(layer, img, layer.convert("L")), 0.85) if strength else img
        ImageDraw.Draw(img).text((sc(xy[0]), sc(xy[1])), text, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=fill)
        return img

    def render_message(self, text: str, sub: str = "") -> Image.Image:
        """The 'Ciao' screen: the theme's background and logos, one big word in the middle (screen locked / PC going off)."""
        t = self.t
        img = self._background_for(None, decor=False).copy()
        dim = Image.new("RGB", img.size, t["bg"])
        img = Image.blend(img, dim, 0.35)
        px = 84 if len(text) <= 6 else (60 if len(text) <= 10 else 40)
        img = self._glow_text(img, (W / 2, H / 2 - 8), text, px, t["white"], t["cyan"], blur=9)
        if sub:
            self.draw_text(ImageDraw.Draw(img), W / 2, H / 2 + 52, sub, 14, t["dim"], "mm")
        return img.resize((W, H), Image.LANCZOS)

    def render_alert(self, a: dict, blink: bool = False, snap: dict | None = None) -> Image.Image:
        """Full-screen overheating alarm for the component described by `a` (see alerts.TempAlarm.update)."""
        t = self.t
        red = t["heat"][-1]
        img = self._background_for(None, decor=False).copy()
        tint = Image.new("RGB", img.size, (150, 6, 14) if blink else (96, 4, 10))
        img = Image.blend(img, tint, 0.62 if blink else 0.5)
        ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.rounded_rectangle(box(190 + 52, 66, W - 12, 236), radius=sc(10), fill=(0, 0, 0, 120), outline=(*red, 255), width=sc(1))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        d = ImageDraw.Draw(img)
        # pulsing frame
        d.rounded_rectangle(box(3, 3, W - 3, H - 3), radius=sc(10), outline=red if blink else lerp(red, (0, 0, 0), 0.5), width=sc(5 if blink else 3))
        # warning triangle + title
        tri = [(30, 14), (54, 54), (6, 54)]
        d.polygon([(sc(x), sc(y)) for x, y in tri], fill=red, outline=(255, 255, 255), width=sc(1.5))
        self.draw_text(d, 30, 44, "!", 26, (255, 255, 255), "mm", bold=True)
        title = f"{a['title']} · {a['label']}"
        self.draw_text(d, 68, 26, title, 19 if len(title) < 26 else 15, (255, 255, 255), "lm", bold=True)
        self.draw_text(d, 68, 47, a["name"], 12, (255, 205, 205), "lm")
        # giant temperature with a halo
        temp = f"{a.get('temp_show', a['temp']):.0f}"
        w_num = self.font(96, True).getlength(temp) / S
        img = self._glow_text(img, (14 + w_num / 2, 128), temp, 96, (255, 255, 255), red, blur=10)
        d = ImageDraw.Draw(img)
        self.draw_text(d, 18 + w_num, 100, a.get("unit", "°C"), 30, (255, 255, 255), "lm", bold=True)
        self.draw_text(d, 18, 192, a["over"], 14, (255, 210, 120), "lm", bold=True)
        self.draw_text(d, 18, 210, a["limit_text"], 11, (255, 205, 205), "lm")
        # gauge: 0..120 °C with the limit marked
        gx0, gx1, gy = 18, 232, 232
        top = max(120.0, a["limit"] + 25, a["temp"] + 5)
        d.rounded_rectangle(box(gx0, gy, gx1, gy + 9), radius=sc(4.5), fill=(30, 6, 10))
        frac = max(0.0, min(1.0, a["temp"] / top))
        d.rounded_rectangle(box(gx0, gy, gx0 + max(9, (gx1 - gx0) * frac), gy + 9), radius=sc(4.5), fill=red)
        mx = gx0 + (gx1 - gx0) * a["limit"] / top
        d.line([sc(mx), sc(gy - 4), sc(mx), sc(gy + 13)], fill=(255, 255, 255), width=sc(1.6))
        # details
        rows = a.get("rows", [])
        y0 = 80
        pitch = min(34.0, 150.0 / max(1, len(rows)))
        for i, (label, value) in enumerate(rows):
            y = y0 + i * pitch + pitch / 2
            self.draw_text(d, 252 + 10, y - 7, str(label), 10.5, (255, 190, 190), "lm")
            self.draw_text(d, W - 24, y + 5, str(value), 17 if pitch > 28 else 14, (255, 255, 255), "rm", bold=True)
        # footer: which alarm of how many + clock
        if a.get("count", 1) > 1:
            self.draw_text(d, 18, 300, f"{a['pos']} / {a['count']}", 11, (255, 205, 205), "lm")
        if snap and snap.get("time"):
            self.draw_text(d, W - 18, 300, str(snap["time"]), 12, (255, 205, 205), "rm")
        return img.resize((W, H), Image.LANCZOS)

    # -- ring -----------------------------------------------------------------------------------
    def _ring(self, d, ring, snap):
        t = self.t
        cx, cy = self.ring_c
        rs = self.rs                          # ring scale: radii, widths, centre offsets and fonts
        vals = snap.get(ring["segments"]) if ring.get("segments") else None
        if vals is not None or ring.get("segments"):
            vals = vals or []
            n = len(vals) or ring.get("count", 12)
            R, width = ring.get("radius", 92) * rs, ring.get("width", 11 if n <= 30 else 9) * rs
            gap = 1.6 if n <= 30 else 1.0
            vmax = float(ring.get("seg_max", 100))
            for i in range(n):
                v = vals[i] if i < len(vals) and vals[i] is not None else None
                a0, a1 = -90 + i * 360 / n + gap, -90 + (i + 1) * 360 / n - gap
                if v is None:
                    col = t["track"]
                elif ring.get("seg_color") == "heat":
                    # each square keeps its own level colour; it only gets brighter as its load rises
                    frac = max(0.0, min(1.0, v / vmax))
                    col = lerp((14, 22, 62), self.heat(frac), 0.45 + 0.55 * frac)
                elif "seg_crit" in ring and v >= ring["seg_crit"]:
                    col = t["magenta"]
                elif "seg_warn" in ring and v >= ring["seg_warn"]:
                    col = t["amber"]
                else:
                    col = lerp(t["cyan_dark"], t["cyan"], (v / vmax) / ring.get("seg_sat", 0.45))
                d.arc(box(cx - R, cy - R, cx + R, cy + R), a0, a1, fill=col, width=sc(width))
        for a in ring.get("arcs", []):
            R, width = a.get("radius", 72) * rs, a.get("width", 5) * rs
            bb = box(cx - R, cy - R, cx + R, cy + R)
            d.arc(bb, 0, 360, fill=t["track"], width=sc(width))
            v = snap.get(a["value"])
            if v is None:
                continue
            lo, hi = float(a.get("min", 0)), float(snap.get(a["max"], 100)) if isinstance(a.get("max"), str) else float(a.get("max", 100))
            frac = max(0.0, min(1.0, (v - lo) / (hi - lo))) if hi > lo else 0
            if a.get("color") == "heat":
                col = self.heat(frac)                 # whole arc takes the colour of the current level
            else:
                col = self.level(a, snap, self.color(a.get("color", "cyan")), temp_aware=False)
            if frac > 0.004:
                d.arc(bb, -90, -90 + 360 * frac, fill=col, width=sc(width))
        c = ring.get("center", {})
        if "label" in c:
            self.draw_text(d, cx, cy - 32 * rs, self.fmt(c["label"], snap), 10.5 * rs, t["dim"], "mm")
        if "big" in c:
            s, col = self.text_of(c["big"], snap, t["white"])
            self.draw_text(d, cx, cy - 9 * rs, s, c.get("big_px", 36 if len(s) <= 4 else 28) * rs, col, "mm")
        if "line1" in c:
            s, col = self.text_of(c["line1"], snap, t["cyan"])
            self.draw_text(d, cx, cy + 16 * rs, s, 16 * rs, col, "mm")
        if "line2" in c:
            s, col = self.text_of(c["line2"], snap, t["dim"])
            self.draw_text(d, cx, cy + 33 * rs, s, 9 * rs, col, "mm")

    def _legend(self, d, items, x=14, y=50, row_h=15):
        """Small key in the free top-left corner (outside the ring). `icon`: 'square' = the segment squares,
        'line:N' = the Nth thin ring from the outside (0,1,2), drawn as three mini lines with the described one lit."""
        t = self.t
        for i, it in enumerate(items):
            ry = y + i * row_h
            icon = str(it.get("icon", "square"))
            if icon == "square":
                d.rounded_rectangle(box(x, ry + 1.5, x + 12, ry + 13.5), radius=sc(2.5), fill=t["cyan"])
            elif icon == "dash":                       # one single horizontal line
                d.line([sc(x), sc(ry + 7.5), sc(x + 14), sc(ry + 7.5)], fill=t["white"], width=sc(2.6))
            elif icon.startswith("line"):
                lit = -1 if icon == "lines" else int(icon[5:])      # 'lines' = all three rings lit, 'line:N' = only the Nth
                for k in range(3):
                    on = lit in (-1, k)
                    col = t["white"] if on else t["track"]
                    yy = ry + 3 + k * 4.5
                    d.line([sc(x), sc(yy), sc(x + 14), sc(yy)], fill=col, width=sc(2.4 if on else 1.6))
            self.draw_text(d, x + 22, ry + 7.5, str(it.get("text", "")), 13, t["dim"], "lm", bold=True)

    # -- cards ----------------------------------------------------------------------------------
    def _card(self, d, card, y, h, snap):
        t = self.t                              # (the panel itself was already drawn by render())
        k, fk = self._k, min(self._k, 1.2)
        self.draw_text(d, CARD_IN0, y + 9 * k, self.fmt(card.get("title", ""), snap), 10.5 * fk, t["dim"])
        getattr(self, "_card_" + card.get("kind", "main"))(d, card, y, h, snap)

    def _bar(self, d, spec, x0, x1, y, snap, height=6):
        t = self.t
        v = snap.get(spec["value"])
        mx = snap.get(spec["max"]) if isinstance(spec.get("max"), str) else spec.get("max", 100)
        d.rounded_rectangle(box(x0, y, x1, y + height), radius=sc(height / 2), fill=t["track"])
        if v is None or not mx:
            return
        frac = max(0.0, min(1.0, (v - spec.get("min", 0)) / (mx - spec.get("min", 0))))
        if spec.get("color") in ("heat", "level"):
            col = self.temp_color(v)               # exactly the same scheme as the text
        elif spec.get("color") == "spectrum":
            col = self.heat(frac)
        else:
            col = self.level(spec, snap, self.color(spec.get("color", "cyan")), temp_aware=False)
        d.rounded_rectangle(box(x0, y, x0 + max(height, (x1 - x0) * frac), y + height), radius=sc(height / 2), fill=col)

    def _card_main(self, d, card, y, h, snap):
        t = self.t
        k, fk = self._k, min(self._k, 1.2)
        tall = h / k >= 76                       # judged on the YAML height, not on the stretched one
        big_px = (30 if tall else 24) * fk
        s = ""
        if "big" in card:
            s, col = self.text_of(card["big"], snap, t["white"])
            self.draw_text(d, CARD_IN0, y + (20 if tall else 18) * k, s, big_px, col)
        right = card.get("right", [])
        if "mid" in card:
            ms, mcol = self.text_of(card["mid"], snap, t["cyan"])
            mx, mpx = CARD_IN0 + self.slot_w(s, big_px) + 14, 18 * min(fk, 1.04)
            if right:                              # the secondary value never runs into the right-hand column (°F values are wider)
                rw = max(self.text_w(self.text_of(r_, snap, t["dim"])[0], 11 * fk) for r_ in right[:2])
                room = CARD_IN1 - rw - 8 - mx
                w = self.text_w(ms, mpx)
                if w > room > 0:
                    mpx = max(11.0, mpx * room / w)
            self.draw_text(d, mx, y + (36 if tall else 33) * k, ms, mpx, mcol, "lm")
        if len(right) == 1:
            rs, rc = self.text_of(right[0], snap, t["dim"])
            self.draw_text(d, CARD_IN1, y + 35 * k, rs, 11 * fk, rc, "rm")
        elif len(right) >= 2:
            rs, rc = self.text_of(right[0], snap, t["dim"])
            self.draw_text(d, CARD_IN1, y + 12 * k, rs, 11 * fk, rc, "ra")
            rs, rc = self.text_of(right[1], snap, t["dim"])
            self.draw_text(d, CARD_IN1, y + 36 * k, rs, 11 * fk, rc, "rm")
        if "bar" in card:
            self._bar(d, card["bar"], CARD_IN0, CARD_IN1, y + h - 16 * k, snap, height=6 * fk)

    def _card_stats(self, d, card, y, h, snap):
        t = self.t
        k, fk = self._k, min(self._k, 1.2)
        items = card.get("items", [])
        n = max(len(items), 1)
        colw = (CARD_IN1 - CARD_IN0) / n
        texts = [self.text_of(it, snap, t["cyan"]) for it in items]
        base = 17.0 * fk
        widest = max((self.text_w(s, base) for s, _ in texts), default=1) or 1
        vpx = max(10.0, min(base, base * (colw - 8) / widest))   # shrink values so columns never overlap
        for i, (it, (s, col)) in enumerate(zip(items, texts)):
            x = CARD_IN0 + i * colw
            self.draw_text(d, x, y + 24 * k, self.fmt(it.get("label", ""), snap), (11 if n <= 3 else 10) * fk, t["dim"])
            self.draw_text(d, x, y + 38 * k + (base - vpx) / 3, s, vpx, col)
        foot = card.get("footer")
        if foot:
            d.line([sc(CARD_IN0), sc(y + h - 20 * k), sc(CARD_IN1 - 2), sc(y + h - 20 * k)], fill=(24, 48, 110), width=sc(1))
            fy = y + h - 10 * k
            for side in ("left", "right"):
                if side not in foot:
                    continue
                spec = foot[side]
                s, col = self.text_of(spec, snap, t["white"])
                mk = spec.get("marker") if isinstance(spec, dict) else None
                x0 = CARD_IN0 if side == "left" else CARD_IN1 - self.text_w(s, 11.5 * fk) - (14 if mk else 0)
                if mk:
                    pts = [(x0, fy - 4), (x0 + 8, fy - 4), (x0 + 4, fy + 3)] if mk == "down" else \
                          [(x0, fy + 3), (x0 + 8, fy + 3), (x0 + 4, fy - 4)]
                    d.polygon([(sc(px), sc(py)) for px, py in pts], fill=t["cyan"] if mk == "down" else t["magenta"])
                    x0 += 14
                self.draw_text(d, x0, fy, s, 11.5 * fk, col, "lm")

    def _card_list(self, d, card, y, h, snap):
        t = self.t
        if "rows_from" in card:
            a, b = card.get("slice", [0, 8])
            rows = [{**snap, **r} for r in (snap.get(card["rows_from"]) or [])[a:b]]
            spec = card.get("row", {})
            specs = [spec] * len(rows)
        else:
            rows, specs = [snap] * len(card.get("rows", [])), card.get("rows", [])
        kk, fk = self._k, min(self._k, 1.2)
        rowh = card.get("row_h", 20) * kk
        for i, (rs, spec) in enumerate(zip(rows, specs)):
            ry = y + 28 * kk + i * rowh
            label = self.fmt(spec.get("label", ""), rs)
            self.draw_text(d, CARD_IN0, ry, label, 11.5 * fk, t["white"], "lm")
            s, col = self.text_of({key: v for key, v in spec.items() if key != "label"}, rs, t["cyan"])
            vpx, room, w = 11.5 * fk, (CARD_IN1 - CARD_IN0) - self.text_w(label, 11.5 * fk) - 10, self.text_w(s, 11.5 * fk)
            if w > room > 0:                       # a long value (eight core temperatures in °F) shrinks instead of covering the label
                vpx = max(7.5, vpx * room / w)
            self.draw_text(d, CARD_IN1, ry, s, vpx, col, "rm")
            if "bar" in spec:
                self._bar(d, spec["bar"], CARD_IN0, CARD_IN1, ry + 8 * kk, rs, height=3 * fk)
        if not rows:
            self.draw_text(d, CARD_IN0, y + 36 * kk, "--", 12 * fk, t["dim"], "lm")

    def _card_spark(self, d, card, y, h, snap):
        t = self.t
        k, fk = self._k, min(self._k, 1.2)
        if "big" in card:
            s, col = self.text_of(card["big"], snap, t["white"])
            self.draw_text(d, CARD_IN0, y + 20 * k, s, 22 * fk, col)
        if "right" in card:
            rs, rc = self.text_of(card["right"], snap, t["dim"])
            self.draw_text(d, CARD_IN1, y + 30 * k, rs, 11 * fk, rc, "rm")
        hist = snap.get(card.get("history")) or []
        x0, x1, y1, y0 = CARD_IN0, CARD_IN1, y + h - 8 * k, y + h - 32 * k - (k - 1) * 12
        d.rectangle(box(x0, y0, x1, y1), fill=(8, 18, 58))
        if len(hist) >= 2:
            mx = max(max(hist), card.get("floor", 1.0))
            n = len(hist)
            pts = [(x0 + (x1 - x0) * i / (n - 1), y1 - (y1 - y0) * (v / mx)) for i, v in enumerate(hist)]
            col = self.color(card.get("color", "cyan"))
            d.polygon([(sc(x0), sc(y1))] + [(sc(px), sc(py)) for px, py in pts] + [(sc(x1), sc(y1))], fill=lerp(t["panel"], col, 0.35))
            d.line([(sc(px), sc(py)) for px, py in pts], fill=col, width=sc(1.4))
