#!/usr/bin/env python3
"""Up to 28 Children for Virtual Families 1: every site the companion DLL vf1kids.dll relies on, proved
against the vanilla executable, and the C header the DLL is built from.

    vf1_kids_sites.py --exe "<vanilla>\\Virtual Families.exe" [--write]

VF1 has no ASLR and one executable, so every address is fixed. Each pin is the exact bytes of one
stock function of the vanilla `Virtual Families.exe` (or its whole head). The DLL compares the live
bytes with the pin before it writes anything, and installs nothing on a difference. The displacement
of every call/jmp rel32 is a wildcard: vf1fun.dll retargets some of those calls (for example the baby
rolls inside Impregnate) and the hook may be installed after it.

The proof (validate): the bytes at each VA are the pinned bytes, whole instructions; each layout
constant appears as an operand where the game uses it; every call the DLL relies on is a call rel32 to
the function it expects; every hooked entry's stolen bytes are whole, position-independent instructions
with no branch into them; CloneAsAdult never writes the slot index; MakeGameStatePath formats
"%s%d.ldw".

The native layout (research/villagers.md, re-proved here):
* CFamilyTree 0x5AB908: +0 generation count (1-based; 0 = none), +4 the first of 30 records of 0x6C8.
  The current record is tree + count * 0x6C8 - 0x6C4; record +0x1B4 child count, +0x1B8 six child
  SPeepRecords of 0xD8 (a seventh would overwrite the next record); SPeepRecord +0x1A valid, +0x1C
  gender, +0x28 villager slot (-1 = dead).
* CVillagerManager 0x5B8898: villager i at +0x14640 + i * 0x145FC, 30 household slots; villager +0x13538
  slot index, +0x13574 present, +0x13578 left home, +0x2A34 age, +0x2A38 gender, +0x2A44 name (25),
  +0x2A60 head, +0x2A64 body.
* theGameState (instance at [0x50025C]): +0x1B120/+0x1B124/+0x1B128 the slots reserved for the babies on
  the way.
* CAdoptionScene: +0x8 the candidate on show, +0x10 Next Generation mode byte, +0x14 six clone slots, +0x2C
  six source slots, +0x44 count, +0x48 cursor.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "native" / "vf1kids" / "vf1kids_sites.h"
# The vanilla executable the pins are taken from (the patcher's own identity, vf1_patcher.VANILLA_SHA256).
VANILLA_EXE_SHA256 = "5db828c3f53c68696c18719aec0eb114be3fd4458ae2cbf185d8d4ef7eca4487"

# The owner's numbers.
MAX_CHILDREN = 28
TREE_CHILDREN = 6
MAX_EXTRA_CHILDREN = MAX_CHILDREN - TREE_CHILDREN

FAMILY_TREE = 0x5AB908
VILLAGER_MANAGER = 0x5B8898
GAME_STATE_INSTANCE = 0x50025C
FAMILY_RECORD_SIZE = 0x6C8
FAMILY_RECORD_BASE = 0x6C4          # current record = tree + count * 0x6C8 - 0x6C4
TREE_GENERATIONS = 30
RECORD_CHILD_COUNT = 0x1B4
RECORD_CHILDREN = 0x1B8
RECORD_PARENT1 = 0x04
PEEP_RECORD_SIZE = 0xD8
PEEP_VALID = 0x1A
PEEP_GENDER = 0x1C
PEEP_SLOT = 0x28
VILLAGER_ARRAY_OFFSET = 0x14640
VILLAGER_STRIDE = 0x145FC
HOUSEHOLD_SLOTS = 30
VILLAGER_SLOT = 0x13538
VILLAGER_PRESENT = 0x13574
VILLAGER_LEFT_HOME = 0x13578
VILLAGER_AGE = 0x2A34
VILLAGER_GENDER = 0x2A38
VILLAGER_NAME = 0x2A44
VILLAGER_NAME_LEN = 25
VILLAGER_HEAD = 0x2A60
VILLAGER_BODY = 0x2A64
GAME_STATE_RESERVED_BABY = 0x1B120
ADOPTION_CANDIDATE = 0x08
ADOPTION_MODE = 0x10
ADOPTION_CLONES = 0x14
ADOPTION_SOURCES = 0x2C
ADOPTION_COUNT = 0x44
ADOPTION_CURSOR = 0x48
LDW_PATH_VSLOT = 0x0C
SAVE_BACKUP_OFFSET = 0x14
SIDECAR_VERSION = 1

# name, VA, length, note
PINS = [
    ("ft_empty_offspring", 0x4816E0, 0x19, "CFamilyTree::EmptyOffspringSlots: 6 - count (6 with no family)"),
    ("ft_add_offspring", 0x481AA0, 0x90, "CFamilyTree::AddOffspring: refuses count 6"),
    ("ft_start_next_gen", 0x481B30, 0xE5, "CFamilyTree::StartNextGeneration(villager, source slot)"),
    ("ft_count_surviving", 0x481850, 0x44, "CFamilyTree::CountSurvivingChildren: children whose slot is not -1"),
    ("ft_reset", 0x481560, 0x1E, "CFamilyTree::Reset"),
    ("ft_current_family", 0x481730, 0x20, "CFamilyTree::GetCurrentFamily"),
    ("ft_change_name", 0x481C20, 0xC7, "CFamilyTree::ChangeName(villager, name)"),
    ("ft_report_death", 0x481CF0, 0x101, "CFamilyTree::ReportDeath(villager)"),
    ("ad_create_candidates", 0x436390, 0xC5, "CAdoptionScene::CreateNextGenerationCandidates"),
    ("ad_get_next", 0x436460, 0x24, "CAdoptionScene::GetNextCandidate"),
    ("ad_activate", 0x436700, 0x74, "CAdoptionScene::Activate(bool)"),
    ("ad_generate", 0x436540, 0x83, "CAdoptionScene::GeneratePeepCandidate, head: mode 1 shows GetNextCandidate()"),
    ("ad_handle_message", 0x436780, 0x198, "CAdoptionScene::HandleMessage, head through Accept"),
    ("vm_find_empty", 0x489C70, 0x4B, "CVillagerManager::FindEmptySlot"),
    ("vm_get_villager", 0x489900, 0x1F, "CVillagerManager::GetVillager"),
    ("vm_clone_peep", 0x48B400, 0x2F, "CVillagerManager::ClonePeepAsAdult"),
    ("v_clone_as_adult", 0x485470, 0x15D, "CVillager::CloneAsAdult: Reset(this), then copies from the argument"),
    ("v_impregnate", 0x4864D0, 0xE0, "CVillager::Impregnate, head through the twin / triplet decision"),
    ("gs_get", 0x423660, 0x7A, "theGameState::Get"),
    ("gs_save", 0x423790, 0x3A, "theGameState::Save(slot), head: slot 0 is the settings file"),
    ("gs_load", 0x424A50, 0x3B, "theGameState::Load(slot), head: slot 0 is the settings file"),
    ("ldw_save", 0x403930, 0x7A, "ldwGameState::Save(data, size, slot): slot + 14h keeps the previous save"),
    ("ldw_make_path", 0x4035F0, 0x59, "ldwGameState::MakeGameStatePath(slot): \"%s%d.ldw\""),
]
PIN = {p[0]: p for p in PINS}

# Functions the DLL calls or hooks.
FUNCTIONS = {
    "FT_EMPTY_OFFSPRING": "ft_empty_offspring", "FT_ADD_OFFSPRING": "ft_add_offspring",
    "FT_START_NEXT_GEN": "ft_start_next_gen", "FT_COUNT_SURVIVING": "ft_count_surviving",
    "FT_RESET": "ft_reset", "FT_CHANGE_NAME": "ft_change_name", "FT_REPORT_DEATH": "ft_report_death",
    "AD_CREATE_CANDIDATES": "ad_create_candidates", "AD_GET_NEXT": "ad_get_next",
    "VM_FIND_EMPTY": "vm_find_empty", "VM_CLONE_PEEP": "vm_clone_peep", "V_CLONE_AS_ADULT": "v_clone_as_adult",
    "GS_SAVE": "gs_save", "GS_LOAD": "gs_load",
}

# Calls the DLL relies on: (pin, VA of the E8 byte, the function it must call).
CALLS = (
    ("ft_report_death", 0x481DDB, "ft_count_surviving"),
    ("ad_activate", 0x43671C, "ft_count_surviving"),
    ("ad_activate", 0x436733, "ad_create_candidates"),
    ("ad_activate", 0x43673A, "ad_generate"),
    ("ad_create_candidates", 0x4363DE, "vm_get_villager"),
    ("ad_create_candidates", 0x4363EB, "vm_clone_peep"),
    ("ad_generate", 0x4365AE, "ad_get_next"),
    ("ad_handle_message", 0x4368E6, "ft_start_next_gen"),
    ("vm_clone_peep", 0x48B404, "vm_find_empty"),
    ("vm_clone_peep", 0x48B423, "v_clone_as_adult"),
    ("v_impregnate", 0x4864DC, "ft_empty_offspring"),
    ("vm_find_empty", 0x489C73, "gs_get"),
    ("ldw_save", 0x403960, None),
)

# Entry hooks: (kind, stolen bytes).
HOOKS = {
    "FT_EMPTY_OFFSPRING": ("replace", 5),    # mov edx,[ecx] / test edx,edx / mov eax,6 (partly)
    "FT_ADD_OFFSPRING": ("wrap", 5),          # push ebx / mov ebx,ecx / mov eax,[ebx]
    "FT_START_NEXT_GEN": ("wrap", 6),         # push ecx / push edi / mov edi,ecx / mov eax,[edi]
    "FT_COUNT_SURVIVING": ("wrap", 6),        # mov edx,[ecx] / xor eax,eax / test edx,edx
    "FT_RESET": ("wrap", 8),                  # push esi / mov esi,ecx / push 0CB70h
    "FT_CHANGE_NAME": ("wrap", 6),            # push esi / push edi / mov edi,[esp+0Ch]
    "FT_REPORT_DEATH": ("wrap", 5),           # mov eax,[esp+4] / push ebx
    "AD_CREATE_CANDIDATES": ("wrap", 5),      # push ecx / push ebp / push esi / mov esi,ecx
    "AD_GET_NEXT": ("wrap", 7),               # add dword [ecx+48h],1 / mov eax,[ecx+48h]
    "GS_SAVE": ("wrap", 6),                   # push esi / push edi / mov edi,[esp+0Ch]
    "GS_LOAD": ("wrap", 5),                   # mov eax,1B210h
}

# Operands that must appear in a pin (layout cross-checks).
NEG = lambda v: (-v) & 0xFFFFFFFF  # noqa: E731
CROSS = {
    "ft_empty_offspring": {6, FAMILY_RECORD_SIZE, NEG(0x510)},
    "ft_add_offspring": {6, FAMILY_RECORD_SIZE, NEG(0x510), NEG(0x6C4), PEEP_RECORD_SIZE, RECORD_CHILDREN,
                         RECORD_CHILD_COUNT, VILLAGER_NAME, VILLAGER_GENDER, VILLAGER_HEAD, VILLAGER_BODY,
                         VILLAGER_SLOT, PEEP_VALID, PEEP_GENDER, PEEP_SLOT},
    "ft_current_family": {FAMILY_RECORD_SIZE, NEG(FAMILY_RECORD_BASE)},
    "ft_count_surviving": {FAMILY_RECORD_SIZE, NEG(FAMILY_RECORD_BASE), RECORD_CHILD_COUNT,
                           RECORD_CHILDREN + PEEP_SLOT, PEEP_RECORD_SIZE, 0xFFFFFFFF},
    "ft_report_death": {VILLAGER_SLOT, RECORD_CHILD_COUNT, RECORD_CHILDREN + PEEP_SLOT, PEEP_RECORD_SIZE},
    "ft_reset": {0xCB70},
    "ft_start_next_gen": {TREE_GENERATIONS, FAMILY_RECORD_SIZE, VILLAGER_SLOT},
    "ad_create_candidates": {ADOPTION_COUNT, ADOPTION_CURSOR, RECORD_CHILD_COUNT, RECORD_CHILDREN + PEEP_SLOT,
                             ADOPTION_CLONES, ADOPTION_SOURCES, VILLAGER_SLOT, VILLAGER_PRESENT, FAMILY_TREE,
                             VILLAGER_MANAGER},
    "ad_get_next": {ADOPTION_COUNT, ADOPTION_CURSOR, ADOPTION_CLONES},
    "ad_activate": {ADOPTION_MODE, ADOPTION_CANDIDATE, FAMILY_TREE},
    "ad_generate": {ADOPTION_MODE, ADOPTION_CANDIDATE},
    "ad_handle_message": {ADOPTION_MODE, ADOPTION_CANDIDATE, ADOPTION_CURSOR, ADOPTION_SOURCES,
                          HOUSEHOLD_SLOTS, VILLAGER_PRESENT},
    "vm_find_empty": {VILLAGER_ARRAY_OFFSET + VILLAGER_PRESENT, GAME_STATE_RESERVED_BABY,
                      GAME_STATE_RESERVED_BABY + 4, GAME_STATE_RESERVED_BABY + 8, HOUSEHOLD_SLOTS, VILLAGER_STRIDE},
    "vm_get_villager": {VILLAGER_STRIDE, VILLAGER_ARRAY_OFFSET, HOUSEHOLD_SLOTS - 1},
    "vm_clone_peep": {VILLAGER_STRIDE, VILLAGER_ARRAY_OFFSET},
    "v_clone_as_adult": {VILLAGER_PRESENT},
    "v_impregnate": {1, 2, 3, 7, 0x19, 0x2AFC, 0x55, FAMILY_TREE},
    "gs_get": {GAME_STATE_INSTANCE},
    "gs_save": {0x88},
    "gs_load": {0x88, 0x1B210},
    "ldw_save": {SAVE_BACKUP_OFFSET, LDW_PATH_VSLOT},
    "ldw_make_path": {0x14},
}


class SiteError(RuntimeError):
    pass


def _md() -> Cs:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    return md


class Exe:
    def __init__(self, data: bytes):
        self.data = data
        self.pe = pefile.PE(data=data, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase

    def read(self, va: int, n: int) -> bytes:
        try:
            return self.pe.get_data(va - self.base, n)
        except Exception as e:  # pragma: no cover
            raise SiteError(f"{va:#x} is not in the image") from e


def mask_for(raw: bytes, va: int) -> bytes:
    m = bytearray(len(raw))
    for i in _md().disasm(raw, va):
        if (i.mnemonic in ("call", "jmp") or i.mnemonic.startswith("j")) and i.operands \
                and i.operands[0].type == X86_OP_IMM and i.size >= 5:
            o = i.address - va + i.size - 4
            for k in range(4):
                m[o + k] = 1
    return bytes(m)


def _operands(raw: bytes, va: int) -> set[int]:
    out = set()
    for i in _md().disasm(raw, va):
        for op in i.operands:
            if op.type == X86_OP_IMM and i.mnemonic not in ("call", "jmp") and not i.mnemonic.startswith("j"):
                out.add(op.imm & 0xFFFFFFFF)
            elif op.type == X86_OP_MEM:
                out.add(op.mem.disp & 0xFFFFFFFF)
    return out


def call_target(exe: Exe, at: int) -> int:
    raw = exe.read(at, 5)
    if raw[0] != 0xE8:
        raise SiteError(f"{at:#x} is not a call rel32")
    return (at + 5 + struct.unpack("<i", raw[1:])[0]) & 0xFFFFFFFF


def validate(data: bytes) -> dict:
    if hashlib.sha256(data).hexdigest() != VANILLA_EXE_SHA256:
        raise SiteError("not the vanilla Virtual Families.exe the pins are taken from")
    exe = Exe(data)
    if exe.base != 0x400000:
        raise SiteError("not the VF1 image base")
    pins = {}
    for name, va, n, note in PINS:
        raw = exe.read(va, n)
        insns = list(_md().disasm(raw, va))
        if sum(i.size for i in insns) != n:
            raise SiteError(f"{name}: not whole instructions")
        pins[name] = (va, raw, mask_for(raw, va))
    for name, values in CROSS.items():
        va, raw, _m = pins[name]
        got = _operands(raw, va)
        for v in values:
            if (v & 0xFFFFFFFF) not in got:
                raise SiteError(f"{name}: no operand {v:#x}")
    for pin, at, func in CALLS:
        va, raw, _m = pins[pin]
        if not va <= at < va + len(raw) - 4:
            raise SiteError(f"{pin}: call {at:#x} outside the pin")
        t = call_target(exe, at)
        if func and t != PIN[func][1]:
            raise SiteError(f"{pin}+{at - va:#x}: calls {t:#x}, not {func}")
    for name, (kind, steal) in HOOKS.items():
        va, raw, mask = pins[FUNCTIONS[name]]
        size = 0
        for i in _md().disasm(raw[:steal] if kind == "wrap" else b"", va):
            if i.mnemonic.startswith("j") or i.mnemonic in ("call", "ret"):
                raise SiteError(f"{name}: a branch in the stolen bytes")
            for op in i.operands:
                if op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                    raise SiteError(f"{name}: an absolute operand in the stolen bytes")
            size += i.size
        if kind == "wrap" and size != steal:
            raise SiteError(f"{name}: the stolen bytes are not whole instructions")
        if kind == "replace" and (steal != 5 or len(raw) < 5):
            raise SiteError(f"{name}: a replaced entry takes exactly the 5-byte jmp")
        for i in _md().disasm(raw, va):
            if (i.mnemonic.startswith("j") or i.mnemonic == "loop") and i.operands \
                    and i.operands[0].type == X86_OP_IMM and va < i.operands[0].imm < va + max(steal, 5):
                raise SiteError(f"{name}: a branch into the stolen bytes")
    # CloneAsAdult never writes the slot index.
    va, raw, _m = pins["v_clone_as_adult"]
    for i in _md().disasm(raw, va):
        if i.operands and i.operands[0].type == X86_OP_MEM and (i.operands[0].mem.disp & 0xFFFFFFFF) == VILLAGER_SLOT \
                and i.mnemonic.startswith("mov"):
            raise SiteError("CloneAsAdult writes the slot index")
    # MakeGameStatePath's format string.
    va, raw, _m = pins["ldw_make_path"]
    fmt = [i.operands[0].imm for i in _md().disasm(raw, va) if i.mnemonic == "push" and i.operands
           and i.operands[0].type == X86_OP_IMM and i.operands[0].imm > 0x400000]
    if not fmt or exe.read(fmt[0], 9) != b"%s%d.ldw\0":
        raise SiteError("MakeGameStatePath does not format %s%d.ldw")
    # theGameState's MakeGameStatePath is vtable slot 3: the pointer at 0x4B5E40 (vtable 0x4B5E34).
    if struct.unpack("<I", exe.read(0x4B5E40, 4))[0] != PIN["ldw_make_path"][1]:
        raise SiteError("theGameState vtable +0Ch is not MakeGameStatePath")
    if struct.unpack("<I", exe.read(0x4B5E68, 4))[0] != PIN["gs_load"][1] or \
            struct.unpack("<I", exe.read(0x4B5E6C, 4))[0] != PIN["gs_save"][1]:
        raise SiteError("theGameState Load / Save slots")
    return pins


def render_header(pins: dict) -> str:
    arr = lambda b: ", ".join(f"0x{x:02X}" for x in b)  # noqa: E731
    out = [
        "// GENERATED by tools/vf1_kids_sites.py from the vanilla Virtual Families.exe. Do not edit.",
        "// Every pin is the exact bytes of a stock function at its fixed address (VF1 has no ASLR); mask 1 =",
        "// a call/jmp displacement, which another hook may have retargeted. The DLL installs nothing unless",
        "// every pin matches.",
        "#pragma once",
        "",
        "struct KidsPin { const char *name; unsigned va; unsigned len; const unsigned char *bytes; const unsigned char *mask; };",
        "struct KidsHook { unsigned va; unsigned char replace; unsigned char steal; };",
        "",
    ]
    for key, value in sorted(globals().items()):
        if key.isupper() and isinstance(value, int) and not isinstance(value, bool)                 and not key.startswith(("CS_", "X86_")):
            out.append(f"#define KIDS_{key} 0x{value:X}u")
    out.append("")
    for name, (va, raw, mask) in pins.items():
        out.append(f"#define KIDS_PIN_{name.upper()} 0x{va:X}u")
    out.append("")
    for name, (va, raw, mask) in pins.items():
        out.append(f"static const unsigned char kpin_{name}[] = {{ {arr(raw)} }};")
        out.append(f"static const unsigned char kmask_{name}[] = {{ {arr(mask)} }};")
    out.append("")
    out.append("static const KidsPin KIDS_PINS[] = {")
    for name, (va, raw, mask) in pins.items():
        out.append(f'    {{ "{name}", 0x{va:X}u, {len(raw)}u, kpin_{name}, kmask_{name} }},')
    out.append("};")
    out.append("")
    for name, func in FUNCTIONS.items():
        out.append(f"#define KIDS_{name} 0x{PIN[func][1]:X}u")
    out.append("")
    out.append("static const KidsHook KIDS_HOOKS[] = {")
    for name, (kind, steal) in HOOKS.items():
        out.append(f"    {{ KIDS_{name}, {1 if kind == 'replace' else 0}, {steal} }},   // {name}")
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
