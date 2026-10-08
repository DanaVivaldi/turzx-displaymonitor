"""Small file helpers: atomic writes (never a half-written state / cache file) and the command inbox swap."""
import os
import tempfile


def atomic_write(path: str, text: str, encoding: str = "utf-8"):
    """Write `text` to a temporary file in the same folder, then rename it over `path` (atomic on Windows and POSIX)."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def take_lines(path: str) -> list[str]:
    """Commands waiting in `path`: the file is renamed first, so a line appended meanwhile goes to a NEW file instead of being lost.
    Returns [] when there is nothing (or the writer still holds the file: it is picked up on the next call)."""
    work = path + ".work"
    try:
        os.replace(path, work)
    except OSError:
        if not os.path.exists(work):
            return []                                   # nothing waiting, or the sender still has it open
    try:
        with open(work, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        os.remove(work)
        return lines
    except OSError:
        return []
