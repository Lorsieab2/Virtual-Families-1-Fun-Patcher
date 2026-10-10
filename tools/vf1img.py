"""Shared read-only helpers for analysing the VF1 executable."""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

ROOT = Path(__file__).resolve().parents[1]


class Image:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
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
        self.md = Cs(CS_ARCH_X86, CS_MODE_32)
        def load(name):
            path = ROOT / "data" / name
            return {int(a, 16): v for a, v in json.loads(path.read_text()).items()} if path.exists() else {}
        # Checked names: vtables, plus hand-verified addresses (value is a dict
        # with "name" and "evidence"). Call-graph hints are shown with "?hint".
        self.names = load("vf1_vtable_names.json")
        self.names.update({a: v["name"] for a, v in load("vf1_verified.json").items()})
        self.hints = load("vf1_callgraph_hints.json")

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
        end = self.data.find(b"\0", o)
        return self.data[o:end].decode("latin-1") if 0 <= end - o < 400 else None

    def is_code(self, va):
        _n, sva, vsize, _r, _rs = self.section(".text")
        return va is not None and sva <= va < sva + vsize

    def vtable(self, cls):
        """VF1 vtable slots for an RTTI class name."""
        d = self.data
        m = re.search(rb"\.\?AV" + cls.encode() + rb"@@\0", d)
        td = self.va(m.start()) - 8
        _n, rva, _vs, rraw, rsize = self.section(".rdata")
        for o in range(rraw, rraw + rsize - 20, 4):
            sig, off, _cd, ptd = struct.unpack_from("<IIII", d, o)
            if sig == 0 and off == 0 and ptd == td:
                col = rva + o - rraw
                ref = d.find(struct.pack("<I", col), rraw, rraw + rsize)
                vt = self.va(ref) + 4
                slots = []
                while self.is_code(self.u32(vt + 4 * len(slots))):
                    slots.append(self.u32(vt + 4 * len(slots)))
                return vt, slots
        return None, []

    def label(self, va):
        n = self.names.get(va)
        if n:
            return n
        if va in self.hints:
            return "?hint " + self.hints[va]
        s = self.cstr(va)
        if s and len(s) > 2 and all(32 <= ord(c) < 127 for c in s):
            return repr(s)
        return ""

    def disasm(self, va, limit=0x2000, stop_at_int3=True):
        o = self.offset(va)
        out = []
        for ins in self.md.disasm(self.data[o:o + limit], va):
            note = ""
            for tok in re.findall(r"0x[0-9a-f]+", ins.op_str):
                lab = self.label(int(tok, 16))
                if lab:
                    note += " ; " + lab
            out.append((ins.address, ins.mnemonic, ins.op_str, note))
            if stop_at_int3 and ins.mnemonic == "int3":
                break
        return out

    def xrefs_to(self, target):
        """Code addresses whose call/jmp rel32 or push/mov imm32 is target."""
        _n, tva, tvs, traw, _r = self.section(".text")
        d = self.data
        out = []
        packed = struct.pack("<I", target)
        start = traw
        while True:
            i = d.find(packed, start, traw + tvs)
            if i < 0:
                break
            out.append(("abs", self.va(i)))
            start = i + 1
        for i in range(traw, traw + tvs - 5):
            if d[i] in (0xE8, 0xE9):
                rel = struct.unpack_from("<i", d, i + 1)[0]
                src = tva + i - traw
                if src + 5 + rel == target:
                    out.append(("call" if d[i] == 0xE8 else "jmp", src))
        return out


def vf1_exe(path=None):
    return Image(path or r"C:\Users\Owner\Downloads\Read-Only Vanilla LDW Games\Virtual Families\Virtual Families.exe")
