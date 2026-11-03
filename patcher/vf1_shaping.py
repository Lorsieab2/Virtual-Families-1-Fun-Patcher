"""Right-to-left and shaped scripts: which stretches of a text the game draws as one shaped run (Render Unicode with
In-Game Fonts, Use Unicode Font, the Game Text tool; native/vf1text/shape.inc is the same rule in C, and
tests/test_shaping.py proves the two equal).

Arabic, Hebrew, Syriac, Thaana, the Indic scripts, Thai, Lao, Tibetan, Myanmar, Khmer and the other scripts whose
letters change shape with their neighbours or run right to left were drawn one whole character at a time, each in its
isolated form and in logical order. Now a run of such letters -- with the spaces, digits and punctuation between them
-- is drawn as one picture by GDI's TextOutW of the whole run, which shapes it (Uniscribe) and lays it out in visual
order (the bidi algorithm, left-to-right base), as Windows draws it in its own windows. A run is at most MAX_RUN
whole characters (the DLLs' pages are 1024 pixels wide); a longer one is cut there, at a space when there is one.
"""
from __future__ import annotations

import vf1_text

__all__ = ["COMPLEX_RANGES", "MAX_RUN", "is_complex", "is_run_neutral", "pieces", "has_glued_space"]

# sorted, not overlapping (shape.inc ComplexRanges)
COMPLEX_RANGES: tuple[tuple[int, int], ...] = (
    (0x0590, 0x08FF), (0x0900, 0x0DFF), (0x0E00, 0x0EFF), (0x0F00, 0x0FFF), (0x1000, 0x109F), (0x1780, 0x17FF),
    (0x1800, 0x18AF), (0x1900, 0x194F), (0x1980, 0x19DF), (0x1A00, 0x1AAF), (0x1B00, 0x1BBF), (0x1C00, 0x1C4F),
    (0xA800, 0xA82F), (0xA880, 0xA8DF), (0xA8E0, 0xA8FF), (0xA900, 0xA95F), (0xA980, 0xA9DF), (0xAA00, 0xAADF),
    (0xABC0, 0xABFF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF), (0x10800, 0x10FFF), (0x11000, 0x11FFF), (0x1E800, 0x1EFFF),
)
MAX_RUN = 32


def is_complex(cp: int) -> bool:
    lo, hi = 0, len(COMPLEX_RANGES) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b = COMPLEX_RANGES[mid]
        if cp < a:
            hi = mid - 1
        elif cp > b:
            lo = mid + 1
        else:
            return True
    return False


def is_run_neutral(cp: int) -> bool:
    """A character that belongs to the run around it: a space, a digit, ASCII and Latin-1 punctuation, general
    punctuation."""
    return (cp == 0x20 or 0x21 <= cp <= 0x40 or 0x5B <= cp <= 0x60 or 0x7B <= cp <= 0x7E or 0xA0 <= cp <= 0xBF
            or 0x2000 <= cp <= 0x206F)


def pieces(text: str) -> list[str]:
    """`text` as the pieces the patched game draws one by one: a shaped run, or one whole character
    (shape.inc PieceEnd over vf1_text.clusters)."""
    clusters = vf1_text.clusters(text)
    out: list[str] = []
    i = 0
    while i < len(clusters):
        first = ord(clusters[i][0])
        if not is_complex(first):
            out.append(clusters[i])
            i += 1
            continue
        count, end, last_space = 1, i + 1, -1
        k = i + 1
        while k < len(clusters) and count < MAX_RUN:
            cp = ord(clusters[k][0])
            if is_complex(cp):
                end = k + 1
            elif not is_run_neutral(cp):
                break
            elif cp == 0x20:
                last_space = k
            count += 1
            k += 1
        if count >= MAX_RUN and 0 < last_space < end:
            end = last_space
        out.append("".join(clusters[i:end]))
        i = end
    return out


def has_glued_space(text: str) -> bool:
    """Whether a run holds a space (the word wrapper must not cut there)."""
    return any(" " in p and len(p) > 1 and is_complex(ord(p[0])) for p in pieces(text))
