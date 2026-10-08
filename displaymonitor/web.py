"""Local web preview: what is on the display, in a browser, with page buttons and a brightness slider.

Off by default; switched on with `web: {enabled: true}` or the tray's "Web preview" tick. It listens on 127.0.0.1 only,
unless you set `host` to another address, which then REQUIRES a `token` (pass it as ?t=TOKEN in the URL):

    web:
      enabled: false
      host: 127.0.0.1
      port: 8765
      token: ""
"""
import hmac
import http.server
import io
import json
import logging
import re
import threading
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)
LOOPBACK = ("127.0.0.1", "localhost", "::1")
COMMAND = re.compile(r"^(home|next|prev|rotate|pin|reload|page:[A-Za-z0-9_-]{1,40}|brightness:\d{1,3})$")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DisplayMonitor</title><style>
:root{color-scheme:dark;--bg:#060a28;--panel:#0c184a;--edge:#0c549c;--cyan:#2fd0ff;--text:#f0f8ff;--dim:#7fa4d6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,sans-serif;min-height:100vh;
display:flex;flex-direction:column;align-items:center;gap:16px;padding:20px 16px}
h1{margin:0;font-size:15px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.screen{width:min(100%,720px);aspect-ratio:3/2;background:#000;border:2px solid var(--edge);border-radius:10px;overflow:hidden}
.screen img{width:100%;height:100%;display:block;image-rendering:auto}
.row{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;width:min(100%,720px)}
button{background:var(--panel);color:var(--text);border:1px solid var(--edge);border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer}
button:hover,button.on{border-color:var(--cyan);color:var(--cyan)}
label{display:flex;align-items:center;gap:10px;color:var(--dim)}input[type=range]{width:min(60vw,320px);accent-color:var(--cyan)}
small{color:var(--dim)}
</style></head><body><h1>DisplayMonitor</h1><div class="screen"><img id="f" alt="display"></div>
<div class="row" id="pages"></div><div class="row"><button data-c="home">Home</button><button data-c="prev">&#9664;</button><button data-c="next">&#9654;</button>
<button data-c="rotate">Auto-rotate</button></div>
<label>Brightness <input id="b" type="range" min="0" max="100" step="5"><span id="bv"></span></label><small id="s"></small>
<script>
const t=new URLSearchParams(location.search).get('t'),q=t?'t='+encodeURIComponent(t):'';
const u=(p,e='')=>p+'?'+[q,e].filter(Boolean).join('&');
const img=document.getElementById('f');let busy=false;
async function frame(){if(busy)return;busy=true;try{const r=await fetch(u('/frame.png','_='+Date.now()),{cache:'no-store'});
if(r.ok){const o=URL.createObjectURL(await r.blob());const old=img.src;img.src=o;if(old.startsWith('blob:'))URL.revokeObjectURL(old);}}catch(e){}busy=false}
async function cmd(c){await fetch(u('/cmd'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c})});setTimeout(state,300)}
async function state(){try{const s=await (await fetch(u('/state.json'),{cache:'no-store'})).json();
const p=document.getElementById('pages');p.innerHTML='';s.pages.forEach((g,i)=>{const b=document.createElement('button');b.textContent=g.title;
if(i===s.index)b.className='on';b.onclick=()=>cmd('page:'+g.id);p.appendChild(b)});
const r=document.getElementById('b');if(document.activeElement!==r)r.value=s.brightness;document.getElementById('bv').textContent=s.brightness+' %';
document.getElementById('s').textContent='v'+s.version+(s.update?' - update '+s.update+' available':'')+(s.diag?' - '+s.diag:'')}catch(e){}}
document.querySelectorAll('button[data-c]').forEach(b=>b.onclick=()=>cmd(b.dataset.c));
document.getElementById('b').onchange=e=>cmd('brightness:'+e.target.value);
setInterval(frame,1000);setInterval(state,5000);frame();state();
</script></body></html>"""


class WebPreview:
    def __init__(self, app):
        self.app = app
        self._srv = None
        self._thread = None
        self._png = (None, b"")            # (frame sequence, PNG bytes)
        self._lock = threading.Lock()
        self.token = ""
        self.loopback = True

    @property
    def running(self) -> bool:
        return self._srv is not None

    @property
    def port(self):
        return self._srv.server_address[1] if self._srv else None

    @property
    def url(self):
        if not self._srv:
            return None
        host = "localhost" if self.loopback else self._srv.server_address[0]
        return f"http://{host}:{self.port}/" + (f"?t={self.token}" if self.token else "")

    def start(self, cfg: dict | None = None) -> bool:
        if self._srv:
            return True
        c = cfg or {}
        host, port, self.token = str(c.get("host", "127.0.0.1")), int(c.get("port", 8765)), str(c.get("token") or "")
        self.loopback = host in LOOPBACK
        if not self.loopback and not self.token:
            log.error("web preview: host %s is not local, so a token is required (web.token); not started", host)
            return False
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = "DisplayMonitor"

            def log_message(self, *a):         # keep the log file quiet
                pass

            def _ok(self) -> bool:
                if outer.loopback:             # DNS-rebinding guard: only the local names may be used
                    if self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]") not in LOOPBACK:
                        self.send_error(403)
                        return False
                if outer.token:
                    given = (parse_qs(urlparse(self.path).query).get("t") or [self.headers.get("X-Token", "")])[0]
                    if not hmac.compare_digest(given.encode(), outer.token.encode()):
                        self.send_error(401)
                        return False
                return True

            def _send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._ok():
                    return
                path = urlparse(self.path).path
                if path == "/":
                    self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                elif path == "/frame.png":
                    png = outer.frame_png()
                    self._send(200, png, "image/png") if png else self.send_error(503)
                elif path == "/state.json":
                    self._send(200, json.dumps(outer.state()).encode(), "application/json")
                else:
                    self.send_error(404)

            def do_POST(self):
                if not self._ok():
                    return
                if urlparse(self.path).path != "/cmd":
                    return self.send_error(404)
                try:
                    n = min(int(self.headers.get("Content-Length", 0)), 512)
                    cmd = str(json.loads(self.rfile.read(n)).get("cmd", ""))
                except (ValueError, TypeError):
                    return self.send_error(400)
                if not COMMAND.match(cmd):
                    return self.send_error(400)
                outer.app.commands.put(cmd)
                self._send(200, b'{"ok":true}', "application/json")

        try:
            self._srv = http.server.ThreadingHTTPServer((host, port), Handler)
        except OSError as e:
            log.error("web preview: cannot listen on %s:%s: %s", host, port, e)
            return False
        self._srv.daemon_threads = True
        self._thread = threading.Thread(target=self._srv.serve_forever, name="web", daemon=True)
        self._thread.start()
        log.info("web preview on %s", self.url)
        return True

    def stop(self):
        srv, self._srv = self._srv, None
        if srv:
            srv.shutdown()
            srv.server_close()
            log.info("web preview stopped")

    def frame_png(self) -> bytes:
        img, seq = self.app.last_frame, self.app.frame_seq
        if img is None:
            return b""
        with self._lock:
            if self._png[0] != seq:
                buf = io.BytesIO()
                img.save(buf, "PNG")
                self._png = (seq, buf.getvalue())
            return self._png[1]

    def state(self) -> dict:
        from . import __version__
        a = self.app
        return {"pages": [{"id": p["id"], "title": str(p.get("title", p["id"])).title()} for p in a.pages], "index": a.index,
                "brightness": a.display.brightness, "version": __version__, "update": a.updates.available if a.updates else None,
                "diag": a.diag_text() if hasattr(a, "diag_text") else ""}
