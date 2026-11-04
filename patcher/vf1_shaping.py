"""Shaped and right-to-left scripts: which stretches of a text the patched game draws as one shaped run (Render
Unicode with In-Game Fonts, Use Unicode Font and the Game Text tool; native/vf1text/shape.inc is the same rule in C,
and tests/test_shaping.py proves the two equal on the real executable).

Arabic, Hebrew, Syriac, Thaana, the Indic scripts, Thai, Lao, Tibetan, Myanmar, Khmer, Mongolian and the other scripts
whose letters change shape with their neighbours or run right to left were drawn one whole character at a time, each
in its isolated form and in logical order. Now a RUN of such letters is drawn as one piece by GDI's TextOutW, which
shapes it (Uniscribe) and puts it in visual order (the bidi algorithm, left-to-right base), as Windows draws it in its
own windows. The Virtual Villagers patcher's rule: a run is letters of one script with their marks, and the spaces
between two of its words. A run is at most MAX_RUN_CLUSTERS whole characters and MAX_RUN_BYTES bytes of UTF-8 (a page
is 1024 pixels wide, a letter's key 384 bytes): a longer one is cut at its last space. A run no face of the chain has
every letter of is drawn a character at a time, as before. Text with no such letter is drawn exactly as before.
"""
from __future__ import annotations

from typing import Callable

import vf1_text

# (first, last, script group, right to left): shape.inc ComplexRanges, sorted, not overlapping
COMPLEX_RANGES: tuple[tuple[int, int, int, bool], ...] = (
    (0x0590, 0x05FF, 1, True), (0x0600, 0x08FF, 2, True), (0x0900, 0x097F, 3, False), (0x0980, 0x09FF, 4, False),
    (0x0A00, 0x0A7F, 5, False), (0x0A80, 0x0AFF, 6, False), (0x0B00, 0x0B7F, 7, False), (0x0B80, 0x0BFF, 8, False),
    (0x0C00, 0x0C7F, 9, False), (0x0C80, 0x0CFF, 10, False), (0x0D00, 0x0D7F, 11, False), (0x0D80, 0x0DFF, 12, False),
    (0x0E00, 0x0E7F, 13, False), (0x0E80, 0x0EFF, 14, False), (0x0F00, 0x0FFF, 15, False), (0x1000, 0x109F, 16, False),
    (0x1780, 0x17FF, 17, False), (0x1800, 0x18AF, 18, False), (0x1900, 0x194F, 19, False), (0x1980, 0x19DF, 20, False),
    (0x1A00, 0x1AAF, 21, False), (0x1B00, 0x1BBF, 22, False), (0x1BC0, 0x1BFF, 23, False), (0x1C00, 0x1C4F, 24, False),
    (0xA800, 0xA82F, 25, False), (0xA880, 0xA8DF, 26, False), (0xA8E0, 0xA8FF, 3, False), (0xA900, 0xA92F, 27, False),
    (0xA930, 0xA95F, 28, False), (0xA980, 0xA9DF, 29, False), (0xA9E0, 0xA9FF, 16, False), (0xAA00, 0xAA5F, 30, False),
    (0xAA60, 0xAA7F, 16, False), (0xAA80, 0xAADF, 31, False), (0xABC0, 0xABFF, 32, False), (0xFB1D, 0xFB4F, 1, True),
    (0xFB50, 0xFDFF, 2, True), (0xFE70, 0xFEFF, 2, True), (0x10800, 0x10FFF, 33, True), (0x11000, 0x11FFF, 34, False),
    (0x1E800, 0x1EFFF, 35, True),
)
MAX_RUN_CLUSTERS = 64
MAX_RUN_BYTES = 380
MAX_LETTER_UNITS = 190          # glyph_gdi.inc MaxLetterUnits: the code points of the longest letter drawn


def _range(cp: int):
    lo, hi = 0, len(COMPLEX_RANGES) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b, _g, _r = COMPLEX_RANGES[mid]
        if cp < a:
            hi = mid - 1
        elif cp > b:
            lo = mid + 1
        else:
            return COMPLEX_RANGES[mid]
    return None


def script_group(cp: int) -> int:
    r = _range(cp)
    return r[2] if r else 0


def is_rtl(cp: int) -> bool:
    r = _range(cp)
    return bool(r and r[3])


def _utf8(s: str) -> int:
    return len(s.encode("utf-8", "surrogatepass"))


def run_end(text: str, starts: list[int], ends: dict[int, int], i: int) -> int:
    """shape.inc RunEnd: the end (code point index) of the shaped run starting at i, or 0 when it is one character."""
    group = script_group(ord(text[i]))
    if not group:
        return 0
    n = len(text)
    first = ends[i]
    end, clusters, last_space, size, capped = first, 1, -1, _utf8(text[i:first]), False
    k = end
    while k < n:
        if script_group(ord(text[k])) == group:
            e = ends[k]
            add = _utf8(text[k:e])
            if clusters >= MAX_RUN_CLUSTERS or size + add > MAX_RUN_BYTES or e - i > MAX_LETTER_UNITS:
                capped = True
                break
            end = k = e
            size += add
            clusters += 1
            continue
        if text[k] != " ":
            break
        q = k
        while q < n and text[q] == " ":
            q += 1
        if q >= n or script_group(ord(text[q])) != group:
            break
        if clusters + (q - k) >= MAX_RUN_CLUSTERS or size + (q - k) > MAX_RUN_BYTES:
            capped = True
            break
        last_space = k
        clusters += q - k
        size += q - k
        k = q
    if capped and last_space > i:
        end = last_space
    return end if end > first else 0


def pieces(text: str, covered: Callable[[str], bool] | None = None) -> list[str]:
    """`text` as the pieces the patched game draws one at a time (shape.inc PieceEnd): a shaped run that a face of
    the chain has every letter of (covered(run)), else one whole character (vf1_text.clusters(draw=True))."""
    parts = vf1_text.clusters(text, draw=True)
    starts, at = [], 0
    for p in parts:
        starts.append(at)
        at += len(p)
    ends = {s: s + len(p) for s, p in zip(starts, parts)}
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        j = ends[i]
        end = run_end(text, starts, ends, i)
        if end and covered is not None and covered(text[i:end]):
            j = end
        out.append(text[i:j])
        i = j
    return out


def has_rtl_phrase(text: str) -> bool:
    """shape.inc HasRtlPhrase: a right-to-left run with a space inside (the word wrapper keeps it together)."""
    n = len(text)
    for i, c in enumerate(text):
        if c == " " and i > 0 and is_rtl(ord(text[i - 1])):
            q = i
            while q < n and text[q] == " ":
                q += 1
            if q < n and script_group(ord(text[q])) == script_group(ord(text[i - 1])):
                return True
    return False
