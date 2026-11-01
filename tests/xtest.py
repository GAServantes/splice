# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the real window under Xvfb, drive it, and save a screenshot. Never touches the live desktop."""
import os, sys, subprocess
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk, Adw
from splice import app as A
from splice.model import Text

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
OUT = sys.argv[1]
steps = []
class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        w = self.win
        theme = Gtk.IconTheme.get_for_display(w.get_display())
        missing = [i for i in ("edit-cut-symbolic","insert-text-symbolic","image-crop-symbolic","audio-volume-high-symbolic","zoom-in-symbolic","zoom-out-symbolic","document-open-symbolic","media-skip-backward-symbolic") if not theme.has_icon(i)]
        print("missing icons:", missing)
        w.project.clips[1].env = [[0, 1.0], [8, 0.3], [16, 1.0]] if len(w.project.clips) > 1 else []
        w.project.texts.append(Text("Welcome to the demo", 1.0, 5.0))
        w.project.texts.append(Text("Thanks for watching", 12.0, 16.0, "top"))
        w.changed(); w.seek(2.0); w.select(("s", 1))
        GLib.timeout_add(1500, lambda: shot("a") or w.tool_crop() or GLib.timeout_add(600, lambda: shot("b") or w.select(("s", 1)) or GLib.timeout_add(600, lambda: shot("c") or self.quit()) and False) and False)
def shot(n):
    subprocess.run(["ffmpeg","-v","error","-y","-f","x11grab","-video_size","1280x800","-i",os.environ["DISPLAY"]+"+0,0","-frames:v","1",f"{OUT}_{n}.png"])
    return None
files = [f"{M}/c1.mp4", f"{M}/c2.mp4", f"{M}/c3_silent.mp4"]
T(files).run([sys.argv[0]])
