"""One character limit for every name box (native/vf1text/names.inc): the REAL vanilla executable and the REAL
compiled vf1text.dll / vf1font.dll in Unicorn (text_emu.TextWorld), plus what the name boxes need around them:

* theGameState (*0x50025C) with its slot being played (+0x1B188) and its save-file path (vtable +0xC, 0x4035F0,
  stood in for: "C:\\Saves\\Virtual Families<N>.ldw");
* the save folder as a dictionary of files (CreateFileA / ReadFile / WriteFile / MoveFileExA / CreateDirectoryA),
  so the Names files the DLL writes are read back by patcher/vf1_names.py;
* the text box's own code runs as it is: SetEditable 0x40D370 (through its wrapper 0x40D6F0), SetText 0x40D430,
  HandleMessage 0x40DA70, GetText 0x40D740, Draw 0x40D140, the word wrapper 0x409D70 -- reached from the game's
  REAL call sites, by running the game's own instructions from just before each call to just after the copy that
  follows it (run_window), with every buffer the game copies into surrounded by guard bytes.

Stood in for (not text logic): operator delete 0x497A33, the message calls 0x4021C0, the clock 0x401F00 / 0x401F10,
the box's frame and cursor drawing 0x408100 / 0x4081D0 / 0x4083F0, FamilyTree::ChangeName 0x481C20 (recorded: it
copies at most 0x19 bytes, 0x481C3A).
"""
from __future__ import annotations

import struct
from pathlib import Path

import kids_emu as K
import text_emu

SAVES = "C:\\Saves\\"
GS_SIZE = 0x1C000
GS_INSTANCE = 0x50025C
GS_SLOT = 0x1B188
DEFAULT_WINDOW = 0x500668


class NamesWorld(text_emu.TextWorld):
    def __init__(self, exe: Path, dll: Path, game_dir: Path, **kw):
        super().__init__(exe, dll, game_dir, **kw)
        e = self.e
        self.fs: dict[str, bytes] = {}          # the save folder: path -> bytes
        self.dirs: set[str] = set()
        self.open_files: dict[int, list] = {}
        self.renames: list[str] = []
        self.change_names: list[bytes] = []
        self.make_paths = 0
        self.gs = e.alloc(GS_SIZE)
        vtable = e.alloc(0x40)
        self.path_fn = e.fake_code(b"\xC2\x04\x00")
        e.w32(vtable + 0xC, self.path_fn)
        e.w32(self.gs, vtable)
        e.w32(GS_INSTANCE, self.gs)
        self.paths = {n: self.cstr(f"{SAVES}Virtual Families{n}.ldw".encode()) for n in range(0, 6)}

        def make_path(em):
            self.make_paths += 1
            return self.paths[em.arg(0)], 4
        e.seam_live(self.path_fn, make_path)
        # the default window font for a box with none (0x4080B0 -> [0x500668], 0x408400 -> [[it]] + 0x5C)
        holder = e.alloc(0x10)
        e.w32(holder, self.window)
        e.w32(DEFAULT_WINDOW, holder)
        e.seam(0x497A33, lambda em: (0, 0))
        e.seam(0x4021C0, lambda em: (0, 12))
        e.seam(0x401F00, lambda em: (0, 0))
        e.seam(0x401F10, lambda em: (0, 0))
        e.seam(0x408100, lambda em: (0, 8))
        e.seam(0x4081D0, lambda em: (0, 16))
        e.seam(0x4083F0, lambda em: (0, 4))

        def change_name(em):
            self.change_names.append(em.read(em.arg(1), 64).split(b"\0", 1)[0])
            return 0, 8
        e.seam(0x481C20, change_name)
        self._file_imports()
        self.guard_new = True

    def guards_intact(self) -> bool:
        """No allocation made by the game since the world was built was written past its end."""
        return all(self.e.read(p + n, 16) == b"\xCC" * 16 for p, n in self.news)

    # ------------------------------------------------------------------ the save folder
    def _file_imports(self):
        e = self.e

        def create(em):
            path = em.cstr(em.arg(0))
            access, disposition = em.arg(1), em.arg(4)
            if not path.startswith(SAVES):
                return 0xFFFFFFFF, 28
            if access & 0x40000000:                     # GENERIC_WRITE, CREATE_ALWAYS
                self.handles += 4
                self.open_files[self.handles] = [path, bytearray()]
                return self.handles, 28
            if path not in self.fs:
                return 0xFFFFFFFF, 28
            self.handles += 4
            self.files[self.handles] = [self.fs[path], 0]
            return self.handles, 28

        def write(em):
            h, buf, n, put = (em.arg(i) for i in range(4))
            self.open_files[h][1] += em.read(buf, n)
            if put:
                em.w32(put, n)
            return 1, 20

        def close(em):
            h = em.arg(0)
            if h in self.open_files:
                path, data = self.open_files.pop(h)
                self.fs[path] = bytes(data)
            self.files.pop(h, None)
            return 1, 4

        def move(em):
            src, dst = em.cstr(em.arg(0)), em.cstr(em.arg(1))
            self.renames.append(dst)
            self.fs[dst] = self.fs.pop(src)
            return 1, 12

        def delete(em):
            self.fs.pop(em.cstr(em.arg(0)), None)
            return 1, 4

        def mkdir(em):
            self.dirs.add(em.cstr(em.arg(0)))
            return 1, 8

        e.imports.update({"CreateFileA": create, "WriteFile": write, "CloseHandle": close, "MoveFileExA": move,
                          "DeleteFileA": delete, "CreateDirectoryA": mkdir})

    def names_file(self, slot: int) -> str:
        return f"{SAVES}Virtual Families 1 Patcher Data\\Names\\Virtual Families{slot}.ldw.txt"

    def set_slot(self, slot: int):
        self.e.w32(self.gs + GS_SLOT, slot)

    # ------------------------------------------------------------------ the game's text boxes
    def control(self, limit: int = 0) -> tuple[int, int]:
        """(ldwTextControl, its impl): an impl as the game makes it (editable off, empty), drawn in SegoeUiBold18."""
        e = self.e
        impl = e.alloc(0x80)
        owner = e.alloc(0x10)
        e.write(owner + 8, b"\x01")
        e.w32(impl + 4, 77)
        e.w32(impl + 0x1C, owner)
        e.w32(impl + 0x3C, self.fonts["SegoeUiBold18"])
        e.write(impl + 0x58, struct.pack("<f", 1.0))
        ctl = e.alloc(0x20)
        e.w32(ctl + 0x10, impl)
        return ctl, impl

    def box_buffer(self, impl: int) -> int:
        return self.e.r32(impl + 0x30)

    def box_bytes(self, impl: int) -> bytes:
        return self.e.read(self.box_buffer(impl), self.e.r32(impl + 0x28) + 1).split(b"\0", 1)[0]

    def run_window(self, start: int, stop: int, regs: dict, stack: dict[int, int] | None = None,
                   esp: int | None = None):
        """Run the game's own instructions from `start` until `stop` with these registers (and stack dwords)."""
        e = self.e
        for addr, v in (stack or {}).items():
            e.w32(addr, v)
        for reg, v in regs.items():
            e.setreg(reg, v)
        if esp is not None:
            e.setreg(K.UC_X86_REG_ESP, esp)
        try:
            e.uc.emu_start(start, stop, count=50_000_000)
        except K.UcError as exc:
            raise K.EmuError(f"stopped at {e.reg(K.UC_X86_REG_EIP):#x}: {exc}") from exc
        assert e.reg(K.UC_X86_REG_EIP) == stop, f"ended at {e.reg(K.UC_X86_REG_EIP):#x}, not {stop:#x}"

    def frame(self, size: int = 0x400) -> int:
        """A stack frame filled with 0xCC (a guard everywhere the game does not write), its base."""
        base = self.e.sp_top - 0x3000
        self.e.write(base - size, b"\xCC" * (2 * size))
        return base

    def set_editable_from(self, call_site: int, ctl: int, limit: int, editable: int = 1):
        """The game's own `call 0x40D6F0` at call_site: SetEditable(editable, limit) on ctl."""
        base = self.frame()
        self.e.w32(base, editable)
        self.e.w32(base + 4, limit)
        self.run_window(call_site, call_site + 5, {K.UC_X86_REG_ECX: ctl}, esp=base)

    def set_text(self, ctl: int, text: bytes):
        self.e.call(0x40D700, (self.cstr(text),), ecx=ctl)

    def press(self, impl: int, ch: int) -> int:
        return self.e.call(0x40DA70, (5, 0, ch), ecx=impl) & 0xFF

    def type_text(self, impl: int, text: str):
        for ch in text:
            cp = ord(ch)
            self.press(impl, cp if cp < 0x80 else (0x40000000 | cp))

    def draw_box(self, impl: int) -> list[tuple]:
        self.blits = []
        self.e.call(0x40D140, (), ecx=impl)
        return self.blits

    def wrap(self, text: bytes, width: int = 400, font: str = "SegoeUiBold18") -> list[tuple]:
        """The justified word wrapper 0x409D70(text, x, y, width, colour, font, measure only) on the world's window."""
        self.blits = []
        win = self.e.alloc(0x10)
        self.e.w32(win, self.window)
        self.e.call(0x409D70, (self.cstr(text), 0, 0, width, 0xFFFFFFFF, self.fonts[font], 0), ecx=win,
                    limit=50_000_000)
        return self.blits
