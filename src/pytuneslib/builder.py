"""High-level API: music folder -> iTunes Library.itl + iTunes Music Library.xml."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from . import paths
from .limits import clamp_library
from .model import Library, Playlist, Track
from .scanner import scan
from .xml_writer import write_xml

ITL_NAME = "iTunes Library.itl"
XML_NAME = "iTunes Music Library.xml"


def write_library(
    lib: Library,
    out_dir: str | Path,
    *,
    itl: bool = True,
    music_folder: str | Path | None = None,
    location_map: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Write the XML (and, if itl, the .itl) for lib into out_dir. Returns written paths.

    The library's Music Folder becomes music_folder, or <out_dir>/iTunes Media by default.
    iTunes resets a Music Folder that isn't its own and remaps every track under the old one,
    so the scan root must not be used here. Text fields are clamped to iTunes' 255-character
    limit first (iTunes would truncate them on load), so both files say the same thing.
    """
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    clamp_library(lib)
    _ensure_master(lib)
    lib.music_folder = _music_folder(music_folder, out, location_map)
    written = {"xml": write_xml(lib, out / XML_NAME)}
    if itl:
        from .itl.writer import write_itl  # imported lazily: optional until the ITL writer lands

        written["itl"] = write_itl(lib, out / ITL_NAME, music_folder=lib.music_folder)
    return written


def build_library(
    music_dir: str | Path,
    out_dir: str | Path,
    *,
    itl: bool = True,
    include_unsupported: bool = False,
    kind_locale: str = "en",
    music_folder: str | Path | None = None,
    location_map: Mapping[str, str] | None = None,
) -> tuple[Library, dict[str, Path]]:
    """Scan music_dir and write both library files into out_dir."""
    lib = scan(music_dir, include_unsupported=include_unsupported, kind_locale=kind_locale,
               location_map=location_map)
    return lib, write_library(lib, out_dir, itl=itl, music_folder=music_folder, location_map=location_map)


def _music_folder(music_folder: str | Path | None, out: Path, location_map: Mapping[str, str] | None) -> str:
    """The iTunes Media folder as iTunes will see it (Windows/UNC strings are never run through os.path)."""
    if music_folder is None:
        folder = os.path.join(os.path.abspath(out), "iTunes Media")
    else:
        folder = str(music_folder)
        if not paths.is_windows(folder):
            folder = os.path.abspath(folder)
    return paths.map_location(folder, location_map)


def _free_id(lib: Library) -> int:
    used = [t.track_id + 1 for t in lib.tracks] + [p.playlist_id for p in lib.playlists]
    return max(used, default=4999) + 1


def _ensure_master(lib: Library) -> None:
    """iTunes needs exactly one master "Library" playlist holding every track."""
    if not any(p.master for p in lib.playlists):
        lib.playlists.insert(0, Playlist(playlist_id=_free_id(lib), name="Library", master=True, visible=False,
                                         track_ids=[t.track_id for t in lib.tracks]))


def add_playlist(lib: Library, name: str, tracks: Iterable[Track | int] = ()) -> Playlist:
    """Append a regular (non-master) playlist to lib and return it.

    tracks may be Track objects or track ids; they must belong to lib. The playlist gets a free id
    in iTunes' shared id space (above every track id + 1 and every playlist id).
    """
    known = {t.track_id for t in lib.tracks}
    ids = [t.track_id if isinstance(t, Track) else int(t) for t in tracks]
    missing = [i for i in ids if i not in known]
    if missing:
        raise ValueError(f"track ids not in library: {missing[:5]}")
    playlist = Playlist(playlist_id=_free_id(lib), name=name, track_ids=ids)
    lib.playlists.append(playlist)
    return playlist

