# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Frame accuracy: the preview shows the frame that is really on screen at a time, cuts snap to
whole frames, the exported clip starts and ends on exactly the frames the trim preview showed,
and scrubbing never shows a keyframe from far away.

Uses test videos where every frame has its own gray level (tests/make_media.sh: frameid_*.mp4),
one of them with a variable frame rate and long gaps like a screen recording."""
import bisect, os, subprocess, sys, tempfile, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gst", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gdk
from splice.model import Project
from splice import export as E, media, player as PL

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
problems = []


def check(ok, what):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        problems.append(what)


def decode(path):
    """(pts, gray level) of every frame in presentation order."""
    pts = [float(x.split(",")[0]) for x in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.split()]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=16:16,format=rgb24", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    g = [sum(raw[k:k + 768]) / 768 for k in range(0, len(raw), 768)]
    assert len(g) == len(pts), (len(g), len(pts))
    return list(zip(pts, g))


class Ref:
    def __init__(self, path):
        self.frames = decode(path)
        self.pts = [p for p, _ in self.frames]

    def at(self, t):
        """Index of the frame on screen at time t: the last one that started at or before t
        (within media.EPS, which absorbs timestamp rounding, as the app does)."""
        return max(0, bisect.bisect_right(self.pts, t + media.EPS) - 1)

    def ident(self, gray, near):
        """Which frame has this gray level, searching +-0.25 s around the frame expected at `near`
        (levels repeat only every 32 source frames)."""
        c = self.pts[self.at(near)]
        cand = [i for i, p in enumerate(self.pts) if abs(p - c) <= 0.25]
        return min(cand, key=lambda i: abs(self.frames[i][1] - gray))


# ------------------------------------------------------------------ preview
def preview_frames(path, ref, times, fast=False):
    """Seek the real player to each time and report (target, shown frame index, latency)."""
    p = Project()
    p.add_clip(path)
    shown = []

    def on_frame(tex, w, h):                # what the window would draw
        if tex is not None:
            dl = Gdk.TextureDownloader.new(tex)
            dl.set_format(Gdk.MemoryFormat.R8G8B8)
            b = dl.download_bytes()[0].get_data()
            shown.append((time.monotonic(), sum(b[::97]) / len(b[::97])))
    pl = PL.Player(p, on_frame, lambda t: None, lambda s: None)
    media.frame_times(path)                 # the app reads these when a file is opened
    pl.seek(0.0)                            # load the file first
    loop, res = GLib.MainLoop(), []

    def step(i=0):
        if i >= len(times):
            pl.close()
            loop.quit()
            return False
        t = times[i]
        n0, t0 = len(shown), time.monotonic()
        pl.seek(t, fast=fast)

        quiet = [None]

        def poll():
            # settled: no seek in flight, nothing waiting, and no new frame for 80 ms. A seek to the frame
            # already shown is skipped by the player, so the picture on screen is simply the last frame.
            now = time.monotonic()
            if pl._busy() or pl._pending is not None or (shown and now - shown[-1][0] < 0.08):
                quiet[0] = None
            elif quiet[0] is None:
                quiet[0] = now
            if (quiet[0] is not None and now - quiet[0] > 0.08) or now - t0 > 4:
                lat = shown[n0][0] - t0 if len(shown) > n0 else 0.0
                res.append((t, ref.ident(shown[-1][1], t) if shown else None, lat))
                GLib.timeout_add(20, step, i + 1)
                return False
            return True
        GLib.timeout_add(2, poll)
        return False
    GLib.timeout_add(500, step)
    loop.run()
    return res


def test_preview(name):
    path = os.path.join(D, name)
    ref = Ref(path)
    # times right on, just after and just before frames, plus in the middle of long gaps
    times = []
    for i in (5, 40, 41, 120, 200, 260, 300):
        if i + 1 < len(ref.pts):
            a, b = ref.pts[i], ref.pts[i + 1]
            times += [a, a + 0.25 * (b - a), b - 0.001]
    times += [4.2, 4.39, 7.15]
    res = preview_frames(path, ref, times)
    bad = [(round(t, 4), ref.pts[got] if got is not None else None, ref.pts[ref.at(t)]) for t, got, _ in res
           if got != ref.at(t)]
    check(not bad, f"{name}: parked preview shows the frame on screen at that time ({len(res) - len(bad)}/{len(res)})"
          + (f" wrong: {bad[:4]}" if bad else ""))


# ------------------------------------------------------------------ export
def exported(project):
    out = os.path.join(tempfile.mkdtemp(prefix="frames-"), "o.mp4")
    E.export(project, out)
    return decode(out)


def test_export(name, cuts):
    path = os.path.join(D, name)
    ref = Ref(path)
    fps = E._fps_value(E.output_fps(_proj(path)))
    for a, b in cuts:
        p = _proj(path)
        p.trim(0, new_in=a)
        p.trim(0, new_out=b, full=media.probe(path).duration)
        c = p.clips[0]
        out = exported(p)
        want_n = int(round(c.duration * fps))
        wrong = []
        for k, (tk, g) in enumerate(out):
            exp = ref.at(c.src_in + k / fps)
            got = ref.ident(g, c.src_in + k / fps)
            if got != exp:
                wrong.append((k, round(ref.pts[got], 4), round(ref.pts[exp], 4)))
        check(len(out) == want_n and not wrong,
              f"{name}: cut {a:.3f}-{b:.3f} (snapped {c.src_in:.4f}-{c.src_out:.4f}): {len(out)} frames (want {want_n}), "
              f"every frame is the one on screen at its time" + (f"; wrong (frame, got, want): {wrong[:4]}" if wrong else ""))
        # what the trim preview shows at each edge
        fi, la = preview_edge_frames(p, ref)
        check(fi == ref.at(c.src_in), f"{name}: left-edge preview = first exported frame")
        check(la == ref.at(c.src_in + (want_n - 1) / fps), f"{name}: right-edge preview = last exported frame")


def _proj(path):
    p = Project()
    p.add_clip(path)
    return p


def preview_edge_frames(p, ref):
    """The frames the app's trim preview targets for the clip's two edges."""
    from splice import lanes
    c = p.clips[0]
    t_first, t_last = lanes.edge_preview_offset(p, 0, "l"), lanes.edge_preview_offset(p, 0, "r")
    res = preview_frames(c.path, ref, [c.src_in + t_first, c.src_in + t_last])   # same file, untrimmed
    return res[0][1], res[1][1]


# ------------------------------------------------------------------ snapping
def test_snap(name):
    path = os.path.join(D, name)
    p = _proj(path)
    fps = E._fps_value(E.output_fps(p))
    for v in (1.2345, 2.00001, 3.3333, 5.9):
        p2 = _proj(path)
        p2.trim(0, new_in=v)
        p2.trim(0, new_out=v + 1.111, full=media.probe(path).duration)
        c = p2.clips[0]
        k_in, k_d = c.src_in * fps, c.duration * fps
        check(abs(k_in - round(k_in)) < 1e-6 and abs(k_d - round(k_d)) < 1e-6,
              f"{name}: trim to {v} lands on whole frames (in {c.src_in:.5f}, length {c.duration:.5f})")


# ------------------------------------------------------------------ cache
def test_cache(name, spots):
    """Frames decoded around a trim edge are filed under the right frame (checked by gray level)."""
    from splice import framecache
    path = os.path.join(D, name)
    ref = Ref(path)
    media.frame_times(path)
    for t in spots:
        fc = framecache.FrameCache()
        t0 = time.monotonic()
        fc.fill(path, t)
        lo, hi = fc._range
        want = [i for i, p in enumerate(ref.pts) if lo - 1e-6 <= p <= hi + 1e-6]
        while time.monotonic() - t0 < 10 and len(fc._frames) < len(want) and (fc._proc and fc._proc.poll() is None):
            time.sleep(0.02)
        time.sleep(0.2)
        bad, have = [], 0
        for i in want:
            hit = fc.get(path, media.frame_start(path, ref.pts[i]))
            if hit is None:
                continue
            have += 1
            buf, w, h = hit
            g = sum(buf[::7]) / len(buf[::7])
            if ref.ident(g, ref.pts[i]) != i:
                bad.append(round(ref.pts[i], 4))
        fc.stop()
        check(have == len(want) and not bad, f"{name}: cache around {t}s holds all {len(want)} frames, each the right one "
              f"({have} cached, {time.monotonic() - t0:.2f}s)" + (f" wrong: {bad[:5]}" if bad else ""))


# ------------------------------------------------------------------ dragging an edge
def test_drag(name, t0, steps=40):
    """Drag frame by frame near a spot, as when fine-trimming: every picture shown is the right frame, and
    with the frames around the edge decoded in the background the picture changes at once."""
    path = os.path.join(D, name)
    ref = Ref(path)
    p = _proj(path)
    shown = []

    def on_frame(tex, w, h):
        if tex is not None:
            dl = Gdk.TextureDownloader.new(tex)
            dl.set_format(Gdk.MemoryFormat.R8G8B8)
            b = dl.download_bytes()[0].get_data()
            shown.append(sum(b[::97]) / len(b[::97]))
    media.frame_times(path)
    pl = PL.Player(p, on_frame, lambda t: None, lambda s: None)
    pl.seek(t0)
    pl.prefetch(t0)
    loop, stats = GLib.MainLoop(), dict(instant=0, wrong=[], n=0)
    j0 = ref.at(t0)
    seq = [j0 + k for k in range(steps // 2)] + [j0 + steps // 2 - k for k in range(steps)]
    seq = [j for j in seq if 0 <= j < len(ref.pts)]

    def step(k=0):
        if k >= len(seq):
            GLib.timeout_add(600, finish)
            return False
        j = seq[k]
        t = ref.pts[j] + 0.3 * ((ref.pts[j + 1] if j + 1 < len(ref.pts) else ref.pts[j] + 0.016) - ref.pts[j])
        n0 = len(shown)
        pl.seek(t, scrub=True)
        stats["n"] += 1
        if len(shown) > n0:                     # shown right away, from the decoded frames
            stats["instant"] += 1
            if ref.ident(shown[-1], t) != j:
                stats["wrong"].append(round(ref.pts[j], 4))
        GLib.timeout_add(30, step, k + 1)
        return False

    def finish():
        if pl._busy() or pl._pending is not None:
            return True
        stats["final_ok"] = ref.ident(shown[-1], pl.t) == ref.at(pl.t)
        pl.close()
        loop.quit()
        return False
    GLib.timeout_add(800, step)                 # time for the background decode
    loop.run()
    check(not stats["wrong"] and stats["final_ok"] and stats["instant"] >= stats["n"] * 0.9,
          f"{name}: dragging frame by frame near {t0}s: {stats['instant']}/{stats['n']} pictures instant, "
          f"all the right frame, ends on the right frame" + (f"; wrong: {stats['wrong'][:5]}" if stats["wrong"] else ""))


if __name__ == "__main__":
    test_drag("frameid_vfr.mp4", 3.9)
    test_drag("frameid_vfr.mp4", 9.0)
    test_drag("frameid_2997.mp4", 5.0)
    test_cache("frameid_vfr.mp4", [0.3, 4.2, 6.0, 11.8])
    test_cache("frameid_2997.mp4", [2.0, 7.9])
    for n in ("frameid_vfr.mp4", "frameid_2997.mp4"):
        test_snap(n)
        test_preview(n)
    test_export("frameid_vfr.mp4", [(1.0, 2.5), (4.2, 4.6), (3.95, 7.15), (0.0, 0.3), (10.0, 99)])
    test_export("frameid_2997.mp4", [(1.0, 2.5), (2.51, 2.6), (0.0, 0.5), (7.0, 99)])
    print(f"PROBLEMS: {len(problems)}")
    sys.exit(1 if problems else 0)
