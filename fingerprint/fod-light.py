#!/usr/bin/env python3
"""Draw a bright white disc over the in-display fingerprint sensor for N seconds.
usage: fod-light.py [seconds] [flip]   (flip=1 puts it on the opposite edge)"""
import os; os.environ.setdefault("GSK_RENDERER", "cairo")
import sys, re, subprocess, gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gtk4LayerShell as LS
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 10
FLIP = len(sys.argv) > 2 and sys.argv[2] == "1"
NX, NY, NR, NW, NH = 876, 2614, 77, 1752, 2800      # native portrait px (LineageOS sensor_location)
SCALE = 2; D = int(NR * 2 / SCALE) + 16               # disc diameter in logical px (a bit bigger)
t = re.search(r"Transform:\s*(\S+)", subprocess.run(["wlr-randr"], capture_output=True, text=True).stdout)
t = t.group(1) if t else "normal"
px, py = NX / SCALE, NY / SCALE                        # portrait logical
W, H = NW / SCALE, NH / SCALE
if FLIP: px, py = W - px, H - py
if t in ("normal", "180"):                             # landscape: rotate portrait coords
    px, py = (py, W - px) if t == "normal" else (H - py, px)
css = Gtk.CssProvider(); css.load_from_data(b"window{background:transparent;} .disc{background:#fff;border-radius:999px;}")
def act(app):
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, 800)
    w = Gtk.ApplicationWindow(application=app); LS.init_for_window(w)
    LS.set_layer(w, LS.Layer.OVERLAY); LS.set_exclusive_zone(w, -1)
    for e in (LS.Edge.TOP, LS.Edge.LEFT, LS.Edge.RIGHT, LS.Edge.BOTTOM): LS.set_anchor(w, e, True)
    d = Gtk.DrawingArea(); d.set_can_target(False)
    def draw(area, cr, ww, hh, *_):
        cr.set_source_rgba(0, 0, 0, 0); cr.paint()
        cr.set_source_rgb(1, 1, 1); cr.arc(px, py, D / 2, 0, 6.2832); cr.fill()
    d.set_draw_func(draw); w.set_child(d); w.set_can_target(False); w.present()
    print(f"transform={t} disc at ({int(px)},{int(py)}) d={D}", flush=True)
    GLib.timeout_add(int(SECS * 1000), app.quit)
a = Gtk.Application(application_id="local.fodlight"); a.connect("activate", act); a.run(None)
