#!/bin/bash
# Audio manager for the Galaxy Tab S7+ (Droidian, PulseAudio + droid card).
# Outputs that exist on this tablet: built-in speakers, USB-C headphones (EarPods), Bluetooth, "MacBook" (bridge).
#  - priority: USB headphones > Bluetooth (A2DP) > speakers
#  - headphones removed  -> pause media and fall back to the speakers at a safe volume (never blast at 2 am)
#  - user picks the speakers in Phosh -> cap the speaker volume too
#  - the droid sink has no jack/earpiece here: always keep it on the speaker port
#  - hide useless outputs: fake SCO null sink/source; sink.fast is redirected to the primary sink
#  - built-in mic forced to input-builtin_mic (the default wired-headset port records at ~20 % speed)
F=$HOME/.config/last-volume; SPK=sink.primary-out; SAFE=35

getvol(){ pactl list sinks | awk -v s="$SPK" '$1=="Name:"{f=($2==s)} f&&/^\tVolume:/{for(i=1;i<=NF;i++) if($i ~ /%$/){print $i; exit}}'; }
move_all(){ for i in $(pactl list short sink-inputs | cut -f1); do pactl move-sink-input "$i" "$1" 2>/dev/null; done; }
ext_sink(){                         # first external output present, USB before Bluetooth
  pactl list short sinks | awk '/alsa_output.usb/{print $2; exit}'
  pactl list short sinks | awk '/bluez_sink\..*a2dp/{print $2; exit}'
}
is_ext(){ case "$1" in alsa_output.usb*|bluez_sink*) return 0;; esac; return 1; }
kill_sidetone(){ $HOME/.local/bin/kill-sidetone.sh; }
ensure_mac(){ pactl list short sinks | grep -q "mac_speaker" || pactl load-module module-null-sink sink_name=mac_speaker rate=48000 sink_properties=device.description=MacBook >/dev/null; }
defsink(){ pactl info | awk -F': ' '/^Default Sink/{print $2}'; }
hide_junk(){                        # calls-only fake SCO devices: useless on a Wi-Fi tablet, just clutter the output list
  for m in $(pactl list short modules | awk '/module-null-(sink|source).*fake\.sco/{print $1}'); do pactl unload-module "$m" 2>/dev/null; done
}
safe_speaker(){                     # cap the speaker volume (percent of the first channel)
  v=$(getvol | tr -d %); [ -n "$v" ] && [ "$v" -gt $SAFE ] && pactl set-sink-volume $SPK ${SAFE}%
}
speaker_port(){ pactl set-sink-port $SPK output-speaker 2>/dev/null; }

route(){
  kill_sidetone
  hide_junk
  pactl set-source-port source.primary-in input-builtin_mic 2>/dev/null
  speaker_port
  for c in $(pactl list short cards | awk '/alsa_card.usb/{print $2}'); do
    pactl set-card-profile "$c" output:analog-stereo+input:mono-fallback 2>/dev/null || pactl set-card-profile "$c" output:analog-stereo 2>/dev/null
  done
  for c in $(pactl list short cards | awk '/bluez_card/{print $2}'); do      # music profile, not the call profile
    pactl set-card-profile "$c" a2dp_sink 2>/dev/null
  done
  cur=$(defsink); u=$(ext_sink | head -1)
  if [ -n "$u" ]; then
    [ "$cur" = mac_speaker ] && [ "$1" != plug ] && return     # user chose the Mac: leave it unless headphones were just plugged
    pactl set-default-sink "$u"; move_all "$u"
  else
    [ "$cur" = mac_speaker ] && return
    if is_ext "$lastdef" || ! pactl list short sinks | cut -f2 | grep -qx "$cur"; then
      playerctl -a pause 2>/dev/null                          # headphones gone: pause, like Android's "becoming noisy"
      safe_speaker
    fi
    pactl set-default-sink $SPK; move_all $SPK
  fi
  lastdef=$(defsink)
}

for i in $(seq 1 30); do [ -n "$(getvol)" ] && break; sleep 1; done
ensure_mac
v=$(cat $F 2>/dev/null | grep -E '^[0-9]+%$' | tr -d %); [ -z "$v" ] && v=30; [ "$v" -gt 60 ] && v=60
pactl set-sink-volume $SPK ${v}%
lastdef=$(defsink)
route
last=0
pactl subscribe | while read -r line; do
  case "$line" in
    *"new"*"on card"*|*"new"*"on sink #"*)       sleep 0.4; route plug ;;
    *"remove"*"on card"*|*"remove"*"on sink #"*) sleep 0.3; route ;;
    *"change"*"on server"*)                     # default output changed (e.g. from the Phosh quick settings)
      d=$(defsink)
      { [ -z "$d" ] || [ "$d" = "$lastdef" ]; } && continue
      case "$d" in
        sink.fast|sink.fake.sco) pactl set-default-sink $SPK; d=$SPK ;;
      esac
      [ "$d" = "$SPK" ] && { speaker_port; safe_speaker; }
      move_all "$d"; lastdef=$d ;;
    *"change"*"on sink #"*)
      now=$(date +%s); [ $((now-last)) -lt 1 ] && continue; last=$now
      # someone picked a jack/earpiece port on the droid sink: there is no jack, snap back to the speaker
      p=$(pactl list sinks | awk -v s="$SPK" '$1=="Name:"{f=($2==s)} f&&/Active Port:/{print $3; exit}')
      [ -n "$p" ] && [ "$p" != output-speaker ] && { speaker_port; safe_speaker; }
      [ "$(defsink)" = "$SPK" ] && { v=$(getvol); [ -n "$v" ] && echo "$v" > $F; } ;;
  esac
done
