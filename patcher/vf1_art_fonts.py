"""The Picture Maker's fonts: every font picture in Virtual Families 1's Images folder, every glyph the game
cuts from one, and a line of text in every colour the game draws each of its fonts in, laid out exactly as the
game lays out text.

How the game does it (the vanilla Virtual Families.exe 1.01.00):

* Four font classes, SegoeUi33 / SegoeUiBold17 / SegoeUiBold18 / SegoeUiBold24 (constructors 0x421F80 /
  0x421FF0 / 0x422060 / 0x4220F0), each call ldwFont::Init 0x4022A0 with its name ("SegoeUi33" ... at
  0x4B5D50..0x4B5DA0), its glyph table (0x4EB6F0 / 0x4EC610 / 0x4ED538 / 0x4EE460) and a letter spacing of 0.
  ldwFontImpl::Load 0x402720 adds ".png" to a name with no dot (0x4027B0) and loads that picture, so the four
  fonts are SegoeUi33.png, SegoeUiBold17.png, SegoeUiBold18.png and SegoeUiBold24.png.  The *x512.png
  pictures and the other twelve font pictures are never loaded: no string, and no file-name format, in the exe
  names them.
* A glyph table is 20-byte rows (character, left, top, right, bottom) in one long strip, ended by a 0; the
  same 190 characters in every table (! to DEL, then space, then 0xA2..0xFF), each glyph as tall as the
  font and right after the one before.  The loader wraps a glyph that would run past the picture's right edge
  onto a new row (0x402858..0x4028B9); in the four strips nothing runs past, so the rectangles are the
  table's own.  A character with no row (0x00..0x1F, 0x80..0xA1) draws the table's first glyph, "!"
  (0x4028BB..0x4028F1 leaves its slot at 0).
* The font maker 0x44FC90 puts the four fonts in the font list of the singleton 0x450530 ([0x570218]): +0
  Bold 18, +4 Bold 17, +8 Bold 24, +0xC Segoe UI 33, and makes Bold 24 the window's default font (0x44FD63 ->
  0x4083F0).  The game reads the list back at +0 (Bold 18, everywhere else), +4 (Bold 17: only the getter
  0x4173A0, called at 0x412EF8 by the achievement row 0x412D00, which draws the achievement's description with
  it, 0x409D20 at 0x412F23) and +8 (that one default); +0xC only when it deletes the fonts at exit (0x450460, at
  0x4504B7).  So Segoe UI 33 is loaded but never drawn.  tests/test_font_slots.py proves it by running, in
  Unicorn, the font maker and every function that reads the list, with a read hook on it.
* Text is drawn by ldwGameWindowImpl 0x409660 (DrawText; 0x409CC0 left, 0x409CD0 right-aligned at x - the
  width, 0x409D20 centred at x - width / 2, the width from ldwFont 0x402320) and 0x409450 (the same, for a
  count of characters; justified paragraphs 0x409D70).  For each character: a new line moves down the font's
  height (0x4023F0) back to the first x; any other character's glyph (ldwFontImpl::GetCharRect 0x402AD0) is
  drawn with its top-left at the pen, and the pen moves right by the glyph's width plus the spacing (0).
  The colour is 0xAABBGGRR; an alpha of 0 means the default colour, opaque white (0x4E927C).  The glyphs are
  tinted (0x402940): unless the colour is white, a copy of the font picture is made whose every pixel is the
  picture's pixel AND (red, green, blue, 255) (SDL_MapRGBA, then `pixel & colour`) -- the glyphs are white, so
  they come out in the colour.  An alpha of 255 draws the glyph with SDL_UpperBlit (the cell as it is); any
  other alpha with BlitRectWithAlpha 0x404C30 at that alpha / 255 (a 32-bit float), scale 1.

tests/test_art_fonts.py runs the game's own font loader and text drawer in Unicorn (tests/fonts_emu.py) and
checks every glyph rectangle, every planned draw and the tinted pixels against them.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import vf1_game_art as ga
import vf1_picture_image as pi

TITLE = "Fonts"
CATEGORY = "Fonts"
SPACING = 0                         # ldwFont::Init's third argument (push 0 at 0x421FAD, 0x42201D, 0x42208D, 0x42211D)
DEFAULT_COLOUR = 0xFFFFFFFF         # 0x4E927C: the colour used when a colour's alpha byte is 0
WHITE, BLACK = 0xFFFFFFFF, 0xFF000000
SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog 0123456789"
ENCODING = "latin-1"                # a character is one byte; 0xA0..0xFF are the same in Windows-1252

# The characters of every glyph table, in table order (the same in all four).
CHARS = bytes(range(33, 128)) + b" " + bytes(range(0xA2, 0x100))


@dataclass(frozen=True)
class GameFont:
    """One of the exe's four font classes: its picture, its glyph widths (in CHARS order), and how it is used."""
    cls: str                        # the class name, which is also the picture's name without ".png"
    label: str                      # plain words
    height: int
    widths: bytes
    table: int                      # the glyph table's address
    constructor: int
    slot: int                       # its place in theGraphicsManager's font list
    used: bool
    why: str
    colours: tuple = ()             # (colour 0xAABBGGRR, plain name, why) the game draws it in

    @property
    def file(self) -> str:
        return self.cls + ".png"


def _w(hexes: str) -> bytes:
    return bytes.fromhex(hexes)


FONTS = {
    "SegoeUiBold18": GameFont(
        "SegoeUiBold18", "Segoe UI Bold 18", 18, _w(
            "050809090e0c050606070b040604070909090909090909090904040b0b0b070f0b0a0a0c09080b0c05070a080f0d0c0a"
            "0c0a09090c0b100a0a0a0607060b0705090a080a09060a0a050509050f0a0a0a0a0607060a090d0909080605060b0b05"
            "090909090508070e07090b060e03060b0606050a0804030607090f0f10070b0b0b0b0b0b0f0a09090909050505050c0d"
            "0c0c0c0c0c0b0c0c0c0c0c0a0a0a0909090909090d0809090909050505050a0a0a0a0a0a0a0b0a0a0a0a0a090a09"),
        0x4ED538, 0x422060, 0, True,
        "The game's text font: loaded when the game starts (0x44FD00) and drawn by the text drawer 0x409660, "
        "e.g. the centred words at 0x448C8B.",
        (
            (WHITE, "white", "Drawn in white, e.g. at 0x448C8B (colour 0x4F1740) and on every button made by "
                             "0x4015D0 with white (e.g. 0x416DD4)."),
            (BLACK, "black", "Drawn in black at 0x43AC99 / 0x43ACBA / 0x43BE9A (colour 0x4F100C; the font stored "
                             "at 0x43DDDB)."),
            (0xFF804C05, "dark blue", "Drawn in dark blue (5, 76, 128) as the text of the first dialog style "
                                      "(0x44F627, kept at 0x41AEFC, drawn at 0x419DEA)."),
        )),
    "SegoeUiBold24": GameFont(
        "SegoeUiBold24", "Segoe UI Bold 24", 24, _w(
            "070a0c0c120f0608080a0f060806090c0c0c0c0c0c0c0c0c0c06060f0f0f09140f0d0d0f0b0b0f1007090e0b1411100d"
            "100d0b0c0f0e150e0d0d0809080f09070b0d0a0d0b080d0d06060c06130d0d0d0d0809080d0b110c0b0a0807080f0e06"
            "0c0c0c0c070a0a12090c0f081204080f0808060d0b0605080a0c141415090f0f0f0f0f0f140d0b0b0b0b070707070f11"
            "10101010100f100f0f0f0f0d0d0d0b0b0b0b0b0b110a0b0b0b0b060606060c0d0d0d0d0d0d0f0d0d0d0d0d0b0d0b"),
        0x4EE460, 0x4220F0, 8, True,
        "The window's default font (0x44FD63): loaded when the game starts (0x44FD2B) and drawn whenever text "
        "names no font, e.g. at 0x41DA62 and on the buttons made at 0x43DE49.",
        (
            (WHITE, "white", "Drawn in white at 0x41DA62 and the other draws of 0x41D9C0 (colour 0x5021C4, which "
                             "nothing writes, so 0: the default white)."),
            (BLACK, "black", "Drawn in black on the buttons made at 0x43DE49 (their first colour, 0x4F1028)."),
            (0xFF555555, "dark grey", "Drawn in dark grey (85, 85, 85) on the buttons made at 0x43DE49 (their "
                                      "second colour, 0x4F102C)."),
            (0xFFEFEFEF, "light grey", "Drawn in light grey (239, 239, 239) on the buttons made at 0x43DE49 (their "
                                       "third colour, 0x4F1030)."),
        )),
    "SegoeUiBold17": GameFont(
        "SegoeUiBold17", "Segoe UI Bold 17", 17, _w(
            "050709090d0b040606070b040604070909090909090909090904040b0b0b070e0b0a090b08080b0b05070a080e0c0b09"
            "0b0a08090b0a0f0a09090607060b06050809070908060909040408040e0909090906070609080c0808070605060b0a04"
            "090908090507070d06090b060d03060b060605090804030607090e0e0f070b0b0b0b0b0b0e0908080808050505050b0c"
            "0b0b0b0b0b0b0b0b0b0b0b0909090808080808080c070808080804040404090909090909090b0909090909080908"),
        0x4EC610, 0x421FF0, 4, True,
        "The achievements' description font: loaded when the game starts (0x44FCD1), fetched from the font list "
        "(+4) only by 0x4173A0, which the achievement row 0x412D00 calls at 0x412EF8, and drawn there as the "
        "achievement's description (centred, 0x409D20 at 0x412F23).",
        (
            (WHITE, "white", "Drawn in white on the achievements screen (0x435360 calls 0x412D00 at 0x4353EA; the "
                             "colour 0x5008D0, which nothing writes, so 0: the default white)."),
            (0xFF804C05, "dark blue", "Drawn in dark blue (5, 76, 128) on the banner for a new achievement (0x413250 "
                                      "calls 0x412D00 at 0x4133A9; colour made at 0x412E6A..0x412EB0), opaque "
                                      "until it fades out."),
        )),
    "SegoeUi33": GameFont(
        "SegoeUi33", "Segoe UI 33", 33, _w(
            "090c121119160709090d15070c070c1111111111111111111107071515150e1e14121316100f1516080b120f1c171711"
            "17120f1015131d121112090c09150d0810120e12100a121208080f081b121212120b0c0b120f160e0f0e090709151509"
            "11111111070e0d1c0c10150c1c0d0c150b0b09120e07060b0d101c1d1e0e1414141414141b1310101010080808081617"
            "17171717171517151515151111111010101010101a0e1010101008080808111212121212121512121212120f120f"),
        0x4EB6F0, 0x421F80, 0xC, False,
        "Loaded when the game starts (0x44FD57) but never drawn: the only code that reads it back from the font "
        "list (+0xC) is the clean-up at exit 0x450460 (at 0x4504B7), which deletes it.  Checked by running every "
        "function that reads the list in Unicorn."),
}

# The font pictures no code loads: file -> (category name, label).
X512 = {
    "SegoeUI33x512.png": "SegoeUi33",
    "SegoeUIBold17x512.png": "SegoeUiBold17",
    "SegoeUIBold18x512.png": "SegoeUiBold18",
    "SegoeUIBold24x512.png": "SegoeUiBold24",
}
OTHER_FILES = {
    "SegoeUi20.png": "Segoe UI 20",
    "SegoeUi27.png": "Segoe UI 27",
    "SegoeUiBold21.png": "Segoe UI Bold 21",
    "SegoeUiBold27.png": "Segoe UI Bold 27",
    "SegoeUiBold33.png": "Segoe UI Bold 33",
    "AmericanTypewriter21.png": "American Typewriter 21",
    "AmericanTypewriter27.png": "American Typewriter 27",
    "SFCartoonistHandBold21.png": "SF Cartoonist Hand Bold 21",
    "SFCartoonistHandBold28.png": "SF Cartoonist Hand Bold 28",
    "ldwBurweed27.png": "Burweed 27",
    "ldwarialbold.png": "Arial Bold 20",
}
NOT_LOADED = ("No code loads it: the game names its fonts only SegoeUi33, SegoeUiBold17, SegoeUiBold18 and "
              "SegoeUiBold24 (0x4B5D50..0x4B5DA0, \".png\" added at 0x4027B0), no other string in the exe "
              "names this file, and the only name-making format ending in .png (0x40AF8F) makes only the "
              "image table's two-file pictures.")
X512_WHY = (NOT_LOADED + " Its glyphs are not cut: the game's glyph table is for the long strip, and the "
            "game's own wrapping onto rows (0x402858) does not put the glyphs where this picture has them.")
OTHER_WHY = (NOT_LOADED + " Its glyphs are not cut: the exe has no glyph table for it (its only four are at "
             "0x4EB6F0, 0x4EC610, 0x4ED538 and 0x4EE460), and cutting it without one would be a guess.")
LOADER_CHECK = "Checked against the game's own font loader 0x4022A0 run in Unicorn."
DRAW_CHECK = "Checked against the game's own text drawer 0x409660 and its tint 0x402940 run in Unicorn."


# ------------------------------------------------------------------ glyphs
def glyph_table(font: GameFont) -> list[tuple[int, tuple[int, int, int, int]]]:
    """(character, (left, top, right, bottom)) for every row of the font's glyph table, in table order: the
    rectangles the loader 0x402720 leaves (the strip is never wider than the picture, so never wrapped)."""
    out, left = [], 0
    for code, width in zip(CHARS, font.widths):
        out.append((code, (left, 0, left + width, font.height)))
        left += width
    return out


def char_index(font: GameFont) -> list[int]:
    """The loader's character -> table row (0x4028BB): the row whose character it is, else row 0 ("!")."""
    index = [0] * 256
    for k, code in enumerate(CHARS):
        if index[code] == 0:
            index[code] = k
    return index


def glyph_rect(font: GameFont, code: int) -> tuple[int, int, int, int]:
    """ldwFontImpl::GetCharRect 0x402AD0 for a character byte."""
    return glyph_table(font)[char_index(font)[code & 0xFF]][1]


def _bytes(text: str | bytes) -> bytes:
    data = text if isinstance(text, bytes) else text.encode(ENCODING, errors="replace")
    return data.split(b"\0", 1)[0]


def string_width(font: GameFont, text: str | bytes) -> int:
    """ldwFont 0x402320 at scale 1: the widest line's sum of (glyph width + spacing), less one spacing."""
    widest = line = 0
    for code in _bytes(text):
        if code == 0x0A:
            widest = max(widest, line) if line else widest
            line = 0
            continue
        l, _t, r, _b = glyph_rect(font, code)
        line += r - l + SPACING
    widest = max(widest, line)
    return widest - SPACING if widest else 0


def colour_parts(colour: int) -> tuple[tuple[int, int, int], float]:
    """(tint (red, green, blue), alpha) for a 0xAABBGGRR colour as 0x409660 uses it."""
    colour &= 0xFFFFFFFF
    if colour >> 24 == 0:
        colour = DEFAULT_COLOUR
    rgb = (colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF)
    a = colour >> 24
    return rgb, (1.0 if a == 0xFF else pi.f32(a / 255.0))


@dataclass(frozen=True)
class TintedDraw(pi.Draw):
    """A glyph draw from the font picture tinted by 0x402940: every pixel AND (red, green, blue, 255)."""
    tint: tuple = (255, 255, 255)


def tinted(image: pi.Image, rgb) -> pi.Image:
    """The copy 0x402940 makes of a font picture for a colour: each pixel AND (red, green, blue, 255)."""
    r, g, b = (int(v) & 0xFF for v in rgb[:3])
    out = image.copy()
    data = out.data
    if r != 0xFF:
        data[0::4] = bytes(v & r for v in data[0::4])
    if g != 0xFF:
        data[1::4] = bytes(v & g for v in data[1::4])
    if b != 0xFF:
        data[2::4] = bytes(v & b for v in data[2::4])
    return out


def layer_image(files: ga.GameFiles, layer) -> pi.Image:
    """One draw's pixels as the game puts them on screen, the tint included."""
    sheet = files.image(layer.file)
    tint = tuple(getattr(layer, "tint", (255, 255, 255)))
    if tint != (255, 255, 255):
        sheet = tinted(sheet, tint)
    return pi.game_layer(sheet, tuple(layer.rect), layer.scale, layer.alpha)


def text_draws(font: GameFont, text: str | bytes, x: int, y: int, colour: int = 0,
               align: str = "left") -> list[pi.Draw]:
    """The glyph draws 0x409660 makes for `text` (DrawText 0x409CC0; align "right" is 0x409CD0, "centre"
    0x409D20), unclipped."""
    data = _bytes(text)
    if align == "right":
        x -= string_width(font, data)
    elif align == "centre":
        w = string_width(font, data)
        x -= int(w / 2)                     # cdq; sub eax, edx; sar eax, 1
    elif align != "left":
        raise ValueError(f"unknown alignment {align!r}")
    rgb, alpha = colour_parts(colour)
    pen_x, pen_y, out = x, y, []
    for code in data:
        if code == 0x0A:
            pen_y += font.height
            pen_x = x
            continue
        rect = glyph_rect(font, code)
        width = rect[2] - rect[0]
        if width == 0:
            continue
        what = f"glyph {code}"
        if rgb == (255, 255, 255):
            out.append(pi.Draw(what, font.file, rect, pen_x, pen_y, 1.0, alpha))
        else:
            out.append(TintedDraw(what, font.file, rect, pen_x, pen_y, 1.0, alpha, rgb))
        pen_x += width + SPACING
    return out


def text_layers(files: ga.GameFiles | None, font: str | GameFont, text: str | bytes, x: int, y: int,
                colour: int = 0, align: str = "left") -> list[pi.Draw]:
    """`text` laid out exactly as the game draws it in `font` (a class name such as "SegoeUiBold18", or a
    GameFont) with its top-left pen at (x, y): one draw per glyph.  A draw in a colour other than white is a
    TintedDraw (render it with `layer_image`)."""
    if isinstance(font, str):
        font = FONTS[font]
    return text_draws(font, text, x, y, colour, align)


def render_text(files: ga.GameFiles, layers) -> pi.Image:
    """The draws on a transparent canvas as big as all of them, the tints included."""
    pieces = [(layer_image(files, layer), layer.x, layer.y) for layer in layers]
    pieces = [p for p in pieces if p[0].width and p[0].height]
    if not pieces:
        return pi.Image(1, 1)
    left = min(x for _i, x, _y in pieces)
    top = min(y for _i, _x, y in pieces)
    canvas = pi.Image(max(x + i.width for i, x, _y in pieces) - left, max(y + i.height for i, _x, y in pieces) - top)
    for image, x, y in pieces:
        canvas.draw(image, x - left, y - top)
    return canvas


def draw_art(files: ga.GameFiles, art: ga.Art) -> pi.Image:
    """An Art of this module as the game draws it, the tints included (vf1_game_art.draw leaves them out)."""
    return render_text(files, ga.resolve(files, art).layers)


def glyph_label(code: int) -> str:
    if code == 0x20:
        return "Space"
    if code == 0x7F:
        return "Character 127 (no letter)"
    if code == 0xAD:
        return "Soft hyphen"
    ch = bytes([code]).decode(ENCODING, errors="replace")
    if ch.isdigit():
        return f'Digit "{ch}"'
    if ch.isalpha():
        return f'Letter "{ch}"'
    return f'Sign "{ch}"'


# ------------------------------------------------------------------ the catalogue
def _key(name: str) -> str:
    return "fonts/" + name.lower().replace(".png", "")


def arts(files: ga.GameFiles) -> list[ga.Art]:
    out: list[ga.Art] = []
    for font in FONTS.values():
        category = f"{CATEGORY}/{font.label}"
        if not font.used:                        # loaded at start-up, never drawn (tests/test_font_slots.py)
            category += " (loaded but never drawn in the game)"
        if files.has(font.file):
            out.append(ga.Art(_key(font.cls) + "/whole", category, "Whole picture", (ga.whole(font.file),),
                              font.used, font.why, LOADER_CHECK))
            for code, rect in glyph_table(font):
                why = ("Cut from the picture when the game starts (0x402720) and drawn for this character by "
                       "0x409660." if font.used else
                       "Cut from the picture when the game starts (0x402720), but the font is never drawn. "
                       + font.why)
                out.append(ga.Art(f"{_key(font.cls)}/glyph/{code:03d}", category, glyph_label(code),
                                  (pi.Draw("glyph", font.file, rect, 0, 0),), font.used, why, LOADER_CHECK))
            for colour, name, why in font.colours:
                layers = tuple(text_draws(font, SAMPLE_TEXT, 0, 0, colour))
                out.append(ga.Art(f"{_key(font.cls)}/sample/{name.replace(' ', '-')}", category,
                                  f"Sample text in {name}", layers, True, why, DRAW_CHECK))
        x512 = next(f for f, c in X512.items() if c == font.cls)
        if files.has(x512):
            out.append(ga.Art(_key(x512) + "/whole", category, "Whole picture, rows 512 wide",
                              (ga.whole(x512),), False, X512_WHY, ""))
    for name, label in OTHER_FILES.items():
        if files.has(name):
            out.append(ga.Art(_key(name) + "/whole", f"{CATEGORY}/{label}", "Whole picture",
                              (ga.whole(name),), False, OTHER_WHY, ""))
    return out


def font_files() -> list[str]:
    """Every font picture this module lists."""
    return [f.file for f in FONTS.values()] + list(X512) + list(OTHER_FILES)


def table_rows(image: bytes, address: int, base: int = 0x400000) -> list[tuple[int, int, int, int, int]]:
    """The glyph table at `address` in a memory image of the exe (for the tests)."""
    rows, at = [], address - base
    while True:
        row = struct.unpack_from("<5i", image, at)
        if row[0] == 0:
            return rows
        rows.append(row)
        at += 20
