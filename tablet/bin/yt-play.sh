#!/bin/bash
# Play a YouTube link (arg or clipboard) in Clapper with hardware decoding (gst-droid). Max 1080p.
URL="${1:-$(wl-paste -n 2>/dev/null)}"
case "$URL" in http*youtu*) ;; *) notify-send -i video-x-generic "YouTube" "Copy a YouTube link first"; exit 1;; esac
notify-send -i video-x-generic "YouTube" "Loading in Clapper (HW decode)..."
V=$($HOME/.local/bin/yt-dlp -g -f "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[vcodec^=avc1]/b" "$URL" 2>/dev/null)
[ -z "$V" ] && { notify-send "YouTube" "Could not get stream"; exit 1; }
set -- $V
if [ -n "$2" ]; then exec clapper "$1" --enqueue 2>/dev/null & else exec clapper "$1"; fi
