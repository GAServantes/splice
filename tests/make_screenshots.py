# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerates docs/screenshots/*.png under Xvfb (never touches the live desktop):
   GDK_BACKEND=x11 xvfb-run -a -s "-screen 0 1280x800x24" python3 tests/make_screenshots.py
Needs tests/media_qa/demo.mp4 (tests/make_media.sh)."""
import os, subprocess, sys
os.environ["SPLICE_NOAUDIO"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A
from splice.model import Text

DEMO = os.path.join(ROOT, "tests", "media_qa", "demo.mp4")
OUT = os.path.join(ROOT, "docs", "screenshots")

def grab(name):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1100x760", "-i", os.environ["DISPLAY"] + "+0,0",
                    "-frames:v", "1", os.path.join(OUT, name)], check=True)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        w = self.win
        P = w.project
        for a, b in ((1.0, 9.0), (11.0, 19.0), (20.0, 23.5)):
            c = P.add_clip(DEMO)
            c.src_in, c.src_out = a, b
        P.clips[1].env = [[0, 1.0], [2.5, 1.0], [3.5, 0.3], [5.0, 0.3], [6.0, 1.0]]
        P.clips[2].fade_out = 2.0
        P.texts = [Text("Weekend project", 0.6, 5.0, "bottom", 0.07), Text("Zooming in...", 9.2, 15.0, "top", 0.06, "#ffd23f"),
                   Text("Thanks for watching 🎉", 16.4, 19.2, "middle", 0.08)]
        w.changed()
        w.lanes.pps = 32.0
        w.lanes.refresh()
        w.seek(3.2)
        w.select(("t", 0))
        def shot1():
            grab("window.png")
            w.select(None)
            w.seek(13.0)
            w.tool_crop()
            return False
        def shot2():
            grab("crop.png")
            w.player.pause()
            w._force_close = True
            self.quit()
            return False
        GLib.timeout_add(2500, shot1)
        GLib.timeout_add(5200, shot2)

T([]).run([sys.argv[0]])
