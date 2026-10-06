"""Linux / macOS sensor backend (the Windows one is LibreHardwareMonitor in sensors.py).

psutil + the kernel's hwmon files + `nvidia-smi` (+ optional macOS tools). It produces the same snapshot keys as the
Windows backend; whatever a machine cannot report is simply absent and its cards show "--". Reading CPU power
(RAPL) and some temperatures may need extra permissions, see docs/PLATFORMS.md.
"""
from __future__ import annotations

import glob
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time

import psutil

log = logging.getLogger(__name__)
IS_MAC = sys.platform == "darwin"
SYS = "/sys"
# hwmon chips that are not "the motherboard": everything else with a temperature is shown as a motherboard probe
NOT_MB = {"coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "nvme", "amdgpu", "nouveau", "radeon", "jc42", "spd5118",
          "drivetemp", "iwlwifi", "iwlwifi_1", "pch_cannonlake", "pch_skylake", "BAT0", "ucsi_source_psy", "i915", "xe"}


def _run(cmd, timeout=5.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:  # noqa: BLE001
        return ""


def _read(path) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def _num(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


# -- pure parsers (unit-tested with fake data) ------------------------------------------------
def parse_nvidia_smi(text: str) -> dict:
    """Output of: nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed,
    clocks.gr,clocks.mem --format=csv,noheader,nounits   (first GPU)"""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    f = [x.strip() for x in line.split(",")]
    if len(f) < 9:
        return {}
    name, temp, load, used, total, power, fan, clk, mclk = f[:9]
    out = {"gpu_short": name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", ""), "gpu_temp": _num(temp), "gpu_load": _num(load),
           "gpu_power": _num(power), "gpu_fan_pct": _num(fan), "gpu_clock": _num(clk), "gpu_mem_clock": _num(mclk)}
    u, t = _num(used), _num(total)
    if u is not None and t:
        out.update(gpu_vram_used=u / 1024, gpu_vram_total=t / 1024, gpu_vram_pct=100 * u / t)
    return {k: v for k, v in out.items() if v is not None}


def parse_cpu_temps(chips: dict) -> dict:
    """psutil.sensors_temperatures() -> cpu_temp, cpu_temp_max, per-core average. Prefers coretemp (Intel) / k10temp (AMD)."""
    for chip in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal"):
        entries = chips.get(chip)
        if not entries:
            continue
        package, cores = None, []
        for e in entries:
            label = (e.label or "").lower()
            if label.startswith(("package", "tdie", "tctl", "cpu")) and (package is None or "tdie" in label):
                package = e.current
            elif label.startswith(("core", "tccd")):
                cores.append(e.current)
        out = {}
        if package is None and cores:
            package = max(cores)
        if package is None:
            package = entries[0].current
        out["cpu_temp"] = package
        if cores:
            out["cpu_temp_max"] = max(cores)
            out["cpu_p_temp"] = sum(cores) / len(cores)
            out["cpu_p_temps_str"] = " ".join(f"{c:.0f}" for c in cores)
        return out
    return {}


def parse_ram_temps(chips: dict) -> dict:
    temps = [e.current for chip in ("jc42", "spd5118") for e in chips.get(chip, []) if e.current is not None]
    if not temps:
        return {}
    return {"ram_temp": max(temps), "ram_temp_avg": sum(temps) / len(temps), "ram_temps_str": " ".join(f"{t:.0f}" for t in temps)}


def parse_mb(chips: dict, fans: dict, ignore=()) -> dict:
    """Motherboard probes (mb_t1..), mb_t_max, fans, from the chips that are not CPU / GPU / disk / RAM."""
    out, valid, i = {}, [], 0
    for chip, entries in chips.items():
        if chip in NOT_MB:
            continue
        for e in entries:
            i += 1
            ok = e.current is not None and 0 < e.current < 100 and str(i) not in {str(x) for x in ignore}
            out[f"mb_t{i}"] = e.current if ok else None
            if ok:
                valid.append(e.current)
    out["mb_t_max"] = max(valid) if valid else None
    flist = [{"name": e.label or chip, "rpm": e.current, "pct": None} for chip, es in fans.items() for e in es if e.current and e.current > 0]
    out["mb_fans"] = flist
    out["mb_fan_count"] = len(flist)
    return out


def physical_disk_of(device: str) -> str:
    """/dev/nvme0n1p2 -> nvme0n1 ; /dev/sda3 -> sda ; /dev/mmcblk0p1 -> mmcblk0"""
    name = os.path.basename(device)
    m = re.match(r"^(nvme\d+n\d+|mmcblk\d+)p\d+$", name)
    if m:
        return m.group(1)
    return re.sub(r"\d+$", "", name) if re.match(r"^(sd|hd|vd|xvd)[a-z]+\d+$", name) else name


class PosixProbe:
    """One instance per Sensors object; `fast()` every second, `disks()` every storage_s."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mb_ignore = (cfg.get("sensors") or {}).get("mb_ignore_temps", [])
        self._rapl = None
        self._nv = shutil.which("nvidia-smi")
        self._gpu_cache = (0.0, {})
        self._cpu_name = self._detect_cpu_name()
        self._mac_gpu = None
        self._osx_temp = shutil.which("osx-cpu-temp") if IS_MAC else None

    # -- static ---------------------------------------------------------------------------------
    @staticmethod
    def _detect_cpu_name() -> str:
        if IS_MAC:
            name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        else:
            m = re.search(r"model name\s*:\s*(.+)", _read("/proc/cpuinfo") or "")
            name = m.group(1).strip() if m else platform.processor()
        name = re.sub(r"\((R|TM)\)|CPU @ [\d.]+GHz|\d+th Gen |Processor|with Radeon.*", "", name)
        return " ".join(name.split()) or "CPU"

    def static(self) -> dict:
        if IS_MAC:
            name = _run(["sysctl", "-n", "hw.model"]).strip()
        else:
            parts = [_read(f"{SYS}/class/dmi/id/{n}") for n in ("board_vendor", "board_name")]
            name = " ".join(p for p in parts[1:] if p) or (parts[0] or "")
        return {"mb_name": name} if name else {}

    # -- fast group -----------------------------------------------------------------------------
    def fast(self) -> dict:
        out = {"cpu_name": self._cpu_name}
        out["cpu_load"] = psutil.cpu_percent(None)
        out["cpu_threads"] = psutil.cpu_percent(percpu=True, interval=None)
        try:
            f = psutil.cpu_freq()
            if f and f.current:
                out["cpu_clock"] = f.current / 1000
        except Exception:  # noqa: BLE001
            pass
        chips = {}
        try:
            chips = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        except Exception:  # noqa: BLE001
            pass
        out.update(parse_cpu_temps(chips))
        out.update(parse_ram_temps(chips))
        try:
            fans = psutil.sensors_fans() if hasattr(psutil, "sensors_fans") else {}
        except Exception:  # noqa: BLE001
            fans = {}
        out.update(parse_mb(chips, fans, self.mb_ignore))
        if "cpu_temp" not in out and self._osx_temp:
            m = re.search(r"([\d.]+)", _run([self._osx_temp]))
            if m and float(m.group(1)) > 0:
                out["cpu_temp"] = float(m.group(1))
        p = self._rapl_power()
        if p is not None:
            out["cpu_power"] = p
        out.update(self._gpu())
        return out

    def _rapl_power(self):
        path = f"{SYS}/class/powercap/intel-rapl:0/energy_uj"
        v = _num(_read(path))
        if v is None:
            return None
        now, prev = time.time(), self._rapl
        self._rapl = (now, v)
        if prev and now > prev[0] and v >= prev[1]:
            return (v - prev[1]) / 1e6 / (now - prev[0])
        return None

    def _gpu(self) -> dict:
        now = time.time()
        if now - self._gpu_cache[0] < 0.9:
            return self._gpu_cache[1]
        out = {}
        if self._nv:
            out = parse_nvidia_smi(_run([self._nv, "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,"
                                         "power.draw,fan.speed,clocks.gr,clocks.mem", "--format=csv,noheader,nounits"], 4))
        if not out:
            out = self._amd_gpu()
        if not out and IS_MAC:
            if self._mac_gpu is None:
                m = re.search(r"Chipset Model:\s*(.+)", _run(["system_profiler", "SPDisplaysDataType"], 15))
                self._mac_gpu = m.group(1).strip() if m else ""
            if self._mac_gpu:
                out = {"gpu_short": self._mac_gpu}
        self._gpu_cache = (now, out)
        return out

    @staticmethod
    def _amd_gpu() -> dict:
        for card in sorted(glob.glob(f"{SYS}/class/drm/card[0-9]/device")):
            if _read(f"{card}/vendor") != "0x1002":
                continue
            out = {"gpu_short": (_read(f"{card}/product_name") or "AMD GPU").replace("AMD Radeon ", "")}
            hw = next(iter(glob.glob(f"{card}/hwmon/hwmon*")), None)
            if hw:
                for key, f, div in (("gpu_temp", "temp1_input", 1000), ("gpu_hotspot", "temp2_input", 1000),
                                    ("gpu_fan", "fan1_input", 1), ("gpu_power", "power1_average", 1e6)):
                    v = _num(_read(f"{hw}/{f}"))
                    if v is not None:
                        out[key] = v / div
            v = _num(_read(f"{card}/gpu_busy_percent"))
            if v is not None:
                out["gpu_load"] = v
            used, total = _num(_read(f"{card}/mem_info_vram_used")), _num(_read(f"{card}/mem_info_vram_total"))
            if used is not None and total:
                out.update(gpu_vram_used=used / 2 ** 30, gpu_vram_total=total / 2 ** 30, gpu_vram_pct=100 * used / total)
            return out
        return {}

    # -- storage --------------------------------------------------------------------------------
    def disks(self) -> list[dict]:
        return self._disks_mac() if IS_MAC else self._disks_linux()

    def _usage_by_disk(self) -> dict:
        agg = {}
        for p in psutil.disk_partitions(all=False):
            if not p.device.startswith("/dev/") or p.fstype in ("squashfs", "tmpfs", "vfat", "efivarfs"):
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            a = agg.setdefault(physical_disk_of(p.device), [0, 0])
            a[0] += u.used
            a[1] += u.total
        return agg

    def _disks_linux(self) -> list[dict]:
        usage, out = self._usage_by_disk(), []
        for blk in sorted(glob.glob(f"{SYS}/block/*")):
            n = os.path.basename(blk)
            if re.match(r"^(loop|ram|zram|dm-|md|sr|fd|nbd)", n):
                continue
            model = (_read(f"{blk}/device/model") or n).strip()
            size = (_num(_read(f"{blk}/size")) or 0) * 512 / 1e9
            kind = "NVMe" if n.startswith("nvme") else ("HDD" if _read(f"{blk}/queue/rotational") == "1" else "SSD")
            d = {"name": model, "short": model.split()[-1] if n.startswith("nvme") and len(model) > 18 else model, "kind": kind,
                 "total_gb": size}
            t = next((_num(_read(p)) for p in glob.glob(f"{blk}/device/hwmon*/temp1_input") + glob.glob(f"{blk}/device/*/hwmon/hwmon*/temp1_input")
                      if _num(_read(p)) is not None), None)
            if t is not None:
                d["temp"] = t / 1000
            if n in usage and usage[n][1]:
                d["used_pct"] = 100 * usage[n][0] / usage[n][1]
            d["used_str"] = f" · {d['used_pct']:.0f}%" if d.get("used_pct") is not None else ""
            out.append(d)
        return out

    def _disks_mac(self) -> list[dict]:
        try:
            u = psutil.disk_usage("/")
        except OSError:
            return []
        label = _run(["diskutil", "info", "/"]).splitlines()
        m = next((re.search(r"Volume Name:\s*(.+)", ln) for ln in label if "Volume Name" in ln), None)
        name = m.group(1).strip() if m else "Macintosh HD"
        d = {"name": name, "short": name, "kind": "SSD", "total_gb": u.total / 1e9, "used_pct": u.percent}
        d["used_str"] = f" · {u.percent:.0f}%"
        return [d]
