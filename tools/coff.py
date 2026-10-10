"""Minimal read-only COFF object reader (i386).

Adapted from the Virtual Families 2 Restoration patcher's work/coff_patch.py,
reduced to the read side: sections, symbols, relocations and section bytes.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Section:
    index: int
    name: str
    raw_size: int
    raw_ptr: int
    reloc_ptr: int
    nreloc: int


@dataclass
class Symbol:
    index: int
    name: str
    value: int
    section: int


class CoffObject:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.buf = self.path.read_bytes()
        (_machine, nsects, _stamp, symptr, nsyms, opthdr, _chars) = struct.unpack_from(
            "<HHIIIHH", self.buf, 0)
        strtab_ptr = symptr + nsyms * 18
        size = struct.unpack_from("<I", self.buf, strtab_ptr)[0]
        self.strtab = self.buf[strtab_ptr:strtab_ptr + size]
        self.sections = []
        off = 20 + opthdr
        for i in range(1, nsects + 1):
            name = self.buf[off:off + 8].split(b"\0", 1)[0].decode("ascii", "replace")
            (_vs, _va, raw_size, raw_ptr, reloc_ptr, _lp, nreloc, _nl, _ch) = struct.unpack_from(
                "<IIIIIIHHI", self.buf, off + 8)
            self.sections.append(Section(i, name, raw_size, raw_ptr, reloc_ptr, nreloc))
            off += 40
        self.symbols = []
        pos, idx = symptr, 0
        while idx < nsyms:
            value, sectnum, _typ, _storage, aux = struct.unpack_from("<IhHBB", self.buf, pos + 8)
            self.symbols.append(Symbol(idx, self._name_at(pos), value, sectnum))
            pos += 18 * (1 + aux)
            idx += 1 + aux
        self.symbol_by_index = {s.index: s for s in self.symbols}
        self._relocs = {}

    def _name_at(self, pos: int) -> str:
        raw = self.buf[pos:pos + 8]
        zeroes, str_off = struct.unpack_from("<II", raw, 0)
        if zeroes == 0 and 0 <= str_off < len(self.strtab):
            end = self.strtab.find(b"\0", str_off)
            return self.strtab[str_off:end if end >= 0 else None].decode("ascii", "replace")
        return raw.split(b"\0", 1)[0].decode("ascii", "replace")

    def section(self, index: int) -> Section:
        return self.sections[index - 1]

    def section_bytes(self, index: int) -> bytes:
        sec = self.section(index)
        return self.buf[sec.raw_ptr:sec.raw_ptr + sec.raw_size]

    def relocations(self, index: int) -> dict[int, tuple[str, int]]:
        """{offset in section: (target symbol name, relocation type)}"""
        if index not in self._relocs:
            sec = self.section(index)
            out = {}
            for i in range(sec.nreloc):
                va, symidx, rtype = struct.unpack_from("<IIH", self.buf, sec.reloc_ptr + i * 10)
                out[va] = (self.symbol_by_index[symidx].name, rtype)
            self._relocs[index] = out
        return self._relocs[index]
