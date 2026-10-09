"""Generate a small synthetic music library for tests.

Audio comes from ffmpeg (PATH, else C:/Apps/Tools; sine tones).
Tags are written and read with mutagen. ``TRACKS`` is the single source of
truth; ``EXPECTED`` is derived from it.
"""

import shutil
import subprocess
from pathlib import Path

import mutagen
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.id3 import COMM, TALB, TBPM, TCMP, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

_FALLBACK_FFMPEG = Path(r"C:\Apps\Tools\ffmpeg\bin\ffmpeg.exe")


def find_ffmpeg() -> Path | None:
    """ffmpeg on PATH, else the local C:/Apps/Tools build; None when unavailable."""
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    return _FALLBACK_FFMPEG if _FALLBACK_FFMPEG.is_file() else None


FFMPEG = find_ffmpeg()

# Keys that describe tags; EXPECTED entries carry these (None when untagged).
TAG_KEYS = (
    "title",
    "artist",
    "album_artist",
    "album",
    "genre",
    "year",
    "track_number",
    "track_total",
    "disc_number",
    "disc_total",
    "bpm",
    "compilation",
    "comment",
)

# ffmpeg output args per format. Staging name is ASCII; the real name is set afterwards.
_CODECS = {
    "mp3_192": ["-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3"],
    "mp3_320": ["-c:a", "libmp3lame", "-b:a", "320k", "-f", "mp3"],
    "aac": ["-c:a", "aac", "-b:a", "256k", "-f", "ipod"],
    "alac": ["-c:a", "alac", "-f", "ipod"],
    "wav": ["-c:a", "pcm_s16le", "-f", "wav"],
    "aiff": ["-c:a", "pcm_s16be", "-f", "aiff"],
    "flac": ["-c:a", "flac", "-f", "flac"],
}


# Default for album_artist: "same as artist". Pass None explicitly to leave the tag out.
_SAME = object()


def _tags(title, track, *, album="Album B", artist="Artist A", album_artist=_SAME,
          genre="Test Genre", year=2016, track_total=12, disc=(1, 2), bpm=95,
          compilation=False, comment="fixture comment"):
    return {
        "title": title,
        "artist": artist,
        "album_artist": artist if album_artist is _SAME else album_artist,
        "album": album,
        "genre": genre,
        "year": year,
        "track_number": track,
        "track_total": track_total,
        "disc_number": disc[0],
        "disc_total": disc[1],
        "bpm": bpm,
        "compilation": compilation,
        "comment": comment,
    }


# (relative path, format key, bitrate kbps for mp3 or None, tags or None)
TRACKS = [
    ("Beyoncé/Lemonade/Ñandú.mp3", "mp3_192", 192,
     _tags("Ñandú", 1, album="Lemonade", artist="Beyoncé", bpm=95)),
    ("Beyoncé/Lemonade/02 Intro.mp3", "mp3_320", 320,
     _tags("Intro", 2, album="Lemonade", artist="Beyoncé", bpm=120, year=2016)),
    ("Artist A/Album B/03 Song AAC.m4a", "aac", None,
     _tags("Song AAC", 3, compilation=True, comment="aac comment")),
    ("Artist A/Album B/04 Song ALAC.m4a", "alac", None,
     _tags("Song ALAC", 4, genre="Lossless", disc=(2, 2), bpm=70)),
    ("Various Artists/Mix Tape/05 Wav Track.wav", "wav", None,
     _tags("Wav Track", 5, album="Mix Tape", artist="Various Artists",
           album_artist="Various Artists", compilation=False, year=1999)),
    ("Various Artists/Mix Tape/06 Aiff Track.aiff", "aiff", None,
     _tags("Aiff Track", 6, album="Mix Tape", artist="Various Artists",
           album_artist="Various Artists", year=2001)),
    ("Rock & Roll #2/Live Set/07 Flac Track.flac", "flac", None,
     _tags("Flac Track", 7, album="Live Set", artist="Rock & Roll #2",
           genre="Rock", year=2020)),
    ("Rock & Roll #2/Live Set/08 No Tags.mp3", "mp3_320", 320, None),
    # --- artist / album-artist cases (added for the ITL writer check) ---
    # Two albums by the same album artist; track artists differ.
    ("DJ Host/Mix One/01 Opening.mp3", "mp3_192", 192,
     _tags("Opening", 1, album="Mix One", artist="DJ Host, Guest One", album_artist="DJ Host",
           genre="Electronic", year=2021, track_total=2)),
    ("DJ Host/Mix One/02 Closing.mp3", "mp3_192", 192,
     _tags("Closing", 2, album="Mix One", artist="Guest Two;Guest Three", album_artist="DJ Host",
           genre="Electronic", year=2021, track_total=2)),
    ("DJ Host/Mix Two/01 Set.mp3", "mp3_192", 192,
     _tags("Set", 1, album="Mix Two", artist="DJ Host", album_artist="DJ Host",
           genre="Electronic", year=2022, track_total=2)),
    ("DJ Host/Mix Two/02 Encore.mp3", "mp3_192", 192,
     _tags("Encore", 2, album="Mix Two", artist="Guest One", album_artist="DJ Host",
           genre="Electronic", year=2022, track_total=2)),
    # Artist set, album artist absent.
    ("Solo Artist/Single/01 No Album Artist.mp3", "mp3_192", 192,
     _tags("No Album Artist", 1, album="Single", artist="Solo Artist", album_artist=None,
           track_total=1)),
    # Album artist set, artist absent.
    ("Label/Only Album Artist/01 No Artist.mp3", "mp3_192", 192,
     _tags("No Artist", 1, album="Only Album Artist", artist=None, album_artist="Label Owner",
           track_total=1)),
    # Compilation album: three different track artists, album artist "Various Artists".
    ("Various Artists/Hits 2020/01 Hit One.mp3", "mp3_192", 192,
     _tags("Hit One", 1, album="Hits 2020", artist="Artist Alpha", album_artist="Various Artists",
           compilation=True, year=2020, track_total=3)),
    ("Various Artists/Hits 2020/02 Hit Two.mp3", "mp3_192", 192,
     _tags("Hit Two", 2, album="Hits 2020", artist="Artist Beta", album_artist="Various Artists",
           compilation=True, year=2020, track_total=3)),
    ("Various Artists/Hits 2020/03 Hit Three.mp3", "mp3_192", 192,
     _tags("Hit Three", 3, album="Hits 2020", artist="Artist Gamma", album_artist="Various Artists",
           compilation=True, year=2020, track_total=3)),
    # Same title in NFC and NFD (decomposed e + combining diaeresis). Titles differ in code points.
    ("Tiësto/Remixes/01 NFC.mp3", "mp3_192", 192,
     _tags("Tiësto Remix", 1, album="Remixes", artist="Tiësto", track_total=2)),
    ("Tiësto/Remixes/02 NFD.mp3", "mp3_192", 192,
     _tags("Tiësto Remix", 2, album="Remixes", artist="Tiësto", track_total=2)),
]


def _run_ffmpeg(fmt, staging_file):
    cmd = [
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.0:sample_rate=44100",
        "-ac", "2", "-fflags", "+bitexact", "-map_metadata", "-1",
        *_CODECS[fmt], str(staging_file),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _write_id3(tags, t):
    tags.add(TIT2(encoding=3, text=[t["title"]]))
    if t["artist"] is not None:
        tags.add(TPE1(encoding=3, text=[t["artist"]]))
    if t["album_artist"] is not None:
        tags.add(TPE2(encoding=3, text=[t["album_artist"]]))
    tags.add(TALB(encoding=3, text=[t["album"]]))
    tags.add(TCON(encoding=3, text=[t["genre"]]))
    tags.add(TDRC(encoding=3, text=[str(t["year"])]))
    tags.add(TRCK(encoding=3, text=[f"{t['track_number']}/{t['track_total']}"]))
    tags.add(TPOS(encoding=3, text=[f"{t['disc_number']}/{t['disc_total']}"]))
    tags.add(TBPM(encoding=3, text=[str(t["bpm"])]))
    tags.add(TCMP(encoding=3, text=["1" if t["compilation"] else "0"]))
    tags.add(COMM(encoding=3, lang="eng", desc="", text=[t["comment"]]))


def _write_mp4(f, t):
    f["\xa9nam"] = [t["title"]]
    if t["artist"] is not None:
        f["\xa9ART"] = [t["artist"]]
    if t["album_artist"] is not None:
        f["aART"] = [t["album_artist"]]
    f["\xa9alb"] = [t["album"]]
    f["\xa9gen"] = [t["genre"]]
    f["\xa9day"] = [str(t["year"])]
    f["trkn"] = [(t["track_number"], t["track_total"])]
    f["disk"] = [(t["disc_number"], t["disc_total"])]
    f["tmpo"] = [t["bpm"]]
    f["cpil"] = bool(t["compilation"])
    f["\xa9cmt"] = [t["comment"]]


def _write_flac(f, t):
    f["title"] = t["title"]
    if t["artist"] is not None:
        f["artist"] = t["artist"]
    if t["album_artist"] is not None:
        f["albumartist"] = t["album_artist"]
    f["album"] = t["album"]
    f["genre"] = t["genre"]
    f["date"] = str(t["year"])
    f["tracknumber"] = f"{t['track_number']}/{t['track_total']}"
    f["discnumber"] = f"{t['disc_number']}/{t['disc_total']}"
    f["bpm"] = str(t["bpm"])
    f["compilation"] = "1" if t["compilation"] else "0"
    f["comment"] = t["comment"]


def _fresh(cls, path):
    """Open ``path`` with ``cls``, dropping any existing tags first.

    mutagen's ``delete()`` does not clear the in-memory object, so reopen after it.
    """
    f = cls(path)
    if f.tags is not None:
        f.delete()
        f = cls(path)
    return f


def write_tags(path, fmt, t):
    """Write tags from dict ``t`` into ``path`` using the container's native tag type.

    ffmpeg may already have written a tag header, so existing tags are removed first.
    """
    if fmt.startswith("mp3"):
        f = _fresh(MP3, path)
        if f.tags is None:
            f.add_tags()
        _write_id3(f.tags, t)
        f.save(v2_version=3)
    elif fmt in ("wav", "aiff"):
        f = _fresh(WAVE if fmt == "wav" else AIFF, path)
        if f.tags is None:
            f.add_tags()
        _write_id3(f.tags, t)
        f.save(v2_version=3)
    elif fmt in ("aac", "alac"):
        f = _fresh(MP4, path)
        if f.tags is None:
            f.add_tags()
        _write_mp4(f, t)
        f.save()
    elif fmt == "flac":
        f = FLAC(path)
        _write_flac(f, t)
        f.save()
    else:
        raise ValueError(fmt)


def _read_id3(tags):
    def text(frame):
        return str(frame.text[0]) if frame is not None and frame.text else None

    def num(frame):
        return int(frame.text[0]) if frame is not None and frame.text else None

    def pair(frame):
        if frame is None or not frame.text:
            return None, None
        n, _, total = str(frame.text[0]).partition("/")
        return int(n), (int(total) if total else None)

    comm = tags.get("COMM::eng")
    trck = pair(tags.get("TRCK"))
    tpos = pair(tags.get("TPOS"))
    tdrc = tags.get("TDRC")
    return {
        "title": text(tags.get("TIT2")),
        "artist": text(tags.get("TPE1")),
        "album_artist": text(tags.get("TPE2")),
        "album": text(tags.get("TALB")),
        "genre": text(tags.get("TCON")),
        "year": int(str(tdrc.text[0])[:4]) if tdrc is not None and tdrc.text else None,
        "track_number": trck[0],
        "track_total": trck[1],
        "disc_number": tpos[0],
        "disc_total": tpos[1],
        "bpm": num(tags.get("TBPM")),
        "compilation": (text(tags.get("TCMP")) == "1") if tags.get("TCMP") is not None else None,
        "comment": str(comm.text[0]) if comm is not None and comm.text else None,
    }


def _read_mp4(f):
    def first(key):
        v = f.get(key)
        return v[0] if v else None

    trkn = first("trkn") or (None, None)
    disk = first("disk") or (None, None)
    day = first("\xa9day")
    return {
        "title": first("\xa9nam"),
        "artist": first("\xa9ART"),
        "album_artist": first("aART"),
        "album": first("\xa9alb"),
        "genre": first("\xa9gen"),
        "year": int(str(day)[:4]) if day else None,
        "track_number": trkn[0],
        "track_total": trkn[1],
        "disc_number": disk[0],
        "disc_total": disk[1],
        "bpm": first("tmpo"),
        "compilation": bool(f["cpil"]) if "cpil" in f else None,
        "comment": first("\xa9cmt"),
    }


def _read_flac(f):
    def first(key):
        v = f.get(key)
        return v[0] if v else None

    def pair(key):
        n, _, total = (first(key) or "").partition("/")
        return (int(n) if n else None), (int(total) if total else None)

    trck = pair("tracknumber")
    disc = pair("discnumber")
    date = first("date")
    return {
        "title": first("title"),
        "artist": first("artist"),
        "album_artist": first("albumartist"),
        "album": first("album"),
        "genre": first("genre"),
        "year": int(date[:4]) if date else None,
        "track_number": trck[0],
        "track_total": trck[1],
        "disc_number": disc[0],
        "disc_total": disc[1],
        "bpm": int(first("bpm")) if first("bpm") else None,
        "compilation": first("compilation") == "1" if first("compilation") is not None else None,
        "comment": first("comment"),
    }


def read_tags(path):
    """Read the normalized tag dict (TAG_KEYS only) from any supported file."""
    empty = dict.fromkeys(TAG_KEYS)
    f = mutagen.File(path)
    if f is None or f.tags is None:
        return empty
    if isinstance(f, MP3) or isinstance(f.tags, mutagen.id3.ID3):
        return _read_id3(f.tags)
    if isinstance(f, MP4):
        return _read_mp4(f.tags)
    if isinstance(f, FLAC):
        return _read_flac(f)
    return empty


def _build_expected():
    expected = {}
    for rel, fmt, bitrate, tags in TRACKS:
        entry = {
            "format": fmt.split("_")[0],
            "itunes_supported": fmt != "flac",
            "has_tags": tags is not None,
            "bitrate_kbps": bitrate,
        }
        entry.update(tags if tags is not None else dict.fromkeys(TAG_KEYS))
        expected[rel] = entry
    return expected


EXPECTED = _build_expected()


def build_library(root):
    """Create the library under ``root``. Returns ``root``."""
    root = Path(root)
    staging = root / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for i, (rel, fmt, _bitrate, tags) in enumerate(TRACKS):
            ext = Path(rel).suffix
            stage = staging / f"stage_{i:02d}{ext}"
            _run_ffmpeg(fmt, stage)
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stage), str(dest))
            if tags is None:
                # ffmpeg may still leave container-level tags; strip them so the file truly has none.
                m = mutagen.File(dest)
                if m is not None and m.tags is not None:
                    m.delete()
            else:
                write_tags(dest, fmt, tags)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return root
