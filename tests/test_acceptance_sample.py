"""Acceptance: reading and rewriting a reference library loses nothing.

Runs the checks from tools/verify_roundtrip.py on each reference library:
  - samples/                 (snapshot used for development)
  - samples/live/           (read-only copy of the user's live library)
A library whose files are absent is skipped. Built-in special playlists count as losses.

Run alone with:

    python -m pytest tests/test_acceptance_sample.py
    python -m pytest -m acceptance
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("verify_roundtrip", ROOT / "tools" / "verify_roundtrip.py")
verify = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = verify  # dataclasses looks the module up by name while it executes
_spec.loader.exec_module(verify)

LIBRARIES = {
    "samples": ROOT / "samples",
    "samples-live": ROOT / "samples" / "live",
}

pytestmark = pytest.mark.acceptance


def _params():
    for name, folder in LIBRARIES.items():
        itl = folder / "iTunes Library.itl"
        xml = folder / "iTunes Music Library.xml"
        marks = [] if itl.is_file() else [pytest.mark.skip(reason=f"{itl} not present")]
        yield pytest.param((itl, xml if xml.is_file() else None), id=name, marks=marks)


@pytest.fixture(params=list(_params()))
def rewritten(request, tmp_path_factory):
    itl, xml = request.param
    out = tmp_path_factory.mktemp("acceptance")
    censuses, models, losses, total = verify.run(itl, xml, out)
    return censuses, models, losses


def _assert_no_loss(per: dict[str, int], pipeline: str) -> None:
    lost = {k: v for k, v in per.items() if v}
    assert not lost, f"{pipeline} lost: {lost}"


def test_write_itl_keeps_all_playlists(rewritten):
    _, _, losses = rewritten
    _assert_no_loss({"playlists": losses["write_itl"]["playlists"]}, "write_itl")


def test_write_itl_keeps_folders_and_parent_relations(rewritten):
    _, _, losses = rewritten
    _assert_no_loss({k: losses["write_itl"][k] for k in ("folders", "parent_relations")}, "write_itl")


def test_write_itl_keeps_smart_playlists_with_identical_rules(rewritten):
    _, _, losses = rewritten
    _assert_no_loss({k: losses["write_itl"][k] for k in ("smart_playlists", "smart_blobs")}, "write_itl")


def test_write_itl_keeps_special_playlists(rewritten):
    _, _, losses = rewritten
    _assert_no_loss({"special_playlists": losses["write_itl"]["special_playlists"]}, "write_itl")


def test_write_itl_keeps_track_fields(rewritten):
    _, _, losses = rewritten
    fields = ("tracks",) + verify.TRACK_FIELDS
    _assert_no_loss({k: losses["write_itl"][k] for k in fields}, "write_itl")


def test_write_xml_keeps_everything(rewritten):
    _, _, losses = rewritten
    if "write_xml" not in losses:
        pytest.skip("no XML for this library")
    _assert_no_loss(losses["write_xml"], "write_xml")


@pytest.mark.skipif(verify.ItlDocument is None, reason="edit mode (ItlDocument) not available yet")
def test_edit_mode_keeps_everything(rewritten):
    _, _, losses = rewritten
    if "edit" not in losses:
        pytest.skip("edit mode not run")
    _assert_no_loss(losses["edit"], "edit")
