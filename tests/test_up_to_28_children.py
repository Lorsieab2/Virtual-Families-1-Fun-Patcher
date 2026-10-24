"""Up to 28 Children (vf1kids.dll).

Layers (nothing here starts the game; there is no live test):

* always: the manifest row, the README, the DLL source and vf1fun's loader agree on the names, the
  numbers and the owner's sentence; the DLL holds no address outside the generated header;
* with the vanilla executable (VF1_VANILLA_EXE or VF1_VANILLA_DIR): every pin is proved with capstone +
  pefile, the committed header is a fresh render, and a damaged executable is refused;
* with the vanilla executable AND the MSVC toolchain: the DLL builds with /W4 /WX, and the REAL compiled
  DLL runs inside unicorn with the REAL game code (tests/kids_scenarios.py); every mutation of its source
  makes a scenario fail; vf1fun's loader is built in a harness with a stand-in vf1kids.dll.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

from conftest import ROOT  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vf1_kids_sites as K  # noqa: E402

SRC = ROOT / "native" / "vf1kids"
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")
OWNER_SENTENCE = ('Virtual Families 1 natively keeps up to 6 children per generation in its Family Tree, and a household holds at most 30 villagers (2 parents and 28 children). This patch keeps children 7 to 28 in a separate file beside the save, so they never overwrite Family Tree entries; storing more than 6 children in the Family Tree itself would overwrite its entries and glitch the game.')


def vanilla_exe() -> Path:
    value = os.environ.get("VF1_VANILLA_EXE")
    if not value and os.environ.get("VF1_VANILLA_DIR"):
        value = str(Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe")
    if not value or not Path(value).is_file():
        pytest.skip("set VF1_VANILLA_EXE (or VF1_VANILLA_DIR) to the vanilla Virtual Families game")
    return Path(value)


def need_toolchain():
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")


def _env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


# ===================================================================== always
def test_the_owners_numbers():
    assert K.MAX_CHILDREN == 28 and K.TREE_CHILDREN == 6 and K.MAX_EXTRA_CHILDREN == 22
    assert 2 + K.MAX_CHILDREN == K.HOUSEHOLD_SLOTS
    assert K.RECORD_CHILDREN + K.TREE_CHILDREN * K.PEEP_RECORD_SIZE == K.FAMILY_RECORD_SIZE


def test_manifest_row():
    m = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
    rows = [s for s in m["settings"] if s["id"] == "UpTo28Children"]
    assert len(rows) == 1
    row = rows[0]
    assert row["default"] is False and row["category"] == "experimental" and row["label"] == "Up to 28 Children"
    assert OWNER_SENTENCE in row["description"]
    assert row["files"] == [{"source": "vf1kids.dll", "target": "Virtual Families 1 Patcher Files/vf1kids.dll"}]


def test_readme_and_transparency_log_carry_the_owners_sentence():
    assert OWNER_SENTENCE in re.sub(r"\s+", " ", (ROOT / "README.md").read_text(encoding="utf-8"))
    log = (ROOT / "release" / "Transparency Log.txt").read_text(encoding="utf-8")
    assert OWNER_SENTENCE in re.sub(r"\s+", " ", log)


def test_vf1fun_loads_the_companion_only_with_the_setting():
    cpp = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8")
    assert 'if (SettingOn(L"UpTo28Children", false))\n        LoadKidsCompanion();' in cpp.replace("\r\n", "\n")
    assert 'L"vf1kids.dll"' in cpp and '"VF1Kids_Startup"' in cpp and '"VF1Kids_Children"' in cpp
    kids = (SRC / "vf1kids.cpp").read_text(encoding="utf-8")
    assert 'L"UpTo28Children"' in kids and 'L"settings.ini"' in kids
    assert "Virtual Families 1 Patcher Data\\\\Children\\\\" in kids


def test_the_source_has_no_hard_coded_game_address():
    text = (SRC / "vf1kids.cpp").read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    found = [x for x in re.findall(r"0x[0-9A-Fa-f]{5,8}\b", text)
             if int(x, 16) > 0x400000 and x.lower() not in ("0x434b3156u", "0xcbf29ce484222325", "0x100000001b3")]
    assert not found, found


# ===================================================================== with the vanilla exe
def test_every_site_is_proved():
    K.validate(vanilla_exe().read_bytes())


def test_the_pins_are_the_patchers_vanilla():
    sys.path.insert(0, str(ROOT / "patcher"))
    import vf1_patcher
    assert K.VANILLA_EXE_SHA256 == vf1_patcher.VANILLA_SHA256


def test_committed_header_is_a_fresh_render():
    assert (SRC / "vf1kids_sites.h").read_text() == K.render_header(K.validate(vanilla_exe().read_bytes()))


@pytest.mark.parametrize("pin", [p[0] for p in K.PINS])
def test_a_damaged_executable_is_refused(pin):
    data = bytearray(vanilla_exe().read_bytes())
    exe = K.Exe(bytes(data))
    name, va, n, note = K.PIN[pin]
    raw = exe.read(va, n)
    mask = K.mask_for(raw, va)
    k = next(i for i in range(n) if not mask[i])
    data[exe.pe.get_offset_from_rva(va + k - exe.base)] ^= 0x01
    with pytest.raises(K.SiteError):
        K.validate(bytes(data))


# ===================================================================== the DLL under emulation
def _build(kind: str, out_dir: Path) -> Path:
    """Runs build_kids.bat itself, but into this run's own out_dir (VF1_BUILD_DIR) instead of the shared
    build\\ folder, so test runs going at the same time never compile into the same files."""
    need_toolchain()
    out_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_kids.bat")] + ([kind] if kind else []),
                       capture_output=True, text=True, env=dict(_env(), VF1_BUILD_DIR=str(out_dir)))
    assert r.returncode == 0, r.stdout + r.stderr
    return out_dir / ("vf1kids_test.dll" if kind == "test" else "vf1kids.dll")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    vanilla_exe()
    out = tmp_path_factory.mktemp("kids")
    return {"test": _build("test", out), "release": _build("", out)}


def _scen():
    import kids_scenarios as scen
    return scen


def test_the_shipped_dll_has_no_test_entry_points(built):
    data = built["release"].read_bytes()
    assert b"VF1Kids_Startup" in data and b"VF1Kids_TestPlan" not in data


def test_the_plan(built):
    scen = _scen()
    w = scen.KidsWorld(vanilla_exe(), built["test"], install=False)
    status, writes = w.test_plan(True)
    assert status == 1 and {va for va, _ in writes} == {K.PIN[K.FUNCTIONS[n]][1] for n in K.HOOKS}
    assert all(raw[0] == 0xE9 for _, raw in writes)
    assert w.test_plan(False) == (0, [])


SCEN = __import__("kids_scenarios")


@pytest.mark.parametrize("name", [f.__name__ for f in SCEN.ALL])
def test_installed_scenarios(built, name):
    scen = _scen()
    getattr(scen, name)(scen.KidsWorld(vanilla_exe(), built["test"]))


@pytest.mark.parametrize("name", [f.__name__ for f in SCEN.FACTORY])
def test_birth_scenarios(built, name):
    scen = _scen()
    getattr(scen, name)(lambda: scen.KidsWorld(vanilla_exe(), built["test"]))


@pytest.mark.parametrize("name", [f.__name__ for f in SCEN.OFF])
def test_setting_off_is_stock(built, name):
    scen = _scen()
    getattr(scen, name)(scen.KidsWorld(vanilla_exe(), built["test"], install=False))


def test_a_patched_function_is_refused(built):
    """A pinned function that is not the vanilla bytes (here: AddOffspring's cap) refuses the whole plan."""
    scen = _scen()
    w = scen.KidsWorld(vanilla_exe(), built["test"], install=False)
    w.e.write(0x481ABE, b"\x07")    # cmp ecx,6 -> cmp ecx,7
    status, writes = w.test_plan(True)
    assert status == -1 and writes == []


MUTATIONS = [
    ("free-slot cap dropped", "    return room < free ? room : free;\n}", "    (void)free;\n    return room;\n}",
     "scenario_free_slots_cap"),
    ("28 becomes 29", "    int room = (int)KIDS_MAX_CHILDREN - born;", "    int room = (int)KIDS_MAX_CHILDREN + 1 - born;",
     "scenario_limit_counts_lifetime_births"),
    ("no reused-slot invalidation",
     "        if (Extras[i].slot == slot && Extras[i].state == STATE_ALIVE) Extras[i].state = STATE_GONE;",
     "        if (Extras[i].slot == slot && Extras[i].state == 99) Extras[i].state = STATE_GONE;",
     "scenario_rename_and_reused_slot"),
    ("no restore of the swapped child", "    if (v) Copy(v, ChildImage, KIDS_VILLAGER_STRIDE);\n    Next.swapped = -1;",
     "    (void)v;\n    Next.swapped = -1;", "scenario_full_house"),
    ("the save sees the clone", "        Copy(v, ChildImage, KIDS_VILLAGER_STRIDE);\n    }\n    bool saved",
     "    }\n    bool saved", "scenario_full_house"),
    ("no backup sidecar", "    if (hashed && SidecarPath(state, slot + (int)KIDS_SAVE_BACKUP_OFFSET",
     "    if (false && hashed && SidecarPath(state, slot + (int)KIDS_SAVE_BACKUP_OFFSET", "scenario_sidecar_follows_backup"),
    ("deaths not recorded", "                Extras[i].state = STATE_DEAD;", "                (void)0;",
     "scenario_deaths_count_toward_28"),
    ("extras never candidates",
     "        if (Extras[i].state == STATE_ALIVE && Matches(Extras[i])) Next.sources[n++] = Extras[i].slot;",
     "        if (Extras[i].state == 99) Next.sources[n++] = Extras[i].slot;", "scenario_next_generation_candidates"),
    ("clones left on show", "    if (clone >= 0) SetPresent(clone, false);", "    (void)&SetPresent;",
     "scenario_next_generation_candidates"),
    ("unreadable overwritten", "        bool moved = MoveAside(path);",
     "        bool moved = ((void)&MoveAside, true);", "scenario_unreadable_sidecar_is_kept_aside"),
    # the three sidecar defects: each fix removed must fail its scenario
    ("unreadable backup deleted unread",
     "    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = MoveAside(backup);",
     "    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = DeleteFileA(backup) != 0;",
     "scenario_unreadable_backup_is_set_aside"),
    ("foreign backup deleted unread",
     "    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = MoveAside(backup);",
     "    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = DeleteFileA(backup) != 0;",
     "scenario_foreign_backup_is_set_aside"),
    ("backup removed without being read", "    int old = Classify(backup, backupSave, &oldFile);",
     "    int old = (DeleteFileA(backup), FILE_MISSING); (void)&oldFile;", "scenario_unreadable_backup_is_set_aside"),
    ("an unvalidated sidecar rotated", "    if (mine == FILE_OK) {\n        if (clear) MoveFileExA(path, backup, 0);",
     "    if (mine == FILE_OK || mine == FILE_FOREIGN) {\n        if (clear) MoveFileExA(path, backup, 0);",
     "scenario_foreign_backup_is_set_aside"),
    ("no retry of a shut file", "    return e == ERROR_SHARING_VIOLATION || e == ERROR_LOCK_VIOLATION || e == ERROR_ACCESS_DENIED;",
     "    return e == 0xFFFFu;", "scenario_shut_sidecar_is_retried_never_set_aside"),
    ("a shut file is judged damaged",
     "    return e == ERROR_FILE_NOT_FOUND || e == ERROR_PATH_NOT_FOUND ? FILE_MISSING : FILE_SHUT;",
     "    return e == ERROR_FILE_NOT_FOUND || e == ERROR_PATH_NOT_FOUND ? FILE_MISSING : FILE_DAMAGED;",
     "scenario_shut_sidecar_is_retried_never_set_aside"),
    ("a save replaces a shut sidecar", "    if (mine == FILE_SHUT || ShutSlot == slot) {", "    if (false) {",
     "scenario_shut_sidecar_is_retried_never_set_aside"),
    ("a sidecar read late is not merged", "            Merge(mineFile, mine == FILE_OK || backups);",
     "            (void)backups;", "scenario_shut_sidecar_is_retried_never_set_aside"),
    ("the set-aside name buffer too small", "    char aside[kSidecarPathCap + 32];", "    char aside[MAX_PATH + 24];",
     "scenario_long_path_set_aside"),
    ("a damaged file that cannot be set aside is replaced", "        if (!MoveAside(path)) {",
     "        if (!MoveAside(path) && false) {", "scenario_long_path_set_aside"),
    ("dead entries dropped on an exact load", "        if (!exact && e.state != STATE_ALIVE) continue;",
     "        if (e.state != STATE_ALIVE) continue;", "scenario_sidecar_round_trip"),
    ("rename not followed", "            CopyName(e.name, name);", "            (void)name;", "scenario_rename_and_reused_slot"),
]


def _build_variant(source: str, out_dir: Path) -> Path:
    need_toolchain()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vf1kids.cpp").write_text(source, encoding="utf-8", newline="\n")
    shutil.copyfile(SRC / "vf1kids_sites.h", out_dir / "vf1kids_sites.h")
    (out_dir / "build.bat").write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        "cl /nologo /O2 /MT /EHsc /W4 /WX /DVF1KIDS_TEST /LD /GS vf1kids.cpp /Fevf1kids_test.dll "
        "/link kernel32.lib /NXCOMPAT /SAFESEH:NO || exit /b 1\r\n", encoding="ascii")
    r = subprocess.run(["cmd.exe", "/c", str(out_dir / "build.bat")], cwd=out_dir, capture_output=True, text=True,
                       env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return out_dir / "vf1kids_test.dll"


@pytest.mark.parametrize("label,old,new,scenario", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_every_mutation_is_caught(built, tmp_path, label, old, new, scenario):
    source = (SRC / "vf1kids.cpp").read_text(encoding="utf-8")
    assert source.count(old) == 1, ("the mutation no longer matches the source", label)
    dll = _build_variant(source.replace(old, new), tmp_path / "m")
    scen = _scen()
    fn = getattr(scen, scenario)
    with pytest.raises(AssertionError):
        if fn in scen.FACTORY:
            fn(lambda: scen.KidsWorld(vanilla_exe(), dll))
        else:
            fn(scen.KidsWorld(vanilla_exe(), dll))


# ===================================================================== vf1fun's loader
LOADER_HARNESS = r'''
#include "@SOURCE@"

int main(int argc, char **argv) {
    // vf1fun builds its settings path from its own module; point it at this folder.
    GetModuleFileNameW(0, SettingsPath, MAX_PATH);
    wchar_t *slash = wcsrchr(SettingsPath, L'\\');
    wcscpy_s(slash + 1, MAX_PATH - (slash + 1 - SettingsPath), L"settings.ini");
    const wchar_t *before = FamilyFullText();
    if (SettingOn(L"UpTo28Children", false)) LoadKidsCompanion();
    const wchar_t *after = FamilyFullText();
    printf("%d %d %d %d %ls|%ls\n", KidsChildren != 0, KidsLimit != 0, KidsChildren ? KidsChildren() : -1,
           KidsLimit ? KidsLimit() : -1, before, after);
    return 0;
}
'''

STAND_IN = r'''
#include <windows.h>
static int started;
extern "C" __declspec(dllexport) int __cdecl VF1Kids_Startup() { started = 1; return INSTALLED; }
extern "C" __declspec(dllexport) int __cdecl VF1Kids_Children() { return 17; }
extern "C" __declspec(dllexport) int __cdecl VF1Kids_Limit() { return 28; }
'''


@pytest.fixture(scope="module")
def loader_harness(tmp_path_factory):
    need_toolchain()
    tmp = tmp_path_factory.mktemp("kids_loader")
    (tmp / "loader.cpp").write_text(LOADER_HARNESS.replace("@SOURCE@", (ROOT / "native" / "vf1fun" / "vf1fun.cpp").as_posix()),
                                    encoding="utf-8")
    for name, installed in (("stand_in_on", 1), ("stand_in_off", 0)):
        (tmp / f"{name}.cpp").write_text(STAND_IN.replace("INSTALLED", str(installed)), encoding="utf-8")
    script = tmp / "build.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 loader.cpp /Feloader_harness.exe '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n"
        "cl /nologo /O2 /MT /LD stand_in_on.cpp /Festand_in_on.dll || exit /b 1\r\n"
        "cl /nologo /O2 /MT /LD stand_in_off.cpp /Festand_in_off.dll || exit /b 1\r\n", encoding="ascii")
    r = subprocess.run(["cmd", "/c", str(script)], cwd=tmp, capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return tmp


def _run_loader(folder: Path, setting: int | None, dll: str | None) -> str:
    ini = folder / "settings.ini"
    target = folder / "vf1kids.dll"
    if target.exists():
        target.unlink()
    if dll:
        shutil.copyfile(folder / dll, target)
    ini.write_text("[Patches]\r\n" + (f"UpTo28Children={setting}\r\n" if setting is not None else ""), encoding="ascii")
    r = subprocess.run([str(folder / "loader_harness.exe")], cwd=folder, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


def test_the_loader(loader_harness):
    six = "This family already has six children."
    full = "This family has no room for another child (28 at most)."
    assert _run_loader(loader_harness, 1, "stand_in_on.dll") == f"1 1 17 28 {six}|{full}"
    assert _run_loader(loader_harness, 0, "stand_in_on.dll") == f"0 0 -1 -1 {six}|{six}", "setting off: not loaded"
    assert _run_loader(loader_harness, None, "stand_in_on.dll") == f"0 0 -1 -1 {six}|{six}", "no key: off"
    assert _run_loader(loader_harness, 1, None) == f"0 0 -1 -1 {six}|{six}", "no DLL: the game keeps six"
    assert _run_loader(loader_harness, 1, "stand_in_off.dll") == f"0 0 -1 -1 {six}|{six}", "not installed: six"
