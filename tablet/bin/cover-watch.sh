#!/bin/bash
# Smart cover: CLOSE -> lock + display off ; OPEN -> display on (lock screen shows)
HALL=/sys/class/sec/hall_ic/hall_detect
set_psm(){ busctl --user set-property org.gnome.Mutter.DisplayConfig /org/gnome/Mutter/DisplayConfig org.gnome.Mutter.DisplayConfig PowerSaveMode i "$1" 2>/dev/null; }
prev=$(cat $HALL)
while sleep 0.4; do
  cur=$(cat $HALL)
  [ "$cur" = "$prev" ] && continue
  if [ "$cur" = "CLOSE" ]; then loginctl lock-session 2>/dev/null; sleep 0.3; set_psm 3
  else set_psm 0; fi
  prev=$cur
done
