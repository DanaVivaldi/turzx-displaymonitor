# Configuration reference

Two files, both optional copies of the shipped examples (created by `scripts\setup.ps1`, git‑ignored):

* `config/config.yaml` — general settings (display, refresh, thresholds, network, alerts). Example: [`config.example.yaml`](../config/config.example.yaml)
* `config/pages.yaml` — the pages. Example: [`pages.example.yaml`](../config/pages.example.yaml)

## Language packs

Two ready-made, equivalent packs ship with the program:

| Pack | Files | Contents |
|---|---|---|
| English | `config.example.yaml`, `pages.example.yaml` | English page titles/labels, `language: en` |
| Italiano | `config.it.example.yaml`, `pages.it.example.yaml` | titoli, etichette, menu della tray e meteo in italiano, `language: it` |

```powershell
python -m displaymonitor --init it            # install the Italian pack as config/config.yaml + pages.yaml
python -m displaymonitor --init en --force    # switch to English (existing files are kept as *.bak)
python -m displaymonitor --demo --lang it     # render the Italian pack with invented data to docs/img/it
```

`--init` refuses to overwrite your files unless `--force` is given. `scripts\setup.ps1` runs it for you (`-Language en|it`).
Pack files are plain YAML: to add another language copy one, translate it and add the code to `LANGUAGES` in `displaymonitor/app.py`
(plus tray texts in `tray.py` and day/month/weather names in `sensors.py` / `weather.py`).

If your own file is missing the example is used. Changes take effect after a restart:
`python -m displaymonitor --send quit`, wait ~4 s, then start it again (scheduled task: `Start-ScheduledTask DisplayMonitor`).
`python -m displaymonitor --preview` / `--demo` renders PNGs so you can check a page without the display.

## config.yaml

| Key | Default | Meaning |
|---|---|---|
| `language` | `en` | `en` or `it`: tray menu (and the date names unless `date_language` is set) |
| `date_language` | = `language` | `en` or `it`: day / month names of the date (`Sat 03 Dec` / `sab 03 dic`); the time is always 24 h |
| `temperature_unit` | `celsius` | `celsius` or `fahrenheit`: every temperature on the display, the alarm screen and the legends (`°C` in a label becomes `°F`). Colour thresholds (`theme.scale`), alarm limits and the sensor keys always stay in °C. Also in the tray (*Temperature unit*, remembered in `config/state.yaml`) and `--send unit:f` / `unit:c` / `unit:toggle` / `unit:config` |
| `sensors.cpu_power_max` | `150` | watts of a full bar on the CPU page's *package power* card; it grows by itself if the CPU draws more (keys `cpu_power_peak`, `cpu_power_scale`) |
| `layout.header` | `false` | `true`: top bar with page title, date/time and the optional logos. `false` (default): **compact layout** — no top bar, a 15 % bigger ring, cards stretched over the full height (fonts and spacing scale with them), logos at the two lower corners of the ring |
| `layout.logo_h` | `22` | logo height in px |
| `layout.ring_scale` | `1.15` | compact layout only: ring size relative to the default |
| `display.rotate` | `1` | software rotation (`np.rot90` steps): `1` or `3` depending on mounting |
| `display.brightness` | `100` | backlight in **percent**, 0–100 (100 = brightest), applied at every start. (The firmware's own scale is inverted — 0 brightest, 255 darkest — the program converts.) Also tray *Brightness* and `--send brightness:60` |
| `display.tile` / `merge_gap` | `2` / `4` | change‑detection tile and rectangle merging, in px |
| `display.max_block_px` | `12800` | maximum pixels per bitmap command |
| `display.refresh_band` | `8` | rows resent every frame, cycling (self‑healing); `0` = off |
| `display.flood_bytes` | `2200000` | recovery flood after an abnormal exit |
| `refresh_s` | `1.0` | seconds between frames |
| `hot_reload` | `true` | re-read `config.yaml`, `pages.yaml` and theme presets when they change (checked every second) and apply them without restarting. Sensor settings (poll periods, network interface) still need a restart. A broken file keeps the previous configuration and is reported in the log. Also: tray *Reload configuration*, `--send reload` |
| `weather.*` | off | the optional weather page, see below |
| `home_page` | first page | id of the recap page, shown at every start |
| `stay_on_selected` | `true` | a page picked from the tray stays until *Back to recap* (else it returns after `peek_s`) |
| `rotate_s` | `0` | `0` = no automatic rotation, `N` = seconds per page (also toggled from the tray) |
| `layout.clock` | `true` | compact layout only: big time + date at the top-left of the ring |
| `theme.scale` | `[50, 60, 100]` | colour thresholds, see below |
| `config/state.yaml` | | written by the program: choices made from the tray that must survive a restart (the two logos). Delete it, or use *Logos from config*, to go back to `config.yaml` |
| `theme.*` | | colours, **background picture**, logos, fonts, translucency, and `theme.preset` to load a saved look: everything is in **[THEMING.md](THEMING.md)** |
| `network.interface` | `auto` | adapter name, or `auto` (the busiest adapter that has an IPv4 address, virtual ones excluded) |
| `network.ping_host` | `1.1.1.1` | target of the ping shown on the network page |
| `sensors.*_s` | 1 / 10 / 3 / 5 | polling period of the fast sensors, storage, processes, ping |
| `sensors.ram_temp` | `false` | read the RAM modules' temperatures from their SPD sensors (`ram_temp` = hottest module, `ram_temps_str`): needs PawnIO and DDR5 (or DDR4 with a thermal sensor); can clash with iCUE / Armoury Crate, so it is opt-in |
| `sensors.mb_ignore_temps` | `[]` | motherboard probe numbers to hide (unconnected probes read garbage) |
| `alerts` | see example | `{page, when, hold_s}`: when the Python expression is true the page is shown for `hold_s` seconds |

### Colour scheme

Every **temperature** (any key containing `temp`, `mb_t*`, `disk_max_*`, `gpu_hotspot`) and every **utilisation %** (keys ending in `_load` / `_pct`)
is coloured by `theme.scale = [white_below, green_until, red_at]`:

| Value | Colour |
|---|---|
| below `scale[0]` (50) | white (text) |
| up to `scale[1]` (60) | green |
| then | yellow → orange → red, reaching full red at `scale[2]` (100) |

Bars use the same scheme. Rings and the thread squares use a "level spectrum" (cyan → green → yellow → orange → red over 0–100 % of their range).

## pages.yaml

```yaml
pages:
  - id: overview            # used by home_page, alerts, --send page:<id>
    title: OVERVIEW         # shown at the top and in the tray
    logos: [geforce, gigabyte]   # optional: this page's own two logos (library names); otherwise theme.logos
    ring: { ... }           # the left part (optional)
    cards: [ ... ]          # up to three cards on the right
```

### Text and formats

Any text may contain `{key}` or `{key:format}` with a Python format spec — `"{cpu_temp:.0f}°C"`, `"{mem_used:.1f} / {mem_total:.0f} GB"`.
A missing / unavailable value renders as `--` instead of failing. A *spec* is either a plain string or a mapping:

```yaml
{text: "{gpu_temp:.0f}°C", value: gpu_temp, color: cyan, warn: 75, crit: 90}
```

`value` names the key used for colouring (temperatures and % are coloured automatically, see above); for other keys `warn` turns the text amber and `crit` magenta.
`color` is a theme colour name (`white`, `dim`, `cyan`, `blue`, `magenta`, `amber`) used when no rule applies.

### ring

| Key | Meaning |
|---|---|
| `segments` | key of a **list** of numbers: one square per element (e.g. `cpu_threads`, `disk_temps`, `mb_fan_duties`, `clock_seconds`) |
| `seg_max` | value that fills a square (default 100) |
| `seg_color` | `heat` = each square takes the level colour of its own value and brightens as the value grows. Without it: cyan with `seg_warn` / `seg_crit` thresholds |
| `seg_sat` | how quickly the default cyan saturates (fraction of `seg_max`) |
| `arcs` | list of thin rings `{value, min, max, color, radius, width}`; `color: heat` colours by level, otherwise a theme colour; `max` may be a key |
| `legend` | key at the top‑left: `{icon: square | dash, text}` rows |
| `center` | `label`, `big` (+`big_px`), `line1`, `line2`: specs shown in the middle |

The ring is centred at (118, 200) with radius 92 for the squares; arcs sit inside it (radius 61–90).

### cards

Cards are stacked from the top; `h` is the height in px (all heights + 8 px gaps must fit in 246 px).

| `kind` | Fields |
|---|---|
| `main` | `title`, `big`, `mid` (next to `big`), `right` (1–2 lines), `bar {value, min, max, color}` |
| `stats` | `title`, `items: [{label, text, value}]` (1–4 columns, auto‑shrunk), optional `footer: {left, right}` (a spec may have `marker: down|up` for the little arrows) |
| `list` | `title`, either `rows: [{label, text, value, bar}]` or `rows_from: <list key>` + `slice: [from, to]` + `row: {...}` evaluated per element (e.g. `disks`, `mb_fans`, `proc_cpu`, `proc_mem`), `row_h` |
| `spark` | `title`, `big`, `right`, `history: <list key>`, `color`, `floor` (a sparkline graph) |

`bar: {color: heat}` colours the bar with the same scheme as the text.

## Crash resilience (Windows)

LibreHardwareMonitor reads the GPU driver, the CPU and the Super I/O chip through native code. If a driver resets (an NVIDIA driver reset
crashed this program, iCUE and Task Manager at the same instant) the process dies with an access violation, which Python cannot catch.
So, by default, the hardware polling runs in a **child process** (`sensors.isolate: true`): if it dies or stops answering for 20 s the program
keeps drawing (the temperatures show `--`, never stale values), and the child is started again after 5-60 s. `--send debug:kill-hw` simulates the crash.

The **watchdog** covers the rest: `scripts\install_autostart.ps1` (elevated) also registers a task *DisplayMonitor Watchdog* that runs
`python -m displaymonitor --watchdog` every 5 minutes. It starts the program again if it crashed or froze (no heartbeat for 90 s), and does nothing after
a deliberate quit (tray *Quit*, `--send quit`), which leaves `logs/quit.flag` until the next start. Its decisions are logged in `logs/watchdog.log`;
a crashed child leaves `logs/hw_fault.txt`, the main program `logs/fault.txt`. A process that dies from a crash ends at once (no "stopped working" dialog),
which is also why the "Ciao" screen cannot appear in that case: it is drawn only on an orderly stop (lock, sleep, shutdown, SIGTERM).

## Night schedule, "Ciao" screen, temperature alarm, web preview, updates

All of these are in `config.yaml` and hot-reload.

```yaml
night:                  # dim the backlight (or switch the screen off) between two times
  enabled: false
  from: "23:00"
  to: "07:00"           # earlier than `from`: the window wraps over midnight
  mode: dim             # dim | off (off = black screen, backlight 0 %)
  brightness: 10        # % while dimmed
```

`display.brightness` stays what you chose (tray, `--send brightness:N`); the schedule overrides it only inside the window.

```yaml
away:                   # screen locked / PC sleeping / shutting down / signing out
  enabled: true
  text: "Ciao"          # the one big word, on the theme's own background and logos
  subtitle: true        # a small line under it ("screen locked", "sleeping", "shutting down")
```

On **shutdown or log-off** the program draws the screen, waits until it has been sent, and exits cleanly: the display keeps showing it.
On lock / sleep it returns to the pages by itself when you unlock. `--send away:lock` and `--send away:unlock` try it by hand.

```yaml
alerts:
  temperature:          # the full-screen alarm
    enabled: true
    threshold: 85       # °C: every component ...
    thresholds: {cpu: 90, gpu: 83, ram: 60, disk: 65, mb: 70}    # ... unless listed here
    hysteresis: 3       # ends once the part is 3 °C below its limit
    min_show_s: 15      # but never sooner than this
    rotate_s: 6         # several parts too hot: they alternate
    wake: true          # backlight to 100 % during the alarm, even in the night window
  pages: []             # the older "show this page when <condition>" rules: [{page: memory, when: "mem_pct >= 92", hold_s: 30}]
```

Components: `cpu` (package temperature, with load / power / clock / hottest core), `gpu` (core, with hot spot / load / power / fan / VRAM),
`ram` (modules, needs `sensors.ram_temp`), `disk` (the hottest drive: its name, type, space used, health) and `mb` (hottest motherboard probe).
The alarm screen uses the theme's background and shows the component, the device name, the temperature, how far over the limit it is, a gauge with the limit marked, and the details.
`alerts:` written as a plain list still works (page rules only, no alarm screen).

```yaml
web:                    # live preview in a browser, page buttons, brightness slider (tray: "Web preview" tick)
  enabled: false
  host: 127.0.0.1       # only this PC. For a phone: 0.0.0.0 AND a token
  port: 8765
  token: ""             # required when host is not local; open http://<pc>:8765/?t=<token>
```

The tray tick is remembered in `config/state.yaml` and wins over `web.enabled`. Only `home | next | prev | rotate | pin | reload | page:<id> | brightness:<n>`
are accepted from the page; requests with a foreign `Host` header are refused while it listens locally (DNS-rebinding guard).

```yaml
updates:                # one GET to GitHub at start-up and every interval_h hours: nothing is sent
  check: true
  interval_h: 24
  # repo: DanaVivaldi/turzx-displaymonitor
```

A newer version shows as *update vX.Y.Z* at the bottom-right of the screen and a tray item that opens the release page.
`python -m displaymonitor --check-update` says what is available; `--update` installs it (asks first; `git pull` in a clone, otherwise the repository
zip is unpacked over the program files — your `config/`, `assets/` and `logs/` are never touched).

## Sensor keys

Run `python -m displaymonitor --dump-sensors` to see the live values (and `--demo`'s `displaymonitor/demo.py` for the full list with types).

| Group | Keys |
|---|---|
| CPU | `cpu_name`, `cpu_load`, `cpu_threads` (list), `cpu_temp` (package), `cpu_temp_max`, `cpu_p_temp`, `cpu_e_temp`, `cpu_p_temps_str`, `cpu_e_temps_str`, `cpu_clock` (best P‑core, GHz), `cpu_clock_e`, `cpu_power` (W) |
| GPU | `gpu_short`, `gpu_load`, `gpu_temp`, `gpu_hotspot`, `gpu_power`, `gpu_clock`, `gpu_mem_clock`, `gpu_fan`, `gpu_fan_pct`, `gpu_vram_used` / `_total` (GB), `gpu_vram_pct` |
| Memory | `mem_used`, `mem_total`, `mem_avail` (GiB), `mem_pct`, `ram_temp` / `ram_temps_str` (opt-in), `vmem_used`, `vmem_total`, `vmem_pct` (page file) |
| Motherboard | `mb_name`, `mb_t1`, `mb_t2`, `mb_t4`, … (raw Super I/O probes), `mb_t_max`, `mb_fans` (list of `{name, rpm, pct}`), `mb_fan_count`, `mb_fan_duties` (list), `mb_vcore`, `mb_v33`, `mb_v3sb`, `mb_vbat`, `mb_avcc` |
| Disks | `disks` (list of `{name, short, kind, temp, used_pct, used_str, total_gb}`), `disk_count`, `disk_temps` (list), `disk_temp_max`, `disk_max_nvme` / `_ssd` / `_hdd`, `disk_read_mbs`, `disk_write_mbs` |
| Network | `net_name`, `net_ip`, `net_speed`, `ping_ms`, `net_down`, `net_up` (B/s), `net_down_str`, `net_up_str`, `net_down_val`/`_unit`, `net_up_val`/`_unit`, `net_down_hist`, `net_up_hist` (lists), `net_down_pct`, `net_up_pct` |
| System | `time`, `time_s`, `date`, `clock_seconds` (list of 60), `sys_uptime` (s), `uptime_str`, `sys_procs`, `proc_cpu`, `proc_mem` (lists of `{name, cpu, mem_mb, mem_gb, mem_pct}`) |

Motherboard probes have no official names: compare `mb_t1…` with your BIOS and rename the card labels. Probes that are not connected read garbage
(e.g. 21 / 81 / 110 °C on the tested board): list their numbers in `sensors.mb_ignore_temps`.

## Weather (optional)

```yaml
weather:
  enabled: true
  latitude: 43.7
  longitude: 13.2
  city: "My town"        # just a label: {weather_city}
  refresh_min: 30
```

A page with `requires: weather` (the example `weather` page) is hidden until this is enabled. The only network request is a GET to
`api.open-meteo.com` with your coordinates (no key, no account); it runs in a background thread, retries with exponential backoff (5 → 80 s) and the last
good reading is kept in `logs/weather.json`, so the screen never shows a stale value after a restart. Keys: `weather_temp`, `weather_feels`,
`weather_humidity`, `weather_wind` (km/h), `weather_code`, `weather_desc` (text in your `date_language`), `weather_city`, `weather_age_min`.
Any page can use `requires: weather` (or a list) to appear only when that feature is on.

## Command line

```
python -m displaymonitor                    run
python -m displaymonitor --send <cmd>       quit | home | next | prev | rotate | pin | reload | page:<id> | brightness:<0-100> | logo:left:<name> | logo:right:<name|none> | logo:reset | unit:c|f|toggle|config | web:on|off|toggle | away:lock|unlock|sleep|resume|shutdown | update:check
python -m displaymonitor --preview          PNGs with real sensors  -> docs/preview/
python -m displaymonitor --demo             PNGs with invented data -> docs/img/
python -m displaymonitor --demo --theme ember --compact     try a theme preset / the compact layout
python -m displaymonitor --dump-sensors     print the sensor snapshot
python -m displaymonitor --debug            verbose log (rectangles / bytes / ms per frame)
python -m displaymonitor --no-tray          without the tray icon
python -m displaymonitor --version | --check-update | --update [--yes]
python -m displaymonitor --rotate 5         override rotate_s
```
