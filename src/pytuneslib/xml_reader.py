"""iTunes Music Library.xml -> Library (via plistlib)."""

from __future__ import annotations

import plistlib
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

from .model import Library, Playlist, Track

_PREFIXES = ("file://localhost/", "file:///")


def file_url_to_path(url: str) -> str:
    """'file://localhost/C:/a%20b.mp3' -> 'C:\\a b.mp3'; POSIX urls -> '/a b.mp3'."""
    rest = url
    for pre in _PREFIXES:
        if url.startswith(pre):
            rest = url[len(pre):]
            break
    rest = unquote(rest)
    if re.match(r"^[A-Za-z]:/", rest):
        return str(PureWindowsPath(rest))
    return str(PurePosixPath("/" + rest.lstrip("/")))  # drops the trailing '/' of folder urls


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _track(d: dict) -> Track:
    t = Track(
        track_id=d["Track ID"],
        location=file_url_to_path(d["Location"]) if "Location" in d else "",
        persistent_id=d.get("Persistent ID") or Track.__dataclass_fields__["persistent_id"].default_factory(),
        name=d.get("Name"),
        artist=d.get("Artist"),
        album_artist=d.get("Album Artist"),
        album=d.get("Album"),
        composer=d.get("Composer"),
        genre=d.get("Genre"),
        kind=d.get("Kind"),
        size=d.get("Size", 0),
        total_time=d.get("Total Time", 0),
        disc_number=d.get("Disc Number"),
        disc_count=d.get("Disc Count"),
        track_number=d.get("Track Number"),
        track_count=d.get("Track Count"),
        year=d.get("Year"),
        bpm=d.get("BPM"),
        bit_rate=d.get("Bit Rate"),
        sample_rate=d.get("Sample Rate"),
        play_count=d.get("Play Count", 0),
        # "Rating Computed" = derived from the album rating, not set by the user (ITL stores none)
        rating=None if d.get("Rating Computed") else d.get("Rating"),
        comments=d.get("Comments"),
        compilation=bool(d.get("Compilation", False)),
    )
    if "Date Modified" in d:
        t.date_modified = _utc(d["Date Modified"])
    if "Date Added" in d:
        t.date_added = _utc(d["Date Added"])
    return t


def _playlist(d: dict) -> Playlist:
    return Playlist(
        playlist_id=d["Playlist ID"],
        name=d.get("Name", ""),
        track_ids=[i["Track ID"] for i in d.get("Playlist Items", [])],
        persistent_id=d["Playlist Persistent ID"],
        master=bool(d.get("Master", False)),
        distinguished_kind=d.get("Distinguished Kind"),
    )


def library_from_dict(d: dict) -> Library:
    lib = Library(
        tracks=[_track(t) for t in d.get("Tracks", {}).values()],
        playlists=[_playlist(p) for p in d.get("Playlists", [])],
        persistent_id=d.get("Library Persistent ID") or Library().persistent_id,
        application_version=d.get("Application Version", "12.13.11.1"),
        music_folder=file_url_to_path(d["Music Folder"]) if "Music Folder" in d else None,
    )
    if "Date" in d:
        lib.date = _utc(d["Date"])
    return lib


def library_from_bytes(data: bytes) -> Library:
    return library_from_dict(plistlib.loads(data))


def read_xml(path: str | Path) -> Library:
    """Read an "iTunes Music Library.xml" export into a Library."""
    return library_from_bytes(Path(path).read_bytes())
