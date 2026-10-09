"""Library -> iTunes Music Library.xml, byte-compatible with iTunes 12.13 output.

Format quirks (verified against samples/iTunes Music Library.xml) are documented
in docs/KNOWLEDGE.md under "Findings: XML format".
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote

from .model import Library, Playlist, Track

EOL = "\r\n"
DOCTYPE = (
    '<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
)
# chars iTunes leaves unescaped in file URLs (everything else, incl. UTF-8 bytes, is %XX)
URL_SAFE = "/:!$&'()*+,;=@~"
FILE_URL_PREFIX = "file://localhost/"

# "Smart Info" / "Smart Criteria" blobs iTunes attaches to the Music playlist
# (Distinguished Kind 4); copied verbatim from the sample.
MUSIC_SMART_INFO = base64.b64decode(
    "AQEAAwAAAAIAAAAZAAAAAAAAAAcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
)
MUSIC_SMART_CRITERIA = base64.b64decode(
    "U0xzdAABAAEAAAACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAABEAAAAAAAQIbEAAAAAAAAAAAAAAAAAAAABAAAAAAAQIbEAAAAA"
    "AAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8AgAEAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARAAAAAAAIIAEAAAAAAAAAAAAAAAAAAAAAQAA"
    "AAAAIIAEAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAA"
)

_CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def escape(text: str) -> str:
    """XML escaping as iTunes does it: numeric entities, quotes left raw."""
    text = _CTRL_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("&", "&#38;").replace("<", "&#60;").replace(">", "&#62;")


def fmt_date(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def path_to_file_url(path: str | Path) -> str:
    """'C:\\Users\\A\\x y.mp3' -> 'file://localhost/C:/Users/A/x%20y.mp3'."""
    s = str(path)
    if re.match(r"^[A-Za-z]:[\\/]", s):
        posix = PureWindowsPath(s).as_posix()
    else:
        posix = PurePosixPath(s.replace("\\", "/")).as_posix().lstrip("/")
    return FILE_URL_PREFIX + quote(posix, safe=URL_SAFE)


class _Out:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0

    def add(self, line: str) -> None:
        self.lines.append("\t" * self.depth + line)

    def open(self, tag: str) -> None:
        self.add(f"<{tag}>")
        self.depth += 1

    def close(self, tag: str) -> None:
        self.depth -= 1
        self.add(f"</{tag}>")

    def kv(self, key: str, value: object) -> None:
        k = f"<key>{escape(key)}</key>"
        if value is True:
            self.add(f"{k}<true/>")
        elif value is False:
            self.add(f"{k}<false/>")
        elif isinstance(value, int):
            self.add(f"{k}<integer>{value}</integer>")
        elif isinstance(value, datetime):
            self.add(f"{k}<date>{fmt_date(value)}</date>")
        elif isinstance(value, str):
            self.add(f"{k}<string>{escape(value)}</string>")
        else:
            raise TypeError(f"unsupported value for {key!r}: {type(value)}")

    def data(self, key: str, blob: bytes) -> None:
        self.add(f"<key>{key}</key>")
        self.add("<data>")
        b64 = base64.b64encode(blob).decode("ascii")
        self.depth += 1
        for i in range(0, len(b64), 72):
            self.add(b64[i : i + 72])
        self.depth -= 1
        self.add("</data>")


def _is_under(location: str, folder: str | None) -> bool:
    if not folder:
        return False
    a = str(location).replace("\\", "/").lower()
    b = str(folder).replace("\\", "/").lower().rstrip("/") + "/"
    return a.startswith(b)


def _write_track(o: _Out, t: Track, music_folder: str | None) -> None:
    """Key order = iTunes order (see KNOWLEDGE.md). Absent/None values are omitted."""
    o.kv("Track ID", t.track_id)
    o.kv("Size", t.size)
    o.kv("Total Time", t.total_time)
    for key, val in (
        ("Disc Number", t.disc_number),
        ("Disc Count", t.disc_count),
        ("Track Number", t.track_number),
        ("Track Count", t.track_count),
        ("Year", t.year),
        ("BPM", t.bpm),
    ):
        if val is not None:
            o.kv(key, val)
    o.kv("Date Modified", t.date_modified)
    o.kv("Date Added", t.date_added)
    if t.bit_rate is not None:
        o.kv("Bit Rate", t.bit_rate)
    if t.sample_rate is not None:
        o.kv("Sample Rate", t.sample_rate)
    if t.play_count:
        o.kv("Play Count", t.play_count)
    if t.rating is not None:
        o.kv("Rating", t.rating)
    if t.compilation:
        o.kv("Compilation", True)
    o.kv("Persistent ID", t.persistent_id)
    o.kv("Track Type", "File")
    managed = _is_under(t.location, music_folder)
    o.kv("File Folder Count", 5 if managed else -1)
    o.kv("Library Folder Count", 1 if managed else -1)
    for key, val in (
        ("Name", t.name),
        ("Artist", t.artist),
        ("Album Artist", t.album_artist),
        ("Composer", t.composer),
        ("Album", t.album),
        ("Genre", t.genre),
        ("Kind", t.kind),
        ("Comments", t.comments),
    ):
        if val is not None:
            o.kv(key, val)
    o.kv("Location", path_to_file_url(t.location))


def _write_playlist(o: _Out, p: Playlist) -> None:
    o.open("dict")
    if p.master:
        o.kv("Master", True)
    o.kv("Playlist ID", p.playlist_id)
    o.kv("Playlist Persistent ID", p.persistent_id)
    if p.distinguished_kind is not None:
        o.kv("Distinguished Kind", p.distinguished_kind)
        if p.distinguished_kind == 4:
            o.kv("Music", True)
    o.kv("All Items", True)
    if p.master:
        o.kv("Visible", False)
    o.kv("Name", p.name)
    if p.distinguished_kind == 4:
        o.data("Smart Info", MUSIC_SMART_INFO)
        o.data("Smart Criteria", MUSIC_SMART_CRITERIA)
    if p.track_ids:
        o.add("<key>Playlist Items</key>")
        o.open("array")
        for tid in p.track_ids:
            o.open("dict")
            o.kv("Track ID", tid)
            o.close("dict")
        o.close("array")
    o.close("dict")


def library_to_xml(lib: Library) -> bytes:
    o = _Out()
    o.lines += ['<?xml version="1.0" encoding="UTF-8"?>', DOCTYPE]
    o.add('<plist version="1.0">')
    o.open("dict")
    o.kv("Major Version", 1)
    o.kv("Minor Version", 1)
    o.kv("Application Version", lib.application_version)
    o.kv("Date", lib.date)
    o.kv("Features", 5)
    o.kv("Show Content Ratings", True)
    o.kv("Library Persistent ID", lib.persistent_id)
    o.add("<key>Tracks</key>")
    o.open("dict")
    for t in lib.tracks:
        o.add(f"<key>{t.track_id}</key>")
        o.open("dict")
        _write_track(o, t, lib.music_folder)
        o.close("dict")
    o.close("dict")
    o.add("<key>Playlists</key>")
    o.open("array")
    for p in lib.playlists:
        _write_playlist(o, p)
    o.close("array")
    if lib.music_folder:
        folder = path_to_file_url(lib.music_folder)
        if not folder.endswith("/"):
            folder += "/"
        o.add(f"<key>Music Folder</key><string>{escape(folder)}</string>")
    o.close("dict")
    o.add("</plist>")
    return (EOL.join(o.lines) + EOL).encode("utf-8")


def write_xml(lib: Library, path: str | Path) -> Path:
    """Write lib as an iTunes-style "iTunes Music Library.xml". Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(library_to_xml(lib))
    return path
