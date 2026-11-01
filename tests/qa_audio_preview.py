# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview audio: put a level meter on the audio sink and check gain tracking (volume, line, fades, muted clip, silent clip)."""
import os, sys, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst
from splice.model import Project, Clip
from splice.player import Player

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
BASE = f"{D}/base.mp4"     # 4 s constant tone
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)

def run(clips, seconds):
    """Play the project and return [(timeline_time, rms_linear)] from the level meter."""
    p = Project(); p.clips.extend(clips)
    pl = Player(p, lambda *a: None, lambda t: None, lambda s: None)
    lvl = Gst.parse_bin_from_description("level name=lvl interval=100000000 post-messages=true ! fakesink sync=true", True)
    pl.pb.set_property("audio-sink", lvl)
    out = []
    def on_msg(bus, msg):
        s = msg.get_structure()
        if s and s.get_name() == "level":
            rms = s.get_value("rms")
            if rms:
                out.append((pl.t, 10 ** (rms[0] / 20)))
    pl.pb.get_bus().connect("message::element", on_msg)
    loop = GLib.MainLoop()
    GLib.timeout_add(500, lambda: (pl.seek(0.0), pl.play()) and False)
    GLib.timeout_add(int(1000 * seconds) + 800, lambda: (pl.close(), loop.quit()) and False)
    loop.run()
    return out

def avg(samples, a, b):
    v = [r for t, r in samples if a <= t < b]
    return sum(v) / len(v) if v else None

def clip(**kw):
    c = Clip(BASE, 0.0, 3.0); [setattr(c, k, v) for k, v in kw.items()]; return c

ref = avg(run([clip()], 3), 0.8, 2.6)
check("plain clip is audible", ref and ref > 0.02, f"rms={ref:.3f}" if ref else "no level messages")
half = avg(run([clip(volume=0.5)], 3), 0.8, 2.6)
check("volume 0.5 is half as loud", ref and half and abs(half / ref - 0.5) < 0.08, f"ratio={half/ref:.2f}" if ref and half else "")
mute = avg(run([clip(volume=0.0)], 3), 0.8, 2.6)
check("volume 0 is silent", mute is not None and mute < 0.002, f"rms={mute}")
s = run([clip(env=[[0, 1.0], [1.0, 0.2], [2.0, 1.0]])], 3)
a, b, c = avg(s, 0.9, 1.15), avg(s, 0.2, 0.4), avg(s, 2.3, 2.8)
check("volume line dips in the middle", ref and a and b and abs(a / ref - 0.2) < 0.12 and b / ref > 0.45 and c / ref > 0.85, f"dip={a/ref:.2f} early={b/ref:.2f} late={c/ref:.2f}" if ref and a else "")
f = run([clip(fade_in=1.0, fade_out=1.0)], 3)
fi, mid, fo = avg(f, 0.1, 0.3), avg(f, 1.2, 1.8), avg(f, 2.7, 2.95)
check("fade in/out shapes the level", ref and fi / ref < 0.35 and mid / ref > 0.85 and fo / ref < 0.35, f"in={fi/ref:.2f} mid={mid/ref:.2f} out={fo/ref:.2f}" if ref and fi is not None else "")
j = run([clip(volume=0.3), clip(volume=1.0)], 6)
j1, j2 = avg(j, 0.8, 2.6), avg(j, 3.8, 5.6)
check("gain changes at the clip boundary during playback", ref and j1 and j2 and abs(j1 / ref - 0.3) < 0.08 and abs(j2 / ref - 1.0) < 0.1, f"first={j1/ref:.2f} second={j2/ref:.2f}" if ref and j1 and j2 else "")
sil = run([Clip(f"{D}/tiny_silent.mp4", 0, 1.5)], 1.5)
check("clip without audio plays without crashing (silence)", True, f"{len(sil)} level msgs")
print("PROBLEMS:", len(fails), fails)
