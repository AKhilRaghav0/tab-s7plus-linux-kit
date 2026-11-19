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
state = {"proc": None, "saved": None, "watch": None, "locked": False, "poll": None}

def cur_transform():
    r = subprocess.run(["wlr-randr", "--output", OUT], capture_output=True, text=True).stdout
    m = re.search(r"Transform:\s*(\S+)", r); return m.group(1) if m else None

def sensor_orientation():
    r = subprocess.run(["busctl", "--system", "get-property", "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
                        "net.hadess.SensorProxy", "AccelerometerOrientation"], capture_output=True, text=True).stdout
    m = re.search(r'"([a-z-]+)"', r); return m.group(1) if m else None

def apply(o):
    t = mapping.get(o)
    cur = cur_transform()          # None while the panel is off (output disabled)
    if t and cur and cur != t:
        subprocess.run(["wlr-randr", "--output", OUT, "--transform", t])

def reapply():
    """Phosh resets the transform when it turns the panel back on, so re-apply a few times after wake."""
    if state["locked"]:
        o = sensor_orientation()
        if o: apply(o)
    return False

def power_save_mode():
    try:
        v = bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                          "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", ("org.gnome.Mutter.DisplayConfig", "PowerSaveMode")), None, 0, 1000, None)
        return v.unpack()[0]
    except Exception:
        return None

def poll():
    if not state["locked"]:
        state["poll"] = None
        return False
    if power_save_mode() == 0:          # lock screen is visible: follow the sensor
        if state["proc"] is None:       # just woke: let Phosh finish laying out the lockscreen first
            start_sensor()
            GLib.timeout_add(700, reapply)
        else:
            reapply()
    else:                               # panel off: no need to keep the accelerometer running
        stop_sensor()
    return True

def on_power(conn, sender, path, iface, signal, params):
    i, changed, _ = params.unpack()
    if state["locked"] and "PowerSaveMode" in changed and changed["PowerSaveMode"] == 0:   # screen just came on
        GLib.timeout_add(700, reapply)      # once, after Phosh's own lockscreen fixup has settled

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
    state["saved"] = t or state["saved"]
    state["locked"] = True
    if state["poll"] is None:
        state["poll"] = GLib.timeout_add(1000, poll)

def on_unlocked():
    state["locked"] = False
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
bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", "/org/gnome/Mutter/DisplayConfig",
                     None, Gio.DBusSignalFlags.NONE, on_power)
GLib.MainLoop().run()
