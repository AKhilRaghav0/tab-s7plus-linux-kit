#!/bin/bash
# Toggle: send all tablet audio to the Mac (via the Mac bridge) or back to the tablet.
cur=$(pactl info | awk -F": " "/^Default Sink/{print \$2}")
move(){ for i in $(pactl list short sink-inputs | cut -f1); do pactl move-sink-input "$i" "$1" 2>/dev/null; done; }
if [ "$cur" = "mac_speaker" ]; then
  t=$(pactl list short sinks | awk "/alsa_output.usb/{print \$2; exit}"); t=${t:-sink.primary-out}
  pactl set-default-sink "$t"; move "$t"; notify-send -i audio-speakers "Audio" "Playing on the tablet"
else
  pactl set-default-sink mac_speaker; move mac_speaker; notify-send -i computer "Audio" "Playing on the Mac 💻"
fi
