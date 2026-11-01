# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU vs CPU export: speed, CPU load, size and quality, on the same project. Usage: qa_gpu_bench.py <case>"""
import os, subprocess, sys, tempfile, time, resource
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice import export as E
from splice.model import Project, Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
case = sys.argv[1]
def proj():
    p = Project()
    if case == "1080p-40s":
        c = p.add_clip(f"{D}/hd1080.mp4")
    elif case == "4k":
        for _ in range(8): c = p.add_clip(f"{D}/uhd.mp4")
    elif case == "pieces":
        for i in range(12):
            c = p.add_clip(f"{D}/long10min.mp4"); c.src_in = 30 + i * 40; c.src_out = c.src_in + 6
    if case == "captioned":
        c = p.add_clip(f"{D}/hd1080.mp4"); c.src_out = 20
        p.texts = [Text("Caption 🎉 日本語", 2, 18, "bottom", 0.06)]
    return p
def cpu_seconds(): r = resource.getrusage(resource.RUSAGE_CHILDREN); return r.ru_utime + r.ru_stime
res = {}
for mode in ("cpu", "gpu"):
    p = proj(); out = os.path.join(tempfile.mkdtemp(), f"{mode}.mp4")
    c0, t0 = cpu_seconds(), time.time()
    used = E.export(p, out, use_gpu=(mode == "gpu"))
    wall, cpu = time.time() - t0, cpu_seconds() - c0
    size = os.path.getsize(out) / 1e6
    res[mode] = (out, wall, cpu, size, used)
    print(f"  {mode.upper():3s} (used {used}): {wall:5.1f}s wall, {cpu:6.1f}s CPU time, {size:6.1f} MB")
(co, cw, cc, cs, _), (go, gw, gc, gs, gu) = res["cpu"], res["gpu"]
dur = proj().duration
print(f"  -> GPU is {cw/gw:4.1f}x the speed in wall time, uses {cc/max(gc,0.01):4.1f}x less CPU time; {dur/gw:5.1f}x realtime on GPU vs {dur/cw:5.1f}x on CPU; size {gs/cs:4.2f}x")
def psnr(a, b):
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", a, "-i", b, "-lavfi", "psnr", "-f", "null", "-"], capture_output=True, text=True).stderr
    return [l for l in r.splitlines() if "average:" in l][-1].split("average:")[1].split()[0]
print(f"  quality of GPU file vs CPU file (PSNR, higher = closer): {psnr(go, co)} dB")
