# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Gio
from splice import app as A
from splice.model import Project
D = os.path.dirname(os.path.abspath(__file__))
class V:
    def __init__(self, paths): self.p = paths
    def get_files(self): return [Gio.File.new_for_path(p) for p in self.p]
class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        toasts = []; w.toast = lambda m: toasts.append(m)
        pf = "/tmp/drop.splice"; q = Project(); q.add_clip(f"{D}/media/c1.mp4"); q.save(pf)
        def go():
            ok = []
            w._drop(None, V([f"{D}/media/c1.mp4", f"{D}/media_qa/garbage.mp4", f"{D}/media_qa/audio_only.mp3", "/nonexistent.mp4", D, f"{D}/media_qa/rot90.mp4"]), 0, 0)
            ok.append(("drop of mixed items keeps the 2 good videos", len(w.project.clips) == 2 and [c.name for c in w.project.clips] == ["c1", "rot90"]))
            ok.append(("one toast names the bad ones", len(toasts) == 1 and "garbage" in toasts[0]))
            w._drop(None, V([pf]), 0, 0)
            ok.append(("dropping a .splice file opens it", [c.name for c in w.project.clips] == ["c1"] and w.path == pf))
            w.undo_b.emit("clicked")
            ok.append(("undo after opening a project brings the previous clips back", len(w.project.clips) == 2))
            for n, v in ok: print(("PASS " if v else "FAIL ") + n)
            print("ALL PASS" if all(v for _, v in ok) else "FAILED"); w._force_close = True; self.quit(); return False
        GLib.timeout_add(800, go)
T([]).run([sys.argv[0]])
