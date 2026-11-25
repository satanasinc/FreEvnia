"""Ambiglow LEDs of the Philips Evnia 49M2C8900L (ENE KB7730, USB 0cf2:b20b).

Protocol (vendor control transfers on endpoint 0), from the reverse engineering published at
https://github.com/tomasf/evnia (macOS, PID 0xB201) and verified on a PID 0xB20B unit under Linux:

  read  : bmRequestType 0xC0, bRequest 0x81, wValue 0, wIndex = register address
  write : bmRequestType 0x40, bRequest 0x80, wValue 0, wIndex = register address

  0xE020 / 0xE030  16-byte control block; this block takes software ownership of the LEDs
  0xE100..0xE183   44 LEDs x 3 bytes, in the order R, B, G on the unit tested (green and blue are swapped
                   compared with the macOS notes; push() takes normal (r, g, b) tuples and swaps them)
  0xE020..0xE05F   64-byte control region; writing back what was there before gives the LEDs
                   back to the monitor OSD

The OSD settings (off, the seven presets) are NOT visible in these registers, so they cannot be
read or chosen from USB. What can be done is to take over the LEDs (colours, effects, off) and to
release them again, which restores the state saved just before taking over.
"""
import colorsys
import os
import time
from pathlib import Path

import usb.core

VID = 0x0CF2
PIDS = (0xB20B, 0xB201)
LED_COUNT = 44
REQ_READ, REQ_WRITE = 0x81, 0x80
ADDR_CTRL_A, ADDR_CTRL_B, ADDR_FRAME = 0xE020, 0xE030, 0xE100
REGION_LEN = 64
FRAME_LEN = LED_COUNT * 3
CAPTURE_BLOCK = bytes.fromhex("01000204000500000002ff0000000001")
# Region seen on the test unit with the OSD Ambiglow in its normal state, used if no snapshot exists.
DEFAULT_BASELINE = bytes.fromhex(
    "00000000000500000000000000000000" "00000000000500000000000000000000"
    "00000000000000000000000000000000" "00000000000000000000000000000000")
BASELINE_FILE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "freevnia" / "ambiglow_baseline.hex"

# LED slots seen from the front (from the tomasf/evnia notes).
ZONES = {
    "all": range(0, 44),
    "sides": list(range(0, 4)) + list(range(20, 24)),
    "top": range(3, 21),
    "center": range(24, 44),
}

COLORS = {
    "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "orange": (255, 100, 0), "purple": (128, 0, 255), "pink": (255, 60, 140),
    "warm": (255, 160, 60),
}


class AmbiglowNotFound(Exception):
    """The ENE LED controller is not visible (the monitor's USB cable is not on this computer)."""


def find_device():
    for pid in PIDS:
        dev = usb.core.find(idVendor=VID, idProduct=pid)
        if dev is not None:
            return dev
    raise AmbiglowNotFound(
        "Ambiglow controller 0cf2:b20b not found. Is the monitor's USB upstream cable connected to "
        "this computer, and is this computer on the left/main picture?")


def read(dev, addr, n):
    return bytes(dev.ctrl_transfer(0xC0, REQ_READ, 0, addr, n))


def write(dev, addr, data):
    dev.ctrl_transfer(0x40, REQ_WRITE, 0, addr, bytes(data))


def is_captured(dev) -> bool:
    """True if software currently owns the LEDs (the capture block is in place).

    The monitor itself also sets byte 0 to 1 in its own "follow video" mode (byte 1 = 0x0b), so byte 0 alone
    is not enough: our capture block has byte 1 = 0 (effect "Off")."""
    b = read(dev, ADDR_CTRL_A, 2)
    return b[0] == 1 and b[1] == 0


def capture(dev):
    """Take ownership of the LEDs, saving the previous region so release() can restore it."""
    if not is_captured(dev):
        region = read(dev, ADDR_CTRL_A, REGION_LEN) + read(dev, ADDR_FRAME, FRAME_LEN)
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(region.hex())
    write(dev, ADDR_CTRL_A, CAPTURE_BLOCK)
    write(dev, ADDR_CTRL_B, CAPTURE_BLOCK)


def release(dev, ddc=None):
    """Give the LEDs back to the monitor.

    Best: with the DDC device (usbddc.find_device()), clear the colour buffer and write the monitor's own
    Ambiglow mode back to itself; the monitor then reconfigures the LED controller by itself (verified with a
    camera: a software blue goes back to the OSD state). Fallback without DDC: restore the control region and
    colours saved by capture(), which can be stale if the OSD was touched in between."""
    if ddc is not None:
        try:
            from . import usbddc as u
            mode = u.get_vcp(ddc, DDC_MODE)["cur"]
            write(dev, ADDR_FRAME, bytes(FRAME_LEN))
            time.sleep(0.01)
            u.set_vcp(ddc, DDC_MODE, mode)
            time.sleep(0.5)
            return
        except (ValueError, usb.core.USBError):
            pass
    try:
        saved = bytes.fromhex(BASELINE_FILE.read_text().strip())
        if len(saved) != REGION_LEN + FRAME_LEN or saved[0] == 1:
            raise ValueError
    except (OSError, ValueError):
        saved = DEFAULT_BASELINE + bytes(FRAME_LEN)
    write(dev, ADDR_FRAME, saved[REGION_LEN:])
    time.sleep(0.01)
    write(dev, ADDR_CTRL_A, saved[:REGION_LEN])


def push(dev, leds):
    """Write a full frame: a list of 44 (r, g, b) tuples."""
    if len(leds) != LED_COUNT:
        raise ValueError(f"a frame needs {LED_COUNT} LEDs, got {len(leds)}")
    write(dev, ADDR_FRAME, bytes(c for led in leds for c in (led[0], led[2], led[1])))   # LED order is R, B, G


def scale(rgb, brightness):
    """brightness 0..100 (%)."""
    f = max(0, min(100, brightness)) / 100
    return tuple(round(c * f) for c in rgb)


def solid(dev, rgb, zone="all", brightness=100, base=None):
    """Light `zone` with one colour; the rest stays black (or `base` if given)."""
    capture(dev)
    frame = list(base) if base else [(0, 0, 0)] * LED_COUNT
    for i in ZONES[zone]:
        frame[i] = scale(rgb, brightness)
    push(dev, frame)


def off(dev):
    """All LEDs dark, but still under software control (release() gives control back to the OSD)."""
    capture(dev)
    push(dev, [(0, 0, 0)] * LED_COUNT)


def parse_color(text):
    """Colour name or #RRGGBB / RRGGBB."""
    t = text.strip().lower()
    if t in COLORS:
        return COLORS[t]
    t = t.lstrip("#")
    if len(t) == 6:
        try:
            return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    raise ValueError(f"unknown colour {text!r} (use a name: {', '.join(COLORS)} or #RRGGBB)")


# --- effects (blocking loops; the caller stops them with Ctrl-C / a flag) ------------------

def rainbow(dev, speed=1.0, brightness=100, stop=lambda: False):
    capture(dev)
    t = 0.0
    while not stop():
        frame = []
        for i in range(LED_COUNT):
            r, g, b = colorsys.hsv_to_rgb((i / LED_COUNT + t) % 1.0, 1.0, 1.0)
            frame.append(scale((round(r * 255), round(g * 255), round(b * 255)), brightness))
        push(dev, frame)
        t = (t + 0.01 * speed) % 1.0
        time.sleep(0.03)


def breathe(dev, rgb, speed=1.0, brightness=100, stop=lambda: False):
    import math
    capture(dev)
    t = 0.0
    while not stop():
        level = (math.sin(t) + 1) / 2
        push(dev, [scale(rgb, brightness * (0.08 + 0.92 * level))] * LED_COUNT)
        t += 0.08 * speed
        time.sleep(0.03)


# --- what the monitor OSD is currently set to (read-only) -----------------------------------
# From the official library (MNTLightEffect_E, Bright_E): byte 1 of each 16-byte block at 0xE020 is the
# effect, byte 9 the brightness. Writing these bytes does NOT change the monitor (verified with a camera).
OSD_MODES = {
    0: "Off", 1: "Static", 2: "Static rainbow", 3: "Color shift", 4: "Color shift rainbow",
    5: "Color wave", 6: "Color wave rainbow", 7: "Color breathing", 8: "Color breathing rainbow",
    9: "Follow audio", 10: "Follow audio rainbow", 11: "Follow video", 12: "Starry night",
    13: "Starry night rainbow", 14: "User defined",
}
OSD_BRIGHTNESS = {0: "Brightest", 2: "Brighter", 4: "Bright"}


def osd_state(dev):
    """Read the monitor's own Ambiglow setting: a list of (mode name, brightness name) per active block."""
    if is_captured(dev):
        return None          # FreEvnia has the LEDs; the OSD setting is not on display
    region = read(dev, ADDR_CTRL_A, REGION_LEN)
    out = []
    for i in range(0, REGION_LEN, 16):
        blk = region[i:i + 16]
        if blk[1] == 0:
            continue          # an "Off" block has no brightness worth showing
        out.append((OSD_MODES.get(blk[1], f"mode {blk[1]}"), OSD_BRIGHTNESS.get(blk[9], f"level {blk[9]}")))
    return out


# --- the monitor's own Ambiglow settings, over DDC/CI (extended VCP codes) ---------------------
# Names from the official library. These are the values the OSD stores. Do NOT write E2A038 ("Ambiglow Set"):
# in the official app it is part of EffectReset() and restores the factory settings.
DDC_MODE, DDC_COLOR, DDC_POSITION, DDC_BRIGHTNESS, DDC_SPEED = 0xE2A019, 0xE2A01A, 0xE2A01B, 0xE2A01C, 0xE2A01D
DDC_MODES = {0: "Off", 1: "Follow video", 2: "Follow audio", 3: "Color shift", 4: "Color wave",
             5: "Color breathing", 6: "Starry night", 7: "Static"}
DDC_COLORS = {0: "Rainbow", 1: "White", 2: "Red", 3: "Rose", 4: "Magenta", 5: "Violet", 6: "Blue",
              7: "Azure", 8: "Cyan", 9: "Aqua", 10: "Green", 11: "Pear", 12: "Yellow", 13: "Orange"}
DDC_POSITIONS = {0: "All zones", 2: "Central", 4: "3-sided"}      # the ones this monitor advertises
DDC_BRIGHTNESS_LEVELS = {0: "Bright", 1: "Brighter", 2: "Brightest"}
DDC_SPEEDS = {0: "Low", 1: "Normal", 2: "High"}
DDC_FIELDS = {"mode": (DDC_MODE, DDC_MODES), "color": (DDC_COLOR, DDC_COLORS), "position": (DDC_POSITION, DDC_POSITIONS),
              "brightness": (DDC_BRIGHTNESS, DDC_BRIGHTNESS_LEVELS), "speed": (DDC_SPEED, DDC_SPEEDS)}


def ddc_settings(ddc) -> dict:
    """{'mode': 1, 'color': 0, ...} as stored in the monitor."""
    from . import usbddc as u
    return {k: u.get_vcp(ddc, code)["cur"] for k, (code, _) in DDC_FIELDS.items()}


def ddc_describe(values: dict) -> str:
    return " · ".join(DDC_FIELDS[k][1].get(v, str(v)) for k, v in values.items())


def ddc_apply(ddc, **kw):
    """Write some of mode/color/position/brightness/speed (values are the raw numbers). Order matters little;
    the mode goes last."""
    from . import usbddc as u
    for k in ("position", "brightness", "speed", "color", "mode"):
        if kw.get(k) is not None:
            code, table = DDC_FIELDS[k]
            if kw[k] not in table:
                raise ValueError(f"{k}: {kw[k]} is not one of {sorted(table)}")
            u.set_vcp(ddc, code, kw[k])
            time.sleep(0.3)
