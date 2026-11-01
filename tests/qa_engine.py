# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""QA matrix: every awkward media file through probe -> add -> export -> re-decode."""
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice.model import Project, Text
from splice.export import export
from splice.media import probe

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
out_dir = tempfile.mkdtemp(prefix="qa-")

def ff(path):
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
                                  capture_output=True, text=True, check=True).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = [s for s in j["streams"] if s["codec_type"] == "audio"]
    return int(v["width"]), int(v["height"]), float(j["format"]["duration"]), len(a), v.get("r_frame_rate")

def decode_errors(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-f", "null", "-"], capture_output=True, text=True)
    return p.stderr.strip()

rows, bad = [], 0
for name in sorted(os.listdir(D)):
    path = os.path.join(D, name)
    row = [name[:30]]
    try:
        p = Project()
        c = p.add_clip(path)
    except Exception as e:
        row.append("add refused: " + type(e).__name__)
        rows.append(row)
        if name not in ("garbage.mp4", "audio_only.mp3"):
            bad += 1; row.append("<<< UNEXPECTED")
        continue
    info = probe(path)
    row += [f"{info.width}x{info.height}", f"dur={info.duration:.2f}", f"audio={info.has_audio}"]
    if info.duration <= 0:
        row.append("<<< ZERO DURATION"); bad += 1; rows.append(row); continue
    p.texts = [Text("QA: 100% it's", 0.2, 1.0)]
    out = os.path.join(out_dir, f"{abs(hash(name))}.mp4")
    t0 = time.time()
    try:
        used = export(p, out)
    except Exception as e:
        row.append("EXPORT FAILED: " + str(e)[:80].replace("\n", " ")); bad += 1; rows.append(row); continue
    w, h, d, na, fr = ff(out)
    err = decode_errors(out)
    row += [f"-> {w}x{h} {d:.2f}s a={na} {fr} {time.time()-t0:.1f}s [{used.upper()}]"]
    if abs(d - c.duration) > 0.25: row.append(f"<<< DURATION {d:.2f} vs {c.duration:.2f}"); bad += 1
    if na != 1: row.append("<<< NO AUDIO"); bad += 1
    if err: row.append("<<< DECODE ERR " + err[:60]); bad += 1
    rows.append(row)
for r in rows: print("  ".join(r))
print("PROBLEMS:", bad)
