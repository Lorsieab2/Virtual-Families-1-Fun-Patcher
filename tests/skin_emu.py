"""tests/picture_emu.py's emulator with vf1skin.dll loaded into it, for tests/test_skin_tone_draw.py.

The game's own people-drawing code runs as in picture_emu (the vanilla Virtual Families.exe, read only).
The DLL is the built one, byte for byte: its sections are mapped, its relocations applied, and each of its
imports is a stand-in here (kernel32: VirtualProtect, VirtualAlloc, GetModuleHandleA, GetProcAddress,
GetModuleFileNameW, WideCharToMultiByte, FlushInstructionCache, GetCurrentProcess; SDL2: SDL_CreateRGBSurface,
SDL_FreeSurface; SDL2_image: IMG_Load, which hands out the mask pictures the test gives).

Once VF1Skin_Startup has put its jump at BlitRectWithAlpha 0x404C30, every blit is recorded where the DLL
hands the draw back to the game (VF1Skin_TestBlitOriginal), so what is recorded is what the game's blitter
would really be given: the surface (the game's own, or a recoloured row), the rectangle and the place.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pefile
import picture_emu as pe
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP

DLL_BASE = 0x30000000
THUNKS = 0x2F000000
SDL, SDL_IMAGE, DLL_MODULE = 0x51000000, 0x52000000, DLL_BASE
FOLDER = "X:\\Patcher Files\\"


class SkinEmu(pe.Emu):
    def __init__(self, game: Path, dll: Path, *, pixels, masks, wanted) -> None:
        """`masks(file name) -> (width, height, rgba bytes) or None`; `wanted`: the sheets whose pixels are
        needed (the others are surfaces with no pixels: nothing may read them)."""
        self.wanted = set(wanted)
        self.masks = masks
        self.asked: list[str] = []
        self.freed: list[int] = []
        self.made: dict[int, tuple[int, int]] = {}
        super().__init__(game, pixels=pixels)
        self._map_dll(Path(dll))

    # -------------------------------------------------------------- the DLL
    def _map_dll(self, path: Path) -> None:
        dll = pefile.PE(str(path))
        u = self.u
        size = (dll.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        u.mem_map(DLL_BASE, size)
        raw = dll.__data__
        u.mem_write(DLL_BASE, bytes(raw[:dll.OPTIONAL_HEADER.SizeOfHeaders]))
        for s in dll.sections:
            u.mem_write(DLL_BASE + s.VirtualAddress, bytes(raw[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]))
        delta = DLL_BASE - dll.OPTIONAL_HEADER.ImageBase
        for block in dll.DIRECTORY_ENTRY_BASERELOC:
            for e in block.entries:
                if e.type == pefile.RELOCATION_TYPE["IMAGE_REL_BASED_HIGHLOW"]:
                    a = DLL_BASE + e.rva
                    v = struct.unpack("<I", u.mem_read(a, 4))[0]
                    u.mem_write(a, struct.pack("<I", (v + delta) & 0xFFFFFFFF))
        self.exports = {s.name.decode(): DLL_BASE + s.address for s in dll.DIRECTORY_ENTRY_EXPORT.symbols if s.name}
        u.mem_map(THUNKS, 0x2000)
        u.mem_write(THUNKS, b"\xC3" * 0x2000)
        self.thunks: dict[int, str] = {}
        self.thunk_of: dict[str, int] = {}
        for d in dll.DIRECTORY_ENTRY_IMPORT:
            for imp in d.imports:
                slot = DLL_BASE + (imp.address - dll.OPTIONAL_HEADER.ImageBase)
                u.mem_write(slot, struct.pack("<I", self._thunk(imp.name.decode())))
        u.hook_add(UC_HOOK_CODE, self._thunk_hit, begin=THUNKS, end=THUNKS + 0x1FFF)

    def _thunk(self, name: str) -> int:
        if name not in self.thunk_of:
            addr = THUNKS + 0x10 * len(self.thunks)
            self.thunks[addr] = name
            self.thunk_of[name] = addr
        return self.thunk_of[name]

    def _stack(self, n: int) -> tuple[int, ...]:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        return struct.unpack(f"<{n}I", self.u.mem_read(esp + 4, 4 * n))

    def _cstr(self, a: int) -> str:
        out = bytearray()
        while True:
            b = bytes(self.u.mem_read(a + len(out), 1))
            if b == b"\0":
                return out.decode("utf-8")
            out += b

    def _thunk_hit(self, u, addr, size, _data) -> None:
        name = self.thunks.get(addr)
        if name is None:
            return
        handler = getattr(self, "_imp_" + name, None)
        if handler is None:
            raise AssertionError(f"the DLL called {name}, which the test does not stand in for")
        value, clean = handler()
        self._ret_value(value, clean)(self)

    # kernel32 (stdcall)
    def _imp_VirtualProtect(self):
        addr, size, new, old = self._stack(4)
        self.protects.append((addr, size, new))
        self.w32(old, 0x20)
        return 1, 16

    def _imp_VirtualAlloc(self):
        _addr, size, _kind, _protect = self._stack(4)
        return self.alloc(size), 16             # the emulator's heap is zero-filled, as VirtualAlloc's is

    def _imp_FlushInstructionCache(self):
        return 1, 12

    def _imp_GetCurrentProcess(self):
        return 0xFFFFFFFF, 0

    def _imp_GetModuleHandleA(self):
        return {"sdl2.dll": SDL, "sdl2_image.dll": SDL_IMAGE}.get(self._cstr(self._stack(1)[0]).lower(), 0), 4

    def _imp_GetProcAddress(self):
        module, name = self._stack(2)
        return self._thunk(self._cstr(name)), 8

    def _imp_GetModuleFileNameW(self):
        _module, out, room = self._stack(3)
        text = FOLDER + "vf1skin.dll"
        assert len(text) < room
        self.u.mem_write(out, text.encode("utf-16-le") + b"\0\0")
        return len(text), 12

    def _imp_WideCharToMultiByte(self):
        _cp, _flags, wide, _n, out, room, _d, _u = self._stack(8)
        raw = bytearray()
        while True:
            two = bytes(self.u.mem_read(wide + len(raw), 2))
            if two == b"\0\0":
                break
            raw += two
        data = raw.decode("utf-16-le").encode("utf-8") + b"\0"
        assert len(data) <= room
        self.u.mem_write(out, data)
        return len(data), 32

    # SDL2 and SDL2_image (cdecl)
    def _imp_SDL_CreateRGBSurface(self):
        _flags, w, h, depth, r, g, b, a = self._stack(8)
        assert depth == 32
        surf = self._surface(f"made@{len(self.made)}", w, h)
        fmt = self.r32(surf + 4) & 0xFFFFFFFF
        for k, v in enumerate((r, g, b, a)):
            self.w32(fmt + 0xC + 4 * k, v)
        self.u.mem_write(fmt + 8, bytes([32, 4]))
        self.made[surf] = (w, h)
        return surf, 0

    def _imp_SDL_FreeSurface(self):
        self.freed.append(self._stack(1)[0])
        return 0, 0

    def _imp_IMG_Load(self):
        path = self._cstr(self._stack(1)[0])
        self.asked.append(path)
        assert path.startswith(FOLDER + "Skin Masks\\"), path
        got = self.masks(path.rsplit("\\", 1)[1])
        if got is None:
            return 0, 0
        w, h, data = got
        surf = self._surface("mask", w, h)
        self.u.mem_write(self.r32(surf + 0x14) & 0xFFFFFFFF, bytes(data))
        fmt = self.r32(surf + 4) & 0xFFFFFFFF
        self.u.mem_write(fmt + 8, bytes([32, 4]))
        return surf, 0

    # -------------------------------------------------------------- picture_emu's, for this test
    def _surface(self, name, w, h, *, alpha=True, pixels=True):
        surf = super()._surface(name, w, h, alpha=alpha, pixels=pixels)
        fmt = self.r32(surf + 4) & 0xFFFFFFFF
        self.u.mem_write(fmt + 8, bytes([32, 4]))          # BitsPerPixel, BytesPerPixel
        return surf

    def _file_surface(self, name):
        if name not in self.surface_of and name not in self.wanted:
            w, h = pe._png_size(self.game / "Images" / name)
            self.surface_of[name] = self._surface(name, w, h, pixels=False)
        return super()._file_surface(name)

    def _blit(self, _self) -> None:
        if self.run_blits:
            return
        esp = self.u.reg_read(UC_X86_REG_ESP)
        surf = struct.unpack("<I", self.u.mem_read(esp + 4, 4))[0]
        super()._blit(_self)
        self.blits[-1]["surface"] = surf

    def draw_house(self, alpha: float = 1.0) -> list[dict]:
        # reading a sheet's mask the first time is a pass over every pixel of it: far more instructions than
        # picture_emu allows a draw
        self.blits = []
        self.call(0x48B4D0, (0, struct.unpack("<I", struct.pack("<f", alpha))[0]), ecx=pe.MANAGER,
                  max_ins=4_000_000_000)
        return list(self.blits)

    def install(self) -> int:
        """VF1Skin_Startup, then the recording moves to where the DLL hands each blit back to the game."""
        self.protects: list[tuple[int, int, int]] = []
        self.call(self.exports["VF1Skin_TestSetModule"], (DLL_MODULE,))
        ok = self.call(self.exports["VF1Skin_Startup"])
        if ok:
            original = self.call(self.exports["VF1Skin_TestBlitOriginal"])
            self._code_hooks[original] = self._code_hooks.pop(0x404C30)
            self.u.hook_add(UC_HOOK_CODE, self._code, begin=original, end=original)
        return ok

    def set_tone(self, slot: int, tone: int) -> int:
        return self.call(self.exports["VF1Skin_SetTone"], (slot, tone))

    def status(self) -> dict:
        names = ("magic", "version", "installed", "sheets", "masks", "rows", "bytes", "swapped", "made")
        return dict(zip(names, struct.unpack("<9I", self.u.mem_read(self.exports["VF1Skin_Status"], 36))))

    def surface_pixels(self, surf: int) -> tuple[int, int, bytes]:
        w, h, pitch = self.r32(surf + 8), self.r32(surf + 0xC), self.r32(surf + 0x10)
        assert pitch == w * 4
        return w, h, bytes(self.u.mem_read(self.r32(surf + 0x14) & 0xFFFFFFFF, w * h * 4))

    def picture(self, colour, blits, width, height, origin) -> bytes:
        """blit_onto for blits that may name a recoloured row: the game's own blitter draws them."""
        named = []
        for k, b in enumerate(blits):
            name = b["file"]
            if name not in self.surface_of or self.surface_of[name] != b["surface"]:
                name = f"blit@{k}"
                self.surface_of[name] = b["surface"]
            named.append(dict(b, file=name))
        return self.blit_onto(colour, named, width, height, origin)
