#!/usr/bin/env python3
"""Drop-in replacement for Droidian's flashlightd on the Galaxy Tab S7+ (Qualcomm LEDs).

Phosh's torch quick-setting talks to org.droidian.Flashlightd (session bus):
  property Brightness (i), method SetBrightness(u)  -- yes, Phosh really mixes them.
On this tablet the rear LED only lights when a torch channel AND the switch are set.
"""
import gi; gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

LEDS = "/sys/class/leds/"
TORCH = ["led:torch_0", "led:torch_1"]
SWITCH = "led:switch_0"
LEVEL = 200          # of max 500; bright but not too hot
XML = """<node><interface name="org.droidian.Flashlightd">
  <property name="Brightness" type="i" access="readwrite"/>
  <method name="SetBrightness"><arg name="value" type="u" direction="in"/></method>
</interface></node>"""

state = {"b": 0}
conn_ref = {}


def write(name, val):
    try:
        with open(LEDS + name + "/brightness", "w") as f:
            f.write(str(val))
    except OSError as e:
        print("write", name, e, flush=True)


def apply(b):
    b = int(b)
    if b > 0:
        lvl = LEVEL if b <= 1 else min(b, 500)
        for t in TORCH: write(t, lvl)
        write(SWITCH, 1)
    else:
        write(SWITCH, 0)
        for t in TORCH: write(t, 0)
    state["b"] = b
    c = conn_ref.get("c")
    if c:
        c.emit_signal(None, "/org/droidian/Flashlightd", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                      GLib.Variant("(sa{sv}as)", ("org.droidian.Flashlightd", {"Brightness": GLib.Variant("i", b)}, [])))


def on_call(conn, sender, path, iface, method, params, inv):
    if method == "SetBrightness":
        apply(params.unpack()[0]); inv.return_value(None)


def get_prop(conn, sender, path, iface, prop):
    return GLib.Variant("i", state["b"])


def set_prop(conn, sender, path, iface, prop, value):
    apply(value.unpack()); return True


def on_bus(conn, name):
    conn_ref["c"] = conn
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object("/org/droidian/Flashlightd", node.interfaces[0], on_call, get_prop, set_prop)


apply(0)
Gio.bus_own_name(Gio.BusType.SESSION, "org.droidian.Flashlightd", Gio.BusNameOwnerFlags.REPLACE,
                 on_bus, None, lambda c, n: print("lost name", flush=True))
GLib.MainLoop().run()
