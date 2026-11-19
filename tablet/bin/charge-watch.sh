#!/bin/bash
# Charger plugged in -> desk display (screen stays on). Unplugged -> back to normal.
ST=/sys/class/power_supply/battery/status; HALL=/sys/class/sec/hall_ic/hall_detect
SAVE=$HOME/.config/charge-watch.saved; FLAG=$HOME/.config/desk-auto.off
sid(){ loginctl list-sessions --no-legend | awk "\$3==\"$USER\"{print \$1; exit}"; }
on(){
  [ -f $FLAG ] && return; [ "$(cat $HALL)" = "CLOSE" ] && return
  echo "$(gsettings get org.gnome.desktop.session idle-delay)|$(gsettings get org.gnome.desktop.screensaver lock-enabled)" > $SAVE
  gsettings set org.gnome.desktop.session idle-delay 0; gsettings set org.gnome.desktop.screensaver lock-enabled false
  busctl --user set-property org.gnome.Mutter.DisplayConfig /org/gnome/Mutter/DisplayConfig org.gnome.Mutter.DisplayConfig PowerSaveMode i 0
  loginctl unlock-session "$(sid)" 2>/dev/null
  pgrep -f "[d]esk-display.py" >/dev/null || (setsid python3 $HOME/.local/bin/desk-display.py >/dev/null 2>&1 &)
}
off(){
  pkill -f "[d]esk-display.py"
  if [ -f $SAVE ]; then IFS="|" read -r d l < $SAVE; gsettings set org.gnome.desktop.session idle-delay "${d#uint32 }"; gsettings set org.gnome.desktop.screensaver lock-enabled "$l"; rm -f $SAVE; fi
}
charging(){ case "$(cat $ST)" in Charging|Full) echo 1;; *) echo 0;; esac; }
prev=$(charging); [ "$prev" = 1 ] && on
while sleep 2; do
  cur=$(charging); [ "$cur" = "$prev" ] && continue
  if [ "$cur" = 1 ]; then on; else off; fi; prev=$cur
done
