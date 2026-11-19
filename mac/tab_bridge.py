#!/usr/bin/env python3
"""Mac <-> Tab S7+ (Droidian) bridge, run from the Mac over SSH (host alias: tabs7).

1. Clipboard sync (text), both ways.
   - Mac -> Tab: poll pbpaste, push to wl-copy.
   - Tab -> Mac: stream `wl-paste --watch`, write to pbcopy.
2. Tab notifications show up as macOS notifications (dbus-monitor on the tab).

Reconnects on its own when the tab drops off the network.
"""
import base64, hashlib, subprocess, threading, time, re, sys

HOST = "tabs7"
ENV = "export XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus;"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", HOST]
MAX = 2_000_000  # skip clipboard items bigger than ~2 MB

lock = threading.Lock()
last_hash = None  # hash of the last text we synced (either direction), to avoid echo loops


def h(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def mac_get() -> bytes:
    return subprocess.run(["pbpaste"], capture_output=True).stdout


def mac_set(b: bytes):
    subprocess.run(["pbcopy"], input=b)


def mac_to_tab():
    global last_hash
    prev = h(mac_get())
    while True:
        time.sleep(0.6)
        data = mac_get()
        cur = h(data)
        if cur == prev:
            continue
        prev = cur
        if not data or len(data) > MAX:
            continue
        with lock:
            if cur == last_hash:
                continue
            last_hash = cur
        r = subprocess.run(SSH + [ENV + " setsid wl-copy >/dev/null 2>&1"], input=data, capture_output=True, timeout=15)
        log("mac->tab", len(data), "bytes", "ok" if r.returncode == 0 else f"err {r.returncode}")


def tab_to_mac():
    global last_hash
    cmd = ENV + " wl-paste -n -t text --watch sh -c 'base64 -w0; echo'"
    while True:
        try:
            p = subprocess.Popen(SSH + [cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            first = True
            for line in p.stdout:
                line = line.strip()
                if first:  # wl-paste --watch emits the current clipboard on start; don't clobber the Mac's
                    first = False
                    continue
                if not line:
                    continue
                try:
                    data = base64.b64decode(line)
                except Exception:
                    continue
                if not data or len(data) > MAX:
                    continue
                cur = h(data)
                with lock:
                    if cur == last_hash:
                        continue
                    last_hash = cur
                mac_set(data)
                log("tab->mac", len(data), "bytes")
            p.wait()
        except Exception as e:
            log("tab->mac error", e)
        time.sleep(5)


def notify_mac(app, title, body):
    def q(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')[:240]
    script = f'display notification "{q(body)}" with title "📱 {q(app or "Tab")}" subtitle "{q(title)}"'
    subprocess.run(["osascript", "-e", script])


def tab_notifications():
    cmd = ENV + " dbus-monitor --session \"interface='org.freedesktop.Notifications',member='Notify'\""
    skip_apps = {"notify-send"}  # our own S Pen / bridge popups
    while True:
        try:
            p = subprocess.Popen(SSH + [cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            buf = []
            for line in p.stdout:
                if line.startswith("method call") and "member=Notify" in line:
                    buf = []
                    continue
                m = re.match(r'\s+string "(.*)"\s*$', line)
                if m is not None:
                    buf.append(m.group(1))
                    # Notify args: app_name, (uint id), app_icon, summary, body ...
                    if len(buf) == 4:
                        app, _icon, title, body = buf
                        if app not in skip_apps and (title or body):
                            notify_mac(app, title, body)
                            log("notif", app, "|", title)
            p.wait()
        except Exception as e:
            log("notif error", e)
        time.sleep(5)


FFPLAY = next((p for p in ("/opt/homebrew/bin/ffplay", "/usr/local/bin/ffplay") if __import__("os").path.exists(p)), "ffplay")

def mac_speaker():
    """Play the tablet's 'Mac-Speaker' sink on this Mac whenever something is playing into it."""
    state_cmd = ENV + " pactl list short sinks | awk '$2==\"mac_speaker\"{print $NF}'"
    rec_cmd = ENV + " exec parec -d mac_speaker.monitor --format=s16le --rate=48000 --channels=2 --latency-msec=40 --raw"
    player = None
    while True:
        try:
            st = subprocess.run(SSH + [state_cmd], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            st = ""
        playing = st == "RUNNING"
        if playing and player is None:
            src = subprocess.Popen(SSH + [rec_cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            ply = subprocess.Popen([FFPLAY, "-nodisp", "-loglevel", "quiet", "-fflags", "nobuffer", "-flags", "low_delay",
                                    "-probesize", "32", "-f", "s16le", "-ar", "48000", "-ch_layout", "stereo", "-i", "-"],
                                   stdin=src.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            player = (src, ply); log("mac speaker: playing")
        elif player and (not playing or player[1].poll() is not None or player[0].poll() is not None):
            for p in player:
                try: p.kill()
                except Exception: pass
            player = None; log("mac speaker: stopped")
        time.sleep(2)


if __name__ == "__main__":
    log("tab bridge starting")
    for fn in (mac_to_tab, tab_to_mac, tab_notifications, mac_speaker):
        threading.Thread(target=fn, daemon=True).start()
    while True:
        time.sleep(3600)
