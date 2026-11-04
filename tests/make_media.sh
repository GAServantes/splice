#!/bin/sh
# Copyright (C) 2026 G. Austin Servantes
# SPDX-License-Identifier: GPL-3.0-or-later
# Regenerates all test media with ffmpeg (nothing is committed). Takes about a minute.
# shellcheck disable=SC2086  # $F and $E are deliberate option lists
set -e
# --ci skips the large footage (used only by the GPU, performance and screenshot tests)
CI=no; [ "$1" = "--ci" ] && CI=yes
cd "$(dirname "$0")" && mkdir -p media media_qa
F="ffmpeg -v error -y -nostdin"; V="testsrc2=size=1280x720:rate=30:duration=4"; A="sine=frequency=440:duration=4"; E="-c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac"
cd media
for n in 1 2; do $F -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=6" -f lavfi -i "sine=frequency=$((300*n)):duration=6" -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac c$n.mp4; done
$F -f lavfi -i "testsrc=size=1920x1080:rate=24:duration=4" -c:v libx264 -preset ultrafast -pix_fmt yuv420p c3_silent.mp4
cd ../media_qa
$F -f lavfi -i "$V" -f lavfi -i "$A" $E base.mp4
$F -display_rotation 90 -i base.mp4 -c copy rot90.mp4
$F -f lavfi -i "testsrc2=size=720x1280:rate=30:duration=4" -f lavfi -i "$A" $E portrait.mp4
$F -f lavfi -i "testsrc2=size=1279x719:rate=30:duration=4" -f lavfi -i "$A" -c:v libx264 -preset ultrafast -pix_fmt yuv444p -c:a aac odd.mp4
$F -f lavfi -i "testsrc2=size=640x360:rate=30:duration=4" -f lavfi -i "$A" -vf "setpts='if(lt(N,60),N/30,2+(N-60)/10)/TB'" -fps_mode vfr $E vfr.mp4
$F -f lavfi -i "testsrc2=size=1280x720:rate=60:duration=4" -f lavfi -i "$A" $E fps60.mp4
$F -f lavfi -i "testsrc2=size=640x360:rate=30000/1001:duration=4" -f lavfi -i "$A" $E fps2997.mp4
$F -f lavfi -i "$V" -f lavfi -i "sine=frequency=440:sample_rate=22050:duration=4" -ac 1 $E mono22k.mp4
$F -f lavfi -i "$V" -f lavfi -i "$A" -af "pan=5.1|FL=c0|FR=c0|FC=c0|LFE=c0|BL=c0|BR=c0" $E surround.mp4
$F -f lavfi -i "$V" -f lavfi -i "sine=frequency=440:sample_rate=8000:duration=4" -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a pcm_s16le pcm8k.mov
$F -f lavfi -i "testsrc2=size=3840x2160:rate=30:duration=2" -f lavfi -i "sine=frequency=440:duration=2" $E uhd.mp4
$F -f lavfi -i "testsrc2=size=16x16:rate=30:duration=2" -c:v libx264 -preset ultrafast -pix_fmt yuv420p tiny_silent.mp4
$F -f lavfi -i "$A" -c:a libmp3lame audio_only.mp3
head -c 5000 /dev/urandom > garbage.mp4
$F -f lavfi -i "$V" -f lavfi -i "$A" $E -f matroska - > nodur.mkv
$F -f lavfi -i "$V" -f lavfi -i "$A" -c:v libx264 -preset ultrafast -pix_fmt yuv420p10le -profile:v high10 -c:a aac tenbit.mp4
$F -filter_complex "color=c=red:s=320x180:r=30:d=1[a];color=c=green:s=320x180:r=30:d=1[b];color=c=blue:s=320x180:r=30:d=1[c];color=c=yellow:s=320x180:r=30:d=1[d];[a][b][c][d]concat=n=4:v=1:a=0[v];aevalsrc='sin(2*PI*t*(200*pow(2,floor(t))))*0.5':s=48000:d=4[aud]" -map "[v]" -map "[aud]" -c:v libx264 -preset ultrafast -pix_fmt yuv420p -g 15 -c:a aac -b:a 192k tones.mp4
$F -f lavfi -i "color=c=black:s=640x360:r=60:d=12" -f lavfi -i "sine=frequency=440:duration=12" -vf "geq=lum='16+6*mod(N*13\,32)':cb=128:cr=128,select='if(between(t\,4\,4.4)+between(t\,7\,7.3)\,0\,lt(random(0)\,0.55))'" -fps_mode vfr -c:v libx264 -preset ultrafast -g 240 -bf 2 -video_track_timescale 16000 -pix_fmt yuv420p -c:a aac -shortest frameid_vfr.mp4
$F -f lavfi -i "color=c=black:s=640x360:r=30000/1001:d=8" -vf "geq=lum='16+6*mod(N*13\,32)':cb=128:cr=128" -c:v libx264 -preset ultrafast -g 300 -pix_fmt yuv420p frameid_2997.mp4
cp base.mp4 "my video (1) #2 %20 'q' é日本.mp4"; cp base.mp4 -- "-dash.mp4"; cp base.mp4 "a:b.mp4"
[ "$CI" = yes ] && { echo "media ready (CI subset)"; exit 0; }
# detailed footage used by the GPU quality tests and the README screenshots
$F -f lavfi -i "mandelbrot=size=1920x1080:rate=30,format=yuv420p" -t 20 -c:v libx264 -preset ultrafast -crf 14 fractal.mp4
$F -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=40" -f lavfi -i "sine=frequency=330:duration=40" -c:v libx264 -preset ultrafast -g 60 -pix_fmt yuv420p -c:a aac hd1080.mp4
$F -f lavfi -i "mandelbrot=size=1920x1080:rate=30,format=yuv420p" -f lavfi -i "sine=frequency=196:sample_rate=48000,tremolo=f=1.6:d=0.9,volume=3" -t 24 -c:v libx264 -preset ultrafast -crf 16 -pix_fmt yuv420p -c:a aac demo.mp4
echo "optional and slow (10 min of 720p): ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=30:duration=600 -f lavfi -i sine=duration=600 -c:v libx264 -preset ultrafast -g 250 -c:a aac tests/media_qa/long10min.mp4"
