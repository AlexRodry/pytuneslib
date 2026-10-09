import subprocess
from pathlib import Path

import pytest

from audio_fixture import FFMPEG
from music_fixtures import music_dir, music_expected  # noqa: F401  (shared session fixtures)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_XML = ROOT / "samples" / "iTunes Music Library.xml"


@pytest.fixture(scope="session")
def sample_xml() -> Path:
    if not SAMPLE_XML.exists():
        pytest.skip("samples/iTunes Music Library.xml not present")
    return SAMPLE_XML


@pytest.fixture(scope="session")
def ffmpeg() -> str:
    exe = str(FFMPEG) if FFMPEG else None
    if not exe:
        pytest.skip("ffmpeg not available")
    return exe


def make_audio(ffmpeg: str, out: Path, *, seconds: float = 1.0, codec_args=(), meta=None):
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
           f"sine=frequency=440:sample_rate=44100:duration={seconds}"]
    cmd += list(codec_args)
    for k, v in (meta or {}).items():
        cmd += ["-metadata", f"{k}={v}"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True)
    return out


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point Path.home() at an empty temp dir so no test can see or touch the real ~/Music."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PYTUNESLIB_ALLOW_LIVE", raising=False)
    return home
