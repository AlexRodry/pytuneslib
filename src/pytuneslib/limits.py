"""Field limits enforced by iTunes, applied before writing so the XML and the .itl agree."""

from __future__ import annotations

from .model import Library

# iTunes 12.13 cuts tag text to 255 UTF-16 code units when it loads a library
# (verified: a 685-char Album Artist came back as its first 255 characters).
MAX_TEXT = 255
TEXT_FIELDS = ("name", "artist", "album_artist", "album", "composer", "genre", "kind", "comments")


def clamp_text(text: str | None, limit: int = MAX_TEXT) -> str | None:
    """Truncate to `limit` UTF-16 code units without splitting a surrogate pair."""
    if text is None or len(text) <= limit // 2:
        return text
    units = 0
    for i, ch in enumerate(text):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit:
            return text[:i]
    return text


def clamp_library(lib: Library) -> Library:
    """Clamp every track text field in place (paths are never touched). Returns lib."""
    for t in lib.tracks:
        for f in TEXT_FIELDS:
            v = getattr(t, f)
            if v is not None:
                setattr(t, f, clamp_text(v))
    return lib
