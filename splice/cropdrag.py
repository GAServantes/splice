# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Crop box dragging, as pure geometry (no GUI). A crop is [x, y, w, h] as fractions of the picture."""

MIN = 0.05          # smallest crop side, as a fraction of the picture
HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
CURSORS = {"nw": "nwse-resize", "se": "nwse-resize", "ne": "nesw-resize", "sw": "nesw-resize",
           "n": "ns-resize", "s": "ns-resize", "e": "ew-resize", "w": "ew-resize", "move": "move"}


def _c(v, lo, hi):
    return max(lo, min(hi, v))


def handle_points(crop, fx, fy, fw, fh):
    """Screen position of each of the 8 handles for a crop drawn on the frame rect (fx, fy, fw, fh)."""
    x, y, w, h = crop
    l, t, r, b = fx + x * fw, fy + y * fh, fx + (x + w) * fw, fy + (y + h) * fh
    mx, my = (l + r) / 2, (t + b) / 2
    return {"nw": (l, t), "n": (mx, t), "ne": (r, t), "e": (r, my), "se": (r, b), "s": (mx, b), "sw": (l, b), "w": (l, my)}


def hit(crop, fx, fy, fw, fh, px, py, grip=11):
    """Which handle (or 'move') is under the pointer at (px, py)? None when it is outside the box."""
    x, y, w, h = crop
    l, t, r, b = fx + x * fw, fy + y * fh, fx + (x + w) * fw, fy + (y + h) * fh
    g = min(grip, (r - l) / 3, (b - t) / 3)       # on a tiny box, leave room to move it
    g = max(g, 3.0)
    if not (l - g <= px <= r + g and t - g <= py <= b + g):
        return None
    west, east = abs(px - l) <= g, abs(px - r) <= g
    north, south = abs(py - t) <= g, abs(py - b) <= g
    if north and west: return "nw"
    if north and east: return "ne"
    if south and west: return "sw"
    if south and east: return "se"
    if north: return "n"
    if south: return "s"
    if west: return "w"
    if east: return "e"
    return "move" if (l < px < r and t < py < b) else None


def drag(crop, handle, dx, dy, lock=None, fa=1.0):
    """New crop after dragging `handle` by (dx, dy), both as fractions of the picture's width and height.
    lock: keep this pixel aspect ratio (w/h) when given; fa: picture width/height in pixels."""
    x, y, w, h = crop
    l, t, r, b = x, y, x + w, y + h
    if handle == "move":
        dx, dy = _c(dx, -l, 1 - r), _c(dy, -t, 1 - b)
        return [x + dx, y + dy, w, h]
    if not lock:
        if "w" in handle: l = _c(l + dx, 0.0, r - MIN)
        if "e" in handle: r = _c(r + dx, l + MIN, 1.0)
        if "n" in handle: t = _c(t + dy, 0.0, b - MIN)
        if "s" in handle: b = _c(b + dy, t + MIN, 1.0)
        return [l, t, r - l, b - t]
    k = lock / fa                                   # w/h in picture fractions
    wmin = max(MIN, MIN * k)
    if len(handle) == 2:                            # corner: the opposite corner stays put
        sx, sy = (1 if "e" in handle else -1), (1 if "s" in handle else -1)
        ax, ay = (l if sx > 0 else r), (t if sy > 0 else b)
        wc, hc = w + sx * dx, h + sy * dy
        nw_ = max(wc, hc * k)
        room_w = (1 - ax) if sx > 0 else ax
        room_h = (1 - ay) if sy > 0 else ay
        nw_ = max(wmin, min(nw_, room_w, room_h * k))
        nh = nw_ / k
        return [ax if sx > 0 else ax - nw_, ay if sy > 0 else ay - nh, nw_, nh]
    if handle in ("e", "w"):                        # side: one edge moves, the box grows about its middle
        cy = y + h / 2
        sx = 1 if handle == "e" else -1
        nw_ = w + sx * dx
        room_w = (1 - l) if sx > 0 else r
        nw_ = max(wmin, min(nw_, room_w, 2 * min(cy, 1 - cy) * k))
        nh = nw_ / k
        return [l if sx > 0 else r - nw_, cy - nh / 2, nw_, nh]
    cx = x + w / 2                                  # "n" / "s"
    sy = 1 if handle == "s" else -1
    nh = h + sy * dy
    room_h = (1 - t) if sy > 0 else b
    nh = max(wmin / k, min(nh, room_h, 2 * min(cx, 1 - cx) / k))
    nw_ = nh * k
    return [cx - nw_ / 2, t if sy > 0 else b - nh, nw_, nh]
