#!/usr/bin/env bash
# Build dist/freevnia_<ver>_all.deb (pure Python, uses Debian's python3-usb and PySide6).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VER="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")"
D="$(mktemp -d)"; trap 'rm -rf "$D"' EXIT
P="$D/pkg"
install -d "$P/DEBIAN" "$P/usr/lib/python3/dist-packages" "$P/usr/bin" "$P/usr/lib/udev/rules.d" "$P/usr/share/applications" "$P/usr/share/icons/hicolor/scalable/apps"
cp -r "$ROOT/freevnia" "$P/usr/lib/python3/dist-packages/"
find "$P" -name __pycache__ -prune -exec rm -rf {} +
printf '#!/bin/sh\nexec python3 -c "import sys; from freevnia.cli import main; sys.exit(main())" "$@"\n' > "$P/usr/bin/freevnia"
printf '#!/bin/sh\nexec python3 -m freevnia.gui "$@"\n' > "$P/usr/bin/freevnia-gui"
chmod 755 "$P/usr/bin/"*
sed 's/MODE="0660"/MODE="0660", GROUP="plugdev"/' "$ROOT/udev/99-freevnia.rules" > "$P/usr/lib/udev/rules.d/99-freevnia.rules"   # Debian/Ubuntu have plugdev
sed 's/^Exec=.*/Exec=freevnia-gui/; s/^Icon=.*/Icon=freevnia/' "$ROOT/packaging/appimage/freevnia.desktop" > "$P/usr/share/applications/freevnia.desktop"
cp "$ROOT/packaging/appimage/freevnia.svg" "$P/usr/share/icons/hicolor/scalable/apps/"
cat > "$P/DEBIAN/control" <<EOT
Package: freevnia
Version: $VER
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-usb, python3-pyside6.qtwidgets
Maintainer: satanasinc <satanasinc@users.noreply.github.com>
Homepage: https://github.com/satanasinc/FreEvnia
Description: Unofficial control for Philips Evnia monitors on Linux
 Input, PBP/PIP, Ambiglow and settings of the Philips Evnia 49M2C8900L
 over DDC/CI through its USB hub. Commands: freevnia, freevnia-gui.
EOT
printf '#!/bin/sh\nudevadm control --reload 2>/dev/null || true\nudevadm trigger --subsystem-match=usb --attr-match=idVendor=2109 2>/dev/null || true\nexit 0\n' > "$P/DEBIAN/postinst"; chmod 755 "$P/DEBIAN/postinst"
mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$P" "$ROOT/dist/freevnia_${VER}_all.deb"
