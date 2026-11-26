#!/usr/bin/env python3
"""Skin Tones for Virtual Families 1: every site the companion DLL vf1skin.dll relies on, proved against the vanilla
executable, and the C header the DLL is built from.

    vf1_skin_sites.py --exe "<vanilla>\\Virtual Families.exe" [--write]

VF1 has no ASLR and one executable, so every address is fixed. Each pin is the exact bytes of stock code (the
displacement of every call/jmp rel32 is a wildcard: other companions retarget some of those calls). The DLL compares
the live bytes with every pin before it writes anything and installs nothing on a difference.

Who draws a person, and how the DLL knows who it is (every draw of a cell of a sheet ends in
ldwGameWindowImpl::BlitRectWithAlpha 0x404C30):

* the house (and the menu's background family): CVillagerManager::DrawVillager 0x48B4D0 (slot, alpha), entry hook;
* the held baby: the carried-items draw 0x48A100, called at 0x48B7DE and 0x48B9F9 inside DrawVillager (call
  retargets): while the mother carries (+0x2AF8 not 0) it draws carrying.png cell 3 once per baby (+0x2AFC);
* Details, Adoption and the marriage proposal: CVillager's portrait 0x486B60 (`this`), entry hook;
* the event pop-up's picked person: CVillager 0x486D20 (`this`), entry hook;
* the Family Tree: the tree scene's draw 0x439BA0 calls DrawParent 0x439790 at 0x439CC6 (the record's parent 1, the
  record in edi) and 0x439E01 (parent 2, edi), and DrawChild 0x439930 at 0x439FA0 (child k, ebp = the record +
  k * 0xD8). The three calls are retargeted; the record's place comes from those registers, which this tool proves
  are not written between where they are set and the calls.

The plain blit 0x404BC0 (the unscaled grid draws 0x4088B0 / 0x408920) is not reached from any of these (by direct
calls; tests/test_skin_tones.py runs every draw and records that it is never entered).

Who gets a tone: the conception's Impregnate call 0x48EBB2 (the same site vf1fun.dll and vf1logs.dll retarget; the
DLL chains), after which the babies are the slots theGameState +0x1B120 / +0x1B124 / +0x1B128; renames: the two calls
of CFamilyTree::ChangeName 0x481C20 (0x44BCF8, 0x44BDF5); loads and saves: theGameState's vtable slots 0x4B5E68 /
0x4B5E6C (vf1fun.dll hooks them first; the DLL chains, as vf1kids, vf1logs and vf1revive do).

Where the sheets are: theGraphicsManager's image table 0x4F2D00 (0x30 bytes an entry, the id at +0): GetImageGrid
0x44F3E0 keeps an entry's grid at +0x2C once it is made (and makes it on first use); the DLL only reads +0x2C, so it
never loads a picture the game has not loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vf1_logs_sites as L  # noqa: E402
from capstone.x86 import X86_REG_EBP as _EBP, X86_REG_EDI as _EDI  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "native" / "vf1skin" / "vf1skin_sites.h"
VANILLA_EXE_SHA256 = L.VANILLA_EXE_SHA256

FAMILY_TREE = L.FAMILY_TREE
VILLAGER_MANAGER = L.VILLAGER_MANAGER
GAME_STATE_INSTANCE = L.GAME_STATE_INSTANCE
FAMILY_RECORD_SIZE = L.FAMILY_RECORD_SIZE
FAMILY_RECORD_BASE = L.FAMILY_RECORD_BASE
TREE_GENERATIONS = L.TREE_GENERATIONS
RECORD_PARENT1 = L.RECORD_PARENT1
RECORD_PARENT2 = L.RECORD_PARENT2
RECORD_CHILD_COUNT = L.RECORD_CHILD_COUNT
RECORD_CHILDREN = L.RECORD_CHILDREN
TREE_CHILDREN = L.TREE_CHILDREN
PEEP_RECORD_SIZE = L.PEEP_RECORD_SIZE
PEEP_VALID = L.PEEP_VALID
PEEP_GENDER = L.PEEP_GENDER
PEEP_HEAD = L.PEEP_HEAD
PEEP_BODY = L.PEEP_BODY
PEEP_SLOT = L.PEEP_SLOT
VILLAGER_ARRAY_OFFSET = L.VILLAGER_ARRAY_OFFSET
VILLAGER_STRIDE = L.VILLAGER_STRIDE
HOUSEHOLD_SLOTS = L.HOUSEHOLD_SLOTS
VILLAGER_PRESENT = L.VILLAGER_PRESENT
VILLAGER_AGE = L.VILLAGER_AGE
VILLAGER_GENDER = L.VILLAGER_GENDER
VILLAGER_NAME = L.VILLAGER_NAME
VILLAGER_NAME_LEN = L.VILLAGER_NAME_LEN
VILLAGER_HEAD = L.VILLAGER_HEAD
VILLAGER_BODY = L.VILLAGER_BODY
VILLAGER_PARENT1_NAME = 0x2A68     # bio +0x34: the first parent's name (0x1A bytes), then the second's
VILLAGER_PARENT2_NAME = 0x2A82
VILLAGER_HEALTH = L.VILLAGER_HEALTH
VILLAGER_PREGNANT = L.VILLAGER_PREGNANT
VILLAGER_CARRIED = L.VILLAGER_CARRIED
GAME_STATE_RESERVED_BABY = L.GAME_STATE_RESERVED_BABY
GS_VTABLE_LOAD = L.GS_VTABLE_LOAD
GS_VTABLE_SAVE = 0x4B5E6C
LDW_PATH_VSLOT = L.LDW_PATH_VSLOT
SAVE_BACKUP_OFFSET = 20
IMAGE_TABLE = 0x4F2D00
IMAGE_ENTRY_SIZE = 0x30
IMAGE_ENTRY_GRID = 0x2C            # the grid GetImageGrid made (0 before)
IMAGE_TABLE_ENTRIES = 0xD6         # 0x44F2D0: ids 0..0xD5 are tried at their own index first
IMAGE_TABLE_END = 0x4F5520         # ... then the table is searched up to here
GRID_HOLDER = 0x04                 # ldwImageGrid: +4 the file's holder (its first dword: the SDL surface)
GRID_CELL_HEIGHT = 0x14
GRID_FILES = 0x30                  # a grid of two files: the holders, one a file
TREE_PARENT1_REGISTER_OFFSET = RECORD_PARENT1     # edi + 4 at 0x439CC6
TREE_PARENT2_REGISTER_OFFSET = RECORD_PARENT2     # edi + 0xDC at 0x439E01
TREE_CHILD_REGISTER_OFFSET = RECORD_CHILDREN      # ebp + 0x1B8 at 0x439FA0

# name, VA, length, note
PINS = [
    ("blit", 0x404C30, 0x13, "ldwGameWindowImpl::BlitRectWithAlpha: sub esp,5Ch / fldz / its first arguments"),
    ("draw_villager", 0x48B4D0, 0x40, "CVillagerManager::DrawVillager(slot, alpha): the villager at manager + "
                                      "0x14640 + slot * 0x145FC"),
    ("dv_carried_1", 0x48B7D2, 0x11, "DrawVillager: the carried-items draw (villager, x, y)"),
    ("dv_carried_2", 0x48B9E6, 0x18, "DrawVillager's second carried-items draw"),
    ("carried", 0x48A100, 0x11D, "the carried-items draw: carrying.png cell 3 once per baby while pregnant"),
    ("portrait", 0x486B60, 0x0D, "CVillager's portrait (Details, Adoption, the marriage proposal): sub esp,28h"),
    ("event_portrait", 0x486D20, 0x0D, "CVillager's event pop-up portrait: sub esp,38h / mov al,[esp+4Ch]"),
    ("tree_scene", 0x439BC5, 0x3E0, "the Family Tree scene's draw: GetRecord(gen) in edi, DrawParent x2, DrawChild"),
    ("conception_call", 0x48EBA5, 0x12, "the try-for-a-baby step's Impregnate call"),
    ("change_name_1", 0x44BCED, 0x10, "the Details screen's rename: CFamilyTree::ChangeName(villager, name)"),
    ("change_name_2", 0x44BDEA, 0x10, "the second rename: CFamilyTree::ChangeName(villager, name)"),
    ("image_lookup", 0x44F2D0, 0x3D, "theGraphicsManager's table look-up: entry id at +0, 0x30 bytes, table 0x4F2D00"),
    ("image_grid", 0x44F485, 0x5B, "GetImageGrid: a grid of rows made once and kept at entry +0x2C"),
    ("vm_get_patriarch", 0x4899C0, 0x61, "CVillagerManager::GetPatriarch (the conception step passes his head and body)"),
    ("ldw_make_path", 0x4035F0, 0x59, "ldwGameState::MakeGameStatePath(slot): \"%s%d.ldw\""),
    ("gs_save_current", 0x4238E0, 0x3D, "theGameState::SaveCurrentGame: Save(0), Save(slot), Save(slot + 20)"),
]
PIN = {p[0]: p for p in PINS}

FUNCTIONS = {
    "BLIT": 0x404C30, "DRAW_VILLAGER": 0x48B4D0, "CARRIED": 0x48A100, "PORTRAIT": 0x486B60,
    "EVENT_PORTRAIT": 0x486D20, "DRAW_PARENT": 0x439790, "DRAW_CHILD": 0x439930, "IMPREGNATE": 0x4864D0,
    "CHANGE_NAME": 0x481C20, "GET_PATRIARCH": 0x4899C0, "GS_LOAD": 0x424A50, "GS_SAVE": 0x423790, "PLAIN_BLIT": 0x404BC0,
}

# Entry hooks: (pin, the whole instructions moved to the trampoline).
ENTRY_HOOKS = (("BLIT", "blit", 5), ("DRAW_VILLAGER", "draw_villager", 7), ("PORTRAIT", "portrait", 5),
               ("EVENT_PORTRAIT", "event_portrait", 7))

# Calls the DLL retargets: (pin, VA of the E8 byte, the stock target).
CALL_HOOKS = (
    ("dv_carried_1", 0x48B7DE, 0x48A100),
    ("dv_carried_2", 0x48B9F9, 0x48A100),
    ("tree_scene", 0x439CC6, 0x439790),
    ("tree_scene", 0x439E01, 0x439790),
    ("tree_scene", 0x439FA0, 0x439930),
    ("conception_call", 0x48EBB2, 0x4864D0),
    ("change_name_1", 0x44BCF8, 0x481C20),
    ("change_name_2", 0x44BDF5, 0x481C20),
)
CALL_HOOK_NAMES = ("CARRIED_1", "CARRIED_2", "TREE_PARENT1", "TREE_PARENT2", "TREE_CHILD", "CONCEPTION",
                   "CHANGE_NAME_1", "CHANGE_NAME_2")

CALLS = (
    ("conception_call", 0x48EBA5 + 0x0D, 0x4864D0),   # the step's Impregnate (the hooked call itself)
    ("tree_scene", 0x439BCE, 0x481700),       # CFamilyTree::GetRecord(gen) -> edi
    ("carried", 0x48A169, 0x44EC90),          # the baby's cell
)

NEG = L.NEG
CROSS = {
    "draw_villager": {VILLAGER_STRIDE, VILLAGER_ARRAY_OFFSET},
    "carried": {VILLAGER_PREGNANT, VILLAGER_CARRIED, 3},
    "portrait": {0x28},
    "image_lookup": {IMAGE_TABLE, IMAGE_TABLE_ENTRIES - 1, IMAGE_TABLE_END},
    "image_grid": {IMAGE_ENTRY_GRID},
    "ldw_make_path": {0x14},
    "gs_save_current": {0x38, SAVE_BACKUP_OFFSET},
    "tree_scene": {FAMILY_TREE, RECORD_PARENT2, RECORD_CHILDREN, PEEP_RECORD_SIZE,
                   RECORD_CHILDREN + PEEP_GENDER, RECORD_CHILDREN + PEEP_HEAD, RECORD_CHILDREN + PEEP_BODY,
                   RECORD_PARENT2 + PEEP_GENDER, RECORD_PARENT2 + PEEP_HEAD, RECORD_PARENT2 + PEEP_BODY},
}

# The registers the tree hooks read: (from, to, register, what it must be). No instruction in [from, to) writes it.
REGISTER_SPANS = (
    (0x439BD5, 0x439CC6, _EDI, "the generation's record (mov edi, eax at 0x439BD3)"),
    (0x439BD5, 0x439E01, _EDI, "the generation's record"),
    (0x439F33, 0x439FA0, _EBP, "the record + child * 0xD8 (lea ebp, [ecx + edi] at 0x439F31)"),
)

SiteError = L.SiteError


def _writes(exe, start: int, end: int, reg: int) -> list[int]:
    md = L._md()
    raw = exe.read(start, end - start)
    out = []
    for i in md.disasm(raw, start):
        _read, written = i.regs_access()
        if reg in written:
            out.append(i.address)
    return out


def image_entry(exe, image: int) -> int:
    """The table entry theGraphicsManager's look-up 0x44F2D0 finds for `image`: entry `image` when its id is `image`,
    else the first entry with that id."""
    direct = IMAGE_TABLE + image * IMAGE_ENTRY_SIZE
    if image < IMAGE_TABLE_ENTRIES and struct.unpack("<I", exe.read(direct, 4))[0] == image:
        return direct
    for at in range(IMAGE_TABLE, IMAGE_TABLE_END, IMAGE_ENTRY_SIZE):
        if struct.unpack("<I", exe.read(at, 4))[0] == image:
            return at
    raise SiteError(f"no image {image:#x}")


def validate(data: bytes) -> dict:
    if hashlib.sha256(data).hexdigest() != VANILLA_EXE_SHA256:
        raise SiteError("not the vanilla Virtual Families.exe the pins are taken from")
    exe = L.Exe(data)
    if exe.base != 0x400000:
        raise SiteError("not the VF1 image base")
    pins = {}
    for name, va, n, _note in PINS:
        raw = exe.read(va, n)
        if sum(i.size for i in L._md().disasm(raw, va)) != n:
            raise SiteError(f"{name}: not whole instructions")
        pins[name] = (va, raw, L.mask_for(raw, va))
    spans = sorted((va, va + n, name) for name, va, n, _note in PINS)
    for (a0, a1, an), (b0, _b1, bn) in zip(spans, spans[1:]):
        if b0 < a1:
            raise SiteError(f"pins {an} and {bn} overlap")
    for name, values in CROSS.items():
        va, raw, _m = pins[name]
        got = L._operands(raw, va)
        for v in values:
            if (v & 0xFFFFFFFF) not in got:
                raise SiteError(f"{name}: no operand {v:#x}")
    for pin, at, func in CALLS + CALL_HOOKS:
        va, raw, _m = pins[pin]
        if not va <= at <= va + len(raw) - 5:
            raise SiteError(f"{pin}: call {at:#x} outside the pin")
        if L.call_target(exe, at) != func:
            raise SiteError(f"{pin}+{at - va:#x}: calls {L.call_target(exe, at):#x}, not {func:#x}")
    for key, pin, stolen in ENTRY_HOOKS:
        va, raw, _m = pins[pin]
        if va != FUNCTIONS[key]:
            raise SiteError(f"{key}: the pin does not start at the function")
        sizes, total = [], 0
        for i in L._md().disasm(raw, va):
            if total >= stolen:
                break
            if i.mnemonic in ("call", "jmp") or i.mnemonic.startswith("j") or "eip" in i.op_str:
                raise SiteError(f"{key}: the stolen bytes hold a branch or an eip-relative operand")
            total += i.size
            sizes.append(i.size)
        if total != stolen:
            raise SiteError(f"{key}: {stolen} is not a whole number of instructions")
    callers = L.all_callers(exe, {0x48A100: None, 0x439790: None, 0x439930: None, 0x481C20: None,
                                  0x4864D0: None, 0x48B4D0: None, 0x486B60: None, 0x486D20: None})
    want = {0x48A100: [0x48B7DE, 0x48B9F9], 0x439790: [0x439CC6, 0x439E01], 0x439930: [0x439FA0],
            0x481C20: [0x44BCF8, 0x44BDF5], 0x4864D0: [0x48EBB2], 0x48B4D0: [0x44CBF9, 0x44CD8F, 0x44EB94],
            0x486B60: [0x436365, 0x43813B, 0x44B8EF], 0x486D20: [0x419DB5, 0x440B12]}
    for target, sites in want.items():
        if sorted(callers[target]) != sites:
            raise SiteError(f"{target:#x} has the callers {[hex(c) for c in callers[target]]}")
    for start, end, reg, what in REGISTER_SPANS:
        bad = _writes(exe, start, end, reg)
        if bad:
            raise SiteError(f"{what}: written at {[hex(b) for b in bad]}")
    if exe.read(0x439BD3, 2) != b"\x8b\xf8" or exe.read(0x439F31, 3) != b"\x8d\x2c\x39":
        raise SiteError("the tree's record registers are not set where they should be")
    for at, func in ((GS_VTABLE_LOAD, FUNCTIONS["GS_LOAD"]), (GS_VTABLE_SAVE, FUNCTIONS["GS_SAVE"]),
                     (0x4B5E40, PIN["ldw_make_path"][1])):
        if struct.unpack("<I", exe.read(at, 4))[0] != func:
            raise SiteError(f"theGameState vtable {at:#x} is not {func:#x}")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import vf1_skin_masks as M
    entries = []
    for name, image, part, rows in M.SHEETS:
        entry = image_entry(exe, image)
        eid, file_va, cols, erows = struct.unpack("<IIII", exe.read(entry, 16))
        stem = exe.cstr(file_va)
        if eid != image or erows != rows or not name.startswith(stem.replace(".png", "")):
            raise SiteError(f"image {image:#x} is {stem!r}, {cols} x {erows}, not {name}")
        entries.append(entry)
    pins["_image_entries"] = entries
    return pins


def render_header(pins: dict) -> str:
    arr = lambda b: ", ".join(f"0x{x:02X}" for x in b)  # noqa: E731
    out = [
        "// GENERATED by tools/vf1_skin_sites.py from the vanilla Virtual Families.exe. Do not edit.",
        "// Every pin is the exact bytes of stock code at its fixed address (VF1 has no ASLR); mask 1 = a",
        "// call/jmp displacement, which another hook may have retargeted. The DLL installs nothing unless",
        "// every pin matches.",
        "#pragma once",
        "",
        "struct SkinPin { const char *name; unsigned va; unsigned len; const unsigned char *bytes; const unsigned char *mask; };",
        "struct SkinCallHook { unsigned site; unsigned target; };",
        "struct SkinEntryHook { unsigned va; unsigned stolen; };",
        "",
    ]
    for key, value in sorted(globals().items()):
        if key.isupper() and isinstance(value, int) and not isinstance(value, bool):
            out.append(f"#define SKIN_{key} 0x{value:X}u")
    out.append("")
    for name, va in FUNCTIONS.items():
        out.append(f"#define SKIN_FN_{name} 0x{va:X}u")
    out.append("")
    entries = pins.pop("_image_entries")
    out.append("// each sheet's entry in the image table, in skin_masks.h's order (the entry's grid is at +0x2C)")
    out.append("static const unsigned SKIN_IMAGE_ENTRIES[] = { " + ", ".join(f"0x{e:X}u" for e in entries) + " };")
    out.append("")
    for name, (va, raw, mask) in pins.items():
        out.append(f"static const unsigned char spin_{name}[] = {{ {arr(raw)} }};")
        out.append(f"static const unsigned char smask_{name}[] = {{ {arr(mask)} }};")
    out.append("")
    out.append("static const SkinPin SKIN_PINS[] = {")
    for name, (va, raw, mask) in pins.items():
        out.append(f'    {{ "{name}", 0x{va:X}u, {len(raw)}u, spin_{name}, smask_{name} }},')
    out.append("};")
    out.append("")
    out.append("enum { " + ", ".join(f"SKIN_ENTRY_{k} = {i}" for i, (k, _p, _s) in enumerate(ENTRY_HOOKS)) + " };")
    out.append("static const SkinEntryHook SKIN_ENTRY_HOOKS[] = {")
    for key, _pin, stolen in ENTRY_HOOKS:
        out.append(f"    {{ 0x{FUNCTIONS[key]:X}u, {stolen}u }},   // {key}")
    out.append("};")
    out.append("")
    out.append("enum { " + ", ".join(f"SKIN_CALL_{n} = {i}" for i, n in enumerate(CALL_HOOK_NAMES)) + " };")
    out.append("static const SkinCallHook SKIN_CALL_HOOKS[] = {")
    for (_pin, site, target), n in zip(CALL_HOOKS, CALL_HOOK_NAMES):
        out.append(f"    {{ 0x{site:X}u, 0x{target:X}u }},   // {n}")
    out.append("};")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, help="the vanilla Virtual Families.exe")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    data = Path(args.exe).read_bytes()
    pins = validate(data)
    text = render_header(pins)
    if args.write:
        HEADER.parent.mkdir(parents=True, exist_ok=True)
        HEADER.write_text(text, newline="\n")
        print(f"wrote {HEADER}")
    elif not HEADER.is_file() or HEADER.read_text() != text:
        print("the committed header differs from a fresh render")
        return 1
    print(f"{len(PINS)} pins proved on {hashlib.sha256(data).hexdigest()[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
