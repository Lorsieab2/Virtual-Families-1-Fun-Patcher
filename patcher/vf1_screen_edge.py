"""Nothing runs off the screen (the owner, 2026-11-03: "i dont care if things run out of boxes, they just need to not
run off the screen"): the patched game's rule (native/vf1text/screen.inc, native/vf1tr/screen_tr.inc), the model the
tests compare the DLLs with, and the translation editor's check (vf1_translations_window).

At run time a text the game draws (DrawString 0x409660: every left, right-aligned and centred draw and every text box
ends there) or wraps (0x409D70) that would leave the screen, but is partly on it, is moved so that it ends at the
screen's edge; one wider than the screen is cut, each line, to its longest start of whole characters and "…"; one
taller keeps the lines that fit, the last ending in "…". Only text the patches or a translation bring is touched:
text with a letter beyond ASCII, or any text while a translation is chosen.

The editor measures a translation with the game's own font, the letters the patcher makes and the ones Windows draws
included (vf1_game_fonts), and warns when a line is wider than the screen; "Wrap to fit" breaks such lines.
"""
from __future__ import annotations

import vf1_text

SCREEN_W, SCREEN_H = 800, 600          # the game's screen (0x423750 answers 800)
ELLIPSIS = "…"


def _advance(font, piece: str) -> int:
    return font.glyph(piece).width + font.spacing


def fit_to_room(font, text: str, room: int) -> str:
    """names.inc FitToRoom: `text` (one line) when no wider than `room`, else its longest start of whole characters,
    trailing spaces dropped, then "…"; "" when not even "…" fits."""
    if font.width(text) <= room:
        return text
    import vf1_shaping
    parts = vf1_text.clusters(text, draw=True)
    ell = _advance(font, ELLIPSIS)
    if ell - font.spacing > room:
        return ""
    if any(vf1_shaping.script_group(ord(c)) for c in text):
        ends, at = [], 0
        for p in parts:
            at += len(p)
            ends.append(at)
        lo, hi = 0, len(ends)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.width(text[:ends[mid - 1]].rstrip(" ") + ELLIPSIS) <= room:
                lo = mid
            else:
                hi = mid - 1
        return (text[:ends[lo - 1]] if lo else "").rstrip(" ") + ELLIPSIS
    width = used = keep = 0
    for p in parts:
        w = width + _advance(font, p)
        space = p == " "
        if not space and w + ell - font.spacing > room:
            break
        width = w
        used += len(p)
        if not space:
            keep = used
    return text[:keep] + ELLIPSIS


def cut_lines(font, text: str, room: int, max_lines: int) -> str:
    """screen.inc CutLines: every line fitted to `room`, at most `max_lines`, the last kept one ending in "…" when
    lines were dropped."""
    lines = text.split("\n")
    out = []
    for k, line in enumerate(lines[:max_lines]):
        if k + 1 == max_lines and len(lines) > max_lines:
            line += ELLIPSIS
        out.append(fit_to_room(font, line, room))
    return "\n".join(out)


def clamp_wanted(text: str, translation: bool) -> bool:
    return translation or any(ord(c) >= 0x80 for c in text)


def on_screen(font, text: str, x: int, y: int, *, translation: bool = False, screen=(SCREEN_W, SCREEN_H)):
    """screen.inc OnScreen: (text, x, y) DrawString draws."""
    sw, sh = screen
    if not text or not clamp_wanted(text, translation):
        return text, x, y
    width = font.width(text)
    lines = text.count("\n") + 1
    h = lines * font.height
    if x >= 0 and x + width <= sw and y >= 0 and y + h <= sh:
        return text, x, y
    if x >= sw or x + width <= 0 or y >= sh or y + h <= 0:
        return text, x, y
    fit = max(1, sh // font.height) if font.height > 0 else lines
    if width > sw or lines > fit:
        text = cut_lines(font, text, sw, fit)
        width = font.width(text)
        h = (text.count("\n") + 1) * font.height
    x = 0 if (x < 0 or width > sw) else (sw - width if x + width > sw else x)
    y = 0 if (y < 0 or h > sh) else (sh - h if y + h > sh else y)
    return text, x, y


def box_on_screen(x: int, y: int, width: int, height: int, *, screen=(SCREEN_W, SCREEN_H)) -> tuple[int, int]:
    """screen.inc WrapOnScreen: where the word wrapper's box goes (its text is wrapped inside it)."""
    sw, sh = screen
    if x >= 0 and x + width <= sw and y >= 0 and y + height <= sh:
        return x, y
    if x >= sw or x + width <= 0 or y >= sh or y + height <= 0:
        return x, y
    x = 0 if (x < 0 or width > sw) else (sw - width if x + width > sw else x)
    y = 0 if (y < 0 or height > sh) else (sh - height if y + height > sh else y)
    return x, y


# --------------------------------------------------------------------------- the translation editor's check
def too_wide(fonts, text: str, screen_w: int = SCREEN_W) -> list[tuple[str, int, str]]:
    """The lines of `text` wider than the screen in a font the game draws text with: (line, its width in pixels,
    the font). Measured with the game's own letters, the patcher-made ones and the ones Windows draws."""
    out = []
    for line in text.split("\n"):
        widest = max(((fonts.font(name).width(line), name) for name in DRAWN_FONTS), default=(0, ""))
        if widest[0] > screen_w:
            out.append((line, widest[0], widest[1]))
    return out


DRAWN_FONTS = ("SegoeUiBold18", "SegoeUiBold17", "SegoeUiBold24")   # SegoeUi33 is never drawn (test_font_slots)


def wrap_to_fit(fonts, text: str, screen_w: int = SCREEN_W) -> str:
    """Wrap to fit: each line wider than the screen in the widest drawn font is broken at its last space that fits
    (in a script written without spaces, between whole characters where a line may break), never inside a
    character."""
    import vf1_line_break as lb
    out = []
    for line in text.split("\n"):
        def width(s: str) -> int:
            return max(fonts.font(name).width(s) for name in DRAWN_FONTS)
        while width(line) > screen_w:
            breaks, _ = lb.break_points(line)
            cuts = sorted({i for i, c in enumerate(line) if c == " " and i > 0} | breaks)
            fitting = [c for c in cuts if width(line[:c].rstrip(" ")) <= screen_w]
            if not fitting:
                head = ""
                for cluster in vf1_text.clusters(line):
                    if head and width(head + cluster) > screen_w:
                        break
                    head += cluster
                cut = len(head)
            else:
                cut = fitting[-1]
            out.append(line[:cut].rstrip(" "))
            line = line[cut:].lstrip(" ")
        out.append(line)
    return "\n".join(out)
