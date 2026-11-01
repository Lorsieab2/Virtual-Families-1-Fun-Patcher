"""Letters the game's fonts lack, drawn by Windows (GDI) in the font's own style (Render Unicode with In-Game
Fonts, and the Game Text tool).

Virtual Families 1's four fonts are white, anti-aliased Segoe UI letters on a transparent sheet, each with
its own size and baseline (vf1_game_fonts). A character none of them has is drawn here, exactly as
vf1text.dll draws it in the game (native/vf1text/glyph_gdi.inc is the same steps in C, and
tests/test_vf1_glyph_gdi.py runs the DLL's own copy through 32-bit rundll32 and compares every pixel):

1. the first face of the font's chain that is installed (GetTextFaceW gives back the asked-for name) and
   whose character map (its 'cmap' table, read with GetFontData, format 4 or 12) has every character of
   the letter (joiners, variation selectors and tag characters are not needed);
2. CreateFontW(-em, weight, ANTIALIASED_QUALITY) of that face, the letter drawn white on black with
   TextOutW at x = pad, y = baseline - tmAscent in a 32-bit top-down DIB of the cell's height;
3. the coverage is the green channel; the letter's box is from min(pad, first inked column) to
   max(pad + advance, last inked column + 1), where the advance is GetTextExtentPoint32W's width;
4. none of the chain has it: the missing-letter box (an outline the height of a capital, half as wide).

The result is a white letter with that coverage as its alpha, the cell's height high, which the game tints
like its own letters.
"""
from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from functools import lru_cache

import vf1_picture_image as pi
import vf1_text

# The fallback chain after the font's own face (the owner's order, 2026-11-01), then other Windows script
# fonts, then Noto when installed.
FALLBACK_FACES = (
    "Segoe UI Historic", "Segoe UI Symbol", "Segoe UI Emoji",
    "Yu Gothic", "Microsoft YaHei", "Malgun Gothic",
    "Nirmala UI", "Ebrima",
    "Microsoft JhengHei", "Leelawadee UI", "Gadugi", "Myanmar Text", "Javanese Text", "Mongolian Baiti",
    "Microsoft Himalaya", "Microsoft Yi Baiti", "Microsoft New Tai Lue", "Microsoft Tai Le",
    "Microsoft PhagsPa", "Sylfaen", "Cambria Math",
    "Noto Sans", "Noto Sans Symbols", "Noto Sans Symbols 2", "Noto Sans CJK JP", "Noto Sans Math",
)
PAD_FACTOR = 1          # the drawing starts `height` pixels in, so overhangs on either side are kept


def not_needed(cp: int) -> bool:
    """Characters a face need not have for the letter to be drawn with it."""
    return cp in (0x200C, 0x200D) or 0xFE00 <= cp <= 0xFE0F or 0xE0000 <= cp <= 0xE01EF


# --------------------------------------------------------------------------- cmap
def cmap_covers(table: bytes) -> "callable":
    """A function cp -> bool from a TrueType 'cmap' table (Windows Unicode subtables 3/10 format 12, else
    3/1 format 4; also 0/x Unicode subtables)."""
    if len(table) < 4:
        return lambda cp: False
    _, count = struct.unpack_from(">HH", table, 0)
    best12 = best4 = None
    for i in range(count):
        at = 4 + 8 * i
        if at + 8 > len(table):
            break
        platform, encoding, offset = struct.unpack_from(">HHI", table, at)
        if offset + 2 > len(table):
            continue
        fmt = struct.unpack_from(">H", table, offset)[0]
        unicode_sub = platform == 0 or (platform == 3 and encoding in (1, 10))
        if not unicode_sub:
            continue
        if fmt == 12 and best12 is None:
            best12 = offset
        elif fmt == 4 and best4 is None:
            best4 = offset
    if best12 is not None:
        o = best12
        n = struct.unpack_from(">I", table, o + 12)[0]
        groups = [struct.unpack_from(">III", table, o + 16 + 12 * k) for k in range(n)
                  if o + 16 + 12 * k + 12 <= len(table)]
        ranges = [(a, b) for a, b, g in groups]
        return lambda cp: any(a <= cp <= b for a, b in ranges)
    if best4 is not None:
        o = best4
        segx2 = struct.unpack_from(">H", table, o + 6)[0]
        seg = segx2 // 2
        ends = struct.unpack_from(f">{seg}H", table, o + 14)
        starts = struct.unpack_from(f">{seg}H", table, o + 16 + segx2)
        deltas = struct.unpack_from(f">{seg}h", table, o + 16 + 2 * segx2)
        roff_at = o + 16 + 3 * segx2
        roffs = struct.unpack_from(f">{seg}H", table, roff_at)

        def covers(cp: int) -> bool:
            if cp > 0xFFFF:
                return False
            for k in range(seg):
                if cp <= ends[k]:
                    if cp < starts[k]:
                        return False
                    if roffs[k] == 0:
                        gid = (cp + deltas[k]) & 0xFFFF
                    else:
                        at = roff_at + 2 * k + roffs[k] + 2 * (cp - starts[k])
                        if at + 2 > len(table):
                            return False
                        gid = struct.unpack_from(">H", table, at)[0]
                        if gid:
                            gid = (gid + deltas[k]) & 0xFFFF
                    return gid != 0
            return False
        return covers
    return lambda cp: False


# --------------------------------------------------------------------------- GDI
AVAILABLE = sys.platform == "win32"

if AVAILABLE:
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class TEXTMETRICW(ctypes.Structure):
        _fields_ = [("tmHeight", wintypes.LONG), ("tmAscent", wintypes.LONG), ("tmDescent", wintypes.LONG),
                    ("tmInternalLeading", wintypes.LONG), ("tmExternalLeading", wintypes.LONG),
                    ("tmAveCharWidth", wintypes.LONG), ("tmMaxCharWidth", wintypes.LONG),
                    ("tmWeight", wintypes.LONG), ("tmOverhang", wintypes.LONG),
                    ("tmDigitizedAspectX", wintypes.LONG), ("tmDigitizedAspectY", wintypes.LONG),
                    ("tmFirstChar", wintypes.WCHAR), ("tmLastChar", wintypes.WCHAR),
                    ("tmDefaultChar", wintypes.WCHAR), ("tmBreakChar", wintypes.WCHAR),
                    ("tmItalic", ctypes.c_byte), ("tmUnderlined", ctypes.c_byte), ("tmStruckOut", ctypes.c_byte),
                    ("tmPitchAndFamily", ctypes.c_byte), ("tmCharSet", ctypes.c_byte)]

    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetTextFaceW.argtypes = [wintypes.HDC, ctypes.c_int, wintypes.LPWSTR]
    gdi32.GetFontData.restype = wintypes.DWORD
    gdi32.GetFontData.argtypes = [wintypes.HDC, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    gdi32.GetTextMetricsW.argtypes = [wintypes.HDC, ctypes.POINTER(TEXTMETRICW)]
    gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.SIZE)]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
    gdi32.GdiFlush.restype = wintypes.BOOL

CMAP_TAG = 0x70616D63    # 'cmap' as GetFontData wants it


def _utf16(text: str) -> str:
    return text      # ctypes passes Python str as UTF-16, surrogate pairs included


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class _Face:
    def __init__(self, dc, face: str, em: int, weight: int):
        self.font = gdi32.CreateFontW(-em, 0, 0, 0, weight, 0, 0, 0, 1, 7, 0, 4, 0, face)
        self.ok = False
        self.covers = lambda cp: False
        if not self.font:
            return
        old = gdi32.SelectObject(dc, self.font)
        buf = ctypes.create_unicode_buffer(64)
        gdi32.GetTextFaceW(dc, 64, buf)
        if buf.value.casefold() == face.casefold():
            size = gdi32.GetFontData(dc, CMAP_TAG, 0, None, 0)
            if size not in (0, 0xFFFFFFFF) and size < 0x1000000:
                data = ctypes.create_string_buffer(size)
                if gdi32.GetFontData(dc, CMAP_TAG, 0, data, size) == size:
                    self.covers = cmap_covers(data.raw)
                    self.ok = True
        gdi32.SelectObject(dc, old)


class Renderer:
    """Draws letters for one font style: a face chain, a weight, an em size in pixels, a baseline row and
    the cell's height (all from the font's own sheet; vf1_game_fonts.STYLES)."""

    def __init__(self, face: str, weight: int, em: int, baseline: int, height: int,
                 fallbacks: tuple[str, ...] = FALLBACK_FACES):
        self.faces = (face,) + tuple(f for f in fallbacks if f != face)
        self.weight, self.em, self.baseline, self.height = int(weight), int(em), int(baseline), int(height)
        self._dc = None
        self._loaded: dict[str, "_Face"] = {}

    def _face(self, name: str):
        if self._dc is None:
            self._dc = gdi32.CreateCompatibleDC(None)
        if name not in self._loaded:
            self._loaded[name] = _Face(self._dc, name, self.em, self.weight)
        return self._loaded[name]

    def face_for(self, letter: str) -> str | None:
        """The first face of the chain that has every needed character of `letter`."""
        if not AVAILABLE:
            return None
        needed = [ord(c) for c in letter if not not_needed(ord(c))]
        for name in self.faces:
            face = self._face(name)
            if face.ok and all(face.covers(cp) for cp in needed):
                return name
        return None

    def draw(self, letter: str) -> tuple[pi.Image, str]:
        """(white letter with coverage alpha, the face's name or "" for the missing-letter box)."""
        name = self.face_for(letter)
        if name is None:
            return missing_box(self.height, self.baseline, self.em), ""
        face = self._face(name)
        dc = self._dc
        pad = self.height * PAD_FACTOR
        size = wintypes.SIZE()
        old = gdi32.SelectObject(dc, face.font)
        units = _units(letter)
        gdi32.GetTextExtentPoint32W(dc, letter, units, ctypes.byref(size))
        tm = TEXTMETRICW()
        gdi32.GetTextMetricsW(dc, ctypes.byref(tm))
        advance = int(size.cx)
        width = advance + 2 * pad
        h = self.height
        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        try:
            old_bmp = gdi32.SelectObject(dc, bmp)
            ctypes.memset(bits, 0, width * h * 4)
            gdi32.SetBkMode(dc, 1)                   # TRANSPARENT
            gdi32.SetTextColor(dc, 0x00FFFFFF)
            gdi32.TextOutW(dc, pad, self.baseline - tm.tmAscent, letter, units)
            gdi32.GdiFlush()
            raw = ctypes.string_at(bits, width * h * 4)
            gdi32.SelectObject(dc, old_bmp)
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.SelectObject(dc, old)
        green = raw[1::4]
        first, last = width, -1
        for x in range(width):
            if any(green[y * width + x] for y in range(h)):
                first = min(first, x)
                last = x
        left = min(pad, first) if last >= 0 else pad
        right = max(pad + advance, last + 1) if last >= 0 else pad + advance
        w = right - left
        out = pi.Image(w, h)
        for y in range(h):
            for x in range(w):
                a = green[y * width + left + x]
                if a:
                    at = (y * w + x) * 4
                    out.data[at:at + 4] = bytes((255, 255, 255, a))
        return out, name

    def extent(self, text: str, face: str | None = None) -> int:
        """GetTextExtentPoint32W's width of `text` in `face` (the renderer's own by default); 0 when the face is not
        installed."""
        if not AVAILABLE:
            return 0
        f = self._face(face or self.faces[0])
        if not f.ok:
            return 0
        old = gdi32.SelectObject(self._dc, f.font)
        size = wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(self._dc, text, _units(text), ctypes.byref(size))
        gdi32.SelectObject(self._dc, old)
        return int(size.cx)

    def close(self) -> None:
        for face in self._loaded.values():
            if face.font:
                gdi32.DeleteObject(face.font)
        self._loaded.clear()
        if self._dc:
            gdi32.DeleteDC(self._dc)
            self._dc = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def missing_box(height: int, baseline: int, em: int) -> pi.Image:
    """The missing-letter box: a 1-pixel outline from the cap height to the baseline, half the em wide, with
    one blank column each side (the same as vf1text.dll's MissingBox)."""
    cap = max(3, (em * 7) // 10)
    inner = max(3, em // 2)
    w = inner + 2
    out = pi.Image(w, height)
    top = max(0, baseline - cap)
    bottom = max(top + 2, min(height, baseline)) - 1
    for y in range(top, bottom + 1):
        for x in range(1, w - 1):
            if y in (top, bottom) or x in (1, w - 2):
                at = (y * w + x) * 4
                out.data[at:at + 4] = b"\xff\xff\xff\xff"
    return out


@lru_cache(maxsize=None)
def renderer(face: str, weight: int, em: int, baseline: int, height: int,
             fallbacks: tuple = FALLBACK_FACES) -> Renderer:
    return Renderer(face, weight, em, baseline, height, fallbacks)


# Use Unicode Font: the chosen font, then Segoe UI, then the chain (vf1font.dll's ChooseFace).
UNICODE_FONT_FALLBACKS = ("Segoe UI",) + FALLBACK_FACES
_private: set[str] = set()


def add_private_font(path) -> bool:
    """A .ttf / .otf file made usable by this process only (AddFontResourceExW, FR_PRIVATE), as vf1font.dll does in
    the game."""
    if not AVAILABLE:
        return False
    key = str(path)
    if key in _private:
        return True
    gdi32.AddFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    if gdi32.AddFontResourceExW(key, 0x10, None) > 0:
        _private.add(key)
        return True
    return False


def font_file_family(data: bytes) -> str | None:
    """The name Windows knows a TrueType or OpenType font file's family by (name ID 1, Windows English first), or
    None. A collection (.ttc) gives its first font's."""
    try:
        base = 0
        if data[:4] == b"ttcf":
            base = struct.unpack_from(">I", data, 12)[0]
        count = struct.unpack_from(">H", data, base + 4)[0]
        name_at = None
        for i in range(count):
            tag, _sum, offset, _length = struct.unpack_from(">4sIII", data, base + 12 + 16 * i)
            if tag == b"name":
                name_at = offset
        if name_at is None:
            return None
        _fmt, n, strings = struct.unpack_from(">HHH", data, name_at)
        found: dict[tuple, str] = {}
        for i in range(n):
            platform, _encoding, language, name_id, length, offset = struct.unpack_from(
                ">6H", data, name_at + 6 + 12 * i)
            if name_id != 1:
                continue
            raw = data[name_at + strings + offset:name_at + strings + offset + length]
            if platform in (0, 3):
                text = raw.decode("utf-16-be", errors="replace")
            elif platform == 1:
                text = raw.decode("mac_roman", errors="replace")
            else:
                continue
            found[(platform == 3 and language == 0x409, platform == 3, -i)] = text
        return found[max(found)] if found else None
    except (struct.error, IndexError):
        return None


def letters(text: str) -> list[str]:
    return vf1_text.clusters(text)
