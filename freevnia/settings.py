"""Monitor settings (Power LED, resolution notice, CEC and OLED panel care) over DDC/CI-over-USB.

Codes and allowed values come from the monitor's own capability string (Get Capabilities, 0xF3) and
from the names in the official Evnia Precision Center. Standard codes are one byte (0xF2, 0xE9);
the Philips extended ones are three bytes (0xE2A0xx) and are read/written like any other VCP code
with the 3-byte code in place of the 1-byte one. All of these were read back after writing on a
49M2C8900L (firmware 1.08).
"""
from dataclasses import dataclass, field

from . import usbddc as u


@dataclass(frozen=True)
class Setting:
    key: str
    code: int
    label: str
    group: str                       # "general" | "image" | "game" | "panel"
    values: dict = field(default_factory=dict)   # raw value -> label (only the values the monitor accepts)
    note: str = ""
    expect_max: int = None            # largest value in the capability string, to reject stale answers


def _levels(*vals, off=True, top=""):
    out = {}
    for v in vals:
        out[v] = "Off" if (v == 0 and off) else f"Level {v}"
    if top and vals:
        out[vals[-1]] += f" ({top})"
    return out


SETTINGS = (
    # --- general ---
    Setting("power-led", 0xF2, "Power LED brightness", "general",
            {0: "Level 0", 1: "Level 1", 2: "Level 2", 3: "Level 3", 4: "Level 4"},
            "levels 0-4 as defined by the monitor; the labels are the firmware's, not verified on the LED"),
    Setting("resolution-notice", 0xE9, "Resolution notice", "general", {0: "Off", 2: "On"}),
    Setting("cec", 0xE2A017, "CEC (HDMI control)", "general", {0: "Off", 1: "On"}),
    # --- image and audio ---
    Setting("smart-image", 0xDC, "Picture mode (SmartImage)", "image",
            {0: "Standard", 17: "Console", 81: "Illustrator", 1: "FPS", 6: "Racing", 7: "RTS", 3: "Movie",
             11: "Low blue", 14: "EasyRead", 8: "Economy", 4: "Game 1", 5: "Game 2"}),
    Setting("audio-source", 0xE0, "Audio input", "image",
            {1: "HDMI 1", 2: "HDMI 2", 3: "DisplayPort", 5: "USB-C"},
            "which input's audio comes out of the monitor", expect_max=5),
    # --- gaming ---
    Setting("adaptive-sync", 0xE2A040, "Adaptive Sync", "game", {0: "Off", 1: "On"}, expect_max=1),
    Setting("smart-crosshair", 0xE2A004, "Smart Crosshair", "game", {0: "Off", 1: "On", 2: "Smart Crosshair"},
            "draws a fixed crosshair in the centre of the screen", expect_max=2),
    Setting("stark-shadow-boost", 0xE2A044, "Stark Shadow Boost", "game",
            {0: "Off", 1: "Level 1", 2: "Level 2", 3: "Level 3"},
            "brightens dark areas so things hiding in shadows are easier to see", expect_max=3),
    Setting("smart-sniper", 0xE2A006, "Smart Sniper (zoom)", "game",
            {0: "Off", 1: "1x", 2: "1.5x", 3: "2x"},
            "a magnified window of the screen centre, to aim at distant targets", expect_max=3),
    Setting("sniper-position", 0xE2A025, "Smart Sniper position", "game", {0: "Center", 1: "Top"},
            "where the magnified window is placed", expect_max=1),
    # --- OLED panel care ---
    Setting("pixel-orbiting", 0xE2A034, "Pixel Orbiting", "panel",
            {0: "Off", 2: "Slow", 3: "Normal", 4: "Fast"}, "shifts the picture a few pixels now and then"),
    Setting("screen-saver", 0xE2A035, "Screen Saver", "panel", {0: "Off", 2: "Slow", 3: "Fast"}),
    Setting("multi-logo", 0xE2A048, "Multi-Logo Protection", "panel", _levels(0, 1, 2, top="max")),
    Setting("boundary-dimmer", 0xE2A049, "Boundary Dimmer", "panel", _levels(0, 1, 2, 3, top="max")),
    Setting("taskbar-dimmer", 0xE2A04A, "Taskbar Dimmer", "panel", _levels(0, 1, 2, 3, top="max")),
    Setting("thermal-protection", 0xE2A04B, "Thermal Protection", "panel", {0: "Off", 1: "On"}),
    Setting("auto-warning", 0xE2A043, "Auto Warning", "panel", {0: "Off", 1: "On"}),
)
BY_KEY = {s.key: s for s in SETTINGS}

# Pixel Refresh is an OLED maintenance cycle, not a setting: capability E2A036 only accepts 1.
PIXEL_REFRESH = 0xE2A036
# Time since the last pixel refresh: hours = (E2A050 << 8) | E2A051, minutes = E2A053.
TIME_SINCE_REFRESH = (0xE2A050, 0xE2A051, 0xE2A053)


def read(dev, s: Setting) -> int:
    mx = s.expect_max
    if mx is None and s.code > 0xFF:
        mx = max(s.values)            # extended codes: the capability string lists every accepted value
    return u.get_vcp(dev, s.code, expect_max=mx)["cur"]


def read_all(dev) -> dict:
    """{key: raw value, or None if the monitor does not answer for it}"""
    out = {}
    for s in SETTINGS:
        try:
            out[s.key] = read(dev, s)
        except (ValueError, OSError):
            out[s.key] = None
    return out


def write(dev, s: Setting, value: int) -> None:
    if value not in s.values:
        raise ValueError(f"{s.key}: {value} is not one of {sorted(s.values)}")
    u.set_vcp(dev, s.code, value)


def label(s: Setting, value) -> str:
    return "?" if value is None else s.values.get(value, str(value))


def parse_value(s: Setting, text: str) -> int:
    """Accept the raw number or the label (case-insensitive, 'level 2' or just '2')."""
    t = text.strip().lower()
    for v, name in s.values.items():
        if t == name.lower() or t == name.lower().split(" (")[0]:
            return v
    try:
        return int(t, 0)
    except ValueError:
        raise ValueError(f"{s.key}: unknown value {text!r}; choose from "
                         + ", ".join(f"{v}={n}" for v, n in s.values.items()))


def time_since_pixel_refresh(dev):
    """(hours, minutes) since the last pixel refresh, or None if it cannot be read."""
    try:
        hi, lo, mi = (u.get_vcp(dev, c)["cur"] for c in TIME_SINCE_REFRESH)
    except (ValueError, OSError):
        return None
    return (hi << 8) | lo, mi


def pixel_refresh(dev) -> None:
    """Start the OLED pixel-refresh cycle. NOT a setting: it is a maintenance action that takes the
    panel out of use for a while; it was not run during development."""
    u.set_vcp(dev, PIXEL_REFRESH, 1)
