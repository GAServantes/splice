# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Seek latency (seek call -> new frame) on a 10-minute file, plus a rapid-scrub burst."""
import os, random, sys, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib
from splice.model import Project
from splice.player import Player

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
p = Project(); c = p.add_clip(f"{D}/long10min.mp4")
frames = []
pl = Player(p, lambda t, w, h: frames.append(time.monotonic()), lambda t: None, lambda s: None)
R = random.Random(5)
loop = GLib.MainLoop()
lat = []
def phase1(i=0):
    if i >= 12:
        return phase2()
    n0 = len(frames); t0 = time.monotonic()
    pl.seek(R.uniform(5, 590))
    def poll():
        if len(frames) > n0:
            lat.append(time.monotonic() - t0); phase1(i + 1); return False
        if time.monotonic() - t0 > 5:
            lat.append(5.0); phase1(i + 1); return False
        return True
    GLib.timeout_add(5, poll)
def phase2():
    print(f"single seeks to random spots in a 10-min file (GOP 250): median {sorted(lat)[len(lat)//2]*1000:.0f} ms, worst {max(lat)*1000:.0f} ms")
    n0 = len(frames); t0 = time.monotonic(); target = [0]
    def burst(k=0):
        if k >= 100:
            GLib.timeout_add(1500, done); return False
        target[0] = R.uniform(5, 590); pl.seek(target[0], fast=True); GLib.timeout_add(15, burst, k + 1); return False
    GLib.idle_add(burst)
    def done():
        el = time.monotonic() - t0
        print(f"burst of 100 rapid seeks (15 ms apart): {len(frames)-n0} frames shown, finished settling within {el:.1f}s, final playhead {pl.t:.1f}s (target {target[0]:.1f}s)")
        ok = abs(pl.t - target[0]) < 0.01 and len(frames) > n0
        n1 = len(frames); pl.seek(100.0)
        GLib.timeout_add(1000, lambda: (print("player still responsive after burst:", len(frames) > n1), pl.close(), loop.quit()) and False)
        return False
GLib.timeout_add(1000, lambda: (pl.seek(1.0), GLib.timeout_add(800, phase1)) and False)
loop.run()
