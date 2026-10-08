"""Night schedule, "Ciao" screen, red background, web preview, update check, Linux / macOS parsers."""
import datetime
import http.client
import io
import json
import os
import types
import zipfile

import pytest
from PIL import Image

from displaymonitor import app as app_mod
from displaymonitor import render as render_mod
from displaymonitor import schedule, sensors_posix, session, updates
from displaymonitor.tint import Tint
from displaymonitor.app import App, CommandQueue, load_config, page_alert_rules
from displaymonitor.demo import demo_snapshot
from displaymonitor.render import Renderer
from displaymonitor.web import WebPreview

render_mod.SHIPPED_ONLY = True


# -- night schedule ------------------------------------------------------------------------------
def at(h, m=0):
    return datetime.datetime(2026, 10, 6, h, m)


def test_night_window_wraps_over_midnight():
    cfg = {"enabled": True, "from": "23:00", "to": "07:00"}
    assert schedule.night_active(cfg, at(23, 0)) and schedule.night_active(cfg, at(3)) and schedule.night_active(cfg, at(6, 59))
    assert not schedule.night_active(cfg, at(7, 0)) and not schedule.night_active(cfg, at(12)) and not schedule.night_active(cfg, at(22, 59))


def test_night_window_same_day_and_edge_cases():
    cfg = {"enabled": True, "from": "13:00", "to": "15:30"}
    assert schedule.night_active(cfg, at(14)) and not schedule.night_active(cfg, at(15, 30))
    assert not schedule.night_active({"enabled": False, "from": "00:00", "to": "23:59"}, at(12))
    assert not schedule.night_active({"enabled": True, "from": "10:00", "to": "10:00"}, at(10))
    assert not schedule.night_active({"enabled": True, "from": "garbage", "to": "07:00"}, at(3))
    assert schedule.night_active({"enabled": True, "from": 1380, "to": 420}, at(1))     # YAML turns an unquoted 23:00 into 1380


def test_night_brightness():
    assert schedule.night_brightness({"mode": "off"}) == 0 and schedule.night_brightness({}) == 10
    assert schedule.night_brightness({"brightness": 250}) == 100


# -- red background -------------------------------------------------------------------------------
def tint(**kw):
    return Tint({"tint": {"enabled": True, **kw}})


def settle(t, snap_, seconds=40):
    for i in range(seconds):
        t.update(snap_, float(i))
    return t


def test_tint_follows_the_worst_reading_and_stays_off_below_the_ranges():
    t = tint()
    assert t.target({"cpu_temp": 74, "gpu_temp": 60, "cpu_load": 80, "mem_pct": 50}) == 0.0
    assert t.target({"cpu_temp": 95}) == 1.0 and t.target({"gpu_load": 100}) == 1.0
    assert t.target({"cpu_temp": 85}) == pytest.approx(0.5) and t.target({"mem_pct": 92.5}) == pytest.approx(0.5)
    assert t.target({"ram_temp": 85}) == pytest.approx(0.5) and t.target({}) == 0.0


def test_tint_is_smoothed_quantised_and_fades_slowly():
    t = tint(steps=6, strength=0.5)
    assert t.update({"cpu_load": 40}, 0.0) == 0 and t.alpha == 0.0
    assert t.update({"cpu_load": 100}, 1.0) < 6                             # a single spike does not turn the screen fully red
    settle(t, {"cpu_load": 100})
    assert t.level == 6 and t.alpha == pytest.approx(0.5)
    steps_seen = []
    for i in range(40, 140):
        steps_seen.append(t.update({"cpu_load": 10}, float(i)))
    assert steps_seen[0] >= 5 and steps_seen[-1] == 0                        # it cools down ...
    assert all(a >= b for a, b in zip(steps_seen, steps_seen[1:]))           # ... monotonically, never flickering
    assert len(set(steps_seen)) <= 7


def test_tint_disabled_by_config_or_by_the_older_list_form():
    assert Tint([{"page": "cpu"}]).update({"cpu_temp": 120}, 0.0) == 0
    t = Tint({"tint": {"enabled": False}})
    assert t.update({"cpu_temp": 120}, 0.0) == 0 and t.alpha == 0.0
    t.configure({"tint": {"enabled": True}})
    settle(t, {"cpu_temp": 120})
    assert t.alpha > 0
    t.configure({"tint": {"enabled": False}})
    assert t.alpha == 0.0


# -- screens ---------------------------------------------------------------------------------------
def test_message_screen_and_tinted_pages_render():
    r = Renderer(None, {"header": False})
    assert r.render_message("Ciao", "locked").size == (480, 320) and r.render_message("Ciao").size == (480, 320)
    page = load_config(examples=True, lang="en")[1]["pages"][0]
    s = demo_snapshot("en")
    plain, red = r.render(page, s, 0, 9), r.render(page, s, 0, 9, 0.5)
    assert plain.size == red.size == (480, 320) and plain.tobytes() != red.tobytes()
    px_a, px_b = plain.getpixel((300, 4)), red.getpixel((300, 4))              # a background pixel above the cards got redder
    assert px_b[0] - px_b[2] > px_a[0] - px_a[2]


def test_gpu_card_on_the_overview_has_two_labelled_bars():
    cfg, pages = load_config(examples=True, lang="it")
    gpu = pages["pages"][0]["cards"][0]
    assert [b["label"] for b in gpu["bars"]] == ["GPU", "VRAM"] and gpu["bars"][1]["value"] == "gpu_vram_pct"
    r = Renderer(None, {"header": False})
    s = {**demo_snapshot("it"), "gpu_load": 90.0, "gpu_vram_pct": 20.0}
    img = r.render(pages["pages"][0], s, 0, 9)
    assert img.size == (480, 320)
def make_app(extra=None):
    cfg, pages = load_config(examples=True, lang="it")
    cfg = {**cfg, **(extra or {})}
    return App(cfg, pages)


def test_app_chooses_the_frame_and_the_backlight(monkeypatch):
    app = make_app({"night": {"enabled": True, "from": "00:00", "to": "23:59", "mode": "dim", "brightness": 12}})
    s = demo_snapshot("it")
    _, kind = app._compose(s, 1000.0)
    assert kind == "page"
    app._apply_brightness(kind)
    assert app.display.brightness == 12                          # night: dimmed
    app.away = "lock"
    _, kind = app._compose(s, 2000.0)
    assert kind == "away"
    app.cfg["night"]["mode"] = "off"
    app.away = None
    assert app._compose(s, 3000.0)[1] == "night"
    app._handle("brightness:55")
    assert app.base_brightness == 55
    app.cfg["night"]["enabled"] = False
    app._apply_brightness("page")
    assert app.display.brightness == 55
    hot = {**s, "cpu_temp": 97.0, "cpu_load": 100.0}
    for i in range(30):
        app._compose(hot, 4000.0 + i)
    assert app.tint.alpha > 0.4                                  # the red background builds up while the CPU is hot


def test_shutdown_screen_wins_over_everything_and_commands_wake_the_loop():
    app = make_app()
    app._handle("away:shutdown")
    assert app._compose({**demo_snapshot("it"), "cpu_temp": 99}, 0.0)[1] == "away"
    app._handle("away:unlock")
    assert app.away == "shutdown"                                # only a lock / sleep is undone by unlock
    q = CommandQueue()
    q.put("x")
    assert q.wake.is_set()


def test_session_events_map_to_names_and_polling_reports_changes():
    assert session.windows_event(session.WM_WTSSESSION_CHANGE, 7) == "lock" and session.windows_event(session.WM_WTSSESSION_CHANGE, 8) == "unlock"
    assert session.windows_event(session.WM_POWERBROADCAST, 4) == "sleep" and session.windows_event(session.WM_POWERBROADCAST, 18) == "resume"
    assert session.windows_event(session.WM_ENDSESSION, 1) == "shutdown" and session.windows_event(session.WM_ENDSESSION, 0) is None
    got = []
    w = session.SessionWatcher(got.append)
    ticks = iter([False, False, True, True, False])

    class Stop:
        def __init__(self):
            self.n = 0

        def wait(self, _):
            self.n += 1
            return self.n > 5
    w._stop = Stop()
    w._poll(lambda: next(ticks, None))
    assert got == ["lock", "unlock"]


# -- web preview -----------------------------------------------------------------------------------
class FakeApp:
    def __init__(self):
        import queue
        self.last_frame = Image.new("RGB", (480, 320), (10, 20, 30))
        self.frame_seq = 1
        self.pages = [{"id": "overview", "title": "OVERVIEW"}, {"id": "cpu", "title": "CPU"}]
        self.index = 0
        self.display = types.SimpleNamespace(brightness=80)
        self.updates = types.SimpleNamespace(available="9.9.9")
        self.commands = queue.Queue()


def request(web, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", web.port, timeout=5)
    c.request(method, path, body=body, headers=headers or {"Host": f"localhost:{web.port}"})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def test_web_preview_serves_frame_state_and_commands():
    app = FakeApp()
    web = WebPreview(app)
    assert web.start({"port": 0}) and web.running
    try:
        st, data = request(web, "GET", "/frame.png")
        assert st == 200 and Image.open(io.BytesIO(data)).size == (480, 320)
        st, data = request(web, "GET", "/state.json")
        assert st == 200 and json.loads(data)["pages"][1]["id"] == "cpu" and json.loads(data)["brightness"] == 80 and json.loads(data)["update"] == "9.9.9"
        assert request(web, "GET", "/")[0] == 200 and request(web, "GET", "/nope")[0] == 404
        hdr = {"Host": f"localhost:{web.port}", "Content-Type": "application/json"}
        assert request(web, "POST", "/cmd", json.dumps({"cmd": "page:cpu"}), hdr)[0] == 200
        assert app.commands.get_nowait() == "page:cpu"
        for bad in ("quit", "page:../x", "brightness:abc", "rm -rf"):
            assert request(web, "POST", "/cmd", json.dumps({"cmd": bad}), hdr)[0] == 400
        assert request(web, "POST", "/cmd", "not json", hdr)[0] == 400
        assert request(web, "GET", "/state.json", headers={"Host": "evil.example"})[0] == 403    # DNS-rebinding guard
    finally:
        web.stop()
    assert not web.running


def test_web_preview_off_network_needs_a_token():
    web = WebPreview(FakeApp())
    assert not web.start({"host": "0.0.0.0", "port": 0})                  # refuses to listen on the network without a token
    assert web.start({"host": "127.0.0.1", "port": 0, "token": "s3cret"})
    try:
        assert request(web, "GET", "/state.json", headers={"Host": f"localhost:{web.port}"})[0] == 401
        assert request(web, "GET", "/state.json?t=wrong", headers={"Host": f"localhost:{web.port}"})[0] == 401
        assert request(web, "GET", "/state.json?t=s3cret", headers={"Host": f"localhost:{web.port}"})[0] == 200
    finally:
        web.stop()


# -- updates ---------------------------------------------------------------------------------------
def test_version_comparison():
    assert updates.parse_version("v1.2.3") == (1, 2, 3) and updates.parse_version("junk") == ()
    assert updates.is_newer("1.10.0", "1.9.9") and updates.is_newer("2.0", "1.9.9") and not updates.is_newer("1.1.0", "1.1.0")
    assert not updates.is_newer("junk", "1.0.0")


def test_fetch_latest_prefers_releases_then_main(monkeypatch):
    calls = []

    def fake_get(url, timeout=10.0):
        calls.append(url)
        if "releases/latest" in url:
            return json.dumps({"tag_name": "v3.0.0", "html_url": "https://example/r"}).encode()
        raise AssertionError(url)
    monkeypatch.setattr(updates, "_get", fake_get)
    assert updates.fetch_latest("a/b")["version"] == "3.0.0"
    import urllib.error

    def no_release(url, timeout=10.0):
        if "releases/latest" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return b'__version__ = "2.5.0"\n'
    monkeypatch.setattr(updates, "_get", no_release)
    info = updates.fetch_latest("a/b")
    assert info["version"] == "2.5.0" and info["source"] == "main"
    monkeypatch.setattr(updates, "_get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert updates.fetch_latest("a/b") is None


def test_update_from_zip_only_touches_program_files(tmp_path):
    root = tmp_path / "install"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("mine", encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "bg.png").write_text("mine", encoding="utf-8")
    zp = tmp_path / "u.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("repo-main/displaymonitor/new.py", "x = 1")
        z.writestr("repo-main/config/config.yaml", "THEIRS")
        z.writestr("repo-main/config/config.example.yaml", "example")
        z.writestr("repo-main/assets/bg.png", "THEIRS")
        z.writestr("repo-main/README.md", "readme")
    done = updates.update_from_zip(str(zp), str(root))
    assert (root / "displaymonitor" / "new.py").exists() and (root / "config" / "config.example.yaml").read_text() == "example"
    assert (root / "config" / "config.yaml").read_text() == "mine" and (root / "assets" / "bg.png").read_text() == "mine"
    assert "README.md" in done
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("repo-main/../../evil.txt", "x")
    with pytest.raises(ValueError):
        updates.update_from_zip(str(evil), str(root))


# -- Linux / macOS parsers -------------------------------------------------------------------------
def entry(label, current):
    return types.SimpleNamespace(label=label, current=current, high=None, critical=None)


def test_nvidia_smi_output():
    out = sensors_posix.parse_nvidia_smi("NVIDIA GeForce RTX 3060, 61, 23, 1024, 12288, 45.12, 40, 1500, 7500\n")
    assert out["gpu_short"] == "RTX 3060" and out["gpu_temp"] == 61 and out["gpu_vram_pct"] == pytest.approx(100 * 1024 / 12288)
    assert out["gpu_power"] == 45.12 and out["gpu_fan_pct"] == 40
    assert "gpu_power" not in sensors_posix.parse_nvidia_smi("X, 50, 1, 1, 2, [N/A], [N/A], 1, 1")
    assert sensors_posix.parse_nvidia_smi("") == {}


def test_cpu_ram_and_motherboard_temperatures():
    intel = {"coretemp": [entry("Package id 0", 61), entry("Core 0", 58), entry("Core 1", 63)]}
    r = sensors_posix.parse_cpu_temps(intel)
    assert r["cpu_temp"] == 61 and r["cpu_temp_max"] == 63 and r["cpu_p_temp"] == pytest.approx(60.5)
    amd = {"k10temp": [entry("Tctl", 70), entry("Tccd1", 65)]}
    assert sensors_posix.parse_cpu_temps(amd)["cpu_temp"] == 70
    assert sensors_posix.parse_cpu_temps({}) == {}
    chips = {"coretemp": [entry("Package id 0", 61)], "nct6798": [entry("SYSTIN", 35), entry("CPUTIN", 40), entry("AUXTIN", 120)],
             "jc42": [entry("", 41), entry("", 43)]}
    assert sensors_posix.parse_ram_temps(chips) == {"ram_temp": 43, "ram_temp_avg": 42, "ram_temps_str": "41 43"}
    mb = sensors_posix.parse_mb(chips, {"nct6798": [entry("fan1", 1200), entry("fan2", 0)]})
    assert mb["mb_t_max"] == 40 and mb["mb_t3"] is None and mb["mb_fan_count"] == 1       # 120 °C is a floating probe
    assert sensors_posix.parse_mb(chips, {}, ignore=[1])["mb_t1"] is None


def test_physical_disk_names():
    f = sensors_posix.physical_disk_of
    assert f("/dev/nvme0n1p2") == "nvme0n1" and f("/dev/sda3") == "sda" and f("/dev/mmcblk0p1") == "mmcblk0" and f("/dev/vdb") == "vdb"


@pytest.mark.skipif(os.name == "nt", reason="the Linux / macOS backend")
def test_posix_backend_end_to_end():
    import time
    from displaymonitor.sensors import Sensors
    s = Sensors({"sensors": {}, "network": {"ping_host": "127.0.0.1"}})
    s.start()
    time.sleep(1.5)
    snap = s.snapshot()
    s.stop()
    assert snap["cpu_load"] is not None and snap["mem_pct"] > 0 and snap["cpu_name"]
    assert isinstance(snap["disks"], list) and "date" in snap


# -- hardware child process and watchdog ---------------------------------------------------------------
def test_hardware_worker_survives_a_crash_and_clears_stale_values(monkeypatch):
    import time
    from displaymonitor import hwproc
    monkeypatch.setattr(hwproc, "BACKOFF", (0.2,))
    state, cleared = {}, []
    w = hwproc.HardwareWorker({"sensors": {"selftest": "crash"}}, state.update, lambda keys: (cleared.append(set(keys)), [state.__setitem__(k, None) for k in keys]),
                              target=hwproc.selftest_worker)
    w.start()
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not cleared:
            w.poll()
            time.sleep(0.05)
        assert cleared, "the crash of the child was not noticed"
        assert {"cpu_name", "cpu_temp", "disks"} <= cleared[0]
        assert state["cpu_temp"] is None and state["disks"] is None          # no stale temperature left on screen
        deadline = time.time() + 20
        while time.time() < deadline and state.get("cpu_temp") is None:      # ... and the child is started again
            w.poll()
            time.sleep(0.05)
        assert state["cpu_name"] == "fake" and w.restarts >= 1
    finally:
        w.stop()


def test_watchdog_decisions(tmp_path, monkeypatch):
    import os
    import time
    from displaymonitor import watchdog
    monkeypatch.setattr(watchdog, "LOGS", str(tmp_path))
    now = time.time()
    alive = {"v": True}
    monkeypatch.setattr(watchdog, "is_ours", lambda pid, started: alive["v"])      # the process checks are tested separately
    assert watchdog.decide(now) == "not-running"
    (tmp_path / "running.flag").write_text(f"{os.getpid()} 123.0 x")
    assert watchdog.decide(now) == "ok"                                     # no heartbeat yet, flag just written: start-up grace
    os.utime(tmp_path / "running.flag", (now - 600, now - 600))
    assert watchdog.decide(now) == "frozen"                                 # alive but no heartbeat for minutes
    watchdog.touch_heartbeat()
    assert watchdog.decide(time.time()) == "ok"
    alive["v"] = False
    assert watchdog.decide(now) == "dead"
    (tmp_path / "quit.flag").write_text("x")
    assert watchdog.decide(now) == "quit-requested"


def test_watchdog_only_recognises_our_own_process(tmp_path, monkeypatch):
    from displaymonitor import watchdog

    class Proc:
        def __init__(self, pid, name="pythonw.exe", started=1000.0, cmd=("pythonw.exe", "-m", "displaymonitor")):
            self._n, self._s, self._c = name, started, list(cmd)

        def is_running(self):
            return True

        def name(self):
            return self._n

        def create_time(self):
            return self._s

        def cmdline(self):
            return self._c
    monkeypatch.setattr(watchdog.psutil, "Process", Proc)
    assert watchdog.is_ours(1, 1000.5)                                       # same start time, our command line
    assert not watchdog.is_ours(1, 5000.0)                                   # the pid was recycled by a younger process
    monkeypatch.setattr(watchdog.psutil, "Process", lambda pid: Proc(pid, cmd=("python.exe", "other_script.py")))
    assert not watchdog.is_ours(1, 1000.0)                                   # another Python program is never touched
    monkeypatch.setattr(watchdog.psutil, "Process", lambda pid: Proc(pid, name="chrome.exe"))
    assert not watchdog.is_ours(1, 1000.0)
    monkeypatch.setattr(watchdog.psutil, "Process", lambda pid: Proc(pid, started=1000.0))
    assert watchdog.is_ours(1, None)                                         # a flag written by an older version has no start time
    monkeypatch.setattr(watchdog, "LOGS", str(tmp_path))
    (tmp_path / "running.flag").write_text("4242 1000.25 2026-10-08")
    assert watchdog._flag_info() == (4242, 1000.25)
    (tmp_path / "running.flag").write_text("4242 2026-10-08 13:00:00")
    assert watchdog._flag_info() == (4242, None)


# -- configuration sanity, safe commands, atomic files, stale data, diagnostics ----------------------
def test_display_settings_are_validated_and_never_raise():
    import numpy as np
    from displaymonitor import validate
    from displaymonitor.display import Display
    st, w = validate.display_settings({"tile": 3, "refresh_band": 9999, "max_block_px": 5, "rotate": 2, "brightness": "abc", "merge_gap": -4, "flood_bytes": "x"})
    assert st["tile"] == 2 and st["refresh_band"] == 8 and st["max_block_px"] == 12800 and st["rotate"] == 1 and st["brightness"] == 100
    assert st["merge_gap"] == 4 and st["flood_bytes"] == 2_200_000 and len(w) >= 6
    for bad in (0, -2, 3, 7, 1000, "two", None, True, float("nan")):
        d = Display({"tile": bad})                                           # used to raise ZeroDivisionError / break the diff
        assert d.tile in validate.TILES
        a = np.zeros((480, 320), "<u2")
        b = a.copy()
        b[10, 10] = 1
        assert d._diff(a, b)
    assert validate.display_settings({"tile": 8})[0]["tile"] == 8 and validate.display_settings({})[1] == []


def test_hot_reload_keeps_the_current_value_when_a_new_one_is_wrong():
    from displaymonitor.display import Display
    d = Display({"tile": 4, "refresh_band": 16})
    d.configure({"tile": 3, "refresh_band": "lots", "max_block_px": 8000})
    assert d.tile == 4 and d.band == 16 and d.max_px == 8000                 # the broken values were ignored, the good one applied


def test_top_level_numbers_are_checked():
    from displaymonitor import validate
    t, w = validate.top_level({"refresh_s": 0, "rotate_s": "fast", "peek_s": -1})
    assert t == {"refresh_s": 1.0, "rotate_s": 0.0, "peek_s": 30.0} and len(w) == 3
    assert validate.top_level({"refresh_s": 2.5})[0]["refresh_s"] == 2.5


def test_malformed_commands_are_ignored_not_fatal():
    app = make_app()
    for cmd in ("brightness:abc", "logo:", "logo:left", "page", "unit:", "away:", "web:", "", ":::", "page:nope", "brightness:", "rotate:x"):
        app._handle(cmd)                                                     # none of these may raise
    app._handle("brightness:40")
    assert app.base_brightness == 40


def test_atomic_write_and_the_command_inbox(tmp_path):
    from displaymonitor import fsutil
    target = tmp_path / "sub" / "state.yaml"
    fsutil.atomic_write(str(target), "a: 1\n")
    fsutil.atomic_write(str(target), "a: 2\n")
    assert target.read_text() == "a: 2\n" and [p.name for p in target.parent.iterdir()] == ["state.yaml"]    # no temp files left
    inbox = tmp_path / "control.cmd"
    assert fsutil.take_lines(str(inbox)) == []
    inbox.write_text("next\n\nhome\n", encoding="utf-8")
    assert fsutil.take_lines(str(inbox)) == ["next", "home"] and not inbox.exists() and not (tmp_path / "control.cmd.work").exists()
    inbox.write_text("late\n", encoding="utf-8")                               # a line written after the swap goes to a fresh file
    assert fsutil.take_lines(str(inbox)) == ["late"]
    (tmp_path / "control.cmd.work").write_text("left over\n", encoding="utf-8")   # a half-processed batch from a crashed run is not lost
    assert fsutil.take_lines(str(inbox)) == ["left over"]


def test_a_failing_frame_does_not_stop_the_loop(monkeypatch, tmp_path):
    import threading
    import time
    from displaymonitor import watchdog
    app = make_app()
    monkeypatch.setattr(app_mod, "ROOT", str(tmp_path))                     # run() writes logs/running.flag, quit.flag: never the real ones
    monkeypatch.setattr(watchdog, "LOGS", str(tmp_path / "logs"))
    app.control_file, app.state_file = str(tmp_path / "control.cmd"), str(tmp_path / "state.yaml")
    monkeypatch.setattr(type(app.display), "connected", property(lambda self: True))
    monkeypatch.setattr(app.display, "show", lambda frame, critical=False: True, raising=False)
    calls = {"n": 0}

    def boom(snap, now):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("bad page")
        return Image.new("RGB", (480, 320)), "page"
    monkeypatch.setattr(app, "_compose", boom)
    monkeypatch.setattr(app.sensors, "start", lambda: None)
    monkeypatch.setattr(app.sensors, "stop", lambda: None)
    monkeypatch.setattr(app.session, "start", lambda: None)
    monkeypatch.setattr(app.updates, "start", lambda: None)
    app.refresh_s = 0.1
    t = threading.Thread(target=app.run, daemon=True)
    t.start()
    deadline = time.time() + 15
    while time.time() < deadline and calls["n"] < 4:
        time.sleep(0.05)
    app.commands.put("quit")
    t.join(10)
    assert calls["n"] >= 4 and app.errors == 2 and not t.is_alive()          # two bad frames were survived, then it kept drawing


def test_healing_band_is_skipped_while_the_panel_is_busy():
    import numpy as np
    from displaymonitor.display import Display, HW_H, HW_W
    d = Display({"refresh_band": 8, "band_budget": 24_000})
    sent = []
    d._ser = types.SimpleNamespace(write=lambda b: sent.append(len(b)), flush=lambda: None)
    frame = np.zeros((320, 480), "<u2")
    d.show(frame)                                                            # first frame: everything
    d.show(frame)                                                            # nothing changed: the band is sent
    assert d.last_rects == 1 and d.band_skipped == 0
    big = frame.copy()
    big[:, :] = 7                                                            # a whole-screen change: far over the budget
    d.show(big)
    assert d.band_skipped == 1 and d.last_ms >= 0
    small = big.copy()
    small[10:20, 10:20] = 3
    d.show(small)
    assert d.band_skipped == 1                                               # a small change: the band is back


def test_stale_hardware_data_is_dimmed_and_labelled():
    r = Renderer(None, {"header": False})
    page = load_config(examples=True, lang="en")[1]["pages"][0]
    s = demo_snapshot("en")
    live = r.render(page, s, 0, 9)
    stale = r.render(page, {**s, "hw_stale": True, "hw_age_s": 9.0}, 0, 9)
    assert live.size == stale.size == (480, 320) and live.tobytes() != stale.tobytes()
    assert not r._faded                                                      # the dimming never leaks into the next frame
    badge_live = live.crop((380, 303, 480, 320)).tobytes()
    assert badge_live != stale.crop((380, 303, 480, 320)).tobytes()


def test_hardware_worker_reports_the_age_of_its_data():
    import time
    from displaymonitor import hwproc
    w = hwproc.HardwareWorker({"sensors": {}}, lambda d: None, lambda k: None, target=hwproc.selftest_worker)
    assert w.age() is None                                                   # not started
    w.start()
    try:
        assert w.age() is None                                               # started but silent: start-up, not "stale"
        deadline = time.time() + 20
        while time.time() < deadline and w.age() is None:
            w.poll()
            time.sleep(0.05)
        assert w.age() is not None and w.age() < 5
        w._last -= 30
        assert w.age() > 25
    finally:
        w.stop()


def test_app_keeps_diagnostics():
    app = make_app()
    assert app.diag_text() == "--"
    app.display.last_bytes, app.display.last_rects, app.display.last_ms = 20480, 3, 55.0
    app._update_diag(100.0, 12.0, {"hw_age_s": 1.0})
    t = app.diag_text()
    assert "KB/s" in t and "55 ms" in t and "12 ms" in t and "3 rect" in t
