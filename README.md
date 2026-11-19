# Tab S7+ Linux Kit 🐧✏️

**Turn a Samsung Galaxy Tab S7+ (SM-T970, gts7xlwifi) running [Droidian](https://droidian.org) into a fully featured Linux tablet.**

This repo is a set of small, dependency-light scripts, systemd user services and config tweaks. They sit on top of the excellent Droidian port by
[@mukahraman](https://github.com/mukahraman/galaxy-tab-s7-plus-droidian) and fill in the "tablet" parts the base port doesn't have yet: cover, S Pen, headsets, rotation, desktop mode, Mac integration and more.

> Status: daily-driven on one device. Things are tuned for the SM-T970, but most scripts are generic Phosh/Droidian and easy to adapt.

---

## ✨ Features

| Feature | What it does | Files |
|---|---|---|
| 🔌 **USB networking** | The CDC-NCM gadget (native on macOS, no driver needed) gives the tablet `10.15.19.82`, and the host gets `10.15.19.100` from DHCP. It hands out no gateway or DNS, so the host keeps its own internet. For SSH, use `Match host tabs7 exec "nc -z -G 1 10.15.19.82 22"` → `HostName 10.15.19.82` to prefer the cable automatically. | `usb-net.sh`, `usb-net.service` |
| 🧠 **zram tuning** | Rebuilds the zram swap as 3 GB **lz4** with priority 100, plus `swappiness=100`, `page-cluster=0`. | `zram-tune.sh`, `zram-tune.service` |
| ⚡ **CPU guard** | mobile-power-saver sets the governor to `powersave` on screen-off and sometimes fails to restore it, which leaves all 8 cores stuck at about 0.7 GHz and makes everything lag. This keeps them on `schedutil` while the screen is on, with UI tuning: instant ramp-up, a 20 ms hold, higher hispeed frequencies, and a 0.98 GHz floor on the little cores. | `cpu-guard.sh` |
| 🔊 **Real volume steps** | Fixes the port's all-or-nothing volume by switching the droid sink to software volume (`hw_volume=false`). | `tablet/system/etc/pulse/arm_droid_card_custom.pa` |
| 🎧 **Audio manager** | Remembers the speaker volume across reboots and forces the speaker port when nothing is plugged in. USB-C headsets get the right profile, become the default and receive the playing streams; unplugging routes back to the speakers (no more "stuck on a dead device" browser hangs). It also mutes headset **sidetone** (mic monitor) so you don't hear yourself. | `volume-keeper.sh`, `kill-sidetone.sh` |
| ⏯️ **Headset buttons** | USB-C or wired headset buttons drive MPRIS through playerctl: 1× play/pause, 2× next, 3× previous, plus vol ±. Hot-plug aware, and it grabs the device so the button doesn't double-toggle in Firefox. | `headset-buttons.py` |
| 📕 **Smart cover** | Closing the Book Cover locks the tablet and turns the display **off**; opening turns it back on. | `cover-watch.sh`, `20-cover-lock.conf` |
| ✏️ **S Pen button actions** | Hovering with the side button: **double-click takes a screenshot** (to `~/Pictures/Screenshots`), **long-press opens a new Xournal++ note**. Optional: open notes when the pen is detached. | `spen-buttons.py`, `spen-watch.sh` |
| 🔋 **S Pen charging** | Android's S Pen service turns on wireless charging when the pen is docked on the back; without it the pen sits at `DISCHARGE`. This writes `1` to `/sys/class/sec/sec_epen/epen_ble_charging_mode` whenever `epen_insert=1`. | `spen-charge.sh`, `spen-charge.service` |
| 🪄 **S Pen Air Actions** | The pen's Bluetooth remote button and air gestures, **reverse-engineered** from Samsung's BLE service `0xfd6c`: 1× play/pause, 2× next, long-press previous; hold the button and swipe left/right for prev/next and up/down for volume. Like on One UI, it disconnects and goes quiet when you dock the pen, and reconnects when you pull it out. Protocol notes below. | `spen-air.py`, `spen-air.service` |
| 🔄 **Lock-screen rotation** | Phosh freezes rotation while locked; this rotates the lock screen from the accelerometer. It learns Phosh's own orientation→transform mapping and hands control back on unlock. | `lock-rotate.py` |
| 🖥️ **Desktop mode** | One-tap toggle for windowed apps (`auto-maximize=false`), kept on even when Phosh's docked manager disagrees. It also gives Qt apps (Telegram etc.) proper title bars. | `desktop-mode.sh`, `mobi.phosh.Shell.service.d-desktop-mode.conf`, `zz-wayland.sh` |
| 🕐 **Desk display** | Always-on dashboard: big clock, date, battery, Wi-Fi, temperature, weather and ping status of your servers. It switches to a dim AMOLED night style from 23:00 to 07:00 and can **open automatically when a charger is plugged in** (`charge-watch`, off by default: a USB cable to a computer also counts as charging and would keep the screen on). | `desk-display.py`, `charge-watch.sh` |
| 📚 **Reading mode** | Toggle for DND, dimmer screen, a longer timeout, and Foliate in sepia. | `reading-mode.sh` |
| 📺 **Smooth YouTube** | Plays the copied YouTube link in Clapper with the **hardware decoder** (`droidvdec`) via yt-dlp. | `yt-play.sh` |
| 🤖 **Claude Code launcher** | A persistent `tmux` session running Claude Code. | `claude-code.desktop`, `tmux.conf` |
| 🖱️ **Mac keyboard/trackpad** | [lan-mouse](https://github.com/feschber/lan-mouse) user service (wlroots emulation plus layer-shell capture). | `lan-mouse.service` |
| 📋 **Mac ↔ Tab bridge** | Runs on the Mac over SSH: **two-way clipboard sync** (pbcopy ↔ wl-copy) and **tablet notifications as macOS notifications**. | `mac/tab_bridge.py` |
| 🔈 **Play on Mac** (AirPlay-style) | A one-tap toggle sends all tablet audio to a `Mac-Speaker` sink, and the Mac bridge streams it there with `parec` → SSH → `ffplay`, only while something is playing. Real AirPlay (RAOP) fails against the macOS receiver because it needs AirPlay 2 pairing. | `play-on-mac.sh`, `mac/tab_bridge.py` |
| 👆 **In-display fingerprint (WIP)** | Research plus a helper that talks to Samsung's SEH HAL over hwbinder and lights the sensor. See below. | `fingerprint/`, `docs/fingerprint-research.md` |

## 📦 Install (on the tablet)

```bash
git clone https://github.com/AKhilRaghav0/tab-s7plus-linux-kit.git
cd tab-s7plus-linux-kit
./install.sh            # installs scripts + user services, asks before touching /etc
```

Everything goes to `~/.local/bin`, `~/.config/systemd/user` and `~/.local/share/applications`. System files (`/etc/...`) are backed up as `*.orig` before being replaced. Run `./install.sh --no-system` to skip them.

**Desk display servers**: create `~/.config/desk-display/servers` with one `Name host` per line. Set `DESK_CITY` for the weather; leave it empty to auto-detect.

### Mac bridge (optional)
Needs an SSH host alias `tabs7` with key auth. Then:
```bash
python3 mac/tab_bridge.py      # or wrap it in a launchd agent
```

## 🪄 S Pen Air Actions: how it works

**Pairing (one-time):**
1. BlueZ must be pairable, or the pen rejects the "No bonding" request with `SMP Pairing Failed (Unspecified reason)`.
2. If the pen was paired with Android before, dock it and send a BLE reset: `echo 2 | sudo tee /sys/class/sec/sec_epen/epen_ble_charging_mode`, then `echo 1 | sudo tee ...` to start charging again.
3. Pull the pen out, press its button, and pair:

```bash
bluetoothctl
  agent NoInputNoOutput
  default-agent
  pairable on
  scan le          # wait for "SPEN 02 (xxxx)"
  pair  <MAC>
  trust <MAC>
```

`spen-air.py` finds the first paired device named `SPEN*` (override with `SPEN_MAC`).

**Protocol** (service `0000fd6c-...`, characteristic **"Button State"** `6c290d2e-1c03-aca1-ab48-a9b908bae79e`, notify):

| Packet | Meaning |
|---|---|
| `03` | button down |
| `f0 NN` + NN × `[0f dx:int16le dy:int16le seq]` | motion while held (the pen integrates the IMU itself) |
| `00 00 00 00 00 NN` | button up |

Other characteristics carry user descriptions: **Battery Level** `5a87b4ef-...434f` (byte 0 = %), Status, FW Version, **Mode**, **Raw ST Data** (raw IMU), Battery Raw, Manu_Date. A press counts as a gesture when the motion peak goes over about 600; otherwise it is a click, a double-click (within 0.35 s) or a long press (over 0.8 s). Edit `ACTIONS` in the script to remap. `SPEN_DEBUG=0` turns off the on-screen toasts.

## 👆 Fingerprint (in-display optical) — help wanted

The SM-T970 has an **optical UDFPS**. Droidian's `droidian-fpd` speaks only the AOSP @2.1 HAL, but Samsung's sensor only scans after `ISehBiometricsFingerprint::sehRequest(22, 2)` (finger down) and `(22, 1)` (finger up).

What works so far:
- **Talking to the SEH HAL** over hwbinder with `python3-gbinder`: transaction 11, `seh(6,0)` returns `100045`.
- **Lighting the sensor**: a white layer-shell disc at native `(876, 2614)`, r=77. Note: GTK4 needs `GSK_RENDERER=cairo` on hybris.
- **A full capture cycle** on every touch (`10001 READY → 10002 STARTED → 10003 COMPLETED → 10005 CAPTURE_SUCCESS`), using `fingerprint/udfps-helper.py` and `droidian-fpd` patched to log vendor codes.
- ❌ But enrollment `remaining` stays at 100. Most likely the illumination is too dim, because the panel's HBM mask path is disabled in the kernel DT.

All the details and next steps are in [`docs/fingerprint-research.md`](docs/fingerprint-research.md). PRs welcome!

## ⚠️ Notes
- **Firefox:** Widevine DRM works (L3 only, since the bootloader is unlocked) via [AsahiLinux/widevine-installer](https://github.com/AsahiLinux/widevine-installer). It needs `LIBDIR=/usr/lib CHROME_WIDEVINE_BASE=/usr/lib/chromium` on Debian. Installing `gstreamer1.0-libav` (FFmpeg) noticeably smooths Firefox video.
- **Firefox speed-ups** (software rendering on hybris): `media.av1.enabled=false` and `media.mediasource.vp9.enabled=false` (YouTube then sends H.264), `layout.frame_rate=60`, and no smooth scrolling or animations.
- **mobile-power-saver** freezes apps when the screen is off. Add your music app to `org.adishatz.Mps suspend-apps-blacklist`, and these services to `suspend-user-services-blacklist`.
- **Debloat:** cups, ModemManager, ofono, nfcd, strongswan and openvpn are useless on the Wi-Fi tablet, as are the GNOME Software, Chatty and Evolution autostarts; disable them.
- **Refresh-rate switching** isn't possible yet: libhybris' `libhwc2` compat layer has no `set_active_config`, so phoc stays on the HWC default mode (120 Hz).
- **Panel:** 60/120 Hz only ("No support LFD"). The night-light/gamma has no effect on hwcomposer.

## 🙏 Credits
- [@mukahraman](https://github.com/mukahraman) for the Droidian port, kernel and camera for this tablet
- The Droidian, Halium, LineageOS and libhybris communities
- [lan-mouse](https://github.com/feschber/lan-mouse), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Asahi widevine-installer](https://github.com/AsahiLinux/widevine-installer)

MIT licensed. No warranty: you are poking at your own tablet.
