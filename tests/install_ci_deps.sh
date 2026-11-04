#!/bin/sh
# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
# Packages the CI subset needs on a bare Ubuntu image (used by .github/workflows/ci.yml).
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-gi python3-gi-cairo python3-cairo \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav \
  ffmpeg fontconfig fonts-dejavu-core fonts-noto-color-emoji fonts-noto-cjk \
  xvfb python3-pyflakes python3-numpy shellcheck ca-certificates
