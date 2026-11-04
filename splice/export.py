# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn a Project into one ffmpeg command and run it."""
import atexit, os, subprocess, tempfile, shutil, threading
from typing import Callable, Optional

from .media import probe, fps_string, frame_start, EPS
from .model import Project
from . import textfit

_gpu_cache: dict = {}
# GPU encode settings, tuned against x264 (veryfast, CRF 20) on this machine's Radeon: QP 27 with no B-frames
# gives the same perceived quality (SSIM) and runs faster than the CPU encode. B-frames cost ~40% speed.
GPU_QP = 27


def _vram(node: str) -> int:
    try:
        with open(f"/sys/class/drm/{os.path.basename(node)}/device/mem_info_vram_total") as f:
            return int(f.read())
    except (OSError, ValueError):
        return 0


def gpu_device() -> Optional[str]:
    """The render node to encode on, or None when there is no working VAAPI H.264 encoder.
    Prefers the card with the most video memory (your discrete GPU over the CPU's built-in graphics).
    Override with SPLICE_VAAPI_DEVICE; SPLICE_ENCODER=cpu turns the GPU off."""
    if os.environ.get("SPLICE_ENCODER", "").lower() == "cpu":
        return None
    if "dev" in _gpu_cache:
        return _gpu_cache["dev"]
    forced = os.environ.get("SPLICE_VAAPI_DEVICE")
    nodes = [forced] if forced else sorted((os.path.join("/dev/dri", n) for n in os.listdir("/dev/dri") if n.startswith("renderD")),
                                           key=lambda n: -_vram(n)) if os.path.isdir("/dev/dri") else []
    found = None
    for node in nodes:
        try:
            r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-init_hw_device", f"vaapi=gpu:{node}", "-filter_hw_device", "gpu",
                                "-f", "lavfi", "-i", "color=c=black:s=256x256:r=30:d=0.2", "-vf", "format=nv12,hwupload",
                                "-c:v", "h264_vaapi", "-f", "null", "-"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            found = node
            break
    _gpu_cache["dev"] = found
    return found


FORMATS = {".mp4": "mp4", ".mov": "mov", ".mkv": "matroska"}


class ExportCanceled(Exception):
    pass


_running: set = set()
_parts: set = set()


def kill_all():
    """Stop any ffmpeg we started (called when the app quits mid-export, so nothing is left running)."""
    for proc in list(_running):
        try:
            proc.kill()
            proc.wait(2)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for part in list(_parts):
        try:
            os.remove(part)
        except OSError:
            pass


atexit.register(kill_all)


def _even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def _gain_expr(c) -> str:
    """Piecewise-linear gain over clip time t, as an ffmpeg expression (points are absolute gains)."""
    pts = sorted(c.env)
    if not pts:
        return f"{c.volume:.4f}"
    pts = [[0.0, pts[0][1]]] + pts + [[max(c.duration, pts[-1][0]), pts[-1][1]]]
    expr = f"{pts[-1][1]:.4f}"
    for (t0, g0), (t1, g1) in reversed(list(zip(pts, pts[1:]))):
        if t1 - t0 < 1e-6:
            continue
        seg = f"({g0:.4f}+({g1 - g0:.4f})*(t-{t0:.4f})/{t1 - t0:.4f})"
        expr = f"if(lt(t\\,{t1:.4f})\\,{seg}\\,{expr})"
    return expr


def _fades(c) -> str:
    """afade filters for a clip's (or unlinked sound's) fade in and out, starting with a comma; "" for none."""
    out = ""
    if c.fade_in > 0:
        out += f",afade=t=in:st=0:d={min(c.fade_in, c.duration):.3f}"
    if c.fade_out > 0:
        fo = min(c.fade_out, c.duration)
        out += f",afade=t=out:st={max(0, c.duration - fo):.3f}:d={fo:.3f}"
    return out


def crop_rect(c, info) -> tuple[int, int, int, int]:
    """Crop as whole, even pixels inside the (rotated) frame: (x, y, w, h). Never smaller than 2x2."""
    iw, ih = info.width, info.height
    x, y, w, h = c.crop
    cw = min(max(2, int(iw * w) // 2 * 2), max(2, iw // 2 * 2))
    ch = min(max(2, int(ih * h) // 2 * 2), max(2, ih // 2 * 2))
    cx = max(0, min(int(iw * x), iw - cw)) // 2 * 2
    cy = max(0, min(int(ih * y), ih - ch)) // 2 * 2
    return cx, cy, cw, ch


def output_fps(p: Project) -> str:
    return fps_string(probe(p.clips[0].path).fps)


def output_size(p: Project) -> tuple[int, int]:
    c = p.clips[0]
    info = probe(c.path)
    w, h = info.width, info.height
    if c.crop:
        _, _, w, h = crop_rect(c, info)
    return _even(w), _even(h)


def _frames(dur: float, fps: float) -> int:
    return max(1, int(round(dur * fps)))


def _fps_value(s: str) -> float:
    n, _, d = s.partition("/")
    return float(n) / float(d or 1)


def segment_times(p: Project) -> list[float]:
    """Output length of each clip: whole frames at the output rate."""
    f = _fps_value(output_fps(p))
    return [_frames(c.duration, f) / f for c in p.clips]


def output_duration(p: Project) -> float:
    return sum(segment_times(p)) if p.clips else 0.0


def map_time(p: Project, t: float) -> float:
    """Timeline time (sum of exact clip lengths) -> exported time (sum of whole-frame lengths)."""
    segs = segment_times(p)
    nom = out = 0.0
    for c, s in zip(p.clips, segs):
        if t < nom + c.duration:
            return out + (t - nom) * (s / c.duration if c.duration else 1)
        nom += c.duration
        out += s
    return out + (t - nom)


def build(p: Project, out: str, workdir: str, crf: int = 20, fmt: str = "mp4", gpu: Optional[str] = None) -> list[str]:
    if not p.clips:
        raise ValueError("Add at least one clip first.")
    W, H = output_size(p)
    fps_s = output_fps(p)
    fps = _fps_value(fps_s)
    segs = segment_times(p)
    cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    if gpu:
        cmd += ["-init_hw_device", f"vaapi=gpu:{gpu}", "-filter_hw_device", "gpu"]
    filt, labels, n_in = [], [], 0
    for i, (c, seg) in enumerate(zip(p.clips, segs)):
        info = probe(c.path)
        # Seek on the input: only the needed part is decoded (fast and light on memory for long recordings).
        # Decoding stays on the CPU: GPU decode would have to copy every frame back for the CPU filters (slower).
        cmd += ["-threads", "1" if len(p.clips) > 4 else "0"]
        # Start the read at the frame that is on screen at the in-point (a still screen may have started it
        # well before), so the clip opens on the frame the preview showed and the picture stays in sync.
        held = frame_start(c.path, c.src_in)
        start = max(0.0, min(c.src_in, (held if held is not None else c.src_in - 1.0) - 0.0005))
        look = c.src_in - start
        cmd += ["-ss", f"{start:.6f}", "-t", f"{look + seg + 0.25:.6f}", "-i", c.path]
        vi = n_in
        n_in += 1
        crop = ""
        if c.crop:
            cx, cy, cw, ch = crop_rect(c, info)
            crop = f",crop={cw}:{ch}:{cx}:{cy}"
        nfr = _frames(seg, fps)
        # Times are now relative to the read start; shift them to the in-point. With round=up, output frame k
        # shows the last frame that started at or before in + k/fps (the same frame the preview shows there),
        # and start_time=0 holds the frame that was already on screen at the in-point.
        filt.append(f"[{vi}:v:0]setpts=PTS-{look + EPS:.6f}/TB,fps={fps_s}:round=up:start_time=0,"
                    f"tpad=stop=-1:stop_mode=clone{crop},"
                    f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,trim=end_frame={nfr},setpts=PTS-STARTPTS[v{i}]")
        fmt_a = "aformat=sample_fmts=fltp:channel_layouts=stereo"
        exact = f"apad=whole_dur={seg:.4f},atrim=end={seg:.4f},asetpts=PTS-STARTPTS"
        if info.has_audio and c.linked:
            filt.append(f"[{vi}:a:0]atrim=start={look:.6f},asetpts=PTS-STARTPTS,volume='{_gain_expr(c)}':eval=frame{_fades(c)},"
                        f"aresample=48000,{fmt_a},{exact}[a{i}]")
        else:
            cmd += ["-f", "lavfi", "-t", f"{seg:.4f}", "-i", "anullsrc=r=48000:cl=stereo"]
            filt.append(f"[{n_in}:a]{fmt_a},{exact}[a{i}]")
            n_in += 1
        labels.append(f"[v{i}][a{i}]")
    loose = []
    total = sum(segs)
    for j, snd in enumerate(p.sounds):             # unlinked sound, mixed in at its own place
        at = map_time(p, snd.start)
        if at >= total - 0.001 or snd.duration <= 0 or not probe(snd.path).has_audio:
            continue                                # starts after the video ends: not in the saved video
        length = min(snd.duration, total - at)
        cmd += ["-vn", "-ss", f"{snd.src_in:.6f}", "-t", f"{length + 0.25:.6f}", "-i", snd.path]
        filt.append(f"[{n_in}:a:0]asetpts=PTS-STARTPTS,atrim=end={length:.6f},volume='{_gain_expr(snd)}':eval=frame"
                    f"{_fades(snd)},aresample=48000,{fmt_a},adelay={int(round(at * 1000))}:all=1[u{j}]")
        loose.append(f"[u{j}]")
        n_in += 1
    if loose:
        filt.append(f"{''.join(labels)}concat=n={len(p.clips)}:v=1:a=1[vc][ac]")
        filt.append(f"[ac]{''.join(loose)}amix=inputs={len(loose) + 1}:duration=first:normalize=0[aout]")
    else:
        filt.append(f"{''.join(labels)}concat=n={len(p.clips)}:v=1:a=1[vc][aout]")
    chain, last = [], "vc"
    for j, t in enumerate(p.texts):
        if not t.text.strip():
            continue
        px = _even(textfit.fit_px(t.text, H * t.size, W))
        png = os.path.join(workdir, f"t{j}.png")
        bw, bh = textfit.render_png(png, t.text, px, t.color)
        x, y = textfit.box_position(t.pos, W, H, bw, bh)
        s, e = map_time(p, t.start), map_time(p, t.end)
        cmd += ["-i", png]
        k, n_in = n_in, n_in + 1
        nxt = f"vt{j}"
        chain.append(f"[{last}][{k}:v]overlay=x={int(round(x))}:y={int(round(y))}:format=auto:"
                     f"enable='between(t,{s:.3f},{e:.3f})'[{nxt}]")
        last = nxt
    filt += chain
    filt.append(f"[{last}]{'format=nv12,hwupload' if gpu else 'null'}[vout]")
    if gpu:
        video = ["-c:v", "h264_vaapi", "-rc_mode", "CQP", "-qp", str(GPU_QP), "-bf", "0", "-profile:v", "high"]
    else:
        video = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    cmd += ["-filter_complex", ";".join(filt), "-map", "[vout]", "-map", "[aout]", *video,
            "-c:a", "aac", "-b:a", "160k", "-f", fmt]
    if fmt in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(out)
    return cmd


def export(p: Project, out: str, progress: Optional[Callable[[float], None]] = None, crf: int = 20,
           cancel: Optional[threading.Event] = None, use_gpu: bool = True) -> str:
    """Run the export on the GPU when it can (falling back to the CPU if it cannot). Calls progress(0..1).
    Writes to a temporary name and renames on success, so an existing file is never damaged by a failed or
    canceled run. Returns "gpu" or "cpu": which one did the encoding."""
    ext = os.path.splitext(out)[1].lower()
    if ext not in FORMATS:
        raise ValueError("Save as .mp4, .mov or .mkv.")
    real_out = os.path.realpath(out)
    for c in p.clips + p.sounds:
        if not os.path.exists(c.path):
            raise ValueError(f"A video file is missing: {c.path}")
        if os.path.realpath(c.path) == real_out:
            raise ValueError("That file is one of your clips. Pick a different name.")
    if not os.path.isdir(os.path.dirname(real_out) or "."):
        raise ValueError("That folder does not exist.")
    work = tempfile.mkdtemp(prefix="splice-")
    part = out + ".splice-part"
    _parts.add(part)
    try:
        dev = gpu_device() if use_gpu else None
        if dev:
            try:
                _encode(p, out, part, work, crf, FORMATS[ext], dev, progress, cancel)
                return "gpu"
            except ExportCanceled:
                raise
            except RuntimeError as err:          # the GPU path failed: finish on the CPU instead of failing the export
                _gpu_cache["last_error"] = str(err)
        _encode(p, out, part, work, crf, FORMATS[ext], None, progress, cancel)
        return "cpu"
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _parts.discard(part)
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def _encode(p, out, part, work, crf, fmt, gpu, progress, cancel):
    """One ffmpeg run (GPU when `gpu` is a render node, else CPU) into `part`, then rename onto `out`."""
    errf = tempfile.TemporaryFile("w+")
    try:
        for f in os.listdir(work):                # a retry starts from a clean work folder
            if f.startswith("t") and f.endswith(".png"):
                os.remove(os.path.join(work, f))
        cmd = build(p, part, work, crf, fmt, gpu)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True)
        _running.add(proc)
        total = max(output_duration(p), 0.001)
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                _running.discard(proc)
                raise ExportCanceled()
            if line.startswith("out_time_us=") and progress:
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / total))
                except ValueError:
                    pass
        rc = proc.wait()
        _running.discard(proc)
        if cancel is not None and cancel.is_set():
            raise ExportCanceled()
        if rc != 0:
            errf.seek(0)
            raise RuntimeError(errf.read().strip()[-800:] or "ffmpeg failed")
        os.replace(part, out)
        if progress:
            progress(1.0)
    finally:
        errf.close()
