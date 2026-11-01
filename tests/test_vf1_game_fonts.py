"""Virtual Families 1's fonts, read from the game, and its text drawn as the game draws it (patcher/vf1_game_fonts.py,
the Game Text tool's preview): checked against the game's own code run in Unicorn (tests/text_emu.py)."""
import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import vf1_game_fonts as gf  # noqa: E402
import vf1_picture_image as pi  # noqa: E402

SAMPLES = [b"Hello, world!", b"The Smith Family", b"0123456789 $%&()", b"Line one\nand line two",
           bytes(range(0x20, 0x7F)), bytes(range(0xA2, 0x100)), b"Caf\xe9 \xc5ngstr\xf6m \xd8re"]


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    return gf.Fonts(vanilla_dir)


@pytest.fixture(scope="module")
def stock(vanilla_dir):
    """The vanilla game's text code (vf1text.dll is mapped but not installed)."""
    import text_emu
    return text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", _any_dll(), vanilla_dir, install=False)


def _any_dll():
    """The harness maps a DLL beside the game; for the stock game any small 32-bit DLL does (none of its code runs)."""
    for candidate in (ROOT / "build" / "vf1text.dll", ROOT / "patcher" / "payload" / "vf1logs.dll",
                      ROOT / "patcher" / "payload" / "vf1kids.dll", ROOT / "patcher" / "payload" / "vf1fun.dll"):
        if candidate.is_file():
            return candidate
    pytest.skip("needs a built 32-bit DLL for the harness (native/build_text.bat or the payload DLLs)")


def test_the_four_fonts_are_found_in_the_program(fonts):
    assert fonts.found == {"SegoeUi33": (0x4EB6F0, 0), "SegoeUiBold17": (0x4EC610, 0),
                           "SegoeUiBold18": (0x4ED538, 0), "SegoeUiBold24": (0x4EE460, 0)}
    for name in gf.GAME_FONTS:
        f = fonts.font(name)
        assert f.in_game and f.metrics_from_game and len(f.rows) == 190
        assert {(r[0] & 0xFF) for r in f.rows} == set(gf.SHEET_ORDER)
        assert f.height == f.sheet.height
        assert f.rows[-1][3] == f.sheet.width          # the boxes cover the sheet exactly


def test_every_unused_sheet_is_offered_with_its_own_boxes(fonts):
    names = fonts.names()
    assert names[:4] == list(gf.GAME_FONTS)
    assert names[4:] == list(gf.UNUSED_FONTS)
    for name in gf.UNUSED_FONTS:
        f = fonts.font(name)
        assert not f.in_game and not f.metrics_from_game and "metrics not from the game" in f.label
        assert len(f.rows) == 190 and f.rows[0][1] == 0 and f.rows[-1][3] == f.sheet.width
        assert all(r[3] > r[1] for r in f.rows if r[0] != 0x20)
        assert f.render("Hamburg").width > 20


@pytest.mark.parametrize("name", gf.GAME_FONTS)
def test_the_layout_is_the_games(fonts, stock, name):
    """Every box and every place DrawString 0x409660 draws, and GetWidth 0x402320, for the stock characters."""
    f = fonts.font(name)
    for data in SAMPLES:
        text = data.decode("latin-1")
        blits = stock.draw(data, name, x=5, y=7)
        ours = [(g.image, x + 5, y + 7) for g, x, y in f.layout(text)]
        assert len(blits) == len(ours)
        for (kind, _surface, (sx, sy, w, h), (dx, dy)), (image, x, y) in zip(blits, ours):
            assert kind == "blit" and (dx, dy) == (x, y) and (w, h) == (image.width, image.height)
            assert f.sheet.sub(sx, sy, w, h) == image
        assert stock.width(data, name) == f.width(text)
        assert stock.width(data, name, 1.5) == f.width(text, 1.5)


def test_a_see_through_colour_goes_through_blit_rect_with_alpha(fonts, stock):
    blits = stock.draw(b"Hi", "SegoeUiBold18", colour=0x80FFFFFF)
    assert [b[0] for b in blits] == ["alpha", "alpha"]
    assert abs(blits[0][4] - 128 / 255) < 1e-6
    assert stock.draw(b"Hi", "SegoeUiBold18", colour=0x00123456) == stock.draw(b"Hi", "SegoeUiBold18")


def test_the_counted_draw_is_the_same_layout(fonts, stock):
    f = fonts.font("SegoeUiBold18")
    width, blits = stock.draw_n(b"Hello there", 5)
    assert width == f.width("Hello") and len(blits) == 5
    width, blits = stock.draw_n(b"Hello there", 11, measure=True)
    assert width == f.width("Hello there") and blits == []


def test_tint_is_the_games_and(fonts):
    f = fonts.font("SegoeUiBold18")
    white = f.render("A")
    red = f.render("A", 0xFF2040E0)
    for i in range(0, len(white.data), 4):
        assert red.data[i:i + 4] == bytes((white.data[i] & 0xE0, white.data[i + 1] & 0x40,
                                           white.data[i + 2] & 0x20, white.data[i + 3]))


def test_the_stock_game_draws_utf8_names_as_latin1_letters_without_harm(fonts, stock):
    """Proof for the setting's description: a UTF-8 name in the stock game is drawn byte by byte, each byte the
    game's Latin-1 letter (bytes 0x80..0xA1, which no sheet has, as row 0, "!"), and nothing breaks."""
    import vf1_game_text as tool
    f = fonts.font("SegoeUiBold18")
    for text in ["Zoë", "İlkay Ğül", "日本語", "\U0001202d \U0001f44d\U0001f3fd",
                 "Łukasz Šárka Đặng"]:
        data = text.encode("utf-8")
        blits = stock.draw(data, "SegoeUiBold18")
        expected = [f.box(b) for b in data]
        assert [(b[2][0], b[2][0] + b[2][2]) for b in blits] == [(l, r) for l, _t, r, _b in expected]
        assert stock.width(data) == sum(r - l for l, _t, r, _b in expected)
        picture = tool.stock_picture(f, text, 0xFFFFFFFF)
        assert picture.width == stock.width(data)


def test_unknown_bytes_draw_row_zero_as_the_game(fonts, stock):
    f = fonts.font("SegoeUi33")
    blits = stock.draw(b"\x01\x85\xa1", "SegoeUi33")
    assert [b[2][0] for b in blits] == [f.rows[0][1]] * 3
    assert [f.glyph(c).image for c in "\x01\x85"] == [f.game_glyph(0).image] * 2


def test_glyph_files_are_well_formed():
    for name in gf.GAME_FONTS:
        g = gf.load_glyph_file(name)
        assert g is not None and g.sheet is not None and len(g.boxes) > 2500
        for letter, (x, y, w, how) in g.boxes.items():
            assert 0 <= x and x + w <= g.sheet.width and 0 <= y and w > 0, letter
            assert how in ("composed", "drawn", "game-shape"), how
        assert g.sheet.width == 2048 and len(g.style.lut) == 256
        # Windows-1252, Latin Extended-A, Greek and Cyrillic are all there
        for cp in [0x20AC, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2013, 0x2014, 0x0152, 0x0153, 0x0160, 0x0178]:
            assert chr(cp) in g.boxes, hex(cp)
        assert all(chr(cp) in g.boxes for cp in range(0x0100, 0x0180))
        assert all(chr(cp) in g.boxes for cp in range(0x0410, 0x0450))
        assert all(chr(cp) in g.boxes for cp in range(0x03B1, 0x03CA))
    for name in gf.UNUSED_FONTS:
        g = gf.load_glyph_file(name)
        assert g is not None and len(g.metrics) == 190 and not g.boxes


def test_accented_letters_are_built_from_the_games_own_pixels(fonts):
    """A composed letter keeps the game's base letter pixel for pixel: Ā is the game's A with a mark above."""
    f = fonts.font("SegoeUiBold24")
    base = f.game_glyph(ord("A")).image
    made = f.glyph("Ā")
    assert made.kind == "patcher-made"
    assert made.image.width == base.width
    hb = f.glyph("A").image
    rows_a = [bytes(hb.data[y * hb.width * 4 + 3:(y + 1) * hb.width * 4:4]) for y in range(hb.height)]
    rows_m = [bytes(made.image.data[y * hb.width * 4 + 3:(y + 1) * hb.width * 4:4]) for y in range(hb.height)]
    top = next(y for y, row in enumerate(rows_a) if any(row))
    assert rows_m[top:] == rows_a[top:]                     # the letter itself is the game's (its coverage)
    assert any(any(r) for r in rows_m[:top])                # and the mark sits above it
    # the same for a Cyrillic letter drawn like a Latin one
    assert bytes(f.glyph("А").image.data[3::4]) == bytes(base.data[3::4])


def test_the_tool_preview_matches_the_layout(fonts):
    f = fonts.font("SegoeUiBold18")
    picture = f.render("Zoë\nLine 2", 0xFF000000)
    assert picture.width == f.width("Zoë\nLine 2") and picture.height == 2 * f.height
    assert isinstance(picture, pi.Image)
