"""Colour emoji (native/vf1text/glyph_color.inc, patcher/vf1_glyph_color.py, vf1_emoji.py): emoji drawn in colour by
DirectWrite and Direct2D into the glyph cache, in vf1text.dll, vf1font.dll and the Game Text tool's preview.

* The one rule for which whole characters are colour emoji is the same in the DLLs and the patcher (the generated
  emoji.inc equals vf1_emoji's table; the table equals Windows' ICU's Emoji_Presentation when ICU is there).
* The DLL's own VF1Text_ColourLetter (through 32-bit rundll32) gives the same pixels as vf1_glyph_color.draw: size,
  box, every R, G, B and A byte; skin tones, ZWJ sequences, keycaps and flags each come out as one picture.
* Inside the emulator (the REAL DLLs on the REAL exe, GDI by real GDI, VF1Text_ColourLetter by the machine's real
  Direct2D), the game's DrawString, GetWidth and word wrapper draw a name with emoji as the tool's preview draws
  it: every place, box and pixel (all four channels), the picture untinted whatever the text colour, see-through
  with a see-through colour; the same em and baseline as the black-and-white letters; letters around the emoji
  exactly as before; and with settings.ini ColourEmoji=0, or without Direct2D, black and white as before.
"""
import os
import struct
import subprocess

import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import vf1_emoji  # noqa: E402
import vf1_game_fonts as gf  # noqa: E402
import vf1_glyph_color as gc  # noqa: E402
import vf1_glyph_gdi as g  # noqa: E402
import vf1_text  # noqa: E402
from test_vf1_glyph_gdi import RUNDLL32, need_windows  # noqa: E402
from test_vf1_unicode_text import dll, VCVARS  # noqa: E402,F401  (the module-scoped build)

EMOJI = [
    "\U0001f600",                                    # grinning face
    "\U0001f44d\U0001f3fd",                          # thumbs up, medium skin tone
    "\U0001f468‍\U0001f469‍\U0001f467",    # family (ZWJ sequence)
    "\U0001f1ef\U0001f1f5",                          # flag: Japan (two regional indicators)
    "1️⃣",                                 # keycap 1
    "❤️",                                  # red heart with emoji presentation
    "☃️",                                  # snowman with emoji presentation
    "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",   # flag: Scotland (tags)
]
NOT_EMOJI = ["A", "é", "日", "❤", "☃", "☹", "1", "\U0001f600︎", "é"]


def need_colour():
    need_windows()
    if gc.factories() is None:
        pytest.skip("needs Direct2D and DirectWrite")


# --------------------------------------------------------------------------- the rule
def test_the_rule_picks_pictures_not_text():
    for e in EMOJI:
        assert vf1_emoji.is_colour_emoji(e), e
        assert len(vf1_text.clusters(e)) == 1, e                   # one whole character
    for t in NOT_EMOJI:
        assert not vf1_emoji.is_colour_emoji(t), t


def test_the_dlls_table_is_the_patchers():
    import re
    src = (ROOT / "native" / "vf1text" / "emoji.inc").read_text(encoding="utf-8")
    rows = [(int(a, 16), int(b, 16)) for a, b in re.findall(r"\{(0x[0-9A-F]+),(0x[0-9A-F]+)\}", src)]
    assert tuple(rows) == vf1_emoji.EMOJI_PRESENTATION_RANGES
    assert src == vf1_emoji.emoji_table_c()
    for (a0, b0), (a1, _) in zip(rows, rows[1:]):
        assert a0 <= b0 < a1


def test_the_table_is_unicode_18s_and_holds_every_emoji_windows_icu_knows():
    import vf1_line_break as lb
    import vf1_unicode18
    assert vf1_emoji.EMOJI_PRESENTATION_RANGES == vf1_unicode18.EMOJI_PRESENTATION
    if lb.icu() is None:
        pytest.skip("needs icu.dll")
    ours = {cp for a, b in vf1_emoji.EMOJI_PRESENTATION_RANGES for cp in range(a, b + 1)}
    assert {cp for a, b in vf1_emoji.build_emoji_presentation() for cp in range(a, b + 1)} <= ours


# --------------------------------------------------------------------------- the DLL's drawing, through rundll32
def dll_colours(dll, tmp_path, face, weight, em, baseline, height, letters):
    """The DLL's own VF1Text_ColourLetter for each of `letters`, in one 32-bit rundll32 process (Direct2D's start-up,
    which loads Direct3D's WARP rasterizer, is paid once; it took over a minute on a loaded machine):
    [(w, h, drawn, straight RGBA rows)]."""
    out = tmp_path / f"colour-{abs(hash((face, weight, em, tuple(letters))))}.bin"
    field = "/".join("+".join(f"{ord(c):X}" for c in letter) for letter in letters)
    p = subprocess.Popen([RUNDLL32, f"{dll},VF1Text_TestColour", f"{out}|{face}|{weight}|{em}|{baseline}|{height}|{field}"])
    try:
        p.wait(timeout=600)
    except subprocess.TimeoutExpired:
        p.kill()            # only the process this test started
        raise
    data = out.read_bytes()
    results, at = [], 0
    for _ in letters:
        w, h, drawn = struct.unpack_from("<3i", data, at)
        at += 12
        n = w * h * 4 if drawn else 0
        results.append((w, h, drawn, data[at:at + n]))
        at += n
    assert at == len(data)
    return results


@pytest.mark.parametrize("font", gf.GAME_FONTS)
def test_the_dll_draws_each_emoji_as_the_patcher_does(dll, tmp_path, font):
    need_colour()
    style = gf.load_glyph_file(font).style
    height = HEIGHTS[font]
    theirs = dll_colours(dll, tmp_path, gc.EMOJI_FACE, 400, style.em, style.baseline, height, EMOJI)
    for letter, (w, h, drawn, rows) in zip(EMOJI, theirs):
        image = gc.draw(letter, 400, style.em, style.baseline, height)
        if letter == EMOJI[3]:
            # a country flag: Segoe UI Emoji has no flag pictures and draws the two letters in the brush's white,
            # which has no colour, so neither side keeps it (GDI draws it, tinted, as the Virtual Villagers patcher)
            assert image is None and (w, drawn, rows) == (0, 0, b""), letter
            continue
        assert image is not None, letter
        assert (w, h, drawn) == (image.width, image.height, 1), letter
        assert rows == bytes(image.data), letter                   # every R, G, B, A byte
        # a picture, in colour: not every inked pixel is white (the Scotland tag flag is the font's black flag)
        inked = [image.data[i:i + 3] for i in range(0, len(image.data), 4) if image.data[i + 3]]
        assert inked, letter
        assert any(px != b"\xff\xff\xff" for px in inked), letter
        if letter != EMOJI[7]:
            assert any(len(set(px)) > 1 for px in inked), letter
        assert image.width > 0 and image.width <= height * 3


def test_a_face_that_is_not_there_draws_nothing(dll, tmp_path):
    need_colour()
    (w, h, drawn, rows), = dll_colours(dll, tmp_path, "No Such Face Anywhere", 400, 16, 14, 18, ["\U0001f600"])
    # DirectWrite falls back to a face it has: the DLL still draws; what matters is both sides agree
    image = gc.draw("\U0001f600", 400, 16, 14, 18, face="No Such Face Anywhere")
    assert (w, h, bool(drawn)) == ((image.width, image.height, True) if image else (0, 18, False))


HEIGHTS = {"SegoeUi33": 33, "SegoeUiBold17": 17, "SegoeUiBold18": 18, "SegoeUiBold24": 24}


@pytest.mark.parametrize("font", gf.GAME_FONTS)
def test_size_and_baseline_match_the_black_and_white_letters(font):
    """The colour picture sits on the same baseline and em as GDI's monochrome emoji, in each of the game's four
    fonts: its first and last rows of ink are within 2 pixels of GDI's and its width within 3."""
    need_colour()
    style = gf.load_glyph_file(font).style
    height = HEIGHTS[font]
    mono = g.Renderer(gc.EMOJI_FACE, 400, style.em, style.baseline, height, ())
    for letter in EMOJI[:3]:
        colour = gc.draw(letter, 400, style.em, style.baseline, height)
        grey, face = mono.draw(letter)
        assert face

        def ink_rows(img):
            return [y for y in range(img.height) if any(img.data[(y * img.width + x) * 4 + 3] for x in range(img.width))]
        c, m = ink_rows(colour), ink_rows(grey)
        assert c and m
        assert abs(c[0] - m[0]) <= 2 and abs(c[-1] - m[-1]) <= 2, (letter, c, m)
        assert abs(colour.width - grey.width) <= 3, (letter, colour.width, grey.width)


# --------------------------------------------------------------------------- the tool's model
def test_the_patchers_fonts_draw_emoji_in_colour_untinted(vanilla_dir):
    need_colour()
    fonts = gf.Fonts(vanilla_dir)
    for font in gf.GAME_FONTS:
        f = fonts.font(font)
        for letter in EMOJI:
            glyph = f.glyph(letter)
            if letter == EMOJI[3]:      # a country flag: its two letters, by GDI, tinted as any letter
                assert glyph.kind == "drawn by Windows" and not glyph.colour, (font, letter)
                continue
            assert glyph.kind == "colour emoji" and glyph.colour and glyph.face == gc.EMOJI_FACE, (font, letter)
        assert f.glyph("❤").kind != "colour emoji"
        # the tint leaves the picture's colours alone; a see-through colour still thins it
        text = "Mia " + EMOJI[0]
        white = f.render(text, 0xFFFFFFFF)
        red = f.render(text, 0xFF0000FF)
        g0, x, y = f.layout(text)[-1]
        for yy in range(g0.image.height):
            for xx in range(g0.image.width):
                s = (yy * g0.image.width + xx) * 4
                if g0.image.data[s + 3]:
                    d = ((y + yy) * white.width + x + xx) * 4
                    assert white.data[d:d + 4] == red.data[d:d + 4] == g0.image.data[s:s + 4]
        seen = f.render(text, 0x80FFFFFF)
        d = ((y + g0.image.height // 2) * seen.width + x + g0.image.width // 2) * 4
        assert seen.data[d + 3] < white.data[d + 3] or white.data[d + 3] == 0
        # the letters around it are the game's own
        assert [gl.kind for gl, _, _ in f.layout(text)[:-1]] == ["game"] * 4
        # off: the black-and-white letter, as before
        f.colour_emoji = False
        f._made.clear()
        assert f.glyph(EMOJI[0]).kind == "drawn by Windows"
        f.colour_emoji = True
        f._made.clear()


# --------------------------------------------------------------------------- in the game (emulated)
@pytest.fixture(scope="module")
def world(dll, vanilla_dir):
    need_colour()
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True, real_gdi=True)
    assert w.installed == 1
    return w


def same_pixels(world, blits, layout):
    import vf1_picture_image as pi
    assert len(blits) == len(layout)
    for (kind, surface, box, place), (glyph, x, y) in zip(blits, layout):
        assert kind == "blit" and place == (x, y) and box[2] == glyph.width
        if glyph.kind == "game":
            continue
        info = world.surfaces[surface]
        sheet = pi.Image(info["w"], info["h"], world.surface_pixels(surface))
        piece = sheet.sub(*box)
        if glyph.colour:
            assert bytes(piece.data) == bytes(glyph.image.data), glyph.kind       # all four channels, untinted
        else:
            assert bytes(piece.data[3::4]) == bytes(glyph.image.data[3::4]), glyph.kind


@pytest.mark.parametrize("font", gf.GAME_FONTS)
def test_the_game_draws_emoji_in_colour_as_the_tool_does(world, vanilla_dir, font):
    f = gf.Fonts(vanilla_dir).font(font)
    for name in ["Mia " + "".join(EMOJI), "Zoë \U0001f600 日本 ❤ ❤️"]:
        data = vf1_text.encode(name)
        for colour in (0xFFFFFFFF, 0xFF2040C0):
            blits = world.draw(data, font, x=2, y=3, colour=colour)
            same_pixels(world, blits, f.layout(name, 2, 3))
        assert world.width(data, font) == f.width(name)
    assert world.colour_calls
    assert all(c[0] == gc.EMOJI_FACE and c[1] == 400 for c in world.colour_calls)


def test_a_see_through_colour_goes_through_the_alpha_blit(world):
    blits = world.draw(vf1_text.encode(EMOJI[0] + "a"), "SegoeUiBold18", colour=0x80FFFFFF)
    assert [b[0] for b in blits] == ["alpha", "alpha"]


def test_the_picture_is_kept_and_drawn_once(world):
    data = vf1_text.encode(EMOJI[2] * 3)
    before = len(world.colour_calls)
    world.draw(data)
    world.draw(data)
    assert len(world.colour_calls) == before             # already in the cache from the test before


def test_the_wrapper_and_the_counted_draw_use_the_same_pictures(world, vanilla_dir):
    import vf1_line_break as lb
    f = gf.Fonts(vanilla_dir).font("SegoeUiBold18")
    text = "Happy birthday " + EMOJI[0] + EMOJI[1] + " to the whole family " + EMOJI[2] + "!"
    data = vf1_text.encode(text)
    ratio = lb.justify_ratio((vanilla_dir / "Virtual Families.exe").read_bytes())
    got, blits = world.wrap(data, 160, limit=50_000_000)
    want, draws = lb.wrap(f, text, 0, 0, 160, ratio)
    assert got == want
    layout = []
    for piece, x, y in draws:
        layout += f.layout(piece, x, y)
    same_pixels(world, blits, layout)


def test_a_country_flag_takes_the_text_colour(world):
    """A flag's two letters have no colour of their own (Segoe UI Emoji has no flag pictures), so they are drawn by
    GDI on the tinted pages, in the text's colour, as any letter (FP's raster_colour; VV shows them as letters)."""
    blits = world.draw(vf1_text.encode(EMOJI[3]), "SegoeUiBold18", colour=0xFF0000FF)       # red
    assert blits
    import vf1_picture_image as pi
    for kind, surface, box, _ in blits:
        info = world.surfaces[surface]
        piece = pi.Image(info["w"], info["h"], world.surface_pixels(surface)).sub(*box)
        inked = [piece.data[i:i + 3] for i in range(0, len(piece.data), 4) if piece.data[i + 3]]
        assert inked and all(px == b"\xff\x00\x00" for px in inked)


@pytest.mark.parametrize("font", ["SegoeUiBold18", "SegoeUi33"])
def test_any_letter_from_a_colour_font_is_in_colour(dll, vanilla_dir, font):
    """FP's rule, the shared spec's: a letter whose chain face is a colour font is drawn in its own colours even when
    the emoji table does not list it, in the game as in the tool, untinted. With the Unicode 18.0 table no installed
    font has such a letter in the plain chain (test_unicode18), so the chain's first face is a colour font here: Use
    Unicode Font with Segoe UI Emoji, and the copyright sign (an emoji shown as text by default)."""
    need_colour()
    import text_emu
    import vf1_emoji
    letter = "©"
    assert not vf1_emoji.is_colour_emoji(letter)
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll.parent / "vf1font.dll", vanilla_dir, install=True,
                           real_gdi=True, ini={("UnicodeFont", "Face"): gc.EMOJI_FACE})
    assert w.installed == 1
    f = gf.Fonts(vanilla_dir).font(font).with_unicode_font(gc.EMOJI_FACE)
    glyph = f.glyph(letter)
    assert glyph.kind == "colour emoji" and glyph.colour and glyph.face == gc.EMOJI_FACE
    for colour in (0xFFFFFFFF, 0xFF2040C0):
        same_pixels(w, w.draw(vf1_text.encode(letter), font, colour=colour), f.layout(letter))
    assert any(c[5] == letter for c in w.colour_calls)


def test_the_colour_test_is_fps():
    white = bytes((200, 200, 200, 200)) * 4                     # premultiplied white ink
    assert not gc.has_colour(white)
    assert not gc.has_colour(bytes((0, 0, 0, 15)))              # too faint to count
    assert gc.has_colour(white + bytes((0, 0, 0, 255)))          # black: the font's own colour
    assert gc.has_colour(bytes((10, 120, 200, 200)))


def test_the_fallback_chain_is_the_shared_spec_in_both():
    import re
    spec = ("Segoe UI Historic", "Segoe UI Symbol", "Segoe UI Emoji", "Yu Gothic", "Meiryo", "Microsoft YaHei",
            "Microsoft JhengHei", "Malgun Gothic", "SimSun-ExtB", "Nirmala UI", "Ebrima", "Gadugi", "Leelawadee UI",
            "Myanmar Text", "Javanese Text", "Mongolian Baiti", "Microsoft Himalaya", "Microsoft Yi Baiti",
            "Microsoft New Tai Lue", "Microsoft Tai Le", "Microsoft PhagsPa", "Sylfaen", "Cambria Math", "Noto Sans",
            "Noto Sans Symbols", "Noto Sans Symbols 2", "Noto Sans CJK JP", "Noto Sans CJK SC", "Noto Sans Math",
            "Noto Sans Cuneiform", "Noto Color Emoji",
            "Unifont", "Unifont Upper", "Noto Serif Tangut", "Last Resort High-Efficiency")   # shipped: last
    src = (ROOT / "native" / "vf1text" / "glyph_gdi.inc").read_text(encoding="utf-8")
    table = src[src.index("FallbackFaces[] = {"):]
    table = table[:table.index("};")]
    assert tuple(re.findall(r'L"([^"]+)"', table)) == g.FALLBACK_FACES == spec
    assert g.UNICODE_FONT_FALLBACKS == ("Segoe UI",) + spec


def test_switched_off_in_settings_ini_the_emoji_are_black_and_white(dll, vanilla_dir):
    need_colour()
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True, real_gdi=True,
                           ini={("UnicodeText", "ColourEmoji"): "0"})
    f = gf.Fonts(vanilla_dir).font("SegoeUiBold18")
    f.colour_emoji = False
    name = "Mia " + EMOJI[0] + EMOJI[1]
    blits = w.draw(vf1_text.encode(name), "SegoeUiBold18")
    same_pixels(w, blits, f.layout(name))
    assert w.colour_calls == [] and "TextOutW" in w.gdi_calls


def blitted(world, blits):
    """Each blit's kind, size, place and blitted pixels (all four channels); the game's own sheet by its box."""
    import vf1_picture_image as pi
    out = []
    for blit in blits:
        kind, surface, box, place = blit[:4]
        info = world.surfaces.get(surface)
        if info is None:
            out.append((kind, tuple(box), place, "game"))
            continue
        sheet = pi.Image(info["w"], info["h"], world.surface_pixels(surface))
        out.append((kind, tuple(box[2:]), place, bytes(sheet.sub(*box).data)))
    return out


NON_EMOJI_TEXT = ["Zoë Ångström", "Çağrı Nguyễn", "日本語のテキスト 한국어", "Ελληνικά Кириллица", "\U0001208D ❤ ☃ ☹ ★",
                  "é ä ﬁ ½ ™", "Thai ภาษาไทย 中文"]


def test_text_without_emoji_is_drawn_exactly_as_with_colour_emoji_off(world, dll, vanilla_dir):
    """Colour emoji change nothing else: text without a colour emoji (accents, Japanese, Korean, Greek, Cuneiform,
    the text-style ❤ and ☃) is drawn by the DLL with ColourEmoji on exactly as with it off (the code before colour
    emoji): every blit's kind, place, box and pixel, in all four fonts, white, a colour and see-through, and the
    word wrapper's lines; no colour picture is asked for."""
    import text_emu
    off = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True, real_gdi=True,
                             ini={("UnicodeText", "ColourEmoji"): "0"})
    before = len(world.colour_calls)
    for font in gf.GAME_FONTS:
        for text in NON_EMOJI_TEXT:
            data = vf1_text.encode(text)
            for colour in (0xFFFFFFFF, 0xFF2040C0, 0x80FFFFFF):
                assert blitted(world, world.draw(data, font, 3, 4, colour)) == \
                    blitted(off, off.draw(data, font, 3, 4, colour)), (font, text, hex(colour))
            assert world.width(data, font) == off.width(data, font)
    sentence = vf1_text.encode("Zoë and 日本語 went to the 한국어 market with ❤ and ☃ for Ελληνικά friends today")
    on_r, on_b = world.wrap(sentence, 160, limit=50_000_000)
    off_r, off_b = off.wrap(sentence, 160, limit=50_000_000)
    assert on_r == off_r and blitted(world, on_b) == blitted(off, off_b)
    assert len(world.colour_calls) == before and off.colour_calls == []


def test_without_direct2d_the_emoji_are_black_and_white(dll, vanilla_dir):
    need_colour()
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True, real_gdi=True)
    w.direct2d = False
    f = gf.Fonts(vanilla_dir).font("SegoeUiBold18")
    f.colour_emoji = False
    name = "Mia " + EMOJI[0]
    blits = w.draw(vf1_text.encode(name), "SegoeUiBold18")
    same_pixels(w, blits, f.layout(name))
    assert w.colour_calls == []


def test_vf1font_draws_emoji_in_colour_too(dll, vanilla_dir):
    need_colour()
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll.parent / "vf1font.dll", vanilla_dir, install=True,
                           real_gdi=True, ini={("UnicodeFont", "Face"): "Segoe UI"})
    assert w.installed == 1
    f = gf.Fonts(vanilla_dir).font("SegoeUiBold24").with_unicode_font("Segoe UI")
    name = "Mia " + EMOJI[0] + EMOJI[3]
    blits = w.draw(vf1_text.encode(name), "SegoeUiBold24", x=1, y=1)
    same_pixels(w, blits, f.layout(name, 1, 1))
    assert w.colour_calls and w.colour_calls[0][2] == f.override[1]       # the fitted em


def test_the_game_text_tool_labels_colour_emoji(vanilla_dir):
    need_colour()
    import vf1_game_text as gt
    f = gf.Fonts(vanilla_dir).font("SegoeUiBold18")
    assert "(colour emoji: Segoe UI Emoji)" in gt.describe(f, 0x1F600)
    assert "colour emoji" not in gt.describe(f, 0x2764)
