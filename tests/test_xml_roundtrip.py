import dataclasses
import plistlib
import re
from datetime import datetime, timezone

from pytuneslib.model import Library, Playlist, Track
from pytuneslib.xml_reader import file_url_to_path, library_from_bytes, read_xml
from pytuneslib.xml_writer import escape, library_to_xml, path_to_file_url


def _norm(lib: Library):
    return dataclasses.asdict(lib)


def test_sample_roundtrip_equal(sample_xml):
    lib1 = read_xml(sample_xml)
    assert len(lib1.tracks) > 2000
    data = library_to_xml(lib1)
    lib2 = library_from_bytes(data)
    assert _norm(lib1) == _norm(lib2)


def test_writer_output_parses_with_plistlib(sample_xml):
    d = plistlib.loads(library_to_xml(read_xml(sample_xml)))
    assert list(d)[:3] == ["Major Version", "Minor Version", "Application Version"]
    assert d["Tracks"] and d["Playlists"]
    assert d["Playlists"][0]["Master"] is True


MODELED = {
    "Track ID", "Size", "Total Time", "Disc Number", "Disc Count", "Track Number",
    "Track Count", "Year", "BPM", "Date Modified", "Date Added", "Bit Rate", "Sample Rate",
    "Play Count", "Rating", "Compilation", "Persistent ID", "Track Type", "Name", "Artist",
    "Album Artist", "Composer", "Album", "Genre", "Kind", "Comments", "Location",
}


def _track_blocks(raw: bytes) -> dict[str, list[str]]:
    """track id -> list of entry strings (CRLF-split), limited to modeled keys."""
    text = raw.decode("utf-8")
    body = text[text.index("\t<key>Tracks</key>"): text.index("\t<key>Playlists</key>")]
    out = {}
    for m in re.finditer(r"\t\t<key>(\d+)</key>\r\n\t\t<dict>\r\n(.*?)\r\n\t\t</dict>\r\n", body, re.S):
        entries = re.split(r"\r\n(?=\t\t\t<key>)", m.group(2))
        keep = []
        keys = [re.match(r"\t\t\t<key>([^<]*)</key>", e).group(1) for e in entries]
        for key, e in zip(keys, entries):
            if key == "Rating" and "Rating Computed" in keys:
                continue  # computed ratings are not user ratings; reader drops them
            if key in MODELED:
                keep.append(e.replace("\r\n", "\n"))  # XML parsers normalise CRLF inside values
        out[m.group(1)] = keep
    return out


def test_track_dicts_byte_identical_to_sample(sample_xml):
    """Key order, escaping, dates, URL-encoding must match iTunes exactly (modeled keys)."""
    raw = sample_xml.read_bytes()
    ours = library_to_xml(read_xml(sample_xml))
    a, b = _track_blocks(raw), _track_blocks(ours)
    assert a.keys() == b.keys()
    for tid in a:
        assert a[tid] == b[tid], tid


def test_framing_matches_sample(sample_xml):
    raw = sample_xml.read_bytes()
    ours = library_to_xml(read_xml(sample_xml))
    cut = raw.index(b"\t<key>Tracks</key>")
    strip = lambda b: re.sub(rb"<date>[^<]*</date>", b"<date/>", b)
    assert strip(ours[:cut]) == strip(raw[:cut])
    assert not ours.startswith(b"\xef\xbb\xbf")
    tail = b"</dict>\r\n</plist>\r\n"
    assert raw.endswith(tail) and ours.endswith(tail)


def test_master_and_music_playlist_layout():
    lib = Library(
        tracks=[Track(1, r"C:\m\a.mp3")],
        playlists=[
            Playlist(10, "Library", [1], master=True),
            Playlist(11, "Music", [1], distinguished_kind=4),
            Playlist(12, "Empty"),
        ],
        music_folder=r"C:\m",
    )
    text = library_to_xml(lib).decode()
    assert "\t\t\t<key>Master</key><true/>\r\n\t\t\t<key>Playlist ID</key><integer>10</integer>" in text
    assert "<key>Visible</key><false/>\r\n\t\t\t<key>Name</key><string>Library</string>" in text
    assert "<key>Distinguished Kind</key><integer>4</integer>\r\n\t\t\t<key>Music</key><true/>\r\n\t\t\t<key>All Items</key>" in text
    assert "<key>Smart Info</key>" in text and "<key>Smart Criteria</key>" in text
    # empty playlist has no Playlist Items
    empty = text[text.index("<integer>12</integer>"):]
    assert "Playlist Items" not in empty
    assert text.endswith("\t<key>Music Folder</key><string>file://localhost/C:/m/</string>\r\n</dict>\r\n</plist>\r\n")
    d = plistlib.loads(text.encode())
    assert d["Playlists"][1]["Distinguished Kind"] == 4


def test_escape_and_url():
    assert escape('A & B <c> "q"') == 'A &#38; B &#60;c&#62; "q"'
    path = "C:\\Users\\A\\Ti\u00ebsto & Co\\x [1].mp3"
    url = path_to_file_url(path)
    assert url == "file://localhost/C:/Users/A/Ti%C3%ABsto%20&%20Co/x%20%5B1%5D.mp3"
    assert file_url_to_path(url) == path


def test_dates_are_utc_z():
    t = Track(1, r"C:\a.mp3", date_added=datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
              date_modified=datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    text = library_to_xml(Library(tracks=[t])).decode()
    assert "<key>Date Added</key><date>2020-01-02T03:04:05Z</date>" in text


def test_control_chars_stripped_and_roundtrip():
    t = Track(1, r"C:\a.mp3", name="a\x01b\nc", comments="line1\r\nline2")
    lib = library_from_bytes(library_to_xml(Library(tracks=[t])))
    assert lib.tracks[0].name == "ab\nc"
    assert lib.tracks[0].comments == "line1\nline2"
