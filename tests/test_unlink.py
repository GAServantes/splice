# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unlinked sound: the model (unlink, move, trim, split, link again, save/load), the saved video's sound
(checked by tone: c1.mp4 plays 300 Hz, c2.mp4 600 Hz) and the preview playing it at its own place."""
import os, subprocess, sys, tempfile
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from splice.model import Project, Sound
from splice.export import export, build

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
C1, C2 = f"{M}/c1.mp4", f"{M}/c2.mp4"      # 6 s each: 300 Hz and 600 Hz
fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(name)


def two_clips():
    p = Project()
    a = p.add_clip(C1); a.src_in, a.src_out = 0.0, 4.0
    b = p.add_clip(C2); b.src_in, b.src_out = 0.0, 4.0
    return p


# --- model ---------------------------------------------------------------------------------------------
p = two_clips()
p.clips[1].volume, p.clips[1].fade_in, p.clips[1].env = 0.8, 0.5, [[0.0, 0.8], [2.0, 0.4]]
j = p.unlink(1)
s = p.sounds[j]
check("unlink: a sound at the clip's place with its range, volume line and fades",
      isinstance(s, Sound) and s.start == 4.0 and (s.src_in, s.src_out) == (0.0, 4.0) and s.fade_in == 0.5
      and s.env == [[0.0, 0.8], [2.0, 0.4]] and not p.clips[1].linked)
p.trim(0, new_in=1.0)
check("trimming another clip doesn't move it", s.start == 4.0 and p.clip_start(1) == 3.0)
p.reorder(1, 0)
check("reordering doesn't move it", s.start == 4.0)
p.trim_sound(j, new_in=1.0)
check("left trim keeps the sound in place", abs(s.start - 5.0) < 1e-9 and s.src_in == 1.0 and s.env[0][0] == 0.0)
p.trim_sound(j, new_in=-10.0)
check("left trim can't go before the file's start", s.src_in == 0.0 and abs(s.start - 4.0) < 1e-9)
p.trim_sound(j, new_in=2.0)
p.move_sound(j, 0.5)
p.trim_sound(j, new_in=-10.0)
check("...or the timeline's start", s.start == 0.0 and abs(s.src_in - 1.5) < 1e-9, f"start {s.start}, in {s.src_in}")
p.move_sound(j, 1.0)
p.trim_sound(j, new_out=99.0, full=6.0)
check("right trim stops at the file's end", s.src_out == 6.0)
p.move_sound(j, -3)
check("can't move before 0", s.start == 0.0)
check("split a sound", p.split_sound(j, 2.0) and len(p.sounds) == 2 and p.sounds[1].start == 2.0
      and abs(p.sounds[0].end - 2.0) < 1e-9 and abs(p.sounds[0].src_out - p.sounds[1].src_in) < 1e-9)
check("no split at an edge", not p.split_sound(0, 0.05))
clip = p.clips[0]                    # the unlinked c2 clip, now first
check("split clip halves stay unlinked", p.split(1.0) and not p.clips[0].linked and not p.clips[1].linked)
tmp = tempfile.mkdtemp()
p.save(f"{tmp}/x.splice")
q = Project.load(f"{tmp}/x.splice")
check("save and load keep unlinked sounds", len(q.sounds) == 2 and all(isinstance(x, Sound) for x in q.sounds)
      and [x.start for x in q.sounds] == [x.start for x in p.sounds] and not q.clips[0].linked)
with open(f"{tmp}/old.splice", "w") as f:
    f.write('{"version": 1, "clips": [{"path": "%s", "src_in": 0, "src_out": 2}], "texts": []}' % C1)
old = Project.load(f"{tmp}/old.splice")
check("older projects open (sound linked, no unlinked sounds)", old.clips[0].linked and old.sounds == [])
# the sounds now cover 1.5-6 s of c2; clip 0 shows 0-1 s of it, clip 1 shows 1-4 s
n = p.relink(0)
check("link again keeps unlinked sound from other parts of the file", p.clips[0].linked and n == 0 and len(p.sounds) == 2)
n = p.relink(1)
check("link again removes the unlinked sound from its own part", p.clips[1].linked and n == 2 and not p.sounds,
      f"removed {n}, left {len(p.sounds)}")
p = two_clips()
p.unlink(0)
p.delete_clip(0)
check("deleting a clip keeps its unlinked sound", len(p.sounds) == 1 and len(p.clips) == 1)


# --- the saved video ----------------------------------------------------------------------------------
def tones(path, a, b):
    """Strength of 300 Hz and 600 Hz between a and b seconds of a file's sound (relative to full scale)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a), "-t", str(b - a), "-i", path, "-ac", "1", "-ar",
                          "8000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float) / 32768
    if len(x) < 800:
        return 0.0, 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x)
    hz = np.fft.rfftfreq(len(x), 1 / 8000)
    band = lambda f: float(spec[(hz > f - 20) & (hz < f + 20)].max())
    return band(300), band(600)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True).stdout.strip()
    return float(r) if r else 0.0


ON = 0.02     # a tone counts as present above this
p = two_clips()
p.unlink(0)
p.move_sound(0, 4.0)                 # c1's sound (300 Hz) now plays under c2's picture
out = f"{tmp}/moved.mp4"
export(p, out)
a1, a2 = tones(out, 0.5, 3.5)
b1, b2 = tones(out, 4.5, 7.5)
check("unlinked clip's picture is silent", a1 < ON / 4 and a2 < ON / 4, f"300 Hz {a1:.3f}, 600 Hz {a2:.3f}")
check("its sound plays where it was moved, mixed with the next clip's",
      b1 > ON and b2 > ON, f"300 Hz {b1:.3f}, 600 Hz {b2:.3f}")
check("length is the video's", abs(duration(out) - 8.0) < 0.15, f"{duration(out):.2f} s")

p = two_clips()
p.unlink(1)
p.move_sound(0, 6.0)                 # c2's sound runs 2 s past the end
p.sounds[0].volume = 0.5
out = f"{tmp}/past_end.mp4"
cmd = build(p, out, tmp)
check("the export command mixes it in", "amix=inputs=2:duration=first" in " ".join(cmd))
export(p, out)
c1_, c2_ = tones(out, 0.5, 3.5)
d1, d2 = tones(out, 4.3, 5.7)
e1, e2 = tones(out, 6.3, 7.8)
check("before the moved sound: only c1", c1_ > ON and c2_ < ON / 4, f"{c1_:.3f} / {c2_:.3f}")
check("between: silent (c2's picture is unlinked)", d1 < ON / 4 and d2 < ON / 4, f"{d1:.3f} / {d2:.3f}")
check("from 6 s: the moved sound at half volume", e2 > ON / 4 and e1 < ON / 4, f"{e1:.3f} / {e2:.3f}")
ref = tones(f"{tmp}/moved.mp4", 4.5, 7.5)[1]
check("volume applies (about half of full)", 0.35 < e2 / ref < 0.65, f"ratio {e2 / ref:.2f}")
check("sound past the end is cut: length stays 8 s", abs(duration(out) - 8.0) < 0.15, f"{duration(out):.2f} s")

p = two_clips()
p.unlink(0)
p.delete_clip(0)                     # keep the sound, drop the picture
out = f"{tmp}/deleted.mp4"
export(p, out)
f1, f2 = tones(out, 0.5, 3.5)
check("picture deleted, its sound kept under the next clip", f1 > ON and f2 > ON, f"{f1:.3f} / {f2:.3f}")

# --- preview -----------------------------------------------------------------------------------------
import gi  # noqa: E402
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402
from splice.player import Player  # noqa: E402

p = two_clips()
p.unlink(0)
p.move_sound(0, 4.0)
pl = Player(p, lambda *a: None, lambda t: None, lambda s: None)
levels = []


def meter():
    b = Gst.parse_bin_from_description("level name=lvl interval=100000000 post-messages=true ! fakesink sync=true", True)
    return b


pl.loose.sink_factory = meter
main_levels = []
mlvl = Gst.parse_bin_from_description("level interval=100000000 post-messages=true ! fakesink sync=true", True)
pl.pb.set_property("audio-sink", mlvl)


def watch(bus, msg, store):
    st = msg.get_structure()
    if st and st.get_name() == "level" and st.get_value("rms"):
        store.append((pl.t, 10 ** (st.get_value("rms")[0] / 20)))


pl.pb.get_bus().connect("message::element", watch, main_levels)
watched = set()


def hook():
    for pb in pl.loose.pbs.values():
        if id(pb) not in watched:
            watched.add(id(pb))
            pb.get_bus().add_signal_watch()
            pb.get_bus().connect("message::element", watch, levels)
    return True


loop = GLib.MainLoop()
GLib.timeout_add(100, hook)
GLib.timeout_add(500, lambda: (pl.seek(0.0), pl.play()) and False)
GLib.timeout_add(9300, lambda: (pl.close(), loop.quit()) and False)
loop.run()
early = [r for t, r in main_levels if 0.8 <= t < 3.5]
loose_before = [r for t, r in levels if t < 3.8]
loose_during = [r for t, r in levels if 4.5 <= t < 7.5]
check("preview: the unlinked clip's picture is silent", early and max(early) < 0.002, f"max {max(early or [0]):.4f}")
check("preview: the unlinked sound plays only from where it was moved",
      not loose_before and loose_during and min(loose_during) > 0.02,
      f"before {len(loose_before)}, during {len(loose_during)} min {min(loose_during or [0]):.3f}")

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)
