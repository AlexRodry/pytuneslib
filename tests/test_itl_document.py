"""ItlDocument (edit mode): untouched bytes stay identical, edits touch only their playlists."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pytuneslib import ItlDocument
from pytuneslib.itl import chunks as C
from pytuneslib.itl.crypto import decrypt_file
from pytuneslib.itl.reader import parse_itl, read_itl
from pytuneslib.itl.writer import itl_bytes
from pytuneslib.model import Library, Playlist, Track

SAMPLE_ITL = Path(__file__).resolve().parent.parent / "samples" / "iTunes Library.itl"
D0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _raw() -> bytes:
    tracks = [Track(track_id=1000 + 2 * i, location=rf"C:\M\{i}.mp3", name=f"T{i}", size=1,
                    total_time=1, date_modified=D0, date_added=D0) for i in range(4)]
    pls = [Playlist(5000, "Library", [t.track_id for t in tracks], master=True, visible=False),
           Playlist(5001, "Folder", [1000, 1002], folder=True, persistent_id="00000000000000F0"),
           Playlist(5002, "Child", [1000, 1002], parent_persistent_id="00000000000000F0",
                    persistent_id="00000000000000C1"),
           Playlist(5003, "Other", [1004], persistent_id="00000000000000C2")]
    return itl_bytes(Library(tracks=tracks, playlists=pls, date=D0, persistent_id="0123456789ABCDEF"))


def _sections(raw: bytes) -> dict[int, bytes]:
    itl = parse_itl(raw)
    return {s.type: C.serialize_payload([s], 0x90) for s in itl.sections if s.type != C.SEC_HDFM}


def _hpims(raw: bytes) -> dict[str, bytes]:
    from pytuneslib.itl.document import ItlDocument as D

    itl = parse_itl(raw)
    return {D._pid(c): C.serialize_payload([_one(c)], 0x90) for c in itl.section(C.SEC_PLAYLISTS).items("hpim")}


def _one(c: C.Chunk) -> C.Section:
    s = C.new_section(C.SEC_PLAYLISTS)
    s.chunks.append(c)
    return s


def test_open_save_without_edits_is_identical(tmp_path):
    raw = _raw()
    doc = ItlDocument(raw)
    assert not doc.edited and doc.to_bytes() == raw
    assert doc.save(tmp_path / "x.itl").read_bytes() == raw
    assert parse_itl(raw).to_bytes() == raw  # re-serialising the tree is lossless too


def test_add_playlist_touches_only_playlist_section_and_counts(tmp_path):
    raw = _raw()
    doc = ItlDocument(raw)
    p = doc.add_playlist("New", [1006, 1000], parent="00000000000000F0")
    out = doc.save(tmp_path / "x.itl").read_bytes()
    before, after = _sections(raw), _sections(out)
    assert [t for t in before if before[t] != after[t]] == [C.SEC_PLAYLISTS]
    old, new = _hpims(raw), _hpims(out)
    # existing playlists byte-identical, except the parent folder whose child rules gained one entry
    assert [k for k, v in old.items() if new[k] != v] == ["00000000000000F0"]
    from pytuneslib.itl.folders import criteria_children
    folder = next(x for x in read_itl_bytes(out).playlists if x.persistent_id == "00000000000000F0")
    assert criteria_children(folder.smart_criteria) == ["00000000000000C1", p.persistent_id]
    assert set(new) - set(old) == {p.persistent_id}
    back = read_itl_bytes(out)
    q = next(x for x in back.playlists if x.persistent_id == p.persistent_id)
    assert (q.name, q.track_ids, q.parent_persistent_id) == ("New", [1006, 1000], "00000000000000F0")
    assert int.from_bytes(decrypt_file(out)[0][0x48:0x4C], "big") == 5
    ids = [t.track_id for t in back.tracks] + [x.playlist_id for x in back.playlists]
    assert len(ids) == len(set(ids)) and q.playlist_id > 5003


def test_update_rename_tracks_and_move(tmp_path):
    doc = ItlDocument(_raw())
    item_before = next(k for k in doc._chunk("00000000000000C1").kids("hptm") if k.u32(0x18) == 1002)
    doc.update_playlist("00000000000000C1", name="Renamed", track_ids=[1002, 1004], parent=None)
    item_after = next(k for k in doc._chunk("00000000000000C1").kids("hptm") if k.u32(0x18) == 1002)
    assert bytes(item_after.head) == bytes(item_before.head)  # kept item keeps its id/pid
    back = read_itl(doc.save(tmp_path / "x.itl"))
    c = next(p for p in back.playlists if p.persistent_id == "00000000000000C1")
    assert (c.name, c.track_ids, c.parent_persistent_id) == ("Renamed", [1002, 1004], None)
    other = next(p for p in back.playlists if p.persistent_id == "00000000000000C2")
    assert other.track_ids == [1004] and other.name == "Other"


def test_remove_and_validation():
    doc = ItlDocument(_raw())
    with pytest.raises(ValueError):
        doc.remove_playlist("00000000000000F0")  # non-empty folder
    with pytest.raises(ValueError):
        doc.add_playlist("x", [999])  # unknown track
    with pytest.raises(ValueError):
        doc.add_playlist("x", parent="00000000000000C2")  # parent is not a folder
    with pytest.raises(ValueError):
        doc.update_playlist("00000000000000F0", parent="00000000000000F0")
    with pytest.raises(KeyError):
        doc.update_playlist("FFFFFFFFFFFFFFFF", name="x")
    master = next(p for p in doc.library.playlists if p.master)
    with pytest.raises(ValueError):
        doc.remove_playlist(master.persistent_id)
    assert doc.remove_playlist("00000000000000F0", recursive=True) == ["00000000000000C1", "00000000000000F0"]
    assert [p.name for p in doc.library.playlists] == ["Library", "Other"]


def test_refuses_live_dir(fake_home):
    with pytest.raises(PermissionError):
        ItlDocument(_raw()).save(fake_home / "Music" / "iTunes" / "iTunes Library.itl")


# --- on the real sample (skipped without samples/) ------------------------------------------

@pytest.fixture(scope="module")
def sample_raw():
    if not SAMPLE_ITL.exists():
        pytest.skip("sample itl missing")
    return SAMPLE_ITL.read_bytes()


def test_sample_noop_save_identical(sample_raw):
    assert ItlDocument(sample_raw).to_bytes() == sample_raw
    assert parse_itl(sample_raw).to_bytes() == sample_raw


def test_sample_edit_keeps_everything_else(sample_raw):
    doc = ItlDocument(sample_raw)
    lib = doc.library
    folder = next(p for p in lib.playlists if p.folder)
    target = next(p for p in lib.playlists if not p.master and not p.folder and not p.smart
                  and not p.distinguished_kind and len(p.track_ids) > 1)
    new = doc.add_playlist("pytuneslib test", [t.track_id for t in lib.tracks[:5]], parent=folder.persistent_id)
    doc.update_playlist(target.persistent_id, track_ids=target.track_ids[:1])
    out = doc.to_bytes()
    before, after = _sections(sample_raw), _sections(out)
    assert [t for t in before if before[t] != after[t]] == [C.SEC_PLAYLISTS]
    old, cur = _hpims(sample_raw), _hpims(out)
    changed = {k for k in old if old[k] != cur[k]}
    assert changed == {target.persistent_id, folder.persistent_id}  # folder: one more child rule
    back = read_itl_bytes(out)
    assert len(back.playlists) == len(lib.playlists) + 1
    assert sum(p.folder for p in back.playlists) == sum(p.folder for p in lib.playlists)
    assert sum(p.smart for p in back.playlists) == sum(p.smart for p in lib.playlists)
    assert next(p for p in back.playlists if p.persistent_id == new.persistent_id).parent_persistent_id \
        == folder.persistent_id


def read_itl_bytes(raw: bytes) -> Library:
    from pytuneslib.itl.reader import to_library

    return to_library(parse_itl(raw))


def test_folder_rules_follow_moves_and_removals():
    from pytuneslib.itl.folders import criteria_children

    doc = ItlDocument(_raw())
    rules = lambda pid: criteria_children(doc.playlist(pid).smart_criteria)  # noqa: E731
    assert rules("00000000000000F0") == ["00000000000000C1"]
    f2 = doc.add_playlist("Folder 2", folder=True)
    assert rules(f2.persistent_id) == [] and doc.playlist(f2.persistent_id).folder
    doc.update_playlist("00000000000000C2", parent=f2.persistent_id)
    doc.update_playlist("00000000000000C1", parent=f2.persistent_id)
    assert rules("00000000000000F0") == []
    assert rules(f2.persistent_id) == ["00000000000000C2", "00000000000000C1"]
    doc.remove_playlist("00000000000000C2")
    assert rules(f2.persistent_id) == ["00000000000000C1"]


def test_sample_folder_rules_regenerate_byte_identical(sample_raw):
    """Our folder rule generator reproduces every folder of a real iTunes library byte for byte."""
    from pytuneslib.itl.folders import FOLDER_SMART_INFO, criteria_children, folder_criteria

    lib = read_itl_bytes(sample_raw)
    folders = [p for p in lib.playlists if p.folder]
    assert folders
    for f in folders:
        kids = [p.persistent_id for p in lib.playlists if p.parent_persistent_id == f.persistent_id]
        assert f.smart_info == FOLDER_SMART_INFO
        assert sorted(criteria_children(f.smart_criteria)) == sorted(kids)
        assert folder_criteria(criteria_children(f.smart_criteria)) == f.smart_criteria

