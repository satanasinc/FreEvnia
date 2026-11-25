"""freevnia command line: read-only `info`/`get`, and `mode`/`set` which WRITE to the monitor."""
import argparse
import sys
import time

import usb.core

from . import ambiglow as amb
from . import settings as st
from . import usbddc as u


def to_int(s: str) -> int:
    return int(s, 0)


def run_settings(a):
    try:
        dev = u.find_device()
        if a.cmd == "pixel-refresh":
            if not a.yes:
                sys.exit("Pixel refresh is an OLED maintenance cycle that takes the panel out of use for a "
                         "while. Run again with --yes to start it.")
            st.pixel_refresh(dev)
            print("pixel refresh started")
        elif a.key is None:
            groups = {"general": "General", "panel": "OLED panel care"}
            cur = st.read_all(dev)
            for g, title in groups.items():
                print(f"{title}:")
                for s in st.SETTINGS:
                    if s.group == g:
                        print(f"  {s.key:20s} {s.label:24s} {st.label(s, cur[s.key])}")
            t = st.time_since_pixel_refresh(dev)
            if t:
                print(f"Time since the last pixel refresh: {t[0]} h {t[1]} min")
        elif a.value is None:
            s = st.BY_KEY[a.key]
            print(f"{s.label}: {st.label(s, st.read(dev, s))}   (values: "
                  + ", ".join(f"{v}={n}" for v, n in s.values.items()) + ")")
        else:
            s = st.BY_KEY[a.key]
            v = st.parse_value(s, a.value)
            st.write(dev, s, v)
            time.sleep(0.4)
            print(f"{s.label}: {st.label(s, st.read(dev, s))}")
    except u.MonitorNotFound as e:
        sys.exit(str(e))
    except (ValueError, usb.core.USBError) as e:
        sys.exit(f"error talking to the monitor: {e}")


def run_ambiglow(a):
    try:
        dev = amb.find_device()
        if a.action == "status":
            print("software control" if amb.is_captured(dev) else "monitor OSD control")
        elif a.action == "info":
            state = amb.osd_state(dev)
            if state is None:
                print("FreEvnia has the LEDs (use `freevnia ambiglow release` to see the OSD setting)")
            elif not state:
                print("OSD setting: Off")
            else:
                for i, (mode, bright) in enumerate(state, 1):
                    print(f"OSD setting, block {i}: {mode}, brightness {bright}")
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
    se = sub.add_parser("settings", help="list the monitor settings, or set one: settings <key> <value>")
    se.add_argument("key", nargs="?", choices=list(st.BY_KEY))
    se.add_argument("value", nargs="?")
    pr = sub.add_parser("pixel-refresh", help="start the OLED pixel-refresh cycle (maintenance action)")
    pr.add_argument("--yes", action="store_true", help="confirm")
    am = sub.add_parser("ambiglow", help="Ambiglow LEDs: info | color | off | release | rainbow | breathe | status")
    am.add_argument("action", choices=["color", "off", "release", "rainbow", "breathe", "status", "info"])
    am.add_argument("value", nargs="?", help="colour name or #RRGGBB (for color / breathe)")
    am.add_argument("--zone", choices=list(amb.ZONES), default="all")
    am.add_argument("--brightness", type=int, default=100, help="0-100 %%")
    am.add_argument("--speed", type=float, default=1.0, help="effect speed (default 1)")
    a = ap.parse_args(argv)

    if a.cmd == "ambiglow":
        return run_ambiglow(a)
    if a.cmd in ("settings", "pixel-refresh"):
        return run_settings(a)
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
