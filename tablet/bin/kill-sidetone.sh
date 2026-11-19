#!/bin/bash
# Mute the mic-monitor (sidetone) path on USB headsets: a mixer control that has both playback and capture volume.
for c in $(awk "/USB-Audio/{print \$1}" /proc/asound/cards); do
  amixer -c "$c" scontrols | sed -E "s/^Simple mixer control (.*)$/\1/" | while IFS= read -r ctl; do
    info=$(amixer -c "$c" sget "$ctl")
    if echo "$info" | grep -q " pvolume" && echo "$info" | grep -q " cvolume"; then
      amixer -c "$c" sset "$ctl" playback 0 >/dev/null 2>&1
    fi
  done
done
