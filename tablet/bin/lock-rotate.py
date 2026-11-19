#!/usr/bin/env python3
"""Rotate the Phosh lock screen with the accelerometer, event-driven.

Phosh freezes rotation while locked. This daemon sleeps (GLib main loop, no polling)
until org.gnome.ScreenSaver emits ActiveChanged(true). Only then does it start
monitor-sensor and rotate the output with wlr-randr. On unlock it stops the
sensor, restores Phosh's transform and nudges Phosh to re-read the sensor.
The orientation->transform mapping is a fixed table (see `mapping`)."""
import json, os, re, subprocess
from gi.repository import Gio, GLib

OUT = "HWCOMPOSER-1"
MAPF = os.path.expanduser("~/.config/lock-rotate.json")
mapping = {"normal": "normal", "bottom-up": "180", "left-up": "90", "right-up": "270"}
# fixed mapping for this landscape-native panel (right-up -> 270 verified)
KEY = ("org.gnome.settings-daemon.peripherals.touchscreen", "orientation-lock")
state = {"proc": None, "saved": None, "watch": None}

def cur_transform():
    r = subprocess.run(["wlr-randr", "--output", OUT], capture_output=True, text=True).stdout
    m = re.search(r"Transform:\s*(\S+)", r); return m.group(1) if m else None

def sensor_orientation():
    r = subprocess.run(["busctl", "--system", "get-property", "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
                        "net.hadess.SensorProxy", "AccelerometerOrientation"], capture_output=True, text=True).stdout
    m = re.search(r'"([a-z-]+)"', r); return m.group(1) if m else None

def apply(o):
    t = mapping.get(o)
    if t and cur_transform() != t:
        subprocess.run(["wlr-randr", "--output", OUT, "--transform", t])

def on_sensor_line(stream):
    line = stream.readline()
    if not line: return False
    m = re.search(r"orientation(?: changed)?: ([a-z-]+)", line)
    if m and m.group(1) not in ("null", "undefined"): apply(m.group(1))
    return True

def start_sensor():
    if state["proc"]: return
    p = subprocess.Popen(["monitor-sensor", "--accel"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    state["proc"] = p
    ch = GLib.IOChannel.unix_new(p.stdout.fileno())
    state["watch"] = GLib.io_add_watch(ch, GLib.IO_IN | GLib.IO_HUP, lambda c, cond: on_sensor_line(p.stdout))

def stop_sensor():
    if state["watch"]: GLib.source_remove(state["watch"]); state["watch"] = None
    if state["proc"]:
        state["proc"].kill(); state["proc"].wait(); state["proc"] = None

def on_locked():
    # Learning the mapping from Phosh's last choice was unreliable (rotation lock on, or the tablet lying flat,
    # means Phosh doesn't rotate, so we'd learn "normal" for everything). Use the fixed mapping instead.
    t = cur_transform()
    state["saved"] = t
    start_sensor()

def on_unlocked():
    stop_sensor()
    if state["saved"]: subprocess.run(["wlr-randr", "--output", OUT, "--transform", state["saved"]])
    if subprocess.run(["gsettings", "get", *KEY], capture_output=True, text=True).stdout.strip() == "false":
        subprocess.run(["gsettings", "set", *KEY, "true"]); subprocess.run(["gsettings", "set", *KEY, "false"])

def on_signal(conn, sender, path, iface, signal, params):
    (active,) = params.unpack()
    on_locked() if active else on_unlocked()

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
bus.signal_subscribe(None, "org.gnome.ScreenSaver", "ActiveChanged", "/org/gnome/ScreenSaver", None,
                     Gio.DBusSignalFlags.NONE, on_signal)
GLib.MainLoop().run()
