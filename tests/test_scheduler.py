"""Transmission scheduler, slow mode, light alert, config fallback, device profiles (no hardware, no serial port)."""
import os
import types

import numpy as np
import pytest

from displaymonitor import app as app_mod
from displaymonitor import devices, render as render_mod, slowmode, txsched
from displaymonitor.app import App, load_config
from displaymonitor.demo import demo_snapshot
from displaymonitor.display import HW_H, HW_W, Display
from displaymonitor.render import Renderer
from displaymonitor.validate import ConfigError
from test_features import make_app

render_mod.SHIPPED_ONLY = True


class LinkStub:
    """A fake serial port: remembers every write, and can fail on the n-th one."""

    def __init__(self, fail_on=None):
        self.writes, self.fail_on = [], fail_on

    def write(self, data):
        if self.fail_on is not None and len(self.writes) + 1 == self.fail_on:
            raise OSError("cable pulled")
        self.writes.append(bytes(data))

    def flush(self):
        pass

    def blocks(self):
        """[(x, y, w, h)] of the bitmap commands written, in order."""
        out = []
        for hdr in self.writes[0::2]:
            x = (hdr[0] << 2) | (hdr[1] >> 6)
            y = ((hdr[1] & 63) << 4) | (hdr[2] >> 4)
            ex = ((hdr[2] & 15) << 6) | (hdr[3] >> 2)
            ey = ((hdr[3] & 3) << 8) | hdr[4]
            out.append((x, y, ex - x + 1, ey - y + 1))
        return out

    def payload(self):
        return sum(len(p) for p in self.writes[1::2])


def connected_display(**cfg):
    d = Display({"refresh_band": 0, **cfg})
    d._ser = LinkStub()
    return d


def landscape(value=0):
    return np.full((320, 480), value, dtype="<u2")


def portrait(d, frame):
    return np.ascontiguousarray(np.rot90(frame, d.rot_k))


# -- the scheduler -----------------------------------------------------------------------------------
def test_txsched_blocks_priorities_and_budget():
    assert txsched.split_rect((0, 0, 320, 100), 12800) == [(0, 0, 320, 40), (0, 40, 320, 40), (0, 80, 320, 20)]
    data, bulk = txsched.classify([(0, 0, 10, 10), (0, 0, 320, 100)], 6000)
    assert data == [(0, 0, 10, 10)] and bulk == [(0, 0, 320, 100)]
    order = txsched.ordered_blocks([(0, 100, 320, 100), (50, 300, 8, 8), (5, 5, 8, 8)], 6000, 12800)
    prios = [p for p, _ in order]
    assert prios == sorted(prios) and prios[0] == txsched.DATA and prios[-1] == txsched.BULK       # data first, bulk after
    assert [b for p, b in order if p == txsched.DATA] == [(5, 5, 8, 8), (50, 300, 8, 8)]            # top to bottom
    blocks = [(txsched.DATA, (0, i * 10, 100, 10)) for i in range(10)]                             # 2000 bytes each
    chosen, rest = txsched.take(blocks, 5000)
    assert len(chosen) == 2 and len(rest) == 8 and chosen + rest == blocks
    assert txsched.take(blocks, 0) == (blocks, [])                                                  # 0 = unlimited
    chosen, rest = txsched.take(blocks, 10)
    assert len(chosen) == 1 and len(rest) == 9                                                      # always makes progress
    assert txsched.latency_estimate(165_000) == pytest.approx(1.0)


def test_normal_mode_is_unchanged_one_cycle_sends_everything():
    d = connected_display()
    assert d.mode == "normal" and d.tx_budget == 0
    d.show(landscape(0))
    d._ser.writes.clear()
    d.show(landscape(5))                                                                            # the whole screen changes
    assert d._ser.payload() == HW_W * HW_H * 2 and d.tx["pending"] == 0 and d.tx["budget"] == 0 and d.tx["used"] is None


def test_budget_limits_each_cycle_and_the_panel_converges_on_the_latest_frame():
    d = connected_display(tx_budget_bytes=20_000)
    d.show(landscape(0))                                                                            # first frame: critical, sent whole
    assert d._ser.payload() == HW_W * HW_H * 2 and d.tx["critical"] == 1
    target = landscape(9)
    sent_per_cycle = []
    for _ in range(40):
        d._ser.writes.clear()
        d.show(target)
        sent_per_cycle.append(d._ser.payload())
        if d.tx["pending"] == 0:
            break
    assert max(sent_per_cycle) <= 20_000 + 12_800 * 2                                               # budget + at most one block over it
    assert len(sent_per_cycle) > 3                                                                  # it really was spread over several cycles
    assert d.tx["pending"] == 0 and np.array_equal(d._prev, portrait(d, target))                    # converged
    assert d.tx["used"] is not None and d.tx["budget"] == 20_000


def test_pending_work_is_replaced_by_a_newer_frame_not_queued():
    d = connected_display(tx_budget_bytes=15_000)
    d.show(landscape(0))
    d.show(landscape(1))                                                                            # only part of it goes out
    assert d.tx["pending"] > 0 and d.tx["coalesced"] == 0
    second = landscape(2)
    d.show(second)                                                                                  # the unsent rest of the first is dropped
    assert d.tx["coalesced"] == 1
    for _ in range(60):
        d.show(second)
        if d.tx["pending"] == 0:
            break
    assert np.array_equal(d._prev, portrait(d, second))                                             # the panel shows the NEWEST frame
    assert d.tx["latency_s"] == 0.0


def test_data_goes_out_before_bulk_and_the_band_waits_for_spare_capacity():
    d = connected_display(tx_budget_bytes=30_000, refresh_band=8, band_budget=10_000_000)
    d.show(landscape(0))
    d._ser.writes.clear()
    frame = landscape(4)                                                                            # a big background change (bulk) ...
    frame[10:20, 10:20] = 7                                                                         # ... and a small digit-like change (data)
    d.show(frame)
    blocks = d._ser.blocks()
    small = [i for i, b in enumerate(blocks) if b[2] * b[3] <= d.bulk_px]
    assert small and small[0] == 0                                                                  # the small rectangle is written first
    assert d.tx["pending"] > 0 and d.band_skipped >= 1                                              # busy: no healing band this cycle
    for _ in range(80):
        d.show(frame)
        if d.tx["pending"] == 0:
            break
    d._ser.writes.clear()
    d.show(frame)                                                                                   # nothing pending, spare budget: the band goes out
    assert len(d._ser.blocks()) == 1 and d._ser.blocks()[0][2:] == (HW_W, 8)


def test_sent_framebuffer_only_learns_blocks_that_were_written():
    d = connected_display(max_block_px=3200)                                                        # 10-row blocks
    d.show(landscape(0))
    prev_ref = d._prev
    stub = d._ser = LinkStub(fail_on=4)                                                             # block 1 (two writes) ok, block 2's header fails
    new = landscape(3)
    assert d.show(new) is False and not d.connected and d.needs_flood and d._prev is None           # link lost: nothing is trusted any more
    hw_new = portrait(d, new)
    x, y, w, h = stub.blocks()[0]
    assert np.array_equal(prev_ref[y:y + h, x:x + w], hw_new[y:y + h, x:x + w])                     # the block that was written is recorded ...
    assert not np.array_equal(prev_ref[y + h:y + 2 * h, x:x + w], hw_new[y + h:y + 2 * h, x:x + w])  # ... the one that failed is not
    d2 = connected_display()
    d2.show(landscape(0))
    d2._ser = LinkStub(fail_on=1)
    assert d2.show(landscape(5)) is False and d2._prev is None and d2.needs_flood                   # serial error during a delta
    assert d2.tx["pending"] == 0 or d2._pending_bytes == 0


def test_critical_frames_are_sent_whole_regardless_of_the_budget():
    d = connected_display(tx_budget_bytes=5_000)
    d.show(landscape(0))
    d._ser.writes.clear()
    d.show(landscape(6), critical=True)                                                             # the "Ciao" screen
    assert d._ser.payload() == HW_W * HW_H * 2 and d.tx["pending"] == 0 and d.tx["critical"] == 2


def test_a_tint_step_is_budgeted_and_data_still_goes_first():
    d = connected_display(mode="slow", tx_budget_bytes=40_960)
    d.show(landscape(0))
    d._ser.writes.clear()
    red = landscape(0x1800)                                                                         # a tint step over the whole background
    red[100:110, 100:140] = 0xFFFF                                                                  # and a number that changed too
    d.show(red)
    assert d._ser.payload() <= 40_960 + 12_800 * 2 and d.tx["pending"] > 0
    assert d.tx["latency_s"] == pytest.approx(d.tx["pending"] / 165_000)
    first = d._ser.blocks()[0]
    assert first[2] * first[3] <= d.bulk_px                                                         # the number is written first


# -- slow mode -----------------------------------------------------------------------------------------
def test_slow_mode_defaults_and_validation():
    d = Display({"mode": "slow"})
    assert d.mode == "slow" and d.tx_budget == 40_960 and d.slow["noncritical_s"] == 10.0
    assert Display({"mode": "slow", "tx_budget_bytes": 8000}).tx_budget == 8000
    assert Display({"mode": "turbo"}).mode == "normal"                                              # unknown: the safe default
    assert Display({"tx_budget_bytes": -5}).tx_budget == 0 and Display({"bulk_px": 5}).bulk_px == 6000
    d.configure({"mode": "normal"})
    assert d.mode == "normal" and d.tx_budget == 0                                                  # hot reload back to normal


def test_slow_mode_keeps_critical_values_live_and_holds_the_rest():
    f = slowmode.SlowFilter(10.0)
    s1 = {"cpu_load": 10, "cpu_temp": 50, "mem_pct": 30, "net_down": 100.0, "net_down_hist": [1, 2], "uptime_str": "1h", "cpu_threads": [1, 2], "time": "10:00"}
    assert f.apply(s1, 0.0) == s1
    s2 = {**s1, "cpu_load": 90, "net_down": 999.0, "net_down_hist": [1, 2, 3], "uptime_str": "2h", "cpu_threads": [9, 9], "time": "10:01"}
    out = f.apply(s2, 5.0)
    assert out["cpu_load"] == 90 and out["time"] == "10:01"                                         # critical: live
    assert out["net_down"] == 100.0 and out["net_down_hist"] == [1, 2] and out["uptime_str"] == "1h" and out["cpu_threads"] == [1, 2]
    assert f.apply(s2, 10.5)["net_down"] == 999.0                                                   # refreshed after noncritical_s
    assert slowmode.is_critical("gpu_vram_pct") and slowmode.is_critical("ram_temp") and not slowmode.is_critical("disk_temp_max")
    assert not slowmode.is_critical("net_up_hist") and not slowmode.is_critical("weather_temp") and not slowmode.is_critical("mb_t1")


def test_slow_mode_band_cadence_and_page_dwell():
    d = connected_display(mode="slow", refresh_band=8, tx_budget_bytes=0, slow={"band_every": 3})
    d.show(landscape(0))                                                                            # cycle 1 (first frame)
    bands = 0
    for _ in range(9):
        d._ser.writes.clear()
        d.show(landscape(0))
        bands += len(d._ser.blocks())
    assert bands == 3                                                                               # one healing band every 3rd cycle
    app = make_app({"display": {"mode": "slow"}})
    assert app.slow is not None and app.rotate_s == 30.0                                            # slow mode: longer dwell by default
    app = make_app({"display": {"mode": "slow", "slow": {"rotate_s": 45}}, "rotate_s": 20})
    assert app.rotate_s == 20.0                                                                     # an explicit rotate_s always wins
    assert make_app().slow is None and make_app().rotate_s == 12.0                                  # normal: untouched


# -- the light alert -----------------------------------------------------------------------------------
def test_light_alert_border_changes_only_the_edge():
    r = Renderer(None, {"header": False})
    page = load_config(examples=True, lang="en")[1]["pages"][0]
    s = demo_snapshot("en")
    plain = r.render(page, s, 0, 9)
    border = r.render(page, s, 0, 9, 0.5, "border")
    wash = r.render(page, s, 0, 9, 0.5, "background")
    both = r.render(page, s, 0, 9, 0.5, "both")
    diff = (np.asarray(plain, dtype=int) != np.asarray(border, dtype=int)).any(axis=2)
    ys, xs = np.nonzero(diff)
    assert diff.any() and (np.minimum(np.minimum(xs, 479 - xs), np.minimum(ys, 319 - ys)) <= 6).all()   # only the outer frame changed (3 px + anti-aliasing)
    assert (np.asarray(wash, dtype=int) != np.asarray(plain, dtype=int)).any(axis=2).sum() > 5 * diff.sum()
    assert both.tobytes() != wash.tobytes()
    from displaymonitor.tint import Tint
    assert Tint({"tint": {"style": "border"}}).style == "border" and Tint({"tint": {"style": "nonsense"}}).style == "background"
    assert Tint({"tint": {}}).style == "background"                                                 # the existing alerts.tint keeps working
    assert txsched.rect_bytes((0, 0, 480, 3)) * 4 < 40_000                                          # a border step is tens of KB, not the ~175 KB of a background step


# -- configuration fallback ----------------------------------------------------------------------------
def config_root(tmp_path, monkeypatch, config_text=None, pages_text=None):
    import shutil
    (tmp_path / "config").mkdir()
    for f in os.listdir(os.path.join(app_mod.ROOT, "config")):
        if f.endswith(".example.yaml"):
            shutil.copy(os.path.join(app_mod.ROOT, "config", f), tmp_path / "config" / f)
    if config_text is not None:
        (tmp_path / "config" / "config.yaml").write_text(config_text, encoding="utf-8")
    if pages_text is not None:
        (tmp_path / "config" / "pages.yaml").write_text(pages_text, encoding="utf-8")
    monkeypatch.setattr(app_mod, "ROOT", str(tmp_path))


BAD_CONFIGS = ["display: [unclosed\n  - : :", "- just\n- a list\n", "just a string", "display: 5\n", "theme: [a, b]\n", "alerts: 7\n"]
BAD_PAGES = ["pages: [unclosed", "- a\n- list\n", "pages: []\n", "pages: {a: 1}\n", "pages:\n  - title: no id\n", "pages:\n  - id: a\n  - id: a\n",
             "pages:\n  - id: a\n    cards: oops\n", "pages:\n  - id: a\n    ring: [1]\n"]


@pytest.mark.parametrize("text", BAD_CONFIGS)
def test_bad_config_yaml_falls_back_to_the_example_and_is_never_modified(tmp_path, monkeypatch, text):
    config_root(tmp_path, monkeypatch, config_text=text)
    with pytest.raises(ConfigError) as e:
        load_config()                                                                               # strict: a hot reload keeps the previous config
    assert "config.yaml" in str(e.value)
    cfg, pages = load_config(fallback=True)                                                         # cold start: the example, no exception
    assert isinstance(cfg, dict) and cfg["language"] == "en" and pages["pages"]
    assert (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8") == text                # the user's file is untouched


@pytest.mark.parametrize("text", BAD_PAGES)
def test_bad_pages_yaml_falls_back_to_the_example_and_is_never_modified(tmp_path, monkeypatch, text):
    config_root(tmp_path, monkeypatch, pages_text=text)
    with pytest.raises(ConfigError) as e:
        load_config()
    assert "pages.yaml" in str(e.value)
    cfg, pages = load_config(fallback=True)
    assert pages["pages"][0]["id"] == "overview"
    assert (tmp_path / "config" / "pages.yaml").read_text(encoding="utf-8") == text


def test_fallback_uses_the_language_of_the_valid_config(tmp_path, monkeypatch):
    config_root(tmp_path, monkeypatch, config_text="language: it\n", pages_text="not: valid")
    cfg, pages = load_config(fallback=True)
    assert cfg["language"] == "it" and pages["pages"][0]["title"] == "PANORAMICA"                   # the Italian pack's pages


def test_a_missing_or_empty_file_is_not_an_error(tmp_path, monkeypatch):
    config_root(tmp_path, monkeypatch, config_text="")                                              # an empty config.yaml is just "all defaults"
    cfg, pages = load_config()
    assert cfg == {} and pages["pages"]


def test_hot_reload_keeps_the_working_configuration(tmp_path, monkeypatch):
    config_root(tmp_path, monkeypatch, config_text="language: en\n")
    app = App(*load_config())
    pages_before, cfg_before = app.pages, app.cfg
    (tmp_path / "config" / "config.yaml").write_text("display: [broken", encoding="utf-8")
    app.reload_config()
    assert app.pages is pages_before and app.cfg is cfg_before                                      # nothing was replaced
    (tmp_path / "config" / "config.yaml").write_text("language: en\n", encoding="utf-8")
    (tmp_path / "config" / "pages.yaml").write_text("pages: []", encoding="utf-8")
    app.reload_config()
    assert app.pages is pages_before


# -- device profiles -----------------------------------------------------------------------------------
def port(device, vid=0x1A86, pid=0x5722, serial="USB35INCHIPSV2"):
    return types.SimpleNamespace(device=device, vid=vid, pid=pid, serial_number=serial)


def test_device_profile_defaults_and_parsing():
    prof, w = devices.parse_profile(None)
    assert (prof["vid"], prof["pid"], prof["serial"], prof["port"], prof["index"], prof["custom_ids"]) == (0x1A86, 0x5722, "", "", 0, False) and w == []
    prof, w = devices.parse_profile({"vid": "0x1234", "pid": "abcd", "serial": " S1 ", "port": "COM7", "index": 2})
    assert (prof["vid"], prof["pid"], prof["serial"], prof["port"], prof["index"], prof["custom_ids"]) == (0x1234, 0xABCD, "S1", "COM7", 2, True) and w == []
    prof, w = devices.parse_profile({"vid": "zz", "pid": 99999999, "profile": "other", "index": "x"})
    assert (prof["vid"], prof["pid"], prof["profile"], prof["index"]) == (0x1A86, 0x5722, "turzx-rev-a", 0) and len(w) == 4
    assert devices.parse_profile("nonsense")[1]                                                    # not a mapping: defaults + a warning
    assert Display({"device": {"vid": 0x1234, "pid": 0x4321}}).profile["vid"] == 0x1234


def test_only_compatible_ports_are_ever_chosen():
    prof = devices.parse_profile(None)[0]
    other = port("COM9", vid=0x0403, pid=0x6001, serial="FTDI1")
    mine = port("COM3")
    assert devices.choose([other], prof) is None and devices.choose([], prof) is None               # an unrelated serial device is never opened
    assert devices.choose([other, mine], prof) == "COM3"
    assert devices.choose([port("COM4", vid=1, pid=2, serial="USB35INCHIPSV2")], prof) == "COM4"    # the known serial still identifies it
    assert devices.compatible([other, mine], prof) == [mine]


def test_several_compatible_displays_need_an_explicit_choice_and_the_choice_is_checked():
    a, b = port("COM3", serial="AAA"), port("COM5", serial="BBB")
    warned = set()
    assert devices.choose([b, a], devices.parse_profile(None)[0], warned) == "COM3"                 # deterministic: sorted, first, with a warning
    assert ("multi", 2) in warned
    assert devices.choose([a, b], devices.parse_profile({"index": 1})[0]) == "COM5"
    assert devices.choose([a, b], devices.parse_profile({"serial": "BBB"})[0]) == "COM5"
    assert devices.choose([a, b], devices.parse_profile({"serial": "CCC"})[0]) is None
    assert devices.choose([a, b], devices.parse_profile({"port": "com5"})[0]) == "COM5"
    other = port("COM9", vid=0x0403, pid=0x6001, serial="X")
    warned = set()
    assert devices.choose([a, other], devices.parse_profile({"port": "COM9"})[0], warned) is None  # a port is never opened on trust ...
    assert ("port", "COM9") in warned                                                              # ... and why is logged once
    clone = port("COM8", vid=0x1234, pid=0x4321, serial="CLONE")
    custom = devices.parse_profile({"vid": 0x1234, "pid": 0x4321})[0]
    assert devices.choose([a, clone], custom) == "COM8"                                            # configured ids: the clone, not the default one
    assert devices.choose([a], custom) is None


def test_display_find_port_uses_the_profile(monkeypatch):
    from displaymonitor import display as display_mod
    monkeypatch.setattr(display_mod, "comports", lambda: [port("COM3", serial="AAA"), port("COM5", serial="BBB")])
    assert Display({}).find_port() == "COM3"
    assert Display({"device": {"serial": "BBB"}}).find_port() == "COM5"
    d = Display({})
    d.configure({"device": {"serial": "BBB"}})
    assert d.find_port() == "COM5"


# -- diagnostics ---------------------------------------------------------------------------------------
def test_diagnostics_text_mentions_the_budget_and_the_backlog_only_when_relevant():
    app = make_app({"display": {"mode": "slow"}})
    app.display.last_bytes, app.display.last_rects, app.display.last_ms = 30_000, 4, 40.0
    app.display.tx.update(budget=40_960, sent=30_000, pending=60_000, latency_s=60_000 / 165_000, coalesced=3)
    app._update_diag(100.0, 10.0, {})
    t = app.diag_text()
    assert "budget 29/40 KB" in t and "pending 59 KB" in t and "3 coalesced" in t
    quiet = make_app()
    quiet.display.last_bytes, quiet.display.last_rects, quiet.display.last_ms = 1000, 1, 5.0
    quiet._update_diag(100.0, 3.0, {})
    assert "budget" not in quiet.diag_text() and "pending" not in quiet.diag_text()
