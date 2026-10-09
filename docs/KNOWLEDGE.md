# Shared knowledge base (pgMain / pgOpus / pgSonnet / pgHaiku)

Single source of truth. Append findings under your section. Keep it factual; cite sources/offsets.
Also mirrored into codebase-memory ADR (project = this repo) by pgMain.

## Goal
Python library `pytuneslib` (src/pytuneslib) that, from a music folder, generates:
1. `iTunes Library.itl` (binary, encrypted+compressed) that iTunes 12.13 opens.
2. `iTunes Music Library.xml` (plist) consistent with the .itl.
Plus pytest suite.

## Environment facts (pgMain, verified)
- iTunes 12.13.11.1 (Microsoft Store build, `%USERPROFILE%\AppData\Local\Microsoft\WindowsApps\iTunes.exe`). Currently RUNNING.
- Real library: `%USERPROFILE%\Music\iTunes\` — NEVER write there. Read-only copies in `samples/` (gitignored, personal data).
- Python 3.10, mutagen installed.
- Sample .itl header (big-endian):
  - 0x00 `hdfm`, 0x04 header len = 0x90, 0x08 file len = 0x0011db8d (=1170317, matches file size)
  - 0x10 pascal string: len 0x0a, "12.13.11.1"
  - 0x34..0x3B library persistent ID (8 bytes, matches XML `Library Persistent ID`)
  - payload starts at 0x90 (encrypted)
- Prior knowledge (to verify): payload AES-128-ECB key `BHUILuilfghuila3`; since iTunes ~10 only first N bytes encrypted (max crypt size field in header, commonly 102400), then zlib-compressed. Chunks: hdsm, htim (track), hohm (string/data), hpim (playlist), hptm (playlist item), hghm, halm/hiim (albums/artists), etc. Refs: titl (Java, Joe Walnes), ParseiTunesLibrary, libitunes, "itl" repos on GitHub.

## Module layout / contracts (pgMain)
```
src/pytuneslib/
  model.py      # dataclasses Track, Playlist, Library (shared contract — owned by pgMain)
  scanner.py    # folder -> Library via mutagen (pgSonnet)
  xml_writer.py # Library -> iTunes Music Library.xml (pgSonnet)
  xml_reader.py # xml -> Library (for tests / round trip) (pgSonnet)
  itl/crypto.py # decrypt/encrypt + zlib (pgOpus)
  itl/reader.py # .itl -> chunk tree + Library (pgOpus)
  itl/writer.py # Library -> .itl bytes (pgOpus)
  cli.py        # `python -m pytuneslib build <music_dir> <out_dir>` (pgMain)
tests/          # pytest, each owner writes tests for own modules
```

## Findings: ITL format (pgOpus)
All verified on the sample (iTunes 12.13.11.1 on Windows, 2101 tracks). Code: `src/pytuneslib/itl/`
(`crypto.py`, `chunks.py`, `reader.py`, `writer.py`, generated `_defaults.py` from `tools/gen_itl_defaults.py`).
Tests: `tests/test_itl_format.py`.

### File / crypto
- Outer header `hdfm`, **big-endian**, 0x90 bytes. Fields: 0x04 header len, 0x08 file len, 0x0C `00 43 00 01` (?),
  0x10 pascal string app version (32-byte field), 0x30 u32 =13 (?), 0x34 library PID (8 B), 0x3C u32 =111 (?),
  0x40 `02 02 00 01` (?), **0x44 track count, 0x48 playlist count (hpim in section 2), 0x4C album count,
  0x54 artist count**, 0x50 `00 38 01 00` (?), 0x58 u32 =100 (?), **0x5C max crypt size = 102400**,
  **0x64 tz offset seconds (7200)**, **0x70 library date (mac secs, local)**.
- Payload (after 0x90) = **zlib level 1** stream; first `min(len,102400) & ~15` bytes AES-128-ECB, key
  `BHUILuilfghuila3`; rest plain. `zlib.compress(level=1)` reproduces iTunes byte-for-byte →
  `encrypt_file(decrypt_file(sample)) == sample`. Dep: `cryptography`.
- Decompressed payload (6.29 MB) is **little-endian**, tags stored byte-reversed (`msdh` = hdsm).

### Chunk tree
- Every chunk: tag(4) + u32 header len + u32 "len-or-count". Payload = list of `hdsm` sections
  (hdr 96 B: +8 total len, +12 section type). Inside a section, `hohm` (data, advance by +8 total len) and
  `hptm` belong to the preceding owner chunk; other chunks advance by header len.
- +8 semantics: total len (hdr+children) for htim/haim/hiim/hpim/hqim/hpsm; count of following items for list
  headers halm/hilm/htlm/hplm/hslm/hrlm; hohm count for hghm; hohm = own total len. `chunks.serialize_payload`
  recomputes all of them; unmodified tree reserializes byte-identically.
- Sections in file order (type: content): 16 inner `hdfm` (LE copy of outer header; its +8 = uncompressed
  payload len + 0x90) · 12 `hghm` library settings (+hohm 500 hash, 503, 508 library name, 517) ·
  9 `halm`+`haim` albums · 11 `hilm`+`hiim` artists · 1 `htlm`+`htim` tracks · 13 empty `htlm` ·
  20 `hqlm`+`hqim` Up Next queue · 23 `hsts` · 2 `hplm`+`hpim`(+`hptm`) playlists · 14 Genius `hplm` ·
  21 `hslm`+`hpsm` podcast settings plist (hohm 800) · 4 **raw** body = Music Folder `file://` URL ·
  15 `hrlm`+`hrpm` (recent playlists refs).
- **IDs**: one shared counter: albums (67..), artists, tracks (**each track uses 2 ids: id and id+1** — htim
  +0x1F4 = track_id+1), playlists, playlist items. Scanner's tracks-step-2 matches this.

### hohm (data chunk), hdr 24
- +0x0C type, **+0x10 string-pool id** (see "String pools" below), +0x18 encoding,
  +0x1C byte len, +0x28 data. Encoding: **3 = Latin-1** (used when all chars ≤ U+00FF), **1 = UTF-16LE**
  otherwise, **2 = ASCII** (URLs). Multi-value tags separated by NUL (XML shows space).
- Track types: 2 name, 3 album, 4 artist, 5 genre, 6 kind, 8 comments, 11 location URL, 12 composer,
  13 Windows path (stale, may be old user dir), 14 grouping, 18 ?, 27 album artist, 30 sort name,
  31 sort album, 32 sort artist, 33 sort album artist, 34 sort composer, 46 ?, 63 work. Order in iTunes: 2,4,27,3,5,6,8,…,13,11. Album: 300 album, 301 album-artist-or-artist,
  302 album artist. Artist: 400 name, 401 sort. Playlist: 100 name (master = `####!####`, localized by iTunes),
  **101 = Smart Criteria, 102 = Smart Info** (payload from +0x18 to the end = the XML `<data>` blob
  byte-for-byte, verified on all 71), 103 (Podcasts only, 40 B), 105 ×2 + 108 view/column blobs (no ids),
  109 per-playlist view-state plist (`lastViewedPlaylist`...; optional, writer omits it).

### String pools (hohm +0x10) — verified on the sample, 0 violations
- Same string → same id, distinct strings → distinct ids, **case-sensitive, exact code points**. iTunes resolves
  the DISPLAYED artist/album through the pool: a clash shows another string (the lib_real bug: 1556 tracks).
- Shared pools: **artist** = 4 artist, 12 composer, 27 album artist, 301/302 haim artists, 400 hiim name ·
  **album** = 3, 300 · **sort-artist** = 32, 33, 401 · genre (5), kind (6), grouping (14) each own pool.
- Unique per occurrence (never shared): 2 name, 8 comments, 18, 30. Fixed in a fresh library: 13 path → 1,
  11 URL → 2. Playlist name (100) → 4, master → 0.
- iTunes stores tag text **NFC**-normalized and caps it at **255 UTF-16 units** (a 685-char album artist came
  back as its first 255). Scanner NFC-normalizes; `pytuneslib.limits.clamp_library` (builder) and the writer clamp.

### htim (track) header 756 B, LE — offsets verified 100% against XML
0x0C hohm count · 0x10 Track ID · 0x20 Date Modified · 0x24 Size · 0x28 Total Time ms · 0x2C Track Number ·
0x30 Track Count · 0x34 Year · 0x38 Bit Rate · 0x4C & 0x60 Play Count · 0x50 codec (12 mp3, 51 AAC, 60 ALAC,
70 AIFF/WAV) · 0x53 Compilation · 0x64 Play Date · 0x68 u16 Disc Number · 0x6A u16 Disc Count · 0x6C u8 Rating
(0–100, own rating only) · 0x78 Date Added · 0x80 Persistent ID (8 B reversed) · 0x8C file type 4cc reversed
(`MP3 `, `M4A `, `AIFF`, `WAV `) · 0x90 u16 Artwork Count · 0x98 f32 Sample Rate · 0xA4 u16 BPM · 0xD8 Skip Count ·
0xDC album id (→haim) · 0xF0 encoder delay · 0xF4 sample count · 0x100 encoder padding · 0x11C Skip Date ·
0x120 audio byte len · 0x128 =2 for lossless/PCM · 0x144 Size copy · 0x1E0 artist id (→hiim, keyed by album
artist or artist) · 0x1F4 track_id+1 · 0x290–0x2AB loudness/analysis data · **0xA0 Release Date (UTC mac
secs, NOT local)** · 0x2BF u8 love: 2 = Loved (15/15 vs XML), 3 = Disliked (inferred; not in the sample),
1 seen on 3 tracks with neither flag in the XML. Play Date 0x64 and Skip Date 0x11C are local like the others.
Album rating lives on haim: +0x28 value, +0x29 flags 0x01 user-set / 0x20 computed → model `album_rating` only
when 0x01 (mirrors track rating vs "Rating Computed"). All checked: 0 mismatches vs XML on 2101 tracks.
- **Dates**: mac seconds since 1904-01-01 in **local wall-clock time, DST-aware** (Sept dates +2h, Dec +1h on
  this machine) → convert via the system timezone, not the header tz offset.
- XML "Rating Computed" = album rating (haim +0x28) shown for unrated tracks; haim +0x29 flags 0x01 user /
  0x20 computed.

### haim / hiim / hpim / hptm
- haim (88): 0x0C hohm count, 0x10 album id, 0x14 album PID, 0x1C u8 2, 0x1D compilation, 0x20 PID of a
  member track, 0x28 album rating.
- hiim (100): 0x0C hohm count, 0x10 artist id, 0x14 PID.
- hpim (3500): 0x0C hohm count, 0x10 item count, 0x16 master flag, 0x1B8 PID, 0x20A folder flag,
  0x210 parent PID (8 B reversed, 0 = top level), 0x239 u8 Distinguished Kind, 0xD40 Playlist ID, 0x1C
  creation date. hdfm 0x48 = number of hpim (179 in the sample, hidden ones included).
- **Counts (ITL is the truth)**: sample and samples/live both have 179 hpim, 41 folders (+0x20A = 1),
  134 with a parent, 76 smart (hohm 101), 13 built-ins. The XML export has 174 / 41 / 134 / 71 / 8: it omits
  5 hidden built-in smart playlists (kinds 7, 26 Genius, 47, 48, 64), so reader sets `visible=False` for
  those kinds and for the master. The user-reported 42 / 146 / 72 could not be reproduced from either file.
- **A folder is a smart playlist** (found via iTunes probe: our flag-only folder lost its folder status on
  re-save). Every real folder (41/41) has +0x20A = 1 AND hohm 102/101: one shared Smart Info (112 B,
  `0101000300000002000000190000000000000007` + zeros) and Smart Criteria = `SLst` header (136 B, u32 BE rule
  count at +8, match-any) + one 124-byte rule per DIRECT child: field 0x28 "Playlist", op 1 "is", child pid at
  rule+0x38 and +0x50. Rule order is iTunes' (differs from hpim order in 20/41). `itl/folders.py` generates it
  (byte-identical for all 41 sample folders); the writer keeps an existing blob when it already lists exactly the
  children, ItlDocument refreshes the parent folders' rules on add/move/remove. Folders therefore also count as
  `smart` in the model (as in the XML, where all 41 folders have Smart Info/Criteria).
- Folders and smart playlists both carry their hptm item lists (folder = union of children, smart = cached
  result; 11 smart + 2 folders have none).
- hptm (84): 0x10 item id, 0x18 track id, 0x20 u16 ?, 0x44 8 random bytes (item PID?).

### Writer strategy
- Library → fresh chunk tree; unknown bytes from `_defaults.py` = per-byte mode over all sample records
  (bytes with <60% agreement zeroed → no ids/dates/names leak). Master and Music(kind 4, smart) playlists use
  their own header+blob templates. Genius/hrlm emitted empty; **hqlm (20, Up Next) omitted**;
  library name hohm 508 = "iTunes Library".
- Not modeled → written as 0: play date, skip count/date, artwork count, gapless info, loudness.
- Dates: hghm +0xB4 (library created) and hpim +0x1C (playlist created) = `lib.date`; every other
  date-looking u32 in the singleton templates (hghm +0x10/+0x14/+0xE0/+0xF4/+0xFC, hpim +0x274/+0xC70) is zeroed
  by `tools/gen_itl_defaults.py`, as are the master playlist's library totals (+0x20/+0x24) and the podcast
  plist `<date>` (→ 2001-01-01). A fresh iTunes library also has 0 at those hghm offsets.
- Playlists: every playlist is written. Header + view blobs come from per-kind templates captured by
  `tools/gen_itl_defaults.py`: master, each built-in kind in the sample (2,3,4,5,7,10,26,47,48,64–67, with
  iTunes' stock smart rules = the XML's for all of them), folder, smart, plain. Own `smart_info`/`smart_criteria`
  replace the template's rules; folder flag + parent pid set from the model. Dangling track ids dropped.
  Not yet probed in iTunes for a library containing folders/smart/built-ins written from scratch.
- **Edit mode** (`pytuneslib.itl.document.ItlDocument`): parses the chunk tree (re-serialising it is
  byte-identical for sample, live copy and oracle), edits only the touched hpim (name hohm, hptm list, parent
  pid; kept items keep their bytes), appends new hpim built like the writer's, recomputes lengths/counts and
  hdfm 0x48 in both headers. New ids = max over all ids in the file + 1. No edits ⇒ original bytes returned.
- `write_itl` refuses to write into `~/Music/iTunes` (override env `PYTUNESLIB_ALLOW_LIVE=1`).
- Verified: synthetic Library and full sample → itl_bytes → read_itl round-trip with 0 diffs.

### Validation against real iTunes 12.13.11.1 (2026-10-09, pgOpus)
Harness: `tools/itunes_probe.py CAND.itl ...` (closes iTunes, moves lab `*.itl` to `out/lab/backups/`, installs the
candidate in `out/validate/lib_fixture`, launches iTunes, "(Damaged)" rename ⇒ REJECTED, copies resulting itl+xml to
`out/lab/results/`). Variants: `tools/itl_variants.py` (oracle = itl iTunes made from the fixture XML).
- Crypto/zlib/chunk framing were fine (oracle re-encoded byte-identically, ACCEPTED).
- **Rejection cause: section 20 `hqlm` (Up Next).** Dropping only 20 ⇒ ACCEPTED; dropping only 21 or only 15 ⇒
  still REJECTED; restoring the "tslp" magic or using the sample's real hqlm header ⇒ still REJECTED. A fresh
  iTunes library has no section 20, so the writer omits it. Sections 21 (hslm) and 15 (hrlm) are accepted.
- **Location bug: Music Folder (section 4) must not be the scan root.** On open iTunes replaces the itl's Music
  Folder with the media folder from its settings (default `<library dir>/iTunes Media/`) and **remaps every track
  located under the old folder into the new one** (`<old>/A/B/x.m4a` → `<lib>/iTunes Media/A/B/x.m4a`, nonexistent).
  Tracks iTunes happens to re-analyze (gapless/`+0x5C`) get re-resolved from disk, so the symptom looked random
  (ALAC only, then all lossless, then all 7 once "analyzed" htim bytes were copied from the oracle).
  ⇒ `write_itl` writes `<itl dir>/iTunes Media` as Music Folder unless `music_folder=` is passed explicitly.
  Tracks outside the media folder are kept as absolute paths by iTunes (fine).
- hohm +0x10 is NOT an intern id for path/URL strings: iTunes writes 13→1, 11→2 in a fresh library, later bumps
  them (generation-like; sample has 13 odd / 11 even in groups of 50). Value does not affect location (tested).
- Result: fresh `scan(fixture_music)` → `write_itl` ⇒ ACCEPTED twice; iTunes' re-saved XML has all 7 Locations
  correct (Unicode/`&`/`#` paths included).
- iTunes on re-save sets htim +0x5C = ffffffff, zeroes +0x8C (file type) for mp3/AAC, fills gapless fields.

## Findings: XML format (pgSonnet)
Source: samples/iTunes Music Library.xml (iTunes 12.13.11.1, 2101 tracks, 160 playlists). Implemented in
`xml_writer.py`; test `test_track_dicts_byte_identical_to_sample` checks all modeled track keys byte-for-byte on all 2101 tracks.

**File framing**
- UTF-8, no BOM, **CRLF** line endings, file ends with `</plist>\r\n`. Indentation = tabs.
- Header: `<?xml version="1.0" encoding="UTF-8"?>`, DOCTYPE `-//Apple Computer//DTD PLIST 1.0//EN`, `<plist version="1.0">`.
- Strings use **numeric entities**: `&` -> `&#38;`, `<` -> `&#60;`, `>` -> `&#62;`. Quotes left raw. Never `&amp;`.
- Scalars are on one line with their key: `<key>Size</key><integer>7183671</integer>`. Bool: `<true/>`/`<false/>`.
- `<date>` = `YYYY-MM-DDTHH:MM:SSZ` (UTC, no fraction). `Play Date` is a raw integer (Mac epoch secs), `Play Date UTC` is a date.
- `<data>`: base64 wrapped at 72 chars/line, lines indented like `<data>` itself.
- Raw newlines inside string values are kept as-is (some are `\r\n`, some `\n`); XML parsers normalise `\r\n`->`\n`, so that is not recoverable via plistlib (harmless).

**Top-level key order**: Major Version(1), Minor Version(1), Application Version, Date, Features(5), Show Content Ratings(true),
Library Persistent ID, Tracks, Playlists, Music Folder (last, after Playlists).
`Tracks` is a dict keyed by the track id as string, in library order (ascending-ish ids, even numbers).

**Track dict key order** (omitted when absent; topological sort over all 2101 sample tracks, no conflicts; Disliked is a guess):
Track ID, Size, Total Time, Disc Number, Disc Count, Track Number, Track Count, Year, BPM, Date Modified, Date Added, Bit Rate,
Sample Rate, Volume Adjustment, Play Count, Play Date, Play Date UTC, Skip Count, Skip Date, Release Date, Rating,
Rating Computed, Album Rating, Album Rating Computed, Compilation, Loved, (Disliked), Artwork Count, Persistent ID, Explicit,
Track Type, Purchased, File Folder Count, Library Folder Count, Name, Artist, Album Artist, Composer, Album, Grouping, Genre,
Kind, Comments, Sort Name, Sort Album, Sort Artist, Sort Album Artist, Sort Composer, Work, Location.
- Numeric/date metadata first, then Persistent ID / Track Type, then folder counts, then strings, **Location last**.
- `Track Type` always `File` for local files. `File Folder Count`/`Library Folder Count` = `5`/`1` for files inside the iTunes Media
  folder, `-1`/`-1` otherwise (2 odd tracks in sample have -1 even inside media; writer uses 5/1 when under Music Folder).
- Booleans (`Compilation`, `Loved`, `Explicit`, ...) only present when true. `Play Count`/`Skip Count` only when > 0.
- `Play Date` is a raw integer: seconds since 1904-01-01 in **local time** (not UTC; sample is UTC+1/+2 with DST per date);
  `Play Date UTC` is the real instant. Writer derives the raw value from the system time zone (verified: 585/585 identical here,
  Europe/Madrid); reader prefers `Play Date UTC`. Test drops the raw value when the machine's tz differs from the sample's.
- `Rating Computed` / `Album Rating Computed` (true) mean the value is derived from the album, not set by the user. The reader
  returns `None` for such `rating`/`album_rating` (the ITL stores none), so those keys are not written back.
- `Kind` is **localized** to the iTunes UI language (sample is Spanish: `Archivo de audio MPEG`, `Archivo de audio AAC`,
  `Archivo de audio AIFF`, `Archivo de audio WAV`; ALAC is the unlocalized `Audio Apple Lossless`). English: `MPEG audio file`,
  `AAC audio file`, `Apple Lossless audio file`, `WAV audio file`, `AIFF audio file`. scanner has `kind_locale="en"|"es"`.
- `Location` = `file://localhost/C:/Users/...` forward slashes, drive letter + `:` unescaped, UTF-8 percent-encoded
  (`%C3%AB`), space `%20`, `[` `]` -> `%5B` `%5D`, `#` -> `%23`, and left raw: `! $ & ' ( ) * + , ; = @ ~ : /`.
  Then XML-escaped (`&` -> `&#38;`) on top. All path/URL logic lives in `pytuneslib/paths.py` (see "Paths" below).

**Playlists** (array of dicts). Merged key order over all 174 playlists of both samples (no conflicts):
`Master`, Playlist ID, `Parent Persistent ID`, Playlist Persistent ID, `Distinguished Kind`, `<kind flag>`, All Items, `Visible`,
`Folder`, Name, `Smart Info`, `Smart Criteria`, Playlist Items. Everything after `Tracks` (all playlists + Music Folder) is
byte-identical to the sample (`test_playlists_and_music_folder_byte_identical`, both `samples/` and `samples/live/`).
- Master ("Library"; name localized, e.g. `Biblioteca`): Master, Playlist ID, Playlist Persistent ID, All Items, `Visible`(false), Name,
  Playlist Items. Model: `master=True, visible=False` (`Visible` is written exactly when `visible` is False).
- `Distinguished Kind` + flag key: 2 `Movies`, 3 `TV Shows`, 4 `Music`, 5 `Audiobooks`, 10 `Podcasts`; 65, 66, 67 (the three
  "Downloaded" lists) have **no** flag. Other kinds (47, 48, 26, 64, 7 = Videoclips, Home Videos, Genius, ...) exist only in the ITL.
- Smart playlists: `Smart Info` (112 B) and `Smart Criteria` (384+ B) are `<data>` blobs kept byte for byte in
  `Playlist.smart_info/smart_criteria`. Music (kind 4) without blobs gets the sample's constants (`xml_writer.MUSIC_SMART_*`).
- Folders: `Folder`(true) after `All Items`; children point to them with `Parent Persistent ID` (before `Playlist Persistent ID`).
  A folder's `Playlist Items` is the union of its children's tracks. Folders may also carry Smart Info/Criteria.
- `Playlist Items` = array of `<dict><key>Track ID</key><integer>N</integer></dict>`; **omitted when empty** (also for the
  special lists Movies/TV/Podcasts/Audiobooks in the sample).
- `<data>` base64 lines have the **same indent as `<data>`** (3 tabs), 72 chars per line (an earlier note said one tab deeper: wrong).

**Not modeled (dropped on read, never written)**: Volume Adjustment, Rating Computed, Album Rating Computed, Artwork Count, Explicit,
Purchased, Track Type (always File), Features / Show Content Ratings (constants), Play Date raw (derived). Playlist sort/view
settings do not exist in the XML. `File Folder Count`/`Library Folder Count` are derived (5/1 or -1/-1).

**Paths** (`paths.py`, pure string functions, same result on Linux/macOS/Windows; never `os.path` on a location):
- `Track.location` is the path *as the iTunes that opens the library sees it*: `C:\Music\a.mp3`, UNC `\\NAS\music\a.mp3`, or a POSIX
  path for iTunes on macOS. Windows paths always use backslashes in the model.
- URLs: drive -> `file://localhost/C:/Music/a.mp3` (verified); UNC -> `file://localhost//NAS/music/a.mp3` (**not in the sample**,
  matches how iTunes writes network shares as far as known; verify against a real network track); POSIX -> `file://localhost/Users/x/a.mp3`.
  `from_file_url` also accepts `file:///C:/..`, `file://server/share/..`, `file:////server/share/..`.
- Scanning on one OS for iTunes on another: `scan(dir, location_map={"/mnt/nas/music": r"\\NAS\music"})` or CLI
  `--path-map SRC=DST` (repeatable). Longest source prefix wins, whole path components only, case-insensitive for Windows sources;
  the remainder takes the destination's separator style. `scan` uses `os.path.abspath`, not `resolve()` (keeps mapped drive letters).
  `--music-folder` accepts a Windows/UNC string even on Linux; the default `<out_dir>/iTunes Media` is mapped too.

**Scanner notes** (`scanner.scan(music_dir, include_unsupported=False, kind_locale="en", location_map=None)`): mp3/m4a/m4b/aac/wav/aif/aiff via mutagen;
flac/ogg/opus/wma skipped by default. ID3 read raw (EasyID3 can't see WAV/AIFF tags); `TXXX:comment` accepted as comment fallback
(ffmpeg writes that). Untagged -> Name = file stem. Ids start at 1000 step 2, playlists 5000/5001. Date Modified = mtime, Date Added = min(ctime, mtime).
The scanner does not read the new track fields (grouping, loved, plays, sort tags); only the XML/ITL readers do.
Install: pip 21.2 here, so `setup.py` shim + `setuptools<64` pin make `pip install -e .` work.

## Research: existing libs / docs (pgHaiku)
Repos cloned (depth 1, untrusted, not run): `research/repos/{titl,libitlp,itunesutilities}` (gitignored).

**Verified on sample (`samples/iTunes Library.itl`, decrypted by test script, not run from repo code):**
- Header: `hdfm` @0x00; hdr len 0x90; file len 0x11db8d; version pascal @0x10; pid @0x34 (8B).
- @0x41 enc flag = `02` (capped prefix); @0x43 zlib = `01`; @0x52 byte order = 0 (hdfm itself is BE; payload is LE, see RESOLVED below); @0x5C cap = `0x19000` (102400).
- Decrypt: AES-128-ECB, key `BHUILuilfghuila3`, no padding, first `min(body,cap)//16*16` bytes of body, rest clear. Then zlib inflate → 6,293,540 B; top-level msdh sections walk exactly to end. Works.
- Counts in header: tracks @0x44=0x835, playlists @0x48=0xb3, albums @0x4c=0x618, artists @0x54=0x4dd.
- Inflated tags are **msdh / mith / mhoh / miph / mtph / miah / miih / mhgh / mlth...** (NOT htim/hohm/hpim/hptm). Sample tallies: mith 2123, miph 181, miah 1560, miih 1245, mhoh ~25k, mtph ~12.5k.
- msdh: `+4` hdr len u32 LE (96), `+8` total len u32 LE, `+12` section type u32 LE (16 mfdh, 12 mhgh, 9 mlah, 11 mlih, 1 mlth, 2 mlph, 13, 20, 23 stsh, 4, 14, 15 mlrh, 21 mlsh).
- mhoh: `+4` hdr len (24), `+8` total len, `+12` type u32 LE. Body: `+24` encoding u32 LE, `+28` byte_len u32 LE, `+32..39` 8 unknown bytes, string from `+40`.
- mhoh types seen in sample (with verified encodings): **2 name (enc 3 Latin-1), 3 album (enc 3), 13 = Windows path `C:\...` (enc 3), 11 = `file://localhost/C:/...%20` URL (enc 2 = ASCII)**. Other types: 4 artist, 5 genre, 6 kind, 8 comment, 12 composer, 14, 18, 22, 27 album artist, 30–34 sort, 46, 59, 63, 100–109 (playlist/smart), 300–302, 400–402, 500–508, 517, 700–703, 800.
- **Conflict**: libitlp `types.h` says 0x0B = LOCAL_PATH; sample says 11 = URL, 13 = path. Trust sample.
- Encodings: enc 1 = UTF-16LE; enc 3 = each byte → code point (Latin-1), not UTF-8; enc 2 = ASCII (URLs); enc 0 unimplemented.

**Repo/doc notes (from fetch/search, not verified by run):**
- nmt3325/windows-itunes-itl-research `ITL_FORMAT_SPEC.md` (iTunes 12.13.10.3, Windows, Japanese notes): hdfm offsets table matches sample exactly (0x41 enc, 0x43 zlib, 0x5c cap 102400, 0x52 byte order: 0=BE, nonzero=LE; "library support is LE-only" — payload is LE). Dates HFS 1904 epoch, 0=unset. mith (track, hdr 756): +0x10 track_id, +0x6c rating 0–100, +0x80 persistent id 8B, +0xdc album_id, +0x1e0 artist_id, +0x78 date_added. miah hdr 88, miih hdr 100. miph hdr 3500 (+12 mhoh count, +16 mtph count, pid +0x1b8). mtph hdr 84 (+0x10 local item id, +0x18 track ref, +0x44 item pid). Mention of a "byte order" flag vs. the BE hdfm: sample hdfm is BE, payload byte order to verify.
- mrexodia blog (2014, "iTunes Library Format 1", github.com/mrexodia/mrexodia.github.io): v10 key/AES-ECB/NoPadding from `requiem`; header @0x5C = max encrypted size; decrypt from header_size, length `(file_len-hdr)&~0xF`. No v12 offsets given.
- libitlp `doc/a-primer-on-itl-format.md`: hdfm BE; zlib then AES128-ECB first 100kB; msdh root; mith/mhoh/miph/mtph. Says earlier parsers (titl, Mac::iTunes::Library::Parse) got block structure wrong. Key passed at build time in README (placeholder), so key not hardcoded there.
- titl (josephw, LGPL, Java): older tag names (hdsm/htim/hohm/hpim/hptm/hghm/halm/hilm/htlm/hplm/hiim/hslm/hpsm). Has hdfm 6.0.4 and 8.0 tests. Use for old-version ideas only; sample is 12.x.
- No public source found that **writes** .itl. Forum consensus: generate XML and let iTunes rebuild .itl (plist via plistlib). nmt3325 repo claims a Windows writer only for byte-exact same version.

**iTunes library swap / rebuild (community posts, not Apple docs):**
- Backups live in `iTunes\Previous iTunes Libraries\`. Restore = rename damaged `iTunes Library.itl`, copy good copy to `iTunes Library.itl`, relaunch. Beware hidden .itl extension (don't double it).
- Shift-launch at startup opens library chooser; pick the `.itl` manually (avoids swapping while running).
- Rebuild from XML: delete .itl, File > Library > Import Playlist (XML). Ratings/playlists may be lost if no XML.
- Sources: https://discussions.apple.com/docs/DOC-6561 · https://discussions.apple.com/thread/3812847 · https://kirkville.com/how-to-rebuild-your-itunes-library/ · https://www.technipages.com/itunes-the-file-itunes-library-itl-cannot-be-read-fix
- Not confirmed: sentinel file / which exact file iTunes checks first. Needs testing on a copy (never the real library).

**Links:** nmt3325 spec https://github.com/nmt3325/windows-itunes-itl-research · libitlp https://github.com/jeanthom/libitlp · titl https://github.com/josephw/titl · mrexodia https://mrexodia.github.io/reversing/2014/12/16/iTunes-Library-Format-1 · CPAN Mac::iTunes::Library::Parse https://metacpan.org/pod/Mac::iTunes::Library::Parse

**RESOLVED (payload endianness):** hdfm header is big-endian; decompressed payload numeric fields are little-endian (msdh +4/+8/+12, mhoh +12/+24/+28 all read correctly as LE, e.g. first section hdr len 96, type 16). Tag bytes are **plain ASCII on disk**, not byte-reversed: the first decompressed bytes are `msdh` and the sample has 13 top-level `msdh` sections and 0 `hdsm`. (A reading of the tags as LE u32 gives `hdsm`; that is a misreading, not the on-disk layout.) libitlp's "BE" claim is wrong for the payload. Confirmed by pgOpus' reader/writer round-trip (0 diffs). mith header 756 and HFS epoch are covered by pgOpus' htim table above.

**Summary for pgMain/pgOpus (5 lines):**
1. Sample verified: AES-ECB(key above) on first 102400 B of body, then zlib → msdh/mith/mhoh (iTunes 12 tags). Reader decrypt+inflate works.
2. Strings: mhoh type 2 name, 3 album, 13 Windows path, 11 file:// URL; enc 1 UTF-16LE, enc 3 Latin-1, enc 2 ASCII.
3. Repos cloned: titl (old tags, Java), libitlp (C, mith/mhoh primer), itunesutilities (xml, dormant). nmt3325 spec best for v12 offsets; no writer for .itl exists publicly.
4. RESOLVED: payload is LE numerics with ASCII tags; hdfm is BE (see "RESOLVED" above). Open: iTunes actually opening a generated .itl (manual test, docs/VALIDATION.md).
5. Swap/rebuild: Previous iTunes Libraries backups, Shift-launch chooser, XML import rebuild — test on a copy only.
