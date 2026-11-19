#!/usr/bin/env python3
"""Pick up to wake (like One UI) for the Galaxy Tab S7+ on Droidian.

The sensor hub's low-power "Pick Up Gesture" wake-up sensor is exposed by our sensorfw plugin
(libhybrispickupadaptor) in the unused proximity slot: every pick-up toggles ProximityNear on
net.hadess.SensorProxy. This daemon only claims it while the panel is off (and the Book Cover is
open), and turns the panel on when it fires.
"""
import time
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

HALL = "/sys/class/sec/hall_ic/hall_detect"
COOLDOWN = 3.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class PickupWake:
    def __init__(self):
        self.sys = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        self.ses = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.claimed = False
        self.last = 0
        self.prev = None
        self.sensor = Gio.DBusProxy.new_sync(self.sys, 0, None, "net.hadess.SensorProxy",
                                             "/net/hadess/SensorProxy", "net.hadess.SensorProxy", None)
        self.sensor.connect("g-properties-changed", self.on_sensor)
        self.ses.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  "/org/gnome/Mutter/DisplayConfig", None, 0, lambda *a: self.update())
        GLib.timeout_add_seconds(5, self.update)          # safety net (signals can be missed)
        self.update()

    def psm(self):
        try:
            v = self.ses.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                                   "org.freedesktop.DBus.Properties", "Get",
                                   GLib.Variant("(ss)", ("org.gnome.Mutter.DisplayConfig", "PowerSaveMode")),
                                   None, 0, 1000, None)
            return v.unpack()[0]
        except Exception:
            return 0

    def cover_closed(self):
        try:
            return open(HALL).read().strip() == "CLOSE"
        except Exception:
            return False

    def update(self):
        want = self.psm() != 0 and not self.cover_closed()   # panel off, cover open
        try:
            if want and not self.claimed:
                self.sensor.call_sync("ClaimProximity", None, 0, 3000, None)
                self.claimed = True
                v = self.sensor.get_cached_property("ProximityNear")
                self.prev = v.unpack() if v is not None else None
                log("armed")
            elif not want and self.claimed:
                self.sensor.call_sync("ReleaseProximity", None, 0, 3000, None)
                self.claimed = False
                log("disarmed")
        except Exception as e:
            log("sensor:", e)
        return True

    def on_sensor(self, proxy, changed, invalidated):
        if "ProximityNear" not in changed.keys() or not self.claimed:
            return
        v = changed["ProximityNear"]
        if v == self.prev:
            return
        self.prev = v
        now = time.monotonic()
        if now - self.last < COOLDOWN or self.cover_closed():
            return
        self.last = now
        log("picked up -> wake")
        try:
            self.ses.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                               "org.freedesktop.DBus.Properties", "Set",
                               GLib.Variant("(ssv)", ("org.gnome.Mutter.DisplayConfig", "PowerSaveMode",
                                                      GLib.Variant("i", 0))), None, 0, 2000, None)
        except Exception as e:
            log("wake failed:", e)
        GLib.timeout_add(500, self.update)


if __name__ == "__main__":
    PickupWake()
    log("pickup-wake running")
    GLib.MainLoop().run()
