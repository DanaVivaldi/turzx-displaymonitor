"""Builds the shipped logo library (logos/*.png) from Wikimedia Commons and writes logos/LOGOS.md (sources + licences).

    python tools/fetch_logos.py            # download everything in MANIFEST
    python tools/fetch_logos.py --check    # only print the licence of each file, download nothing

Only files whose Commons licence is *Public domain* or *CC0* (and that Commons does not mark as copyrighted) are accepted: the script refuses
anything else. These marks are still TRADEMARKS of their owners (Commons tags them "trademarked"): copyright-free is not the same as
"you may use it for anything". The library is shipped for identification of the hardware you actually own (nominative use) and for nothing else.

Each logo is rendered to PNG by Commons (SVG -> PNG), trimmed, and, when `white` is set, painted white (a monochrome version for the
dark UI; colours can be restored from the Commons original linked in LOGOS.md).
"""
import argparse
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "logos")
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "turzx-displaymonitor-logo-fetch/1.0 (https://github.com/DanaVivaldi/turzx-displaymonitor)"}
ALLOWED = ("public domain", "cc0")

# name -> (brand / what it is, Commons file title, recolour for the dark UI: False | "white" | "lighten")
MANIFEST = {
    "intel": ("Intel", "File:Intel logo 2023.svg", False),
    "intel-core": ("Intel Core", "File:Intel Core 2020 logo.svg", False),
    "intel-arc": ("Intel Arc (white)", "File:Intel Arc logo (white).svg", False),
    "amd": ("AMD", "File:AMD Logo.svg", "white"),
    "ryzen": ("AMD Ryzen", "File:AMD Ryzen logo.svg", "matte"),
    "radeon": ("AMD Radeon", "File:New AMD Radeon logo (2020).svg", "matte"),
    "nvidia": ("NVIDIA", "File:Nvidia logo.svg", "white"),
    "geforce": ("NVIDIA GeForce", "File:GeForce (2022).svg", False),
    "geforce-rtx": ("NVIDIA GeForce RTX 30 series", "File:RTX 30 series logo with slogan.svg", False),
    "asus": ("ASUS", "File:ASUS Logo.svg", "white"),
    "rog-classic": ("ASUS ROG (2007 logo)", "File:ASUS ROG 2007 logo.svg", "lighten"),
    "msi": ("MSI", "File:Micro-Star International logo2020.svg", "white"),
    "gigabyte": ("GIGABYTE", "File:Gigabyte Technology Logo.svg", "white"),
    "asrock": ("ASRock", "File:ASRock Logo.svg", "white"),
    "evga": ("EVGA", "File:EVGA Logo.svg", False),
    "zotac": ("ZOTAC", "File:Logo of Zotac International.svg", False),
    "sapphire": ("Sapphire", "File:Sapphire wordmark.svg", False),
    "powercolor": ("PowerColor", "File:Powercolor 2024 logo.svg", "lighten"),
    "xfx": ("XFX", "File:XFX 2019 logo.svg", "white"),
    "pny": ("PNY", "File:PNY Technologies logo.svg", "white"),
    "palit": ("Palit", "File:Palit logo.svg", "lighten"),
    "inno3d": ("Inno3D", "File:Inno3d logo.svg", "white"),
    "nzxt": ("NZXT", "File:Logo NZXT.svg", "white"),
    "corsair": ("Corsair", "File:Corsair 2020 logo.svg", "white"),
    "coolermaster": ("Cooler Master", "File:Cooler Master Logo.svg", False),
}


def api(params):
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.load(r)


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def info(title):
    res = api({"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 700})
    page = next(iter(res["query"]["pages"].values()))
    ii = (page.get("imageinfo") or [None])[0]
    if not ii:
        raise RuntimeError(f"{title}: not found")
    m = ii.get("extmetadata", {})
    return {
        "license": clean(m.get("LicenseShortName", {}).get("value")),
        "copyrighted": clean(m.get("Copyrighted", {}).get("value")),
        "restrictions": clean(m.get("Restrictions", {}).get("value")),
        "artist": clean(m.get("Artist", {}).get("value")),
        "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe=":()"),
        "thumb": ii.get("thumburl") or ii["url"],
    }


def process(png: bytes, mode) -> Image.Image:
    """mode: False = untouched, "white" = every visible pixel white (black monochrome logos),
    "lighten" = only the dark pixels become white (keeps colours: multi-colour logos with dark text),
    "matte" = dark logo on a white plate -> white logo on a transparent background."""
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        l, t, r, b = box
        im = im.crop((max(0, l - 2), max(0, t - 2), min(im.width, r + 2), min(im.height, b + 2)))
    if mode:
        arr = np.asarray(im).copy()
        if mode == "white":
            arr[..., :3] = 255
        elif mode == "matte":                      # dark logo on a white plate -> white logo on transparency (luminance = opacity)
            lum = arr[..., :3].astype(np.float32).mean(axis=2)
            arr[..., 3] = (arr[..., 3].astype(np.float32) * (1 - lum / 255.0)).astype(np.uint8)
            arr[..., :3] = 255
        else:
            dark = arr[..., :3].max(axis=2) < 95
            arr[dark, :3] = 255
        im = Image.fromarray(arr, "RGBA")
    if im.height > 220:
        im = im.resize((max(1, round(im.width * 220 / im.height)), 220), Image.LANCZOS)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only print licences")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    rows, refused = [], []
    for name, (brand, title, white) in MANIFEST.items():
        try:
            meta = info(title)
        except Exception as e:  # noqa: BLE001
            print(f"{name:<13} ERROR {e}")
            refused.append(name)
            continue
        ok = meta["license"].lower() in ALLOWED and meta["copyrighted"].lower() != "true"
        print(f"{name:<13} {meta['license']:<18} copyrighted={meta['copyrighted'] or '?':<6} {'OK' if ok else 'REFUSED'}  {title}")
        if not ok:
            refused.append(name)
            continue
        if not a.check:
            req = urllib.request.Request(meta["thumb"], headers=UA)
            im = process(urllib.request.urlopen(req, timeout=60).read(), white)
            im.save(os.path.join(OUT, name + ".png"), optimize=True)
            time.sleep(0.4)
        rows.append((name, brand, title, meta, white))
    if a.check:
        return
    today = datetime.date.today().isoformat()
    md = ["# Logo library", "",
          "Logos for identifying the hardware you own (CPU, GPU, motherboard, board partners), picked from the tray menu or `theme.logos` / a page's `logos:`.",
          "",
          "**Copyright vs trademark.** Every file below is marked *Public domain* (or CC0, not copyrighted) on Wikimedia Commons — typically because it is",
          "a simple text/geometric logo below the threshold of originality. They are nevertheless **registered trademarks of their owners**",
          "(Commons tags them \"trademarked\"). They are shipped only so you can identify your own hardware (nominative use); this project is not",
          "affiliated with or endorsed by any of these companies. Do not use them in a way that suggests endorsement. If you are a rights holder and want",
          "a file removed, open an issue.", "",
          "Logos whose licence is not clearly free (for example AORUS, the current ROG \"eye\" or any vendor-theme artwork) are deliberately NOT included:",
          "import your own copy into `assets/logos/` (git-ignored) with `tools/import_logo.py`, see [docs/THEMING.md](../docs/THEMING.md#logos).", "",
          f"Fetched {today} with `python tools/fetch_logos.py` (it refuses any file that is not Public domain / CC0). *Recoloured* = made white for the dark UI (\"white\" = whole logo, \"dark parts white\" = only its dark pixels, \"plate removed\" = white-plate logos made transparent);",
          "the original colours are on the linked Commons page.", "",
          "| Name | Brand | Source (Wikimedia Commons) | Licence | Author (as listed on Commons) | Recoloured |", "|---|---|---|---|---|---|"]
    for name, brand, title, meta, white in rows:
        artist = (meta["artist"] or "-")[:60].replace("|", "/")
        md.append(f"| `{name}` | {brand} | [{title[5:]}]({meta['page']}) | {meta['license']} (trademarked) | {artist} | { {'white': 'white', 'lighten': 'dark parts white', 'matte': 'white (plate removed)'}.get(white, '') } |")
    open(os.path.join(OUT, "LOGOS.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"\n{len(rows)} logos written to logos/, refused: {refused or 'none'}")


if __name__ == "__main__":
    sys.exit(main())
