# Ideas / roadmap

Gathered from looking at the other open projects for these displays (see `THIRD_PARTY_NOTICES.md`). Nothing here is promised; pull requests welcome.

| Idea | Seen in | Notes |
|---|---|---|
| **Software brightness fallback**: scale pixel values before sending | Rebscreen | rebscreen says Rev A units have no backlight command; on the tested V2 unit command 110 does dim the backlight, so this is only useful for firmwares where it does not |
| **Game FPS** (PresentMon) | TURZX-3.5-Custom-Monitor, Bezel | needs the PresentMon tool and admin rights |
| **Frozen single-file .exe** (the downloader scripts install a real Python instead) | Rebscreen, Rizplay, Bezel | PyInstaller + bundled LibreHardwareMonitor; code signing is the hard part |
| Per-drive read / write speed | TURZX-3.5-Custom-Monitor | LibreHardwareMonitor exposes read / write rates per drive; a page row layout is needed |
| Drag-and-drop theme editor | TelemetryForge, Bezel | big; the YAML pages + hot reload are the lightweight alternative |

## Done (kept here so the origin of the idea is not lost)

Night schedule (igam3-screen), lock / shutdown screen (igam3-screen, Bezel), local web preview (usb-lcd-dashboard, igam3-screen, Rizplay),
hot reload and the weather page, red background on heat / load (a full-screen alarm was tried and dropped: too slow to redraw), update check, Linux / macOS support, a no-Python installer (`scripts/get.ps1` / `get.sh`).
A frozen single-file `.exe` (PyInstaller) is still open: it needs code signing to avoid SmartScreen warnings, which is why the downloader scripts
install a real Python instead.

## Deliberately not planned (implementable if we ever change our mind)

These were considered and consciously left out: they are not interesting for the way this display is used, or they fight the ~165 KB/s link.
Nothing prevents building them later; the notes say where the work would go.

| Idea | Seen in | Why it is left out / how it could be done |
|---|---|---|
| **Now playing** page: title, artist, cover art from the Windows media session | Rebscreen, Rizplay, SpotifyStatusIPS | Not wanted. Doable with the `winrt-Windows.Media.Control` packages; the cover (a full frame is ≈ 1.8 s) would be sent once per track |
| **History / flight recorder / peaks and averages** over 1–24 h (a rolling CSV, an export command, "max since boot" figures) | TMOG's Flight Recorder | Not wanted. A small ring-buffer file written every few seconds from the sensor thread, read by a `--history` command |
| **Scrolling history graphs** (CPU / GPU / memory as lines instead of meters) | TMOG's "Traces" skin | Not wanted: continuous motion means continuous traffic. The network card already has a sparkline; the same card kind could take other keys |
| **Disk activity lights** (one blinking segment per drive) | TMOG's disk lights | A blink needs ~30 ms refreshes; the link and the 1 s refresh cannot show it properly |
| **Full-screen temperature alarm** with the component's details | — | Built and removed: redrawing the screen for an alarm is too slow here. Replaced by the red background tint (`alerts.tint`) |
| **Budgeted transmission scheduler** / "slow display" profile (priority queues, per-page refresh rates, partial frames) | — | A whole-screen change takes 1–2 s, which only happens at the tint's few steps. The cheap part exists: the self-healing band is skipped while a frame is busy (`display.band_budget`) |
| **Several panels / device profiles** (choose by serial, VID / PID; other protocols) | — | Only one model is tested. Port discovery and the Rev A protocol are isolated in `display.py`, so a second driver with the same `show()` surface would plug in |
