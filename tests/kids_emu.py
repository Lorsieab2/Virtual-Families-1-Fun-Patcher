"""A small x86-32 emulation harness (unicorn) for the Up to 28 Children DLL (vf1kids.dll).

It maps the REAL vanilla Virtual Families executable and the REAL compiled test DLL into one address
space, points the DLL's imports at Python seams, and runs genuine game and DLL code. It is the Virtual
Families 2 patcher's harness (tests/b200_time_emu.py in that repository), copied unchanged apart from
this docstring; VF1 is not relocated, so it is always used at the link address.

Nothing here starts the game, and nothing writes the executable on disk.
"""
from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pefile
from unicorn import (UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED,
                     UC_HOOK_MEM_FETCH_UNMAPPED, UC_MODE_32, Uc, UcError)
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,
                               UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
                               UC_X86_REG_FS, UC_X86_REG_GDTR, UC_X86_REG_CS, UC_X86_REG_DS,
                               UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_GS)

# unicorn commits guest memory lazily through first-chance access violations that it handles itself;
# faulthandler would print a stack for each one.
faulthandler.disable()

LINK_BASE = 0x400000
DLL_BASE = 0x30000000
HEAP_BASE = 0x40000000
HEAP_SIZE = 0x1000000
STACK_BASE = 0x50000000
STACK_SIZE = 0x100000
TEB_BASE = 0x60000000
THUNK_BASE = 0x70000000
GDT_BASE = 0x71000000
SENTINEL = 0x70001000
PAGE = 0x1000


class EmuError(RuntimeError):
    pass


def u32(data: bytes, off: int = 0) -> int:
    return struct.unpack_from("<I", data, off)[0]


class Emu:
    def __init__(self, exe_path, dll_path, delta: int = 0):
        self.delta = delta
        self.base = LINK_BASE + delta
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.heap_next = HEAP_BASE
        self.calls = []            # (name, args...) log of every seam hit
        self.seams = {}            # live address -> python callable(emu) -> (eax, pop_bytes) | None
        self.thunks = {}           # thunk address -> import name
        self.imports = {}          # import name -> python callable(emu) -> (eax, pop_bytes)
        self.exe = pefile.PE(str(exe_path))
        self.dll = pefile.PE(str(dll_path))
        self._map_all()
        self.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED,
                         self._unmapped)
        self.uc.hook_add(UC_HOOK_CODE, self._thunk_hook, begin=THUNK_BASE, end=THUNK_BASE + 0x1FFF)
        self.sp_top = STACK_BASE + STACK_SIZE - 0x1000
        self.sdl_module = 0           # what GetModuleHandleW(L"SDL2.dll") answers
        self.active_window = 0x1234
        self.messagebox_answer = 6    # IDYES
        self.status_text = None       # the last SetDlgItemTextW string
        self.dialogs = []             # (template address, owner, dialog proc) of every DialogBoxIndirectParamW
        self.imports.update({
            "GetModuleHandleW": self._imp_get_module_handle,
            "GetActiveWindow": lambda emu: (emu.active_window, 0),
            "DialogBoxIndirectParamW": self._imp_dialog,
            "SetDlgItemTextW": self._imp_set_text,
            "MessageBoxW": self._imp_message_box,
            "EndDialog": lambda emu: (1, 8),
            "GetProcAddress": self._imp_get_proc_address,
        })
        # ISOLATION_AWARE_ENABLED makes the DLL wrap each user32 call in its own activation context
        # (CreateActCtxW / ActivateActCtx / DeactivateActCtx / ReleaseActCtx, found through GetProcAddress).
        self.dyn_procs = {
            "CreateActCtxW": lambda emu: (0x55, 4),
            "ActivateActCtx": self._imp_activate,
            "DeactivateActCtx": lambda emu: (1, 8),
            "ReleaseActCtx": lambda emu: (0, 4),
        }
        self.activations = 0

    # ------------------------------------------------------------------ mapping
    def _map_image(self, pe, base, delta):
        size = (pe.OPTIONAL_HEADER.SizeOfImage + PAGE - 1) & ~(PAGE - 1)
        self.uc.mem_map(base, size)
        raw = pe.__data__
        self.uc.mem_write(base, bytes(raw[:pe.OPTIONAL_HEADER.SizeOfHeaders]))
        for s in pe.sections:
            data = bytes(raw[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData])
            self.uc.mem_write(base + s.VirtualAddress, data)
        if delta:
            for block in pe.DIRECTORY_ENTRY_BASERELOC:
                for e in block.entries:
                    if e.type == pefile.RELOCATION_TYPE["IMAGE_REL_BASED_HIGHLOW"]:
                        a = base + e.rva
                        v = u32(self.uc.mem_read(a, 4))
                        self.uc.mem_write(a, struct.pack("<I", (v + delta) & 0xFFFFFFFF))

    def _map_all(self):
        self._map_image(self.exe, self.base, self.delta)
        self._map_image(self.dll, DLL_BASE, DLL_BASE - self.dll.OPTIONAL_HEADER.ImageBase)
        self.uc.mem_map(HEAP_BASE, HEAP_SIZE)
        self.uc.mem_map(STACK_BASE, STACK_SIZE)
        self.uc.mem_map(TEB_BASE, PAGE)
        self.uc.mem_map(THUNK_BASE, 0x2000)
        self.uc.mem_write(THUNK_BASE, b"\xC3" * 0x2000)
        self._set_fs(TEB_BASE)
        self.uc.mem_write(TEB_BASE, struct.pack("<I", 0xFFFFFFFF))   # fs:[0] = end of the SEH chain
        # The DLL's imports: one thunk each.
        idx = 0
        for d in self.dll.DIRECTORY_ENTRY_IMPORT:
            for imp in d.imports:
                name = imp.name.decode()
                addr = THUNK_BASE + 0x10 * idx
                idx += 1
                self.thunks[addr] = name
                slot = DLL_BASE + (imp.address - self.dll.OPTIONAL_HEADER.ImageBase)
                self.uc.mem_write(slot, struct.pack("<I", addr))
        assert idx * 0x10 < 0x1000

    def _set_fs(self, base):
        """Flat segments plus FS -> the fake TEB through a small GDT (unicorn has no FS_BASE in 32-bit mode)."""
        gdt = GDT_BASE
        self.uc.mem_map(gdt, PAGE)

        def entry(b, limit, access, flags):
            return (limit & 0xFFFF) | ((b & 0xFFFFFF) << 16) | (access << 40) | (((limit >> 16) & 0xF) << 48) |                 (flags << 52) | (((b >> 24) & 0xFF) << 56)
        self.uc.mem_write(gdt + 8, struct.pack("<Q", entry(0, 0xFFFFF, 0x9B, 0xC)))       # 08: flat code
        self.uc.mem_write(gdt + 16, struct.pack("<Q", entry(0, 0xFFFFF, 0x93, 0xC)))      # 10: flat data
        self.uc.mem_write(gdt + 24, struct.pack("<Q", entry(base, 0xFFF, 0x93, 0x4)))     # 18: the TEB
        self.uc.reg_write(UC_X86_REG_GDTR, (0, gdt, 0xFF, 0))
        self.uc.reg_write(UC_X86_REG_CS, 0x08)
        for r in (UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_GS):
            self.uc.reg_write(r, 0x10)
        self.uc.reg_write(UC_X86_REG_FS, 0x18)

    # ------------------------------------------------------------------ default imports
    def _imp_get_module_handle(self, emu):
        name = emu.arg(0)
        if name == 0:
            return emu.base, 4
        if emu.wstr(name).lower() == "sdl2.dll":
            return emu.sdl_module, 4
        if emu.wstr(name).lower() == "kernel32.dll":
            return 0x7FFF0000, 4
        raise EmuError("GetModuleHandleW of an unexpected module")

    def _imp_get_proc_address(self, emu):
        name = emu.cstr(emu.arg(1))
        fn = self.dyn_procs.get(name)
        if fn is None:
            raise EmuError(f"the DLL asked GetProcAddress for the unexpected {name}")
        for addr, n in self.thunks.items():
            if n == "dyn:" + name:
                return addr, 8
        addr = THUNK_BASE + 0x10 * (len(self.thunks) + 1)
        self.thunks[addr] = "dyn:" + name
        self.imports["dyn:" + name] = fn
        return addr, 8

    def _imp_activate(self, emu):
        self.activations += 1
        emu.w32(emu.arg(1), 0x99)
        return 1, 8

    def _imp_dialog(self, emu):
        # DialogBoxIndirectParamW(hInstance, template, owner, proc, param): record, close at once.
        self.dialogs.append((emu.arg(1), emu.arg(2), emu.arg(3)))
        return 0, 20

    def _imp_set_text(self, emu):
        self.status_text = emu.wstr(emu.arg(2))
        return 1, 12

    def _imp_message_box(self, emu):
        self.calls.append(("MessageBoxW", emu.wstr(emu.arg(1)), emu.wstr(emu.arg(2))))
        return self.messagebox_answer, 16

    def bind_exe_imports(self, handlers: dict):
        """Point the EXECUTABLE's import-table slots for the named functions at Python handlers.
        handlers: name -> fn(emu) -> (eax, bytes popped)."""
        bound = set()
        for d in self.exe.DIRECTORY_ENTRY_IMPORT:
            for imp in d.imports:
                name = imp.name.decode() if imp.name else None
                if name in handlers:
                    addr = THUNK_BASE + 0x10 * len(self.thunks)
                    self.thunks[addr] = "exe:" + name
                    self.imports["exe:" + name] = handlers[name]
                    self.uc.mem_write(imp.address + self.delta, struct.pack("<I", addr))
                    bound.add(name)
        missing = set(handlers) - bound
        if missing:
            raise EmuError(f"the executable does not import {sorted(missing)}")

    # ------------------------------------------------------------------ memory helpers
    def a(self, link_va: int) -> int:
        """Live address of a link-time game VA."""
        return link_va + self.delta

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self.uc.mem_read(addr, n))

    def write(self, addr: int, data: bytes):
        self.uc.mem_write(addr, data)

    def r32(self, addr: int) -> int:
        return u32(self.read(addr, 4))

    def w32(self, addr: int, v: int):
        self.write(addr, struct.pack("<I", v & 0xFFFFFFFF))

    def rs32(self, addr: int) -> int:
        return struct.unpack("<i", self.read(addr, 4))[0]

    def alloc(self, n: int, fill: int = 0) -> int:
        p = self.heap_next
        self.heap_next += (n + 15) & ~15
        if self.heap_next > HEAP_BASE + HEAP_SIZE:
            raise EmuError("emulator heap exhausted")
        if fill:
            self.write(p, bytes([fill]) * n)
        return p

    def cstr(self, addr: int) -> str:
        out = b""
        while True:
            c = self.read(addr, 1)
            if c == b"\0":
                return out.decode("latin-1")
            out += c
            addr += 1

    def wstr(self, addr: int) -> str:
        out = b""
        while True:
            c = self.read(addr, 2)
            if c == b"\0\0":
                return out.decode("utf-16-le")
            out += c
            addr += 2

    def dll_export(self, name: str) -> int:
        for e in self.dll.DIRECTORY_ENTRY_EXPORT.symbols:
            if e.name and e.name.decode() == name:
                return DLL_BASE + e.address
        raise EmuError(f"DLL has no export {name}")

    def fake_code(self, code: bytes) -> int:
        p = self.alloc(len(code) + 16)
        self.write(p, code)
        return p

    # ------------------------------------------------------------------ registers / args
    def reg(self, which):
        return self.uc.reg_read(which)

    def setreg(self, which, v):
        self.uc.reg_write(which, v & 0xFFFFFFFF)

    def arg(self, i: int) -> int:
        """i-th stack argument of the function being entered (after the return address)."""
        return self.r32(self.reg(UC_X86_REG_ESP) + 4 + 4 * i)

    @property
    def ecx(self):
        return self.reg(UC_X86_REG_ECX)

    # ------------------------------------------------------------------ hooks
    def _unmapped(self, uc, access, address, size, value, user):
        raise EmuError(f"unmapped access {access} at {address:#x} (eip {self.reg(UC_X86_REG_EIP):#x})")

    def _return_from_seam(self, eax, pop):
        esp = self.reg(UC_X86_REG_ESP)
        ret = self.r32(esp)
        self.setreg(UC_X86_REG_ESP, esp + 4 + pop)
        if eax is not None:
            self.setreg(UC_X86_REG_EAX, eax)
        self.setreg(UC_X86_REG_EIP, ret)

    def _thunk_hook(self, uc, address, size, user):
        name = self.thunks.get(address)
        if name is None:
            return
        fn = self.imports.get(name)
        if fn is None:
            raise EmuError(f"the DLL called the unexpected import {name}")
        eax, pop = fn(self)
        self._return_from_seam(eax, pop)

    def seam(self, link_va: int, fn):
        """Replace the game function at link-time VA link_va by a Python seam: fn(emu) -> (eax, bytes popped)."""
        self.seam_live(self.a(link_va), fn)

    def seam_live(self, addr: int, fn):
        """The same, at a live address (the DLL's own code, or a rebased game address)."""

        def cb(uc, address, size, user):
            eax, pop = fn(self)
            self._return_from_seam(eax, pop)
        self.uc.hook_add(UC_HOOK_CODE, cb, begin=addr, end=addr)

    # ------------------------------------------------------------------ running
    def call(self, addr: int, args=(), ecx=None, edx=None, ebx=None, esi=None, edi=None, limit=0):
        """Call a function (any convention: args are pushed right to left, esp is reset after)."""
        esp = self.sp_top
        for v in reversed(args):
            esp -= 4
            self.w32(esp, v)
        esp -= 4
        self.w32(esp, SENTINEL)
        self.setreg(UC_X86_REG_ESP, esp)
        for reg, v in ((UC_X86_REG_ECX, ecx), (UC_X86_REG_EDX, edx), (UC_X86_REG_EBX, ebx),
                       (UC_X86_REG_ESI, esi), (UC_X86_REG_EDI, edi)):
            if v is not None:
                self.setreg(reg, v)
        self._run(addr, limit)
        return self.reg(UC_X86_REG_EAX)

    def _run(self, start, limit=0):
        try:
            self.uc.emu_start(start, SENTINEL, count=limit)
        except UcError as e:
            raise EmuError(f"emulation stopped at eip {self.reg(UC_X86_REG_EIP):#x}: {e}") from e
        if self.reg(UC_X86_REG_EIP) != SENTINEL:
            raise EmuError(f"emulation ended at {self.reg(UC_X86_REG_EIP):#x}, not at the return sentinel")

    def run_frame(self, start, regs: dict, stack: list[tuple[int, int]]):
        """Start in the middle of a function: set registers and the given stack dwords
        {address: value}; the caller arranges that the function ends in a `ret` to SENTINEL."""
        for addr, v in stack:
            self.w32(addr, v)
        for reg, v in regs.items():
            self.setreg(reg, v)
        self._run(start)
