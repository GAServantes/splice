# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Waveform peaks via ffmpeg (no numpy): PEAK_RATE values per second, each 0..1."""
import math, subprocess

PEAK_RATE = 25
_SR = 4000


def compute(path: str) -> list[float]:
    af = (f"aresample={_SR},asetnsamples=n={_SR // PEAK_RATE}:p=0,"
          "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-")
    p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True)
    out = []
    for line in p.stdout.splitlines():
        if line.startswith("lavfi.astats.Overall.Peak_level="):
            v = line.split("=", 1)[1]
            try:
                db = float(v)
                out.append(0.0 if math.isinf(db) else min(1.0, 10 ** (db / 20)))
            except ValueError:
                out.append(0.0)
    return out
