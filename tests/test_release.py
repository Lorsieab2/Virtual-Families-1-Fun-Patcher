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
    modules = sorted(p.name for p in (ROOT / "patcher").glob("*.py"))
    assert {"vf1_patcher.py", "vf1_patcher_gui.py", "vf1_picture_maker.py", "vf1_game_art.py", "vf1_jpeg.py",
            "vf1_small_formats.py", "vf1_art_fonts.py", "vf1_art_sheets.py", "vf1_game_text.py"} <= set(modules)
    assert sorted(n.removeprefix(TOP + "/") for n in names) == sorted(set(PLAYER_FILES + [f"{FILES}/{n}" for n in [
        "manifest.json", "how_to_use.json", "stub.json", *modules,
        "vf1_translation_limits.json", "vf1_patch_strings.json",
        "payload/vf1fun.dll"] + [f"payload/UnicodeText/{p.name}" for p in (ROOT / "patcher" / "payload" / "UnicodeText").glob("*.txt")
                                 if p.stem not in ("SegoeUiBold18", "SegoeUiBold17", "SegoeUiBold24", "SegoeUi33")] + [f"tree_pictures/{p.name}" for p in (ROOT / "patcher" / "tree_pictures").glob("*.png")] + [f"payload/{row['source']}" for setting in json.loads(
            (folder / "manifest.json").read_text(encoding="utf-8"))["settings"] for row in setting.get("files", [])]]))
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


def test_every_bundled_module_imports_from_the_bundle_alone(bundle, tmp_path):
    """Each module the bundle ships imports from an empty folder, with only the bundle on the path (python -I), and
    so does every module a tool loads only when its window opens: nothing the zip needs is left in the repository."""
    folder, _names = bundle
    elsewhere = tmp_path / "empty"
    elsewhere.mkdir()
    probe = ("import importlib, sys; from pathlib import Path; folder = Path(sys.argv[1]).resolve(); "
             "sys.path.insert(0, str(folder)); bad = []\n"
             "for p in sorted(folder.glob('*.py')):\n"
             "    try:\n"
             "        m = importlib.import_module(p.stem)\n"
             "        if Path(m.__file__).resolve().parent != folder: bad.append(p.stem + ' from ' + m.__file__)\n"
             "    except Exception as e: bad.append(p.stem + ': ' + repr(e))\n"
             "for name in ('vf1_jpeg', 'vf1_small_formats', 'vf1_art_sheets', 'vf1_art_fonts', 'vf1_art_meters', "
             "'vf1_art_ui', 'vf1_art_house', 'vf1_art_misc', 'vf1_game_text', 'vf1_unicode_font', 'vf1_picture_maker'):\n"
             "    if name not in sys.modules: bad.append(name + ' not loaded')\n"
             "print('\\n'.join(bad)); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(folder)], capture_output=True, text=True,
                            cwd=elsewhere)
    assert result.returncode == 0, result.stdout + result.stderr


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


def test_test_translations_never_ship(bundle, tmp_path):
    """The owner: "Only exclude TEST files". The release ships the accepted translations of the public translations/
    folder (and of patcher/translations/vf1/), but never a "(TEST)" one: its display name (@language) or its credit
    (@translator) starts with "(TEST)", or, as a backstop, its file name says "(TEST)"."""
    _folder, names = bundle
    assert not any("(TEST)" in n.upper() for n in names)
    for name in names:                                                  # the real folders: no (TEST) file shipped
        if "/translations/vf1/" in name:
            source = next(p for f in package_release.TRANSLATION_FOLDERS for p in [f / name.rsplit("/", 1)[1]]
                          if p.is_file())
            assert not package_release.is_test_translation(source), name
    french = ROOT / "translations" / "fr.tsv"
    if french.is_file() and "(TEST)" in french.read_text(encoding="utf-8-sig")[:2000]:
        assert package_release.is_test_translation(french)
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    head = "Key\tEnglish\tTranslation\tNotes\r\n@format\t1\t1\r\n@game\tVirtual Families\t\r\n"
    (shelf / "Virtual Families - Deutsch.txt").write_text(head + "@language\tEnglish\tDeutsch\r\n", encoding="utf-8")
    (shelf / "de.tsv").write_text(head + "@language\tEnglish\tDeutsch\r\n@translator\t\tBob\r\n", encoding="utf-8")
    (shelf / "Virtual Families - Test.txt").write_text(
        head + "@language\tEnglish\t(TEST) - French AI Translation\r\n", encoding="utf-8")
    (shelf / "Virtual Families - Credit.txt").write_text(
        head + "@language\tEnglish\tFrançais\r\n@translator\t\t(TEST) AI translation\r\n", encoding="utf-8")
    (shelf / "fr.tsv").write_text("﻿" + head + "@language\tEnglish\t(test) Français\r\n", encoding="utf-8")
    (shelf / "(TEST) Virtual Families - Español.txt").write_text(head, encoding="utf-8")
    assert sorted(p.name for p in package_release.shipped_translations(shelf)) == ["Virtual Families - Deutsch.txt",
                                                                                  "de.tsv"]
    dll = tmp_path / "vf1fun.dll"
    dll.write_bytes(b"MZ stand-in")
    payload = tmp_path / "payload2"
    for setting in package_release.load_manifest()["settings"]:
        for row in setting.get("files", []):
            (payload / row["source"]).parent.mkdir(parents=True, exist_ok=True)
            (payload / row["source"]).write_bytes(b"stand-in")
    zip_path = package_release.build(VERSION, dll, tmp_path / "zip2", payload, translation_roots=[shelf])
    with zipfile.ZipFile(zip_path) as z:
        shipped = sorted(n.rsplit("/", 1)[1] for n in z.namelist() if "/translations/vf1/" in n)
    assert shipped == ["Virtual Families - Deutsch.txt", "de.tsv"]       # an accepted one ships, no (TEST) one
