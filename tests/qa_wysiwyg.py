# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview vs export: grab the stage from a screenshot and SSIM it against the exported frame at the same time."""
import os, re, subprocess, sys, tempfile
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Graphene", "1.0")
from gi.repository import GLib, Graphene
from splice import app as A, export as E
from splice.model import Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
case = sys.argv[1]
work = tempfile.mkdtemp(prefix="wys-")
class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win; P = w.project
        c = P.clips[0]
        if case == "cropped":
            c.crop = [0.2, 0.1, 0.6, 0.7]
        P.texts = [Text("Party 🎉 ok ✓ éñ", 0.2, 3.5, "bottom", 0.07), Text("日本語 你好", 0.2, 3.5, "top", 0.05, "#ffd23f"), Text("❤️ 🚀 مرحبا", 0.2, 3.5, "middle", 0.09)]
        w.changed(); w.seek(1.0)
        def shot():
            w.player.pause()
            ok, pt = w.video.compute_point(w, Graphene.Point().init(0, 0))
            vw, vh = w.video.get_width(), w.video.get_height()
            ox, oy, ow, oh = w.geometry(vw, vh)["out"]
            # screen coords (X11 under Xvfb: no WM, window at 0,0 + 5px client shadow calibrated below)
            shot_png = os.path.join(work, "shot.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "x11grab", "-video_size", "1280x800", "-i", os.environ["DISPLAY"] + "+0,0", "-frames:v", "1", shot_png])
            out = os.path.join(work, "o.mp4"); E.export(P, out)
            ref = os.path.join(work, "ref.png")
            ow_i, oh_i = int(round(ow)), int(round(oh))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", f"{E.map_time(P, 1.0):.3f}", "-i", out, "-frames:v", "1", "-vf", f"scale={ow_i}:{oh_i}:flags=lanczos", ref])
            best = (-1, None)
            for dx in range(-8, 9, 1):          # window-decoration offset in this headless setup is unknown: search it
                for dy in range(-8, 9, 1):
                    x, y = int(pt.x + ox) + dx, int(pt.y + oy) + dy
                    cr = os.path.join(work, "cr.png")
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", shot_png, "-vf", f"crop={ow_i}:{oh_i}:{x}:{y}", cr])
                    r = subprocess.run(["ffmpeg", "-nostdin", "-i", ref, "-i", cr, "-lavfi", "ssim", "-f", "null", "-"], capture_output=True, text=True).stderr
                    m = re.search(r"All:([0-9.]+)", r)
                    if m and float(m.group(1)) > best[0]: best = (float(m.group(1)), (dx, dy))
                if best[0] > 0.97: break
            print(f"{case}: stage output rect {ow_i}x{oh_i}, best SSIM vs exported frame = {best[0]:.3f} at offset {best[1]}")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", shot_png, "-vf", f"crop={ow_i}:{oh_i}:{int(pt.x+ox)+best[1][0]}:{int(pt.y+oy)+best[1][1]}", os.path.join(work, "preview_crop.png")])
            print("files:", work)
            w._force_close = True; self.quit(); return False
        GLib.timeout_add(2200, shot)
T([os.path.join(D, "base.mp4" if case == "cropped" else "rot90.mp4")]).run([sys.argv[0]])
