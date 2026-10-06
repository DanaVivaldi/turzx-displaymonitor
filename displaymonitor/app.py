"""Main loop: sensors -> page renderer -> display (only changed rectangles), page rotation, alerts, reconnect."""
import logging
import os
import queue
import time
from collections import defaultdict

import yaml

from .display import Display, rgb565
from .render import Renderer
from .sensors import Sensors

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(examples: bool = False):
    """config/config.yaml and config/pages.yaml are your own (git-ignored) files; if they do not exist the
    shipped config/*.example.yaml are used, so a fresh checkout works out of the box (examples=True forces them)."""
    def read(name):
        base = os.path.join(ROOT, "config", name)
        path = base if os.path.exists(base) and not examples else base.replace(".yaml", ".example.yaml")
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return read("config.yaml"), read("pages.yaml")


class _Env(defaultdict):
    def __missing__(self, key):
        return None


def alert_active(expr: str, snap: dict) -> bool:
    try:
        return bool(eval(compile(expr, "<alert>", "eval"), {"__builtins__": {}}, _Env(lambda: None, snap)))  # noqa: S307
    except Exception:  # noqa: BLE001
        return False


class App:
    def __init__(self, cfg: dict, pages_cfg: dict):
        self.cfg = cfg
        self.pages = pages_cfg["pages"]
        self.sensors = Sensors(cfg)
        self.display = Display(cfg.get("display", {}))
        self.renderer = Renderer(cfg.get("theme"))
        self.commands: "queue.Queue[str]" = queue.Queue()   # next | prev | home | pin | rotate | quit | page:<id> | brightness:<n>
        ids = [p["id"] for p in self.pages]
        self.home = ids.index(cfg.get("home_page", ids[0])) if cfg.get("home_page", ids[0]) in ids else 0
        self.index = self.home                 # page currently shown
        self.stay_on_selected = bool(cfg.get("stay_on_selected", True))
        self.peek_s = float(cfg.get("peek_s", 30))
        self.peek_until = 0.0                  # a page picked from the tray stays visible until then, then back home
        self.pinned = False                    # stay on the picked page indefinitely
        self.rotate = float(cfg.get("rotate_s", 0)) > 0   # automatic rotation (off by default: one recap page)
        self.rotate_s = float(cfg.get("rotate_s", 0)) or 12.0   # seconds per page when rotation is switched on
        self.alert_page = None
        self.alert_until = 0.0
        self._page_since = time.time()
        self.control_file = os.path.join(ROOT, "logs", "control.cmd")

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
        elif cmd.startswith("brightness:"):
            self.display.set_brightness(int(cmd[11:]))

    def _poll_control_file(self):
        """Commands from `python -m displaymonitor --send <cmd>` (clean restarts, page selection from scripts)."""
        try:
            with open(self.control_file, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            os.remove(self.control_file)
        except OSError:
            return
        for ln in lines:
            self.commands.put(ln)

    def _current(self, snap) -> int:
        now = time.time()
        for al in self.cfg.get("alerts", []):
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

    # -- run ------------------------------------------------------------------------------------
    def run(self):
        # Clean-exit marker: if it is still there, the last run was killed (possibly mid-bitmap) and the display's
        # firmware may be waiting for pixels -> flush it before use. Removed only by an orderly shutdown.
        flag = os.path.join(ROOT, "logs", "running.flag")
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        if os.path.exists(flag):
            log.warning("previous run did not exit cleanly")
            self.display.needs_flood = True
        with open(flag, "w") as f:
            f.write(f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.sensors.start()
        refresh = float(self.cfg.get("refresh_s", 1.0))
        last_retry = 0.0
        try:
            while True:
                t0 = time.time()
                self._poll_control_file()
                try:
                    while True:
                        cmd = self.commands.get_nowait()
                        if cmd == "quit":
                            return
                        self._handle(cmd)
                except queue.Empty:
                    pass
                if not self.display.connected and t0 - last_retry >= 2.0:
                    last_retry = t0
                    self.display.connect()
                if self.display.connected:
                    snap = self.sensors.snapshot()
                    idx = self._current(snap)
                    img = self.renderer.render(self.pages[idx], snap, idx, len(self.pages))
                    self.display.show(rgb565(img))
                    log.debug("page %s: %d rects, %d bytes, %.0f ms", self.pages[idx]["id"],
                              self.display.last_rects, self.display.last_bytes, (time.time() - t0) * 1000)
                time.sleep(max(0.05, refresh - (time.time() - t0)))
        finally:
            self.sensors.stop()
            self.display.disconnect()
            try:
                os.remove(flag)          # orderly shutdown: nothing is left half-sent
            except OSError:
                pass
