#!/usr/bin/env python3
"""Revive a Family Member for Virtual Families 1: every site the companion DLL vf1revive.dll relies on, proved
against the vanilla executable, and the C header the DLL is built from.

    vf1_revive_sites.py --exe "<vanilla>\\Virtual Families.exe" [--write]

VF1 has no ASLR and one executable, so every address is fixed. Each pin is the exact bytes of one stock
function or block of the vanilla `Virtual Families.exe` (the displacement of every call/jmp rel32 is a
wildcard: vf1logs.dll retargets the same two ReportDeath calls). The DLL compares the live bytes with the pin
before it writes anything and installs nothing on a difference.

What the DLL hooks (no function entry is hooked):

* the two calls of CFamilyTree::ReportDeath, 0x48E200 (the death behaviour's end) and 0x489D8F (the body's
  removal), the same sites vf1logs.dll hooks (tools/vf1_logs_sites.py proves they are its only callers). Each
  call is retargeted to the DLL, which takes the snapshot BEFORE the tree forgets the person and then calls what
  was there (the stock function, or vf1logs.dll's wrapper of it);
* theGameState's vtable slots Load 0x4B5E68 and Save 0x4B5E6C (vf1fun.dll hooks them first; the DLL chains
  to what is there). theGameState::SaveCurrentGame 0x4238E0 saves 0, the slot and the slot + 20 through the
  Save slot (call [edx+38h]), so every save file is seen.

What the DLL calls: CVillagerManager::SpawnPeepFull 0x48B2E0 (the game's own creator, as vf1fun's Spawn Child
uses it), which finds the free place with FindEmptySlot 0x489C70 and builds the villager with CVillager::Init.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vf1_logs_sites as L  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "native" / "vf1revive" / "vf1revive_sites.h"
VANILLA_EXE_SHA256 = L.VANILLA_EXE_SHA256

# ---- the layout (docs/vf1-save-format.md 2.4 / 2.5; re-proved by CROSS below)
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
VILLAGER_SLOT = L.VILLAGER_SLOT
VILLAGER_PRESENT = L.VILLAGER_PRESENT
VILLAGER_LEFT_HOME = L.VILLAGER_LEFT_HOME
VILLAGER_BIO = 0x2A34              # CVillagerBio, 0xA0 bytes (the save's record +8)
VILLAGER_BIO_SIZE = 0xA0
VILLAGER_AGE = L.VILLAGER_AGE      # bio +0
VILLAGER_GENDER = L.VILLAGER_GENDER
VILLAGER_NAME = L.VILLAGER_NAME
VILLAGER_NAME_LEN = L.VILLAGER_NAME_LEN
VILLAGER_HEAD = L.VILLAGER_HEAD
VILLAGER_BODY = L.VILLAGER_BODY
VILLAGER_STATE = L.VILLAGER_STATE  # CVillagerState, 0x98 bytes (the save's record +0xA8)
VILLAGER_STATE_SIZE = 0x98
VILLAGER_HEALTH = L.VILLAGER_HEALTH
VILLAGER_CAUSE = L.VILLAGER_CAUSE
VILLAGER_FERTILITY = 0x2B20        # st +0x4C
VILLAGER_WANTS_KIDS = 0x2B24       # st +0x50 ("Wants kids?")
VILLAGER_SKILLS = 0x2B6C           # career, level, +8, salary (the save's record +0x140)
VILLAGER_SKILLS_SIZE = 0x10
VILLAGER_LIKES = 0x13620           # likes int[3], then dislikes int[3] (the save's record +0x150)
VILLAGER_LIKES_SIZE = 0x18
GAME_STATE_RESERVED_BABY = L.GAME_STATE_RESERVED_BABY
GAME_STATE_SLOT = L.GAME_STATE_SLOT
GS_VTABLE_LOAD = L.GS_VTABLE_LOAD
GS_VTABLE_SAVE = 0x4B5E6C
LDW_PATH_VSLOT = L.LDW_PATH_VSLOT
SAVE_BACKUP_OFFSET = 20
UNITS_PER_YEAR = L.UNITS_PER_YEAR
REVIVE_ADULT_YEARS = 18            # the owner, 2026-11-26: died at 18 or older -> back at exactly 18

# name, VA, length, note
PINS = [
    ("ft_report_death", 0x481CF0, 0x101, "CFamilyTree::ReportDeath(villager)"),
    ("death_behaviour_end", 0x48E1E3, 0x5C, "the death behaviour's end: life event 4, ReportDeath, present 0"),
    ("body_removal", 0x489D31, 0x63, "the dead body's removal: present 0, ReportDeath"),
    ("vm_spawn_full", 0x48B2E0, 0x66, "CVillagerManager::SpawnPeepFull: FindEmptySlot, CVillager::Init, the slot"),
    ("vm_find_empty", 0x489C70, 0x4B, "CVillagerManager::FindEmptySlot: not present, not a reserved baby"),
    ("ldw_make_path", 0x4035F0, 0x59, "ldwGameState::MakeGameStatePath(slot): \"%s%d.ldw\""),
    ("v_save_state", 0x485640, 0xD1, "CVillager::SaveState: the bio, state, skills, likes and dislikes it saves"),
    ("gs_save_current", 0x4238E0, 0x3D, "theGameState::SaveCurrentGame: Save(0), Save(slot), Save(slot + 20) by the vtable"),
]
PIN = {p[0]: p for p in PINS}

FUNCTIONS = {
    "FT_REPORT_DEATH": 0x481CF0, "VM_SPAWN_FULL": 0x48B2E0, "VM_FIND_EMPTY": 0x489C70,
    "GS_LOAD": 0x424A50, "GS_SAVE": 0x423790,
}

CALL_HOOKS = (
    ("death_behaviour_end", 0x48E200, 0x481CF0),
    ("body_removal", 0x489D8F, 0x481CF0),
)
CALL_HOOK_NAMES = ("DEATH_END", "BODY_REMOVAL")

CALLS = (
    ("vm_spawn_full", 0x48B2E4, 0x489C70),     # FindEmptySlot
    ("vm_spawn_full", 0x48B33A, 0x484EE0),     # CVillager::Init
)

NEG = L.NEG
CROSS = {
    "ft_report_death": {VILLAGER_SLOT, RECORD_CHILD_COUNT, RECORD_CHILDREN + PEEP_SLOT, PEEP_RECORD_SIZE},
    "body_removal": {NEG(VILLAGER_LEFT_HOME - VILLAGER_HEALTH), FAMILY_TREE},
    "death_behaviour_end": {VILLAGER_SLOT, VILLAGER_PRESENT, FAMILY_TREE},
    "vm_spawn_full": {VILLAGER_STRIDE, VILLAGER_ARRAY_OFFSET, 0x30},
    "vm_find_empty": {GAME_STATE_RESERVED_BABY, GAME_STATE_RESERVED_BABY + 4, GAME_STATE_RESERVED_BABY + 8,
                      VILLAGER_STRIDE, HOUSEHOLD_SLOTS, VILLAGER_ARRAY_OFFSET + VILLAGER_PRESENT},
    "ldw_make_path": {0x14},
    "gs_save_current": {GAME_STATE_SLOT, 0x38, SAVE_BACKUP_OFFSET},
    "v_save_state": {VILLAGER_BIO, VILLAGER_STATE, VILLAGER_SKILLS, VILLAGER_LIKES, VILLAGER_LIKES + 0x14,
                     VILLAGER_PRESENT, VILLAGER_LEFT_HOME},
}

SiteError = L.SiteError


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
    found = L.all_callers(exe, {0x481CF0: None})
    if found[0x481CF0] != [0x489D8F, 0x48E200]:
        raise SiteError("ReportDeath has other callers")
    # theGameState's vtable: Load, Save and MakeGameStatePath.
    for at, func in ((GS_VTABLE_LOAD, FUNCTIONS["GS_LOAD"]), (GS_VTABLE_SAVE, FUNCTIONS["GS_SAVE"]),
                     (0x4B5E40, PIN["ldw_make_path"][1])):
        if struct.unpack("<I", exe.read(at, 4))[0] != func:
            raise SiteError(f"theGameState vtable {at:#x} is not {func:#x}")
    # SaveCurrentGame calls the Save slot (vtable +38h, the vtable starting at 0x4B5E34) for every file.
    if GS_VTABLE_SAVE - 0x38 != 0x4B5E34 or GS_VTABLE_LOAD - 0x34 != 0x4B5E34:
        raise SiteError("the vtable slot arithmetic")
    return pins


def render_header(pins: dict) -> str:
    arr = lambda b: ", ".join(f"0x{x:02X}" for x in b)  # noqa: E731
    out = [
        "// GENERATED by tools/vf1_revive_sites.py from the vanilla Virtual Families.exe. Do not edit.",
        "// Every pin is the exact bytes of stock code at its fixed address (VF1 has no ASLR); mask 1 = a",
        "// call/jmp displacement, which another hook may have retargeted. The DLL installs nothing unless",
        "// every pin matches.",
        "#pragma once",
        "",
        "struct RevivePin { const char *name; unsigned va; unsigned len; const unsigned char *bytes; const unsigned char *mask; };",
        "struct ReviveCallHook { unsigned site; unsigned target; };",
        "",
    ]
    for key, value in sorted(globals().items()):
        if key.isupper() and isinstance(value, int) and not isinstance(value, bool):
            out.append(f"#define REV_{key} 0x{value:X}u")
    out.append("")
    for name, va in FUNCTIONS.items():
        out.append(f"#define REV_{name} 0x{va:X}u")
    out.append("")
    for name, (va, raw, mask) in pins.items():
        out.append(f"static const unsigned char rpin_{name}[] = {{ {arr(raw)} }};")
        out.append(f"static const unsigned char rmask_{name}[] = {{ {arr(mask)} }};")
    out.append("")
    out.append("static const RevivePin REV_PINS[] = {")
    for name, (va, raw, mask) in pins.items():
        out.append(f'    {{ "{name}", 0x{va:X}u, {len(raw)}u, rpin_{name}, rmask_{name} }},')
    out.append("};")
    out.append("")
    out.append("enum { " + ", ".join(f"REV_CALL_{n} = {i}" for i, n in enumerate(CALL_HOOK_NAMES)) + " };")
    out.append("static const ReviveCallHook REV_CALL_HOOKS[] = {")
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
