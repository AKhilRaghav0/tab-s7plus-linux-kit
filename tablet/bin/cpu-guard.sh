#!/bin/bash
# Keep CPU governors on schedutil while the screen is on.
# mobile-power-saver sets "powersave" on screen-off and sometimes fails to restore it on resume,
# which leaves all 8 cores pinned at minimum clock (~0.7 GHz) and makes the UI crawl.
w(){ [ "$(cat $1 2>/dev/null)" = "$2" ] || echo "$2" | sudo -n tee "$1" >/dev/null 2>&1; }
fix(){
  for p in /sys/devices/system/cpu/cpufreq/policy*; do
    w $p/scaling_governor schedutil
    w $p/schedutil/up_rate_limit_us 0        # ramp up immediately on load (touch, scroll)
    w $p/schedutil/down_rate_limit_us 20000  # hold the higher clock 20 ms so frames do not stutter
    w $p/schedutil/hispeed_load 80
  done
  P=/sys/devices/system/cpu/cpufreq
  w $P/policy0/schedutil/hispeed_freq 1420800   # little cores jump straight to 1.4 GHz under load
  w $P/policy4/schedutil/hispeed_freq 1862400
  w $P/policy7/schedutil/hispeed_freq 1862400
  w $P/policy0/scaling_min_freq 979200          # UI floor while the screen is on (powersave on screen-off still wins)
}
screen_on(){ [ "$(cat /sys/class/backlight/panel0-backlight/bl_power 2>/dev/null)" = "0" ]; }
fix
# wake up on screen unlock / display power changes, plus a slow safety net
gdbus monitor --session --dest org.gnome.ScreenSaver 2>/dev/null | while read -r l; do
  case "$l" in *ActiveChanged*false*) sleep 1; fix;; esac
done &
while sleep 20; do screen_on && fix; done
