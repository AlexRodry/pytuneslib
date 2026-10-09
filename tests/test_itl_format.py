"""ITL crypto / chunk tree / reader / writer tests (pgOpus).

Sample-based tests skip when samples/ is missing; synthetic ones always run.
"""
import dataclasses
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pytuneslib.itl import chunks as C
from pytuneslib.itl.crypto import decrypt_file, encrypt_file, encode_payload, decode_payload
from pytuneslib.itl.reader import load_itl, parse_itl, read_itl, to_library
from pytuneslib.itl.writer import build_itl, itl_bytes, write_itl
from pytuneslib.xml_writer import MUSIC_SMART_CRITERIA, MUSIC_SMART_INFO
from pytuneslib.model import Library, Playlist, Track

SAMPLE_ITL = Path(__file__).resolve().parent.parent / "samples" / "iTunes Library.itl"
SAMPLE_XML = SAMPLE_ITL.with_name("iTunes Music Library.xml")


@pytest.fixture(scope="module")
def sample_raw() -> bytes:
    if not SAMPLE_ITL.exists():
        pytest.skip("samples/iTunes Library.itl not present")
    return SAMPLE_ITL.read_bytes()


def _lib() -> Library:
    d = datetime(2024, 3, 5, 10, 20, 30, tzinfo=timezone.utc)
    tracks = [
        Track(1000, r"C:\Music\A\Alb\01 One.mp3", name="One", artist="A", album="Alb",
              album_artist="A", genre="Pop", kind="MPEG audio file", size=1234, total_time=61000,
              track_number=1, track_count=2, disc_number=1, disc_count=1, year=2020, bpm=120,
              bit_rate=320, sample_rate=44100, date_added=d, date_modified=d, rating=80,
              comments="hi", composer="Comp"),
        Track(1002, r"C:\Music\A\Alb\02 Tiësto ünï.m4a", name="Tiësto", artist="A", album="Alb",
              kind="Apple Lossless audio file", size=99, total_time=1000, sample_rate=48000,
              date_added=d, date_modified=d),
        Track(1004, r"C:\Music\Б\Ж — x.wav", name="Ж — ’quote’", artist="Б", kind="WAV audio file",
              date_added=d, date_modified=d, compilation=True),
    ]
    pls = [Playlist(5000, "Library", [1000, 1002, 1004], master=True, visible=False),
           Playlist(5001, "Music", [1000, 1002, 1004], distinguished_kind=4,
                    smart_info=MUSIC_SMART_INFO, smart_criteria=MUSIC_SMART_CRITERIA),
           Playlist(5002, "Mine", [1004, 1000])]
    return Library(tracks=tracks, playlists=pls, music_folder=r"C:\Music", date=d,
                   persistent_id="0123456789ABCDEF")


def _diff(a: Library, b: Library) -> list[str]:
    out = []
    for f in ("persistent_id", "application_version", "music_folder", "date"):
        if getattr(a, f) != getattr(b, f):
            out.append(f"library.{f}: {getattr(a, f)!r} != {getattr(b, f)!r}")
    for x, y in zip(a.tracks, b.tracks, strict=True):
        for f in dataclasses.fields(x):
            if getattr(x, f.name) != getattr(y, f.name):
                out.append(f"track {x.track_id}.{f.name}: {getattr(x, f.name)!r} != {getattr(y, f.name)!r}")
    bp = {p.playlist_id: p for p in b.playlists}
    for p in a.playlists:
        q = bp.get(p.playlist_id)
        if q is None:
            out.append(f"playlist {p.playlist_id} missing")
            continue
        for f in dataclasses.fields(p):
            if f.name != "name" or not p.master:
                if getattr(p, f.name) != getattr(q, f.name):
                    out.append(f"playlist {p.playlist_id}.{f.name}: {getattr(p, f.name)!r} != {getattr(q, f.name)!r}")
    return out


# --- crypto ------------------------------------------------------------------

def test_crypto_sample_roundtrip_byte_identical(sample_raw):
    header, data = decrypt_file(sample_raw)
    assert data[:4] == b"msdh"
    assert encrypt_file(header, data) == sample_raw


def test_crypto_partial_encryption_and_zlib():
    data = bytes(range(256)) * 2000
    enc = encode_payload(data)
    assert decode_payload(enc) == data
    assert enc[:2] != b"\x78\x01"  # first block encrypted
    small = encode_payload(b"x" * 10)  # < one AES block stays plain
    assert decode_payload(small) == b"x" * 10


# --- chunk tree ----------------------------------------------------------------

def test_chunk_tree_sample_roundtrip_byte_identical(sample_raw):
    itl = parse_itl(sample_raw)
    assert itl.to_bytes() == sample_raw


def test_chunk_tree_recomputes_lengths(sample_raw):
    itl = parse_itl(sample_raw)
    tr = itl.section(C.SEC_TRACKS)
    tr.chunks.pop()  # drop last track
    back = parse_itl(itl.to_bytes())
    assert len(back.section(C.SEC_TRACKS).items("htim")) == len(tr.items("htim"))
    assert back.section(C.SEC_TRACKS).chunks[0].u32(8) == len(tr.items("htim"))


# --- reader --------------------------------------------------------------------

def test_reader_sample_basics(sample_raw):
    """Expected values come from the matching XML export at runtime (no library data in the repo)."""
    from pytuneslib.xml_reader import read_xml

    if not SAMPLE_XML.exists():
        pytest.skip("sample xml missing")
    lib, ref = to_library(parse_itl(sample_raw)), read_xml(SAMPLE_XML)
    assert lib.persistent_id == ref.persistent_id
    assert lib.application_version == ref.application_version
    assert len(lib.tracks) == len(ref.tracks)
    assert sum(p.master for p in lib.playlists) == 1
    assert lib.music_folder and lib.music_folder.endswith("iTunes Media")
    by_id = {t.track_id: t for t in lib.tracks}
    fields = ("name", "artist", "album_artist", "persistent_id", "size", "total_time",
              "track_number", "year", "bpm", "bit_rate", "sample_rate")
    for r in ref.tracks[::50]:
        t = by_id[r.track_id]
        assert [getattr(t, f) for f in fields] == [getattr(r, f) for f in fields], r.track_id


# --- writer --------------------------------------------------------------------

def test_writer_synthetic_roundtrip(tmp_path):
    lib = _lib()
    path = write_itl(lib, tmp_path / "iTunes Library.itl", music_folder=lib.music_folder)
    raw = path.read_bytes()
    assert raw[:4] == b"hdfm" and struct.unpack(">I", raw[8:12])[0] == len(raw)
    back = read_itl(path)
    assert _diff(lib, back) == []


def test_writer_header_counts_and_ids():
    lib = _lib()
    itl = build_itl(lib)
    h = itl.header
    assert struct.unpack_from(">IIII", h, 0x44)[:3] == (3, 3, 2)  # tracks, playlists, albums
    assert struct.unpack_from(">I", h, 0x54)[0] == 2  # artists: "A", "Б"
    assert bytes(h[0x34:0x3C]).hex().upper() == lib.persistent_id
    inner = itl.section(C.SEC_HDFM).chunks[0]
    assert inner.u32(0x44) == 3
    ids = [c.u32(0x10) for s in (C.SEC_ALBUMS, C.SEC_ARTISTS) for c in itl.section(s).chunks[1:]]
    ids += [k.u32(0x10) for p in itl.section(C.SEC_PLAYLISTS).items("hpim") for k in p.kids("hptm")]
    used = {t.track_id for t in lib.tracks} | {t.track_id + 1 for t in lib.tracks} | {5000, 5001, 5002}
    assert len(set(ids)) == len(ids) and not set(ids) & used


def test_writer_string_encodings():
    itl = build_itl(_lib())
    encs = {}
    for t in itl.section(C.SEC_TRACKS).items("htim"):
        for k in t.kids("hohm"):
            encs[C.hohm_string(k)] = struct.unpack_from("<I", k.head, 24)[0]
    assert encs["One"] == C.ENC_LATIN1
    assert encs["Tiësto"] == C.ENC_LATIN1
    assert encs["Ж — ’quote’"] == C.ENC_UTF16
    url = next(s for s in encs if s.startswith("file://") and "wav" in s)
    assert encs[url] == C.ENC_ASCII and "%D0%96" in url


def test_writer_adds_master_when_missing():
    lib = _lib()
    lib.playlists = [p for p in lib.playlists if not p.master]
    back = to_library(parse_itl(itl_bytes(lib)))
    master = [p for p in back.playlists if p.master]
    assert len(master) == 1 and master[0].track_ids == [1000, 1002, 1004]


def test_writer_sample_semantic_roundtrip(sample_raw):
    lib = to_library(parse_itl(sample_raw))
    # built-in playlists other than master/Music are not written (iTunes recreates them)
    lib.playlists = [p for p in lib.playlists if p.master or p.distinguished_kind in (None, 4)]
    back = to_library(parse_itl(itl_bytes(lib)))
    assert _diff(lib, back) == []


def test_write_itl_refuses_live_library_dir(fake_home):
    with pytest.raises(PermissionError):
        write_itl(_lib(), fake_home / "Music" / "iTunes" / "iTunes Library.itl")


# --- regressions found by probing real iTunes 12.13 (tools/itunes_probe.py) ----------

def test_writer_omits_up_next_section():
    """A synthesized hqlm (section 20, Up Next) makes iTunes rename the file "(Damaged)"."""
    itl = build_itl(_lib())
    assert itl.section(C.SEC_HQLM) is None
    assert [s.type for s in itl.sections] == [16, 12, 9, 11, 1, 13, 23, 2, 14, 21, 4, 15]
    assert struct.unpack_from(">I", itl.header, 0x30)[0] == len(itl.sections)


def test_write_itl_music_folder_defaults_to_library_dir(tmp_path):
    """iTunes resets the Music Folder to <lib dir>/iTunes Media and remaps tracks under the old
    folder into it; so the scan root must never be written as the Music Folder."""
    lib = _lib()  # music_folder=C:\Music, tracks live under it
    back = read_itl(write_itl(lib, tmp_path / "iTunes Library.itl"))
    assert back.music_folder == str((tmp_path / "iTunes Media").resolve())
    assert [t.location for t in back.tracks] == [t.location for t in lib.tracks]
    explicit = read_itl(write_itl(lib, tmp_path / "b.itl", music_folder=r"D:\Media"))
    assert explicit.music_folder == r"D:\Media"


# hohm +0x10 is a string-pool id; iTunes shows the artist/album via the pool, so a clash between
# e.g. a track artist and another record's album artist scrambles what it displays (lib_real bug).
_ARTIST_POOL = (4, 12, 27, 301, 302, 400)
_ALBUM_POOL = (3, 300)


def _pool_violations(itl, types) -> list[str]:
    id2s: dict[int, set] = {}
    s2id: dict[str, set] = {}
    for sec in itl.sections:
        for ch in sec.chunks or []:
            for k in ch.kids("hohm"):
                if k.hohm_type in types:
                    s = C.hohm_string(k)
                    id2s.setdefault(k.u32(16), set()).add(s)
                    s2id.setdefault(s, set()).add(k.u32(16))
    return ([f"id {i} -> {sorted(v)}" for i, v in id2s.items() if len(v) > 1]
            + [f"{s!r} -> ids {sorted(v)}" for s, v in s2id.items() if len(v) > 1])


def _artist_mix_lib() -> Library:
    d = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def t(i, name, artist, album_artist, album, comp=False):
        return Track(track_id=i, location=rf"C:\M\{i}.mp3", persistent_id=f"{i:016X}", name=name,
                     artist=artist, album_artist=album_artist, album=album, composer=artist,
                     size=1, total_time=1, date_modified=d, date_added=d, compilation=comp)

    tracks = [t(1000, "a", "DJ Host, Guest One", "DJ Host", "Mix One"),
              t(1002, "b", "Guest Two;Guest Three", "DJ Host", "Mix One"),
              t(1004, "c", "Guest One", "DJ Host", "Mix Two"),
              t(1006, "d", "Solo Artist", None, "Solo"),
              t(1008, "e", None, "Label Owner", "Label"),
              t(1010, "f", "X", "Various Artists", "Hits 2020", True),
              t(1012, "g", "Y", "Various Artists", "Hits 2020", True),
              t(1014, "Tiësto Remix", "Tiësto", "Tiësto", "Mix One")]
    return Library(tracks=tracks, playlists=[], date=d, persistent_id="0123456789ABCDEF")


@pytest.mark.parametrize("types", [_ARTIST_POOL, _ALBUM_POOL])
def test_sample_string_pools_are_consistent(types):
    if not SAMPLE_ITL.exists():
        pytest.skip("sample itl missing")
    assert _pool_violations(load_itl(SAMPLE_ITL), types) == []


@pytest.mark.parametrize("types", [_ARTIST_POOL, _ALBUM_POOL, (2,), (5,), (6,)])
def test_writer_string_pools_are_consistent(types):
    assert _pool_violations(build_itl(_artist_mix_lib()), types) == []


def test_writer_artist_album_artist_roundtrip_nfc(tmp_path):
    import unicodedata

    lib = _artist_mix_lib()
    back = read_itl(write_itl(lib, tmp_path / "a.itl"))
    nfc = lambda s: s and unicodedata.normalize("NFC", s)  # noqa: E731
    for a, b in zip(lib.tracks, back.tracks):
        assert (b.name, b.artist, b.album_artist, b.album, b.composer) == (
            nfc(a.name), nfc(a.artist), nfc(a.album_artist), nfc(a.album), nfc(a.composer))
    itl = build_itl(lib)
    names = [C.hohm_string(k) for c in itl.section(C.SEC_TRACKS).items("htim") for k in c.kids("hohm")
             if k.hohm_type in (2, 4)]
    assert all(unicodedata.is_normalized("NFC", s) for s in names)
    # one artist record per album artist (or artist), referenced by htim +0x1E0
    arts = {c.u32(0x10): C.hohm_string(c.kids("hohm")[0]) for c in itl.section(C.SEC_ARTISTS).items("hiim")}
    for t, c in zip(lib.tracks, itl.section(C.SEC_TRACKS).items("htim")):
        assert arts[c.u32(0x1E0)] == nfc(t.album_artist or t.artist)

