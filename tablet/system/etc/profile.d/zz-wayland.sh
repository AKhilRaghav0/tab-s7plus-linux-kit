#!/bin/sh
# Help some windowing systems along until they use wayland by default

export QT_QPA_PLATFORM
QT_QPA_PLATFORM=wayland

export QT_IM_MODULE
QT_IM_MODULE=textinputv3

export QT_WAYLAND_DISABLE_WINDOWDECORATION
_dmh=${HOME:-$(getent passwd $(id -u) | cut -d: -f6)}; if [ -f "$_dmh/.config/desktop-mode.on" ]; then unset QT_WAYLAND_DISABLE_WINDOWDECORATION; else QT_WAYLAND_DISABLE_WINDOWDECORATION=1; fi; unset _dmh

export MOZ_ENABLE_WAYLAND
MOZ_ENABLE_WAYLAND=1
