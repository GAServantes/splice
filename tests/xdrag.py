# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the timeline with real mouse events (xdotool) under Xvfb and check the edits."""
import os, subprocess, sys, threading, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A, lanes as L
from splice.model import Text

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name, info)
    if not ok: fails.append(name)

def main_call(fn):
    ev, res = threading.Event(), []
    def run():
        try: res.append(fn())
        except Exception as e: res.append(e)
        ev.set(); return False
    GLib.idle_add(run); ev.wait(10)
    if res and isinstance(res[0], Exception): raise res[0]
    return res[0] if res else None

def xd(*a): subprocess.run(["xdotool", *map(str, a)], check=True)
def drag(x0, y0, x1, y1):
    xd("mousemove", x0, y0); time.sleep(.15); xd("mousedown", 1); time.sleep(.15)
    n = 6
    for k in range(1, n + 1):
        xd("mousemove", int(x0 + (x1 - x0) * k / n), int(y0 + (y1 - y0) * k / n)); time.sleep(.05)
    xd("mouseup", 1); time.sleep(.3)

def driver(app):
    w = app.win
    time.sleep(1.5)
    from gi.repository import Graphene
    def origin():
        ok, pt = w.lanes.compute_point(w, Graphene.Point().init(0, 0)); return pt.x, pt.y
    xd("mousemove", 400, 600); time.sleep(.4); xd("mousemove", 410, 610); time.sleep(.4)
    ox, oy = main_call(origin)
    sx = 410 - (main_call(lambda: w.lanes._mouse_x) + ox)
    sy = 610 - (main_call(lambda: w.lanes._mouse_y) + oy)
    print("calibration shift", round(sx, 1), round(sy, 1))
    def pos(t, y):   # timeline seconds + lane y -> screen coords
        return int(w.lanes.x_of(t) + ox + sx), int(y + oy + sy)
    P = w.project
    d0 = [c.duration for c in P.clips]
    n0 = len(w.undo)
    # 1. trim right edge of clip 1 by 2 s (drag left 2*pps)
    x, y = main_call(lambda: pos(6, L.V_Y + L.V_H / 2))
    drag(x - 3, y, x - 3 - int(2 * w.lanes.pps), y)
    check("trim right edge", abs(P.clips[0].duration - 4.0) < 0.2, f"dur={P.clips[0].duration:.2f}")
    check("texts ripple after trim", abs(P.texts[1].start - 10.0) < 0.2, f"start={P.texts[1].start:.2f}")
    # 2. reorder: drag clip 2 (now 4..10) right past clip 3
    names = [c.name for c in P.clips]
    c3 = P.clips[2]; off3 = P.texts[1].start - P.clip_start(2)
    x, y = main_call(lambda: pos(P.clip_start(1) + 3, L.V_Y + L.V_H / 2))
    drag(x, y, x + int(7 * w.lanes.pps), y)
    check("reorder clips", [c.name for c in P.clips] == [names[0], names[2], names[1]], str([c.name for c in P.clips]))
    check("caption travelled with its clip during the drag", abs(P.texts[1].start - (P.clip_start(P.clips.index(c3)) + off3)) < 0.05,
          f"caption at {P.texts[1].start:.2f}, clip now starts {P.clip_start(1):.2f}, offset {off3:.2f}")
    # 3. text move: drag text 0 right by 1 s
    s0 = P.texts[0].start
    x, y = main_call(lambda: pos(P.texts[0].start + 1, L.T_Y + L.T_H / 2))
    drag(x, y, x + int(1 * w.lanes.pps), y)
    check("move text", abs(P.texts[0].start - (s0 + 1)) < 0.2, f"start={P.texts[0].start:.2f}")
    # 4. volume line: drag the flat line of clip 1 down to ~half
    c = P.clips[0]
    x, y = main_call(lambda: pos(1.5, w.lanes._gain_y(c.line_at(1.5))))
    _, y2 = main_call(lambda: pos(1.5, w.lanes._gain_y(0.4)))
    drag(x, y, x, y2)
    check("volume point added", len(c.env) >= 3 and min(g for _, g in c.env) < 0.6, str(c.env))
    # 5. undo steps back through every edit
    n = len(w.undo) - n0
    for _ in range(n): main_call(w.do_undo)
    back = [round(c.duration, 1) for c in P.clips]
    check("undo restores everything", back == [round(v, 1) for v in d0] and not P.clips[0].env, str(back))
    for _ in range(n): main_call(w.do_redo)
    check("redo reapplies", abs(P.clips[0].duration - 4.0) < 0.2)
    main_call(lambda: setattr(w, "_force_close", True))
    main_call(w.close)
    app.quit_flag = True

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        w = self.win
        w.project.texts.append(Text("One", 1.0, 3.0)); w.project.texts.append(Text("Two", 12.0, 14.0))
        w.changed(); w.seek(0.0)
        threading.Thread(target=driver, args=(self,), daemon=True).start()
T([f"{M}/c1.mp4", f"{M}/c2.mp4", f"{M}/c3_silent.mp4"]).run([sys.argv[0]])
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
