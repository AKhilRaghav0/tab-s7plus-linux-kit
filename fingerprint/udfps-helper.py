#!/usr/bin/env python3
"""UDFPS helper for Galaxy Tab S7+ (SM-T970) on Droidian.

droidian-fpd talks to the AOSP @2.1 fingerprint HAL. That works for capacitive sensors,
but the in-display optical sensor only scans after the Samsung SEH HAL receives
sehRequest(22 SEM_REQUEST_TOUCH_EVENT, 2 = finger down) and later (22, 1 = finger up).
This helper adds that missing piece.

While droidian-fpd is ENROLLING/IDENTIFYING/VERIFYING:
  - draw a white disc over the sensor (layer-shell overlay) at full brightness
  - watch sec_touchscreen; when a finger lands inside the sensor circle,
    wait ~80 ms for the light, then send seh(22, 2); when it lifts, send seh(22, 1).
Sensor: 876,2614 r=77 in native portrait px (from LineageOS ro.vendor.fingerprint.sensor_location).
"""
import os
os.environ.setdefault("GSK_RENDERER", "cairo")
import sys, re, time, threading, subprocess
import gi, evdev, gbinder
gi.require_version("Gtk", "4.0"); gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, GLib, Gdk, Gtk4LayerShell as LS

NX, NY, NR, NW, NH = 876, 2614, 77, 1752, 2800
HIT = NR + 45                      # touch tolerance (native px)
SCALE = 2
D = int(NR * 2 / SCALE) + 16       # disc diameter (logical px)
TOUCH_DEV = "/dev/input/event3"
IFACE = "vendor.samsung.hardware.biometrics.fingerprint@3.0::ISehBiometricsFingerprint"
TXN_SEH = int(os.environ.get("SEH_TXN", "11"))
LIGHT_MS = int(os.environ.get("FOD_LIGHT_MS", "90"))
UP_DEBOUNCE_MS = int(os.environ.get("FOD_UP_MS", "400"))
POWER = ("org.gnome.SettingsDaemon.Power", "/org/gnome/SettingsDaemon/Power",
         "org.gnome.SettingsDaemon.Power.Screen", "Brightness")

def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)

# ---- Samsung SEH HAL -------------------------------------------------------
class Seh:
    def __init__(self):
        sm = gbinder.ServiceManager("/dev/hwbinder", "hidl", "hidl")
        remote, st = sm.get_service_sync(IFACE + "/default")
        if not remote: raise RuntimeError(f"SEH service not found ({st})")
        self.cl = gbinder.Client(remote, IFACE)
    def req(self, cmd, param):
        r = self.cl.new_request(); r.append_int32(cmd); r.append_int32(param); r.append_hidl_string_vec([])
        reply, st = self.cl.transact_sync_reply(TXN_SEH, r)
        if reply is None: return None
        rd = reply.init_reader(); hs = rd.read_int32(); ret = rd.read_int32()
        return ret[1] if ret[0] else None

# ---- helpers ---------------------------------------------------------------
def busctl(*a): return subprocess.run(["busctl", "--user", *a], capture_output=True, text=True).stdout.strip()
def get_bright():
    out = busctl("get-property", *POWER).split()
    return int(out[1]) if len(out) == 2 else None
def set_bright(v): busctl("set-property", *POWER, "i", str(v))
def fpd_state():
    r = subprocess.run(["busctl", "--system", "call", "org.droidian.fingerprint", "/org/droidian/fingerprint",
                        "org.droidian.fingerprint", "GetState"], capture_output=True, text=True).stdout
    m = re.search(r'"(\w+)"', r); return m.group(1) if m else "UNKNOWN"
def transform():
    m = re.search(r"Transform:\s*(\S+)", subprocess.run(["wlr-randr"], capture_output=True, text=True).stdout)
    return m.group(1) if m else "normal"
def logical_center():
    px, py, W, H = NX / SCALE, NY / SCALE, NW / SCALE, NH / SCALE
    t = transform()
    if t == "normal":   px, py = py, W - px
    elif t == "180":    px, py = H - py, px
    elif t == "270":    px, py = W - px, H - py
    return px, py, t

# ---- overlay ---------------------------------------------------------------
class Overlay:
    def __init__(self, app):
        self.app = app; self.win = None; self.saved_b = None
    def show(self):
        if self.win: return
        px, py, t = logical_center()
        w = Gtk.ApplicationWindow(application=self.app); LS.init_for_window(w)
        LS.set_layer(w, LS.Layer.OVERLAY); LS.set_exclusive_zone(w, -1)
        LS.set_keyboard_mode(w, LS.KeyboardMode.NONE)
        for e in (LS.Edge.TOP, LS.Edge.LEFT): LS.set_anchor(w, e, True)
        LS.set_margin(w, LS.Edge.LEFT, max(0, int(px - D / 2))); LS.set_margin(w, LS.Edge.TOP, max(0, int(py - D / 2)))
        d = Gtk.DrawingArea(); d.set_content_width(D); d.set_content_height(D)
        def draw(area, cr, ww, hh, *_):
            cr.set_source_rgb(1, 1, 1); cr.arc(ww / 2, hh / 2, min(ww, hh) / 2, 0, 6.2832); cr.fill()
        d.set_draw_func(draw); w.set_child(d); w.set_default_size(D, D); w.present(); self.win = w
        self.saved_b = get_bright(); set_bright(100)
        log(f"overlay on (transform={t}, center={int(px)},{int(py)})")
    def hide(self):
        if not self.win: return
        self.win.destroy(); self.win = None
        if self.saved_b is not None: set_bright(self.saved_b)
        log("overlay off")

# ---- main ------------------------------------------------------------------
class Helper(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.udfpshelper")
        self.active = False; self.down = False; self.lock = threading.Lock()
        self.on_sensor = False; self.off_since = None
    def do_activate(self):
        css = Gtk.CssProvider(); css.load_from_data(b"window{background:transparent;}")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 800)
        self.hold()  # keep running with no windows
        self.ov = Overlay(self)
        self.seh = Seh(); log("SEH ping (6,0) ->", self.seh.req(6, 0))
        subprocess.run(["sudo", "-n", "sh", "-c", "echo fod_enable,1,1,0 > /sys/class/sec/tsp/cmd"], capture_output=True)
        GLib.timeout_add(400, self.poll_state)
        threading.Thread(target=self.touch_loop, daemon=True).start()
    def poll_state(self):
        st = fpd_state(); want = st in ("FPSTATE_ENROLLING", "FPSTATE_IDENTIFYING", "FPSTATE_VERIFYING")
        if want and not self.active: self.active = True; log("fpd", st); self.ov.show()
        elif not want and self.active:
            self.active = False; log("fpd", st)
            if self.down: self.finger_up()
            self.ov.hide()
        return True
    def finger_down(self):
        GLib.timeout_add(LIGHT_MS, lambda: (log("seh(22,2) finger down ->", self.seh.req(22, 2)), False)[1])
    def maybe_up(self):
        if self.down and not self.on_sensor and self.off_since and time.time() - self.off_since >= UP_DEBOUNCE_MS / 1000 - 0.02:
            self.down = False; self.off_since = None; self.send_up()
        elif self.down and not self.on_sensor:
            return True
        return False
    def send_up(self):
        log("seh(22,1) finger up ->", self.seh.req(22, 1))
    def finger_up(self):
        self.down = False; self.send_up()
    def touch_loop(self):
        dev = evdev.InputDevice(TOUCH_DEV)
        slots = {}; cur = 0
        for e in dev.read_loop():
            if e.type == evdev.ecodes.EV_ABS:
                if e.code == evdev.ecodes.ABS_MT_SLOT: cur = e.value
                elif e.code == evdev.ecodes.ABS_MT_TRACKING_ID:
                    if e.value == -1: slots.pop(cur, None)
                    else: slots[cur] = [None, None]
                elif e.code == evdev.ecodes.ABS_MT_POSITION_X: slots.setdefault(cur, [None, None])[0] = e.value
                elif e.code == evdev.ecodes.ABS_MT_POSITION_Y: slots.setdefault(cur, [None, None])[1] = e.value
            elif e.type == evdev.ecodes.EV_SYN and self.active:
                on = any(x is not None and y is not None and (x - NX) ** 2 + (y - NY) ** 2 <= HIT ** 2
                         for x, y in slots.values())
                self.on_sensor = on
                if on:
                    self.off_since = None
                    if not self.down:
                        self.down = True; GLib.idle_add(lambda: (self.finger_down(), False)[1])
                elif self.down and self.off_since is None:
                    self.off_since = time.time()
                    GLib.timeout_add(UP_DEBOUNCE_MS, self.maybe_up)

if __name__ == "__main__":
    Helper().run(None)
