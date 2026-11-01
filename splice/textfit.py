# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Captions: one renderer for the preview and the export, so they always look the same.

Pango does font fallback, so emoji (colour), CJK and accented text all draw. Text sits in a translucent
box. A caption is one line and shrinks to fit the frame width.
"""
import threading
import cairo
import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

FONT = "DejaVu Sans Bold"
MARGIN = 0.92          # a caption may use at most this much of the frame width, box padding included
EDGE = 0.06            # top/bottom captions sit this fraction of the frame height from the edge
_lock = threading.Lock()     # Pango's font map is shared: preview (main thread) and export (worker) take turns
_cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, 1, 1))


def parse_color(s: str):
    s = (s or "#ffffff").lstrip("#")
    try:
        return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (1.0, 1.0, 1.0)


def _layout(cr, text: str, px: float):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(Pango.FontDescription(f"{FONT} {px:.2f}px"))
    lay.set_text(text, -1)
    return lay


def text_width(text: str, px: float) -> float:
    with _lock:
        return float(_layout(_cr, text, px).get_pixel_size()[0])


def fit_px(text: str, px: float, frame_w: float) -> float:
    """Font size in pixels (<= px) so that the text plus its box padding fits the frame width."""
    if not text.strip() or frame_w <= 0:
        return px
    avail = frame_w * MARGIN - px / 2           # padding is px/4 on each side
    w = text_width(text, px)
    if w <= avail:
        return px
    return max(6.0, px * max(avail, 1.0) / w)


def missing_glyphs(text: str, px: float = 40) -> int:
    """How many characters no installed font can draw (they would show as empty boxes)."""
    with _lock:
        return int(_layout(_cr, text, px).get_unknown_glyphs_count())


def box_size(text: str, px: float) -> tuple[float, float]:
    """Size of the caption box (text plus padding)."""
    with _lock:
        tw, th = _layout(_cr, text, px).get_pixel_size()
    pad = px / 4
    return tw + 2 * pad, th + 2 * pad


def box_position(pos: str, frame_w: float, frame_h: float, bw: float, bh: float) -> tuple[float, float]:
    """Top-left of the caption box inside a frame."""
    x = (frame_w - bw) / 2
    if pos == "top":
        return x, frame_h * EDGE
    if pos == "middle":
        return x, (frame_h - bh) / 2
    return x, frame_h - bh - frame_h * EDGE


def draw_caption(cr, text: str, px: float, color: str, x: float, y: float):
    """Draw the box and text with the box's top-left corner at (x, y)."""
    with _lock:
        lay = _layout(cr, text, px)
        tw, th = lay.get_pixel_size()
        pad = px / 4
        cr.save()
        cr.set_source_rgba(0, 0, 0, .45)
        cr.rectangle(x, y, tw + 2 * pad, th + 2 * pad)
        cr.fill()
        r, g, b = parse_color(color)
        cr.set_source_rgba(r, g, b, 1)
        cr.move_to(x + pad, y + pad)
        PangoCairo.show_layout(cr, lay)
        cr.restore()


def render_png(path: str, text: str, px: float, color: str) -> tuple[int, int]:
    """Write the caption box as a transparent PNG; returns its pixel size."""
    bw, bh = box_size(text, px)
    w, h = max(1, int(bw + 0.999)), max(1, int(bh + 0.999))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    draw_caption(cr, text, px, color, 0, 0)
    surf.write_to_png(path)
    return w, h


def ui_text(cr, text: str, x: float, y: float, size: float = 11, bold: bool = False):
    """Draw UI text (labels in the timeline) with font fallback, so emoji and CJK names show properly.
    (x, y) is the baseline-left of the text, like Cairo's show_text."""
    with _lock:
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription(f"Sans{' Bold' if bold else ''} {size:.1f}px"))
        lay.set_text(text, -1)
        base = lay.get_baseline() / Pango.SCALE
        cr.move_to(x, y - base)
        PangoCairo.show_layout(cr, lay)
