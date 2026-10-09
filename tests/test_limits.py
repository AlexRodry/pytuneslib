import dataclasses

from pytuneslib.limits import MAX_TEXT, TEXT_FIELDS, clamp_library
from pytuneslib.model import Library, Track

NEW_FIELDS = ("grouping", "work", "sort_name", "sort_artist", "sort_album", "sort_album_artist", "sort_composer")


def test_text_fields_cover_all_new_tag_fields():
    assert set(NEW_FIELDS) <= set(TEXT_FIELDS)
    names = {f.name for f in dataclasses.fields(Track)}
    assert set(TEXT_FIELDS) <= names


def test_clamp_new_fields_utf16_units():
    long = "x" * 400
    astral = "\U0001d11e" * 200  # 2 UTF-16 units each -> 127 chars fit in 255 units (254)
    t = Track(1, "C:\a.mp3", **{f: long for f in NEW_FIELDS}, name=astral)
    clamp_library(Library(tracks=[t]))
    for f in NEW_FIELDS:
        assert getattr(t, f) == "x" * MAX_TEXT
    assert t.name == "\U0001d11e" * 127
    assert Track(2, "C:\b.mp3", grouping="short").grouping == "short"


def test_clamp_leaves_none_and_paths_alone():
    t = Track(1, "C:\\" + "d\\" * 200 + "a.mp3")
    loc = t.location
    clamp_library(Library(tracks=[t]))
    assert t.location == loc and t.work is None and t.sort_name is None
