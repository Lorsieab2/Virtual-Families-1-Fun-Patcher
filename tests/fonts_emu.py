"""Runs Virtual Families 1's own font loading and text drawing in Unicorn, for tests/test_art_fonts.py.

Everything that decides where a glyph goes and what it looks like runs as the game's own code on the vanilla
Virtual Families.exe (VF1_VANILLA_DIR, read only):

* theGraphicsManager's font maker 0x44FC90, which runs the four font constructors (0x421F80 / 0x421FF0 /
  0x422060 / 0x4220F0), ldwFont::Init 0x4022A0 and ldwFontImpl::Load 0x402720 (the file name, the row
  wrapping, the character index) and makes Segoe UI Bold 24 the window's default font (0x4083F0);
* ldwGameWindow's DrawText 0x409CC0 / right-aligned 0x409CD0 / centred 0x409D20 -> 0x409660, the string
  width 0x402320, the line height 0x4023F0, the clip 0x407E60 and the tint 0x402940 (its pixel copy loop
  included), down to SDL_UpperBlit and ldwGameWindowImpl::BlitRectWithAlpha 0x404C30, where every draw is
  recorded (source picture, tint, rectangle, place, alpha, scale).

Stood in for (not game logic): operator new / delete, the file-exists test 0x40B270 (records the name and says
yes), the picture loader ldwImageImpl 0x40B350 (records the name and hands out a surface of the picture's
size, with its pixels when asked), ldwGameWindow::Get's global (0x500668), the SDL calls (CreateRGBSurface,
Lock / Unlock, MapRGBA for the loaded pictures' R, G, B, A byte order, UpperBlit) and BlitRectWithAlpha.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pefile
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

BASE = 0x400000
STACK = 0x0F000000
HEAP = 0x10000000
STOP = 0x0EFFFFF0
WINDOW_GLOBAL = 0x500668            # ldwGameWindow::Get 0x4080B0 returns [0x500668]
SCREEN = 4000

NEW, DELETE = 0x497B14, 0x497A33
FILE_EXISTS, IMAGE_LOAD = 0x40B270, 0x40B350
SDL_UNLOCK, SDL_MAPRGBA, SDL_LOCK, SDL_CREATE, SDL_FREE, SDL_BLIT = (
    0x4978E0, 0x4978E6, 0x4978EC, 0x4978F2, 0x4978F8, 0x497916)
BLIT_ALPHA = 0x404C30
MAKE_FONTS = 0x44FC90
DRAW_LEFT, DRAW_RIGHT, DRAW_CENTRE = 0x409CC0, 0x409CD0, 0x409D20
STRING_WIDTH = 0x402320
SLOTS = {"SegoeUiBold18": 0, "SegoeUiBold17": 4, "SegoeUiBold24": 8, "SegoeUi33": 0xC}


class FontEmu:
    def __init__(self, game: Path, *, pixels=None) -> None:
        """`pixels(name) -> (width, height, rgba bytes)` gives a picture's pixels (None: sizes only)."""
        self.game = Path(game)
        pe = pefile.PE(str(self.game / "Virtual Families.exe"), fast_load=True)
        self.img = bytes(pe.get_memory_mapped_image())
        self.pixels = pixels
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x1000)                         # fs:[0] (the SEH chain) with a zero FS base
        u.mem_map(BASE, (len(self.img) + 0xFFF) & ~0xFFF)
        u.mem_write(BASE, self.img)
        u.mem_map(STACK - 0x200000, 0x210000)
        self.u = u
        self.top = HEAP
        self.mapped = HEAP
        self.asked: list[str] = []                   # names given to the file-exists test
        self.loaded: list[str] = []                  # names given to the picture loader
        self.surfaces: dict[int, str] = {}           # surface -> picture name ("tint" for 0x402940's copies)
        self.created: list[int] = []
        self.draws: list[dict] = []
        hooks = {
            NEW: self._new, DELETE: self._ret(0, 0), FILE_EXISTS: self._exists, IMAGE_LOAD: self._load,
            SDL_UNLOCK: self._ret(0, 0), SDL_LOCK: self._ret(0, 0), SDL_FREE: self._ret(0, 0),
            SDL_MAPRGBA: self._map_rgba, SDL_CREATE: self._create, SDL_BLIT: self._upper_blit,
            BLIT_ALPHA: self._blit_alpha,
        }
        self.hooks = hooks
        for address in hooks:
            u.hook_add(UC_HOOK_CODE, self._code, begin=address, end=address)
        self.window, self.impl = self._window()
        self.manager = self.alloc(0x14)
        self.call(MAKE_FONTS, (), ecx=self.manager)
        self.fonts = {name: self.r32(self.manager + slot) for name, slot in SLOTS.items()}

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

    def r32(self, a: int) -> int:
        return struct.unpack("<I", self.u.mem_read(a, 4))[0]

    def i32(self, a: int) -> int:
        return struct.unpack("<i", self.u.mem_read(a, 4))[0]

    def cstr(self, a: int) -> str:
        out = bytearray()
        while True:
            b = self.u.mem_read(a + len(out), 1)[0]
            if b == 0:
                return out.decode("latin-1")
            out.append(b)

    def args(self, n: int) -> list[int]:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        return list(struct.unpack(f"<{n}I", self.u.mem_read(esp + 4, 4 * n)))

    # -------------------------------------------------------------- stand-ins
    def _ret(self, value: int, clean: int):
        def run():
            esp = self.u.reg_read(UC_X86_REG_ESP)
            ra = struct.unpack("<I", self.u.mem_read(esp, 4))[0]
            self.u.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
            self.u.reg_write(UC_X86_REG_ESP, esp + 4 + clean)
            self.u.reg_write(UC_X86_REG_EIP, ra)
        return run

    def _code(self, u, addr, size, _data):
        hook = self.hooks.get(addr)
        if hook is not None:
            hook()

    def _new(self) -> None:
        (n,) = self.args(1)
        self._ret(self.alloc(max(n, 4)), 0)()          # cdecl

    def _exists(self) -> None:
        (name,) = self.args(1)
        self.asked.append(self.cstr(name))
        self._ret(1, 0)()                               # cdecl, true

    def _format(self) -> int:
        fmt = self.alloc(0x28)
        self.w32(fmt + 0xC, 0xFF)                      # memory order R, G, B, A (SDL_image's ABGR8888)
        self.w32(fmt + 0x10, 0xFF00)
        self.w32(fmt + 0x14, 0xFF0000)
        self.w32(fmt + 0x18, 0xFF000000)
        self.u.mem_write(fmt + 8, bytes([32, 4]))
        return fmt

    def surface(self, name: str, w: int, h: int, data: bytes | None) -> int:
        surf = self.alloc(0x40)
        self.w32(surf + 4, self._format())
        self.w32(surf + 8, w)
        self.w32(surf + 0xC, h)
        self.w32(surf + 0x10, w * 4)
        pixels = self.alloc(w * h * 4) if data is not None else 0
        if data is not None:
            self.u.mem_write(pixels, bytes(data))
        self.w32(surf + 0x14, pixels)
        self.surfaces[surf] = name
        return surf

    def _load(self) -> None:
        """ldwImageImpl(name), thiscall ret 4: [this] = the picture's surface."""
        (name_at,) = self.args(1)
        this = self.u.reg_read(UC_X86_REG_ECX)
        name = self.cstr(name_at)
        self.loaded.append(name)
        if self.pixels is not None:
            w, h, data = self.pixels(name)
        else:
            w, h = _png_size(self.game / "Images" / name)
            data = None
        self.w32(this, self.surface(name, w, h, data))
        self.w32(this + 4, 0)
        self._ret(this, 4)()

    def _create(self) -> None:
        _flags, w, h, depth, rm, gm, bm, am = self.args(8)
        assert (depth, rm, gm, bm, am) == (32, 0xFF, 0xFF00, 0xFF0000, 0xFF000000)
        surf = self.surface("tint", w, h, bytes(w * h * 4))
        self.created.append(surf)
        self._ret(surf, 0)()

    def _map_rgba(self) -> None:
        _fmt, r, g, b, a = self.args(5)
        self._ret((r & 0xFF) | (g & 0xFF) << 8 | (b & 0xFF) << 16 | (a & 0xFF) << 24, 0)()

    def _source(self, surf: int) -> tuple[str, tuple[int, int, int]]:
        """(picture, tint) of a surface a glyph is drawn from: a font picture, or 0x402940's tinted copy of
        one (found in the font's colour cache at +0x41C: colour, surface, next)."""
        name = self.surfaces.get(surf, "?")
        if name != "tint":
            return name, (255, 255, 255)
        for font in self.fonts.values():
            impl = self.r32(font + 4)
            node = self.r32(impl + 0x41C)
            while node:
                if self.r32(node + 4) == surf:
                    colour = self.r32(node)
                    base = self.surfaces[self.r32(self.r32(impl + 0xC))]
                    return base,(colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF)
                node = self.r32(node + 8)
        return "?", (0, 0, 0)

    def _upper_blit(self) -> None:
        src, srcrect, dst, dstrect = self.args(4)
        sx, sy, sw, sh = struct.unpack("<4i", self.u.mem_read(srcrect, 16))
        dx, dy = struct.unpack("<2i", self.u.mem_read(dstrect, 8))
        name, tint = self._source(src)
        self.draws.append({"file": name, "tint": tint, "rect": (sx, sy, sx + sw, sy + sh), "x": dx, "y": dy,
                           "alpha": 1.0, "scale": 1.0, "how": "SDL_UpperBlit", "surface": src,
                           "to_screen": dst == self.screen})
        self._ret(0, 0)()

    def _blit_alpha(self) -> None:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        surf, x, y, x0, y0, x1, y1, alpha, scale, centre = struct.unpack("<IiiiiiiffB", self.u.mem_read(esp + 4, 37))
        name, tint = self._source(surf)
        self.draws.append({"file": name, "tint": tint, "rect": (x0, y0, x1, y1), "x": x, "y": y, "alpha": alpha,
                           "scale": scale, "how": "BlitRectWithAlpha", "surface": surf, "centre": centre})
        self._ret(0, 0x28)()

    def _window(self) -> tuple[int, int]:
        window = self.alloc(16)
        impl = self.alloc(0x80)
        self.w32(window, impl)
        self.w32(impl + 8, SCREEN)
        self.w32(impl + 0xC, SCREEN)
        for k, v in enumerate((0, 0, SCREEN, SCREEN)):          # the clip rect 0x407E60 reads
            self.w32(impl + 0x60 + 4 * k, v)
        self.screen = self.surface("screen", 1, 1, None)
        self.w32(impl + 0x30, self.screen)
        self.w32(WINDOW_GLOBAL, window)
        return window, impl

    # -------------------------------------------------------------- the game's code
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
        u.emu_start(fn, STOP, count=max_ins)
        return u.reg_read(UC_X86_REG_EAX)

    def text(self, data: bytes) -> int:
        at = self.alloc(len(data) + 1)
        self.u.mem_write(at, data + b"\0")
        return at

    def draw_text(self, font: str | None, data: bytes, x: int, y: int, colour: int, align: str = "left") -> list[dict]:
        """ldwGameWindow DrawText 0x409CC0 (or 0x409CD0 right, 0x409D20 centre); font None = the default."""
        fn = {"left": DRAW_LEFT, "right": DRAW_RIGHT, "centre": DRAW_CENTRE}[align]
        self.draws = []
        self.call(fn, (self.text(data), x, y, colour, self.fonts[font] if font else 0), ecx=self.window)
        return list(self.draws)

    def string_width(self, font: str, data: bytes) -> int:
        return self.call(STRING_WIDTH, (self.text(data), 0x3F800000), ecx=self.fonts[font])

    def glyph_rows(self, font: str) -> list[tuple[int, int, int, int, int]]:
        """The glyph table as the loader left it (rows of character, left, top, right, bottom)."""
        impl = self.r32(self.fonts[font] + 4)
        at, rows = self.r32(impl + 0x18), []
        while True:
            row = struct.unpack("<5i", self.u.mem_read(at, 20))
            if row[0] == 0:
                return rows
            rows.append(row)
            at += 20

    def char_index(self, font: str) -> list[int]:
        impl = self.r32(self.fonts[font] + 4)
        return list(struct.unpack("<256i", self.u.mem_read(impl + 0x1C, 1024)))

    def font_file(self, font: str) -> str:
        impl = self.r32(self.fonts[font] + 4)
        return self.surfaces[self.r32(self.r32(impl + 0xC))]

    def default_font(self) -> int:
        return self.r32(self.impl + 0x5C)

    def line_height(self, font: str) -> int:
        return self.call(0x4023F0, (0,), ecx=self.fonts[font])

    def surface_pixels(self, surf: int) -> bytes:
        w, h = self.r32(surf + 8), self.r32(surf + 0xC)
        return bytes(self.u.mem_read(self.r32(surf + 0x14), w * h * 4))


def _png_size(path: Path) -> tuple[int, int]:
    data = Path(path).read_bytes()[:24]
    return struct.unpack(">II", data[16:24])
