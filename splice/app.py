# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Splice main window."""
import copy, json, os, shutil, sys, threading, time
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, Graphene

from . import cropdrag
from . import export as exporter
from .lanes import Lanes, Labels, Playhead
from .media import probe
from .model import Project, Clip, Text
from .player import Player
from . import textfit

CSS = """
.pv-frame { background: #0d1117; border-radius: 8px; }
.pop { padding: 8px 12px; border-radius: 10px; }
.tool-btn { padding: 8px 6px; min-width: 74px; }
.tm { font-feature-settings: 'tnum'; }
"""
ASPECTS = [("Full picture", None), ("16:9", 16 / 9), ("4:3", 4 / 3), ("1:1", 1.0), ("9:16", 9 / 16)]
BG = Gdk.RGBA()
BG.parse("#0d1117")


def fmt_t(s):
    s = max(0.0, s)
    return f"{int(s // 60)}:{s % 60:04.1f}"


def hex_of(rgba):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in (rgba.red, rgba.green, rgba.blue))


def contain(aw, ah, bw, bh):
    """Largest rectangle with aspect aw:ah that fits inside bw x bh, centred. Returns (x, y, w, h)."""
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return (0.0, 0.0, float(bw), float(bh))
    s = min(bw / aw, bh / ah)
    w, h = aw * s, ah * s
    return ((bw - w) / 2, (bh - h) / 2, w, h)


def safe_info(path):
    try:
        return probe(path)
    except Exception:
        return None


def spin(lo, hi, step, val, digits=1, width=7):
    s = Gtk.SpinButton.new_with_range(lo, hi, step)
    s.set_digits(digits)
    s.set_value(val)
    s.set_width_chars(width)
    return s


def label(text, dim=False, bold=False):
    l = Gtk.Label(label=text, xalign=0)
    if dim:
        l.add_css_class("dim-label")
    if bold:
        l.add_css_class("heading")
    return l


def tool_button(icon, text, tip, cb):
    b = Gtk.Button(tooltip_text=tip, focus_on_click=False)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    box.append(Gtk.Image.new_from_icon_name(icon))
    box.append(Gtk.Label(label=text))
    b.set_child(box)
    b.add_css_class("tool-btn")
    b.connect("clicked", lambda *_: cb())
    return b


class VideoView(Gtk.Widget):
    """Draws the current frame the way the export will: output shape, crop applied, black bars."""
    __gtype_name__ = "SpliceVideoView"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.tex = None
        self.set_size_request(448, 252)
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        snapshot.append_color(BG, Graphene.Rect().init(0, 0, w, h))
        g = self.win.geometry(w, h)
        if not g or self.tex is None:
            return
        snapshot.save()
        snapshot.push_clip(Graphene.Rect().init(*g["clip"]))
        x, y, tw, th = g["tex"]
        snapshot.translate(Graphene.Point().init(x, y))
        self.tex.snapshot(snapshot, tw, th)
        snapshot.pop()
        snapshot.restore()


class SpliceWindow(Adw.ApplicationWindow):
    def __init__(self, app, project=None):
        super().__init__(application=app, title="Splice", default_width=1100, default_height=760)
        self.project = project or Project()
        self.sel = None              # ("v"|"t"|"s", index) or None
        self.crop_mode = False
        self.t = 0.0
        self.frame_wh = (16, 9)
        self.undo, self.redo = [], []
        self._cp_key, self._cp_time = None, 0.0
        self.path = None             # project file
        self.dirty = False
        self._busy = False
        self._cancel = None
        self._force_close = False
        self._rev = 0
        self._okey = None
        self._settle_id = 0
        self.crop_lock = None        # keep this pixel aspect while dragging the crop box (None = free)
        self._crop_ui = None         # the number boxes of the open crop editor
        self._cdrag = None
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons"))
        self.player = Player(self.project, self._on_frame, self._on_time, self._on_state, self.toast_once)
        self._build()
        self.lanes.refresh()
        self.refresh_pop()
        self._update_title()
        missing = [n for n in ("ffmpeg", "ffprobe") if not shutil.which(n)]
        if missing:
            GLib.idle_add(self._need_tools, missing)

    def _need_tools(self, missing):
        d = Adw.AlertDialog(heading="ffmpeg is not installed",
                            body="Splice needs " + " and ".join(missing) + " to open and save videos.\nInstall it with:  sudo apt install ffmpeg")
        d.add_response("ok", "OK")
        d.present(self)
        return False

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.toasts = Adw.ToastOverlay()
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.title_w = Adw.WindowTitle(title="Splice", subtitle="")
        hb.set_title_widget(self.title_w)
        openb = Gtk.Button(tooltip_text="Add videos")
        openb.set_child(Adw.ButtonContent(icon_name="document-open-symbolic", label="Open"))
        openb.connect("clicked", lambda *_: self.open_videos())
        self.undo_b = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Undo (Ctrl+Z)", focus_on_click=False)
        self.redo_b = Gtk.Button(icon_name="edit-redo-symbolic", tooltip_text="Redo (Ctrl+Shift+Z)", focus_on_click=False)
        self.undo_b.connect("clicked", lambda *_: self.do_undo())
        self.redo_b.connect("clicked", lambda *_: self.do_redo())
        for w in (openb, self.undo_b, self.redo_b):
            hb.pack_start(w)
        save = Gtk.Button(tooltip_text="Export the finished video")
        save.set_child(Adw.ButtonContent(icon_name="document-save-symbolic", label="Save video"))
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self.save_video())
        hb.pack_end(save)
        menu = Gio.Menu()
        menu.append("Open project…", "win.open_project")
        menu.append("Save project", "win.save_project")
        menu.append("Save project as…", "win.save_project_as")
        hb.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        for name, fn in (("open_project", self.open_project), ("save_project", self.save_project),
                         ("save_project_as", lambda: self.save_project(True))):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_, f=fn: f())
            self.add_action(a)
        tv.add_top_bar(hb)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10, margin_bottom=12,
                       margin_start=12, margin_end=12)
        top = Gtk.Box(spacing=16, halign=Gtk.Align.FILL, hexpand=True, vexpand=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.video = VideoView(self)
        self.over = Gtk.DrawingArea()
        self.over.set_can_target(False)
        self.over.set_draw_func(self._draw_over)
        ov = Gtk.Overlay(css_classes=["pv-frame"], overflow=Gtk.Overflow.HIDDEN)
        ov.set_child(self.video)
        ov.add_overlay(self.over)
        self.stage_ov = ov
        cd = Gtk.GestureDrag()
        cd.connect("drag-begin", self._crop_begin)
        cd.connect("drag-update", self._crop_update)
        cd.connect("drag-end", self._crop_end)
        ov.add_controller(cd)
        cm = Gtk.EventControllerMotion()
        cm.connect("motion", self._crop_hover)
        cm.connect("leave", lambda *_: ov.set_cursor_from_name(None))
        ov.add_controller(cm)
        frame = Gtk.AspectFrame(ratio=16 / 9, obey_child=False, hexpand=True, vexpand=True, child=ov)
        left.append(frame)
        tr = Gtk.Box(spacing=6)
        prev = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text="Previous clip", focus_on_click=False)
        nxt = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Next clip", focus_on_click=False)
        self.play_b = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Play (Space)", focus_on_click=False)
        self.play_b.add_css_class("suggested-action")
        self.play_b.add_css_class("circular")
        prev.connect("clicked", lambda *_: self.jump(-1))
        nxt.connect("clicked", lambda *_: self.jump(1))
        self.play_b.connect("clicked", lambda *_: self.player.toggle())
        self.time_l = Gtk.Label(label="0:00.0 / 0:00.0", css_classes=["tm", "dim-label"])
        self.scrub = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.001)
        self.scrub.set_draw_value(False)
        self.scrub.set_hexpand(True)
        self.scrub.set_focus_on_click(False)
        self.scrub.connect("change-value", self._scrub_changed)
        for w in (prev, self.play_b, nxt, self.time_l, self.scrub):
            tr.append(w)
        left.append(tr)
        top.append(left)
        tools = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.START, halign=Gtk.Align.END, hexpand=False)
        tools.append(tool_button("edit-cut-symbolic", "Split", "Split the clip at the playhead (S)", self.tool_split))
        tools.append(tool_button("insert-text-symbolic", "Add text", "Add a caption at the playhead", self.tool_text))
        tools.append(tool_button("splice-crop-symbolic", "Crop", "Crop the clip under the playhead", self.tool_crop))
        tools.append(tool_button("audio-volume-high-symbolic", "Volume", "Edit the sound of the clip under the playhead", self.tool_volume))
        zr = Gtk.Box(spacing=4, hexpand=False)
        for ic, f in (("zoom-out-symbolic", 1 / 1.4), ("zoom-in-symbolic", 1.4)):
            b = Gtk.Button(icon_name=ic, tooltip_text="Zoom the timeline (Alt+scroll)", focus_on_click=False)
            b.set_hexpand(True)
            b.connect("clicked", lambda _b, f=f: self.lanes.zoom(f))
            zr.append(b)
        tools.append(zr)
        top.append(tools)
        root.append(top)
        self.pop = Gtk.Box(spacing=10, css_classes=["card", "pop"], valign=Gtk.Align.FILL, vexpand=True)
        # Fixed height: the timeline below must never move when the selection (and so this row) changes.
        pop_sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                    propagate_natural_height=False, child=self.pop)
        pop_sw.set_min_content_width(300)
        pop_sw.set_vexpand(False)
        pop_sw.set_size_request(-1, 54)
        pop_sw.set_min_content_height(54)
        pop_sw.set_max_content_height(54)
        root.append(pop_sw)
        lane_box = Gtk.Box(spacing=6, vexpand=True, valign=Gtk.Align.START)
        lane_box.append(Labels())
        self.lanes = Lanes(self)
        self.playhead = Playhead(self)
        lov = Gtk.Overlay(hexpand=True)
        lov.set_child(self.lanes)
        lov.add_overlay(self.playhead)
        self.lanes.hadj.connect("value-changed", lambda *_: self.playhead.queue_draw())
        self.lane_bar = Gtk.Scrollbar(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.lanes.hadj)
        lane_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        lane_col.append(lov)
        lane_col.append(self.lane_bar)
        lane_box.append(lane_col)
        root.append(lane_box)
        tv.set_content(root)
        self.toasts.set_child(tv)
        self.set_content(self.toasts)
        dt = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        dt.connect("drop", self._drop)
        self.add_controller(dt)
        kc = Gtk.EventControllerKey()
        kc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        kc.connect("key-pressed", self._key)
        self.add_controller(kc)
        self.connect("close-request", self._close_request)

    # --------------------------------------------------------------- state
    def _dump(self):
        return json.dumps({"clips": [vars(c) for c in self.project.clips], "texts": [vars(t) for t in self.project.texts]})

    def _push(self, snap):
        self.undo.append(snap)
        self.undo = self.undo[-100:]
        self.redo.clear()
        self.dirty = True
        self._sync_undo()
        self._update_title()

    def checkpoint(self, key=None):
        """Remember the state before an edit. The same key within a second counts as one edit."""
        now = time.monotonic()
        if key is not None and key == self._cp_key and now - self._cp_time < 1.0:
            self._cp_time = now
            return
        self._cp_key, self._cp_time = key, now
        self._push(self._dump())

    def _restore(self, s):
        d = json.loads(s)
        self.project.clips[:] = [Clip(**c) for c in d["clips"]]
        self.project.texts[:] = [Text(**t) for t in d["texts"]]
        self.sel = None
        self.crop_mode = False
        self._cp_key = None
        self.dirty = True
        self.changed()

    def do_undo(self):
        if self.undo:
            self.redo.append(self._dump())
            self._restore(self.undo.pop())

    def do_redo(self):
        if self.redo:
            self.undo.append(self._dump())
            self._restore(self.redo.pop())

    def _sync_undo(self):
        self.undo_b.set_sensitive(bool(self.undo))
        self.redo_b.set_sensitive(bool(self.redo))

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else (self.project.clips[0].name if self.project.clips else "")
        self.title_w.set_subtitle((name + (" •" if self.dirty and name else "")) if name else "")

    def changed(self, player=True, pop=True):
        """Call after editing the project."""
        self._rev += 1
        if self.sel:
            k, i = self.sel
            n = len(self.project.texts) if k == "t" else len(self.project.clips)
            if i >= n:
                self.sel = None
                self.crop_mode = False
        if self.crop_mode:
            ok = self.sel and self.sel[0] == "v" and self.sel[1] < len(self.project.clips) and self.project.clips[self.sel[1]].crop
            if not ok:
                self.crop_mode = False
        self.lanes.refresh()
        if player:
            self.player.refresh()
        if pop:
            self.refresh_pop()
        self._update_time_label()
        self._refresh_over()
        self.playhead.queue_draw()
        self._sync_undo()
        self._update_title()

    def select(self, sel):
        if sel != self.sel:
            self.sel = sel
            self.crop_mode = False                     # crop editing belongs to one clip
            self.refresh_pop()
        self.lanes.queue_draw()
        self._refresh_over()

    def seek(self, t):
        self.player.seek(max(0.0, min(t, self.project.duration)))

    def seek_scrub(self, t):
        """Seek while the user is dragging: quick keyframe jumps, then one exact seek once they pause."""
        t = max(0.0, min(t, self.project.duration))
        self.player.seek(t, fast=True)
        if self._settle_id:
            GLib.source_remove(self._settle_id)
        self._settle_id = GLib.timeout_add(200, self._settle, t)

    def _settle(self, t):
        self._settle_id = 0
        self.player.seek(t)
        return False

    def jump(self, d):
        p = self.project
        if not p.clips:
            return
        i, off = p.clip_at(self.t)
        if d > 0 and i == len(p.clips) - 1:
            return self.seek(p.duration)
        j = i + d if (d > 0 or off < 0.3) else i
        self.seek(p.clip_start(max(0, min(j, len(p.clips) - 1))) + 0.001)

    # --------------------------------------------------------- player hooks
    def _on_frame(self, tex, w, h):
        self.video.tex = tex
        if tex is not None and self.frame_wh != (w, h):
            self.frame_wh = (w, h)
            self._refresh_over()
        self.video.queue_draw()

    def _on_time(self, t):
        self.t = t
        self._update_time_label()
        self.playhead.queue_draw()
        self._refresh_over()
        if self.player.playing:
            self.lanes.scroll_to_show(t)

    def _on_state(self, playing):
        self.play_b.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")

    def _update_time_label(self):
        d = self.project.duration
        self.time_l.set_label(f"{fmt_t(self.t)} / {fmt_t(d)}")
        self.scrub.set_value(self.t / d if d else 0)

    def _scrub_changed(self, scale, st, value):
        self.seek_scrub(max(0.0, min(1.0, value)) * self.project.duration)
        return False

    # ----------------------------------------------------- preview drawing
    def geometry(self, w, h):
        """Where things go on the stage. Shared by the picture and the overlay."""
        p = self.project
        if not p.clips:
            return None
        try:
            ow, oh = exporter.output_size(p)
        except Exception:
            ow, oh = 16, 9
        i, _ = p.clip_at(self.t)
        c = p.clips[i]
        fw, fh = self.frame_wh
        out = contain(ow, oh, w, h)
        if self.crop_mode and self.sel == ("v", i):
            F = contain(fw, fh, w, h)
            return dict(out=out, frame=F, crop=c.crop, clip=(0, 0, w, h), tex=F, editing=True)
        cr = c.crop or [0.0, 0.0, 1.0, 1.0]
        ar = (cr[2] * fw) / max(1e-6, cr[3] * fh)
        D = contain(ar, 1.0, out[2], out[3])
        D = (D[0] + out[0], D[1] + out[1], D[2], D[3])
        tex = (D[0] - cr[0] * D[2] / cr[2], D[1] - cr[1] * D[3] / cr[3], D[2] / cr[2], D[3] / cr[3])
        return dict(out=out, frame=None, crop=c.crop, clip=D, tex=tex, editing=False)

    def _overlay_key(self):
        p = self.project
        if not p.clips:
            return ("empty", self._rev)
        i, _ = p.clip_at(self.t)
        texts = tuple(j for j, t in enumerate(p.texts) if t.start <= self.t < t.end)
        return (i, self.frame_wh, self.crop_mode and self.sel == ("v", i), tuple(p.clips[i].crop or ()), texts, self._rev)

    def _refresh_over(self):
        k = self._overlay_key()
        if k != self._okey:
            self._okey = k
            self.over.queue_draw()

    def _draw_over(self, area, cr, w, h):
        g = self.geometry(w, h)
        if not g:
            return
        p = self.project
        if g["editing"] and g["crop"]:
            fx, fy, fw, fh = g["frame"]
            x, y, cw, ch = g["crop"]
            rx, ry, rw, rh = fx + x * fw, fy + y * fh, cw * fw, ch * fh
            cr.set_source_rgba(0, 0, 0, .55)
            cr.set_fill_rule(1)
            cr.rectangle(fx, fy, fw, fh)
            cr.rectangle(rx, ry, rw, rh)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(1.5)
            cr.set_dash([5, 4])
            cr.rectangle(rx, ry, rw, rh)
            cr.stroke()
            cr.set_dash([])
            for hx, hy in cropdrag.handle_points(g["crop"], fx, fy, fw, fh).values():
                cr.rectangle(hx - 5, hy - 5, 10, 10)
                cr.set_source_rgb(1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgba(0, 0, 0, .7)
                cr.set_line_width(1)
                cr.stroke()
            return
        ox, oy, ow, oh = g["out"]
        for t in p.texts:
            if t.start <= self.t < t.end and t.text.strip():
                px = max(6, textfit.fit_px(t.text, oh * t.size, ow))
                bw, bh = textfit.box_size(t.text, px)
                x, y = textfit.box_position(t.pos, ow, oh, bw, bh)
                textfit.draw_caption(cr, t.text, px, t.color, ox + x, oy + y)

    # ------------------------------------------------------------- tools
    def tool_split(self):
        snap = self._dump()
        i, _ = self.project.clip_at(self.t)           # the clip being split (before the split)
        if self.project.split(self.t):
            self._push(snap)
            self.sel = ("v", i + 1)                    # select the new right half
            self.crop_mode = False
            self.changed()
        else:
            self.toast("Move the playhead into a clip, away from its edges, to split.")

    def tool_text(self):
        if not self.project.clips:
            return self.toast("Add a video first.")
        self.checkpoint()
        d = self.project.duration
        start = min(self.t, max(0.0, d - 0.5))
        self.project.texts.append(Text("Your text", start, min(d, start + 3)))
        self.select(("t", len(self.project.texts) - 1))
        self.changed()

    def tool_crop(self):
        if not self.project.clips:
            return self.toast("Add a video first.")
        i, _ = self.project.clip_at(self.t)
        c = self.project.clips[i]
        if c.crop is None:
            self.checkpoint()
            c.crop = [0.1, 0.1, 0.8, 0.8]
        self.crop_mode = True
        self.sel = ("v", i)
        self.refresh_pop()
        self.lanes.queue_draw()
        self.changed(player=False, pop=False)

    def tool_volume(self):
        if not self.project.clips:
            return self.toast("Add a video first.")
        i, _ = self.project.clip_at(self.t)
        self.select(("s", i))

    def delete_selected(self):
        if not self.sel:
            return
        k, i = self.sel
        self.checkpoint()
        if k == "v":
            self.project.delete_clip(i)               # captions that start in it go, the rest move up
            self.sel = None
        elif k == "t":
            self.project.texts.pop(i)
            self.sel = None
        elif k == "s":
            c = self.project.clips[i]
            c.env, c.volume, c.fade_in, c.fade_out = [], 1.0, 0.0, 0.0
        self.changed()

    # ---------------------------------------------------------- pop editor
    def refresh_pop(self):
        self._crop_ui = None                            # rebuilt below if the crop editor is open
        while (ch := self.pop.get_first_child()):
            self.pop.remove(ch)
        p, sel = self.project, self.sel
        add = self.pop.append
        if sel and sel[1] >= (len(p.texts) if sel[0] == "t" else len(p.clips)):
            sel = self.sel = None                      # selection no longer exists
        if not sel:
            add(label("Click a clip, a text block or the sound row to edit it. Drag the edges of a clip to trim it.", dim=True))
            return
        k, i = sel
        if k == "v":
            c = p.clips[i]
            info = safe_info(c.path)
            full = info.duration if info else c.src_out
            add(label(c.name, bold=True))
            if not info:
                add(label("The file is missing or unreadable.", dim=True))
            if self.crop_mode and c.crop:
                self._crop_controls(c, add)
                return
            add(label("Starts at", dim=True))
            a = spin(0, full, 0.1, c.src_in)
            add(a)
            add(label("Ends at", dim=True))
            b = spin(0, full, 0.1, c.src_out)
            add(b)
            busy = [False]

            def edit(w, which):
                if busy[0]:
                    return
                self.checkpoint(("trim", i, which))
                if which == "a":
                    n = p.trim(i, new_in=w.get_value())
                else:
                    n = p.trim(i, new_out=w.get_value(), full=full)
                self.removed_toast(n)
                busy[0] = True
                a.set_value(c.src_in)
                b.set_value(c.src_out)
                busy[0] = False
                self.changed(pop=False)
            a.connect("value-changed", edit, "a")
            b.connect("value-changed", edit, "b")
            sp = Gtk.Button(label="Split at playhead")
            sp.connect("clicked", lambda *_: self.tool_split())
            add(sp)
            cr_b = Gtk.Button(label="Crop…")
            cr_b.connect("clicked", lambda *_: self.tool_crop())
            add(cr_b)
            self._delete_button(add, "Delete clip")
        elif k == "t":
            t = p.texts[i]
            add(label("Text", bold=True))
            e = Gtk.Entry(text=t.text, width_chars=24)
            e.connect("changed", lambda w: (self.checkpoint(("text", i)), setattr(t, "text", w.get_text()), self.changed(False, False)))
            add(e)
            add(label("From", dim=True))
            s1 = spin(0, max(p.duration, t.end), 0.1, t.start)
            add(s1)
            add(label("to", dim=True))
            s2 = spin(0, max(p.duration, t.end) + 60, 0.1, t.end)
            add(s2)
            s1.connect("value-changed", lambda w: (self.checkpoint(("ts", i)), setattr(t, "start", min(w.get_value(), t.end - 0.1)), self.changed(False, False)))
            s2.connect("value-changed", lambda w: (self.checkpoint(("te", i)), setattr(t, "end", max(w.get_value(), t.start + 0.1)), self.changed(False, False)))
            dd = Gtk.DropDown.new_from_strings(["Top", "Middle", "Bottom"])
            dd.set_selected({"top": 0, "middle": 1}.get(t.pos, 2))
            dd.connect("notify::selected", lambda w, _p: (self.checkpoint(("pos", i)), setattr(t, "pos", ["top", "middle", "bottom"][w.get_selected()]), self.changed(False, False)))
            add(dd)
            add(label("Size", dim=True))
            sz = spin(2, 25, 1, t.size * 100, 0, 3)
            sz.connect("value-changed", lambda w: (self.checkpoint(("size", i)), setattr(t, "size", w.get_value() / 100), self.changed(False, False)))
            add(sz)
            col = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
            rgba = Gdk.RGBA()
            rgba.parse(t.color)
            col.set_rgba(rgba)
            col.connect("notify::rgba", lambda w, _p: (self.checkpoint(("col", i)), setattr(t, "color", hex_of(w.get_rgba())), self.changed(False, False)))
            add(col)
            self._delete_button(add, "Delete text")
        elif k == "s":
            c = p.clips[i]
            add(label(f"Sound of {c.name}", bold=True))
            add(label("Volume", dim=True))
            cur = c.line_at(0) if not c.env else max(g for _, g in c.env)
            vs = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
            vs.set_value(cur * 100)
            vs.set_size_request(160, -1)
            vs.set_draw_value(True)
            vs.set_value_pos(Gtk.PositionType.RIGHT)
            vs.set_format_value_func(lambda sc, v: f"{int(v)}%")
            vs.set_tooltip_text("Drag the line in the Sound row to shape the volume. Right-click a dot to remove it.")
            vs.connect("value-changed", lambda w: self._set_volume(c, w.get_value() / 100, i))
            add(vs)
            add(label("Fade in", dim=True))
            f1 = spin(0, 30, 0.5, c.fade_in, 1, 4)
            add(f1)
            add(label("Fade out", dim=True))
            f2 = spin(0, 30, 0.5, c.fade_out, 1, 4)
            add(f2)
            f1.connect("value-changed", lambda w: (self.checkpoint(("fi", i)), setattr(c, "fade_in", w.get_value()), self.changed(False, False)))
            f2.connect("value-changed", lambda w: (self.checkpoint(("fo", i)), setattr(c, "fade_out", w.get_value()), self.changed(False, False)))
            self._delete_button(add, "Reset sound")

    def _delete_button(self, add, text):
        b = Gtk.Button(label=text, css_classes=["destructive-action"], hexpand=True, halign=Gtk.Align.END)
        b.connect("clicked", lambda *_: self.delete_selected())
        add(b)

    def _set_volume(self, c, vol, i):
        self.checkpoint(("vol", i))
        if c.env:
            cur = max(g for _, g in c.env) or 1.0
            c.env = [[t, g * vol / cur] for t, g in c.env]
        c.volume = vol
        self.changed(player=True, pop=False)

    def _crop_controls(self, c, add):
        info = safe_info(c.path)
        sa = info.width / info.height if info else 16 / 9
        self.crop_lock = None
        dd = Gtk.DropDown.new_from_strings([n for n, _ in ASPECTS] + ["Custom"])
        dd.set_selected(len(ASPECTS))
        dd.set_tooltip_text("Crop shape. Pick one to keep that shape while you drag the box.")
        add(dd)
        spins = []
        for nm, idx in (("Left", 0), ("Top", 1), ("Width", 2), ("Height", 3)):
            add(label(nm, dim=True))
            s = spin(0, 100, 1, c.crop[idx] * 100, 0, 3)
            spins.append(s)
            add(s)
        self._crop_ui = dict(spins=spins, busy=False, dd=dd)

        def from_spin(w):
            if not self._crop_ui["busy"]:
                self.crop_lock = None
                self.apply_crop(c, [s.get_value() / 100 for s in spins])
                dd.set_selected(len(ASPECTS))
        for s in spins:
            s.connect("value-changed", from_spin)

        def from_shape(w, _p):
            a = ASPECTS[w.get_selected()][1] if w.get_selected() < len(ASPECTS) else "custom"
            if a == "custom":
                self.crop_lock = None
                return
            if a is None:
                self.crop_lock = None
                return self.apply_crop(c, [0, 0, 1, 1])
            self.crop_lock = a                          # dragging the box now keeps this shape
            cw, ch = (a / sa, 1.0) if sa > a else (1.0, sa / a)
            self.apply_crop(c, [(1 - cw) / 2, (1 - ch) / 2, cw, ch])
        dd.connect("notify::selected", from_shape)
        allb = Gtk.Button(label="All clips", tooltip_text="Use this crop on every clip")
        allb.connect("clicked", lambda *_: self._crop_all(c))
        add(allb)
        rb = Gtk.Button(label="Remove", tooltip_text="Remove the crop from this clip")
        rb.connect("clicked", lambda *_: self._crop_remove(c))
        add(rb)
        done = Gtk.Button(label="Done", css_classes=["suggested-action"], hexpand=True, halign=Gtk.Align.END)
        done.connect("clicked", lambda *_: self._crop_done())
        add(done)

    def apply_crop(self, c, vals, quiet=False):
        """Set a clip's crop (clamped), keep the number boxes in step, and redraw."""
        if not quiet:
            self.checkpoint(("crop", id(c)))
        x, y, w, h = vals
        w, h = max(cropdrag.MIN, min(1, w)), max(cropdrag.MIN, min(1, h))
        x, y = max(0, min(1 - w, x)), max(0, min(1 - h, y))
        c.crop = [x, y, w, h]
        ui = self._crop_ui
        if ui:
            ui["busy"] = True
            for s, v in zip(ui["spins"], c.crop):
                s.set_value(round(v * 100))
            ui["busy"] = False
        self._rev += 1
        self._refresh_over()
        if not quiet:
            self.changed(player=False, pop=False)

    # --- dragging the crop box on the picture ---
    def _crop_target(self):
        """(clip, frame rect, picture aspect) while the crop editor is open on the clip under the playhead."""
        g = self.geometry(self.video.get_width(), self.video.get_height())
        if not g or not g["editing"] or not g["crop"]:
            return None
        c = self.project.clips[self.sel[1]]
        info = safe_info(c.path)
        return c, g["frame"], (info.width / info.height if info else 16 / 9)

    def _crop_begin(self, gesture, x, y):
        self._cdrag = None
        tgt = self._crop_target()
        if not tgt:
            return
        c, F, fa = tgt
        h = cropdrag.hit(c.crop, *F, x, y)
        if h:
            self._cdrag = dict(c=c, F=F, fa=fa, handle=h, orig=list(c.crop), cp=False)

    def _crop_update(self, gesture, dx, dy):
        d = self._cdrag
        if not d:
            return
        F = d["F"]
        new = cropdrag.drag(d["orig"], d["handle"], dx / F[2], dy / F[3], self.crop_lock, d["fa"])
        if not d["cp"]:
            if max(abs(a - b) for a, b in zip(new, d["orig"])) < 1e-4:
                return
            self.checkpoint()
            d["cp"] = True
        self.apply_crop(d["c"], new, quiet=True)

    def _crop_end(self, gesture, dx, dy):
        d, self._cdrag = self._cdrag, None
        if d and d["cp"]:
            ui = self._crop_ui
            if ui and not self.crop_lock:
                ui["dd"].set_selected(len(ASPECTS))
            self.changed(player=False, pop=False)

    def _crop_hover(self, ctl, x, y):
        tgt = self._crop_target()
        h = cropdrag.hit(tgt[0].crop, *tgt[1], x, y) if tgt else None
        self.stage_ov.set_cursor_from_name(cropdrag.CURSORS.get(h) if h else None)

    def _crop_all(self, c):
        self.checkpoint()
        for o in self.project.clips:
            o.crop = list(c.crop)
        self.changed(pop=False)
        self.toast("Crop applied to every clip.")

    def _crop_remove(self, c):
        self.checkpoint()
        c.crop = None
        self.crop_mode = False
        self.changed()

    def _crop_done(self):
        self.crop_mode = False
        self._crop_ui = None
        self.refresh_pop()
        self.changed(player=False, pop=False)

    # ------------------------------------------------------------ files
    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast.new(msg))
        return False

    def removed_toast(self, n):
        if n:
            self.toast(f"{n} caption(s) on the trimmed-away part were removed. Undo brings them back.")

    def toast_once(self, msg):
        self.toast(msg)
        return False

    def add_files(self, paths):
        good, bad = [], []
        for path in paths:
            try:
                probe(path)
                good.append(path)
            except Exception:
                bad.append(os.path.basename(path))
        if good:
            self.checkpoint()
            for path in good:
                self.project.add_clip(path)
            self.changed()
        if bad:
            self.toast("Could not open " + ", ".join(bad[:3]) + (" and more" if len(bad) > 3 else "") + ". Not a video?")

    def open_videos(self):
        dlg = Gtk.FileDialog(title="Add videos")
        f = Gtk.FileFilter(name="Videos")
        f.add_mime_type("video/*")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)
        dlg.open_multiple(self, None, lambda d, r: self._opened(d, r))

    def _opened(self, dlg, res):
        try:
            files = dlg.open_multiple_finish(res)
        except GLib.Error:
            return
        self.add_files([files.get_item(i).get_path() for i in range(files.get_n_items())])

    def _drop(self, target, value, x, y):
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        projs = [p for p in paths if p.endswith(".splice")]
        if projs:
            self.load_project(projs[0])
        self.add_files([p for p in paths if not p.endswith(".splice")])
        return True

    def open_project(self):
        dlg = Gtk.FileDialog(title="Open project")
        dlg.open(self, None, lambda d, r: self._proj_opened(d, r))

    def _proj_opened(self, dlg, res):
        try:
            path = dlg.open_finish(res).get_path()
        except GLib.Error:
            return
        self.load_project(path)

    def load_project(self, path):
        try:
            newp = Project.load(path)
        except Exception:
            return self.toast("That is not a Splice project.")
        self.checkpoint()
        self.project.clips[:] = newp.clips
        self.project.texts[:] = newp.texts
        self.path = path
        self.sel = None
        self.crop_mode = False
        self.changed()
        self.seek(0)
        self.dirty = False
        self._update_title()
        missing = [c.name for c in self.project.clips if not os.path.exists(c.path)]
        if missing:
            self.toast(f"{len(missing)} video file(s) are missing, for example {missing[0]}. Move them back to open this project fully.")

    def save_project(self, save_as=False):
        if self.path and not save_as:
            return self._write_project(self.path)
        dlg = Gtk.FileDialog(title="Save project", initial_name=(os.path.basename(self.path) if self.path else "untitled.splice"))
        dlg.save(self, None, lambda d, r: self._proj_saved(d, r))

    def _proj_saved(self, dlg, res, then=None):
        try:
            path = dlg.save_finish(res).get_path()
        except GLib.Error:
            return
        if not path.endswith(".splice"):
            path += ".splice"
        self._write_project(path)
        if then:
            then()

    def _write_project(self, path):
        try:
            self.project.save(path)
        except OSError as e:
            return self.toast(f"Could not save the project: {e.strerror or e}")
        self.path = path
        self.dirty = False
        self._update_title()
        self.toast("Project saved.")

    def save_video(self):
        if not self.project.clips:
            return self.toast("Add a video first.")
        if self._busy:
            return
        name = self.project.clips[0].name + "-edited.mp4"
        dlg = Gtk.FileDialog(title="Save video", initial_name=name)
        vids = os.path.expanduser("~/Videos")
        if os.path.isdir(vids):
            dlg.set_initial_folder(Gio.File.new_for_path(vids))
        dlg.save(self, None, lambda d, r: self._export_to(d, r))

    def _export_to(self, dlg, res):
        try:
            out = dlg.save_finish(res).get_path()
        except GLib.Error:
            return
        if os.path.splitext(out)[1].lower() not in exporter.FORMATS:
            out += ".mp4"
        self.export_to_path(out)

    def export_to_path(self, out, on_done=None):
        self._busy = True
        self._cancel = threading.Event()
        win = Adw.Window(transient_for=self, modal=True, title="Saving video", default_width=400, resizable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        msg = Gtk.Label(label=f"Saving {os.path.basename(out)}…", xalign=0)
        bar = Gtk.ProgressBar(show_text=True)
        cancel_b = Gtk.Button(label="Cancel", halign=Gtk.Align.END)
        cancel_b.connect("clicked", lambda *_: (self._cancel.set(), cancel_b.set_sensitive(False), msg.set_label("Cancelling…")))
        for w in (msg, bar, cancel_b):
            box.append(w)
        win.set_content(box)
        win.present()
        snap = Project.__new__(Project)
        snap.clips = copy.deepcopy(self.project.clips)
        snap.texts = copy.deepcopy(self.project.texts)
        cancel = self._cancel

        def prog(f):
            GLib.idle_add(bar.set_fraction, f)
            GLib.idle_add(bar.set_text, f"{int(f * 100)}%")

        def work():
            err, used = None, None
            try:
                dev = exporter.gpu_device()                       # first call probes the GPU (about 0.2 s)
                GLib.idle_add(msg.set_label, f"Saving {os.path.basename(out)} on your GPU…" if dev else f"Saving {os.path.basename(out)}…")
                used = exporter.export(snap, out, prog, cancel=cancel)
                if dev and used == "cpu":
                    used = "cpu-fallback"
            except exporter.ExportCancelled:
                err = "cancelled"
            except Exception as e:      # shown to the user below
                err = str(e) or type(e).__name__
            GLib.idle_add(done, err, used)

        def done(err, used=None):
            win.close()
            self._busy = False
            if err == "cancelled":
                self.toast("Saving cancelled.")
            elif err:
                dlg2 = Adw.AlertDialog(heading="Could not save the video", body=err[:600])
                dlg2.add_response("ok", "OK")
                dlg2.present(self)
            else:
                how = {"gpu": " (GPU)", "cpu": " (CPU)", "cpu-fallback": " (CPU: the GPU could not encode this video)"}.get(used, "")
                self.toast(f"Saved {os.path.basename(out)}{how}")
            if on_done:
                on_done(err)
            return False
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- keys
    def _key(self, ctl, keyval, keycode, state):
        focus = self.get_focus()
        typing = isinstance(focus, Gtk.Editable)
        w, in_popover = focus, False
        while w is not None:
            if isinstance(w, Gtk.Popover):
                in_popover = True
            w = w.get_parent()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z) and not typing:
            self.do_redo() if shift else self.do_undo()
            return True
        if ctrl and keyval in (Gdk.KEY_y, Gdk.KEY_Y) and not typing:
            self.do_redo()
            return True
        if ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.save_project()
            return True
        if typing or in_popover or ctrl:
            return False
        if keyval == Gdk.KEY_space:
            self.player.toggle()
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.tool_split()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.delete_selected()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and not isinstance(focus, Gtk.Range):
            step = (5.0 if shift else 0.5) * (1 if keyval == Gdk.KEY_Right else -1)
            self.seek(self.t + step)
            return True
        return False

    # -------------------------------------------------------------- close
    def _close_request(self, *_):
        if self._force_close:
            return False
        if self._busy and self._cancel:
            self._cancel.set()
            exporter.kill_all()
        if self.dirty and self.project.clips:
            d = Adw.AlertDialog(heading="Close without saving?", body="You have changes that are not saved in a project file.")
            d.add_response("cancel", "Keep editing")
            d.add_response("discard", "Close without saving")
            d.add_response("save", "Save project")
            d.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
            d.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
            d.set_default_response("save")
            d.set_close_response("cancel")
            d.choose(self, None, self._close_answer)
            return True
        self.player.close()
        return False

    def _close_answer(self, dlg, res):
        r = dlg.choose_finish(res)
        if r == "discard":
            self._finish_close()
        elif r == "save":
            if self.path:
                self._write_project(self.path)
                self._finish_close()
            else:
                d = Gtk.FileDialog(title="Save project", initial_name="untitled.splice")
                d.save(self, None, lambda dd, rr: self._after_save_close(dd, rr))

    def _after_save_close(self, dlg, res):
        try:
            self._proj_saved(dlg, res, then=self._finish_close)
        except GLib.Error:
            pass

    def _finish_close(self):
        self._force_close = True
        self.player.close()
        self.close()


class SpliceApp(Adw.Application):
    def __init__(self, files):
        super().__init__(application_id="io.github.gaservantes.Splice", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.files = files

    def do_activate(self):
        Gtk.Window.set_default_icon_name("io.github.gaservantes.Splice")
        win = SpliceWindow(self)
        win.present()
        projects = [f for f in self.files if f.endswith(".splice")]
        if projects:
            try:
                p = Project.load(projects[0])
                win.project.clips[:] = p.clips
                win.project.texts[:] = p.texts
                win.path = os.path.abspath(projects[0])
            except Exception as e:
                print("Could not open project:", e, file=sys.stderr)
        vids = [f for f in self.files if not f.endswith(".splice")]
        if vids:
            win.add_files([os.path.abspath(f) for f in vids])
        win.changed()
        win.seek(0)
        win.undo.clear()
        win.redo.clear()
        win.dirty = False
        win._sync_undo()
        win._update_title()
        self.win = win


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    return SpliceApp(argv).run([sys.argv[0]])
