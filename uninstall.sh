#!/usr/bin/env bash
# Removes what install.sh put in place (asks for sudo only to remove the udev rule).
set -u
rm -f "$HOME/.local/bin/freevnia" \
      "$HOME/.local/share/applications/freevnia.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/freevnia.svg"
rm -rf "$HOME/.local/share/freevnia"
if [ -e /etc/udev/rules.d/99-freevnia.rules ]; then
    if [ "$(id -u)" = 0 ]; then S=""; else S="sudo"; fi
    if $S rm -f /etc/udev/rules.d/99-freevnia.rules && $S udevadm control --reload; then
        echo "udev rule removed."
    else
        echo "Could not remove the udev rule (needs root): sudo rm /etc/udev/rules.d/99-freevnia.rules" >&2
    fi
fi
echo "FreEvnia removed from ~/.local."
