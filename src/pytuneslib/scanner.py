"""Music folder -> Library, tags read with mutagen."""

from __future__ import annotations


import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import mutagen
from mutagen.mp4 import MP4

from .model import Library, Playlist, Track, new_persistent_id, utcnow

# extensions iTunes can play
SUPPORTED_EXTS = {".mp3", ".m4a", ".m4b", ".aac", ".wav", ".aif", ".aiff"}
# not supported by iTunes; only scanned with include_unsupported=True
UNSUPPORTED_EXTS = {".flac", ".ogg", ".opus", ".wma"}

KINDS_EN = {
    "mp3": "MPEG audio file",
    "aac": "AAC audio file",
    "alac": "Apple Lossless audio file",
    "wav": "WAV audio file",
    "aiff": "AIFF audio file",
    "m4p": "Protected AAC audio file",
    "flac": "FLAC audio file",
    "ogg": "Ogg Vorbis audio file",
}
# Spanish iTunes (as in the sample; note ALAC is unlocalized there)
KINDS_ES = {
    **KINDS_EN,
    "mp3": "Archivo de audio MPEG",
    "aac": "Archivo de audio AAC",
    "alac": "Audio Apple Lossless",
    "wav": "Archivo de audio WAV",
    "aiff": "Archivo de audio AIFF",
}
KIND_TABLES = {"en": KINDS_EN, "es": KINDS_ES}

# first track id iTunes-like libraries start around; any positive unique int works
FIRST_TRACK_ID = 1000
FIRST_PLAYLIST_ID = 5000


def _first(v):
    if isinstance(v, (list, tuple)):
        return v[0] if v else None
    return v


def _text(tags, *keys) -> str | None:
    if tags is None:
        return None
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        v = _first(v)
        if v is None:
            continue
        s = str(getattr(v, "text", [v])[0]) if hasattr(v, "text") else str(v)
        s = s.strip()
        if s:
            return s
    return None


def _pair(s: str | None) -> tuple[int | None, int | None]:
    """'3/12' -> (3, 12); '3' -> (3, None)."""
    if not s:
        return None, None
    m = re.match(r"\s*(\d+)\s*(?:/\s*(\d+))?", s)
    if not m:
        return None, None
    n = int(m.group(1)) or None
    c = int(m.group(2)) if m.group(2) else None
    return n, (c or None)


def _int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.match(r"\s*(\d+)", s)
    return int(m.group(1)) if m else None


def _year(s: str | None) -> int | None:
    if not s:
        return None
    m = re.match(r"\s*(\d{4})", s)
    return int(m.group(1)) if m else None


def _read_tags(path: Path, ext: str) -> dict:
    """Return a dict of normalised fields (empty on failure)."""
    out: dict = {}
    if ext in (".m4a", ".m4b", ".aac"):
        try:
            f = MP4(str(path))
        except Exception:
            f = None
        if f is not None:
            t = f.tags or {}
            tn = _first(t.get("trkn")) or (None, None)
            dn = _first(t.get("disk")) or (None, None)
            out.update(
                name=_text(t, "\xa9nam"),
                artist=_text(t, "\xa9ART"),
                album_artist=_text(t, "aART"),
                album=_text(t, "\xa9alb"),
                composer=_text(t, "\xa9wrt"),
                genre=_text(t, "\xa9gen"),
                comments=_text(t, "\xa9cmt"),
                year=_year(_text(t, "\xa9day")),
                bpm=_first(t.get("tmpo")),
                compilation=bool(_first(t.get("cpil"))),
                track_number=tn[0] or None,
                track_count=(tn[1] if len(tn) > 1 else None) or None,
                disc_number=dn[0] or None,
                disc_count=(dn[1] if len(dn) > 1 else None) or None,
            )
            out["_info"] = f.info
            out["_alac"] = getattr(f.info, "codec", "") == "alac"
            return out
    try:
        raw = mutagen.File(str(path))
    except Exception:
        raw = None
    if raw is None:
        return out
    t = raw.tags
    if t is not None and hasattr(t, "getall"):  # ID3 (mp3, wav, aiff)
        out.update(_read_id3(t))
    elif t is not None:  # Vorbis comments (flac, ogg)
        out.update(_read_vorbis(t))
    out["_info"] = raw.info
    return out


def _frame(t, key) -> str | None:
    fr = t.get(key)
    if fr is None or not getattr(fr, "text", None):
        return None
    return str(fr.text[0]).strip() or None


def _read_id3(t) -> dict:
    tn, tc = _pair(_frame(t, "TRCK"))
    dn, dc = _pair(_frame(t, "TPOS"))
    comments = None
    for fr in t.getall("COMM"):
        s = str(fr.text[0]).strip() if fr.text else ""
        if s:
            comments = s
            break
    if comments is None:  # ffmpeg writes -metadata comment=... as TXXX:comment
        for fr in t.getall("TXXX"):
            if fr.desc.lower() == "comment" and fr.text:
                comments = str(fr.text[0]).strip() or None
                break
    return dict(
        name=_frame(t, "TIT2"),
        artist=_frame(t, "TPE1"),
        album_artist=_frame(t, "TPE2"),
        album=_frame(t, "TALB"),
        composer=_frame(t, "TCOM"),
        genre=_frame(t, "TCON"),
        year=_year(_frame(t, "TDRC") or _frame(t, "TYER")),
        bpm=_int(_frame(t, "TBPM")),
        track_number=tn,
        track_count=tc,
        disc_number=dn,
        disc_count=dc,
        compilation=_frame(t, "TCMP") == "1",
        comments=comments,
    )


def _read_vorbis(t) -> dict:
    tn, tc = _pair(_text(t, "tracknumber"))
    dn, dc = _pair(_text(t, "discnumber"))
    return dict(
        name=_text(t, "title"),
        artist=_text(t, "artist"),
        album_artist=_text(t, "albumartist"),
        album=_text(t, "album"),
        composer=_text(t, "composer"),
        genre=_text(t, "genre"),
        year=_year(_text(t, "date", "originaldate")),
        bpm=_int(_text(t, "bpm")),
        track_number=tn,
        track_count=tc or _int(_text(t, "tracktotal", "totaltracks")),
        disc_number=dn,
        disc_count=dc or _int(_text(t, "disctotal", "totaldiscs")),
        compilation=_text(t, "compilation") == "1",
        comments=_text(t, "comment", "description"),
    )


def _kind(ext: str, alac: bool, table: dict) -> str:
    if ext == ".mp3":
        return table["mp3"]
    if ext in (".m4a", ".m4b", ".aac"):
        return table["alac"] if alac else table["aac"]
    if ext == ".wav":
        return table["wav"]
    if ext in (".aif", ".aiff"):
        return table["aiff"]
    if ext == ".flac":
        return table["flac"]
    if ext in (".ogg", ".opus"):
        return table["ogg"]
    return "Audio file"


def _bit_rate_kbps(info, size: int, seconds: float) -> int | None:
    br = getattr(info, "bitrate", None)
    if not br and seconds > 0:
        br = size * 8 / seconds
    return int(round(br / 1000)) if br else None


def scan_file(path: Path, track_id: int, *, kind_locale: str = "en") -> Track | None:
    ext = path.suffix.lower()
    tags = _read_tags(path, ext)
    info = tags.pop("_info", None)
    alac = tags.pop("_alac", False)
    if info is None:  # mutagen could not parse it
        return None
    st = path.stat()
    seconds = float(getattr(info, "length", 0) or 0)
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).replace(microsecond=0)
    ctime = datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).replace(microsecond=0)
    table = KIND_TABLES.get(kind_locale, KINDS_EN)
    # iTunes stores tag text NFC-normalized; do the same so XML and ITL match what it shows.
    tags = {k: unicodedata.normalize("NFC", v) if isinstance(v, str) else v
            for k, v in tags.items() if v not in (None, "", 0)}
    tags.setdefault("compilation", False)
    return Track(
        track_id=track_id,
        location=str(path),
        size=st.st_size,
        total_time=int(round(seconds * 1000)),
        bit_rate=_bit_rate_kbps(info, st.st_size, seconds),
        sample_rate=getattr(info, "sample_rate", None) or None,
        kind=_kind(ext, alac, table),
        date_modified=mtime,
        date_added=min(ctime, mtime),
        name=tags.pop("name", None) or unicodedata.normalize("NFC", path.stem),
        **tags,
    )


def scan(
    music_dir: str | Path,
    *,
    include_unsupported: bool = False,
    kind_locale: str = "en",
    music_folder: str | Path | None = None,
) -> Library:
    """Walk music_dir and build a Library with master 'Library' and 'Music' playlists.

    Files are visited in sorted path order so track IDs are deterministic.
    FLAC/OGG/... are skipped unless include_unsupported (iTunes can't play them).
    """
    root = Path(music_dir).resolve()
    exts = SUPPORTED_EXTS | (UNSUPPORTED_EXTS if include_unsupported else set())
    files = sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts),
        key=lambda p: str(p).lower(),
    )
    tracks: list[Track] = []
    tid = FIRST_TRACK_ID
    for p in files:
        t = scan_file(p, tid, kind_locale=kind_locale)
        if t is None:
            continue
        tracks.append(t)
        tid += 2  # iTunes allocates even ids in the sample
    ids = [t.track_id for t in tracks]
    playlists = [
        Playlist(FIRST_PLAYLIST_ID, "Library", list(ids), master=True),
        Playlist(FIRST_PLAYLIST_ID + 1, "Music", list(ids), distinguished_kind=4),
    ]
    return Library(
        tracks=tracks,
        playlists=playlists,
        music_folder=str(Path(music_folder).resolve() if music_folder else root),
        date=utcnow(),
    )
