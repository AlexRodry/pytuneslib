"""Playlist folders are smart playlists whose rules list their children.

iTunes 12.13 only treats an hpim as a folder when, besides the +0x20A flag, it carries a Smart Info /
Smart Criteria pair (hohm 102 / 101) with one rule "Playlist is <child persistent id>" per direct child,
OR-ed together. Verified on all 41 folders of the sample: one Smart Info blob for all, one header and one
124-byte rule template; only the child pids (and the rule order) vary. Without the rules iTunes drops the
folder flag on re-save.
"""

from __future__ import annotations

import struct

# Smart Info shared by every folder in the sample (112 bytes)
FOLDER_SMART_INFO = bytes.fromhex("0101000300000002000000190000000000000007") + bytes(92)

_HEADER_LEN, _RULE_LEN = 136, 124
_COUNT = 8  # u32 BE number of rules in the criteria header
_RULE_PIDS = (0x38, 0x50)  # child pid (8 bytes, big-endian hex order) appears twice per rule


def _header(n: int) -> bytes:
    h = bytearray(_HEADER_LEN)
    h[0:8] = b"SLst\x00\x01\x00\x01"
    struct.pack_into(">II", h, _COUNT, n, 1)  # n rules, match any
    return bytes(h)


def _rule(pid: str) -> bytes:
    r = bytearray(_RULE_LEN)
    struct.pack_into(">II", r, 0, 0x28, 1)  # field "Playlist", operator "is"
    struct.pack_into(">I", r, 0x34, 0x44)
    struct.pack_into(">I", r, 0x4C, 1)
    struct.pack_into(">I", r, 0x64, 1)
    for off in _RULE_PIDS:
        r[off:off + 8] = bytes.fromhex(pid)
    return bytes(r)


def criteria_children(criteria: bytes | None) -> list[str] | None:
    """Child pids of a folder criteria blob in rule order, or None if it is not one."""
    if not criteria or len(criteria) < _HEADER_LEN or criteria[:4] != b"SLst":
        return None
    n = struct.unpack_from(">I", criteria, _COUNT)[0]
    if len(criteria) != _HEADER_LEN + n * _RULE_LEN:
        return None
    out = []
    for i in range(n):
        r = criteria[_HEADER_LEN + i * _RULE_LEN:_HEADER_LEN + (i + 1) * _RULE_LEN]
        pid = r[_RULE_PIDS[0]:_RULE_PIDS[0] + 8].hex().upper()
        if r != _rule(pid):
            return None
        out.append(pid)
    return out


def folder_criteria(children: list[str], existing: bytes | None = None) -> bytes:
    """Criteria for a folder with these direct children (persistent ids).

    If `existing` already lists exactly these children it is returned unchanged (iTunes' own rule order is
    kept byte-for-byte); otherwise its rule order is kept for children that remain and new ones appended.
    """
    children = [c.upper() for c in children]
    old = criteria_children(existing) or []
    if existing is not None and sorted(old) == sorted(children):
        return existing
    order = [c for c in old if c in children] + [c for c in children if c not in old]
    return _header(len(order)) + b"".join(_rule(c) for c in order)
