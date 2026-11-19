# Tab S7+ Linux Kit 🐧✏️

**Turn a Samsung Galaxy Tab S7+ (SM-T970, gts7xlwifi) running [Droidian](https://droidian.org) into a fully featured Linux tablet.**

This repo is a set of small, dependency-light scripts, systemd user services and config tweaks. They sit on top of the excellent Droidian port by
[@mukahraman](https://github.com/mukahraman/galaxy-tab-s7-plus-droidian) and fill in the "tablet" parts the base port doesn't have yet: cover, S Pen, headsets, rotation, desktop mode, Mac integration and more.

> Status: daily-driven on one device. Things are tuned for the SM-T970, but most scripts are generic Phosh/Droidian and easy to adapt.

---

## ✨ Features

| Feature | What it does | Files |
|---|---|---|
| 🔊 **Real volume steps** | Fixes the port's all-or-nothing volume by switching the droid sink to software volume (`hw_volume=false`). | `tablet/system/etc/pulse/arm_droid_card_custom.pa` |
| 🎧 **Audio manager** | Remembers the speaker volume across reboots and forces the speaker port when nothing is plugged in. USB-C headsets get the right profile, become the default and receive the playing streams; unplugging routes back to the speakers (no more "stuck on a dead device" browser hangs). It also mutes headset **sidetone** (mic monitor) so you don't hear yourself. | `volume-keeper.sh`, `kill-sidetone.sh` |
| ⏯️ **Headset buttons** | USB-C or wired headset buttons drive MPRIS through playerctl: 1× play/pause, 2× next, 3× previous, plus vol ±. Hot-plug aware, and it grabs the device so the button doesn't double-toggle in Firefox. | `headset-buttons.py` |
| 📕 **Smart cover** | Closing the Book Cover locks the tablet and turns the display **off**; opening turns it back on. | `cover-watch.sh`, `20-cover-lock.conf` |
| ✏️ **S Pen button actions** | Hovering with the side button: **double-click takes a screenshot** (to `~/Pictures/Screenshots`), **long-press opens a new Xournal++ note**. Optional: open notes when the pen is detached. | `spen-buttons.py`, `spen-watch.sh` |
| 🔄 **Lock-screen rotation** | Phosh freezes rotation while locked; this rotates the lock screen from the accelerometer. It learns Phosh's own orientation→transform mapping and hands control back on unlock. | `lock-rotate.py` |
| 🖥️ **Desktop mode** | One-tap toggle for windowed apps (`auto-maximize=false`), kept on even when Phosh's docked manager disagrees. It also gives Qt apps (Telegram etc.) proper title bars. | `desktop-mode.sh`, `mobi.phosh.Shell.service.d-desktop-mode.conf`, `zz-wayland.sh` |
| 🕐 **Desk display** | Always-on dashboard: big clock, date, battery, Wi-Fi, temperature, weather and ping status of your servers. It switches to a dim AMOLED night style from 23:00 to 07:00 and **opens automatically when the charger is plugged in**. | `desk-display.py`, `charge-watch.sh` |
| 📚 **Reading mode** | Toggle for DND, dimmer screen, a longer timeout, and Foliate in sepia. | `reading-mode.sh` |
| 📺 **Smooth YouTube** | Plays the copied YouTube link in Clapper with the **hardware decoder** (`droidvdec`) via yt-dlp. | `yt-play.sh` |
| 🤖 **Claude Code launcher** | A persistent `tmux` session running Claude Code. | `claude-code.desktop`, `tmux.conf` |
| 🖱️ **Mac keyboard/trackpad** | [lan-mouse](https://github.com/feschber/lan-mouse) user service (wlroots emulation plus layer-shell capture). | `lan-mouse.service` |
| 📋 **Mac ↔ Tab bridge** | Runs on the Mac over SSH: **two-way clipboard sync** (pbcopy ↔ wl-copy) and **tablet notifications as macOS notifications**. | `mac/tab_bridge.py` |
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
- **mobile-power-saver** freezes apps when the screen is off. Add your music app to `org.adishatz.Mps suspend-apps-blacklist`, and these services to `suspend-user-services-blacklist`.
- **Panel:** 60/120 Hz only ("No support LFD"). The night-light/gamma has no effect on hwcomposer.

## 🙏 Credits
- [@mukahraman](https://github.com/mukahraman) for the Droidian port, kernel and camera for this tablet
- The Droidian, Halium, LineageOS and libhybris communities
- [lan-mouse](https://github.com/feschber/lan-mouse), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Asahi widevine-installer](https://github.com/AsahiLinux/widevine-installer)

MIT licensed. No warranty: you are poking at your own tablet.
