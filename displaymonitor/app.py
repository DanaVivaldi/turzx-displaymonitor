"""Main loop: sensors -> page renderer -> display (only changed rectangles), page rotation, alerts, reconnect."""
import glob
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


LANGUAGES = ("en", "it")          # shipped language packs: config/config.<lang>.example.yaml + config/pages.<lang>.example.yaml


def example_path(name: str, lang: str | None = None) -> str:
    """config/pages.yaml -> config/pages.<lang>.example.yaml (the language pack) or, for English / unknown, config/pages.example.yaml."""
    stem = name[:-len(".yaml")]
    if lang and lang != "en":
        p = os.path.join(ROOT, "config", f"{stem}.{lang}.example.yaml")
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "config", f"{stem}.example.yaml")


def load_config(examples: bool = False, lang: str | None = None):
    """config/config.yaml and config/pages.yaml are your own (git-ignored) files; if they do not exist the
    shipped examples are used, so a fresh checkout works out of the box (examples=True forces them).
    `lang` picks the language pack ("en" or "it") when an example is used."""
    def read(name):
        mine = os.path.join(ROOT, "config", name)
        path = mine if os.path.exists(mine) and not examples else example_path(name, lang)
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return read("config.yaml"), read("pages.yaml")


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


class App:
    def __init__(self, cfg: dict, pages_cfg: dict):
        self.cfg = cfg
        self.pages = enabled_pages(pages_cfg, cfg)
        self.sensors = Sensors(cfg)
        self.display = Display(cfg.get("display", {}))
        self.renderer = Renderer(cfg.get("theme"), cfg.get("layout"))
        self.commands: "queue.Queue[str]" = queue.Queue()   # next | prev | home | pin | rotate | quit | page:<id> | brightness:<0-100>
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
            renderer = Renderer(cfg.get("theme"), cfg.get("layout"))
        except Exception as e:  # noqa: BLE001
            log.warning("config reload failed, keeping the previous configuration: %s", e)
            return
        current = self.pages[self.index]["id"] if self.pages else None
        self.cfg, self.pages, self.renderer = cfg, pages, renderer
        ids = [p["id"] for p in pages]
        self.home = ids.index(cfg.get("home_page", ids[0])) if cfg.get("home_page", ids[0]) in ids else 0
        self.index = ids.index(current) if current in ids else self.home
        self.stay_on_selected = bool(cfg.get("stay_on_selected", True))
        self.peek_s = float(cfg.get("peek_s", 30))
        self.rotate_s = float(cfg.get("rotate_s", 0)) or 12.0
        self._config_logos = tuple(renderer.t["logos"])
        self._load_state()
        self.display.configure(cfg.get("display", {}))
        log.info("configuration reloaded (%s): %d pages, theme preset %s", reason, len(pages), (cfg.get("theme") or {}).get("preset"))

    def _load_state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                logos = (yaml.safe_load(f) or {}).get("logos")
        except OSError:
            return
        if logos:
            self.renderer.set_logos(*(list(logos) + [None, None])[:2])

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                yaml.safe_dump({"logos": [x if isinstance(x, (str, dict)) else None for x in self.renderer.t["logos"]]}, f)
        except OSError as e:
            log.warning("cannot save %s: %s", self.state_file, e)

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
        elif cmd == "reload":
            self.reload_config("requested")
        elif cmd == "logo:reset":
            self.renderer.set_logos(*(list(self._config_logos) + [None, None])[:2])
            try:
                os.remove(self.state_file)
            except OSError:
                pass
        elif cmd.startswith("logo:"):
            _, side, name = cmd.split(":", 2)           # logo:left:amd | logo:right:none
            cur = list(self.renderer.t["logos"]) + [None, None]
            cur[0 if side == "left" else 1] = None if name == "none" else name
            self.renderer.set_logos(cur[0], cur[1])
            self._save_state()
        elif cmd.startswith("brightness:"):
            self.display.set_brightness(float(cmd[11:]))

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
                if self.cfg.get("hot_reload", True) and t0 - self._sig_checked >= 1.0:
                    self._sig_checked = t0
                    if config_signature() != self._sig:
                        self.reload_config()
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
