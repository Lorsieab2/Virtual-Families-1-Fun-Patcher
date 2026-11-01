"""Runs Virtual Families 1's own interface-drawing code in Unicorn, for tests/test_art_ui.py.

The vanilla Virtual Families.exe (VF1_VANILLA_DIR, read only) is mapped as it is; what runs is the game's own
code: the button draw ldwButtonImpl 0x4011D0 (built by its constructor 0x4018E0), the check box / radio
button draw 0x40BC40 (built by 0x40BF50), the dialog backdrop ldwTiledBackground 0x40DF90 / 0x40DDD0, the
Options dialog's contents 0x41D9C0, the achievements screen 0x435360 and its rows 0x412D00, the floating
animations 0x4217B0 / 0x421810 / 0x421A30, theGraphicsManager's draw-by-id functions 0x44F960 / 0x44F880,
the focus ring 0x44EC30, and pieces of code run from one address to another (`run`) -- each down to the
blitters, where every draw is recorded:

* ldwGameWindowImpl::BlitRectWithAlpha 0x404C30 (surface, x, y, left, top, right, bottom, alpha, scale);
* the plain SDL blit 0x404BC0 (surface, x, y, left, top, right, bottom), recorded as alpha 1, scale 1;
* SDL_FillRect (the import thunk 0x497904) and the tinted blit 0x408EC0, recorded as "fill" / "tint" (the
  tint with its arguments, before its clip) so a test sees it if the game ever took those paths.

Stood in for (not drawing logic): theGraphicsManager's picture loaders 0x44F3E0 / 0x44F650 / 0x44F320
(they hand out picture objects laid out as ldwImageGrid's: +4 the picture, +8 columns, +0xC rows, +0x10 /
+0x14 the cell size; the size of the file from the game's Images folder), ldwGameWindow::Get 0x4080B0 (a
4000 x 4000 screen), the heap (0x497B14 / 0x497A33), SDL's lock / unlock, and the text routines (the string
table 0x450530 / 0x44FD90 hands out an empty string; the text draws 0x409660 / 0x409CD0 / 0x409D20 /
0x409D70 are recorded as "text" and draw nothing: text belongs to the fonts).  The x87 runs at 53-bit
precision (Windows' default control word 0x27F).
"""
from __future__ import annotations

import struct
from pathlib import Path

import pefile
import vf1_game_art as ga
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_DS,
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ES,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
    UC_X86_REG_FS,
    UC_X86_REG_GDTR,
    UC_X86_REG_GS,
    UC_X86_REG_SS,
)

BASE = 0x400000
STACK = 0x0F000000
HEAP = 0x10000000
STOP = 0x0EFFFFF0
GRAPHICS = 0x56B800
TEB = 0x0E000000
SCREEN = 4000
REGS = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
        "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}


def f32(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


class UiEmu:
    def __init__(self, game: Path) -> None:
        self.game = Path(game)
        self.files = ga.GameFiles(self.game)
        pe = pefile.PE(str(self.game / "Virtual Families.exe"), fast_load=True)
        image = bytes(pe.get_memory_mapped_image())
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(BASE, (len(image) + 0xFFF) & ~0xFFF)
        u.mem_write(BASE, image)
        u.mem_map(STACK - 0x200000, 0x210000)
        self.u = u
        # fs:[0], the exception-handler chain the prologues use: a flat GDT (code 0x08, data 0x10) and a data
        # segment 0x18 based at TEB for fs
        u.mem_map(TEB, 0x2000)
        u.mem_write(TEB, struct.pack("<I", 0xFFFFFFFF))

        def desc(base: int, limit: int, access: int) -> bytes:
            return struct.pack("<Q", (limit & 0xFFFF) | ((base & 0xFFFFFF) << 16) | (access << 40)
                               | (((limit >> 16) & 0xF) << 48) | (0xC << 52) | (((base >> 24) & 0xFF) << 56))
        gdt = bytes(8) + desc(0, 0xFFFFF, 0x9B) + desc(0, 0xFFFFF, 0x93) + desc(TEB, 0x1, 0x93)
        u.mem_write(TEB + 0x1000, gdt)
        u.reg_write(UC_X86_REG_GDTR, (0, TEB + 0x1000, len(gdt) - 1, 0))
        for reg, sel in ((UC_X86_REG_SS, 0x10), (UC_X86_REG_DS, 0x10), (UC_X86_REG_ES, 0x10),
                         (UC_X86_REG_GS, 0x10), (UC_X86_REG_FS, 0x18)):
            u.reg_write(reg, sel)
        self.top = HEAP
        self.mapped = HEAP
        self.draws: list[dict] = []
        self.surfaces: dict[int, str] = {}
        self.surface_of: dict[str, int] = {}
        self.grids: dict[int, int] = {}
        self.window = self._window()
        self.mgr = self.alloc(0x10)
        self.w32(self.mgr, self.alloc(0x10))
        self.w32(self.mgr + 4, self.window)
        self.empty = self.alloc(0x10)
        self.strings = self.alloc(0x10)
        self.w32(self.strings, self.alloc(0x10))
        self.gs = self.alloc(0x1C000)
        hooks = {
            0x44F7C0: self._ret(lambda: self.mgr, 0),          # theGraphicsManager::Get
            0x44F3E0: self._by_id(True, 4),                    # the picture grid of an image id
            0x44F650: self._by_id(False, 4),                   # the picture of an image id
            0x44F320: self._by_id(False, 4),                   # the strip of an image id
            0x4080B0: self._ret(lambda: self.window, 0),       # ldwGameWindow::Get
            0x404C30: self._blit,
            0x404BC0: self._sdl_blit,
            0x408EC0: self._tint,
            0x497904: self._fill,                              # SDL_FillRect (cdecl thunk)
            0x497B14: self._malloc,                            # operator new (cdecl)
            0x497A33: self._ret(lambda: 0, 0),                 # operator delete (cdecl)
            0x4978EC: self._ret(lambda: 0, 0),                 # SDL_LockSurface
            0x4978E0: self._ret(lambda: 0, 0),                 # SDL_UnlockSurface
            0x450530: self._ret(lambda: self.strings, 0),      # the string table
            0x44FD90: self._ret(lambda: self.empty, 4),        # a string by number
            0x423660: self._ret(lambda: self.gs, 0),           # theGameState
            0x409660: self._text(0x14),
            0x409CD0: self._text(0x14),
            0x409D20: self._text(0x14),
            0x409D70: self._text(0x1C),
        }
        self.hooks = hooks
        for address in hooks:
            u.hook_add(UC_HOOK_CODE, self._code, begin=address, end=address)
        # theGraphicsManager's draw object 0x56B800: no zoom, no scroll (0x44EA40's fields)
        self.w32(GRAPHICS + 0x3004, 0)
        self.w32(GRAPHICS + 0x3008, 0)
        self.wf(GRAPHICS + 0x300C, 1.0)
        self.w32(GRAPHICS + 0x3010, 100)
        # the dialog backdrop's overlaps, as theGame's start-up 0x422B25 / 0x422B2F sets them
        self.w32(0x5008B8, 0xC)
        self.w32(0x5008B4, 0x12)
        self.cw = self.alloc(4)
        u.mem_write(self.cw, struct.pack("<H", 0x27F))

    # -------------------------------------------------------------- memory
    def alloc(self, n: int) -> int:
        a = self.top
        self.top += (n + 0xF) & ~0xF
        if self.top > self.mapped:
            grow = (self.top - self.mapped + 0xFFFFF) & ~0xFFFFF
            self.u.mem_map(self.mapped, grow)
            self.mapped += grow
        self.u.mem_write(a, bytes(n))
        return a

    def w32(self, a: int, v: int) -> None:
        self.u.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def w8(self, a: int, v: int) -> None:
        self.u.mem_write(a, bytes([v & 0xFF]))

    def r32(self, a: int) -> int:
        return struct.unpack("<i", self.u.mem_read(a, 4))[0]

    def wf(self, a: int, v: float) -> None:
        self.u.mem_write(a, struct.pack("<f", v))

    def wd(self, a: int, v: float) -> None:
        self.u.mem_write(a, struct.pack("<d", v))

    def cstr(self, text: str) -> int:
        a = self.alloc(len(text) + 1)
        self.u.mem_write(a, text.encode("latin-1") + b"\0")
        return a

    # -------------------------------------------------------------- stand-ins
    def _arg(self, k: int) -> int:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", self.u.mem_read(esp + 4 + 4 * k, 4))[0]

    def _return(self, value: int, clean: int) -> None:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        ra = struct.unpack("<I", self.u.mem_read(esp, 4))[0]
        self.u.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
        self.u.reg_write(UC_X86_REG_ESP, esp + 4 + clean)
        self.u.reg_write(UC_X86_REG_EIP, ra)

    def _ret(self, value, clean: int):
        return lambda: self._return(value(), clean)

    def _by_id(self, grid_only: bool, clean: int):
        def run():
            image = self._arg(0)
            _name, cols, _rows, _files = ga.TABLE[image]
            self._return(0 if grid_only and cols == 0 else self.grid(image), clean)
        return run

    def _malloc(self) -> None:
        self._return(self.alloc(max(16, self._arg(0))), 0)

    def _text(self, clean: int):
        def run():
            self.draws.append({"kind": "text"})
            self._return(0, clean)
        return run

    def _tint(self) -> None:
        """The tinted blit 0x408EC0 (picture object, x, y, left, top, right, bottom, colour 0xAABBGGRR, alpha,
        scale), recorded as it is called (before its clip 0x407E60) and not drawn."""
        esp = self.u.reg_read(UC_X86_REG_ESP)
        pic, x, y, x0, y0, x1, y1, colour, alpha, scale = struct.unpack("<IiiiiiiIff",
                                                                        self.u.mem_read(esp + 4, 40))
        image = next((i for i, g in self.grids.items() if g == pic), None)
        self.draws.append({"kind": "tint", "image": image, "file": ga.TABLE[image][0] if image is not None else "?",
                           "rect": (x0, y0, x1, y1), "x": x, "y": y, "colour": colour, "alpha": alpha,
                           "scale": scale})
        self._return(0, 0x28)

    def _fill(self) -> None:
        self.draws.append({"kind": "fill", "args": tuple(self._arg(k) for k in range(3))})
        self._return(0, 0)

    def _blit(self) -> None:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        surf, x, y, x0, y0, x1, y1, alpha, scale = struct.unpack("<Iiiiiiiff", self.u.mem_read(esp + 4, 36))
        self.draws.append({"kind": "blit", "file": self.surfaces.get(surf, "?"), "rect": (x0, y0, x1, y1),
                           "x": x, "y": y, "alpha": alpha, "scale": scale})
        self._return(0, 0x28)

    def _sdl_blit(self) -> None:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        surf, x, y, x0, y0, x1, y1 = struct.unpack("<Iiiiiii", self.u.mem_read(esp + 4, 28))
        self.draws.append({"kind": "blit", "file": self.surfaces.get(surf, "?"), "rect": (x0, y0, x1, y1),
                           "x": x, "y": y, "alpha": 1.0, "scale": 1.0})
        self._return(0, 0x1C)

    def _code(self, u, addr, size, _data) -> None:
        hook = self.hooks.get(addr)
        if hook is not None:
            hook()

    def _window(self) -> int:
        window = self.alloc(16)
        impl = self.alloc(0x100)
        self.w32(window, impl)
        self.w32(impl + 8, SCREEN)
        self.w32(impl + 0xC, SCREEN)
        for k, v in enumerate((0, 0, SCREEN, SCREEN)):          # the clip rectangle 0x407E60 reads
            self.w32(impl + 0x60 + 4 * k, v)
        self.w32(impl + 0x30, self._surface("screen", SCREEN, SCREEN))
        self.impl = impl
        return window

    def _surface(self, name: str, w: int, h: int) -> int:
        fmt = self.alloc(0x28)
        self.w32(fmt + 0xC, 0xFF)
        self.w32(fmt + 0x10, 0xFF00)
        self.w32(fmt + 0x14, 0xFF0000)
        self.w32(fmt + 0x18, 0xFF000000)
        surf = self.alloc(0x40)
        self.w32(surf + 4, fmt)
        self.w32(surf + 8, w)
        self.w32(surf + 0xC, h)
        self.w32(surf + 0x10, w * 4)
        self.surfaces[surf] = name
        return surf

    def grid(self, image: int) -> int:
        """A picture object for image id `image`, laid out as ldwImageGrid (a single picture: one cell)."""
        if image in self.grids:
            return self.grids[image]
        name, cols, rows, _files = ga.TABLE[image]
        w, h = self.files.size(name) if self.files.has(name) else (64, 64)
        if name not in self.surface_of:
            self.surface_of[name] = self._surface(name, w, h)
        impl = self.alloc(16)
        self.w32(impl, self.surface_of[name])
        g = self.alloc(0x40)
        cols, rows = (cols or 1), (rows or 1)
        self.w32(g + 4, impl)
        self.w32(g + 8, cols)
        self.w32(g + 0xC, rows)
        self.w32(g + 0x10, w // cols)
        self.w32(g + 0x14, h // rows)
        self.grids[image] = g
        return g

    def picture(self, name: str) -> int:
        """A picture object for a file the game opens by name (as 0x40ABE0 makes one)."""
        w, h = self.files.size(name)
        if name not in self.surface_of:
            self.surface_of[name] = self._surface(name, w, h)
        impl = self.alloc(16)
        self.w32(impl, self.surface_of[name])
        g = self.alloc(0x40)
        for field, value in ((4, impl), (8, 1), (0xC, 1), (0x10, w), (0x14, h)):
            self.w32(g + field, value)
        return g

    # -------------------------------------------------------------- running the game's code
    def _fldcw(self) -> None:
        stub = getattr(self, "_stub", None)
        if stub is None:
            stub = self._stub = self.alloc(16)
            self.u.mem_write(stub, b"\xD9\x2D" + struct.pack("<I", self.cw) + b"\xF4")
        self.u.emu_start(stub, stub + 6)

    def call(self, fn: int, args=(), ecx: int = 0, max_ins: int = 20_000_000) -> int:
        u = self.u
        esp = STACK - 0x1000
        for a in reversed(args):
            esp -= 4
            u.mem_write(esp, struct.pack("<I", a & 0xFFFFFFFF))
        esp -= 4
        u.mem_write(esp, struct.pack("<I", STOP))
        u.reg_write(UC_X86_REG_ESP, esp)
        u.reg_write(UC_X86_REG_ECX, ecx)
        self._fldcw()
        u.emu_start(fn, STOP, count=max_ins)
        return u.reg_read(UC_X86_REG_EAX)

    def run(self, start: int, end: int, regs: dict | None = None, stack: dict | None = None,
            max_ins: int = 5_000_000) -> None:
        """The game's code from `start` up to (not including) `end`, with registers and stack slots
        ({offset from esp: dword}) set first."""
        esp = STACK - 0x8000
        self.u.mem_write(esp, bytes(0x400))
        for off, v in (stack or {}).items():
            self.w32(esp + off, v)
        self.u.reg_write(UC_X86_REG_ESP, esp)
        for r, v in (regs or {}).items():
            self.u.reg_write(REGS[r], v & 0xFFFFFFFF)
        self._fldcw()
        self.u.emu_start(start, end, count=max_ins)

    def take(self) -> list[dict]:
        out, self.draws = self.draws, []
        return out

    # -------------------------------------------------------------- the pieces
    def button(self, image: int, state: int, x: int = 1000, y: int = 1000) -> list[dict]:
        """ldwButtonImpl built by its constructor 0x4018E0 (no parent, no text), shown (+0x28), drawn by
        0x4011D0 in `state` (0 normal, 1 mouse over, 2 pressed: 0x401630 / 0x401640 / 0x401620)."""
        impl = self.alloc(0x68)
        self.call(0x4018E0, (1, self.grid(image), x, y, 0, 0, 0), ecx=impl)
        self.w8(impl + 0x28, 1)
        self.take()
        self.call(0x4011D0, (state,), ecx=impl)
        return self.take()

    def toggle(self, image: int, checked: bool, state: int = 0, x: int = 1000, y: int = 1000) -> list[dict]:
        """ldwRadioButtonImpl built by 0x40BF50 (no parent, no text), shown (+0x30), checked (+0x31) or not, in
        mouse `state` (+0x38), drawn by 0x40BC40."""
        impl = self.alloc(0x60)
        self.call(0x40BF50, (0, 4, self.grid(image), x, y, 0, self.empty, 0, 0, 0), ecx=impl)
        self.w32(impl + 0x48, 0)
        self.w8(impl + 0x30, 1)
        self.w8(impl + 0x31, 1 if checked else 0)
        self.w32(impl + 0x38, state)
        self.take()
        self.call(0x40BC40, (), ecx=impl)
        return self.take()

    def backdrop(self, image: int, width: int, height: int, x: int = 1000, y: int = 1000,
                 alpha: float = 1.0) -> list[dict]:
        """A dialog's backdrop: ldwTiledBackground 0x40DF90 (grid, width, height), drawn by 0x40DDD0."""
        bg = self.alloc(0x20)
        self.call(0x40DF90, (self.grid(image), width, height), ecx=bg)
        self.take()
        self.call(0x40DDD0, (x, y, f32(alpha)), ecx=bg)
        return self.take()

    def draw_by_id(self, image: int, x: int, y: int, alpha: float = 1.0, percent: int = 100) -> list[dict]:
        """theGraphicsManager 0x44F960 (id, x, y, alpha, percent)."""
        self.take()
        self.call(0x44F960, (image, x, y, f32(alpha), percent), ecx=self.mgr)
        return self.take()

    def draw_centred(self, image: int, x: int, y: int) -> list[dict]:
        """theGraphicsManager 0x44F880 (id, centre x, centre y)."""
        self.take()
        self.call(0x44F880, (image, x, y), ecx=self.mgr)
        return self.take()
