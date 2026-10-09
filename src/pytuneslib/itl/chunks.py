"""Generic chunk tree of a decrypted .itl payload (iTunes 12.x, little-endian).

Payload = sequence of ``hdsm`` sections. Every chunk starts with a 4-byte tag
(stored byte-reversed on disk: ``msdh`` = hdsm), u32 header length, u32
"length-or-count" field. Inside a section, ``hohm`` (data) and ``hptm``
(playlist item) chunks belong to the preceding "owner" chunk.

Serialization recomputes every length/count field so edited trees stay
consistent; an unmodified tree serializes byte-identically.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SECTION_HEADER_LEN = 96

# Chunks whose +8 field is total length (header + children).
TOTAL_LEN_TAGS = {"htim", "haim", "hiim", "hpim", "hqim", "hpsm"}
# List headers whose +8 field counts the item chunks that follow in the section.
LIST_COUNT_TAGS = {"halm", "hilm", "htlm", "hplm", "hslm", "hrlm"}
# Owner chunks whose +8 field counts their hohm children.
HOHM_COUNT_TAGS = {"hghm"}
CHILD_TAGS = {"hohm", "hptm"}
KNOWN_TAGS = (
    TOTAL_LEN_TAGS | LIST_COUNT_TAGS | HOHM_COUNT_TAGS | CHILD_TAGS
    | {"hdfm", "hqlm", "hsts", "hrpm"}
)

# Section types (hdsm +12) seen in iTunes 12.13
SEC_HDFM = 16
SEC_LIBRARY = 12  # hghm: library-wide settings
SEC_ALBUMS = 9
SEC_ARTISTS = 11
SEC_TRACKS = 1
SEC_TRACKS2 = 13
SEC_HQLM = 20
SEC_HSTS = 23
SEC_PLAYLISTS = 2
SEC_GENIUS = 14
SEC_HSLM = 21
SEC_MUSIC_FOLDER = 4  # raw body: file:// URL of the iTunes Media folder
SEC_HRLM = 15


def _tag(raw4: bytes) -> str:
    return raw4[::-1].decode("latin-1")


def _raw_tag(tag: str) -> bytes:
    return tag.encode("latin-1")[::-1]


@dataclass
class Chunk:
    tag: str
    head: bytearray  # header bytes; for hohm the entire chunk
    children: list[Chunk] = field(default_factory=list)

    def u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.head, off)[0]

    def set_u32(self, off: int, v: int) -> None:
        struct.pack_into("<I", self.head, off, v)

    def u16(self, off: int) -> int:
        return struct.unpack_from("<H", self.head, off)[0]

    def set_u16(self, off: int, v: int) -> None:
        struct.pack_into("<H", self.head, off, v)

    def kids(self, tag: str) -> list[Chunk]:
        return [c for c in self.children if c.tag == tag]

    @property
    def hohm_type(self) -> int:
        return self.u32(12)


@dataclass
class Section:
    head: bytearray
    chunks: list[Chunk] | None = None
    raw: bytes | None = None  # body when not a chunk list

    @property
    def type(self) -> int:
        return struct.unpack_from("<I", self.head, 12)[0]

    def items(self, tag: str) -> list[Chunk]:
        return [c for c in self.chunks or [] if c.tag == tag]


def _parse_body(buf: bytes, start: int, end: int) -> list[Chunk] | None:
    chunks: list[Chunk] = []
    owner: Chunk | None = None
    p = start
    while p < end:
        if p + 12 > end:
            return None
        tag = _tag(buf[p:p + 4])
        if tag not in KNOWN_TAGS:
            return None
        hl, b = struct.unpack_from("<II", buf, p + 4)
        n = b if tag == "hohm" else hl
        if n < 12 or p + n > end:
            return None
        c = Chunk(tag, bytearray(buf[p:p + n]))
        if tag in CHILD_TAGS and owner is not None:
            owner.children.append(c)
        else:
            chunks.append(c)
            owner = c
        p += n
    return chunks


def parse_payload(buf: bytes) -> list[Section]:
    sections: list[Section] = []
    o = 0
    while o < len(buf):
        if buf[o:o + 4] != b"msdh":
            raise ValueError(f"expected hdsm at 0x{o:x}")
        hl, tl = struct.unpack_from("<II", buf, o + 4)
        head = bytearray(buf[o:o + hl])
        chunks = _parse_body(buf, o + hl, o + tl)
        if chunks is None:
            sections.append(Section(head, raw=bytes(buf[o + hl:o + tl])))
        else:
            sections.append(Section(head, chunks=chunks))
        o += tl
    return sections


def _ser_chunk(c: Chunk) -> bytes:
    if c.tag == "hohm":
        c.set_u32(8, len(c.head))
        return bytes(c.head)
    kids = b"".join(_ser_chunk(k) for k in c.children)
    if c.tag in TOTAL_LEN_TAGS:
        c.set_u32(8, len(c.head) + len(kids))
    elif c.tag in HOHM_COUNT_TAGS:
        c.set_u32(8, len(c.kids("hohm")))
    return bytes(c.head) + kids


def serialize_payload(sections: list[Section], outer_header_len: int = 0x90) -> bytes:
    parts = []
    for s in sections:
        if s.chunks is not None:
            for i, c in enumerate(s.chunks):
                if c.tag in LIST_COUNT_TAGS:
                    c.set_u32(8, sum(1 for d in s.chunks[i + 1:] if d.tag not in LIST_COUNT_TAGS))
            body = b"".join(_ser_chunk(c) for c in s.chunks)
        else:
            body = s.raw or b""
        struct.pack_into("<I", s.head, 8, len(s.head) + len(body))
        parts.append(bytes(s.head) + body)
    data = bytearray(b"".join(parts))
    # Inner hdfm copy (section 16) stores uncompressed file length.
    if data[SECTION_HEADER_LEN:SECTION_HEADER_LEN + 4] == b"mfdh":
        struct.pack_into("<I", data, SECTION_HEADER_LEN + 8, len(data) + outer_header_len)
    return bytes(data)


def new_chunk(tag: str, head_len: int, template: bytes | None = None) -> Chunk:
    head = bytearray(template) if template else bytearray(head_len)
    if len(head) < head_len:
        head += bytes(head_len - len(head))
    head[0:4] = _raw_tag(tag)
    struct.pack_into("<I", head, 4, head_len if tag != "hohm" else 24)
    return Chunk(tag, head)


def new_section(sec_type: int) -> Section:
    head = bytearray(SECTION_HEADER_LEN)
    head[0:4] = b"msdh"
    struct.pack_into("<III", head, 4, SECTION_HEADER_LEN, SECTION_HEADER_LEN, sec_type)
    return Section(head, chunks=[])


# --- hohm (data chunk) helpers -------------------------------------------

ENC_UTF16 = 1
ENC_ASCII = 2
ENC_LATIN1 = 3


def hohm_string(c: Chunk) -> str | None:
    """Decode a string hohm; None if it is not a string payload."""
    h = c.head
    if len(h) < 40:
        return None
    enc, n = struct.unpack_from("<II", h, 24)
    if n != len(h) - 40:
        return None
    data = bytes(h[40:])
    if enc == ENC_UTF16:
        return data.decode("utf-16-le")
    if enc in (ENC_ASCII, ENC_LATIN1, 0):
        return data.decode("latin-1")
    return None


def make_hohm_string(htype: int, text: str, ascii_url: bool = False) -> Chunk:
    """Build a string hohm the way iTunes does: Latin-1 when possible, else UTF-16LE."""
    if ascii_url:
        enc, data = ENC_ASCII, text.encode("ascii")
    else:
        try:
            enc, data = ENC_LATIN1, text.encode("latin-1")
        except UnicodeEncodeError:
            enc, data = ENC_UTF16, text.encode("utf-16-le")
    head = bytearray(40)
    head[0:4] = _raw_tag("hohm")
    struct.pack_into("<IIIII", head, 4, 24, 40 + len(data), htype, 0, 0)
    # +0x10 is an opaque per-string value in iTunes files (often 1); 1 is safe.
    struct.pack_into("<I", head, 16, 1 if enc != ENC_ASCII else 0)
    struct.pack_into("<II", head, 24, enc, len(data))
    return Chunk("hohm", head + data)
