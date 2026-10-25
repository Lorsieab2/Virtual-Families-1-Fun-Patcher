"""The release bundle (tools/package_release.py) works as shipped."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import package_release
import vf1_patcher as vp

VERSION = "v9.9.9-test"
TOP = f"Virtual-Families-1-Fun-Patcher-{VERSION}"


@pytest.fixture
def bundle(tmp_path):
    dll = tmp_path / "vf1fun.dll"
    dll.write_bytes(b"MZ stand-in vf1fun.dll for the bundle test")
    payload = tmp_path / "payload"
    for setting in package_release.load_manifest()["settings"]:
        for row in setting.get("files", []):
            (payload / row["source"]).parent.mkdir(parents=True, exist_ok=True)
            (payload / row["source"]).write_bytes(b"stand-in for " + row["source"].encode())
    zip_path = package_release.build(VERSION, dll, tmp_path / "zip", payload)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        z.extractall(tmp_path / "x")
    return tmp_path / "x" / TOP, names


def test_bundle_layout_matches_the_vf2_release(bundle):
    folder, names = bundle
    assert sorted(n.removeprefix(TOP + "/") for n in names) == sorted([
        "Launch_GUI.bat", f"Apply_{VERSION}_Patcher.bat", "How to Use.txt", f"README-{VERSION}-PATCHER.txt",
        "Transparency Log.txt", "manifest.json", "vf1_patcher.py", "vf1_patcher_gui.py", "vf1_save_backup.py",
        "vf1_save.py", "vf1_rename_family.py", "vf1_game_speed.py", "vf1_check_saves.py",
        "vf1_how_to_use.py", "how_to_use.json", "stub.json",
        "vf1_genealogy.py", "vf1_family_history.py", "vf1_tree_memory.py", "vf1_family_tree.py",
        "vf1_family_tree_window.py", "vf1_member_info.py", "vf1_line_colours.py", "vf1_tree_editor_tools.py",
        "vf1_gdiplus.py",
        "payload/vf1fun.dll"] + [f"payload/{row['source']}" for setting in json.loads(
            (folder / "manifest.json").read_text(encoding="utf-8"))["settings"] for row in setting.get("files", [])])
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == VERSION
    assert manifest["payload"]["vf1fun.dll"]["size"] == (folder / "payload" / "vf1fun.dll").stat().st_size
    apply_bat = (folder / f"Apply_{VERSION}_Patcher.bat").read_bytes()
    assert b"{VERSION}" not in apply_bat and b"\r\n" in apply_bat
    assert b'vf1_patcher_gui.py" "%SCRIPT_DIR%manifest.json"' in (folder / "Launch_GUI.bat").read_bytes()
    assert (folder / "Transparency Log.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == \
        vp.transparency_log_text(manifest)
    for name in names:
        assert "patch" not in Path(name).name.lower() or not name.lower().endswith(".exe")


def run_bundled(folder, *args):
    return subprocess.run([sys.executable, "-I", str(folder / "vf1_patcher.py"), *args],
                          capture_output=True, text=True, cwd=folder)


def test_bundled_patcher_builds_and_checks_its_payload(bundle, vanilla_unchanged, tmp_path):
    folder, _ = bundle
    out = tmp_path / "out"
    result = run_bundled(folder, "apply", "--exe", str(vanilla_unchanged / vp.VANILLA_EXE), "--output-dir", str(out))
    assert result.returncode == 0, result.stderr
    assert (out / vp.DLL_REL).read_bytes() == (folder / "payload" / "vf1fun.dll").read_bytes()
    (folder / "payload" / "vf1fun.dll").write_bytes(b"tampered")
    result = run_bundled(folder, "apply", "--output-dir", str(out))
    assert result.returncode == 2 and "does not match manifest.json" in result.stderr
