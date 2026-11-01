# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Captions: glyph coverage (emoji, CJK, Arabic), colour emoji, fit-to-width, timing, many captions, edge cases."""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cairo
from splice import textfit
from splice.export import export, map_time, output_size
from splice.model import Project, Text

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_qa")
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (" " + info if info else ""))
    if not ok: fails.append(name)
work = tempfile.mkdtemp(prefix="qa-text-")

def colorful(png):
    s = cairo.ImageSurface.create_from_png(png); w, h = s.get_width(), s.get_height(); d = bytes(s.get_data()); n = 0
    for i in range(0, w * h * 4, 4):
        b, g, r, a = d[i], d[i + 1], d[i + 2], d[i + 3]
        if a > 200 and max(r, g, b) - min(r, g, b) > 70: n += 1
    return n

for label, txt in (("emoji", "Party 🎉 🚀 ❤️ 👍🏽"), ("Japanese", "日本語のテキスト"), ("Chinese", "你好，世界"), ("Korean", "안녕하세요"),
                   ("Arabic", "مرحبا بالعالم"), ("Hebrew", "שלום עולם"), ("Cyrillic/Greek", "Привет Γειά σου"), ("accents", "Ünïcödé àéîõü ñ ç"), ("symbols", "✓ ★ → ♥ © ™ € ½")):
    check(f"every character in {label} can be drawn", textfit.missing_glyphs(txt) == 0, f"({textfit.missing_glyphs(txt)} missing)")
textfit.render_png(f"{work}/e.png", "🎉🚀❤️", 60, "#ffffff"); textfit.render_png(f"{work}/p.png", "Hello world", 60, "#ffffff")
check("emoji are colour glyphs, not white boxes", colorful(f"{work}/e.png") > 2000 and colorful(f"{work}/e.png") > 4 * colorful(f"{work}/p.png"), f"colourful pixels: emoji={colorful(f'{work}/e.png')} plain={colorful(f'{work}/p.png')}")

# fit to width, including portrait
W = 720
long = "A very long caption that would never fit on one line of a narrow portrait video"
px = textfit.fit_px(long, 60, W); bw, bh = textfit.box_size(long, px)
check("long caption shrinks to fit a portrait frame", bw <= W * 0.93 and px < 60, f"box {bw:.0f}px of {W}px at {px:.0f}px font")
check("short caption keeps its size", textfit.fit_px("Hi", 60, 1280) == 60)
x, y = textfit.box_position("bottom", 1280, 720, 400, 80); check("bottom box sits above the bottom edge", 720 - (y + 80) > 30 and abs(x - 440) < 1)
x, y = textfit.box_position("top", 1280, 720, 400, 80); check("top box sits below the top edge", 30 < y < 60)
x, y = textfit.box_position("middle", 1280, 720, 400, 80); check("middle box is vertically centred", abs(y - 320) < 1)

# export: emoji exported and visible, portrait caption inside the frame
p = Project(); c = p.add_clip(f"{D}/portrait.mp4"); c.src_out = 2
p.texts = [Text("Party 🎉 日本語 مرحبا — and a very long portrait caption", 0.2, 1.8, "bottom", 0.07)]
out = f"{work}/o.mp4"; export(p, out)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", "1.0", "-i", out, "-frames:v", "1", f"{work}/f.png"])
subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", f"{work}/f.png", "-vf", "crop=720:150:0:1050", f"{work}/band.png"])
check("export: colour emoji appear in the saved video", colorful(f"{work}/band.png") > 300, f"{colorful(f'{work}/band.png')} colourful px")
Wo, Ho = output_size(p)
bw, bh = textfit.box_size(p.texts[0].text, textfit.fit_px(p.texts[0].text, Ho * 0.07, Wo))
check("export: portrait caption stays inside the frame", bw <= Wo, f"box {bw:.0f} of {Wo}")

# timing after frame rounding (white text pixels only while the caption is up)
T = f"{D}/tones.mp4"; p = Project()
for i in range(10):
    c = p.add_clip(T); c.src_in = (i * 0.37) % 3.5; c.src_out = c.src_in + 0.35
p.texts = [Text("MARK", 1.4, 2.1, "middle", 0.3, "#ffffff")]
out = f"{work}/m.mp4"; export(p, out)
def white(t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.3f}", "-i", out, "-frames:v", "1", "-vf", "crop=160:60:80:60", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return sum(1 for i in range(0, len(raw) - 2, 3) if raw[i] > 215 and raw[i + 1] > 215 and raw[i + 2] > 215)
s, e = map_time(p, 1.4), map_time(p, 2.1)
during, before, after = [white(t) for t in (s + .04, (s + e) / 2, e - .04)], white(s - .07), white(e + .07)
check("caption shows exactly during its window", all(d > 150 for d in during) and before < 20 and after < 20, f"before={before} during={during} after={after}")

# many captions, overlapping, and empty/whitespace ones
p = Project(); c = p.add_clip(f"{D}/base.mp4")
p.texts = [Text(f"Caption {i} 🎉", i * 0.08, i * 0.08 + 1.5, ["top", "middle", "bottom"][i % 3], 0.04) for i in range(40)] + [Text("", 0, 1), Text("   ", 0, 1)]
t0 = time.time(); out = f"{work}/many.mp4"; export(p, out)
dec = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", out, "-f", "null", "-"], capture_output=True, text=True).stderr.strip()
check("40 overlapping captions plus empty ones export and decode", not dec, f"in {time.time()-t0:.1f}s")
# special characters
p = Project(); c = p.add_clip(f"{D}/base.mp4"); c.src_out = 1
p.texts = [Text("50% off: it's \"here\" \\ back'slash #tag {braces} [x] $HOME `tick` & <b>", 0, 1)]
export(p, f"{work}/sp.mp4"); check("special characters (% ' : \\ \" $ ` & <>) are harmless", os.path.exists(f"{work}/sp.mp4"))
print("PROBLEMS:", len(fails), fails)
sys.exit(1 if fails else 0)
