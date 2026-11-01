# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Player QA over the media matrix (silent audio sink, no window)."""
import os, sys, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib
from splice.model import Project
from splice.player import Player
from splice.media import probe

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
names = [n for n in sorted(os.listdir(D)) if n not in ("garbage.mp4", "audio_only.mp3", "long10min.mp4", "tones.mp4")]
loop = GLib.MainLoop()
results = []

def run(i):
    if i >= len(names):
        loop.quit(); return False
    name = names[i]
    path = os.path.join(D, name)
    p = Project(); c = p.add_clip(path)
    frames, times = [], []
    pl = Player(p, lambda tex, w, h: frames.append((w, h)), times.append, lambda s: None)
    info = probe(path)
    mid = min(c.duration - 0.8, 1.0)
    pl.seek(max(0.0, mid))
    def after_seek():
        got = frames[-1] if frames else None
        t0 = time.monotonic(); n0 = len(times)
        pl.play()
        def after_play():
            el = time.monotonic() - t0
            adv = (max(times[n0:] or [0]) - max(0.0, mid))
            pl.close()
            exp_ar = info.width / info.height
            ar_ok = got and abs(got[0] / got[1] - exp_ar) < 0.02
            results.append((name, f"frame={got}", f"expect_aspect={exp_ar:.2f}", "aspect OK" if ar_ok else "<<< ASPECT WRONG" if got else "<<< NO FRAME",
                            f"played {adv:.2f}s in {el:.2f}s", "" if 0.7 * el < adv < 1.2 * el else "<<< NOT REAL TIME"))
            GLib.timeout_add(50, run, i + 1)
            return False
        GLib.timeout_add(1500, after_play)
        return False
    GLib.timeout_add(900, after_seek)
    return False
GLib.idle_add(run, 0)
loop.run()
for r in results: print("  ".join(x for x in r if x))
# missing file must not crash
p = Project(); c = p.add_clip(os.path.join(D, "base.mp4")); c.path = "/nonexistent/x.mp4"
pl = Player(p, lambda *a: None, lambda t: None, lambda s: None)
pl.seek(1.0); pl.play(); time.sleep(0.2); pl.pause(); pl.close(); print("missing file: no crash")
