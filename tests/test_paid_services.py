"""VF2's paid services and the Free and Guaranteed Cheats setting, in vf1fun.dll.

The owner, 2026-11-01: "Include in VF1 all things that VF2 has already" -- VF2's store services and its Time
Warp and Adoption Services Special Upgrades are sold on a new Services page (setting SpecialUpgrades, on by
default) at VF2's prices, and Roll the Dice costs VF2's $2,000. The free and never-failing cheats (Force
Successful Pregnancy, the Clothing and Hairstyles page, Anti-Spam Software Ownership, the Flea Market's Get for
free, and every paid service for free) are behind their own setting, Free and Guaranteed Cheats
(FreeAndGuaranteedCheats, off by default).

VF2's prices and rules are the VF2 Fun Patcher's Game Mechanics page (vf2_game_mechanics.py, SPECIAL_ITEMS and
SERVICE_ITEMS, read from VF2's own store code); they are copied into VF2 below and every price is checked
against them.

A small harness DLL that includes native/vf1fun/vf1fun.cpp (native/build.bat's settings) exports the DLL's own
functions; the vanilla exe (VF1_VANILLA_DIR) and that DLL share one unicorn address space (tests/kids_emu.py).
The DLL's code runs for real -- the prices, the refusals, the money check, Psychotherapy's bands, Higher
Learning's pick, Desensitization, the gates and the dialog handlers -- and the game routines it calls are
seams that record their calls (the money, the career calls, the spawn and the family tree, leaving home, the
Time Warp's game steps). The source checks run everywhere; the rest needs the vanilla game and MSVC.
"""
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

NATIVE = ROOT / "native" / "vf1fun"
SOURCE = NATIVE / "vf1fun.cpp"
CPP = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
SERVICES = (NATIVE / "services.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
PAGES = (NATIVE / "pages.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
FAMILY = (NATIVE / "family.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
FAMILY_PAGE = (NATIVE / "family_page.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

# VF2's store: vf2_game_mechanics.py SPECIAL_ITEMS / SERVICE_ITEMS (the VF2 Fun Patcher, B202).
VF2 = {"Roll the Dice": 2000, "Time Warp": 2000, "Adoption Services": 4000, "Boarding School": 1500,
       "Systematic Desensitization": 2500, "Psychotherapy": 1750, "Higher Learning Classes": 1000,
       "Advanced Career Training": 1100, "Career Change": 1200}
ITEMS = ["Time Warp", "Adoption Services", "Boarding School", "Systematic Desensitization", "Psychotherapy",
         "Higher Learning Classes", "Advanced Career Training", "Career Change"]
SV = {name: i for i, name in enumerate(ITEMS)}

VILLAGERS = 0x5B8898 + 0x14640
STRIDE = 0x145FC
MONEY = 0x50C60C
LIKES = b"running, cooking, reading, gardening, music, painting\0"
DISLIKES = b"cooking, music, dancing\0"
NEEDED = "This needs the Free and Guaranteed Cheats patch. Tick it in the patcher, then click Enable/Disable Patches."

HARNESS = r'''
#include "@SOURCE@"
extern "C" __declspec(dllexport) void __cdecl T_SetFree(int on) { gFreeCheats = on != 0; }
extern "C" __declspec(dllexport) int __cdecl T_ReadFree() { return ReadFreeCheatsSetting(); }
extern "C" __declspec(dllexport) int __cdecl T_Price(int item, int who) { return ServicePrice(item, who); }
extern "C" __declspec(dllexport) const wchar_t *__cdecl T_Buy(int item, int who) { return BuyService(item, who); }
extern "C" __declspec(dllexport) int __cdecl T_DiceCost() { return RollTheDiceCost(); }
extern "C" __declspec(dllexport) int __cdecl T_ForceArmed(int armed) { gVillage.armed = armed; return ForceArmed(); }
extern "C" __declspec(dllexport) int __cdecl T_ReadArmed() { ReadArmed((HWND)0x77); return gVillage.armed; }
extern "C" __declspec(dllexport) void __cdecl T_FleaFree() { BuyItem((HWND)0x77, true); }
extern "C" __declspec(dllexport) void __cdecl T_FleaBuy() { BuyItem((HWND)0x77, false); }
extern "C" __declspec(dllexport) void __cdecl T_AntiSpam() { StoreCheatsProc((HWND)0x77, WM_COMMAND, ID_SC_ANTISPAM, 0); }
extern "C" __declspec(dllexport) void __cdecl T_Appearance() { UpgradesProc((HWND)0x77, WM_COMMAND, ID_UP_APPEARANCE, 0); }
extern "C" __declspec(dllexport) void __cdecl T_Hide(int which) {
    static const int ids[] = { ID_FA_FORCE, ID_SC_ANTISPAM, ID_FM_FREE };
    HideWithoutFreeCheats((HWND)0x77, ids[which]);
}
extern "C" __declspec(dllexport) int __cdecl T_Id(int which) {
    static const int ids[] = { ID_FA_FORCE, ID_SC_ANTISPAM, ID_FM_FREE };
    return ids[which];
}
'''


# ===================================================================== always
def test_the_prices_are_vf2s():
    for name, price in VF2.items():
        if name == "Roll the Dice":
            assert f"RollTheDicePrice = {price};" in CPP
            continue
        row = re.search(r'\{ L"%s", (\d+), (true|false),' % re.escape(name), SERVICES)
        assert row, name
        assert int(row.group(1)) == price, name
    assert "price = 1100 * (CareerLevel(who) + 1);" in SERVICES and "kTopCareerLevel = 7;" in SERVICES
    order = re.findall(r"enum \{ (SV_[A-Z_, ]+)\};", SERVICES)[0]
    assert [n.strip() for n in order.split(",")][:-1] == ["SV_TIME_WARP", "SV_ADOPTION", "SV_BOARDING",
                                                          "SV_DESENS", "SV_PSYCHO", "SV_LEARN", "SV_TRAINING",
                                                          "SV_CAREER"]


def test_the_services_page_belongs_to_special_upgrades():
    assert 'EnableWindow(GetDlgItem(dlg, ID_UP_SERVICES), SettingOn(L"SpecialUpgrades", true));' in CPP
    assert "case ID_UP_SERVICES: ShowServices(dlg); break;" in CPP
    assert '#include "services.inc"' in CPP
    assert 'L"Services: Time Warp, Adoption, Career Training..."' in CPP


def test_the_service_cheats_are_gone_from_the_cheat_pages():
    for gone in ('L"Instant job promotion"', 'L"Career Change (new career)"', 'L"Boarding School"',
                 'L"Systematic Desens."', 'L"Higher Learning"', 'L"Psychotherapy"'):
        assert gone not in CPP, gone
    assert "ID_TC_WARP, L\"Time Warp" not in PAGES and "TimeWarp();" not in PAGES
    assert "TimeWarp(); return 0;" in SERVICES


def test_buttons_that_add_or_remove_a_person_say_how():
    for label in ("Spawn child in house (male)", "Spawn child in house (female)",
                  "Spawn outside child in house (male)", "Spawn outside child in house (female)",
                  "Divorce Spouse (spouse leaves)...", "Evict Family (everyone leaves the house)...",
                  "Adopt New Person (the game's Adoption screen; after a game over)"):
        assert f'L"{label}"' in FAMILY_PAGE, label
    for old in ("Spawn Male Child", "Adopt Outside Boy", "Adopt Outside Girl"):
        assert f'L"{old}"' not in FAMILY_PAGE
    assert "Spawn outside child in house (3 years old, male or female at random)" in SERVICES


def test_every_free_cheat_is_gated():
    assert 'gFreeCheats = SettingOn(L"FreeAndGuaranteedCheats", false);' in CPP
    assert "ReadFreeCheatsSetting();\n    InstallFeatureHooks();" in CPP
    assert "static bool ForceArmed() { return gFreeCheats && (gVillage.armed & ARM_FORCE) != 0; }" in FAMILY
    assert FAMILY.count("ForceArmed()") == 3 and "gVillage.armed & ARM_FORCE) return" not in FAMILY
    assert "HideWithoutFreeCheats(dlg, ID_FA_FORCE);" in FAMILY_PAGE
    assert "if (gFreeCheats && IsDlgButtonChecked(dlg, ID_FA_FORCE)) m |= ARM_FORCE;" in FAMILY_PAGE
    assert "HideWithoutFreeCheats(dlg, ID_SC_ANTISPAM);" in PAGES
    assert "case ID_SC_ANTISPAM: if (!FreeCheatsRefused(dlg)) SetAntiSpam(!AntiSpamOwned()); break;" in PAGES
    assert "HideWithoutFreeCheats(dlg, ID_FM_FREE);" in CPP
    assert "if (free && FreeCheatsRefused(dlg)) return;" in CPP
    assert 'SettingOn(L"CheatUpgrades", true) && gFreeCheats);' in CPP
    assert "case ID_UP_APPEARANCE: if (!FreeCheatsRefused(dlg)) ShowAppearance(dlg); break;" in CPP
    assert "return gFreeCheats ? 0 : price;" in SERVICES
    assert "return gFreeCheats ? 0 : RollTheDicePrice;" in CPP


# ===================================================================== emulated
def _vanilla_exe() -> Path:
    if not os.environ.get("VF1_VANILLA_DIR"):
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    exe = Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe"
    if not exe.is_file():
        pytest.skip("VF1_VANILLA_DIR has no Virtual Families.exe")
    return exe


@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    tmp_path = tmp_path_factory.mktemp("services")
    src = tmp_path / "services_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    dll = tmp_path / "services_harness.dll"
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


def villager(slot):
    return VILLAGERS + slot * STRIDE


@pytest.fixture
def emu(harness_dll):
    exe = _vanilla_exe()
    pytest.importorskip("unicorn")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kids_emu
    e = kids_emu.Emu(exe, harness_dll)
    e.log = []
    e.rolls = []
    e.checked = set()
    e.shown = {}
    e.profile = {}
    gs = e.alloc(0x1B400)
    family = e.alloc(0x200)
    e.write(family, b"\x01")
    strings = e.alloc(0x200)
    e.write(strings, LIKES)
    e.write(strings + 0x100, DISLIKES)
    e.gs = gs

    def log(name, pop, value=0):
        def fn(emu):
            emu.log.append((name, emu.ecx) + tuple(emu.arg(k) for k in range(pop // 4)))
            return value, pop
        return fn

    def money_adjust(emu):                                     # CMoney::Adjust(amount, earned)
        amount = struct.unpack("<f", struct.pack("<I", emu.arg(0)))[0]
        emu.log.append(("money", amount))
        now = struct.unpack("<f", emu.read(MONEY, 4))[0]
        emu.write(MONEY, struct.pack("<f", now + amount))
        return 0, 8

    def roll(emu):                                             # GetRandom(n): scripted, then 0
        n = emu.arg(0)
        emu.log.append(("roll", n))
        return (emu.rolls.pop(0) if emu.rolls else 0), 0

    def get_string(emu):
        return {0x45B: strings, 0x45C: strings + 0x100}[emu.arg(0)], 4

    def spawn(emu):                                            # CVillagerManager::SpawnPeep(voice, gender, age)
        emu.log.append(("spawn", emu.arg(0), emu.arg(1), emu.arg(2)))
        v = villager(5)
        emu.write(v + 0x13574, b"\x01")
        emu.w32(v + 0x2AE0, 50)
        return 5, 12
    e.seam(0x423660, lambda emu: (gs, 0))                     # theGameState::Get
    e.seam(0x481730, lambda emu: (family, 0))                 # CFamilyTree::GetCurrentFamily
    e.seam(0x450530, lambda emu: (0x1234, 0))                 # theStringManager::Get
    e.seam(0x44FD90, get_string)
    e.seam(0x403650, roll)
    e.seam(0x422740, money_adjust)
    e.seam(0x48F590, log("advance career", 12))
    e.seam(0x48F020, log("reset career", 0))
    e.seam(0x4816E0, lambda emu: (3, 0))                      # EmptyOffspringSlots: room for 3
    e.seam(0x48BC60, spawn)
    e.seam(0x481AA0, log("add offspring", 4, 1))
    e.seam(0x48C5A0, log("forget plans", 4))
    e.seam(0x48A410, log("clear focus", 0))
    e.seam(0x4857F0, log("left home", 0))
    e.seam(0x423E10, log("life event", 12))
    e.seam(0x422830, log("interest", 0))                      # the Time Warp's game steps
    e.seam(0x489D00, log("timeflow", 0))
    e.seam(0x425010, lambda emu: (0x5555, 0))
    e.seam(0x424F80, log("realtime", 0))

    def message(emu):
        emu.log.append(("message", emu.wstr(emu.arg(1))))
        return 1, 16

    def get_item(emu):
        return 0x1000 + emu.arg(1), 8

    def show(emu):
        emu.shown[emu.arg(0) - 0x1000] = emu.arg(1)
        return 1, 8

    def profile(emu):                                          # GetPrivateProfileIntW(section, key, default, path)
        key = emu.wstr(emu.arg(1))
        emu.log.append(("profile", emu.wstr(emu.arg(0)), key, emu.arg(2)))
        return emu.profile.get(key, emu.arg(2)), 16

    def module_file(emu):
        path = "C:\\Game\\Virtual Families 1 Patcher Files\\vf1fun.dll\0".encode("utf-16-le")
        emu.write(emu.arg(1), path)
        return len(path) // 2 - 1, 12
    # the dialog's isolation-aware wrapper (ISOLATION_AWARE_ENABLED) asks for these first
    e.dyn_procs["QueryActCtxW"] = lambda emu: (1, 28)

    def module_handle_ex(emu):
        emu.w32(emu.arg(2), 0x30000000)
        return 1, 12
    e.dyn_procs["GetModuleHandleExW"] = module_handle_ex
    e.dyn_procs["FindActCtxSectionStringW"] = lambda emu: (0, 20)
    e.imports.update({
        "MessageBoxW": message,
        "GetLastError": lambda emu: (0, 0),
        "GetDlgItem": get_item,
        "ShowWindow": show,
        "EnableWindow": lambda emu: (0, 8),
        "IsDlgButtonChecked": lambda emu: (1 if emu.arg(1) in emu.checked else 0, 8),
        "SendMessageW": lambda emu: (0xFFFFFFFF, 16),          # no list row picked (LB_ERR)
        "GetPrivateProfileIntW": profile,
        "GetModuleFileNameW": module_file,
    })
    return e


def money(e):
    return struct.unpack("<f", e.read(MONEY, 4))[0]


def set_money(e, amount):
    e.write(MONEY, struct.pack("<f", float(amount)))


def put(e, slot, name=b"Ann", career=-1, level=0, happiness=60, likes=(-1, -1, -1), dislikes=(-1, -1, -1)):
    v = villager(slot)
    e.write(v + 0x13574, b"\x01\x00\x00\x00\x00")             # present; +0x13578: at home
    e.w32(v + 0x2AE0, 80)
    e.write(v + 0x2A44, name + b"\0")
    e.w32(v + 0x2B6C, career)
    e.w32(v + 0x2B70, level)
    e.w32(v + 0x2AD4 + 0x38, happiness)
    for k in range(3):
        e.w32(v + 0x13620 + 4 * k, likes[k])
        e.w32(v + 0x1362C + 4 * k, dislikes[k])


def buy(e, item, who=-1):
    r = e.call(e.dll_export("T_Buy"), (SV[item], who & 0xFFFFFFFF))
    return None if r == 0 else e.wstr(r)


def price(e, item, who=-1):
    r = e.call(e.dll_export("T_Price"), (SV[item], who & 0xFFFFFFFF))
    return struct.unpack("<i", struct.pack("<I", r))[0]


def charges(e):
    return [x[1] for x in e.log if x[0] == "money"]


def test_the_setting_is_read_from_settings_ini_and_off_when_missing(emu):
    assert emu.call(emu.dll_export("T_ReadFree")) == 0
    assert ("profile", "Patches", "FreeAndGuaranteedCheats", 0) in emu.log
    emu.profile["FreeAndGuaranteedCheats"] = 1
    assert emu.call(emu.dll_export("T_ReadFree")) == 1


def test_every_price_and_the_career_training_scale(emu):
    put(emu, 0, career=-1)
    for item in ITEMS:
        if item != "Advanced Career Training":
            assert price(emu, item, 0) == VF2[item], item
    assert price(emu, "Advanced Career Training", 0) == -1                     # a child: not sold
    for level in range(8):
        put(emu, 1, b"Bob", career=12, level=level)
        assert price(emu, "Advanced Career Training", 1) == (1100 * (level + 1) if level < 7 else -1)
    assert emu.call(emu.dll_export("T_DiceCost")) == 2000


def test_free_and_guaranteed_cheats_make_everything_free(emu):
    emu.call(emu.dll_export("T_SetFree"), (1,))
    put(emu, 1, b"Bob", career=12, level=3)
    assert [price(emu, item, 1) for item in ITEMS] == [0] * 8
    assert emu.call(emu.dll_export("T_DiceCost")) == 0
    set_money(emu, 0)
    assert buy(emu, "Advanced Career Training", 1) is None and buy(emu, "Career Change", 1) is None
    assert charges(emu) == [] and money(emu) == 0
    put(emu, 1, b"Bob", career=12, level=7)
    assert price(emu, "Advanced Career Training", 1) == -1                     # still nothing at Master


@pytest.mark.parametrize("item", ITEMS)
def test_a_family_that_cannot_afford_it_is_refused_with_nothing_changed(emu, item):
    put(emu, 0, career=-1, likes=(0, -1, -1), dislikes=(0, 1, -1))
    put(emu, 1, b"Bob", career=12, level=2, likes=(0, -1, -1), dislikes=(0, 1, -1))
    who = 0 if item == "Boarding School" else 1
    cost = price(emu, item, who)
    set_money(emu, cost - 1)
    before = emu.read(villager(who), STRIDE)
    assert buy(emu, item, who) == "You don't have enough money for that."
    assert money(emu) == cost - 1 and charges(emu) == []
    assert emu.read(villager(who), STRIDE) == before
    assert [x for x in emu.log if x[0] not in ("roll",)] == []                 # no game call at all


def test_time_warp(emu):
    put(emu, 0, career=12)
    set_money(emu, 2500)
    assert buy(emu, "Time Warp") is None
    names = [x[0] for x in emu.log]
    assert names.index("timeflow") < names.index("realtime") and charges(emu) == [-2000.0]
    assert money(emu) == 500


def test_adoption_services_a_three_year_old_of_either_sex(emu):
    put(emu, 0, career=12)
    for sex in (0, 1):
        emu.log.clear()
        emu.rolls = [sex]
        set_money(emu, 4000)
        assert buy(emu, "Adoption Services") is None
        assert ("roll", 2) in emu.log                                          # either sex, equally likely
        assert ("spawn", 1, sex, 60) in emu.log                                # voice 1, 3 years = 60 units
        assert ("add offspring", 0x5AB908, villager(5)) in emu.log            # into the family tree as a child
        assert charges(emu) == [-4000.0] and money(emu) == 0


def test_boarding_school_children_only(emu):
    put(emu, 0, career=-1)
    put(emu, 1, b"Bob", career=12)
    set_money(emu, 5000)
    assert buy(emu, "Boarding School", 1) == "Boarding School is for children only."
    assert charges(emu) == []
    assert buy(emu, "Boarding School", 0) is None
    assert ("left home", villager(0)) in emu.log
    event = [x for x in emu.log if x[0] == "life event"]
    assert [(x[1], x[2], x[4]) for x in event] == [(emu.gs, 5, 0xFFFFFFFF)]   # "is going to college"
    assert charges(emu) == [-1500.0]


def test_systematic_desensitization_removes_every_dislike(emu):
    put(emu, 1, b"Bob", career=12, dislikes=(0, 1, 2))
    set_money(emu, 2500)
    assert buy(emu, "Systematic Desensitization", 1) is None
    assert [emu.rs32(villager(1) + 0x1362C + 4 * k) for k in range(3)] == [-1, -1, -1]
    assert charges(emu) == [-2500.0]
    assert buy(emu, "Systematic Desensitization", 1) == "This family member has no dislikes."
    assert charges(emu) == [-2500.0]


@pytest.mark.parametrize("before, roll, after", [(0, 0, 30), (24, 19, 49), (25, 0, 55), (49, 19, 74),
                                                 (50, 0, 55), (60, 19, 84), (90, 19, 100)])
def test_psychotherapy_follows_vf2s_bands(emu, before, roll, after):
    put(emu, 1, b"Bob", career=12, happiness=before)
    emu.rolls = [roll]
    set_money(emu, 1750)
    assert buy(emu, "Psychotherapy", 1) is None
    assert ("roll", 20) in emu.log
    assert emu.rs32(villager(1) + 0x2AD4 + 0x38) == after and charges(emu) == [-1750.0]


def test_higher_learning_one_new_like_into_a_free_place(emu):
    # likes: 0 running, 1 cooking, 2 reading, 3 gardening, 4 music, 5 painting; dislikes: 0 cooking, 1 music
    put(emu, 1, b"Bob", career=12, likes=(0, -1, 2), dislikes=(0, 1, -1))
    emu.rolls = [0]                       # the first like not already liked: cooking, which is also a dislike
    set_money(emu, 1000)
    assert buy(emu, "Higher Learning Classes", 1) is None
    assert ("roll", 4) in emu.log                                              # 6 likes, 2 already liked
    assert [emu.rs32(villager(1) + 0x13620 + 4 * k) for k in range(3)] == [0, 1, 2]
    assert [emu.rs32(villager(1) + 0x1362C + 4 * k) for k in range(3)] == [-1, 1, -1]   # cooking: no dislike
    assert charges(emu) == [-1000.0]
    set_money(emu, 1000)
    assert buy(emu, "Higher Learning Classes", 1) == "Every like place is already full."
    assert charges(emu) == [-1000.0]


def test_advanced_career_training_and_career_change(emu):
    put(emu, 0, career=-1)
    put(emu, 1, b"Bob", career=12, level=4)
    set_money(emu, 10000)
    assert buy(emu, "Advanced Career Training", 0) == "Advanced Career Training is for adults with a career."
    assert buy(emu, "Advanced Career Training", 1) is None
    assert ("advance career", villager(1) + 0x2B6C, villager(1), 0, 1) in \
        [(x[0], x[1], x[2], x[3] & 0xFF, x[4] & 0xFF) for x in emu.log if x[0] == "advance career"]
    assert charges(emu) == [-5500.0]                                           # $1,100 x (4 + 1)
    put(emu, 1, b"Bob", career=12, level=7)
    assert buy(emu, "Advanced Career Training", 1) == "This family member is already a Master: nothing to train."
    assert buy(emu, "Career Change", 0) == "Career Change is for adults with a career."
    assert buy(emu, "Career Change", 1) is None
    assert ("reset career", villager(1) + 0x2B6C) in emu.log
    assert charges(emu) == [-5500.0, -1200.0]


def test_force_successful_pregnancy_needs_the_setting(emu):
    assert emu.call(emu.dll_export("T_ForceArmed"), (1,)) == 0                # armed, but off: nothing
    emu.checked = {emu.call(emu.dll_export("T_Id"), (0,))}
    assert emu.call(emu.dll_export("T_ReadArmed")) & 1 == 0                  # the box cannot arm it
    emu.call(emu.dll_export("T_SetFree"), (1,))
    assert emu.call(emu.dll_export("T_ForceArmed"), (1,)) == 1
    assert emu.call(emu.dll_export("T_ReadArmed")) & 1 == 1


def test_the_free_buttons_are_hidden_without_the_setting(emu):
    for which in range(3):
        emu.call(emu.dll_export("T_Hide"), (which,))
    ids = [emu.call(emu.dll_export("T_Id"), (k,)) for k in range(3)]
    assert emu.shown == {i: 0 for i in ids}                                    # SW_HIDE
    emu.shown.clear()
    emu.call(emu.dll_export("T_SetFree"), (1,))
    for which in range(3):
        emu.call(emu.dll_export("T_Hide"), (which,))
    assert emu.shown == {}


def test_get_for_free_anti_spam_and_clothing_are_refused_without_the_setting(emu):
    flag = emu.gs + 0x1CC
    emu.call(emu.dll_export("T_FleaFree"))
    emu.call(emu.dll_export("T_AntiSpam"))
    emu.call(emu.dll_export("T_Appearance"))
    assert [x[1] for x in emu.log if x[0] == "message"] == [NEEDED] * 3
    assert emu.read(flag, 1) == b"\0" and emu.dialogs == []
    emu.log.clear()
    emu.call(emu.dll_export("T_FleaBuy"))                                      # Buy never needs it
    assert [x[1] for x in emu.log if x[0] == "message"] == ["Pick an item first."]
    emu.log.clear()
    emu.call(emu.dll_export("T_SetFree"), (1,))
    emu.call(emu.dll_export("T_FleaFree"))
    emu.call(emu.dll_export("T_AntiSpam"))
    emu.call(emu.dll_export("T_Appearance"))
    assert [x[1] for x in emu.log if x[0] == "message"] == ["Pick an item first."]   # past the gate
    assert emu.read(flag, 1) == b"\x01" and len(emu.dialogs) == 1             # installed; the page opened
