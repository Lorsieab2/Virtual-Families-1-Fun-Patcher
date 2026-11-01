"""Virtual Families 1's fonts, read from the game, and its text drawn exactly as the game draws it (the Game
Text tool, and the reference for Render Unicode with In-Game Fonts).

The game's fonts (VERIFIED in the vanilla exe, 1.01.00)
    theStringManager makes four ldwFonts (0x44FCC0..0x44FD60: [+0] SegoeUiBold18, [+4] SegoeUiBold17, [+8]
    SegoeUiBold24, [+0xC] SegoeUi33). Each constructor (0x421F80, 0x421FF0, 0x422060, 0x4220F0) calls
    ldwFont::ldwFont 0x4022A0(name, glyph table, spacing 0), which makes an ldwFontImpl and runs
    0x402720: the sheet is Images\\<name>.png (".png" is added when the name has no dot; "Font Image not
    found: %s" otherwise), the glyph table is rows of five ints {character, left, top, right, bottom} ended by
    a 0 character (tables 0x4EB6F0, 0x4EC610, 0x4ED538, 0x4EE460, 190 rows each: 0x21..0x7F, the space, and
    0xA2..0xFF as signed chars), and a row whose right edge passes the sheet's width is moved to the next
    band (0x402869..0x4028AD; never needed for these four). Then a 256-entry map, byte -> row, is built
    (0x4028BB..0x4028F1): a byte without a row maps to row 0 ("!").
    The sheets are white letters whose alpha is the coverage. The other 14 font sheets in Images
    (AmericanTypewriter21/27, SFCartoonistHandBold21/28, ldwBurweed27, ldwarialbold, SegoeUi20/27,
    SegoeUiBold21/27/33 and the four "x512" copies) are named nowhere in the exe and never drawn; the tool
    still offers the 10 that are not copies, "(unused in the game)", with glyph boxes found from the sheet
    (scripts/build_vf1_glyphs.py; "metrics not from the game").

How the game draws a string (VERIFIED)
    ldwGameWindowImpl::DrawString 0x409660(text, x, y, colour, font): colour alpha 0 means the default
    0xFFFFFFFF (0x4E927C); the sheet tinted for the colour comes from 0x402940 (the white sheet itself for
    white, else a cached copy of every pixel ANDed with MapRGBA(r, g, b, 255): r = colour byte 0, g = byte 1,
    b = byte 2). For each byte: "\\n" moves to the next line (y += the font's height, x back to the start);
    any other byte's row gives the box; a box 0 wide is skipped; otherwise the box is clipped (0x407E60) and
    drawn at (x, y), with SDL_UpperBlit when the colour's alpha is 255 and BlitRectWithAlpha 0x404C30 with
    alpha/255 otherwise, and x moves on by the box's width plus the spacing. ldwFont::GetWidth 0x402320
    (text, scale) adds trunc((box width + spacing) x scale) per byte, takes the widest line and subtracts
    the spacing once. 0x409450 is the same draw for the first n bytes (word wrapping uses it to measure).
    tests/test_vf1_game_fonts.py runs these functions in Unicorn and compares every box and pixel.

With Render Unicode with In-Game Fonts (vf1text.dll) a string is read by vf1_text's rule and drawn one
whole character at a time: the game's own letter when it has one (U+0020..U+007F and U+00A2..U+00FF), else
a patcher-made letter (payload\\UnicodeText, made by vf1_glyph_maker), else one drawn on the spot by
vf1_glyph_gdi in the font's style, else the missing-letter box. The tool draws the same.
"""
from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import vf1_picture_image as pi
import vf1_text

PATCHER_DIR = Path(__file__).resolve().parent
GLYPH_DIR = PATCHER_DIR / "payload" / "UnicodeText"
GLYPH_INSTALL_DIR = "Virtual Families 1 Patcher Files/Unicode Text"
EXE_NAME = "Virtual Families.exe"
IMAGE_BASE = 0x400000
FONT_CTOR = 0x4022A0                 # ldwFont::ldwFont(name, table, spacing)
DEFAULT_COLOUR = 0xFFFFFFFF          # 0x4E927C
# theStringManager's four fonts, in the order the tool lists them (what each is used for, by the game's
# own calls: buttons and most dialogs use [+0], SegoeUiBold18).
GAME_FONTS = ("SegoeUiBold18", "SegoeUiBold17", "SegoeUiBold24", "SegoeUi33")
GAME_FONT_USE = {
    "SegoeUiBold18": "buttons, dialogs and most of the game's text",
    "SegoeUiBold17": "small labels",
    "SegoeUiBold24": "titles",
    "SegoeUi33": "large text",
}
UNUSED_FONTS = ("SegoeUi20", "SegoeUi27", "SegoeUiBold21", "SegoeUiBold27", "SegoeUiBold33",
                "AmericanTypewriter21", "AmericanTypewriter27", "SFCartoonistHandBold21",
                "SFCartoonistHandBold28", "ldwBurweed27", "ldwarialbold")
UNUSED_COPIES = ("SegoeUI33x512", "SegoeUIBold17x512", "SegoeUIBold18x512", "SegoeUIBold24x512")
# The 190 characters every sheet holds, in sheet order (the game's tables; the unused sheets have the same).
SHEET_ORDER = tuple(range(0x21, 0x80)) + (0x20,) + tuple(range(0xA2, 0x100))
# The game's text colours a player is offered first (ldwColor: r | g << 8 | b << 16 | alpha << 24).
COLOUR_PRESETS = (
    ("White (the font as it is)", 0xFFFFFFFF),
    ("Black", 0xFF000000),
    ("Button text (0x4F1740)", None),       # read from the exe
)


class FontError(Exception):
    """A font that cannot be read, with a reason a player can read."""


# --------------------------------------------------------------------------- the exe
class _Exe:
    def __init__(self, data: bytes):
        if data[:2] != b"MZ":
            raise FontError("This is not a Windows program.")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise FontError("This is not a Windows program.")
        count = struct.unpack_from("<H", data, pe + 6)[0]
        opt = struct.unpack_from("<H", data, pe + 20)[0]
        self.base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
        self.sections = []
        at = pe + 24 + opt
        for i in range(count):
            name, vsize, va, rsize, raw = struct.unpack_from("<8sIIII", data, at + 40 * i)
            self.sections.append((name.rstrip(b"\0"), va, vsize, raw, rsize))
        self.data = data

    def read(self, va: int, n: int) -> bytes:
        rva = va - self.base
        for _, sva, vsize, raw, rsize in self.sections:
            if sva <= rva < sva + max(vsize, rsize):
                off = raw + rva - sva
                return self.data[off:off + n]
        raise FontError(f"0x{va:X} is not in the program.")

    def text(self) -> tuple[int, bytes]:
        for name, sva, vsize, raw, rsize in self.sections:
            if name == b".text":
                return self.base + sva, self.data[raw:raw + rsize]
        raise FontError("The program has no code section.")

    def cstr(self, va: int, limit: int = 64) -> str:
        return self.read(va, limit).split(b"\0", 1)[0].decode("latin-1")


def read_glyph_table(exe: "_Exe", va: int) -> list[tuple[int, int, int, int, int]]:
    rows = []
    while len(rows) < 0x8000:
        row = struct.unpack("<5i", exe.read(va + 20 * len(rows), 20))
        if row[0] == 0:
            return rows
        rows.append(row)
    raise FontError("A font table never ends.")


def find_game_fonts(exe_data: bytes) -> dict[str, tuple[int, int]]:
    """{font name: (glyph table address, spacing)} for every `push spacing8; push table; push name; ...; call
    ldwFont::ldwFont` in the program (four in 1.01.00)."""
    exe = _Exe(exe_data)
    start, code = exe.text()
    found: dict[str, tuple[int, int]] = {}
    i = code.find(b"\x6a")
    while 0 <= i < len(code) - 12:
        if code[i + 2] == 0x68 and code[i + 7] == 0x68:
            spacing = struct.unpack_from("<b", code, i + 1)[0]
            table, name_va = struct.unpack_from("<II", code, i + 3)[0], struct.unpack_from("<I", code, i + 8)[0]
            window = code[i + 12:i + 40]
            for k in range(len(window) - 4):
                if window[k] == 0xE8:
                    target = start + i + 12 + k + 5 + struct.unpack_from("<i", window, k + 1)[0]
                    if target == FONT_CTOR:
                        try:
                            name = exe.cstr(name_va)
                        except FontError:
                            break
                        if name and name.isprintable():
                            found[name] = (table, spacing)
                        break
        i = code.find(b"\x6a", i + 1)
    return found


# --------------------------------------------------------------------------- styles (patcher-made letters)
@dataclass
class Style:
    """How letters the sheet lacks are drawn for a font (from its glyph file; vf1_glyph_maker made it)."""
    face: str
    weight: int
    em: int
    baseline: int
    lut: tuple[int, ...]          # GDI coverage -> the sheet's coverage


@dataclass
class GlyphFile:
    """A font's patcher-made letters: payload\\UnicodeText\\<font>.png and <font>.txt."""
    style: Style
    sheet: pi.Image | None
    boxes: dict[str, tuple[int, int, int, str]] = field(default_factory=dict)   # letter: (x, y, w, how)
    metrics: list[tuple[int, int, int]] | None = None   # an unused font's own boxes: (character, left, right)

    def letter(self, text: str, height: int) -> pi.Image | None:
        box = self.boxes.get(text)
        if box is None or self.sheet is None:
            return None
        x, y, w, _ = box
        return self.sheet.sub(x, y, w, height)


def parse_glyph_file(text: str) -> tuple[dict, dict[str, tuple[int, int, int, str]], list | None]:
    """The <font>.txt format (also read by vf1text.dll, LoadGlyphFile):
        # comments
        vf1-glyphs 1
        font <name> / height <n> / baseline <n> / face <name> / weight <n> / em <n>
        lut <256 numbers>
        g <code points in hex joined by +> <x> <y> <w> <how>
        m <character in hex> <left> <right>     (an unused font's own boxes, metrics not from the game)
    """
    head: dict = {}
    boxes: dict[str, tuple[int, int, int, str]] = {}
    metrics: list[tuple[int, int, int]] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "vf1-glyphs 1":
        raise FontError("Not a patcher glyph file.")
    for line in lines[1:]:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0]
        if key == "g" and len(parts) >= 5:
            letter = "".join(chr(int(c, 16)) for c in parts[1].split("+"))
            boxes[letter] = (int(parts[2]), int(parts[3]), int(parts[4]), parts[5] if len(parts) > 5 else "")
        elif key == "m" and len(parts) == 4:
            metrics.append((int(parts[1], 16), int(parts[2]), int(parts[3])))
        elif key == "lut":
            head["lut"] = tuple(int(v) for v in parts[1:])
        elif key == "face":
            head["face"] = line.split(None, 1)[1].strip()
        elif key in ("font",):
            head[key] = parts[1]
        elif len(parts) == 2:
            head[key] = int(parts[1])
    if len(head.get("lut", ())) != 256:
        raise FontError("A glyph file needs a 256-entry lut.")
    return head, boxes, (metrics or None)


def load_glyph_file(name: str, folder: Path = GLYPH_DIR) -> GlyphFile | None:
    txt = folder / f"{name}.txt"
    if not txt.is_file():
        return None
    head, boxes, metrics = parse_glyph_file(txt.read_text(encoding="utf-8"))
    style = Style(head.get("face", "Segoe UI"), head.get("weight", 400), head.get("em", 12),
                  head.get("baseline", 0), head["lut"])
    png = folder / f"{name}.png"
    sheet = pi.decode_png(png.read_bytes()) if (png.is_file() and boxes) else None
    return GlyphFile(style, sheet, boxes, metrics)


# --------------------------------------------------------------------------- one font
@dataclass
class Glyph:
    image: pi.Image          # white letter, alpha = coverage, the font's height high
    width: int               # the box's width (the game moves on by width + spacing)
    kind: str                # "game", "patcher-made", "drawn by Windows", "missing"
    face: str = ""


class GameFont:
    """One font: its sheet, its boxes, and the letters the patcher adds."""

    def __init__(self, name: str, sheet: pi.Image, rows: list[tuple[int, int, int, int, int]], spacing: int,
                 *, in_game: bool, metrics_from_game: bool, glyphs: GlyphFile | None):
        self.name = name
        self.sheet = sheet
        self.spacing = spacing
        self.in_game = in_game
        self.metrics_from_game = metrics_from_game
        self.glyphs = glyphs
        self.rows = self._place(rows, sheet.width)
        self.height = self.rows[0][4] - self.rows[0][2] if self.rows else sheet.height
        self.index = [0] * 256
        for byte in range(256):
            for k, row in enumerate(self.rows):
                code = row[0]
                if code < 0:
                    code &= 0xFF
                if code == byte:
                    self.index[byte] = k
                    break
        self.native = frozenset(byte for byte in range(1, 256)
                                if any(((r[0] & 0xFF) if r[0] < 0 else r[0]) == byte for r in self.rows))
        self._made: dict[str, Glyph] = {}
        self._renderer = None

    @staticmethod
    def _place(rows, sheet_width):
        """0x402858..0x4028B9: a row whose right edge passes the sheet's width goes to the next band."""
        rows = [list(r) for r in rows]
        if not rows:
            return []
        height = rows[0][4] - rows[0][2]
        dx = dy = 0
        for r in rows:
            r[3] -= dx
            r[1] -= dx
            r[2] += dy
            r[4] += dy
            if r[3] > sheet_width:
                dx += r[1]
                dy += height + 1
                r[3] -= r[1]
                r[1] = 0
                r[2] += height + 1
                r[4] += height + 1
        return [tuple(r) for r in rows]

    @property
    def label(self) -> str:
        if self.in_game:
            return f"{self.name} ({GAME_FONT_USE.get(self.name, 'in the game')})"
        return f"{self.name} (unused in the game; metrics not from the game)"

    # -- letters
    def box(self, byte: int) -> tuple[int, int, int, int]:
        """The game's box for a byte (0x402AD0): a byte without a row gets row 0."""
        r = self.rows[self.index[byte & 0xFF]]
        return r[1], r[2], r[3], r[4]

    def game_glyph(self, byte: int) -> Glyph:
        l, t, r, b = self.box(byte)
        return Glyph(self.sheet.sub(l, t, r - l, b - t), r - l, "game")

    def has_native(self, letter: str) -> bool:
        return len(letter) == 1 and ord(letter) in self.native

    @property
    def style(self) -> Style | None:
        return self.glyphs.style if self.glyphs else None

    def renderer(self):
        if self._renderer is None and self.style is not None:
            import vf1_glyph_gdi
            if vf1_glyph_gdi.AVAILABLE:
                s = self.style
                if self.override is not None:
                    face, em = self.override
                    self._renderer = vf1_glyph_gdi.renderer(face, s.weight, em, s.baseline, self.height,
                                                            vf1_glyph_gdi.UNICODE_FONT_FALLBACKS)
                else:
                    self._renderer = vf1_glyph_gdi.renderer(s.face, s.weight, s.em, s.baseline, self.height)
        return self._renderer

    override: tuple[str, int] | None = None      # Use Unicode Font: (face, fitted em)

    def with_unicode_font(self, face: str = "Segoe UI") -> "GameFont":
        """This font as Use Unicode Font (overrides in-game fonts) draws it: every letter by Windows in `face` (then
        Segoe UI and the chain), at this font's height, baseline and weight, the size fitted by fit_unicode_font."""
        import copy
        other = copy.copy(self)
        other._made = {}
        other._renderer = None
        other.override = (face, fit_unicode_font(self, face))
        return other

    def glyph(self, letter: str) -> Glyph:
        """A whole character as the patched game draws it."""
        if letter == "\n":
            return Glyph(pi.Image(0, self.height), 0, "line break")
        if len(letter) > 1:
            composed = unicodedata.normalize("NFC", letter)     # vf1text.dll: NormalizeString(C)
            if len(composed) == 1:
                letter = composed
        if len(letter) == 1 and ord(letter) < 0x100 and (ord(letter) < 0x20 or 0x7F < ord(letter) < 0xA0):
            return self.game_glyph(0) if ord(letter) not in self.native else self.game_glyph(ord(letter))
        if self.override is None and self.has_native(letter):
            return self.game_glyph(ord(letter))
        if letter in self._made:
            return self._made[letter]
        made = None
        if self.glyphs is not None and self.override is None:
            image = self.glyphs.letter(letter, self.height)
            if image is not None:
                made = Glyph(image, image.width, "patcher-made")
        if made is None:
            made = self._runtime(letter)
        self._made[letter] = made
        return made

    def _runtime(self, letter: str) -> Glyph:
        import vf1_glyph_gdi
        r = self.renderer()
        if r is None:
            s = self.style
            box = vf1_glyph_gdi.missing_box(self.height, s.baseline if s else self.height - 4,
                                            s.em if s else self.height)
            return Glyph(box, box.width, "missing")
        image, face = r.draw(letter)
        if not face:
            return Glyph(image, image.width, "missing")
        lut = self.style.lut
        image.data[3::4] = bytes(lut[a] for a in image.data[3::4])
        return Glyph(image, image.width, "drawn by Windows", face)

    # -- the game's drawing
    def letters(self, text: str) -> list[str]:
        return vf1_text.clusters(text)

    def width(self, text: str, scale: float = 1.0) -> int:
        """ldwFont::GetWidth (0x402320), one whole character at a time."""
        widest = line = 0
        for letter in self.letters(text):
            if letter == "\n":
                if line and line > widest:
                    widest = line
                line = 0
                continue
            line += int(_f32((self.glyph(letter).width + self.spacing)) * _f32(scale))
        widest = max(widest, line)
        if widest:
            widest -= self.spacing
        return widest

    def lines(self, text: str) -> int:
        return text.count("\n") + 1

    def layout(self, text: str, x: int = 0, y: int = 0) -> list[tuple[Glyph, int, int]]:
        """Where DrawString (0x409660) puts each letter: (glyph, x, y)."""
        out = []
        cx, cy = x, y
        for letter in self.letters(text):
            if letter == "\n":
                cx = x
                cy += self.height
                continue
            g = self.glyph(letter)
            if g.width == 0:
                continue
            out.append((g, cx, cy))
            cx += g.width + self.spacing
        return out

    def render(self, text: str, colour: int = DEFAULT_COLOUR) -> pi.Image:
        """The string on a transparent picture as big as the game's own measure of it (GetWidth by the
        lines' height): each pixel is the tinted letter's pixel."""
        width = max(1, self.width(text))
        height = self.height * self.lines(text)
        out = pi.Image(width, height)
        for g, x, y in self.layout(text):
            paint(out, g.image, x, y, colour)
        return out


FIT_REFERENCE = "The quick brown fox jumps over the lazy dog 0123456789"


def fit_unicode_font(font: "GameFont", face: str) -> int:
    """Use Unicode Font's size for `font` in `face` (vf1font.dll's FitChosenFont, the same arithmetic): the em at
    which FIT_REFERENCE is as wide in `face` as the game font draws it, kept within 60% to 130% of the font's own
    em; the font's own em when `face` is not installed."""
    import vf1_glyph_gdi
    s = font.style
    if s is None or not vf1_glyph_gdi.AVAILABLE:
        return s.em if s else font.height
    game = sum(font.box(ord(c))[2] - font.box(ord(c))[0] for c in FIT_REFERENCE)
    probe = vf1_glyph_gdi.Renderer(face, s.weight, s.em, s.baseline, font.height, ())
    try:
        width = probe.extent(FIT_REFERENCE)
    finally:
        probe.close()
    if width <= 0 or game <= 0:
        return s.em
    em = (s.em * game * 2 + width) // (2 * width)
    return max(s.em * 6 // 10, min(s.em * 13 // 10, em))


def _f32(v: float) -> float:
    return struct.unpack("<f", struct.pack("<f", v))[0]


def tint_pixel(px: bytes, colour: int) -> bytes:
    """0x402940: a pixel ANDed with MapRGBA(r, g, b, 255) (white is the sheet itself)."""
    r, g, b = colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF
    return bytes((px[0] & r, px[1] & g, px[2] & b, px[3]))


def paint(out: pi.Image, letter: pi.Image, x: int, y: int, colour: int = DEFAULT_COLOUR) -> None:
    """One letter's pixels into `out` at (x, y), tinted for `colour` (alpha 0 = the default colour); a
    colour alpha below 255 lowers each pixel's alpha as BlitRectWithAlpha 0x404C30 does."""
    if (colour >> 24) == 0:
        colour = DEFAULT_COLOUR
    alpha = (colour >> 24) & 0xFF
    r, g, b = colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF
    weight = None
    if alpha != 0xFF:
        weight = int(alpha / 255.0 * 255.0 + 0.5)
    for yy in range(letter.height):
        ty = y + yy
        if not 0 <= ty < out.height:
            continue
        for xx in range(letter.width):
            tx = x + xx
            if not 0 <= tx < out.width:
                continue
            s = (yy * letter.width + xx) * 4
            a = letter.data[s + 3]
            d = (ty * out.width + tx) * 4
            if weight is not None:
                a = (a * weight + 0x7F) >> 8
            if a or out.data[d + 3] == 0:
                out.data[d:d + 4] = bytes((letter.data[s] & r, letter.data[s + 1] & g, letter.data[s + 2] & b, a))


# --------------------------------------------------------------------------- loading
class Fonts:
    """Every font of a game folder: the game's four, and the unused sheets."""

    def __init__(self, game_dir: Path, glyph_dir: Path = GLYPH_DIR):
        self.game_dir = Path(game_dir)
        self.glyph_dir = Path(glyph_dir)
        exe = self.game_dir / EXE_NAME
        if not exe.is_file():
            raise FontError(f"{EXE_NAME} is not in {self.game_dir}.")
        self.exe_data = exe.read_bytes()
        self._exe = _Exe(self.exe_data)
        self.found = find_game_fonts(self.exe_data)
        if not self.found:
            raise FontError("No fonts were found in this Virtual Families program.")
        self._fonts: dict[str, GameFont] = {}

    def names(self) -> list[str]:
        game = [n for n in GAME_FONTS if n in self.found] + sorted(n for n in self.found if n not in GAME_FONTS)
        unused = [n for n in UNUSED_FONTS if (self.game_dir / "Images" / f"{n}.png").is_file()
                  and (self.glyph_dir / f"{n}.txt").is_file()]
        return game + unused

    def button_colour(self) -> int:
        return struct.unpack("<I", self._exe.read(0x4F1740, 4))[0]

    def font(self, name: str) -> GameFont:
        if name in self._fonts:
            return self._fonts[name]
        image_name = name if "." in name else name + ".png"
        path = self.game_dir / "Images" / image_name
        if not path.is_file():
            raise FontError(f"Font Image not found: {image_name}")
        sheet = pi.decode_png(path.read_bytes())
        glyphs = load_glyph_file(name, self.glyph_dir)
        if name in self.found:
            table, spacing = self.found[name]
            rows = read_glyph_table(self._exe, table)
            font = GameFont(name, sheet, rows, spacing, in_game=True, metrics_from_game=True, glyphs=glyphs)
        else:
            if glyphs is None or not glyphs.metrics:
                raise FontError(f"{name} has no glyph boxes.")
            h = sheet.height
            rows = [(c if c < 0x80 else c - 0x100, l, 0, r, h) for c, l, r in glyphs.metrics]
            font = GameFont(name, sheet, rows, 0, in_game=False, metrics_from_game=False, glyphs=glyphs)
        self._fonts[name] = font
        return font
