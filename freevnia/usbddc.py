"""DDC/CI over USB for the Philips Evnia 49M2C8900L (VIA Labs Billboard device 2109:8884).

The monitor does not honour input-source / PBP / PIP changes sent over the DisplayPort/HDMI
DDC channel. The official Evnia Precision Center sends them over USB instead, through the
VIA Labs hub: raw DDC/CI frames wrapped in vendor control transfers. See PROTOCOL.md.

  write : control OUT  bmRequestType=0x40  bRequest=0xB2  wValue=0  wIndex=0
          data = raw DDC/CI frame [0x6E, 0x51, 0x80|len, payload..., checksum]
  read  : control IN   bmRequestType=0xC0  bRequest=0xA3  wValue=0  wIndex=0x006F  wLength=32
          data = raw DDC/CI reply [0x6E, 0x80|len, 0x02, ...]
  checksum = XOR of every previous byte of the frame; wait ~150 ms between write and read.
"""
import time
from functools import reduce

import usb.core

VID, PID = 0x2109, 0x8884
DEST, SRC = 0x6E, 0x51
REQ_OUT, REQ_IN = 0xB2, 0xA3
WINDEX_READ = 0x006F
DELAY = 0.15


class MonitorNotFound(Exception):
    """The VIA Billboard device is not visible on this host."""


def checksum(buf: bytes) -> int:
    return reduce(lambda a, b: a ^ b, buf, 0)


def frame(payload: bytes) -> bytes:
    body = bytes([DEST, SRC, 0x80 | len(payload)]) + payload
    return body + bytes([checksum(body)])


def find_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise MonitorNotFound(
            "VIA Billboard 2109:8884 not found. Is the monitor's USB upstream cable connected to this "
            "computer, and is this computer the one currently on the monitor's left/main input?")
    return dev


def transact(dev, payload: bytes) -> bytes:
    dev.ctrl_transfer(0x40, REQ_OUT, 0, 0, frame(payload))
    time.sleep(DELAY)
    return bytes(dev.ctrl_transfer(0xC0, REQ_IN, 0, WINDEX_READ, 32))


def parse_reply(raw: bytes) -> bytes:
    if len(raw) < 3 or raw[0] != DEST:
        raise ValueError(f"unexpected reply: {raw.hex()}")
    n = raw[1] & 0x7F
    if n == 0:
        raise ValueError("empty reply (the monitor has not answered yet)")
    return raw[2:2 + n]


class VcpRejected(ValueError):
    """The monitor answered that it does not support this VCP code."""


def code_bytes(code: int) -> bytes:
    """A VCP code as sent on the wire: 1 byte for standard codes, 3 bytes for the Philips extended
    ones (0xE2A0xx, advertised in the capability string as e.g. E2A017)."""
    return bytes([code]) if code <= 0xFF else code.to_bytes(3, "big")


def get_vcp(dev, code: int, retries: int = 5, expect_max=None) -> dict:
    """Get VCP. The reply buffer keeps the previous answer until the monitor prepares a new one, so the
    reply is only accepted if it is for the code we asked about; otherwise we wait and ask again.

    Extended replies only echo the first byte (0xE2), so a stale answer for another extended code looks
    valid: for those the same request must give the same answer twice in a row. If expect_max is given (the
    largest value the capability string lists for the code), an answer with a different maximum is a stale
    answer for another code and is asked again."""
    ext = code > 0xFF
    first = code_bytes(code)[0]
    last = ValueError("no reply")
    prev = None
    for _ in range(retries + (4 if ext else 0)):
        try:
            p = parse_reply(transact(dev, bytes([0x01]) + code_bytes(code)))
        except ValueError as e:
            last = e
        else:
            if p[0] == 0x02 and p[2] == first:
                if p[1] != 0x00:
                    raise VcpRejected(f"monitor rejects VCP 0x{code:02x} (result {p[1]:#x})")
                r = {"code": code, "type": p[3], "max": (p[4] << 8) | p[5], "cur": (p[6] << 8) | p[7]}
                if expect_max is not None and r["max"] != expect_max:
                    last = ValueError(f"answer with max {r['max']} is not for VCP 0x{code:02x} (expected {expect_max})")
                    prev = None
                    time.sleep(0.25)
                    continue
                if not ext or r == prev:
                    return r
                prev = r
                continue
            last = ValueError(f"stale reply for another code: {p.hex()}")
        time.sleep(0.25)
    raise last


def set_vcp(dev, code: int, value: int) -> None:
    dev.ctrl_transfer(0x40, REQ_OUT, 0, 0,
                      frame(bytes([0x03]) + code_bytes(code) + bytes([(value >> 8) & 0xFF, value & 0xFF])))


def vendor_str(dev, args: bytes) -> str:
    """Manufacturer commands: Get VCP 0xFE + arguments; the reply carries ASCII text."""
    p = parse_reply(transact(dev, bytes([0x01, 0xFE]) + args))
    return p[3:].split(b"\x00")[0].decode("ascii", "replace").strip()


INFO_QUERIES = (("model", "e90d0000"), ("BOM", "e1e61d00"), ("firmware", "e1e60600"), ("scaler", "e1e80000"))

# PIP/PBP mode = high byte of VCP 0xA5 (this monitor reports capability 0xF7 = 0x42). 0x0200 and 0x0000 verified.
MODES = {"off": 0x0000, "pip": 0x0100, "pbp1": 0x0200}
# Input codes. main = low byte of VCP 0x60, sub (second picture) = high byte.
SRC_MAIN = {"dp1": 0x0F, "hdmi1": 0x11, "hdmi2": 0x12, "usbc": 0x15}   # dp1 and usbc verified
SRC_SUB = {"usbc": 0x35, "hdmi1": 0x21, "hdmi2": 0x22}                  # all verified
# PIP window position (VCP 0xEC high byte) and size (low byte) - verified with a camera.
PIP_POSITION = {"upper-right": 1, "lower-right": 2, "upper-left": 3, "lower-left": 4}
PIP_SIZE = {"small": 1, "medium": 2, "large": 3}


def apply_mode(dev, mode: int, main: int, sub: int, size: int = 2, loc: int = 1) -> None:
    """The sequence the Precision Center uses (decompiled, then verified on the panel):
    0xA5 = mode, 0xEC = (position << 8 | size), 0x60 = (sub << 8 | main), 0xA4 = 0xFFFF (commit);
    100 ms between steps. Writing 0xA5 alone does nothing."""
    set_vcp(dev, 0xA5, mode); time.sleep(0.1)
    set_vcp(dev, 0xEC, (loc << 8) | size); time.sleep(0.1)
    set_vcp(dev, 0x60, (sub << 8) | main); time.sleep(0.1)
    set_vcp(dev, 0xA4, 0xFFFF)
