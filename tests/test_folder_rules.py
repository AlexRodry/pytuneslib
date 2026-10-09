"""A folder is a smart playlist in iTunes: XML and ITL writers must derive the same rule blobs."""
import plistlib

from pytuneslib.folders import direct_children, folder_rules, sync_folder_rules
from pytuneslib.itl.folders import FOLDER_SMART_INFO, criteria_children, folder_criteria
from pytuneslib.itl.reader import read_itl
from pytuneslib.itl.writer import write_itl
from pytuneslib.model import Library, Playlist, Track
from pytuneslib.xml_reader import library_from_bytes
from pytuneslib.xml_writer import library_to_xml


def _lib() -> Library:
    folder = Playlist(20, "Folder", [1, 3], persistent_id="AAAAAAAAAAAAAAA1", folder=True)
    a = Playlist(21, "A", [1], persistent_id="BBBBBBBBBBBBBBB1", parent_persistent_id=folder.persistent_id)
    b = Playlist(22, "B", [3], persistent_id="CCCCCCCCCCCCCCC1", parent_persistent_id=folder.persistent_id)
    master = Playlist(10, "Library", [1, 3], master=True, visible=False)
    return Library(
        tracks=[Track(1, r"C:\M\a.mp3", name="a"), Track(3, r"C:\M\b.mp3", name="b")],
        playlists=[master, folder, a, b],
        music_folder=r"C:\M",
    )


def test_fresh_folder_gets_rules_in_xml():
    lib = _lib()
    kids = ["BBBBBBBBBBBBBBB1", "CCCCCCCCCCCCCCC1"]
    assert direct_children(lib) == {"AAAAAAAAAAAAAAA1": kids}
    d = plistlib.loads(library_to_xml(lib))
    folder = d["Playlists"][1]
    assert folder["Folder"] is True
    assert folder["Smart Info"] == FOLDER_SMART_INFO
    assert folder["Smart Criteria"] == folder_criteria(kids)
    assert criteria_children(folder["Smart Criteria"]) == kids
    assert "Smart Info" not in d["Playlists"][2]  # children are plain playlists
    assert lib.playlists[1].smart_criteria is None  # writer does not mutate the library


def test_xml_and_itl_agree(tmp_path):
    lib = _lib()
    xml_folder = library_from_bytes(library_to_xml(lib)).playlists[1]
    back = read_itl(write_itl(lib, tmp_path / "x.itl"))
    itl_folder = next(p for p in back.playlists if p.folder)
    assert xml_folder.smart_criteria == itl_folder.smart_criteria == folder_criteria(
        ["BBBBBBBBBBBBBBB1", "CCCCCCCCCCCCCCC1"]
    )
    assert xml_folder.smart_info == itl_folder.smart_info == FOLDER_SMART_INFO


def test_existing_blobs_kept_stale_ones_regenerated():
    lib = _lib()
    kids = ["BBBBBBBBBBBBBBB1", "CCCCCCCCCCCCCCC1"]
    reordered = folder_criteria(list(reversed(kids)))  # same children, iTunes' own order: keep
    lib.playlists[1].smart_criteria = reordered
    assert folder_rules(lib)["AAAAAAAAAAAAAAA1"][1] == reordered
    lib.playlists[1].smart_criteria = folder_criteria(kids[:1])  # stale: a child is missing
    fixed = folder_rules(lib)["AAAAAAAAAAAAAAA1"][1]
    assert criteria_children(fixed) == kids
    sync_folder_rules(lib)
    assert lib.playlists[1].smart_criteria == fixed
    # idempotent and stable through the XML
    again = library_from_bytes(library_to_xml(lib))
    assert again.playlists[1].smart_criteria == fixed


def test_empty_folder_and_non_folders():
    lib = Library(playlists=[Playlist(1, "Empty", folder=True, persistent_id="DDDDDDDDDDDDDDD1"),
                             Playlist(2, "Plain")])
    rules = folder_rules(lib)
    assert list(rules) == ["DDDDDDDDDDDDDDD1"]
    assert criteria_children(rules["DDDDDDDDDDDDDDD1"][1]) == []
    plistlib.loads(library_to_xml(lib))
