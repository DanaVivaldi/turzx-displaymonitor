# Theming: logos, colours, backgrounds, fonts, layout

Everything about the look lives in two places:

* **`theme:`** in `config/config.yaml` — colours, background picture, logos, fonts, translucency;
* **theme presets** — a preset is just a small YAML file with the same keys, so a look can be saved, shared and switched with one line.

![Shipped presets](img/themes.png)

*(the six shipped presets, rendered with invented data and the compact layout: `python tools/make_gallery.py`)*

## Quick start

1. Pick a shipped preset: in `config/config.yaml`

   ```yaml
   theme:
     preset: nebula        # default | nebula | grid | ember | sunset | aurora
   ```

   Restart the program (`python -m displaymonitor --send quit`, then start it again).
2. Try one without touching the config: `python -m displaymonitor --demo --theme ember` (writes PNGs to `docs/img/`, no display needed),
   or `python -m displaymonitor --preview --theme ember` with your real sensors (writes to `docs/preview/`).
3. Make your own: copy `themes/default.yaml` to `config/themes/mytheme.yaml`, change what you like, set `preset: mytheme`.
   Presets in `config/themes/` are yours (git‑ignored) and win over the shipped ones with the same name.

Keys written directly under `theme:` in `config.yaml` **override** the preset, so you can use a preset and still change one colour or add your logos:

```yaml
theme:
  preset: nebula
  logos: [assets/my_left_logo.png, assets/my_right_logo.png]
  cyan: "#ff66cc"
```

## Reference

Colours are `"#RRGGBB"`, `"#RGB"` or `[r, g, b]`. Every key is optional.

### Colours

| Key | Default | Used for |
|---|---|---|
| `bg` | `#060a28` | base colour; pictures are dimmed *towards* it; translucent backdrops use it |
| `panel` | `#0c184a` | card background |
| `edge` | `#0c549c` | card outline and the corner brackets |
| `track` | `#102460` | the empty part of bars and rings, inactive page dots |
| `cyan` | `#2fd0ff` | the accent: legend square, active page dot, default arcs and sparklines |
| `cyan_dark` | `#0e4678` | dim end of the default segment ramp |
| `blue`, `magenta`, `amber` | | extra colours some pages use by name (`color: magenta`) |
| `white` | `#f0f8ff` | main text |
| `dim` | `#7fa4d6` | secondary text (labels, titles) |
| `heat` | cyan, green, yellow, orange, red | the five level colours, low → high: ring arcs, the thread squares and the warm part of the text/bar scheme |
| `scale` | `[50, 60, 100]` | thresholds for temperatures and %: white below the 1st, green up to the 2nd, then yellow → orange → red at the 3rd |
| `glow`, `glow_color` | `true`, `#142878` | soft glow behind the ring (turn it off on pictures) |
| `disc` | violet → magenta | the three rings of the centre disc behind the big number, outside → inside |

> The *meaning* colours (green = fine, red = hot) live in `heat`. If you change them keep a clear low → high progression.

### Background picture

| Key | Default | Meaning |
|---|---|---|
| `background` | none | an image file, path relative to the project folder (or absolute): PNG / JPG / anything Pillow opens |
| `background_fit` | `cover` | `cover` fills the screen and crops what does not fit, `contain` keeps the whole picture with bars in `bg`, `stretch` distorts it |
| `background_focus` | `[0.5, 0.5]` | with `cover`: which part survives the crop (x, y in 0..1). `[0.5, 0.2]` keeps the upper part of a tall picture |
| `background_dim` | `0` | 0..1: pushes the picture towards `bg`. **Bright pictures need 0.4–0.6** or small text becomes unreadable |
| `background_blur` | `0` | blur radius in px: calms down busy pictures |
| `panel_opacity` | `1` | cards: 1 = solid, 0.6–0.8 lets the picture show through |
| `ring_backdrop` | `0` | 0..1: a dark translucent disc behind the ring |
| `text_shadow` | `false` | a soft dark shadow behind every text: the cheapest readability fix |

The screen is 480×320 (3:2). Any size works, but a **960×640** (or 1440×960) picture is sharp and small. Tall (portrait) pictures work with `cover`
+ `background_focus`; do not rotate them. Pictures are drawn once and only the changed pixels are sent to the display, so a photo costs nothing at run time
(only the first full draw, ~2 s, is slower).

A quick recipe for a photo that stays readable:

```yaml
# config/themes/holiday.yaml
background: assets/backgrounds/holiday.jpg
background_dim: 0.35
panel_opacity: 0.68
ring_backdrop: 0.45
text_shadow: true
glow: false
```

### Logos

```yaml
theme:
  logos: [assets/left.png, assets/right.png]    # either may be omitted: [assets/left.png]
layout:
  logo_h: 22                                    # height in px; width follows the picture's aspect ratio
```

PNG with transparency works best. With the compact layout (`layout.header: false`) the logos sit at the two lower corners of the ring;
with the top bar they sit in the top corners. **No logos are shipped** — brand logos are trademarks.

### Fonts

| Key | Default | Meaning |
|---|---|---|
| `font` | `C:\Windows\Fonts\bahnschrift.ttf` | any TrueType font file (absolute, or relative to the project folder). If it is missing the program falls back to Segoe UI, then Arial |
| `font_bold` | none | a bold file for the same family. Without it: Bahnschrift's real bold variation, or a thin stroke that fakes bold for other fonts |

Narrow, tabular‑figure fonts look best (numbers must not jump around). Sizes are set by the layout, so a much wider font may overflow the cards.

### Layout (in `config.yaml`, not in a preset)

| Key | Default | Meaning |
|---|---|---|
| `layout.header` | `true` | `true`: top bar with title, date/time and logos. `false`: compact layout, bigger ring and cards, logos at the ring's lower corners |
| `layout.clock` | `true` | compact layout only: big time + date at the top‑left of the ring |
| `layout.logo_h` | `22` | logo height |
| `layout.ring_scale` | `1.15` | compact layout only: ring size |

## Sharing a theme

A theme is one `.yaml` plus its picture(s). To share it, send the files, and say where the picture must be put (the `background:` path).
**Check the picture's licence first**: wallpapers, game art and anime illustrations are almost always copyrighted. The pictures shipped in
`themes/img/` were generated by `tools/make_backgrounds.py` and are part of this project's MIT licence; you can edit that script to make more.

If you open a pull request with a new preset, only include images you made or that are clearly free to redistribute, and say where they come from.

## Troubleshooting

| Problem | Fix |
|---|---|
| The picture does not show | the path is relative to the **project folder** (where `README.md` is), not to `config/`; check `logs/displaymonitor.log` for "cannot open background" |
| The preset is ignored | the name is the file name without `.yaml`; it must be in `config/themes/` or `themes/`; a warning "theme preset … not found" is logged otherwise |
| Text is hard to read on the picture | raise `background_dim`, lower `panel_opacity`, add `ring_backdrop`, set `text_shadow: true` |
| My `theme:` values seem to do nothing | keys in `config.yaml` override the preset; a typo in a key is silently ignored — compare with the reference above |
| Colours look different on the display | the panel is RGB565 (5‑6‑5 bits per channel) and IPS panels vary: expect small shifts, avoid very dark gradients (banding) |
