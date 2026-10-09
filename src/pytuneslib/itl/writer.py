"""Build an iTunes 12.x .itl file from a :class:`model.Library`.

Everything is generated from the model; bytes iTunes needs but the model does
not describe come from ``_defaults`` (per-byte mode of a real iTunes 12.13
library, ids/pids/dates scrubbed; regenerate with tools/gen_itl_defaults.py).

ID space: iTunes uses one counter for albums, artists, tracks (2 ids each:
track_id and track_id+1), playlists and playlist items. Model track/playlist
ids are kept; albums, artists and items get fresh ids above all of them.
"""

from __future__ import annotations

import dataclasses
import os
import secrets
import struct
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from ..limits import clamp_text
from ..model import Library, Playlist, Track
from ..xml_writer import path_to_file_url
from . import _defaults as D
from . import chunks as C
from .crypto import encrypt_file
from .reader import (
    HDFM_ALBUM_COUNT, HDFM_ARTIST_COUNT, HDFM_SECTION_COUNT, HDFM_DATE, HDFM_LIBRARY_PID, HDFM_PLAYLIST_COUNT,
    HDFM_TRACK_COUNT, HDFM_TZ_OFFSET, HDFM_VERSION, I_ITEM_ID, I_TRACK_ID, MASTER_NAME_TOKEN,
    A, P, R, S_ALBUM, S_ALBUM_ARTIST, S_ALBUM_ARTIST_A, S_ALBUM_ARTIST_B, S_ALBUM_NAME,
    S_ARTIST, S_ARTIST_NAME, S_COMMENTS, S_COMPOSER, S_GENRE, S_KIND, S_NAME, S_PATH,
    S_PLAYLIST_NAME, S_URL, T, ItlFile, datetime_to_mac, pid_to_bytes,
)

# htim codec code (+0x50) by file type; observed in iTunes 12.13
CODEC_MP3, CODEC_AAC, CODEC_ALAC, CODEC_PCM = 12, 51, 60, 70
HTIM_LOSSLESS_FLAG = 0x128  # 2 for ALAC/AIFF/WAV, 0 for lossy
HPTM_ITEM_PID = 0x44
HAIM_COMPILATION = 0x1D
HGHM_DATE_CREATED = 0xB4  # library creation date (mac secs); iTunes sets it on a fresh library
HPIM_DATE_CREATED = 0x1C  # playlist creation date

_MP4_EXTS = {"m4a", "m4p", "m4b", "aac", "mp4", "m4v"}
_PCM_EXTS = {"aif", "aiff", "aifc", "wav"}


# hohm +0x10 is a string-pool id (verified on the sample: same string -> same id, distinct strings
# -> distinct ids, case-sensitive). iTunes resolves the displayed artist/album through the pool, so
# a collision shows another record's string. Types sharing one pool:
_POOLS = {
    4: "artist", 12: "artist", 27: "artist", 301: "artist", 302: "artist", 400: "artist",
    3: "album", 300: "album",
    32: "sort_artist", 33: "sort_artist", 401: "sort_artist",
}
_UNIQUE = {2, 8, 18, 30}  # name, comments, ...: a fresh id per occurrence, never shared
_FIXED = {13: 1, 11: 2}  # path / URL: what iTunes writes in a fresh library


class _Interner:
    """Allocates hohm +0x10 ids. Pools not listed in _POOLS are per hohm type."""

    def __init__(self) -> None:
        self.pools: dict[str, dict[str, int]] = {}
        self.counters: dict[int, int] = {}

    def __call__(self, owner: str, htype: int, text: str) -> int:
        if htype in _FIXED:
            return _FIXED[htype]
        if htype in _UNIQUE:
            self.counters[htype] = self.counters.get(htype, 0) + 1
            return self.counters[htype]
        table = self.pools.setdefault(_POOLS.get(htype, f"{owner}:{htype}"), {})
        return table.setdefault(text, len(table) + 1)


def _nfc(text: str) -> str:
    """iTunes stores tag strings NFC-normalized (it shows 'Tiësto', never the NFD form)."""
    return unicodedata.normalize("NFC", text)


def _hohm(intern: _Interner, owner: str, htype: int, text: str, *, url: bool = False) -> C.Chunk:
    if htype not in _FIXED:  # paths/URLs must match the filesystem byte-for-byte
        text = _nfc(text)
        if owner in ("htim", "haim", "hiim"):
            text = clamp_text(text)
    c = C.make_hohm_string(htype, text, ascii_url=url)
    c.set_u32(16, intern(owner, htype, text))
    return c


def _blob(b: bytes) -> C.Chunk:
    return C.Chunk("hohm", bytearray(b))


def _ext(location: str) -> str:
    name = PureWindowsPath(location).name if "\\" in location else os.path.basename(location)
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _codec(ext: str, kind: str | None) -> int:
    if ext in _PCM_EXTS:
        return CODEC_PCM
    if ext in _MP4_EXTS:
        return CODEC_ALAC if kind and "lossless" in kind.lower() else CODEC_AAC
    return CODEC_MP3


def _file_type(ext: str) -> bytes:
    return ext.upper().encode("ascii", "replace")[:4].ljust(4)[::-1]


def _rand_pid() -> bytes:
    return secrets.token_bytes(8)


def _mac(dt: datetime | None) -> int:
    return datetime_to_mac(dt) if dt else 0


def _album_artist_key(t: Track) -> str:
    return t.album_artist or t.artist or ""


class _Builder:
    def __init__(self, lib: Library, library_name: str, music_folder: str | None = None):
        self.lib = lib
        self.library_name = library_name
        self.music_folder = music_folder if music_folder is not None else lib.music_folder
        self.intern = _Interner()
        used = [t.track_id + 1 for t in lib.tracks] + [p.playlist_id for p in lib.playlists]
        self.next_id = max(used, default=0) + 1
        self.albums: dict[tuple[str, str, bool], C.Chunk] = {}
        self.artists: dict[str, C.Chunk] = {}

    def new_id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i

    # -- albums / artists ---------------------------------------------------
    def album_for(self, t: Track) -> int:
        key = (t.album or "", _album_artist_key(t), t.compilation)
        c = self.albums.get(key)
        if c is None:
            c = C.Chunk("haim", bytearray(D.HAIM))
            c.set_u32(A["album_id"], self.new_id())
            c.head[A["persistent_id"]:A["persistent_id"] + 8] = _rand_pid()
            c.head[A["track_pid"]:A["track_pid"] + 8] = pid_to_bytes(t.persistent_id)
            c.head[HAIM_COMPILATION] = 1 if t.compilation else 0
            if t.album:
                c.children.append(_hohm(self.intern, "haim", S_ALBUM_NAME, t.album))
            if key[1]:
                c.children.append(_hohm(self.intern, "haim", S_ALBUM_ARTIST_A, key[1]))
            if t.album_artist:
                c.children.append(_hohm(self.intern, "haim", S_ALBUM_ARTIST_B, t.album_artist))
            c.set_u32(A["hohm_count"], len(c.children))
            self.albums[key] = c
        return c.u32(A["album_id"])

    def artist_for(self, t: Track) -> int:
        key = _album_artist_key(t)
        c = self.artists.get(key)
        if c is None:
            c = C.Chunk("hiim", bytearray(D.HIIM))
            c.set_u32(R["artist_id"], self.new_id())
            c.head[R["persistent_id"]:R["persistent_id"] + 8] = _rand_pid()
            if key:
                c.children.append(_hohm(self.intern, "hiim", S_ARTIST_NAME, key))
            c.set_u32(R["hohm_count"], len(c.children))
            self.artists[key] = c
        return c.u32(R["artist_id"])

    # -- tracks ---------------------------------------------------------------
    def track(self, t: Track) -> C.Chunk:
        c = C.Chunk("htim", bytearray(D.HTIM))
        h = c.head
        ext = _ext(t.location)
        c.set_u32(T["track_id"], t.track_id)
        c.set_u32(T["track_id2"], t.track_id + 1)
        c.set_u32(T["date_modified"], _mac(t.date_modified))
        c.set_u32(T["date_added"], _mac(t.date_added))
        c.set_u32(T["size"], t.size)
        c.set_u32(T["size2"], t.size)
        c.set_u32(T["total_time"], t.total_time)
        c.set_u32(T["track_number"], t.track_number or 0)
        c.set_u32(T["track_count"], t.track_count or 0)
        c.set_u32(T["year"], t.year or 0)
        c.set_u32(T["bit_rate"], t.bit_rate or 0)
        c.set_u32(T["codec"], _codec(ext, t.kind))
        h[HTIM_LOSSLESS_FLAG] = 2 if _codec(ext, t.kind) in (CODEC_ALAC, CODEC_PCM) else 0
        h[T["compilation"]] = 1 if t.compilation else 0
        c.set_u32(T["play_count"], t.play_count)
        c.set_u32(T["play_count2"], t.play_count)
        c.set_u32(T["play_date"], 0)
        c.set_u16(T["disc_number"], t.disc_number or 0)
        c.set_u16(T["disc_count"], t.disc_count or 0)
        h[T["rating"]] = t.rating or 0
        h[T["persistent_id"]:T["persistent_id"] + 8] = pid_to_bytes(t.persistent_id)
        h[T["file_type"]:T["file_type"] + 4] = _file_type(ext)
        c.set_u16(T["artwork_count"], 0)
        struct.pack_into("<f", h, T["sample_rate"], float(t.sample_rate or 0))
        c.set_u16(T["bpm"], t.bpm or 0)
        c.set_u32(T["skip_count"], 0)
        c.set_u32(T["skip_date"], 0)
        c.set_u32(T["album_id"], self.album_for(t))
        c.set_u32(T["artist_id"], self.artist_for(t))

        o = "htim"
        for htype, val in ((S_NAME, t.name), (S_ARTIST, t.artist), (S_ALBUM_ARTIST, t.album_artist),
                           (S_ALBUM, t.album), (S_GENRE, t.genre), (S_KIND, t.kind),
                           (S_COMMENTS, t.comments), (S_COMPOSER, t.composer)):
            if val:
                c.children.append(_hohm(self.intern, o, htype, val))
        if t.location:
            c.children.append(_hohm(self.intern, o, S_PATH, t.location))
            c.children.append(_hohm(self.intern, o, S_URL, path_to_file_url(t.location), url=True))
        c.set_u32(T["hohm_count"], len(c.children))
        return c

    # -- playlists ------------------------------------------------------------
    def playlist(self, p: Playlist) -> C.Chunk:
        if p.master:
            head, kids, name = D.HPIM_MASTER, D.HPIM_MASTER_KIDS, MASTER_NAME_TOKEN
        elif p.distinguished_kind == 4:
            head, kids, name = D.HPIM_MUSIC, D.HPIM_MUSIC_KIDS, p.name
        else:
            head, kids, name = D.HPIM, D.HPIM_KIDS, p.name
        c = C.Chunk("hpim", bytearray(head))
        h = c.head
        c.set_u32(P["playlist_id"], p.playlist_id)
        c.set_u32(HPIM_DATE_CREATED, _mac(self.lib.date))
        h[P["persistent_id"]:P["persistent_id"] + 8] = pid_to_bytes(p.persistent_id)
        h[P["master"]] = 1 if p.master else 0
        h[P["distinguished_kind"]] = p.distinguished_kind or 0
        name_hohm = _hohm(self.intern, "hpim", S_PLAYLIST_NAME, name)
        name_hohm.set_u32(16, 0 if p.master else 4)  # as iTunes writes it (not a pool id)
        c.children.append(name_hohm)
        c.children += [_blob(b) for b in kids]
        c.set_u32(P["hohm_count"], len(c.children))
        for tid in p.track_ids:
            it = C.Chunk("hptm", bytearray(D.HPTM))
            it.set_u32(I_ITEM_ID, self.new_id())
            it.set_u32(I_TRACK_ID, tid)
            it.head[HPTM_ITEM_PID:HPTM_ITEM_PID + 8] = _rand_pid()
            c.children.append(it)
        c.set_u32(P["item_count"], len(p.track_ids))
        return c

    # -- library-level --------------------------------------------------------
    def library_section(self) -> C.Section:
        s = C.new_section(C.SEC_LIBRARY)
        gh = C.Chunk("hghm", bytearray(D.HGHM))
        gh.set_u32(HGHM_DATE_CREATED, _mac(self.lib.date))
        gh.children.append(_hohm(self.intern, "hghm", 508, self.library_name))
        gh.children.append(_blob(D.HGHM_517))
        s.chunks.append(gh)
        return s

    def build(self) -> ItlFile:
        lib = self.lib
        tracks = [self.track(t) for t in lib.tracks]
        # Built-in playlists other than master/Music (Podcasts, Movies, ...; distinguished kinds) have
        # no template here; iTunes recreates them on open, so they are not written.
        playlists = [p for p in lib.playlists if p.master or p.distinguished_kind in (None, 4)]
        known = {t.track_id for t in lib.tracks}
        playlists = [dataclasses.replace(p, track_ids=[i for i in p.track_ids if i in known])
                     for p in playlists]
        if not any(p.master for p in playlists):
            playlists.insert(0, Playlist(playlist_id=self.new_id(), name="Library", master=True,
                                         track_ids=[t.track_id for t in lib.tracks]))
        hpims = [self.playlist(p) for p in playlists]

        def sec(sec_type: int, *chs: C.Chunk) -> C.Section:
            s = C.new_section(sec_type)
            s.chunks.extend(chs)
            return s

        def head(tag: str, b: bytes) -> C.Chunk:
            return C.Chunk(tag, bytearray(b))

        hpsm = head("hpsm", D.HPSM)
        hpsm.children.append(_blob(D.HPSM_800))
        mf = C.new_section(C.SEC_MUSIC_FOLDER)
        mf.chunks = None
        mf.raw = self._music_folder_url().encode("ascii")

        sections = [
            sec(C.SEC_HDFM, head("hdfm", D.HDFM_INNER)),
            self.library_section(),
            sec(C.SEC_ALBUMS, head("halm", D.HALM), *self.albums.values()),
            sec(C.SEC_ARTISTS, head("hilm", D.HILM), *self.artists.values()),
            sec(C.SEC_TRACKS, head("htlm", D.HTLM), *tracks),
            sec(C.SEC_TRACKS2, head("htlm", D.HTLM2)),
            # No hqlm (section 20, Up Next): iTunes 12.13 rejects a synthesized empty one as
            # "Damaged", and a library it creates itself omits the section.
            sec(C.SEC_HSTS, head("hsts", D.HSTS)),
            sec(C.SEC_PLAYLISTS, head("hplm", D.HPLM), *hpims),
            sec(C.SEC_GENIUS, head("hplm", D.HPLM_GENIUS)),
            sec(C.SEC_HSLM, head("hslm", D.HSLM), hpsm),
            mf,
            sec(C.SEC_HRLM, head("hrlm", D.HRLM)),
        ]
        header = bytearray(D.HDFM_OUTER)
        for h, e in ((header, ">"), (sections[0].chunks[0].head, "<")):
            self._patch_hdfm(h, e, len(tracks), len(hpims))
            struct.pack_into(e + "I", h, HDFM_SECTION_COUNT, len(sections))
        return ItlFile(header, sections)

    def _music_folder_url(self) -> str:
        folder = self.music_folder
        if not folder:
            return ""
        url = path_to_file_url(folder)
        return url if url.endswith("/") else url + "/"

    def _patch_hdfm(self, h: bytearray, e: str, n_tracks: int, n_playlists: int) -> None:
        lib = self.lib
        ver = lib.application_version.encode("ascii")[:31]
        h[HDFM_VERSION:HDFM_VERSION + 32] = bytes([len(ver)]) + ver.ljust(31, b"\0")
        pid = bytes.fromhex(lib.persistent_id)
        h[HDFM_LIBRARY_PID:HDFM_LIBRARY_PID + 8] = pid if e == ">" else pid[::-1]
        struct.pack_into(e + "I", h, HDFM_TRACK_COUNT, n_tracks)
        struct.pack_into(e + "I", h, HDFM_PLAYLIST_COUNT, n_playlists)
        struct.pack_into(e + "I", h, HDFM_ALBUM_COUNT, len(self.albums))
        struct.pack_into(e + "I", h, HDFM_ARTIST_COUNT, len(self.artists))
        date = lib.date or datetime.now(timezone.utc)
        struct.pack_into(e + "I", h, HDFM_DATE, datetime_to_mac(date))
        offset = date.astimezone().utcoffset()
        struct.pack_into(e + "i", h, HDFM_TZ_OFFSET, int(offset.total_seconds()) if offset else 0)


def build_itl(lib: Library, *, library_name: str = "iTunes Library",
              music_folder: str | None = None) -> ItlFile:
    """music_folder overrides lib.music_folder for the itl's Music Folder (section 4)."""
    return _Builder(lib, library_name, music_folder).build()


def itl_bytes(lib: Library, *, library_name: str = "iTunes Library",
              music_folder: str | None = None) -> bytes:
    """Encode lib as the bytes of an .itl file (see write_itl for music_folder)."""
    itl = build_itl(lib, library_name=library_name, music_folder=music_folder)
    return encrypt_file(bytes(itl.header), itl.payload())


def default_music_folder(itl_path: str | Path) -> str:
    """iTunes' default media folder for a library file: <library dir>/iTunes Media."""
    return str(Path(itl_path).resolve().parent / "iTunes Media")


def write_itl(lib: Library, path: str | Path, *, library_name: str = "iTunes Library",
              music_folder: str | None = None) -> Path:
    """Write lib as an iTunes 12.13 .itl.

    The Music Folder defaults to <path dir>/iTunes Media, NOT lib.music_folder: on open iTunes
    resets it to the media folder from its own settings (the default one for a fresh library)
    and remaps every track located under the old folder into the new one, e.g.
    <scan root>/A/B/x.m4a -> <lib dir>/iTunes Media/A/B/x.m4a (a file that does not exist).
    Pass music_folder explicitly only when it is the folder iTunes is configured to use.
    """
    path = Path(path)
    if _is_real_itunes_dir(path):
        raise PermissionError(f"refusing to overwrite a live iTunes library: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    folder = music_folder if music_folder is not None else default_music_folder(path)
    path.write_bytes(itl_bytes(lib, library_name=library_name, music_folder=folder))
    return path


def _is_real_itunes_dir(path: Path) -> bool:
    """Guard: never write into the user's live library folder (~/Music/iTunes)."""
    live = Path.home() / "Music" / "iTunes"
    try:
        return path.resolve().parent == live.resolve() and not os.environ.get("PYTUNESLIB_ALLOW_LIVE")
    except OSError:
        return False
