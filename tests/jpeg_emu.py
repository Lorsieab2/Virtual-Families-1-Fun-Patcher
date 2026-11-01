"""Runs Virtual Families 1's own libjpeg-9.dll in Unicorn, the way SDL2_image.dll's IMG_LoadJPG_RW
(0x10003510) calls it, for tests/test_jpeg_decoder.py.

The game decodes every .jpg through SDL2_image.dll, which loads libjpeg-9.dll ("9  13-Jan-2013") from
the game folder at run time (0x10003100..0x1000325B fill the function table 0x1001E6A8..0x1001E6C8).
IMG_LoadJPG_RW then does, in this order:

* jpeg_std_error (0x10003572) with its own error_exit 0x100034F0 (longjmp) and a silent output_message;
* jpeg_CreateDecompress(cinfo, version 90, struct size 0x1C8) (0x10003615);
* its own SDL_RWops source manager (0x10003490: a 4096-byte buffer, a fake EOI at the end of the data,
  skip_input_data, jpeg_resync_to_restart) -- here libjpeg's own jpeg_mem_src does the same for a
  whole file in memory;
* jpeg_read_header(cinfo, TRUE) (0x10003632);
* out_color_space = JCS_CMYK (4) for a 4-component file, else JCS_RGB (2) (0x10003647..0x1000367D),
  quantize_colors = FALSE (0x10003640); nothing else is changed: dct_method stays JDCT_ISLOW,
  do_fancy_upsampling TRUE, do_block_smoothing TRUE, scale 1/1 (no FAST_JPEG settings);
* jpeg_calc_output_dimensions, an SDL surface of output_width x output_height, 24 bits, masks
  R 0xFF / G 0xFF00 / B 0xFF0000 (bytes R, G, B) (0x1000368D..0x100036B0);
* jpeg_start_decompress, jpeg_read_scanlines one row at a time into the surface while output_scanline
  < output_height (0x10003712..0x10003776), jpeg_finish_decompress, jpeg_destroy_decompress.

`decode(data)` does the same and returns (width, height, RGB bytes).  The DLL's C library imports
(malloc, free, memcpy, memset, getenv, ...) are stood in for in Python; error_exit is replaced by a stop
that raises JpegEmuError with libjpeg's message code.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pefile
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc, UcError
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP

STUBS = 0x01000000          # one byte per imported function: a RET hooked in Python
STOP = 0x01100000           # return address of every call made from Python
ERROR_EXIT = 0x01100010     # our error_exit
STACK = 0x02000000
STACK_SIZE = 0x00200000
HEAP = 0x10000000

CINFO_SIZE = 0x1C8          # what SDL2_image passes (0x1000360D)
JPEG_LIB_VERSION = 90       # 0x10003612
# jpeg_decompress_struct fields (32-bit, boolean = unsigned char, as SDL2_image's offsets show)
OFF_NUM_COMPONENTS = 0x24
OFF_OUT_COLOR_SPACE = 0x2C
OFF_QUANTIZE_COLORS = 0x4A
OFF_OUTPUT_WIDTH = 0x5C
OFF_OUTPUT_HEIGHT = 0x60
OFF_OUTPUT_COMPONENTS = 0x68
OFF_OUTPUT_SCANLINE = 0x78
JERR_SIZE = 0x84            # struct jpeg_error_mgr (SDL2_image keeps 0xC4 bytes for its own)


class JpegEmuError(Exception):
    """libjpeg-9.dll called error_exit (the message code is in .code)."""

    def __init__(self, code: int, text: str = "") -> None:
        super().__init__(f"libjpeg error {code}{': ' + text if text else ''}")
        self.code = code


class JpegEmu:
    def __init__(self, game: Path) -> None:
        path = Path(game) / "libjpeg-9.dll"
        pe = pefile.PE(str(path))
        self.base = pe.OPTIONAL_HEADER.ImageBase
        image = bytearray(pe.get_memory_mapped_image())
        size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        image += bytes(size - len(image))
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u = u
        self.handlers: dict[int, object] = {}
        stub_names: dict[int, str] = {}
        n = 0
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            for imp in entry.imports:
                name = (imp.name or b"").decode()
                address = STUBS + n
                n += 1
                struct.pack_into("<I", image, imp.address - self.base, address)
                stub_names[address] = name
        u.mem_map(self.base, size)          # loaded at its preferred base: no relocation needed
        u.mem_write(self.base, bytes(image))
        u.mem_map(STUBS, 0x200000)
        u.mem_write(STUBS, b"\xC3" * n)
        u.mem_map(STACK, STACK_SIZE)
        self.exports = {e.name.decode(): e.address + self.base
                        for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
        self.stub_names = stub_names
        self.heap_top = HEAP
        self.heap_mapped = HEAP
        self.sizes: dict[int, int] = {}
        self.errno = self.alloc(4)
        self.mb_cur_max = self.alloc(4)
        self.w32(self.mb_cur_max, 1)
        u.hook_add(UC_HOOK_CODE, self._stub, begin=STUBS, end=STUBS + n)
        u.hook_add(UC_HOOK_CODE, self._error_exit, begin=ERROR_EXIT, end=ERROR_EXIT)
        self.error: JpegEmuError | None = None

    # ------------------------------------------------------------------ memory
    def alloc(self, size: int) -> int:
        a = self.heap_top
        self.heap_top += (max(size, 1) + 0xF) & ~0xF
        if self.heap_top > self.heap_mapped:
            grow = (self.heap_top - self.heap_mapped + 0xFFFFF) & ~0xFFFFF
            self.u.mem_map(self.heap_mapped, grow)
            self.heap_mapped += grow
        self.sizes[a] = size
        return a

    def r32(self, a: int) -> int:
        return struct.unpack("<I", self.u.mem_read(a, 4))[0]

    def w32(self, a: int, v: int) -> None:
        self.u.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def arg(self, i: int) -> int:
        return self.r32(self.u.reg_read(UC_X86_REG_ESP) + 4 + 4 * i)

    # ------------------------------------------------------------------ stand-ins
    def _stub(self, u, address, size, user) -> None:
        name = self.stub_names[address]
        a = self.arg
        result = 0
        if name == "malloc":
            result = self.alloc(a(0))
        elif name == "calloc":
            result = self.alloc(a(0) * a(1))
            u.mem_write(result, bytes(a(0) * a(1)))
        elif name == "free":
            result = 0
        elif name == "memcpy":
            dst, src, n = a(0), a(1), a(2)
            if n:
                u.mem_write(dst, bytes(u.mem_read(src, n)))
            result = dst
        elif name == "memset":
            dst, value, n = a(0), a(1), a(2)
            if n:
                u.mem_write(dst, bytes([value & 0xFF]) * n)
            result = dst
        elif name == "getenv":
            result = 0
        elif name == "_errno":
            result = self.errno
        elif name == "strlen":
            s = a(0)
            n = 0
            while u.mem_read(s + n, 1)[0]:
                n += 1
            result = n
        elif name in ("fprintf", "sprintf", "fputc", "fflush", "ferror", "fwrite", "fread", "sscanf") or name in ("_lock", "_unlock", "setlocale", "localeconv"):
            result = 0
        elif name in ("exit", "abort"):
            self.error = JpegEmuError(-1, f"the DLL called {name}")
            u.emu_stop()
            return
        else:
            self.error = JpegEmuError(-1, f"unexpected call to {name}")
            u.emu_stop()
            return
        u.reg_write(UC_X86_REG_EAX, result & 0xFFFFFFFF)     # cdecl: the RET at the stub returns

    def _error_exit(self, u, address, size, user) -> None:
        cinfo = self.arg(0)
        err = self.r32(cinfo)
        code = self.r32(err + 0x14)          # msg_code
        self.error = JpegEmuError(code)
        u.emu_stop()

    # ------------------------------------------------------------------ calls
    def call(self, name: str, *args: int) -> int:
        esp = STACK + STACK_SIZE - 0x100
        esp -= 4 * len(args)
        for i, value in enumerate(args):
            self.w32(esp + 4 * i, value)
        esp -= 4
        self.w32(esp, STOP)
        self.u.reg_write(UC_X86_REG_ESP, esp)
        self.error = None
        try:
            self.u.emu_start(self.exports[name], STOP)
        except UcError as exc:
            raise JpegEmuError(-2, f"{name}: {exc} at 0x{self.u.reg_read(UC_X86_REG_EIP):X}") from None
        if self.error is not None:
            raise self.error
        return self.u.reg_read(UC_X86_REG_EAX)

    def decode(self, data: bytes) -> tuple[int, int, bytes]:
        """The picture as SDL2_image's surface holds it: (width, height, R G B bytes, rows top to bottom)."""
        mark = self.heap_top
        try:
            return self._decode(data)
        finally:
            self.heap_top = mark          # everything the decode allocated is dropped

    def _decode(self, data: bytes) -> tuple[int, int, bytes]:
        jerr = self.alloc(0xC4)
        cinfo = self.alloc(CINFO_SIZE)
        self.u.mem_write(cinfo, bytes(CINFO_SIZE))
        self.w32(cinfo, self.call("jpeg_std_error", jerr))
        self.w32(jerr + 0, ERROR_EXIT)       # error_exit (SDL2_image: 0x100034F0, a longjmp)
        source = self.alloc(len(data))
        self.u.mem_write(source, data)
        try:
            self.call("jpeg_CreateDecompress", cinfo, JPEG_LIB_VERSION, CINFO_SIZE)
            self.call("jpeg_mem_src", cinfo, source, len(data))
            self.call("jpeg_read_header", cinfo, 1)
            components = self.r32(cinfo + OFF_NUM_COMPONENTS)
            self.w32(cinfo + OFF_OUT_COLOR_SPACE, 4 if components == 4 else 2)
            self.u.mem_write(cinfo + OFF_QUANTIZE_COLORS, b"\x00")
            self.call("jpeg_calc_output_dimensions", cinfo)
            width = self.r32(cinfo + OFF_OUTPUT_WIDTH)
            height = self.r32(cinfo + OFF_OUTPUT_HEIGHT)
            self.call("jpeg_start_decompress", cinfo)
            channels = self.r32(cinfo + OFF_OUTPUT_COMPONENTS)
            pitch = width * channels
            pixels = self.alloc(pitch * height)
            row_ptr = self.alloc(4)
            while self.r32(cinfo + OFF_OUTPUT_SCANLINE) < height:
                self.w32(row_ptr, pixels + pitch * self.r32(cinfo + OFF_OUTPUT_SCANLINE))
                self.call("jpeg_read_scanlines", cinfo, row_ptr, 1)
            self.call("jpeg_finish_decompress", cinfo)
            out = bytes(self.u.mem_read(pixels, pitch * height))
        finally:
            try:
                self.call("jpeg_destroy_decompress", cinfo)
            except JpegEmuError:
                pass
        if channels != 3:
            raise JpegEmuError(-3, f"{channels} output components")
        return width, height, out

    def idct(self, name: str, coefficients: list[int], quant: list[int], rows: int, cols: int) -> bytes:
        """Runs one of the DLL's IDCT routines (e.g. "jpeg_idct_16x16") on one block of 64 coefficients
        (natural order) with a quantisation table (natural order, as compptr->dct_table holds it), and
        returns its rows x cols output samples.  Needs a decoder made by jpeg_start_decompress for the
        range-limit table, so it builds one from a tiny picture first."""
        if not hasattr(self, "_idct_cinfo"):
            self._idct_cinfo = self._idct_setup()
        cinfo = self._idct_cinfo
        compptr = self.alloc(0x60)
        table = self.alloc(64 * 4)
        self.u.mem_write(table, struct.pack("<64i", *quant))
        self.w32(compptr + 0x54, table)       # dct_table (libjpeg 9 jpeg_component_info, 32-bit)
        block = self.alloc(64 * 2)
        self.u.mem_write(block, struct.pack("<64h", *coefficients))
        out = self.alloc(rows * cols)
        ptrs = self.alloc(4 * rows)
        for r in range(rows):
            self.w32(ptrs + 4 * r, out + r * cols)
        self.call(name, cinfo, compptr, block, ptrs, 0)
        return bytes(self.u.mem_read(out, rows * cols))

    def _idct_setup(self) -> int:
        """A decompressor that has run jpeg_start_decompress on a 1x1 grey picture (it owns
        sample_range_limit, which the IDCTs read); kept for the IDCT checks."""
        jerr = self.alloc(0xC4)
        cinfo = self.alloc(CINFO_SIZE)
        self.u.mem_write(cinfo, bytes(CINFO_SIZE))
        self.w32(cinfo, self.call("jpeg_std_error", jerr))
        self.w32(jerr, ERROR_EXIT)
        data = TINY_JPEG
        source = self.alloc(len(data))
        self.u.mem_write(source, data)
        self.call("jpeg_CreateDecompress", cinfo, JPEG_LIB_VERSION, CINFO_SIZE)
        self.call("jpeg_mem_src", cinfo, source, len(data))
        self.call("jpeg_read_header", cinfo, 1)
        self.call("jpeg_start_decompress", cinfo)
        return cinfo


def _tiny_jpeg() -> bytes:
    """A 1x1 one-component baseline JPEG, written by hand (one DC-only block of value 0)."""
    q = bytes([1] * 64)
    dqt = b"\xFF\xDB" + struct.pack(">H", 67) + b"\x00" + q
    sof = b"\xFF\xC0" + struct.pack(">HBHHB", 11, 8, 1, 1, 1) + b"\x01\x11\x00"
    # DC table: one code of length 1 for category 0; AC table: one code of length 1 for EOB (0x00)
    dht_dc = b"\xFF\xC4" + struct.pack(">H", 20) + b"\x00" + bytes([1] + [0] * 15) + b"\x00"
    dht_ac = b"\xFF\xC4" + struct.pack(">H", 20) + b"\x10" + bytes([1] + [0] * 15) + b"\x00"
    sos = b"\xFF\xDA" + struct.pack(">HB", 8, 1) + b"\x01\x00" + b"\x00\x3F\x00"
    scan = b"\x3F"          # bits 0 (DC cat 0), 0 (EOB), then 1-padding
    return b"\xFF\xD8" + dqt + sof + dht_dc + dht_ac + sos + scan + b"\xFF\xD9"


TINY_JPEG = _tiny_jpeg()
