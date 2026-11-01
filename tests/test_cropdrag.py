# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure geometry tests for crop dragging, plus fuzz of the invariants."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice import cropdrag as C
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
def close(a, b, e=1e-9): return all(abs(x - y) < e for x, y in zip(a, b))

box = [0.2, 0.2, 0.5, 0.5]
check("move shifts the box", close(C.drag(box, "move", 0.1, -0.05), [0.3, 0.15, 0.5, 0.5]))
check("move stops at the picture edge (right/bottom)", close(C.drag(box, "move", 5, 5), [0.5, 0.5, 0.5, 0.5]))
check("move stops at the picture edge (left/top)", close(C.drag(box, "move", -5, -5), [0.0, 0.0, 0.5, 0.5]))
check("east edge widens", close(C.drag(box, "e", 0.1, 0.3), [0.2, 0.2, 0.6, 0.5]))
check("west edge narrows from the left", close(C.drag(box, "w", 0.1, 0), [0.3, 0.2, 0.4, 0.5]))
check("corner changes both sides", close(C.drag(box, "se", 0.1, 0.1), [0.2, 0.2, 0.6, 0.6]) and close(C.drag(box, "nw", -0.1, -0.1), [0.1, 0.1, 0.6, 0.6]))
r = C.drag(box, "e", -5, 0); check("cannot shrink past the minimum", abs(r[2] - C.MIN) < 1e-9, str(r))
r = C.drag(box, "se", 5, 5); check("cannot grow past the picture", abs(r[0] + r[2] - 1) < 1e-9 and abs(r[1] + r[3] - 1) < 1e-9, str(r))
r = C.drag(box, "w", 5, 0); check("dragging an edge across the other stops at the minimum", abs(r[2] - C.MIN) < 1e-9 and r[0] + r[2] <= 0.7 + 1e-9, str(r))
# locked 16:9 on a 16:9 picture: fractions w==h
sq = [0.25, 0.25, 0.5, 0.5]
r = C.drag(sq, "se", 0.1, 0.0, lock=16 / 9, fa=16 / 9); check("locked corner keeps the shape", abs(r[2] / r[3] - 1.0) < 1e-9 and close(r[:2], [0.25, 0.25]), str(r))
r = C.drag(sq, "e", 0.1, 0.9, lock=16 / 9, fa=16 / 9); check("locked side grows the other side about the middle", abs(r[2] / r[3] - 1) < 1e-9 and abs((r[1] + r[3] / 2) - 0.5) < 1e-9, str(r))
# 9:16 lock on a 16:9 picture: crop w/h in fractions = (9/16)/(16/9)
k = (9 / 16) / (16 / 9); tall = [0.3, 0.1, 0.8 * k, 0.8]
r = C.drag(tall, "se", 0.05, 0.05, lock=9 / 16, fa=16 / 9); check("portrait lock on a wide picture keeps 9:16 in pixels", abs((r[2] * 16 / 9) / r[3] - 9 / 16) < 1e-9, str(r))
# hit testing
fx, fy, fw, fh = 100, 50, 400, 300; crop = [0.25, 0.25, 0.5, 0.5]          # box (200,125)-(400,275)
tests = {(200, 125): "nw", (400, 125): "ne", (200, 275): "sw", (400, 275): "se", (300, 125): "n", (300, 275): "s", (200, 200): "w", (400, 200): "e", (300, 200): "move", (120, 60): None, (300, 330): None}
check("hit testing finds each handle", all(C.hit(crop, fx, fy, fw, fh, *p) == want for p, want in tests.items()), str({p: C.hit(crop, fx, fy, fw, fh, *p) for p in tests}))
check("a tiny box can still be moved", C.hit([0.5, 0.5, 0.05, 0.05], 0, 0, 400, 300, 210, 160) in ("move", "nw", "se", "n", "s", "e", "w", "ne", "sw"))
check("handle positions", C.handle_points(crop, fx, fy, fw, fh)["se"] == (400.0, 275.0))

# fuzz invariants
R = random.Random(3); bad = []
for _ in range(60000):
    fa = R.choice([16 / 9, 4 / 3, 1.0, 9 / 16, 21 / 9, 0.3, 3.0])
    lock = R.choice([None, None, 16 / 9, 4 / 3, 1.0, 9 / 16])
    w0, h0 = R.uniform(0.06, 1), R.uniform(0.06, 1)
    if lock:                         # start from a box that satisfies the lock (the UI guarantees that)
        k = lock / fa; w0 = min(w0, 1.0, k * 1.0); h0 = w0 / k
        if h0 > 1 or w0 < C.MIN or h0 < C.MIN: continue
    x0, y0 = R.uniform(0, 1 - w0), R.uniform(0, 1 - h0)
    hd = R.choice(list(C.HANDLES) + ["move"]); dx, dy = R.uniform(-1.5, 1.5), R.uniform(-1.5, 1.5)
    x, y, w, h = C.drag([x0, y0, w0, h0], hd, dx, dy, lock, fa)
    e = 1e-7
    if not (x >= -e and y >= -e and x + w <= 1 + e and y + h <= 1 + e and w >= C.MIN - e and h >= C.MIN - e):
        bad.append(("bounds", hd, lock, round(fa, 2), [x0, y0, w0, h0], [x, y, w, h]))
    if lock and hd != "move" and abs((w * fa) / h - lock) > 1e-6:
        bad.append(("aspect", hd, lock, [x, y, w, h]))
    if hd == "move" and (abs(w - w0) > e or abs(h - h0) > e): bad.append(("move resized",))
check("60,000 random drags: always inside the picture, never below the minimum, aspect kept when locked", not bad, f"{len(bad)} violations, first: {bad[:1]}")
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
