"""ITL <-> XML cross-checks. Skipped until pytuneslib.itl.reader/writer exist.

Mismatches are reported as a compact diff (first MAX_DIFFS) so the ITL mapping can be fixed.
"""
import dataclasses
from pathlib import Path

import pytest

from pytuneslib.model import Library
from pytuneslib.scanner import scan
from pytuneslib.xml_reader import read_xml
from pytuneslib.xml_writer import library_to_xml
from pytuneslib.xml_reader import library_from_bytes

SAMPLE_ITL = Path(__file__).resolve().parent.parent / "samples" / "iTunes Library.itl"
MAX_DIFFS = 40


def _reader():
    return pytest.importorskip("pytuneslib.itl.reader", reason="itl reader not implemented yet").read_itl


def _writer():
    return pytest.importorskip("pytuneslib.itl.writer", reason="itl writer not implemented yet").write_itl


def _short(v, n=70):
    s = repr(v)
    return s if len(s) <= n else s[: n - 3] + "..."


def _n(v):
    """XML parsers turn CRLF into LF inside values; the ITL keeps the original CRLF."""
    return v.replace("\r\n", "\n") if isinstance(v, str) else v


def diff_libraries(xml: Library, itl: Library, *, check_playlists=True) -> list[str]:
    """Compact list of 'where: xml=<v> itl=<v>' lines."""
    out: list[str] = []
    if xml.persistent_id != itl.persistent_id:
        out.append(f"library.persistent_id: xml={xml.persistent_id} itl={itl.persistent_id}")
    xt = {t.track_id: t for t in xml.tracks}
    it = {t.track_id: t for t in itl.tracks}
    miss = sorted(set(xt) - set(it))
    extra = sorted(set(it) - set(xt))
    if miss:
        out.append(f"tracks missing in itl ({len(miss)}): {miss[:10]}")
    if extra:
        out.append(f"tracks extra in itl ({len(extra)}): {extra[:10]}")
    per_field: dict[str, int] = {}
    for tid in sorted(set(xt) & set(it)):
        a, b = xt[tid], it[tid]
        for f in dataclasses.fields(a):
            va, vb = _n(getattr(a, f.name)), _n(getattr(b, f.name))
            if va != vb:
                per_field[f.name] = per_field.get(f.name, 0) + 1
                if per_field[f.name] <= 3:  # first few examples per field
                    out.append(f"track {tid}.{f.name}: xml={_short(va)} itl={_short(vb)}")
    for name, n in sorted(per_field.items()):
        out.append(f"SUMMARY field {name}: {n} tracks differ")
    if check_playlists:
        xp = {p.playlist_id: p for p in xml.playlists}
        ip = {p.playlist_id: p for p in itl.playlists}
        miss = sorted(set(xp) - set(ip))
        # iTunes omits empty system playlists (TV, Videoclips, Genius...) from the XML
        extra = sorted(
            pid for pid in set(ip) - set(xp)
            if ip[pid].track_ids or ip[pid].distinguished_kind is None
        )
        if miss:
            out.append(f"playlists missing in itl ({len(miss)}): {miss[:10]}")
        if extra:
            out.append(f"playlists extra in itl ({len(extra)}): {extra[:10]}")
        pf: dict[str, int] = {}
        for pid in sorted(set(xp) & set(ip)):
            a, b = xp[pid], ip[pid]
            for f in dataclasses.fields(a):
                if f.name == "name" and a.master:  # master name is localized in XML ("Biblioteca")
                    continue
                va, vb = getattr(a, f.name), getattr(b, f.name)
                if va != vb:
                    pf[f.name] = pf.get(f.name, 0) + 1
                    if pf[f.name] <= 3:
                        out.append(f"playlist {pid} ({a.name!r}).{f.name}: xml={_short(va)} itl={_short(vb)}")
        for name, n in sorted(pf.items()):
            out.append(f"SUMMARY playlist field {name}: {n} playlists differ")
    return out


def _assert_no_diff(diffs: list[str]):
    if diffs:
        head = diffs[:MAX_DIFFS]
        more = f"\n... {len(diffs) - MAX_DIFFS} more" if len(diffs) > MAX_DIFFS else ""
        pytest.fail(f"{len(diffs)} mismatches\n" + "\n".join(head) + more, pytrace=False)


@pytest.fixture(scope="module")
def sample_itl_path():
    if not SAMPLE_ITL.exists():
        pytest.skip("samples/iTunes Library.itl not present")
    return SAMPLE_ITL


def test_sample_itl_matches_sample_xml(sample_itl_path, sample_xml):
    read_itl = _reader()
    _assert_no_diff(diff_libraries(read_xml(sample_xml), read_itl(sample_itl_path)))


def test_sample_itl_track_ids_and_pid(sample_itl_path, sample_xml):
    """Cheaper subset: ids + library persistent id only."""
    read_itl = _reader()
    x, i = read_xml(sample_xml), read_itl(sample_itl_path)
    assert {t.track_id for t in x.tracks} == {t.track_id for t in i.tracks}
    assert x.persistent_id == i.persistent_id


def test_scan_write_itl_read_itl_roundtrip(music_dir, tmp_path):
    read_itl, write_itl = _reader(), _writer()
    lib = scan(music_dir)
    out = write_itl(lib, tmp_path / "iTunes Library.itl")
    back = read_itl(out)
    _assert_no_diff(diff_libraries(lib, back))


def test_end_to_end_xml_consistent_with_itl(music_dir, tmp_path):
    read_itl, write_itl = _reader(), _writer()
    lib = scan(music_dir)
    from_itl = read_itl(write_itl(lib, tmp_path / "x.itl"))
    from_xml = library_from_bytes(library_to_xml(lib))
    _assert_no_diff(diff_libraries(from_xml, from_itl))
