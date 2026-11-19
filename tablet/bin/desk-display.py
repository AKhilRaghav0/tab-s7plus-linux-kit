#!/usr/bin/env python3
"""Always-on desk display for the Tab S7+ (Droidian/Phosh).
Shows a big clock, date, battery/charging, Wi-Fi, CPU temp, weather and server pings.
After 23:00 and before 07:00 it switches to a dim night style (AMOLED-friendly).
Tap anywhere 3 times quickly to exit."""
import gi, subprocess, threading, time, datetime, json, urllib.request, os
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gdk

def _load_servers():
    """~/.config/desk-display/servers : one "Name host" per line (host = IP or hostname)."""
    f = os.path.expanduser("~/.config/desk-display/servers")
    try:
        return [tuple(l.split(None, 1)) for l in open(f) if l.strip() and not l.startswith("#")]
    except OSError:
        return [("Router", "192.168.1.1"), ("Cloudflare", "1.1.1.1")]
SERVERS = _load_servers()
CITY = os.environ.get("DESK_CITY", "")   # empty = wttr.in auto-detects by IP

CSS = b"""
window { background: #000; }
.clock { font-size: 210px; font-weight: 200; color: #f2f2f2; }
.date  { font-size: 42px; color: #9aa0a6; }
.info  { font-size: 30px; color: #c8c8c8; }
.srv   { font-size: 26px; padding: 6px 18px; border-radius: 16px; background: #111; color: #ddd; }
.up    { color: #5fdc7a; } .down { color: #ff6b6b; }
.night .clock { color: #7a2a1a; } .night .date, .night .info, .night .srv { color: #4a2a20; }
"""

def sh(cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception: return ""

def read(p):
    try: return open(p).read().strip()
    except Exception: return ""

class Desk(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.deskdisplay")
        self.weather = "…"; self.srv = {}; self.taps = []

    def do_activate(self):
        prov = Gtk.CssProvider(); prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, 800)
        self.win = Gtk.ApplicationWindow(application=self, title="Desk Display")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.clock = Gtk.Label(css_classes=["clock"]); self.date = Gtk.Label(css_classes=["date"])
        self.info = Gtk.Label(css_classes=["info"]); self.wx = Gtk.Label(css_classes=["info"])
        self.srvbox = Gtk.Box(spacing=14, halign=Gtk.Align.CENTER, margin_top=24)
        self.srvlbl = {}
        for name, _ in SERVERS:
            l = Gtk.Label(label=f"● {name}", css_classes=["srv"]); self.srvbox.append(l); self.srvlbl[name] = l
        for w in (self.clock, self.date, self.wx, self.info, self.srvbox): box.append(w)
        self.win.set_child(box)
        g = Gtk.GestureClick(); g.connect("pressed", self.on_tap); self.win.add_controller(g)
        self.win.fullscreen(); self.win.present()
        self.tick(); GLib.timeout_add_seconds(1, self.tick); GLib.timeout_add_seconds(20, self.stats)
        self.stats()
        threading.Thread(target=self.bg, daemon=True).start()

    def on_tap(self, *a):
        now = time.time(); self.taps = [t for t in self.taps if now - t < 1.2] + [now]
        if len(self.taps) >= 3: self.quit()

    def tick(self):
        n = datetime.datetime.now()
        self.clock.set_label(n.strftime("%H:%M")); self.date.set_label(n.strftime("%A, %d %B"))
        night = n.hour >= 23 or n.hour < 7
        if night: self.win.add_css_class("night")
        else: self.win.remove_css_class("night")
        return True

    def stats(self):
        cap = read("/sys/class/power_supply/battery/capacity"); st = read("/sys/class/power_supply/battery/status")
        bolt = "⚡" if st in ("Charging", "Full") else "🔋"
        temp = read("/sys/class/thermal/thermal_zone0/temp")
        t = f"{int(temp)//1000}°C" if temp.isdigit() else "–"
        ssid = sh(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]).split("\n")
        ssid = next((s.split(":", 1)[1] for s in ssid if s.startswith("yes:")), "offline")
        self.info.set_label(f"{bolt} {cap}%   ·   📶 {ssid}   ·   🌡 {t}")
        self.wx.set_label(self.weather)
        for name, _ in SERVERS:
            ok = self.srv.get(name)
            l = self.srvlbl[name]; l.set_label(f"● {name}")
            l.remove_css_class("up"); l.remove_css_class("down")
            if ok is not None: l.add_css_class("up" if ok else "down")
        return True

    def bg(self):
        last_wx = 0
        while True:
            for name, ip in SERVERS:
                self.srv[name] = subprocess.run(["ping", "-c1", "-W2", ip], capture_output=True).returncode == 0
            if time.time() - last_wx > 1800:
                try:
                    with urllib.request.urlopen(f"https://wttr.in/{CITY}?format=%c+%t+%h", timeout=10) as r:
                        self.weather = f"{CITY}  {r.read().decode().strip()}".strip()
                    last_wx = time.time()
                except Exception: pass
            time.sleep(60)

Desk().run(None)
