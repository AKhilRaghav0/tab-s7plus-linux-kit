#!/bin/bash
# S Pen: detach -> open Xournal++ (new note) ; attach -> small notification
PEN=/sys/class/sec/sec_epen/epen_insert
APP="${SPEN_APP:-xournalpp}"
prev=$(cat $PEN)
while sleep 0.4; do
  cur=$(cat $PEN 2>/dev/null) || continue
  [ "$cur" = "$prev" ] && continue
  if [ "$cur" = "0" ]; then
    notify-send -i accessories-text-editor "S Pen" "Pen detached - opening notes" 2>/dev/null
    pgrep -x "$APP" >/dev/null || (setsid "$APP" >/dev/null 2>&1 &)
  else
    notify-send -i input-tablet "S Pen" "Pen attached - charging" 2>/dev/null
  fi
  prev=$cur
done
