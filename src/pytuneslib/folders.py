"""Folder rules shared by the XML and ITL writers.

In iTunes a playlist folder is a smart playlist: besides the Folder flag it carries a Smart Info /
Smart Criteria pair with one rule "Playlist is <child persistent id>" per direct child (see
itl/folders.py for the blob layout). A library built from scratch has folders without those blobs,
so both writers derive them from the playlists' ``parent_persistent_id`` links.
"""

from __future__ import annotations

from .itl.folders import FOLDER_SMART_INFO, folder_criteria
from .model import Library


def direct_children(lib: Library) -> dict[str, list[str]]:
    """Folder persistent id -> persistent ids of its direct child playlists, in library order."""
    out: dict[str, list[str]] = {}
    for p in lib.playlists:
        if p.parent_persistent_id:
            out.setdefault(p.parent_persistent_id.upper(), []).append(p.persistent_id.upper())
    return out


def folder_rules(lib: Library) -> dict[str, tuple[bytes, bytes]]:
    """Folder persistent id (upper case) -> (smart_info, smart_criteria) to write.

    Existing blobs that already list exactly the direct children are kept byte for byte (iTunes'
    own rule order); missing or stale ones are generated. Does not modify ``lib``.
    """
    kids = direct_children(lib)
    return {
        p.persistent_id.upper(): (
            p.smart_info or FOLDER_SMART_INFO,
            folder_criteria(kids.get(p.persistent_id.upper(), []), p.smart_criteria),
        )
        for p in lib.playlists
        if p.folder
    }


def sync_folder_rules(lib: Library) -> Library:
    """Store the generated folder blobs on the playlists (in place). Returns lib."""
    rules = folder_rules(lib)
    for p in lib.playlists:
        if p.folder:
            p.smart_info, p.smart_criteria = rules[p.persistent_id.upper()]
    return lib
