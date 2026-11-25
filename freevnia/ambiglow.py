"""Ambiglow LEDs of the Philips Evnia 49M2C8900L (ENE KB7730, USB 0cf2:b20b).

Protocol (vendor control transfers on endpoint 0), from the reverse engineering published at
https://github.com/tomasf/evnia (macOS, PID 0xB201) and verified on a PID 0xB20B unit under Linux:

  read  : bmRequestType 0xC0, bRequest 0x81, wValue 0, wIndex = register address
  write : bmRequestType 0x40, bRequest 0x80, wValue 0, wIndex = register address

  0xE020 / 0xE030  16-byte control block; this block takes software ownership of the LEDs
  0xE100..0xE183   44 LEDs x (R, G, B)
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
    """True if software currently owns the LEDs (the capture block is in place)."""
    return read(dev, ADDR_CTRL_A, 1)[0] == 1


def capture(dev):
    """Take ownership of the LEDs, saving the previous region so release() can restore it."""
    if not is_captured(dev):
        region = read(dev, ADDR_CTRL_A, REGION_LEN) + read(dev, ADDR_FRAME, FRAME_LEN)
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(region.hex())
    write(dev, ADDR_CTRL_A, CAPTURE_BLOCK)
    write(dev, ADDR_CTRL_B, CAPTURE_BLOCK)


def release(dev):
    """Give the LEDs back to the monitor OSD (restores the region and colours saved by capture()).

    The controller keeps showing whatever is in the colour buffer, so the buffer is restored too
    (black if nothing was saved). If the OSD look does not come back, pick any Ambiglow preset in
    the OSD: it rewrites the colours."""
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
    write(dev, ADDR_FRAME, bytes(c for led in leds for c in led))


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
