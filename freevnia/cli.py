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
            groups = {"general": "General", "image": "Image and audio", "game": "Gaming", "panel": "OLED panel care"}
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


def _ddc_or_none():
    try:
        return u.find_device()
    except u.MonitorNotFound:
        return None


def run_ambiglow(a):
    try:
        dev = amb.find_device()
        if a.action == "status":
            print("software control" if amb.is_captured(dev) else "monitor OSD control")
        elif a.action == "info":
            vals = amb.ddc_settings(u.find_device())
            print("Monitor Ambiglow setting: " + amb.ddc_describe(vals))
            if amb.is_captured(dev):
                print("(FreEvnia has the LEDs right now; `freevnia ambiglow release` gives them back)")
        elif a.action == "set":
            def pick(table, text):
                if text is None:
                    return None
                for k, v in table.items():
                    if v.lower() == text.lower() or str(k) == text:
                        return k
                raise ValueError(f"{text!r}: choose from " + ", ".join(table.values()))
            kw = {f: pick(amb.DDC_FIELDS[f][1], getattr(a, "osd_" + f)) for f in amb.DDC_FIELDS}
            if all(v is None for v in kw.values()):
                sys.exit("nothing to set: use --osd-mode / --osd-color / --osd-position / --osd-brightness / --osd-speed")
            amb.apply_osd(u.find_device(), dev, **kw)
            print("Monitor Ambiglow setting: " + amb.ddc_describe(amb.ddc_settings(u.find_device())))
        elif a.action == "color":
            if not a.value:
                sys.exit("color needs a colour (name or #RRGGBB)")
            amb.solid(dev, amb.parse_color(a.value), a.zone, a.brightness)
        elif a.action == "off":
            amb.off(dev)
        elif a.action == "release":
            amb.release(dev, _ddc_or_none())
    except amb.AmbiglowNotFound as e:
        sys.exit(str(e))
    except u.MonitorNotFound as e:
        sys.exit(str(e))
    except (ValueError, usb.core.USBError) as e:
        sys.exit(f"error talking to the Ambiglow controller: {e}")


def _local_hub():
    from . import backend
    return backend.hub_present()


def run_pair(a):
    import time
    from . import net
    node = net.Node()
    if a.pin:
        try:
            host = node.pair_with(a.pin)
        except (ValueError, RuntimeError) as e:
            sys.exit(str(e))
        print(f"Paired with {host}.")
        return
    pin = node.open_pairing()
    print(f"PIN: {pin}   (type it on the other computer: freevnia pair {pin}, or Pair… in the window; valid 2 minutes)", flush=True)
    try:
        while node._pairing_active():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    done = node.pairing_done()
    node.close_pairing()
    print("Paired." if done else "Pairing closed without a new computer.")


def run_serve():
    import time
    from . import net
    node = net.Node()
    node.start()
    print(f"FreEvnia server on {node.name}; to add another computer run `freevnia pair` here  (Ctrl+C to stop)")
    last = None
    try:
        while True:
            d = node.describe()
            if d != last:
                print(time.strftime("%H:%M:%S"), d, flush=True)
                last = d
            time.sleep(2)
    except KeyboardInterrupt:
        node.stop()


def run_mode_remote(a):
    """This computer does not hold the USB hub: ask the computer that does."""
    from . import net
    node = net.Node()
    if not node._discover(wait=1.5):
        sys.exit("This computer has no access to the monitor and no paired FreEvnia server answered." +
                 (" A server was found with another pairing code: use `freevnia pair`." if node.unpaired else ""))
    try:
        node.call("apply", a.name, u.PIP_POSITION[a.position], u.PIP_SIZE[a.size], a.main, a.sub)
    except Exception as e:
        sys.exit(f"error: {e}")
    print(f"mode {a.name}: main={a.main} second={a.sub} (via {node.remote_name})")


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
    am = sub.add_parser("ambiglow", help="Ambiglow LEDs: info | set (the monitor's own mode) | color | off | release | status")
    am.add_argument("action", choices=["color", "off", "release", "status", "info", "set"])
    am.add_argument("value", nargs="?", help="colour name or #RRGGBB (for color)")
    am.add_argument("--zone", choices=list(amb.ZONES), default="all")
    am.add_argument("--brightness", type=int, default=100, help="0-100 %%")
    am.add_argument("--osd-mode", help="(set) the monitor's own mode: " + ", ".join(amb.DDC_MODES.values()))
    am.add_argument("--osd-color", help="(set) " + ", ".join(amb.DDC_COLORS.values()))
    am.add_argument("--osd-position", help="(set) " + ", ".join(amb.DDC_POSITIONS.values()))
    am.add_argument("--osd-brightness", help="(set) " + ", ".join(amb.DDC_BRIGHTNESS_LEVELS.values()))
    am.add_argument("--osd-speed", help="(set) " + ", ".join(amb.DDC_SPEEDS.values()))
    sub.add_parser("serve", help="run in the background as the monitor server/relay for the other computers "
                                 "(no window; takes over when this computer holds the USB hub)")
    pc = sub.add_parser("pair", help="pair two computers: `pair` shows a 4-digit PIN; on the other computer `pair PIN`")
    pc.add_argument("pin", nargs="?", help="the PIN shown by `freevnia pair` / the GUI on the other computer")
    a = ap.parse_args(argv)

    if a.cmd == "pair":
        return run_pair(a)
    if a.cmd == "serve":
        return run_serve()
    if a.cmd == "mode" and not _local_hub():
        return run_mode_remote(a)
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
