"""Runs Virtual Families 1's own text code, and vf1text.dll (Render Unicode with In-Game Fonts) on top of it, in
Unicorn: the REAL vanilla executable (VF1_VANILLA_DIR, read only) and the REAL compiled DLL, mapped into one
address space by kids_emu.Emu (the VF2 patcher's harness).

Game code that runs as it is: ldwFont::ldwFont 0x4022A0 and its loader 0x402720 (the glyph table, the bands,
the 256-entry byte map, on the game's own table in .data), ldwFont::GetWidth 0x402320, GetHeight 0x4023F0,
ldwGameWindowImpl::DrawString 0x409660 and its counted twin 0x409450, ldwFontImpl::GetCharSourceRect 0x402AD0,
and the text box's HandleMessage 0x40DA70, GetText 0x40D740 and the SDL_TEXTINPUT case at 0x4049BB.

Stood in for (not text logic): the font sheet's file check and image object (0x40B270 / 0x40B350 /
0x40B6C0: a surface of the sheet's size), operator new 0x497B14, the tinted sheet 0x402940 (one surface per
colour, recorded), the clip 0x407E60 (a screen with room for everything), BlitRectWithAlpha 0x404C30 and
SDL_UpperBlit (recorded), the message queue (0x402140 / 0x401E80 / 0x401EA0, recorded), and SDL's surface
calls, IMG_Load and the DLL's kernel32 calls (files come from the repository's payload\\UnicodeText).
Nothing here starts the game.
"""
from __future__ import annotations

import struct
import unicodedata
from pathlib import Path

from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ESP

import kids_emu as K

ROOT = Path(__file__).resolve().parents[1]
GLYPHS = ROOT / "patcher" / "payload" / "UnicodeText"
DLL_PATH = "C:\\Game\\Virtual Families 1 Patcher Files\\vf1text.dll"
FOLDER = "C:\\Game\\Virtual Families 1 Patcher Files\\Unicode Text\\"
FONT_CTORS = {   # name: (table, spacing) -- found by vf1_game_fonts.find_game_fonts
    "SegoeUi33": 0x4EB6F0, "SegoeUiBold17": 0x4EC610, "SegoeUiBold18": 0x4ED538, "SegoeUiBold24": 0x4EE460,
}
RGBA_MASKS = (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)


class TextWorld:
    """One emulated process: the game's fonts, a screen, a text box; vf1text.dll installed or not."""

    def __init__(self, exe: Path, dll: Path, game_dir: Path, *, install: bool, real_gdi: bool = False):
        self.real_gdi = real_gdi
        import vf1_picture_image as pi
        self.pi = pi
        self.game_dir = Path(game_dir)
        self.e = K.Emu(exe, dll, 0)
        e = self.e
        self.blits: list[tuple] = []       # ("blit", surface, (sx, sy, w, h), (dx, dy)) / ("alpha", ...)
        self.posts: list[tuple] = []
        self.changed = 0
        self.tints: dict[int, int] = {}    # colour -> surface
        self.surfaces: dict[int, dict] = {}
        self.files: dict[int, bytes] = {}
        self.handles = 0x500
        self.gdi_calls: list[str] = []
        self.normalize = True
        self._seams()
        self.screen = self.surface(16, 16)
        self.window = e.alloc(0x80)
        e.w32(self.window + 0x30, self.screen)
        self.fonts = {name: self.make_font(name, table) for name, table in FONT_CTORS.items()}
        e.w32(self.window + 0x5C, self.fonts["SegoeUiBold18"])
        self.installed = None
        if install:
            self.installed = e.call(e.dll_export("VF1Text_Startup"))

    # ------------------------------------------------------------------ memory
    PIXELS, PIXELS_SIZE = 0x42000000, 0x0C000000      # the sheets' pixels (kids_emu's heap is 16 MB)

    def pixel_alloc(self, n: int) -> int:
        if not getattr(self, "_pixel_next", 0):
            self.e.uc.mem_map(self.PIXELS, self.PIXELS_SIZE)
            self._pixel_next = self.PIXELS
        p = self._pixel_next
        self._pixel_next += (n + 0xFFF) & ~0xFFF
        if self._pixel_next > self.PIXELS + self.PIXELS_SIZE:
            raise K.EmuError("the emulator's picture memory is used up")
        return p

    def surface(self, w: int, h: int, masks=RGBA_MASKS, pixels: bytes | None = None, tag: str = "") -> int:
        e = self.e
        fmt = e.alloc(0x28)
        e.write(fmt, struct.pack("<IIBBxxIIII", 0x16462004, 0, 32, 4, *masks))
        px = self.pixel_alloc(max(4, w * h * 4))
        if pixels:
            e.write(px, pixels)
        s = e.alloc(0x40)
        e.write(s, struct.pack("<IIiiiI", 0, fmt, w, h, w * 4, px))
        self.surfaces[s] = {"w": w, "h": h, "px": px, "tag": tag}
        return s

    def surface_pixels(self, s: int) -> bytes:
        info = self.surfaces[s]
        return self.e.read(info["px"], info["w"] * info["h"] * 4)

    # ------------------------------------------------------------------ seams
    def _seams(self):
        e = self.e

        def new(em):
            return em.alloc(max(4, em.arg(0))), 0
        e.seam(0x497B14, new)
        e.seam(0x40B270, lambda em: (1, 0))                                  # the sheet file is there

        def image_ctor(em):                                                  # thiscall(name), ret 4
            obj = em.ecx
            name = em.cstr(em.arg(0))
            sheet = self.pi.decode_png((self.game_dir / "Images" / name).read_bytes())
            s = self.surface(sheet.width, sheet.height, pixels=bytes(sheet.data), tag="game:" + name)
            em.w32(obj, s)
            return obj, 4
        e.seam(0x40B350, image_ctor)
        e.seam(0x40B6C0, lambda em: (em.r32(em.ecx), 0))                     # GetSurface

        def tinted(em):                                                      # thiscall(colour), ret 4
            colour = em.arg(0)
            impl = em.ecx
            key = (impl, colour & 0xFFFFFF)
            if key not in self.tints:
                self.tints[key] = em.alloc(0x40)
            return self.tints[key], 4
        e.seam(0x402940, tinted)
        e.seam(0x407E60, lambda em: (1, 12))                                 # clip: everything fits

        def alpha_blit(em):
            a = [em.arg(i) for i in range(10)]
            alpha = struct.unpack("<f", struct.pack("<I", a[7]))[0]
            self.blits.append(("alpha", a[0], (a[3], a[4], a[5] - a[3], a[6] - a[4]), (a[1], a[2]), alpha))
            return 0, 0x28
        e.seam(0x404C30, alpha_blit)

        mgr = e.alloc(0x10)
        e.seam(0x402140, lambda em: (mgr, 0))

        def post(em):
            self.posts.append((em.arg(0), em.arg(1), em.arg(2)))
            return 0, 12
        e.seam(0x401E80, post)

        def post_changed(em):
            self.changed += 1
            return 0, 8
        e.seam(0x401EA0, post_changed)
        e.seam(0x40D4F0, lambda em: (0, 0))                                  # EndEdit

        def upper_blit(em):
            src, srect, dst, drect = (em.arg(i) for i in range(4))
            sx, sy, w, h = struct.unpack("<4i", em.read(srect, 16))
            dx, dy = struct.unpack("<2i", em.read(drect, 8))
            self.blits.append(("blit", src, (sx, sy, w, h), (dx, dy)))
            return 0, 0

        def create(em):
            flags, w, h, depth, r, g, b, a = (em.arg(i) for i in range(8))
            return self.surface(w, h, (r, g, b, a), tag="created"), 0

        def map_rgba(em):
            fmt = em.arg(0)
            r, g, b, a = (em.arg(i) & 0xFF for i in range(1, 5))
            rm, gm, bm, am = struct.unpack("<4I", em.read(fmt + 12, 16))

            def put(v, m):
                if not m:
                    return 0
                s = (m & -m).bit_length() - 1
                return (v << s) & m
            return put(r, rm) | put(g, gm) | put(b, bm) | put(a, am), 0

        def img_load(em):
            path = em.read(em.arg(0), 600).split(b"\0", 1)[0].decode("utf-8")
            assert path.startswith(FOLDER), path
            local = GLYPHS / path[len(FOLDER):]
            if not local.is_file():
                return 0, 0
            sheet = self.pi.decode_png(local.read_bytes())
            return self.surface(sheet.width, sheet.height, pixels=bytes(sheet.data), tag="patcher:" + local.name), 0

        e.bind_exe_imports({
            "SDL_UpperBlit": upper_blit, "SDL_CreateRGBSurface": create, "SDL_MapRGBA": map_rgba,
            "SDL_LockSurface": lambda em: (0, 0), "SDL_UnlockSurface": lambda em: (0, 0), "IMG_Load": img_load,
        })

        # the DLL's own imports
        heap = 0x7777

        def get_module_file_name(em):
            buf, size = em.arg(1), em.arg(2)
            data = DLL_PATH.encode("utf-16-le") + b"\0\0"
            em.write(buf, data)
            return len(DLL_PATH), 12

        def wide_to_multi(em):
            cp, flags, src, n, dst, size = (em.arg(i) for i in range(6))
            text = em.wstr(src)
            data = text.encode("utf-8") + b"\0"
            if dst and size:
                em.write(dst, data[:size])
            return len(data), 32

        def create_file(em):
            path = em.wstr(em.arg(0))
            if not path.startswith(FOLDER):
                return 0xFFFFFFFF, 28
            local = GLYPHS / path[len(FOLDER):]
            if not local.is_file():
                return 0xFFFFFFFF, 28
            self.handles += 4
            self.files[self.handles] = [local.read_bytes(), 0]
            return self.handles, 28

        def get_file_size(em):
            return len(self.files[em.arg(0)][0]), 8

        def read_file(em):
            h, buf, n, got = (em.arg(i) for i in range(4))
            data, at = self.files[h]
            piece = data[at:at + n]
            em.write(buf, piece)
            self.files[h][1] = at + len(piece)
            if got:
                em.w32(got, len(piece))
            return 1, 20

        def virtual_protect(em):
            if em.arg(3):
                em.w32(em.arg(3), 0x20)
            return 1, 16

        def load_library(em):
            name = em.wstr(em.arg(0)).lower()
            return (0x6600 if name == "normaliz.dll" and self.normalize else 0), 4

        def normalize_string(em):
            form, src, n, dst, size = (em.arg(i) for i in range(5))
            text = em.read(src, n * 2).decode("utf-16-le", "surrogatepass")
            out = unicodedata.normalize("NFC", text).encode("utf-16-le", "surrogatepass")
            units = len(out) // 2
            if units > size:
                return 0, 20
            em.write(dst, out)
            return units, 20

        def gdi(name):
            def fn(em):
                self.gdi_calls.append(name)
                raise K.EmuError(f"{name}: a letter was drawn by Windows inside the emulator")
            return fn

        e.dyn_procs["NormalizeString"] = normalize_string
        e.imports.update({
            "GetModuleFileNameW": get_module_file_name, "WideCharToMultiByte": wide_to_multi,
            "CreateFileW": create_file, "GetFileSize": get_file_size, "ReadFile": read_file,
            "CloseHandle": lambda em: (1, 4), "GetProcessHeap": lambda em: (heap, 0),
            "HeapAlloc": lambda em: (em.alloc(max(4, em.arg(2))), 12),
            "HeapFree": lambda em: (1, 12), "VirtualProtect": virtual_protect,
            "FlushInstructionCache": lambda em: (1, 12), "GetCurrentProcess": lambda em: (0xFFFFFFFF, 0),
            "LoadLibraryW": load_library,
        })
        for name in ("CreateCompatibleDC", "CreateFontW", "SelectObject", "GetTextFaceW", "GetFontData",
                     "GetTextExtentPoint32W", "GetTextMetricsW", "CreateDIBSection", "SetBkMode", "SetTextColor",
                     "TextOutW", "GdiFlush", "DeleteObject"):
            e.imports[name] = gdi(name)
        if self.real_gdi:
            RealGdi(self).bind()

    # ------------------------------------------------------------------ the game's objects
    def make_font(self, name: str, table: int) -> int:
        """ldwFont::ldwFont(name, table, 0) 0x4022A0 run as it is."""
        e = self.e
        font = e.alloc(8)
        n = e.alloc(64)
        e.write(n, name.encode() + b"\0")
        e.call(0x4022A0, (n, table, 0), ecx=font)
        return font

    def impl(self, font: str) -> int:
        return self.e.r32(self.fonts[font] + 4)

    def cstr(self, data: bytes) -> int:
        p = self.e.alloc(len(data) + 1)
        self.e.write(p, data + b"\0")
        return p

    # ------------------------------------------------------------------ calls
    def draw(self, text: bytes, font: str = "SegoeUiBold18", x: int = 0, y: int = 0,
             colour: int = 0xFFFFFFFF) -> list[tuple]:
        """ldwGameWindowImpl::DrawString 0x409660 (or vf1text.dll's, when installed)."""
        self.blits = []
        self.e.call(0x409660, (self.cstr(text), x, y, colour, self.fonts[font]), ecx=self.window)
        return self.blits

    def draw_n(self, text: bytes, count: int, font: str = "SegoeUiBold18", measure: bool = False) -> tuple[int, list]:
        self.blits = []
        width = self.e.call(0x409450, (self.cstr(text), count, 0, 0, 1 if measure else 0, 0xFFFFFFFF,
                                       self.fonts[font]), ecx=self.window)
        return width, self.blits

    def width(self, text: bytes, font: str = "SegoeUiBold18", scale: float = 1.0) -> int:
        bits = struct.unpack("<I", struct.pack("<f", scale))[0]
        return self.e.call(0x402320, (self.cstr(text), bits), ecx=self.fonts[font])

    # ------------------------------------------------------------------ the text box
    def text_box(self, limit: int = 20) -> int:
        """An ldwTextControlImpl in edit mode, empty, with the stock 0x40D370 buffer (limit + 1 bytes)."""
        e = self.e
        c = e.alloc(0x40)
        owner = e.alloc(0x10)
        e.write(owner + 8, b"\x01")
        e.w32(c + 4, 77)
        e.w32(c + 0x1C, owner)
        e.write(c + 0x25, b"\x01")
        e.w32(c + 0x28, limit)
        buf = e.alloc(limit + 1 + 16, fill=0xCC)     # 0xCC after the buffer shows any overrun
        e.write(buf, b"\0")
        e.w32(c + 0x30, buf)
        self.box_end = buf + limit + 1
        return c

    def box_text(self, c: int) -> bytes:
        return self.e.read(self.e.r32(c + 0x30), self.e.r32(c + 0x28) + 1).split(b"\0", 1)[0]

    def overrun(self, c: int) -> bool:
        return self.e.read(self.box_end, 16) != b"\xcc" * 16

    def key(self, c: int, ch: int) -> int:
        """HandleMessage(5, 0, ch) 0x40DA70."""
        return self.e.call(0x40DA70, (5, 0, ch), ecx=c) & 0xFF

    def get_text(self, c: int, size: int) -> bytes:
        """ldwTextControl::GetText(buffer, size) 0x40D740 on a control whose +0x10 is the box."""
        e = self.e
        ctl = e.alloc(0x20)
        e.w32(ctl + 0x10, c)
        buf = e.alloc(size + 16, fill=0xCC)
        e.call(0x40D740, (buf, size), ecx=ctl)
        data = e.read(buf, size + 16)
        assert data[size:] == b"\xcc" * 16, "GetText wrote past the buffer"
        return data[:size]

    def typed(self, text: bytes) -> list[tuple]:
        """The SDL_TEXTINPUT case of the event loop with `text` as the event's text (0x4049A5..): runs from
        0x4049BB with eax = its length to 0x4049C4 (one byte, the stock path) or 0x404A87 (done)."""
        e = self.e
        self.posts = []
        frame = e.sp_top - 0x200
        e.write(frame + 0x30, text + b"\0")
        e.setreg(UC_X86_REG_ESP, frame)
        e.setreg(UC_X86_REG_EAX, len(text))
        e.setreg(UC_X86_REG_EBX, 0)
        self.stops = []
        if not getattr(self, "_stop_hooks", False):
            self._stop_hooks = True
            for stop in (0x4049C4, 0x404A87):
                def hit(uc, address, size, user, stop=stop):
                    if self.stopping:
                        self.stops.append(stop)
                        uc.emu_stop()
                e.uc.hook_add(K.UC_HOOK_CODE, hit, begin=stop, end=stop)
        self.stopping = True
        try:
            e.uc.emu_start(0x4049BB, 0xFFFFFFFF, count=200000)
        finally:
            self.stopping = False
        self.last_stop = self.stops[0] if self.stops else None
        assert e.reg(UC_X86_REG_ESP) == frame, "the stack is not where the event loop left it"
        return self.posts


class RealGdi:
    """The DLL's GDI calls carried out by this machine's real GDI (Windows only), so a letter Windows draws on the
    spot goes through the DLL's own code inside the emulator: every call's arguments are read from the emulated
    memory, the real call is made, and its results are written back (a DIB's pixels are copied in and out around
    TextOutW)."""

    def __init__(self, world: TextWorld):
        import ctypes
        import vf1_glyph_gdi as g
        if not g.AVAILABLE:
            raise K.EmuError("real GDI needs Windows")
        self.w, self.c, self.g = world, ctypes, g
        self.handles: dict[int, int] = {}       # emulated handle -> real handle
        self.reverse: dict[int, int] = {}
        self.dibs: dict[int, tuple[int, int, int]] = {}    # emulated bitmap -> (real bits, emulated bits, size)
        self.next = 0x9000
        self.calls: list[str] = []

    def _id(self, real: int) -> int:
        if not real:
            return 0
        if real in self.reverse:
            return self.reverse[real]
        self.next += 4
        self.handles[self.next] = real
        self.reverse[real] = self.next
        return self.next

    def _real(self, fake: int):
        return self.handles.get(fake)

    def bind(self):
        c, gdi = self.c, self.g.gdi32
        W = self.w

        def log(name, fn):
            def wrapped(em):
                self.calls.append(name)
                W.gdi_calls.append(name)
                return fn(em)
            return wrapped

        def create_dc(em):
            return self._id(gdi.CreateCompatibleDC(None) or 0), 4

        def create_font(em):
            a = [em.arg(i) for i in range(13)]
            face = em.wstr(em.arg(13))
            signed = [v - 0x100000000 if v >= 0x80000000 else v for v in a[:5]]
            real = gdi.CreateFontW(*signed, *a[5:13], face)
            return self._id(real or 0), 56

        def select(em):
            dc, obj = self._real(em.arg(0)), self._real(em.arg(1))
            prev = gdi.SelectObject(dc, obj) if dc and obj else 0
            return self._id(prev or 0), 8

        def text_face(em):
            n, buf = em.arg(1), em.arg(2)
            out = c.create_unicode_buffer(max(1, n))
            got = gdi.GetTextFaceW(self._real(em.arg(0)), n, out)
            em.write(buf, (out.value + "\0").encode("utf-16-le")[:n * 2])
            return got, 12

        def font_data(em):
            dc, table, offset, buf, size = (em.arg(i) for i in range(5))
            if not buf:
                return gdi.GetFontData(self._real(dc), table, offset, None, 0), 20
            data = c.create_string_buffer(size)
            got = gdi.GetFontData(self._real(dc), table, offset, data, size)
            if got not in (0, 0xFFFFFFFF):
                em.write(buf, data.raw[:got])
            return got, 20

        def extent(em):
            dc, s, n, size = (em.arg(i) for i in range(4))
            text = em.read(s, n * 2).decode("utf-16-le", "surrogatepass")
            sz = self.g.wintypes.SIZE()
            ok = gdi.GetTextExtentPoint32W(self._real(dc), text, n, c.byref(sz))
            em.write(size, struct.pack("<ii", sz.cx, sz.cy))
            return ok, 16

        def metrics(em):
            tm = self.g.TEXTMETRICW()
            ok = gdi.GetTextMetricsW(self._real(em.arg(0)), c.byref(tm))
            em.write(em.arg(1), c.string_at(c.addressof(tm), c.sizeof(tm)))
            return ok, 8

        def dib(em):
            dc, info, usage, ppv, section, offset = (em.arg(i) for i in range(6))
            head = em.read(info, 40)
            size, width, height = struct.unpack_from("<Iii", head, 0)
            bits = c.c_void_p()
            real = gdi.CreateDIBSection(self._real(dc), c.create_string_buffer(head, 40), usage, c.byref(bits), None, 0)
            n = abs(width) * abs(height) * 4
            fake_bits = em.alloc(n + 16)
            em.w32(ppv, fake_bits)
            fake = self._id(real or 0)
            self.dibs[fake] = (bits.value, fake_bits, n)
            return fake, 24

        def text_out(em):
            dc, x, y, s, n = (em.arg(i) for i in range(5))
            text = em.read(s, n * 2).decode("utf-16-le", "surrogatepass")
            x = x - 0x100000000 if x >= 0x80000000 else x
            y = y - 0x100000000 if y >= 0x80000000 else y
            # the DIB selected now is the one the DLL made last
            real_bits, fake_bits, size = list(self.dibs.values())[-1]
            c.memmove(real_bits, em.read(fake_bits, size), size)
            ok = gdi.TextOutW(self._real(dc), x, y, text, n)
            gdi.GdiFlush()
            em.write(fake_bits, c.string_at(real_bits, size))
            return ok, 20

        def delete(em):
            real = self.handles.pop(em.arg(0), None)
            if real:
                self.reverse.pop(real, None)
                gdi.DeleteObject(real)
            self.dibs.pop(em.arg(0), None)
            return 1, 4

        W.e.imports.update({
            "CreateCompatibleDC": log("CreateCompatibleDC", create_dc), "CreateFontW": log("CreateFontW", create_font),
            "SelectObject": log("SelectObject", select), "GetTextFaceW": log("GetTextFaceW", text_face),
            "GetFontData": log("GetFontData", font_data),
            "GetTextExtentPoint32W": log("GetTextExtentPoint32W", extent),
            "GetTextMetricsW": log("GetTextMetricsW", metrics), "CreateDIBSection": log("CreateDIBSection", dib),
            "SetBkMode": log("SetBkMode", lambda em: (gdi.SetBkMode(self._real(em.arg(0)), em.arg(1)), 8)),
            "SetTextColor": log("SetTextColor", lambda em: (gdi.SetTextColor(self._real(em.arg(0)), em.arg(1)), 8)),
            "TextOutW": log("TextOutW", text_out), "GdiFlush": log("GdiFlush", lambda em: (gdi.GdiFlush(), 0)),
            "DeleteObject": log("DeleteObject", delete),
        })
