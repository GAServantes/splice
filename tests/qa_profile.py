# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Python time goes during 1080p playback: wrap each hot callback with a timer."""
import os, sys, time, functools
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A, lanes as L, player as PL

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
acc = {}
def timed(cls, name):
    f = getattr(cls, name)
    @functools.wraps(f)
    def w(*a, **k):
        t = time.perf_counter()
        try: return f(*a, **k)
        finally:
            r = acc.setdefault(f"{cls.__name__}.{name}", [0, 0.0]); r[0] += 1; r[1] += time.perf_counter() - t
    setattr(cls, name, w)
for cls, names in ((A.SpliceWindow, ["_on_time", "_on_frame", "_update_time_label", "_refresh_over", "_draw_over", "geometry"]),
                   (A.VideoView, ["do_snapshot"]), (L.Playhead, ["draw"]), (L.Lanes, ["draw"]),
                   (PL.Player, ["_sample", "_show", "_tick"])):
    for n in names: timed(cls, n)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        w.seek(0); w.player.play(); t0 = time.monotonic()
        def stop():
            el = time.monotonic() - t0; w.player.pause()
            print(f"python time per callback over {el:.0f}s of playback (percent of one core):")
            for k, (n, s) in sorted(acc.items(), key=lambda kv: -kv[1][1]):
                print(f"  {k:28s} {n:5d} calls  {100*s/el:5.1f}%  ({1000*s/max(n,1):.2f} ms each)")
            self.quit(); return False
        GLib.timeout_add(10000, stop)
T([f"{D}/hd1080.mp4"]).run([sys.argv[0]])
