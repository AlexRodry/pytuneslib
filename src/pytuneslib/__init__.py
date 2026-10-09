"""pytuneslib: build iTunes libraries (.itl + .xml) from a music folder, and read them back.

Quick start::

    from pytuneslib import build_library
    lib, files = build_library("D:/Music", "D:/MyLib")  # -> D:/MyLib/iTunes Library.itl + .xml

Edit a library and write it again::

    from pytuneslib import read_itl, add_playlist, write_library
    lib = read_itl("D:/MyLib/iTunes Library.itl")
    add_playlist(lib, "Favourites", [t for t in lib.tracks if t.rating == 100])
    write_library(lib, "D:/MyLib")

Open the result in iTunes (Windows: hold Shift while starting iTunes -> "Choose Library...").
Never point the writers at the library iTunes is currently using.
"""

from .builder import add_playlist, build_library, write_library
from .itl.reader import read_itl
from .itl.writer import itl_bytes, write_itl
from .model import Library, Playlist, Track
from .scanner import scan
from .xml_reader import read_xml
from .xml_writer import write_xml

__version__ = "0.1.0"

__all__ = [
    "Library",
    "Playlist",
    "Track",
    "add_playlist",
    "build_library",
    "itl_bytes",
    "read_itl",
    "read_xml",
    "scan",
    "write_itl",
    "write_library",
    "write_xml",
    "__version__",
]
