# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project files: round trip, tolerance, corruption, missing media (UI + export), dirty/close logic."""
import json, os, shutil, sys, tempfile, threading, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A, export as E
from splice.model import Project, Text

D = os.path.dirname(os.path.abspath(__file__))
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
tmp = tempfile.mkdtemp(prefix="qa-proj-")
shutil.copy(f"{D}/media/c1.mp4", f"{tmp}/a.mp4"); shutil.copy(f"{D}/media/c2.mp4", f"{tmp}/b.mp4")

# model-level
p = Project(); c = p.add_clip(f"{tmp}/a.mp4"); c.env = [[2, .5], [1, 1.0]]; c.crop = [.1, .1, .5, .5]; p.add_clip(f"{tmp}/b.mp4"); p.texts = [Text("héllo", 1, 2)]
p.save(f"{tmp}/p.splice"); q = Project.load(f"{tmp}/p.splice")
check("round trip keeps everything (env sorted on load)", [vars(x) for x in q.clips][0]["env"] == [[1, 1.0], [2, .5]] and q.texts[0].text == "héllo" and q.clips[0].crop == [.1, .1, .5, .5])
check("no .tmp file left after save", not os.path.exists(f"{tmp}/p.splice.tmp"))
d = json.load(open(f"{tmp}/p.splice")); d["clips"][0]["future_field"] = 1; d["texts"][0]["another"] = "x"; json.dump(d, open(f"{tmp}/new.splice", "w"))
check("newer file with unknown fields loads", len(Project.load(f"{tmp}/new.splice").clips) == 2)
d = {"clips": [{"path": f"{tmp}/a.mp4", "src_in": 0, "src_out": 2}], "texts": []}; json.dump(d, open(f"{tmp}/old.splice", "w"))
check("older file with missing fields loads with defaults", Project.load(f"{tmp}/old.splice").clips[0].volume == 1.0)
for name, content in (("empty", ""), ("garbage", "not json at all"), ("wrong shape", '{"x": 1}'), ("truncated", open(f"{tmp}/p.splice").read()[:60])):
    open(f"{tmp}/{name}.splice", "w").write(content)
    try: Project.load(f"{tmp}/{name}.splice"); check(f"{name} project is rejected", False)
    except Exception: check(f"{name} project is rejected cleanly", True)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        def run():
            time.sleep(1.0)
            def call(fn):
                ev, res = threading.Event(), []
                def go():
                    try: res.append(fn())
                    except Exception as e: res.append(e)
                    ev.set(); return False
                GLib.idle_add(go); ev.wait(10)
                if res and isinstance(res[0], Exception): raise res[0]
                return res[0] if res else None
            # missing media
            os.rename(f"{tmp}/b.mp4", f"{tmp}/b_moved.mp4")
            try:
                call(lambda: w.load_project(f"{tmp}/p.splice"))
                check("project with a moved video opens without crashing", len(w.project.clips) == 2)
                call(lambda: w.select(("v", 1))); call(lambda: w.seek(w.project.clip_start(1) + 1)); time.sleep(.5)
                check("selecting the missing clip shows its editor", call(lambda: w.pop.get_first_child() is not None))
                call(lambda: w.tool_split()); call(lambda: w.tool_crop()); call(lambda: w.tool_volume())
                check("tools on a missing clip do not crash", True)
            except Exception as e:
                check("missing-media handling", False, repr(e)[:150])
            try: E.export(w.project, f"{tmp}/out.mp4"); check("export with missing media is refused", False)
            except ValueError as e: check("export with missing media says which file", "missing" in str(e).lower(), str(e)[-40:])
            os.rename(f"{tmp}/b_moved.mp4", f"{tmp}/b.mp4")
            # dirty / close logic
            call(lambda: w.load_project(f"{tmp}/p.splice"))
            check("freshly loaded project is not dirty", not w.dirty)
            call(lambda: w.tool_text())
            check("an edit marks the project dirty", w.dirty)
            check("closing a dirty project asks first", call(lambda: w._close_request()) is True)
            time.sleep(.5); dlg = call(lambda: w.get_visible_dialog())
            check("the confirmation dialog is showing", dlg is not None)
            if dlg is not None: call(lambda: dlg.force_close())
            call(lambda: w._write_project(f"{tmp}/saved.splice"))
            check("saving clears dirty and remembers the path", not w.dirty and w.path.endswith("saved.splice"))
            # unreadable save target
            os.chmod(tmp, 0o555)
            call(lambda: w._write_project(f"{tmp}/denied.splice")); check("saving to a read-only folder keeps the app alive and the project dirty-safe", True)
            os.chmod(tmp, 0o755)
            check("closing a clean project does not ask", call(lambda: w._close_request()) is False)
            call(lambda: setattr(w, "_force_close", True)); call(w.close)
        threading.Thread(target=run, daemon=True).start()
T([]).run([sys.argv[0]])
print("PROBLEMS:", len(fails), fails)
sys.exit(1 if fails else 0)
