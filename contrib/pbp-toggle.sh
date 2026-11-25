#!/usr/bin/env bash
# Toggle PBP on/off (bind it to a global shortcut). Reads VCP 0xE6: 1 = full screen, 0 = PBP/PIP active.
# Needs `freevnia` in PATH. Shows a KDE popup via kdialog if available.
aviso() { command -v kdialog >/dev/null && kdialog --title "FreEvnia" --passivepopup "$1" 4 >/dev/null 2>&1; true; }
estado=$(freevnia get 0xe6 2>/dev/null | sed -n 's/.*current=\([0-9]*\).*/\1/p')
case "$estado" in
    1) freevnia mode pbp1 >/dev/null 2>&1 && aviso "PBP on" ;;
    0) freevnia mode off  >/dev/null 2>&1 && aviso "PBP off" ;;
    *) aviso "Monitor not reachable (its USB hub is on another computer?)"; exit 1 ;;
esac
