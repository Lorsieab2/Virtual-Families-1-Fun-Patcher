"""Runs Virtual Families 1's own people-drawing code in Unicorn, for tests/test_picture_maker.py.

Everything that decides a picture runs as the game's own code on the vanilla Virtual Families.exe
(VF1_VANILLA_DIR, read only):

* the animation table: Assets\\animpts.dat is put where 0x450F99's two freads put it (table 0x570408
  + 0x76F0 and + 0x34774), then the loader's own tail 0x45102A..0x451176 runs (it rewrites every
  block's picture and column);
* CVillagerManager::DrawVillager 0x48B4D0 (the house), CVillager 0x486B60 (the portrait), with
  ldwImageGrid::GetCellRect 0x40AD40, the draw wrappers 0x44ED70 / 0x44ED00 / 0x44EC90 / 0x4099xx /
  0x408DF0 / 0x408C70 / 0x408BC0 and the clip 0x407F00, down to ldwGameWindowImpl::BlitRectWithAlpha
  0x404C30, where every draw is recorded (source file, cell, place, alpha, scale);
* for the pixels, 0x404C30 itself runs on real surfaces (the sheet's pixels decoded by Pillow, an
  opaque screen of one colour), except its scale 1 / alpha 1 path, which is SDL_UpperBlit (SDL2.dll,
  not the game's code): that one is recorded and its pixels are the cell's own.

Stood in for (not game logic): theGraphicsManager (GetImageGrid hands out grid objects laid out as
ldwImageGrid's: +8 columns, +0xC rows, +0x10 / +0x14 cell size, +0x20 files across, +0x28 / +0x2C cells
per file, +0x30 the files), ldwGameWindow (a 4000 x 4000 screen), the water test 0x495E00 (dry), SDL's
lock / unlock, and the focus ring 0x44EC30.  The x87 runs at 53-bit precision (Windows' default
control word 0x27F); `precision=64` reruns at 64 bits to show the results do not depend on it.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESP,
)

BASE = 0x400000
TEXT_END = 0x4B2000
STACK = 0x0F000000
HEAP = 0x10000000
STOP = 0x0EFFFFF0
ANIM = 0x570408
MANAGER = 0x5B8898
VILLAGER0 = MANAGER + 0x14640
GRAPHICS = 0x56B800
SCREEN = 4000

IMAGES = {   # id: (stem, columns, rows, files across) -- the image table 0x4F2D00 (test_image_table checks it)
    0x9C: ("female_heads", 24, 50, 2), 0xA0: ("male_heads", 24, 50, 2),
    0x9D: ("female_bodies00.png", 32, 50, 1), 0xA1: ("male_bodies00.png", 32, 50, 1),
    0x9E: ("female_actions00.png", 15, 50, 1), 0xA2: ("male_actions00.png", 15, 50, 1),
    0x9F: ("female_sit00.png", 9, 50, 1), 0xA3: ("male_sit00.png", 9, 50, 1),
    0x04: ("bigheads", 12, 50, 2), 0x05: ("highrez_bodies_final2.png", 2, 50, 1),
    0xA4: ("peep_shadow1.png", 0, 0, 1), 0x68: ("carrying.png", 13, 6, 1),
    0x77: ("collectables_small.png", 6, 12, 1), 0x3B: ("focus_circle.png", 0, 0, 1),
    0xA5: ("ripple.png", 4, 1, 1),
}

_md = Cs(CS_ARCH_X86, CS_MODE_32)


class Emu:
    def __init__(self, game: Path, *, precision: int = 53, pixels=None) -> None:
        """`pixels(name) -> (width, height, rgba bytes)` gives a picture's pixels (None: draws are recorded
        only, never blitted)."""
        self.game = Path(game)
        pe = pefile.PE(str(self.game / "Virtual Families.exe"), fast_load=True)
        self.img = bytes(pe.get_memory_mapped_image())
        self.pixels = pixels
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(BASE, (len(self.img) + 0xFFF) & ~0xFFF)
        u.mem_write(BASE, self.img)
        u.mem_map(STACK - 0x200000, 0x210000)
        self.u = u
        self.top = HEAP
        self.mapped = HEAP          # the heap is mapped as it is used
        self.ret_n: dict[int, int] = {}
        self.blits: list[dict] = []
        self.surfaces: dict[int, str] = {}
        self.grids: dict[int, int] = {}
        self.surface_of: dict[str, int] = {}
        self.run_blits = False
        self._code_hooks = {
            0x44F7C0: self._ret_value(1, 0),          # theGraphicsManager::Get
            0x44F5A0: self._get_grid,                 # GetImageGrid(EImage), thiscall ret 4
            0x44F860: self._get_grid,                 # GetImage(EImage): a single-cell grid serves
            0x495E00: self._ret_value(0, 8),          # not in water
            0x44EC30: self._ret_value(0, 0x10),       # the focus ring
            0x4978EC: self._ret_value(0, 0),          # SDL_LockSurface (cdecl import thunks)
            0x4978E0: self._ret_value(0, 0),          # SDL_UnlockSurface
            0x404C30: self._blit,
        }
        self.window = self._window()
        self._code_hooks[0x4080B0] = self._ret_value(self.window, 0)      # ldwGameWindow::Get
        # one hook per stood-in address (GetRandom 0x403650 only while a portrait is drawn), so the game's
        # own loops run without a Python call per instruction
        for address in list(self._code_hooks) + [0x403650]:
            u.hook_add(UC_HOOK_CODE, self._code, begin=address, end=address)
        # theGraphicsManager's draw object 0x56B800: no zoom, no scroll (0x44EA40's fields)
        self.w32(GRAPHICS + 0x3004, 0)
        self.w32(GRAPHICS + 0x3008, 0)
        self.wf(GRAPHICS + 0x300C, 1.0)
        self.w32(GRAPHICS + 0x3010, 100)
        # the manager's pictures (0x4898B2..): +4 shadow, +0x20 focus, +0x24 carrying, +0x28 collectables
        for field, image in ((4, 0xA4), (0x20, 0x3B), (0x24, 0x68), (0x28, 0x77), (0x2C, 0xA5)):
            self.w32(MANAGER + field, self.grid(image))
        self.cw = self.alloc(4)
        u.mem_write(self.cw, struct.pack("<H", 0x27F if precision == 53 else 0x37F))
        self._load_animpts()

    # -------------------------------------------------------------- memory
    def alloc(self, n: int) -> int:
        a = self.top
        self.top += (n + 0xF) & ~0xF
        if self.top > self.mapped:
            grow = (self.top - self.mapped + 0xFFFFF) & ~0xFFFFF
            self.u.mem_map(self.mapped, grow)
            self.mapped += grow
        return a

    def w32(self, a: int, v: int) -> None:
        self.u.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def r32(self, a: int) -> int:
        return struct.unpack("<i", self.u.mem_read(a, 4))[0]

    def wf(self, a: int, v: float) -> None:
        self.u.mem_write(a, struct.pack("<f", v))

    def rf(self, a: int) -> float:
        return struct.unpack("<f", self.u.mem_read(a, 4))[0]

    # -------------------------------------------------------------- stand-ins
    def _ret_value(self, value: int, clean: int):
        def run(_self):
            esp = self.u.reg_read(UC_X86_REG_ESP)
            ra = struct.unpack("<I", self.u.mem_read(esp, 4))[0]
            self.u.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
            self.u.reg_write(UC_X86_REG_ESP, esp + 4 + clean)
            self.u.reg_write(UC_X86_REG_EIP, ra)
        return run

    def _window(self) -> int:
        window = self.alloc(16)
        impl = self.alloc(0x80)
        self.w32(window, impl)
        self.w32(impl + 8, SCREEN)
        self.w32(impl + 0xC, SCREEN)
        for k, v in enumerate((0, 0, SCREEN, SCREEN)):          # the clip rect 0x407E60 reads
            self.w32(impl + 0x60 + 4 * k, v)
        self.screen = self._surface("screen", SCREEN, SCREEN, alpha=False, pixels=False)
        self.w32(impl + 0x30, self.screen)
        self.impl = impl
        return window

    def _surface(self, name: str, w: int, h: int, *, alpha: bool = True, pixels: bool = True) -> int:
        fmt = self.alloc(0x28)
        self.w32(fmt + 0xC, 0xFF)              # memory order R, G, B, A (SDL_image's ABGR8888)
        self.w32(fmt + 0x10, 0xFF00)
        self.w32(fmt + 0x14, 0xFF0000)
        self.w32(fmt + 0x18, 0xFF000000 if alpha else 0)
        self.u.mem_write(fmt + 0x22, bytes([16]))
        surf = self.alloc(0x40)
        self.w32(surf + 4, fmt)
        self.w32(surf + 8, w)
        self.w32(surf + 0xC, h)
        self.w32(surf + 0x10, w * 4)
        if pixels:
            self.w32(surf + 0x14, self.alloc(w * h * 4))
        self.surfaces[surf] = name
        return surf

    def _file_surface(self, name: str) -> int:
        if name not in self.surface_of:
            if self.pixels is not None:
                w, h, data = self.pixels(name)
                surf = self._surface(name, w, h)
                self.u.mem_write(self.r32(surf + 0x14), bytes(data))
            else:
                w, h = _png_size(self.game / "Images" / name)
                surf = self._surface(name, w, h, pixels=False)
            self.surface_of[name] = surf
        return self.surface_of[name]

    def grid(self, image: int) -> int:
        if image in self.grids:
            return self.grids[image]
        stem, cols, rows, files = IMAGES[image]
        names = [stem] if files == 1 else [f"{stem}{k}0.png" for k in range(files)]
        impls = []
        for name in names:
            impl = self.alloc(16)
            self.w32(impl, self._file_surface(name))
            impls.append(impl)
        w, h = _png_size(self.game / "Images" / names[0])
        g = self.alloc(0x40)
        per_file = max(1, cols // files)
        self.w32(g + 4, impls[0])
        self.w32(g + 8, cols)
        self.w32(g + 0xC, rows)
        self.w32(g + 0x10, w // per_file if cols else w)
        self.w32(g + 0x14, h // rows if rows else h)
        if files > 1:
            table = self.alloc(4 * files)
            for k, impl in enumerate(impls):
                self.w32(table + 4 * k, impl)
            self.w32(g + 0x20, files)
            self.w32(g + 0x24, 1)
            self.w32(g + 0x28, per_file)
            self.w32(g + 0x2C, rows)
            self.w32(g + 0x30, table)
        self.grids[image] = g
        return g

    def _get_grid(self, _self) -> None:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        image = struct.unpack("<I", self.u.mem_read(esp + 4, 4))[0]
        self._ret_value(self.grid(image), 4)(self)

    def _blit(self, _self) -> None:
        """BlitRectWithAlpha(surface, x, y, left, top, right, bottom, alpha, scale, centre)."""
        esp = self.u.reg_read(UC_X86_REG_ESP)
        a = struct.unpack("<IiiiiiiffB", self.u.mem_read(esp + 4, 37))
        surf, x, y, x0, y0, x1, y1, alpha, scale, centre = a
        if self.run_blits:
            return                                  # blit_onto: the game's own blitter runs
        self.blits.append({"file": self.surfaces.get(surf, "?"), "rect": (x0, y0, x1, y1), "x": x, "y": y,
                           "alpha": alpha, "scale": scale, "centre": centre})
        self._ret_value(0, 0x28)(self)

    def _code(self, u, addr, size, _data):
        hook = self._code_hooks.get(addr)
        if hook is not None:
            hook(self)

    # -------------------------------------------------------------- the game's code
    def call(self, fn: int, args=(), ecx: int = 0, max_ins: int = 50_000_000) -> int:
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

    def _fldcw(self) -> None:
        stub = getattr(self, "_stub", None)
        if stub is None:
            stub = self._stub = self.alloc(16)
            self.u.mem_write(stub, b"\xD9\x2D" + struct.pack("<I", self.cw) + b"\xF4")   # fldcw [cw]; hlt
        self.u.emu_start(stub, stub + 6)

    def _load_animpts(self) -> None:
        data = (self.game / "Assets" / "animpts.dat").read_bytes()
        n1 = struct.unpack_from("<I", data, 0)[0]
        n2 = struct.unpack_from("<I", data, 4 + n1)[0]
        self.u.mem_write(ANIM + 0x76F0, data[4:4 + n1])
        self.u.mem_write(ANIM + 0x34774, data[8 + n1:8 + n1 + n2])
        # the loader's tail (0x45102A..0x451176): edi = the table, ebx = 4 (set at 0x450F37)
        u = self.u
        esp = STACK - 0x1000
        u.reg_write(UC_X86_REG_ESP, esp)
        u.reg_write(UC_X86_REG_EDI, ANIM)
        u.reg_write(UC_X86_REG_EBX, 4)
        u.emu_start(0x45102A, 0x451176, count=1_000_000)

    # -------------------------------------------------------------- scenes
    def villager(self, *, female: bool, age: int, head: int, body: int, pose: int, direction: int = 0,
                 head_turn: int = 5, ghost: bool = False, carried: int = -1, babies: int = 0,
                 x: int = 2000, y: int = 2000) -> int:
        """Villager 0 set up for a draw; (x, y) is its place (+0x13544 / +0x13548)."""
        v = VILLAGER0
        self.u.mem_write(v, bytes(0x145FC))
        self.w32(v + 0x2A34, age)
        self.w32(v + 0x2A38, 1 if female else 0)
        self.w32(v + 0x2A60, head)
        self.w32(v + 0x2A64, body)
        self.w32(v + 0x2AE0, 90)
        if babies:
            self.w32(v + 0x2AF8, max(1, age - 5))
            self.w32(v + 0x2AFC, babies)
        self.w32(v + 0x13544, x)
        self.w32(v + 0x13548, y)
        self.w32(v + 0x13560, pose)
        self.w32(v + 0x13568, 0)
        self.w32(v + 0x13580, direction)
        self.w32(v + 0x13584, head_turn)
        self.w32(v + 0x13588, 0)
        self.w32(v + 0x1358C, carried)
        self.u.mem_write(v + 0x13540, bytes([1 if ghost else 0]))
        self.wf(v + 0x2B80, 0.0)                     # the ghost's timer: just risen
        self.u.mem_write(v + 0x13574, b"\x01")
        self.w32(v + 0x145E8, self.window)              # the villager's game window (0x486C4A)
        return v

    def feet(self) -> tuple[int, int]:
        """CVillager::FeetPos 0x4869C0 of villager 0."""
        out = self.alloc(8)
        self.call(0x4869C0, (out,), ecx=VILLAGER0)
        return self.r32(out), self.r32(out + 4)

    def draw_house(self, alpha: float = 1.0) -> list[dict]:
        self.blits = []
        self.call(0x48B4D0, (0, struct.unpack("<I", struct.pack("<f", alpha))[0]), ecx=MANAGER)
        return list(self.blits)

    def draw_portrait(self, x: int = 2000, y: int = 2000, expression: int = 0) -> list[dict]:
        self.blits = []
        self.w32(0x4FC0C0, expression)
        # 0x486B66: GetRandom(1000) <= 20 picks a new expression; the stand-in GetRandom says 999
        self._code_hooks[0x403650] = self._ret_value(999, 0)
        try:
            self.call(0x486B60, (x, y), ecx=VILLAGER0)
        finally:
            del self._code_hooks[0x403650]
        return list(self.blits)

    # -------------------------------------------------------------- pixels
    def blit_onto(self, colour: tuple[int, int, int], blits: list[dict], width: int, height: int,
                  origin: tuple[int, int]) -> bytes:
        """Every recorded draw blitted again by the game's 0x404C30 onto an opaque `colour` screen of
        width x height whose top-left is the screen point `origin`; returns the screen's RGB bytes.  A
        scale 1 / alpha 1 draw (SDL_UpperBlit in the game) is not allowed here."""
        key = ("backdrop", width, height)
        if key not in self.surface_of:
            self.surface_of[key] = self._surface("backdrop", width, height, alpha=False)
        surf = self.surface_of[key]
        self.w32(self.impl + 8, width)
        self.w32(self.impl + 0xC, height)
        for k, v in enumerate((0, 0, width, height)):
            self.w32(self.impl + 0x60 + 4 * k, v)
        self.w32(self.impl + 0x30, surf)
        pixels = self.r32(surf + 0x14)
        self.u.mem_write(pixels, bytes((*colour, 0)) * (width * height))
        self.run_blits = True
        try:
            for b in blits:
                assert not (b["alpha"] == 1.0 and b["scale"] == 1.0), "an SDL_UpperBlit draw"
                src = self._file_surface(b["file"])
                x0, y0, x1, y1 = b["rect"]
                args = struct.pack("<IiiiiiiffI", src, b["x"] - origin[0], b["y"] - origin[1], x0, y0, x1, y1,
                                   b["alpha"], b["scale"], b["centre"])
                esp = STACK - 0x1000
                self.u.mem_write(esp + 4, args)
                self.u.mem_write(esp, struct.pack("<I", STOP))
                self.u.reg_write(UC_X86_REG_ESP, esp)
                self.u.reg_write(UC_X86_REG_ECX, self.impl)
                self._fldcw()
                self.u.emu_start(0x404C30, STOP, count=50_000_000)
        finally:
            self.run_blits = False
            self.w32(self.impl + 0x30, self.screen)
            self.w32(self.impl + 8, SCREEN)
            self.w32(self.impl + 0xC, SCREEN)
            for k, v in enumerate((0, 0, SCREEN, SCREEN)):
                self.w32(self.impl + 0x60 + 4 * k, v)
        raw = bytes(self.u.mem_read(pixels, width * height * 4))
        out = bytearray(width * height * 3)
        out[0::3], out[1::3], out[2::3] = raw[0::4], raw[1::4], raw[2::4]
        return bytes(out)


def _png_size(path: Path) -> tuple[int, int]:
    data = Path(path).read_bytes()[:24]
    return struct.unpack(">II", data[16:24])
