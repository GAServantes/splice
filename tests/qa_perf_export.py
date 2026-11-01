# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice.model import Project
from splice.export import export
L = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa", "long10min.mp4")
n = int(sys.argv[1])
p = Project()
for i in range(n):
    c = p.add_clip(L); c.src_in = 30 + i * (540 / n); c.src_out = c.src_in + 2.0
t = time.time(); export(p, os.path.join(tempfile.mkdtemp(), "perf.mp4"))
print(f"{n} pieces of 2s from a 10-min file: export took {time.time()-t:.1f}s")
