"""Render Unicode with In-Game Fonts (native/vf1text): the REAL compiled vf1text.dll on the REAL vanilla executable,
run in Unicorn (tests/text_emu.py), against the patcher's own reading of the same text (vf1_game_fonts, which
tests/test_vf1_game_fonts.py checks against the stock game's code).

Letters Windows draws on the spot (not shipped in payload\\UnicodeText) cannot be drawn inside the emulator;
tests/test_vf1_glyph_gdi.py runs the DLL's own drawing of those through 32-bit rundll32 instead."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import vf1_game_fonts as gf  # noqa: E402
import vf1_text  # noqa: E402

VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")
UNICODE_KEY = 0x40000000
# Names in the languages the shipped letters cover (all of them patcher-made or the game's own).
NAMES = ["Zo\u00eb Ch\u00e2telet", "\u0130lkay \u011e\u00fcl\u015fen", "\u0141ukasz \u017b\u00f3\u0142kiewski",
         "Nguy\u1ec5n \u0110\u1eb7ng", "\u0391\u03b8\u03b7\u03bd\u03ac", "\u0410\u043d\u043d\u0430 \u041f\u0435\u0442\u0440\u043e\u0432\u0430",
         "\u201cSmith\u201d \u2013 \u20ac5 \u2026", "Caf\u00e9 \u0160ar\u00e1", "\u00a1Ol\u00e9!"]


def build_env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


@pytest.fixture(scope="module")
def dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("text_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=dict(build_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr          # /W4 /WX
    return out / "vf1text.dll"


@pytest.fixture(scope="module")
def world(dll, vanilla_dir):
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True)
    assert w.installed == 1
    return w


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    return gf.Fonts(vanilla_dir)


def expected(fonts, name, text, x=0, y=0):
    """The patcher's layout of `text`: (source sheet tag or game, source box, place)."""
    f = fonts.font(name)
    out = []
    for g, gx, gy in f.layout(text, x, y):
        out.append((g.kind, g.width, (gx, gy), g.image))
    return out


def sheet_piece(world, surface, box):
    """The pixels of `box` on an emulated surface (the shipped sheet IMG_Load gave the DLL, or the game's)."""
    import vf1_picture_image as pi
    info = world.surfaces[surface]
    sx, sy, w, h = box
    data = world.surface_pixels(surface)
    whole = pi.Image(info["w"], info["h"], data)
    return whole.sub(sx, sy, w, h)


# --------------------------------------------------------------------------- drawing
def test_installs_all_six_sites_or_nothing(dll, vanilla_dir):
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=False)
    w.e.write(0x409450, b"\x90")                          # someone else changed one site
    assert w.e.call(w.e.dll_export("VF1Text_Startup")) == 0
    assert w.e.read(0x402320, 3) == bytes.fromhex("83ec10")    # nothing was written


@pytest.mark.parametrize("font", gf.GAME_FONTS)
def test_every_name_is_drawn_as_the_patcher_draws_it(world, fonts, font):
    for name in NAMES:
        data = vf1_text.encode(name)
        blits = world.draw(data, font, x=3, y=4)
        ours = expected(fonts, font, name, 3, 4)
        assert len(blits) == len(ours), name
        for (kind, surface, box, place), (our_kind, width, our_place, image) in zip(blits, ours):
            assert kind == "blit" and place == our_place and box[2] == width, name
            if our_kind == "game":
                assert world.surfaces.get(surface) is None   # the game's own tinted sheet (0x402940)
            else:
                assert our_kind == "patcher-made", name
                piece = sheet_piece(world, surface, box)
                assert bytes(piece.data[3::4]) == bytes(image.data[3::4]), name
        assert world.width(data, font) == fonts.font(font).width(name), name
    assert world.gdi_calls == []


def test_a_colour_tints_the_patcher_made_letters_as_the_game_tints_its_own(world, fonts):
    data = vf1_text.encode("\u0141")
    blits = world.draw(data, "SegoeUiBold24", colour=0xFF3060C0)
    (_kind, surface, box, _place), = blits
    tinted = sheet_piece(world, surface, box)
    white = fonts.font("SegoeUiBold24").glyph("\u0141").image
    for i in range(0, len(white.data), 4):
        a = white.data[i + 3]
        if a:
            assert tinted.data[i:i + 4] == bytes((0xC0, 0x60, 0x30, a))


def test_see_through_text_goes_through_blit_rect_with_alpha(world):
    blits = world.draw(vf1_text.encode("\u0141a"), "SegoeUiBold18", colour=0x80FFFFFF)
    assert [b[0] for b in blits] == ["alpha", "alpha"]


def test_old_single_byte_names_read_as_before(world, fonts, vanilla_dir):
    import text_emu
    from test_vf1_game_fonts import _any_dll
    stock = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", _any_dll(), vanilla_dir, install=False)
    for data in [b"Smith", b"Caf\xe9 \xc5ngstr\xf6m", bytes(range(0x20, 0x7F)), bytes(range(0xA2, 0x100))]:
        ours = [(b[2], b[3]) for b in world.draw(data)]
        theirs = [(b[2], b[3]) for b in stock.draw(data)]
        assert ours == theirs
        assert world.width(data) == stock.width(data)
    # a Windows-1252 byte the sheets lack now reads as its letter, not "!"
    blits = world.draw(b"\x93Hi\x94")
    assert [b[3][0] for b in blits][:1] == [0] and len(blits) == 4
    assert fonts.font("SegoeUiBold18").glyph("\u201c").kind == "patcher-made"


def test_the_counted_draw_never_draws_part_of_a_letter(world, fonts):
    f = fonts.font("SegoeUiBold18")
    data = vf1_text.encode("Zo\u00eb!")                    # Z o (2 bytes) !
    width, blits = world.draw_n(data, 3)
    assert width == f.width("Zo") and len(blits) == 2      # the half letter is not drawn
    width, blits = world.draw_n(data, 4)
    assert width == f.width("Zo\u00eb") and len(blits) == 3
    width, blits = world.draw_n(data, 5, measure=True)
    assert width == f.width("Zo\u00eb!") and blits == []


# --------------------------------------------------------------------------- typing
def test_typed_text_reaches_the_box_a_character_at_a_time(world):
    assert world.typed(b"a") == [] and world.last_stop == 0x4049C4      # one byte: the stock path
    posts = world.typed("\u00e9".encode())
    assert posts == [(5, 0, UNICODE_KEY | 0xE9)] and world.last_stop == 0x404A87
    posts = world.typed("\u65e5\u672cx".encode())          # an input method's whole word
    assert posts == [(5, 0, UNICODE_KEY | 0x65E5), (5, 0, UNICODE_KEY | 0x672C), (5, 0, ord("x"))]
    posts = world.typed("\U0001202d\U0001f44d\U0001f3fd".encode())     # four-byte characters
    assert [p[2] & 0x1FFFFF for p in posts] == [0x1202D, 0x1F44D, 0x1F3FD]


def type_into(world, box, text):
    for ch in text:
        world.key(box, ord(ch) if ord(ch) < 0x80 else UNICODE_KEY | ord(ch))


def test_the_family_name_box_at_its_limit_and_one_past(world):
    """The new-family box: limit 20 (0x41C67C), GetText(buffer, 0x14) (0x41C72B). Every character fits whole or
    not at all; nothing is ever written past the box's buffer (limit + 1 bytes) or the 20-byte name buffer."""
    box = world.text_box(20)
    type_into(world, box, "\u00e9" * 10)                   # exactly 20 bytes: the limit
    assert world.box_text(box) == "\u00e9".encode() * 10 and not world.overrun(box)
    type_into(world, box, "\u00e9")                        # limit + 1: refused whole
    assert world.box_text(box) == "\u00e9".encode() * 10 and not world.overrun(box)
    type_into(world, box, "a")
    assert world.box_text(box) == "\u00e9".encode() * 10
    stored = world.get_text(box, 0x14)                     # 19 bytes kept: 9 whole letters, never half of one
    assert stored == "\u00e9".encode() * 9 + b"\0\0"
    box = world.text_box(20)
    type_into(world, box, "a" * 18 + "\u65e5")             # 18 + 3 = 21 bytes: refused whole
    assert world.box_text(box) == b"a" * 18
    type_into(world, box, "\u00e9")                        # 20
    assert world.box_text(box) == b"a" * 18 + "\u00e9".encode() and not world.overrun(box)
    assert world.get_text(box, 0x14) == b"a" * 18 + b"\0\0"
    box = world.text_box(20)
    type_into(world, box, "x" * 25)                        # the stock rule for plain letters is unchanged
    assert world.box_text(box) == b"x" * 20 and world.get_text(box, 0x14) == b"x" * 19 + b"\0"


def test_backspace_deletes_a_whole_character(world):
    box = world.text_box(40)
    type_into(world, box, "Zo\u00eb")
    for ch in ["\U0001f44d", "\U0001f3fd"]:
        world.key(box, UNICODE_KEY | ord(ch))
    world.key(box, ord("e"))
    world.key(box, UNICODE_KEY | 0x301)                    # e + combining acute
    assert vf1_text.decode(world.box_text(box)) == "Zo\u00eb\U0001f44d\U0001f3fde\u0301"
    world.key(box, 8)
    assert vf1_text.decode(world.box_text(box)) == "Zo\u00eb\U0001f44d\U0001f3fd"
    world.key(box, 8)
    assert vf1_text.decode(world.box_text(box)) == "Zo\u00eb"
    world.key(box, 8)
    assert world.box_text(box) == b"Zo"


def test_a_numbers_only_box_takes_no_letters(world):
    box = world.text_box(10)
    world.e.write(box + 0x2D, b"\x01")
    world.key(box, UNICODE_KEY | 0x0661)                   # ARABIC-INDIC DIGIT ONE
    world.key(box, ord("7"))
    assert world.box_text(box) == b"7"


def test_controls_and_the_old_keys_are_unchanged(world):
    box = world.text_box(20)
    world.key(box, UNICODE_KEY | 0x85)                     # a control character is never typed
    world.key(box, 0x1F)
    assert world.box_text(box) == b""
    before = world.changed
    world.key(box, ord("A"))
    assert world.box_text(box) == b"A" and world.changed == before + 1
