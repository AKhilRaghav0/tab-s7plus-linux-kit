#!/bin/bash
# Reading mode: DND + warm night light + dimmer screen + longer screen timeout + Foliate.
S=$HOME/.config/reading-mode.saved
P=(org.gnome.SettingsDaemon.Power /org/gnome/SettingsDaemon/Power org.gnome.SettingsDaemon.Power.Screen Brightness)
C=org.gnome.settings-daemon.plugins.color
getb(){ busctl --user get-property "${P[@]}" | awk "{print \$2}"; }
on(){
  [ -f $S ] || printf "%s\n" "$(getb)" "$(gsettings get org.gnome.desktop.notifications show-banners)" "$(gsettings get $C night-light-enabled)" "$(gsettings get org.gnome.desktop.session idle-delay | awk "{print \$2}")" "$(gsettings get com.github.johnfactotum.Foliate.viewer.view theme)" "$(gsettings get com.github.johnfactotum.Foliate color-scheme)" > $S
  gsettings set org.gnome.desktop.notifications show-banners false
  gsettings set $C night-light-schedule-automatic false
  gsettings set $C night-light-schedule-from 0.0; gsettings set $C night-light-schedule-to 23.99
  gsettings set $C night-light-temperature 3200; gsettings set $C night-light-enabled true
  gsettings set org.gnome.desktop.session idle-delay 900
  busctl --user set-property "${P[@]}" i ${READING_BRIGHTNESS:-30}
  gsettings set com.github.johnfactotum.Foliate.viewer.view theme sepia; gsettings set com.github.johnfactotum.Foliate color-scheme 1
  pgrep -x foliate >/dev/null || (setsid foliate >/dev/null 2>&1 &)
  notify-send -i accessories-dictionary "Reading mode" "ON - quiet, warm and dim. Enjoy the book"
}
off(){
  if [ -f $S ]; then mapfile -t v < $S
    busctl --user set-property "${P[@]}" i "${v[0]:-50}"
    gsettings set org.gnome.desktop.notifications show-banners "${v[1]:-true}"
    gsettings set $C night-light-enabled "${v[2]:-false}"
    gsettings set org.gnome.desktop.session idle-delay "${v[3]:-300}"
    gsettings set com.github.johnfactotum.Foliate.viewer.view theme "${v[4]:-default}"; gsettings set com.github.johnfactotum.Foliate color-scheme "${v[5]:-4}"
    rm -f $S; fi
  notify-send -i accessories-dictionary "Reading mode" "OFF"
}
case "$1" in on) on;; off) off;; *) [ -f $S ] && off || on;; esac
