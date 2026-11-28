#!/usr/bin/env bash
# Builds dist/FreEvnia-macos-<arch>.zip on macOS (Python 3.12): FreEvnia.app (window) + freevnia (command line).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] || ARCH="x86_64"
python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller pyusb libusb-package PySide6-Essentials .
rm -rf build dist/FreEvnia dist/FreEvnia.app dist/freevnia dist/FreEvnia-macos
# the window (.app); libusb comes from libusb-package
python3 -m PyInstaller --noconfirm --windowed --name FreEvnia --osx-bundle-identifier uk.satanasinc.freevnia \
    --collect-all libusb_package packaging/windows/gui_entry.py
# the command line: one small file, no Qt
python3 -m PyInstaller --noconfirm --onefile --console --name freevnia --collect-all libusb_package \
    --exclude-module PySide6 packaging/windows/cli_entry.py
OUT="dist/FreEvnia-macos"; mkdir -p "$OUT"
cp -R dist/FreEvnia.app "$OUT/FreEvnia.app"
cp dist/freevnia "$OUT/freevnia"
cp LICENSE README.md "$OUT/"
cat > "$OUT/READ-ME.txt" <<'TXT'
FreEvnia for macOS (unofficial)
===============================
FreEvnia.app  - the window (PBP / PIP / swap / Ambiglow / settings). Drag it to Applications.
freevnia      - command line (run it in Terminal: ./freevnia --help)

The files are not signed or notarized, so macOS blocks them the first time:
  right-click FreEvnia.app > Open > Open     (or in Terminal: xattr -dr com.apple.quarantine FreEvnia.app freevnia)
The monitor's USB upstream cable must go to THIS Mac (the one on the left/main picture).
https://github.com/satanasinc/FreEvnia
TXT
( cd "$OUT" && ditto -c -k --sequesterRsrc --keepParent . "../FreEvnia-macos-$ARCH.zip" ) || ( cd dist && zip -qr "FreEvnia-macos-$ARCH.zip" FreEvnia-macos )
ls -lh dist/*.zip
