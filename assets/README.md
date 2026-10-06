# Assets

Nothing is shipped here: brand logos are trademarks and third-party pictures are copyrighted. Everything in this folder except this file is git-ignored.

* `logos/` — **the logo library**. Every picture here can be picked as the left / right logo (tray menu, `config.yaml`, `--send logo:...`).
  Add logos with `python tools/import_logo.py FILE --name NAME` (trims, removes a flat background, makes dark logos white).
* `backgrounds/` — anything you want to use as a `theme.background` picture (see `docs/THEMING.md`).

Full guide: [docs/THEMING.md](../docs/THEMING.md).
