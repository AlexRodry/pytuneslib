"""Network / cross-platform locations through scanner, builder, CLI and the XML round trip."""
import os
import plistlib

from pytuneslib.builder import build_library
from pytuneslib.cli import main
from pytuneslib.model import Library, Playlist, Track
from pytuneslib.scanner import scan
from pytuneslib.xml_reader import library_from_bytes, read_xml
from pytuneslib.xml_writer import library_to_xml

UNC_ROOT = "\\\\NAS\\music"


def test_unc_track_xml_roundtrip():
    loc = "\\\\NAS\\music\\Ti\u00ebsto\\Alb\\01 A&B.mp3"
    lib = Library(
        tracks=[Track(1, loc, name="x"), Track(3, "C:\\Music\\b.mp3"), Track(5, "/Users/x/c.mp3")],
        playlists=[Playlist(10, "Library", [1, 3, 5], master=True, visible=False)],
        music_folder="\\\\NAS\\music",
    )
    data = library_to_xml(lib)
    text = data.decode()
    assert "<key>Location</key><string>file://localhost//NAS/music/Ti%C3%ABsto/Alb/01%20A&#38;B.mp3</string>" in text
    assert "file://localhost/C:/Music/b.mp3" in text and "file://localhost/Users/x/c.mp3" in text
    assert "<key>Music Folder</key><string>file://localhost//NAS/music/</string>" in text
    plistlib.loads(data)
    back = library_from_bytes(data)
    assert [t.location for t in back.tracks] == [loc, "C:\\Music\\b.mp3", "/Users/x/c.mp3"]
    assert back.music_folder == "\\\\NAS\\music"
    # UNC tracks under the UNC media folder are "managed" (folder counts 5/1)
    assert text.count("<key>File Folder Count</key><integer>5</integer>") == 1


def test_scan_location_map(music_dir):
    lib = scan(music_dir, location_map={str(music_dir): UNC_ROOT})
    assert lib.tracks
    for t in lib.tracks:
        assert t.location.startswith(UNC_ROOT + "\\")
        assert "/" not in t.location  # remainder takes the Windows separator style
    assert lib.music_folder == UNC_ROOT
    # same relative structure as the unmapped scan
    plain = scan(music_dir)
    rel = lambda loc, root: loc[len(root) + 1:].replace("\\", "/").replace("/", "\\")
    assert [rel(t.location, UNC_ROOT) for t in lib.tracks] == [
        rel(t.location, os.path.abspath(music_dir)) for t in plain.tracks
    ]


def test_cli_path_map_writes_unc_urls(music_dir, tmp_path):
    out = tmp_path / "out"
    rc = main(["build", str(music_dir), str(out), "--no-itl", "--path-map", f"{music_dir}={UNC_ROOT}"])
    assert rc == 0
    xml = (out / "iTunes Music Library.xml").read_text(encoding="utf-8")
    assert xml.count("file://localhost//NAS/music/") >= 18
    lib = read_xml(out / "iTunes Music Library.xml")
    assert all(t.location.startswith(UNC_ROOT + "\\") for t in lib.tracks)


def test_build_music_folder_can_be_unc(music_dir, tmp_path):
    lib, written = build_library(music_dir, tmp_path / "o", itl=False, music_folder="\\\\NAS\\music\\iTunes Media")
    assert lib.music_folder == "\\\\NAS\\music\\iTunes Media"
    assert read_xml(written["xml"]).music_folder == "\\\\NAS\\music\\iTunes Media"


def test_cli_bad_path_map(music_dir, tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        main(["build", str(music_dir), str(tmp_path / "o"), "--no-itl", "--path-map", "oops"])
