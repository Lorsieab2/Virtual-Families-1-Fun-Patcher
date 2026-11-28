"""tests/picture_emu.py's emulator with vf1skin.dll loaded and installed in it, for tests/test_skin_tone_draw.py.

The game's own people-drawing code runs as in picture_emu (the vanilla Virtual Families.exe, read only): the house
(CVillagerManager::DrawVillager 0x48B4D0 and the carried-items draw 0x48A100 inside it), the portrait (0x486B60), the
event pop-up's portrait (0x486D20) and the Family Tree's DrawParent / DrawChild, entered from the tree scene's own call
instructions (0x439CC6, 0x439E01, 0x439FA0) with the record in the register the scene keeps it in.

The DLL is the built one, byte for byte: its sections are mapped, its relocations applied, and it installs itself
through its own VF1Skin_Startup (every pin compared with the vanilla bytes, the hooks written). Each of its imports is a
stand-in here: kernel32 (files: the vanilla Images folder's sheets, the patcher's own Skin Masks pictures, read only),
SDL2 (SDL_CreateRGBSurface makes a surface in the emulator's memory, SDL_FreeSurface records the free).

Every blit is recorded where the game's own BlitRectWithAlpha 0x404C30 goes on after the DLL's hook and the
trampoline's two moved instructions (0x404C35, `sub esp, 5Ch` and `fldz` done), so what is recorded is what the game's
blitter is really given: the surface (the game's own, or a recoloured row), the rectangle and the place. The plain
blit 0x404BC0 is watched too: a person's draw must never reach it.
"""
from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pefile
import picture_emu as pe
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EIP, \
    UC_X86_REG_ESP

# unicorn commits guest memory through first-chance access violations it handles itself (tests/kids_emu.py)
faulthandler.disable()

ROOT = Path(__file__).resolve().parents[1]
MASKS = ROOT / "patcher" / "payload" / "SkinMasks"
DLL_BASE = 0x30000000
THUNKS = 0x2F000000
SDL = 0x51000000
GAME = "X:\\Game\\"
FOLDER = GAME + "Virtual Families 1 Patcher Files\\"
BLIT_ON = 0x404C35            # BlitRectWithAlpha after its first two instructions
PLAIN_BLIT = 0x404BC0
TREE = 0x5AB908
GAME_STATE_INSTANCE = 0x50025C
PAGE_EXECUTE_READWRITE = 0x40


class SkinEmu(pe.Emu):
    def __init__(self, game: Path, dll: Path, *, pixels, wanted, setting: int = 1, preferred: int = 0) -> None:
        """`pixels(name) -> (width, height, rgba bytes)`; `wanted`: the sheets whose pixels are needed (the others are
        surfaces with no pixels: nothing may read them)."""
        self.wanted = set(wanted)
        self.setting = setting
        self.preferred = preferred
        self.opened: list[str] = []
        self.freed: list[int] = []
        self.made: dict[int, tuple[int, int]] = {}
        self.handles: dict[int, list] = {}
        self.protects: list[tuple[int, int, int]] = []
        self.plain_blits = 0
        self.files_override: dict[str, bytes] = {}
        self.logged: list[tuple[int, ...]] = []
        super().__init__(game, pixels=pixels)
        self._map_dll(Path(dll))
        # the recording moves from 0x404C30 (now the DLL's jump) to where the game's blit goes on
        del self._code_hooks[0x404C30]
        self._code_hooks[BLIT_ON] = self._blit_on
        self._code_hooks[PLAIN_BLIT] = self._plain_blit
        for address in (BLIT_ON, PLAIN_BLIT):
            self.u.hook_add(UC_HOOK_CODE, self._code, begin=address, end=address)
        self._finish = self.alloc(16)        # fstp st(0); add esp, 5Ch; ret 28h -- the recorded blit returns from here
        self.u.mem_write(self._finish, b"\xDD\xD8\x83\xC4\x5C\xC2\x28\x00")

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
        self.dll_size = size
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

    def in_dll(self, address: int) -> bool:
        return DLL_BASE <= address < DLL_BASE + self.dll_size

    def _thunk(self, name: str) -> int:
        if name not in self.thunk_of:
            addr = THUNKS + 0x10 * len(self.thunks)
            self.thunks[addr] = name
            self.thunk_of[name] = addr
        return self.thunk_of[name]

    def _stack(self, n: int) -> tuple[int, ...]:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        return struct.unpack(f"<{n}I", self.u.mem_read(esp + 4, 4 * n))

    def _wstr(self, a: int) -> str:
        out = bytearray()
        while True:
            two = bytes(self.u.mem_read(a + len(out), 2))
            if two == b"\0\0":
                return out.decode("utf-16-le")
            out += two

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

    def _imp_VirtualFree(self):
        return 1, 12

    def _imp_FlushInstructionCache(self):
        return 1, 12

    def _imp_GetCurrentProcess(self):
        return 0xFFFFFFFF, 0

    def _imp_GetCurrentProcessId(self):
        return 0x1234, 0

    def _imp_GetTickCount(self):
        return 0x00C0FFEE, 0

    def _imp_QueryPerformanceCounter(self):
        out, = self._stack(1)
        self.u.mem_write(out, struct.pack("<Q", 0x123456789))
        return 1, 4

    def _imp_GetModuleHandleW(self):
        name, = self._stack(1)
        if name == 0:
            return pe.BASE, 4
        return {"sdl2.dll": SDL}.get(self._wstr(name).lower(), 0), 4

    def _imp_GetModuleHandleExW(self):
        flags, address, out = self._stack(3)
        assert flags & 4 and self.in_dll(address)          # FROM_ADDRESS: the DLL asks for itself
        self.w32(out, DLL_BASE)
        return 1, 12

    def _imp_GetProcAddress(self):
        _module, name = self._stack(2)
        text = bytearray()
        while (c := bytes(self.u.mem_read(name + len(text), 1))) != b"\0":
            text += c
        return self._thunk(text.decode()), 8

    def _imp_GetModuleFileNameW(self):
        module, out, room = self._stack(3)
        assert module in (0, DLL_BASE)
        text = GAME + "Virtual Families - Modded.exe" if module == 0 else FOLDER + "vf1skin.dll"
        assert len(text) < room
        self.u.mem_write(out, text.encode("utf-16-le") + b"\0\0")
        return len(text), 12

    def _imp_GetPrivateProfileIntW(self):
        section, key, default, _path = self._stack(4)
        name = (self._wstr(section), self._wstr(key))
        return {("Patches", "SkinTones"): self.setting, ("SkinTones", "PreferredTone"): self.preferred}.get(
            name, default), 16

    def _file(self, path: str) -> bytes | None:
        if path in self.files_override:
            return self.files_override[path]
        if path.startswith(GAME + "Images\\"):
            p = self.game / "Images" / path[len(GAME + "Images\\"):]
        elif path.startswith(FOLDER + "Skin Masks\\"):
            p = MASKS / path[len(FOLDER + "Skin Masks\\"):]
        else:
            return None
        return p.read_bytes() if p.is_file() else None

    def _imp_CreateFileW(self):
        path, access, _share, _sa, disposition, _flags, _template = self._stack(7)
        text = self._wstr(path)
        if text.endswith("vf1skin.log"):
            return 0xFFFFFFFF, 28
        assert access == 0x80000000 and disposition == 3, text          # GENERIC_READ, OPEN_EXISTING only
        data = self._file(text)
        self.opened.append(text)
        if data is None:
            return 0xFFFFFFFF, 28
        h = 0x1000 + 4 * len(self.handles)
        self.handles[h] = [data, 0]
        return h, 28

    def _imp_GetFileSize(self):
        h, high = self._stack(2)
        if high:
            self.w32(high, 0)
        return len(self.handles[h][0]), 8

    def _imp_ReadFile(self):
        h, buf, n, got, _ov = self._stack(5)
        data, pos = self.handles[h]
        chunk = data[pos:pos + n]
        self.u.mem_write(buf, chunk)
        self.handles[h][1] = pos + len(chunk)
        self.w32(got, len(chunk))
        return 1, 20

    def _imp_CloseHandle(self):
        h, = self._stack(1)
        self.handles.pop(h, None)
        return 1, 4

    # SDL2 (cdecl)
    def _imp_SDL_CreateRGBSurface(self):
        _flags, w, h, depth, r, g, b, a = self._stack(8)
        assert depth == 32
        surf = self._surface(f"made@{len(self.made)}", w, h)
        fmt = self.r32(surf + 4) & 0xFFFFFFFF
        for k, v in enumerate((r, g, b, a)):
            self.w32(fmt + 0xC + 4 * k, v)
        self.made[surf] = (w, h)
        return surf, 0

    def _imp_SDL_FreeSurface(self):
        self.freed.append(self._stack(1)[0])
        return 0, 0

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

    def grid(self, image: int) -> int:
        """picture_emu's grid, kept where the game's GetImageGrid keeps it: the image table entry's +0x2C (the DLL
        reads the sheets from there)."""
        g = super().grid(image)
        import vf1_skin_sites as S          # tools/
        for entry in self.entries.get(image, ()):
            self.w32(entry + S.IMAGE_ENTRY_GRID, g)
        return g

    @property
    def entries(self) -> dict[int, list[int]]:
        if not hasattr(self, "_entries"):
            import vf1_skin_masks as M
            import vf1_skin_sites as S
            data = open(self.game / "Virtual Families.exe", "rb").read()
            exe = S.L.Exe(data)
            self._entries = {}
            for _name, image, _part, _rows in M.SHEETS:
                self._entries.setdefault(image, set()).add(S.image_entry(exe, image))
        return self._entries

    def _blit_on(self, _self) -> None:
        if self.run_blits:
            return
        esp = self.u.reg_read(UC_X86_REG_ESP)
        a = struct.unpack("<IiiiiiiffB", self.u.mem_read(esp + 0x5C + 4, 37))
        surf, x, y, x0, y0, x1, y1, alpha, scale, centre = a
        self.blits.append({"file": self.surfaces.get(surf, "?"), "rect": (x0, y0, x1, y1), "x": x, "y": y,
                           "alpha": alpha, "scale": scale, "centre": centre, "surface": surf})
        self.u.reg_write(UC_X86_REG_EIP, self._finish)

    def _plain_blit(self, _self) -> None:
        self.plain_blits += 1
        raise AssertionError("a person's draw reached the plain blit 0x404BC0")

    # -------------------------------------------------------------- installing and naming the people
    def install(self) -> int:
        return self.call(self.exports["VF1Skin_Startup"], max_ins=200_000_000)

    def status(self) -> dict:
        names = ("magic", "version", "requested", "resolved", "installed", "entries", "sheets", "refused", "rows",
                 "bytes", "swapped", "made", "lastLoad", "lastSave", "babies", "preferred")
        return dict(zip(names, struct.unpack(f"<{len(names)}I",
                                             self.u.mem_read(self.exports["VF1Skin_Status"], 4 * len(names)))))

    def name(self, slot: int, text: str) -> None:
        self.u.mem_write(pe.VILLAGER0 + slot * 0x145FC + 0x2A44, text.encode("latin-1") + b"\0")

    def set_tone(self, slot: int, tone: int) -> int:
        return self.call(self.exports["VF1Skin_Set"], (slot, tone), max_ins=50_000_000)

    def get_tone(self, slot: int) -> tuple[int, int]:
        out = self.alloc(8)
        ok = self.call(self.exports["VF1Skin_Get"], (slot, out, out + 4), max_ins=50_000_000)
        assert ok == 1
        return self.r32(out), self.r32(out + 4)

    # -------------------------------------------------------------- the draws
    def draw_house(self, alpha: float = 1.0, slot: int = 0) -> list[dict]:
        # reading a sheet's file and mask the first time is a pass over every byte of them: far more instructions
        # than picture_emu allows a draw
        self.blits = []
        self.call(0x48B4D0, (slot, struct.unpack("<I", struct.pack("<f", alpha))[0]), ecx=pe.MANAGER,
                  max_ins=4_000_000_000)
        return list(self.blits)

    def draw_portrait(self, x: int = 2000, y: int = 2000, expression: int = 0) -> list[dict]:
        self.blits = []
        self.w32(0x4FC0C0, expression)
        self._code_hooks[0x403650] = self._ret_value(999, 0)
        try:
            self.call(0x486B60, (x, y), ecx=pe.VILLAGER0, max_ins=4_000_000_000)
        finally:
            del self._code_hooks[0x403650]
        return list(self.blits)

    def draw_event_portrait(self, x: int = 2000, y: int = 2000) -> list[dict]:
        """The event pop-up's portrait as CIslandEventDialog's draw calls it (0x419DA0..0x419DB5)."""
        self.blits = []
        one = struct.unpack("<I", struct.pack("<f", 1.0))[0]
        self.call(0x486D20, (x, y, 0, one, 0), ecx=pe.VILLAGER0, max_ins=4_000_000_000)
        return list(self.blits)

    def draw_tree_person(self, call_site: int, record: int, peep: int, *, x: int = 2000, y: int = 2000) -> list[dict]:
        """One Family Tree person, entered at the tree scene's own call instruction (0x439CC6 / 0x439E01 with the
        record in edi, 0x439FA0 with record + child * 0xD8 in ebp); the call's seven arguments as the scene pushes
        them (the clip rectangle, x, y, gender, head, body, scale)."""
        self.blits = []
        scene = self.alloc(0x80)
        for k, v in enumerate((0, 0, pe.SCREEN, pe.SCREEN)):
            self.w32(scene + 8 + 4 * k, v)
        clip = self.alloc(16)
        for k, v in enumerate((0, 0, pe.SCREEN, pe.SCREEN)):
            self.w32(clip + 4 * k, v)
        gender, head, body = (self.r32(peep + o) for o in (0x1C, 0x20, 0x24))
        one = struct.unpack("<I", struct.pack("<f", 1.0))[0]
        args = (clip, x, y, gender, head, body, one)
        esp = pe.STACK - 0x1000
        for a in reversed(args):
            esp -= 4
            self.u.mem_write(esp, struct.pack("<I", a & 0xFFFFFFFF))
        stop = call_site + 5
        self.u.reg_write(UC_X86_REG_ESP, esp)
        self.u.reg_write(UC_X86_REG_ECX, scene)
        if call_site == 0x439FA0:
            self.u.reg_write(UC_X86_REG_EBP, peep - 0x1B8)
        else:
            self.u.reg_write(UC_X86_REG_EDI, record)
        self._fldcw()
        self.u.emu_start(call_site, stop, count=4_000_000_000)
        return list(self.blits)

    def surface_pixels(self, surf: int) -> tuple[int, int, bytes]:
        w, h, pitch = self.r32(surf + 8), self.r32(surf + 0xC), self.r32(surf + 0x10)
        assert pitch == w * 4
        return w, h, bytes(self.u.mem_read(self.r32(surf + 0x14) & 0xFFFFFFFF, w * h * 4))

    def picture(self, colour, blits, width, height, origin) -> bytes:
        """blit_onto for blits that may name a recoloured row: the game's own blitter draws them (the trampoline
        then the game's code; the DLL's hook only hands the draw on, since no tone is noted outside a draw)."""
        named = []
        for k, b in enumerate(blits):
            name = b["file"]
            if name not in self.surface_of or self.surface_of[name] != b["surface"]:
                name = f"blit@{k}"
                self.surface_of[name] = b["surface"]
            named.append(dict(b, file=name))
        return self.blit_onto(colour, named, width, height, origin)
