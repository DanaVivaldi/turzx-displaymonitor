"""Entry point.

  python -m displaymonitor                 run (display + rotation)
  python -m displaymonitor --preview       render every page to docs/preview/*.png (no display needed)
  python -m displaymonitor --dump-sensors  print the sensor snapshot
  python -m displaymonitor --debug         verbose log (rect / byte counts per frame)
"""
import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time

from . import __version__
from .app import ROOT, App, load_config


def setup_logging(debug: bool, console: bool):
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(os.path.join(ROOT, "logs", "displaymonitor.log"),
                                                      maxBytes=500_000, backupCount=3, encoding="utf-8")]
    if console and sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def single_instance():
    """Return a lock handle, or None if another instance is already running (Windows: a named mutex, elsewhere: a lock file)."""
    if os.name != "nt":
        import fcntl
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        f = open(os.path.join(ROOT, "logs", "instance.lock"), "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        return f                       # keep the handle alive for the whole run
    try:
        import win32api, win32event, winerror
        h = win32event.CreateMutex(None, False, "Global\\DisplayMonitorTURZX")
        return None if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS else h
    except ImportError:
        return True


def main():
    ap = argparse.ArgumentParser(prog="displaymonitor")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--demo", action="store_true", help="render every page with invented data to docs/img (no hardware needed)")
    ap.add_argument("--dump-sensors", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--rotate", type=float, help="override rotate_s (seconds per page)")
    ap.add_argument("--init", metavar="LANG", choices=["en", "it"], help="install a language pack (en | it) as your config/config.yaml + pages.yaml")
    ap.add_argument("--force", action="store_true", help="with --init: replace existing config files (a .bak copy is kept)")
    ap.add_argument("--lang", choices=["en", "it"], help="language pack for --demo (default: the example in English)")
    ap.add_argument("--version", action="store_true", help="print the version")
    ap.add_argument("--check-update", action="store_true", help="look for a newer version on GitHub and say so")
    ap.add_argument("--update", action="store_true", help="download and install the newest version (asks first; config/ and assets/ are never touched)")
    ap.add_argument("--yes", action="store_true", help="with --update: do not ask")
    ap.add_argument("--theme", metavar="NAME", help="use this theme preset (themes/NAME.yaml or config/themes/NAME.yaml)")
    ap.add_argument("--compact", action="store_true", help="force the compact layout (no top bar), handy with --demo/--preview")
    ap.add_argument("--send", metavar="CMD", help="send a command to the running instance: quit, home, pin, rotate, next, prev, page:<id>, brightness:<n>")
    a = ap.parse_args()
    if a.version:
        print(__version__)
        return
    if a.check_update or a.update:
        from . import updates
        cfg = load_config()[0].get("updates") or {}
        repo = cfg.get("repo", updates.DEFAULT_REPO)
        if a.update:
            return updates.run_update(repo, assume_yes=a.yes)
        info = updates.fetch_latest(repo)
        if not info:
            print("could not reach GitHub")
            return 1
        print(f"installed {__version__}, latest {info['version']} ({info['source']}): "
              + ("update available - run: python -m displaymonitor --update" if updates.is_newer(info["version"]) else "up to date"))
        return
    if a.init:
        from .app import init_language_pack
        try:
            for f in init_language_pack(a.init, a.force):
                print("written", f)
        except (FileExistsError, ValueError) as e:
            print("error:", e)
            return 1
        print(f"language pack '{a.init}' installed: edit config/config.yaml and config/pages.yaml; restart the program to apply.")
        return
    if a.send:
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        with open(os.path.join(ROOT, "logs", "control.cmd"), "a", encoding="utf-8") as f:
            f.write(a.send + "\n")
        print("sent:", a.send)
        return
    setup_logging(a.debug, console=a.preview or a.dump_sensors or a.debug)
    cfg, pages = load_config(examples=a.demo, lang=a.lang)
    if a.rotate is not None:
        cfg["rotate_s"] = a.rotate
    if a.theme:
        cfg.setdefault("theme", {})["preset"] = a.theme
    if a.compact:
        cfg.setdefault("layout", {})["header"] = False

    if a.demo:                                    # render with invented data: no hardware, no display, no admin needed
        from .demo import demo_snapshot
        app = App(cfg, pages)
        snap = demo_snapshot(cfg.get("language", "en"))
        out = os.path.join(ROOT, "docs", "img" if not a.lang else os.path.join("img", a.lang))
        os.makedirs(out, exist_ok=True)
        for i, p in enumerate(app.pages):
            app.renderer.render(p, snap, i, len(app.pages)).save(os.path.join(out, f"{i + 1:02d}_{p['id']}.png"))
        print("demo screenshots written to", out)
        return

    if a.preview or a.dump_sensors:
        app = App(cfg, pages)
        app.sensors.start()
        time.sleep(3.5)
        snap = app.sensors.snapshot()
        if a.dump_sensors:
            for k in sorted(snap):
                print(f"{k:<20} {snap[k]!r}"[:200])
        if a.preview:
            out = os.path.join(ROOT, "docs", "preview")
            os.makedirs(out, exist_ok=True)
            for i, p in enumerate(app.pages):
                app.renderer.render(p, snap, i, len(app.pages)).save(os.path.join(out, f"{i + 1:02d}_{p['id']}.png"))
            print("preview written to", out)
        app.sensors.stop()
        return

    log = logging.getLogger(__name__)
    mutex = single_instance()
    if mutex is None:
        log.error("another instance is already running")
        return
    import faulthandler                      # native crashes (pythonnet / .NET) leave a trace in logs/fault.txt
    fault = open(os.path.join(ROOT, "logs", "fault.txt"), "a")
    faulthandler.enable(file=fault, all_threads=True)
    sys.excepthook = lambda t, v, tb: log.critical("unhandled exception", exc_info=(t, v, tb))
    app = App(cfg, pages)

    def on_signal(signum, frame):                 # SIGTERM / Ctrl-C / log-off: show the "Ciao" screen, then exit cleanly
        app.commands.put("away:shutdown")
    for name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), on_signal)
            except (ValueError, OSError):
                pass
    icon = None
    code = 0
    log.info("DisplayMonitor %s started (admin=%s, pid=%s)", __version__, app.sensors.admin, os.getpid())
    try:
        if not a.no_tray and sys.platform == "darwin":     # macOS: the tray icon must own the main thread, the app runs beside it
            from .tray import build_tray
            icon = build_tray(app)
            worker = threading.Thread(target=lambda: (app.run(), icon.stop()), name="app")
            worker.start()
            icon.run()
            app.commands.put("quit")
            worker.join(15)
        else:
            if not a.no_tray:
                from .tray import start_tray
                icon = start_tray(app)
            app.run()
        log.info("DisplayMonitor stopped (orderly)")
    except BaseException:
        log.exception("DisplayMonitor crashed")
        code = 1
    finally:
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass
        logging.shutdown()
        os._exit(code)   # the tray thread is not a daemon: without this the process lingers after a quit


if __name__ == "__main__":
    sys.exit(main())
