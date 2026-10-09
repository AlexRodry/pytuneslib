"""Public API (pytuneslib.*), iTunes text limits, custom playlists and _defaults hygiene."""

import re
import struct
from datetime import datetime, timezone

import pytest

import pytuneslib
from pytuneslib import (Library, Playlist, Track, add_playlist, build_library, itl_bytes, read_itl,
                        read_xml, write_library)
from pytuneslib.itl import _defaults as D
from pytuneslib.limits import MAX_TEXT, clamp_text

D0 = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def _lib(n=3) -> Library:
    tracks = [Track(track_id=1000 + 2 * i, location=rf"C:\M\{i}.mp3", name=f"T{i}", artist="A",
                    album="Al", size=1, total_time=1000, date_modified=D0, date_added=D0)
              for i in range(n)]
    return Library(tracks=tracks, date=D0, persistent_id="0123456789ABCDEF")


def test_all_exports_exist():
    assert all(hasattr(pytuneslib, n) for n in pytuneslib.__all__)
    for n in ("build_library", "write_library", "scan", "read_xml", "write_xml", "read_itl",
              "write_itl", "itl_bytes", "add_playlist", "Library", "Track", "Playlist"):
        assert n in pytuneslib.__all__


# --- 255-char limit ---------------------------------------------------------------

def test_clamp_text_utf16_units_and_surrogates():
    assert clamp_text("x" * 300) == "x" * MAX_TEXT
    assert clamp_text("short") == "short"
    assert clamp_text(None) is None
    s = "a" * 254 + "\U0001F600" + "b"  # emoji = 2 UTF-16 units: would straddle the limit
    assert clamp_text(s) == "a" * 254


def test_long_text_clamped_identically_in_xml_and_itl(tmp_path):
    lib = _lib(1)
    lib.tracks[0].album_artist = "Ж" * 700
    lib.tracks[0].comments = "c" * 1000
    files = write_library(lib, tmp_path)
    for back in (read_itl(files["itl"]), read_xml(files["xml"])):
        t = back.tracks[0]
        assert t.album_artist == "Ж" * MAX_TEXT and t.comments == "c" * MAX_TEXT
    assert lib.tracks[0].location == r"C:\M\0.mp3"  # paths never clamped


def test_itl_writer_clamps_even_without_builder():
    lib = _lib(1)
    lib.tracks[0].name = "n" * 400
    from pytuneslib.itl.reader import parse_itl, to_library
    assert to_library(parse_itl(itl_bytes(lib))).tracks[0].name == "n" * MAX_TEXT


# --- custom playlists -----------------------------------------------------------------

def test_add_playlist_and_write_roundtrip(tmp_path):
    lib = _lib(4)
    fav = add_playlist(lib, "Favourites ★", [lib.tracks[2], lib.tracks[0].track_id])
    assert fav.playlist_id > max(t.track_id + 1 for t in lib.tracks)
    with pytest.raises(ValueError):
        add_playlist(lib, "bad", [999999])
    files = write_library(lib, tmp_path)
    for back in (read_itl(files["itl"]), read_xml(files["xml"])):
        p = next(p for p in back.playlists if p.name == "Favourites ★")
        assert p.track_ids == [1004, 1000] and not p.master
        assert p.persistent_id == fav.persistent_id
        assert sum(p.master for p in back.playlists) == 1  # master added by the writer


def test_itl_edit_cycle_keeps_custom_playlists(tmp_path):
    lib = _lib(3)
    add_playlist(lib, "One", lib.tracks[:1])
    write_library(lib, tmp_path)
    again = read_itl(tmp_path / "iTunes Library.itl")
    add_playlist(again, "Two", again.tracks[1:])
    write_library(again, tmp_path / "v2")
    names = [p.name for p in read_itl(tmp_path / "v2" / "iTunes Library.itl").playlists]
    assert names.count("One") == 1 and names.count("Two") == 1 and names.count("Library") == 1


def test_writer_skips_builtins_and_dangling_track_ids():
    lib = _lib(2)
    lib.playlists = [Playlist(5000, "Library", [1000, 1002], master=True),
                     Playlist(5001, "Podcasts", [], distinguished_kind=10),
                     Playlist(5002, "Mine", [1000, 4242])]
    from pytuneslib.itl.reader import parse_itl, to_library
    back = to_library(parse_itl(itl_bytes(lib)))
    assert [p.name for p in back.playlists] == ["Library", "Mine"]
    assert back.playlists[1].track_ids == [1000]


def test_build_library_end_to_end_with_playlist(music_dir, tmp_path):
    lib, files = build_library(music_dir, tmp_path / "lib")
    add_playlist(lib, "Mix", lib.tracks[::2])
    write_library(lib, tmp_path / "lib")
    back = read_itl(files["itl"])
    assert [p.track_ids for p in back.playlists if p.name == "Mix"] == [[t.track_id for t in lib.tracks[::2]]]
    assert back.music_folder == str((tmp_path / "lib" / "iTunes Media").resolve())


# --- _defaults must not carry data from the library it was generated from ---------------

def _blobs():
    for k, v in vars(D).items():
        if isinstance(v, bytes):
            yield k, v
        elif isinstance(v, list):
            yield from ((f"{k}[{i}]", b) for i, b in enumerate(v))


def test_defaults_have_no_source_library_dates():
    singletons = {"HGHM", "HTIM", "HPIM_MASTER", "HPIM_MUSIC", "HPIM"}
    for k, b in _blobs():
        if k in singletons:
            dates = [hex(o) for o in range(0x10, len(b) - 3, 4)
                     if 0xB2000000 <= struct.unpack_from("<I", b, o)[0] < 0xF0000000]
            assert dates == [], k
        assert set(re.findall(rb"<date>([^<]*)</date>", b)) <= {b"2001-01-01T00:00:00Z"}, k
    assert struct.unpack_from("<II", D.HPIM_MASTER, 0x20) == (0, 0)  # source library totals
