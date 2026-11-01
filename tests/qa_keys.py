# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real key and mouse events (xdotool/XTest) under Xvfb: shortcuts, focus traps, typing in fields."""
import os, subprocess, sys, threading, time
os.environ["SPLICE_NOAUDIO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk, Graphene
from splice import app as A, lanes as L

M = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
fails = []
def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name, info)
    if not ok: fails.append(name)
def call(fn):
    ev, res = threading.Event(), []
    def run():
        try: res.append(fn())
        except Exception as e: res.append(e)
        ev.set(); return False
    GLib.idle_add(run); ev.wait(10)
    if res and isinstance(res[0], Exception): raise res[0]
    return res[0] if res else None
def xd(*a): subprocess.run(["xdotool", *map(str, a)], check=True)
def key(*k): xd("key", *k); time.sleep(0.25)
def click_at(x, y): xd("mousemove", x, y); time.sleep(.15); xd("click", 1); time.sleep(.35)

def driver(app):
    w = app.win; P = w.project
    time.sleep(1.5)
    wid = subprocess.run(["xdotool", "search", "--name", "Splice"], capture_output=True, text=True).stdout.split()
    xd("windowfocus", wid[-1]) if wid else None
    time.sleep(.4)
    xd("mousemove", 400, 600); time.sleep(.4); xd("mousemove", 410, 610); time.sleep(.4)
    ox, oy = call(lambda: (lambda p: (p.x, p.y))(w.lanes.compute_point(w, Graphene.Point().init(0, 0))[1]))
    sx = 410 - (call(lambda: w.lanes._mouse_x) + ox); sy = 610 - (call(lambda: w.lanes._mouse_y) + oy)
    def center(widget):
        ok, pt = widget.compute_point(w, Graphene.Point().init(widget.get_width() / 2, widget.get_height() / 2))
        return int(pt.x + sx), int(pt.y + sy)
    # 1. space toggles play
    key("space"); check("space starts playback", call(lambda: w.player.playing))
    key("space"); check("space pauses", not call(lambda: w.player.playing))
    # 2. 's' splits at playhead
    call(lambda: w.seek(2.0)); n = len(P.clips); key("s")
    check("S splits clip", len(P.clips) == n + 1, f"clips {n}->{len(P.clips)}")
    # 3. focus trap: click Split button with mouse, then Space must play, not split again
    n = len(P.clips); call(lambda: w.seek(8.0))
    tools = []
    def find(widget, acc):
        c = widget.get_first_child()
        while c:
            if isinstance(c, Gtk.Button) and c.get_tooltip_text() and "Split" in c.get_tooltip_text(): acc.append(c)
            find(c, acc); c = c.get_next_sibling()
    call(lambda: find(w, tools))
    x, y = call(lambda: center(tools[0]))
    click_at(x, y)
    check("clicking Split button splits", len(P.clips) == n + 1, f"{n}->{len(P.clips)}")
    n = len(P.clips); call(lambda: w.seek(2.5)); key("space")
    check("space after clicking a tool button plays (no repeat split)", len(P.clips) == n and call(lambda: w.player.playing), f"clips {len(P.clips)} playing {w.player.playing}")
    key("space")
    # 4. arrows step the playhead
    call(lambda: w.seek(5.0)); key("Right"); t1 = call(lambda: w.t); key("Left"); t2 = call(lambda: w.t)
    check("Right/Left step playhead by 0.5s", abs(t1 - 5.5) < 0.05 and abs(t2 - 5.0) < 0.05, f"{t1:.2f} {t2:.2f}")
    # 5. Delete removes selected clip; ctrl+z restores it
    call(lambda: w.select(("v", 0))); n = len(P.clips); key("Delete")
    check("Delete removes selected clip", len(P.clips) == n - 1)
    key("ctrl+z"); check("Ctrl+Z restores it", len(P.clips) == n)
    key("ctrl+shift+z"); check("Ctrl+Shift+Z redoes the delete", len(P.clips) == n - 1)
    key("ctrl+z")
    # 6. typing in the text entry must not trigger shortcuts
    call(lambda: w.tool_text()); time.sleep(.3)
    entry = []
    def findentry(widget):
        c = widget.get_first_child()
        while c:
            if isinstance(c, Gtk.Entry): entry.append(c)
            findentry(c); c = c.get_next_sibling()
    call(lambda: findentry(w.pop))
    x, y = call(lambda: center(entry[0])); click_at(x, y)
    nclips, ntexts, playing = len(P.clips), len(P.texts), call(lambda: w.player.playing)
    key("ctrl+a"); xd("type", "--delay", "60", "s ss Delete me"); time.sleep(.4)
    check("typing 's' and spaces in the text box does not split/play", len(P.clips) == nclips and not call(lambda: w.player.playing) and not playing)
    check("text box received the typing", P.texts[-1].text == "s ss Delete me", repr(P.texts[-1].text))
    key("BackSpace"); key("BackSpace")
    check("Backspace in the text box edits text, not clips/texts", len(P.clips) == nclips and len(P.texts) == ntexts and P.texts[-1].text == "s ss Delete ", repr(P.texts[-1].text))
    key("ctrl+z")
    check("Ctrl+Z in the text box is the box's own undo (project untouched)", len(P.texts) == ntexts)
    call(lambda: setattr(w, "_force_close", True)); call(w.close)

class T(A.SpliceApp):
    def do_activate(self):
        super().do_activate(); w = self.win
        threading.Thread(target=driver, args=(self,), daemon=True).start()
T([f"{M}/c1.mp4", f"{M}/c2.mp4"]).run([sys.argv[0]])
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
