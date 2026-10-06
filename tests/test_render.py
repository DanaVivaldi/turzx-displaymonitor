"""Rendering without hardware: every shipped page / theme / layout draws a 480x320 image."""
import glob
import os

import pytest
from PIL import Image

from displaymonitor import render as render_mod
from displaymonitor.app import ROOT, enabled_pages, load_config
from displaymonitor.demo import demo_snapshot
from displaymonitor.render import Renderer, fmt, resolve_logo, resolve_theme, to_rgb

render_mod.SHIPPED_ONLY = True        # tests must not depend on anybody's personal assets/logos


@pytest.fixture(scope="module")
def cfg_pages():
    return load_config(examples=True)


@pytest.mark.parametrize("header", [False, True])
def test_every_example_page_renders(cfg_pages, header):
    cfg, pages = cfg_pages
    cfg = {**cfg, "weather": {"enabled": True}}
    r = Renderer({}, {"header": header})
    plist = enabled_pages(pages, cfg)
    assert len(plist) >= 8
    for i, p in enumerate(plist):
        im = r.render(p, demo_snapshot("en"), i, len(plist))
        assert isinstance(im, Image.Image) and im.size == (480, 320) and im.mode == "RGB"


THEMES = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(ROOT, "themes", "*.yaml")))


@pytest.mark.parametrize("name", THEMES)
def test_every_shipped_theme_renders(cfg_pages, name):
    _, pages = cfg_pages
    im = Renderer({"preset": name}, {"header": False}).render(pages["pages"][0], demo_snapshot("en"), 0, 8)
    assert im.size == (480, 320)


def test_missing_values_render_as_dashes_instead_of_crashing():
    assert fmt("{nothing:.0f}%", {}) == "--%"
    assert fmt("{cpu_temp:.0f}", {"cpu_temp": 41.6}) == "42"
    assert fmt("{bad:d}", {"bad": "x"}) == "x"


def test_colour_parsing_and_theme_merge():
    assert to_rgb("#ff8000") == (255, 128, 0) and to_rgb("#f80") == (255, 136, 0) and to_rgb([1, 2, 3]) == (1, 2, 3)
    th = resolve_theme({"cyan": "#112233", "preset": "ember"})
    assert th["cyan"] == (0x11, 0x22, 0x33)             # explicit config wins over the preset
    assert th["panel"] == to_rgb("#1c1210")             # ... the rest comes from the preset


def test_unknown_preset_falls_back_to_defaults():
    assert resolve_theme({"preset": "does-not-exist"})["bg"] == (6, 10, 40)


def test_temperature_and_percent_scheme():
    r = Renderer({}, {"header": False})
    white, green, red = r.t["white"], r.t["heat"][1], r.t["heat"][4]
    assert r.temp_color(30) == white and r.temp_color(55) == green and r.temp_color(100) == red
    assert r.temp_color(30, bar=True) == green          # bars use green instead of white in the lowest band
    assert r.is_temp_key("cpu_temp") and r.is_temp_key("mem_pct") and r.is_temp_key("mb_t1")
    assert not r.is_temp_key("net_down") and not r.is_temp_key("gpu_fan_pct")


def test_shipped_logos_resolve_and_are_documented():
    for n in ["intel", "amd", "nvidia", "msi", "asus", "gigabyte", "asrock"]:
        assert resolve_logo(n) and os.path.exists(resolve_logo(n)), n
    assert resolve_logo("none") is None and resolve_logo("") is None
    listed = open(os.path.join(ROOT, "logos", "LOGOS.md"), encoding="utf-8").read()
    for f in glob.glob(os.path.join(ROOT, "logos", "*.png")):
        name = os.path.splitext(os.path.basename(f))[0]
        assert "`" + name + "`" in listed, name         # every shipped logo has a source / licence row


def test_a_page_can_carry_its_own_logos(cfg_pages):
    _, pages = cfg_pages
    r = Renderer({"logos": ["intel", "asus"]}, {"header": False})
    plain = r.render(pages["pages"][0], demo_snapshot("en"), 0, 8)
    page = dict(pages["pages"][0], logos=["amd", "msi"])
    other = r.render(page, demo_snapshot("en"), 0, 8)
    assert plain.tobytes() != other.tobytes()
