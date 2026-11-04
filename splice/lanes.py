# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three-lane timeline: Video, Text, Sound. Everything is edited by dragging on it."""
import copy
import threading
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, GLib, Adw

from . import export, peaks, textfit

RULER_H, V_H, T_H, S_H, GAP, PAD, HANDLE = 24, 54, 30, 54, 4, 10, 7
V_Y = RULER_H + GAP
T_Y = V_Y + V_H + GAP
S_Y = T_Y + T_H + GAP
TOTAL_H = S_Y + S_H + 6
GAIN_MAX = 1.5          # gain at the top edge of the Sound lane
LABELS = (("Video", V_Y, V_H), ("Text", T_Y, T_H), ("Sound", S_Y, S_H))

LIGHT = dict(bg=(.98, .98, .985), line=(.83, .85, .88), mute=(.40, .44, .52), ink=(.11, .14, .17),
             vid=(.36, .55, .94), txt=(.91, .65, .23), snd=(.25, .69, .52), ph=(.94, .27, .27), acc=(.15, .39, .85))
DARK = dict(bg=(.125, .145, .175), line=(.25, .29, .34), mute=(.60, .65, .72), ink=(.90, .92, .95),
            vid=(.33, .52, .91), txt=(.91, .65, .23), snd=(.25, .69, .52), ph=(.96, .36, .36), acc=(.42, .62, 1.0))
STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600]


def edge_preview_offset(p, i, side):
    """Time into clip i of the frame its edge keeps: the first frame for the left edge, the last exported
    frame for the right edge. Trimming shows exactly this frame, so what you see is where the cut lands."""
    if side == "l":
        return 0.0
    c = p.clips[i]
    try:
        f = export._fps_value(export.output_fps(p))
    except Exception:
        return max(0.0, c.duration - 0.04)
    return max(0.0, (export._frames(c.duration, f) - 1) / f)


def palette():
    return DARK if Adw.StyleManager.get_default().get_dark() else LIGHT


def fmt(s):
    s = max(0, s)
    return f"{int(s // 60)}:{int(s % 60):02d}"


def rr(cr, x, y, w, h, r=5):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


class Labels(Gtk.DrawingArea):
    """Fixed row names on the left, aligned with the lanes."""
    def __init__(self):
        super().__init__()
        self.set_content_width(58)
        self.set_content_height(TOTAL_H)
        self.set_draw_func(self.draw)

    def draw(self, area, cr, w, h):
        p = palette()
        cr.set_source_rgb(*p["mute"])
        for name, y, hh in LABELS:
            textfit.ui_text(cr, name, 4, y + hh / 2 + 4, 12)


class Lanes(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.pps = 24.0
        self.peaks = {}
        self._pending = set()
        self._drag = None
        # The widget is only as wide as the window; scrolling is an offset. (A scrolled, content-wide
        # widget crashes GTK once it passes ~32,000 px, which is a few minutes when zoomed in.)
        self.hadj = Gtk.Adjustment.new(0, 0, 1, 40, 200, 1)
        self.hadj.connect("value-changed", lambda *_: self.queue_draw())
        self.set_content_height(TOTAL_H)
        self.set_hexpand(True)
        self.set_draw_func(self.draw)
        self.connect("resize", lambda a, w, h: self._sync_adj())
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._begin)
        g.connect("drag-update", self._update)
        g.connect("drag-end", self._end)
        self.add_controller(g)
        rc = Gtk.GestureClick(button=3)
        rc.connect("pressed", self._right)
        self.add_controller(rc)
        sc = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        sc.connect("scroll", self._scroll)
        self.add_controller(sc)
        mo = Gtk.EventControllerMotion()
        mo.connect("motion", self._motion)
        self.add_controller(mo)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *a: self.queue_draw())

    # --- geometry ---------------------------------------------------------
    def x_of(self, t):
        return PAD + t * self.pps - self.hadj.get_value()

    def t_of(self, x):
        return max(0.0, (x + self.hadj.get_value() - PAD) / self.pps)

    @property
    def p(self):
        return self.app.project

    def _vis(self):
        """Visible x range (draw only what can be seen)."""
        return -20.0, float(self.get_width() or 1000) + 20.0

    def content_width(self):
        d = self.p.duration
        return PAD * 2 + (d + max(10.0, d * 0.2)) * self.pps

    def _sync_adj(self):
        page = float(self.get_width() or 1)
        upper = max(self.content_width(), page)
        self.hadj.configure(min(self.hadj.get_value(), max(0.0, upper - page)), 0, upper, 40, page * 0.9, page)
        bar = getattr(self.app, "lane_bar", None)
        if bar is not None:                              # keep the space, hide the bar when nothing scrolls
            bar.set_opacity(1.0 if upper > page + 1 else 0.0)
            bar.set_sensitive(upper > page + 1)

    def refresh(self):
        self._sync_adj()
        for c in self.p.clips + self.p.sounds:
            self._want_peaks(c.path)
        self.queue_draw()

    def _want_peaks(self, path):
        if path in self.peaks or path in self._pending:
            return
        self._pending.add(path)

        def work():
            data = peaks.compute(path)
            GLib.idle_add(self._got_peaks, path, data)
        threading.Thread(target=work, daemon=True).start()

    def _got_peaks(self, path, data):
        self.peaks[path] = data
        self._pending.discard(path)
        self.queue_draw()
        return False

    def zoom(self, factor, anchor_x=None):
        if anchor_x is None:
            anchor_x = (self.get_width() or 0) / 2
        t = self.t_of(anchor_x)
        self.pps = max(1.0, min(400.0, self.pps * factor))
        self._sync_adj()
        page = self.hadj.get_page_size()
        self.hadj.set_value(max(0.0, min(PAD + t * self.pps - anchor_x, self.hadj.get_upper() - page)))
        self.queue_draw()

    def scroll_to_show(self, t, margin=60):
        """Keep time t on screen (used while playing)."""
        x = self.x_of(t)
        page = self.hadj.get_page_size()
        if x > page - 30 or x < 0:
            self.hadj.set_value(max(0.0, min(self.hadj.get_value() + x - margin, self.hadj.get_upper() - page)))

    def _scroll(self, ctl, dx, dy):
        st = ctl.get_current_event_state()
        if st & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.CONTROL_MASK):
            self.zoom(1.15 ** (-dy), self._mouse_x)
        else:
            d = dx if abs(dx) > abs(dy) else dy
            page = self.hadj.get_page_size()
            self.hadj.set_value(max(0.0, min(self.hadj.get_value() + d * 60, self.hadj.get_upper() - page)))
        return True

    _mouse_x = 0.0
    _mouse_y = 0.0

    def _motion(self, ctl, x, y):
        self._mouse_x, self._mouse_y = x, y

    # --- hit testing ------------------------------------------------------
    def _clip_at(self, x):
        t = self.t_of(x)
        for i in range(len(self.p.clips)):
            s = self.p.clip_start(i)
            if s <= t < s + self.p.clips[i].duration:
                return i
        return None

    def hit(self, x, y):
        if y < V_Y - 1:
            return ("ruler",)
        if V_Y <= y <= V_Y + V_H:
            i = self._clip_at(x)
            if i is None:
                return ("empty",)
            s = self.p.clip_start(i)
            x0, x1 = self.x_of(s), self.x_of(s + self.p.clips[i].duration)
            part = "l" if x - x0 < HANDLE else "r" if x1 - x < HANDLE else "body"
            return ("v", i, part)
        if T_Y <= y <= T_Y + T_H:
            for j in reversed(range(len(self.p.texts))):
                t = self.p.texts[j]
                x0, x1 = self.x_of(t.start), self.x_of(t.end)
                if x0 <= x <= x1:
                    return ("t", j, "l" if x - x0 < HANDLE else "r" if x1 - x < HANDLE else "body")
            return ("empty",)
        if S_Y <= y <= S_Y + S_H:
            for j in reversed(range(len(self.p.sounds))):        # unlinked sound sits on top
                snd = self.p.sounds[j]
                x0, x1 = self.x_of(snd.start), self.x_of(snd.end)
                if x0 <= x <= x1:
                    return ("a", j, "l" if x - x0 < HANDLE else "r" if x1 - x < HANDLE else "body")
            i = self._clip_at(x)
            return ("s", i, "body") if i is not None else ("empty",)
        return ("empty",)

    def _gain_y(self, g):
        return S_Y + S_H - 4 - (S_H - 8) * min(g, GAIN_MAX) / GAIN_MAX

    def _y_gain(self, y):
        return max(0.0, min(GAIN_MAX, (S_Y + S_H - 4 - y) / (S_H - 8) * GAIN_MAX))

    def _owner(self, kind, i):
        """(clip or unlinked sound, its timeline start) for a sound hit."""
        if kind == "a":
            snd = self.p.sounds[i]
            return snd, snd.start
        return self.p.clips[i], self.p.clip_start(i)

    def _near_point(self, i, x, y, kind="s"):
        c, s = self._owner(kind, i)
        for k, (t, g) in enumerate(c.env):
            if abs(self.x_of(s + t) - x) <= 8 and abs(self._gain_y(g) - y) <= 8:
                return k
        return None

    # --- interaction ------------------------------------------------------
    def _begin(self, g, x, y):
        h = self.hit(x, y)
        d = self._drag = dict(h=h, x0=x, y0=y, mode=None, dx=0.0, cp=False)
        app = self.app
        if h[0] in ("ruler", "empty"):
            d["mode"] = "scrub"
            app.select(None)
            app.seek(self.t_of(x))
        elif h[0] == "v":
            i, part = h[1], h[2]
            c = self.p.clips[i]
            app.select(("v", i))
            d.update(orig=(c.src_in, c.src_out), orig_env=[list(q) for q in c.env], orig_texts=[copy.copy(t) for t in self.p.texts],
                     start=self.p.clip_start(i), dur=c.duration, removed=0,
                     mode={"l": "trim_l", "r": "trim_r", "body": "move"}[part])
            if part == "body":
                app.seek(self.t_of(x))
            else:                                       # decode the frames around this edge for instant feedback
                app.player.prefetch(d["start"] + edge_preview_offset(self.p, i, part))
        elif h[0] == "t":
            j, part = h[1], h[2]
            t = self.p.texts[j]
            app.select(("t", j))
            d.update(orig=(t.start, t.end), mode={"l": "t_l", "r": "t_r", "body": "t_move"}[part])
            app.seek(max(t.start, min(self.t_of(x), t.end - 0.01)))
        elif h[0] == "s" and not self.p.clips[h[1]].linked:
            d["mode"] = "scrub"                          # its sound is unlinked: nothing to edit here
            app.select(("s", h[1]))
            app.seek(self.t_of(x))
        elif h[0] in ("s", "a"):
            kind, i = h[0], h[1]
            c, s = self._owner(kind, i)
            app.select((kind, i))
            k = self._near_point(i, x, y, kind)
            if k is None and kind == "a" and h[2] in ("l", "r"):          # trim an unlinked sound
                from .media import probe
                d.update(mode="a_" + h[2], orig=(c.src_in, c.src_out, c.start), orig_env=[list(q) for q in c.env],
                         full=probe(c.path).duration)
                self.queue_draw()
                return
            if k is None:
                tl = self.t_of(x) - s
                if abs(self._gain_y(c.line_at(tl)) - y) <= 10:       # grabbed the line: add a point
                    self._cp()
                    if not c.env:
                        c.env = [[0.0, c.volume], [c.duration, c.volume]]
                    c.env.append([tl, c.line_at(tl)])
                    c.env.sort()
                    k = min(range(len(c.env)), key=lambda q: abs(c.env[q][0] - tl))
                elif kind == "a":                                    # drag the unlinked sound along
                    d.update(mode="a_move", orig=c.start)
                    app.seek(self.t_of(x))
                else:
                    app.seek(self.t_of(x))
            if k is not None:
                d.update(mode="point", k=k, start=s, kind=kind)
        self.queue_draw()

    def _cp(self):
        if not self._drag["cp"]:
            self.app.checkpoint()
            self._drag["cp"] = True

    def _update(self, g, dx, dy):
        d = self._drag
        if not d or not d["mode"]:
            return
        d["dx"] = dx
        m, dt = d["mode"], dx / self.pps
        if m == "scrub":
            self.app.seek_scrub(self.t_of(d["x0"] + dx))
        elif m in ("trim_l", "trim_r"):
            if abs(dx) < 2 and not d["cp"]:
                return
            self._cp()
            c = self.p.clips[d["h"][1]]
            from .media import probe
            full = probe(c.path).duration
            c.src_in, c.src_out = d["orig"]                 # always recompute from the drag start
            c.env = [list(q) for q in d["orig_env"]]
            self.p.texts[:] = [copy.copy(t) for t in d["orig_texts"]]
            if m == "trim_l":
                d["removed"] = self.p.trim(d["h"][1], new_in=d["orig"][0] + dt)
            else:
                d["removed"] = self.p.trim(d["h"][1], new_out=d["orig"][1] + dt, full=full)
            # show the frame the moved edge keeps (exact, so releasing the mouse never changes it)
            self.app.seek_scrub(d["start"] + edge_preview_offset(self.p, d["h"][1], "l" if m == "trim_l" else "r"))
        elif m in ("t_l", "t_r", "t_move"):
            if abs(dx) < 2 and not d["cp"]:
                return
            self._cp()
            t = self.p.texts[d["h"][1]]
            s0, e0 = d["orig"]
            if m == "t_move":
                dt = max(dt, -s0)
                t.start, t.end = s0 + dt, e0 + dt
            elif m == "t_l":
                t.start = max(0.0, min(s0 + dt, e0 - 0.3))
            else:
                t.end = max(s0 + 0.3, e0 + dt)
            self.app.refresh_pop()
        elif m == "a_move":
            if abs(dx) < 2 and not d["cp"]:
                return
            self._cp()
            j = d["h"][1]
            self.p.move_sound(j, self._snap_start(j, d["orig"] + dt))
        elif m in ("a_l", "a_r"):
            if abs(dx) < 2 and not d["cp"]:
                return
            self._cp()
            j = d["h"][1]
            snd = self.p.sounds[j]
            snd.src_in, snd.src_out, snd.start = d["orig"]
            snd.env = [list(q) for q in d["orig_env"]]
            if m == "a_l":
                self.p.trim_sound(j, new_in=d["orig"][0] + dt)
            else:
                self.p.trim_sound(j, new_out=d["orig"][1] + dt, full=d["full"])
        elif m == "point":
            self._cp()
            c, _ = self._owner(d.get("kind", "s"), d["h"][1])
            k = d["k"]
            lo = c.env[k - 1][0] if k > 0 else 0.0
            hi = c.env[k + 1][0] if k < len(c.env) - 1 else c.duration
            tl = max(lo, min(hi, self.t_of(d["x0"] + dx) - d["start"]))
            c.env[k] = [tl, self._y_gain(d["y0"] + dy)]
        self.queue_draw()

    def _end(self, g, dx, dy):
        d, self._drag = self._drag, None
        if not d or not d["mode"]:
            return
        m = d["mode"]
        if m in ("trim_l", "trim_r"):
            self.app.player.end_prefetch()
        if m == "move" and abs(dx) > 4:
            i = d["h"][1]
            mid = d["start"] * self.pps + d["dur"] * self.pps / 2 + dx
            others = [(self.p.clip_start(j) + self.p.clips[j].duration / 2) * self.pps
                      for j in range(len(self.p.clips)) if j != i]
            new = sum(1 for o in others if o < mid)
            if new != i:
                self.app.checkpoint()
                self.p.reorder(i, new)                      # captions travel with their clips
                self.app.select(("v", new))
                self.app.changed()
        elif m in ("trim_l", "trim_r") and d["cp"]:
            self.app.changed()
            self.app.removed_toast(d["removed"])
        elif m in ("t_l", "t_r", "t_move", "point") and d["cp"]:
            self.app.changed(player=False)
        elif m in ("a_move", "a_l", "a_r") and d["cp"]:
            self.app.changed(player=False)
        self.queue_draw()

    def _snap_start(self, j, start):
        """A dragged unlinked sound clicks onto clip edges, the playhead and the timeline start (within 8 px),
        by either of its ends."""
        snd = self.p.sounds[j]
        marks = [0.0, self.app.t] + [self.p.clip_start(i) for i in range(len(self.p.clips) + 1)]
        best, dist = start, 8.0 / self.pps
        for m in marks:
            for cand in (m, m - snd.duration):
                if abs(cand - start) < dist and cand >= 0:
                    best, dist = cand, abs(cand - start)
        return best

    def _right(self, g, n, x, y):
        h = self.hit(x, y)
        if h[0] in ("s", "a"):
            k = self._near_point(h[1], x, y, h[0])
            c, _ = self._owner(h[0], h[1])
            if k is not None and len(c.env) > 1:
                self.app.checkpoint()
                c.env.pop(k)
                self.app.changed()

    # --- drawing ----------------------------------------------------------
    def draw(self, area, cr, w, h):
        p = palette()
        proj = self.p
        # ruler
        step = next((s for s in STEPS if s * self.pps >= 70), STEPS[-1])
        cr.set_line_width(1)
        vx0, vx1 = self._vis()
        t = max(0, int(((vx0 - PAD) / self.pps) // step) - 1) * step
        end = (vx1 - PAD) / self.pps
        while t <= end:
            x = self.x_of(t) + .5
            cr.set_source_rgb(*p["mute"])
            cr.move_to(x, RULER_H - 11)
            cr.line_to(x, RULER_H)
            cr.stroke()
            textfit.ui_text(cr, fmt(t), x + 4, 11, 10)
            if step * self.pps / 5 >= 9:
                cr.set_source_rgb(*p["line"])
                for k in range(1, 5):
                    xm = self.x_of(t + step * k / 5) + .5
                    cr.move_to(xm, RULER_H - 5)
                    cr.line_to(xm, RULER_H)
                cr.stroke()
            t += step
        cr.set_source_rgb(*p["line"])
        cr.move_to(0, RULER_H + .5)
        cr.line_to(w, RULER_H + .5)
        cr.stroke()
        sel = self.app.sel
        d = self._drag
        if not proj.clips:
            cr.set_source_rgb(*p["mute"])
            textfit.ui_text(cr, "Drop a video here, or press Open", PAD + 6, V_Y + V_H / 2 + 5, 13)
        # video + sound
        for i, c in enumerate(proj.clips):
            s = proj.clip_start(i)
            x0, x1 = self.x_of(s), self.x_of(s + c.duration)
            off = d["dx"] if d and d["mode"] == "move" and d["h"][1] == i else 0.0
            if (x1 + off < vx0 or x0 + off > vx1) and (x1 < vx0 or x0 > vx1):
                continue                                   # off screen (also while being dragged)
            bw = max(2.0, x1 - x0 - 2)
            # video block
            cr.save()
            rr(cr, x0 + off, V_Y, bw, V_H)
            cr.set_source_rgba(*p["vid"], .55 if off else 1)
            cr.fill_preserve()
            if sel == ("v", i):
                cr.set_source_rgb(*p["acc"])
                cr.set_line_width(2.5)
                cr.stroke()
            else:
                cr.new_path()
            cr.restore()
            cr.save()
            cr.rectangle(x0 + off + 9, V_Y, max(0, bw - 18), V_H)
            cr.clip()
            cr.set_source_rgb(1, 1, 1)
            textfit.ui_text(cr, f"{c.name}  {fmt(c.duration)}" if bw > 90 else c.name, x0 + off + 11, V_Y + 15, 11, True)
            cr.restore()
            if bw > 20:
                cr.set_source_rgba(1, 1, 1, .5)
                rr(cr, x0 + off + 1, V_Y + 8, 4, V_H - 16, 2)
                rr(cr, x0 + off + bw - 5, V_Y + 8, 4, V_H - 16, 2)
                cr.fill()
            if not c.linked:                              # its sound is unlinked: an empty dashed outline
                cr.save()
                rr(cr, x0 + .5, S_Y + .5, bw - 1, S_H - 1)
                cr.set_source_rgba(*p["mute"], .9 if sel == ("s", i) else .45)
                cr.set_line_width(1.5 if sel == ("s", i) else 1)
                cr.set_dash([4, 4])
                cr.stroke()
                cr.restore()
                if bw > 20:                                # mark the picture as silent
                    cr.set_source_rgba(1, 1, 1, .85)
                    cr.save()
                    cr.rectangle(x0 + off + 9, V_Y, max(0, bw - 18), V_H)
                    cr.clip()
                    textfit.ui_text(cr, "sound unlinked", x0 + off + 11, V_Y + V_H - 9, 10)
                    cr.restore()
                continue
            self._sound_block(cr, p, c, x0, bw, s, sel == ("s", i), vx0, vx1)
        # unlinked sound, on top of the clips' sound
        end_x = self.x_of(proj.duration)
        for j, snd in enumerate(proj.sounds):
            x0, x1 = self.x_of(snd.start), self.x_of(snd.end)
            if x1 < vx0 or x0 > vx1:
                continue
            bw = max(2.0, x1 - x0 - 2)
            self._sound_block(cr, p, snd, x0, bw, snd.start, sel == ("a", j), vx0, vx1, loose=True)
            if x1 > end_x and proj.clips:                  # past the end of the video: not in the saved video
                cr.save()
                cr.rectangle(max(end_x, x0), S_Y, x1 - max(end_x, x0), S_H)
                cr.set_source_rgba(*p["bg"], .65)
                cr.fill()
                cr.restore()
        # text pills
        for j, t in enumerate(proj.texts):
            x0, x1 = self.x_of(t.start), self.x_of(t.end)
            if x1 < vx0 or x0 > vx1:
                continue
            cr.save()
            rr(cr, x0, T_Y + 1, max(4, x1 - x0), T_H - 2, 5)
            cr.set_source_rgb(*p["txt"])
            cr.fill_preserve()
            if sel == ("t", j):
                cr.set_source_rgb(*p["acc"])
                cr.set_line_width(2.5)
                cr.stroke_preserve()
            cr.clip()
            cr.set_source_rgb(.16, .11, 0)
            textfit.ui_text(cr, t.text, x0 + 8, T_Y + T_H / 2 + 4, 11, True)
            cr.restore()

    def _sound_block(self, cr, p, c, x0, bw, s, selected, vx0, vx1, loose=False):
        """One block in the Sound row: waveform, volume line (with its points when selected) and fade ramps.
        loose: an unlinked sound (stronger fill and outline, trim handles)."""
        x1 = x0 + bw + 2
        cr.save()
        rr(cr, x0, S_Y, bw, S_H)
        cr.set_source_rgba(*p["snd"], .38 if loose else .20)
        cr.fill_preserve()
        cr.set_source_rgba(*(p["acc"] if loose and selected else p["snd"]), .75 if not selected else 1)
        cr.set_line_width(2.5 if selected else 1.5 if loose else 1)
        cr.stroke_preserve()
        cr.clip()
        pk = self.peaks.get(c.path)
        if pk:
            cr.set_source_rgba(*p["snd"], .9)
            cr.set_line_width(1.2)
            mid = S_Y + S_H / 2
            px = max(x0, vx0)
            px = x0 + int((px - x0) // 2) * 2
            while px < min(x0 + bw, vx1):
                k = int((c.src_in + (px - x0) / self.pps) * peaks.PEAK_RATE)
                k2 = max(k + 1, int((c.src_in + (px - x0 + 2) / self.pps) * peaks.PEAK_RATE))
                a = max(pk[k:k2] or [0.0]) * (S_H / 2 - 5)
                cr.move_to(px + .5, mid - a)
                cr.line_to(px + .5, mid + a)
                px += 2
            cr.stroke()
        cr.set_source_rgb(*p["ink"])
        cr.set_line_width(1.8)
        pts = [[0.0, c.line_at(0)]] + sorted(c.env) + [[c.duration, c.line_at(c.duration)]] if c.env \
            else [[0.0, c.volume], [c.duration, c.volume]]
        for q, (tt, g) in enumerate(pts):
            (cr.move_to if q == 0 else cr.line_to)(self.x_of(s + tt), self._gain_y(g))
        cr.stroke()
        if selected:
            for tt, g in c.env:
                cr.arc(self.x_of(s + tt), self._gain_y(g), 4, 0, 6.2832)
                cr.set_source_rgb(1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgb(*p["ink"])
                cr.set_line_width(1.5)
                cr.stroke()
        cr.restore()
        if loose and bw > 20:                              # trim handles, like a clip's
            cr.set_source_rgba(*p["ink"], .45)
            rr(cr, x0 + 1, S_Y + 8, 4, S_H - 16, 2)
            rr(cr, x0 + bw - 5, S_Y + 8, 4, S_H - 16, 2)
            cr.fill()
        if c.fade_in > 0 or c.fade_out > 0:                # small fade ramps
            cr.set_source_rgba(*p["ink"], .55)
            cr.set_line_width(1)
            if c.fade_in > 0:
                cr.move_to(x0, S_Y + S_H - 2)
                cr.line_to(x0 + c.fade_in * self.pps, S_Y + 3)
            if c.fade_out > 0:
                cr.move_to(x1 - 2, S_Y + S_H - 2)
                cr.line_to(x1 - 2 - c.fade_out * self.pps, S_Y + 3)
            cr.stroke()


class Playhead(Gtk.DrawingArea):
    """Thin overlay with just the playhead, so the lanes do not redraw while playing."""
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_can_target(False)
        self.set_hexpand(True)
        self.set_content_height(TOTAL_H)
        self.set_draw_func(self.draw)

    def draw(self, area, cr, w, h):
        p = palette()
        x = self.app.lanes.x_of(self.app.t) + .5
        if x < -6 or x > w + 6:
            return
        cr.set_source_rgb(*p["ph"])
        cr.set_line_width(2)
        cr.move_to(x, 0)
        cr.line_to(x, TOTAL_H)
        cr.stroke()
        cr.move_to(x - 5, 0)
        cr.line_to(x + 5, 0)
        cr.line_to(x, 8)
        cr.fill()
