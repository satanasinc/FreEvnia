# FreEvnia

**Unofficial, open-source control for Philips Evnia monitors on Linux**: switch inputs, turn **PBP / PIP** on and
off, drive the **Ambiglow** lights and change the monitor's settings (picture mode, audio input, gaming options,
Power LED, CEC and the **OLED panel care** options) from your PC, without the Windows-only Evnia Precision Center.

> Not affiliated with, endorsed by or supported by Philips or TPV. "Philips" and "Evnia" are trademarks
> of their owners and are used here only to say which monitors this works with.

![FreEvnia window](docs/gui.png)

## Why

The Philips Evnia 49M2C8900L accepts input / PBP / PIP changes **only over USB**, not over the usual
DDC channel (`ddcutil` reads work, but writes to the input source are silently ignored). The official
app is Windows-only. FreEvnia talks to the monitor's USB hub directly, so it works on Linux and, since it
is just USB control transfers, on anything that can run `libusb`.

How it works and how it was reverse-engineered: [PROTOCOL.md](PROTOCOL.md).

## Status

Tested on one monitor: **Philips Evnia 49M2C8900L, firmware 1.08**. Everything below was verified on the real
panel (with a camera where it is visible).

| Works | Not verified / not done |
|---|---|
| Input, full screen / **PBP** / **PIP**, PIP corner and size, second picture (USB-C, HDMI 1, HDMI 2, DisplayPort) | PBP 2, PBP 3, swap pictures, HDMI as the *main* source |
| **Ambiglow**: every mode, colour, position, brightness and speed the OSD offers (the monitor draws them) | Follow audio was not confirmed with a camera |
| Fixed Ambiglow colours of any RGB value, drawn by the PC | |
| Power LED, resolution notice, CEC, picture mode (SmartImage), audio input | |
| Adaptive Sync, Smart Crosshair, Stark Shadow Boost, Smart Sniper | |
| OLED care: Pixel Orbiting, Screen Saver, Multi-Logo Protection, Boundary / Taskbar Dimmer, Thermal Protection | Pixel refresh (a maintenance action, never run during development) |

The official app's own data flags other Evnia models as USB-DDC capable; they may work, but **I have not
tested any of them**. Reports and pull requests are welcome.

## Install

```bash
sudo apt install libusb-1.0-0        # or your distro's equivalent
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[gui]"               # drop [gui] if you only want the command line
```

Let your user talk to the devices (no root needed afterwards):

```bash
sudo cp udev/99-freevnia.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2109   # hub (input, PBP/PIP, settings)
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=0cf2   # Ambiglow LED controller
# your user must be in the "plugdev" group
```

The monitor's **USB upstream cable must be connected to this computer**.

## Use

```bash
freevnia info                                   # model, BOM, firmware, scaler (read-only)
freevnia mode pbp1                              # side by side: this PC on the left, USB-C on the right
freevnia mode pip --position lower-left --size large
freevnia mode off                               # back to full screen

freevnia settings                               # every setting with its current value
freevnia settings smart-image fps               # change one (see `freevnia settings --help`)
freevnia settings audio-source displayport
freevnia pixel-refresh --yes                    # OLED pixel-refresh cycle (the panel is unusable while it runs)

freevnia ambiglow info                          # the monitor's own Ambiglow setting
freevnia ambiglow set --osd-mode "Color wave" --osd-color Rainbow --osd-brightness Brightest
freevnia ambiglow color "#ff8800" --zone sides  # a fixed colour of any RGB value, drawn by the PC
freevnia ambiglow off                           # LEDs off
freevnia ambiglow release                       # hand the LEDs back to the monitor

freevnia-gui                                    # the window shown above (PBP/PIP, Ambiglow, Settings tabs)
```

A launcher for KDE/GNOME menus is in `contrib/freevnia.desktop`; `contrib/pbp-toggle.sh` toggles PBP
(handy for a global keyboard shortcut).

## Read this before you use it

* **The monitor sends its USB (KVM) to the left / main picture.** If you make *another* device the main
  source, this computer loses the hub and **cannot switch back** - you will need the remote. The GUI asks
  for confirmation before changing the main source.
* The GUI always knows whether PBP/PIP is active. Mode, corner and size read back only for what you set
  from FreEvnia; what you choose with the **remote cannot be read** (the monitor does not report it).
* The monitor sometimes answers a read with its *previous* reply; FreEvnia asks again until the answer is
  consistent, so loading the Settings tab takes a few seconds.
* **Do not write the Ambiglow code `E2A038`**: it is the factory reset of the Ambiglow settings.
* This writes to your monitor's configuration. It uses the same commands as the official app, but it is
  alpha software: **use at your own risk**, no warranty (see [LICENSE](LICENSE)).

## Roadmap

* Verify and enable PBP 2 / 3, picture swap, HDMI sources.
* Confirm follow audio with a camera.
* Other Evnia models; a proper list of tested hardware.
* Packaging (PyPI, AUR, Flatpak) and a KDE Plasma widget.

## Related projects

* [tomasf/evnia](https://github.com/tomasf/evnia) - macOS (Swift) library for the 49M2C8900 Ambiglow LEDs over USB;
  the LED colour buffer protocol used here comes from it.

## License

MIT - see [LICENSE](LICENSE). [README en español](README.es.md).

## Download (no build needed)

Grab one of these from the [Releases](https://github.com/satanasinc/FreEvnia/releases) page:

- **`FreEvnia-x86_64.AppImage`** - any x86_64 distro: `chmod +x FreEvnia-x86_64.AppImage && ./FreEvnia-x86_64.AppImage` opens the GUI; with arguments it is the CLI (`./FreEvnia-x86_64.AppImage mode pip --loc 1`).
- **`freevnia_<version>_all.deb`** - Debian/Ubuntu: `sudo apt install ./freevnia_*.deb` (installs `freevnia`, `freevnia-gui` and the udev rule).
- **`FreEvnia-linux-x86_64.tar.gz`** - AppImage + `install.sh` (installs to `~/.local/bin` and sets up the udev rule).

With the AppImage you still need the udev rule once (`udev/99-freevnia.rules`, see the file header) so your user can talk to the monitor without root.

## Several computers, one monitor

The monitor connects its USB hub to one computer at a time (the one on the left/main picture), and only that computer can talk to it. Run FreEvnia on every computer and pair them once:

1. On one computer: `freevnia pair` shows a code (or open the GUI, **Pair…**). On the others: `freevnia pair CODE`, or paste it in **Pair…**.
2. That's it. Each copy looks for the others with a UDP broadcast on the LAN (UDP 47600, TCP 47601). The copy that sees the USB hub becomes the *server*; the rest forward their commands to it. When you switch the input and the hub moves to another computer, that computer's copy takes over automatically.
3. Before changing the main source the GUI lists the computers that have FreEvnia open; if the new source's computer is not running it, you lose control until you switch back with the remote.
4. `freevnia serve` runs the same logic without a window (e.g. as a systemd user service), and `freevnia mode ...` works from a computer without the hub by asking the server.

Firewall: the computer that holds the hub must accept UDP 47600 and TCP 47601 from the LAN. With ufw (the `.deb` and `install.sh` install a profile): `sudo ufw allow from 192.168.1.0/24 to any app FreEvnia` (use your own subnet). Any computer may be the one holding the hub, so open it on all of them. With firewalld: `sudo firewall-cmd --permanent --add-port=47600/udp --add-port=47601/tcp --reload`.

Security: requests are signed with a shared secret (`~/.config/freevnia/secret`) but not encrypted; use it on a trusted LAN only and don't forward the ports.
