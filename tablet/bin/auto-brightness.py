#!/usr/bin/env python3
"""Auto brightness for Phosh on the Galaxy Tab S7+ (Droidian).

Reads the ambient light sensor through iio-sensor-proxy, maps lux to a brightness percentage on a log
curve, eases towards it, and sets it through gnome-settings-daemon (org.gnome.SettingsDaemon.Power.Screen).
If you move the brightness slider yourself, it learns an offset ("I like it brighter/darker") and keeps it.
The sensor is released while the screen is locked/blank.
"""
import json, math, time
from pathlib import Path
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

STATE = Path.home() / ".config" / "auto-brightness.json"
MIN_PCT, MAX_PCT = 3, 100
STEP_MS = 60           # easing tick
HOLD_AFTER_USER = 8    # s to back off after a manual change


def curve(lux):
    # 0 lx -> 3 %, 10 -> 26 %, 100 -> 47 %, 1000 -> 69 %, 10k+ -> ~91-100 %
    return 3 + 22 * math.log10(1 + max(lux, 0))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Auto:
    def __init__(self):
        self.sys = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.ses = Gio.bus_get_sync(Gio.BusType.SESSION)
        try:
            self.offset = json.loads(STATE.read_text()).get("offset", 0.0)
        except Exception:
            self.offset = 0.0
        self.lux_s = None          # smoothed log-lux
        self.target = None
        self.current = None
        self.ours = None           # last value we wrote
        self.hold_until = 0
        self.claimed = False
        self.anim = None
        self.sensor = Gio.DBusProxy.new_sync(self.sys, 0, None, "net.hadess.SensorProxy",
                                             "/net/hadess/SensorProxy", "net.hadess.SensorProxy", None)
        self.sensor.connect("g-properties-changed", self.on_sensor)
        self.ses.signal_subscribe("org.gnome.SettingsDaemon.Power", "org.freedesktop.DBus.Properties",
                                  "PropertiesChanged", "/org/gnome/SettingsDaemon/Power", None, 0, self.on_power)
        self.ses.signal_subscribe(None, "org.gnome.ScreenSaver", "ActiveChanged", "/org/gnome/ScreenSaver",
                                  None, 0, lambda *a: self.set_active(not a[5].unpack()[0]))
        self.current = self.get_brightness()
        self.set_active(True)

    # --- brightness via gsd ---
    def get_brightness(self):
        try:
            v = self.ses.call_sync("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power",
                                   "org.freedesktop.DBus.Properties", "Get",
                                   GLib.Variant("(ss)", ("org.gnome.SettingsDaemon.Power.Screen", "Brightness")),
                                   None, 0, 2000, None)
            return v.unpack()[0]
        except Exception:
            return None

    def set_brightness(self, pct):
        pct = int(round(max(MIN_PCT, min(MAX_PCT, pct))))
        if pct == self.ours:
            return
        self.ours = pct
        try:
            self.ses.call_sync("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power",
                               "org.freedesktop.DBus.Properties", "Set",
                               GLib.Variant("(ssv)", ("org.gnome.SettingsDaemon.Power.Screen", "Brightness",
                                                      GLib.Variant("i", pct))), None, 0, 2000, None)
        except Exception as e:
            log("set failed", e)

    def on_power(self, conn, sender, path, iface, sig, params):
        i, changed, _ = params.unpack()
        if i != "org.gnome.SettingsDaemon.Power.Screen" or "Brightness" not in changed:
            return
        v = changed["Brightness"]
        if self.ours is not None and abs(v - self.ours) <= 1:
            return                                   # our own write echoing back
        if self.lux_s is None:
            return
        # the user moved the slider: learn how much brighter/darker they want it at this light level
        self.offset = max(-40, min(40, v - curve(10 ** self.lux_s - 1)))
        self.current = self.target = v
        self.ours = v
        self.hold_until = time.time() + HOLD_AFTER_USER
        try:
            STATE.write_text(json.dumps({"offset": round(self.offset, 1)}))
        except Exception:
            pass
        log(f"user set {v}% -> offset {self.offset:+.1f}")

    # --- sensor ---
    def set_active(self, on):
        try:
            if on and not self.claimed:
                self.sensor.call_sync("ClaimLight", None, 0, 2000, None); self.claimed = True
                log("sensor on"); self.lux_s = None; self.on_sensor()
            elif not on and self.claimed:
                self.sensor.call_sync("ReleaseLight", None, 0, 2000, None); self.claimed = False
                log("sensor off (screen locked)")
        except Exception as e:
            log("sensor", e)

    def on_sensor(self, *a):
        v = self.sensor.get_cached_property("LightLevel")
        if v is None or not self.claimed:
            return
        lux = v.unpack()
        l = math.log10(1 + lux)
        # fast when getting brighter, slower when getting darker (avoids flicker from shadows)
        if self.lux_s is None:
            self.lux_s = l
        else:
            k = 0.5 if l > self.lux_s else 0.2
            self.lux_s += k * (l - self.lux_s)
        if time.time() < self.hold_until:
            return
        t = curve(10 ** self.lux_s - 1) + self.offset
        if self.current is None:
            self.current = self.get_brightness() or t
        if abs(t - self.current) < 3 and self.target is not None:
            return                                   # dead band: ignore tiny changes
        self.target = t
        if self.anim is None:
            self.anim = GLib.timeout_add(STEP_MS, self.step)

    def step(self):
        if self.target is None or time.time() < self.hold_until:
            self.anim = None; return False
        d = self.target - self.current
        if abs(d) < 0.6:
            self.current = self.target; self.set_brightness(self.current); self.anim = None; return False
        self.current += max(-2.5, min(2.5, d * 0.25))
        self.set_brightness(self.current)
        return True


if __name__ == "__main__":
    a = Auto()
    log(f"auto-brightness running, offset {a.offset:+.1f}")
    GLib.MainLoop().run()
