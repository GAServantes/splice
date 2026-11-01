# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Playback cost: CPU and memory of the player + window while playing 1080p, plus a leak check."""
import os, sys, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
def rss(): return int(open("/proc/self/statm").read().split()[1]) * 4096 / 1e6
def cpu():
    f = open("/proc/self/stat").read().split(")")[1].split(); return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        w = self.win
        mode = os.environ.get("QA_MODE", "")
        if "nolanes" in mode: w.lanes.queue_draw = lambda *a: None
        if "noover" in mode: w.over.queue_draw = lambda *a: None
        w.seek(0); w.player.play()
        samples = []
        t0, c0 = time.monotonic(), cpu()
        def tick():
            el = time.monotonic() - t0
            samples.append((el, rss(), cpu() - c0))
            if el >= 12:
                w.player.pause()
                print(f"played {w.t:.1f}s of timeline in {el:.1f}s wall")
                for el_, r, c in samples[-1:]:
                    print(f"  t={el_:5.1f}s  RSS={r:6.0f} MB  CPU so far={c:5.1f}s  ({100*c/max(el_,0.1):4.0f}% of one core)")
                grow = samples[-1][1] - samples[len(samples)//4][1]
                print(f"RSS growth over last 3/4 of run: {grow:+.0f} MB")
                self.quit(); return False
            return True
        GLib.timeout_add(500, tick)
T([f"{D}/hd1080.mp4"]).run([sys.argv[0]])
