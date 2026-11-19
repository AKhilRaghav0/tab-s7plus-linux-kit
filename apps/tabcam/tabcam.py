#!/usr/bin/env python3
"""TabCam: a camera app for the Galaxy Tab S7+ on Droidian (GTK4 + gst-droid).

Cameras (Android HAL ids): 0 rear main 13 MP, 2 rear ultra-wide 5 MP, 1 front 8 MP (wide), 3 front (crop).
Modes: Photo, Video, Night (stacked frames), Pro (WB / EV / focus).
"""
import ctypes, datetime, math, os, subprocess, threading, time
from pathlib import Path

import gi
# GTK's GL renderers draw nothing on libhybris; the cairo renderer works
os.environ.setdefault("GSK_RENDERER", "cairo")
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0"); gi.require_version("Gst", "1.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gst, Gtk

Gst.init(None)

APP_DIR = Path(os.path.realpath(__file__)).parent
ICONS = APP_DIR / "icons"
PICS = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or Path.home() / "Pictures") / "Camera"
VIDS = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS) or Path.home() / "Videos") / "Camera"
CONF = Path.home() / ".config" / "tabcam.ini"

# id -> label, facing, max 4:3 photo size
CAMS = {
    0: dict(name="Main", front=False, photo=(4128, 3096)),
    2: dict(name="Ultra-wide", front=False, photo=(2576, 1932)),
    1: dict(name="Front wide", front=True, photo=(3264, 2448)),
    3: dict(name="Front", front=True, photo=(2608, 1956)),
}
LENSES = {False: [("0.6", 2, 1.0), ("1×", 0, 1.0), ("2×", 0, 2.0), ("4×", 0, 4.0)],
          True: [("1×", 3, 1.0), ("Wide", 1, 1.0)]}
MODES = ["Night", "Photo", "Video", "Pro"]
WB = [("Auto", 0), ("Day", 1), ("Cloudy", 2), ("Sunset", 3), ("Tungsten", 4), ("Fluor.", 5)]
FOCUS = [("Auto", 6), ("Macro", 1), ("Infinity", 3)]   # continuous-normal, macro, infinity

CSS = b"""
window, .bg { background: #000; }
.panel { background: rgba(0,0,0,0.45); border-radius: 28px; padding: 10px; }
.chip { background: rgba(255,255,255,0.12); color: #fff; border-radius: 999px; min-height: 40px; min-width: 40px;
        padding: 0 12px; font-weight: 700; border: none; box-shadow: none; }
.chip:checked, .chip.on { background: #ffd60a; color: #000; }
.iconbtn { background: transparent; border: none; box-shadow: none; padding: 8px; border-radius: 999px; }
.iconbtn:hover { background: rgba(255,255,255,0.12); }
.iconbtn.on { background: rgba(255,214,10,0.25); }
.mode { color: rgba(255,255,255,0.65); background: transparent; border: none; box-shadow: none; font-weight: 700;
        letter-spacing: 1px; padding: 6px 4px; }
.mode.on { color: #ffd60a; }
.shutter { background: transparent; border: none; box-shadow: none; padding: 0; }
.thumb { border-radius: 14px; border: 2px solid rgba(255,255,255,0.8); }
.rec { color: #fff; background: #ff3b30; border-radius: 999px; padding: 4px 14px; font-weight: 800; font-feature-settings: "tnum"; }
.toast { color: #fff; background: rgba(0,0,0,0.7); border-radius: 999px; padding: 8px 18px; }
.big { color: #fff; font-size: 96px; font-weight: 800; }
.label { color: rgba(255,255,255,0.85); font-weight: 700; font-size: 12px; }
scale trough { background: rgba(255,255,255,0.25); min-height: 4px; }
scale highlight { background: #ffd60a; }
scale slider { background: #fff; min-width: 22px; min-height: 22px; }
"""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------- icons (Codex-made SVGs use currentColor; render them white) ----------
_icon_cache = {}


def icon(name, px=26, color="#ffffff"):
    key = (name, px, color)
    if key not in _icon_cache:
        svg = (ICONS / f"{name}.svg").read_text().replace("currentColor", color)
        scale = 3
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(svg.encode()))
        pb = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, px * scale, px * scale, True, None)
        _icon_cache[key] = Gdk.Texture.new_for_pixbuf(pb)
    img = Gtk.Image.new_from_paintable(_icon_cache[key])
    img.set_pixel_size(px)
    return img


def icon_button(name, tip, cb, px=26):
    b = Gtk.Button(child=icon(name, px), tooltip_text=tip)
    b.add_css_class("iconbtn")
    b.connect("clicked", lambda *_: cb())
    return b


# ---------- GstPhotography autofocus via ctypes (no typelib for it) ----------
_photo_lib = None


def gst_autofocus(element, on=True):
    global _photo_lib
    try:
        if _photo_lib is None:
            _photo_lib = ctypes.CDLL("libgstphotography-1.0.so.0")
            _photo_lib.gst_photography_set_autofocus.argtypes = [ctypes.c_void_p, ctypes.c_int]
        ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
        ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
        ptr = ctypes.pythonapi.PyCapsule_GetPointer(element.__gpointer__, None)
        _photo_lib.gst_photography_set_autofocus(ptr, 1 if on else 0)
    except Exception as e:
        log("autofocus unavailable:", e)


# ---------- device orientation (iio-sensor-proxy) ----------
class Orientation:
    def __init__(self, on_change):
        self.value = "normal"
        self.on_change = on_change
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM, 0, None, "net.hadess.SensorProxy",
                                                         "/net/hadess/SensorProxy", "net.hadess.SensorProxy", None)
            self.proxy.call_sync("ClaimAccelerometer", None, 0, 2000, None)
            self.proxy.connect("g-properties-changed", self._changed)
            self._changed()
        except Exception as e:
            log("no orientation sensor:", e)
            self.proxy = None

    def _changed(self, *a):
        v = self.proxy.get_cached_property("AccelerometerOrientation") if self.proxy else None
        if v is not None and v.unpack() != "undefined" and v.unpack() != self.value:
            self.value = v.unpack()
            self.on_change(self.value)

    def release(self):
        if self.proxy:
            try: self.proxy.call_sync("ReleaseAccelerometer", None, 0, 1000, None)
            except Exception: pass


# rotation (degrees clockwise) to make a sensor frame upright, per device orientation
ROT = {"normal": 0, "bottom-up": 180, "left-up": 90, "right-up": 270}
FLIP_DIR = {0: "identity", 90: "90r", 180: "180", 270: "90l"}


class Camera:
    """Owns the droidcamsrc preview pipeline and the (optional) recording pipeline."""

    def __init__(self, app):
        self.app = app
        self.pipe = None
        self.cam = None
        self.rec = None
        self.rec_src = None
        self.recording = False
        self.vf = (1920, 1440)
        self.night_frames = None

    # --- preview pipeline ---
    def start(self, cam_id, video):
        """Blocking (call from a worker thread). Returns True once the first preview frame arrives."""
        self.stop()
        cands = [(1920, 1080), (1280, 720), (1440, 1080)] if video else [(1920, 1440), (1440, 1080), (1280, 960), (1088, 1088)]
        iw, ih = CAMS[cam_id]["photo"]
        flip = "horiz" if CAMS[cam_id]["front"] else "identity"
        for vw, vh in cands:
            pw = 1280
            ph = round(pw * vh / vw / 2) * 2
            desc = (
                f"droidcamsrc name=cam camera-device={cam_id} mode=1 "
                f"cam.vfsrc ! video/x-raw,format=NV21,width={vw},height={vh} ! tee name=t "
                f"t. ! queue leaky=downstream max-size-buffers=1 ! videoscale ! video/x-raw,width={pw},height={ph} "
                f"! videoconvert n-threads=2 ! videoflip video-direction={flip} ! videoflip name=rot video-direction=identity "
                f"! video/x-raw,format=RGB ! appsink name=pv emit-signals=true sync=false async=false max-buffers=1 drop=true "
                f"t. ! queue leaky=downstream max-size-buffers=2 ! appsink name=rv emit-signals=true sync=false async=false max-buffers=2 drop=true "
                f"cam.imgsrc ! image/jpeg,width={iw},height={ih} ! queue ! appsink name=img emit-signals=true sync=false async=false"
            )
            try:
                p = Gst.parse_launch(desc)
            except GLib.Error as e:
                log("pipeline parse failed:", e.message); return False
            self.first_frame = threading.Event()
            p.get_by_name("pv").connect("new-sample", self._on_preview)
            p.get_by_name("rv").connect("new-sample", self._on_raw)
            p.get_by_name("img").connect("new-sample", self._on_image)
            p.set_state(Gst.State.PLAYING)
            bus, err, t0 = p.get_bus(), None, time.time()
            while time.time() - t0 < 5 and not self.first_frame.is_set():
                m = bus.timed_pop_filtered(50 * Gst.MSECOND, Gst.MessageType.ERROR)
                if m:
                    err = m; break
            if err is None and self.first_frame.is_set():
                self.pipe, self.cam, self.vf = p, p.get_by_name("cam"), (vw, vh)
                bus.add_signal_watch(); bus.connect("message", self._on_msg)
                log(f"camera {cam_id} up in {time.time() - t0:.2f}s, viewfinder {vw}x{vh}, photo {iw}x{ih}")
                return True
            log(f"camera {cam_id} {vw}x{vh} failed: {err.parse_error()[0].message if err else 'no frames'}")
            p.set_state(Gst.State.NULL)
        return False

    def stop(self):
        if self.recording:
            self.stop_recording()
        if self.pipe:
            self.pipe.get_bus().remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
        self.pipe = self.cam = None

    def set_rotation(self, deg):
        if self.pipe:
            self.pipe.get_by_name("rot").set_property("video-direction", FLIP_DIR[deg])

    def _on_msg(self, bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            e = msg.parse_error()[0].message
            log("camera error:", e)
            GLib.idle_add(self.app.toast, f"Camera error: {e}")

    # --- frames ---
    def _on_preview(self, sink):
        s = sink.emit("pull-sample")
        st = s.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        buf = s.get_buffer()
        self.latest = (w, h, buf.extract_dup(0, buf.get_size()))
        if getattr(self, "first_frame", None) is not None:
            self.first_frame.set()
        self.nframes = getattr(self, "nframes", 0) + 1
        if self.nframes % 90 == 1:
            log("preview frames", self.nframes, f"{w}x{h}")
        if not getattr(self, "pending", False):      # only one frame queued for the UI at a time
            self.pending = True
            GLib.idle_add(self._present)
        return Gst.FlowReturn.OK

    def _present(self):
        self.pending = False
        f, self.latest = getattr(self, "latest", None), None
        if f:
            self.app.show_frame(*f)
        return False

    def _on_raw(self, sink):
        s = sink.emit("pull-sample")
        if self.recording and self.rec_src is not None:
            b = s.get_buffer().copy()
            b.pts = self.rec_clock.get_time() - self.rec.get_base_time()
            b.dts = b.duration = Gst.CLOCK_TIME_NONE
            self.rec_src.emit("push-buffer", b)
        if self.night_frames is not None and len(self.night_frames) < self.night_n:
            buf = s.get_buffer()
            self.night_frames.append(buf.extract_dup(0, buf.get_size()))
            if len(self.night_frames) == self.night_n:
                frames, self.night_frames = self.night_frames, None
                threading.Thread(target=self.app.save_night, args=(frames, *self.vf), daemon=True).start()
        return Gst.FlowReturn.OK

    def _on_image(self, sink):
        s = sink.emit("pull-sample")
        buf = s.get_buffer()
        data = buf.extract_dup(0, buf.get_size())
        threading.Thread(target=self.app.save_photo, args=(data,), daemon=True).start()
        return Gst.FlowReturn.OK

    # --- actions ---
    def capture(self):
        if self.cam:
            self.cam.emit("start-capture")

    def night(self, n=8):
        self.night_n = n
        self.night_frames = []

    def zoom(self, z):
        if self.cam:
            self.cam.set_property("zoom", max(1.0, min(10.0, z)))

    def setp(self, name, value):
        if self.cam:
            try:
                self.cam.set_property(name, value)
            except Exception as e:
                log("set", name, "failed:", e)

    def focus_at(self, fx, fy):
        """fx, fy in 0..1 of the (unrotated, unmirrored) sensor frame."""
        if not self.cam:
            return
        vw, vh = self.vf
        rw, rh = int(vw * 0.12), int(vh * 0.12)
        x = int(min(max(fx * vw - rw / 2, 0), vw - rw)); y = int(min(max(fy * vh - rh / 2, 0), vh - rh))
        txt = (f"regions-of-interest, frame-width=(uint){vw}, frame-height=(uint){vh}, "
               f"regions={{ [region-of-interest, region-x=(uint){x}, region-y=(uint){y}, "
               f"region-w=(uint){rw}, region-h=(uint){rh}, region-priority=(uint)1] }}")
        try:
            s = Gst.Structure.from_string(txt)[0]
            self.cam.send_event(Gst.Event.new_custom(Gst.EventType.CUSTOM_UPSTREAM, s))
        except Exception as e:
            log("focus region failed:", e)
        gst_autofocus(self.cam, True)

    # --- recording ---
    def start_recording(self, path, rot):
        vw, vh = self.vf
        flip = FLIP_DIR[rot]
        mirror = "! videoflip video-direction=horiz " if CAMS[self.app.cam_id]["front"] else ""
        desc = (
            f"appsrc name=src is-live=true format=time caps=video/x-raw,format=NV21,width={vw},height={vh},framerate=30/1 "
            f"! queue max-size-buffers=0 max-size-bytes=0 max-size-time=3000000000 ! videoconvert n-threads=3 {mirror}"
            f"! videoflip video-direction={flip} ! video/x-raw,format=I420 "
            f"! x264enc speed-preset=ultrafast tune=zerolatency bitrate=12000 threads=4 key-int-max=60 ! h264parse "
            f"! queue ! mp4mux name=mux faststart=true ! filesink location={path} "
            f"pulsesrc provide-clock=false do-timestamp=true ! audio/x-raw,rate=48000,channels=2 ! queue "
            f"! audioconvert ! voaacenc bitrate=160000 ! aacparse ! queue ! mux."
        )
        self.rec = Gst.parse_launch(desc)
        self.rec_clock = Gst.SystemClock.obtain()
        self.rec.use_clock(self.rec_clock)
        self.rec.set_start_time(Gst.CLOCK_TIME_NONE)
        self.rec.set_base_time(self.rec_clock.get_time())
        self.rec_src = self.rec.get_by_name("src")
        self.rec.set_state(Gst.State.PLAYING)
        self.recording = True

    def stop_recording(self):
        if not self.rec:
            return
        self.recording = False
        rec, self.rec, self.rec_src = self.rec, None, None
        rec.send_event(Gst.Event.new_eos())

        def finish():
            rec.get_bus().timed_pop_filtered(10 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            rec.set_state(Gst.State.NULL)
        threading.Thread(target=finish, daemon=True).start()


class TabCam(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.tabs7.TabCam", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.cam_id, self.zoom_level, self.mode = 0, 1.0, "Photo"
        self.flash, self.timer, self.grid_on, self.wb, self.focus = 1, 0, False, 0, 6   # flash 1=off
        self.ev = 0.0
        self.rot = 0
        self.last_file = None
        self.rec_start = 0
        self.busy = False

    # ---------- UI ----------
    def do_activate(self):
        prov = Gtk.CssProvider(); prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, 800)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        PICS.mkdir(parents=True, exist_ok=True); VIDS.mkdir(parents=True, exist_ok=True)

        self.win = Gtk.ApplicationWindow(application=self, title="Camera")
        self.win.set_default_size(1400, 900)
        self.win.connect("close-request", self.on_close)

        overlay = Gtk.Overlay(); overlay.add_css_class("bg")
        self.win.set_child(overlay)

        self.picture = Gtk.Picture(can_shrink=True, hexpand=True, vexpand=True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        overlay.set_child(self.picture)

        self.grid_area = Gtk.DrawingArea(can_target=False); self.grid_area.set_draw_func(self.draw_grid)
        overlay.add_overlay(self.grid_area)
        self.focus_area = Gtk.DrawingArea(can_target=False); self.focus_area.set_draw_func(self.draw_focus)
        overlay.add_overlay(self.focus_area)
        self.focus_pt, self.focus_t = None, 0

        # tap to focus, pinch to zoom
        tap = Gtk.GestureClick(); tap.connect("released", self.on_tap); self.picture.add_controller(tap)
        pinch = Gtk.GestureZoom(); pinch.connect("begin", lambda *a: setattr(self, "_z0", self.zoom_level))
        pinch.connect("scale-changed", lambda g, s: self.set_zoom(self._z0 * s, from_pinch=True))
        self.picture.add_controller(pinch)

        # top-left: quick toggles
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.START, valign=Gtk.Align.START,
                      margin_top=18, margin_start=18)
        top.add_css_class("panel")
        self.flash_btn = icon_button("flash-off", "Flash", self.cycle_flash)
        self.timer_btn = icon_button("timer-off", "Timer", self.cycle_timer)
        self.grid_btn = icon_button("grid", "Grid", self.toggle_grid)
        for b in (self.flash_btn, self.timer_btn, self.grid_btn):
            top.append(b)
        overlay.add_overlay(top)

        # recording badge / countdown / toast
        self.rec_label = Gtk.Label(halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margin_top=22, visible=False)
        self.rec_label.add_css_class("rec"); overlay.add_overlay(self.rec_label)
        self.count_label = Gtk.Label(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, visible=False)
        self.count_label.add_css_class("big"); overlay.add_overlay(self.count_label)
        self.toast_label = Gtk.Label(halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=30, visible=False)
        self.toast_label.add_css_class("toast"); overlay.add_overlay(self.toast_label)
        self.flash_overlay = Gtk.Box(visible=False, can_target=False); self.flash_overlay.add_css_class("bg")
        overlay.add_overlay(self.flash_overlay)

        # lens chips (bottom centre)
        self.lens_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=24)
        self.lens_box.add_css_class("panel")
        overlay.add_overlay(self.lens_box)

        # Pro panel (left, vertical)
        self.pro = self.build_pro()
        overlay.add_overlay(self.pro)

        # right column: gallery / modes / shutter / switch
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, halign=Gtk.Align.END, valign=Gtk.Align.CENTER,
                        margin_end=22)
        right.add_css_class("panel")
        self.switch_btn = icon_button("switch-camera", "Switch camera", self.switch_camera, px=30)
        right.append(self.switch_btn)
        self.mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.mode_btns = {}
        for m in MODES:
            b = Gtk.Button(label=m.upper()); b.add_css_class("mode")
            b.connect("clicked", lambda _b, m=m: self.set_mode(m))
            self.mode_btns[m] = b; self.mode_box.append(b)
        right.append(self.mode_box)
        self.shutter = Gtk.Button(); self.shutter.add_css_class("shutter")
        self.shutter.connect("clicked", lambda *_: self.on_shutter())
        right.append(self.shutter)
        self.thumb = Gtk.Picture(can_shrink=True); self.thumb.set_size_request(64, 64)
        self.thumb.set_content_fit(Gtk.ContentFit.COVER); self.thumb.add_css_class("thumb")
        tb = Gtk.Button(child=self.thumb, tooltip_text="Open last"); tb.add_css_class("iconbtn")
        tb.connect("clicked", lambda *_: self.open_last())
        right.append(tb)
        overlay.add_overlay(right)

        # keys: space/enter/volume = shutter
        keys = Gtk.EventControllerKey(); keys.connect("key-pressed", self.on_key); self.win.add_controller(keys)

        self.camera = Camera(self)
        self.orient = Orientation(self.on_orientation)
        self.on_orientation(self.orient.value)
        self.load_last_thumb()
        self.win.present()
        GLib.idle_add(self.restart_camera)
        GLib.timeout_add(500, self.tick)

    def build_pro(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.START, valign=Gtk.Align.CENTER,
                      margin_start=18, visible=False)
        box.add_css_class("panel"); box.set_size_request(250, -1)

        def title(t):
            l = Gtk.Label(label=t, xalign=0); l.add_css_class("label"); return l

        box.append(title("EXPOSURE (EV)"))
        self.ev_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -2, 2, 0.5)
        self.ev_scale.set_value(0); self.ev_scale.set_draw_value(True)
        self.ev_scale.connect("value-changed", lambda s: self.set_ev(s.get_value()))
        box.append(self.ev_scale)

        box.append(title("WHITE BALANCE"))
        wb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=4, row_spacing=4)
        self.wb_btns = []
        for name, val in WB:
            b = Gtk.ToggleButton(label=name); b.add_css_class("chip"); b.set_active(val == 0)
            b.connect("toggled", lambda b, v=val: b.get_active() and self.set_wb(v))
            if self.wb_btns: b.set_group(self.wb_btns[0])
            self.wb_btns.append(b); wb.append(b)
        box.append(wb)

        box.append(title("FOCUS (main camera)"))
        fb = Gtk.Box(spacing=4); self.focus_btns = []
        for name, val in FOCUS:
            b = Gtk.ToggleButton(label=name); b.add_css_class("chip"); b.set_active(val == 6)
            b.connect("toggled", lambda b, v=val: b.get_active() and self.set_focus(v))
            if self.focus_btns: b.set_group(self.focus_btns[0])
            self.focus_btns.append(b); fb.append(b)
        box.append(fb)
        return box

    # ---------- camera control ----------
    def restart_camera(self):
        """Switch cameras off the UI thread so the interface never freezes."""
        if getattr(self, "switching", False):
            self._again = True
            return False
        self.switching, self._again = True, False
        self.picture.set_opacity(0.35)
        cam_id, video = self.cam_id, self.mode == "Video"

        def work():
            ok = self.camera.start(cam_id, video)
            GLib.idle_add(done, ok)

        def done(ok):
            self.switching = False
            self.picture.set_opacity(1.0)
            if self._again or cam_id != self.cam_id or video != (self.mode == "Video"):
                return self.restart_camera()      # user tapped again meanwhile
            if not ok:
                self.toast("Could not start camera")
                return False
            self.camera.set_rotation(self.rot)
            self.apply_settings()
            self.refresh_ui()
            return False

        threading.Thread(target=work, daemon=True).start()
        self.refresh_ui()
        return False

    def apply_settings(self):
        c = self.camera
        c.zoom(self.zoom_level)
        c.setp("flash-mode", self.flash if self.cam_id == 0 else 1)
        c.setp("video-torch", False)
        c.setp("white-balance-mode", self.wb)
        c.setp("ev-compensation", self.ev + (1.0 if self.mode == "Night" else 0.0))
        if self.cam_id == 0:
            c.setp("focus-mode", self.focus)
        c.setp("jpeg-quality", 95)

    def refresh_ui(self):
        front = CAMS[self.cam_id]["front"]
        # lens chips
        child = self.lens_box.get_first_child()
        while child:
            nxt = child.get_next_sibling(); self.lens_box.remove(child); child = nxt
        for label, cid, z in LENSES[front]:
            b = Gtk.Button(label=label); b.add_css_class("chip")
            if cid == self.cam_id and abs(z - self.zoom_level) < 0.05:
                b.add_css_class("on")
            b.connect("clicked", lambda _b, cid=cid, z=z: self.pick_lens(cid, z))
            self.lens_box.append(b)
        if self.zoom_level > 1.0 and all(abs(z - self.zoom_level) > 0.05 for _, c, z in LENSES[front] if c == self.cam_id):
            l = Gtk.Label(label=f"{self.zoom_level:.1f}×"); l.add_css_class("label"); self.lens_box.append(l)
        # modes
        for m, b in self.mode_btns.items():
            (b.add_css_class if m == self.mode else b.remove_css_class)("on")
        self.pro.set_visible(self.mode == "Pro")
        # shutter look
        name = "stop" if self.camera.recording else ("record" if self.mode == "Video" else "shutter")
        self.shutter.set_child(icon(name, 76))
        # flash icon (main camera only)
        self.flash_btn.set_sensitive(self.cam_id == 0)
        fl = {0: "flash-auto", 1: "flash-off", 2: "flash-on", 9: "torch"}[self.flash]
        self.flash_btn.set_child(icon(fl if self.cam_id == 0 else "flash-off"))
        self.timer_btn.set_child(icon({0: "timer-off", 3: "timer-3", 10: "timer-10"}[self.timer]))
        (self.grid_btn.add_css_class if self.grid_on else self.grid_btn.remove_css_class)("on")
        self.switch_btn.set_sensitive(not self.camera.recording)

    def pick_lens(self, cid, z):
        if self.camera.recording and cid != self.cam_id:
            return
        self.zoom_level = z
        if cid != self.cam_id:
            self.cam_id = cid
            self.restart_camera()
        else:
            self.camera.zoom(z); self.refresh_ui()

    def set_zoom(self, z, from_pinch=False):
        self.zoom_level = max(1.0, min(10.0, z))
        self.camera.zoom(self.zoom_level)
        if not from_pinch or int(self.zoom_level * 10) % 2 == 0:
            self.refresh_ui()

    def switch_camera(self):
        front = not CAMS[self.cam_id]["front"]
        self.cam_id = 3 if front else 0
        self.zoom_level = 1.0
        self.restart_camera()

    def set_mode(self, m):
        if self.camera.recording or m == self.mode:
            return
        was_video = self.mode == "Video"
        self.mode = m
        if (m == "Video") != was_video:
            self.restart_camera()
        else:
            self.apply_settings(); self.refresh_ui()
        if m == "Night":
            self.toast("Night: hold still, 8 frames are stacked")

    def cycle_flash(self):
        order = [1, 0, 2, 9]          # off, auto, on, torch
        self.flash = order[(order.index(self.flash) + 1) % len(order)]
        if self.flash == 9:
            self.camera.setp("flash-mode", 1); self.camera.setp("video-torch", True)
        else:
            self.camera.setp("video-torch", False); self.camera.setp("flash-mode", self.flash)
        self.toast({1: "Flash off", 0: "Flash auto", 2: "Flash on", 9: "Torch"}[self.flash])
        self.refresh_ui()

    def cycle_timer(self):
        self.timer = {0: 3, 3: 10, 10: 0}[self.timer]
        self.toast("Timer off" if not self.timer else f"Timer {self.timer}s")
        self.refresh_ui()

    def toggle_grid(self):
        self.grid_on = not self.grid_on
        self.grid_area.queue_draw(); self.refresh_ui()

    def set_ev(self, v):
        self.ev = v; self.camera.setp("ev-compensation", v)

    def set_wb(self, v):
        self.wb = v; self.camera.setp("white-balance-mode", v)

    def set_focus(self, v):
        self.focus = v
        if self.cam_id == 0:
            self.camera.setp("focus-mode", v)

    # ---------- orientation ----------
    def on_orientation(self, value):
        self.rot = ROT.get(value, 0)
        if getattr(self, "camera", None):
            self.camera.set_rotation(self.rot)

    # ---------- shutter ----------
    def on_shutter(self):
        if self.mode == "Video":
            return self.toggle_recording()
        if self.busy:
            return
        if self.timer:
            self.busy = True
            self.countdown(self.timer)
        else:
            self.take()

    def countdown(self, n):
        if n == 0:
            self.count_label.set_visible(False); self.busy = False; self.take(); return False
        self.count_label.set_label(str(n)); self.count_label.set_visible(True)
        GLib.timeout_add(1000, self.countdown, n - 1)
        return False

    def take(self):
        self.flash_overlay.set_visible(True)
        GLib.timeout_add(90, lambda: self.flash_overlay.set_visible(False) or False)
        if self.mode == "Night":
            self.busy = True
            self.toast("Hold still…")
            self.camera.night(8)
        else:
            self.camera.capture()

    def toggle_recording(self):
        if self.camera.recording:
            self.camera.stop_recording()
            self.rec_label.set_visible(False)
            self.toast("Video saved")
            self.last_file = self.video_path
            GLib.timeout_add(1500, lambda: self.load_last_thumb() or False)
        else:
            self.video_path = VIDS / datetime.datetime.now().strftime("VID_%Y%m%d_%H%M%S.mp4")
            self.camera.start_recording(str(self.video_path), self.rot)
            self.rec_start = time.time()
            self.rec_label.set_visible(True)
        self.refresh_ui()

    def tick(self):
        if self.camera.recording:
            s = int(time.time() - self.rec_start)
            self.rec_label.set_label(f"● {s // 60:02d}:{s % 60:02d}")
        if self.focus_pt and time.time() - self.focus_t > 1.5:
            self.focus_pt = None; self.focus_area.queue_draw()
        return True

    # ---------- saving ----------
    def _rotate_for_save(self, img):
        from PIL import Image
        if CAMS[self.cam_id]["front"]:
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if self.rot:
            img = img.rotate(-self.rot, expand=True)
        return img

    def save_photo(self, data):
        path = PICS / datetime.datetime.now().strftime("IMG_%Y%m%d_%H%M%S.jpg")
        try:
            if self.rot or CAMS[self.cam_id]["front"]:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(data))
                exif = img.info.get("exif")
                img = self._rotate_for_save(img)
                img.save(path, quality=95, **({"exif": exif} if exif else {}))
            else:
                path.write_bytes(data)
        except Exception as e:
            log("save failed", e); path.write_bytes(data)
        log("saved", path)
        self.last_file = path
        GLib.idle_add(self.after_save, "Photo saved")

    def save_night(self, frames, w, h):
        """Average N NV21 frames (noise drops by ~sqrt(N)), brighten, save."""
        import numpy as np
        from PIL import Image
        try:
            acc = None
            for f in frames:
                a = np.frombuffer(f, dtype=np.uint8)[: w * h * 3 // 2].astype(np.uint16)
                acc = a if acc is None else acc + a
            avg = (acc / len(frames)).astype(np.float32)
            y = avg[: w * h].reshape(h, w)
            vu = avg[w * h:].reshape(h // 2, w // 2, 2)
            # gentle tone curve on luma: lift shadows
            y = 255.0 * np.power(y / 255.0, 0.75)
            u = vu[:, :, 1].repeat(2, 0).repeat(2, 1) - 128.0
            v = vu[:, :, 0].repeat(2, 0).repeat(2, 1) - 128.0
            r = y + 1.402 * v; g = y - 0.344 * u - 0.714 * v; b = y + 1.772 * u
            rgb = np.clip(np.dstack([r, g, b]), 0, 255).astype(np.uint8)
            img = self._rotate_for_save(Image.fromarray(rgb, "RGB"))
            path = PICS / datetime.datetime.now().strftime("IMG_%Y%m%d_%H%M%S_night.jpg")
            img.save(path, quality=95)
            self.last_file = path
            log("night saved", path)
            GLib.idle_add(self.after_save, "Night photo saved")
        except Exception as e:
            log("night failed", e)
            GLib.idle_add(self.toast, "Night failed")
        finally:
            self.busy = False

    def after_save(self, msg):
        self.toast(msg); self.load_last_thumb()
        return False

    def load_last_thumb(self):
        files = sorted(list(PICS.glob("*.jpg")) + list(VIDS.glob("*.mp4")), key=lambda p: p.stat().st_mtime)
        if not files:
            return
        last = files[-1]; self.last_file = last
        try:
            if last.suffix == ".jpg":
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(last), 160, 160, True)
                self.thumb.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
            else:
                self.thumb.set_paintable(icon("video", 40).get_paintable())
        except Exception as e:
            log("thumb", e)

    def open_last(self):
        if self.last_file and Path(self.last_file).exists():
            subprocess.Popen(["xdg-open", str(self.last_file)])
        else:
            subprocess.Popen(["xdg-open", str(PICS)])

    # ---------- drawing / input ----------
    def show_frame(self, w, h, data):
        tex = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(data), w * 3)
        self.picture.set_paintable(tex)
        return False

    def _content_rect(self):
        p = self.picture.get_paintable()
        W, H = self.picture.get_width(), self.picture.get_height()
        if not p or not W:
            return 0, 0, W, H
        pw, ph = p.get_intrinsic_width(), p.get_intrinsic_height()
        s = min(W / pw, H / ph)
        cw, ch = pw * s, ph * s
        return (W - cw) / 2, (H - ch) / 2, cw, ch

    def draw_grid(self, area, cr, W, H):
        if not self.grid_on:
            return
        x0, y0, cw, ch = self._content_rect()
        cr.set_source_rgba(1, 1, 1, 0.35); cr.set_line_width(1)
        for i in (1, 2):
            cr.move_to(x0 + cw * i / 3, y0); cr.line_to(x0 + cw * i / 3, y0 + ch)
            cr.move_to(x0, y0 + ch * i / 3); cr.line_to(x0 + cw, y0 + ch * i / 3)
        cr.stroke()

    def draw_focus(self, area, cr, W, H):
        if not self.focus_pt:
            return
        x, y = self.focus_pt
        k = min(1.0, (time.time() - self.focus_t) / 0.25)
        s = 70 - 16 * k
        cr.set_source_rgba(1, 0.84, 0.04, 1); cr.set_line_width(2)
        cr.rectangle(x - s / 2, y - s / 2, s, s); cr.stroke()
        if k < 1:
            GLib.timeout_add(16, lambda: self.focus_area.queue_draw() or False)

    def on_tap(self, g, n, x, y):
        x0, y0, cw, ch = self._content_rect()
        if not (x0 <= x <= x0 + cw and y0 <= y <= y0 + ch):
            return
        fx, fy = (x - x0) / cw, (y - y0) / ch
        # undo display rotation / mirroring to get sensor coordinates
        r = self.rot
        if r == 90: fx, fy = fy, 1 - fx
        elif r == 180: fx, fy = 1 - fx, 1 - fy
        elif r == 270: fx, fy = 1 - fy, fx
        if CAMS[self.cam_id]["front"]:
            fx = 1 - fx
        self.focus_pt, self.focus_t = (x, y), time.time()
        self.focus_area.queue_draw()
        self.camera.focus_at(fx, fy)

    def on_key(self, ctl, keyval, code, state):
        if keyval in (Gdk.KEY_space, Gdk.KEY_Return, Gdk.KEY_AudioRaiseVolume, Gdk.KEY_AudioLowerVolume, Gdk.KEY_Camera):
            self.on_shutter(); return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
            self.set_zoom(self.zoom_level + 0.5); return True
        if keyval == Gdk.KEY_minus:
            self.set_zoom(self.zoom_level - 0.5); return True
        return False

    def toast(self, msg):
        self.toast_label.set_label(msg); self.toast_label.set_visible(True)
        self._toast_id = getattr(self, "_toast_id", 0) + 1
        tid = self._toast_id
        GLib.timeout_add(1800, lambda: (tid == self._toast_id and self.toast_label.set_visible(False)) or False)
        return False

    def on_close(self, *a):
        self.camera.stop()
        self.orient.release()
        return False


if __name__ == "__main__":
    TabCam().run(None)
