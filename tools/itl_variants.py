"""Build bisection candidates from an iTunes-made oracle .itl and one of ours.

    python tools/itl_variants.py out/lab/oracle.itl out/lab/ours.itl [--sample "samples/iTunes Library.itl"]

Writes out/lab/variants/NN_name.itl (+ index.txt). Feed them to tools/itunes_probe.py.
"""

from __future__ import annotations

import argparse
import copy
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pytuneslib.itl import chunks as C  # noqa: E402
from pytuneslib.itl.reader import ItlFile, load_itl  # noqa: E402

HDFM_SECTION_COUNT = 0x30


def fix_counts(itl: ItlFile) -> ItlFile:
    n = len(itl.sections)
    struct.pack_into(">I", itl.header, HDFM_SECTION_COUNT, n)
    inner = itl.section(C.SEC_HDFM)
    if inner:
        inner.chunks[0].set_u32(HDFM_SECTION_COUNT, n)
    return itl


def drop(itl: ItlFile, *types: int) -> ItlFile:
    itl = copy.deepcopy(itl)
    itl.sections = [s for s in itl.sections if s.type not in types]
    return fix_counts(itl)


def insert_from(dst: ItlFile, src: ItlFile, *types: int) -> ItlFile:
    """Insert src sections of the given types, keeping src's relative order."""
    dst = copy.deepcopy(dst)
    order = [s.type for s in src.sections]
    for t in types:
        s = copy.deepcopy(src.section(t))
        idx = order.index(t)
        after = [x.type for x in src.sections[:idx]]
        pos = max((i + 1 for i, x in enumerate(dst.sections) if x.type in after), default=0)
        dst.sections.insert(pos, s)
    return fix_counts(dst)


def replace_chunk_head(itl: ItlFile, sec: int, idx: int, head: bytes) -> ItlFile:
    itl = copy.deepcopy(itl)
    c = itl.section(sec).chunks[idx]
    keep = bytes(c.head[8:12])
    c.head = bytearray(head)
    c.head[8:12] = keep
    return itl


def path_ids(itl: ItlFile) -> ItlFile:
    """Set htim hohm 13 (path) +0x10 = 1 and hohm 11 (URL) +0x10 = 2, as iTunes writes them."""
    for c in itl.section(C.SEC_TRACKS).items("htim"):
        for k in c.kids("hohm"):
            if k.hohm_type in (13, 11):
                k.set_u32(0x10, 1 if k.hohm_type == 13 else 2)
    return itl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("oracle", type=Path)
    ap.add_argument("ours", type=Path)
    ap.add_argument("--sample", type=Path, default=ROOT / "samples" / "iTunes Library.itl")
    a = ap.parse_args()
    O, U = load_itl(a.oracle), load_itl(a.ours)
    S = load_itl(a.sample) if a.sample.exists() else None

    v: dict[str, ItlFile] = {
        "00_oracle_reencoded": copy.deepcopy(O),
        "01_ours_unchanged": copy.deepcopy(U),
        "02_ours_without_20_21_15": drop(U, C.SEC_HQLM, C.SEC_HSLM, C.SEC_HRLM),
        "03_ours_without_20": drop(U, C.SEC_HQLM),
        "04_oracle_plus_our_20_21_15": insert_from(O, U, C.SEC_HQLM, C.SEC_HSLM, C.SEC_HRLM),
        "05_oracle_plus_our_21_15": insert_from(O, U, C.SEC_HSLM, C.SEC_HRLM),
        "09_ours_without_21": drop(U, C.SEC_HSLM),
        "10_ours_without_15": drop(U, C.SEC_HRLM),
        "11_ours_wo_20_21_15_path_ids_1_2": path_ids(drop(U, C.SEC_HQLM, C.SEC_HSLM, C.SEC_HRLM)),
        "06_ours_with_oracle_hghm": replace_chunk_head(U, C.SEC_LIBRARY, 0, bytes(O.section(C.SEC_LIBRARY).chunks[0].head)),
    }
    if S is not None:
        hq = bytes(S.section(C.SEC_HQLM).chunks[0].head)
        hq = bytearray(hq)
        struct.pack_into("<II", hq, 0x10, 0, 0)  # no queued items
        v["07_ours_hqlm_from_sample"] = replace_chunk_head(U, C.SEC_HQLM, 0, bytes(hq))

    out = ROOT / "out" / "lab" / "variants"
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, itl in v.items():
        p = out / f"{name}.itl"
        p.write_bytes(itl.to_bytes())
        lines.append(f"{p.name}\t{len(itl.sections)} sections\t{[s.type for s in itl.sections]}")
    (out / "index.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
