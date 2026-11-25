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

## Ambiglow LEDs

Two separate things.

### 1. The monitor's own setting, over DDC (every mode works from here)

Extended VCP codes, read and written like the settings below: `E2A019` mode (0 off, 1 follow video, 2 follow audio,
3 color shift, 4 color wave, 5 color breathing, 6 starry night, 7 static), `E2A01A` colour (0 rainbow, 1 white,
2 red, 3 rose, 4 magenta, 5 violet, 6 blue, 7 azure, 8 cyan, 9 aqua, 10 green, 11 pear, 12 yellow, 13 orange),
`E2A01B` position (0 all zones, 2 central, 4 3-sided), `E2A01C` brightness (0 bright, 1 brighter, 2 brightest),
`E2A01D` speed (0 low, 1 normal, 2 high). **The monitor draws every mode itself** (verified with a camera: colour
shift and wave animate on the wall with nothing written by the host). Follow audio reacts to the audio the
monitor receives; it was not confirmed with a camera.

* **Do not write `E2A038` ("Ambiglow Set")**: in the official app it belongs to `EffectReset()` and restores the
  factory Ambiglow settings (it did on the test unit; the previous values had to be written back).
* The monitor mirrors the setting into the LED controller's control region (below): byte 1 of each 16-byte block at
  `E020` is the effect (the official `MNTLightEffect_E`: 1 static, 2 static rainbow, 3 color shift, 4 color shift
  rainbow, 5 wave, 7 breathing, 9 follow audio, 11 follow video, 12 starry night, ...). Writing those bytes yourself
  does not change anything: use DDC.

### 2. Fixed colours of any RGB value, drawn by the host (ENE controller `0cf2:b20b`)

Transport (from [tomasf/evnia](https://github.com/tomasf/evnia), macOS, PID `0xB201`; the same transfers work on
PID `0xB20B` under Linux): vendor control transfers on endpoint 0, read `C0 / 81 / 0 / <addr>`, write
`40 / 80 / 0 / <addr>`.

- `0xE020` and `0xE030`: write `01 00 02 04 00 05 00 00 00 02 ff 00 00 00 00 01` to take the LEDs for the host.
- `0xE100..0xE183`: 44 LEDs x 3 bytes, **in the order R, B, G** on the unit tested (green and blue swapped
  compared with the macOS notes). The controller shows whatever is in this buffer while it is in host state.
- Giving the LEDs back: clear the buffer, **clear the capture leftovers** (below) and write the monitor's mode
  back to itself over DDC so it reconfigures the controller.

### Capture leftovers (important)

The monitor, when the mode is changed (remote or DDC), only rewrites a few bytes of those blocks (mode, speed,
brightness) and **leaves byte 0 (= 1, "the host draws"), byte 3 (= 4), byte 10 (= 0xff) and byte 15 (= 1) as they
were**. With those leftovers the controller stays in "the host draws" state and the modes chosen with the remote
control **or over DDC show nothing** (this was what made every effect look "dark" at first, and then broke the
remote's own follow-video mode on the test unit). `freevnia.ambiglow.scrub()` clears bytes 0, 3, 10 and 15 of every
block; the clean native state is `00 <mode> 00 00 00 05 00 00 00 <brightness> 00 00 00 00 00 00`.

## Settings: Power LED, resolution notice, CEC, OLED panel care (verified read and write)

The monitor's capability string (`Get Capabilities`, request `0xF3`, 1473 bytes in 32-byte chunks, offset in the
request) lists the supported VCP codes. Philips extended codes appear as **three bytes**, e.g. `E2A017(00 01)`.
They are read and written like any other VCP code, with the 3-byte code instead of the 1-byte one:

```
Get VCP : 01 e2 a0 17            reply 02 00 e2 01 <max hi> <max lo> <cur hi> <cur lo>
Set VCP : 03 e2 a0 17 <hi> <lo>
```

The reply only echoes the first byte (`e2`), so a stale answer for another extended code looks valid: ask again
and accept the value only when two consecutive answers agree (what `freevnia.usbddc.get_vcp` does).

| Setting | Code | Values |
|---|---|---|
| Power LED | `0xF2` | 0-4 |
| Resolution notice | `0xE9` | 0 off, 2 on |
| CEC | `0xE2A017` | 0 off, 1 on |
| Pixel Orbiting | `0xE2A034` | 0 off, 2 slow, 3 normal, 4 fast |
| Screen Saver | `0xE2A035` | 0 off, 2 slow, 3 fast |
| Multi-Logo Protection | `0xE2A048` | 0-2 |
| Boundary Dimmer | `0xE2A049` | 0-3 |
| Taskbar Dimmer | `0xE2A04A` | 0-3 |
| Thermal Protection | `0xE2A04B` | 0 off, 1 on |
| Auto Warning | `0xE2A043` | 0 off, 1 on |
| Time since last pixel refresh | `0xE2A050` / `51` / `53` | hours = (50 << 8) \| 51, minutes = 53 |
| Pixel Refresh (action) | `0xE2A036` | only `1` (starts a maintenance cycle; **not run during development**) |

Names of the dimmer / multi-logo levels are not known; only the numbers are. The OLED working-time and counter
codes (`E2A04D`-`4F`, `E2A054`, `E2A055`) answer with the default (`cur=0, max=255`) and are not exposed.

### Picture mode, audio input and gaming settings (verified read; writes verified with a visible change on the crosshair)

| Setting | Code | Values (from the capability string) |
|---|---|---|
| Picture mode (SmartImage) | `0xDC` | 0 Standard, 1 FPS, 3 Movie, 4 Game 1, 5 Game 2, 6 Racing, 7 RTS, 8 Economy, 11 Low blue, 14 EasyRead, 17 Console, 81 Illustrator (`0x20-0x24`, `0x30`, `0xE2` are also advertised and unnamed) |
| Audio input | `0xE0` | 1 HDMI 1, 2 HDMI 2, 3 DisplayPort, 5 USB-C |
| Adaptive Sync | `0xE2A040` | 0 off, 1 on |
| Smart Crosshair | `0xE2A004` | 0 off, 1 on, 2 smart crosshair (a fixed crosshair drawn in the centre of the screen) |
| Stark Shadow Boost | `0xE2A044` | 0 off, 1-3 (brightens dark areas) |
| Smart Sniper zoom | `0xE2A006` | 0 off, 1 = 1x, 2 = 1.5x, 3 = 2x (magnified window of the screen centre) |
| Smart Sniper position | `0xE2A025` | 0 center, 1 top |

The monitor often answers a read with the *previous* reply (for extended codes the reply only echoes `e2`), so
`get_vcp` can be given `expect_max`, the largest value in the capability string, and asks again when the
answer's maximum does not match.
