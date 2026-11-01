# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless engine test: builds a small project and checks the exported file."""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice.model import Project, Text
from splice.export import export

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
p = Project()
a = p.add_clip(f"{M}/c1.mp4"); a.src_in, a.src_out = 1.0, 4.0; a.fade_out = 0.5
b = p.add_clip(f"{M}/c2.mp4"); b.volume = 0.5; b.env = [[0, 1.0], [1, 0.2], [2, 1.0]]; b.crop = [0.1, 0.1, 0.8, 0.8]
c = p.add_clip(f"{M}/c3_silent.mp4"); c.src_out = 2.0
assert p.split(1.5) and len(p.clips) == 4
p.texts = [Text("Hello: it's 100% fine", 0.5, 2.5), Text("Bottom text", 3, 6, "top")]
expected = p.duration
out = os.path.join(tempfile.mkdtemp(), "out.mp4")
seen = []
export(p, out, seen.append)
info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", out],
                                 capture_output=True, text=True, check=True).stdout)
dur = float(info["format"]["duration"])
kinds = sorted(s["codec_type"] for s in info["streams"])
print(f"expected {expected:.2f}s got {dur:.2f}s streams {kinds} progress_calls {len(seen)} last {seen[-1]:.2f}")
assert abs(dur - expected) < 0.3 and kinds == ["audio", "video"] and seen[-1] == 1.0
print("OK")
