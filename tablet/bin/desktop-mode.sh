#!/bin/bash
# desktop-mode.sh on|off|toggle|keep   (keep = background keeper used by the service)
FLAG=$HOME/.config/desktop-mode.on
apply(){ if [ -f $FLAG ]; then gsettings set sm.puri.phoc auto-maximize false; systemctl --user unset-environment QT_WAYLAND_DISABLE_WINDOWDECORATION; mkdir -p $HOME/.config/systemd/user/mobi.phosh.Shell.service.d; printf "[Service]\nUnsetEnvironment=QT_WAYLAND_DISABLE_WINDOWDECORATION\n" > $HOME/.config/systemd/user/mobi.phosh.Shell.service.d/desktop-mode.conf; systemctl --user daemon-reload; else gsettings set sm.puri.phoc auto-maximize true; systemctl --user set-environment QT_WAYLAND_DISABLE_WINDOWDECORATION=1; rm -f $HOME/.config/systemd/user/mobi.phosh.Shell.service.d/desktop-mode.conf; systemctl --user daemon-reload; fi; }
case "$1" in
  on) touch $FLAG; apply; notify-send -i video-display "Desktop mode" "ON - lock+unlock (or restart) once for title bars on all apps";;
  off) rm -f $FLAG; apply; notify-send -i phone "Desktop mode" "OFF - tablet mode";;
  toggle) if [ -f $FLAG ]; then $0 off; else $0 on; fi;;
  keep) apply; gsettings monitor sm.puri.phoc auto-maximize | while read -r _; do sleep 0.5; want=$([ -f $FLAG ] && echo false || echo true); [ "$(gsettings get sm.puri.phoc auto-maximize)" = "$want" ] || apply; done;;
esac
