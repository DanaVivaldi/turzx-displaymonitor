"""System-tray icon: pick a page (it stays until you go back to the recap), auto-rotation, brightness, quit."""
import logging
import os
import webbrowser

import pystray
from PIL import Image, ImageDraw

from .render import list_logos

log = logging.getLogger(__name__)

TEXT = {
    "en": {"home": "Back to recap", "pages": "Show page", "rotate": "Automatic rotation", "brightness": "Brightness",
           "logo_left": "Left logo", "logo_right": "Right logo", "none": "None", "reset": "Logos from config", "reload": "Reload configuration", "quit": "Quit",
           "unit": "Temperature unit", "web": "Web preview", "web_open": "Open the preview in the browser", "update": "Update available: v{v} (open)", "check": "Check for updates"},
    "it": {"home": "Torna al riepilogo", "pages": "Mostra pagina", "rotate": "Rotazione automatica", "brightness": "Luminosità",
           "logo_left": "Logo a sinistra", "logo_right": "Logo a destra", "none": "Nessuno", "reset": "Loghi da configurazione", "reload": "Ricarica configurazione", "quit": "Esci",
           "unit": "Unità di temperatura", "web": "Anteprima web", "web_open": "Apri l'anteprima nel browser", "update": "Aggiornamento disponibile: v{v} (apri)", "check": "Controlla aggiornamenti"},
}


def _icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 12, 60, 52), radius=6, fill=(6, 10, 40), outline=(47, 208, 255), width=3)
    d.arc((16, 18, 48, 46), 200, 340, fill=(232, 40, 128), width=4)
    d.arc((16, 18, 48, 46), 20, 160, fill=(47, 208, 255), width=4)
    return img


def build_tray(app):
    tr = TEXT.get(app.cfg.get("language", "en"), TEXT["en"])

    def send(cmd):
        return lambda icon, item: app.commands.put(cmd)

    def page_item(i, p):
        return pystray.MenuItem(str(p["title"]).title(), send(f"page:{p['id']}"),
                                checked=lambda item, i=i: app.index == i, radio=True)

    def logo_name(side):
        spec = (list(app.renderer.t["logos"]) + [None, None])[0 if side == "left" else 1]
        return os.path.splitext(os.path.basename(str(spec)))[0] if isinstance(spec, str) and spec else "none"

    def logo_menu(side):
        def items():                         # rebuilt every time the menu opens: new files in assets/logos show up at once
            yield pystray.MenuItem(tr["none"], send(f"logo:{side}:none"), checked=lambda item: logo_name(side) == "none", radio=True)
            for n in list_logos():
                yield pystray.MenuItem(n, send(f"logo:{side}:{n}"), checked=lambda item, n=n: logo_name(side) == n, radio=True)
        return pystray.Menu(items)

    menu = pystray.Menu(
        pystray.MenuItem(tr["home"], send("home"), default=True),
        pystray.MenuItem(tr["pages"], pystray.Menu(lambda: (page_item(i, p) for i, p in enumerate(app.pages)))),
        pystray.MenuItem(tr["rotate"], send("rotate"), checked=lambda item: app.rotate),
        pystray.MenuItem(tr["logo_left"], logo_menu("left")),
        pystray.MenuItem(tr["logo_right"], logo_menu("right")),
        pystray.MenuItem(tr["reset"], send("logo:reset")),
        pystray.MenuItem(tr["reload"], send("reload")),
        pystray.MenuItem(tr["unit"], pystray.Menu(
            pystray.MenuItem("°C", send("unit:c"), checked=lambda item: app.unit == "C", radio=True),
            pystray.MenuItem("°F", send("unit:f"), checked=lambda item: app.unit == "F", radio=True))),
        pystray.MenuItem(tr["web"], send("web:toggle"), checked=lambda item: app.web.running),
        pystray.MenuItem(tr["web_open"], lambda icon, item: webbrowser.open(app.web.url), visible=lambda item: app.web.running),
        pystray.MenuItem(lambda item: tr["update"].format(v=app.updates.available),
                         lambda icon, item: webbrowser.open((app.updates.latest or {}).get("url", "https://github.com")),
                         visible=lambda item: bool(app.updates.available)),
        pystray.MenuItem(tr["check"], send("update:check")),
        pystray.MenuItem(tr["brightness"], pystray.Menu(
            *[pystray.MenuItem(f"{v}%", send(f"brightness:{v}")) for v in (20, 40, 60, 80, 100)])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(tr["quit"], lambda icon, item: (app.commands.put("quit"), icon.stop())),
    )
    icon = pystray.Icon("DisplayMonitor", _icon_image(), "DisplayMonitor", menu)
    return icon


def start_tray(app):
    """Windows / Linux: the icon runs in its own thread. (macOS needs the main thread: see __main__, which uses build_tray + icon.run().)"""
    icon = build_tray(app)
    icon.run_detached()
    log.info("tray icon started")
    return icon
