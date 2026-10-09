from pathlib import Path

import pytest

from pytuneslib.cli import main
from pytuneslib.xml_reader import read_xml


def test_build_xml_only(music_dir, tmp_path, capsys):
    out = tmp_path / "lib"
    assert main(["build", str(music_dir), str(out), "--no-itl"]) == 0
    lib = read_xml(out / "iTunes Music Library.xml")
    assert len(lib.tracks) == 18  # 19 fixtures minus unsupported flac
    assert "18 tracks" in capsys.readouterr().out


def test_refuses_real_library_folder(music_dir, fake_home):
    with pytest.raises(SystemExit):
        main(["build", str(music_dir), str(fake_home / "Music" / "iTunes"), "--no-itl"])


def test_missing_music_dir(tmp_path):
    with pytest.raises(SystemExit):
        main(["build", str(tmp_path / "nope"), str(tmp_path / "out"), "--no-itl"])


def test_music_folder_defaults_to_out_dir(music_dir, tmp_path):
    from pytuneslib.itl.reader import read_itl

    out = tmp_path / "lib"
    assert main(["build", str(music_dir), str(out)]) == 0
    expected = str((out / "iTunes Media").resolve()).rstrip("/\\")
    xml_lib = read_xml(out / "iTunes Music Library.xml")
    itl_lib = read_itl(out / "iTunes Library.itl")
    assert xml_lib.music_folder.rstrip("/\\") == expected
    assert itl_lib.music_folder.rstrip("/\\") == expected
    assert len(itl_lib.tracks) == 18


def test_explicit_music_folder_in_xml_and_itl(music_dir, tmp_path):
    from pytuneslib.itl.reader import read_itl

    out = tmp_path / "lib"
    media = tmp_path / "Media"
    assert main(["build", str(music_dir), str(out), "--music-folder", str(media)]) == 0
    expected = str(media.resolve()).rstrip("/\\")
    assert read_xml(out / "iTunes Music Library.xml").music_folder.rstrip("/\\") == expected
    assert read_itl(out / "iTunes Library.itl").music_folder.rstrip("/\\") == expected
