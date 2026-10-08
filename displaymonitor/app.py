"""Main loop: sensors -> page renderer -> display (only changed rectangles), page rotation, alerts, reconnect."""
import glob
import logging
import os
import queue
import threading
import time
from collections import defaultdict

import psutil
import yaml
from PIL import Image

from .display import Display, rgb565
from .render import Renderer
from .schedule import night_active, night_brightness
from .sensors import Sensors
from .slowmode import SlowFilter
from .tint import Tint
from .session import SessionWatcher
from . import units, validate
from .fsutil import atomic_write, take_lines
from .updates import UpdateChecker
from .watchdog import touch_heartbeat
from .web import WebPreview

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


LANGUAGES = ("en", "it")          # shipped language packs: config/config.<lang>.example.yaml + config/pages.<lang>.example.yaml


def example_path(name: str, lang: str | None = None) -> str:
    """config/pages.yaml -> config/pages.<lang>.example.yaml (the language pack) or, for English / unknown, config/pages.example.yaml."""
    stem = name[:-len(".yaml")]
    if lang and lang != "en":
        p = os.path.join(ROOT, "config", f"{stem}.{lang}.example.yaml")
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "config", f"{stem}.example.yaml")


def _parse_yaml(path: str, label: str, check):
    """Read + parse + structurally check one config file. Raises validate.ConfigError with a message that says what is wrong."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise validate.ConfigError(f"{label}: file not found ({path})") from None
    except yaml.YAMLError as e:
        first = " ".join(str(e).split())[:240]
        raise validate.ConfigError(f"{label}: invalid YAML - {first}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise validate.ConfigError(f"{label}: cannot be read - {e}") from None
    return check(data if data is not None else ({} if label == "config.yaml" else None))


def load_config(examples: bool = False, lang: str | None = None, fallback: bool = False):
    """config/config.yaml and config/pages.yaml are your own (git-ignored) files; if they do not exist the
    shipped examples are used, so a fresh checkout works out of the box (examples=True forces them).
    `lang` picks the language pack ("en" or "it") when an example is used.

    A file that is invalid YAML or has the wrong shape raises validate.ConfigError (a hot reload then keeps the previous configuration).
    With fallback=True (the cold start) the shipped example is used instead, with a clear error in the log: your file is never modified."""
    def read(name, check, hint):
        mine = os.path.join(ROOT, "config", name)
        if os.path.exists(mine) and not examples:
            try:
                return _parse_yaml(mine, name, check)
            except validate.ConfigError as e:
                if not fallback:
                    raise
                log.error("%s - starting with the included example instead (your file is untouched; fix it and the program picks it up by itself)", e)
        return _parse_yaml(example_path(name, hint or lang), name, check)
    cfg = read("config.yaml", validate.check_config, lang)
    pages = read("pages.yaml", validate.check_pages, lang or (cfg.get("language") if isinstance(cfg, dict) else None))
    return cfg, pages


def init_language_pack(lang: str, force: bool = False) -> list[str]:
    """Install a language pack as your own config/config.yaml + config/pages.yaml. Refuses to overwrite unless force."""
    import shutil
    if lang not in LANGUAGES:
        raise ValueError(f"unknown language '{lang}' (available: {', '.join(LANGUAGES)})")
    done = []
    for name in ("config.yaml", "pages.yaml"):
        dst = os.path.join(ROOT, "config", name)
        if os.path.exists(dst) and not force:
            raise FileExistsError(f"{dst} already exists (use --force to replace it; a backup is kept as {name}.bak)")
    for name in ("config.yaml", "pages.yaml"):
        dst = os.path.join(ROOT, "config", name)
        if os.path.exists(dst):
            shutil.copyfile(dst, dst + ".bak")
        shutil.copyfile(example_path(name, lang), dst)
        done.append(dst)
    return done


def config_signature() -> tuple:
    """Modification times of every file that shapes the look: config, pages and theme presets. A change triggers a hot reload."""
    files = [os.path.join(ROOT, "config", n) for n in ("config.yaml", "config.example.yaml", "pages.yaml", "pages.example.yaml")]
    files += glob.glob(os.path.join(ROOT, "config", "themes", "*.yaml")) + glob.glob(os.path.join(ROOT, "themes", "*.yaml"))
    sig = []
    for f in sorted(files):
        try:
            sig.append((f, os.path.getmtime(f)))
        except OSError:
            pass
    return tuple(sig)


def enabled_pages(pages_cfg: dict, cfg: dict) -> list:
    """Pages may declare `requires: weather` (or a list): they are hidden while that feature is switched off in config.yaml."""
    out = []
    for p in pages_cfg["pages"]:
        req = p.get("requires") or []
        req = [req] if isinstance(req, str) else req
        if all(bool((cfg.get(r) or {}).get("enabled")) for r in req):
            out.append(p)
    return out


class _Env(defaultdict):
    def __missing__(self, key):
        return None


def alert_active(expr: str, snap: dict) -> bool:
    try:
        return bool(eval(compile(expr, "<alert>", "eval"), {"__builtins__": {}}, _Env(lambda: None, snap)))  # noqa: S307
    except Exception:  # noqa: BLE001
        return False


AWAY_TEXT = {"en": {"lock": "screen locked", "sleep": "sleeping", "shutdown": "shutting down"},
             "it": {"lock": "schermo bloccato", "sleep": "sospensione", "shutdown": "spegnimento"}}


def page_alert_rules(cfg: dict) -> list:
    """The older "show this page when <condition>" rules: `alerts:` as a list, or `alerts.pages`."""
    a = cfg.get("alerts")
    return list(a) if isinstance(a, list) else list((a or {}).get("pages") or [])


class CommandQueue(queue.Queue):
    """Commands for the main loop; putting one wakes it up at once (the lock / shutdown screen must not wait for the next refresh)."""

    def __init__(self):
        super().__init__()
        self.wake = threading.Event()

    def put(self, item, block=True, timeout=None):
        super().put(item, block, timeout)
        self.wake.set()


class App:
    @property
    def unit(self) -> str:
        """'C' or 'F': the tray's choice, else config.yaml `temperature_unit`."""
        return units.norm(self.unit_wanted if self.unit_wanted else self.cfg.get("temperature_unit"))

    def __init__(self, cfg: dict, pages_cfg: dict):
        self.cfg = cfg
        self.unit_wanted: str | None = None     # °C / °F chosen from the tray (saved in state.yaml); None = follow config temperature_unit
        self.pages = enabled_pages(pages_cfg, cfg)
        self.sensors = Sensors(cfg)
        self.display = Display(cfg.get("display", {}))
        self.renderer = Renderer(cfg.get("theme"), cfg.get("layout"), self.unit)
        self.commands = CommandQueue()   # next | prev | home | pin | rotate | quit | page:<id> | brightness:<0-100> | away:<event> | web:on|off|toggle
        self.lang = cfg.get("language", "en")
        self.tint = Tint(cfg.get("alerts"))
        self.slow = SlowFilter(self.display.slow["noncritical_s"]) if self.display.mode == "slow" else None
        self._last_kind = None
        self.base_brightness = self._cfg_brightness = self.display.brightness   # what the user asked for; the night schedule overrides it
        self.away: str | None = None            # lock | sleep | shutdown while the "Ciao" screen is shown
        self.bye_done = threading.Event()       # set once the shutdown frame has been sent
        self.last_frame: Image.Image | None = None
        self.diag: dict = {}                    # last frame's numbers: KB/s, send / render ms, rectangles (tray, web)
        self._diag_t = 0.0
        self.errors = 0                         # loop iterations that raised and were survived
        self.frame_seq = 0
        self.updates = UpdateChecker(cfg.get("updates"))
        self.web = WebPreview(self)
        self.web_wanted: bool | None = None     # the tray's choice (saved in state.yaml); None = follow config web.enabled
        self.session = SessionWatcher(self._on_session)
        ids = [p["id"] for p in self.pages]
        self.home = ids.index(cfg.get("home_page", ids[0])) if cfg.get("home_page", ids[0]) in ids else 0
        self.index = self.home                 # page currently shown
        top, warns = validate.top_level(cfg)
        validate.warn_all(warns)
        self.refresh_s = top["refresh_s"]
        self.stay_on_selected = bool(cfg.get("stay_on_selected", True))
        self.peek_s = top["peek_s"]
        self.peek_until = 0.0                  # a page picked from the tray stays visible until then, then back home
        self.pinned = False                    # stay on the picked page indefinitely
        self.rotate = top["rotate_s"] > 0   # automatic rotation (off by default: one recap page)
        self.rotate_s = top["rotate_s"] or (self.display.slow["rotate_s"] if self.display.mode == "slow" else 12.0)   # seconds per page when rotation is switched on
        self.alert_page = None
        self.alert_until = 0.0
        self._page_since = time.time()
        self.control_file = os.path.join(ROOT, "logs", "control.cmd")
        self.state_file = os.path.join(ROOT, "config", "state.yaml")     # choices made from the tray that must survive a restart
        self._config_logos = tuple(self.renderer.t["logos"])
        self._load_state()
        self._sig = config_signature()
        self._sig_checked = time.time()

    # -- hot reload -----------------------------------------------------------------------------
    def reload_config(self, reason: str = "files changed"):
        """Re-read config / pages / themes and rebuild the renderer without restarting. Sensor settings (poll rates, network
        interface ...) still need a restart. A broken file keeps the previous configuration and is reported in the log."""
        self._sig = config_signature()
        try:
            cfg, pages_cfg = load_config()
            pages = enabled_pages(pages_cfg, cfg)
            if not pages:
                raise ValueError("no pages left after filtering")
            renderer = Renderer(cfg.get("theme"), cfg.get("layout"), units.norm(self.unit_wanted if self.unit_wanted else cfg.get("temperature_unit")))
        except Exception as e:  # noqa: BLE001
            log.warning("config reload failed, keeping the previous configuration: %s", e)
            return
        current = self.pages[self.index]["id"] if self.pages else None
        self.cfg, self.pages, self.renderer = cfg, pages, renderer
        ids = [p["id"] for p in pages]
        self.home = ids.index(cfg.get("home_page", ids[0])) if cfg.get("home_page", ids[0]) in ids else 0
        self.index = ids.index(current) if current in ids else self.home
        top, warns = validate.top_level(cfg)
        validate.warn_all(warns)
        self.refresh_s = top["refresh_s"]
        self.stay_on_selected = bool(cfg.get("stay_on_selected", True))
        self.peek_s = top["peek_s"]
        self._config_logos = tuple(renderer.t["logos"])
        self._load_state()
        self.display.configure(cfg.get("display", {}))           # first: the new mode decides the default page dwell below
        self.rotate_s = top["rotate_s"] or (self.display.slow["rotate_s"] if self.display.mode == "slow" else 12.0)
        if "brightness" in cfg.get("display", {}) and Display._clamp_pct(cfg["display"]["brightness"]) != self._cfg_brightness:
            self.base_brightness = self._cfg_brightness = Display._clamp_pct(cfg["display"]["brightness"])
        self.lang = cfg.get("language", "en")
        self.tint.configure(cfg.get("alerts"))
        self.slow = SlowFilter(self.display.slow["noncritical_s"]) if self.display.mode == "slow" else None
        self.sensors.set_language(cfg)
        self._sync_web()
        log.info("configuration reloaded (%s): %d pages, theme preset %s", reason, len(pages), (cfg.get("theme") or {}).get("preset"))

    def _load_state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                state = yaml.safe_load(f) or {}
        except OSError:
            return
        if state.get("logos"):
            self.renderer.set_logos(*(list(state["logos"]) + [None, None])[:2])
        if isinstance(state.get("web"), bool):
            self.web_wanted = state["web"]
        if state.get("unit") in ("C", "F"):
            self.unit_wanted = state["unit"]
            self.renderer.unit = self.unit

    def _save_state(self):
        state = {}
        if self.state_file_has_logos():
            state["logos"] = [x if isinstance(x, (str, dict)) else None for x in self.renderer.t["logos"]]
        if self.web_wanted is not None:
            state["web"] = self.web_wanted
        if self.unit_wanted:
            state["unit"] = self.unit_wanted
        try:
            if state:
                atomic_write(self.state_file, yaml.safe_dump(state))
            elif os.path.exists(self.state_file):
                os.remove(self.state_file)
        except OSError as e:
            log.warning("cannot save %s: %s", self.state_file, e)

    def state_file_has_logos(self) -> bool:
        """The tray's logo choice is only saved once it differs from config.yaml (so `logo:reset` leaves no stale choice)."""
        return tuple(self.renderer.t["logos"]) != tuple(self._config_logos)

    def web_enabled(self) -> bool:
        return self.web_wanted if self.web_wanted is not None else bool((self.cfg.get("web") or {}).get("enabled", False))

    def _sync_web(self):
        want = self.web_enabled()
        if want and not self.web.running:
            self.web.start(self.cfg.get("web"))
        elif not want and self.web.running:
            self.web.stop()

    # -- control --------------------------------------------------------------------------------
    def _show_page(self, i: int):
        """A page picked by the user: it stays until 'home' (or, with stay_on_selected: false, for peek_s seconds).
        Nothing is saved: every start begins on the home page."""
        self.index, self._page_since = i, time.time()
        if self.stay_on_selected:
            self.pinned = True
        else:
            self.peek_until = time.time() + self.peek_s

    def _handle(self, cmd: str):
        """Run one command; a malformed one (brightness:abc, logo:) is logged and ignored, never allowed to stop the loop."""
        try:
            self._do(cmd)
        except (ValueError, IndexError, KeyError, TypeError, OSError) as e:
            log.warning("command %r ignored: %s", cmd, e)

    def _do(self, cmd: str):
        n = len(self.pages)
        if cmd == "next":
            self._show_page((self.index + 1) % n)
        elif cmd == "prev":
            self._show_page((self.index - 1) % n)
        elif cmd == "home":
            self.index, self.peek_until, self.pinned = self.home, 0.0, False
        elif cmd == "pin":
            self.pinned = not self.pinned
        elif cmd == "rotate":
            self.rotate = not self.rotate
            self._page_since = time.time()
        elif cmd.startswith("page:"):
            for i, p in enumerate(self.pages):
                if p["id"] == cmd[5:]:
                    self.pinned = False
                    self._show_page(i)
                    if p["id"] == self.pages[self.home]["id"]:
                        self.pinned = False        # picking the home page is simply 'home'
        elif cmd == "reload":
            self.reload_config("requested")
        elif cmd == "logo:reset":
            self.renderer.set_logos(*(list(self._config_logos) + [None, None])[:2])
            self._save_state()
        elif cmd.startswith("logo:"):
            _, side, name = cmd.split(":", 2)           # logo:left:amd | logo:right:none
            cur = list(self.renderer.t["logos"]) + [None, None]
            cur[0 if side == "left" else 1] = None if name == "none" else name
            self.renderer.set_logos(cur[0], cur[1])
            self._save_state()
        elif cmd.startswith("brightness:"):
            self.base_brightness = Display._clamp_pct(cmd[11:])         # applied by _apply_brightness (the night schedule may override it)
        elif cmd.startswith("away:"):
            ev = cmd[5:]
            if ev in ("lock", "sleep", "shutdown"):
                self.away = ev
            elif ev == "unlock":
                if self.away in ("lock", "sleep"):
                    self.away = None             # a shutdown in progress is not undone
            elif ev == "resume":
                self.display.invalidate()
                if self.away == "sleep":
                    self.away = None
        elif cmd.startswith("web:"):
            self.web_wanted = {"on": True, "off": False}.get(cmd[4:], not self.web_enabled())
            self._save_state()
            self._sync_web()
        elif cmd == "debug:kill-hw":                      # simulates a driver crash: the hardware child dies, the program must carry on
            w = self.sensors._worker
            if w is not None and w._proc is not None:
                log.warning("debug: killing the hardware sensor process")
                w._proc.kill()
        elif cmd.startswith("unit:"):                      # unit:c | unit:f | unit:toggle | unit:config (back to config.yaml)
            arg = cmd[5:].lower()
            self.unit_wanted = {"c": "C", "celsius": "C", "f": "F", "fahrenheit": "F", "config": None}.get(arg, "C" if self.unit == "F" else "F")
            self.renderer.unit = self.unit
            self._save_state()
        elif cmd == "update:check":
            threading.Thread(target=self.updates.check_now, daemon=True).start()

    def _poll_control_file(self):
        """Commands from `python -m displaymonitor --send <cmd>` (clean restarts, page selection from scripts)."""
        for ln in take_lines(self.control_file):
            self.commands.put(ln)

    def _current(self, snap) -> int:
        now = time.time()
        for al in page_alert_rules(self.cfg):
            if alert_active(al["when"], snap):
                self.alert_page, self.alert_until = al["page"], now + al.get("hold_s", 30)
                break
        if self.alert_page and now < self.alert_until:
            for i, p in enumerate(self.pages):
                if p["id"] == self.alert_page:
                    return i
        if self.pinned or now < self.peek_until:
            return self.index
        if self.rotate:
            if now - self._page_since >= self.rotate_s:
                self.index, self._page_since = (self.index + 1) % len(self.pages), now
            return self.index
        self.index = self.home
        return self.index

    # -- session events (lock / sleep / shutdown) ------------------------------------------------
    def _on_session(self, event: str):
        """Called from the session watcher's thread. For a shutdown it returns only after the "Ciao" frame was sent."""
        if event in ("lock", "sleep", "shutdown"):
            self.bye_done.clear()
            self.commands.put(f"away:{event}")
            if event == "shutdown":
                self.bye_done.wait(4.0)
        elif event in ("unlock", "resume"):
            self.commands.put(f"away:{event}")

    # -- what is on screen ----------------------------------------------------------------------
    def _night(self) -> bool:
        return night_active(self.cfg.get("night"))

    def _compose(self, snap: dict, now: float):
        """The frame to show now and what it is: 'away' | 'night' | 'page'."""
        away_cfg = self.cfg.get("away") or {}
        away_on = bool(away_cfg.get("enabled", True))
        if self.away == "shutdown" and away_on:
            return self._away_frame(away_cfg), "away"
        if self.away and away_on:
            return self._away_frame(away_cfg), "away"
        if self._night() and str((self.cfg.get("night") or {}).get("mode", "dim")) == "off":
            return Image.new("RGB", (480, 320), (0, 0, 0)), "night"
        idx = self._current(snap)
        self.tint.update(snap, now)
        return self.renderer.render(self.pages[idx], snap, idx, len(self.pages), self.tint.alpha, self.tint.style), "page"

    def _away_frame(self, away_cfg: dict):
        default = "Ciao" if self.lang == "it" else "Bye"
        sub = AWAY_TEXT.get(self.lang, AWAY_TEXT["en"]).get(self.away or "lock", "") if away_cfg.get("subtitle", True) else ""
        return self.renderer.render_message(str(away_cfg.get("text", default)), sub)

    def _apply_brightness(self, kind: str):
        """Backlight: the night schedule dims it, otherwise what the user chose."""
        if self._night():
            want = night_brightness(self.cfg.get("night"))
        else:
            want = self.base_brightness
        if want != self.display.brightness:
            self.display.set_brightness(want)

    # -- diagnostics ----------------------------------------------------------------------------
    def diag_text(self) -> str:
        d = self.diag
        if not d:
            return "--"
        text = f"{d['kbps']:.1f} KB/s · send {d['send_ms']:.0f} ms · render {d['render_ms']:.0f} ms · {d['rects']} rect"
        tx = self.display.tx
        if tx["budget"]:                                     # a budget is in force (slow mode, or tx_budget_bytes): show how it is going
            text += f" · budget {tx['sent'] / 1024:.0f}/{tx['budget'] / 1024:.0f} KB"
        if tx["pending"]:
            text += f" · pending {tx['pending'] / 1024:.0f} KB (~{tx['latency_s']:.1f} s)"
        if tx["coalesced"] and (tx["budget"] or tx["pending"]):
            text += f" · {tx['coalesced']} coalesced"
        return text

    def _update_diag(self, t0: float, render_ms: float, snap: dict):
        dt = max(0.05, t0 - self._diag_t) if self._diag_t else self.refresh_s
        self._diag_t = t0
        kbps = self.display.last_bytes / 1024 / dt
        old = self.diag.get("kbps", kbps)
        self.diag = {"kbps": 0.8 * old + 0.2 * kbps, "send_ms": self.display.last_ms, "render_ms": render_ms, "bytes": self.display.last_bytes,
                     "rects": self.display.last_rects, "band_skipped": self.display.band_skipped, "errors": self.errors, "tx": dict(self.display.tx),
                     "hw_age_s": snap.get("hw_age_s")}

    # -- run ------------------------------------------------------------------------------------
    def run(self):
        # Clean-exit marker: if it is still there, the last run was killed (possibly mid-bitmap) and the display's
        # firmware may be waiting for pixels -> flush it before use. Removed only by an orderly shutdown.
        # It also records this process (pid + start time) for the watchdog, which must never mistake another process for us.
        flag = os.path.join(ROOT, "logs", "running.flag")
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        if os.path.exists(flag):
            log.warning("previous run did not exit cleanly")
            self.display.needs_flood = True
        with open(flag, "w") as f:
            f.write(f"{os.getpid()} {psutil.Process().create_time():.2f} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        quit_flag = os.path.join(ROOT, "logs", "quit.flag")        # written by a deliberate quit, so the watchdog leaves it alone
        try:
            os.remove(quit_flag)
        except OSError:
            pass
        beat = err_at = 0.0
        self.sensors.start()
        self.updates.start()
        self.session.start()
        self._sync_web()
        last_retry = 0.0
        try:
            while True:
                t0 = time.time()
                try:
                    if self.cfg.get("hot_reload", True) and t0 - self._sig_checked >= 1.0:
                        self._sig_checked = t0
                        if config_signature() != self._sig:
                            self.reload_config()
                    self._poll_control_file()
                    if t0 - beat >= 5.0:
                        beat = t0
                        touch_heartbeat()
                    try:
                        while True:
                            cmd = self.commands.get_nowait()
                            if cmd == "quit":
                                with open(quit_flag, "w") as f:
                                    f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
                                return
                            self._handle(cmd)
                    except queue.Empty:
                        pass
                    if not self.display.connected and t0 - last_retry >= 2.0:
                        last_retry = t0
                        self.display.connect()
                    if self.display.connected or self.web.running or self.away == "shutdown":
                        snap = self.sensors.snapshot()
                        snap["update_available"] = self.updates.available
                        if self.slow is not None:                # slow mode: only the critical readings are live
                            snap = self.slow.apply(snap, t0)
                        img, kind = self._compose(snap, t0)
                        render_ms = (time.time() - t0) * 1000
                        self._apply_brightness(kind)
                        self.last_frame, self.frame_seq = img, self.frame_seq + 1
                        if self.display.connected:
                            # the "Ciao" / night-black frames are critical: sent whole, at once, ahead of any budget (on the change, not every cycle)
                            critical = kind in ("away", "night") and kind != self._last_kind
                            self.display.show(rgb565(img), critical=critical)
                        self._last_kind = kind
                        self._update_diag(t0, render_ms, snap)
                        log.debug("%s: %d rects, %d bytes, %.0f ms", kind, self.display.last_rects, self.display.last_bytes,
                                  (time.time() - t0) * 1000)
                        if self.away == "shutdown":      # the session is ending: the "Ciao" frame is out, nothing more to do
                            self.bye_done.set()
                            log.info("shutdown screen shown, exiting")
                            return
                except Exception:  # noqa: BLE001 - one bad frame, page or setting must not stop the program: keep the last picture
                    self.errors += 1
                    if t0 - err_at > 30:
                        err_at = t0
                        log.exception("main loop error (carrying on; fix the page / config and it recovers by itself)")
                self.commands.wake.wait(max(0.05, self.refresh_s - (time.time() - t0)))
                self.commands.wake.clear()
        finally:
            self.bye_done.set()
            self.session.stop()
            self.updates.stop()
            self.web.stop()
            self.sensors.stop()
            self.display.disconnect()
            try:
                os.remove(flag)          # orderly shutdown: nothing is left half-sent
            except OSError:
                pass
