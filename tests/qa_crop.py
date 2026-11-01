# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Crop dragging with real mouse events: corners, edges, move, aspect lock, clamping, number boxes, undo, export size."""
import os, subprocess, sys, tempfile, threading, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Graphene", "1.0")
from gi.repository import GLib, Graphene
from splice import app as A, export as E

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
def call(fn):
    ev, res = threading.Event(), []
    def run():
        try: res.append(fn())
        except Exception as e: res.append(e)
        ev.set(); return False
    GLib.idle_add(run); ev.wait(10)
    if res and isinstance(res[0], Exception): raise res[0]
    return res[0] if res else None
def xd(*a): subprocess.run(["xdotool", *map(str, a)], check=True)
def drag(x0, y0, x1, y1, steps=6):
    xd("mousemove", x0, y0); time.sleep(.15); xd("mousedown", 1); time.sleep(.15)
    for k in range(1, steps + 1):
        xd("mousemove", int(x0 + (x1 - x0) * k / steps), int(y0 + (y1 - y0) * k / steps)); time.sleep(.05)
    xd("mouseup", 1); time.sleep(.3)

def driver(app):
    w = app.win; P = w.project
    time.sleep(1.5)
    ox, oy = call(lambda: (lambda p: (p.x, p.y))(w.lanes.compute_point(w, Graphene.Point().init(0, 0))[1]))
    xd("mousemove", 400, 600); time.sleep(.4); xd("mousemove", 410, 610); time.sleep(.4)
    sx = 410 - (call(lambda: w.lanes._mouse_x) + ox); sy = 610 - (call(lambda: w.lanes._mouse_y) + oy)
    call(lambda: w.seek(1.0)); call(w.tool_crop); time.sleep(.5)
    c = P.clips[0]
    def F():   # frame rect on the stage and the stage's screen origin
        g = w.geometry(w.video.get_width(), w.video.get_height()); p = w.video.compute_point(w, Graphene.Point().init(0, 0))[1]
        return g["frame"], p.x + sx, p.y + sy
    def pt(frac_x, frac_y):
        (fx, fy, fw, fh), px, py = call(F)
        return int(px + fx + frac_x * fw), int(py + fy + frac_y * fh)
    start = list(c.crop)                                  # default [0.1, 0.1, 0.8, 0.8]
    # 1. move: drag from the middle of the box
    x, y = pt(0.5, 0.5); (fx, fy, fw, fh), _, _ = call(F)
    drag(x, y, x + int(0.05 * fw), y + int(0.04 * fh))
    check("dragging inside the box moves it", abs(c.crop[0] - (start[0] + 0.05)) < 0.02 and abs(c.crop[1] - (start[1] + 0.04)) < 0.02 and abs(c.crop[2] - start[2]) < 1e-6, str([round(v, 3) for v in c.crop]))
    # 2. south-east corner
    before = list(c.crop); x, y = pt(before[0] + before[2], before[1] + before[3])
    drag(x, y, x - int(0.1 * fw), y - int(0.1 * fh))
    check("dragging the bottom-right corner resizes it", abs(c.crop[2] - (before[2] - 0.1)) < 0.02 and abs(c.crop[3] - (before[3] - 0.1)) < 0.02 and abs(c.crop[0] - before[0]) < 1e-6, str([round(v, 3) for v in c.crop]))
    # 3. west edge
    before = list(c.crop); x, y = pt(before[0], before[1] + before[3] / 2)
    drag(x, y, x + int(0.08 * fw), y)
    check("dragging the left edge changes only the left side", abs(c.crop[0] - (before[0] + 0.08)) < 0.02 and abs(c.crop[1] - before[1]) < 1e-6 and abs(c.crop[3] - before[3]) < 1e-6, str([round(v, 3) for v in c.crop]))
    # 4. number boxes follow the drag
    spins = call(lambda: [s.get_value() for s in w._crop_ui["spins"]])
    check("the number boxes show the dragged values", all(abs(s - v * 100) <= 1 for s, v in zip(spins, c.crop)), f"{spins} vs {[round(v*100) for v in c.crop]}")
    # 5. dragging far outside clamps to the picture
    before = list(c.crop); x, y = pt(before[0] + before[2], before[1] + before[3])
    drag(x, y, x + 600, y + 600)
    check("dragging past the picture edge stops at the edge", abs(c.crop[0] + c.crop[2] - 1) < 1e-6 and abs(c.crop[1] + c.crop[3] - 1) < 1e-6, str([round(v, 3) for v in c.crop]))
    # 6. cursor changes over handles
    x, y = pt(c.crop[0], c.crop[1]); xd("mousemove", x - 8, y - 8); xd("mousemove", x, y); time.sleep(.4)
    name = call(lambda: (w.stage_ov.get_cursor() or None) and w.stage_ov.get_cursor().get_name())
    check("pointer shows a resize cursor over a corner", name == "nwse-resize", str(name))
    # 7. aspect lock: choose 1:1, then drag a corner
    call(lambda: w._crop_ui["dd"].set_selected(3)); time.sleep(.4)              # "1:1"
    check("choosing 1:1 makes a square box in pixels", abs((c.crop[2] * 1280) / (c.crop[3] * 720) - 1) < 0.01, str([round(v, 3) for v in c.crop]))
    before = list(c.crop); x, y = pt(before[0] + before[2], before[1] + before[3])
    drag(x, y, x - int(0.05 * fw), y - int(0.02 * fh))
    check("dragging a corner keeps the square shape", abs((c.crop[2] * 1280) / (c.crop[3] * 720) - 1) < 0.01 and c.crop[2] < before[2], str([round(v, 3) for v in c.crop]))
    check("the shape stays on 1:1 in the menu", call(lambda: w._crop_ui["dd"].get_selected()) == 3)
    # 8. typing a number unlocks it
    call(lambda: w._crop_ui["spins"][2].set_value(40)); time.sleep(.3)
    check("typing a number switches the shape to Custom and unlocks", call(lambda: w._crop_ui["dd"].get_selected()) == len(A.ASPECTS) and w.crop_lock is None)
    # 9. outside the box does nothing
    before = list(c.crop); x, y = pt(0.02, 0.02)
    drag(x, y, x + 60, y + 60)
    check("dragging outside the box changes nothing", c.crop == before, str([round(v, 3) for v in c.crop]))
    # 10. undo walks back
    n0 = len(w.undo); call(w.do_undo); call(w.do_undo)
    check("undo steps back through crop drags", len(w.undo) == n0 - 2)
    for _ in range(n0): call(w.do_undo)
    # 11. export uses the dragged crop
    call(lambda: setattr(w, "_force_close", False))
    call(lambda: w.select(("v", 0))); call(w.tool_crop)
    c = P.clips[0]; c.crop = [0.25, 0.25, 0.5, 0.5]; call(lambda: w.changed(player=False))
    x, y = pt(0.5, 0.5); (fx, fy, fw, fh), _, _ = call(F); drag(x, y, x + int(0.1 * fw), y)
    out = os.path.join(tempfile.mkdtemp(), "o.mp4"); E.export(P, out)
    dims = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    cx, cy, cw, ch = E.crop_rect(c, __import__("splice.media", fromlist=["probe"]).probe(c.path))
    check("exported size matches the dragged box", dims == f"{cw},{ch}" and cx > 0.25 * 1280, f"{dims} expected {cw},{ch} at x={cx}")
    call(lambda: setattr(w, "_force_close", True)); call(w.close)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        threading.Thread(target=driver, args=(self,), daemon=True).start()
T([f"{M}/c1.mp4", f"{M}/c2.mp4"]).run([sys.argv[0]])
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
