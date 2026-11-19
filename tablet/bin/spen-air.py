#!/usr/bin/env python3
"""S Pen Air Actions for Linux (Galaxy Tab S7+ / Droidian).

The pen talks BLE (Samsung service 0xfd6c). Characteristic "Button State" (handle 0x0023) notifies:
  03                      -> button down
  f0 NN [0f dx dy seq]*NN -> motion deltas while held (int16 LE, already integrated by the pen)
  00 00 00 00 00 NN       -> button up
We classify each press as click / long / swipe-{left,right,up,down} and run an action.
"""
import os, struct, subprocess, time
import gi; gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

def find_pen():
    """First paired BlueZ device whose name starts with 'SPEN' (or $SPEN_MAC)."""
    if os.environ.get("SPEN_MAC"):
        return os.environ["SPEN_MAC"]
    b = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    objs = b.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                       None, None, 0, 5000, None).unpack()[0]
    for path, ifs in objs.items():
        d = ifs.get("org.bluez.Device1")
        if d and str(d.get("Name", "")).upper().startswith("SPEN") and d.get("Paired"):
            return d["Address"]
    raise SystemExit("No paired S Pen found. Pair it first (see README).")


MAC = find_pen()
DEV = "/org/bluez/hci0/dev_" + MAC.replace(":", "_")
BTN = DEV + "/service001e/char0023"
BATT = DEV + "/service001e/char001f"
SWIPE_MIN = 600        # total motion above this = gesture
LONG_S = 0.8           # held longer than this without moving = long press
DOUBLE_GAP = 0.35      # second click within this = double
DEBUG = os.environ.get("SPEN_DEBUG", "1") == "1"

ACTIONS = {
    "click":  ["playerctl", "play-pause"],
    "double": ["playerctl", "next"],
    "long":   ["playerctl", "previous"],
    "right":  ["playerctl", "next"],
    "left":   ["playerctl", "previous"],
    "up":     ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
    "down":   ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
}

bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
press = None
pending_click = None   # GLib source id waiting to see if a double click follows
sub_ok = False
last_batt = [None]
was_docked = False


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fire(name, extra=""):
    log("action", name, extra)
    if DEBUG:
        subprocess.Popen(["notify-send", "-a", "spen-air", "-t", "1200", f"S Pen: {name}", extra])
    cmd = ACTIONS.get(name)
    if cmd:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def click_timeout():
    global pending_click
    pending_click = None
    fire("click")
    return False


def finish(p):
    global pending_click
    dur = time.time() - p["t0"]
    dx, dy = p["dx"], p["dy"]
    mag = max(abs(p["maxx"]), abs(p["minx"]), abs(p["maxy"]), abs(p["miny"]))
    info = f"dx={dx} dy={dy} {dur:.2f}s"
    if mag >= SWIPE_MIN:
        if abs(dx) >= abs(dy):
            fire("right" if dx > 0 else "left", info)
        else:
            fire("down" if dy > 0 else "up", info)
    elif dur >= LONG_S:
        fire("long", info)
    elif pending_click:
        GLib.source_remove(pending_click); pending_click = None
        fire("double", info)
    else:
        pending_click = GLib.timeout_add(int(DOUBLE_GAP * 1000), click_timeout)


def on_value(b: bytes):
    global press
    if b == b"\x03":
        press = {"t0": time.time(), "dx": 0, "dy": 0, "minx": 0, "maxx": 0, "miny": 0, "maxy": 0}
    elif b and b[0] == 0xF0 and press:
        for i in range(b[1]):
            r = b[2 + 6 * i: 8 + 6 * i]
            if len(r) < 6:
                break
            dx, dy = struct.unpack("<hh", r[1:5])
            press["dx"] += dx; press["dy"] += dy
            press["minx"] = min(press["minx"], press["dx"]); press["maxx"] = max(press["maxx"], press["dx"])
            press["miny"] = min(press["miny"], press["dy"]); press["maxy"] = max(press["maxy"], press["dy"])
    elif len(b) == 6 and b[:5] == b"\0" * 5 and press:
        p, press = press, None
        finish(p)


def on_props(conn, sender, path, iface, signal, params):
    global sub_ok
    i, changed, _ = params.unpack()
    if path == BTN and i == "org.bluez.GattCharacteristic1" and "Value" in changed:
        if was_docked:
            return
        on_value(bytes(changed["Value"]))
    elif path == BATT and "Value" in changed:
        v = bytes(changed["Value"])
        if v and v[0] != last_batt[0]:
            last_batt[0] = v[0]; log("battery", v[0])
    elif path == DEV and i == "org.bluez.Device1" and "Connected" in changed:
        log("connected" if changed["Connected"] else "disconnected")
        if not changed["Connected"]:
            sub_ok = False


def call(path, iface, method, timeout=8000):
    return bus.call_sync("org.bluez", path, iface, method, None, None, 0, timeout, None)


def prop(path, iface, name):
    try:
        return bus.call_sync("org.bluez", path, "org.freedesktop.DBus.Properties", "Get",
                             GLib.Variant("(ss)", (iface, name)), None, 0, 3000, None).unpack()[0]
    except Exception:
        return None


def docked():
    try:
        return open("/sys/class/sec/sec_epen/epen_insert").read().strip() == "1"
    except Exception:
        return False


def tick():
    """Keep the pen connected and subscribed while it is out of the tablet."""
    global sub_ok, press, pending_click, was_docked
    d = docked()
    if d:
        # pen is back on the tablet: drop the BLE link so nothing fires and the pen can sleep/charge
        if not was_docked:
            log("docked: air actions off")
            press = None
            if pending_click:
                GLib.source_remove(pending_click); pending_click = None
        was_docked = True
        if prop(DEV, "org.bluez.Device1", "Connected"):
            try:
                call(DEV, "org.bluez.Device1", "Disconnect")
                log("disconnected pen (docked)")
            except Exception as e:
                log("disconnect failed", str(e)[-60:])
        sub_ok = False
        return True
    if was_docked:
        log("undocked: air actions on")
    was_docked = False
    connected = prop(DEV, "org.bluez.Device1", "Connected")
    if not connected:
        sub_ok = False
        if not docked():
            try:
                call(DEV, "org.bluez.Device1", "Connect", 10000)
            except Exception:
                pass
        return True
    if not sub_ok and prop(DEV, "org.bluez.Device1", "ServicesResolved"):
        try:
            call(BTN, "org.bluez.GattCharacteristic1", "StartNotify")
            sub_ok = True
            log("subscribed to button")
            try: call(BATT, "org.bluez.GattCharacteristic1", "StartNotify")
            except Exception: pass
        except Exception as e:
            if "In Progress" in str(e) or "Already" in str(e):
                sub_ok = True
            else:
                log("subscribe failed", str(e)[-80:])
    return True


bus.signal_subscribe("org.bluez", "org.freedesktop.DBus.Properties", "PropertiesChanged", None, None, 0, on_props)
log("spen-air starting for", MAC)
tick()
GLib.timeout_add_seconds(2, tick)
GLib.MainLoop().run()
