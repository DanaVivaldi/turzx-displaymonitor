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
    assert watchdog.decide(now) == "not-running"
    (tmp_path / "running.flag").write_text(f"{os.getpid()} x")
    assert watchdog.decide(now) == "ok"                                     # no heartbeat yet, flag just written: start-up grace
    os.utime(tmp_path / "running.flag", (now - 600, now - 600))
    assert watchdog.decide(now) == "frozen"                                 # pid alive (this test process) but no heartbeat for minutes
    watchdog.touch_heartbeat()
    assert watchdog.decide(time.time()) == "ok"
    (tmp_path / "running.flag").write_text("99999999 x")
    assert watchdog.decide(now) == "dead"
    (tmp_path / "quit.flag").write_text("x")
    assert watchdog.decide(now) == "quit-requested"


# -- Fahrenheit ------------------------------------------------------------------------------------
def test_unit_helpers():
    from displaymonitor import units
    assert units.norm("Fahrenheit") == "F" and units.norm("f") == "F" and units.norm("°F") == "F" and units.norm(None) == "C" and units.norm("kelvin") == "C"
    assert units.c_to_f(0) == 32 and units.c_to_f(100) == 212 and units.delta(10, "F") == 18 and units.delta(10, "C") == 10
    assert units.convert_numbers("61 63 60.5", "F") == "142 145 140.9" and units.convert_numbers("61", "C") == "61"
    assert units.swap_symbol("CPU °C · 45°C", "F") == "CPU °F · 45°F"
    assert units.is_temperature_key("cpu_temp") and units.is_temperature_key("mb_t3") and units.is_temperature_key("weather_feels")
    assert not units.is_temperature_key("cpu_load") and not units.is_temperature_key("gpu_vram_pct") and not units.is_temperature_key("mem_pct")


def test_fmt_converts_temperatures_but_not_percentages():
    s = {"cpu_temp": 50.0, "cpu_load": 50.0, "cpu_p_temps_str": "50 60", "temp": 100.0, "name": "x"}
    assert render_mod.fmt("{cpu_temp:.0f}°C {cpu_load:.0f}% {cpu_p_temps_str} {temp:.0f}°C", s, "F") == "122°F 50% 122 140 212°F"
    assert render_mod.fmt("{cpu_temp:.0f}°C", s) == "50°C" and render_mod.fmt("{cpu_temp:.0f}°C", {}, "F") == "--°F"


def test_fahrenheit_changes_the_text_not_the_colours():
    r_c, r_f = Renderer(None, {"header": False}), Renderer(None, {"header": False}, "F")
    assert r_f.unit == "F"
    snap_ = demo_snapshot("en")
    page = load_config(examples=True, lang="en")[1]["pages"][1]
    a, b = r_c.render(page, snap_, 1, 9), r_f.render(page, snap_, 1, 9)
    assert a.size == b.size == (480, 320) and a.tobytes() != b.tobytes()
    assert r_f.temp_color(70.0) == r_c.temp_color(70.0)                     # the colour scale is judged in °C
    t = Tint({"tint": {"enabled": True}})
    assert t.target({"cpu_temp": 85.0}) == pytest.approx(0.5)               # ... and so is the red background


def test_app_unit_command_and_cpu_power_card():
    app = make_app({"temperature_unit": "fahrenheit"})
    assert app.unit == "F" and app.renderer.unit == "F"
    app._handle("unit:c")
    assert app.unit == "C" and app.renderer.unit == "C"
    app._handle("unit:toggle")
    assert app.unit == "F"
    app._handle("unit:config")
    assert app.unit == "F" and app.unit_wanted is None
    cpu = next(p for p in app.pages if p["id"] == "cpu")
    assert any("cpu_power" in str(c.get("big", "")) for c in cpu["cards"])    # the power card is on the CPU page
    s = demo_snapshot("it")
    assert app.renderer.render(cpu, s, 1, len(app.pages)).size == (480, 320)


def test_cpu_power_peak_and_scale():
    from displaymonitor.sensors import Sensors
    s = Sensors({"sensors": {"cpu_power_max": 100}})
    out = {"cpu_power": 80.0}
    s._power_stats(out)
    assert out["cpu_power_peak"] == 80 and out["cpu_power_scale"] == 100
    out = {"cpu_power": 60.0}
    s._power_stats(out)
    assert out["cpu_power_peak"] == 80                                    # the peak stays
    out = {"cpu_power": 130.0}
    s._power_stats(out)
    assert out["cpu_power_peak"] == 130 and out["cpu_power_scale"] == 130  # the bar grows with the CPU
