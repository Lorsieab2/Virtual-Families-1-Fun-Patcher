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
    return tmp_path


def write_manifest(path: Path, **changes) -> Path:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
