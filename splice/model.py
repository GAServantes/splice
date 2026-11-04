# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project model. Times are seconds. Crop is [x, y, w, h] as fractions of the picture."""
import json, os
from dataclasses import dataclass, field, asdict, fields
from typing import Optional

from .media import probe, snap


@dataclass
class Clip:
    path: str
    src_in: float
    src_out: float
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    crop: Optional[list] = None
    # Volume line: [[seconds_into_clip, gain], ...]. Empty means flat `volume`.
    env: list = field(default_factory=list)
    # False once the clip's sound has been unlinked: the picture plays silent, and the sound lives on as a
    # separate Sound in Project.sounds that can be moved and trimmed on its own.
    linked: bool = True

    @property
    def duration(self) -> float:
        return max(0.0, self.src_out - self.src_in)

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    def set_in(self, v: float):
        """Move the in-point; the volume line stays attached to the picture."""
        v = max(0.0, min(v, self.src_out - 0.1))
        d = v - self.src_in
        if self.env and abs(d) > 1e-9:
            env = sorted(self.env)
            if d > 0:
                g0 = self.line_at(d)
                self.env = [[0.0, g0]] + [[x - d, g] for x, g in env if x - d > 1e-6]
            else:
                self.env = [[x - d, g] for x, g in env]
        self.src_in = v

    def set_out(self, v: float, full: Optional[float] = None):
        """Move the out-point (clamped to the media length); points beyond the new end collapse to one."""
        v = max(self.src_in + 0.1, v)
        if full:
            v = min(v, full)
        new_dur = v - self.src_in
        if self.env and any(x > new_dur for x, _ in self.env):
            g = self.line_at(new_dur)
            self.env = [[x, y] for x, y in sorted(self.env) if x < new_dur - 1e-6] + [[new_dur, g]]
        self.src_out = v

    def line_at(self, off: float) -> float:
        """Gain from the volume line at `off` seconds into the clip (no fades)."""
        pts = sorted(self.env)
        if not pts:
            return self.volume
        if off <= pts[0][0]:
            return pts[0][1]
        for (t0, g0), (t1, g1) in zip(pts, pts[1:]):
            if off <= t1:
                return g0 + (g1 - g0) * (off - t0) / max(t1 - t0, 1e-6)
        return pts[-1][1]

    def gain_at(self, off: float) -> float:
        """Final gain at `off`: the volume line times fades."""
        g = self.line_at(off)
        if self.fade_in > 0 and off < self.fade_in:
            g *= max(0.0, off / self.fade_in)
        if self.fade_out > 0 and off > self.duration - self.fade_out:
            g *= max(0.0, (self.duration - off) / self.fade_out)
        return g


@dataclass
class Sound(Clip):
    """Sound unlinked from its video: the same source range, volume line and fades as a clip, but placed at its
    own timeline time (`start`) instead of under the picture. Unlinked sound never moves when clips are trimmed,
    moved or deleted; anything past the end of the video is not in the saved video."""
    start: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Text:
    text: str
    start: float
    end: float
    pos: str = "bottom"      # top | middle | bottom
    size: float = 0.06       # fraction of picture height
    color: str = "#ffffff"


@dataclass
class Project:
    clips: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    sounds: list = field(default_factory=list)

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

    def clip_start(self, i: int) -> float:
        return sum(c.duration for c in self.clips[:i])

    def clip_at(self, t: float):
        """Return (index, seconds into that clip) for a timeline time."""
        acc = 0.0
        for i, c in enumerate(self.clips):
            if t < acc + c.duration or i == len(self.clips) - 1:
                return i, min(max(0.0, t - acc), c.duration)
            acc += c.duration
        return 0, 0.0

    # --- captions travel with the clip they start in --------------------------------------------------
    def _anchor_map(self):
        """For each caption: (clip object, seconds after that clip's start) for the clip it starts in, or None."""
        out = []
        for t in self.texts:
            a, acc = None, 0.0
            for c in self.clips:
                if acc - 1e-6 <= t.start < acc + c.duration - 1e-6:
                    a = (c, t.start - acc)
                    break
                acc += c.duration
            out.append(a)
        return out

    def _start_of(self, clip) -> float:
        acc = 0.0
        for c in self.clips:
            if c is clip:
                return acc
            acc += c.duration
        return acc

    def _reanchor(self, amap):
        """Put every anchored caption back at the same spot inside its clip, wherever that clip is now."""
        for t, a in zip(self.texts, amap):
            if a:
                d = t.end - t.start
                t.start = self._start_of(a[0]) + a[1]
                t.end = t.start + d

    def reorder(self, i: int, new: int):
        """Move clip i to position `new`. Captions that start inside any clip stay with that clip."""
        if i == new:
            return
        amap = self._anchor_map()
        self.clips.insert(new, self.clips.pop(i))
        self._reanchor(amap)

    def delete_clip(self, i: int) -> int:
        """Remove a clip and the captions that start inside it; later captions move up with their clips."""
        amap = self._anchor_map()
        gone = self.clips.pop(i)
        keep = [(t, a) for t, a in zip(self.texts, amap) if not (a and a[0] is gone)]
        removed = len(self.texts) - len(keep)
        self.texts[:] = [t for t, _ in keep]
        self._reanchor([a for _, a in keep])
        return removed

    def trim(self, i: int, new_in: Optional[float] = None, new_out: Optional[float] = None,
             full: Optional[float] = None) -> int:
        """Change a clip's in/out. Its captions keep their place on the picture (a left trim slides them
        earlier, parts trimmed away are cut off), later clips and their captions move with it.
        Returns how many captions were removed because their picture is now gone."""
        amap = self._anchor_map()
        c = self.clips[i]
        old_in = c.src_in
        if new_in is not None:                     # cuts land on whole frames
            c.set_in(snap(c.path, new_in, 0.0, c.src_out - 0.1))
        if new_out is not None:
            end = full or float("inf")
            c.set_out(end if new_out >= end else snap(c.path, new_out, c.src_in + 0.1, end), full)
        shift, new_dur = c.src_in - old_in, c.duration
        keep, removed = [], 0
        for t, a in zip(self.texts, amap):
            if a and a[0] is c:
                off, dur = a[1] - shift, t.end - t.start
                if off >= new_dur - 1e-6 or off + dur <= 1e-6:      # its picture was trimmed away
                    removed += 1
                    continue
                if off < 0:                                          # start trimmed away: show what remains
                    dur, off = off + dur, 0.0
                t.end = t.start + max(0.1, dur)                      # _reanchor keeps this length
                a = (c, off)
            keep.append((t, a))
        self.texts[:] = [t for t, _ in keep]
        self._reanchor([a for _, a in keep])
        return removed

    def add_clip(self, path: str, index: Optional[int] = None) -> Clip:
        info = probe(path)
        c = Clip(path, 0.0, info.duration)
        amap = self._anchor_map()
        self.clips.insert(len(self.clips) if index is None else index, c)
        self._reanchor(amap)
        return c

    def split(self, t: float) -> bool:
        """Split the clip under timeline time t into two. Returns False if too close to an edge."""
        if not self.clips:
            return False
        i, off = self.clip_at(t)
        c = self.clips[i]
        off = snap(c.path, c.src_in + off) - c.src_in      # split between two frames
        if off < 0.1 or c.duration - off < 0.1:
            return False
        env = sorted(c.env)
        g = c.line_at(off)
        left_env = [[x, y] for x, y in env if x < off - 1e-6] + [[off, g]] if env else []
        right_env = [[0.0, g]] + [[x - off, y] for x, y in env if x > off + 1e-6] if env else []
        right = Clip(c.path, c.src_in + off, c.src_out, c.volume, 0.0, c.fade_out,
                     list(c.crop) if c.crop else None, right_env, c.linked)
        c.src_out = c.src_in + off
        c.fade_out = 0.0
        c.env = left_env
        self.clips.insert(i + 1, right)
        return True

    # --- unlinked sound --------------------------------------------------------------------------------
    def unlink(self, i: int) -> int:
        """Split clip i's sound off into a Sound at the same place, with the same volume line and fades.
        The clip plays silent from now on. Returns the new Sound's index."""
        c = self.clips[i]
        s = Sound(c.path, c.src_in, c.src_out, c.volume, c.fade_in, c.fade_out, None,
                  [list(q) for q in c.env], start=self.clip_start(i))
        c.linked = False
        self.sounds.append(s)
        return len(self.sounds) - 1

    def relink(self, i: int) -> int:
        """Give clip i its own sound back, in sync, and remove the unlinked sound that came from its part of
        the file (it would play twice otherwise). Returns how many unlinked sounds were removed."""
        c = self.clips[i]
        keep = [s for s in self.sounds
                if not (s.path == c.path and s.src_in < c.src_out - 1e-6 and s.src_out > c.src_in + 1e-6)]
        removed = len(self.sounds) - len(keep)
        self.sounds[:] = keep
        c.linked = True
        return removed

    def unlinked_from(self, i: int) -> list:
        """Indexes of the unlinked sounds that came from clip i's part of its file."""
        c = self.clips[i]
        return [j for j, s in enumerate(self.sounds)
                if s.path == c.path and s.src_in < c.src_out - 1e-6 and s.src_out > c.src_in + 1e-6]

    def move_sound(self, j: int, start: float):
        self.sounds[j].start = max(0.0, start)

    def trim_sound(self, j: int, new_in: Optional[float] = None, new_out: Optional[float] = None,
                   full: Optional[float] = None):
        """Trim an unlinked sound. The sound itself stays where it is on the timeline: trimming the left edge
        moves the start with it (and never before the timeline's start)."""
        s = self.sounds[j]
        if new_in is not None:
            old = s.src_in
            s.set_in(max(new_in, old - s.start))
            s.start = max(0.0, s.start + s.src_in - old)
        if new_out is not None:
            s.set_out(new_out, full)

    def split_sound(self, j: int, t: float) -> bool:
        """Split unlinked sound j at timeline time t into two. False if t is too close to an edge."""
        s = self.sounds[j]
        off = t - s.start
        if off < 0.1 or s.duration - off < 0.1:
            return False
        env = sorted(s.env)
        g = s.line_at(off)
        left_env = [[x, y] for x, y in env if x < off - 1e-6] + [[off, g]] if env else []
        right_env = [[0.0, g]] + [[x - off, y] for x, y in env if x > off + 1e-6] if env else []
        right = Sound(s.path, s.src_in + off, s.src_out, s.volume, 0.0, s.fade_out, None, right_env,
                      start=s.start + off)
        s.src_out = s.src_in + off
        s.fade_out = 0.0
        s.env = left_env
        self.sounds.insert(j + 1, right)
        return True

    def save(self, path: str):
        """Write atomically: a crash or full disk never leaves a half-written project."""
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"version": 1, "clips": [asdict(c) for c in self.clips],
                       "texts": [asdict(t) for t in self.texts],
                       "sounds": [asdict(s) for s in self.sounds]}, f, indent=1)
        os.replace(tmp, path)

    @staticmethod
    def load(path: str) -> "Project":
        """Tolerant of newer files: unknown fields are ignored, missing ones take defaults."""
        with open(path) as f:
            d = json.load(f)
        ck, tk, sk = ({f.name for f in fields(Clip)}, {f.name for f in fields(Text)},
                      {f.name for f in fields(Sound)})
        clips = [Clip(**{k: v for k, v in c.items() if k in ck}) for c in d["clips"]]
        texts = [Text(**{k: v for k, v in t.items() if k in tk}) for t in d["texts"]]
        sounds = [Sound(**{k: v for k, v in s.items() if k in sk}) for s in d.get("sounds", [])]
        for c in clips + sounds:
            c.env = sorted([list(p) for p in c.env])
        return Project(clips, texts, sounds)
