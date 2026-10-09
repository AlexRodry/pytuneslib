"""Encryption / compression layer of iTunes .itl files.

File layout: ``hdfm`` header (big-endian, ``header_len`` bytes, 0x90 in 12.x)
followed by the payload. Payload = zlib(level 1) stream whose first
``max_crypt_size`` bytes (header u32 at 0x5C, 102400 in practice, rounded
down to 16) are AES-128-ECB encrypted with a fixed key. Trailing bytes after
that are plain zlib data.
"""

from __future__ import annotations

import struct
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY = b"BHUILuilfghuila3"
DEFAULT_MAX_CRYPT_SIZE = 102400
ZLIB_LEVEL = 1  # reproduces iTunes 12.13 output byte-for-byte

HDFM_MAX_CRYPT_OFFSET = 0x5C


def _cipher() -> Cipher:
    return Cipher(algorithms.AES(KEY), modes.ECB())


def _crypt_len(payload_len: int, max_crypt_size: int) -> int:
    n = min(payload_len, max_crypt_size) if max_crypt_size else payload_len
    return n - n % 16


def decrypt(payload: bytes, max_crypt_size: int = DEFAULT_MAX_CRYPT_SIZE) -> bytes:
    n = _crypt_len(len(payload), max_crypt_size)
    d = _cipher().decryptor()
    return d.update(payload[:n]) + d.finalize() + payload[n:]


def encrypt(payload: bytes, max_crypt_size: int = DEFAULT_MAX_CRYPT_SIZE) -> bytes:
    n = _crypt_len(len(payload), max_crypt_size)
    e = _cipher().encryptor()
    return e.update(payload[:n]) + e.finalize() + payload[n:]


def decode_payload(payload: bytes, max_crypt_size: int = DEFAULT_MAX_CRYPT_SIZE) -> bytes:
    """Encrypted file payload -> decompressed chunk stream."""
    data = decrypt(payload, max_crypt_size)
    # Very old libraries were not compressed; zlib streams start with 0x78.
    if data[:1] == b"\x78":
        return zlib.decompress(data)
    return data


def encode_payload(data: bytes, max_crypt_size: int = DEFAULT_MAX_CRYPT_SIZE) -> bytes:
    """Decompressed chunk stream -> encrypted file payload."""
    return encrypt(zlib.compress(data, ZLIB_LEVEL), max_crypt_size)


def split_file(raw: bytes) -> tuple[bytes, bytes]:
    """Return (hdfm header bytes, raw encrypted payload)."""
    if raw[:4] != b"hdfm":
        raise ValueError("not an iTunes .itl file (missing hdfm magic)")
    header_len = struct.unpack_from(">I", raw, 4)[0]
    return raw[:header_len], raw[header_len:]


def header_max_crypt_size(header: bytes) -> int:
    if len(header) >= HDFM_MAX_CRYPT_OFFSET + 4:
        v = struct.unpack_from(">I", header, HDFM_MAX_CRYPT_OFFSET)[0]
        if v:
            return v
    return DEFAULT_MAX_CRYPT_SIZE


def decrypt_file(raw: bytes) -> tuple[bytes, bytes]:
    """Full .itl bytes -> (hdfm header, decompressed payload)."""
    header, payload = split_file(raw)
    return header, decode_payload(payload, header_max_crypt_size(header))


def encrypt_file(header: bytes, data: bytes) -> bytes:
    """(hdfm header, decompressed payload) -> full .itl bytes.

    Patches the file-length field (0x08) of the header.
    """
    payload = encode_payload(data, header_max_crypt_size(header))
    h = bytearray(header)
    struct.pack_into(">I", h, 8, len(h) + len(payload))
    return bytes(h) + payload
