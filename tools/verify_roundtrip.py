"""Acceptance check: does a read + rewrite keep playlists, folders, smart rules and track fields?

Usage:
    python tools/verify_roundtrip.py <library.itl> [--xml X] [--out DIR]

Every file is counted twice:
  raw    - from the file's own records (ITL chunk offsets, XML plist keys). This is the authority.
  model  - what pytuneslib's reader returns in Track / Playlist / Library. Shows reader gaps.

The original is read, written again with write_itl (and through the edit mode, ItlDocument, when
pytuneslib provides it; and through write_xml when --xml is given), and each output is counted
again from its raw records. A metric that drops is a loss. Exit code 1 when any loss is found.
"""

from __future__ import annotations

import argparse
import plistlib
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pytuneslib.itl import chunks as C  # noqa: E402
from pytuneslib.itl.reader import P, T, parse_itl, pid_from_bytes, read_itl  # noqa: E402
from pytuneslib.itl.writer import write_itl  # noqa: E402
from pytuneslib.xml_reader import read_xml  # noqa: E402
from pytuneslib.xml_writer import write_xml  # noqa: E402

try:  # edit mode (pgOpus); absent until it exists
    from pytuneslib.itl.document import ItlDocument  # type: ignore
except ImportError:
    ItlDocument = None

LOVED_OFF = 0x2BF  # htim: bit 0x02 (validated against XML "Loved": 15 = 15)
DATA_OFF = 0x18  # hohm: payload starts here (per pgOpus; byte-equal to XML for 71/71)
SMART_CRITERIA, SMART_INFO = 101, 102  # hohm 101 = Smart Criteria, 102 = Smart Info
SORT_TYPES = {30, 31, 32, 33, 34}
GROUPING_TYPE, WORK_TYPE = 14, 63

TRACK_FIELDS = ("loved", "play_date", "grouping", "skip", "sort", "work")
COUNT_METRICS = ("tracks", "playlists", "folders", "parent_relations", "smart_playlists", "special_playlists")


@dataclass
class Census:
    tracks: int = 0
    fields: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TRACK_FIELDS, 0))
    pids: set[str] = field(default_factory=set)
    folders: set[str] = field(default_factory=set)
    parents: set[tuple[str, str]] = field(default_factory=set)  # (child pid, parent pid)
    smart: dict[str, tuple[bytes | None, bytes | None]] = field(default_factory=dict)
    special: dict[str, int] = field(default_factory=dict)  # pid -> distinguished kind

    def metrics(self) -> dict[str, int]:
        return {
            "tracks": self.tracks,
            "playlists": len(self.pids),
            "folders": len(self.folders),
            "parent_relations": len(self.parents),
            "smart_playlists": len(self.smart),
            "special_playlists": len(self.special),
            **self.fields,
        }


# --- raw censuses -----------------------------------------------------------

def _section_items(itl, sec_type: int, tag: str) -> list:
    sec = itl.section(sec_type)
    return sec.items(tag) if sec else []


def census_itl_raw(raw: bytes) -> Census:
    itl = parse_itl(raw)
    c = Census()
    for t in _section_items(itl, C.SEC_TRACKS, "htim"):
        c.tracks += 1
        h = t.head
        types = {k.hohm_type for k in t.kids("hohm")}
        if h[LOVED_OFF] & 0x02:
            c.fields["loved"] += 1
        if t.u32(T["play_date"]):
            c.fields["play_date"] += 1
        if GROUPING_TYPE in types:
            c.fields["grouping"] += 1
        if t.u32(T["skip_count"]):
            c.fields["skip"] += 1
        if types & SORT_TYPES:
            c.fields["sort"] += 1
        if WORK_TYPE in types:
            c.fields["work"] += 1
    for p in _section_items(itl, C.SEC_PLAYLISTS, "hpim"):
        h = p.head
        pid = pid_from_bytes(bytes(h[P["persistent_id"]:P["persistent_id"] + 8]))
        c.pids.add(pid)
        parent_raw = bytes(h[P["parent_pid"]:P["parent_pid"] + 8])
        if any(parent_raw):
            c.parents.add((pid, pid_from_bytes(parent_raw)))
        if h[P["folder"]]:
            c.folders.add(pid)
        if h[P["distinguished_kind"]]:
            c.special[pid] = h[P["distinguished_kind"]]
        blobs = {k.hohm_type: bytes(k.head[DATA_OFF:]) for k in p.kids("hohm")
                 if k.hohm_type in (SMART_INFO, SMART_CRITERIA)}
        if blobs:
            c.smart[pid] = (blobs.get(SMART_INFO), blobs.get(SMART_CRITERIA))
    return c


def census_xml_raw(path: Path) -> Census:
    d = plistlib.loads(Path(path).read_bytes())
    c = Census()
    for t in d.get("Tracks", {}).values():
        c.tracks += 1
        if t.get("Loved"):
            c.fields["loved"] += 1
        if "Play Date UTC" in t or "Play Date" in t:
            c.fields["play_date"] += 1
        if "Grouping" in t:
            c.fields["grouping"] += 1
        if t.get("Skip Count"):
            c.fields["skip"] += 1
        if any(k.startswith("Sort ") for k in t):
            c.fields["sort"] += 1
        if "Work" in t:
            c.fields["work"] += 1
    for p in d.get("Playlists", []):
        pid = p["Playlist Persistent ID"]
        c.pids.add(pid)
        if "Parent Persistent ID" in p:
            c.parents.add((pid, p["Parent Persistent ID"]))
        if p.get("Folder"):
            c.folders.add(pid)
        if "Distinguished Kind" in p:
            c.special[pid] = p["Distinguished Kind"]
        if "Smart Criteria" in p or "Smart Info" in p:
            c.smart[pid] = (p.get("Smart Info"), p.get("Smart Criteria"))
    return c


# --- model census (what the reader returns) ----------------------------------

def census_model(lib) -> Census:
    c = Census(tracks=len(lib.tracks))
    for t in lib.tracks:
        if t.loved:
            c.fields["loved"] += 1
        if t.play_date is not None:
            c.fields["play_date"] += 1
        if t.grouping:
            c.fields["grouping"] += 1
        if t.skip_count:
            c.fields["skip"] += 1
        if any(getattr(t, f) for f in ("sort_name", "sort_artist", "sort_album", "sort_album_artist", "sort_composer")):
            c.fields["sort"] += 1
        if t.work:
            c.fields["work"] += 1
    for p in lib.playlists:
        c.pids.add(p.persistent_id)
        if p.parent_persistent_id:
            c.parents.add((p.persistent_id, p.parent_persistent_id))
        if p.folder:
            c.folders.add(p.persistent_id)
        if p.distinguished_kind:
            c.special[p.persistent_id] = p.distinguished_kind
        if p.smart_criteria or p.smart_info:
            c.smart[p.persistent_id] = (p.smart_info, p.smart_criteria)
    return c


# --- comparison --------------------------------------------------------------

def compare(orig: Census, new: Census) -> dict[str, int]:
    """Losses per metric: items in orig that are missing or reduced in new."""
    losses = {}
    o, n = orig.metrics(), new.metrics()
    for k in o:
        losses[k] = max(0, o[k] - n[k])
    losses["folders"] = len(orig.folders - new.folders)
    losses["parent_relations"] = len(orig.parents - new.parents)
    losses["smart_playlists"] = len(set(orig.smart) - set(new.smart))
    losses["special_playlists"] = len(set(orig.special) - set(new.special))
    losses["smart_blobs"] = sum(
        1 for pid, blobs in orig.smart.items() if pid in new.smart and new.smart[pid] != blobs
    )
    return losses


# --- driver ------------------------------------------------------------------

def run(itl_path: Path, xml_path: Path | None, out: Path):
    """Returns (raw censuses, model censuses, losses per pipeline, total loss count)."""
    raw = itl_path.read_bytes()
    censuses: dict[str, Census] = {"ITL original (raw)": census_itl_raw(raw)}
    models: dict[str, Census] = {"ITL original (model)": census_model(read_itl(itl_path))}
    losses: dict[str, dict[str, int]] = {}

    lib_itl = read_itl(itl_path)
    w = out / "write_itl" / "iTunes Library.itl"
    write_itl(lib_itl, w, music_folder=lib_itl.music_folder)
    censuses["write_itl (raw)"] = census_itl_raw(w.read_bytes())
    models["write_itl (model)"] = census_model(read_itl(w))
    losses["write_itl"] = compare(censuses["ITL original (raw)"], censuses["write_itl (raw)"])

    if ItlDocument is not None:
        e = out / "edit" / "iTunes Library.itl"
        e.parent.mkdir(parents=True, exist_ok=True)
        ItlDocument.open(itl_path).save(e)
        censuses["edit (raw)"] = census_itl_raw(e.read_bytes())
        models["edit (model)"] = census_model(read_itl(e))
        losses["edit"] = compare(censuses["ITL original (raw)"], censuses["edit (raw)"])

    if xml_path is not None:
        censuses["XML original (raw)"] = census_xml_raw(xml_path)
        x = out / "write_xml" / "iTunes Music Library.xml"
        write_xml(read_xml(xml_path), x)
        censuses["write_xml (raw)"] = census_xml_raw(x)
        losses["write_xml"] = compare(censuses["XML original (raw)"], censuses["write_xml (raw)"])

    total = sum(v for per in losses.values() for v in per.values())
    return censuses, models, losses, total


def print_table(censuses: dict[str, Census], losses: dict[str, dict[str, int]]) -> None:
    cols = list(censuses)
    width = 22
    head = f"{'metric':<22}" + "".join(f"{c.replace(' (raw)', ''):>{width}}" for c in cols)
    print("raw counts (from each file's own records):")
    print(head)
    print("-" * len(head))
    for k in list(COUNT_METRICS) + list(TRACK_FIELDS):
        print(f"{k:<22}" + "".join(f"{censuses[c].metrics()[k]:>{width}}" for c in cols))
    cells = []
    for c in cols:
        base = "XML original (raw)" if c.startswith("write_xml") else "ITL original (raw)"
        cells.append("-" if c.endswith("original (raw)") else _blob_equal(censuses[base], censuses[c]))
    print(f"{'smart blobs byte-equal':<22}" + "".join(f"{v:>{width}}" for v in cells))
    print()
    print("loss per pipeline (0 = nothing lost):")
    for name, per in losses.items():
        lost = {k: v for k, v in per.items() if v}
        status = "OK" if not lost else "LOSS " + ", ".join(f"{k}={v}" for k, v in lost.items())
        print(f"  {name:<12} {status}")
    print()


def _blob_equal(orig: Census, new: Census) -> str:
    """'equal/total' for smart playlists of orig that new keeps with identical Smart Info + Criteria."""
    same = sum(1 for pid, blobs in orig.smart.items() if new.smart.get(pid) == blobs)
    return f"{same}/{len(orig.smart)}"


def print_model_view(models: dict[str, Census]) -> None:
    cols = list(models)
    width = 22
    print("reader view (model fields, as read_itl / read_xml return them):")
    head = f"{'metric':<22}" + "".join(f"{c.replace(' (model)', ''):>{width}}" for c in cols)
    print(head)
    for k in list(COUNT_METRICS) + list(TRACK_FIELDS):
        print(f"{k:<22}" + "".join(f"{models[c].metrics()[k]:>{width}}" for c in cols))
    print()


def print_diagnostics(censuses: dict[str, Census]) -> None:
    itl = censuses["ITL original (raw)"]
    if "XML original (raw)" not in censuses:
        return
    xml = censuses["XML original (raw)"]
    print("where the ITL and XML originals differ:")
    print(f"  playlists  ITL {len(itl.pids)} vs XML {len(xml.pids)}; only in ITL: {len(itl.pids - xml.pids)}")
    print(f"  special    ITL {len(itl.special)} vs XML {len(xml.special)}; "
          f"only in ITL (pid, kind): {[(p, itl.special[p]) for p in sorted(set(itl.special) - set(xml.special))][:8]}")
    only_smart = set(itl.smart) - set(xml.smart)
    print(f"  smart      ITL {len(itl.smart)} vs XML {len(xml.smart)}; only in ITL: {len(only_smart)}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("itl", type=Path)
    ap.add_argument("--xml", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None, help="keep rewritten files here (default: temp dir)")
    args = ap.parse_args(argv)
    if not args.itl.is_file():
        ap.error(f"not a file: {args.itl}")
    out = args.out or Path(tempfile.mkdtemp(prefix="verify_roundtrip_"))
    out.mkdir(parents=True, exist_ok=True)

    censuses, models, losses, total = run(args.itl, args.xml, out)
    print_table(censuses, losses)
    print_model_view(models)
    print_diagnostics(censuses)
    print(f"rewritten files: {out}")
    if ItlDocument is None:
        print("edit mode: not run (pytuneslib.itl.document.ItlDocument not available yet)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
