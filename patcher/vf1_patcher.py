#!/usr/bin/env python3
"""Virtual Families 1 Patcher: build a patched copy of the game.

The patched game is written to a NEW folder; the source game folder is only
read. The executable gets one hook and two new sections:

* .vf1fun (read + execute): a stub that runs at the end of the store screen's
  constructor. The first time, it loads
  "<game folder>\\Virtual Families 1 Patcher Files\\vf1fun.dll" by full path
  (GetModuleFileNameW + LoadLibraryW, resolved through GetProcAddress) and
  looks up VF1Fun_StoreCreated. Every time, if that worked, it calls
  VF1Fun_StoreCreated(store scene). A missing DLL or export means the stock
  game: the stub remembers the failure and does nothing more.
* .vf1fud (read + write): the stub's state and path buffer. No page is both
  writable and executable.

Everything else (the Upgrades button, the dialogs) lives in vf1fun.dll.

usage: vf1_patcher.py apply --game-dir VANILLA --output-dir NEW [--dll PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path


VANILLA_EXE = "Virtual Families.exe"
VANILLA_SHA256 = "5db828c3f53c68696c18719aec0eb114be3fd4458ae2cbf185d8d4ef7eca4487"
PATCHER_FOLDER = "Virtual Families 1 Patcher Files"
DLL_NAME = "vf1fun.dll"

# theStoreScene constructor tail: `mov ecx, esi; call 0x448BE0` (8B CE E8 rel32).
HOOK_SITE = 0x4497E6
HOOK_ORIGINAL_TARGET = 0x448BE0
HOOK_EXPECTED = bytes.fromhex("e8 f5 f3 ff ff")
# KERNEL32 imports already present in the vanilla import table.
IAT_GET_MODULE_HANDLE_A = 0x4B21D4
IAT_GET_PROC_ADDRESS = 0x4B21D8


class PatchError(RuntimeError):
    pass


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


class PE:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        d = self.data
        self.pe = struct.unpack_from("<I", d, 0x3C)[0]
        self.nsec_off = self.pe + 6
        self.opt = self.pe + 24
        self.optsz = struct.unpack_from("<H", d, self.pe + 20)[0]
        self.base = struct.unpack_from("<I", d, self.opt + 28)[0]
        self.sect_align, self.file_align = struct.unpack_from("<II", d, self.opt + 32)

    @property
    def nsec(self):
        return struct.unpack_from("<H", self.data, self.nsec_off)[0]

    def sections(self):
        out = []
        for i in range(self.nsec):
            o = self.opt + self.optsz + i * 40
            name = bytes(self.data[o:o + 8]).rstrip(b"\0").decode()
            vsize, va, rsize, raw = struct.unpack_from("<IIII", self.data, o + 8)
            out.append((name, va, vsize, raw, rsize))
        return out

    def offset(self, va: int) -> int:
        rva = va - self.base
        for _n, sva, vsize, raw, rsize in self.sections():
            if sva <= rva < sva + max(vsize, rsize):
                return raw + rva - sva
        raise PatchError(f"address {va:#x} is not in the file")

    def next_section_va(self) -> int:
        last = self.sections()[-1]
        return self.base + _align(last[1] + max(last[2], last[4]), self.sect_align)

    def add_section(self, name: str, payload: bytes, characteristics: int) -> int:
        hdr = self.opt + self.optsz + self.nsec * 40
        first_raw = min(s[3] for s in self.sections() if s[3])
        if hdr + 40 > first_raw:
            raise PatchError("no room for another section header")
        if any(self.data[hdr:hdr + 40]):
            raise PatchError("section header slot is not empty")
        va = self.next_section_va()
        raw = _align(len(self.data), self.file_align)
        rsize = _align(len(payload), self.file_align)
        self.data.extend(b"\0" * (raw - len(self.data)))
        self.data.extend(payload + b"\0" * (rsize - len(payload)))
        struct.pack_into("<8sIIIIIIHHI", self.data, hdr, name.encode().ljust(8, b"\0"),
                         len(payload), va - self.base, rsize, raw, 0, 0, 0, 0, characteristics)
        struct.pack_into("<H", self.data, self.nsec_off, self.nsec + 1)
        struct.pack_into("<I", self.data, self.opt + 56, _align(va - self.base + len(payload), self.sect_align))
        return va

    def update_checksum(self):
        off = self.opt + 64
        struct.pack_into("<I", self.data, off, 0)
        total = 0
        d = bytes(self.data) + b"\0" * (len(self.data) % 2)
        for (word,) in struct.iter_unpack("<H", d):
            total += word
            total = (total & 0xFFFF) + (total >> 16)
        total = (total & 0xFFFF) + (total >> 16)
        struct.pack_into("<I", self.data, off, (total + len(self.data)) & 0xFFFFFFFF)


STUB = Path(__file__).resolve().with_name("stub.json")
# theGame's vtable slot for Init (slot 4); stock value theGame::Init.
INIT_SLOT = 0x4B5E14
INIT_SLOT_EXPECTED = 0x422AE0


def patch_executable(vanilla: bytes) -> bytes:
    """Return the patched executable. The stub (built by tools/build_stub.py
    and stored in stub.json) gets its own read-execute section, its state a
    separate read-write section, and two pointers in the game lead into it."""
    if hashlib.sha256(vanilla).hexdigest() != VANILLA_SHA256:
        raise PatchError("this is not the vanilla Virtual Families 1.01.00 executable")
    stub = json.loads(STUB.read_text())
    code_va, data_va = int(stub["code_va"], 16), int(stub["data_va"], 16)
    pe = PE(vanilla)
    site = pe.offset(HOOK_SITE)
    if bytes(pe.data[site:site + 5]) != HOOK_EXPECTED:
        raise PatchError("unexpected bytes at the store hook")
    slot = pe.offset(INIT_SLOT)
    if struct.unpack_from("<I", pe.data, slot)[0] != INIT_SLOT_EXPECTED:
        raise PatchError("unexpected theGame::Init vtable slot")
    if pe.next_section_va() != code_va:
        raise PatchError("the stub was built for a different section address")
    pe.add_section(".vf1fun", bytes.fromhex(stub["code"]), 0x60000020)  # code | execute | read
    if pe.add_section(".vf1fud", bytes(stub["data_size"]), 0xC0000040) != data_va:  # data | read | write
        raise PatchError("data section landed at an unexpected address")
    rel = int(stub["store_entry"], 16) - (HOOK_SITE + 5)
    pe.data[site:site + 5] = bytes([0xE8]) + struct.pack("<i", rel)
    struct.pack_into("<I", pe.data, slot, int(stub["init_entry"], 16))
    pe.update_checksum()
    return bytes(pe.data)


def apply(game_dir: Path, output_dir: Path, dll: Path) -> Path:
    game_dir, output_dir = game_dir.resolve(), output_dir.resolve()
    if output_dir == game_dir or game_dir in output_dir.parents:
        raise PatchError("the output folder must be a new folder outside the game folder")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PatchError(f"output folder is not empty: {output_dir}")
    exe = game_dir / VANILLA_EXE
    patched = patch_executable(exe.read_bytes())
    shutil.copytree(game_dir, output_dir, dirs_exist_ok=True)
    (output_dir / VANILLA_EXE).write_bytes(patched)
    files = output_dir / PATCHER_FOLDER
    files.mkdir(exist_ok=True)
    shutil.copy2(dll, files / DLL_NAME)
    return output_dir / VANILLA_EXE


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--game-dir", required=True, type=Path)
    a.add_argument("--output-dir", required=True, type=Path)
    a.add_argument("--dll", type=Path, default=Path(__file__).resolve().parents[1] / "build" / DLL_NAME)
    a.add_argument("--exe-name", help="rename the patched executable (test builds get their own save folder)")
    args = ap.parse_args()
    try:
        exe = apply(args.game_dir, args.output_dir, args.dll)
        if args.exe_name:
            exe = exe.rename(exe.with_name(args.exe_name))
    except PatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"patched: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
