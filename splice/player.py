# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview player: one GStreamer playbin that follows the project's clips in order.

Frames arrive through an appsink, are scaled small, and handed to the UI as Gdk textures.
Crop and text are drawn by the UI on top, so the pipeline stays simple.
"""
import os
import threading
import gi
gi.require_version("Gst", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gst, GLib, Gdk

from . import framecache, media

Gst.init(None)
PREVIEW_W, PREVIEW_H = 960, 540


class Player:
    def __init__(self, project, on_frame, on_time, on_state, on_error=None):
        self.project = project
        self.on_frame, self.on_time, self.on_state = on_frame, on_time, on_state
        self.on_error = on_error
        self._reported = set()
        self.t = 0.0
        self.playing = False
        self._loaded = None       # path currently loaded
        self._idx = 0             # clip index we are inside
        self._tick_id = 0
        self._seeking = 0.0       # monotonic time the last seek started, 0 when settled
        self._pending = None      # scrub target waiting for the seek in flight to finish
        self._target = None       # (path, position) of the last seek, so a repeat costs nothing
        self._gen = 0             # bumped when a picture from the cache replaces what GStreamer was decoding
        self._sharp_id = 0        # timer: full-size picture once the pointer rests on a cached frame
        self._full_wh = None      # size of GStreamer's pictures (the cache reports the same, for the layout)
        self.cache = framecache.FrameCache(PREVIEW_W, PREVIEW_H)
        self.loose = LooseSounds(project)     # unlinked sound, played alongside the picture
        self._prefetching = None  # path whose frames are being cached for a drag
        self._cached = None       # (path, frame start) of the cached picture on screen
        self._eos = False
        self.pb = Gst.ElementFactory.make("playbin", "pb")
        sinkbin = Gst.parse_bin_from_description(
            "videoflip video-direction=auto ! videoscale ! "
            f"video/x-raw,width=[1,{PREVIEW_W}],height=[1,{PREVIEW_H}],pixel-aspect-ratio=1/1 ! "
            "videoconvert ! video/x-raw,format=RGB ! "
            "appsink name=sink emit-signals=true sync=true max-buffers=1 drop=true", True)
        self.pb.set_property("video-sink", sinkbin)
        sink = sinkbin.get_by_name("sink")
        sink.connect("new-sample", self._sample, "pull-sample")
        sink.connect("new-preroll", self._sample, "pull-preroll")
        if os.environ.get("SPLICE_NOAUDIO"):
            fake = Gst.ElementFactory.make("fakesink")
            fake.set_property("sync", True)
            self.pb.set_property("audio-sink", fake)
        self.pb.get_bus().add_signal_watch()
        self.pb.get_bus().connect("message::async-done", self._async_done)
        self.pb.get_bus().connect("message::eos", lambda b, m: setattr(self, "_eos", True))
        self.pb.get_bus().connect("message::error", lambda b, m: self._report("Preview problem: " + m.parse_error()[0].message))

    # --- frames -----------------------------------------------------------
    def _sample(self, sink, which):
        sample = sink.emit(which)
        if sample is None:
            return Gst.FlowReturn.OK
        caps = sample.get_caps().get_structure(0)
        w, h = caps.get_value("width"), caps.get_value("height")
        ok, mi = sample.get_buffer().map(Gst.MapFlags.READ)
        if ok:
            data = GLib.Bytes.new(mi.data)         # one copy, owned by the texture
            sample.get_buffer().unmap(mi)
            GLib.idle_add(self._show, data, w, h, self._gen)
        return Gst.FlowReturn.OK

    def _show(self, data, w, h, gen=None):
        if gen is not None:
            if gen != self._gen:
                return False                       # a cached picture already shows a newer position
            self._full_wh = (w, h)
            self._cached = None
        stride = data.get_size() // h
        lw, lh = self._full_wh if gen is None and self._full_wh else (w, h)
        self.on_frame(Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8, data, stride), lw, lh)
        return False

    # --- frames near a trim edge -------------------------------------------
    def prefetch(self, t):
        """Decode the frames around timeline time t in the background (used while an edge is dragged)."""
        p = self.project
        if p.clips:
            i, off = p.clip_at(max(0.0, min(t, p.duration - 0.001)))
            self._prefetching = p.clips[i].path
            self.cache.fill(p.clips[i].path, p.clips[i].src_in + off)

    def end_prefetch(self):
        """The drag is over: stop decoding and free the cached pictures."""
        self._prefetching = None
        self.cache.stop()

    def _from_cache(self, path, sec):
        """Show the frame on screen at file time `sec` from the cache. False if it is not there (yet)."""
        f = media.frame_start(path, sec, wait=False)
        hit = self.cache.get(path, f) if f is not None else None
        if hit is None:
            if self._prefetching == path and not self.cache.covers(path, sec):
                self.cache.fill(path, sec)              # dragged past the decoded part: decode around here
            return False
        if self._cached != (path, f):                   # (a new picture only when the frame changes)
            buf, w, h = hit
            self._gen += 1                              # pictures still decoding are for an older position
            self._target = None
            self._cached = (path, f)
            self._show(GLib.Bytes.new(buf), w, h)
        if self._sharp_id:
            GLib.source_remove(self._sharp_id)
        self._sharp_id = GLib.timeout_add(150, self._sharpen)
        return True

    def _sharpen(self):
        self._sharp_id = 0
        if not self.playing:
            self.seek(self.t)                           # the same frame, full size
        return False

    # --- control ----------------------------------------------------------
    def set_project(self, project):
        self.project = project
        self.loose.project = project

    def _report(self, msg):
        """Tell the user once per distinct problem."""
        if msg in self._reported:
            return
        self._reported.add(msg)
        if self.on_error:
            GLib.idle_add(self.on_error, msg)
        else:
            print(msg)

    def _load(self, path):
        if self._loaded == path:
            return True
        if not os.path.exists(path):
            self._loaded = None
            self._report(f"A video file is missing: {os.path.basename(path)}")
            return False
        if not media.frames_ready(path):          # frame start times, read in the background
            threading.Thread(target=media.frame_times, args=(path,), daemon=True).start()
        self._target = None
        self.pb.set_state(Gst.State.NULL)
        self.pb.set_property("uri", Gst.filename_to_uri(path))
        self.pb.set_state(Gst.State.PAUSED)
        ok, _, _ = self.pb.get_state(5 * Gst.SECOND)
        self._loaded = path if ok != Gst.StateChangeReturn.FAILURE else None
        if self._loaded and self.playing:
            self.pb.set_state(Gst.State.PLAYING)
        return self._loaded is not None

    def _async_done(self, bus, msg):
        self._seeking = 0.0
        if self._pending is not None:              # the pointer moved on while that frame was decoding
            t, self._pending = self._pending, None
            self.seek(t, scrub=True)

    def _busy(self):
        return self._seeking and GLib.get_monotonic_time() / 1e6 - self._seeking < 1.0

    def _frame_pos(self, path, sec):
        """Where to seek so the picture is the frame on screen at `sec`. With a variable frame rate (screen
        recordings) a still screen holds one frame for a long time, and seeking into that gap would show the
        next frame instead; so seek just inside the start of the frame that is really on screen."""
        f = media.frame_start(path, sec, wait=False)
        return sec if f is None else f + 0.0002

    def _seek_src(self, sec):
        """Exact seek: always the right frame, never the nearest keyframe (which can be seconds away)."""
        self._seeking = GLib.get_monotonic_time() / 1e6
        self._eos = False
        self.pb.seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                     Gst.SeekType.SET, int(round(max(0, sec) * Gst.SECOND)), Gst.SeekType.NONE, 0)

    def _apply_volume(self, clip, off):
        g = clip.gain_at(off) if clip.linked else 0.0       # unlinked: its sound plays from self.loose
        self.pb.set_property("volume", max(0.0, min(10.0, g)))

    def seek(self, t, fast=False, scrub=False):
        """Jump to timeline time t (paused or playing) and show exactly the frame on screen there.
        scrub=True is for dragging: while a frame is still decoding only the newest target is kept, so the
        picture follows the pointer as fast as frames can be decoded and always ends on the last position."""
        scrub = scrub or fast
        p = self.project
        if not p.clips:
            self.t = 0.0
            self._pending = None
            if self.playing:
                self.pause()
            self.pb.set_state(Gst.State.NULL)
            self._loaded = None
            self._target = None
            self.on_frame(None, 0, 0)
            self.on_time(0.0)
            return
        t = max(0.0, min(t, max(0.0, p.duration - 0.001)))
        i, off = p.clip_at(t)
        c = p.clips[i]
        if scrub and self._loaded == c.path and self._from_cache(c.path, c.src_in + off):
            self._pending = None
            self._idx = i
            self.t = t
            self._apply_volume(c, off)
            self.on_time(t)
            return
        if scrub and self._busy() and self._loaded == c.path:
            self._pending = t                      # picked up when the frame in flight is done
            self.t = t
            self.on_time(t)
            return
        self._pending = None
        self._idx = i
        if self._sharp_id and not scrub:
            GLib.source_remove(self._sharp_id)
            self._sharp_id = 0
        if self._load(c.path):
            pos = self._frame_pos(c.path, c.src_in + off)
            if self.playing or self._target != (c.path, pos):
                self._seek_src(pos)
                self._target = (c.path, pos)
            self._apply_volume(c, off)
        self.t = t
        self.on_time(t)

    def refresh(self):
        """Call after the project changed under the playhead."""
        self._loaded = None if not self.project.clips else self._loaded
        self.seek(min(self.t, self.project.duration))

    def play(self):
        p = self.project
        if not p.clips:
            return
        if self.t >= p.duration - 0.05:
            self.seek(0.0)
        self.pb.set_state(Gst.State.PLAYING)
        self.playing = True
        self._target = None
        self.on_state(True)
        if not self._tick_id:
            self._tick_id = GLib.timeout_add(30, self._tick)

    def pause(self):
        self.pb.set_state(Gst.State.PAUSED)
        self.loose.stop()
        self.playing = False
        self._target = None                        # the picture moved while playing
        self.on_state(False)
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0

    def toggle(self):
        self.pause() if self.playing else self.play()

    def _tick(self):
        p = self.project
        if not self.playing or not p.clips or self._idx >= len(p.clips):
            self._tick_id = 0
            return False
        c = p.clips[self._idx]
        if self._seeking and GLib.get_monotonic_time() / 1e6 - self._seeking < 1.0:
            return True                      # seek still in flight: positions are stale
        ok, pos = self.pb.query_position(Gst.Format.TIME)
        if not ok:
            return True
        sec = c.src_out if self._eos else pos / Gst.SECOND
        if sec >= c.src_out - 0.02:
            if self._idx + 1 >= len(p.clips):
                self.pause()
                self.t = p.duration
                self.on_time(self.t)
                self._tick_id = 0
                return False
            n = p.clips[self._idx + 1]
            self._idx += 1
            if not (n.path == c.path and abs(n.src_in - c.src_out) < 0.05):   # not contiguous: jump
                if self._load(n.path):
                    self._seek_src(self._frame_pos(n.path, n.src_in))
            c, sec = n, max(sec, n.src_in)
        off = max(0.0, sec - c.src_in)
        self.t = p.clip_start(self._idx) + off
        self._apply_volume(c, off)
        self.loose.follow(self.t)
        self.on_time(self.t)
        return True

    def close(self):
        self.end_prefetch()
        self.pause()
        self.pb.set_state(Gst.State.NULL)
        self.loose.close()


class LooseSounds:
    """Plays the project's unlinked sounds next to the picture: one audio-only playbin per sound that is
    playing, kept in step with the timeline time the picture reports (re-seeked if it drifts)."""
    DRIFT = 0.08          # seconds out of step before a sound is re-seeked

    def __init__(self, project):
        self.project = project
        self.pbs = {}     # id(Sound) -> playbin
        self.sink_factory = None   # tests: a function returning an audio sink element

    def _playbin(self, snd):
        pb = self.pbs.get(id(snd))
        if pb is not None and pb.path == snd.path:
            return pb
        if pb is not None:
            pb.set_state(Gst.State.NULL)
        if not os.path.exists(snd.path):
            return None
        pb = Gst.ElementFactory.make("playbin", None)
        pb.set_property("flags", 0x2 | 0x10)                      # audio + soft volume, no video decoding
        pb.set_property("video-sink", Gst.ElementFactory.make("fakesink", None))
        if self.sink_factory:
            pb.set_property("audio-sink", self.sink_factory())
        elif os.environ.get("SPLICE_NOAUDIO"):
            fake = Gst.ElementFactory.make("fakesink", None)
            fake.set_property("sync", True)
            pb.set_property("audio-sink", fake)
        pb.set_property("uri", Gst.filename_to_uri(snd.path))
        pb.path, pb.live = snd.path, False
        self.pbs[id(snd)] = pb
        return pb

    def follow(self, t):
        """Called while playing, with the timeline time on screen."""
        end = self.project.duration
        want = set()
        for snd in self.project.sounds:
            if not (snd.start - 0.01 <= t < min(snd.end, end)):
                continue
            pb = self._playbin(snd)
            if pb is None:
                continue
            want.add(id(snd))
            pos = snd.src_in + (t - snd.start)
            if not pb.live:
                pb.set_state(Gst.State.PAUSED)
                pb.get_state(2 * Gst.SECOND)
                self._seek(pb, pos)
                pb.set_state(Gst.State.PLAYING)
                pb.live = True
            else:
                ok, cur = pb.query_position(Gst.Format.TIME)
                if ok and abs(cur / Gst.SECOND - pos) > self.DRIFT:
                    self._seek(pb, pos)
            pb.set_property("volume", max(0.0, min(10.0, snd.gain_at(t - snd.start))))
        for key, pb in list(self.pbs.items()):
            if key not in want and pb.live:
                pb.set_state(Gst.State.PAUSED)
                pb.live = False
        alive = {id(s) for s in self.project.sounds}
        for key in [k for k in self.pbs if k not in alive]:       # deleted sounds
            self.pbs.pop(key).set_state(Gst.State.NULL)

    @staticmethod
    def _seek(pb, sec):
        pb.seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                Gst.SeekType.SET, int(round(max(0.0, sec) * Gst.SECOND)), Gst.SeekType.NONE, 0)

    def stop(self):
        for pb in self.pbs.values():
            if pb.live:
                pb.set_state(Gst.State.PAUSED)
                pb.live = False

    def close(self):
        for pb in self.pbs.values():
            pb.set_state(Gst.State.NULL)
        self.pbs.clear()
