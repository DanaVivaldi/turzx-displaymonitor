# Third‑party notices

DisplayMonitor's own code is MIT‑licensed (see `LICENSE`). It uses, but does **not** redistribute, the components below:
they are downloaded or installed by `scripts/setup.ps1` / `pip` on your machine under their own licences.

## Downloaded / installed at setup time

| Component | Use | Licence |
|---|---|---|
| [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) v0.9.6 | CPU / GPU / motherboard / disk sensors (`LibreHardwareMonitorLib.dll`, downloaded into `tools/lhm`, SHA‑256 verified) | MPL‑2.0 |
| [PawnIO](https://github.com/namazso/PawnIO) | signed kernel driver LibreHardwareMonitor uses for CPU MSR / Super I/O access (installed with `winget`, optional) | see its repository |

## Python packages (installed with pip, see `requirements.txt`)

pyserial (BSD‑3), Pillow (HPND), NumPy (BSD‑3), psutil (BSD‑3), PyYAML (MIT), pystray (LGPL‑3.0), ping3 (MIT), pywin32 (PSF‑2.0), pythonnet (MIT).

## Prior art this project learned from

No code was copied. The device protocol is a set of facts documented by the community; this project re‑implements it and adds its own measurements (`docs/PROTOCOL.md`).

| Project | Licence | What it taught us |
|---|---|---|
| [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) by Matthieu Houdebine | GPL‑3.0 | the "Rev A" command encoding, RGB565, the HELLO exchange, the existing LibreHardwareMonitor + PawnIO approach |
| [Tedd.TuringScreen](https://github.com/tedd/Tedd.TuringScreen) | MIT | software rotation, the 12 800‑pixel block limit, auto‑recovery |
| [TelemetryForge](https://github.com/riccione83/TelemetryForge) | MIT | initialisation sequence with HELLO / drain, chunked writes, partial updates |
| [TURZX-3.5-Custom-Monitor](https://github.com/xlwreally/TURZX-3.5-Custom-Monitor) | MIT | V2 firmware handling and 2 px differential tiles on Windows, scheduled‑task autostart |
| [turzx-metrics](https://github.com/ikaromm/turzx-metrics), [turzx-native-monitor](https://github.com/Sermilion/turzx-native-monitor) | GPL‑3.0 | confirmation of the device identification (`1A86:5722`, `USB35INCHIPSV2`) on Linux |

"TURZX", "Turing", "ASUS", "Intel" and "ROG" are trademarks of their respective owners; this project is not affiliated with or endorsed by any of them.
