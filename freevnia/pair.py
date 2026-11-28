"""PIN pairing: a SPAKE2-style password-authenticated key exchange over the RFC 3526 2048-bit MODP group.

Two computers that share a short PIN (4 digits) agree on a strong session key; an eavesdropper learns nothing
that lets them test PINs offline, and an active attacker gets ONE PIN guess per pairing attempt (the listener
closes after 3 failures). The session key then carries the long-term secret (freevnia.net) to the new computer.
"""
import hashlib
import hmac
import secrets

P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74"
    "020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF25F1437"
    "4FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF05"
    "98DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C62F356208552BB"
    "9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFFFFFFFFFF"
, 16)
Q = (P - 1) // 2
G = 2


def _group_element(label: bytes) -> int:
    n = int.from_bytes(hashlib.sha512(label).digest() * 4, "big") % P
    return pow(n, 2, P)            # a square: inside the prime-order subgroup


M = _group_element(b"freevnia-spake2-M")
N = _group_element(b"freevnia-spake2-N")


def _w(pin: str) -> int:
    return int.from_bytes(hashlib.sha256(b"freevnia-pin:" + pin.encode()).digest(), "big") % Q


class Side:
    """role 'client' (the computer that types the PIN) or 'server' (the one that shows it)."""

    def __init__(self, pin: str, role: str):
        self.role = role
        self.w = _w(pin)
        self.x = secrets.randbelow(Q - 1) + 1
        self.mine, self.other = (M, N) if role == "client" else (N, M)
        self.msg = pow(G, self.x, P) * pow(self.mine, self.w, P) % P
        self.key = None

    def finish(self, peer_msg: int, client_msg: int, server_msg: int) -> None:
        if not 1 < peer_msg < P - 1:
            raise ValueError("bad pairing message")
        k = pow(peer_msg * pow(self.other, -self.w, P) % P, self.x, P)
        tt = b"".join(len(b).to_bytes(4, "big") + b for b in (
            client_msg.to_bytes(256, "big"), server_msg.to_bytes(256, "big"), k.to_bytes(256, "big")))
        self.key = hashlib.sha256(b"freevnia-pake" + tt).digest()

    def tag(self, label: bytes, data: bytes = b"") -> str:
        return hmac.new(self.key, label + data, hashlib.sha256).hexdigest()

    def check(self, label: bytes, tag, data: bytes = b"") -> bool:
        return isinstance(tag, str) and hmac.compare_digest(tag, self.tag(label, data))

    def encrypt(self, secret: bytes) -> bytes:
        pad = hmac.new(self.key, b"enc", hashlib.sha256).digest()
        return bytes(a ^ b for a, b in zip(secret, pad))

    decrypt = encrypt
