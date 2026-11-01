# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scroll wheel on the timeline, with real wheel events: Alt+scroll and Ctrl+scroll zoom around the pointer, plain scroll pans."""
import os, subprocess, sys, threading, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Graphene", "1.0")
from gi.repository import GLib, Graphene
from splice import app as A, lanes as L

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
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
def wheel(button, times=1, mod=None):
    if mod: xd("keydown", mod); time.sleep(.1)
    for _ in range(times): xd("click", button); time.sleep(.12)
    if mod: xd("keyup", mod); time.sleep(.1)
    time.sleep(.2)

def driver(app):
    w = app.win; ln = w.lanes
    time.sleep(1.5)
    ox, oy = call(lambda: (lambda p: (p.x, p.y))(ln.compute_point(w, Graphene.Point().init(0, 0))[1]))
    xd("mousemove", 400, 600); time.sleep(.4); xd("mousemove", 410, 610); time.sleep(.4)
    sx = 410 - (call(lambda: ln._mouse_x) + ox); sy = 610 - (call(lambda: ln._mouse_y) + oy)
    def at(widget_x, widget_y): xd("mousemove", int(widget_x + ox + sx), int(widget_y + oy + sy)); time.sleep(.3)
    y = L.S_Y + 20
    pps0 = call(lambda: ln.pps)
    # Alt+scroll up zooms in, anchored under the pointer
    at(400, y); t_before = call(lambda: ln.t_of(400))
    wheel(4, 3, "alt")
    pps1 = call(lambda: ln.pps); t_after = call(lambda: ln.t_of(400))
    check("Alt+scroll up zooms in", pps1 > pps0 * 1.4, f"{pps0:.1f} -> {pps1:.1f} px/s")
    check("the moment under the pointer stays under the pointer", abs(t_after - t_before) < 0.15, f"{t_before:.2f}s -> {t_after:.2f}s")
    # Alt+scroll down zooms out
    wheel(5, 3, "alt")
    pps2 = call(lambda: ln.pps)
    check("Alt+scroll down zooms back out", abs(pps2 - pps0) < pps0 * 0.05, f"{pps2:.1f} px/s")
    # Ctrl still works
    wheel(4, 2, "ctrl"); pps3 = call(lambda: ln.pps)
    check("Ctrl+scroll still zooms", pps3 > pps2 * 1.2, f"{pps3:.1f}")
    wheel(5, 2, "ctrl")
    # zoom limits
    wheel(4, 40, "alt"); hi = call(lambda: ln.pps)
    check("zoom in stops at the maximum", abs(hi - 400) < 1, f"{hi:.0f}")
    wheel(5, 80, "alt"); lo = call(lambda: ln.pps)
    check("zoom out stops at the minimum", abs(lo - 1.0) < 0.01, f"{lo:.2f}")
    # plain scroll pans, does not zoom
    call(lambda: ln.zoom(24 / ln.pps)); time.sleep(.2)
    call(lambda: w.lanes.hadj.set_value(0)); pps4 = call(lambda: ln.pps)
    at(400, y); wheel(5, 3)
    check("plain scroll pans the timeline without zooming", call(lambda: ln.pps) == pps4 and call(lambda: ln.hadj.get_value()) > 50, f"offset {call(lambda: ln.hadj.get_value()):.0f}px")
    # scrolling over the preview must not zoom the timeline
    pps5 = call(lambda: ln.pps); xd("mousemove", 500, 250); time.sleep(.3); wheel(4, 3, "alt")
    check("Alt+scroll over the picture leaves the timeline zoom alone", call(lambda: ln.pps) == pps5)
    call(lambda: setattr(w, "_force_close", True)); call(w.close)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        for i in range(6): w.project.add_clip(f"{D}/long10min.mp4")
        w.changed()
        threading.Thread(target=driver, args=(self,), daemon=True).start()
T([]).run([sys.argv[0]])
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
