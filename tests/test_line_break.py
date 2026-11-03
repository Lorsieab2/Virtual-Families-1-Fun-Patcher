"""Line breaking for every script (native/vf1text/wrap.inc, patcher/vf1_line_break.py): the game's justified word
wrapper 0x409D70 run in Unicorn on the REAL vanilla executable, stock and with the REAL vf1text.dll / vf1font.dll,
their GDI and ICU calls made by this machine's real GDI and ICU (tests/text_emu.py).

* Stock text is laid out exactly as before: every blit (source sheet, box, place) and the returned height of the
  stock code and the patched game are equal, for the game's own strings and paragraphs, in every font; and the
  patcher's model of the stock algorithm (vf1_line_break.wrap, patched=False) gives the same places, so the model is
  the stock code.
* Japanese, Chinese, Korean, Thai, emoji and mixed text wrap where UAX #14 allows (Windows' ICU), with the kinsoku
  rules, never inside a whole character; the DLL's layout equals the model's, letter for letter and pixel for pixel;
  without icu.dll the built-in table does the same as the model's table.
* A word wider than the whole line (the stock code loops for ever on it) is cut between whole characters.
"""
import re
import struct

import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import vf1_game_fonts as gf  # noqa: E402
import vf1_line_break as lb  # noqa: E402
import vf1_text  # noqa: E402
from test_vf1_unicode_text import dll, VCVARS  # noqa: E402,F401  (the module-scoped build)

FONTS = gf.GAME_FONTS
WIDTH = 0x1B0            # the event dialog's lines (0x419E43)

PARAGRAPHS = [
    "Your family has grown! A new baby has arrived, and everyone in the house is very happy about it. "
    "Make sure the baby is fed, changed and put to bed on time, or it will start to cry.",
    "The plumbing is broken again. Call the plumber, or fix it yourself... if you dare? It costs $1,250.00 to fix.",
    "Line one.\nLine two, after a break.\n\n  Indented after two breaks, with   extra   spaces inside.",
    "Short.",
    "A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z and 1,000,000 dollars? Yes. No... maybe.",
]

UNICODE_TEXTS = [
    "日本語の文章です。「こんにちは」と言"
    "った。子供たちは庄で遊んでいます。コ"
    "ーヒーを飲みながら、家族の写真を見ま"
    "した。",
    "我们的家庭很大，有很多孩子。他们每天"
    "都在花园里玩（和猫一起）。",
    "한국어 문장입니다. 아이들이 집에서 놀고 "
    "있습니다.",
    "สวัสดีครับผมชื่อสม"
    "ชายครอบครัวของเราม"
    "ีเด็กหลายคน",
    "Mia \U0001f600\U0001f44d\U0001f3fd\U0001f1ef\U0001f1f5\U0001f468‍\U0001f469‍\U0001f467 is happy "
    "today and \U0001f382\U0001f382\U0001f382\U0001f382\U0001f382\U0001f382\U0001f382\U0001f382.",
    "Welcome, 山田花子太郎次郎三郎四郎五郎! Your family "
    "has grown, and 山田 is now the head of the house.",
]

LONG_WORDS = [
    "Supercalifragilisticexpialidocious" * 3,
    "A short start, then " + "W" * 40 + " and an end.",
    "é" * 60,
]


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    return gf.Fonts(vanilla_dir)


@pytest.fixture(scope="module")
def ratio(vanilla_dir):
    return lb.justify_ratio((vanilla_dir / "Virtual Families.exe").read_bytes())


def _world(dll, vanilla_dir, install, **kw):
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=install, **kw)
    if install:
        assert w.installed == 1
    return w


@pytest.fixture(scope="module")
def stock(dll, vanilla_dir):
    return _world(dll, vanilla_dir, False)


@pytest.fixture(scope="module")
def patched(dll, vanilla_dir):
    return _world(dll, vanilla_dir, True)


@pytest.fixture(scope="module")
def unicode_world(dll, vanilla_dir):
    import vf1_glyph_gdi as g
    if not g.AVAILABLE or lb.icu() is None:
        pytest.skip("needs Windows with icu.dll")
    return _world(dll, vanilla_dir, True, real_gdi=True)


def exe_strings(vanilla_dir) -> list[str]:
    """The game's own sentences: printable ASCII runs with a space in the executable."""
    data = (vanilla_dir / "Virtual Families.exe").read_bytes()
    found = []
    for m in re.finditer(rb"[\x20-\x7e]{16,}", data):
        s = m.group().decode()
        if " " in s and "%" not in s and not s.startswith(" "):
            found.append(s)
    return sorted(set(found))


def model_blits(font, draws):
    """The blits the game makes for the model's pieces: (place, box) of every letter (box: source x, y, w, h for a
    game letter; width only otherwise)."""
    out = []
    for text, x, y in draws:
        for g, gx, gy in font.layout(text, x, y):
            out.append(((gx, gy), g.width))
    return out


def world_blits(blits):
    return [(b[3], b[2][2]) for b in blits]


def same_pixels(world, blits):
    """Blits with each source named by what it is (the game's tinted sheet or a patcher sheet), so two emulated
    processes can be compared: the same source, box and place is the same pixels."""
    tints = {v: k[1] for k, v in world.tints.items()}
    out = []
    for b in blits:
        source = ("tint", tints[b[1]]) if b[1] in tints else world.surfaces.get(b[1], {}).get("tag", b[1])
        out.append((b[0], source) + tuple(b[2:]))
    return out


# --------------------------------------------------------------------------- stock text: exactly as before
@pytest.mark.parametrize("font", FONTS)
def test_stock_paragraphs_are_laid_out_exactly_as_before(stock, patched, fonts, ratio, font):
    f = fonts.font(font)
    for text in PARAGRAPHS:
        data = text.encode()
        for width in (WIDTH, 300, 200):
            if not lb.stock_words_fit(f, text, width):
                continue
            r0, b0 = stock.wrap(data, width, font, x=11, y=7, limit=5_000_000)
            r1, b1 = patched.wrap(data, width, font, x=11, y=7, limit=5_000_000)
            assert (r1, same_pixels(patched, b1)) == (r0, same_pixels(stock, b0)), (text, width)
            assert patched.wrap(data, width, font, measure=True)[0] == stock.wrap(data, width, font, measure=True)[0]
            # the patcher's model of the stock code gives the same places
            got, draws = lb.wrap(f, text, 11, 7, width, ratio, patched=False)
            assert got == r0 and model_blits(f, draws) == world_blits(b0), (text, width)
            got, draws = lb.wrap(f, text, 11, 7, width, ratio)
            assert got == r0 and model_blits(f, draws) == world_blits(b0), (text, width)


def test_the_games_own_sentences_are_laid_out_exactly_as_before(stock, patched, fonts, ratio, vanilla_dir):
    f = fonts.font("SegoeUiBold18")
    texts = exe_strings(vanilla_dir)
    assert len(texts) > 100
    checked = 0
    for text in texts:
        if not lb.stock_words_fit(f, text, WIDTH):
            continue
        data = text.encode()
        r0, b0 = stock.wrap(data, WIDTH, limit=5_000_000)
        r1, b1 = patched.wrap(data, WIDTH, limit=5_000_000)
        assert (r1, same_pixels(patched, b1)) == (r0, same_pixels(stock, b0)), text
        got, draws = lb.wrap(f, text, 0, 0, WIDTH, ratio, patched=False)
        assert got == r0 and model_blits(f, draws) == world_blits(b0), text
        checked += 1
    assert checked > 100


# --------------------------------------------------------------------------- every script
def check_lines(font, text, draws, width, use_icu=True):
    """Every piece is whole characters; no line starts with a closing mark (kinsoku); the letters are all there, in
    order (the spaces at a line's wrap are the only ones left out)."""
    clusters = set()
    i = 0
    for c in vf1_text.clusters(text):
        clusters.add(i)
        i += len(c)
    clusters.add(len(text))
    at = 0
    lines: dict[int, list] = {}
    for piece, x, y in draws:
        start = text.find(piece, at)
        assert start >= 0, (piece, text)
        assert start in clusters and start + len(piece) in clusters, piece
        assert text[at:start].strip(" \n") == "", (text[at:start], piece)
        at = start + len(piece)
        lines.setdefault(y, []).append((x, piece))
    assert text[at:].strip(" \n") == ""
    for y, pieces in lines.items():
        first = sorted(pieces)[0][1]
        assert lb.fallback_class(ord(first[0])) != lb.CLOSING or first[0] in ".,!?:;)]}", first
        right = max(x + lb.advance(font, p) for x, p in pieces)
        left = min(x for x, p in pieces)
        multi = len(vf1_text.clusters("".join(p for _, p in sorted(pieces)))) > 1
        assert right - left <= width + font.spacing or not multi, (pieces, width)


@pytest.mark.parametrize("font", FONTS)
@pytest.mark.parametrize("width", [WIDTH, 160])
def test_scripts_without_spaces_wrap_as_the_patcher_does(unicode_world, fonts, ratio, font, width):
    f = fonts.font(font)
    for text in UNICODE_TEXTS:
        data = vf1_text.encode(text)
        got, blits = unicode_world.wrap(data, width, font, x=5, y=9, limit=50_000_000)
        want, draws = lb.wrap(f, text, 5, 9, width, ratio)
        assert got == want, text
        assert world_blits(blits) == model_blits(f, draws), text
        check_lines(f, text, draws, width)
        assert unicode_world.wrap(data, width, font, measure=True, limit=50_000_000)[0] == want
        assert want > f.height or lb.advance(f, text) <= width          # it did wrap


def test_japanese_wraps_at_icu_breaks_with_kinsoku(fonts, ratio):
    if lb.icu() is None:
        pytest.skip("needs icu.dll")
    text = UNICODE_TEXTS[0]
    breaks, any_letter = lb.break_points(text)
    assert any_letter and breaks
    for i in breaks:
        assert text[i] not in "。、」っー" and text[i - 1] != "「", (i, text[i - 1:i + 1])
    f = fonts.font("SegoeUiBold18")
    _, draws = lb.wrap(f, text, 0, 0, 120, ratio)
    assert len({y for _, _, y in draws}) > 3


def test_thai_breaks_between_words_not_letters():
    if lb.icu() is None:
        pytest.skip("needs icu.dll")
    text = "สวัสดีครับผม"     # สวัสดี ครับ ผม
    breaks, _ = lb.break_points(text)
    assert breaks == {6, 10}


def test_emoji_clusters_are_never_cut(unicode_world, fonts, ratio):
    f = fonts.font("SegoeUiBold18")
    text = ("\U0001f44d\U0001f3fd\U0001f1ef\U0001f1f5\U0001f468‍\U0001f469‍\U0001f467" * 6)
    data = vf1_text.encode(text)
    for width in (40, 60, 90):
        got, blits = unicode_world.wrap(data, width, limit=50_000_000)
        want, draws = lb.wrap(f, text, 0, 0, width, ratio)
        assert got == want and world_blits(blits) == model_blits(f, draws)
        check_lines(f, text, draws, width)


def test_without_icu_the_built_in_table_wraps(dll, vanilla_dir, fonts, ratio):
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows")
    w = _world(dll, vanilla_dir, True, real_gdi=True)
    w.icu = False
    f = fonts.font("SegoeUiBold18")
    for text in UNICODE_TEXTS[:2] + UNICODE_TEXTS[4:]:
        data = vf1_text.encode(text)
        got, blits = w.wrap(data, 160, limit=400_000_000)     # the first CJK text reads the word list once
        want, draws = lb.wrap(f, text, 0, 0, 160, ratio, use_icu=False)
        assert got == want and world_blits(blits) == model_blits(f, draws), text
        check_lines(f, text, draws, 160, use_icu=False)
    assert w.icu_calls == []


def test_a_zero_width_space_is_a_break_with_or_without_icu(dll, vanilla_dir, fonts, ratio):
    """UAX #14 LB8: a line may break after U+200B, between Latin letters too, with ICU and with the built-in table."""
    import vf1_glyph_gdi as g
    text = "Supercalifragilistic​expialidocious​Wonderful"
    assert lb.break_points(text, use_icu=False)[0] == {21, 36}
    if lb.icu() is not None:
        assert lb.break_points(text)[0] == {21, 36}
    if not g.AVAILABLE:
        pytest.skip("needs Windows")
    w = _world(dll, vanilla_dir, True, real_gdi=True)
    w.icu = False
    f = fonts.font("SegoeUiBold18")
    got, blits = w.wrap(vf1_text.encode(text), 200, limit=50_000_000)
    want, draws = lb.wrap(f, text, 0, 0, 200, ratio, use_icu=False)
    assert got == want and world_blits(blits) == model_blits(f, draws)
    lines: dict[int, str] = {}
    for piece, _, y in draws:
        lines[y] = lines.get(y, "") + piece
    assert len(lines) > 1                               # cut only at the zero-width spaces, never inside a word
    for line in lines.values():
        assert set(line.replace("​", " ").split()) <= {"Supercalifragilistic", "expialidocious", "Wonderful"}


def test_vf1font_wraps_the_same_way(dll, vanilla_dir, fonts, ratio):
    """Use Unicode Font (vf1font.dll, the same source): stock text as the stock code lays it out with its letters,
    Japanese and emoji text as the model with the chosen font."""
    import vf1_glyph_gdi as g
    if not g.AVAILABLE or lb.icu() is None:
        pytest.skip("needs Windows with icu.dll")
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll.parent / "vf1font.dll", vanilla_dir, install=True,
                           real_gdi=True, ini={("UnicodeFont", "Face"): "Segoe UI"})
    assert w.installed == 1
    f = fonts.font("SegoeUiBold18").with_unicode_font("Segoe UI")
    for text in [PARAGRAPHS[0], PARAGRAPHS[2], UNICODE_TEXTS[0], UNICODE_TEXTS[4], LONG_WORDS[1]]:
        data = vf1_text.encode(text)
        got, blits = w.wrap(data, 200, x=3, y=1, limit=50_000_000)
        want, draws = lb.wrap(f, text, 3, 1, 200, ratio)
        assert got == want, text
        assert world_blits(blits) == model_blits(f, draws), text
        check_lines(f, text, draws, 200)
        assert w.wrap(data, 200, measure=True, limit=50_000_000)[0] == want


# --------------------------------------------------------------------------- a word wider than the line
def test_the_stock_code_loops_for_ever_on_a_word_wider_than_the_line(stock):
    import kids_emu as K
    with pytest.raises(K.EmuError):
        stock.wrap(LONG_WORDS[0].encode(), WIDTH, limit=3_000_000)


@pytest.mark.parametrize("font", FONTS)
def test_a_word_wider_than_the_line_is_cut_between_whole_characters(patched, unicode_world, fonts, ratio, font):
    f = fonts.font(font)
    for text in LONG_WORDS:
        world = unicode_world if any(ord(c) > 0xFF for c in text) else patched
        got, blits = world.wrap(vf1_text.encode(text), 120, font, limit=50_000_000)
        want, draws = lb.wrap(f, text, 0, 0, 120, ratio)
        assert got == want and world_blits(blits) == model_blits(f, draws), text
        check_lines(f, text, draws, 120)
        assert len(draws) > 1


# --------------------------------------------------------------------------- the two tables
def test_the_dlls_built_in_table_is_the_patchers():
    src = (ROOT / "native" / "vf1text" / "linebreak.inc").read_text(encoding="utf-8")
    names = {"LbIdeographic": lb.IDEOGRAPHIC, "LbClosing": lb.CLOSING, "LbOpening": lb.OPENING}
    rows = [(int(a, 16), int(b, 16), names[c]) for a, b, c in
            re.findall(r"\{ (0x[0-9A-F]+), (0x[0-9A-F]+), (Lb\w+) \}", src)]
    assert tuple(rows) == lb.FALLBACK_RANGES
    for (a0, b0, _), (a1, _, _) in zip(rows, rows[1:]):
        assert a0 <= b0 < a1


def test_the_justify_ratio_is_the_games(ratio):
    assert 0.0 < ratio < 1.0
    assert struct.pack("<f", ratio)
