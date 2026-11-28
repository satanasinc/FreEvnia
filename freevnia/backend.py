"""Everything that touches the monitor over USB, without Qt. Used directly when this computer holds the
monitor's USB hub, and through freevnia.net (the server) when another computer does."""
import os
import threading
import time

import usb.core

from . import ambiglow as amb
from . import settings as st
from . import usbddc as p

LOCK = threading.Lock()          # one USB access at a time (polling, commands, network clients)

def device():
    if os.environ.get("FREEVNIA_NO_LOCAL_HUB"):          # testing: behave as a computer that does not hold the hub
        return None
    return usb.core.find(idVendor=p.VID, idProduct=p.PID)


def state():
    """None = no access; 'full' = full screen; 'on' = PBP/PIP active; 'err' = read failure."""
    with LOCK:
        dev = device()
        if dev is None:
            return None
        try:
            return "on" if p.get_vcp(dev, 0xE6, retries=10)["cur"] == 0 else "full"
        except Exception:
            return "err"


def ambi(action, rgb=None, brightness=100):
    """Run one Ambiglow action under the USB lock (the LEDs are a separate USB device)."""
    with LOCK:
        dev = amb.find_device()
        if action == "color":
            amb.solid(dev, rgb, "all", brightness)
        elif action == "off":
            amb.off(dev)
        elif action == "release":
            amb.release(dev, device())


def apply(mode, loc, size, main="dp1", sub="usbc"):
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        p.apply_mode(dev, p.MODES[mode], p.SRC_MAIN[main], p.SRC_SUB[sub], size, loc)



def settings_read():
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        return st.read_all(dev), st.time_since_pixel_refresh(dev)


def setting_write(key, value):
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        s = st.BY_KEY[key]
        st.write(dev, s, value)
        import time
        time.sleep(0.4)
        return key, st.read(dev, s)


def pixel_refresh():
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor")
        st.pixel_refresh(dev)
    return None


def osd_read():
    """The monitor's Ambiglow setting. The monitor sometimes answers with its previous reply: try again."""
    last = None
    for _ in range(4):
        with LOCK:
            dev = device()
            if dev is None:
                return "n/a"
            try:
                return amb.ddc_settings(dev)
            except ValueError as e:
                last = e
        time.sleep(0.8)
    raise last


def osd_write(**kw):
    """Change the monitor's own Ambiglow setting; the monitor draws every mode itself. What to show comes from
    what was asked (current values + the change), not from a read-back, because the monitor sometimes answers a
    read with an older reply."""
    with LOCK:
        ddc = device()
        if ddc is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        vals = amb.ddc_settings(ddc)
        vals.update({k: v for k, v in kw.items() if v is not None})
        amb.apply_osd(ddc, amb.find_device(), **kw)
    return vals


def hub_present() -> bool:
    return device() is not None


# The only calls the server accepts from the network.
RPC = ("state", "ambi", "apply", "settings_read", "setting_write", "pixel_refresh", "osd_read", "osd_write")
