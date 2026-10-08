"""Transmission scheduling for the slow USB link (pure functions: no serial port, no numpy state, fully unit-testable).

The display driver keeps three things:
  * `desired`  - the newest frame the app produced (replaced, never queued),
  * `sent`     - what the panel is believed to show (a region is copied into it only after its bytes were written),
  * the pending work - NOT stored: it is always `diff(sent, desired)`, so a newer frame automatically replaces whatever was not sent yet.

Each cycle the pending rectangles are split into blocks (<= max_px pixels each, the firmware's limit), put in priority order and cut at a byte budget:

  priority 0  critical   full refreshes: first frame after a connect, the "Ciao" / night frames  (never budgeted)
  priority 1  data       small rectangles: digits, bars, text
  priority 2  bulk       large rectangles: a background / tint step, a whole ring changing colour
  priority 3  healing    the self-healing band (only with budget left over and nothing pending)
"""
from __future__ import annotations

LINK_BPS = 165_000            # measured throughput of the panel's serial link, bytes / second
BYTES_PER_PX = 2              # RGB565
HEADER_BYTES = 6              # every bitmap command starts with a 6-byte header
MIN_BUDGET = 1024             # the smallest budget that is honoured exactly: one full-width row (320 px = 640 B + header) always fits

CRITICAL, DATA, BULK, HEALING = 0, 1, 2, 3


def rect_bytes(rect) -> int:
    """Pixel payload of a rectangle."""
    return rect[2] * rect[3] * BYTES_PER_PX


def wire_bytes(rect) -> int:
    """What a rectangle costs on the link: its header + its pixels. The budget is counted in these."""
    return HEADER_BYTES + rect_bytes(rect)


def split_rect(rect, max_px: int) -> list[tuple[int, int, int, int]]:
    """A rectangle -> row-chunk blocks of at most max_px pixels (one bitmap command each)."""
    x, y, w, h = rect
    rows = max(1, max_px // max(1, w))
    return [(x, y0, w, min(rows, y + h - y0)) for y0 in range(y, y + h, rows)]


def classify(rects, bulk_px: int) -> tuple[list, list]:
    """(data, bulk): rectangles at most `bulk_px` pixels are data (digits, bars), larger ones are bulk (backgrounds, tints)."""
    data = [r for r in rects if r[2] * r[3] <= bulk_px]
    bulk = [r for r in rects if r[2] * r[3] > bulk_px]
    return data, bulk


def ordered_blocks(rects, bulk_px: int, max_px: int) -> list[tuple[int, tuple[int, int, int, int]]]:
    """[(priority, block)] in the order they should be sent: data top-to-bottom first, then bulk smallest first (classified by size)."""
    return blocks_for(*classify(rects, bulk_px), max_px)


def blocks_for(data, bulk, max_px: int) -> list[tuple[int, tuple[int, int, int, int]]]:
    """Same, for rectangles that are already classified."""
    out = [(DATA, b) for r in sorted(data, key=lambda r: (r[1], r[0])) for b in split_rect(r, max_px)]
    out += [(BULK, b) for r in sorted(bulk, key=lambda r: (rect_bytes(r), r[1], r[0])) for b in split_rect(r, max_px)]
    return out


def split_to_fit(rect, budget: int) -> list[tuple[int, int, int, int]]:
    """Cut a rectangle into pieces that each cost at most `budget` bytes on the wire: whole rows when a row fits, else pieces of one row."""
    x, y, w, h = rect
    if wire_bytes(rect) <= budget:
        return [rect]
    max_px = max(1, (budget - HEADER_BYTES) // BYTES_PER_PX)
    if max_px >= w:
        rows = max_px // w
        return [(x, y0, w, min(rows, y + h - y0)) for y0 in range(y, y + h, rows)]
    return [(x0, y0, min(max_px, x + w - x0), 1) for y0 in range(y, y + h) for x0 in range(x, x + w, max_px)]


def take(blocks, budget: int):
    """Split `blocks` into (this cycle, the rest) so that what this cycle puts on the wire (headers + pixels) NEVER exceeds `budget`
    (<= 0 means unlimited; a positive budget below MIN_BUDGET is raised to it, the smallest that can carry a row).
    A block that is larger than the budget is cut up (rows, then pieces of a row), so the queue always makes progress."""
    if budget <= 0:
        return list(blocks), []
    budget = max(budget, MIN_BUDGET)
    queue, chosen, used = list(blocks), [], 0
    while queue:
        prio, blk = queue[0]
        size = wire_bytes(blk)
        if size > budget:
            queue[0:1] = [(prio, piece) for piece in split_to_fit(blk, budget)]
            continue
        if used + size > budget:
            break
        chosen.append(queue.pop(0))
        used += size
    return chosen, queue


def latency_estimate(pending_bytes: int) -> float:
    """Seconds the link needs for `pending_bytes`."""
    return pending_bytes / LINK_BPS


def new_metrics() -> dict:
    return {"budget": 0, "sent": 0, "pending": 0, "coalesced": 0, "used": None, "latency_s": 0.0, "cycles": 0, "critical": 0}
