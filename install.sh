#!/bin/bash
# Tab S7+ Linux Kit installer (run on the tablet as the normal user, e.g. droidian)
set -e
cd "$(dirname "$0")"
SYSTEM=1; [ "$1" = "--no-system" ] && SYSTEM=0

echo "==> Installing packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-evdev python3-gi python3-gi-cairo gir1.2-gtk-4.0 libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0 \
  wlr-randr wl-clipboard playerctl libnotify-bin xournalpp foliate clapper tmux \
  gstreamer1.0-plugins-bad gstreamer1.0-libav python3-gbinder python3-pil python3-numpy wtype grim

echo "==> Scripts -> ~/.local/bin"
install -d ~/.local/bin ~/.config/systemd/user ~/.local/share/applications
install -m755 tablet/bin/* ~/.local/bin/
install -m755 fingerprint/fod-light.py fingerprint/udfps-helper.py ~/.local/bin/

echo "==> User services"
install -m644 tablet/systemd-user/*.service ~/.config/systemd/user/
install -d ~/.config/systemd/user/mobi.phosh.Shell.service.d

echo "==> Torch fix (Phosh quick-setting) and TabCam camera app"
install -d ~/.config/systemd/user/org.droidian.Flashlightd.service.d ~/.local/share/tabcam/icons ~/.local/share/icons/hicolor/scalable/apps
install -m644 tablet/systemd-user/org.droidian.Flashlightd.service.d/tab-s7.conf ~/.config/systemd/user/org.droidian.Flashlightd.service.d/
install -m644 apps/tabcam/tabcam.py ~/.local/share/tabcam/
install -m644 apps/tabcam/icons/*.svg ~/.local/share/tabcam/icons/
install -m644 apps/tabcam/io.github.tabs7.TabCam.svg ~/.local/share/icons/hicolor/scalable/apps/
sed "s|/home/droidian|$HOME|g" apps/tabcam/io.github.tabs7.TabCam.desktop > ~/.local/share/applications/io.github.tabs7.TabCam.desktop

echo "==> App launchers"
for f in tablet/applications/*.desktop; do sed "s|/home/droidian|$HOME|g" "$f" > ~/.local/share/applications/"$(basename "$f")"; done
[ -f ~/.tmux.conf ] || install -m644 tablet/tmux.conf ~/.tmux.conf

if [ $SYSTEM = 1 ]; then
  read -r -p "==> Install system tweaks into /etc (volume fix, cover lock, Qt title bars)? [y/N] " a
  if [ "$a" = y ] || [ "$a" = Y ]; then
    for f in pulse/arm_droid_card_custom.pa systemd/logind.conf.d/20-cover-lock.conf profile.d/zz-wayland.sh tmpfiles.d/torch.conf; do
      [ -f /etc/$f ] && [ ! -f /etc/$f.orig ] && sudo cp /etc/$f /etc/$f.orig
      sudo install -D -m644 tablet/system/etc/$f /etc/$f
    done
    sudo systemctl kill -s HUP systemd-logind || true
    sudo systemd-tmpfiles --create /etc/tmpfiles.d/torch.conf || true
    # S Pen charging keeper (needs root for the sec_epen sysfs node)
    sudo install -m755 tablet/system/usr/local/sbin/spen-charge.sh /usr/local/sbin/
    sudo install -m644 tablet/system/etc/systemd/system/spen-charge.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now spen-charge.service || true
  fi
fi

echo "==> Keep services alive when the screen is off (mobile-power-saver)"
if gsettings list-schemas | grep -q org.adishatz.Mps; then
  cur=$(gsettings get org.adishatz.Mps suspend-user-services-blacklist)
  for s in cpu-guard cover-watch spen-buttons spen-air lock-rotate desktop-mode volume-keeper headset-buttons charge-watch lan-mouse org.droidian.Flashlightd auto-brightness; do
    echo "$cur" | grep -q "$s.service" || cur="${cur%]}, '$s.service']"
  done
  gsettings set org.adishatz.Mps suspend-user-services-blacklist "$cur"
fi

echo "==> Enabling services"
systemctl --user daemon-reload
systemctl --user restart org.droidian.Flashlightd.service 2>/dev/null || true
gsettings set org.gnome.settings-daemon.plugins.power ambient-enabled false 2>/dev/null || true   # auto-brightness.py does it
for s in cpu-guard volume-keeper headset-buttons cover-watch spen-buttons lock-rotate desktop-mode auto-brightness; do
  systemctl --user enable --now "$s.service" || echo "   (could not start $s, check: journalctl --user -u $s)"
done
echo
echo "Done. Optional:"
echo "  systemctl --user enable --now lan-mouse     # needs ~/.local/bin/lan-mouse"
echo "  systemctl --user enable --now spen-air      # after pairing the S Pen (see README)"
echo "  systemctl --user enable --now charge-watch  # desk display when charging"
echo "Restart Phosh (sudo systemctl restart phosh) for the profile/title-bar changes."
