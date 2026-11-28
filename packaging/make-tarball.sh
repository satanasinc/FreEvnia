#!/usr/bin/env bash
# dist/FreEvnia-linux-x86_64.tar.gz: AppImage + install.sh + uninstall.sh (needs dist/FreEvnia-x86_64.AppImage).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$(mktemp -d)"; trap 'rm -rf "$D"' EXIT
T="$D/FreEvnia"; mkdir "$T"
cp "$ROOT/dist/FreEvnia-x86_64.AppImage" "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/LICENSE" "$ROOT/README.md" "$T/"
tar -C "$D" -czf "$ROOT/dist/FreEvnia-linux-x86_64.tar.gz" FreEvnia
