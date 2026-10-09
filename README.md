# pytuneslib

[![PyPI version](https://img.shields.io/pypi/v/pytuneslib.svg)](https://pypi.org/project/pytuneslib/)
[![CI](https://github.com/AlexRodry/pytuneslib/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexRodry/pytuneslib/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**[English](README.md)** · [Español](README.es.md)

Generate iTunes library files from a folder of music: `iTunes Library.itl` (the binary database iTunes 12.13 opens) and `iTunes Music Library.xml` (the plist export), built from the same in-memory library.

## Features

- Scans MP3, M4A (AAC and ALAC), WAV, AIFF and M4B files, and reads their tags with [mutagen](https://mutagen.readthedocs.io/).
- Writes `iTunes Library.itl` and `iTunes Music Library.xml` with consistent contents: tracks, albums, artists, playlists, and a master "Library" playlist.
- Reads existing `.itl` and XML libraries back into a Python model, so you can edit a library and write it again.
- Command-line interface and a small Python API.
- Refuses to write into the default iTunes library folder.

## Installation

Requires Python 3.10 or newer.

```bash
pip install pytuneslib
```

From a clone of the repository, for development:

```bash
pip install -e ".[dev]"
```

## Quickstart: command line

Build a library from a music folder into an output folder:

```bash
python -m pytuneslib build D:/Music D:/pytuneslib-out/first-try
```

This writes:

```
D:/pytuneslib-out/first-try/
├── iTunes Library.itl
├── iTunes Music Library.xml
└── iTunes Media/          <- default Music Folder (the media folder iTunes will use)
```

Options:

| Option | Effect |
|---|---|
| `--no-itl` | Write only `iTunes Music Library.xml`. |
| `--include-unsupported` | Also scan FLAC, OGG, Opus and WMA. iTunes cannot play these, so they are skipped by default. |
| `--kind-locale en\|es` | Language of the "Kind" field, for example `MPEG audio file` (`en`) or `Archivo de audio MPEG` (`es`). Default `en`. |
| `--music-folder PATH` | Music Folder to store in the library. Default: `<out_dir>/iTunes Media`. |
| `--path-map SRC=DST` | Rewrite the track path prefix `SRC` (as this machine sees it) to `DST` (as iTunes sees it). Repeatable. Example for Linux to Windows iTunes: `--path-map "/mnt/nas/music=\\NAS\music"`. |

## Quickstart: Python

### Build a library

```python
from pytuneslib.builder import build_library

lib, written = build_library("D:/Music", "D:/pytuneslib-out/first-try")
print(len(lib.tracks), "tracks")
print(written["itl"], written["xml"])
```

`build_library` returns the in-memory `Library` and a dict with the paths it wrote (`"xml"`, and `"itl"` unless `itl=False`).

### Read an existing library

```python
from pytuneslib.itl.reader import read_itl
from pytuneslib.xml_reader import read_xml

lib = read_itl("D:/pytuneslib-out/first-try/iTunes Library.itl")
for track in lib.tracks[:3]:
    print(track.name, "-", track.artist)

lib_xml = read_xml("D:/pytuneslib-out/first-try/iTunes Music Library.xml")
```

### Modify a library and write it

This adds a playlist with every track whose genre is "Electronic" and writes the result to a new folder:

```python
from pytuneslib.builder import write_library
from pytuneslib.itl.reader import read_itl
from pytuneslib.model import Playlist

lib = read_itl("D:/pytuneslib-out/first-try/iTunes Library.itl")

next_id = max(p.playlist_id for p in lib.playlists) + 1
electronic = [t.track_id for t in lib.tracks if t.genre == "Electronic"]
lib.playlists.append(Playlist(playlist_id=next_id, name="Electronic", track_ids=electronic))

write_library(lib, "D:/pytuneslib-out/with-playlist", music_folder=lib.music_folder)
```

Pass `music_folder=lib.music_folder` when rewriting a library you read, so the Music Folder stays the one it had. Without it, `write_library` uses `<out_dir>/iTunes Media`.

### Edit an existing .itl in place

`ItlDocument` changes only the playlists you touch; every other byte of the library (tracks, play counts, folders, smart rules, view settings) is written back exactly as iTunes left it. Saving without edits produces an identical file.

```python
from pytuneslib import ItlDocument

doc = ItlDocument.open("D:/MyLib/iTunes Library.itl")
lib = doc.library  # read-only Library view of the current state

folder = doc.add_playlist("Sets", folder=True)
techno = [t.track_id for t in lib.tracks if t.genre == "Techno"]
mix = doc.add_playlist("Friday", techno, parent=folder.persistent_id)

doc.update_playlist(mix.persistent_id, name="Friday mix", track_ids=techno[:30])
doc.update_playlist(mix.persistent_id, parent=None)        # move to the top level
doc.remove_playlist(folder.persistent_id)                   # recursive=True for non-empty folders

doc.save("D:/MyLib-edited/iTunes Library.itl")
```

Smart playlists can be added with their raw rule blobs (`smart_info=`, `smart_criteria=`, the same bytes as the XML `<data>` values); their rules are never re-encoded.

### Scan without writing

```python
from pytuneslib.scanner import scan

lib = scan("D:/Music", include_unsupported=False, kind_locale="en")
```

### Data model

All three types are plain dataclasses in `pytuneslib.model`.

**`Track`**

| Field | Type | Notes |
|---|---|---|
| `track_id` | `int` | Unique within the library. |
| `location` | `str` | Absolute file path. |
| `persistent_id` | `str` | 16 hex characters; random by default. |
| `name`, `artist`, `album_artist`, `album`, `composer`, `genre`, `kind`, `comments` | `str \| None` | Tags. `kind` is the display string, such as `MPEG audio file`. |
| `size` | `int` | Bytes. |
| `total_time` | `int` | Milliseconds. |
| `track_number`, `track_count`, `disc_number`, `disc_count`, `year`, `bpm` | `int \| None` | Tags. |
| `bit_rate` (kbps), `sample_rate` (Hz) | `int \| None` | Audio properties. |
| `date_modified`, `date_added` | `datetime` | UTC. |
| `play_count` | `int` | Default `0`. |
| `rating` | `int \| None` | 0–100. |
| `compilation` | `bool` | Default `False`. |
| `grouping`, `work` | `str \| None` | Tags. |
| `loved`, `disliked` | `bool` | Default `False`. |
| `play_date`, `skip_date`, `release_date` | `datetime \| None` | UTC. |
| `skip_count` | `int` | Default `0`. |
| `album_rating` | `int \| None` | 0–100. |
| `sort_name`, `sort_artist`, `sort_album`, `sort_album_artist`, `sort_composer` | `str \| None` | Sort keys. |

**`Playlist`**

| Field | Type | Notes |
|---|---|---|
| `playlist_id` | `int` | Unique within the library. |
| `name` | `str` | |
| `track_ids` | `list[int]` | IDs of the tracks in the playlist, in order. |
| `persistent_id` | `str` | Random by default. |
| `master` | `bool` | `True` for the "Library" playlist. |
| `distinguished_kind` | `int \| None` | For example `4` for the Music playlist. |
| `visible` | `bool` | `False` for hidden built-in playlists. Default `True`. |
| `folder` | `bool` | `True` for a playlist folder. Its `track_ids` are the union of its children. |
| `parent_persistent_id` | `str \| None` | Persistent ID of the containing folder, if any. |
| `smart_info`, `smart_criteria` | `bytes \| None` | Raw iTunes smart-playlist blobs, kept byte for byte. |

**`Library`**

| Field | Type | Notes |
|---|---|---|
| `tracks` | `list[Track]` | |
| `playlists` | `list[Playlist]` | |
| `persistent_id` | `str` | Library persistent ID. |
| `application_version` | `str` | Default `"12.13.11.1"`. |
| `music_folder` | `str \| None` | Absolute path of the iTunes Media folder. |
| `date` | `datetime` | UTC. |

## Opening the library in iTunes

1. Quit iTunes completely. Check Task Manager that `iTunes.exe` is no longer running.
2. Hold **Shift** while starting iTunes (tested on Windows). Keep holding until the dialog appears.
3. Click **Choose Library** and select the generated `iTunes Library.itl`.
4. iTunes opens the generated library. Its Music Folder is the one you chose at build time.

To go back to your own library, quit iTunes and repeat the steps, choosing your original `iTunes Library.itl`.

### Safety

- **Never point the output at your live library.** The tool refuses the default folder (`~/Music/iTunes`), but other folders can also hold your real library. Use a separate output folder.
- **Test on a copy first.** [`docs/VALIDATION.md`](docs/VALIDATION.md) has a step-by-step checklist, starting with copying your existing library folder as a backup.
- **Turn off iCloud Music Library and do not sign in** to Apple Music while testing a generated library.
- **Do not run "Organize library" or "Consolidate"** on a generated library, because they move files.
- **Use `--music-folder`** if your media is in a different place than the output folder. It sets where iTunes looks for the media.

## Supported formats

| Format | Read by pytuneslib | Written to library | Notes |
|---|---|---|---|
| MP3 | Yes | Yes | |
| AAC (M4A, M4B) | Yes | Yes | |
| ALAC (M4A) | Yes | Yes | |
| WAV | Yes | Yes | |
| AIFF | Yes | Yes | |
| FLAC, OGG, Opus, WMA | Only with `--include-unsupported` | Only with `--include-unsupported` | iTunes cannot play these. |

## Limitations

- **Not modeled:** artwork. The build command does not create smart playlists or folders from a music folder; they come from a library you read and rewrite (see [Edit an existing .itl in place](#edit-an-existing-itl-in-place)).
- **Built-in playlists:** the writers keep the built-in playlists (Movies, TV Shows, Podcasts, and so on) that the library already has.
- **Up Next queue:** not written. iTunes 12.13 rejects a library that includes this section.
- **Kind strings:** `Track.kind` uses the English or Spanish display string (`--kind-locale`). Other languages are not supported.
- **Tested only** with iTunes 12.13.11.1 on Windows (Microsoft Store build). Other versions and platforms are untested.
- **The `.itl` format is not documented by Apple.** It was reverse-engineered; see [`docs/FORMAT.md`](docs/FORMAT.md).

## How it works

The `.itl` file has a plain 0x90-byte header with the library's file length, persistent ID and track counts. The rest is a zlib-compressed stream, of which the first 100 KB are encrypted with AES-128-ECB. Inside, the library is stored as little-endian chunks (`msdh` sections containing `mith` tracks, `miph` playlists, `mhoh` string and data records). String records carry a per-type pool ID, and track records refer to albums and artists by ID. The Music Folder section is rewritten on write: iTunes moves tracks found under a different Music Folder into its own media folder when it opens a library, so the writer must set the folder that really contains the media. The full description is in [`docs/FORMAT.md`](docs/FORMAT.md).

## Development

### Tests

```bash
python -m pytest
```

Some tests generate a synthetic music library with [ffmpeg](https://ffmpeg.org/). The fixture looks for `ffmpeg` on your `PATH` first, then in `C:\Apps\Tools\ffmpeg\bin\`. If neither exists, those tests are skipped.

### Project layout

```
src/pytuneslib/
  builder.py       # build_library, write_library
  scanner.py       # music folder -> Library (mutagen)
  xml_writer.py    # Library -> XML
  xml_reader.py    # XML -> Library
  itl/             # .itl format: crypto, chunks, reader, writer
  model.py         # Track, Playlist, Library
  cli.py           # command line
tests/             # pytest suite
docs/              # FORMAT.md (format reference), VALIDATION.md (manual iTunes check)
```

## Contributing

Issues and pull requests are welcome. Before opening a pull request, run `python -m pytest` and keep changes focused on one thing. For format changes, include a test that reads and writes the affected records, and describe in the pull request how you checked it against iTunes.

## Disclaimer

pytuneslib is an independent project. It is **not affiliated with, endorsed by, or sponsored by Apple Inc.** iTunes and Apple are trademarks of Apple Inc. The `.itl` format is undocumented; the library is provided as is, and it may stop working with future iTunes versions. Use it on copies of your data, and keep backups of your iTunes library.

## License

MIT. See [`LICENSE`](LICENSE).
