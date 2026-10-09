import mutagen
import pytest

from audio_fixture import TAG_KEYS, read_tags
from music_fixtures import music_dir, music_expected  # noqa: F401


def test_all_expected_files_exist(music_dir, music_expected):
    missing = [rel for rel in music_expected if not (music_dir / rel).is_file()]
    assert missing == []


def test_layout_is_nested_and_has_special_paths(music_dir, music_expected):
    assert any("é" in rel for rel in music_expected)  # non-ASCII path
    assert any(" " in rel and "&" in rel and "#" in rel for rel in music_expected)
    assert all(rel.count("/") >= 2 for rel in music_expected)  # Artist/Album/file
    assert len(music_expected) == 19  # 8 original + 11 artist/album-artist/unicode cases


@pytest.mark.parametrize("rel", ["Beyoncé/Lemonade/Ñandú.mp3"])
def test_non_ascii_path_is_readable(music_dir, rel):
    assert mutagen.File(music_dir / rel) is not None


def test_mutagen_reads_tags(music_dir, music_expected):
    for rel, exp in music_expected.items():
        if not exp["has_tags"]:
            continue
        got = read_tags(music_dir / rel)
        for key in TAG_KEYS:
            assert got[key] == exp[key], f"{rel}: {key}"


def test_untagged_track_has_no_tags(music_dir, music_expected):
    rel = next(r for r, e in music_expected.items() if not e["has_tags"])
    assert read_tags(music_dir / rel) == dict.fromkeys(TAG_KEYS)


def test_flac_is_marked_unsupported(music_expected):
    flacs = [e for e in music_expected.values() if e["format"] == "flac"]
    assert flacs and all(not e["itunes_supported"] for e in flacs)


def test_mp3_bitrates_match(music_dir, music_expected):
    for rel, exp in music_expected.items():
        if exp["format"] != "mp3":
            continue
        kbps = round(mutagen.File(music_dir / rel).info.bitrate / 1000)
        assert kbps == exp["bitrate_kbps"], rel


def test_compilation_flag_on_expected_tracks(music_expected):
    flagged = {r for r, e in music_expected.items() if e["compilation"] is True}
    hits = {r for r, e in music_expected.items() if e["album"] == "Hits 2020"}
    aac = "Artist A/Album B/03 Song AAC.m4a"
    assert flagged == hits | {aac}
    assert len(hits) == 3


def test_missing_album_artist_is_none_in_file(music_dir):
    rel = "Solo Artist/Single/01 No Album Artist.mp3"
    got = read_tags(music_dir / rel)
    assert got["artist"] == "Solo Artist"
    assert got["album_artist"] is None


def test_missing_artist_is_none_in_file(music_dir):
    rel = "Label/Only Album Artist/01 No Artist.mp3"
    got = read_tags(music_dir / rel)
    assert got["artist"] is None
    assert got["album_artist"] == "Label Owner"


def test_dj_host_album_artist_shared_across_albums(music_dir, music_expected):
    dj = [r for r, e in music_expected.items() if e["album_artist"] == "DJ Host"]
    assert len(dj) == 4
    assert {music_expected[r]["album"] for r in dj} == {"Mix One", "Mix Two"}
    for rel in dj:
        assert read_tags(music_dir / rel)["album_artist"] == "DJ Host"


def test_nfc_and_nfd_titles_differ_in_code_points_but_match_after_normalize(music_dir, music_expected):
    import unicodedata

    nfc_rel = "Tiësto/Remixes/01 NFC.mp3"
    nfd_rel = "Tiësto/Remixes/02 NFD.mp3"
    nfc = read_tags(music_dir / nfc_rel)["title"]
    nfd = read_tags(music_dir / nfd_rel)["title"]
    assert nfc == music_expected[nfc_rel]["title"]
    assert nfd == music_expected[nfd_rel]["title"]
    assert nfc != nfd
    assert unicodedata.normalize("NFC", nfd) == nfc
