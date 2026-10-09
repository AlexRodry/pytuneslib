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
    location: str  # absolute filesystem path
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


@dataclass
class Playlist:
    playlist_id: int
    name: str
    track_ids: list[int] = field(default_factory=list)
    persistent_id: str = field(default_factory=new_persistent_id)
    master: bool = False  # the "Library" playlist
    distinguished_kind: int | None = None  # 4 = Music, etc.


@dataclass
class Library:
    tracks: list[Track] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)
    persistent_id: str = field(default_factory=new_persistent_id)
    application_version: str = "12.13.11.1"
    music_folder: str | None = None  # absolute path of iTunes Media folder
    date: datetime = field(default_factory=utcnow)
