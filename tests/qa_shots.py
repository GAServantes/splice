# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scenario screenshots under Xvfb: python qa_shots.py <scenario> <outfile.png>"""
import os, subprocess, sys
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Adw
from splice import app as A
from splice.model import Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
sc, out = sys.argv[1], sys.argv[2]
SIZE = os.environ.get("QA_SIZE", "1280x800")
FILES = {"portrait": ["portrait.mp4"], "rotated": ["rot90.mp4"], "mixed": ["base.mp4", "portrait.mp4", "tiny_silent.mp4"],
         "crop": ["base.mp4"], "light": ["base.mp4", "fps60.mp4"], "hidpi": ["base.mp4", "fps60.mp4"], "odd": ["odd.mp4"], "cropedit": ["base.mp4"], "emoji": ["my video (1) #2 %20 'q' é日本.mp4"]}[sc]

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        if sc in ("light", "hidpi"):
            if sc == "light": Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        w.project.texts.append(Text("Welcome to the demo", 0.5, 3.5)); w.project.texts.append(Text("Top caption", 0.5, 3.5, "top", 0.05, "#ffd23f"))
        if sc == "emoji":
            w.project.texts[:] = [Text("🎉 Party 日本語 مرحبا", 0.5, 3.5, "bottom", 0.07), Text("❤️ Top ✓", 0.5, 3.5, "top", 0.05, "#ffd23f")]
        if sc == "cropedit":
            w.project.texts[:] = []
        if sc == "crop":
            c = w.project.clips[0]; c.crop = [0.25, 0.25, 0.5, 0.5]
        if os.environ.get('QA_WIN'): w.set_default_size(*map(int, os.environ['QA_WIN'].split('x')))
        w.changed(); w.seek(1.0)
        if sc == "cropedit": w.tool_crop(); w.crop_lock = None
        if sc == "light": w.select(("t", 0))
        if sc == "hidpi": w.select(("s", 0))
        def shot():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "x11grab", "-video_size", SIZE, "-i", os.environ["DISPLAY"] + "+0,0", "-frames:v", "1", out])
            w.player.pause(); self.quit(); return False
        GLib.timeout_add(1800, shot)
T([os.path.join(D, f) for f in FILES]).run([sys.argv[0]])
