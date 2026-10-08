"""Hardware sensors in a child process.

LibreHardwareMonitor talks to the GPU driver (NVML / NVAPI), the CPU and the Super I/O chip through native code. When one of
those misbehaves (an NVIDIA driver reset, for instance, which also crashed iCUE and Task Manager at the same moment) the process
dies with an access violation and nothing in Python can catch it. So the polling lives in a child process: if it dies or stops
answering, the program carries on (the hardware cards show "--" for a few seconds) and the child is started again.

    sensors:
      isolate: true      # default on Windows; false = LibreHardwareMonitor inside the main process (the old behaviour)
"""
from __future__ import annotations

import faulthandler
import logging
import multiprocessing as mp
import os
import threading
import time

import psutil

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STALL_S = 20.0           # no message for this long: the child is hung and gets replaced
BACKOFF = (5, 10, 20, 40, 60)


def hw_main(cfg: dict, conn):
    """Child process: open LibreHardwareMonitor, poll it, send the hardware part of the snapshot to the parent."""
    from .sensors import Sensors            # imported here: the child builds its own Sensors, without isolation
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    try:
        faulthandler.enable(open(os.path.join(ROOT, "logs", "hw_fault.txt"), "a"), all_threads=True)
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(filename=os.path.join(ROOT, "logs", "hw.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    child_cfg = {**cfg, "sensors": {**(cfg.get("sensors") or {}), "isolate": False}}
    s = Sensors(child_cfg)
    s._open_lhm()
    s._load_physical_disks()
    parent = os.getppid()
    nxt_fast = nxt_storage = nxt_alive = 0.0
    try:
        while True:
            now = time.time()
            dirty = False
            if now >= nxt_fast:
                nxt_fast, dirty = now + s.fast_s, True
                s._poll_fast(hw_only=True)
            if now >= nxt_storage:
                nxt_storage, dirty = now + s.storage_s, True
                s._poll_storage()
            if dirty:
                with s._lock:
                    conn.send(dict(s._state))
            if now >= nxt_alive:
                nxt_alive = now + 2.0
                if not psutil.pid_exists(parent):
                    break
            time.sleep(0.2)
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        os._exit(0)                          # never Close() LibreHardwareMonitor on the way out: that is what crashes


def selftest_worker(cfg: dict, conn):
    """Stand-in for hw_main used by the tests: a few messages, then the "driver reset" (the process dies abruptly)."""
    conn.send({"cpu_name": "fake", "cpu_temp": 41.0, "disks": [{"name": "d"}]})
    time.sleep(0.3)
    conn.send({"cpu_temp": 42.0})
    if (cfg.get("sensors") or {}).get("selftest") == "crash":
        os._exit(3)
    time.sleep(30)


class HardwareWorker:
    """Parent side: starts the child, receives its messages, clears the hardware values when it dies, restarts it."""

    def __init__(self, cfg: dict, on_data, on_clear, target=hw_main):
        self.cfg, self.on_data, self.on_clear, self.target = cfg, on_data, on_clear, target
        self.keys: set[str] = set()
        self._proc = None
        self._conn = None
        self._started = 0.0
        self._last = 0.0
        self._respawn_at = 0.0
        self._failures = 0
        self.restarts = 0

    def start(self):
        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        self._proc = ctx.Process(target=self.target, args=(self.cfg, child_conn), daemon=True, name="hardware")
        self._proc.start()
        child_conn.close()
        self._conn = parent_conn
        self._started = self._last = time.time()
        log.info("hardware sensors started in process %s", self._proc.pid)

    def stop(self):
        self._down(None, respawn=False)

    def _down(self, reason, respawn=True):
        proc, conn, self._proc, self._conn = self._proc, self._conn, None, None
        if proc is not None:
            if reason:
                log.warning("hardware sensor process %s: restarting in a moment", reason)
            try:
                if proc.is_alive():
                    proc.kill()
                proc.join(2)
            except Exception:  # noqa: BLE001
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        if self.keys:
            self.on_clear(self.keys)             # no stale temperatures on screen while the child is away
            self.keys = set()
        if respawn:
            now = time.time()
            self._failures = 0 if now - self._started > 120 else self._failures + 1
            self._respawn_at = now + BACKOFF[min(self._failures, len(BACKOFF) - 1)]
            self.restarts += 1

    def poll(self):
        """Called every 0.25 s from the sensor thread."""
        now = time.time()
        if self._conn is None:
            if self._respawn_at and now >= self._respawn_at:
                self._respawn_at = 0.0
                self.start()
            return
        try:
            while self._conn.poll(0):
                data = self._conn.recv()
                self.keys.update(data)
                self.on_data(data)
                self._last = now
        except (EOFError, OSError):
            pass
        if not self._proc.is_alive():
            self._down(f"exited (code {self._proc.exitcode})")
        elif now - self._last > STALL_S:
            self._down("stopped answering")
