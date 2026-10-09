"""Shared data model. Contract between scanner, XML writer and ITL writer."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone


def new_persistent_id() -> str:
    """Random 64-bit persistent ID as 16 uppercase hex chars (iTunes style)."""
    return secrets.token_hex(8).upper()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass
class Track:
    track_id: int
    location: str  # absolute path as iTunes sees it (Windows drive path or UNC \\server\share\...)
    persistent_id: str = field(default_factory=new_persistent_id)
    name: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    composer: str | None = None
    genre: str | None = None
    kind: str | None = None  # e.g. "MPEG audio file"
    size: int = 0  # bytes
    total_time: int = 0  # milliseconds
    disc_number: int | None = None
    disc_count: int | None = None
    track_number: int | None = None
    track_count: int | None = None
    year: int | None = None
    bpm: int | None = None
    bit_rate: int | None = None  # kbps
    sample_rate: int | None = None  # Hz
    date_modified: datetime = field(default_factory=utcnow)
    date_added: datetime = field(default_factory=utcnow)
    play_count: int = 0
    rating: int | None = None  # 0-100
    comments: str | None = None
    compilation: bool = False
    grouping: str | None = None
    loved: bool = False
    disliked: bool = False
    play_date: datetime | None = None  # last played
    skip_count: int = 0
    skip_date: datetime | None = None  # last skipped
    release_date: datetime | None = None
    album_rating: int | None = None  # 0-100
    work: str | None = None
    sort_name: str | None = None
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_album_artist: str | None = None
    sort_composer: str | None = None


@dataclass
class Playlist:
    playlist_id: int
    name: str
    track_ids: list[int] = field(default_factory=list)
    persistent_id: str = field(default_factory=new_persistent_id)
    master: bool = False  # the "Library" playlist
    distinguished_kind: int | None = None  # 4 = Music, 10 = Podcasts, 26 = Genius, ...
    visible: bool = True  # False for hidden built-ins
    folder: bool = False  # playlist folder: track_ids are the union of its children
    parent_persistent_id: str | None = None  # containing folder, if any
    # Smart playlists: opaque iTunes blobs ("Smart Info" / "Smart Criteria"), kept byte-for-byte
    smart_info: bytes | None = None
    smart_criteria: bytes | None = None

    @property
    def smart(self) -> bool:
        return self.smart_criteria is not None


@dataclass
class Library:
    tracks: list[Track] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)
    persistent_id: str = field(default_factory=new_persistent_id)
    application_version: str = "12.13.11.1"
    music_folder: str | None = None  # absolute path of iTunes Media folder
    date: datetime = field(default_factory=utcnow)
