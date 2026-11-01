# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless player test: frames arrive, seeking maps to clips, playback crosses a clip boundary."""
import os, sys
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
from gi.repository import GLib
from splice.model import Project
from splice.player import Player

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
p = Project()
a = p.add_clip(f"{M}/c1.mp4"); a.src_in, a.src_out = 0, 1.0
b = p.add_clip(f"{M}/c2.mp4"); b.src_in, b.src_out = 2, 3.0
loop = GLib.MainLoop()
frames, times = [], []
pl = Player(p, lambda tex, w, h: frames.append((w, h)), times.append, lambda s: None)
pl.seek(0.5)
def phase2():
    print("after seek: frames", len(frames), "size", frames[-1] if frames else None, "t", pl.t)
    pl.seek(0.0); pl.play()
    GLib.timeout_add(2500, finish)
    return False
def finish():
    print("played to t=%.2f idx=%d playing=%s max_t=%.2f" % (pl.t, pl._idx, pl.playing, max(times)))
    ok = frames and len(times) > 20 and max(times) <= 2.01 and max(times) > 1.2 and abs(pl.t - 2.0) < 0.1 and not pl.playing
    print("OK" if ok else "FAIL"); pl.close(); loop.quit(); return False
GLib.timeout_add(800, phase2)
loop.run()
