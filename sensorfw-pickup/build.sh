#!/bin/bash
# Build and install the pick-up gesture adaptor for sensorfw (Droidian, Qt6, HIDL sensors HAL).
# The two upstream headers that libsensorfw-qt6-dev doesn't ship are fetched from droidian/sensorfw.
set -e
cd "$(dirname "$0")"
sudo apt-get install -y -qq libsensorfw-qt6-dev qt6-base-dev g++ make libgbinder-dev libglibutil-dev libglib2.0-dev
C=feafda86681933e599c742d6b6bcef0dddd0e73f
for f in hybrisadaptor.h hybrisbindertypes.h mcewatcher.h; do
  [ -f $f ] || curl -sfL -o $f https://raw.githubusercontent.com/droidian/sensorfw/$C/core/$f
done
qmake6 && make -j4
sudo install -m644 libhybrispickupadaptor-qt6.so /usr/lib/aarch64-linux-gnu/sensord-qt6/
CONF=/etc/sensorfw/sensord-hybris.conf
[ -f $CONF.orig ] || sudo cp $CONF $CONF.orig
sudo sed -i "s/^proximityadaptor = .*/proximityadaptor = hybrispickupadaptor/" $CONF
sudo systemctl restart sensorfwd    # the sensor proxy takes ~30 s to come back
echo "Done. Undo: sudo cp $CONF.orig $CONF && sudo systemctl restart sensorfwd"
