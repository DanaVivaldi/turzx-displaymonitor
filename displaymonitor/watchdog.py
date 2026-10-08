"""Watchdog: starts the program again when it died or froze.

`python -m displaymonitor --watchdog` is run every few minutes by the "DisplayMonitor Watchdog" scheduled task
(scripts/install_autostart.ps1). It looks at logs/running.flag (the program's pid), logs/heartbeat (touched every few
seconds by the main loop) and logs/quit.flag (written when YOU quit from the tray / `--send quit`, so a deliberate quit stays a quit):

    quit.flag present             -> nothing
    running and heartbeat fresh   -> nothing
    running but heartbeat stale   -> kill it, start it again   (frozen)
    pid gone, flag left behind    -> start it again            (crashed)
    never started / clean exit    -> start it again
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

import psutil

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "logs")
STALE_S = 90.0
TASK = "DisplayMonitor"


def _path(name: str) -> str:
    return os.path.join(LOGS, name)


def touch_heartbeat():
    try:
        with open(_path("heartbeat"), "w") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def _flag_pid() -> int | None:
    try:
        with open(_path("running.flag")) as f:
            return int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _is_ours(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        return p.is_running() and "python" in p.name().lower()
    except psutil.Error:
        return False


def decide(now: float | None = None) -> str:
    """'quit-requested' | 'ok' | 'frozen' | 'dead' | 'not-running' (pure: reads the three files)."""
    now = now or time.time()
    if os.path.exists(_path("quit.flag")):
        return "quit-requested"
    pid = _flag_pid()
    if pid is None:
        return "not-running"
    if not _is_ours(pid):
        return "dead"
    try:
        age = now - os.path.getmtime(_path("heartbeat"))
    except OSError:
        age = STALE_S + 1
        try:                                            # no heartbeat yet: judge by the pid file's age (a start-up grace period)
            age = now - os.path.getmtime(_path("running.flag"))
        except OSError:
            pass
    return "ok" if age < STALE_S else "frozen"


def start_program() -> bool:
    if os.name != "nt":
        return False                                    # systemd (Restart=on-failure) / launchd (KeepAlive) do this elsewhere
    r = subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True, text=True, timeout=30,
                       creationflags=0x08000000)
    return r.returncode == 0


def run_once() -> str:
    state = decide()
    if state in ("ok", "quit-requested"):
        return state
    if state == "frozen":
        pid = _flag_pid()
        try:
            p = psutil.Process(pid)
            for c in p.children(recursive=True):
                c.kill()
            p.kill()
            p.wait(5)
        except psutil.Error:
            pass
    ok = start_program()
    return f"{state}: " + ("started again" if ok else "could not start it")
