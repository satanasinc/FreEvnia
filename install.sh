#!/usr/bin/env bash
# FreEvnia installer: the AppImage, a launcher and the udev rule, in one go.
#
#   curl -fsSL https://raw.githubusercontent.com/satanasinc/FreEvnia/main/install.sh | bash
#   ./install.sh                      # inside the .tar.gz from the Releases page (uses the AppImage next to it)
#   ./install.sh /path/FreEvnia-x86_64.AppImage
#   ./install.sh --no-udev            # skip the udev rule (no sudo needed)
#   ./install.sh --print-rule         # only show the udev rule it would install
#
# Installs to ~/.local (no root) and asks for sudo ONLY for the udev rule. Remove with ./uninstall.sh.
set -euo pipefail

REPO="satanasinc/FreEvnia"
APP_URL="https://github.com/$REPO/releases/latest/download/FreEvnia-x86_64.AppImage"
DATA="$HOME/.local/share/freevnia"
BIN="$HOME/.local/bin"
RULE_FILE="/etc/udev/rules.d/99-freevnia.rules"
USER_NAME="${SUDO_USER:-${USER:-$(id -un)}}"

DO_UDEV=1; PRINT_RULE=0; SRC=""
for a in "$@"; do
    case "$a" in
        --no-udev) DO_UDEV=0 ;;
        --print-rule) PRINT_RULE=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) SRC="$a" ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

# A group the user belongs to AND that exists here (plugdev on Debian, wheel on Arch...). A GROUP that does not exist
# makes udev drop the whole line, so only pick one that is there. Without one, "uaccess" alone is used.
pick_group() {
    local g
    for g in plugdev wheel sudo users; do
        if id -nG "$USER_NAME" 2>/dev/null | tr ' ' '\n' | grep -qx "$g" && getent group "$g" >/dev/null; then
            echo "$g"; return
        fi
    done
}

make_rule() {
    local g; g="$(pick_group)"
    local grp=""; [ -n "$g" ] && grp=", GROUP=\"$g\""
    cat <<EOF
# FreEvnia: let the user talk to the Philips Evnia monitor (DDC/CI over USB) and its Ambiglow LEDs.
SUBSYSTEM=="usb", ATTR{idVendor}=="2109", ATTR{idProduct}=="8884", MODE="0660"$grp, TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0cf2", ATTR{idProduct}=="b20b", MODE="0660"$grp, TAG+="uaccess"
EOF
}

if [ "$PRINT_RULE" = 1 ]; then make_rule; exit 0; fi

as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else echo "Need root for this step and sudo is not installed: run it as root: $*" >&2; return 1
    fi
}

# --- 1. the AppImage -----------------------------------------------------------------------------------------
mkdir -p "$DATA" "$BIN"
APP="$DATA/FreEvnia-x86_64.AppImage"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo .)"
if [ -z "$SRC" ] && [ -f "$HERE/FreEvnia-x86_64.AppImage" ]; then SRC="$HERE/FreEvnia-x86_64.AppImage"; fi
if [ -n "$SRC" ]; then
    say "Installing $SRC"
    install -m755 "$SRC" "$APP.new"
else
    say "Downloading the latest AppImage"
    if command -v curl >/dev/null 2>&1; then curl -fL --progress-bar -o "$APP.new" "$APP_URL"
    elif command -v wget >/dev/null 2>&1; then wget -O "$APP.new" "$APP_URL"
    else echo "Need curl or wget (or pass the AppImage path)." >&2; exit 1; fi
    chmod 755 "$APP.new"
fi
mv -f "$APP.new" "$APP"

# --- 2. the command "freevnia" (CLI; with no arguments it opens the window) ---------------------------------
# AppImages need FUSE; without it run them extracted instead.
if command -v fusermount >/dev/null 2>&1 || command -v fusermount3 >/dev/null 2>&1; then
    ln -sf "$APP" "$BIN/freevnia"
else
    say "No FUSE found: the launcher will extract the AppImage on each start (a bit slower)."
    printf '#!/bin/sh\nexport APPIMAGE_EXTRACT_AND_RUN=1\nexec "%s" "$@"\n' "$APP" > "$BIN/freevnia"
    chmod 755 "$BIN/freevnia"
fi

# --- 3. launcher + icon -------------------------------------------------------------------------------------
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
cat > "$HOME/.local/share/icons/hicolor/scalable/apps/freevnia.svg" <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="40" fill="#14161f"/><rect x="24" y="72" width="208" height="96" rx="8" fill="#0b0c12" stroke="#7b5cff" stroke-width="8"/><rect x="36" y="84" width="92" height="72" fill="#2a6df4"/><rect x="132" y="84" width="88" height="72" fill="#7b5cff"/><rect x="96" y="184" width="64" height="10" rx="4" fill="#7b5cff"/></svg>
EOF
cat > "$HOME/.local/share/applications/freevnia.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FreEvnia
Comment=PBP / PIP / Ambiglow control for Philips Evnia monitors
Exec=$BIN/freevnia
Icon=freevnia
Terminal=false
Categories=Utility;
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# --- 4. udev rule (the only step that needs root) -----------------------------------------------------------
if [ "$DO_UDEV" = 1 ]; then
    say "Installing the udev rule (asks for your password)"
    TMP="$(mktemp)"; make_rule > "$TMP"
    as_root install -m644 "$TMP" "$RULE_FILE"
    rm -f "$TMP"
    as_root udevadm control --reload
    as_root udevadm trigger --subsystem-match=usb --attr-match=idVendor=2109 || true
    as_root udevadm trigger --subsystem-match=usb --attr-match=idVendor=0cf2 || true
fi

say "Done."
echo "  Open it from the application menu (FreEvnia) or run:  freevnia"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  Note: $BIN is not in your PATH; add it, or run $BIN/freevnia" ;; esac
[ "$DO_UDEV" = 1 ] && echo "  If it says \"Access denied\": unplug and plug the monitor's USB cable once."
echo "  The monitor's USB cable must go to THIS computer (the one on the left/main picture)."
