"""iTunes Music Library.xml -> Library (via plistlib)."""

from __future__ import annotations

import plistlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

from . import paths
from .model import Library, Playlist, Track

_PREFIXES = ("file://localhost/", "file:///")


def file_url_to_path(url: str) -> str:
    """File URL -> location (see paths.from_file_url): Windows drive/UNC paths keep backslashes."""
    return paths.from_file_url(url)


MAC_EPOCH = datetime(1904, 1, 1)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _from_mac_local(secs: int | None) -> datetime | None:
    """Raw 'Play Date' (seconds since 1904-01-01 in *local* time) -> UTC datetime."""
    if secs is None:
        return None
    naive = MAC_EPOCH + timedelta(seconds=secs)
    try:
        return naive.astimezone().astimezone(timezone.utc)
    except (OSError, OverflowError, ValueError):
        return naive.replace(tzinfo=timezone.utc)


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
        grouping=d.get("Grouping"),
        loved=bool(d.get("Loved", False)),
        disliked=bool(d.get("Disliked", False)),
        skip_count=d.get("Skip Count", 0),
        album_rating=None if d.get("Album Rating Computed") else d.get("Album Rating"),
        work=d.get("Work"),
        sort_name=d.get("Sort Name"),
        sort_artist=d.get("Sort Artist"),
        sort_album=d.get("Sort Album"),
        sort_album_artist=d.get("Sort Album Artist"),
        sort_composer=d.get("Sort Composer"),
    )
    t.play_date = _utc(d.get("Play Date UTC")) or _from_mac_local(d.get("Play Date"))
    t.skip_date = _utc(d.get("Skip Date"))
    t.release_date = _utc(d.get("Release Date"))
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
        visible=bool(d.get("Visible", True)),
        folder=bool(d.get("Folder", False)),
        parent_persistent_id=d.get("Parent Persistent ID"),
        smart_info=bytes(d["Smart Info"]) if "Smart Info" in d else None,
        smart_criteria=bytes(d["Smart Criteria"]) if "Smart Criteria" in d else None,
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
