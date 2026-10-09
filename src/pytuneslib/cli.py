"""Command line: python -m pytuneslib build <music_dir> <out_dir>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import build_library
from .paths import parse_path_map


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pytuneslib", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="scan a music folder and write .itl + .xml")
    b.add_argument("music_dir", type=Path)
    b.add_argument("out_dir", type=Path)
    b.add_argument("--no-itl", action="store_true", help="only write the XML")
    b.add_argument("--include-unsupported", action="store_true", help="also add FLAC/OGG/...")
    b.add_argument("--kind-locale", default="en", choices=["en", "es"])
    b.add_argument("--music-folder", help="iTunes Media folder as iTunes sees it (default: <out_dir>/iTunes Media)")
    b.add_argument("--path-map", action="append", default=[], metavar="SRC=DST",
                   help="rewrite track path prefix SRC (this machine) to DST (as iTunes sees it), "
                        "e.g. /mnt/nas/music=\\\\NAS\\music; repeatable")
    args = ap.parse_args(argv)

    out = args.out_dir.resolve()
    if (Path.home() / "Music" / "iTunes").resolve() == out:
        ap.error(f"refusing to overwrite the real iTunes library folder: {out}")
    if not args.music_dir.is_dir():
        ap.error(f"not a directory: {args.music_dir}")

    try:
        location_map = parse_path_map(args.path_map)
    except ValueError as e:
        ap.error(str(e))
    lib, written = build_library(
        args.music_dir,
        out,
        itl=not args.no_itl,
        include_unsupported=args.include_unsupported,
        kind_locale=args.kind_locale,
        music_folder=args.music_folder,
        location_map=location_map,
    )
    print(f"{len(lib.tracks)} tracks")
    for kind, path in written.items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
