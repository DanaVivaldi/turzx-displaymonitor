# Ideas / roadmap

Gathered from looking at the other open projects for these displays (see `THIRD_PARTY_NOTICES.md`). Nothing here is promised; pull requests welcome.

| Idea | Seen in | Notes |
|---|---|---|
| **Now playing** page (title, artist, cover art from the Windows media session: Spotify, browsers…) | Rebscreen, Rizplay, SpotifyStatusIPS | needs the Windows media-control API (e.g. the `winrt-Windows.Media.Control` packages); cover art costs bandwidth (≈ 1.8 s for a full frame), draw it once per track |
| **Night schedule**: dim or switch the screen off between two times | igam3-screen | `display.brightness` is a real 0–100 % backlight on the tested unit, so a schedule is just two values and two times |
| **Software brightness fallback**: scale pixel values before sending | Rebscreen | rebscreen says Rev A units have no backlight command; on the tested V2 unit command 110 does dim the backlight, so this is only useful for firmwares where it does not |
| **Shutdown / lock screen**: a "bye" frame or black screen when the PC shuts down or locks | igam3-screen, Bezel | needs a Windows session-change notification |
| **Local web preview** of what is on the screen (and remote control from a phone) | usb-lcd-dashboard, igam3-screen, Rizplay | opt-in, localhost / LAN only, password |
| **Game FPS** (PresentMon) | TURZX-3.5-Custom-Monitor, Bezel | needs the PresentMon tool and admin rights |
| **Installer / portable ZIP** for people without Python | Rebscreen, Rizplay, Bezel | PyInstaller + bundled LibreHardwareMonitor; code signing is the hard part |
| Per-drive read / write speed | TURZX-3.5-Custom-Monitor | LibreHardwareMonitor exposes read / write rates per drive; a page row layout is needed |
| Drag-and-drop theme editor | TelemetryForge, Bezel | big; the YAML pages + hot reload are the lightweight alternative |
