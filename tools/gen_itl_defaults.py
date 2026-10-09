"""Generate src/pytuneslib/itl/_defaults.py from a real iTunes 12.13 library.

    python tools/gen_itl_defaults.py "samples/iTunes Library.itl"

Item headers (htim/haim/hiim/hpim/hptm) are the per-byte mode across all
records of that type; bytes whose mode is below MODE_MIN are zeroed, so ids,
persistent ids, dates and other per-record values never leak into defaults.
Singletons are copied with ids/pids/dates/counts scrubbed. No strings from the
source library are kept except fixed iTunes blobs (view settings, smart rules,
podcast settings plist).
"""

from __future__ import annotations

import collections
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pytuneslib.itl import chunks as C  # noqa: E402
from pytuneslib.itl.reader import P, load_itl, playlist_from_chunk  # noqa: E402

MODE_MIN = 0.6


def mode_header(chs: list[C.Chunk]) -> bytes:
    n = len(chs)
    size = len(chs[0].head)
    out = bytearray(size)
    for o in range(size):
        v, f = collections.Counter(c.head[o] for c in chs if len(c.head) > o).most_common(1)[0]
        out[o] = v if f >= MODE_MIN * n else 0
    return bytes(out)


def zero(b: bytes, *ranges: tuple[int, int]) -> bytes:
    a = bytearray(b)
    for off, n in ranges:
        a[off:off + n] = bytes(n)
    return bytes(a)


# Aligned u32 values in this range are mac timestamps (~1998..2031): library/playlist creation and
# save dates of the source library. Scrubbed from every singleton blob; the writer sets its own.
MAC_DATE_RANGE = (0xB2000000, 0xF0000000)


def scrub_dates(b: bytes, start: int = 0x10) -> bytes:
    a = bytearray(b)
    for o in range(start, len(a) - 3, 4):
        if MAC_DATE_RANGE[0] <= struct.unpack_from("<I", a, o)[0] < MAC_DATE_RANGE[1]:
            a[o:o + 4] = bytes(4)
    return bytes(a)


def scrub_plist_dates(b: bytes) -> bytes:
    """<date>...</date> in embedded plists -> a fixed neutral date of the same length."""
    return re.sub(rb"<date>[^<]{20}</date>", b"<date>2001-01-01T00:00:00Z</date>", b)


def main(src: str) -> None:
    itl = load_itl(src)
    sec = itl.section
    out: dict[str, bytes] = {}

    # Outer hdfm (BE) / inner hdfm (LE): scrub pid, counts, date, tz.
    hdfm_scrub = [(0x08, 4), (0x34, 8), (0x44, 12), (0x54, 4), (0x64, 4), (0x70, 4)]
    out["HDFM_OUTER"] = zero(bytes(itl.header), *hdfm_scrub)
    out["HDFM_INNER"] = zero(bytes(sec(C.SEC_HDFM).chunks[0].head), *hdfm_scrub)

    gh = sec(C.SEC_LIBRARY).chunks[0]
    out["HGHM"] = scrub_dates(bytes(gh.head))
    out["HGHM_517"] = next(bytes(k.head) for k in gh.kids("hohm") if k.hohm_type == 517)

    for t, s in (("halm", 9), ("hilm", 11), ("htlm", 1), ("hplm", 2), ("hrlm", 15)):
        out[t.upper()] = zero(bytes(sec(s).chunks[0].head), (8, 4))
    out["HTLM2"] = bytes(sec(C.SEC_TRACKS2).chunks[0].head)
    # keep +0x0C/+0x18 flags and the "tslp" magic at +0x1C; zero item count (+0x10) and +0x14
    out["HQLM"] = zero(bytes(sec(C.SEC_HQLM).chunks[0].head), (8, 4), (0x10, 8))
    out["HSTS"] = bytes(sec(C.SEC_HSTS).chunks[0].head)
    out["HPLM_GENIUS"] = zero(bytes(sec(C.SEC_GENIUS).chunks[0].head), (8, 4))
    hslm = sec(C.SEC_HSLM)
    out["HSLM"] = bytes(hslm.chunks[0].head)
    out["HPSM"] = bytes(hslm.chunks[1].head)
    out["HPSM_800"] = scrub_plist_dates(bytes(hslm.chunks[1].children[0].head))

    out["HTIM"] = scrub_dates(mode_header(sec(C.SEC_TRACKS).items("htim")))
    out["HAIM"] = mode_header(sec(C.SEC_ALBUMS).items("haim"))
    out["HIIM"] = mode_header(sec(C.SEC_ARTISTS).items("hiim"))
    hp = sec(C.SEC_PLAYLISTS).items("hpim")
    out["HPTM"] = mode_header([k for p in hp for k in p.kids("hptm")])

    def kid_blobs(p: C.Chunk, skip: set[int]) -> list[bytes]:
        return [bytes(k.head) for k in p.kids("hohm") if k.hohm_type not in skip]

    pid_rng = (P["persistent_id"], 8)
    master = next(p for p in hp if p.head[P["master"]])
    music = next(p for p in hp if playlist_from_chunk(p).distinguished_kind == 4)
    plain = [p for p in hp if not p.head[P["master"]] and not p.head[P["folder"]]
             and not p.head[P["distinguished_kind"]]
             and {k.hohm_type for k in p.kids("hohm")} >= {100, 105, 108}
             and not any(k.hohm_type in (101, 102) for k in p.kids("hohm"))]
    # +0x20/+0x24 of the master playlist are library-wide totals of the source library
    scrub_p = [(8, 12), (0x20, 8), pid_rng, (P["parent_pid"], 8), (P["playlist_id"], 4)]
    out["HPIM_MASTER"] = scrub_dates(zero(bytes(master.head), *scrub_p))
    out["HPIM_MUSIC"] = scrub_dates(zero(bytes(music.head), *scrub_p))
    out["HPIM"] = scrub_dates(zero(mode_header(plain), *scrub_p))
    lists = {
        "HPIM_MASTER_KIDS": kid_blobs(master, {100, 109}),
        "HPIM_MUSIC_KIDS": kid_blobs(music, {100, 109}),
        "HPIM_KIDS": kid_blobs(plain[0], {100, 109}),
    }
    # Playlist folders and user smart playlists: header = per-byte mode over all of them.
    folders = [p for p in hp if p.head[P["folder"]]]
    smart = [p for p in hp if not p.head[P["master"]] and not p.head[P["folder"]]
             and not p.head[P["distinguished_kind"]] and any(k.hohm_type == 101 for k in p.kids("hohm"))]
    out["HPIM_FOLDER"] = scrub_dates(zero(mode_header(folders), *scrub_p))
    out["HPIM_SMART"] = scrub_dates(zero(mode_header(smart), *scrub_p))
    lists["HPIM_FOLDER_KIDS"] = kid_blobs(folders[0], {100, 101, 102, 109})
    lists["HPIM_SMART_KIDS"] = kid_blobs(smart[0], {100, 101, 102, 109})
    # Built-in (distinguished) playlists: their own header + view blobs + iTunes' stock smart rules.
    builtin: dict[int, tuple[bytes, list[bytes]]] = {}
    for p in hp:
        dk = p.head[P["distinguished_kind"]]
        if dk and not p.head[P["master"]] and dk not in builtin:
            builtin[dk] = (scrub_dates(zero(bytes(p.head), *scrub_p)), kid_blobs(p, {100, 109}))

    lines = ['"""Default chunk bytes for the .itl writer. GENERATED by tools/gen_itl_defaults.py."""',
             "", "_h = bytes.fromhex", ""]
    for k, v in out.items():
        lines.append(f'{k} = _h("{v.hex()}")')
    for k, vs in lists.items():
        lines.append(f"{k} = [")
        lines += [f'    _h("{v.hex()}"),' for v in vs]
        lines.append("]")
    lines.append("# distinguished kind -> (hpim header, hohm kids without name/plist); smart rules included")
    lines.append("BUILTIN = {")
    for dk, (head, kids) in sorted(builtin.items()):
        lines.append(f'    {dk}: (_h("{head.hex()}"), [')
        lines += [f'        _h("{v.hex()}"),' for v in kids]
        lines.append("    ]),")
    lines.append("}")
    dst = ROOT / "src" / "pytuneslib" / "itl" / "_defaults.py"
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {dst} ({dst.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "samples" / "iTunes Library.itl"))
