"""Shared fixtures. Game files are never part of the repository: set
VF1_VANILLA_DIR to a copy of your own vanilla Virtual Families folder (or
VF1_VANILLA_EXE to its executable, for the executable-only tests), or the
tests that need it skip. The tests only read that folder."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
sys.path.insert(0, str(ROOT / "tools"))

import vf1_patcher  # noqa: E402

MANIFEST = ROOT / "patcher" / "manifest.json"


@pytest.fixture(scope="session")
def vanilla_dir() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / vf1_patcher.VANILLA_EXE).is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    return Path(value).resolve()


def snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    return {p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def vanilla_unchanged(vanilla_dir):
    """Fails the test if anything in the vanilla folder changed."""
    before = snapshot(vanilla_dir)
    exe = vf1_patcher.sha256_file(vanilla_dir / vf1_patcher.VANILLA_EXE)
    yield vanilla_dir
    assert snapshot(vanilla_dir) == before
    assert vf1_patcher.sha256_file(vanilla_dir / vf1_patcher.VANILLA_EXE) == exe == vf1_patcher.VANILLA_SHA256


@pytest.fixture
def workdir(tmp_path) -> Path:
    """A patcher folder in tmp: a copy of manifest.json (so dry-run logs land
    here, not in the repository), stub.json beside it, and a stand-in DLL in
    payload/. The engine never looks inside the DLL."""
    (tmp_path / "patcher").mkdir()
    shutil.copy2(MANIFEST, tmp_path / "patcher" / "manifest.json")
    (tmp_path / "patcher" / "payload").mkdir()
    (tmp_path / "patcher" / "payload" / vf1_patcher.DLL_NAME).write_bytes(b"MZ stand-in vf1fun.dll for tests")
    # Stand-ins for the files settings install (the real ones are staged by tools/stage_payload.py
    # and never committed).
    for setting in json.loads(MANIFEST.read_text(encoding="utf-8"))["settings"]:
        for row in setting.get("files", []):
            stand_in = tmp_path / "patcher" / "payload" / row["source"]
            stand_in.parent.mkdir(parents=True, exist_ok=True)
            stand_in.write_bytes(b"stand-in for " + row["source"].encode())
    return tmp_path


# --- Release-only tests ----------------------------------------------------
#
# As in the Virtual Villagers Fun Patcher: a test that took 15 s or more in a
# full serial run (pytest --durations, 2026-10-23, 148 tests in 342 s) is
# release-only. An ordinary run skips it; the run before a release includes it:
# `pytest --release`, VF1_RELEASE=1, or scripts/run_tests_parallel.py (which
# passes --release unless told --quick). The skip says why, so a run never hides
# that it left them out. tests/test_release_only.py checks that every entry
# names a real test.
#
# Two slow fixture setups are NOT listed, because skipping the test that first
# uses them only moves the cost to the next one: the vf1kids.dll builds in
# test_up_to_28_children.py (~31 s) and the hook harness build in
# test_hook_install.py (~24 s).

RELEASE_ONLY = (
    "tests/test_up_to_28_children.py::test_every_mutation_is_caught[28 becomes 29]",
    "tests/test_up_to_28_children.py::test_every_mutation_is_caught[no reused-slot invalidation]",
    "tests/test_engine.py::test_rebuild_keeps_remembered_cheats_and_restore_undoes_a_first_build",
    "tests/test_up_to_28_children.py::test_every_mutation_is_caught[no restore of the swapped child]",
    "tests/test_up_to_28_children.py::test_every_mutation_is_caught[free-slot cap dropped]",
)
RELEASE_SKIP_REASON = "release-only (slow): run with --release or VF1_RELEASE=1"


def pytest_addoption(parser):
    parser.addoption("--release", action="store_true", default=False,
                     help="also run the slow release-only tests (tests/conftest.py RELEASE_ONLY)")


def release_run(config) -> bool:
    return bool(config.getoption("--release")) or os.environ.get("VF1_RELEASE") == "1"


def pytest_collection_modifyitems(config, items):
    if release_run(config):
        return
    slow = set(RELEASE_ONLY)
    skip = pytest.mark.skip(reason=RELEASE_SKIP_REASON)
    for item in items:
        if repo_nodeid(item) in slow:
            item.add_marker(skip)


def repo_nodeid(item) -> str:
    """The item's node id relative to the repository, whatever pytest chose as rootdir (with no ini file a
    run of one file roots at tests/, which would turn "tests/x.py::t" into "x.py::t")."""
    rest = item.nodeid.split("::", 1)[1] if "::" in item.nodeid else ""
    return f"{Path(item.path).resolve().relative_to(ROOT).as_posix()}::{rest}"


def write_manifest(path: Path, **changes) -> Path:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
