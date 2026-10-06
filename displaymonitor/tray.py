"""System-tray icon: pick a page (it stays until you go back to the recap), auto-rotation, brightness, quit."""
import logging

import pystray
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

TEXT = {
    "en": {"home": "Back to recap", "pages": "Show page", "rotate": "Automatic rotation",
           "brightness": "Brightness", "quit": "Quit"},
    "it": {"home": "Torna al riepilogo", "pages": "Mostra pagina", "rotate": "Rotazione automatica",
           "brightness": "Luminosità", "quit": "Esci"},
}


def _icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 12, 60, 52), radius=6, fill=(6, 10, 40), outline=(47, 208, 255), width=3)
    d.arc((16, 18, 48, 46), 200, 340, fill=(232, 40, 128), width=4)
    d.arc((16, 18, 48, 46), 20, 160, fill=(47, 208, 255), width=4)
    return img


def start_tray(app):
    tr = TEXT.get(app.cfg.get("language", "en"), TEXT["en"])

    def send(cmd):
        return lambda icon, item: app.commands.put(cmd)

    def page_item(i, p):
        return pystray.MenuItem(str(p["title"]).title(), send(f"page:{p['id']}"),
                                checked=lambda item, i=i: app.index == i, radio=True)

    menu = pystray.Menu(
        pystray.MenuItem(tr["home"], send("home"), default=True),
        pystray.MenuItem(tr["pages"], pystray.Menu(*[page_item(i, p) for i, p in enumerate(app.pages)])),
        pystray.MenuItem(tr["rotate"], send("rotate"), checked=lambda item: app.rotate),
        pystray.MenuItem(tr["brightness"], pystray.Menu(
            *[pystray.MenuItem(f"{v}", send(f"brightness:{v}")) for v in (60, 100, 150, 200, 255)])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(tr["quit"], lambda icon, item: (app.commands.put("quit"), icon.stop())),
    )
    icon = pystray.Icon("DisplayMonitor", _icon_image(), "DisplayMonitor", menu)
    icon.run_detached()
    log.info("tray icon started")
    return icon
