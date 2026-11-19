#!/usr/bin/env python3
"""Headset media buttons -> MPRIS (playerctl). Hot-plug aware.
PLAYPAUSE: play/pause; double press: next; triple press: previous. NEXT/PREVIOUS keys pass through."""
import evdev, selectors, subprocess, time
INTERNAL = {"qpnp_pon","gpio_keys","sec_touchscreen","sec_e-pen","meta_event","hall","hall_logical","hall_wacom",
            "grip_sensor","grip_notifier","grip_sensor_wifi"}
K = evdev.ecodes
def pc(*a): subprocess.Popen(["playerctl", *a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def vol(step):
    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", step])
    subprocess.Popen(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
sel = selectors.DefaultSelector(); devs = {}; presses = []; last_scan = 0
def scan():
    for p in evdev.list_devices():
        if p in devs: continue
        try:
            d = evdev.InputDevice(p)
            if d.name in INTERNAL or d.name.startswith("lan-mouse"): d.close(); continue
            keys = d.capabilities().get(K.EV_KEY, [])
            if K.KEY_PLAYPAUSE in keys or K.KEY_PLAYCD in keys or K.KEY_MEDIA in keys:
                try: d.grab()   # exclusive: stop the compositor/Firefox from also toggling
                except OSError: pass
                devs[p] = d; sel.register(d, selectors.EVENT_READ)
            else: d.close()
        except Exception: pass
while True:
    if time.time() - last_scan > 2: scan(); last_scan = time.time()
    for key, _ in sel.select(timeout=0.3):
        d = key.fileobj
        try:
            for e in d.read():
                if e.type != K.EV_KEY or e.value == 0: continue
                if e.value == 2 and e.code not in (K.KEY_VOLUMEUP, K.KEY_VOLUMEDOWN): continue
                if e.code in (K.KEY_PLAYPAUSE, K.KEY_PLAYCD, K.KEY_MEDIA, K.KEY_PAUSECD): presses.append(time.time())
                elif e.code == K.KEY_VOLUMEUP: vol("+5%")
                elif e.code == K.KEY_VOLUMEDOWN: vol("-5%")
                elif e.code == K.KEY_NEXTSONG: pc("next")
                elif e.code == K.KEY_PREVIOUSSONG: pc("previous")
        except OSError:
            sel.unregister(d); devs.pop(d.path, None)
    if presses and time.time() - presses[-1] > 0.45:
        n = len(presses); presses = []
        pc("play-pause" if n == 1 else "next" if n == 2 else "previous")
