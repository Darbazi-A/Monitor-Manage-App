"""
A self-signed certificate for the laptop screen share, made without any extra package.

Browsers let a page capture the screen only over HTTPS, and a hall PC on a
school network has no domain name a real certificate authority would sign. So
the app signs its own: RSA-2048 and SHA-256, the addresses it can be reached on
in the subjectAltName. A laptop's browser warns about it once ("not private"),
and after "Advanced -> Continue" the page works like any other HTTPS page.

The key is made with Python's own big integers (Miller-Rabin primes) and the
certificate is written out by a small DER encoder - about a second, once; the
files are kept and reused until the PC's addresses change.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import os
import secrets
from typing import Iterable, List, Tuple

E = 65537
_SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]


# --------------------------------------------------------------------------- #
# RSA
# --------------------------------------------------------------------------- #

def _probably_prime(n: int, rounds: int = 40) -> bool:
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        # top two bits set, so p*q has exactly 2*bits bits; odd
        candidate = secrets.randbits(bits) | (3 << (bits - 2)) | 1
        if (candidate - 1) % E and _probably_prime(candidate):
            return candidate


def rsa_key(bits: int = 2048) -> Tuple[int, int, int, int, int]:
    """n, e, d, p, q."""
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        d = pow(E, -1, phi)
        n = p * q
        if n.bit_length() == bits:
            return n, E, d, p, q


# --------------------------------------------------------------------------- #
# DER
# --------------------------------------------------------------------------- #

def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _len(len(body)) + body


def _int(n: int) -> bytes:
    body = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big")   # room for the sign bit
    return _tlv(0x02, body)


def _seq(*parts: bytes) -> bytes:
    return _tlv(0x30, b"".join(parts))


def _set(*parts: bytes) -> bytes:
    return _tlv(0x31, b"".join(parts))


def _oid(dotted: str) -> bytes:
    numbers = [int(x) for x in dotted.split(".")]
    body = bytes([numbers[0] * 40 + numbers[1]])
    for n in numbers[2:]:
        chunk = [n & 0x7F]
        n >>= 7
        while n:
            chunk.append(0x80 | (n & 0x7F))
            n >>= 7
        body += bytes(reversed(chunk))
    return _tlv(0x06, body)


def _utf8(text: str) -> bytes:
    return _tlv(0x0C, text.encode("utf-8"))


def _bits(body: bytes) -> bytes:
    return _tlv(0x03, b"\x00" + body)


def _time(when: datetime.datetime) -> bytes:
    if when.year < 2050:
        return _tlv(0x17, when.strftime("%y%m%d%H%M%SZ").encode("ascii"))
    return _tlv(0x18, when.strftime("%Y%m%d%H%M%SZ").encode("ascii"))


SHA256_RSA = _seq(_oid("1.2.840.113549.1.1.11"), b"\x05\x00")
RSA_ENCRYPTION = _seq(_oid("1.2.840.113549.1.1.1"), b"\x05\x00")
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _name(common: str) -> bytes:
    return _seq(_set(_seq(_oid("2.5.4.3"), _utf8(common))),
                _set(_seq(_oid("2.5.4.10"), _utf8("Stage Display Controller"))))


def _sign(message: bytes, n: int, d: int) -> bytes:
    """RSASSA-PKCS1-v1_5 with SHA-256."""
    size = (n.bit_length() + 7) // 8
    digest = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    padded = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    return pow(int.from_bytes(padded, "big"), d, n).to_bytes(size, "big")


def _pem(kind: str, der: bytes) -> str:
    text = base64.b64encode(der).decode("ascii")
    lines = [text[i:i + 64] for i in range(0, len(text), 64)]
    return f"-----BEGIN {kind}-----\n" + "\n".join(lines) + f"\n-----END {kind}-----\n"


def make_certificate(addresses: Iterable[str], names: Iterable[str] = ("localhost",),
                     years: int = 5) -> Tuple[str, str]:
    """(certificate PEM, private key PEM) for these IP addresses and host names."""
    n, e, d, p, q = rsa_key()
    alt = b""
    for name in names:
        alt += _tlv(0x82, name.encode("ascii"))                          # dNSName
    for address in addresses:
        alt += _tlv(0x87, ipaddress.ip_address(address).packed)        # iPAddress
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    extensions = _tlv(0xA3, _seq(
        _seq(_oid("2.5.29.17"), _tlv(0x04, _seq(alt))),                # subjectAltName
        _seq(_oid("2.5.29.19"), _tlv(0x04, _seq())),                     # basicConstraints: not a CA
        _seq(_oid("2.5.29.37"), _tlv(0x04, _seq(_oid("1.3.6.1.5.5.7.3.1")))),   # serverAuth
    ))
    tbs = _seq(
        _tlv(0xA0, _int(2)),                                              # v3
        _int(secrets.randbits(63) | 1),
        SHA256_RSA,
        _name("Stage Display Controller"),
        _seq(_time(now - datetime.timedelta(days=1)), _time(now + datetime.timedelta(days=365 * years))),
        _name("Stage Display Controller"),
        _seq(RSA_ENCRYPTION, _bits(_seq(_int(n), _int(e)))),
        extensions,
    )
    certificate = _seq(tbs, SHA256_RSA, _bits(_sign(tbs, n, d)))
    key = _seq(_int(0), _int(n), _int(e), _int(d), _int(p), _int(q),
               _int(d % (p - 1)), _int(d % (q - 1)), _int(pow(q, -1, p)))
    return _pem("CERTIFICATE", certificate), _pem("RSA PRIVATE KEY", key)


def ensure_certificate(folder: str, addresses: List[str]) -> Tuple[str, str]:
    """
    Paths of a certificate and key in `folder` that cover `addresses`; made (or
    remade, when the PC has a new address) only when needed.
    """
    os.makedirs(folder, exist_ok=True)
    cert_path = os.path.join(folder, "share-cert.pem")
    key_path = os.path.join(folder, "share-key.pem")
    list_path = os.path.join(folder, "share-addresses.txt")
    wanted = sorted(set(addresses) | {"127.0.0.1"})
    try:
        with open(list_path, encoding="ascii") as handle:
            covered = set(handle.read().split())
        if os.path.exists(cert_path) and os.path.exists(key_path) and set(wanted) <= covered:
            return cert_path, key_path
        wanted = sorted(set(wanted) | covered)      # keep the old ones: a laptop may still use them
    except OSError:
        pass
    cert, key = make_certificate(wanted)
    with open(key_path, "w", encoding="ascii") as handle:
        handle.write(key)
    with open(cert_path, "w", encoding="ascii") as handle:
        handle.write(cert)
    with open(list_path, "w", encoding="ascii") as handle:
        handle.write("\n".join(wanted))
    return cert_path, key_path
