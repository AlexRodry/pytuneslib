"""Read iTunes .itl files into a chunk tree and a :class:`model.Library`."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths
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
    release_date=0xA0,  # UTC mac seconds (unlike the other dates, which are local wall-clock)
    love=0x2BF,  # u8: 2 = Loved, 3 = Disliked (3 inferred, not seen in the sample), 0/1 = neither
)
LOVED, DISLIKED = 2, 3
# haim (album) header offsets; +0x29 rating flags: 0x01 user-set, 0x20 computed
A = dict(hohm_count=0x0C, album_id=0x10, persistent_id=0x14, track_pid=0x20, rating=0x28,
         rating_flags=0x29)
ALBUM_RATING_USER, ALBUM_RATING_COMPUTED = 0x01, 0x20
S_ALBUM_NAME, S_ALBUM_ARTIST_A, S_ALBUM_ARTIST_B = 300, 301, 302
# hiim (artist) header offsets
R = dict(hohm_count=0x0C, artist_id=0x10, persistent_id=0x14)
S_ARTIST_NAME, S_ARTIST_SORT = 400, 401
# hohm string types inside htim
S_NAME, S_ALBUM, S_ARTIST, S_GENRE, S_KIND, S_COMMENTS = 2, 3, 4, 5, 6, 8
S_COMPOSER, S_PATH, S_URL, S_GROUPING, S_ALBUM_ARTIST = 12, 13, 11, 14, 27
S_SORT_NAME, S_SORT_ALBUM, S_SORT_ARTIST, S_SORT_ALBUM_ARTIST, S_SORT_COMPOSER = 30, 31, 32, 33, 34
S_WORK = 63
# hpim (playlist) header offsets
P = dict(hohm_count=0x0C, item_count=0x10, master=0x16, persistent_id=0x1B8,
         parent_pid=0x210, folder=0x20A, distinguished_kind=0x239, playlist_id=0xD40)
S_PLAYLIST_NAME = 100
# smart playlists: hohm payload at +0x18 == XML <data> byte-for-byte (verified on all 71 in the sample)
S_SMART_CRITERIA, S_SMART_INFO = 101, 102
SMART_DATA = 0x18
# built-ins iTunes keeps hidden (absent from the XML export): 7, 26 Genius, 47, 48, 64
HIDDEN_KINDS = {7, 26, 47, 48, 64}
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
    try:
        return naive.astimezone(timezone.utc)  # naive is interpreted as local time
    except (OSError, OverflowError, ValueError):  # Windows cannot localize pre-1970 dates
        return naive.replace(tzinfo=timezone.utc)


def mac_utc_to_datetime(secs: int) -> datetime | None:
    return MAC_EPOCH.replace(tzinfo=timezone.utc) + timedelta(seconds=secs) if secs else None


def datetime_to_mac(dt: datetime) -> int:
    """aware/naive-UTC datetime -> local wall-clock mac seconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        local_naive = dt.astimezone().replace(tzinfo=None)
    except (OSError, OverflowError, ValueError):  # pre-1970 on Windows
        local_naive = dt.replace(tzinfo=None)
    return int((local_naive - MAC_EPOCH).total_seconds())


def datetime_to_mac_utc(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - MAC_EPOCH.replace(tzinfo=timezone.utc)).total_seconds())


def pid_from_bytes(b: bytes) -> str:
    return bytes(b[::-1]).hex().upper()


def pid_to_bytes(pid: str) -> bytes:
    return bytes.fromhex(pid)[::-1]


def url_to_path(url: str) -> str:
    r"""file://localhost/C:/a%20b/c.mp3 -> C:\a b\c.mp3 (UNC and POSIX handled by pytuneslib.paths)."""
    return paths.from_file_url(url) if url.startswith("file:") else url


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

def track_from_chunk(c: C.Chunk, album: C.Chunk | None = None) -> Track:
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
        grouping=s.get(S_GROUPING),
        work=s.get(S_WORK),
        sort_name=s.get(S_SORT_NAME),
        sort_artist=s.get(S_SORT_ARTIST),
        sort_album=s.get(S_SORT_ALBUM),
        sort_album_artist=s.get(S_SORT_ALBUM_ARTIST),
        sort_composer=s.get(S_SORT_COMPOSER),
        loved=h[T["love"]] == LOVED,
        disliked=h[T["love"]] == DISLIKED,
        play_date=mac_to_datetime(u32(T["play_date"])),
        skip_count=u32(T["skip_count"]),
        skip_date=mac_to_datetime(u32(T["skip_date"])),
        release_date=mac_utc_to_datetime(u32(T["release_date"])),
        album_rating=_album_rating(album),
    )


def _album_rating(album: C.Chunk | None) -> int | None:
    """Only a user-set album rating; a computed one (flag 0x20) is not stored in the model."""
    if album is None or not album.head[A["rating_flags"]] & ALBUM_RATING_USER:
        return None
    return album.head[A["rating"]] or None


def smart_blobs(c: C.Chunk) -> tuple[bytes | None, bytes | None]:
    """(smart_info, smart_criteria) raw payloads of an hpim, or (None, None)."""
    k = {x.hohm_type: x for x in c.kids("hohm")}

    def get(t: int) -> bytes | None:
        return bytes(k[t].head[SMART_DATA:]) if t in k else None

    return get(S_SMART_INFO), get(S_SMART_CRITERIA)


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
    info, criteria = smart_blobs(c)
    parent = bytes(h[P["parent_pid"]:P["parent_pid"] + 8])
    return Playlist(
        playlist_id=c.u32(P["playlist_id"]),
        name=name,
        track_ids=[k.u32(I_TRACK_ID) for k in c.kids("hptm")],
        persistent_id=pid_from_bytes(h[P["persistent_id"]:P["persistent_id"] + 8]),
        master=master,
        distinguished_kind=dk or None,
        visible=not master and dk not in HIDDEN_KINDS,
        folder=bool(h[P["folder"]]),
        parent_persistent_id=pid_from_bytes(parent) if any(parent) else None,
        smart_info=info,
        smart_criteria=criteria,
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
        albums_sec = itl.section(C.SEC_ALBUMS)
        albums = {a.u32(A["album_id"]): a for a in albums_sec.items("haim")} if albums_sec else {}
        lib.tracks = [track_from_chunk(c, albums.get(c.u32(T["album_id"])))
                      for c in tracks.items("htim")]
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
