# Windows, Linux and macOS

DisplayMonitor runs on all three. The display driver, the renderer, the pages, the themes, the web preview, the night schedule,
the "Ciao" screen, the red background and the update check are the same code everywhere. Only two things are platform specific:
**where the sensor values come from** and **how session events (lock / sleep / shutdown) are detected**.

| | Windows 10/11 | Linux | macOS |
|---|---|---|---|
| Sensors | LibreHardwareMonitor (+ PawnIO driver) | psutil + kernel hwmon + `nvidia-smi` | psutil (+ optional tools) |
| CPU load / clock / threads | ✔ | ✔ | ✔ (clock: Intel Macs only) |
| CPU temperature | ✔ (PawnIO, admin) | ✔ (`coretemp` / `k10temp`) | optional: `osx-cpu-temp` on PATH |
| CPU power | ✔ | Intel RAPL (needs read access to `/sys/class/powercap`) | – |
| GPU | NVIDIA / AMD / Intel via LHM | NVIDIA via `nvidia-smi`, AMD via sysfs | name only |
| Motherboard temps / fans / voltages | ✔ | temps + fans from hwmon chips (nct67xx, it87 …) | – |
| Disks: temperature | ✔ | NVMe, and SATA with the `drivetemp` module | – |
| Disks: space, type, health | ✔ | space, type | space (the boot volume) |
| RAM temperature | ✔ (`sensors.ram_temp`) | `jc42` / `spd5118` hwmon chips | – |
| Network, ping, uptime, processes, weather | ✔ | ✔ | ✔ |
| Lock / unlock "Ciao" screen | ✔ (session notifications) | ✔ (`loginctl` LockedHint, polled) | ✔ with `pyobjc-framework-Quartz` |
| Sleep / resume | ✔ | – (SIGTERM only) | – (SIGTERM only) |
| Shutdown / log-off "Ciao" screen | ✔ (WM_ENDSESSION) | ✔ (SIGTERM, which systemd sends on logout / shutdown) | ✔ (SIGTERM) |
| Tray icon | ✔ | ✔ (needs a tray: GNOME needs the AppIndicator extension) | ✔ |
| Autostart | scheduled task | systemd user service | launchd agent |
| Installer for people without Python | `scripts/get.ps1` | `scripts/get.sh` | `scripts/get.sh` |

A value the machine cannot report is simply absent and the card shows `--`; nothing crashes. `python -m displaymonitor --dump-sensors`
prints exactly what was found.

> **Honest status.** Windows is the platform the program was built and tested on, with the real display. The Linux backend and
> the shell scripts were run on Debian (WSL: `scripts/setup.sh`, the whole test-suite, `--dump-sensors` with a real NVIDIA GPU through
> `nvidia-smi`); the test-suite also runs on Ubuntu and macOS in GitHub Actions on every push. The USB display itself and the
> macOS-specific code (tray on the main thread, Quartz lock detection) have **not** been tried on real Linux / macOS hardware —
> if something is off, open an issue with `logs/displaymonitor.log`.

## Linux

```bash
curl -fsSL https://raw.githubusercontent.com/DanaVivaldi/turzx-displaymonitor/main/scripts/get.sh | bash     # no git / Python needed
# or, from a clone:
bash scripts/setup.sh --lang en          # venv, dependencies, optional udev rule, language pack
.venv/bin/python -m displaymonitor       # try it
bash scripts/install_autostart.sh        # systemd user service (journalctl --user -u displaymonitor -f)
```

* **Permission to open the display.** `setup.sh` offers to install `scripts/linux/99-turzx.rules` (VID 1a86, PID 5722) so the logged-in user
  can use `/dev/ttyACM*` / `ttyUSB*`; otherwise add yourself to the `dialout` group and log in again.
* **Python**: 3.10–3.13, with `venv` (`sudo apt install python3 python3-venv python3-pip`).
* **Tray**: pystray uses the X11 / AppIndicator backend. On GNOME install the "AppIndicator and KStatusNotifierItem" extension, or run with
  `--no-tray` (everything else keeps working; use `--send` and the web preview to control it).
* **Temperatures**: `coretemp` / `k10temp` / `nct6798` and friends appear in `psutil.sensors_temperatures()` once the kernel module is loaded
  (`sudo sensors-detect` from `lm-sensors` loads them). For SATA drive temperatures load `drivetemp`. Intel RAPL power is root-only on recent kernels:
  `sudo chmod -R a+r /sys/class/powercap/intel-rapl*` (not persistent; ignore it if you do not care about the CPU power figure).
* **NVIDIA**: `nvidia-smi` must be on `PATH` (it ships with the driver). AMD GPUs are read from `/sys/class/drm`.
* **Ping**: the program uses the system `ping` when raw sockets are not allowed.

## macOS

```bash
curl -fsSL https://raw.githubusercontent.com/DanaVivaldi/turzx-displaymonitor/main/scripts/get.sh | bash
bash scripts/install_autostart.sh        # launchd agent (~/Library/LaunchAgents/com.displaymonitor.plist)
```

* Python 3.10–3.13 (`brew install python@3.12`). The tray icon owns the main thread; the program runs beside it.
* macOS does not expose CPU temperatures to ordinary programs. If you install a command-line tool such as `osx-cpu-temp` (Homebrew), it is used
  automatically. Apple Silicon needs root for `powermetrics`, which this program does not use.
* The first start may ask for permission to control the serial port / accept incoming connections (web preview); both are normal.

## What the two backends produce

Both fill the same snapshot keys (see [CONFIGURATION.md](CONFIGURATION.md#sensor-keys)): `cpu_*`, `gpu_*`, `mem_*`, `disks`, `mb_*`, `ram_temp*`, `net_*` ….
That is why the page files are identical on every platform. A page that shows a figure your platform cannot provide just shows `--`; pick the cards
you want in `config/pages.yaml`.
