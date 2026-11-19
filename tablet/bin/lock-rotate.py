#!/usr/bin/env python3
"""Rotate the Phosh lock screen with the accelerometer.
Phosh freezes rotation while locked. This daemon claims the accelerometer through monitor-sensor.
- While UNLOCKED it learns which output transform Phosh picks for each sensor orientation.
- While LOCKED it applies that transform with wlr-randr."""
import subprocess, json, os, re, threading, time
OUT = "HWCOMPOSER-1"
MAPF = os.path.expanduser("~/.config/lock-rotate.json")
mapping = {"normal": "normal", "bottom-up": "180", "left-up": "90", "right-up": "270"}
try: mapping.update(json.load(open(MAPF)))
except Exception: pass
state = {"orient": None}
def locked():
    r = subprocess.run(["busctl","--user","call","org.gnome.ScreenSaver","/org/gnome/ScreenSaver",
                        "org.gnome.ScreenSaver","GetActive"], capture_output=True, text=True)
    return r.stdout.strip().endswith("true")
def cur_transform():
    r = subprocess.run(["wlr-randr","--output",OUT], capture_output=True, text=True).stdout
    m = re.search(r"Transform:\s*(\S+)", r); return m.group(1) if m else None
def apply(o):
    t = mapping.get(o)
    if t and cur_transform() != t:
        subprocess.run(["wlr-randr","--output",OUT,"--transform",t])
def learn(o):
    time.sleep(2.0)
    if state["orient"] == o and not locked():
        t = cur_transform()
        if t and mapping.get(o) != t:
            mapping[o] = t; json.dump(mapping, open(MAPF,"w"))
def gs(*a): return subprocess.run(["gsettings", *a], capture_output=True, text=True).stdout.strip()
def lock_watch():
    was = False; saved = None
    while True:
        now = locked()
        if now and not was: saved = cur_transform()          # Phosh transform before we touch it
        if now and state["orient"]: apply(state["orient"])
        if was and not now:                                    # just unlocked: hand rotation back to Phosh
            if saved: subprocess.run(["wlr-randr", "--output", OUT, "--transform", saved])
            k = ("org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock")
            if gs("get", *k) == "false":                       # nudge Phosh to re-read the sensor
                gs("set", *k, "true"); time.sleep(0.4); gs("set", *k, "false")
        was = now; time.sleep(0.7)
def main():
    threading.Thread(target=lock_watch, daemon=True).start()
    while True:
        p = subprocess.Popen(["monitor-sensor","--accel"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in p.stdout:
            m = re.search(r"orientation(?: changed)?: ([a-z-]+)", line)
            if not m or m.group(1) in ("null","undefined"): continue
            o = m.group(1); state["orient"] = o
            if locked(): apply(o)
            else: threading.Thread(target=learn, args=(o,), daemon=True).start()
        time.sleep(3)
main()
