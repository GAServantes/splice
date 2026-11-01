# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Random edit fuzzing through the real window. Usage: qa_fuzz.py <seed> <ops>"""
import json, os, random, subprocess, sys, tempfile, traceback
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib
from splice import app as A, export as E
from splice.media import probe
from splice.model import Project

seed, NOPS = int(sys.argv[1]), int(sys.argv[2])
R = random.Random(seed)
D = os.path.dirname(os.path.abspath(__file__))
MEDIA = [f"{D}/media/c1.mp4", f"{D}/media/c2.mp4", f"{D}/media/c3_silent.mp4", f"{D}/media_qa/portrait.mp4",
         f"{D}/media_qa/rot90.mp4", f"{D}/media_qa/fps60.mp4", f"{D}/media_qa/tiny_silent.mp4", f"{D}/media_qa/mono22k.mp4"]
errors, log = [], []

def invariants(w):
    P = w.project
    for i, c in enumerate(P.clips):
        full = probe(c.path).duration
        assert c.src_in >= -1e-6, f"clip {i} src_in {c.src_in}"
        assert c.duration >= 0.09, f"clip {i} duration {c.duration}"
        assert c.src_out <= full + 0.02, f"clip {i} src_out {c.src_out} > media {full}"
        ts = [t for t, _ in c.env]
        assert ts == sorted(ts), f"clip {i} env unsorted {c.env}"
        assert all(g >= -1e-6 for _, g in c.env), f"clip {i} negative gain {c.env}"
        assert all(-1e-6 <= t <= c.duration + 1e-3 for t in ts), f"clip {i} env point outside clip {c.env} dur {c.duration}"
        if c.crop:
            x, y, cw, ch = c.crop
            assert 0 <= x <= 1 and 0 <= y <= 1 and 0.04 < cw <= 1 and 0.04 < ch <= 1 and x + cw <= 1.0001 and y + ch <= 1.0001, f"clip {i} crop {c.crop}"
    for j, t in enumerate(P.texts):
        assert t.end > t.start and t.start >= -1e-6, f"text {j} {t.start}-{t.end}"
    if w.sel:
        k, i = w.sel
        assert i < (len(P.texts) if k == "t" else len(P.clips)), f"dangling selection {w.sel}"
    assert abs(P.duration - sum(c.duration for c in P.clips)) < 1e-6
    assert -1e-6 <= w.t <= P.duration + 1e-3, f"playhead {w.t} outside 0..{P.duration}"

def op_add(w):  w.add_files([R.choice(MEDIA)])
def op_split(w):
    if w.project.clips: w.seek(R.uniform(0, w.project.duration)); w.tool_split()
def op_text(w):
    if w.project.clips: w.seek(R.uniform(0, w.project.duration)); w.tool_text()
def op_del(w):
    P = w.project
    pick = R.choice([("v", R.randrange(len(P.clips))) if P.clips else None, ("t", R.randrange(len(P.texts))) if P.texts else None, ("s", R.randrange(len(P.clips))) if P.clips else None])
    if pick: w.select(pick); w.delete_selected()
def op_trim(w):
    P = w.project
    if not P.clips: return
    i = R.randrange(len(P.clips)); c = P.clips[i]; full = probe(c.path).duration
    w.checkpoint()
    if R.random() < .5: P.trim(i, new_in=R.uniform(0, full))
    else: P.trim(i, new_out=R.uniform(0, full * 1.2), full=full)
    w.changed()
def op_move(w):
    P = w.project
    if len(P.clips) > 1:
        w.checkpoint(); P.reorder(R.randrange(len(P.clips)), R.randrange(len(P.clips))); w.changed()
def op_vol(w):
    P = w.project
    if P.clips:
        i = R.randrange(len(P.clips)); c = P.clips[i]; w.select(("s", i)); w.checkpoint()
        r = R.random()
        if r < .35: w._set_volume(c, R.uniform(0, 2), i)
        elif r < .7:
            if not c.env: c.env = [[0.0, c.volume], [c.duration, c.volume]]
            c.env.append([R.uniform(0, c.duration), R.uniform(0, 1.5)]); c.env.sort()
        else: c.fade_in, c.fade_out = R.uniform(0, 3), R.uniform(0, 3)
        w.changed()
def op_crop(w):
    P = w.project
    if not P.clips: return
    w.seek(R.uniform(0, P.duration)); w.tool_crop(); i, _ = P.clip_at(w.t)
    if R.random() < .7:
        cw, ch = R.uniform(.1, 1), R.uniform(.1, 1); P.clips[i].crop = [R.uniform(0, 1 - cw), R.uniform(0, 1 - ch), cw, ch]; w.changed()
    elif R.random() < .5: w._crop_remove(P.clips[i])
    else: w._crop_all(P.clips[i])
    if R.random() < .5: w._crop_done()
def op_undo(w):  w.do_undo()
def op_redo(w):  w.do_redo()
def op_seek(w):  w.seek(R.uniform(0, max(0.01, w.project.duration)))
def op_play(w):
    if w.project.clips: w.player.toggle()
def op_select(w):
    P = w.project
    pick = R.choice([None, ("v", R.randrange(len(P.clips))) if P.clips else None, ("t", R.randrange(len(P.texts))) if P.texts else None, ("s", R.randrange(len(P.clips))) if P.clips else None])
    w.select(pick)
def op_text_edit(w):
    P = w.project
    if P.texts:
        w.checkpoint(); t = R.choice(P.texts); t.start = R.uniform(0, P.duration); t.end = t.start + R.uniform(.1, 5)
        t.pos = R.choice(["top", "middle", "bottom"]); t.text = R.choice(["Hi", "50% off: it's here", "Ünïcode ✓", "Line one", ""]); w.changed()
def op_saveload(w):
    p = os.path.join(tempfile.gettempdir(), f"fuzz{seed}.splice"); w.project.save(p)
    before = json.dumps(Project.load(p).__dict__, default=lambda o: o.__dict__, sort_keys=True)
    after = json.dumps(w.project.__dict__, default=lambda o: o.__dict__, sort_keys=True)
    assert before == after, "save/load round trip differs"
OPS = [op_add] * 4 + [op_split] * 5 + [op_text] * 3 + [op_del] * 3 + [op_trim] * 4 + [op_move] * 2 + [op_vol] * 4 + [op_crop] * 3 + \
      [op_undo] * 3 + [op_redo] * 2 + [op_seek] * 3 + [op_play] * 2 + [op_select] * 2 + [op_text_edit] * 3 + [op_saveload]

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        n = [0]
        def step():
            if n[0] >= NOPS: return finish()
            op = R.choice(OPS); n[0] += 1
            try:
                op(w); invariants(w)
            except Exception:
                errors.append(f"seed {seed} op#{n[0]} {op.__name__}: " + traceback.format_exc().strip().splitlines()[-1])
                log.append(traceback.format_exc())
            return True
        def finish():
            w.player.pause()
            P = w.project
            print(f"seed {seed}: {NOPS} ops, final {len(P.clips)} clips, {len(P.texts)} texts, {P.duration:.1f}s, undo depth {len(w.undo)}")
            if P.clips:
                out = os.path.join(tempfile.mkdtemp(), "fuzz.mp4")
                try:
                    E.export(P, out)
                    j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", out], capture_output=True, text=True).stdout)
                    d = float(j["format"]["duration"]); exp = E.output_duration(P)
                    dec = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", out, "-f", "null", "-"], capture_output=True, text=True).stderr.strip()
                    kinds = sorted(s["codec_type"] for s in j["streams"])
                    ok = abs(d - exp) < 0.3 and kinds == ["audio", "video"] and not dec
                    print(f"  export: {d:.2f}s (expected {exp:.2f}) streams={kinds} decode_errors={'none' if not dec else dec[:80]} -> {'OK' if ok else 'BAD'}")
                    if not ok: errors.append(f"seed {seed} export mismatch")
                except Exception as e:
                    errors.append(f"seed {seed} export failed: {str(e)[:200]}"); print("  export FAILED:", str(e)[:300])
            w._force_close = True; self.quit(); return False
        GLib.timeout_add(25, step)
T([]).run([sys.argv[0]])
print("ERRORS:", len(errors))
for e in errors[:8]: print("  ", e)
for l in log[:2]: print(l)
sys.exit(1 if errors else 0)
