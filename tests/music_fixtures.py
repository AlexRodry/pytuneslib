"""Session fixtures for the synthetic music library.

Not in conftest.py on purpose: conftest is shared. Import the fixtures where needed::

    from music_fixtures import music_dir, music_expected  # noqa: F401
"""

import pytest

from audio_fixture import EXPECTED, FFMPEG, build_library


@pytest.fixture(scope="session")
def music_dir(tmp_path_factory):
    """Synthetic music library (8 tracks, nested folders, one FLAC). Session-scoped.

    Skipped when ffmpeg is missing. Expectations: ``music_expected`` / ``EXPECTED``.
    """
    if FFMPEG is None:
        pytest.skip(r"ffmpeg not available (PATH or C:\Apps\Tools)")
    return build_library(tmp_path_factory.mktemp("music"))


@pytest.fixture(scope="session")
def music_expected():
    """Relative posix path -> expected tag values and flags (same dict as ``EXPECTED``)."""
    return EXPECTED
