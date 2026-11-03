"""Line breaking for every script: the game's justified word wrapper, and where Render Unicode with In-Game Fonts /
Use Unicode Font let it break a line (native/vf1text/wrap.inc is the same rule in C; tests/test_line_break.py runs the
real DLL and the stock code on the real executable in the emulator and compares them with this module).

The stock wrapper (0x409D70) cuts text into "words" -- a run of bytes up to a space or a line break, or just after a
"." not followed by another ".", a "," not followed by a digit, or a "?" -- and fills each line with whole words,
justified. Text in a script written without spaces (Japanese, Chinese, Korean syllables, Thai, Lao, Khmer, Myanmar,
emoji) is one long word, so it never wrapped, and the stock code loops for ever on a word wider than the line.

With the patch a word may also be cut where the Unicode line-breaking rules (UAX #14, from Windows' own ICU,
icu.dll) allow it next to such a letter or the CJK punctuation; never inside a whole character (grapheme cluster)
and never after a space. Without icu.dll a small built-in table (FALLBACK_RANGES) gives the CJK basics. A word's
pieces follow each other with no space; only the spaces between words are stretched. A piece wider than the whole
line is cut between whole characters. Text with none of these letters whose every word fits is laid out by the
game's own code, exactly as before.
"""
from __future__ import annotations

import ctypes
import struct
import sys

import vf1_text

JUSTIFY_RATIO_VA = 0x4B27B8      # the float the stock wrapper compares a line's fill with
MAX_WORDS = 100                  # the stock wrapper's arrays (0x409F38)

# --------------------------------------------------------------------------- the built-in table (linebreak.inc)
OTHER, IDEOGRAPHIC, CLOSING, OPENING = 0, 1, 2, 3
_I, _C, _O = IDEOGRAPHIC, CLOSING, OPENING
FALLBACK_RANGES = (
    (0x0021, 0x0021, _C), (0x0028, 0x0028, _O), (0x0029, 0x0029, _C), (0x002C, 0x002C, _C), (0x002E, 0x002E, _C),
    (0x003A, 0x003B, _C), (0x003F, 0x003F, _C), (0x005B, 0x005B, _O), (0x005D, 0x005D, _C), (0x007B, 0x007B, _O),
    (0x007D, 0x007D, _C),
    (0x0E00, 0x0EFF, _I), (0x1000, 0x109F, _I), (0x1100, 0x115F, _I), (0x1780, 0x17FF, _I), (0x1950, 0x19DF, _I),
    (0x1A20, 0x1AAF, _I),
    (0x2018, 0x2018, _O), (0x2019, 0x2019, _C), (0x201C, 0x201C, _O), (0x201D, 0x201D, _C), (0x2E80, 0x2FFF, _I),
    (0x3000, 0x3000, _I), (0x3001, 0x3002, _C), (0x3003, 0x3004, _I), (0x3005, 0x3005, _C), (0x3006, 0x3007, _I),
    (0x3008, 0x3008, _O), (0x3009, 0x3009, _C), (0x300A, 0x300A, _O), (0x300B, 0x300B, _C), (0x300C, 0x300C, _O),
    (0x300D, 0x300D, _C), (0x300E, 0x300E, _O), (0x300F, 0x300F, _C), (0x3010, 0x3010, _O), (0x3011, 0x3011, _C),
    (0x3012, 0x3013, _I), (0x3014, 0x3014, _O), (0x3015, 0x3015, _C), (0x3016, 0x3016, _O), (0x3017, 0x3017, _C),
    (0x3018, 0x3018, _O), (0x3019, 0x3019, _C), (0x301A, 0x301A, _O), (0x301B, 0x301B, _C), (0x301C, 0x301C, _C),
    (0x301D, 0x301D, _O), (0x301E, 0x301F, _C), (0x3020, 0x303A, _I), (0x303B, 0x303C, _C), (0x303D, 0x3040, _I),
    (0x3041, 0x3041, _C), (0x3042, 0x3042, _I), (0x3043, 0x3043, _C), (0x3044, 0x3044, _I), (0x3045, 0x3045, _C),
    (0x3046, 0x3046, _I), (0x3047, 0x3047, _C), (0x3048, 0x3048, _I), (0x3049, 0x3049, _C), (0x304A, 0x3062, _I),
    (0x3063, 0x3063, _C), (0x3064, 0x3082, _I), (0x3083, 0x3083, _C), (0x3084, 0x3084, _I), (0x3085, 0x3085, _C),
    (0x3086, 0x3086, _I), (0x3087, 0x3087, _C), (0x3088, 0x308D, _I), (0x308E, 0x308E, _C), (0x308F, 0x3094, _I),
    (0x3095, 0x3096, _C), (0x3097, 0x309A, _I), (0x309B, 0x309E, _C), (0x309F, 0x30A0, _I), (0x30A1, 0x30A1, _C),
    (0x30A2, 0x30A2, _I), (0x30A3, 0x30A3, _C), (0x30A4, 0x30A4, _I), (0x30A5, 0x30A5, _C), (0x30A6, 0x30A6, _I),
    (0x30A7, 0x30A7, _C), (0x30A8, 0x30A8, _I), (0x30A9, 0x30A9, _C), (0x30AA, 0x30C2, _I), (0x30C3, 0x30C3, _C),
    (0x30C4, 0x30E2, _I), (0x30E3, 0x30E3, _C), (0x30E4, 0x30E4, _I), (0x30E5, 0x30E5, _C), (0x30E6, 0x30E6, _I),
    (0x30E7, 0x30E7, _C), (0x30E8, 0x30ED, _I), (0x30EE, 0x30EE, _C), (0x30EF, 0x30F4, _I), (0x30F5, 0x30F6, _C),
    (0x30F7, 0x30FA, _I), (0x30FB, 0x30FE, _C), (0x30FF, 0x31FF, _I), (0x3200, 0x4DBF, _I), (0x4E00, 0x9FFF, _I),
    (0xA000, 0xA4CF, _I), (0xA960, 0xA97F, _I), (0xAA60, 0xAADF, _I), (0xAC00, 0xD7FF, _I), (0xF900, 0xFAFF, _I),
    (0xFE30, 0xFE4F, _I),
    (0xFF01, 0xFF01, _C), (0xFF02, 0xFF07, _I), (0xFF08, 0xFF08, _O), (0xFF09, 0xFF09, _C), (0xFF0A, 0xFF0B, _I),
    (0xFF0C, 0xFF0C, _C), (0xFF0D, 0xFF0D, _I), (0xFF0E, 0xFF0E, _C), (0xFF0F, 0xFF19, _I), (0xFF1A, 0xFF1B, _C),
    (0xFF1C, 0xFF1E, _I), (0xFF1F, 0xFF1F, _C), (0xFF20, 0xFF3A, _I), (0xFF3B, 0xFF3B, _O), (0xFF3C, 0xFF3C, _I),
    (0xFF3D, 0xFF3D, _C), (0xFF3E, 0xFF5A, _I), (0xFF5B, 0xFF5B, _O), (0xFF5C, 0xFF5C, _I), (0xFF5D, 0xFF5D, _C),
    (0xFF5E, 0xFF60, _I), (0xFF61, 0xFF61, _C), (0xFF62, 0xFF62, _O), (0xFF63, 0xFF64, _C), (0xFF65, 0xFFEF, _I),
    (0x16FE0, 0x18AFF, _I), (0x1B000, 0x1B2FF, _I), (0x1F000, 0x1FAFF, _I), (0x20000, 0x3FFFD, _I),
)


def fallback_class(cp: int) -> int:
    for first, last, cls in FALLBACK_RANGES:
        if first <= cp <= last:
            return cls
    return OTHER


def fallback_may_break(before: int, after: int) -> bool:
    a, b = fallback_class(before), fallback_class(after)
    if b == CLOSING or a == OPENING:
        return False
    return a == IDEOGRAPHIC or b == IDEOGRAPHIC or (a == CLOSING and b == OPENING)


# --------------------------------------------------------------------------- Windows' ICU
_icu = None
_icu_looked = False
NO_SPACE_CLASSES = frozenset((14, 24, 31, 32, 33, 34, 35, 37, 40, 41))   # ID SA H2 H3 JL JT JV CJ EB EM


def icu():
    """icu.dll (Windows 10 1903 and later), or None."""
    global _icu, _icu_looked
    if not _icu_looked:
        _icu_looked = True
        if sys.platform == "win32":
            try:
                lib = ctypes.WinDLL("icu.dll")
                lib.ubrk_open.restype = ctypes.c_void_p
                lib.ubrk_open.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int,
                                          ctypes.POINTER(ctypes.c_int)]
                for name in ("ubrk_first", "ubrk_next"):
                    getattr(lib, name).argtypes = [ctypes.c_void_p]
                    getattr(lib, name).restype = ctypes.c_int
                lib.ubrk_close.argtypes = [ctypes.c_void_p]
                lib.u_getIntPropertyValue.argtypes = [ctypes.c_int, ctypes.c_int]
                lib.u_getIntPropertyValue.restype = ctypes.c_int
                _icu = lib
            except (OSError, AttributeError):
                _icu = None
    return _icu


def icu_boundaries(units: bytes) -> list[int]:
    """ubrk_open(UBRK_LINE, "") over UTF-16LE `units`: every boundary, in UTF-16 units."""
    lib = icu()
    n = len(units) // 2
    buf = ctypes.create_string_buffer(units + b"\0\0", len(units) + 2)    # ICU keeps the pointer: keep it alive
    status = ctypes.c_int(0)
    it = lib.ubrk_open(2, b"", buf, n, ctypes.byref(status))
    out = []
    try:
        if it and status.value <= 0:
            b = lib.ubrk_first(it)
            while 0 <= b <= n:
                out.append(b)
                b = lib.ubrk_next(it)
    finally:
        if it:
            lib.ubrk_close(it)
    return out


def line_break_class(cp: int) -> int | None:
    lib = icu()
    return lib.u_getIntPropertyValue(cp, 0x1008) if lib else None


def no_space_letter(cp: int, use_icu: bool = True) -> bool:
    """A letter of a script written without spaces (wrap.inc NoSpaceLetter)."""
    if 0x3000 <= cp <= 0x303F or 0xFE30 <= cp <= 0xFE4F or 0xFF00 <= cp <= 0xFFEF:
        return True
    if use_icu and icu() is not None:
        return line_break_class(cp) in NO_SPACE_CLASSES
    return fallback_class(cp) == IDEOGRAPHIC


def break_points(text: str, use_icu: bool = True) -> tuple[set[int], bool]:
    """(code point indices where a word may be cut, whether the text has a letter of a script written without
    spaces) -- wrap.inc BreaksFor."""
    cps = [ord(c) for c in text]
    if not any(no_space_letter(cp, use_icu) or cp == 0x200B for cp in cps):
        return set(), False
    allowed: set[int] | None = None
    if use_icu and icu() is not None:
        units = text.encode("utf-16-le", "surrogatepass")
        unit_cp = []
        for i, cp in enumerate(cps):
            unit_cp += [i, i] if cp >= 0x10000 else [i]
        unit_cp.append(len(cps))
        allowed = set()
        n = len(unit_cp) - 1
        for b in icu_boundaries(units):
            if b == 0 or b == n or unit_cp[b - 1] != unit_cp[b]:
                allowed.add(unit_cp[b])
    out: set[int] = set()
    i, prev = 0, -1
    for cluster in vf1_text.clusters(text, draw=True):
        if prev >= 0:
            before, after, last = cps[prev], cps[i], cps[i - 1]
            ok = (before not in (0x20, 0x0A) and after not in (0x20, 0x0A)
                  and (no_space_letter(before, use_icu) or no_space_letter(after, use_icu) or last == 0x200B))
            if ok:
                ok = (i in allowed) if allowed is not None else (last == 0x200B or fallback_may_break(before, after))
            if ok:
                out.add(i)
        prev = i
        i += len(cluster)
    return out, True


# --------------------------------------------------------------------------- the wrapper
def advance(font, text: str) -> int:
    """0x409450's measure: every letter's box width plus the spacing (the last letter's too)."""
    total = 0
    for letter in font.letters(text):
        if letter == "\n":
            continue
        g = font.glyph(letter)
        if g.width:
            total += g.width + font.spacing
    return total


def _word_end(s: str, at: int) -> int:
    n = len(s)
    while at < n and s[at] == " ":
        at += 1
    stop = False
    while at < n and not stop:
        c = s[at]
        if c in " \n":
            break
        at += 1
        nxt = s[at] if at < n else ""
        if c == ".":
            stop = nxt != "."
        elif c == ",":
            stop = not ("0" <= nxt <= "9")
        elif c == "?":
            stop = True
    return at


def stock_words_fit(font, s: str, width: int) -> bool:
    """wrap.inc StockWordsFit: would the stock code lay this out (every word fits a line it starts)?"""
    at, n, line_start = 0, len(s), True
    while at < n:
        if s[at] == "\n":
            line_start = True
            at += 1
            continue
        spaces = at
        while at < n and s[at] == " ":
            at += 1
        if at >= n:
            break
        if s[at] == "\n":
            continue
        end = _word_end(s, at)
        if advance(font, s[at:end]) > width:
            return False
        if line_start and spaces < at and advance(font, s[spaces:end]) > width:
            return False
        line_start = False
        at = end
    return True


def _emergency(font, piece: str, room: int) -> int:
    used = best = 0
    for cluster in vf1_text.clusters(piece, draw=True):
        used += len(cluster)
        if best and advance(font, piece[:used]) > room:
            break
        best = used
    return best or len(piece)


def wrap(font, text: str, x: int, y: int, width: int, justify_ratio: float, *, measure: bool = False,
         use_icu: bool = True, patched: bool = True) -> tuple[int, list[tuple[str, int, int]]]:
    """The word wrapper 0x409D70 as the patched game runs it (patched=False: the stock code; it must then be able to
    lay the text out): (its return value, the height of the text; each piece drawn, (text, x, y))."""
    s = text
    n = len(s)
    if patched:
        breaks, any_letter = break_points(s, use_icu)
        if not any_letter and stock_words_fit(font, s, width):
            breaks = set()
    else:
        breaks = set()
    space = advance(font, " ")
    max_gap = int(space * 5 / 3) if space >= 0 else -int(-space * 5 / 3)
    height = font.height
    draws: list[tuple[str, int, int]] = []
    at = yoff = 0
    after_break = True
    ch = lambda k: s[k] if k < n else ""          # noqa: E731
    while True:
        if ch(at) == "\n":
            while ch(at) == "\n":
                yoff += height
                at += 1
                after_break = True
            if not ch(at):
                return yoff, draws
        if not after_break:
            while ch(at) == " ":
                at += 1
        if not ch(at):
            return yoff, draws
        line_w = count = gaps = extra = 0
        pieces: list[list] = []                    # [start, length, width, glued]
        while True:
            if not after_break and ch(at) == " ":
                at += 1
            after_break = False
            word_start, end = at, _word_end(s, at)
            full = False
            p = word_start
            while True:                            # a word may be empty (spaces at the text's end make one)
                q = p
                if p < end:
                    q = p + 1
                    while q < end and q not in breaks:
                        q += 1
                glued = p != word_start
                w = advance(font, s[p:q])
                if not glued and count > 0:
                    line_w += space
                    gaps += 1
                line_w += w
                pieces.append([p, q - p, w, glued])
                count += 1
                if line_w > width:
                    full = True
                    if line_w - width < gaps:
                        extra = -1
                        at = q
                        if ch(at) == "\n":
                            at += 1
                    elif count == 1:
                        keep = _emergency(font, s[p:q], width)
                        pieces[0][1] = keep
                        pieces[0][2] = advance(font, s[p:p + keep])
                        line_w = pieces[0][2]
                        at = p + keep
                    else:
                        pieces.pop()
                        count -= 1
                        line_w -= w
                        if not glued:
                            gaps -= 1
                        at = p
                    break
                p = q
                if p >= end:
                    break
                if line_w == width or count == MAX_WORDS:
                    full = True
                    at = p
                    break
            if full:
                break
            at = end
            if not ch(at) or line_w == width or count == MAX_WORDS:
                break
            if ch(at) == "\n":
                after_break = True
                at += 1
                break
        if not measure:
            free = gaps * space - line_w + width
            gap = int(free / gaps) if gaps else 0          # idiv truncates toward zero
            rem = free - gap * gaps
            justify = gaps != 0
            last_of_text = not ch(at) and at > 0 and s[at - 1] in ".?"
            if justify:
                fill = struct.unpack("<f", struct.pack("<f", line_w / width))[0] if width else float("inf")
                if gap > max_gap and fill < justify_ratio:
                    justify = False
                elif last_of_text:
                    justify = False
            if not justify:
                gap, rem = extra + space, 0
            left, xx, k, g = gaps, x, 0, 0
            while k < count:
                e, w = k + 1, pieces[k][2]
                while e < count and pieces[e][3]:
                    w += pieces[e][2]
                    e += 1
                if justify and g == gaps:
                    xx = x - w + width
                start = pieces[k][0]
                stop = pieces[e - 1][0] + pieces[e - 1][1]
                draws.append((s[start:stop], xx, y + yoff))
                xx += w + gap
                if left <= rem:
                    xx += 1
                left -= 1
                k, g = e, g + 1
        yoff += height


def justify_ratio(exe_data: bytes) -> float:
    """The float at 0x4B27B8 of the game's executable."""
    import vf1_game_fonts as gf
    return struct.unpack("<f", gf._Exe(exe_data).read(JUSTIFY_RATIO_VA, 4))[0]
