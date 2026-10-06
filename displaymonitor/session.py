"""Session events: screen lock / unlock, sleep / resume, log-off / shutdown -> the display shows "Ciao".

SessionWatcher(callback).start() calls callback(event) from a helper thread, event being one of:
  "lock" | "unlock"   the session is locked / unlocked
  "sleep" | "resume"  the PC goes to sleep / wakes up
  "shutdown"          the session is ending (log-off, shutdown, restart). The callback should return only once the
                      "bye" frame has been sent: Windows ends the process right after the message is answered.

Windows: a hidden top-level window receives WM_WTSSESSION_CHANGE / WM_POWERBROADCAST / WM_ENDSESSION (pywin32).
Linux:   polls `loginctl` for the LockedHint of the current session; shutdown comes from SIGTERM (see __main__).
macOS:   polls Quartz' session dictionary when pyobjc-framework-Quartz is installed; shutdown comes from SIGTERM.
"""
import logging
import os
import subprocess
import sys
import threading
import time

log = logging.getLogger(__name__)

WM_WTSSESSION_CHANGE, WM_POWERBROADCAST, WM_QUERYENDSESSION, WM_ENDSESSION = 0x02B1, 0x0218, 0x0011, 0x0016
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 7, 8
PBT_APMSUSPEND, PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND = 4, 18, 7


def windows_event(msg: int, wparam: int) -> str | None:
    """Windows message -> event name (pure function, unit-tested)."""
    if msg == WM_WTSSESSION_CHANGE:
        return {WTS_SESSION_LOCK: "lock", WTS_SESSION_UNLOCK: "unlock"}.get(wparam)
    if msg == WM_POWERBROADCAST:
        return {PBT_APMSUSPEND: "sleep", PBT_APMRESUMEAUTOMATIC: "resume", PBT_APMRESUMESUSPEND: "resume"}.get(wparam)
    if msg == WM_ENDSESSION and wparam:
        return "shutdown"
    return None


class SessionWatcher:
    def __init__(self, callback):
        self.callback = callback
        self._stop = threading.Event()
        self._thread = None
        self._hwnd = None

    def start(self):
        target = self._run_windows if os.name == "nt" else (self._run_macos if sys.platform == "darwin" else self._run_linux)
        self._thread = threading.Thread(target=self._guard, args=(target,), name="session", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._hwnd:
            try:
                import win32con
                import win32gui
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                pass

    def _guard(self, target):
        try:
            target()
        except Exception:  # noqa: BLE001
            log.exception("session watcher stopped (lock / shutdown screen disabled)")

    def _emit(self, event: str):
        log.info("session event: %s", event)
        try:
            self.callback(event)
        except Exception:  # noqa: BLE001
            log.exception("session callback failed")

    # -- Windows --------------------------------------------------------------------------------
    def _run_windows(self):
        import win32api
        import win32con
        import win32gui
        import win32ts

        def wndproc(hwnd, msg, wparam, lparam):
            ev = windows_event(msg, wparam)
            if ev:
                self._emit(ev)
            if msg == WM_QUERYENDSESSION:
                return 1
            if msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "DisplayMonitorSession"
        wc.lpfnWndProc = wndproc
        atom = win32gui.RegisterClass(wc)
        self._hwnd = win32gui.CreateWindow(atom, "DisplayMonitor", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        win32ts.WTSRegisterSessionNotification(self._hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
        log.info("session watcher started (lock / sleep / shutdown)")
        win32gui.PumpMessages()
        try:
            win32ts.WTSUnRegisterSessionNotification(self._hwnd)
        except Exception:  # noqa: BLE001
            pass

    # -- Linux / macOS: polling -----------------------------------------------------------------
    def _poll(self, is_locked):
        locked = None
        while not self._stop.wait(2.0):
            now = is_locked()
            if now is None:
                continue
            if locked is not None and now != locked:
                self._emit("lock" if now else "unlock")
            locked = now

    def _run_linux(self):
        sid = os.environ.get("XDG_SESSION_ID")
        if not sid:                                  # e.g. a systemd user service: ask logind for the user's graphical session
            try:
                sid = subprocess.run(["loginctl", "show-user", str(os.getuid()), "-p", "Display", "--value"],
                                     capture_output=True, text=True, timeout=3).stdout.strip()
            except Exception:  # noqa: BLE001
                sid = ""
        if not sid:
            log.info("no login session found: lock detection disabled")
            return

        def is_locked():
            try:
                out = subprocess.run(["loginctl", "show-session", sid, "-p", "LockedHint", "--value"],
                                     capture_output=True, text=True, timeout=3).stdout.strip()
            except Exception:  # noqa: BLE001
                return None
            return {"yes": True, "no": False}.get(out)
        self._poll(is_locked)

    def _run_macos(self):
        try:
            import Quartz
        except ImportError:
            log.info("pyobjc-framework-Quartz not installed: lock detection disabled")
            return

        def is_locked():
            d = Quartz.CGSessionCopyCurrentDictionary()
            return bool(d and d.get("CGSSessionScreenIsLocked", 0))
        self._poll(is_locked)
