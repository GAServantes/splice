# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decoded frames around one spot of a file, so dragging a clip's edge frame by frame shows each frame at once.

An exact seek has to decode from the previous keyframe, which in a screen recording can be seconds away
(a quarter of a second per frame on a 1440p recording). While an edge is being dragged, one ffmpeg decodes
the second on either side of it in the background, at a size that keeps the whole set within a memory
budget. Each frame is filed under its own start time (read from ffmpeg, not counted), so a cached
frame is always the right frame; the player still shows the sharp full-size frame once the pointer rests.
"""
import bisect, re, subprocess, threading

from . import media

BUDGET = 96 * 1024 * 1024        # bytes of decoded pictures kept at most
SPAN = 1.0                       # seconds decoded on each side of the spot
_PTS = re.compile(rb"\bpts_time:\s*(-?[0-9.]+)")


class FrameCache:
    def __init__(self, max_w=960, max_h=540):
        self.max_w, self.max_h = max_w, max_h
        self._lock = threading.Lock()
        self._path = None
        self._range = (0.0, -1.0)            # file times covered (once decoded)
        self._frames = {}                    # frame start time -> (bytes, w, h)
        self._proc = None
        self._gen = 0

    def covers(self, path, t):
        with self._lock:
            return self._path == path and self._range[0] <= t <= self._range[1]

    def get(self, path, start):
        """The decoded picture for the frame starting at `start` (from media.frame_start), or None."""
        with self._lock:
            if self._path != path:
                return None
            return self._frames.get(round(start, 6))

    def fill(self, path, t):
        """Start decoding around file time t, unless that is already covered or under way."""
        ts = media.frame_times(path) if media.frames_ready(path) else None
        if not ts or self.covers(path, t):
            return
        k0 = max(0, bisect.bisect_right(ts, t - SPAN + media.EPS) - 1)
        k1 = min(len(ts), bisect.bisect_right(ts, t + SPAN))
        if k1 <= k0:
            return
        a = ts[k0]
        b = ts[k1] if k1 < len(ts) else ts[-1] + 1.0
        try:
            info = media.probe(path)
        except Exception:
            return
        w, h = _size(info.width, info.height, k1 - k0, self.max_w, self.max_h)
        self.stop()
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._path, self._range, self._frames = path, (a, ts[k1 - 1] if k1 > k0 else a), {}
        starts = ts[k0:k1]
        start_at = max(0.0, a - 0.0005)              # just before the first frame's start, so it is included
        cmd = ["ffmpeg", "-v", "info", "-nostdin", "-hide_banner", "-nostats", "-threads", "0",
               "-ss", f"{start_at:.6f}", "-t", f"{b - start_at:.6f}", "-i", path, "-an", "-sn",
               "-vf", f"showinfo,scale={w}:{h}:flags=bilinear,format=rgb24",
               "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        except OSError:
            return
        self._proc = proc
        threading.Thread(target=self._read, args=(proc, gen, path, starts, start_at, w, h), daemon=True).start()

    def _read(self, proc, gen, path, starts, start_at, w, h):
        times = []                                   # showinfo lines arrive (on stderr) before their pictures
        got = threading.Condition()

        def err():
            for line in proc.stderr:
                m = _PTS.search(line) if b"Parsed_showinfo" in line else None
                if m:
                    with got:
                        times.append(float(m.group(1)) + start_at)
                        got.notify()
            with got:
                times.append(None)
                got.notify()
        threading.Thread(target=err, daemon=True).start()
        size, k = w * h * 3, 0
        try:
            while True:
                buf = proc.stdout.read(size)
                if not buf or len(buf) < size:
                    break
                with got:
                    while len(times) <= k:
                        got.wait(2.0)
                        if proc.poll() is not None and len(times) <= k:
                            break
                    pts = times[k] if len(times) > k else None
                k += 1
                if pts is None:
                    break
                # file it under the frame start it belongs to (within a millisecond), never by counting
                j = bisect.bisect_left(starts, pts - 0.001)
                if j >= len(starts) or abs(starts[j] - pts) > 0.001:
                    continue
                with self._lock:
                    if gen != self._gen:
                        break
                    self._frames[round(starts[j], 6)] = (buf, w, h)
        finally:
            for f in (proc.stdout, proc.stderr):
                try:
                    f.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def stop(self):
        """Stop decoding and forget the frames."""
        p, self._proc = self._proc, None
        with self._lock:
            self._gen += 1
            self._path, self._range, self._frames = None, (0.0, -1.0), {}
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass


def _size(fw, fh, n, max_w, max_h):
    """Picture size: the preview size, smaller when many frames would not fit the budget."""
    s = min(1.0, max_w / max(1, fw), max_h / max(1, fh))
    per = BUDGET / max(1, n) / 3
    s = min(s, (per / max(1, fw * fh)) ** 0.5)
    return max(2, int(fw * s) // 2 * 2), max(2, int(fh * s) // 2 * 2)

