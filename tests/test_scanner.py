import plistlib
import unicodedata
from pathlib import PurePath

import pytest

from pytuneslib.scanner import scan
from pytuneslib.xml_reader import library_from_bytes
from pytuneslib.xml_writer import library_to_xml

KINDS = {
    "mp3": "MPEG audio file",
    "aac": "AAC audio file",
    "alac": "Apple Lossless audio file",
    "wav": "WAV audio file",
    "aiff": "AIFF audio file",
}


def _rel(lib_root, t):
    return PurePath(t.location).relative_to(lib_root.resolve()).as_posix()


@pytest.fixture(scope="module")
def lib(music_dir):
    return scan(music_dir)


def test_flac_skipped_by_default(lib, music_expected):
    supported = [k for k, v in music_expected.items() if v["itunes_supported"]]
    assert len(lib.tracks) == len(supported)
    assert not any(t.location.endswith(".flac") for t in lib.tracks)


def test_tags_match_expected(lib, music_dir, music_expected):
    root = music_dir.resolve()
    by_rel = {_rel(root, t): t for t in lib.tracks}
    supported = {k: v for k, v in music_expected.items() if v["itunes_supported"]}
    assert set(by_rel) == set(supported)
    for rel, exp in supported.items():
        t = by_rel[rel]
        stem = PurePath(rel).stem
        if exp["has_tags"]:
            # the scanner NFC-normalizes tag text like iTunes does (raw NFD stays in read_tags)
            assert t.name == unicodedata.normalize("NFC", exp["title"]), rel
            assert t.artist == exp["artist"], rel
            assert t.album_artist == exp["album_artist"], rel
            assert t.album == exp["album"], rel
            assert t.genre == exp["genre"], rel
            assert t.year == exp["year"], rel
            assert t.track_number == exp["track_number"], rel
            assert t.track_count == exp["track_total"], rel
            assert t.disc_number == exp["disc_number"], rel
            assert t.disc_count == exp["disc_total"], rel
            assert t.bpm == exp["bpm"], rel
            assert t.comments == exp["comment"], rel
            assert t.compilation == bool(exp["compilation"]), rel
        else:
            assert t.name == stem  # falls back to file name
            assert t.artist is None and t.album is None and t.year is None
        assert t.kind == KINDS[_fmt_family(exp["format"])], rel
        if exp.get("bitrate_kbps"):
            assert abs(t.bit_rate - exp["bitrate_kbps"]) <= 2, rel
        assert t.sample_rate == 44100
        assert 1900 <= t.total_time <= 2200, (rel, t.total_time)
        assert t.size == (root / rel).stat().st_size
        assert t.date_modified.tzinfo is not None


def _fmt_family(fmt: str) -> str:
    return "mp3" if fmt.startswith("mp3") else fmt


def test_include_unsupported(music_dir, music_expected):
    lib = scan(music_dir, include_unsupported=True)
    assert len(lib.tracks) == len(music_expected)
    assert any(t.location.endswith(".flac") for t in lib.tracks)


def test_playlists_and_ids(lib):
    master, music = lib.playlists
    assert master.master and master.name == "Library"
    assert music.distinguished_kind == 4 and music.name == "Music"
    ids = [t.track_id for t in lib.tracks]
    assert len(set(ids)) == len(ids)
    assert master.track_ids == ids == music.track_ids
    assert master.persistent_id != music.persistent_id
    assert master.playlist_id != music.playlist_id


def test_scan_xml_roundtrip(lib):
    data = library_to_xml(lib)
    plistlib.loads(data)
    back = library_from_bytes(data)
    assert back.tracks == lib.tracks
    assert back.playlists == lib.playlists
    assert back.music_folder == lib.music_folder


def test_scan_empty_dir(tmp_path):
    lib = scan(tmp_path)
    assert lib.tracks == [] and len(lib.playlists) == 2
    plistlib.loads(library_to_xml(lib))
