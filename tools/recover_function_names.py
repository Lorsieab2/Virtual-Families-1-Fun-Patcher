#!/usr/bin/env python3
"""Recover names for functions in the Virtual Families 1 executable.

VF1 ships no symbols, but Virtual Families 2 (built two days later with the
same compiler, sharing 145 of VF1's 150 classes) has object files with full
names. This tool transfers names from those objects to VF1 in three steps:

1. Vtables. VF1 keeps MSVC RTTI. For every class, the dword before its vtable
   points at a Complete Object Locator naming the class. VF2's object file
   holds the same class's vtable (??_7Class@@6B@) with one relocation per
   slot naming the method, so slot N of VF1's vtable gets the name of slot N.
2. Validation. Every island event's GetTitle returns a string id. VF1's own
   string table pairs each id with its key, so a GetTitle named for event X
   must return the id whose key is eEvent<X>Title (or the same without "The").
   Run with --strict to fail when any does not.
3. Call graph (HINTS ONLY). For a named VF1 function, its direct calls are
   paired, in order, with the direct calls in VF2's object for the same name
   when both lists have the same length and every already-known pair agrees.
   Repeated to a fixpoint; an address that would get two names is dropped.
   These names are NOT reliable: equal-length call lists line up by chance
   (0x489a30 came out as CMoney::UpdateInterest but counts villagers by
   career; 0x48ab50 as MakeAllVillagersDoIt at 33 bytes against 230). They are
   written to a separate file, and each must be confirmed by reading its code
   before anything depends on it.

Byte-for-byte matching does not work: VF2's object files do not produce the
same code as either shipped game (only 14 functions match exactly).

usage:
  recover_function_names.py --vf1-exe PATH --vf2-objs DIR --out vtable_names.json
                            --hints-out callgraph_hints.json
                            [--strings-out strings.json] [--strict]
Read-only: nothing is written except the output files.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coff import CoffObject  # noqa: E402

REL32 = 0x14


class Image:
    """A read-only view of a 32-bit PE file by virtual address."""

    def __init__(self, path: Path):
        self.data = path.read_bytes()
        d = self.data
        pe = struct.unpack_from("<I", d, 0x3C)[0]
        count = struct.unpack_from("<H", d, pe + 6)[0]
        optsz = struct.unpack_from("<H", d, pe + 20)[0]
        self.base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
        self.sections = []
        for i in range(count):
            o = pe + 24 + optsz + i * 40
            name = d[o:o + 8].rstrip(b"\0").decode()
            vsize, va, rsize, raw = struct.unpack_from("<IIII", d, o + 8)
            self.sections.append((name, self.base + va, vsize, raw, rsize))

    def section(self, name):
        return next(s for s in self.sections if s[0] == name)

    def offset(self, va):
        for _n, sva, _vs, raw, rsize in self.sections:
            if sva <= va < sva + rsize:
                return raw + va - sva
        return None

    def va(self, offset):
        for _n, sva, _vs, raw, rsize in self.sections:
            if raw <= offset < raw + rsize:
                return sva + offset - raw
        return None

    def u32(self, va):
        o = self.offset(va)
        return None if o is None else struct.unpack_from("<I", self.data, o)[0]

    def cstr(self, va):
        o = self.offset(va)
        if o is None:
            return None
        return self.data[o:self.data.index(b"\0", o)].decode("latin-1")

    def is_code(self, va):
        _n, sva, vsize, _r, _rs = self.section(".text")
        return va is not None and sva <= va < sva + vsize


def vf1_vtables(img: Image):
    """{class name: [(vtable va, [slot code addresses])]} from RTTI."""
    d = img.data
    type_descriptors = {}
    for m in re.finditer(rb"\.\?AV(\w+)@@\0", d):
        va = img.va(m.start())
        if va is not None:
            type_descriptors[va - 8] = m.group(1).decode()
    _n, rva, _vs, rraw, rsize = img.section(".rdata")
    locators = {}
    for o in range(rraw, rraw + rsize - 20, 4):
        sig, off, _cd, ptd, _pch = struct.unpack_from("<IIIII", d, o)
        if sig == 0 and off == 0 and ptd in type_descriptors:
            locators[rva + o - rraw] = type_descriptors[ptd]
    vtables = defaultdict(list)
    for o in range(rraw, rraw + rsize - 8, 4):
        p = struct.unpack_from("<I", d, o)[0]
        if p in locators:
            vt = rva + o - rraw + 4
            slots = []
            while img.is_code(img.u32(vt + 4 * len(slots))):
                slots.append(img.u32(vt + 4 * len(slots)))
            vtables[locators[p]].append((vt, slots))
    return vtables


def object_vtables_and_calls(objs: Path, md: Cs):
    """VF2 objects: ({class: [slot method names]}, {function: [call names]})."""
    vtables, calls = {}, {}
    for path in sorted(objs.glob("*.obj")):
        obj = CoffObject(path)
        by_section = defaultdict(list)
        for s in obj.symbols:
            if s.section <= 0:
                continue
            sec = obj.section(s.section)
            relocs = obj.relocations(s.section)
            if s.name.startswith("??_7") and s.name.endswith("@@6B@"):
                slots, k = [], 0
                while (s.value + 4 * k) in relocs:
                    slots.append(relocs[s.value + 4 * k][0])
                    k += 1
                vtables.setdefault(s.name[4:-5], slots)
            elif sec.name.startswith(".text") and s.name[:1] in "?_":
                by_section[s.section].append(s)
        for secno, syms in by_section.items():
            sec = obj.section(secno)
            relocs = obj.relocations(secno)
            code = obj.section_bytes(secno)
            syms.sort(key=lambda s: s.value)
            for k, s in enumerate(syms):
                end = syms[k + 1].value if k + 1 < len(syms) else len(code)
                found = []
                for ins in md.disasm(code[s.value:end], s.value):
                    if ins.mnemonic == "call" and ins.size == 5:
                        target = relocs.get(ins.address + 1)
                        if target and target[1] == REL32:
                            found.append(target[0])
                calls.setdefault(s.name, found)
    return vtables, calls


def string_table(img: Image):
    """{string id: key} from VF1's string table (16-byte records id, key*,
    text*, 0), located through a key that is known to exist."""
    d = img.data
    anchor = img.va(d.index(b"eEventTheNeighborWeatherTitle\0"))
    record = d.index(struct.pack("<I", anchor)) - 4

    def key_at(o):
        k = struct.unpack_from("<I", d, o + 4)[0]
        s = img.cstr(k) if k else None
        return s if s and s.startswith("e") else None

    while key_at(record - 16):
        record -= 16
    table = {}
    while key_at(record):
        table[struct.unpack_from("<I", d, record)[0]] = key_at(record)
        record += 16
    return table


def vf1_direct_calls(img: Image, md: Cs, addr: int, limit=0x4000):
    out = []
    o = img.offset(addr)
    for ins in md.disasm(img.data[o:o + limit], addr):
        if ins.mnemonic == "call" and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16)
            if img.is_code(t):
                out.append(t)
        if ins.mnemonic == "int3":
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vf1-exe", required=True, type=Path)
    ap.add_argument("--vf2-objs", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help="checked names (vtables)")
    ap.add_argument("--hints-out", required=True, type=Path, help="unverified call-graph names")
    ap.add_argument("--strings-out", type=Path)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    md = Cs(CS_ARCH_X86, CS_MODE_32)
    img = Image(args.vf1_exe)
    vtables = vf1_vtables(img)
    obj_vtables, obj_calls = object_vtables_and_calls(args.vf2_objs, md)

    names: dict[int, str] = {}
    for cls, entries in vtables.items():
        if cls not in obj_vtables or len(entries) != 1:
            continue
        for addr, name in zip(entries[0][1], obj_vtables[cls]):
            names.setdefault(addr, name)
    from_vtables = len(names)

    table = string_table(img)
    good, bad = 0, []
    for addr, name in names.items():
        m = re.match(r"\?GetTitle@CEvent(\w+)@@", name)
        if not m:
            continue
        ins = next(md.disasm(img.data[img.offset(addr):img.offset(addr) + 8], addr))
        if ins.mnemonic == "mov" and ins.op_str.startswith("eax, "):
            key = table.get(int(ins.op_str.split(", ")[1], 16))
            event = m.group(1)
            if key in (f"eEvent{event}Title", f"eEvent{event.removeprefix('The')}Title"):
                good += 1
            else:
                bad.append((name, key))

    checked = dict(names)
    by_name = defaultdict(set)
    for a, n in names.items():
        by_name[n].add(a)
    dropped = set()
    while True:
        added = 0
        for addr, name in list(names.items()):
            expected = obj_calls.get(name)
            if not expected:
                continue
            actual = vf1_direct_calls(img, md, addr)
            if len(actual) != len(expected):
                continue
            if any(names.get(a) not in (None, n) for a, n in zip(actual, expected)):
                continue
            for a, n in zip(actual, expected):
                if a in names or a in dropped:
                    continue
                if n.startswith("?") and by_name[n] - {a}:
                    dropped.add(a)
                    continue
                names[a] = n
                by_name[n].add(a)
                added += 1
        if not added:
            break

    # Only the vtable names are checked; everything the call graph added is a
    # hint and goes to its own file.
    args.out.write_text(json.dumps({hex(a): n for a, n in sorted(checked.items())}, indent=1) + "\n")
    hints = {hex(a): n for a, n in sorted(names.items()) if a not in checked}
    args.hints_out.write_text(json.dumps(hints, indent=1) + "\n")
    if args.strings_out:
        args.strings_out.write_text(json.dumps({str(k): v for k, v in sorted(table.items())}, indent=1) + "\n")
    print(f"vtable classes {len(vtables)}; checked names from vtables {from_vtables}; "
          f"unverified call-graph hints {len(names) - from_vtables} (dropped {len(dropped)})")
    print(f"string table {len(table)} keys; event GetTitle check: {good} ok, {len(bad)} wrong {bad[:5]}")
    return 1 if args.strict and bad else 0


if __name__ == "__main__":
    sys.exit(main())
