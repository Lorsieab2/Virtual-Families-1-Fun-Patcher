"""Store Refresh Key (setting StoreRefreshKey, on by default): R in the store redraws the store's Flea Market (the
six random items, the code's "specials") and its random clothing, every time it is pressed. Proved by running the
vanilla game's own code (and vf1fun.dll's) in unicorn, before and after, with the setting's hook installed or not,
and with the hook failing open.

The stock store already has the key: theStoreScene::HandleEvent 0x4499D0 takes a typed small 'r' (0x72) and, if
0x496DB0 allows it (more than 1 real hour since the last draw; it then sets the next draw 4 real hours ahead,
inventory +0x13C), redraws the specials (0x449480(-1)), both outfit pictures (0x496C70(1)) and the labels
(0x449100). vf1fun.dll (native/vf1fun/store_keys.inc) jumps from 0x4499EA to a detour that also takes 'R' and
asks the game's own 0x496DB0 with the due time cleared, so it always allows; the game's own draws then run.

A small harness DLL that includes native/vf1fun/vf1fun.cpp (built with native/build.bat's settings) exports the
install; the vanilla exe (VF1_VANILLA_DIR) and that DLL share one unicorn address space (tests/kids_emu.py). The
source checks run everywhere; the rest needs the vanilla game and the MSVC toolchain, and skips without them."""
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
CPP = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
INC = (ROOT / "native" / "vf1fun" / "store_keys.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
FEATURES = (ROOT / "native" / "vf1fun" / "features.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
MANIFEST = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

INV, TRAY = 0x8957A0, 0x8958E8
SPECIALS = 0x4F1308                     # the store's places, 0x14 bytes each; the specials are places 8..13
SITE = 0x4499EA
STOCK_KEY = bytes.fromhex("83f8727573b9a0578900e8b7d3040084c07465")
STOCK_ALLOWED = bytes.fromhex("568bf1e8a8c8f8ff8bc8e811c9f6ff8b8e3c0100008d90302a00003bd1770e8d90403800003bd172043"
                              "2c05ec3054038000089863c010000b0015ec3")
HOUR, FOUR_HOURS = 3600, 0x3840

HARNESS = r'''
#include "@SOURCE@"
extern "C" __declspec(dllexport) void __cdecl T_Install() { InstallStoreRefreshKey(); }
extern "C" __declspec(dllexport) int __cdecl T_On() { return gStoreRefreshKeyOn; }
extern "C" __declspec(dllexport) void __cdecl T_InstallOutfits() { InstallOutfitPictureFix(); }
extern "C" __declspec(dllexport) int __cdecl T_Picture(int place, int item) { return OutfitPicture(place, item); }
'''


# ===================================================================== always
def test_the_setting_is_on_by_default_and_documented():
    row = next(s for s in MANIFEST["settings"] if s["id"] == "StoreRefreshKey")
    assert row["default"] is True and row["category"] == "optional"
    assert "Flea Market" in row["description"] and "half-price" in row["description"]
    assert "specials" in row["description"]


def test_the_game_mechanics_page_has_the_stock_and_patched_lines():
    import vf1_game_mechanics as gm
    text = gm.render()
    patched = gm.with_patcher("StoreRefreshKey", "")
    keys = [f for f in gm.facts() if f.group == gm.KEYS]
    assert any(f.text.startswith("The store's hidden key: typing a small r") for f in keys)       # stock
    assert any(f.text.startswith(patched + "a patcher key: R, small or capital") and f.label == gm.VERIFIED_E
               for f in keys)                                                                       # patched
    assert any(f.text.startswith("The Fun Patcher's keys: one patcher key") for f in keys)
    assert gm.setting("StoreRefreshKey") == "R Refreshes the Store, on by default"
    assert "half-price grocery" in text and "patcher key R, in the store only" in text


def test_the_hook_is_installed_only_by_its_setting():
    assert CPP.count("InstallStoreRefreshKey();") == 1
    assert 'if (SettingOn(L"StoreRefreshKey", true))\n        InstallStoreRefreshKey();' in CPP
    fix = re.search(r'if \(SettingOn\(L"FixVanillaGameBugs", true\)\) \{(.*?)\}', CPP, re.S).group(1)
    assert "InstallStoreRefreshKey" not in fix
    assert '#include "store_keys.inc"' in CPP


def test_every_byte_is_checked_before_anything_is_written():
    body = re.search(r"static void InstallStoreRefreshKey\(\) \{(.*?)\n\}\n", INC, re.S).group(1)
    checks, writes = body.split("return;  // not the stock game")
    assert "BytesAre(kStoreRedrawAllowed, allowed, sizeof allowed)" in checks
    assert "BytesAre(kStoreKeySite, key, sizeof key)" in checks
    assert "InstallJump" not in checks and "InstallJump(kStoreKeySite, key, sizeof key" in writes
    def code(part):  # the bytes listed, without the comments
        return bytes(int(b, 16) for line in part.splitlines()
                     for b in re.findall(r"0x([0-9A-F]{2})\b", line.split("//")[0]))
    key_part, allowed_part = checks.split("allowed[]")
    assert code(key_part) == STOCK_KEY
    assert code(allowed_part.split("if (")[0]) == STOCK_ALLOWED


def test_install_jump_never_overruns_its_buffer():
    # the store key's site is 19 bytes; InstallJump's patch buffer must hold it, and refuse what does not fit
    assert "unsigned char patch[32];" in FEATURES and "n > (int)sizeof patch" in FEATURES


# ===================================================================== the vanilla exe
def _vanilla_exe() -> Path:
    if not os.environ.get("VF1_VANILLA_DIR"):
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    exe = Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe"
    if not exe.is_file():
        pytest.skip("VF1_VANILLA_DIR has no Virtual Families.exe")
    return exe


def test_vanilla_store_key_is_a_small_r_with_a_one_hour_lock():
    pefile = pytest.importorskip("pefile")
    img = pefile.PE(str(_vanilla_exe())).get_memory_mapped_image()
    at = lambda va, n: bytes(img[va - 0x400000:va - 0x400000 + n])  # noqa: E731
    assert at(SITE, len(STOCK_KEY)) == STOCK_KEY
    assert at(0x496DB0, len(STOCK_ALLOWED)) == STOCK_ALLOWED
    # after the check: specials draw 0x449480(-1), outfit pictures 0x496C70(1), labels 0x449100
    assert at(0x4499FD, 4) == bytes.fromhex("6aff8bce")
    assert at(0x449A01, 5) == b"\xE8" + struct.pack("<i", 0x449480 - 0x449A06)
    assert at(0x449A0D, 5) == b"\xE8" + struct.pack("<i", 0x496C70 - 0x449A12)
    assert at(0x449A14, 5) == b"\xE8" + struct.pack("<i", 0x449100 - 0x449A19)


# ===================================================================== emulated
@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    tmp_path = tmp_path_factory.mktemp("storekey")
    src = tmp_path / "storekey_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    dll = tmp_path / "storekey_harness.dll"
    script = tmp_path / "build_harness.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 /LD "{src}" /Fo"{tmp_path}\\\\" /Fe"{dll}" '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n",
        encoding="ascii")
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer"
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")
    build = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=env)
    assert build.returncode == 0, build.stdout + build.stderr
    return dll


@pytest.fixture
def emu(harness_dll):
    exe = _vanilla_exe()
    pytest.importorskip("unicorn")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kids_emu
    e = kids_emu.Emu(exe, harness_dll)
    e.protects = []

    def virtual_protect(emu):
        if emu.arg(2) == 0x40:
            emu.protects.append((emu.arg(0), emu.arg(1)))
        emu.w32(emu.arg(3), 0x20)
        return 1, 16
    e.imports.update({"VirtualProtect": virtual_protect, "GetCurrentProcess": lambda emu: (0xFFFFFFFF, 0),
                      "FlushInstructionCache": lambda emu: (1, 12)})
    # the game's seams: the clocks, the dice, the game state, the family pet, graphics; every other step
    # (the key handler, the check, the specials draw, the outfit draw, the store's stock) is the game's own code
    e.now = 100                                                # real seconds since the family's start
    e.clock = 1000                                             # CGameTime::Seconds (game seconds)
    e.dice = 0
    e.labels = 0
    gs = e.alloc(0x1B400)

    def roll(emu):                                             # GetRandom(n): a fixed, varied sequence
        emu.dice += 1
        n = emu.arg(0)
        return (emu.dice * 7 + 3) % n if n else 0, 0

    def labels(emu):
        emu.labels += 1
        return 0, 0
    e.seam(0x403650, roll)
    e.seam(0x422320, lambda emu: (emu.clock, 0))
    e.seam(0x4036D0, lambda emu: (emu.now, 0))                # GetSecondsFromGameStart (real seconds)
    e.seam(0x423660, lambda emu: (gs, 0))                     # the game state
    e.seam(0x434720, lambda emu: (0, 4))                      # no family pet
    e.seam(0x449100, labels)                                  # the store's labels (text and pictures)
    e.call(0x496DF0, ecx=INV)                                 # a new family's inventory
    e.scene = e.alloc(0x200)
    e.call(0x496D80, ecx=INV)                                 # the store opening: the draw is due ...
    e.call(0x449480, (0xFFFFFFFF,), ecx=e.scene)              # ... the specials are drawn
    return e


def state(e):
    return dict(specials=[e.r32(SPECIALS + 0x14 * k) for k in range(8, 14)],
                special_stock=[e.r32(INV + 0x124 + 4 * k) for k in range(6)],
                due=e.r32(INV + 0x13C), pictures=(e.r32(INV + 0x108), e.r32(INV + 0x10C)),
                pictures_due=e.r32(INV + 0x118), bought=(e.r32(INV + 0x110), e.r32(INV + 0x114)),
                grocery=e.r32(INV + 0x11C), grocery_due=e.r32(INV + 0x120))


def press(e, ch, after=0, event=5):
    """Type one character in the store, `after` real seconds later: HandleEvent(5, 0, ch) (SDL_TEXTINPUT)."""
    e.now += after
    before = state(e)
    labels = e.labels
    r = e.call(0x4499D0, (event, 0, ord(ch) if isinstance(ch, str) else ch), ecx=e.scene) & 0xFF
    after_state = state(e)
    changed = {k for k in before if before[k] != after_state[k]}
    return changed, e.labels - labels, r, before, after_state




def test_the_first_draw_is_a_real_one(emu):
    s = state(emu)
    assert all(s["specials"]) and len(set(s["specials"])) == 6 and s["due"] == emu.now + FOUR_HOURS


def test_stock_r_waits_more_than_one_real_hour(emu):
    changed, labels, r, _, _ = press(emu, "r", HOUR)
    assert changed == set() and labels == 0 and r == 0         # 3,600 s: nothing
    changed, labels, r, before, after = press(emu, "r", 1)
    assert {"specials", "due", "pictures"} <= changed and labels == 1 and r == 0   # 3,601 s: redrawn
    assert after["due"] == emu.now + FOUR_HOURS
    assert after["grocery"] == before["grocery"] and after["grocery_due"] == before["grocery_due"]
    assert after["bought"] == before["bought"]
    changed, labels, _, _, _ = press(emu, "r", 0)
    assert changed == set() and labels == 0                    # and then locked again
    changed, labels, _, _, _ = press(emu, "R", 4 * HOUR)
    assert changed == set() and labels == 0                    # a capital R does nothing in the stock game


def test_patched_r_and_capital_r_redraw_every_time(emu):
    emu.call(emu.dll_export("T_Install"))
    assert emu.call(emu.dll_export("T_On")) == 1
    assert emu.protects == [(SITE, len(STOCK_KEY))]
    assert emu.read(SITE, 1) == b"\xE9" and emu.read(SITE + 5, len(STOCK_KEY) - 5) == b"\x90" * 14
    seen = set()
    for ch, after in (("r", 0), ("r", 0), ("R", 0), ("R", 1), ("r", 5), ("R", 0)):
        changed, labels, r, before, now = press(emu, ch, after)
        assert {"specials", "pictures"} <= changed and labels == 1 and r == 0
        assert now["due"] == emu.now + FOUR_HOURS                # the stock key's own next-draw time
        assert now["pictures_due"] == emu.clock + FOUR_HOURS
        assert all(now["specials"]) and len(set(now["specials"])) == 6
        assert all(0 <= p < 50 for p in now["pictures"])
        # never the half-price grocery: not its item, not its timer (its price follows its item)
        assert now["grocery"] == before["grocery"] and now["grocery_due"] == before["grocery_due"]
        assert now["bought"] == before["bought"]                 # the last bought outfits' fields
        seen.add(tuple(now["specials"]))
    assert len(seen) > 1


def test_patched_other_keys_are_the_stock_games(emu):
    emu.call(emu.dll_export("T_Install"))
    for ch in ("x", "t", "1", " ", 0x08):
        changed, labels, r, _, _ = press(emu, ch)
        assert changed == set() and labels == 0 and r == 0
    changed, labels, _, _, _ = press(emu, 0x52, event=6)        # a key event with the code of R: not typed
    assert changed == set() and labels == 0


def test_patched_the_redraw_writes_only_what_the_stock_key_writes(emu):
    """A stock press (after its hour) and a patched one right after it: the same fields change, the same way."""
    stock_changed, _, _, _, stock_after = press(emu, "r", HOUR + 1)
    assert stock_after["due"] == emu.now + FOUR_HOURS
    emu.call(emu.dll_export("T_Install"))
    patched_changed, _, _, _, patched_after = press(emu, "R", 0)
    assert patched_changed == stock_changed - {"due"}          # due: the same value again, rewritten
    assert patched_after["due"] == stock_after["due"]          # same time, same next draw


def test_bought_outfits_keep_their_pictures_after_r(emu):
    emu.call(emu.dll_export("T_Install"))
    emu.call(emu.dll_export("T_InstallOutfits"))
    emu.seam(0x497360, lambda e: (0, 4))                       # the tray place's widget refresh
    emu.write(TRAY, b"\0" * 0xA8)
    emu.w32(TRAY + 0x88, 40)
    emu.w32(TRAY + 0x8C, 10)
    emu.w32(TRAY + 0x90, 100)
    emu.w32(TRAY + 0x94, 50)
    emu.w32(TRAY + 0x98, 100 + 8 * 40 - 1)
    emu.call(0x497580, ecx=TRAY)                               # the tray's reset: gloves and the Ball
    emu.w32(INV + 18 * 4, 0xFFFFFFFF)
    from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESP
    place, scene = emu.alloc(0x20), emu.alloc(0x40)
    emu.w32(place, 18)                                         # buy a Male Outfit (0x449AF6 .. the tray add)
    emu.setreg(UC_X86_REG_EDI, place)
    emu.setreg(UC_X86_REG_EBX, scene)
    emu.setreg(UC_X86_REG_ESP, emu.sp_top - 0x400)
    emu.uc.emu_start(0x449AF6, 0x449B5D, count=100_000)
    tray = [emu.r32(TRAY + 8 * k) for k in range(8)]
    slot = tray.index(64)
    bought = emu.r32(INV + 0x108)
    assert emu.call(emu.dll_export("T_Picture"), (slot, 64)) == bought
    pictures = set()
    for _ in range(6):
        _, _, _, _, now = press(emu, "R")
        pictures.add(now["pictures"][0])
        assert now["bought"][0] == bought                      # the field the save holds: unchanged
        assert emu.call(emu.dll_export("T_Picture"), (slot, 64)) == bought
        assert [emu.r32(TRAY + 8 * k) for k in range(8)] == tray
    assert pictures - {bought}                                 # the store's own picture did change


@pytest.mark.parametrize("where", ["site", "check"])
def test_fails_open_when_any_byte_differs(emu, where):
    if where == "site":
        emu.write(SITE + 2, b"\x73")                           # another key code: not the stock game
    else:
        emu.write(0x496DB0 + 23, b"\x31")                      # a different lock time
    emu.call(emu.dll_export("T_Install"))
    assert emu.call(emu.dll_export("T_On")) == 0 and emu.protects == []
    if where == "check":
        changed, labels, _, _, _ = press(emu, "R", 0)
        assert changed == set() and labels == 0                # the stock game, untouched
