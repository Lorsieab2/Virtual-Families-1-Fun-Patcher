"""The release bundle (tools/package_release.py) works as shipped."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import package_release
import vf1_patcher as vp
from conftest import ROOT

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
    return tmp_path / "x" / TOP / FILES, names


FILES = "Virtual Families 1 Fun Patcher Files"
PLAYER_FILES = ["Launch_GUI.bat", f"Apply_{VERSION}_Patcher.bat", "How to Use.txt", f"README-{VERSION}-PATCHER.txt",
                "Transparency Log.txt"]


def test_the_top_folder_holds_only_what_the_player_opens(bundle):
    """At the top: the two .bat files, the three texts and the patcher's own folder, nothing else."""
    folder, names = bundle
    assert vp.BUNDLE_FOLDER == FILES
    assert all(n.startswith(TOP + "/") for n in names)
    top = {n.removeprefix(TOP + "/").split("/")[0] for n in names}
    assert top == {*PLAYER_FILES, FILES}
    assert sorted(p.name for p in folder.parent.iterdir()) == sorted([*PLAYER_FILES, FILES])
    assert all(n.removeprefix(TOP + "/") in PLAYER_FILES for n in names if n.count("/") == 1)


def _bat_runs(bat: bytes) -> list[str]:
    """Every "%VF1_FILES%<name>" the .bat names, with VF1_FILES as the .bat sets it."""
    import re
    text = bat.decode("utf-8")
    assert 'set "SCRIPT_DIR=%~dp0"' in text
    assert f'set "VF1_FILES=%SCRIPT_DIR%{FILES}\\"' in text
    assert "%SCRIPT_DIR%vf1_" not in text and "%SCRIPT_DIR%manifest" not in text
    return re.findall(r'"%VF1_FILES%([^"%]+)"', text)


def test_the_bat_files_run_the_patcher_from_its_folder(bundle):
    folder, _names = bundle
    top = folder.parent
    launch = (top / "Launch_GUI.bat").read_bytes()
    apply = (top / f"Apply_{VERSION}_Patcher.bat").read_bytes()
    assert b'%VF1_PY% "%VF1_FILES%vf1_patcher_gui.py" "%VF1_FILES%manifest.json"' in launch
    assert b'%VF1_PY% "%VF1_FILES%vf1_patcher.py" apply --exe "%VF1_EXE%" --manifest "%VF1_FILES%manifest.json"' in apply
    for bat in (launch, apply):
        named = _bat_runs(bat)
        assert named and all((folder / name).is_file() for name in named), named


def test_the_gui_finds_its_files_from_another_folder(bundle, tmp_path):
    """Run as Launch_GUI.bat runs it (by a full path, from some other current folder): the patcher finds its
    manifest, stub, guides, payload and pictures beside itself."""
    folder, _names = bundle
    elsewhere = tmp_path / "somewhere else ü"
    elsewhere.mkdir()
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import vf1_patcher as vp, vf1_how_to_use as how, "
             "vf1_family_tree as ft, vf1_patcher_gui as gui; "
             "assert vp.DEFAULT_MANIFEST.is_file() and vp.STUB.is_file() and how.GUIDES_PATH.is_file(); "
             "assert vp.payload_dir(vp.DEFAULT_MANIFEST).joinpath('vf1fun.dll').is_file(); "
             "assert len(list(ft.PICTURES.glob('*.png'))) == 20; "
             "assert vp.shown_path(gui.local_settings_path().parent) == str(vp.DEFAULT_MANIFEST.parent); print(vp.DEFAULT_MANIFEST)")
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(folder)], capture_output=True, text=True,
                            cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == (folder / "manifest.json").resolve()
    result = subprocess.run([sys.executable, "-I", str(folder / "vf1_patcher.py"), "settings"], capture_output=True,
                            text=True, cwd=elsewhere)
    assert result.returncode == 0, result.stderr


def test_bundle_layout_matches_the_vf2_release(bundle):
    folder, names = bundle
    assert sorted(n.removeprefix(TOP + "/") for n in names) == sorted(PLAYER_FILES + [f"{FILES}/{n}" for n in [
        "manifest.json", "vf1_patcher.py", "vf1_patcher_gui.py", "vf1_save_backup.py",
        "vf1_save.py", "vf1_rename_family.py", "vf1_game_speed.py", "vf1_game_mechanics.py",
        "vf1_how_to_use.py", "how_to_use.json", "stub.json",
        "vf1_genealogy.py", "vf1_family_history.py", "vf1_tree_memory.py", "vf1_family_tree.py",
        "vf1_family_tree_window.py", "vf1_member_info.py", "vf1_line_colours.py", "vf1_tree_editor_tools.py",
        "vf1_gdiplus.py",
        "payload/vf1fun.dll"] + [f"tree_pictures/{p.name}" for p in (ROOT / "patcher" / "tree_pictures").glob("*.png")] + [f"payload/{row['source']}" for setting in json.loads(
            (folder / "manifest.json").read_text(encoding="utf-8"))["settings"] for row in setting.get("files", [])]])
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == VERSION
    assert manifest["payload"]["vf1fun.dll"]["size"] == (folder / "payload" / "vf1fun.dll").stat().st_size
    apply_bat = (folder.parent / f"Apply_{VERSION}_Patcher.bat").read_bytes()
    assert b"{VERSION}" not in apply_bat and b"\r\n" in apply_bat
    assert b'vf1_patcher_gui.py" "%VF1_FILES%manifest.json"' in (folder.parent / "Launch_GUI.bat").read_bytes()
    assert (folder.parent / "Transparency Log.txt").read_text(encoding="utf-8").replace("\r\n", "\n") == \
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


def test_the_tree_pictures_ship_byte_for_byte(bundle):
    """The Family Tree Maker's backgrounds and logos (the owner's pictures): every one a ready-made background or a
    logo, shipped unchanged beside the patcher and named in the Transparency Log."""
    import vf1_family_tree as ft
    folder, _names = bundle
    shipped = sorted(p.name for p in (ROOT / "patcher" / "tree_pictures").glob("*.png"))
    used = sorted([p[3][6:] for p in ft.PRESETS if p[3].startswith("asset:")] + [r[6:] for _n, r in ft.LOGOS])
    assert shipped == used and len(shipped) == 20
    log = (folder.parent / "Transparency Log.txt").read_text(encoding="utf-8")
    assert f"- {FILES}\\tree_pictures\\:" in log
    for name in shipped:
        assert (folder / "tree_pictures" / name).read_bytes() == (ROOT / "patcher" / "tree_pictures" / name).read_bytes()
        assert f"  {name}\r\n" in log or f"  {name}\n" in log
