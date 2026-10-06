"""The English and Italian packs: same structure, both render, --init installs them safely."""
import os
import shutil

import pytest

from displaymonitor import app as app_mod
from displaymonitor import render as render_mod
from displaymonitor.app import enabled_pages, init_language_pack, load_config
from displaymonitor.demo import demo_snapshot
from displaymonitor.render import Renderer

render_mod.SHIPPED_ONLY = True


def test_both_packs_have_the_same_pages_and_cards():
    en_cfg, en_pages = load_config(examples=True, lang="en")
    it_cfg, it_pages = load_config(examples=True, lang="it")
    assert en_cfg["language"] == "en" and it_cfg["language"] == "it" and it_cfg["date_language"] == "it"
    assert [p["id"] for p in en_pages["pages"]] == [p["id"] for p in it_pages["pages"]]
    for a, b in zip(en_pages["pages"], it_pages["pages"]):
        assert len(a.get("cards", [])) == len(b.get("cards", [])), a["id"]
        assert a.get("requires") == b.get("requires"), a["id"]
    assert it_pages["pages"][0]["title"] == "PANORAMICA" and en_pages["pages"][0]["title"] == "OVERVIEW"


@pytest.mark.parametrize("lang", ["en", "it"])
def test_every_page_of_each_pack_renders(lang):
    cfg, pages = load_config(examples=True, lang=lang)
    cfg = {**cfg, "weather": {"enabled": True}}
    r = Renderer(cfg.get("theme"), {"header": False})
    for i, p in enumerate(enabled_pages(pages, cfg)):
        assert r.render(p, demo_snapshot(lang), i, 9).size == (480, 320)


def test_init_installs_a_pack_and_never_overwrites_silently(tmp_path, monkeypatch):
    shutil.copytree(os.path.join(app_mod.ROOT, "config"), tmp_path / "config",
                    ignore=shutil.ignore_patterns("config.yaml", "pages.yaml", "themes", "state.yaml", "*.bak"))
    monkeypatch.setattr(app_mod, "ROOT", str(tmp_path))
    written = init_language_pack("it")
    assert len(written) == 2 and "PACCHETTO ITALIANO" in (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_language_pack("en")
    init_language_pack("en", force=True)
    assert (tmp_path / "config" / "config.yaml.bak").exists()
    assert "DisplayMonitor - general settings" in (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        init_language_pack("xx")
