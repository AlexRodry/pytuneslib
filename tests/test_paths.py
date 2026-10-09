"""paths.py is pure string logic: these tests must behave identically on Linux and Windows."""
import pytest

from pytuneslib import paths as P

WIN = "C:\\Users\\Me\\Music\\iTunes\\iTunes Media\\Music\\Ti\u00ebsto\\Halfway There\\01 A&B [x].mp3"
UNC = "\\\\NAS\\music\\Artist\\Alb\\01 Song #1.mp3"


def test_classify():
    assert P.is_windows(WIN) and P.has_drive(WIN) and not P.is_unc(WIN)
    assert P.is_windows(UNC) and P.is_unc(UNC) and not P.has_drive(UNC)
    assert not P.is_windows("/mnt/nas/a.mp3")
    assert P.is_windows("c:/x/y.mp3")


def test_normalize():
    assert P.normalize("c:/Users//Me/a.mp3") == "C:\\Users\\Me\\a.mp3"
    assert P.normalize("\\\\NAS//music/a.mp3") == "\\\\NAS\\music\\a.mp3"
    assert P.normalize("/mnt//nas/a.mp3") == "/mnt/nas/a.mp3"


@pytest.mark.parametrize(
    "path,url",
    [
        (
            WIN,
            "file://localhost/C:/Users/Me/Music/iTunes/iTunes%20Media/Music/Ti%C3%ABsto/"
            "Halfway%20There/01%20A&B%20%5Bx%5D.mp3",
        ),
        (UNC, "file://localhost//NAS/music/Artist/Alb/01%20Song%20%231.mp3"),
        ("/Users/me/a b.mp3", "file://localhost/Users/me/a%20b.mp3"),
        ("C:\\", "file://localhost/C:/"),
    ],
)
def test_url_roundtrip(path, url):
    assert P.to_file_url(path) == url
    assert P.from_file_url(url) == P.normalize(path)


def test_from_url_variants():
    assert P.from_file_url("file:///C:/a%20b.mp3") == "C:\\a b.mp3"
    assert P.from_file_url("file://localhost/C:/a.mp3") == "C:\\a.mp3"
    assert P.from_file_url("file://localhost//srv/share/a.mp3") == "\\\\srv\\share\\a.mp3"
    assert P.from_file_url("file://srv/share/a.mp3") == "\\\\srv\\share\\a.mp3"
    assert P.from_file_url("file:////srv/share/a.mp3") == "\\\\srv\\share\\a.mp3"
    assert P.from_file_url("file://localhost/Users/x/a.mp3") == "/Users/x/a.mp3"


def test_name_suffix_parent_join():
    assert P.name(WIN) == "01 A&B [x].mp3" and P.suffix(WIN) == "mp3"
    assert P.suffix(UNC) == "mp3" and P.suffix("/a/b/.hidden") == "" and P.suffix("/a/b") == ""
    assert P.parent(UNC) == "\\\\NAS\\music\\Artist\\Alb"
    assert P.parent("C:\\a.mp3") == "C:\\"
    assert P.parent("/a/b.mp3") == "/a"
    assert P.join("C:\\Music", "A", "b.mp3") == "C:\\Music\\A\\b.mp3"
    assert P.join("\\\\NAS\\music", "A/B", "c.mp3") == "\\\\NAS\\music\\A\\B\\c.mp3"
    assert P.join("/mnt/x", "a") == "/mnt/x/a"


def test_is_under():
    assert P.is_under("C:\\Music\\A\\b.mp3", "c:/music/")
    assert not P.is_under("C:\\MusicX\\b.mp3", "C:\\Music")
    assert P.is_under(UNC, "\\\\nas\\MUSIC")
    assert P.is_under("/mnt/nas/a", "/mnt/nas") and not P.is_under("/mnt/Nas/a", "/mnt/nas")
    assert not P.is_under("C:\\a", None)


def test_map_location_posix_to_unc():
    m = {"/mnt/nas/music": "\\\\NAS\\music"}
    assert P.map_location("/mnt/nas/music/Artist/Alb/a.mp3", m) == "\\\\NAS\\music\\Artist\\Alb\\a.mp3"
    assert P.map_location("/mnt/nas/music", m) == "\\\\NAS\\music"
    assert P.map_location("/mnt/nas/music2/a.mp3", m) == "/mnt/nas/music2/a.mp3"  # whole components only


def test_map_location_to_drive_and_longest_prefix():
    m = {"/mnt/c": "C:\\", "/mnt/c/Users/Me/Music": "D:\\Music"}
    assert P.map_location("/mnt/c/Users/Me/Music/a.mp3", m) == "D:\\Music\\a.mp3"
    assert P.map_location("/mnt/c/Other/a.mp3", m) == "C:\\Other\\a.mp3"


def test_map_location_windows_source_and_identity():
    assert P.map_location("Z:\\Music\\a.mp3", {"z:/music": "\\\\NAS\\m"}) == "\\\\NAS\\m\\a.mp3"
    assert P.map_location("C:/a//b.mp3") == "C:\\a\\b.mp3"
    assert P.map_location("/mnt/x/a.mp3", {"/mnt/x": "/Volumes/x"}) == "/Volumes/x/a.mp3"


def test_parse_path_map():
    assert P.parse_path_map(["/mnt/nas=\\\\NAS\\m", "/a=C:\\b"]) == {"/mnt/nas": "\\\\NAS\\m", "/a": "C:\\b"}
    with pytest.raises(ValueError):
        P.parse_path_map(["nonsense"])
    with pytest.raises(ValueError, match="single backslash"):
        P.parse_path_map(["/mnt/nas=\\NAS\\music"])  # shell ate one backslash of the UNC prefix
