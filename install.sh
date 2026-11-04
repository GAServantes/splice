#!/bin/sh
# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
# Install Splice for this user: app menu ("Show Apps"), icon, .splice file type, and a dock shortcut.
#   ./install.sh              install everything (dock shortcut included)
#   ./install.sh --no-dock    install but leave the dock alone
#   ./install.sh --uninstall  remove all of it again
# Nothing is written outside your home folder, and it is safe to run more than once.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ID=io.github.gaservantes.Splice
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
MIME="$HOME/.local/share/mime/packages"
DOCK=yes; REMOVE=no
for a in "$@"; do case "$a" in --no-dock) DOCK=no;; --uninstall) REMOVE=yes;; esac; done

dock() {  # dock add|remove : edit GNOME's favorite apps (the dock) without touching other entries
  command -v gsettings >/dev/null 2>&1 || { echo "gsettings not found: skipped the dock"; return 0; }
  python3 - "$1" "$ID.desktop" <<'PY'
import ast, subprocess, sys
action, desk = sys.argv[1], sys.argv[2]
cur = ast.literal_eval(subprocess.run(["gsettings", "get", "org.gnome.shell", "favorite-apps"], capture_output=True, text=True, check=True).stdout.strip())
new = [d for d in cur if d != desk]
if action == "add":
    new.append(desk)
if new != cur:
    subprocess.run(["gsettings", "set", "org.gnome.shell", "favorite-apps", str(new)], check=True)
print("dock:", "pinned" if action == "add" else "unpinned", "->", new)
PY
}

if [ "$REMOVE" = yes ]; then
  if [ "$DOCK" = yes ]; then dock remove || true; fi
  rm -f "$APPS/$ID.desktop" "$ICONS/$ID.svg" "$MIME/$ID.xml"
  update-desktop-database "$APPS" 2>/dev/null || true
  update-mime-database "$HOME/.local/share/mime" 2>/dev/null || true
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
  echo "Splice removed from the app menu and dock. Your projects and videos are untouched."
  exit 0
fi

mkdir -p "$APPS" "$ICONS" "$MIME"
cp "$HERE/data/$ID.svg" "$ICONS/$ID.svg"
cp "$HERE/data/$ID.mime.xml" "$MIME/$ID.xml"
sed "s|@EXEC@|$HERE/bin/splice|" "$HERE/data/$ID.desktop.in" > "$APPS/$ID.desktop"
chmod 644 "$APPS/$ID.desktop"
# remove the launcher an older version of this script wrote
rm -f "$APPS/splice.desktop"
command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$APPS/$ID.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
update-mime-database "$HOME/.local/share/mime" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
[ "$DOCK" = yes ] && dock add
echo "Splice is installed: open Show Apps and look for Splice."
