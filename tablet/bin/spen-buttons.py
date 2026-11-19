#!/usr/bin/env python3
"""S Pen side-button actions (pen hovering, not touching the screen):
   double-click -> screenshot (~/Pictures/Screenshots)
   long-press   -> open a new Xournal++ note
   single click is left alone (apps treat it as right-click)."""
import evdev, time, subprocess, os, datetime
DEV = "/dev/input/event5"; DOUBLE = 0.45; LONG = 0.8
def screenshot():
    fn = os.path.expanduser(datetime.datetime.now().strftime("~/Pictures/Screenshots/spen_%Y%m%d_%H%M%S.png"))
    subprocess.run(["busctl","--user","call","org.gnome.Shell.Screenshot","/org/gnome/Shell/Screenshot",
                    "org.gnome.Shell.Screenshot","Screenshot","bbs","false","true",fn])
    subprocess.run(["notify-send","-i","camera-photo","S Pen","Screenshot saved"])
def note():
    subprocess.Popen(["setsid","xournalpp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while True:
    try:
        d = evdev.InputDevice(DEV); touching = False; down_t = 0; last_up = 0; clicks = 0
        for e in d.read_loop():
            if e.type != evdev.ecodes.EV_KEY: continue
            if e.code == evdev.ecodes.BTN_TOUCH: touching = bool(e.value); continue
            if e.code != evdev.ecodes.BTN_STYLUS or touching: continue
            now = e.timestamp()
            if e.value == 1: down_t = now
            elif e.value == 0:
                if now - down_t >= LONG: note(); clicks = 0; continue
                clicks = clicks + 1 if now - last_up < DOUBLE else 1
                last_up = now
                if clicks == 2: screenshot(); clicks = 0
    except Exception:
        time.sleep(3)
