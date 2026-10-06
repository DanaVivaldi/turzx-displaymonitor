# Ideas / roadmap

Gathered from looking at the other open projects for these displays (see `THIRD_PARTY_NOTICES.md`). Nothing here is promised; pull requests welcome.

| Idea | Seen in | Notes |
|---|---|---|
| **Now playing** page (title, artist, cover art from the Windows media session: Spotify, browsers…) | Rebscreen, Rizplay, SpotifyStatusIPS | needs the Windows media-control API (e.g. the `winrt-Windows.Media.Control` packages); cover art costs bandwidth (≈ 1.8 s for a full frame), draw it once per track |
| **Software brightness fallback**: scale pixel values before sending | Rebscreen | rebscreen says Rev A units have no backlight command; on the tested V2 unit command 110 does dim the backlight, so this is only useful for firmwares where it does not |
| **Game FPS** (PresentMon) | TURZX-3.5-Custom-Monitor, Bezel | needs the PresentMon tool and admin rights |
| **Frozen single-file .exe** (the downloader scripts install a real Python instead) | Rebscreen, Rizplay, Bezel | PyInstaller + bundled LibreHardwareMonitor; code signing is the hard part |
| Per-drive read / write speed | TURZX-3.5-Custom-Monitor | LibreHardwareMonitor exposes read / write rates per drive; a page row layout is needed |
| Drag-and-drop theme editor | TelemetryForge, Bezel | big; the YAML pages + hot reload are the lightweight alternative |

## Done (kept here so the origin of the idea is not lost)

Night schedule (igam3-screen), lock / shutdown screen (igam3-screen, Bezel), local web preview (usb-lcd-dashboard, igam3-screen, Rizplay),
hot reload and the weather page, dynamic temperature alarm, update check, Linux / macOS support, a no-Python installer (`scripts/get.ps1` / `get.sh`).
A frozen single-file `.exe` (PyInstaller) is still open: it needs code signing to avoid SmartScreen warnings, which is why the downloader scripts
install a real Python instead.
