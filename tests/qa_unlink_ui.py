# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unlinking sound in the real window: the U key and the Unlink tool, dragging the unlinked sound along the Sound
row (it clicks onto clip edges), trimming its edges, the picture staying put, the editor row, Delete, undo, and
linking back. Drags go through the timeline's own drag handlers at real pixel positions.
   GDK_BACKEND=x11 xvfb-run -a -s "-screen 0 1280x800x24" python3 tests/qa_unlink_ui.py [shots_dir]"""
import os, subprocess, sys, traceback
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gdk, Gtk
from splice import app as A
from splice import lanes as L

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(name)


def grab(name):
    if SHOTS:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1100x760",
                        "-i", os.environ["DISPLAY"] + "+0,0", "-frames:v", "1", os.path.join(SHOTS, name)], check=True)


def labels(w):
    out, ch = [], w.pop.get_first_child()
    while ch:
        if isinstance(ch, Gtk.Label):
            out.append(ch.get_text())
        elif isinstance(ch, Gtk.Button):
            out.append("[" + (ch.get_label() or "") + "]")
        ch = ch.get_next_sibling()
    return out


def drag(lanes, x, y, dx, dy=0.0, steps=6):
    lanes._begin(None, x, y)
    for k in range(1, steps + 1):
        lanes._update(None, dx * k / steps, dy * k / steps)
    lanes._end(None, dx, dy)


class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        w = self.win
        P = w.project
        for path in (f"{M}/c1.mp4", f"{M}/c2.mp4"):
            c = P.add_clip(path)
            c.src_in, c.src_out = 0.0, 4.0
        w.changed()
        w.lanes.pps = 40.0
        w.lanes.refresh()
        steps = iter(self.steps(w))

        def tick():
            try:
                delay = next(steps)
            except StopIteration:
                w.player.pause()
                w._force_close = True
                self.quit()
                return False
            except Exception:
                traceback.print_exc()
                fails.append("exception")
                w._force_close = True
                self.quit()
                return False
            GLib.timeout_add(delay or 300, tick)
            return False
        GLib.timeout_add(1500, tick)

    def steps(self, w):
        P, lanes = w.project, w.lanes
        sy = L.S_Y + L.S_H / 2
        yield 300
        # 1. U on clip 2 (playhead inside it)
        w.seek(5.0)
        w.select(None)
        yield 300
        w._key(None, Gdk.KEY_u, 0, 0)
        yield 400
        check("U unlinks the clip under the playhead", not P.clips[1].linked and len(P.sounds) == 1
              and P.sounds[0].start == 4.0, f"sounds {[(s.start, s.src_in, s.src_out) for s in P.sounds]}")
        check("the unlinked sound is selected, with its own editor",
              w.sel == ("a", 0) and "Unlinked sound of c2" in labels(w) and "[Delete sound]" in labels(w)
              and "[Link again]" in labels(w), str(labels(w)))
        grab("unlink_1_unlinked.png")
        # 2. drag it 1 s left along the Sound row (grab off the volume line)
        x = lanes.x_of(6.0)
        drag(lanes, x, L.S_Y + L.S_H - 6, -1.0 * lanes.pps)
        yield 300
        check("dragging moves the sound, not the picture", abs(P.sounds[0].start - 3.0) < 0.03
              and P.clip_start(1) == 4.0 and P.clips[1].src_in == 0.0, f"start {P.sounds[0].start:.3f}")
        # 3. a small drag near a clip edge clicks onto it (the sound's start onto 4.0 s)
        drag(lanes, lanes.x_of(5.5), L.S_Y + L.S_H - 6, 0.85 * lanes.pps)
        yield 300
        check("it clicks onto a clip edge", abs(P.sounds[0].start - 4.0) < 1e-6, f"start {P.sounds[0].start:.4f}")
        # 4. trim its right edge 1.5 s shorter, then its left edge 0.5 s
        s = P.sounds[0]
        drag(lanes, lanes.x_of(s.end) - 4, sy, -1.5 * lanes.pps)
        yield 300
        check("dragging its right edge trims it", abs(s.src_out - 2.5) < 0.03 and s.start == 4.0, f"{s.src_in:.2f}-{s.src_out:.2f}")
        drag(lanes, lanes.x_of(s.start) + 3, sy, 0.5 * lanes.pps)
        yield 300
        check("dragging its left edge trims it and keeps the rest in place",
              abs(s.src_in - 0.5) < 0.03 and abs(s.start - 4.5) < 0.03, f"in {s.src_in:.2f} start {s.start:.2f}")
        # 5. the picture can now be trimmed without touching the sound
        drag(lanes, lanes.x_of(4.0) + 3, L.V_Y + L.V_H / 2, 1.0 * lanes.pps)
        yield 400
        check("trimming the picture leaves the unlinked sound alone", abs(P.clips[1].src_in - 1.0) < 0.05
              and abs(s.start - 4.5) < 0.03, f"clip in {P.clips[1].src_in:.2f}, sound start {s.start:.2f}")
        # 6. a volume point on the unlinked sound
        before = len(s.env)
        gx = lanes.x_of(s.start + 0.8)
        drag(lanes, gx, lanes._gain_y(s.line_at(0.8)), 0, 15)
        yield 300
        check("its volume line takes a point", len(s.env) > before and min(g for _, g in s.env) < s.volume - 0.05, str(s.env))
        grab("unlink_2_edited.png")
        # 7. the clip's own Sound row and its editor
        w.select(("s", 1))
        yield 300
        check("the clip's sound says it's unlinked, with Link sound again",
              any("Unlinked" in t for t in labels(w)) and "[Link sound again]" in labels(w), str(labels(w)))
        w.select(("v", 1))
        yield 200
        check("the clip's editor offers Link sound again", "[Link sound again]" in labels(w))
        # 8. Delete removes the unlinked sound, undo brings it back
        w.select(("a", 0))
        w._key(None, Gdk.KEY_Delete, 0, 0)
        yield 300
        check("Delete removes the unlinked sound", not P.sounds and not P.clips[1].linked)
        w.do_undo()
        yield 300
        check("undo brings it back where it was", len(P.sounds) == 1 and abs(P.sounds[0].start - 4.5) < 0.03)
        # 9. link again from the sound's editor (U with the sound selected)
        w.select(("a", 0))
        w._key(None, Gdk.KEY_u, 0, 0)
        yield 300
        check("U on the unlinked sound links it back", P.clips[1].linked and not P.sounds)
        # 10. the Unlink tool button on the first clip, then play across it (no errors, playhead moves)
        w.seek(1.0)
        w.select(("v", 0))
        w.tool_unlink()
        P.move_sound(0, 2.0)
        w.changed()
        w.seek(0.0)
        w.player.play()
        yield 3000
        w.player.pause()
        check("playing with an unlinked sound runs", w.t > 2.0 and len(w.player.loose.pbs) == 1, f"t={w.t:.2f}")
        grab("unlink_3_played.png")
        # 11. a clip without sound can't be unlinked
        P.add_clip(f"{M}/c3_silent.mp4")
        w.changed()
        w.seek(P.duration - 0.5)
        w.select(None)
        n = len(P.sounds)
        w.tool_unlink()
        yield 300
        check("a silent clip can't be unlinked", len(P.sounds) == n and P.clips[-1].linked)
        # 12. saving the video from the window includes the unlinked sound (c1's 300 Hz under c2's picture)
        import tempfile
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "saved.mp4")
        P.move_sound(0, 5.0)
        w.changed()
        res = []
        w.export_to_path(out, on_done=res.append)
        for _ in range(300):
            if res:
                break
            yield 100
        tone = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-ss", "5.5", "-t", "1", "-i", out, "-af", "highpass=f=250,lowpass=f=350,"
                               "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        mean = [l for l in tone.splitlines() if "mean_volume" in l]
        check("Save video includes the unlinked sound", res == [None] and os.path.exists(out) and mean
              and float(mean[0].split(":")[1].split()[0]) > -40, f"{res} {mean}")
        # 13. a project file with unlinked sound opens with it (also from the command line)
        proj = os.path.join(tmp, "p.splice")
        P.save(proj)
        w.load_project(proj)
        yield 300
        check("opening a project keeps its unlinked sound", len(P.sounds) == 1 and not P.clips[0].linked)
        T.saved_project = proj
        yield 200


T([]).run([sys.argv[0]])


class Open(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        P = self.win.project
        check("a project given on the command line opens with its unlinked sound", len(P.sounds) == 1, f"{len(P.sounds)}")
        self.win._force_close = True
        GLib.idle_add(self.quit)


if getattr(T, "saved_project", None):
    Open([T.saved_project]).run([sys.argv[0]])
print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
