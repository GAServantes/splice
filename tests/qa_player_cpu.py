# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Player-only CPU while playing 1080p for 10 s, for different sink pipelines."""
import os, sys, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib, Gst
from splice import player as PL
from splice.model import Project
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
def cpu():
    f = open("/proc/self/stat").read().split(")")[1].split(); return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")
variants = {
  "A current (convert then scale, bytes copy)": ("videoconvert ! videoscale ! video/x-raw,format=RGB,width=960,pixel-aspect-ratio=1/1", "bytes"),
  "B scale first, then convert":               ("videoscale ! video/x-raw,width=[1,960],height=[1,540],pixel-aspect-ratio=1/1 ! videoconvert ! video/x-raw,format=RGB", "bytes"),
  "C B + cap to 30 fps":                       ("videorate drop-only=true max-rate=30 ! videoscale ! video/x-raw,width=[1,960],height=[1,540],pixel-aspect-ratio=1/1 ! videoconvert ! video/x-raw,format=RGB", "bytes"),
  "D B, frames discarded (no texture)":        ("videoscale ! video/x-raw,width=[1,960],height=[1,540],pixel-aspect-ratio=1/1 ! videoconvert ! video/x-raw,format=RGB", "discard"),
}
name = sys.argv[1]
desc, mode = variants[name]
orig = Gst.parse_bin_from_description
Gst.parse_bin_from_description = lambda d, g: orig(desc + " ! appsink name=sink emit-signals=true sync=true max-buffers=1 drop=true", g)
if mode == "discard":
    PL.Player._show = lambda self, *a: False
p = Project(); c = p.add_clip(os.path.join(D, "hd1080.mp4"))
n = [0]
pl = PL.Player(p, lambda t, w, h: n.__setitem__(0, n[0] + 1), lambda t: None, lambda s: None)
loop = GLib.MainLoop()
def go():
    pl.seek(0.0)
    def start():
        c0, t0 = cpu(), time.monotonic(); pl.play()
        def stop():
            el = time.monotonic() - t0; used = cpu() - c0
            pl.close(); print(f"{name:46s} {100*used/el:5.0f}% of one core, {n[0]/el:4.1f} frames/s shown"); loop.quit(); return False
        GLib.timeout_add(10000, stop); return False
    GLib.timeout_add(800, start); return False
GLib.idle_add(go); loop.run()
