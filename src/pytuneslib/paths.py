"""Path handling for track locations, shared by scanner, XML and ITL code.

``Track.location`` is the path *as iTunes sees it*: a Windows drive path (``C:\\Music\\a.mp3``),
a UNC path (``\\\\server\\share\\a.mp3``) or, for iTunes on macOS, a POSIX path. These helpers are
pure string functions on purpose. They never call ``os.path``/``pathlib`` on a location, so the
result is the same on Linux, macOS and Windows.

URL forms (``file://localhost`` + percent-encoded path), as iTunes writes them:

=====================  =========================================================
location               URL
=====================  =========================================================
``C:\\Music\\a b.mp3``   ``file://localhost/C:/Music/a%20b.mp3``  (seen in the sample)
``\\\\NAS\\music\\a.mp3``  ``file://localhost//NAS/music/a.mp3``  (not in the sample; this is
                       how iTunes writes network shares)
``/Users/x/a.mp3``      ``file://localhost/Users/x/a.mp3``
=====================  =========================================================
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import quote, unquote

# characters iTunes leaves unescaped in file URLs (everything else, incl. UTF-8 bytes, is %XX)
URL_SAFE = "/:!$&'()*+,;=@~"
FILE_URL_PREFIX = "file://localhost"

_DRIVE_RE = re.compile(r"^[A-Za-z]:([\\/]|$)")
_URL_DRIVE_RE = re.compile(r"^/[A-Za-z]:(/|$)")


def is_unc(path: str) -> bool:
    return path.startswith("\\\\")


def has_drive(path: str) -> bool:
    return bool(_DRIVE_RE.match(path))


def is_windows(path: str) -> bool:
    """True for ``C:\\...`` (either slash) and ``\\\\server\\share\\...`` paths."""
    return has_drive(path) or is_unc(path)


def normalize(path: str) -> str:
    """Canonical text form: Windows paths use backslashes, POSIX paths forward slashes.

    Mixed slashes are fixed, duplicate separators are collapsed (a UNC prefix keeps its two).
    """
    if not path:
        return path
    if has_drive(path):
        p = re.sub(r"[\\/]+", "\\\\", path)
        return p[0].upper() + p[1:] if len(p) > 1 else p
    if is_unc(path):
        return "\\\\" + re.sub(r"[\\/]+", "\\\\", path[2:])
    return re.sub(r"/{2,}", "/", path)


def parts(path: str) -> list[str]:
    """Path components without the root (drive or UNC server/share stay as the first part)."""
    p = normalize(path)
    if is_windows(p):
        return [x for x in p.lstrip("\\").split("\\") if x]
    return [x for x in p.split("/") if x]


def sep(path: str) -> str:
    return "\\" if is_windows(path) else "/"


def name(path: str) -> str:
    """Last component (file name)."""
    p = parts(path)
    return p[-1] if p else ""


def suffix(path: str) -> str:
    """Lowercase extension without the dot ('' when none)."""
    n = name(path)
    return n.rsplit(".", 1)[-1].lower() if "." in n.strip(".") else ""


def parent(path: str) -> str:
    p = normalize(path)
    s = sep(p)
    i = p.rfind(s)
    if i <= 0:
        return p[: i + 1] if i == 0 else ""
    if has_drive(p) and i == 2:  # C:\file -> C:\
        return p[:3]
    return p[:i]


def join(base: str, *more: str) -> str:
    """Join with the separator of base (Windows base -> backslashes)."""
    out = normalize(base)
    s = sep(out)
    for m in more:
        m = m.replace("\\", s).replace("/", s).strip(s)
        out = out.rstrip(s) + s + m if m else out
    return out


def _key(path: str) -> str:
    """Comparison key: forward slashes, no trailing slash, case-folded for Windows paths."""
    p = normalize(path)
    k = p.replace("\\", "/").rstrip("/") or "/"
    return k.lower() if is_windows(p) else k


def is_under(path: str, folder: str | None) -> bool:
    """True if path is inside folder (component-wise, case-insensitive for Windows paths)."""
    if not folder:
        return False
    a, b = _key(path), _key(folder)
    return a == b or a.startswith(b.rstrip("/") + "/")


def to_file_url(path: str) -> str:
    """Location -> ``file://localhost/...`` URL (no trailing-slash handling: kept as given)."""
    p = normalize(path)
    if has_drive(p):
        body = "/" + p.replace("\\", "/")
    elif is_unc(p):
        body = "//" + p[2:].replace("\\", "/")
    else:
        body = p if p.startswith("/") else "/" + p
    return FILE_URL_PREFIX + quote(body, safe=URL_SAFE)


def _strip_trailing(p: str) -> str:
    """Drop a trailing separator (folder URLs end in '/') except on roots (drive root, '/')."""
    if len(p) > 1 and p[-1] in "\\/" and not (len(p) == 3 and has_drive(p)):
        return p[:-1]
    return p


def from_file_url(url: str) -> str:
    return _strip_trailing(_from_file_url(url))


def _from_file_url(url: str) -> str:
    """``file://`` URL -> location (Windows paths come back with backslashes).

    Accepts file://localhost/C:/x, file:///C:/x, file://localhost//server/share/x,
    file://server/share/x (host form) and POSIX paths.
    """
    rest = url
    if url.lower().startswith("file://"):
        rest = url[len("file://"):]
        if rest.lower().startswith("localhost"):
            rest = rest[len("localhost"):]
        elif rest and not rest.startswith("/"):  # file://server/share/x
            rest = "//" + rest
    rest = unquote(rest)
    if _URL_DRIVE_RE.match(rest):
        return normalize(rest[1:])
    if rest.startswith("//") and not rest.startswith("///"):
        return normalize("\\\\" + rest[2:])
    if re.match(r"^/{3,}", rest):  # file:////server/share (empty host + UNC)
        return normalize("\\\\" + rest.lstrip("/"))
    return rest if rest.startswith("/") else "/" + rest


# --- mapping scanned filesystem paths onto what iTunes will see ------------------------------

def parse_path_map(items: list[str]) -> dict[str, str]:
    """['/mnt/nas/music=\\\\NAS\\music', ...] -> {src: dst}. Splits on the first '='."""
    out: dict[str, str] = {}
    for it in items:
        src, eq, dst = it.partition("=")
        if not eq or not src or not dst:
            raise ValueError(f"bad path map {it!r}; expected SRC=DST")
        if dst.startswith("\\") and not dst.startswith("\\\\"):
            raise ValueError(
                f"bad path map {it!r}: destination starts with a single backslash; a UNC path needs two "
                "(your shell may have eaten one: quote it or double the backslashes)"
            )
        out[src] = dst
    return out


def map_location(path: str, location_map: Mapping[str, str] | None = None) -> str:
    """Rewrite a scanned path into the location iTunes should use.

    ``location_map`` maps a source prefix (as seen by the scanning machine) to a destination
    prefix (as iTunes sees it), e.g. ``{"/mnt/nas/music": r"\\\\NAS\\music"}``. The longest matching
    source prefix wins, matching is by whole path component, and the remainder takes the
    destination's separator style. Without a match the path is only normalized.
    """
    p = normalize(path)
    if location_map:
        for src in sorted(location_map, key=lambda s: len(_key(s)), reverse=True):
            if is_under(p, src):
                tail = parts(p)[len(parts(src)):]
                dst = normalize(location_map[src])
                return join(dst, *tail) if tail else dst
    return p
