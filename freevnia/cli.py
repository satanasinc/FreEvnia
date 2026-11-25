"""freevnia command line: read-only `info`/`get`, and `mode`/`set` which WRITE to the monitor."""
import argparse
import sys

import usb.core

from . import ambiglow as amb
from . import usbddc as u


def to_int(s: str) -> int:
    return int(s, 0)


def run_ambiglow(a):
    try:
        dev = amb.find_device()
        if a.action == "status":
            print("software control" if amb.is_captured(dev) else "monitor OSD control")
        elif a.action == "color":
            if not a.value:
                sys.exit("color needs a colour (name or #RRGGBB)")
            amb.solid(dev, amb.parse_color(a.value), a.zone, a.brightness)
        elif a.action == "off":
            amb.off(dev)
        elif a.action == "release":
            amb.release(dev)
        elif a.action in ("rainbow", "breathe"):
            try:
                if a.action == "rainbow":
                    amb.rainbow(dev, a.speed, a.brightness)
                else:
                    amb.breathe(dev, amb.parse_color(a.value or "white"), a.speed, a.brightness)
            except KeyboardInterrupt:
                pass
            amb.release(dev)
    except amb.AmbiglowNotFound as e:
        sys.exit(str(e))
    except (ValueError, usb.core.USBError) as e:
        sys.exit(f"error talking to the Ambiglow controller: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="freevnia", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="model, BOM, firmware, scaler (read-only)")
    g = sub.add_parser("get", help="read a VCP code (read-only)")
    g.add_argument("code", type=to_int)
    s = sub.add_parser("set", help="WRITE a raw VCP value")
    s.add_argument("code", type=to_int)
    s.add_argument("value", type=to_int)
    s.add_argument("--yes", action="store_true", help="confirm the write")
    m = sub.add_parser("mode", help="off | pbp1 | pip  (the main source is the left picture)")
    m.add_argument("name", choices=list(u.MODES))
    m.add_argument("--main", choices=list(u.SRC_MAIN), default="dp1")
    m.add_argument("--sub", choices=list(u.SRC_SUB), default="usbc")
    m.add_argument("--size", choices=list(u.PIP_SIZE), default="medium")
    m.add_argument("--position", choices=list(u.PIP_POSITION), default="upper-right")
    am = sub.add_parser("ambiglow", help="Ambiglow LEDs: color | off | release | rainbow | breathe | status")
    am.add_argument("action", choices=["color", "off", "release", "rainbow", "breathe", "status"])
    am.add_argument("value", nargs="?", help="colour name or #RRGGBB (for color / breathe)")
    am.add_argument("--zone", choices=list(amb.ZONES), default="all")
    am.add_argument("--brightness", type=int, default=100, help="0-100 %%")
    am.add_argument("--speed", type=float, default=1.0, help="effect speed (default 1)")
    a = ap.parse_args(argv)

    if a.cmd == "ambiglow":
        return run_ambiglow(a)
    try:
        dev = u.find_device()
        if a.cmd == "info":
            for label, args in u.INFO_QUERIES:
                try:
                    print(f"{label:9s}: {u.vendor_str(dev, bytes.fromhex(args))}")
                except Exception as e:
                    print(f"{label:9s}: error {e}")
        elif a.cmd == "get":
            r = u.get_vcp(dev, a.code)
            print(f"VCP 0x{r['code']:02x}: current={r['cur']} (0x{r['cur']:04x}) max={r['max']} type={r['type']}")
        elif a.cmd == "set":
            if not a.yes:
                sys.exit("Refusing to write without --yes.")
            u.set_vcp(dev, a.code, a.value)
            print(f"sent Set VCP 0x{a.code:02x} = {a.value}")
        elif a.cmd == "mode":
            u.apply_mode(dev, u.MODES[a.name], u.SRC_MAIN[a.main], u.SRC_SUB[a.sub],
                         u.PIP_SIZE[a.size], u.PIP_POSITION[a.position])
            print(f"mode {a.name}: main={a.main} second={a.sub}")
    except u.MonitorNotFound as e:
        sys.exit(str(e))
    except (ValueError, usb.core.USBError) as e:
        sys.exit(f"error talking to the monitor: {e}")


if __name__ == "__main__":
    main()
