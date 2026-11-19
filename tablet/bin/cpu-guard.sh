#!/bin/bash
# Keep CPU governors on schedutil while the screen is on.
# mobile-power-saver sets "powersave" on screen-off and sometimes fails to restore it on resume,
# which leaves all 8 cores pinned at minimum clock (~0.7 GHz) and makes the UI crawl.
fix(){ for p in /sys/devices/system/cpu/cpufreq/policy*; do
         [ "$(cat $p/scaling_governor)" = schedutil ] || echo schedutil | sudo -n tee $p/scaling_governor >/dev/null; done; }
screen_on(){ [ "$(cat /sys/class/backlight/panel0-backlight/bl_power 2>/dev/null)" = "0" ]; }
fix
# wake up on screen unlock / display power changes, plus a slow safety net
gdbus monitor --session --dest org.gnome.ScreenSaver 2>/dev/null | while read -r l; do
  case "$l" in *ActiveChanged*false*) sleep 1; fix;; esac
done &
while sleep 20; do screen_on && fix; done
