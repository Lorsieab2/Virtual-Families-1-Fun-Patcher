"""Two fixes in vf1fun.dll, each proved by running the vanilla game's code (and the DLL's own code) in unicorn.

* Villager Cheats, Cure illnesses: it now also ends a mild or a serious infection, the two flags at villager
  +0x2B54 / +0x2B55 (CVillagerState +0x80 / +0x81), exactly as the game's own full cures clear them: Vancomycin
  (the drop handler, 0x446B65 / 0x446B6C) and the Imported Candy (0x443A0D / 0x443A13).
* Fix Vanilla Game Bugs, Pet Turtle: the store's offer check for the turtle (0x4495BC) tests for the dog (pet kind
  1) instead of the turtle (kind 2), so a family with a dog is never offered the turtle. The DLL changes the
  compare's immediate at 0x4495DC to 2, after checking the stock compare-and-jump bytes.

A small harness DLL that includes native/vf1fun/vf1fun.cpp (built with native/build.bat's settings) exports the two
static functions; the vanilla exe (VF1_VANILLA_DIR) and that DLL share one unicorn address space (tests/kids_emu.py).
The source checks run everywhere; the rest needs the vanilla game and the MSVC toolchain, and skips without them."""
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
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

VILLAGER0 = 0x5B8898 + 0x14640           # CVillagerManager::GetVillager(0)
STATE = VILLAGER0 + 0x2AD4               # its CVillagerState
PET = 0x513CC0 + 0x2BE4                  # the family's pet (0x4342B0 with index 0): +0x1BE4 present, +0x1BE0 kind
KINDS = {"cat": 0, "dog": 1, "turtle": 2}
OFFER_CHECK = {61: 0x449573, 62: 0x449597, 63: 0x4495BC}   # Pet Cat, Pet Dog, Pet Turtle
NEXT_ITEM, OFFERED = 0x4495E6, 0x4495DF

HARNESS = r'''
#include "@SOURCE@"
extern "C" __declspec(dllexport) void __cdecl T_Cure(int i) { CureVillager(i); }
extern "C" __declspec(dllexport) void __cdecl T_InstallTurtleFix() { InstallPetTurtleOfferFix(); }
'''


def _function(name):
    m = re.search(r"static void %s\(\) \{.*?\n\}\n|static void %s\(int i\) \{.*?\n\}\n" % (name, name), CPP, re.S)
    assert m, name + " is missing from vf1fun.cpp"
    return m.group(0)


# ===================================================================== always
def test_cure_clears_both_infection_flags():
    body = _function("CureVillager")
    assert "state[0x80] = 0;" in body and "state[0x81] = 0;" in body
    assert "state[0x5C + s] = 0;" in body and "*(unsigned *)(state + 0x64 + s * 4) = 0;" in body


def test_turtle_fix_is_part_of_fix_vanilla_game_bugs_and_checks_the_stock_bytes():
    block = re.search(r'if \(SettingOn\(L"FixVanillaGameBugs", true\)\) \{(.*?)\}', CPP, re.S).group(1)
    assert "InstallPetTurtleOfferFix();" in block
    assert CPP.count("InstallPetTurtleOfferFix();") == 1
    body = _function("InstallPetTurtleOfferFix")
    assert "0x83, 0xB8, 0xE0, 0x1B, 0x00, 0x00, 0x01" in body and "0x74, 0x07" in body
    assert "if (BytesAre(0x4495D6, stock, sizeof stock))" in body
    assert "WriteCode(0x4495DC, &turtle, 1);" in body and "turtle = 0x02;" in body


# ===================================================================== the vanilla exe
def _vanilla_exe() -> Path:
    if not os.environ.get("VF1_VANILLA_DIR"):
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    exe = Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe"
    if not exe.is_file():
        pytest.skip("VF1_VANILLA_DIR has no Virtual Families.exe")
    return exe


@pytest.fixture(scope="module")
def image():
    pefile = pytest.importorskip("pefile")
    pe = pefile.PE(str(_vanilla_exe()))
    img = pe.get_memory_mapped_image()
    return lambda va, n: bytes(img[va - 0x400000:va - 0x400000 + n])


def test_vanilla_full_cures_clear_the_same_two_flags(image):
    # Vancomycin (drop handler): mov byte ptr [esi+0x2B54], 0; mov byte ptr [esi+0x2B55], 0
    assert image(0x446B65, 14) == bytes.fromhex("c686542b000000 c686552b000000".replace(" ", ""))
    # Imported Candy (+20 health): mov byte ptr [esi+0x2B54], bl; mov byte ptr [esi+0x2B55], bl (bl = 0)
    assert image(0x443A0D, 12) == bytes.fromhex("889e542b0000889e552b0000")
    # Penicillin ends only the mild one
    assert image(0x446A91, 7) == bytes.fromhex("c686542b000000")


def test_vanilla_store_switch_and_pet_kinds(image):
    # the specials draw's switch (0x449511: movzx edx, [edi + 0x4496B6]; jmp [edx*4 + 0x4496BC])
    for item, target in OFFER_CHECK.items():
        index = image(0x4496B6 + item, 1)[0]
        assert struct.unpack("<I", image(0x4496BC + 4 * index, 4))[0] == target
    # the drop handler's kinds (0x443DA0): Pet Cat 0, Pet Dog 1, Pet Turtle 2
    assert image(0x443D9E, 15) == bytes.fromhex("33f683ed3e740a83ed01750a8d7502")
    # the cat's compare uses ebp (0), the dog's and the turtle's both use 1
    assert image(0x44958D, 6) == bytes.fromhex("39a8e01b0000")
    assert image(0x4495B1, 7) == bytes.fromhex("83b8e01b000001")
    assert image(0x4495D6, 9) == bytes.fromhex("83b8e01b0000017407")


# ===================================================================== emulated
@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    tmp_path = tmp_path_factory.mktemp("cure_turtle")
    src = tmp_path / "cure_turtle_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    dll = tmp_path / "cure_turtle_harness.dll"
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

    def virtual_protect(emu):          # VirtualProtect(address, size, new, &old)
        if emu.arg(2) == 0x40:         # PAGE_EXECUTE_READWRITE: a write is coming (the second call restores)
            emu.protects.append((emu.arg(0), emu.arg(1), emu.arg(2)))
        emu.w32(emu.arg(3), 0x20)      # PAGE_EXECUTE_READ, as the game's code pages are
        return 1, 16
    e.imports.update({
        "VirtualProtect": virtual_protect,
        "GetCurrentProcess": lambda emu: (0xFFFFFFFF, 0),
        "FlushInstructionCache": lambda emu: (1, 12),
    })
    return e


def _offered(e, item, pet):
    from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP
    from unicorn import UC_HOOK_CODE
    e.write(PET + 0x1BE4, bytes([0 if pet is None else 1]))
    e.w32(PET + 0x1BE0, 0 if pet is None else KINDS[pet])
    for reg, v in ((UC_X86_REG_EBP, 0), (UC_X86_REG_ESI, 0), (UC_X86_REG_EDI, item),
                   (UC_X86_REG_ESP, e.sp_top - 0x200)):
        e.setreg(reg, v)
    hit = []
    h = e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, size, user: hit.append(a), begin=OFFERED, end=OFFERED)
    try:
        e.uc.emu_start(OFFER_CHECK[item], NEXT_ITEM, count=10_000)
    finally:
        e.uc.hook_del(h)
    return bool(hit)


def _offers(e):
    return {pet: tuple(item for item in (61, 62, 63) if _offered(e, item, pet))
            for pet in (None, "cat", "dog", "turtle")}


def test_cure_ends_symptoms_and_both_infections(emu):
    for s in (0, 3, 6):
        emu.write(STATE + 0x5C + s, b"\x01")
        emu.w32(STATE + 0x64 + 4 * s, 5_000_000)
    emu.write(STATE + 0x80, b"\x01\x01")
    emu.write(STATE + 0x82, b"\xAA" * 6)           # the fields after the infections are left alone
    emu.w32(STATE + 0x0C, 50)                       # health is not the cure's business
    emu.call(emu.dll_export("T_Cure"), (0,))
    assert emu.read(STATE + 0x5C, 7) == b"\0" * 7
    assert emu.read(STATE + 0x64, 28) == b"\0" * 28
    assert emu.read(STATE + 0x80, 2) == b"\0\0"
    assert emu.read(STATE + 0x82, 6) == b"\xAA" * 6
    assert emu.r32(STATE + 0x0C) == 50


def test_stock_store_never_offers_the_turtle_to_a_family_with_a_dog(emu):
    assert _offers(emu) == {None: (61, 62, 63), "cat": (62, 63), "dog": (61,), "turtle": (61, 62, 63)}


def test_fixed_store_offers_the_turtle_unless_the_family_has_one(emu):
    emu.call(emu.dll_export("T_InstallTurtleFix"))
    assert emu.read(0x4495D6, 9) == bytes.fromhex("83b8e01b0000027407")
    assert emu.protects == [(0x4495DC, 1, 0x40)]
    assert _offers(emu) == {None: (61, 62, 63), "cat": (62, 63), "dog": (61, 63), "turtle": (61, 62)}


def test_turtle_fix_fails_open_and_installs_once(emu):
    emu.call(emu.dll_export("T_InstallTurtleFix"))
    emu.call(emu.dll_export("T_InstallTurtleFix"))  # a second Startup: already 2, the stock check fails, no write
    assert emu.protects == [(0x4495DC, 1, 0x40)]
    emu.write(0x4495DC, b"\x05")                    # something else changed the compare: left as it is
    emu.call(emu.dll_export("T_InstallTurtleFix"))
    assert emu.read(0x4495DC, 1) == b"\x05" and len(emu.protects) == 1
