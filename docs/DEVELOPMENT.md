# Development notes

## Layout

```
displaymonitor/
  __main__.py   CLI, logging, single‑instance mutex, orderly exit
  app.py        main loop: config, page selection / alerts / tray commands, frame → display, clean‑exit marker
  sensors.py    LibreHardwareMonitor (pythonnet) + psutil + ping, polled at different rates, flat snapshot dict
  render.py     page renderer (Pillow, 3× supersampling): ring, cards, legend, colour scheme
  display.py    USB display driver: port discovery, init, diff → rectangles → blocks, flood recovery
  tray.py       pystray menu
  demo.py       invented snapshot for screenshots
themes/         shipped theme presets (*.yaml) and their generated pictures (img/)
config/         *.example.yaml (shipped) and your own config.yaml / pages.yaml (git‑ignored)
scripts/        setup.ps1, install_autostart.ps1, uninstall_autostart.ps1
tools/          bench / diagnostic scripts, make_montage.py, make_backgrounds.py (themes/img), make_gallery.py (docs/img/themes.png)
docs/           CONFIGURATION.md, PROTOCOL.md, DEVELOPMENT.md, img/ (demo screenshots)
```

## Three layers

1. **Sensors** (`Sensors`): one daemon thread, groups polled at their own rate (fast 1 s: CPU/GPU/Super I/O + psutil; storage 10 s; processes 3 s; ping 5 s).
   `snapshot()` returns a plain dict; unavailable values are simply absent and render as `--`.
2. **Renderer** (`Renderer.render(page, snapshot, index, total) → PIL.Image 480×320`): the static background (glow, brackets, logos, the centre disc) is built once;
   everything dynamic is drawn at 3× and downsampled. Pages are data (`config/pages.yaml`); widgets are the `_ring`, `_legend` and `_card_*` methods.
3. **Display** (`Display.show(frame)`): rotates the landscape RGB565 frame to the portrait panel, diffs it against the previous frame in 2×2 px tiles,
   merges tiles into rectangles (horizontal gap ≤ 4 px, vertical runs with identical spans) and writes each rectangle in blocks of ≤ 12 800 px.
   The main loop never blocks on anything else: a frame costs 30–350 ms of transmission in steady state.

## Adding things

* **A theme**: a YAML file in `themes/` (shipped) or `config/themes/` (yours), keys documented in [THEMING.md](THEMING.md); `resolve_theme()` in `render.py` merges
  `DEFAULT_THEME` ← preset ← `config.yaml` `theme:`. Pictures: only ones you generated (see `tools/make_backgrounds.py`) or that are clearly free to redistribute.
* **A new value on screen**: add it to `sensors.py` (poll function → `_set({...})`) and to `demo.py`, then use `"{your_key}"` in a page.
* **A new page**: copy a page in `config/pages.yaml`; only `id` and `title` are mandatory. Add `alerts` if it should pop up by itself.
* **A new card kind**: add `_card_<kind>(self, d, card, y, h, snap)` to `render.py`; `kind: <kind>` in YAML picks it up automatically.
* **A different display revision**: implement the same `connect / show / disconnect / set_brightness` surface as `Display` and swap it in `App.__init__`.

## Pitfalls we hit (so you don't have to)

* **pythonnet 3.2.x** terminates the whole process when it cannot convert some .NET exceptions (`System.NullReferenceException` from LibreHardwareMonitor).
  Stay on `pythonnet==3.0.5`.
* **Never `Computer.Close()` while another thread is inside `hw.Update()`**: the resulting NRE is raised on a .NET thread and kills the process.
  `Sensors.stop()` joins the poll thread first.
* **LibreHardwareMonitor's memory module (`IsMemoryEnabled`)** polls the DIMM SPD hubs and crashed the interpreter on one machine. RAM figures come from psutil instead.
* **`pystray`'s detached thread is not a daemon**: without `os._exit()` at the end of `main()` the process lingers after a quit and the scheduled task
  refuses to start a new instance ("task already running").
* **Don't `Stop-ScheduledTask` and immediately `Start-ScheduledTask`**: the scheduler may still be tearing down the old job and kill the new instance. Use `--send quit`.
* **The vendor's brand logos are trademarks**: none are bundled; `theme.logos` is optional.
* **Killing the process mid‑bitmap blacks out the display** — see [PROTOCOL.md](PROTOCOL.md). The driver recovers by itself, but it costs ~13 s.

## Testing without hardware

`python -m displaymonitor --demo` renders every page from `demo.py` (no display, no admin, no sensors), `tools/make_montage.py` builds the README grid.
`--preview` does the same with your real sensors. There is no automated test suite yet; PRs adding one (renderer snapshot tests, diff/rectangle tests on `Display._diff`) are welcome.

## Release checklist

1. `python -m displaymonitor --demo && python tools/make_montage.py` and look at the pages;
2. clean exit + restart on a real display (`--send quit`, then start again);
3. `scripts\setup.ps1` on a clean checkout in a fresh folder.
