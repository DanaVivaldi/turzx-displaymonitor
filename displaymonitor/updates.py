"""Update check against the GitHub repository (and the optional `--update`).

The check is one GET of the repository's latest release (or, while there are no releases, of displaymonitor/__init__.py
on the main branch). Nothing is sent but the standard request headers. Configure it in config.yaml:

    updates:
      check: true
      interval_h: 24
      repo: DanaVivaldi/turzx-displaymonitor
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

from . import __version__

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPO = "DanaVivaldi/turzx-displaymonitor"
CACHE = os.path.join(ROOT, "logs", "update.json")
# what `--update` may overwrite: program code, docs, shipped assets and the *.example.yaml files; never your config / assets / logs
UPDATE_PATHS = ("displaymonitor", "tools", "scripts", "themes", "logos", "docs", "tests", ".github", "requirements.txt",
                "requirements-dev.txt", "README.md", "README.it.md", "LICENSE", "pytest.ini", "THIRD_PARTY_NOTICES.md")


def parse_version(text) -> tuple:
    """'v1.2.3' -> (1, 2, 3); anything unparsable -> ()."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(remote, local=__version__) -> bool:
    r, loc = parse_version(remote), parse_version(local)
    return bool(r) and r > loc


def _get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"DisplayMonitor/{__version__}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https GitHub URLs only
        return r.read()


def fetch_latest(repo: str = DEFAULT_REPO, timeout: float = 10.0) -> dict | None:
    """{'version', 'url', 'source'} of the newest published version, or None when it cannot be determined."""
    try:
        d = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest", timeout))
        if parse_version(d.get("tag_name")):
            return {"version": d["tag_name"].lstrip("v"), "url": d.get("html_url") or f"https://github.com/{repo}/releases/latest",
                    "source": "release", "zip": d.get("zipball_url")}
    except urllib.error.HTTPError as e:
        if e.code != 404:
            log.info("update check: GitHub answered %s", e.code)
            return None
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.info("update check failed: %s", e)
        return None
    try:                                      # no release yet: look at the version in the main branch
        raw = _get(f"https://raw.githubusercontent.com/{repo}/main/displaymonitor/__init__.py", timeout).decode("utf-8", "replace")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', raw)
        if m:
            return {"version": m.group(1), "url": f"https://github.com/{repo}", "source": "main",
                    "zip": f"https://github.com/{repo}/archive/refs/heads/main.zip"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.info("update check failed: %s", e)
    return None


class UpdateChecker:
    """Checks at start-up (after a short delay) and then every `interval_h` hours; the answer is cached in logs/update.json."""

    def __init__(self, cfg: dict | None):
        c = cfg or {}
        self.enabled = bool(c.get("check", True))
        self.interval = max(1.0, float(c.get("interval_h", 24))) * 3600
        self.repo = str(c.get("repo", DEFAULT_REPO))
        self.latest: dict | None = None
        self._stop = threading.Event()
        self._thread = None
        self._load_cache()

    @property
    def available(self) -> str | None:
        """The newer version's number, or None."""
        return self.latest["version"] if self.latest and is_newer(self.latest["version"]) else None

    def _load_cache(self):
        try:
            with open(CACHE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("repo") == self.repo:
                self.latest, self._checked = d.get("latest"), float(d.get("checked", 0))
                return
        except (OSError, ValueError):
            pass
        self._checked = 0.0

    def check_now(self) -> dict | None:
        info = fetch_latest(self.repo)
        self._checked = time.time()
        if info:
            self.latest = info
            if self.available:
                log.info("update available: %s -> %s (%s)", __version__, info["version"], info["url"])
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump({"repo": self.repo, "checked": self._checked, "latest": self.latest}, f)
        except OSError:
            pass
        return info

    def start(self, first_delay: float = 30.0):
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._loop, args=(first_delay,), name="updates", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self, first_delay):
        wait = max(first_delay, self._checked + self.interval - time.time())
        while not self._stop.wait(wait):
            self.check_now()
            wait = self.interval


# -- `python -m displaymonitor --update` ------------------------------------------------------
def _pip_install(root: str):
    req = os.path.join(root, "requirements.txt")
    if os.path.exists(req):
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", req], check=False)


def update_from_zip(zip_path: str, root: str = ROOT) -> list[str]:
    """Copy the program files of a downloaded repository zip over `root` (only UPDATE_PATHS and config/*.example.yaml)."""
    copied = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            top = names[0].split("/")[0]
            for n in names:                               # refuse path traversal
                if os.path.isabs(n) or ".." in n.split("/"):
                    raise ValueError(f"unsafe path in the archive: {n}")
            z.extractall(tmp)
        src = os.path.join(tmp, top)
        items = list(UPDATE_PATHS) + [os.path.join("config", f) for f in os.listdir(os.path.join(src, "config"))
                                      if f.endswith(".example.yaml")]
        for item in items:
            s, d = os.path.join(src, item), os.path.join(root, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            elif os.path.isfile(s):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(s, d)
            else:
                continue
            copied.append(item)
    return copied


def run_update(repo: str = DEFAULT_REPO, root: str = ROOT, assume_yes: bool = False, say=print) -> int:
    info = fetch_latest(repo)
    if not info:
        say("could not reach GitHub: no update information")
        return 1
    if not is_newer(info["version"]):
        say(f"already up to date (installed {__version__}, latest {info['version']})")
        return 0
    say(f"update available: {__version__} -> {info['version']}  ({info['url']})")
    if not assume_yes and input("install it now? your config/ and assets/ are never touched [y/N] ").strip().lower() not in ("y", "yes", "s", "si"):
        return 0
    if os.path.isdir(os.path.join(root, ".git")) and shutil.which("git"):
        r = subprocess.run(["git", "-C", root, "pull", "--ff-only"])
        if r.returncode != 0:
            say("git pull failed (local changes?): resolve it by hand")
            return r.returncode
    else:
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "update.zip")
            with open(zp, "wb") as f:
                f.write(_get(info["zip"] or f"https://github.com/{repo}/archive/refs/heads/main.zip", 60))
            say("updated: " + ", ".join(update_from_zip(zp, root)))
    _pip_install(root)
    say("done. restart the program to use the new version (python -m displaymonitor --send quit, then start it again)")
    return 0
