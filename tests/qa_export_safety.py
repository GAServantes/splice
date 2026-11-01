# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export failure modes: cancel, bad paths, source overwrite, existing file preservation, leftovers."""
import hashlib, os, stat, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from splice import export as E
from splice.model import Project, Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
def sha(p): return hashlib.sha1(open(p, "rb").read()).hexdigest()
tmp = tempfile.mkdtemp(prefix="qa-safe-")
def proj(n=1, long=False):
    p = Project()
    for i in range(n):
        c = p.add_clip(f"{D}/media_qa/long10min.mp4" if long else f"{D}/media/c1.mp4")
        if long: c.src_in = 20 + i * 20; c.src_out = c.src_in + 15
    return p
def listing(): return sorted(os.listdir(tmp))

# 1. success leaves exactly one file, no part file
out = f"{tmp}/ok.mp4"; E.export(proj(2), out)
check("success writes output and leaves no temp files", listing() == ["ok.mp4"], str(listing()))

# 2. existing target survives a failed export
good = f"{tmp}/keep.mp4"; E.export(proj(1), good); h = sha(good)
p = proj(1); p.clips[0].path = f"{tmp}/gone.mp4"
try: E.export(p, good); check("missing media is reported", False)
except ValueError as e: check("missing media reported before touching anything", "missing" in str(e).lower() and sha(good) == h, str(e)[:60])

# 3. writing over a source clip is refused
src = f"{tmp}/src.mp4"; os.system(f"cp {D}/media/c1.mp4 {src}")
p = Project(); p.add_clip(src); h = sha(src)
try: E.export(p, src); check("overwriting a source clip is refused", False)
except ValueError as e: check("overwriting a source clip is refused", sha(src) == h, str(e)[:50])
# also through a symlink
os.symlink(src, f"{tmp}/link.mp4")
try: E.export(p, f"{tmp}/link.mp4"); check("source overwrite via symlink refused", False)
except ValueError as e: check("source overwrite via symlink refused", sha(src) == h)

# 4. bad extension / bad folder
for name, path in (("unsupported extension", f"{tmp}/x.avi"), ("no extension", f"{tmp}/noext"), ("folder missing", f"{tmp}/nodir/x.mp4")):
    try: E.export(proj(1), path); check(name + " refused", False)
    except ValueError as e: check(name + " refused with a clear message", True, str(e))
# unwritable folder
ro = f"{tmp}/ro"; os.mkdir(ro); os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
try: E.export(proj(1), f"{ro}/x.mp4"); check("read-only folder reported", False)
except Exception as e: check("read-only folder reported as an error", True, str(e)[:70].replace("\n", " "))
os.chmod(ro, 0o755)

# 5. cancel mid-export: no output, no part file, existing file untouched, quick return
tgt = f"{tmp}/cancel.mp4"; open(tgt, "w").write("OLD CONTENT"); ev = threading.Event(); res = []
def run():
    try: E.export(proj(20, long=True), tgt, cancel=ev); res.append("finished")
    except E.ExportCancelled: res.append("cancelled")
    except Exception as e: res.append("error " + str(e)[:80])
t = threading.Thread(target=run); t0 = time.time(); t.start(); time.sleep(1.2); ev.set(); t.join(15)
check("cancel stops the export quickly", res == ["cancelled"] and time.time() - t0 < 6, f"{res} in {time.time()-t0:.1f}s")
check("cancel keeps the old file and leaves no temp files", open(tgt).read() == "OLD CONTENT" and not [f for f in listing() if "part" in f], str([f for f in listing() if "cancel" in f or "part" in f]))

# 6. cancel set before start
ev2 = threading.Event(); ev2.set()
try: E.export(proj(1), f"{tmp}/pre.mp4", cancel=ev2); check("pre-cancelled export", False)
except E.ExportCancelled: check("cancel before first progress line", not os.path.exists(f"{tmp}/pre.mp4"))

# 7. ffmpeg failure (impossible text size) leaves nothing and surfaces a message
p = proj(1); p.texts = [Text("x", 0, 1, size=-5)]
try: E.export(p, f"{tmp}/bad.mp4"); check("ffmpeg failure surfaces", True, "(exported fine despite odd size)")
except RuntimeError as e: check("ffmpeg failure surfaces a message and leaves no file", not os.path.exists(f"{tmp}/bad.mp4") and not any("part" in f for f in listing()), str(e)[:60])

# 8. file names with spaces/unicode as output
E.export(proj(1), f"{tmp}/my édit (final).mp4"); check("unicode/space output name", os.path.exists(f"{tmp}/my édit (final).mp4"))
# 9. .mkv and .mov outputs
for ext in (".mkv", ".mov"):
    E.export(proj(1), f"{tmp}/o{ext}"); check(f"{ext} export plays", os.system(f"ffmpeg -v error -nostdin -i {tmp}/o{ext} -f null - 2>/dev/null") == 0)
print("PROBLEMS:", len(fails), fails)
