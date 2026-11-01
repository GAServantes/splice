# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Saving through the window: the dialog and the 'Saved' message say which encoder did the work."""
import os, sys, tempfile, threading, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A, export as E

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
def call(fn):
    ev, res = threading.Event(), []
    def run():
        try: res.append(fn())
        except Exception as e: res.append(e)
        ev.set(); return False
    GLib.idle_add(run); ev.wait(10)
    return res[0] if res else None

def driver(app):
    w = app.win; toasts = []; w.toast = lambda m: toasts.append(m)
    time.sleep(1.2)
    def save(name):
        n = len(toasts); out = os.path.join(tempfile.mkdtemp(), name)
        call(lambda: w.export_to_path(out))
        for _ in range(150):
            time.sleep(0.1)
            if len(toasts) > n and not w._busy: break
        return toasts[-1] if len(toasts) > n else None, out
    msg, out = save("a.mp4")
    check("saving on the GPU says so", msg and "(GPU)" in msg and os.path.exists(out), str(msg))
    os.environ["SPLICE_ENCODER"] = "cpu"; E._gpu_cache.clear()
    msg, out = save("b.mp4")
    check("saving with the GPU off says CPU", msg and "(CPU)" in msg and "fallback" not in msg and os.path.exists(out), str(msg))
    del os.environ["SPLICE_ENCODER"]; E._gpu_cache.clear(); E.gpu_device()
    real = E.build
    E.build = lambda p, o, wk, crf=20, fmt="mp4", gpu=None: [("no_such_encoder" if a == "h264_vaapi" else a) for a in real(p, o, wk, crf, fmt, gpu)]
    msg, out = save("c.mp4"); E.build = real
    check("a GPU failure is reported and the video is still saved", msg and "could not encode" in msg and os.path.exists(out), str(msg))
    call(lambda: setattr(w, "_force_close", True)); call(w.close)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate()
        threading.Thread(target=driver, args=(self,), daemon=True).start()
T([f"{M}/c1.mp4", f"{M}/c2.mp4"]).run([sys.argv[0]])
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
