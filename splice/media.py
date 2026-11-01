# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Probe media files with ffprobe."""
import json, subprocess
from dataclasses import dataclass


@dataclass
class MediaInfo:
    path: str
    width: int          # as displayed (after rotation)
    height: int
    duration: float
    has_audio: bool
    fps: float
    rotation: int = 0


_cache: dict[str, MediaInfo] = {}
_COMMON = [(24000 / 1001, "24000/1001"), (24.0, "24"), (25.0, "25"), (30000 / 1001, "30000/1001"), (30.0, "30"),
           (48.0, "48"), (50.0, "50"), (60000 / 1001, "60000/1001"), (60.0, "60")]


def _rate(s: str) -> float:
    try:
        n, _, d = (s or "0/1").partition("/")
        return float(n) / float(d or 1) if float(d or 1) else 0.0
    except ValueError:
        return 0.0


def fps_string(fps: float) -> str:
    """Nearest common frame rate as an ffmpeg rational (keeps 29.97 and 59.94 exact)."""
    fps = min(60.0, max(10.0, fps or 30.0))
    best = min(_COMMON, key=lambda c: abs(c[0] - fps))
    return best[1] if abs(best[0] - fps) < 0.35 else str(int(round(fps)))


def _scan_duration(path: str) -> float:
    """Duration for files whose header has none (some MKV recordings): last packet time."""
    p = subprocess.Popen(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,duration_time",
                          "-of", "csv=p=0", "-i", path], stdout=subprocess.PIPE, text=True)
    last = 0.0
    for line in p.stdout:
        parts = line.strip().split(",")
        try:
            last = max(last, float(parts[0]) + (float(parts[1]) if len(parts) > 1 and parts[1] not in ("", "N/A") else 0.0))
        except ValueError:
            pass
    p.wait()
    return last


def probe(path: str) -> MediaInfo:
    if path in _cache:
        return _cache[path]
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", "-i", path],
        capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if v is None:
        raise ValueError("No video in this file")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(round(float(sd["rotation"])))
    if not rot and "rotate" in v.get("tags", {}):
        try:
            rot = -int(float(v["tags"]["rotate"]))
        except ValueError:
            pass
    w, h = int(v["width"]), int(v["height"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    avg, r = _rate(v.get("avg_frame_rate")), _rate(v.get("r_frame_rate"))
    cfr = avg > 0 and r > 0 and abs(avg - r) < 0.5
    fps = r if cfr else max(24.0, min(60.0, r if 0 < r <= 120 else (avg or 30.0)))
    try:
        dur = float(data["format"].get("duration") or v.get("duration") or 0)
    except ValueError:
        dur = 0.0
    if dur <= 0:
        dur = _scan_duration(path)
    info = MediaInfo(path, w, h, dur, has_audio, fps or 30.0, rot)
    _cache[path] = info
    return info
