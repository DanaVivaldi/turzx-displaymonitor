# Configuration reference

Two files, both optional copies of the shipped examples (created by `scripts\setup.ps1`, git‑ignored):

* `config/config.yaml` — general settings (display, refresh, thresholds, network, alerts). Example: [`config.example.yaml`](../config/config.example.yaml)
* `config/pages.yaml` — the pages. Example: [`pages.example.yaml`](../config/pages.example.yaml)

If your own file is missing the example is used. Changes take effect after a restart:
`python -m displaymonitor --send quit`, wait ~4 s, then start it again (scheduled task: `Start-ScheduledTask DisplayMonitor`).
`python -m displaymonitor --preview` / `--demo` renders PNGs so you can check a page without the display.

## config.yaml

| Key | Default | Meaning |
|---|---|---|
| `language` | `en` | `en` or `it`: tray menu (and the date names unless `date_language` is set) |
| `date_language` | = `language` | `en` or `it`: day / month names of the date (`Sat 03 Dec` / `sab 03 dic`); the time is always 24 h |
| `layout.header` | `false` | `true`: top bar with page title, date/time and the optional logos. `false` (default): **compact layout** — no top bar, a 15 % bigger ring, cards stretched over the full height (fonts and spacing scale with them), logos at the two lower corners of the ring |
| `layout.logo_h` | `22` | logo height in px |
| `layout.ring_scale` | `1.15` | compact layout only: ring size relative to the default |
| `display.rotate` | `1` | software rotation (`np.rot90` steps): `1` or `3` depending on mounting |
| `display.brightness` | `200` | raw firmware value 0–255 |
| `display.tile` / `merge_gap` | `2` / `4` | change‑detection tile and rectangle merging, in px |
| `display.max_block_px` | `12800` | maximum pixels per bitmap command |
| `display.refresh_band` | `8` | rows resent every frame, cycling (self‑healing); `0` = off |
| `display.flood_bytes` | `2200000` | recovery flood after an abnormal exit |
| `refresh_s` | `1.0` | seconds between frames |
| `home_page` | first page | id of the recap page, shown at every start |
| `stay_on_selected` | `true` | a page picked from the tray stays until *Back to recap* (else it returns after `peek_s`) |
| `rotate_s` | `0` | `0` = no automatic rotation, `N` = seconds per page (also toggled from the tray) |
| `layout.clock` | `true` | compact layout only: big time + date at the top-left of the ring |
| `theme.scale` | `[50, 60, 100]` | colour thresholds, see below |
| `theme.*` | | colours, **background picture**, logos, fonts, translucency, and `theme.preset` to load a saved look: everything is in **[THEMING.md](THEMING.md)** |
| `network.interface` | `auto` | adapter name, or `auto` (the busiest adapter that has an IPv4 address, virtual ones excluded) |
| `network.ping_host` | `1.1.1.1` | target of the ping shown on the network page |
| `sensors.*_s` | 1 / 10 / 3 / 5 | polling period of the fast sensors, storage, processes, ping |
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

## Sensor keys

Run `python -m displaymonitor --dump-sensors` to see the live values (and `--demo`'s `displaymonitor/demo.py` for the full list with types).

| Group | Keys |
|---|---|
| CPU | `cpu_name`, `cpu_load`, `cpu_threads` (list), `cpu_temp` (package), `cpu_temp_max`, `cpu_p_temp`, `cpu_e_temp`, `cpu_p_temps_str`, `cpu_e_temps_str`, `cpu_clock` (best P‑core, GHz), `cpu_clock_e`, `cpu_power` (W) |
| GPU | `gpu_short`, `gpu_load`, `gpu_temp`, `gpu_hotspot`, `gpu_power`, `gpu_clock`, `gpu_mem_clock`, `gpu_fan`, `gpu_fan_pct`, `gpu_vram_used` / `_total` (GB), `gpu_vram_pct` |
| Memory | `mem_used`, `mem_total`, `mem_avail` (GiB), `mem_pct`, `vmem_used`, `vmem_total`, `vmem_pct` (page file) |
| Motherboard | `mb_name`, `mb_t1`, `mb_t2`, `mb_t4`, … (raw Super I/O probes), `mb_t_max`, `mb_fans` (list of `{name, rpm, pct}`), `mb_fan_count`, `mb_fan_duties` (list), `mb_vcore`, `mb_v33`, `mb_v3sb`, `mb_vbat`, `mb_avcc` |
| Disks | `disks` (list of `{name, short, kind, temp, used_pct, used_str, total_gb}`), `disk_count`, `disk_temps` (list), `disk_temp_max`, `disk_max_nvme` / `_ssd` / `_hdd`, `disk_read_mbs`, `disk_write_mbs` |
| Network | `net_name`, `net_ip`, `net_speed`, `ping_ms`, `net_down`, `net_up` (B/s), `net_down_str`, `net_up_str`, `net_down_val`/`_unit`, `net_up_val`/`_unit`, `net_down_hist`, `net_up_hist` (lists), `net_down_pct`, `net_up_pct` |
| System | `time`, `time_s`, `date`, `clock_seconds` (list of 60), `sys_uptime` (s), `uptime_str`, `sys_procs`, `proc_cpu`, `proc_mem` (lists of `{name, cpu, mem_mb, mem_gb, mem_pct}`) |

Motherboard probes have no official names: compare `mb_t1…` with your BIOS and rename the card labels. Probes that are not connected read garbage
(e.g. 21 / 81 / 110 °C on the tested board): list their numbers in `sensors.mb_ignore_temps`.

## Command line

```
python -m displaymonitor                    run
python -m displaymonitor --send <cmd>       quit | home | next | prev | rotate | pin | page:<id> | brightness:<0-255>
python -m displaymonitor --preview          PNGs with real sensors  -> docs/preview/
python -m displaymonitor --demo             PNGs with invented data -> docs/img/
python -m displaymonitor --demo --theme ember --compact     try a theme preset / the compact layout
python -m displaymonitor --dump-sensors     print the sensor snapshot
python -m displaymonitor --debug            verbose log (rectangles / bytes / ms per frame)
python -m displaymonitor --no-tray          without the tray icon
python -m displaymonitor --rotate 5         override rotate_s
```
