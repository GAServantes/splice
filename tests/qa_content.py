# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Numeric QA: cuts/joins land on the right frames and samples, A/V stay in sync, volume/fades/envelope are right, crop is right."""
import os, subprocess, sys, tempfile, array, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice.model import Project, Text, Clip
from splice.export import export

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
TONES, BASE = f"{D}/tones.mp4", f"{D}/base.mp4"
COL = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0)}
FREQ = {"red": 200, "green": 400, "blue": 800, "yellow": 1600}
work = tempfile.mkdtemp(prefix="qa2-")
fails = []

def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)

def color_at(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", "scale=1:1:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    px = tuple(raw[:3])
    return min(COL, key=lambda k: sum((a - b) ** 2 for a, b in zip(COL[k], px)))

def samples(path, t0, dur, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0, t0):.3f}", "-t", f"{dur:.3f}", "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True).stdout
    a = array.array("h"); a.frombytes(raw[: len(raw) // 2 * 2])
    return a

def freq_at(path, t, win=0.08):
    a = samples(path, t - win / 2, win)
    if len(a) < 50: return 0
    zc = sum(1 for i in range(1, len(a)) if (a[i - 1] < 0) != (a[i] < 0))
    return zc / 2 / (len(a) / 16000)

def rms(a):
    return math.sqrt(sum(x * x for x in a) / max(1, len(a)))

def tone_name(f):
    return min(FREQ, key=lambda k: abs(FREQ[k] - f))

def build(pieces):
    p = Project()
    for a, b in pieces:
        c = p.add_clip(TONES); c.src_in, c.src_out = a, b
    return p

def expect_sequence(pieces):
    """list of (output_time, expected_color) sampled mid-frame well inside each second of the source."""
    out, t = [], 0.0
    for a, b in pieces:
        s = a
        while s < b - 1e-6:
            e = min(b, math.floor(s) + 1)
            if e - s >= 0.2:
                out.append((t + (s - a) + min(0.1, (e - s) / 2), ["red", "green", "blue", "yellow"][int(math.floor(s)) % 4]))
            s = e
        t += b - a
    return out

CASES = {
    "single mid-trim [1.5,3.5]": [(1.5, 3.5)],
    "frame-odd trim [0.43,2.77]": [(0.43, 2.77)],
    "join two [2.2,3.9]+[0.1,1.4]": [(2.2, 3.9), (0.1, 1.4)],
    "contiguous seams [0,1.3],[1.3,2.6],[2.6,4]": [(0, 1.3), (1.3, 2.6), (2.6, 4.0)],
    "reverse order [3,4],[2,3],[1,2],[0,1]": [(3, 4), (2, 3), (1, 2), (0, 1)],
    "many tiny pieces": [(i * 0.37 % 3.5, i * 0.37 % 3.5 + 0.35) for i in range(10)],
}
for name, pieces in CASES.items():
    p = build(pieces)
    out = os.path.join(work, "o.mp4")
    export(p, out)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
    # stream durations (A/V sync across joins)
    sd = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.split()
    exp = p.duration
    vd = [float(x.split(",")[1]) for x in sd if x.startswith("video")][0]
    ad = [float(x.split(",")[1]) for x in sd if x.startswith("audio")][0]
    bad = []
    for t, col in expect_sequence(pieces):
        c = color_at(out, t)
        f = tone_name(freq_at(out, t))
        if c != col: bad.append(f"t={t:.2f} video {c}!={col}")
        if f != col: bad.append(f"t={t:.2f} audio {f}!={col}")
    check(f"content: {name}", not bad and abs(vd - exp) < 0.07 and abs(ad - exp) < 0.1,
          f"exp={exp:.2f} v={vd:.2f} a={ad:.2f} " + "; ".join(bad[:4]))

# ---- volume / envelope / fades ----
def level_profile(c, pts, ref=None):
    p = Project(); p.clips.append(c)
    out = os.path.join(work, "v.mp4"); export(p, out)
    return [rms(samples(out, t - 0.05, 0.1)) for t in pts]

def clip(**kw):
    c = Clip(BASE, 0.0, 4.0); [setattr(c, k, v) for k, v in kw.items()]; return c

pts = [0.5, 1.0, 1.5, 2.0, 2.5, 3.5]
ref = level_profile(clip(), pts)
half = level_profile(clip(volume=0.5), pts)
check("volume 0.5", all(abs(h / r - 0.5) < 0.04 for h, r in zip(half, ref)), str([round(h / r, 2) for h, r in zip(half, ref)]))
boost = level_profile(clip(volume=1.8), pts)
check("volume 1.8", all(abs(h / r - 1.8) < 0.1 for h, r in zip(boost, ref)), str([round(h / r, 2) for h, r in zip(boost, ref)]))
mute = level_profile(clip(volume=0.0), pts)
check("volume 0 is silent", all(m < 5 for m in mute), str([round(m) for m in mute]))
env = level_profile(clip(env=[[0, 1.0], [1.0, 0.2], [2.0, 1.0]]), pts)
want = [0.6, 0.2, 0.6, 1.0, 1.0, 1.0]
check("volume line", all(abs(e / r - w) < 0.08 for e, r, w in zip(env, ref, want)), str([round(e / r, 2) for e, r in zip(env, ref)]) + f" want {want}")
fade = level_profile(clip(fade_in=1.0, fade_out=1.0), [0.25, 0.5, 2.0, 3.5, 3.75])
refc = level_profile(clip(), [0.25, 0.5, 2.0, 3.5, 3.75])
got = [round(f / r, 2) for f, r in zip(fade, refc)]
check("fades", abs(got[0] - 0.25) < 0.1 and abs(got[1] - 0.5) < 0.1 and abs(got[2] - 1) < 0.05 and abs(got[3] - 0.5) < 0.1 and abs(got[4] - 0.25) < 0.1, str(got))

# ---- crop: take the right half of the red/green/blue/yellow? use tones.mp4 frame = solid; use base (testsrc2) and compare to ffmpeg's own crop
p = Project(); c = p.add_clip(BASE); c.src_out = 1.0; c.crop = [0.25, 0.25, 0.5, 0.5]
out = os.path.join(work, "c.mp4"); export(p, out)
ref_png = os.path.join(work, "ref.png"); got_png = os.path.join(work, "got.png")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", "0.5", "-i", BASE, "-frames:v", "1", "-vf", "crop=640:360:320:180", ref_png])
subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", "0.5", "-i", out, "-frames:v", "1", got_png])
r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", ref_png, "-i", got_png, "-lavfi", "psnr", "-f", "null", "-"], capture_output=True, text=True)
psnr = subprocess.run(["ffmpeg", "-nostdin", "-i", ref_png, "-i", got_png, "-lavfi", "psnr", "-f", "null", "-"], capture_output=True, text=True).stderr
val = [l for l in psnr.splitlines() if "average:" in l]
check("crop matches ffmpeg crop (PSNR)", bool(val) and ("inf" in val[-1] or float(val[-1].split("average:")[1].split()[0]) > 30), val[-1].strip()[-60:] if val else psnr[-200:])
print("PROBLEMS:", len(fails), fails)
