#!/usr/bin/env bash
# Build FreEvnia-x86_64.AppImage (bundles Python, PySide6, pyusb and libusb). Run from anywhere.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -r "$ROOT/packaging/appimage" "$WORK/recipe"
rm "$WORK/recipe/build.sh"
echo "$ROOT" >> "$WORK/recipe/requirements.txt"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q python-appimage
cd "$WORK"
"$WORK/venv/bin/python-appimage" build app -p 3.12 "$WORK/recipe"
mkdir -p "$ROOT/dist"
mv ./*.AppImage "$ROOT/dist/FreEvnia-x86_64.AppImage"
ls -lh "$ROOT/dist"
