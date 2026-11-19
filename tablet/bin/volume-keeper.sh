#!/bin/bash
# Audio manager: remember speaker volume, sane routing for USB-C headphones.
#  - USB audio plugged  -> analog-stereo profile, make it default, move streams to it
#  - USB audio removed  -> default back to speakers (sink.primary-out), move streams there
#  - never let the fake 8 kHz SCO sink become default
F=$HOME/.config/last-volume; SPK=sink.primary-out
getvol(){ pactl list sinks | awk -v s="$SPK" "\$1==\"Name:\"{f=(\$2==s)} f&&/^\tVolume:/{for(i=1;i<=NF;i++) if(\$i ~ /%\$/){print \$i; exit}}"; }
move_all(){ for i in $(pactl list short sink-inputs | cut -f1); do pactl move-sink-input "$i" "$1" 2>/dev/null; done; }
usb_sink(){ pactl list short sinks | awk "/alsa_output.usb/{print \$2; exit}"; }
kill_sidetone(){ $HOME/.local/bin/kill-sidetone.sh; }
ensure_mac(){ pactl list short sinks | grep -q "mac_speaker" || pactl load-module module-null-sink sink_name=mac_speaker rate=48000 "sink_properties=device.description=Mac-Speaker" >/dev/null; }
defsink(){ pactl info | awk -F": " "/^Default Sink/{print \$2}"; }
route(){
  kill_sidetone
  [ "$(defsink)" = "mac_speaker" ] && return     # user chose Mac Speaker: leave it
  for c in $(pactl list short cards | awk "/alsa_card.usb/{print \$2}"); do
    pactl set-card-profile "$c" output:analog-stereo+input:mono-fallback 2>/dev/null || pactl set-card-profile "$c" output:analog-stereo 2>/dev/null
  done
  u=$(usb_sink)
  if [ -n "$u" ]; then pactl set-default-sink "$u"; move_all "$u"
  else pactl set-sink-port $SPK output-speaker 2>/dev/null; pactl set-default-sink $SPK; move_all $SPK; fi
}
for i in $(seq 1 30); do [ -n "$(getvol)" ] && break; sleep 1; done
ensure_mac
pactl set-sink-volume $SPK "$(cat $F 2>/dev/null | grep -E "^[0-9]+%$" || echo 40%)"
route
last=0
pactl subscribe | while read -r line; do
  case "$line" in
    *"new"*"on card"*|*"remove"*"on card"*|*"remove"*"on sink #"*|*"new"*"on sink #"*) sleep 0.3; route ;;
    *"change"*"on sink #"*)
      now=$(date +%s); [ $((now-last)) -lt 1 ] && continue; last=$now   # throttle saving
      v=$(getvol); [ -n "$v" ] && echo "$v" > $F ;;
  esac
done
