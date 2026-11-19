#!/bin/sh
# Rebuild zram swap: lz4 (fast) 3 GB, high priority; tune VM for compressed swap.
Z=/sys/block/zram0
swapoff /dev/block/zram0 2>/dev/null || swapoff /dev/zram0 2>/dev/null
echo 1 > $Z/reset
echo lz4 > $Z/comp_algorithm
echo 3G > $Z/disksize
mkswap /dev/block/zram0 >/dev/null 2>&1 || mkswap /dev/zram0 >/dev/null
swapon -p 100 /dev/block/zram0 2>/dev/null || swapon -p 100 /dev/zram0
echo 100 > /proc/sys/vm/swappiness; echo 0 > /proc/sys/vm/page-cluster; echo 80 > /proc/sys/vm/vfs_cache_pressure
