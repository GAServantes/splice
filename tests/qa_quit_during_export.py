# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quit the app in the middle of an export: no ffmpeg may survive, no partial file may remain."""
import os, subprocess, sys, tempfile, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A
D = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(tempfile.mkdtemp(prefix="qa-quit-"), "o.mp4")
class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        for i in range(30):
            c = w.project.add_clip(f"{D}/media_qa/long10min.mp4"); c.src_in = 20 + i * 18; c.src_out = c.src_in + 15
        w.changed()
        GLib.timeout_add(500, lambda: (w.export_to_path(out), GLib.timeout_add(1500, quit_now)) and False)
        def quit_now():
            print("exporting:", bool(subprocess.run(["pgrep", "-f", out + ".splice-part"], capture_output=True).stdout.strip()))
            w.close(); self.quit(); return False
T([]).run([sys.argv[0]])
print("OUTDIR", os.path.dirname(out))
