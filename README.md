<p align="center"><img src="data/io.github.gaservantes.Splice.svg" width="96" alt="Splice icon"></p>

<h1 align="center">Splice</h1>
<p align="center"><b>Trim, join, caption, balance the sound, crop. Nothing else.</b><br>
A small video editor for the GNOME desktop on Ubuntu.</p>
<p align="center">
<a href="https://github.com/GAServantes/splice/actions/workflows/ci.yml"><img src="https://github.com/GAServantes/splice/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
<a href="https://github.com/GAServantes/splice/releases/latest"><img src="https://img.shields.io/github/v/release/GAServantes/splice" alt="Latest release"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue" alt="License: GPL-3.0-or-later"></a>
</p>

![The Splice window: preview on top, and the Video, Text and Sound lanes below](docs/screenshots/window.png)

Splice is for the quick jobs: cut the dead air out of a screen recording, put
a few clips in order, add a caption, turn one section down, crop to a shape,
save. It is a small program (under 3,500 lines of Python, no timeline engine
to learn), and it uses your GPU to save the result.

The timeline has three lanes. **Video** holds your clips, **Text** holds
captions, **Sound** shows each clip's waveform with a volume line you can
bend. Everything is edited by dragging on the lane itself.

## What it does

- **Trim.** Drag the edges of a clip, or type exact times. Split at the
  playhead with `S`.
- **Join.** Drag clips into any order. Captions travel with the clip they
  start in, and later clips and captions move up when you trim or delete.
- **Add text.** Click *Add text*, then drag the block to time it. Captions can
  sit at the top, middle or bottom, with any size and color. Emoji, Japanese,
  Chinese, Korean, Arabic and accented text all draw correctly, and long
  captions shrink to fit.
- **Change sound.** Overall volume, fade in and out, and a volume line you
  drag in the Sound lane (click the line to add a point, right-click a point
  to remove it). Clips without sound just work.
- **Unlink sound.** Separate a clip's sound from its picture (*Unlink*, or `U`).
  The sound becomes its own block in the Sound lane: drag it anywhere (it clicks
  onto clip edges), trim its ends, split it, change its volume, or delete it,
  while the picture stays put. Cut the picture and keep the talking going, or
  drop a clip's picture and keep its sound. *Link again* puts the sound back
  under its picture, in sync.
- **Crop.** Drag the box right on the picture, by the middle or any of the
  eight handles. Pick a shape (16:9, 4:3, 1:1, 9:16) to keep that shape while
  you drag, or type numbers.
- **Preview that matches the result.** The preview shows the saved shape,
  crop and captions, in color and in sync with the sound.
- **Save on your GPU.** Export uses the VAAPI H.264 encoder (tested on a
  Radeon; other VAAPI graphics should work) and falls back to the CPU on its own if the card can't take the
  video, so a save never fails because of the GPU. The "Saved" message says
  which one did the work.
- **Undo and redo** for every edit, **save your project** to a `.splice` file,
  and **drop videos** onto the window.
- **Safe saving.** Saving writes to a temporary file first, so a canceled or
  failed export never damages an existing video. Splice refuses to save over
  one of your own clips. The Save window starts in your first clip's folder, so
  the edited copy lands next to the original.
- **Works with SnapCap.** If you use [SnapCap](https://github.com/GAServantes/snapcap)
  (1.4 or newer), a video's preview there has an **Edit** button that opens it
  in Splice.

<p align="center"><img src="docs/screenshots/crop.png" width="760" alt="Cropping: a dashed box with eight handles on the picture, with the crop row below"></p>

Phone videos (rotated), portrait video, odd frame sizes, variable frame rate,
60 and 29.97 fps, 10-bit, 4K, mono and surround sound all work, and colors
come out as they went in.

## Install

Requirements: Ubuntu 24.04 on GNOME (what it is developed and tested on; it
needs GTK 4.10 and libadwaita 1.5, which 24.04 has), with these packages:

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav ffmpeg \
  fonts-dejavu-core fonts-noto-color-emoji fonts-noto-cjk
```

(`gstreamer1.0-plugins-bad` keeps the preview on the exact frame in screen recordings.
`fonts-noto-cjk` is only needed for Chinese, Japanese and Korean captions. GPU export also needs your
graphics driver's VAAPI support, which is `mesa-va-drivers` for Radeon, installed by default on Ubuntu.)

```bash
git clone https://github.com/GAServantes/splice.git ~/splice
~/splice/install.sh             # app menu ("Show Apps"), icon, .splice file type, dock shortcut
~/splice/install.sh --no-dock   # same, without pinning it to the dock
~/splice/install.sh --uninstall # undo (your videos and projects are untouched)
```

The app runs from the cloned folder, so keep it there. To try it without
installing: `~/splice/bin/splice`.

## Using it

| | |
|---|---|
| Drag a clip's edges | Trim, to the exact frame the picture shows |
| Drag a clip's body | Reorder (captions go with it) |
| Drag a text block, or its edges | Time a caption |
| Drag the line in the Sound lane | Shape the volume |
| `U` | Unlink the sound of the clip under the playhead (again: link it back) |
| Drag an unlinked sound, or its edges | Move it in time, or trim it |
| `Space` | Play or pause |
| `S` | Split at the playhead (the selected unlinked sound, if one is selected) |
| `Delete` | Delete the selected clip, caption or unlinked sound, or reset a clip's sound |
| `Left` / `Right` | Step the playhead 0.5 s (`Shift`: 5 s) |
| `Alt` + scroll (or `Ctrl` + scroll) | Zoom the timeline around the pointer |
| Scroll | Pan the timeline |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+S` | Save the project |

## What it doesn't do

One video track, one Sound lane, one caption line per caption, no transitions,
effects or keyframes. Unlinked sound past the end of the video is left out of
the saved video (the timeline shades that part).

On Ubuntu 26.04 (GStreamer 1.26) the preview of a screen recording can show the
next frame at a few spots right before a frame change. The saved video is exact. If you need those, use Kdenlive or Shotcut. Splice is the small tool for the
five jobs above.

## Command line

```
~/splice/bin/splice [VIDEO ...] [PROJECT.splice]    open these (a project, or videos added in order)
```

`SPLICE_ENCODER=cpu` turns the GPU off. `SPLICE_VAAPI_DEVICE=/dev/dri/renderD129`
chooses a specific graphics card.

## How it works, briefly

Python with GTK 4 and libadwaita. The preview is a GStreamer pipeline drawn by
the app; saving is one `ffmpeg` command built from your project; captions are
drawn with Pango so the preview and the saved video match. The timeline is drawn
with Cairo.

## Tests

```bash
sh tests/install_ci_deps.sh   # Ubuntu packages the tests need (ffmpeg, Xvfb, ...)
tests/run_ci.sh               # lint, then the headless tests; about 2 minutes
```

The tests make small videos with ffmpeg (not committed) and cover export
correctness (cuts, joins, sync, volume, crop, unlinked sound, 19 awkward media files), captions
in every script, the preview player, random-edit fuzzing through the real
window, and saving and opening projects. It runs on the CPU under Xvfb, so
nothing opens a window on your desktop. GitHub Actions runs the same script on
Ubuntu 24.04 and 26.04.

## Changelog

- **0.5.0**: Unlink sound from video. A clip's sound can become its own block in the Sound lane, to move, trim, split, turn down or delete without touching the picture, and link back in sync later. The preview and the saved video both play it where you put it. Projects keep it; older projects open as before. Install now lists `gstreamer1.0-plugins-bad`, which the exact-frame preview of 0.4.0 needs (Splice says so if it is missing).
- **0.4.0**: Frame-exact trimming. While you drag a clip's edge, the picture shows exactly the frame the cut keeps, right away, and it stays put when you let go. Trims and splits land on whole frames. The saved video starts and ends on those same frames, also for screen recordings whose frame rate varies (the picture no longer runs early against the sound after a cut in a still part).
- **0.3.2**: The Save window starts in the first clip's folder (was always `~/Videos`). Opens from SnapCap's preview. American English throughout.
- **0.3.1**: Export uses the GPU (VAAPI H.264) by default with automatic CPU fallback. `Alt`+scroll zooms the timeline around the pointer (`Ctrl`+scroll still works).
- **0.3.0**: Drag-to-crop on the picture. Captions follow their clip when you reorder, trim or delete. Emoji, CJK and right-to-left captions, drawn identically in the preview and the saved video. App icon, installer, `.splice` file type, dock shortcut.
- **0.2.0**: Quality pass: fixed a crash on long or zoomed timelines, a memory and time blow-up when cutting many pieces from a long recording, rotated phone clips, frame-rate handling, files with no duration, the volume line at splits and trims, and more. Added cancel, safe saving, an unsaved-changes prompt, fast scrubbing and missing-file messages.
- **0.1.0**: First build.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE). Copyright (C) 2026 G. Austin Servantes.
