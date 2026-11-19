#!/bin/sh
# Keep the S Pen charging while it is docked on the back (Android's S Pen service normally does this).
D=/sys/class/sec/sec_epen
while true; do
  if [ "$(cat $D/epen_insert 2>/dev/null)" = 1 ] && [ "$(cat $D/epen_ble_charging_mode 2>/dev/null)" != CHARGE ]; then
    echo 1 > $D/epen_ble_charging_mode && logger -t spen-charge "charging enabled"
  fi
  sleep 30
done
