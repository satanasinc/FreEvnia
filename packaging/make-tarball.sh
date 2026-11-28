#!/usr/bin/env bash
# dist/FreEvnia-linux-x86_64.tar.gz: AppImage + udev rule + install.sh (needs dist/FreEvnia-x86_64.AppImage).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$(mktemp -d)"; trap 'rm -rf "$D"' EXIT
T="$D/FreEvnia"; mkdir "$T"
cp "$ROOT/dist/FreEvnia-x86_64.AppImage" "$ROOT/udev/99-freevnia.rules" "$ROOT/packaging/ufw/freevnia" "$ROOT/LICENSE" "$ROOT/README.md" "$T/"
cat > "$T/install.sh" <<'EOT'
#!/usr/bin/env bash
# Installs the AppImage to ~/.local/bin/freevnia and the udev rule (asks for sudo).
set -e
cd "$(dirname "$0")"
install -D -m755 FreEvnia-x86_64.AppImage "$HOME/.local/bin/freevnia"
sudo install -m644 99-freevnia.rules /etc/udev/rules.d/99-freevnia.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2109
if [ -d /etc/ufw/applications.d ]; then
    sudo install -m644 freevnia /etc/ufw/applications.d/freevnia
    echo "ufw profile installed. To share the monitor between computers, allow your LAN, e.g.:"
    echo "  sudo ufw allow from 192.168.1.0/24 to any app FreEvnia"
fi
echo "Done. Re-plug the monitor's USB cable. Run: freevnia (GUI)  |  freevnia mode pip ..."
EOT
chmod +x "$T/install.sh"
tar -C "$D" -czf "$ROOT/dist/FreEvnia-linux-x86_64.tar.gz" FreEvnia
