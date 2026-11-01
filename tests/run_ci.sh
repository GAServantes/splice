#!/bin/bash
# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
# The tests that need no GPU, no real display and no big files. This is what GitHub Actions runs.
# Usage: tests/run_ci.sh        (generates the small test media first)
cd "$(dirname "$0")/.." || exit 1
fail=0
run() { name="$1"; shift; if out=$("$@" 2>&1); then printf 'PASS  %s\n' "$name"; else printf 'FAIL  %s\n' "$name"; printf '%s\n' "$out" | tail -25 | sed 's/^/        /'; fail=1; fi; }
tests/make_media.sh --ci || exit 1
run "lint (pyflakes)"              python3 -m pyflakes splice
if command -v shellcheck >/dev/null; then run "shellcheck" shellcheck install.sh tests/*.sh bin/splice; fi
run "compile"                      python3 -m py_compile splice/*.py tests/*.py
export SPLICE_ENCODER=cpu                 # CI runners have no GPU
export SPLICE_NOAUDIO=1                   # no sound card in a container
run "crop geometry"                python3 -I tests/test_cropdrag.py
run "captions follow clips"        python3 -I tests/test_model_anchor.py
run "export basics"                python3 -I tests/test_export.py
run "export content accuracy"      python3 -I tests/qa_content.py
run "media matrix (19 files)"      python3 -I tests/qa_engine.py
run "captions: emoji/CJK/fit"      python3 -I tests/qa_text.py
run "player"                       python3 -I tests/test_player.py
run "preview audio"                python3 -I tests/qa_audio_preview.py
run "random edits in the window"   env GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1280x800x24" python3 -I tests/qa_fuzz.py 1 200
run "projects, files, close"       env GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1280x800x24" python3 -I tests/qa_projects.py
[ $fail -eq 0 ] && echo "ALL GREEN" || echo "SOME FAILED"
exit $fail
