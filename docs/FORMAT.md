# iTunes `.itl` library format (reference notes)

These notes describe the binary `iTunes Library.itl` format as used by iTunes 12.13 on Windows. They were
derived by inspecting a reference library written by iTunes 12.13.11.1 and by round-tripping it. Apple does not
document this format, so treat every offset marked "?" as unknown and do not rely on it.

Byte order: the outer header is **big-endian**; everything after the header is **little-endian**.

## 1. Outer header (`hdfm`, 0x90 bytes, big-endian)

| Offset | Size | Meaning |
|---|---|---|
| 0x00 | 4 | Tag `hdfm` |
| 0x04 | 4 | Header length (`0x90`) |
| 0x08 | 4 | Total file length |
| 0x0C | 4 | `00 43 00 01` (unknown) |
| 0x10 | 1 + n | Pascal string: iTunes version (for example `12.13.11.1`) |
| 0x30 | 4 | `13` (unknown) |
| 0x34 | 8 | Library persistent ID |
| 0x3C | 4 | `111` (unknown) |
| 0x40 | 4 | `02 02 00 01` (unknown) |
| 0x44 | 4 | Track count |
| 0x48 | 4 | Playlist count |
| 0x4C | 4 | Album count |
| 0x50 | 4 | `00 38 01 00` (unknown) |
| 0x54 | 4 | Artist count |
| 0x58 | 4 | `100` (unknown) |
| 0x5C | 4 | Maximum encrypted size (`102400` in the reference library) |
| 0x64 | 4 | Time-zone offset in seconds at write time (7200 in the reference) |
| 0x70 | 4 | Library date (Mac seconds, local time) |

## 2. Payload: encryption and compression

The payload starts at byte 0x90.

1. **Compress:** the decrypted body is one zlib stream. The reference uses zlib level 1; `zlib.compress(data, 1)`
   reproduces iTunes' output byte for byte.
2. **Encrypt:** only the first `min(len, 102400) & ~15` bytes are encrypted, with **AES-128 in ECB mode, no padding**,
   key `BHUILuilfghuila3` (ASCII, 16 bytes). The rest of the stream is stored in clear.

Decryption is the reverse: decrypt the first `min(len, cap) & ~15` bytes, then inflate the result.

## 3. Chunk structure

After decompression the payload is a sequence of top-level **sections**. Every chunk starts with a 4-byte ASCII tag,
followed by a little-endian `u32` header length and a `u32` that is either the total length or a count, depending on
the chunk.

- Section header: 96 bytes. `+8` total length, `+12` section type.
- Common chunk types: `mhgh` (library settings), `mlah`/`miah` (albums), `mlih`/`miih` (artists),
  `mlth`/`mith` (tracks), `mlph`/`miph`/`mtph` (playlists and playlist items), `mhoh` (data strings), `mfdh`.
- `mhoh` (data) chunks follow their owner and are advanced by their total length, not their header length.
- Length fields are recomputed when a tree is serialized. A tree that is parsed and written back unchanged
  reproduces the original bytes.

### Section types in a reference library, in file order

| Type | Content |
|---|---|
| 16 | Inner `hdfm` copy (little-endian); its `+8` is the uncompressed payload length plus 0x90 |
| 12 | Library settings (`mhgh`) |
| 9 | Albums (`mlah` + `miah`) |
| 11 | Artists (`mlih` + `miih`) |
| 1 | Tracks (`mlth` + `mith`) |
| 13 | Empty track-list header |
| 20 | Up Next queue (`mlqh` + `miqh`). **Rejected by iTunes 12.13 when present; omit it.** |
| 23 | Stats (`stsh`) |
| 2 | Playlists (`mlph` + `miph`, with `mtph` items) |
| 14 | Genius playlist list (empty) |
| 21 | Podcast settings (`mlsh` + `mpsh`, a plist in an `mhoh`) |
| 4 | Music Folder: a raw `file://` URL body |
| 15 | Recently-used playlist references (`mlrh`) |

### Identifiers

Albums, artists, tracks, playlists and playlist items draw from one shared counter. Each track uses two
consecutive values: the track ID `n` and `n + 1` (stored at `+0x1F4` of the track record). Playlist items refer to
tracks by ID.

## 4. String objects (`mhoh`)

Header 24 bytes. Body fields:

| Offset | Meaning |
|---|---|
| `+0x0C` | Type code (see below) |
| `+0x10` | String-pool ID (per owner and type, numbered from 1 for distinct strings). Not a stable identifier for paths; see §6. |
| `+0x18` | Encoding: `3` = Latin-1 (every character ≤ U+00FF), `1` = UTF-16LE, `2` = ASCII (used for URLs) |
| `+0x1C` | Byte length |
| `+0x28` | Data |

Multiple values in one field are separated by NUL bytes.

### Track type codes

| Code | Field |
|---|---|
| 2 | Name |
| 3 | Album |
| 4 | Artist |
| 5 | Genre |
| 6 | Kind |
| 8 | Comments |
| 11 | Location (`file://localhost/...` URL, ASCII) |
| 12 | Composer |
| 13 | Windows path (may be stale) |
| 27 | Album artist |
| 30–34 | Sort fields |

Other codes seen in the reference (meaning not established): 14, 18, 46, 63.

Album records use 300 (album), 301 (album artist or artist), 302 (album artist). Artist records use 400 (name) and
401 (sort name). Playlist records use 100 (name), 101 (Smart Criteria) and 102 (Smart Info), 105/108 (view blobs)
and 109 (plist). The smart blobs start at `+0x18` of the chunk, not at the string offset `+0x28`; compared
byte for byte against the XML export, all 71 smart playlists of the reference library match.

### Dates

Dates are Mac seconds since 1904-01-01, written as **local wall-clock time** with daylight-saving time applied. Convert
them with the system time zone rather than the header's offset field. `0` means unset.

## 5. Track record (`mith`, 756 bytes, little-endian)

Offsets verified against the XML export of the reference library.

| Offset | Field |
|---|---|
| 0x0C | Number of `mhoh` children |
| 0x10 | Track ID |
| 0x20 | Date modified |
| 0x24 | File size |
| 0x28 | Total time (ms) |
| 0x2C | Track number |
| 0x30 | Track count |
| 0x34 | Year |
| 0x38 | Bit rate |
| 0x4C, 0x60 | Play count |
| 0x50 | Codec: `12` MP3, `51` AAC, `60` ALAC, `70` AIFF/WAV |
| 0x53 | Compilation flag |
| 0x64 | Play date |
| 0x68, 0x6A | Disc number, disc count (`u16`) |
| 0x6C | Rating (0–100, `u8`) |
| 0x78 | Date added |
| 0x80 | Persistent ID (8 bytes, reversed) |
| 0x8C | File type code, reversed (`MP3 `, `M4A `, `AIFF`, `WAV `) |
| 0x90 | Artwork count (`u16`) |
| 0x98 | Sample rate (`f32`) |
| 0xA4 | BPM (`u16`) |
| 0xD8 | Skip count |
| 0xDC | Album ID |
| 0x120 | Audio byte length |
| 0x128 | `2` for lossless and PCM |
| 0x1E0 | Artist ID (album artist, or artist when there is none) |
| 0x1F4 | Track ID + 1 |

Fields iTunes fills in when it re-saves a library (gapless values, file-type fields and analysis data) are not needed
to create a valid file.

## 6. Other record types

- **Album** (`miah`, 88 bytes): album ID at `+0x10`, persistent ID at `+0x14`, compilation flag at `+0x1D`, rating at `+0x28`.
- **Artist** (`miih`, 100 bytes): artist ID at `+0x10`, persistent ID at `+0x14`.
- **Playlist** (`miph`, 3500 bytes): item count at `+0x10`, master flag at `+0x16`, persistent ID at `+0x1B8`,
  folder flag at `+0x20A`, parent persistent ID at `+0x210`, distinguished kind at `+0x239`, playlist ID at `+0xD40`.
- **Playlist item** (`mtph`, 84 bytes): item ID at `+0x10`, track ID at `+0x18`.

### Locations and the Music Folder

The Music Folder section (4) defines where iTunes looks for media. When iTunes opens a library, it replaces that
folder with its own media folder setting (by default `iTunes Media` next to the library file) and moves every track
located under the old folder into the new one. A writer must therefore set the Music Folder to the folder that actually
contains the media, or tracks will be re-mapped to paths that do not exist. Tracks outside the Music Folder keep their
absolute `file://` locations.

## 7. Validation

- Generating `.itl` from a library and reading it back gives identical data on a reference library.
- A library generated this way was accepted by iTunes 12.13.11.1 on Windows, and iTunes' own re-saved XML export had
  correct locations for ASCII, Unicode, `&` and `#` paths.
- The Up Next section (20) must be omitted; iTunes rejected the file when it was present.
- iTunes rewrites some fields on re-save (for example `+0x5C` and the file-type code of MP3/AAC tracks), so tests
  should compare parsed data, not bytes after a round trip through iTunes.
