"""Makes the letters Virtual Families 1's fonts lack, in each font's own style (Render Unicode with In-Game
Fonts, and the Game Text tool's "(patcher-made)" letters).

scripts/build_vf1_glyphs.py runs this over the four game fonts and writes payload\\UnicodeText\\<font>.png and
<font>.txt, which the patch installs beside the game and vf1text.dll loads (nothing of the game's own art is
changed). The tool makes the same letters for the unused font sheets when it needs them.

How a letter is made, best first:

1. The same shape the game already has: a Greek or Cyrillic letter that looks exactly like a Latin one
   (Α A, Ο O, а a, р p ...) is the game's own letter; µ (U+03BC) is the game's µ.
2. Composed from the game's own pixels: a letter with accents (its Unicode decomposition: a base and
   marks) is the game's own base letter plus each mark. A mark the game has (grave, acute, circumflex,
   tilde, diaeresis, ring above and cedilla, from è é ê ñ ë å ç and the capitals) is cut out of the game's
   own accented letter; the caron is the game's circumflex turned upside down; the macron is the game's
   own "¯"; the dot above is one dot of the game's "¨". Any other mark is cut from the same letter drawn by
   Windows in the font's face and size. Each mark keeps its gap to the letter and its place across it
   (centred, or at the foot for an ogonek), as on the letter it came from, and uses the capital's flatter
   form over capitals and tall letters. Over i and j the dot is taken off first (ı and ȷ are made that
   way too).
3. Drawn by Windows in the font's face, weight and size, its coverage mapped to the sheet's (the "lut",
   fitted to the game's own letters), on the game's baseline (vf1_glyph_gdi).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import vf1_picture_image as pi

# Mark -> (lowercase donor base, lowercase donor letter, capital donor base, capital donor letter).
GAME_MARKS = {
    0x0300: ("e", "è", "E", "È"),
    0x0301: ("e", "é", "E", "É"),
    0x0302: ("e", "ê", "E", "Ê"),
    0x0303: ("n", "ñ", "N", "Ñ"),
    0x0308: ("e", "ë", "E", "Ë"),
    0x030A: ("a", "å", "A", "Å"),
    0x0327: ("c", "ç", "C", "Ç"),
}
CARON, MACRON, DOT_ABOVE = 0x030C, 0x0304, 0x0307
BELOW_MARKS = {0x0316, 0x0317, 0x0318, 0x0319, 0x031C, 0x031D, 0x031E, 0x031F, 0x0320, 0x0323, 0x0324,
               0x0325, 0x0326, 0x0327, 0x0328, 0x0329, 0x032A, 0x032B, 0x032C, 0x032D, 0x032E, 0x032F,
               0x0330, 0x0331, 0x0332, 0x0333, 0x0339, 0x033A, 0x033B, 0x033C, 0x0345}
# Letters drawn exactly like a Latin (or Latin-1) letter the game has.
HOMOGLYPHS = {
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "ο": "o", "μ": "µ",
    "Ѕ": "S", "І": "I", "Ј": "J", "А": "A", "В": "B", "Е": "E", "К": "K",
    "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "ѕ": "s", "і": "i", "ј": "j", "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "Ϊ": "Ï", "ї": "ï",
    "‐": "-", "‑": "-", "‒": "-", " ": " ", " ": " ", " ": " ",
}
DOTLESS = {"ı": "i", "ȷ": "j"}
# Letters whose mark is not the plain mark of their decomposition: the caron as an apostrophe beside ď ľ ť
# Ľ, and the Latvian comma (decomposed as a cedilla) under or over ģ ķ ļ ņ ŗ; Windows draws them whole.
DRAWN_WHOLE = frozenset("ďľťĽĢģĶķĻļŅņŖŗ")

# The letters shipped for every game font (each made only when the font's face draws it): the
# Windows-1252 letters the game lacks, Latin, IPA, Greek, Cyrillic, Vietnamese, punctuation, currency,
# letter-like symbols, numbers, arrows, maths, shapes, symbols and dingbats.
SHIPPED_RANGES = (
    (0x00A0, 0x00A1), (0x0100, 0x024F), (0x0250, 0x02AF), (0x02B0, 0x02FF), (0x0370, 0x03FF),
    (0x0400, 0x052F), (0x1E00, 0x1EFF), (0x1F00, 0x1FFF), (0x2000, 0x206F), (0x2070, 0x209F),
    (0x20A0, 0x20C0), (0x2100, 0x214F), (0x2150, 0x218F), (0x2190, 0x21FF), (0x2200, 0x22FF),
    (0x2460, 0x24FF), (0x2500, 0x259F), (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF),
    (0xFB00, 0xFB06),
)


def shipped_letters() -> list[str]:
    out = []
    for a, b in SHIPPED_RANGES:
        for cp in range(a, b + 1):
            ch = chr(cp)
            cat = unicodedata.category(ch)
            if cat in ("Cn", "Cc", "Cs", "Co", "Mn", "Me", "Mc", "Zl", "Zp") or cat == "Cf":
                continue
            out.append(ch)
    return out


@dataclass
class Made:
    image: pi.Image
    how: str          # "game shape", "composed", "drawn"


def _alpha(img: pi.Image) -> list[list[int]]:
    w = img.width
    a = img.data[3::4]
    return [list(a[y * w:(y + 1) * w]) for y in range(img.height)]


def _ink_box(rows: list[list[int]]):
    ys = [y for y, row in enumerate(rows) if any(row)]
    if not ys:
        return None
    xs = [x for x in range(len(rows[0])) if any(rows[y][x] for y in range(len(rows)))]
    return xs[0], ys[0], xs[-1] + 1, ys[-1] + 1


def _from_rows(rows: list[list[int]]) -> pi.Image:
    h = len(rows)
    w = len(rows[0]) if h else 0
    out = pi.Image(w, h)
    for y in range(h):
        for x in range(w):
            a = rows[y][x]
            if a:
                at = (y * w + x) * 4
                out.data[at:at + 4] = bytes((255, 255, 255, a))
    return out


class Mark:
    """A mark's pixels and where it sat on the letter it came from."""

    def __init__(self, pixels: list[list[int]], box, base_box, below: bool):
        self.pixels = pixels           # rows of alpha, the mark's own box
        self.box = box                 # (l, t, r, b) on its letter
        self.base_box = base_box       # that letter's base ink box
        self.below = below

    def flipped(self) -> "Mark":
        l, t, r, b = self.box
        return Mark(list(reversed(self.pixels)), self.box, self.base_box, self.below)


def cut_mark(base: pi.Image, letter: pi.Image, below: bool) -> Mark | None:
    """The pixels of `letter` above (or below) the ink of `base`."""
    br, lr = _alpha(base), _alpha(letter)
    bb = _ink_box(br)
    if bb is None or len(lr) != len(br):
        return None
    h, w = len(lr), len(lr[0])
    keep = [[0] * w for _ in range(h)]
    for y in range(h):
        if (not below and y < bb[1]) or (below and y >= bb[3]):
            keep[y] = list(lr[y])
    mb = _ink_box(keep)
    if mb is None:
        return None
    l, t, r, b = mb
    pixels = [row[l:r] for row in keep[t:b]]
    # the letter's own base box (the letter may sit at another x than the bare base)
    rest = [[lr[y][x] if (bb[1] <= y < bb[3]) else 0 for x in range(w)] for y in range(h)]
    lb = _ink_box(rest) or bb
    return Mark(pixels, mb, lb, below)


def place(base: pi.Image, mark: Mark, *, extra_gap: int = 0) -> pi.Image:
    """`mark` put on `base` with the same gap and the same place across the letter as where it came from."""
    rows = _alpha(base)
    bb = _ink_box(rows)
    if bb is None:
        return base.copy()
    h, w = len(rows), len(rows[0])
    ml, mt, mr, mbot = mark.box
    dl, dt, dr, db = mark.base_box
    mw, mh = mr - ml, mbot - mt
    dwid = max(1, dr - dl)
    frac = ((ml + mr) / 2 - dl) / dwid
    centre = bb[0] + frac * (bb[2] - bb[0])
    x0 = int(round(centre - mw / 2))
    if mark.below:
        gap = mt - db
        y0 = bb[3] + gap
        y0 = min(y0, h - mh)
        if y0 < bb[3] and gap >= 0:
            return None          # no room under the letter in this font's cell
    else:
        gap = dt - mbot + extra_gap
        y0 = bb[1] - gap - mh
        y0 = max(0, y0)
        if y0 + mh > bb[1] and gap >= 0:
            return None          # no room over the letter (a second mark over a capital)
    # widen the letter's box when the mark passes its edges
    left_pad = max(0, -x0)
    right_pad = max(0, x0 + mw - w)
    nw = w + left_pad + right_pad
    out = [[0] * left_pad + list(r) + [0] * right_pad for r in rows]
    x0 += left_pad
    for y in range(mh):
        ty = y0 + y
        if not 0 <= ty < h:
            continue
        for x in range(mw):
            a = mark.pixels[y][x]
            if a:
                tx = x0 + x
                out[ty][tx] = max(out[ty][tx], a)
    _ = nw
    return _from_rows(out)


class Maker:
    """Makes letters for one font. `game(letter)` gives the game's own letter image (or None) and `draw(letter)`
    the Windows-drawn one already mapped through the font's lut (or None when no face has it)."""

    def __init__(self, height: int, game, draw, x_top: int, cap_top: int):
        self.height = height
        self.game = game
        self.draw = draw
        self.x_top = x_top          # the top ink row of the game's "x"
        self.cap_top = cap_top      # the top ink row of the game's "H"
        self._marks: dict[tuple[int, bool], Mark | None] = {}
        self.cache: dict[str, Made | None] = {}

    # -- the pieces
    def _game_mark(self, mark: int, capital: bool) -> Mark | None:
        key = (mark, capital)
        if key in self._marks:
            return self._marks[key]
        found = None
        if mark in GAME_MARKS:
            lb, ll, cb, cl = GAME_MARKS[mark]
            b, l = (cb, cl) if capital else (lb, ll)
            gb, gl = self.game(b), self.game(l)
            if gb is not None and gl is not None:
                found = cut_mark(gb, gl, below=(mark == 0x0327))
        elif mark == CARON:
            m = self._game_mark(0x0302, capital)
            found = m.flipped() if m else None
        elif mark == MACRON:
            found = self._from_symbol("¯", capital)
        elif mark == DOT_ABOVE:
            m = self._game_mark(0x0308, capital)
            if m is not None:
                cols = [x for x in range(len(m.pixels[0])) if any(r[x] for r in m.pixels)]
                # the left dot: columns up to the first empty column
                end = cols[0]
                while end < len(m.pixels[0]) and any(r[end] for r in m.pixels):
                    end += 1
                w = end - cols[0]
                pixels = [r[cols[0]:end] for r in m.pixels]
                l, t, r, b = m.box
                bl, bt, br, bbm = m.base_box
                centre = (bl + br) / 2
                found = Mark(pixels, (int(centre - w / 2), t, int(centre - w / 2) + w, b), m.base_box, False)
        self._marks[key] = found
        return found

    def _from_symbol(self, symbol: str, capital: bool) -> Mark | None:
        """A spacing mark the game has (¯): its ink, sitting where the acute sits."""
        img = self.game(symbol)
        acute = self._game_mark(0x0301, capital)
        if img is None or acute is None:
            return None
        rows = _alpha(img)
        bb = _ink_box(rows)
        if bb is None:
            return None
        l, t, r, b = bb
        pixels = [row[l:r] for row in rows[t:b]]
        al, at, ar, ab = acute.box
        mid = (al + ar) / 2
        w = r - l
        top = ab - (b - t)
        return Mark(pixels, (int(round(mid - w / 2)), top, int(round(mid - w / 2)) + w, ab), acute.base_box, False)

    def _bare(self, base: str) -> pi.Image | None:
        """The base Windows draws under a mark: i and j without their dot."""
        return self.draw({"i": "\u0131", "j": "\u0237"}.get(base, base))

    def _drawn_mark(self, letter: str, base: str, mark: int) -> Mark | None:
        full, bare = self.draw(letter), self._bare(base)
        if full is None or bare is None:
            return None
        return cut_mark(bare, full, below=(mark in BELOW_MARKS))

    def _base(self, base: str, above: bool) -> pi.Image | None:
        if base in DOTLESS:
            return self.make(base).image if self.make(base) else None
        img = self.game(base)
        if img is None:
            m = self.make(base)
            img = m.image if m else None
        if img is not None and above and base in "ij":
            img = self._dotless(img)
        return img

    def _dotless(self, img: pi.Image) -> pi.Image:
        rows = _alpha(img)
        for y in range(min(self.x_top, len(rows))):
            rows[y] = [0] * len(rows[y])
        return _from_rows(rows)

    def _tall(self, img: pi.Image) -> bool:
        bb = _ink_box(_alpha(img))
        return bb is not None and bb[1] <= self.cap_top + 1

    # -- a letter
    def make(self, letter: str) -> Made | None:
        if letter in self.cache:
            return self.cache[letter]
        self.cache[letter] = None          # no loops
        made = self._make(letter)
        self.cache[letter] = made
        return made

    def _make(self, letter: str) -> Made | None:
        if letter in HOMOGLYPHS:
            img = self.game(HOMOGLYPHS[letter])
            if img is not None:
                return Made(img, "game shape")
        if letter in DOTLESS:
            img = self.game(DOTLESS[letter])
            if img is not None:
                return Made(self._dotless(img), "composed")
        decomposed = unicodedata.normalize("NFD", letter)
        if letter not in DRAWN_WHOLE and len(decomposed) >= 2 and not unicodedata.combining(decomposed[0]):
            made = self._compose(letter, decomposed)
            if made is not None:
                return made
        img = self.draw(letter)
        return Made(img, "drawn") if img is not None else None

    def _compose(self, letter: str, decomposed: str) -> Made | None:
        marks = [ord(c) for c in decomposed[1:]]
        if not all(unicodedata.combining(chr(m)) for m in marks):
            return None
        # the longest start that is a letter we have (ü for ǖ), then the other marks one by one
        start = 1
        base_text = decomposed[0]
        for k in range(len(decomposed), 1, -1):
            head = unicodedata.normalize("NFC", decomposed[:k])
            if len(head) == 1 and head != letter and (self.game(head) is not None or head in HOMOGLYPHS):
                base_text, start = head, k
                break
        rest = [ord(c) for c in decomposed[start:]]
        if not rest:
            return None
        base_text = HOMOGLYPHS.get(base_text, base_text)
        above_any = any(m not in BELOW_MARKS for m in rest)
        img = self._base(base_text, above_any)
        if img is None:
            return None
        stacked = start > 1
        for mark in rest:
            below = mark in BELOW_MARKS
            capital = (not below) and (self._tall(img) or stacked)
            m = self._game_mark(mark, capital)
            if m is None:
                single = unicodedata.normalize("NFC", decomposed[0] + chr(mark))
                m = self._drawn_mark(single if len(single) == 1 else letter, decomposed[0], mark)
                if m is None:
                    return None
                if not self._drawn_mark_ok(single if len(single) == 1 else letter, decomposed[0]):
                    return None
            img = place(img, m)
            if img is None:
                return None
            stacked = stacked or not below
        if img.height != self.height:
            return None
        return Made(img, "composed")

    def _drawn_mark_ok(self, letter: str, base: str) -> bool:
        """A mark Windows draws beside the letter (ď ľ ť) or through it (đ) cannot be cut out: then the
        whole letter is drawn instead."""
        full, bare = self.draw(letter), self._bare(base)
        if full is None or bare is None or full.width != bare.width:
            return False
        fr, br = _alpha(full), _alpha(bare)
        bb = _ink_box(br)
        if bb is None:
            return False
        diff = total = 0
        for y in range(bb[1], bb[3]):
            for x in range(full.width):
                diff += abs(fr[y][x] - br[y][x])
                total += br[y][x]
        return total and diff <= total * 0.08
