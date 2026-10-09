"""Read iTunes .itl files into a chunk tree and a :class:`model.Library`."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from ..model import Library, Playlist, Track
from . import chunks as C
from .crypto import decrypt_file, encrypt_file

MAC_EPOCH = datetime(1904, 1, 1)

# hdfm (outer header, big-endian) offsets
HDFM_VERSION = 0x10  # pascal string
HDFM_SECTION_COUNT = 0x30  # number of hdsm sections
HDFM_LIBRARY_PID = 0x34
HDFM_TRACK_COUNT = 0x44
HDFM_PLAYLIST_COUNT = 0x48
HDFM_ALBUM_COUNT = 0x4C
HDFM_ARTIST_COUNT = 0x54
HDFM_TZ_OFFSET = 0x64  # seconds east of UTC at save time
HDFM_DATE = 0x70

# htim (track) header offsets, little-endian
T = dict(
    hohm_count=0x0C, track_id=0x10, date_modified=0x20, size=0x24, total_time=0x28,
    track_number=0x2C, track_count=0x30, year=0x34, bit_rate=0x38, codec=0x50, play_count2=0x4C,
    compilation=0x53, play_count=0x60, play_date=0x64, disc_number=0x68, disc_count=0x6A,
    rating=0x6C, date_added=0x78, persistent_id=0x80, file_type=0x8C, artwork_count=0x90,
    sample_rate=0x98, bpm=0xA4, skip_count=0xD8, album_id=0xDC, skip_date=0x11C,
    size2=0x144, artist_id=0x1E0, track_id2=0x1F4,
    # gapless info (left 0 by the writer; iTunes fills it on analysis)
    encoder_delay=0xF0, sample_count=0xF4, encoder_padding=0x100, audio_bytes=0x120,
)
# haim (album) header offsets; +0x29 rating flags: 0x01 user-set, 0x20 computed
A = dict(hohm_count=0x0C, album_id=0x10, persistent_id=0x14, track_pid=0x20, rating=0x28)
S_ALBUM_NAME, S_ALBUM_ARTIST_A, S_ALBUM_ARTIST_B = 300, 301, 302
# hiim (artist) header offsets
R = dict(hohm_count=0x0C, artist_id=0x10, persistent_id=0x14)
S_ARTIST_NAME, S_ARTIST_SORT = 400, 401
# hohm string types inside htim
S_NAME, S_ALBUM, S_ARTIST, S_GENRE, S_KIND, S_COMMENTS = 2, 3, 4, 5, 6, 8
S_COMPOSER, S_PATH, S_URL, S_GROUPING, S_ALBUM_ARTIST = 12, 13, 11, 14, 27
# hpim (playlist) header offsets
P = dict(hohm_count=0x0C, item_count=0x10, master=0x16, persistent_id=0x1B8,
         parent_pid=0x210, folder=0x20A, distinguished_kind=0x239, playlist_id=0xD40)
S_PLAYLIST_NAME = 100
MASTER_NAME_TOKEN = "####!####"
# hptm (playlist item)
I_ITEM_ID, I_TRACK_ID = 0x10, 0x18


@dataclass
class ItlFile:
    header: bytearray  # outer hdfm header (big-endian)
    sections: list[C.Section]

    def section(self, sec_type: int) -> C.Section | None:
        return next((s for s in self.sections if s.type == sec_type), None)

    @property
    def version(self) -> str:
        n = self.header[HDFM_VERSION]
        return self.header[HDFM_VERSION + 1:HDFM_VERSION + 1 + n].decode("latin-1")

    def payload(self) -> bytes:
        return C.serialize_payload(self.sections, len(self.header))

    def to_bytes(self) -> bytes:
        return encrypt_file(bytes(self.header), self.payload())


def parse_itl(raw: bytes) -> ItlFile:
    header, data = decrypt_file(raw)
    return ItlFile(bytearray(header), C.parse_payload(data))


def load_itl(path: str | os.PathLike) -> ItlFile:
    return parse_itl(Path(path).read_bytes())


# --- value helpers ----------------------------------------------------------

def mac_to_datetime(secs: int) -> datetime | None:
    """iTunes stores local wall-clock seconds since 1904-01-01. -> aware UTC."""
    if not secs:
        return None
    naive = MAC_EPOCH + timedelta(seconds=secs)
    return naive.astimezone(timezone.utc)  # naive is interpreted as local time


def datetime_to_mac(dt: datetime) -> int:
    """aware/naive-UTC datetime -> local wall-clock mac seconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_naive = dt.astimezone().replace(tzinfo=None)
    return int((local_naive - MAC_EPOCH).total_seconds())


def pid_from_bytes(b: bytes) -> str:
    return bytes(b[::-1]).hex().upper()


def pid_to_bytes(pid: str) -> bytes:
    return bytes.fromhex(pid)[::-1]


def url_to_path(url: str) -> str:
    """file://localhost/C:/a%20b/c.mp3 -> C:\\a b\\c.mp3 (POSIX paths kept as-is)."""
    if url.startswith("file://localhost"):
        p = unquote(url[len("file://localhost"):])
    elif url.startswith("file://"):
        p = unquote(url[len("file://"):])
    else:
        return url
    if len(p) >= 3 and p[0] == "/" and p[2] == ":":  # /C:/...
        return p[1:].replace("/", "\\")
    if p.startswith("//"):  # UNC
        return p.replace("/", "\\")
    return p


def _strings(c: C.Chunk) -> dict[int, str]:
    out: dict[int, str] = {}
    for k in c.kids("hohm"):
        s = C.hohm_string(k)
        if s is not None:
            # iTunes 12.13 separates multi-value tags with NUL; the XML export shows spaces.
            out[k.hohm_type] = s.replace("\x00", " ")
    return out


def _nz(v: int) -> int | None:
    return v or None


# --- model extraction -------------------------------------------------------

def track_from_chunk(c: C.Chunk) -> Track:
    """Track rating is the track's own rating only. iTunes shows the album
    rating (haim +0x28) for unrated tracks; that is "Rating Computed" in XML."""
    h = c.head
    s = _strings(c)
    u32 = c.u32
    u16 = c.u16
    loc = s.get(S_URL)
    location = url_to_path(loc) if loc else s.get(S_PATH, "")
    sample_rate = struct.unpack_from("<f", h, T["sample_rate"])[0]
    return Track(
        track_id=u32(T["track_id"]),
        location=location,
        persistent_id=pid_from_bytes(h[T["persistent_id"]:T["persistent_id"] + 8]),
        name=s.get(S_NAME),
        artist=s.get(S_ARTIST),
        album_artist=s.get(S_ALBUM_ARTIST),
        album=s.get(S_ALBUM),
        composer=s.get(S_COMPOSER),
        genre=s.get(S_GENRE),
        kind=s.get(S_KIND),
        size=u32(T["size"]),
        total_time=u32(T["total_time"]),
        disc_number=_nz(u16(T["disc_number"])),
        disc_count=_nz(u16(T["disc_count"])),
        track_number=_nz(u16(T["track_number"])),
        track_count=_nz(u16(T["track_count"])),
        year=_nz(u16(T["year"])),
        bpm=_nz(u16(T["bpm"])),
        bit_rate=_nz(u32(T["bit_rate"])),
        sample_rate=int(sample_rate) or None,
        date_modified=mac_to_datetime(u32(T["date_modified"])) or _epoch(),
        date_added=mac_to_datetime(u32(T["date_added"])) or _epoch(),
        play_count=u32(T["play_count"]),
        rating=_nz(h[T["rating"]]),
        comments=s.get(S_COMMENTS),
        compilation=bool(h[T["compilation"]]),
    )


def _epoch() -> datetime:
    return MAC_EPOCH.replace(tzinfo=timezone.utc)


def playlist_from_chunk(c: C.Chunk) -> Playlist:
    h = c.head
    s = _strings(c)
    master = bool(h[P["master"]])
    name = s.get(S_PLAYLIST_NAME, "")
    if master and name == MASTER_NAME_TOKEN:
        name = "Library"
    dk = h[P["distinguished_kind"]]
    return Playlist(
        playlist_id=c.u32(P["playlist_id"]),
        name=name,
        track_ids=[k.u32(I_TRACK_ID) for k in c.kids("hptm")],
        persistent_id=pid_from_bytes(h[P["persistent_id"]:P["persistent_id"] + 8]),
        master=master,
        distinguished_kind=dk or None,
    )


def to_library(itl: ItlFile) -> Library:
    h = itl.header
    lib = Library(
        persistent_id=bytes(h[HDFM_LIBRARY_PID:HDFM_LIBRARY_PID + 8]).hex().upper(),
        application_version=itl.version,
        date=mac_to_datetime(struct.unpack_from(">I", h, HDFM_DATE)[0]) or _epoch(),
    )
    tracks = itl.section(C.SEC_TRACKS)
    if tracks:
        lib.tracks = [track_from_chunk(c) for c in tracks.items("htim")]
    pls = itl.section(C.SEC_PLAYLISTS)
    if pls:
        lib.playlists = [playlist_from_chunk(c) for c in pls.items("hpim")]
    mf = itl.section(C.SEC_MUSIC_FOLDER)
    if mf and mf.raw:
        folder = url_to_path(mf.raw.decode("latin-1"))
        # match xml_reader: no trailing separator (unless it is a root like C:\)
        stripped = folder.rstrip("\\/")
        lib.music_folder = stripped if len(stripped) > 2 else folder
    return lib


def read_itl(path: str | os.PathLike) -> Library:
    """Read an iTunes 12.x "iTunes Library.itl" (decrypt, inflate, parse) into a Library."""
    return to_library(load_itl(path))
