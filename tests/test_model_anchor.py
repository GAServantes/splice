# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Captions follow their clip through reorder, trim, delete and insert (pure model, no GUI)."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice.model import Project, Text

D = os.path.dirname(os.path.abspath(__file__))
M = f"{D}/media/c1.mp4"     # 6 s
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
def span(p, t): return (round(t.start, 3), round(t.end, 3))
def proj(*lens):
    p = Project()
    for n in lens:
        c = p.add_clip(M); c.src_out = n
    return p

# reorder: A(0-4) B(4-9?) -> clips 4s,5s,3s ; caption on each
p = proj(4, 5, 3); p.texts = [Text("A", 1, 2), Text("B", 5, 7), Text("C", 10, 11.5)]
p.reorder(0, 2)           # A to the end: order B C A -> starts 0, 5, 8
check("reorder: each caption keeps its place inside its clip", [span(p, t) for t in p.texts] == [(9.0, 10.0), (1.0, 3.0), (6.0, 7.5)], str([span(p, t) for t in p.texts]))
p = proj(4, 5, 3); p.texts = [Text("A", 1, 2), Text("B", 5, 7), Text("C", 7.5, 8.5)]
p.reorder(0, 2)           # order B(0-5) C(5-8) A(8-12)
check("reorder: captions follow their clips", [span(p, t) for t in p.texts] == [(9.0, 10.0), (1.0, 3.0), (3.5, 4.5)], str([span(p, t) for t in p.texts]))
p.reorder(2, 0)           # back
check("reorder back restores the original times", [span(p, t) for t in p.texts] == [(1.0, 2.0), (5.0, 7.0), (7.5, 8.5)], str([span(p, t) for t in p.texts]))
p.reorder(1, 1); check("reorder to the same place is a no-op", [span(p, t) for t in p.texts] == [(1.0, 2.0), (5.0, 7.0), (7.5, 8.5)])

# a caption that runs past its clip keeps its length
p = proj(4, 4); p.texts = [Text("long", 3, 6)]
p.reorder(0, 1); check("caption spanning two clips keeps its length when its clip moves", span(p, p.texts[0]) == (7.0, 10.0), str(span(p, p.texts[0])))

# left trim slides captions earlier with the picture
p = proj(6, 4); p.texts = [Text("A", 2, 3), Text("B", 7, 8)]
r = p.trim(0, new_in=1.0)
check("left trim 1 s: caption on the clip slides 1 s earlier", span(p, p.texts[0]) == (1.0, 2.0), str(span(p, p.texts[0])))
check("left trim 1 s: caption on the next clip moves up 1 s", span(p, p.texts[1]) == (6.0, 7.0), str(span(p, p.texts[1])))
check("left trim removed nothing", r == 0)
# left trim into a caption cuts its start
p = proj(6); p.texts = [Text("A", 1, 3)]
p.trim(0, new_in=2.0); check("left trim into a caption keeps the part that remains", span(p, p.texts[0]) == (0.0, 1.0), str(span(p, p.texts[0])))
# left trim past a caption removes it
p = proj(6); p.texts = [Text("A", 1, 2)]
r = p.trim(0, new_in=3.0); check("left trim past a caption removes it and reports 1", len(p.texts) == 0 and r == 1)
# right trim removes captions that start in the cut-off part, shifts later clips' captions
p = proj(6, 4); p.texts = [Text("in", 1, 2), Text("cut", 5, 5.8), Text("next", 7, 8)]
r = p.trim(0, new_out=4.0)
check("right trim: caption over the cut-off end is removed", [t.text for t in p.texts] == ["in", "next"] and r == 1, str([t.text for t in p.texts]))
check("right trim: later caption moves up with its clip", span(p, p.texts[1]) == (5.0, 6.0), str(span(p, p.texts[1])))
# extending a clip pushes later captions down
p = proj(3, 4); p.texts = [Text("B", 4, 5)]
p.clips[0].src_out = 3.0; p.trim(0, new_out=5.0); check("extending a clip moves later captions down", span(p, p.texts[0]) == (6.0, 7.0), str(span(p, p.texts[0])))
# delete
p = proj(4, 4, 4); p.texts = [Text("A", 1, 2), Text("B", 5, 6), Text("C", 9, 10), Text("spill", 3, 6)]
r = p.delete_clip(1)
check("delete: captions that start in the clip go, later ones move up", [t.text for t in p.texts] == ["A", "C", "spill"] and span(p, p.texts[1]) == (5.0, 6.0) and r == 1, str([(t.text, span(p, t)) for t in p.texts]))
# insert in the middle
p = proj(4, 4); p.texts = [Text("B", 5, 6)]
p.add_clip(M, 1); check("inserting a clip pushes later captions down", span(p, p.texts[0]) == (11.0, 12.0), str(span(p, p.texts[0])))
# identical clips (equal by value) must not confuse anchoring
p = proj(3, 3, 3); p.texts = [Text("x", 4, 5)]
p.reorder(0, 2); check("equal-looking clips are told apart (identity, not equality)", span(p, p.texts[0]) == (1.0, 2.0), str(span(p, p.texts[0])))

# fuzz: invariants hold and total caption count only drops via trim/delete
R = random.Random(1); bad = 0
for k in range(400):
    p = proj(*[R.uniform(1, 6) for _ in range(R.randint(1, 6))])
    p.texts = [Text(str(j), (s := R.uniform(0, p.duration)), s + R.uniform(.1, 3)) for j in range(R.randint(0, 6))]
    for _ in range(8):
        op = R.choice(["reorder", "trim_in", "trim_out", "delete"])
        try:
            if op == "reorder" and len(p.clips) > 1: p.reorder(R.randrange(len(p.clips)), R.randrange(len(p.clips)))
            elif op == "trim_in": p.trim(R.randrange(len(p.clips)), new_in=R.uniform(0, 5))
            elif op == "trim_out": p.trim(R.randrange(len(p.clips)), new_out=R.uniform(0.2, 6), full=6.0)
            elif op == "delete" and len(p.clips) > 1: p.delete_clip(R.randrange(len(p.clips)))
        except Exception as e:
            bad += 1; print("exception", op, e)
        for t in p.texts:
            if not (t.end > t.start and t.start >= -1e-6): bad += 1
print(f"fuzz: 400 projects x 8 ops, {bad} invariant breaks")
check("fuzz invariants", bad == 0)
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
