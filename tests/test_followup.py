"""Follow-up review: a hard transmission budget, complete serial writes, hot-reload order, strict device identification."""
import logging

import numpy as np
import pytest

from displaymonitor import devices, render as render_mod, txsched, validate
from displaymonitor.app import App, load_config
from displaymonitor.display import HW_H, HW_W, Display
from test_scheduler import LinkStub, config_root, connected_display, landscape, port, portrait

render_mod.SHIPPED_ONLY = True


# -- 1. the budget is a limit, not a suggestion ----------------------------------------------------------
def test_split_to_fit_covers_the_rectangle_exactly_and_respects_the_limit():
    for rect in ((0, 0, 320, 480), (10, 20, 17, 33), (0, 0, 320, 1), (5, 5, 1, 90)):
        for budget in (1024, 1500, 4000, 20_000):
            pieces = txsched.split_to_fit(rect, budget)
            assert all(txsched.wire_bytes(p) <= budget for p in pieces)
            covered = np.zeros((480, 320), dtype=int)
            for x, y, w, h in pieces:
                covered[y:y + h, x:x + w] += 1
            x, y, w, h = rect
            assert covered[y:y + h, x:x + w].min() == 1 and covered.sum() == w * h              # every pixel once, nothing outside


@pytest.mark.parametrize("budget", [1, 7, 100, 1023, 1024, 3000, 20_000])
def test_take_never_exceeds_the_budget_and_always_makes_progress(budget):
    blocks = [(txsched.DATA, (0, 0, 320, 40)), (txsched.BULK, (0, 40, 320, 440))]
    effective = max(budget, txsched.MIN_BUDGET)
    queue, cycles = list(blocks), 0
    while queue:
        chosen, queue = txsched.take(queue, budget)
        assert chosen, "no progress"
        assert sum(txsched.wire_bytes(b) for _, b in chosen) <= effective                        # headers included
        cycles += 1
        assert cycles < 2000
    assert txsched.take(blocks, 0) == (blocks, [])                                               # 0 stays unlimited


def test_a_tiny_configured_budget_is_raised_to_the_floor_and_still_a_hard_limit():
    st, warnings = validate.display_settings({"tx_budget_bytes": 1})
    assert st["tx_budget"] == txsched.MIN_BUDGET == validate.MIN_TX_BUDGET and any("smallest usable budget" in w for w in warnings)
    d = connected_display(tx_budget_bytes=1)
    assert d.tx_budget == 1024
    d.show(landscape(0))
    target = landscape(7)
    cycles = 0
    while True:
        d._ser.writes.clear()
        d.show(target)
        cycles += 1
        assert sum(len(w) for w in d._ser.writes) <= 1024                                        # every byte on the wire, headers included
        assert d.tx["sent"] == sum(len(w) for w in d._ser.writes) and d.tx["budget"] == 1024
        if d.tx["pending"] == 0:
            break
        assert cycles < 1000
    assert np.array_equal(d._prev, portrait(d, target)) and cycles > 100                        # converged, in many tiny steps
    assert d.tx["used"] == pytest.approx(d.tx["sent"] / 1024)


def test_the_healing_band_never_breaks_the_budget():
    d = connected_display(tx_budget_bytes=6_000, refresh_band=8, band_budget=10_000_000)
    d.show(landscape(0))
    for _ in range(5):
        d._ser.writes.clear()
        d.show(landscape(0))                                                                     # idle: the band (5126 B on the wire) fits in 6000
        assert sum(len(w) for w in d._ser.writes) <= 6_000
    tight = connected_display(tx_budget_bytes=2_000, refresh_band=8, band_budget=10_000_000)
    tight.show(landscape(0))
    tight._ser.writes.clear()
    tight.show(landscape(0))
    assert tight._ser.writes == [] and tight.band_skipped >= 1                                   # it does not fit: it waits


# -- 2. every byte of a command reaches the port ------------------------------------------------------------
class TrickleLink(LinkStub):
    """Accepts at most `chunk` bytes per call and says how many it took, like a port with a full output buffer."""

    def __init__(self, chunk=7, **kw):
        super().__init__(**kw)
        self.chunk, self.stream = chunk, bytearray()

    def write(self, data):
        take = bytes(data[:self.chunk])
        self.stream += take
        return len(take)


class DeadLink(LinkStub):
    def write(self, data):
        return 0                                                                                 # the port accepts nothing, and raises nothing


def test_partial_serial_writes_are_completed():
    d = Display({"refresh_band": 0})
    d._ser = TrickleLink(chunk=7)
    frame = landscape(0)
    frame[:, :] = np.arange(480, dtype="<u2")[None, :]
    assert d.show(frame) is True
    hw = portrait(d, frame)
    expected = bytearray()
    for _prio, (x, y, w, h) in [(0, b) for b in txsched.split_rect((0, 0, HW_W, HW_H), d.max_px)]:
        from displaymonitor.display import CMD_BITMAP, _header
        expected += _header(CMD_BITMAP, x, y, x + w - 1, y + h - 1) + np.ascontiguousarray(hw[y:y + h, x:x + w]).tobytes()
    assert bytes(d._ser.stream) == bytes(expected)                                               # every header and pixel, in order, none lost
    assert d._prev is not None and np.array_equal(d._prev, hw)


def test_a_port_that_accepts_nothing_is_a_lost_link_not_a_sent_block():
    d = Display({"refresh_band": 0})
    d.WRITE_STALL_S = 0.05
    d._ser = LinkStub()
    d.show(landscape(0))
    d._ser = DeadLink()
    assert d.show(landscape(5)) is False                                                         # the stall raises OSError, handled as a link loss
    assert not d.connected and d._prev is None and d.needs_flood
    d2 = Display({})
    d2.WRITE_STALL_S = 0.05
    d2._ser = DeadLink()
    with pytest.raises(OSError):
        d2._write(b"abc")


def test_a_port_that_does_not_report_a_count_is_accepted_as_before():
    d = connected_display()                                                                     # LinkStub.write returns None
    d._write(b"hello")
    assert d._ser.writes == [b"hello"]


# -- 3. hot reload: the display is configured before the page dwell is chosen -----------------------------------
def test_switching_to_slow_mode_by_hot_reload_applies_the_slow_dwell(tmp_path, monkeypatch):
    config_root(tmp_path, monkeypatch, config_text="language: en\n")
    app = App(*load_config())
    assert app.display.mode == "normal" and app.rotate_s == 12.0 and app.slow is None
    (tmp_path / "config" / "config.yaml").write_text("language: en\ndisplay:\n  mode: slow\n", encoding="utf-8")
    app.reload_config()
    assert app.display.mode == "slow" and app.rotate_s == 30.0 and app.slow is not None and app.display.tx_budget == 40_960
    (tmp_path / "config" / "config.yaml").write_text("language: en\ndisplay:\n  mode: slow\nrotate_s: 20\n", encoding="utf-8")
    app.reload_config()
    assert app.rotate_s == 20.0                                                                  # an explicit rotate_s still wins
    (tmp_path / "config" / "config.yaml").write_text("language: en\n", encoding="utf-8")
    app.reload_config()
    assert app.display.mode == "normal" and app.rotate_s == 12.0 and app.slow is None            # and back


# -- 4. strict identification ---------------------------------------------------------------------------------
def test_vid_and_pid_must_both_match_a_serial_never_decides_alone():
    prof = devices.parse_profile(None)[0]
    good = port("COM3")
    assert devices.compatible([good], prof) == [good]
    assert devices.compatible([port("COM4", vid=0x1A86, pid=0x7523)], prof) == []                # same VID, other product (a plain CH340)
    assert devices.compatible([port("COM4", vid=0x0403, pid=0x5722)], prof) == []                # same PID, other vendor
    assert devices.compatible([port("COM4", vid=1, pid=2, serial="USB35INCHIPSV2")], prof) == []   # the known serial alone is not enough
    assert devices.compatible([port("COM4", vid=None, pid=None, serial="USB35INCHIPSV2")], prof) == []
    narrow = devices.parse_profile({"serial": "BBB"})[0]
    assert devices.compatible([port("COM3", serial="AAA"), port("COM5", serial="BBB")], narrow)[0].device == "COM5"
    assert devices.compatible([port("COM6", vid=1, pid=2, serial="BBB")], narrow) == []          # a matching serial does not replace the ids


def test_an_index_with_no_display_behind_it_opens_nothing(caplog):
    a, b = port("COM3", serial="AAA"), port("COM5", serial="BBB")
    warned = set()
    with caplog.at_level(logging.WARNING, logger="displaymonitor.devices"):
        assert devices.choose([a, b], devices.parse_profile({"index": 2})[0], warned) is None
        assert devices.choose([a, b], devices.parse_profile({"index": 2})[0], warned) is None
        assert devices.choose([a], devices.parse_profile({"index": 1})[0], warned) is None
    assert sum("not opened" in r.message for r in caplog.records) == 2                           # logged once per situation, not every second
    assert devices.choose([a, b], devices.parse_profile({"index": 1})[0]) == "COM5"
    assert devices.choose([a], devices.parse_profile({"index": 0})[0]) == "COM3"
    assert devices.choose([], devices.parse_profile({"index": 0})[0]) is None


def test_display_never_connects_to_a_port_that_is_not_compatible(monkeypatch):
    from displaymonitor import display as display_mod
    monkeypatch.setattr(display_mod, "comports", lambda: [port("COM9", vid=0x0403, pid=0x6001, serial="USB35INCHIPSV2")])
    assert Display({}).find_port() is None
    opened = []
    monkeypatch.setattr(display_mod.serial, "Serial", lambda *a, **k: opened.append(a))
    assert Display({}).connect() is False and opened == []
