"""Share the monitor between computers on the LAN.

The monitor connects its USB hub to ONE computer at a time (the one on the left/main picture), and only that
computer can talk to the monitor. Every running FreEvnia therefore works like this:

  * the copy that sees the USB hub becomes the SERVER (HTTP on TCP 47601, UDP answers on 47600);
  * the others find it with a UDP broadcast and become CLIENTS: every call is forwarded to the server;
  * when the hub moves to another computer (you switched input), the old server drops out and the copy on the
    new computer takes over.

Security: all computers share one secret (a 4-digit PIN pairing (`freevnia pair`)). Requests are signed with HMAC-SHA256 over a
timestamp + body; the server only runs the calls listed in backend.RPC. This keeps strangers on the LAN out;
it does not encrypt traffic and a captured request can be replayed for ~2 minutes. Do not expose the ports to
the internet.
"""
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import backend, pair

UDP_PORT = 47600
HTTP_PORT = 47601
SKEW = 120                   # seconds of clock difference accepted between computers
PEER_TTL = 20                # a peer that has not announced itself for this long is gone
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "freevnia"


class NoMonitor(RuntimeError):
    """This computer has no access to the monitor and no server was found."""


# --- shared secret ---------------------------------------------------------------------------------------------
def _secret_file():
    return CONFIG / "secret"


def get_secret() -> bytes:
    f = _secret_file()
    try:
        return bytes.fromhex(f.read_text().strip())
    except (OSError, ValueError):
        CONFIG.mkdir(parents=True, exist_ok=True)
        s = secrets.token_bytes(16)
        f.write_text(s.hex() + "\n")
        f.chmod(0o600)
        return s


def set_secret(s: bytes) -> None:
    CONFIG.mkdir(parents=True, exist_ok=True)
    f = _secret_file()
    f.write_text(s.hex() + "\n")
    f.chmod(0o600)


def _sign(secret: bytes, *parts) -> str:
    return hmac.new(secret, ".".join(str(x) for x in parts).encode(), hashlib.sha256).hexdigest()


def _ok_sig(secret, sig, *parts) -> bool:
    return isinstance(sig, str) and hmac.compare_digest(sig, _sign(secret, *parts))


def broadcast_targets():
    """Directed broadcast address of every IPv4 interface (255.255.255.255 alone only leaves by one interface, which
    is the wrong one on computers with VPNs or VM networks), plus loopback for copies on this same computer."""
    out = ["255.255.255.255", "127.0.0.1"]
    try:
        txt = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=3).stdout
        for line in txt.splitlines():
            f = line.split()
            if "brd" in f:
                b = f[f.index("brd") + 1]
                if b not in out:
                    out.append(b)
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def _send_all(sock, data):
    for dst in broadcast_targets():
        try:
            sock.sendto(data, (dst, UDP_PORT))
        except OSError:
            pass


# --- server ----------------------------------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    node = None
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(n, 1 << 20)) if n else b""
        ts = self.headers.get("X-Ts", "")
        ok = (ts.isdigit() and abs(time.time() - int(ts)) <= SKEW
              and _ok_sig(self.node.secret, self.headers.get("X-Sig"), ts, self.path, body.decode("utf-8", "replace")))
        return body, ok

    def _pairing(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(min(n, 1 << 16)) or b"{}")
            if self.path == "/pair/start":
                return self._reply(200, self.node.pair_start(req))
            return self._reply(200, self.node.pair_finish(req))
        except PermissionError as e:
            self._reply(403, {"ok": False, "e": str(e)})
        except Exception as e:
            self._reply(400, {"ok": False, "e": str(e) or type(e).__name__})

    def do_GET(self):
        body, ok = self._body()
        if not ok:
            return self._reply(401, {"ok": False, "e": "not paired"})
        if self.path == "/status":
            return self._reply(200, {"ok": True, "r": self.node.status_info()})
        self._reply(404, {"ok": False, "e": "unknown"})

    def do_POST(self):
        if self.path in ("/pair/start", "/pair/finish"):
            return self._pairing()
        body, ok = self._body()
        if not ok:
            return self._reply(401, {"ok": False, "e": "not paired"})
        if self.path != "/rpc":
            return self._reply(404, {"ok": False, "e": "unknown"})
        try:
            req = json.loads(body)
            name = req["m"]
            if name not in backend.RPC:
                raise ValueError(f"unknown call {name!r}")
            r = getattr(backend, name)(*req.get("a", []), **req.get("k", {}))
            self._reply(200, {"ok": True, "r": r})
        except Exception as e:
            self._reply(200, {"ok": False, "e": str(e) or type(e).__name__})


# --- node ------------------------------------------------------------------------------------------------------
class Node:
    """Role manager. role: 'server' (this computer holds the hub), 'client' (forwarding to `remote`), or 'none'."""

    def __init__(self, name=None, interval=2.0):
        self.name = name or socket.gethostname()
        self.interval = interval
        self.secret = get_secret()
        self.role = "none"
        self.remote = None            # (ip, port) of the server while we are a client
        self.remote_name = ""
        self.unpaired = False         # a server answered but with another secret
        self.peers = {}               # host -> last seen (server only)
        self._httpd = None
        self._udp = None
        self._stop = threading.Event()
        self._last_peer_ping = 0.0
        self._thread = None
        self._pairing = None          # {'pin', 'until', 'fails', 'sessions', 'done'} while showing a PIN
        self._listening = False

    # -- lifecycle
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="freevnia-node")
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._stop_server()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self._stop.wait(self.interval)

    def tick(self):
        if backend.hub_present():
            if self.role != "server":
                self._start_server()
        else:
            if self.role == "server":
                self._stop_server()
            if self.role == "client" and not self._ping():
                self.role, self.remote = "none", None
            if self.role != "client":
                self._discover()
            if self.role == "client" and time.time() - self._last_peer_ping > 5:
                self._announce()
        if self.role == "server":
            now = time.time()
            self.peers = {h: t for h, t in self.peers.items() if now - t < PEER_TTL}
        if self._pairing and not self._pairing["done"] and not self._pairing_active():
            self.close_pairing()          # window expired or too many wrong PINs

    # -- server side
    def _start_listeners(self):
        if self._listening:
            return
        _Handler.node = self
        try:
            self._httpd = ThreadingHTTPServer(("", HTTP_PORT), _Handler)
        except OSError:
            self._httpd = None        # port taken (another copy on this computer): serve locally only
        if self._httpd:
            threading.Thread(target=self._httpd.serve_forever, daemon=True, name="freevnia-http").start()
        try:
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp.bind(("", UDP_PORT))
            threading.Thread(target=self._udp_loop, args=(self._udp,), daemon=True, name="freevnia-udp").start()
        except OSError:
            self._udp = None
        self._listening = True

    def _stop_listeners(self):
        if self._httpd:
            threading.Thread(target=self._httpd.shutdown, daemon=True).start()
            self._httpd.server_close()
            self._httpd = None
        if self._udp:
            u, self._udp = self._udp, None
            try:
                u.close()
            except OSError:
                pass
        self._listening = False

    def _start_server(self):
        self._start_listeners()
        self.role, self.remote, self.remote_name, self.unpaired = "server", None, "", False

    def _stop_server(self):
        self.peers = {}
        if self.role == "server":
            self.role = "none"
        if not self._pairing_active():
            self._stop_listeners()

    def _udp_loop(self, sock):
        while True:
            try:
                data, addr = sock.recvfrom(2048)
                msg = json.loads(data)
            except (OSError, ValueError):
                if sock is not self._udp:
                    return
                continue
            try:
                if msg.get("t") == "who":
                    port = HTTP_PORT
                    reply = {"t": "here", "host": self.name, "port": port,
                             "sig": _sign(self.secret, msg["n"], port, self.name)}
                    sock.sendto(json.dumps(reply).encode(), addr)
                elif msg.get("t") == "pairwho" and self._pairing_active():
                    sock.sendto(json.dumps({"t": "pairhere", "host": self.name, "port": HTTP_PORT}).encode(), addr)
                elif msg.get("t") == "peer" and _ok_sig(self.secret, msg.get("sig"), msg["host"], msg["ts"]) \
                        and abs(time.time() - int(msg["ts"])) <= SKEW:
                    self.peers[msg["host"]] = time.time()
            except Exception:
                pass

    def status_info(self):
        return {"server": self.name, "peers": sorted(self.peers)}

    # -- pairing (PIN)
    def _pairing_active(self):
        p = self._pairing
        return bool(p and not p["done"] and time.time() < p["until"] and p["fails"] < 3)

    def open_pairing(self, seconds=120) -> str:
        """Start listening for a new computer and return the 4-digit PIN to show to the user."""
        pin = f"{secrets.randbelow(10000):04d}"
        self._pairing = {"pin": pin, "until": time.time() + seconds, "fails": 0, "sessions": {}, "done": False}
        self._start_listeners()
        return pin

    def close_pairing(self):
        self._pairing = None
        if self.role != "server":
            self._stop_listeners()

    def pairing_done(self) -> bool:
        return bool(self._pairing and self._pairing["done"])

    def pair_start(self, req):
        if not self._pairing_active():
            raise PermissionError("pairing is not open on this computer")
        p = self._pairing
        side = pair.Side(p["pin"], "server")
        client_msg = int(req["X"], 16)
        side.finish(client_msg, client_msg, side.msg)
        sid = secrets.token_hex(8)
        p["sessions"][sid] = side
        return {"ok": True, "sid": sid, "Y": format(side.msg, "x")}

    def pair_finish(self, req):
        if not self._pairing_active():
            raise PermissionError("pairing is not open on this computer")
        p = self._pairing
        side = p["sessions"].pop(req.get("sid"), None)
        if side is None or not side.check(b"client", req.get("mac")):
            p["fails"] += 1
            raise PermissionError("wrong PIN")
        ct = side.encrypt(self.secret)
        p["done"] = True
        return {"ok": True, "ct": ct.hex(), "mac": side.tag(b"server", ct)}

    def pair_with(self, pin: str, wait=1.5) -> str:
        """Type the PIN shown on another computer: find it, run the exchange and adopt its secret."""
        pin = pin.strip()
        if not (pin.isdigit() and len(pin) == 4):
            raise ValueError("The PIN is 4 digits.")
        targets = []
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(wait)
            _send_all(s, json.dumps({"t": "pairwho"}).encode())
            end = time.time() + wait
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(2048)
                    r = json.loads(data)
                except socket.timeout:
                    break
                except (OSError, ValueError):
                    continue
                if r.get("t") == "pairhere":
                    targets.append((addr[0], int(r["port"]), r.get("host", "")))
        finally:
            s.close()
        if not targets:
            raise RuntimeError("No computer is showing a pairing PIN right now (open Pair… on the other one first, "
                               "and check its firewall: UDP 47600, TCP 47601).")
        ip, port, host = targets[0]

        def post(path, obj):
            req = urllib.request.Request(f"http://{ip}:{port}{path}", data=json.dumps(obj).encode(), method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                raise RuntimeError(json.loads(e.read() or b"{}").get("e", "pairing refused"))

        side = pair.Side(pin, "client")
        r = post("/pair/start", {"X": format(side.msg, "x")})
        side.finish(int(r["Y"], 16), side.msg, int(r["Y"], 16))
        r2 = post("/pair/finish", {"sid": r["sid"], "mac": side.tag(b"client")})
        ct = bytes.fromhex(r2["ct"])
        if not side.check(b"server", r2["mac"], ct):
            raise RuntimeError("The other computer did not prove it knows the PIN.")
        set_secret(side.decrypt(ct))
        self.secret = get_secret()
        if self.role == "client":
            self.role, self.remote = "none", None
        self.unpaired = False
        return host

    # -- client side
    def _announce(self):
        """Tell the server (if any listens) that this computer has FreEvnia open."""
        self._last_peer_ping = time.time()
        ts = int(time.time())
        msg = json.dumps({"t": "peer", "host": self.name, "ts": ts, "sig": _sign(self.secret, self.name, ts)})
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            _send_all(s, msg.encode())
            s.close()
        except OSError:
            pass

    def _discover(self, wait=0.6):
        nonce = secrets.token_hex(8)
        found = None
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(wait)
            _send_all(s, json.dumps({"t": "who", "n": nonce}).encode())
            end = time.time() + wait
            self.unpaired = False
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(2048)
                    r = json.loads(data)
                except socket.timeout:
                    break
                except (OSError, ValueError):
                    continue
                if r.get("t") != "here":
                    continue
                if _ok_sig(self.secret, r.get("sig"), nonce, r.get("port"), r.get("host")):
                    found = (addr[0], int(r["port"]), r.get("host", ""))
                    break
                self.unpaired = True
        except OSError:
            pass
        finally:
            s.close()
        if found:
            self.role, self.remote, self.remote_name = "client", found[:2], found[2]
            self.unpaired = False
            self._announce()
        return found

    def _request(self, method, path, obj=None, timeout=15):
        ip, port = self.remote
        body = json.dumps(obj) if obj is not None else ""
        ts = str(int(time.time()))
        req = urllib.request.Request(f"http://{ip}:{port}{path}", data=body.encode() if method == "POST" else None,
                                     method=method)
        req.add_header("X-Ts", ts)
        req.add_header("X-Sig", _sign(self.secret, ts, path, body))
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b"{}")

    def _ping(self):
        try:
            return bool(self._request("GET", "/status", timeout=3).get("ok"))
        except (OSError, ValueError):
            return False

    # -- what the UI uses
    def call(self, name, *args, **kw):
        """Run a backend call here (server) or on the server (client). state() returns None without access."""
        if name not in backend.RPC:
            raise ValueError(name)
        if self.role == "server" or (self.role == "none" and backend.hub_present()):
            return getattr(backend, name)(*args, **kw)
        if self.role == "client":
            try:
                r = self._request("POST", "/rpc", {"m": name, "a": list(args), "k": kw})
            except (OSError, ValueError):
                self.role, self.remote = "none", None
                r = None
            else:
                if not r.get("ok"):
                    raise RuntimeError(r.get("e", "server error"))
                return r.get("r")
        if name == "state":
            return None
        raise NoMonitor("No access to the monitor: its USB hub is on another computer and no FreEvnia server was found.")

    def peers_info(self):
        """Names of the other computers running FreEvnia, as the server sees them (best effort)."""
        if self.role == "server":
            return {"server": self.name, "peers": sorted(self.peers)}
        if self.role == "client":
            try:
                r = self._request("GET", "/status", timeout=3)
                if r.get("ok"):
                    return r["r"]
            except (OSError, ValueError):
                pass
        return {"server": None, "peers": []}

    def describe(self) -> str:
        if self.role == "server":
            n = len(self.peers)
            return f"This computer holds the monitor's USB hub (server) · {n} other copy(ies) online"
        if self.role == "client":
            return f"Connected through {self.remote_name or self.remote[0]}, which holds the monitor's USB hub"
        if self.unpaired:
            return "A FreEvnia server was found but it uses another pairing code: pair this computer"
        return "Looking for the computer that holds the monitor's USB hub…"
