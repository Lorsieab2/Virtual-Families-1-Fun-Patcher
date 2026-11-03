"""Runs vf1tr.dll (Translations) on Virtual Families 1's own string code in Unicorn: the REAL vanilla executable
(VF1_VANILLA_DIR, read only) and the REAL compiled DLL, mapped into one address space by kids_emu.Emu.

Game code that runs as it is: theStringManagerImpl's constructor 0x450200 (it indexes the static records by id),
theStringManager::GetString 0x44FD90 and GetStringFromNameGenderTemplate 0x44FDD0 (the game's own {name} and
{he/she} filling, with strchr / strstr / strncpy / strncat of the game's C runtime), and the guarded calls' own
instructions.

Stood in for: the path provider 0x402F50 and fopen 0x498DAC (no "sm.xml", as in the shipped game), sprintf
0x4985BB at the guarded calls (a Python sprintf of %s / %d / %%), and the DLL's kernel32 calls (its files are
Python bytes: Translation.ini, the translation, Translations.log).  Nothing here starts the game.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from unicorn.x86_const import UC_X86_REG_ESP

import kids_emu as K

FOLDER = "C:\\Game\\Virtual Families 1 Patcher Files\\"
DLL_PATH = FOLDER + "vf1tr.dll"
CHOSEN = "C:\\Translations\\Virtual Families - Test.txt"
GET_STRING, TEMPLATE, MANAGER_CTOR = 0x44FD90, 0x44FDD0, 0x450200
SPRINTF = 0x4985BB


def c_sprintf(e: K.Emu, fmt: bytes, args: list[int]) -> bytes:
    out = bytearray()
    k = 0
    i = 0
    while i < len(fmt):
        if fmt[i:i + 1] == b"%":
            m = re.match(rb"%([-+ #0]*)(\d*)([dsiu%])", fmt[i:])
            if not m:
                raise K.EmuError(f"unexpected format {fmt!r}")
            kind = m.group(3)
            if kind == b"%":
                out += b"%"
            elif kind == b"s":
                out += e.read_cstr_bytes(args[k])
                k += 1
            else:
                out += str(struct.unpack("<i", struct.pack("<I", args[k]))[0]).encode()
                k += 1
            i += len(m.group(0))
            continue
        out += fmt[i:i + 1]
        i += 1
    return bytes(out)


class Emu(K.Emu):
    def read_cstr_bytes(self, addr: int) -> bytes:
        out = bytearray()
        while True:
            c = self.read(addr, 1)
            if c == b"\0":
                return bytes(out)
            out += c
            addr += 1


class TranslationWorld:
    """One emulated process: the game's string manager, vf1tr.dll started over the given files."""

    def __init__(self, exe: Path, dll: Path, files: dict[str, bytes], unicode_dll: bool = False,
                 unicode_active: bool = True):
        self.e = e = Emu(exe, dll, 0)
        self.files = {k.lower(): v for k, v in files.items()}     # path -> bytes (reading)
        self.written: dict[str, bytearray] = {}
        self.handles: dict[int, list] = {}
        self.next_handle = 0x700
        self.protect_calls: list[int] = []
        if unicode_dll:
            # vf1text.dll is loaded; whether its hooks are installed is what its VF1Text_UnicodeTextActive answers
            e.modules["vf1text.dll"] = 0x6E000000
            e.dyn_procs["VF1Text_UnicodeTextActive"] = lambda em: (1 if unicode_active else 0, 0)
        self._seams()
        self.installed = None

    def _seams(self) -> None:
        e = self.e

        def module_file_name(em):
            buf, size = em.arg(1), em.arg(2)
            em.write(buf, DLL_PATH.encode("utf-16-le") + b"\0\0")
            return len(DLL_PATH), 12

        def create_file(em):
            path, access = em.wstr(em.arg(0)), em.arg(1)
            self.next_handle += 4
            if access & 0x40000000:                                  # GENERIC_WRITE
                self.written[path] = bytearray()
                self.handles[self.next_handle] = ["w", path]
                return self.next_handle, 28
            data = self.files.get(path.lower())
            if data is None:
                return 0xFFFFFFFF, 28
            self.handles[self.next_handle] = ["r", data, 0]
            return self.next_handle, 28

        def file_size(em):
            h, high = em.arg(0), em.arg(1)
            if high:
                em.w32(high, 0)
            return len(self.handles[h][1]), 8

        def read_file(em):
            h, buf, n, got = (em.arg(i) for i in range(4))
            entry = self.handles[h]
            piece = entry[1][entry[2]:entry[2] + n]
            em.write(buf, piece)
            entry[2] += len(piece)
            if got:
                em.w32(got, len(piece))
            return 1, 20

        def write_file(em):
            h, buf, n, done = (em.arg(i) for i in range(4))
            self.written[self.handles[h][1]] += em.read(buf, n)
            if done:
                em.w32(done, n)
            return 1, 20

        def virtual_protect(em):
            self.protect_calls.append(em.arg(0))
            if em.arg(3):
                em.w32(em.arg(3), 0x20)
            return 1, 16

        def virtual_query(em):
            info = em.arg(1)
            # BaseAddress, AllocationBase, AllocationProtect, RegionSize, State, Protect, Type
            em.write(info, struct.pack("<7I", em.arg(0) & ~0xFFF, 0x400000, 0x20, 0x1000, 0x1000, 0x20, 0x1000000))
            return 28, 12

        e.imports.update({
            "GetModuleFileNameW": module_file_name, "CreateFileW": create_file, "GetFileSize": file_size,
            "ReadFile": read_file, "WriteFile": write_file, "CloseHandle": lambda em: (1, 4),
            "GetProcessHeap": lambda em: (0x7777, 0), "HeapAlloc": lambda em: (em.alloc(max(4, em.arg(2))), 12),
            "VirtualProtect": virtual_protect, "VirtualQuery": virtual_query,
            "FlushInstructionCache": lambda em: (1, 12), "GetCurrentProcess": lambda em: (0xFFFFFFFF, 0),
        })
        # the string manager's file: no sm.xml (the shipped game has none)
        path_object = e.alloc(16)
        vtable = e.alloc(16)
        provider = e.fake_code(bytes.fromhex("b8") + struct.pack("<I", e.alloc(8)) + bytes.fromhex("c20400"))
        e.w32(path_object, vtable)
        e.w32(vtable + 8, provider)
        e.seam(0x402F50, lambda em: (path_object, 0))
        e.seam(0x498DAC, lambda em: (0, 0))                         # fopen("sm.xml") -> NULL

        def sprintf(em):
            dst, fmt = em.arg(0), em.arg(1)
            text = c_sprintf(em, em.read_cstr_bytes(fmt), [em.arg(2 + k) for k in range(8)])
            em.write(dst, text + b"\0")
            return len(text), 0
        e.seam(SPRINTF, sprintf)

    # ------------------------------------------------------------------ running
    def start(self) -> int:
        self.installed = self.e.call(self.e.dll_export("VF1Tr_Startup"))
        self.manager = self.e.alloc(16)
        self.e.call(MANAGER_CTOR, ecx=self.manager)
        return self.installed

    def log(self) -> str:
        data = bytes(self.written.get(FOLDER + "Translations.log", b""))
        return data.decode("utf-8-sig")

    def get_string(self, sid: int) -> bytes:
        return self.e.read_cstr_bytes(self.e.call(GET_STRING, (sid,), ecx=self.manager))

    def translation_of(self, sid: int) -> int:
        return self.e.call(self.e.dll_export("VF1Tr_Translation"), (sid,))

    def template(self, sid: int, name: bytes, male: bool, award: int = 0, name2: bytes = b"", male2: bool = True,
                 size: int = 512) -> bytes:
        """GetStringFromNameGenderTemplate(out, size, id, name, male, award, name2, male2), the game's own."""
        e = self.e
        out = e.alloc(size + 64, fill=0xCC)
        n1, n2 = e.alloc(len(name) + 1), e.alloc(len(name2) + 1)
        e.write(n1, name + b"\0")
        e.write(n2, name2 + b"\0")
        e.call(TEMPLATE, (out, size, sid, n1, int(male), award, n2, int(male2)), ecx=self.manager)
        text = e.read_cstr_bytes(out)
        assert len(text) < size and e.read(out + size, 64) == b"\xCC" * 64, "the template wrote past its buffer"
        return text

    def run_call(self, call_at: int, args: list[int]) -> int:
        """The game's own `call rel32` at call_at (a guarded copy), with these arguments on the stack."""
        e = self.e
        esp = e.sp_top - 0x100
        for v in reversed(args):
            esp -= 4
            e.w32(esp, v)
        e.setreg(UC_X86_REG_ESP, esp)
        e.uc.emu_start(call_at, call_at + 5)
        return e.reg(K.UC_X86_REG_EAX)
