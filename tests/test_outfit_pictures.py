"""Fix Vanilla Game Bugs: every outfit of a kind in the tray was the last one bought. Proved by running the vanilla
game's own code (and vf1fun.dll's) in unicorn, before and after the fix.

The stock game keeps ONE bought picture per kind (inventory 0x8957A0 +0x110 male, +0x114 female, copied from the
store's current picture +0x108 / +0x10C when one is bought, 0x4969A0). The tray (0x8958E8) keeps only (item, uses)
per place, so its draw (0x496F80 -> 0x496A10, 0x496A76 / 0x496A87) and the drop on a family member (0x446EEF:
0x496D10, then villager +0x2A64 = that) both use the last one bought. vf1fun.dll keeps each place's own picture in
memory and in a sidecar .dat per save (native/vf1fun/outfits.inc); nothing in the game's records or save changes.

A small harness DLL that includes native/vf1fun/vf1fun.cpp (built with native/build.bat's settings) exports the
fix's functions; the vanilla exe (VF1_VANILLA_DIR) and that DLL share one unicorn address space (tests/kids_emu.py).
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
OUTFITS = ROOT / "native" / "vf1fun" / "outfits.inc"
CPP = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
INC = OUTFITS.read_text(encoding="utf-8").replace("\r\n", "\n")
FEATURES = (ROOT / "native" / "vf1fun" / "features.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

INV, TRAY = 0x8957A0, 0x8958E8
VILLAGER0 = 0x5B8898 + 0x14640
BODY = 0x2A64
SITES = {0x449B58: 0x4973E0, 0x4976D6: 0x497520, 0x4977D4: 0x497520, 0x496FCD: 0x496A10, 0x49703C: 0x496A10,
         0x446EEF: 0x496D10}
SAVE_PATH = "C:\\Saves\\VF1\\Virtual Families1.ldw"
SIDECAR = "C:\\Saves\\VF1\\Virtual Families 1 Patcher Data\\Outfits\\Virtual Families1.ldw.dat"

HARNESS = r'''
#include "@SOURCE@"
extern "C" __declspec(dllexport) void __cdecl T_Install() { InstallOutfitPictureFix(); }
extern "C" __declspec(dllexport) int __cdecl T_On() { return gOutfitFixOn; }
extern "C" __declspec(dllexport) int __cdecl T_Picture(int place, int item) { return OutfitPicture(place, item); }
extern "C" __declspec(dllexport) void __cdecl T_AfterLoad(void *state, int slot) { OutfitsAfterLoad(state, slot); }
extern "C" __declspec(dllexport) void __cdecl T_AfterSave(void *state, int slot) { OutfitsAfterSave(state, slot); }
extern "C" __declspec(dllexport) void __cdecl T_Reset() { OutfitsReset(); }
'''


# ===================================================================== always
def test_the_fix_is_part_of_fix_vanilla_game_bugs():
    block = re.search(r'if \(SettingOn\(L"FixVanillaGameBugs", true\)\) \{(.*?)\}', CPP, re.S).group(1)
    assert "InstallOutfitPictureFix();" in block and CPP.count("InstallOutfitPictureFix();") == 1
    assert '#include "outfits.inc"' in CPP


def test_every_site_is_checked_before_anything_is_written():
    body = re.search(r"static void InstallOutfitPictureFix\(\) \{(.*?)\n\}\n", INC, re.S).group(1)
    checks, writes = body.split("return;  // not the stock game")
    for site, target in SITES.items():
        assert f"CallIs(0x{site:X}, 0x{target:X})" in checks
        assert f"RetargetCall(0x{site:X}," in writes
    assert "WriteCode" not in checks and "gOutfitFixOn = true;" in writes


def test_the_save_hooks_call_the_sidecar():
    assert "OutfitsAfterLoad(state, slot);" in FEATURES and "OutfitsAfterSave(state, slot);" in FEATURES
    assert "OutfitsReset();\n    GameStateInit(state);" in FEATURES


def test_the_fix_never_writes_the_games_records():
    # the only write into game memory outside the install: the lent field, put back right after the draw
    assert len(re.findall(r"^\s+\*field = ", INC, re.M)) == 2 and "*field = kept;" in INC


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


def test_vanilla_keeps_one_bought_picture_per_kind(image):
    # 0x4969A0: item 18 copies +0x108 to +0x110, item 19 +0x10C to +0x114
    assert image(0x4969BB, 37).hex() == ("83fa12750f8b9108010000899110010000c2040083fa13750c8b810c01000089811401"
                                         "0000")
    # 0x496D10: 64 gives +0x110, 65 gives +0x114
    assert image(0x496D19, 6) == bytes.fromhex("8b8110010000") and image(0x496D27, 6) == bytes.fromhex("8b8114010000")
    # the drop handler puts it on: villager +0x2A64 = 0x496D10(64 / 65)
    assert image(0x446EF9, 6) == bytes.fromhex("8987642a0000")
    for site, target in SITES.items():
        assert image(site, 5) == b"\xE8" + struct.pack("<i", target - (site + 5))


# ===================================================================== emulated
@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    tmp_path = tmp_path_factory.mktemp("outfits")
    src = tmp_path / "outfits_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    dll = tmp_path / "outfits_harness.dll"
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


class Files:
    """The DLL's kernel32 file calls answered from a dict (path -> bytes); nothing touches the disk."""

    def __init__(self):
        self.disk = {}
        self.dirs = set()
        self.handles = {}
        self.locked = set()
        self.error = 0
        self.next = 0x100

    def install(self, e):
        def create(emu):
            path, access, disposition = emu.cstr(emu.arg(0)), emu.arg(1), emu.arg(4)
            if path in self.locked:
                self.error = 32
                return 0xFFFFFFFF, 28
            if disposition == 3 and path not in self.disk:   # OPEN_EXISTING
                self.error = 2
                return 0xFFFFFFFF, 28
            if disposition == 2:                              # CREATE_ALWAYS
                self.disk[path] = b""
            self.next += 4
            self.handles[self.next] = [path, 0]
            return self.next, 28

        def read(emu):
            h, buf, n, got = emu.arg(0), emu.arg(1), emu.arg(2), emu.arg(3)
            path, pos = self.handles[h]
            data = self.disk[path][pos:pos + n]
            emu.write(buf, data)
            emu.w32(got, len(data))
            self.handles[h][1] += len(data)
            return 1, 20

        def write(emu):
            h, buf, n, done = emu.arg(0), emu.arg(1), emu.arg(2), emu.arg(3)
            path = self.handles[h][0]
            self.disk[path] += emu.read(buf, n)
            emu.w32(done, n)
            return 1, 20

        def move(emu):
            a, b, flags = emu.cstr(emu.arg(0)), emu.cstr(emu.arg(1)), emu.arg(2)
            if b in self.disk and not flags & 1:
                self.error = 183
                return 0, 12
            self.disk[b] = self.disk.pop(a)
            return 1, 12

        def attributes(emu):
            return (0x80 if emu.cstr(emu.arg(0)) in self.disk else 0xFFFFFFFF), 4

        def mkdir(emu):
            self.dirs.add(emu.cstr(emu.arg(0)))
            return 1, 8

        def delete(emu):
            self.disk.pop(emu.cstr(emu.arg(0)), None)
            return 1, 4
        e.imports.update({
            "CreateFileA": create, "ReadFile": read, "WriteFile": write, "CloseHandle": lambda emu: (1, 4),
            "FlushFileBuffers": lambda emu: (1, 4), "MoveFileExA": move, "GetFileAttributesA": attributes,
            "CreateDirectoryA": mkdir, "DeleteFileA": delete, "GetLastError": lambda emu: (self.error, 0),
            "Sleep": lambda emu: (0, 4),
        })


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
    e.files = Files()
    e.files.install(e)
    # the game's seams: graphics and sounds only (the tray's place redraw, the item draw, the cursor, the
    # family member's reaction); every other step is the game's own code
    e.draws = []
    e.rolls = []
    e.clock = 1000
    e.seam(0x497360, lambda emu: (0, 4))                       # the tray place's widget refresh
    e.seam(0x48BB40, lambda emu: (0, 4))                       # the family member's reaction

    def draw(emu):                                             # 0x496A10(x, y, item, ...): what it would draw
        item = emu.arg(2)
        picture = emu.r32(INV + (0x110 if item == 64 else 0x114)) if item in (64, 65) else None
        emu.draws.append((emu.arg(1), item, picture))
        return 0, 0x18
    e.seam(0x496A10, draw)
    e.seam(0x4083B0, lambda emu: (emu.w32(emu.arg(0), 300) or emu.w32(emu.arg(0) + 4, 300) or emu.arg(0), 4))
    e.seam(0x403650, lambda emu: (emu.rolls.pop(0), 0))       # GetRandom(n)
    e.seam(0x422320, lambda emu: (emu.clock, 0))              # CGameTime::Seconds
    e.write(TRAY, b"\0" * 0xA8)
    e.w32(TRAY + 0x88, 40)                                    # each place 40 high, from y = 100
    e.w32(TRAY + 0x8C, 10)
    e.w32(TRAY + 0x90, 100)
    e.w32(TRAY + 0x94, 50)
    e.w32(TRAY + 0x98, 100 + 8 * 40 - 1)
    e.call(0x497580, ecx=TRAY)                                # the tray's reset: gloves and the Ball
    e.w32(INV + 18 * 4, 0xFFFFFFFF)                           # outfits: unlimited stock, as the table gives
    e.w32(INV + 19 * 4, 0xFFFFFFFF)
    return e


def redraw(e, male, female):
    """The store's 4-hourly outfit draw 0x496C70, forced (as on a store opening when it is due)."""
    e.rolls[:] = [male, female]
    e.call(0x496C70, (1,), ecx=INV)


def buy(e, item):
    """The store's buy from 0x449AF6 to after the tray add (0x449B5D), with item 18 / 19 in the place."""
    from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESP
    place, scene = e.alloc(0x20), e.alloc(0x40)
    e.w32(place, item)
    e.setreg(UC_X86_REG_EDI, place)
    e.setreg(UC_X86_REG_EBX, scene)
    e.setreg(UC_X86_REG_ESP, e.sp_top - 0x400)
    e.uc.emu_start(0x449AF6, 0x449B5D, count=100_000)


def tray(e):
    return [(e.r32(TRAY + 8 * k), e.rs32(TRAY + 8 * k + 4)) for k in range(8)]


def drawn(e):
    """The tray's draw 0x496F80: the picture each outfit place shows."""
    e.draws.clear()
    e.call(0x496F80, ecx=TRAY)
    return {(y - 100) // 40: picture for y, item, picture in e.draws if item in (64, 65)}


def put_on(e, place, item=64):
    """Drag the outfit at `place` onto family member 0 (male) and drop it: the drop handler 0x446EB9..0x446F04."""
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESI, UC_X86_REG_ESP
    e.w32(TRAY + 0xA0, place)
    e.write(TRAY + 0xA4, b"\x00\x01")
    e.w32(VILLAGER0 + 0x2A38, 0 if item == 64 else 1)
    e.w32(VILLAGER0 + BODY, 99)
    e.setreg(UC_X86_REG_EAX, item)
    e.setreg(UC_X86_REG_ESI, 0)
    e.setreg(UC_X86_REG_ESP, e.sp_top - 0x400)
    e.uc.emu_start(0x446EB9, 0x446F04, count=100_000)
    return e.r32(VILLAGER0 + BODY)


def dragged(e, place):
    """The dragged item's draw 0x496FE0 (tray +0xA0)."""
    e.w32(TRAY + 0xA0, place)
    e.write(TRAY + 0xA4, b"\x01\x00")
    e.draws.clear()
    e.call(0x496FE0, ecx=TRAY)
    return [picture for y, item, picture in e.draws]


def scenario(e):
    redraw(e, 7, 31)
    buy(e, 18)                    # a Male Outfit at picture 7
    e.clock += 14_401
    redraw(e, 12, 40)
    buy(e, 18)                    # a second Male Outfit, at picture 12
    buy(e, 19)                    # a Female Outfit at picture 40


def test_stock_every_outfit_of_a_kind_is_the_last_one_bought(emu):
    scenario(emu)
    assert tray(emu)[3:6] == [(64, 1), (64, 1), (65, 1)]
    assert drawn(emu) == {3: 12, 4: 12, 5: 40}           # the first Male Outfit now shows 12
    assert dragged(emu, 3) == [12]
    assert put_on(emu, 3) == 12                           # ... and puts on 12
    assert tray(emu)[3] == (0, 0)                         # used up


def test_fixed_each_outfit_keeps_its_own_picture(emu):
    emu.call(emu.dll_export("T_Install"))
    assert emu.call(emu.dll_export("T_On")) == 1
    assert sorted(a for a, n in emu.protects) == sorted(s + 1 for s in SITES)
    scenario(emu)
    assert drawn(emu) == {3: 7, 4: 12, 5: 40}
    assert dragged(emu, 3) == [7] and dragged(emu, 4) == [12]
    assert emu.r32(INV + 0x110) == 12 and emu.r32(INV + 0x114) == 40   # the saved fields are the stock game's
    assert put_on(emu, 3) == 7                            # the first one puts on its own picture
    assert put_on(emu, 4) == 12
    assert tray(emu)[3:5] == [(0, 0), (0, 0)]


def test_fixed_pictures_move_with_the_outfits(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    # drag the first Male Outfit (place 3) to place 6 (y = 100 + 6 * 40 + 5) and drop it in the tray
    emu.w32(TRAY + 0xA0, 3)
    emu.write(TRAY + 0xA4, b"\x01\x00")
    emu.call(0x497740, (20, 345), ecx=TRAY)
    assert tray(emu)[3] == (0, 0) and tray(emu)[6] == (64, 1)
    assert drawn(emu) == {4: 12, 5: 40, 6: 7}
    # swap it with the Female Outfit
    emu.w32(TRAY + 0xA0, 6)
    emu.write(TRAY + 0xA4, b"\x01\x00")
    emu.call(0x497740, (20, 305), ecx=TRAY)
    assert drawn(emu) == {4: 12, 5: 7, 6: 40}
    assert put_on(emu, 5) == 7 and put_on(emu, 6, 65) == 40


def test_fix_fails_open_when_any_site_differs(emu):
    emu.write(0x49703C, b"\xE8\0\0\0\0")
    emu.call(emu.dll_export("T_Install"))
    assert emu.call(emu.dll_export("T_On")) == 0 and emu.protects == []
    scenario(emu)
    assert drawn(emu) == {3: 12, 4: 12, 5: 40}        # the stock game, untouched


def test_fix_installs_once(emu):
    emu.call(emu.dll_export("T_Install"))
    emu.call(emu.dll_export("T_Install"))
    assert len(emu.protects) == len(SITES)


def fake_state(e):
    """theGameState with a vtable whose +0xC (the slot's save path) answers SAVE_PATH."""
    text = e.alloc(64)
    e.write(text, SAVE_PATH.encode() + b"\0")
    code = e.fake_code(b"\xB8" + struct.pack("<I", text) + b"\xC2\x04\x00")   # mov eax, text; ret 4
    vtable = e.alloc(0x40)
    e.w32(vtable + 0xC, code)
    state = e.alloc(0x10)
    e.w32(state, vtable)
    return state


def saved_state(e):
    """What a save holds that the sidecar describes: the tray (0x40 bytes) and the inventory (0x140)."""
    return e.read(TRAY, 0x40), e.read(INV - 0xC, 0x140)


def load(e, state, saved):
    """A new session: the game's Load puts the save's tray and inventory back, then the DLL reads the sidecar."""
    e.call(e.dll_export("T_Reset"))
    e.write(TRAY, b"\0" * 0x40)
    e.write(TRAY, saved[0])
    e.write(INV - 0xC, saved[1])
    e.call(e.dll_export("T_AfterLoad"), (state, 1))


def test_sidecar_keeps_the_pictures_across_save_and_load(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    emu.files.disk[SAVE_PATH] = b"the save the game wrote" * 10
    emu.call(emu.dll_export("T_AfterSave"), (state, 1))
    saved = saved_state(emu)
    blob = emu.files.disk[SIDECAR]
    assert len(blob) == 148 and blob[:8] == b"VF1OUTFT" and blob[12:19] == b"VF1V101"
    assert struct.unpack_from("<8i", blob, 108) == (-1, -1, -1, 7, 12, 40, -1, -1)
    assert "C:\\Saves\\VF1\\Virtual Families 1 Patcher Data\\Outfits" in emu.files.dirs
    assert emu.files.disk[SAVE_PATH] == b"the save the game wrote" * 10   # the save is never written
    assert set(emu.files.disk) == {SAVE_PATH, SIDECAR}                     # the .tmp was swapped in
    # mess the session up, then load the save again
    redraw(emu, 1, 2)
    buy(emu, 18)
    load(emu, state, saved)
    assert drawn(emu) == {3: 7, 4: 12, 5: 40}
    assert put_on(emu, 3) == 7


def test_a_save_edited_by_rename_or_game_speed_keeps_the_pictures(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    emu.call(emu.dll_export("T_AfterSave"), (state, 1))
    saved = saved_state(emu)
    emu.files.disk[SAVE_PATH] = b"renamed" * 10              # the file's bytes are not what binds it
    load(emu, state, saved)
    assert drawn(emu) == {3: 7, 4: 12, 5: 40}


def test_old_save_without_a_sidecar_loads_as_the_stock_game(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    load(emu, state, saved_state(emu))
    assert drawn(emu) == {3: 12, 4: 12, 5: 40}
    assert put_on(emu, 3) == 12
    assert SIDECAR not in emu.files.disk                       # loading writes nothing


@pytest.mark.parametrize("change", ["tray", "bought", "store", "redraw"])
def test_sidecar_for_another_state_of_the_save_is_not_used(emu, change):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    emu.call(emu.dll_export("T_AfterSave"), (state, 1))
    tray_bytes, inventory = map(bytearray, saved_state(emu))
    if change == "tray":
        tray_bytes[3 * 8 + 4] = 0                              # the first Male Outfit used while the fix was off
    else:
        field = {"bought": 0x110, "store": 0x108, "redraw": 0x118}[change] + 0xC
        inventory[field] ^= 1
    blob = emu.files.disk[SIDECAR]
    load(emu, state, (bytes(tray_bytes), bytes(inventory)))
    assert all(emu.call(emu.dll_export("T_Picture"), (k, 64)) == 0xFFFFFFFF for k in range(8))
    assert emu.files.disk[SIDECAR] == blob                     # kept as it is until the next save


def test_damaged_sidecar_is_moved_aside_never_overwritten(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    emu.files.disk[SIDECAR] = b"not a sidecar"
    load(emu, state, saved_state(emu))
    aside = SIDECAR[:-4] + ".unreadable-1.dat"
    assert emu.files.disk[aside] == b"not a sidecar" and SIDECAR not in emu.files.disk
    assert drawn(emu) == {3: 12, 4: 12, 5: 40}


def test_tampered_sidecar_is_moved_aside(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    emu.call(emu.dll_export("T_AfterSave"), (state, 1))
    saved = saved_state(emu)
    blob = bytearray(emu.files.disk[SIDECAR])
    blob[108 + 3 * 4] = 77                                     # a picture out of range: the checksum fails too
    emu.files.disk[SIDECAR] = bytes(blob)
    load(emu, state, saved)
    assert SIDECAR[:-4] + ".unreadable-1.dat" in emu.files.disk
    assert drawn(emu) == {3: 12, 4: 12, 5: 40}


def test_locked_sidecar_is_never_replaced(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    state = fake_state(emu)
    emu.files.disk[SIDECAR] = b"held by another program"
    emu.files.locked.add(SIDECAR)
    load(emu, state, saved_state(emu))
    emu.files.locked.clear()
    emu.call(emu.dll_export("T_AfterSave"), (state, 1))
    assert emu.files.disk[SIDECAR] == b"held by another program"


def test_no_sidecar_is_made_while_no_outfit_is_known(emu):
    emu.call(emu.dll_export("T_Install"))
    state = fake_state(emu)
    emu.call(emu.dll_export("T_AfterSave"), (state, 1))
    assert SIDECAR not in emu.files.disk
    emu.call(emu.dll_export("T_AfterSave"), (state, 21))      # the game's backup slots are never described
    assert not emu.files.disk


def test_a_new_family_forgets_the_pictures(emu):
    emu.call(emu.dll_export("T_Install"))
    scenario(emu)
    emu.call(emu.dll_export("T_Reset"))
    assert all(emu.call(emu.dll_export("T_Picture"), (k, 64)) == 0xFFFFFFFF for k in range(8))
