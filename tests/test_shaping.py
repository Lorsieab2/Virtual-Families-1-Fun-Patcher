"""Shaped and right-to-left scripts (native/vf1text/shape.inc, patcher/vf1_shaping.py): Arabic, Hebrew, the Indic
scripts, Thai and the others are drawn a RUN at a time, shaped and in visual order, by the REAL vf1text.dll and
vf1font.dll on the REAL executable in Unicorn, their GDI calls made by this machine's real GDI (tests/text_emu.py),
exactly as the patcher's model (vf1_game_fonts / vf1_line_break) draws them, pixel for pixel.

* The rule: a run is letters of one script, their marks and the spaces between two of its words; Latin, digits
  and punctuation end it; Hebrew and Arabic are separate runs; a run is at most 64 characters, cut at a space.
* Shaped: Arabic letters join (the run is not its isolated letters side by side); Devanagari conjuncts form.
* Visual order: a Hebrew word's first letter is drawn at its right.
* Every place, box and pixel the DLL draws equals the model's, in all four fonts, with both DLLs, for DrawString,
  GetWidth and the word wrapper; a right-to-left phrase wraps whole words per line, each line one run.
* Backspace still removes one whole character; the run is drawn again from what is left.
* Text with no such letter is drawn exactly as before (the model's pieces are the whole characters)."""
import os
import subprocess

import pytest

from conftest import ROOT

import vf1_shaping as sh
import vf1_text

ARABIC = "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645"            # مرحبا بالعالم
HEBREW = "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd"                                     # שלום עולם
DEVANAGARI = "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e"          # नमस्ते दुनिया
THAI = "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e04\u0e23\u0e31\u0e1a"
BENGALI = "\u09ac\u09be\u0982\u09b2\u09be"
TAMIL = "\u0ba4\u0bae\u0bbf\u0bb4\u0bcd"
MIXED = "Hi " + ARABIC + " and " + HEBREW + " 123!"
TEXTS = [ARABIC, HEBREW, DEVANAGARI, THAI, BENGALI, TAMIL, MIXED, "\u0645\u064e\u0631\u0652\u062d\u064e\u0628\u064b\u0627"]
LONG_ARABIC = " ".join([ARABIC] * 6)


# --------------------------------------------------------------------------- the rule
def test_a_run_takes_its_scripts_letters_and_inner_spaces():
    yes = lambda run: True                                       # noqa: E731
    assert sh.pieces(ARABIC, yes) == [ARABIC]
    assert sh.pieces("x" + HEBREW + ".", yes) == ["x", HEBREW, "."]
    assert sh.pieces(ARABIC + " " + HEBREW, yes) == [ARABIC, " ", HEBREW]          # two scripts: two runs
    assert sh.pieces(ARABIC + "  ", yes) == [ARABIC, " ", " "]                     # trailing spaces stay the game's
    assert sh.pieces(MIXED, yes)[:4] == ["H", "i", " ", ARABIC]
    assert sh.pieces("Zo\u00eb \u65e5\u672c", yes) == vf1_text.clusters("Zo\u00eb \u65e5\u672c", draw=True)
    assert sh.pieces(ARABIC, lambda run: False) == vf1_text.clusters(ARABIC, draw=True)   # no face: as before


def test_a_long_run_is_cut_at_a_space():
    pieces = sh.pieces(LONG_ARABIC, lambda run: True)
    assert len(pieces) > 1 and "".join(pieces) == LONG_ARABIC
    for p in pieces:
        assert len(vf1_text.clusters(p)) <= sh.MAX_RUN_CLUSTERS and len(p.encode()) <= sh.MAX_RUN_BYTES
    assert pieces[1] == " "                                       # the cut is at a space


def test_rtl_phrases():
    assert sh.has_rtl_phrase(ARABIC) and sh.has_rtl_phrase(HEBREW)
    assert not sh.has_rtl_phrase(DEVANAGARI) and not sh.has_rtl_phrase("Hello there " + ARABIC[:5])


# --------------------------------------------------------------------------- the patcher's drawing
@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    import vf1_game_fonts as gf
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows GDI")
    return gf.Fonts(vanilla_dir)


def test_arabic_is_shaped_and_hebrew_is_in_visual_order(fonts):
    f = fonts.font("SegoeUiBold24")
    word = ARABIC[:5]
    run = f.glyph(word)
    isolated = [f.glyph(c) for c in word]
    assert run.kind == "drawn by Windows"
    assert run.width != sum(g.width for g in isolated) or \
        bytes(run.image.data[3::4]) != b"".join(bytes(g.image.data[3::4]) for g in isolated)
    # Hebrew: shin is the first letter in memory and is drawn at the right of the word
    shin, lamed = f.glyph("\u05e9"), f.glyph("\u05dc")
    both = f.glyph("\u05e9\u05dc").image

    def ink(img, x0, x1):
        return sum(img.data[(y * img.width + x) * 4 + 3] for y in range(img.height) for x in range(x0, x1))
    right = ink(both, both.width - shin.width, both.width)
    assert right > 0
    expect_shin = sum(shin.image.data[3::4])
    assert abs(right - expect_shin) < abs(right - sum(lamed.image.data[3::4])) or right == expect_shin


# --------------------------------------------------------------------------- the real DLLs
def _build(tmp_path_factory):
    vcvars = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat"
    if os.name != "nt" or not os.path.isfile(vcvars):
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("shape_build")
    installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             "Microsoft Visual Studio", "Installer")
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}", VF1_BUILD_DIR=str(out))
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _build(tmp_path_factory)


@pytest.fixture(scope="module")
def world(built, vanilla_dir, fonts):
    pytest.importorskip("unicorn")
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", built / "vf1text.dll", vanilla_dir, install=True,
                           real_gdi=True)
    assert w.installed == 1
    return w


def _same(world, blits, layout, what):
    import vf1_picture_image as pi
    assert len(blits) == len(layout), what
    for (kind, surface, box, place), (glyph, x, y) in zip([b[:4] for b in blits], layout):
        assert place == (x, y) and box[2] == glyph.width, what
        if glyph.kind == "game":
            continue
        info = world.surfaces[surface]
        piece = pi.Image(info["w"], info["h"], world.surface_pixels(surface)).sub(*box)
        assert bytes(piece.data[3::4]) == bytes(glyph.image.data[3::4]), (what, glyph.kind)


@pytest.mark.parametrize("font", ["SegoeUiBold18", "SegoeUiBold17", "SegoeUiBold24", "SegoeUi33"])
def test_the_dll_draws_every_run_as_the_patcher_does(world, fonts, font):
    f = fonts.font(font)
    for text in TEXTS:
        data = vf1_text.encode(text)
        _same(world, world.draw(data, font, x=3, y=4), f.layout(text, 3, 4), (font, text))
        assert world.width(data, font) == f.width(text), (font, text)
        runs = [p for p in f.letters(text) if len(vf1_text.clusters(p)) > 1]
        assert runs, text                                         # it was drawn as runs


@pytest.mark.parametrize("width", [432, 160, 90])
def test_a_right_to_left_phrase_wraps_as_whole_runs(world, fonts, width, vanilla_dir):
    import vf1_line_break as lb
    ratio = lb.justify_ratio((vanilla_dir / "Virtual Families.exe").read_bytes())
    f = fonts.font("SegoeUiBold18")
    for text in (LONG_ARABIC, HEBREW + " " + HEBREW + " " + HEBREW, "The word " + HEBREW + " means peace."):
        got, blits = world.wrap(vf1_text.encode(text), width, "SegoeUiBold18", x=5, y=9, limit=200_000_000)
        want, draws = lb.wrap(f, text, 5, 9, width, ratio)
        assert got == want, (text, width)
        model = [(g, gx, gy) for piece, x, y in draws for g, gx, gy in f.layout(piece, x, y)]
        _same(world, blits, model, (text, width))
        # each line's right-to-left words are one piece, and the lines keep the words' logical order
        words = [w for piece, _x, _y in draws for w in piece.split()]
        assert words == [w for w in text.split()], (text, width)


def test_backspace_removes_one_whole_character_and_the_run_is_drawn_again(world, fonts):
    import test_vf1_unicode_text as vt
    box = world.text_box(60)
    vt.type_into(world, box, ARABIC)
    assert vf1_text.decode(world.box_text(box)) == ARABIC
    world.key(box, 8)
    left = ARABIC[:-1]
    assert vf1_text.decode(world.box_text(box)) == left
    f = fonts.font("SegoeUiBold18")
    _same(world, world.draw(world.box_text(box), "SegoeUiBold18"), f.layout(left), "after Backspace")


def test_vf1font_draws_runs_in_the_chosen_face(built, vanilla_dir, fonts):
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", built / "vf1font.dll", vanilla_dir, install=True,
                           real_gdi=True)
    assert w.installed == 1
    for text in (ARABIC, DEVANAGARI, MIXED):
        blits = w.draw(vf1_text.encode(text), "SegoeUiBold18")
        assert len(blits) < len(vf1_text.clusters(text)), text      # runs, not one picture per character
