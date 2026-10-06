"""Sensor layer: LibreHardwareMonitor (pythonnet) + psutil + ping, polled at different rates.

Everything ends up in one flat dict (see Sensors.snapshot) so pages can reference plain keys
such as `cpu_temp` or `gpu_vram_used`. Missing / unavailable values are simply absent (None).
"""
import ctypes
import datetime
import json
import logging
import os
import socket
import subprocess
import threading
import time
from collections import deque

import psutil

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LHM_DLL = os.path.join(ROOT, "tools", "lhm", "LibreHardwareMonitorLib.dll")
FAST_KINDS = {"Cpu", "GpuNvidia", "GpuAmd", "GpuIntel", "SuperIO"}
DAYS = {"it": ["lun", "mar", "mer", "gio", "ven", "sab", "dom"],
        "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
MONTHS = {"it": ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"],
          "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
BAD_NICS = ("vmware", "virtual", "bluetooth", "loopback", "vethernet", "wsl", "isatap", "teredo", "*")


def _f(v):
    return None if v is None else float(v)


def rate_str(bps):
    """bytes/s -> (value string, unit)."""
    if bps is None:
        return None, None
    for unit, div in (("MB/s", 1e6), ("KB/s", 1e3)):
        if bps >= div:
            return (f"{bps / div:.1f}" if bps / div < 100 else f"{bps / div:.0f}"), unit
    return f"{bps:.0f}", "B/s"


def uptime_str(sec):
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}g {h:02d}h" if d else f"{h}h {m:02d}m"


class Sensors:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        s = cfg.get("sensors", {})
        self.fast_s, self.storage_s = s.get("fast_s", 1.0), s.get("storage_s", 10.0)
        self.procs_s, self.ping_s = s.get("procs_s", 3.0), s.get("ping_s", 5.0)
        self.ping_host = cfg.get("network", {}).get("ping_host", "1.1.1.1")
        self.mb_ignore = {str(i) for i in s.get("mb_ignore_temps", [])}
        lang = cfg.get("date_language") or cfg.get("language", "en")   # day / month names, e.g. "Sat 03 Dec" (en) or "sab 03 dic" (it)
        self.lang = lang if lang in DAYS else "en"
        self._lock = threading.Lock()
        self._state: dict = {}
        self._stop = threading.Event()
        self._thread = None
        self._hw = []
        self._pd = []                      # physical disk info from Windows (bus/media type)
        self._nic = None
        self._net_prev = None              # (t, recv, sent)
        self._io_prev = None               # (t, read, write)
        self._hist = {"net_down": deque(maxlen=60), "net_up": deque(maxlen=60)}
        self.admin = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False

    # -- lifecycle ------------------------------------------------------------------------------
    def start(self):
        if not self.admin:
            log.warning("not running as administrator: CPU / motherboard sensors will be missing")
        self._open_lhm()
        self._load_physical_disks()
        psutil.cpu_percent(None)
        for p in psutil.process_iter(["cpu_percent"]):  # prime per-process CPU counters
            pass
        self._poll_all(first=True)
        self._thread = threading.Thread(target=self._loop, name="sensors", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:      # never Close() LHM while the poll thread is inside Update(): that crashes the process
            self._thread.join(timeout=10)
        try:
            if self._computer is not None:
                self._computer.Close()
        except Exception:
            pass

    _computer = None

    def _open_lhm(self):
        try:
            import clr  # pythonnet
            clr.AddReference(LHM_DLL)
            from LibreHardwareMonitor import Hardware
            c = Hardware.Computer()
            # Memory stays off: LHM would poll the DIMMs' SPD hubs, and one failing Update() crashes pythonnet.
            c.IsCpuEnabled = c.IsGpuEnabled = True
            c.IsMotherboardEnabled = c.IsStorageEnabled = True
            c.Open()
            self._computer = c

            def walk(hw):
                yield hw
                for sub in hw.SubHardware:
                    yield from walk(sub)
            self._hw = [h for top in c.Hardware for h in walk(top)]
            for h in self._hw:
                if str(h.HardwareType) == "Motherboard":   # short board name for the labels, e.g. "ROG STRIX Z690-E"
                    name = " ".join(w for w in str(h.Name).split() if w.upper() not in ("ASUS", "GAMING", "WIFI", "WI-FI", "(WI-FI)"))
                    self._set({"mb_name": name or str(h.Name)})
            log.info("LibreHardwareMonitor: %s", ", ".join(f"{h.HardwareType}:{h.Name}" for h in self._hw))
        except Exception as e:  # noqa: BLE001
            log.error("LibreHardwareMonitor unavailable: %s", e)

    def _load_physical_disks(self):
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PhysicalDisk | Select FriendlyName,BusType,MediaType | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=20, creationflags=0x08000000).stdout
            data = json.loads(out)
            self._pd = data if isinstance(data, list) else [data]
        except Exception as e:  # noqa: BLE001
            log.warning("Get-PhysicalDisk failed: %s", e)

    # -- polling loop ---------------------------------------------------------------------------
    def _loop(self):
        nxt = {"fast": 0.0, "storage": 0.0, "procs": 0.0, "ping": 0.0}
        while not self._stop.wait(0.25):
            now = time.time()
            try:
                if now >= nxt["fast"]:
                    nxt["fast"] = now + self.fast_s
                    self._poll_fast()
                if now >= nxt["storage"]:
                    nxt["storage"] = now + self.storage_s
                    self._poll_storage()
                if now >= nxt["procs"]:
                    nxt["procs"] = now + self.procs_s
                    self._poll_procs()
                if now >= nxt["ping"]:
                    nxt["ping"] = now + self.ping_s
                    self._poll_ping()
            except Exception:  # noqa: BLE001
                log.exception("sensor poll failed")

    def _poll_all(self, first=False):
        for fn in (self._poll_fast, self._poll_storage, self._poll_procs, self._poll_ping):
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("initial poll failed: %s", fn.__name__)

    def _set(self, d: dict):
        with self._lock:
            self._state.update(d)

    # -- LibreHardwareMonitor groups ------------------------------------------------------------
    def _poll_fast(self):
        out = {}
        for hw in self._hw:
            kind = str(hw.HardwareType)
            if kind not in FAST_KINDS:
                continue
            try:
                log.debug("update %s %s", kind, hw.Name)
                hw.Update()
                rows = [(str(s.SensorType), str(s.Name), _f(s.Value)) for s in hw.Sensors]
                log.debug("updated %s (%d sensors)", kind, len(rows))
            except Exception:  # noqa: BLE001
                continue
            if kind == "Cpu":
                self._cpu(rows, str(hw.Name), out)
            elif kind.startswith("Gpu"):
                self._gpu(rows, str(hw.Name), out)
            elif kind == "Memory":
                self._memory(rows, str(hw.Name), out)
            elif kind == "SuperIO":
                self._superio(rows, out)
        out.update(self._poll_system())
        self._set(out)

    @staticmethod
    def _cpu(rows, name, out):
        th, pt, et, pc, ec = [], [], [], [], []
        for t, n, v in rows:
            if v is None:
                continue
            if t == "Load":
                if n == "CPU Total":
                    out["cpu_load"] = v
                elif n.startswith("CPU Core #"):
                    th.append(v)
            elif t == "Temperature" and "Distance" not in n:
                if n == "CPU Package":
                    out["cpu_temp"] = v
                elif n == "Core Max":
                    out["cpu_temp_max"] = v
                elif n.startswith("P-Core #"):
                    pt.append(v)
                elif n.startswith("E-Core #"):
                    et.append(v)
            elif t == "Clock":
                if n.startswith("P-Core #"):
                    pc.append(v)
                elif n.startswith("E-Core #"):
                    ec.append(v)
            elif t == "Power" and n == "CPU Package":
                out["cpu_power"] = v
        out["cpu_name"] = name.replace("12th Gen Intel(R) Core(TM) ", "").replace("12th Gen Intel Core ", "")
        out["cpu_threads"] = th
        if pt:
            out["cpu_p_temp"] = sum(pt) / len(pt)
            out["cpu_p_temps_str"] = " ".join(f"{x:.0f}" for x in pt)
        if et:
            out["cpu_e_temp"] = sum(et) / len(et)
            out["cpu_e_temps_str"] = " ".join(f"{x:.0f}" for x in et)
        if pc:
            out["cpu_clock"] = max(pc) / 1000
        if ec:
            out["cpu_clock_e"] = max(ec) / 1000

    @staticmethod
    def _gpu(rows, name, out):
        out["gpu_short"] = name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")
        for t, n, v in rows:
            if v is None:
                continue
            key = {("Temperature", "GPU Core"): "gpu_temp", ("Temperature", "GPU Hot Spot"): "gpu_hotspot",
                   ("Load", "GPU Core"): "gpu_load", ("Load", "GPU Memory"): "gpu_vram_pct",
                   ("Clock", "GPU Core"): "gpu_clock", ("Clock", "GPU Memory"): "gpu_mem_clock",
                   ("Power", "GPU Package"): "gpu_power", ("Fan", "GPU Fan 1"): "gpu_fan",
                   ("Control", "GPU Fan 1"): "gpu_fan_pct", ("Voltage", "GPU Core Voltage"): "gpu_volt",
                   ("SmallData", "GPU Memory Used"): "gpu_vram_used", ("SmallData", "GPU Memory Total"): "gpu_vram_total",
                   }.get((t, n))
            if key:
                out[key] = v / 1024 if key.startswith("gpu_vram_") and key != "gpu_vram_pct" else v

    @staticmethod
    def _memory(rows, name, out):
        pre = "vmem" if name.startswith("Virtual") else "mem"
        for t, n, v in rows:
            if v is None:
                continue
            if t == "Data" and n == "Memory Used":
                out[f"{pre}_used"] = v
            elif t == "Data" and n == "Memory Available":
                out[f"{pre}_avail"] = v
            elif t == "Load" and n == "Memory":
                out[f"{pre}_pct"] = v
        if f"{pre}_used" in out and f"{pre}_avail" in out:
            out[f"{pre}_total"] = out[f"{pre}_used"] + out[f"{pre}_avail"]

    def _superio(self, rows, out):
        temps, fans, duty, volts = {}, [], {}, {}
        for t, n, v in rows:
            if v is None:
                continue
            if t == "Temperature":
                temps[n] = v
            elif t == "Fan":
                fans.append((n, v))
            elif t == "Control":
                duty[n] = v
            elif t == "Voltage":
                volts[n] = v
        valid = []
        for n, v in temps.items():
            idx = n.replace("Temperature #", "")
            ok = 0 < v < 100 and idx not in self.mb_ignore   # unconnected probes read garbage (T5: 21 / 81 / 110)
            out[f"mb_t{idx}"] = v if ok else None
            if ok:
                valid.append(v)
        out["mb_t_max"] = max(valid) if valid else None
        out["mb_fans"] = [{"name": n, "rpm": v, "pct": duty.get(n)} for n, v in fans if v > 0]
        out["mb_fan_count"] = len(out["mb_fans"])
        out["mb_fan_duties"] = [duty[k] for k in sorted(duty)]
        out["mb_vcore"] = volts.get("Vcore")
        out["mb_v33"] = volts.get("+3.3V")
        out["mb_v3sb"] = volts.get("+3V Standby")
        out["mb_vbat"] = volts.get("CMOS Battery")
        out["mb_avcc"] = volts.get("AVCC")

    def _poll_storage(self):
        disks, used_pd = [], set()
        for hw in self._hw:
            if str(hw.HardwareType) != "Storage":
                continue
            try:
                log.debug("update Storage %s", hw.Name)
                hw.Update()
                rows = [(str(s.SensorType), str(s.Name), _f(s.Value)) for s in hw.Sensors]
                log.debug("updated Storage (%d sensors)", len(rows))
            except Exception:  # noqa: BLE001
                continue
            name = str(hw.Name).strip()
            d = {"name": name, "short": self._short(name), "kind": self._kind(name, used_pd)}
            for t, n, v in rows:
                if v is None:
                    continue
                if t == "Temperature" and n in ("Composite Temperature", "Temperature"):
                    d["temp"] = v
                elif t == "Load" and n == "Used Space":
                    d["used_pct"] = v
                elif t == "Data" and n == "Total Space":
                    d["total_gb"] = v
                elif t == "Level" and n == "Life":
                    d["life"] = v
            d["used_str"] = f" · {d['used_pct']:.0f}%" if d.get("used_pct") is not None else ""
            disks.append(d)
        temps = [d["temp"] for d in disks if d.get("temp") is not None]
        out = {"disks": disks, "disk_count": len(disks), "disk_temps": temps,
               "disk_temp_max": max(temps) if temps else None}
        for kind in ("NVMe", "SSD", "HDD"):
            vals = [d["temp"] for d in disks if d["kind"] == kind and d.get("temp") is not None]
            out[f"disk_max_{kind.lower()}"] = max(vals) if vals else None
        self._set(out)

    @staticmethod
    def _short(name):
        n = name.replace("Samsung SSD ", "").replace("Samsung ", "")
        return n.split("-")[0] if n.startswith("ST") else n

    def _kind(self, name, used):
        for i, pd in enumerate(self._pd):
            if i in used or str(pd.get("FriendlyName", "")).strip() != name:
                continue
            used.add(i)
            if str(pd.get("BusType")) == "17" or str(pd.get("BusType")).lower() == "nvme":
                return "NVMe"
            return "HDD" if str(pd.get("MediaType")).lower() in ("hdd", "3") else "SSD"
        return "HDD" if name.startswith(("ST", "WD", "HGST")) else "SSD"

    # -- psutil groups --------------------------------------------------------------------------
    def _pick_nic(self):
        want = self.cfg.get("network", {}).get("interface", "auto")
        stats, addrs, io = psutil.net_if_stats(), psutil.net_if_addrs(), psutil.net_io_counters(pernic=True)
        if want != "auto" and want in stats:
            return want
        best, best_b = None, -1
        for n, s in stats.items():
            if not s.isup or any(b in n.lower() for b in BAD_NICS) or n not in io:
                continue
            if not any(a.family == socket.AF_INET and not a.address.startswith(("169.254", "127."))
                       for a in addrs.get(n, [])):
                continue
            b = io[n].bytes_recv + io[n].bytes_sent
            if b > best_b:
                best, best_b = n, b
        return best

    def _poll_system(self):
        out, now = {}, time.time()
        if self._nic is None or int(now) % 30 == 0:
            nic = self._pick_nic()
            if nic != self._nic:
                self._nic, self._net_prev = nic, None
        if self._nic:
            c = psutil.net_io_counters(pernic=True).get(self._nic)
            if c and self._net_prev:
                dt = max(now - self._net_prev[0], 1e-3)
                down = max(0.0, (c.bytes_recv - self._net_prev[1]) / dt)
                up = max(0.0, (c.bytes_sent - self._net_prev[2]) / dt)
                self._hist["net_down"].append(down)
                self._hist["net_up"].append(up)
                out.update(net_down=down, net_up=up)
                out["net_down_val"], out["net_down_unit"] = rate_str(down)
                out["net_up_val"], out["net_up_unit"] = rate_str(up)
                out["net_down_str"] = "{} {}".format(*rate_str(down))
                out["net_up_str"] = "{} {}".format(*rate_str(up))
                for k in ("down", "up"):
                    h = self._hist[f"net_{k}"]
                    scale = max(max(h), 1e6) if h else 1e6
                    out[f"net_{k}_pct"] = 100 * out[f"net_{k}"] / scale
            if c:
                self._net_prev = (now, c.bytes_recv, c.bytes_sent)
            out["net_name"] = self._nic
            st = psutil.net_if_stats().get(self._nic)
            out["net_speed"] = f"{st.speed / 1000:g} Gbit" if st and st.speed >= 1000 else (f"{st.speed} Mbit" if st else None)
            out["net_ip"] = next((a.address for a in psutil.net_if_addrs().get(self._nic, [])
                                  if a.family == socket.AF_INET), None)
        out["net_down_hist"] = list(self._hist["net_down"])
        out["net_up_hist"] = list(self._hist["net_up"])
        io = psutil.disk_io_counters()
        if io and self._io_prev:
            dt = max(now - self._io_prev[0], 1e-3)
            out["disk_read_mbs"] = max(0.0, (io.read_bytes - self._io_prev[1]) / dt / 1e6)
            out["disk_write_mbs"] = max(0.0, (io.write_bytes - self._io_prev[2]) / dt / 1e6)
        if io:
            self._io_prev = (now, io.read_bytes, io.write_bytes)
        vm, sw, gib = psutil.virtual_memory(), psutil.swap_memory(), 1024 ** 3
        out.update(mem_total=vm.total / gib, mem_used=(vm.total - vm.available) / gib, mem_avail=vm.available / gib,
                   mem_pct=100 * (vm.total - vm.available) / vm.total,
                   vmem_total=sw.total / gib, vmem_used=sw.used / gib, vmem_pct=sw.percent)
        out["sys_uptime"] = now - psutil.boot_time()
        out["uptime_str"] = uptime_str(out["sys_uptime"])
        return out

    def _poll_procs(self):
        ncpu = psutil.cpu_count() or 1
        agg = {}
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            i = p.info
            name = (i.get("name") or "?")
            if name in ("System Idle Process", "Memory Compression"):
                continue
            a = agg.setdefault(name[:-4] if name.lower().endswith(".exe") else name, [0.0, 0])
            a[0] += (i.get("cpu_percent") or 0.0) / ncpu
            a[1] += i["memory_info"].rss if i.get("memory_info") else 0
        top_cpu = sorted(agg.items(), key=lambda kv: -kv[1][0])[:5]
        top_mem = sorted(agg.items(), key=lambda kv: -kv[1][1])[:5]
        self._set({
            "proc_cpu": [{"name": n[:18], "cpu": v[0], "mem_mb": v[1] / 1e6} for n, v in top_cpu],
            "proc_mem": [{"name": n[:18], "cpu": v[0], "mem_mb": v[1] / 1e6,
                          "mem_gb": v[1] / 1e9, "mem_pct": 100 * v[1] / psutil.virtual_memory().total}
                         for n, v in top_mem],
            "sys_procs": len(agg),
        })

    def _poll_ping(self):
        try:
            import ping3
            ms = ping3.ping(self.ping_host, timeout=1, unit="ms")
            self._set({"ping_ms": float(ms) if ms else None})
        except Exception:  # noqa: BLE001
            self._set({"ping_ms": None})

    # -- public ---------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            s = dict(self._state)
        now = datetime.datetime.now()
        s["time"] = now.strftime("%H:%M")
        s["time_s"] = now.strftime("%H:%M:%S")
        s["date"] = f"{DAYS[self.lang][now.weekday()]} {now.day:02d} {MONTHS[self.lang][now.month - 1]}"
        s["clock_seconds"] = [100 if i <= now.second else 0 for i in range(60)]
        return s
