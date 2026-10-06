"""Synthetic sensor snapshot: used to render screenshots / previews without touching any real hardware."""
import datetime
import math

from .sensors import DAYS, MONTHS


def demo_snapshot(lang: str = "en") -> dict:
    now = datetime.datetime.now()
    threads = [88, 12, 64, 9, 71, 22, 55, 4, 91, 17, 38, 6, 47, 12, 76, 8,
               33, 61, 24, 82, 15, 49, 28, 66]
    disks = [
        {"name": "NVMe SSD 1TB", "short": "NVMe SSD 1TB", "kind": "NVMe", "temp": 47, "used_pct": 62, "total_gb": 1000},
        {"name": "NVMe SSD 500GB", "short": "NVMe SSD 500GB", "kind": "NVMe", "temp": 44, "used_pct": 38, "total_gb": 500},
        {"name": "SATA SSD 1TB", "short": "SATA SSD 1TB", "kind": "SSD", "temp": 31, "used_pct": 81, "total_gb": 1000},
        {"name": "SATA SSD 500GB", "short": "SATA SSD 500GB", "kind": "SSD", "temp": 29, "used_pct": 24, "total_gb": 500},
        {"name": "HDD 2TB", "short": "HDD 2TB", "kind": "HDD", "temp": 36, "used_pct": 52, "total_gb": 2000},
        {"name": "HDD 4TB", "short": "HDD 4TB", "kind": "HDD", "temp": 38, "used_pct": 91, "total_gb": 4000},
    ]
    for d in disks:
        d["used_str"] = f" · {d['used_pct']:.0f}%"
    down = [120e3 + 90e3 * (1 + math.sin(i / 4)) + (i % 7) * 15e3 for i in range(60)]
    up = [20e3 + 12e3 * (1 + math.sin(i / 6)) for i in range(60)]
    s = {
        "time": now.strftime("%H:%M"), "time_s": now.strftime("%H:%M:%S"),
        "date": f"{DAYS[lang][now.weekday()]} {now.day:02d} {MONTHS[lang][now.month - 1]}",
        "clock_seconds": [100 if i <= now.second else 0 for i in range(60)],
        # CPU
        "cpu_name": "Example CPU", "cpu_load": 46.0, "cpu_threads": threads, "cpu_temp": 62.0, "cpu_temp_max": 66.0,
        "cpu_p_temp": 61.0, "cpu_e_temp": 57.0, "cpu_p_temps_str": "61 63 60 62 59 64 61 60",
        "cpu_e_temps_str": "56 57 58 55 57 56 58 57", "cpu_clock": 4.9, "cpu_clock_e": 3.8, "cpu_power": 78.0,
        # GPU
        "gpu_short": "RTX 4070", "gpu_load": 63.0, "gpu_temp": 66.0, "gpu_hotspot": 74.0, "gpu_power": 148.0,
        "gpu_vram_used": 7.4, "gpu_vram_total": 12.0, "gpu_vram_pct": 61.7, "gpu_clock": 2475.0, "gpu_mem_clock": 10500.0,
        "gpu_fan": 1450.0, "gpu_fan_pct": 48.0,
        # memory
        "mem_used": 21.3, "mem_total": 32.0, "mem_avail": 10.7, "mem_pct": 66.6,
        "vmem_used": 1.1, "vmem_total": 4.0, "vmem_pct": 27.5,
        # motherboard
        "mb_name": "Example Board", "mb_t1": 38.0, "mb_t2": 41.0, "mb_t4": 29.0, "mb_t6": 35.0, "mb_t_max": 41.0,
        "mb_fans": [{"name": "Fan #1", "rpm": 1180.0, "pct": 42.0}, {"name": "Fan #2", "rpm": 1320.0, "pct": 47.0},
                    {"name": "Fan #3", "rpm": 2650.0, "pct": 100.0}],
        "mb_fan_count": 3, "mb_fan_duties": [42.0, 47.0, 100.0, 60.0, 60.0, 35.0, 80.0],
        "mb_vcore": 1.142, "mb_v33": 3.31, "mb_v3sb": 3.4, "mb_vbat": 3.25, "mb_avcc": 3.4,
        # disks
        "disks": disks, "disk_count": len(disks), "disk_temps": [d["temp"] for d in disks], "disk_temp_max": 47.0,
        "disk_max_nvme": 47.0, "disk_max_ssd": 31.0, "disk_max_hdd": 38.0, "disk_read_mbs": 38.5, "disk_write_mbs": 12.2,
        # network
        "net_name": "Ethernet", "net_ip": "192.168.1.23", "net_speed": "2.5 Gbit", "ping_ms": 14.0,
        "net_down": down[-1], "net_up": up[-1], "net_down_hist": down, "net_up_hist": up,
        "net_down_val": "205", "net_down_unit": "KB/s", "net_down_str": "205 KB/s",
        "net_up_val": "32.0", "net_up_unit": "KB/s", "net_up_str": "32.0 KB/s", "net_down_pct": 62.0, "net_up_pct": 38.0,
        # system
        "weather_city": "My town", "weather_temp": 21.4, "weather_feels": 20.1, "weather_humidity": 58.0, "weather_wind": 12.0,
        "weather_code": 2, "weather_desc": "Partly cloudy", "weather_age_min": 7.0,
        "sys_uptime": 3 * 86400 + 5 * 3600, "uptime_str": "3d 05h" if lang == "en" else "3g 05h", "sys_procs": 214,
        "proc_cpu": [{"name": "game", "cpu": 21.4, "mem_mb": 5200}, {"name": "browser", "cpu": 6.8, "mem_mb": 3100},
                     {"name": "code", "cpu": 3.2, "mem_mb": 1200}, {"name": "chat", "cpu": 1.1, "mem_mb": 800}],
        "proc_mem": [{"name": "browser", "cpu": 6.8, "mem_gb": 6.2, "mem_pct": 19.4},
                     {"name": "game", "cpu": 21.4, "mem_gb": 5.1, "mem_pct": 15.9},
                     {"name": "code", "cpu": 3.2, "mem_gb": 1.9, "mem_pct": 5.9}],
    }
    return s
