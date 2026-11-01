#!/bin/bash
# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
# Full headless QA. Never opens a window on the live desktop (GTK tests run under Xvfb).
# Usage: tests/run_all.sh [quick|full]
cd "$(dirname "$0")/.." || exit 1
MODE=${1:-quick}
fail=0
run() { name="$1"; shift; out=$("$@" 2>&1); rc=$?
  last=$(printf '%s\n' "$out" | grep -E "ALL PASS|PROBLEMS: 0|^OK|ERRORS: 0" | tail -1)
  if [ $rc -eq 0 ] && [ -n "$last" ]; then printf 'PASS  %-34s %s\n' "$name" "$last"; else printf 'FAIL  %-34s (exit %s)\n' "$name" "$rc"; printf '%s\n' "$out" | grep -E "FAIL|Error|Traceback|assert" | head -6 | sed 's/^/        /'; fail=1; fi; }
# shellcheck disable=SC2317  # called through run()
gtk() { GDK_BACKEND=x11 timeout "$1" xvfb-run -a -s "-screen 0 1280x800x24" python3 -I -u "${@:2}"; }
python3 -m pyflakes splice && echo "PASS  lint"
[ -d tests/media_qa ] || { echo "tests/media_qa missing: run tests/make_media.sh first"; exit 1; }
run "export basics"            python3 -I tests/test_export.py
run "export safety"            timeout 120 python3 -I tests/qa_export_safety.py
run "GPU export"               timeout 200 python3 -I tests/qa_gpu.py
run "media matrix"             timeout 120 python3 -I tests/qa_engine.py
run "content accuracy"         timeout 120 python3 -I tests/qa_content.py
run "captions follow clips"     python3 -I tests/test_model_anchor.py
run "crop geometry"            timeout 90 python3 -I tests/test_cropdrag.py
run "captions: emoji/CJK/fit"  timeout 120 python3 -I tests/qa_text.py
run "player"                   timeout 60 python3 -I tests/test_player.py
run "preview audio"            timeout 90 python3 -I tests/qa_audio_preview.py
run "mouse drags (UI)"         gtk 90 tests/xdrag.py
run "keyboard + focus (UI)"    gtk 90 tests/qa_keys.py
run "crop dragging (UI)"       gtk 120 tests/qa_crop.py
run "alt/ctrl scroll zoom (UI)" gtk 120 tests/qa_zoom.py
run "export labels (UI)"       gtk 90 tests/qa_export_ui.py
run "projects + close (UI)"    gtk 90 tests/qa_projects.py
for s in 1 2 3; do run "fuzz seed $s (UI)" gtk 120 tests/qa_fuzz.py $s 250; done
if [ "$MODE" = full ]; then
  for s in 4 5 6 7 8 9; do run "fuzz seed $s (UI)" gtk 150 tests/qa_fuzz.py $s 350; done
  run "one-hour timeline (UI)"  gtk 120 tests/qa_longtimeline.py
fi
[ $fail -eq 0 ] && echo "ALL GREEN" || echo "SOME FAILED"
exit $fail
