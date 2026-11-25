# Protocol notes: DDC/CI over USB on the Philips Evnia 49M2C8900L

Everything here was observed on a **49M2C8900L, firmware 1.08** (scaler MediaTek MT9810, USB hub VIA Labs).
"Verified" means it was seen working on the real panel; the rest is marked as such.

## Why the usual DDC does not work

Over the DisplayPort / HDMI DDC channel (`ddcutil`, `i2c-dev`) this monitor answers standard MCCS reads
(brightness, colour preset, ...) and *accepts* writes to VCP `0x60` (input source) without error, but
**ignores them**. Input switching, PBP and PIP are handled over **USB**, through the monitor's VIA Labs
hub. The official Evnia Precision Center does exactly that (the app's own metadata marks this model as
`SupUsbDDC`).

## Device

| | |
|---|---|
| USB ID | `2109:8884` (VIA Labs "USB Billboard Device") |
| Bus | the monitor's USB *upstream* cable must be connected to the computer |
| Interface | none needed: plain control transfers on endpoint 0 |
| Other USB devices of the monitor | `0cf2:b20b` (ENE, HID + vendor) is the Ambiglow LED controller, not used here |

## Transport

DDC/CI frames are sent **raw** inside two vendor-specific control transfers:

| Direction | bmRequestType | bRequest | wValue | wIndex | wLength | Data |
|---|---|---|---|---|---|---|
| write | `0x40` | `0xB2` | 0 | 0 | n | the full frame, including the destination address `0x6E` |
| read | `0xC0` | `0xA3` | 0 | `0x006F` | 32 | the raw reply |

Wait about **150 ms** between a write and the read that follows it.

### Frame format

```
write frame : 6E 51 <0x80|len> <payload...> <checksum>
reply       : 6E <0x80|len> <payload...> <checksum>
checksum    : XOR of every previous byte of the frame
```

Example (captured, verified): *Get VCP 0xC8*

```
OUT  6e 51 82 01 c8 74
IN   6e 88 02 00 c8 01 ff 16 00 05 91      # reply opcode 0x02, result 0x00, VCP c8, type 1,
                                           # max 0xff16, current 0x0005 (MStar)
```

Standard commands: `01 <vcp>` Get VCP, `03 <vcp> <hi> <lo>` Set VCP.

### Manufacturer reads (Get VCP `0xFE` + arguments, ASCII reply)

| Request payload | Returns |
|---|---|
| `01 fe e9 0d 00 00` | model name (`49M2C8900L`) |
| `01 fe e1 e6 1d 00` | BOM string |
| `01 fe e1 e6 06 00` | firmware version (`1.08`) |
| `01 fe e1 e8 00 00` | scaler (`MT9810...`) |

## VCP codes used for input / PBP / PIP

All values are 16-bit (`hi`, `lo`).

| VCP | Meaning | Values |
|---|---|---|
| `0x60` | sources | low byte = **main** source, high byte = **second picture** source |
| `0xA5` | PIP/PBP mode (high byte) | `0x0000` off, `0x0100` PIP, `0x0200` PBP 1; `0x0400` PBP 2 / `0x0800` PBP 3 exist in the app's tables but are untested |
| `0xEC` | PIP geometry | high byte = position, low byte = size |
| `0xA4` | commit | write `0xFFFF` last |
| `0xF7` | capability (read-only) | `0x42` on this model |
| `0xE6` | state indicator (read-only) | `1` = full screen, `0` = PBP/PIP active (also when set from the remote) |

Source codes: main `0x0F` DisplayPort 1, `0x11` HDMI 1, `0x12` HDMI 2, `0x15` USB-C; second picture
`0x35` USB-C, `0x21` HDMI 1, `0x22` HDMI 2.
PIP position: `1` upper-right, `2` lower-right, `3` upper-left, `4` lower-left. Size: `1` small, `2` medium, `3` large.

### The sequence that works

Writing `0xA5` alone does nothing. The official software sends, in this order, with ~100 ms between steps:

1. `0xA5` = mode
2. `0xEC` = `(position << 8) | size`
3. `0x60` = `(second << 8) | main`
4. `0xA4` = `0xFFFF`

## Behaviour worth knowing

* **The KVM follows the main (left) picture.** The monitor's USB downstream ports and the control hub go to
  whichever device is on the left/main picture. If you make another device the main source, the host
  running these commands loses the hub and **cannot switch back**; use the remote.
* After you set a mode from software, `0xA5` (mode) and `0xEC` (position/size) **read back** the values you
  wrote (e.g. PIP lower-left large reads `0xA5=0x0100`, `0xEC=0x0403`), and `0xE6` tells whether PBP/PIP is active.
  Changes made with the **remote are NOT reflected** in `0xA5`/`0xEC` (they stay at the last software value, or 0):
  with a PIP set from the remote, `0xE6` = 0 and the second-source byte of `0x60` change, but `0xA5` and `0xEC` read 0.
* The reply buffer keeps the **previous** answer until the monitor prepares a new one, so a Get VCP must check that the
  reply is for the code you asked about and retry otherwise (FreEvnia does).
* Values written to `0x60` that equal the current one do nothing.

## Verification status

| Item | Status |
|---|---|
| Reads (`info`, Get VCP) | verified |
| Main source `0x15` (USB-C) | verified; DP1 verified |
| Second picture USB-C, HDMI 1, HDMI 2 | verified (HDMI 1/2 in both PBP and PIP, from the GUI; USB-C also on the OSD) |
| Main source HDMI 1 / HDMI 2 | from the app's tables, **unverified** |
| PBP 1, PIP, off | verified with a camera |
| PIP positions and sizes | verified with a camera |
| PBP 2 / PBP 3, swap (`0xF6`) | not tested |

## How this was found (so you can repeat it on another model)

1. Run the official Evnia Precision Center in a Windows VM with the monitor's `2109:8884` device passed
   through (it needs the real EDID to *show* the monitor, but it still performs its identification reads
   at start-up).
2. Capture the host USB bus with `usbmon` (`sudo modprobe usbmon; sudo cat /sys/kernel/debug/usb/usbmon/3u`)
   and look at the control transfers to the Billboard device: `0x40/0xB2` writes and `0xC0/0xA3` reads.
3. Identify the framing: the data are plain DDC/CI frames and the checksum is the XOR rule above.
4. The names and values of the PIP/PBP/source enums come from the application's .NET metadata
   (the VCP code is embedded in the type names, e.g. `VCP_A5_PIPPBPType`), and the write order from reading
   how the application builds a "set input source" request. No vendor code is included in this repository.

This is independent interoperability work, **not affiliated with Philips or TPV**.

## Ambiglow LEDs (ENE, USB `0cf2:b20b`) — verified on the 49M2C8900L under Linux

Protocol found by [tomasf/evnia](https://github.com/tomasf/evnia) (macOS, PID `0xB201`); the same
transfers work on PID `0xB20B`. Vendor control transfers on endpoint 0: read `C0 / 81 / 0 / <addr>`,
write `40 / 80 / 0 / <addr>`.

- `0xE020` and `0xE030`: write `01 00 02 04 00 05 00 00 00 02 FF 00 00 00 00 01` to take software control.
- `0xE100..0xE183`: 44 LEDs x `R G B`. Red, green and blue were seen correctly on the panel.
- Release: write back the 64-byte region `0xE020..0xE05F` that was there before taking control.
- The controller keeps showing whatever is in the colour buffer, so FreEvnia also saves and restores
  `0xE100..0xE183`.
- The OSD settings (off, the 7 presets) are **not** visible in these registers. After releasing, the LEDs
  keep the restored buffer (dark) until a preset is picked in the OSD.
- Needs the udev rule for `0cf2:b20b` (see `udev/99-freevnia.rules`).
