# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU export: device choice, CPU fallback, quality/size parity with x264, compatibility, CPU savings, cancel, containers."""
import os, resource, subprocess, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice import export as E
from splice.model import Project, Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
work = tempfile.mkdtemp(prefix="qa-gpu-")
def proj(path="hd1080.mp4", n=1, secs=None):
    p = Project()
    for _ in range(n):
        c = p.add_clip(f"{D}/{path}")
        if secs: c.src_out = secs
    return p
def probe(path, entries):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entries, "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
def decode_err(path):
    return subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-f", "null", "-"], capture_output=True, text=True).stderr.strip()
def cpu_s(): r = resource.getrusage(resource.RUSAGE_CHILDREN); return r.ru_utime + r.ru_stime
def psnr(a, b):
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", a, "-i", b, "-lavfi", "psnr", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float([l for l in r.splitlines() if "average:" in l][-1].split("average:")[1].split()[0])

# 1. device choice
dev = E.gpu_device()
vram = {n: E._vram(os.path.join("/dev/dri", n)) for n in os.listdir("/dev/dri") if n.startswith("renderD")}
best = max(vram, key=vram.get) if vram else None
check("the GPU with the most video memory is chosen", dev is not None and os.path.basename(dev) == best, f"{dev} (VRAM by node: { {k: round(v/1e9,1) for k,v in vram.items()} })")

# 2. basic GPU export is real GPU, H.264 High, plays, faststart
out = f"{work}/g.mp4"; used = E.export(proj(secs=10), out)
check("export reports it used the GPU", used == "gpu")
check("output is H.264 High, yuv420p", probe(out, "stream=codec_name,profile,pix_fmt") == "h264,High,yuv420p", probe(out, "stream=codec_name,profile,pix_fmt"))
check("output decodes cleanly", decode_err(out) == "")
head = open(out, "rb").read(65536)
check("mp4 is set up for streaming (index at the start of the file)", b"moov" in head)

# 3. CPU escape hatch and bad device
os.environ["SPLICE_ENCODER"] = "cpu"; E._gpu_cache.clear()
check("SPLICE_ENCODER=cpu turns the GPU off", E.gpu_device() is None and E.export(proj(secs=3), f"{work}/c.mp4") == "cpu")
del os.environ["SPLICE_ENCODER"]; E._gpu_cache.clear()
os.environ["SPLICE_VAAPI_DEVICE"] = "/dev/null"
check("an unusable GPU device falls back to the CPU", E.gpu_device() is None and E.export(proj(secs=3), f"{work}/b.mp4") == "cpu")
del os.environ["SPLICE_VAAPI_DEVICE"]; E._gpu_cache.clear(); E.gpu_device()

# 4. GPU run that fails part-way: must finish on the CPU, valid file, no leftovers
real_build = E.build
def broken(p, o, w, crf=20, fmt="mp4", gpu=None):
    cmd = real_build(p, o, w, crf, fmt, gpu)
    return [("no_such_encoder" if a == "h264_vaapi" else a) for a in cmd] if gpu else cmd
E.build = broken
out = f"{work}/fb.mp4"; used = E.export(proj(secs=4), out)
E.build = real_build
check("a failing GPU encode is retried on the CPU", used == "cpu" and decode_err(out) == "" and probe(out, "stream=codec_name") == "h264")
check("no temp files left after the fallback", not [f for f in os.listdir(work) if "part" in f])

# 5. quality and size parity with the CPU encoder, speed and CPU load
def run(use_gpu, p):
    o = f"{work}/{'g' if use_gpu else 'c'}_par.mp4"; c0, t0 = cpu_s(), time.time(); E.export(p, o, use_gpu=use_gpu); return o, time.time() - t0, cpu_s() - c0
for src in ("hd1080.mp4", "fractal.mp4"):
    gp, gw, gc = run(True, proj(src)); cp, cw, cc = run(False, proj(src))
    ref = f"{D}/{src}"; pg, pc = psnr(gp, ref), psnr(cp, ref)
    sg, sc = os.path.getsize(gp), os.path.getsize(cp)
    print(f"  [{src}] GPU {gw:.1f}s wall {gc:.1f}s CPU {sg/1e6:.1f} MB {pg:.1f} dB | CPU {cw:.1f}s wall {cc:.1f}s CPU {sc/1e6:.1f} MB {pc:.1f} dB")
    check(f"{src}: GPU quality is within 1 dB of the CPU encode", pg >= pc - 1.0, f"{pg:.1f} vs {pc:.1f} dB")
    check(f"{src}: GPU file is not much bigger (<= 1.35x)", sg <= 1.35 * sc, f"{sg/sc:.2f}x")
    check(f"{src}: GPU export is not slower than 1.5x the CPU export", gw <= 1.5 * cw, f"{gw:.1f}s vs {cw:.1f}s")
    check(f"{src}: GPU export uses at least 3x less CPU time", gc * 3 <= cc, f"{gc:.1f}s vs {cc:.1f}s")

# 6. containers and captions and audio through the GPU path
for ext in (".mp4", ".mov", ".mkv"):
    p = proj("base.mp4"); p.texts = [Text("GPU 🎉 日本語", 0.5, 3)]
    o = f"{work}/t{ext}"; u = E.export(p, o)
    check(f"{ext} export with a caption works on the GPU", u == "gpu" and decode_err(o) == "" and probe(o, "stream=codec_name") == "h264")

# 7. cancel kills the GPU ffmpeg and removes the temp file
ev = threading.Event(); res = []
def go():
    try: E.export(proj("long10min.mp4", 1), f"{work}/cancel.mp4", cancel=ev); res.append("done")
    except E.ExportCancelled: res.append("cancelled")
t = threading.Thread(target=go); t.start(); time.sleep(1.5); ev.set(); t.join(15)
time.sleep(0.5)
check("cancelling a GPU export stops it and leaves nothing behind", res == ["cancelled"] and not [f for f in os.listdir(work) if "cancel" in f] and subprocess.run(["pgrep", "-xc", "ffmpeg"], capture_output=True, text=True).stdout.strip() == "0", str(res))
print("PROBLEMS:", len(fails), fails)
sys.exit(1 if fails else 0)
