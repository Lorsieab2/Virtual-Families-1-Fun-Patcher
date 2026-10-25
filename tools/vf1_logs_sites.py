#!/usr/bin/env python3
"""Family Logs for Virtual Families 1: every site the companion DLL vf1logs.dll relies on, proved against
the vanilla executable, and the C header the DLL is built from.

    vf1_logs_sites.py --exe "<vanilla>\\Virtual Families.exe" [--write]

VF1 has no ASLR and one executable, so every address is fixed. Each pin is the exact bytes of one stock
function or block of the vanilla `Virtual Families.exe`. The DLL compares the live bytes with the pin
before it writes anything and installs nothing on a difference. Wildcards (the DLL accepts them):

* the displacement of every call/jmp rel32 (vf1fun.dll retargets some calls, and this DLL its own);
* at a hooked function's entry, a 5-byte `jmp rel32` to code outside the executable: another companion
  (vf1kids.dll) hooked that entry first. The DLL then chains to that jmp's target.

How each event is seen (every site traced in the vanilla disassembly; see docs/FAMILY_LOGS.md):

* conception: the one call of CVillager::Impregnate, 0x48EBB2 (the try-for-a-baby plan step; ecx = the
  matriarch, args (1, "Joey", patriarch head, patriarch body, false), ret 14h). vf1fun may have retargeted
  it to its own wrapper; the DLL chains to whatever the call reaches.
* birth: the one call of CVillagerManager's physiology pass 0x48BC90, 0x424F93 (theGameState realtime
  update). The only code that delivers a baby is inside it (0x48C073..0x48C2FD): reserved slot
  gs+0x1B120/24/28 -> present 1 and -1, the mother's +0x2AF8 -> 0 (the only writer of 0 in the game), +0x2AFC
  -> 0. The DLL compares before and after the pass.
* death: both calls of CFamilyTree::ReportDeath, 0x48E200 (the death behaviour's end) and 0x489D8F (the
  body's removal). The cause is the villager's own CVillagerState+0x10, which SetHealth 0x48F820 and
  AdjustHealth 0x48F860 store when health reaches 0 (their only writers). Logged once per villager.
* marriage: CFamilyTree::UpdateParents 0x4819C0 (entry; the Marry button's call 0x438337 and vf1fun's
  same-sex wedding).
* next generation / a new family / Adopt New Person: CFamilyTree::StartNextGeneration 0x481B30 (entry; the
  adoption scene's accept 0x4368E6, StartFamilyTree 0x481E11, vf1fun's Adopt New Person).
* a child who joins (The Little Visitor 0x418828 / 0x4188D8, vf1fun's Spawn Child and Adopt Outside
  Child): CFamilyTree::AddOffspring 0x481AA0 (entry). Calls from Impregnate (0x48665B, 0x486712,
  0x48677B: the babies, at conception) are told apart by the return address.
* leaving home: CVillager::SetLeftHome 0x4857F0 (entry; the age-19 leaving 0x489EC5, the island event
  0x418F46, vf1fun's Boarding School).
* Start Over: the one call of theGameState::Restart, 0x448426 (the menu's confirmed Start Over).
* after a save / load: theGameState's vtable slots Load 0x4B5E68 and Save 0x4B5E6C (vf1fun hooks them
  first; the DLL chains to what is there).
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
HEADER = ROOT / "native" / "vf1logs" / "vf1logs_sites.h"
VANILLA_EXE_SHA256 = "5db828c3f53c68696c18719aec0eb114be3fd4458ae2cbf185d8d4ef7eca4487"

# ---- the layout (docs/vf1-save-format.md, research/villagers.md; re-proved by CROSS below)
FAMILY_TREE = 0x5AB908
VILLAGER_MANAGER = 0x5B8898
GAME_STATE_INSTANCE = 0x50025C
STRINGS_INSTANCE_GET = 0x450530
MONEY = 0x50C60C
FOOD = 0x50C550
STATS_BABIES = 0x50C568          # CGameStats+8: babies (counted at conception, Impregnate 0x48678D)
STATS_OLDEST = 0x50C580          # CGameStats+0x20: oldest age ever, years
FAMILY_RECORD_SIZE = 0x6C8
FAMILY_RECORD_BASE = 0x6C4       # record of generation g = tree + g * 0x6C8 - 0x6C4
TREE_GENERATIONS = 30
RECORD_PARENT1 = 0x04
RECORD_PARENT2 = 0xDC
RECORD_CHILD_COUNT = 0x1B4
RECORD_CHILDREN = 0x1B8
TREE_CHILDREN = 6
PEEP_RECORD_SIZE = 0xD8
PEEP_VALID = 0x1A
PEEP_GENDER = 0x1C
PEEP_HEAD = 0x20
PEEP_BODY = 0x24
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
VILLAGER_BIO_PARENT1 = 0x2A68
VILLAGER_BIO_PARENT2 = 0x2A82
VILLAGER_STATE = 0x2AD4
VILLAGER_HEALTH = 0x2AE0
VILLAGER_CAUSE = 0x2AE4
VILLAGER_PREGNANT = 0x2AF8
VILLAGER_CARRIED = 0x2AFC
VILLAGER_CAREER = 0x2B6C
GAME_STATE_RESERVED_BABY = 0x1B120
GAME_STATE_FAMILY_NAME = 0x1B12C
GAME_STATE_FAMILY_NAME_LEN = 0x1C
GAME_STATE_SLOT = 0x1B188
GS_VTABLE_LOAD = 0x4B5E68
GS_VTABLE_SAVE = 0x4B5E6C
LDW_PATH_VSLOT = 0x0C
UNITS_PER_YEAR = 20
# The exe's own words (string ids; the text is the exe's, read at run time with GetString).
STR_MALE = 0x464
STR_FEMALE = 0x465
STR_NURSING = 0x630
STR_COLLEGE_TITLE = 0x3AE         # "{name} is going to college!"
STR_CAUSE_UNKNOWN = 0x507         # 0x507 + 1 + cause: -1 Unknown causes, 0 Disease, 1 Starvation, 2 Old age,
STR_CAUSE_LAST = 0x50C            # 3 Work accident, 4 Act of Nature
STR_FAMILY_TREE = 0x1C9
STR_NEW_GENERATION = 0x1CA

# name, VA, length, note
PINS = [
    ("v_impregnate", 0x4864D0, 0x2D4, "CVillager::Impregnate, whole (two ret 14h)"),
    ("plan_conception", 0x48EB33, 0xB8, "the try-for-a-baby plan step: GetMatriarch / GetPatriarch, the Impregnate call"),
    ("vm_physiology_call", 0x424F80, 0x18, "theGameState realtime update head: AllVillagersTimeflowUpkeep, the physiology pass"),
    ("vm_delivery", 0x48C073, 0x294, "the delivery inside the physiology pass (0x48C073..0x48C307)"),
    ("ft_report_death", 0x481CF0, 0x101, "CFamilyTree::ReportDeath(villager)"),
    ("death_behaviour_end", 0x48E1E3, 0x5C, "the death behaviour's end: life event 4, ReportDeath, present 0"),
    ("body_removal", 0x489D31, 0x63, "the dead body's removal: present 0, ReportDeath"),
    ("vs_set_health", 0x48F820, 0x32, "CVillagerState::SetHealth(health, cause)"),
    ("vs_adjust_health", 0x48F860, 0x74, "CVillagerState::AdjustHealth(delta, cause)"),
    ("ft_update_parents", 0x4819C0, 0xDB, "CFamilyTree::UpdateParents(a, b)"),
    ("ft_add_offspring", 0x481AA0, 0x175, "CFamilyTree::AddOffspring(villager)"),
    ("ft_start_next_gen", 0x481B30, 0xE5, "CFamilyTree::StartNextGeneration(villager, source)"),
    ("ft_start_family_tree", 0x481E00, 0x1A, "CFamilyTree::StartFamilyTree = Reset + StartNextGeneration(v, -1)"),
    ("v_set_left_home", 0x4857F0, 0x1C, "CVillager::SetLeftHome"),
    ("menu_restart_call", 0x448423, 0x8, "theMenuScene: the confirmed Start Over calls theGameState::Restart"),
    ("gs_restart", 0x4243C0, 0x74, "theGameState::Restart: keep the name, Init, SaveCurrentGame, ret"),
    ("vm_physiology_tail", 0x48C464, 0xB, "the physiology pass returns with a plain ret (thiscall, no arguments)"),
    ("vm_get_matriarch", 0x489950, 0x61, "CVillagerManager::GetMatriarch"),
    ("vm_get_patriarch", 0x4899C0, 0x61, "CVillagerManager::GetPatriarch"),
    ("strings_get_string", 0x44FD90, 0x3F, "theStringManager::GetString(id)"),
    ("ldw_make_path", 0x4035F0, 0x59, "ldwGameState::MakeGameStatePath(slot): \"%s%d.ldw\""),
]
PIN = {p[0]: p for p in PINS}

# Functions the DLL calls, hooks or tells apart.
FUNCTIONS = {
    "V_IMPREGNATE": 0x4864D0, "VM_PHYSIOLOGY": 0x48BC90, "FT_REPORT_DEATH": 0x481CF0,
    "FT_UPDATE_PARENTS": 0x4819C0, "FT_ADD_OFFSPRING": 0x481AA0, "FT_START_NEXT_GEN": 0x481B30,
    "V_SET_LEFT_HOME": 0x4857F0, "GS_RESTART": 0x4243C0, "VM_GET_MATRIARCH": 0x489950,
    "VM_GET_PATRIARCH": 0x4899C0, "STRINGS_GET": 0x450530, "STRINGS_GET_STRING": 0x44FD90,
    "GS_LOAD": 0x424A50, "GS_SAVE": 0x423790, "V_IMPREGNATE_END": 0x4867A4,
}

# Calls the DLL retargets: (pin, VA of the E8 byte, the stock target).
CALL_HOOKS = (
    ("plan_conception", 0x48EBB2, 0x4864D0),
    ("vm_physiology_call", 0x424F93, 0x48BC90),
    ("death_behaviour_end", 0x48E200, 0x481CF0),
    ("body_removal", 0x489D8F, 0x481CF0),
    ("menu_restart_call", 0x448426, 0x4243C0),
)
CALL_HOOK_NAMES = ("CONCEPTION", "PHYSIOLOGY", "DEATH_END", "BODY_REMOVAL", "RESTART")

# Calls that must reach what the DLL expects (pin, VA, target).
CALLS = (
    ("v_impregnate", 0x4864DC, 0x4816E0),        # EmptyOffspringSlots
    ("v_impregnate", 0x48665B, 0x481AA0),        # AddOffspring: the first baby
    ("v_impregnate", 0x486712, 0x481AA0),        # the twin
    ("v_impregnate", 0x48677B, 0x481AA0),        # the triplet
    ("plan_conception", 0x48EB40, 0x489950),     # GetMatriarch
    ("plan_conception", 0x48EB4C, 0x4899C0),     # GetPatriarch
    ("ft_start_family_tree", 0x481E03, 0x481560),
    ("ft_start_family_tree", 0x481E11, 0x481B30),
    ("vm_delivery", 0x48C2F8, 0x486A10),
    ("death_behaviour_end", 0x48E1F5, 0x423E10),
    ("ft_update_parents", 0x4819D8, 0x4817B0),   # FindPeepRecord
    ("gs_restart", 0x42441E, 0x4238E0),          # SaveCurrentGame
)

# Entry hooks: (function, stolen bytes when the entry is stock).
ENTRY_HOOKS = {
    "FT_UPDATE_PARENTS": ("ft_update_parents", 8),    # push ebx / push ebp / mov ebp,ecx / cmp dword [ebp],0
    "FT_ADD_OFFSPRING": ("ft_add_offspring", 5),      # push ebx / mov ebx,ecx / mov eax,[ebx]
    "FT_START_NEXT_GEN": ("ft_start_next_gen", 6),    # push ecx / push edi / mov edi,ecx / mov eax,[edi]
    "V_SET_LEFT_HOME": ("v_set_left_home", 8),        # push esi / mov esi,ecx / mov ecx,50C5D0h
}

NEG = lambda v: (-v) & 0xFFFFFFFF  # noqa: E731
# Operands that must appear in a pin (the layout, cross-checked where the game uses it).
CROSS = {
    "v_impregnate": {VILLAGER_PREGNANT, VILLAGER_CARRIED, GAME_STATE_RESERVED_BABY, GAME_STATE_RESERVED_BABY + 4,
                     GAME_STATE_RESERVED_BABY + 8, FAMILY_TREE, VILLAGER_MANAGER,
                     VILLAGER_MANAGER + VILLAGER_ARRAY_OFFSET + VILLAGER_PRESENT, STATS_BABIES},
    "plan_conception": {VILLAGER_GENDER, VILLAGER_HEAD, VILLAGER_BODY, VILLAGER_AGE, VILLAGER_MANAGER},
    "vm_delivery": {NEG(VILLAGER_LEFT_HOME - VILLAGER_PREGNANT), NEG(VILLAGER_LEFT_HOME - VILLAGER_CARRIED),
                    GAME_STATE_RESERVED_BABY, GAME_STATE_RESERVED_BABY + 4, GAME_STATE_RESERVED_BABY + 8,
                    VILLAGER_PRESENT, VILLAGER_STRIDE, VILLAGER_ARRAY_OFFSET, NEG(VILLAGER_LEFT_HOME)},
    "ft_report_death": {VILLAGER_SLOT, RECORD_CHILD_COUNT, RECORD_CHILDREN + PEEP_SLOT, PEEP_RECORD_SIZE},
    "body_removal": {NEG(VILLAGER_LEFT_HOME - VILLAGER_HEALTH), FAMILY_TREE},
    "death_behaviour_end": {VILLAGER_SLOT, VILLAGER_PRESENT, FAMILY_TREE},
    "vs_set_health": {0xC, 0x10},
    "vs_adjust_health": {0xC, 0x10},
    "ft_update_parents": {FAMILY_RECORD_SIZE, NEG(FAMILY_RECORD_BASE), VILLAGER_NAME, VILLAGER_GENDER, VILLAGER_HEAD,
                          VILLAGER_BODY, VILLAGER_SLOT, RECORD_PARENT2, RECORD_PARENT2 + PEEP_VALID},
    "ft_add_offspring": {6, FAMILY_RECORD_SIZE, RECORD_CHILDREN, RECORD_CHILD_COUNT, VILLAGER_NAME, VILLAGER_GENDER,
                         VILLAGER_SLOT, PEEP_RECORD_SIZE},
    "ft_start_next_gen": {TREE_GENERATIONS, FAMILY_RECORD_SIZE, VILLAGER_SLOT},
    "v_set_left_home": {VILLAGER_LEFT_HOME},
    "gs_restart": {GAME_STATE_FAMILY_NAME},
    "vm_get_matriarch": {NEG(VILLAGER_LEFT_HOME - VILLAGER_HEALTH), NEG(VILLAGER_LEFT_HOME - VILLAGER_GENDER)},
    "vm_get_patriarch": {NEG(VILLAGER_LEFT_HOME - VILLAGER_HEALTH), NEG(VILLAGER_LEFT_HOME - VILLAGER_GENDER)},
    "strings_get_string": {0x674},
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

    def string_record(self, string_id: int) -> tuple[int, str]:
        """The exe's own text for a string id: the static record {id, key, text, override} that
        theStringManager indexes (GetString 0x44FD90 returns +0xC or +8 of it)."""
        raw = self.read(0x4F1000, 0xC000)
        for k in range(0, len(raw) - 16, 4):
            i, key, text, override = struct.unpack_from("<IIII", raw, k)
            if i == string_id and override == 0 and 0x4B0000 <= key < 0x4E0000 and 0x4B0000 <= text < 0x4E0000:
                if self.cstr(key).startswith(("eString", "eSay", "eTip", "ePregnant", "eEvent")):
                    return text, self.cstr(text)
        raise SiteError(f"no string record for id {string_id:#x}")

    def cstr(self, va: int) -> str:
        out = bytearray()
        while True:
            c = self.read(va, 1)[0]
            if c == 0:
                return out.decode("latin-1")
            out.append(c)
            va += 1


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


def all_callers(exe: Exe, target: int) -> list[int]:
    sec = next(s for s in exe.pe.sections if s.Name.startswith(b".text"))
    text = sec.get_data()
    va0 = exe.base + sec.VirtualAddress
    out = []
    for k in range(len(text) - 5):
        if text[k] in (0xE8, 0xE9) and (va0 + k + 5 + struct.unpack_from("<i", text, k + 1)[0]) & 0xFFFFFFFF == target:
            out.append(va0 + k)
    return out


def validate(data: bytes) -> dict:
    if hashlib.sha256(data).hexdigest() != VANILLA_EXE_SHA256:
        raise SiteError("not the vanilla Virtual Families.exe the pins are taken from")
    exe = Exe(data)
    if exe.base != 0x400000:
        raise SiteError("not the VF1 image base")
    pins = {}
    for name, va, n, note in PINS:
        raw = exe.read(va, n)
        if sum(i.size for i in _md().disasm(raw, va)) != n:
            raise SiteError(f"{name}: not whole instructions")
        pins[name] = (va, raw, mask_for(raw, va))
    for name, values in CROSS.items():
        va, raw, _m = pins[name]
        got = _operands(raw, va)
        for v in values:
            if (v & 0xFFFFFFFF) not in got:
                raise SiteError(f"{name}: no operand {v:#x}")
    for pin, at, func in CALLS + tuple((p, a, t) for p, a, t in CALL_HOOKS):
        va, raw, _m = pins[pin]
        if not va <= at <= va + len(raw) - 5:
            raise SiteError(f"{pin}: call {at:#x} outside the pin")
        if call_target(exe, at) != func:
            raise SiteError(f"{pin}+{at - va:#x}: calls {call_target(exe, at):#x}, not {func:#x}")
    # Each retargeted call is the ONLY call (or jmp) of its function: nothing else reaches it unseen.
    singles = {0x4864D0: [0x48EBB2], 0x48BC90: [0x424F93], 0x481CF0: [0x489D8F, 0x48E200], 0x4243C0: [0x448426]}
    for target, sites in singles.items():
        if all_callers(exe, target) != sites:
            raise SiteError(f"{target:#x} has callers {[hex(x) for x in all_callers(exe, target)]}")
    for name, (pin, steal) in ENTRY_HOOKS.items():
        va, raw, _m = pins[pin]
        size = 0
        for i in _md().disasm(raw[:steal], va):
            if i.mnemonic.startswith("j") or i.mnemonic in ("call", "ret"):
                raise SiteError(f"{name}: a branch in the stolen bytes")
            for op in i.operands:
                if op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                    raise SiteError(f"{name}: an absolute operand in the stolen bytes")
            size += i.size
        if size != steal or steal < 5:
            raise SiteError(f"{name}: the stolen bytes are not whole instructions")
        for i in _md().disasm(raw, va):
            if (i.mnemonic.startswith("j") or i.mnemonic == "loop") and i.operands \
                    and i.operands[0].type == X86_OP_IMM and va < i.operands[0].imm < va + steal:
                raise SiteError(f"{name}: a branch into the stolen bytes")
    # The only writers of the cause (CVillagerState+0x10) and of 0 to the pregnancy field.
    va, raw, _m = pins["vm_delivery"]
    zeroes = [i for i in _md().disasm(raw, va) if i.mnemonic == "mov" and i.operands[0].type == X86_OP_MEM
              and (i.operands[0].mem.disp & 0xFFFFFFFF) == NEG(VILLAGER_LEFT_HOME - VILLAGER_PREGNANT)]
    if len(zeroes) != 1 or zeroes[0].address != 0x48C2EE:
        raise SiteError("the delivery does not clear the pregnancy exactly once, at 0x48C2EE")
    # theGameState's vtable: Load, Save and MakeGameStatePath.
    if struct.unpack("<I", exe.read(GS_VTABLE_LOAD, 4))[0] != FUNCTIONS["GS_LOAD"] or \
            struct.unpack("<I", exe.read(GS_VTABLE_SAVE, 4))[0] != FUNCTIONS["GS_SAVE"]:
        raise SiteError("theGameState Load / Save slots")
    if struct.unpack("<I", exe.read(0x4B5E40, 4))[0] != PIN["ldw_make_path"][1]:
        raise SiteError("theGameState vtable +0Ch is not MakeGameStatePath")
    # The words: the exe's own.
    for sid, want in ((STR_MALE, "Male"), (STR_FEMALE, "Female"), (STR_NURSING, "Nursing"),
                      (STR_COLLEGE_TITLE, "{name} is going to college!"), (STR_CAUSE_UNKNOWN, "Unknown causes"),
                      (STR_CAUSE_UNKNOWN + 3, "Old age"), (STR_CAUSE_LAST, "Act of Nature")):
        if exe.string_record(sid)[1] != want:
            raise SiteError(f"string {sid:#x} is not {want!r}")
    return pins


def render_header(pins: dict) -> str:
    arr = lambda b: ", ".join(f"0x{x:02X}" for x in b)  # noqa: E731
    out = [
        "// GENERATED by tools/vf1_logs_sites.py from the vanilla Virtual Families.exe. Do not edit.",
        "// Every pin is the exact bytes of stock code at its fixed address (VF1 has no ASLR); mask 1 = a",
        "// call/jmp displacement, which another hook may have retargeted. The DLL installs nothing unless",
        "// every pin matches (a hooked entry may also hold another companion's 5-byte jmp).",
        "#pragma once",
        "",
        "struct LogsPin { const char *name; unsigned va; unsigned len; const unsigned char *bytes; const unsigned char *mask; };",
        "struct LogsCallHook { unsigned site; unsigned target; };",
        "struct LogsEntryHook { unsigned va; unsigned steal; };",
        "",
    ]
    for key, value in sorted(globals().items()):
        if key.isupper() and isinstance(value, int) and not isinstance(value, bool) \
                and not key.startswith(("CS_", "X86_")):
            out.append(f"#define LOGS_{key} 0x{value:X}u")
    out.append("")
    for name, va in FUNCTIONS.items():
        out.append(f"#define LOGS_{name} 0x{va:X}u")
    out.append("")
    for name, (va, raw, mask) in pins.items():
        out.append(f"static const unsigned char lpin_{name}[] = {{ {arr(raw)} }};")
        out.append(f"static const unsigned char lmask_{name}[] = {{ {arr(mask)} }};")
    out.append("")
    out.append("static const LogsPin LOGS_PINS[] = {")
    for name, (va, raw, mask) in pins.items():
        out.append(f'    {{ "{name}", 0x{va:X}u, {len(raw)}u, lpin_{name}, lmask_{name} }},')
    out.append("};")
    out.append("")
    out.append("enum { " + ", ".join(f"LOGS_CALL_{n} = {i}" for i, n in enumerate(CALL_HOOK_NAMES)) + " };")
    out.append("static const LogsCallHook LOGS_CALL_HOOKS[] = {")
    for (pin, site, target), n in zip(CALL_HOOKS, CALL_HOOK_NAMES):
        out.append(f"    {{ 0x{site:X}u, 0x{target:X}u }},   // {n}")
    out.append("};")
    out.append("")
    out.append("enum { " + ", ".join(f"LOGS_ENTRY_{n} = {i}" for i, n in enumerate(ENTRY_HOOKS)) + " };")
    out.append("static const LogsEntryHook LOGS_ENTRY_HOOKS[] = {")
    for name, (pin, steal) in ENTRY_HOOKS.items():
        out.append(f"    {{ LOGS_{name}, {steal}u }},   // {name}")
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
