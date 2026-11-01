# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview player: one GStreamer playbin that follows the project's clips in order.

Frames arrive through an appsink, are scaled small, and handed to the UI as Gdk textures.
Crop and text are drawn by the UI on top, so the pipeline stays simple.
"""
import os
import gi
gi.require_version("Gst", "1.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gst, GLib, Gdk

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
        self.pb.get_bus().connect("message::async-done", lambda b, m: setattr(self, "_seeking", 0.0))
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
            GLib.idle_add(self._show, data, w, h)
        return Gst.FlowReturn.OK

    def _show(self, data, w, h):
        stride = data.get_size() // h
        self.on_frame(Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8, data, stride), w, h)
        return False

    # --- control ----------------------------------------------------------
    def set_project(self, project):
        self.project = project

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
        self.pb.set_state(Gst.State.NULL)
        self.pb.set_property("uri", Gst.filename_to_uri(path))
        self.pb.set_state(Gst.State.PAUSED)
        ok, _, _ = self.pb.get_state(5 * Gst.SECOND)
        self._loaded = path if ok != Gst.StateChangeReturn.FAILURE else None
        if self._loaded and self.playing:
            self.pb.set_state(Gst.State.PLAYING)
        return self._loaded is not None

    def _seek_src(self, sec, fast=False):
        self._seeking = GLib.get_monotonic_time() / 1e6
        self._eos = False
        # fast: jump to the keyframe before `sec` (quick feedback while dragging); otherwise land on the exact frame
        flags = Gst.SeekFlags.FLUSH | (Gst.SeekFlags.KEY_UNIT if fast else Gst.SeekFlags.ACCURATE)
        self.pb.seek(1.0, Gst.Format.TIME, flags, Gst.SeekType.SET, int(max(0, sec) * Gst.SECOND), Gst.SeekType.NONE, 0)

    def _apply_volume(self, clip, off):
        self.pb.set_property("volume", max(0.0, min(10.0, clip.gain_at(off))))

    def seek(self, t, fast=False):
        """Jump to timeline time t (paused or playing). fast=True is for scrubbing: nearest keyframe, no wait."""
        p = self.project
        if not p.clips:
            self.t = 0.0
            if self.playing:
                self.pause()
            self.pb.set_state(Gst.State.NULL)
            self._loaded = None
            self.on_frame(None, 0, 0)
            self.on_time(0.0)
            return
        t = max(0.0, min(t, max(0.0, p.duration - 0.001)))
        i, off = p.clips.index(p.clips[p.clip_at(t)[0]]), p.clip_at(t)[1]
        c = p.clips[i]
        self._idx = i
        if self._load(c.path):
            self._seek_src(c.src_in + off, fast)
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
        self.on_state(True)
        if not self._tick_id:
            self._tick_id = GLib.timeout_add(30, self._tick)

    def pause(self):
        self.pb.set_state(Gst.State.PAUSED)
        self.playing = False
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
                    self._seek_src(n.src_in)
            c, sec = n, max(sec, n.src_in)
        off = max(0.0, sec - c.src_in)
        self.t = p.clip_start(self._idx) + off
        self._apply_volume(c, off)
        self.on_time(self.t)
        return True

    def close(self):
        self.pause()
        self.pb.set_state(Gst.State.NULL)
