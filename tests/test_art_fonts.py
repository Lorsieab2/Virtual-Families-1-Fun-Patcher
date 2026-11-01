"""The Picture Maker's fonts (patcher/vf1_art_fonts.py).

Without the game: a synthetic Images folder (font strips of the right sizes, every glyph its own alpha) checks
the catalogue's entries, the glyph rectangles, the text layout (alignment, new lines, characters with no
glyph, colours, alpha) and the tint's pixels.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read): tests/fonts_emu.py runs the game's own font
maker 0x44FC90 (the four font constructors and the loader 0x402720) and its text drawer 0x409660 (with the
alignments 0x409CC0 / 0x409CD0 / 0x409D20, the width 0x402320 and the tint 0x402940) in Unicorn: the files it
asks for, the glyph rectangles and character index it builds, every glyph draw it makes (picture, tint,
rectangle, place, alpha, scale) and every tinted copy's pixels must equal the module's.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import vf1_art_fonts as af
import vf1_game_art as ga
import vf1_picture_image as pi

SAMPLES = (
    af.SAMPLE_TEXT,
    "Virtual Families",
    "Two lines\nof text",
    "No glyph: \x85\x01\t end",
    "\xc9t\xe9 \xa3 \xbf \xff",
    "",
    "\nstarts on a new line",
)
COLOURS = (0, af.WHITE, af.BLACK, 0xFF804C05, 0xFF555555, 0xFFEFEFEF, 0x80646464, 0x01FFFFFF, 0x7F0000FF)


# ------------------------------------------------------------------ a synthetic game folder
def _strip(font: af.GameFont) -> pi.Image:
    """The font's strip: glyph k is a box of colour (k, 255 - k, 7, alpha 1 + k) one pixel in from its edges."""
    table = af.glyph_table(font)
    img = pi.Image(table[-1][1][2], font.height)
    for k, (_code, (l, t, r, b)) in enumerate(table):
        for y in range(t + 1, b - 1):
            for x in range(l + 1, r - 1):
                at = (y * img.width + x) * 4
                img.data[at:at + 4] = bytes((k, 255 - k, 7, 1 + k))
    return img


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory) -> ga.GameFiles:
    root = tmp_path_factory.mktemp("game")
    images = root / "Images"
    images.mkdir()
    for font in af.FONTS.values():
        (images / font.file.lower()).write_bytes(pi.encode_png(_strip(font)))        # any case is found
    for name in list(af.X512) + list(af.OTHER_FILES):
        (images / name).write_bytes(pi.encode_png(pi.Image(8, 4)))
    return ga.GameFiles(root)


def test_catalogue_entries(synthetic):
    arts = af.arts(synthetic)
    keys = [a.key for a in arts]
    assert len(keys) == len(set(keys))
    assert all(k.startswith("fonts/") for k in keys)
    assert all(a.category.split("/")[0] in ga.CATEGORY_ORDER for a in arts)
    per_font = {f.cls: [a for a in arts if a.key.startswith(af._key(f.cls) + "/")] for f in af.FONTS.values()}
    for font in af.FONTS.values():
        mine = per_font[font.cls]
        glyphs = [a for a in mine if "/glyph/" in a.key]
        samples = [a for a in mine if "/sample/" in a.key]
        assert len(glyphs) == 190
        assert len(samples) == len(font.colours)
        assert all(a.used == font.used for a in glyphs + [a for a in mine if a.key.endswith("/whole")])
        assert all(a.used for a in samples)
        for a in glyphs:
            (layer,) = a.layers
            l, t, r, b = layer.rect
            assert 0 <= l < r <= synthetic.size(font.file)[0] and (t, b) == (0, font.height)
    unused = [a for a in arts if a.key.endswith("/whole") and not any(a.key == af._key(f.cls) + "/whole"
                                                                      for f in af.FONTS.values())]
    assert len(unused) == len(af.X512) + len(af.OTHER_FILES)
    assert not any(a.used or a.checked for a in unused)
    assert all("No code loads it" in a.why for a in unused)
    # labels are plain words
    for a in arts:
        assert not re.search(r"0x[0-9A-Fa-f]", a.label), a.label
    labels = {a.label for a in per_font["SegoeUiBold18"]}
    assert {'Letter "A"', 'Digit "7"', "Space", 'Sign "!"', 'Letter "\xe9"', "Character 127 (no letter)",
            "Soft hyphen", "Whole picture", "Sample text in black"} <= labels


def test_catalogue_without_files(tmp_path):
    (tmp_path / "Images").mkdir()
    assert af.arts(ga.GameFiles(tmp_path)) == []


def test_layout_by_hand():
    font = af.FONTS["SegoeUiBold18"]
    table = dict(af.glyph_table(font))
    draws = af.text_layers(None, "SegoeUiBold18", "Ab\nc\x85 ", 100, 50)
    assert [d.rect for d in draws] == [table[ord("A")], table[ord("b")], table[ord("c")], table[ord("!")],
                                       table[ord(" ")]]
    wa = table[ord("A")][2] - table[ord("A")][0]
    wc = table[ord("c")][2] - table[ord("c")][0]
    assert [(d.x, d.y) for d in draws] == [(100, 50), (100 + wa, 50), (100, 68), (100 + wc, 68),
                                           (100 + wc + table[ord("!")][2], 68)]
    assert all(type(d) is pi.Draw and d.alpha == 1.0 and d.scale == 1.0 for d in draws)
    width = af.string_width(font, "Ab\nc")
    assert width == max(wa + table[ord("b")][2] - table[ord("b")][0], wc)
    right = af.text_layers(None, font, "Ab\nc", 100, 0, align="right")
    centre = af.text_layers(None, font, "Ab\nc", 100, 0, align="centre")
    assert right[0].x == 100 - width and centre[0].x == 100 - width // 2
    assert af.text_layers(None, font, "", 0, 0) == [] and af.string_width(font, "") == 0
    assert af.text_layers(None, font, "a\0b", 0, 0)[-1].rect == table[ord("a")]
    with pytest.raises(ValueError):
        af.text_layers(None, font, "a", 0, 0, align="middle")


def test_colours():
    assert af.colour_parts(0) == ((255, 255, 255), 1.0)                 # alpha 0: the default white
    assert af.colour_parts(0x00123456) == ((255, 255, 255), 1.0)
    assert af.colour_parts(0xFF804C05) == ((5, 76, 128), 1.0)
    assert af.colour_parts(0x80646464) == ((100, 100, 100), pi.f32(128 / 255))
    (black,) = af.text_layers(None, "SegoeUiBold24", "x", 0, 0, af.BLACK)
    assert isinstance(black, af.TintedDraw) and black.tint == (0, 0, 0)
    (white,) = af.text_layers(None, "SegoeUiBold24", "x", 0, 0, af.WHITE)
    assert type(white) is pi.Draw


def test_tint_and_render(synthetic):
    font = af.FONTS["SegoeUiBold17"]
    strip = synthetic.image(font.file)
    t = af.tinted(strip, (0x0F, 0xF0, 0xFF))
    for at in range(0, len(strip.data), 4):
        r, g, b, a = strip.data[at:at + 4]
        assert tuple(t.data[at:at + 4]) == (r & 0x0F, g & 0xF0, b, a)
    layers = af.text_layers(synthetic, font, "AB", 0, 0, 0x80FF00FF)
    img = af.render_text(synthetic, layers)
    k = af.CHARS.index(ord("A"))
    weight = int(128 / 255 * 255 + 0.5)
    assert img.pixel(1, 1) == (k & 0xFF, 0, 7, ((1 + k) * weight + 0x7F) >> 8)
    assert img.width == af.string_width(font, "AB") and img.height == font.height


# ------------------------------------------------------------------ against the game
@pytest.fixture(scope="module")
def game() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    return Path(value).resolve()


@pytest.fixture(scope="module")
def files(game) -> ga.GameFiles:
    return ga.GameFiles(game)


@pytest.fixture(scope="module")
def emu(game, files):
    fonts_emu = pytest.importorskip("fonts_emu")

    def pixels(name):
        image = files.image(name)
        return image.width, image.height, bytes(image.data)
    return fonts_emu.FontEmu(game, pixels=pixels)


def _plan(draw) -> dict:
    return {"file": draw.file, "tint": tuple(getattr(draw, "tint", (255, 255, 255))), "rect": tuple(draw.rect),
            "x": draw.x, "y": draw.y, "alpha": draw.alpha, "scale": draw.scale}


def _game(rec) -> dict:
    return {k: rec[k] for k in ("file", "tint", "rect", "x", "y", "alpha", "scale")}


def test_the_game_loads_these_files_and_glyphs(emu):
    assert emu.asked == emu.loaded == ["SegoeUiBold17.png", "SegoeUiBold18.png", "SegoeUiBold24.png",
                                       "SegoeUi33.png"]
    for name, font in af.FONTS.items():
        assert emu.font_file(name) == font.file
        assert [(c & 0xFF, (l, t, r, b)) for c, l, t, r, b in emu.glyph_rows(name)] == af.glyph_table(font)
        assert emu.char_index(name) == af.char_index(font)
        assert emu.line_height(name) == font.height
    assert emu.default_font() == emu.fonts["SegoeUiBold24"]


def test_glyph_tables_in_the_exe(emu):
    for font in af.FONTS.values():
        rows = af.table_rows(emu.img, font.table)
        assert [(c & 0xFF, (l, t, r, b)) for c, l, t, r, b in rows] == af.glyph_table(font)


def test_text_draws_equal_the_game(emu):
    count = 0
    for name, font in af.FONTS.items():
        for text in SAMPLES:
            data = text.encode(af.ENCODING)
            assert emu.string_width(name, data) == af.string_width(font, text)
            for colour in COLOURS:
                for align in ("left", "right", "centre"):
                    got = [_game(r) for r in emu.draw_text(name, data, 1500, 1200, colour, align)]
                    want = [_plan(d) for d in af.text_layers(None, name, text, 1500, 1200, colour, align)]
                    assert got == want, (name, text, hex(colour), align)
                    count += len(got)
    assert count > 10_000


def test_default_font_draws(emu):
    for colour in (0, af.BLACK, 0xFF555555, 0xFFEFEFEF):
        got = [_game(r) for r in emu.draw_text(None, af.SAMPLE_TEXT.encode(), 300, 200, colour)]
        assert got == [_plan(d) for d in af.text_layers(None, "SegoeUiBold24", af.SAMPLE_TEXT, 300, 200, colour)]


def test_sample_arts_equal_the_game(emu, files):
    arts = {a.key: a for a in af.arts(files)}
    for name, font in af.FONTS.items():
        for colour, word, _why in font.colours:
            art = arts[f"{af._key(name)}/sample/{word.replace(' ', '-')}"]
            got = [_game(r) for r in emu.draw_text(name, af.SAMPLE_TEXT.encode(), 0, 0, colour)]
            assert got == [_plan(d) for d in art.layers]
            if colour != af.WHITE:
                assert all(r["how"] == "SDL_UpperBlit" for r in emu.draws)


def test_tinted_pixels_equal_the_game(emu, files):
    """Every tinted copy 0x402940 made in the tests above (its own pixel loop) equals vf1_art_fonts.tinted."""
    emu.draw_text("SegoeUiBold18", b"x", 10, 10, 0x80646464)
    seen = 0
    for name, font in af.FONTS.items():
        impl = emu.r32(emu.fonts[name] + 4)
        node = emu.r32(impl + 0x41C)
        while node:
            colour, surf = emu.r32(node), emu.r32(node + 4)
            rgb = (colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF)
            assert emu.surface_pixels(surf) == bytes(af.tinted(files.image(font.file), rgb).data), (name, hex(colour))
            seen += 1
            node = emu.r32(node + 8)
    assert seen >= 8


def test_unused_font_files_are_named_nowhere(emu, files):
    image = emu.img.lower()
    for name in list(af.X512) + list(af.OTHER_FILES):
        stem = name[:-4].lower().encode()
        assert stem not in image and stem.decode().encode("utf-16-le") not in image, name
        assert files.has(name), name
    assert b"x512" not in image
    for font in af.FONTS.values():
        assert image.count(font.cls.lower().encode() + b"\0") == 1
    # every font picture in the Images folder is listed
    listed = {n.lower() for n in af.font_files()}
    pattern = re.compile(r"(segoe|typewriter|cartoonist|burweed|arial)", re.I)
    assert {n for n in files.names() if pattern.search(n) and "/" not in n} == listed


def test_glyph_arts_render(files):
    arts = {a.key: a for a in af.arts(files)}
    art = arts["fonts/segoeuibold18/glyph/065"]
    img = ga.draw(files, art)
    assert (img.width, img.height) == (11, 18)
    whole = ga.draw(files, arts["fonts/segoeuibold18/whole"])
    assert (whole.width, whole.height) == files.size("SegoeUiBold18.png")
    assert af.draw_art(files, art) == img
    black = af.draw_art(files, arts["fonts/segoeuibold18/sample/black"])
    white = ga.draw(files, arts["fonts/segoeuibold18/sample/white"])
    assert (black.width, black.height) == (white.width, white.height) == (
        af.string_width(af.FONTS["SegoeUiBold18"], af.SAMPLE_TEXT), 18)
    assert black.data[3::4] == white.data[3::4]
    assert set(black.data[0::4]) == {0} and set(white.data[0::4][k] for k in range(len(white.data) // 4)
                                                 if white.data[4 * k + 3]) == {255}
