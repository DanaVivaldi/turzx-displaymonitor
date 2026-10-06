# Assets

Your own pictures. Everything in this folder except this file is git-ignored (never published).

* `logos/` — **your logo library**. A file here is a logo you can pick (tray menu, `config.yaml`, a page's `logos:`, `--send logo:...`); it **wins**
  over a shipped logo of the same name (the shipped library is `../logos/`, 25 public-domain brand logos, see `../logos/LOGOS.md`).
  Add logos with `python tools/import_logo.py FILE --name NAME` (trims, removes a flat background, makes dark logos white).
* `backgrounds/` — anything you want to use as a `theme.background` picture (see `docs/THEMING.md`).

Full guide: [docs/THEMING.md](../docs/THEMING.md). Mind the copyright of pictures you did not make.
