"""Edit an existing iTunes .itl in place: only touched playlists are re-encoded.

    doc = ItlDocument.open("iTunes Library.itl")
    folder = doc.add_playlist("Sets", folder=True)
    mix = doc.add_playlist("Friday", [t.track_id for t in doc.library.tracks[:20]],
                           parent=folder.persistent_id)
    doc.update_playlist(mix.persistent_id, name="Friday mix")
    doc.remove_playlist(some_pid)
    doc.save("out/iTunes Library.itl")

Every chunk that is not edited is re-emitted from the original bytes; only list lengths/counts and
the header playlist count are recomputed. Saving without edits writes the original file unchanged.
"""

from __future__ import annotations

import os
import struct
from datetime import datetime, timezone
from pathlib import Path

from ..limits import clamp_text
from ..model import Library, Playlist, new_persistent_id
from . import chunks as C
from .folders import FOLDER_SMART_INFO, folder_criteria
from .reader import (
    HDFM_PLAYLIST_COUNT, I_ITEM_ID, I_TRACK_ID, P, S_PLAYLIST_NAME, S_SMART_CRITERIA, S_SMART_INFO,
    SMART_DATA, T, ItlFile, parse_itl, pid_from_bytes, playlist_from_chunk, to_library,
)
from .writer import HPTM_ITEM_PID, _Builder, _is_real_itunes_dir, _rand_pid, _smart_hohm

PathLike = str | os.PathLike


class ItlDocument:
    """An .itl opened for editing. `library` is a read-only Library view of the current state."""

    def __init__(self, raw: bytes):
        self._raw = raw
        self.itl: ItlFile = parse_itl(raw)
        self._edited = False
        self._library: Library | None = None
        self._next_id = self._max_id() + 1

    @classmethod
    def open(cls, path: PathLike) -> ItlDocument:
        return cls(Path(path).read_bytes())

    # -- views ------------------------------------------------------------------------------
    @property
    def library(self) -> Library:
        if self._library is None:
            self._library = to_library(self.itl)
        return self._library

    @property
    def edited(self) -> bool:
        return self._edited

    def playlist(self, persistent_id: str) -> Playlist:
        return playlist_from_chunk(self._chunk(persistent_id))

    # -- edits ------------------------------------------------------------------------------
    def add_playlist(self, name: str, track_ids=(), *, parent: str | None = None, folder: bool = False,
                     smart_info: bytes | None = None, smart_criteria: bytes | None = None,
                     persistent_id: str | None = None) -> Playlist:
        """Append a regular playlist (or folder / smart playlist with raw rules). Returns it."""
        if parent is not None:
            self._require_folder(parent)
        p = Playlist(playlist_id=self._new_id(), name=name, track_ids=self._check_tracks(track_ids),
                     persistent_id=persistent_id or new_persistent_id(), folder=folder,
                     parent_persistent_id=parent, smart_info=smart_info, smart_criteria=smart_criteria)
        if any(self._pid(c) == p.persistent_id for c in self._hpims()):
            raise ValueError(f"persistent id already used: {p.persistent_id}")
        b = _Builder(Library(date=datetime.now(timezone.utc)), "iTunes Library")
        b.next_id = self._next_id
        chunk = b.playlist(p)
        self._next_id = b.next_id
        self._playlists_section().chunks.append(chunk)
        if parent is not None:
            self._refresh_folder(parent)
        self._touch()
        return playlist_from_chunk(chunk)

    def update_playlist(self, persistent_id: str, *, name: str | None = None, track_ids=None,
                        parent: str | None | type[...] = ...) -> Playlist:
        """Rename, replace the track list and/or move (parent=folder pid, or None for top level).

        Existing items for tracks that stay keep their bytes (item ids and pids)."""
        c = self._chunk(persistent_id)
        if c.head[P["master"]]:
            raise ValueError("the master Library playlist cannot be edited")
        if name is not None:
            k = next(k for k in c.kids("hohm") if k.hohm_type == S_PLAYLIST_NAME)
            new = C.make_hohm_string(S_PLAYLIST_NAME, clamp_text(name))
            new.set_u32(16, k.u32(16))
            c.children[c.children.index(k)] = new
        if track_ids is not None:
            ids = self._check_tracks(track_ids)
            old: dict[int, list[C.Chunk]] = {}
            for it in c.kids("hptm"):
                old.setdefault(it.u32(I_TRACK_ID), []).append(it)
            items = [old[i].pop(0) if old.get(i) else self._new_item(i) for i in ids]
            c.children = [k for k in c.children if k.tag != "hptm"] + items
            c.set_u32(P["item_count"], len(items))
        if parent is not ...:
            old_parent = self._parent(c)
            if parent is not None:
                self._require_folder(parent)
                if parent == persistent_id or persistent_id in self._ancestors(parent):
                    raise ValueError("a folder cannot be moved into itself")
            c.head[P["parent_pid"]:P["parent_pid"] + 8] = (
                bytes.fromhex(parent)[::-1] if parent else bytes(8))
            for folder in {old_parent, parent.upper() if parent else None} - {None}:
                self._refresh_folder(folder)
        self._touch()
        return playlist_from_chunk(c)

    def remove_playlist(self, persistent_id: str, *, recursive: bool = False) -> list[str]:
        """Remove a playlist. A non-empty folder needs recursive=True. Returns removed pids."""
        persistent_id = persistent_id.upper()
        c = self._chunk(persistent_id)
        if c.head[P["master"]]:
            raise ValueError("the master Library playlist cannot be removed")
        children = [self._pid(k) for k in self._hpims() if self._parent(k) == persistent_id]
        if children and not recursive:
            raise ValueError(f"folder {persistent_id} is not empty ({len(children)} children)")
        removed = []
        for child in children:
            removed += self.remove_playlist(child, recursive=True)
        parent = self._parent(c)
        sec = self._playlists_section()
        sec.chunks = [k for k in sec.chunks if k is not c]
        if parent is not None and parent not in removed:
            self._refresh_folder(parent)
        self._touch()
        return removed + [persistent_id]

    # -- output -----------------------------------------------------------------------------
    def to_bytes(self) -> bytes:
        if not self._edited:
            return self._raw
        n = len(self._hpims())
        struct.pack_into(">I", self.itl.header, HDFM_PLAYLIST_COUNT, n)
        inner = self.itl.section(C.SEC_HDFM)
        if inner is not None and inner.chunks:
            inner.chunks[0].set_u32(HDFM_PLAYLIST_COUNT, n)
        return self.itl.to_bytes()

    def save(self, path: PathLike) -> Path:
        path = Path(path)
        if _is_real_itunes_dir(path):
            raise PermissionError(f"refusing to overwrite a live iTunes library: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.to_bytes())
        return path

    # -- internals --------------------------------------------------------------------------
    def _touch(self) -> None:
        self._edited = True
        self._library = None

    def _playlists_section(self) -> C.Section:
        s = self.itl.section(C.SEC_PLAYLISTS)
        if s is None:
            raise ValueError("library has no playlist section")
        return s

    def _hpims(self) -> list[C.Chunk]:
        return self._playlists_section().items("hpim")

    @staticmethod
    def _pid(c: C.Chunk) -> str:
        return pid_from_bytes(c.head[P["persistent_id"]:P["persistent_id"] + 8])

    @staticmethod
    def _parent(c: C.Chunk) -> str | None:
        b = bytes(c.head[P["parent_pid"]:P["parent_pid"] + 8])
        return pid_from_bytes(b) if any(b) else None

    def _chunk(self, persistent_id: str) -> C.Chunk:
        pid = persistent_id.upper()
        for c in self._hpims():
            if self._pid(c) == pid:
                return c
        raise KeyError(f"no playlist with persistent id {persistent_id}")

    def _refresh_folder(self, folder_pid: str) -> None:
        """Rewrite a folder's "Playlist is <child>" rules to match its current children."""
        try:
            f = self._chunk(folder_pid)
        except KeyError:
            return
        children = [self._pid(k) for k in self._hpims() if self._parent(k) == self._pid(f)]
        kids = {k.hohm_type: k for k in f.kids("hohm")}
        old = bytes(kids[S_SMART_CRITERIA].head[SMART_DATA:]) if S_SMART_CRITERIA in kids else None
        new = folder_criteria(children, old)
        if new == old:
            return
        crit = _smart_hohm(S_SMART_CRITERIA, new)
        if S_SMART_CRITERIA in kids:
            f.children[f.children.index(kids[S_SMART_CRITERIA])] = crit
        else:
            at = f.children.index(next(k for k in f.children if k.tag == "hohm")) + 1  # after the name
            f.children[at:at] = [_smart_hohm(S_SMART_INFO, FOLDER_SMART_INFO), crit]
            f.set_u32(P["hohm_count"], len(f.kids("hohm")))

    def _require_folder(self, pid: str) -> None:
        if not self._chunk(pid).head[P["folder"]]:
            raise ValueError(f"{pid} is not a playlist folder")

    def _ancestors(self, pid: str) -> list[str]:
        out, cur = [], self._parent(self._chunk(pid))
        while cur and cur not in out:
            out.append(cur)
            cur = self._parent(self._chunk(cur))
        return out

    def _check_tracks(self, track_ids) -> list[int]:
        ids = [getattr(t, "track_id", t) for t in track_ids]
        known = {c.u32(T["track_id"]) for c in self._tracks()}
        missing = [i for i in ids if i not in known]
        if missing:
            raise ValueError(f"track ids not in library: {missing[:5]}")
        return [int(i) for i in ids]

    def _tracks(self) -> list[C.Chunk]:
        s = self.itl.section(C.SEC_TRACKS)
        return s.items("htim") if s else []

    def _max_id(self) -> int:
        """Highest id in iTunes' shared id space (tracks use id and id+1)."""
        ids = [0]
        for c in self._tracks():
            ids += [c.u32(T["track_id"]) + 1, c.u32(T["track_id2"])]
        for sec, tag in ((C.SEC_ALBUMS, "haim"), (C.SEC_ARTISTS, "hiim")):
            s = self.itl.section(sec)
            if s:
                ids += [c.u32(0x10) for c in s.items(tag)]
        for c in self._hpims():
            ids.append(c.u32(P["playlist_id"]))
            ids += [k.u32(I_ITEM_ID) for k in c.kids("hptm")]
        return max(ids)

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _new_item(self, track_id: int) -> C.Chunk:
        from . import _defaults as D

        it = C.Chunk("hptm", bytearray(D.HPTM))
        it.set_u32(I_ITEM_ID, self._new_id())
        it.set_u32(I_TRACK_ID, track_id)
        it.head[HPTM_ITEM_PID:HPTM_ITEM_PID + 8] = _rand_pid()
        return it
