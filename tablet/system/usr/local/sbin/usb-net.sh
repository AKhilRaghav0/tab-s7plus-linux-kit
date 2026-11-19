#!/bin/sh
# USB networking (CDC-NCM, works natively on macOS): tablet = 10.15.19.82, host gets 10.15.19.100 via DHCP.
# No gateway/DNS is handed out, so the Mac keeps using its own internet.
G=/sys/kernel/config/usb_gadget/g1
cd $G || exit 1
if [ -z "$(cat UDC)" ]; then
  echo 0x1d6b > idVendor; echo 0x0104 > idProduct
  mkdir -p strings/0x409; echo Droidian > strings/0x409/manufacturer
  echo "Galaxy Tab S7+" > strings/0x409/product; echo SM-T970-NCM > strings/0x409/serialnumber
  mkdir -p configs/b.1/strings/0x409; echo NCM > configs/b.1/strings/0x409/configuration
  [ -e configs/b.1/f1 ] || ln -s functions/ncm.0 configs/b.1/f1
  echo "$(ls /sys/class/udc | head -1)" > UDC
fi
for i in 1 2 3 4 5; do IF=$(cat functions/ncm.0/ifname); [ -n "$IF" ] && [ "$IF" != "(unnamed net_device)" ] && break; sleep 1; done
ip addr replace 10.15.19.82/24 dev "$IF"; ip link set "$IF" up
[ -f /run/usb-net-dnsmasq.pid ] && kill "$(cat /run/usb-net-dnsmasq.pid)" 2>/dev/null
dnsmasq --interface="$IF" --bind-interfaces --except-interface=lo --port=0 \
  --dhcp-range=10.15.19.100,10.15.19.100,255.255.255.0,12h --dhcp-option=3 --dhcp-option=6 \
  --dhcp-authoritative --pid-file=/run/usb-net-dnsmasq.pid --log-facility=/dev/null
echo "usb-net up on $IF"
