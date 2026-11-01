# Splice: development notes

Read this before changing anything. The README is the public-facing doc.

## Files

| Path | What it is |
|---|---|
| `splice/app.py` | Main window: stage (preview + crop box), tools, editor row, files, export dialog, undo, keys |
| `splice/lanes.py` | The three-lane timeline (Cairo drawing, mouse editing) and the playhead overlay |
| `splice/model.py` | `Project`, `Clip`, `Text`: all edits that keep captions attached to clips live here |
| `splice/export.py` | One ffmpeg command from a project; GPU/CPU choice; safe output; cancel |
| `splice/player.py` | Preview: one GStreamer `playbin` that follows the clips in order |
| `splice/textfit.py` | Captions: one Pango renderer for preview and export, fit-to-width |
| `splice/cropdrag.py` | Crop box geometry (pure, no GUI) |
| `splice/media.py`, `peaks.py` | ffprobe wrapper (rotation, fps, header-less files); waveform peaks via ffmpeg |
| `data/` | Desktop entry template, icon, `.splice` mime type |
| `install.sh` | App menu, icon, file type, dock pin; `--no-dock`, `--uninstall` |
| `tests/` | See Testing |

## How it works

**Project.** Times are seconds. A clip is `path, src_in, src_out, volume, env, fade_in, fade_out, crop`. `crop` is `[x, y, w, h]` as fractions of the picture. `env` is the volume line: absolute gain points in clip time; empty means flat `volume`. Captions (`Text`) live on the timeline, but every edit that moves a clip (`reorder`, `trim`, `delete_clip`, `add_clip`) remaps them through an *anchor*: the clip a caption starts in plus its offset. A left trim slides a caption earlier with the picture; a caption whose picture is trimmed away is removed (undo brings it back). Equal-looking clips are told apart by identity, not equality.

**Preview.** `playbin` with `videoflip ! videoscale ! videoconvert ! appsink`; frames become `Gdk.MemoryTexture`s drawn by `VideoView`. Crop, letterboxing and captions are drawn by the app, using the same geometry as the export (`exporter.output_size`, `crop_rect`, `textfit`). Scrubbing uses fast keyframe seeks and one exact seek 200 ms after the last move. Playback across clips switches the loaded file only when needed; contiguous clips of one file (after a split) play gaplessly. Gain (volume line times fades) is applied to the `volume` property each tick.

**Export.** One `ffmpeg` with one input per clip using input seeking (`-ss/-t` before `-i`), per-clip `setpts, fps, crop, scale, pad, format, trim`, audio `volume=<expression>:eval=frame, afade, apad/atrim`, then `concat`, then one `overlay` per caption PNG. Each clip is exported as whole frames; caption times are mapped through `map_time` so they stay on the right picture. Output goes to `name.splice-part` and is renamed on success. ffmpeg is killed on cancel and at interpreter exit.

**GPU export.** `gpu_device()` picks the render node with the most video memory and test-encodes a tiny clip once. The encode is `h264_vaapi` (CQP QP 27, no B-frames, High profile); decode and filters stay on the CPU. Any failure (no GPU, unsupported size, error part-way) retries on x264 (veryfast, CRF 20) and the UI says which was used. `SPLICE_ENCODER=cpu` forces the CPU; `SPLICE_VAAPI_DEVICE=/dev/dri/renderD129` forces a card.

Measured (Radeon AI PRO R9700 + Ryzen 9800X3D), same project both ways:

| 1080p source | GPU | CPU (x264 veryfast) |
|---|---|---|
| 40 s clip: time / CPU time / size / PSNR | 1.7 s / 3.3 s / 38.7 MB / 46.9 dB | 2.1 s / 19.3 s / 37.1 MB / 45.4 dB |
| 20 s detailed fractal | 0.9 s / 2.6 s / 45.9 MB / 42.7 dB | 1.7 s / 17.5 s / 36.9 MB / 41.0 dB |

How the settings were found: the card's video engine does about 270 fps at 1080p with the default B-frames and about 400 fps without them; x264 on 16 threads does about 600 fps. With default settings the GPU was *slower* (3.0 s vs 2.1 s); B-frames off made it faster. GPU decode was slower still (frames are copied back for the CPU filters). The reliable win is about 6x less CPU time per export. Re-measure on other hardware with `tests/qa_gpu.py`.

**Captions.** `textfit.py` renders the box and text with Pango, so emoji (colour), CJK, Arabic/Hebrew and accents work, and the preview and export match exactly. The export overlays each caption as a PNG; ffmpeg `drawtext` has no font fallback and drops text containing `%` unless `expansion=none`. A caption is one line and shrinks to fit the frame width. Pango's font map is shared, so all calls take `textfit._lock`.

**Timeline.** `Lanes` is window-sized and scrolls by an offset (`hadj`): a content-wide drawing widget aborts GTK past about 32,000 px (a few minutes of video when zoomed in). The playhead is its own overlay so the lanes only redraw on edits. Everything outside the visible range is skipped. Alt+scroll (or Ctrl+scroll) zooms around the pointer; plain scroll pans.

## Testing

Everything runs headless: GTK tests run under Xvfb with `GDK_BACKEND=x11` and never open a window on your desktop. Generate the test media first (about a minute, nothing is committed):

```bash
tests/make_media.sh
tests/run_all.sh quick     # about 3 minutes
tests/run_all.sh full      # adds more fuzz seeds and a one-hour timeline
tests/run_ci.sh            # the subset that needs no GPU, no display and no big files (what CI runs)
```

Needs `xvfb xdotool ffmpeg python3-pyflakes` besides the runtime packages. `qa_gpu.py` needs a working VAAPI GPU. `long10min.mp4` (optional) is for the performance tests.

| Test | What it covers |
|---|---|
| `qa_gpu.py`, `qa_export_ui.py` | GPU device choice, forced CPU, bad device, GPU failing part-way, quality/size/speed/CPU load vs x264, containers, cancel; the dialog and message naming the encoder |
| `test_export.py`, `qa_engine.py` | export of awkward files: rotated phone clip, portrait, odd sizes, variable frame rate, 60 and 29.97 fps, mono/5.1/8 kHz audio, 10-bit, 4K, no-duration MKV, hostile filenames, non-videos |
| `qa_content.py` | numeric: cuts and joins land on the right colour and tone per second, A/V sync across joins, volume, volume line, fades, crop |
| `qa_export_safety.py` | cancel, bad paths, refusing to overwrite a source (also via symlink), old file survives failure, no temp leftovers |
| `qa_audio_preview.py` | preview audio gain tracking, measured with a level meter on the sink |
| `test_model_anchor.py` | captions follow clips through reorder, trim, delete, insert (plus 3,200 random ops) |
| `test_cropdrag.py`, `qa_crop.py` | crop geometry (60,000 random drags) and real mouse dragging of the box, lock, clamping, undo, export size |
| `qa_text.py` | every script draws (emoji, CJK, Arabic, Hebrew, Korean, accents, symbols), colour emoji, fit-to-width, timing, many captions, special characters |
| `test_player.py`, `qa_player.py`, `qa_seek.py` | playback across clips, real-time pace, rotation, scrubbing latency |
| `xdrag.py`, `qa_keys.py`, `qa_zoom.py`, `qa_drop.py`, `qa_projects.py` | real mouse, key and wheel events under Xvfb, drag and drop, project files, missing media, unsaved-changes prompt |
| `qa_fuzz.py <seed> <ops>` | random edits through the real window with invariants after every step, then an export and decode check |
| `qa_wysiwyg.py`, `qa_shots.py` | preview vs exported frame, screenshots (portrait, rotated, mixed, light, HiDPI) |
| `qa_resources.py`, `qa_profile.py`, `qa_player_cpu.py`, `qa_longtimeline.py` | CPU, memory, leak check, one-hour timeline at every zoom |
| `qa_quit_during_export.py` | quitting mid-export leaves no ffmpeg and no partial file |

`tests/make_screenshots.py` regenerates `docs/screenshots/*.png` under Xvfb.

Xvfb has no window manager, so the window sits slightly offset from where the test expects; the mouse tests calibrate that offset from a real pointer motion first (see `xdrag.py`).

## Design rules learned the hard way

- Keep the timeline window-sized and scroll by offset (see above).
- Cut with input seeking (`-ss/-t` before `-i`), not the `trim` filter. `trim` decodes every source from the start: 12 pieces of a 10-minute file took 10 s and 1.3 GB. Beyond 4 clips use 1 decoder thread per input (3.2 GB became 0.8 GB for 40 pieces).
- Never write over the target until the export succeeds. Refuse a target that is one of the clips (also through a symlink).
- The editor row has a fixed height. If it changes height with the selection, the timeline jumps under the pointer mid-drag.
- Preview and export share the output shape, crop rectangle and caption fitting; change them in one place.
- Do not redraw big widgets per video frame: the playhead is an overlay, and text/crop only redraw when their content changes.
- GStreamer positions are stale until `async-done` after a seek. A silent test audio sink must have `sync=true` or playback races.
- Do not run `gsettings` under a throwaway `HOME`: dconf may write to the real settings.
- `-bf 0` for the GPU encoder; B-frames cost about 40% of its speed.

## Deliberately not done

- Transitions, effects, keyframes, more than one video track.
- Hardware decode and GPU-side filters (`scale_vaapi`, `overlay_vaapi`): decode on the GPU was slower here, and the filter work is small next to the encode.
- Multi-line captions.

## Known gaps

- One fixed quality (GPU QP 27, or x264 CRF 20 on the CPU fallback).
- A caption that starts in one clip and runs into the next travels with the clip it starts in.
- No auto-scroll while dragging a clip toward the edge of the visible timeline; zoom out instead.
- Preview audio may have a tiny gap when a clip change needs a file switch.
- Developed and tested on Ubuntu 24.04 (GNOME 46, X11 and software rendering under Xvfb; the live session was never driven by the tests). Not tried on Intel or NVIDIA GPUs.
