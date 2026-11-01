# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-hour timeline: draw time and sanity at several zoom levels, scrolling, and peaks load."""
import os, sys, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A, lanes as L
from splice.model import Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
draws = []
orig = L.Lanes.draw
def timed(self, *a):
    t = time.perf_counter(); orig(self, *a); draws.append(time.perf_counter() - t)
L.Lanes.draw = timed
def rss(): return int(open("/proc/self/statm").read().split()[1]) * 4096 / 1e6

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        w.add_files([f"{D}/long10min.mp4"] * 6)
        for i in range(40): w.project.texts.append(Text(f"caption {i}", i * 90.0, i * 90.0 + 5))
        w.changed()
        steps = [("fit (pps=2)", 2.0), ("default (pps=24)", 24.0), ("close (pps=100)", 100.0), ("max zoom (pps=400)", 400.0), ("default again", 24.0)]
        def run(i=0):
            if i >= len(steps):
                print(f"RSS now {rss():.0f} MB"); self.quit(); return False
            name, pps = steps[i]
            w.lanes.pps = pps; w.lanes.refresh()
            adj = w.lanes.hadj
            GLib.timeout_add(700, lambda: after(i, name, pps, adj))
            return False
        def after(i, name, pps, adj):
            draws.clear()
            for k in range(5):   # scroll across the timeline and force redraws
                adj.set_value(min(adj.get_upper() - adj.get_page_size(), k * adj.get_upper() / 5)); w.lanes.queue_draw()
            def fin():
                mx = max(draws) * 1000 if draws else -1
                print(f"{name:20s} viewport={w.lanes.get_width():5d}px content={int(w.lanes.hadj.get_upper()):8d}px  draws={len(draws):2d} slowest={mx:6.1f} ms  duration={w.project.duration/60:.0f} min")
                run(i + 1); return False
            GLib.timeout_add(900, fin); return False
        GLib.timeout_add(2500, run)
T([]).run([sys.argv[0]])
