"""Letters Windows draws on the spot (Render Unicode with In-Game Fonts): vf1text.dll's own drawing (glyph_gdi.inc)
and the patcher's (vf1_glyph_gdi.py, the Game Text tool) give the same pixels.

Two ways, both with the real compiled DLL:
* through 32-bit rundll32 (VF1Text_TestLetterW), letter by letter;
* inside the emulator, the game drawing a name (DrawString 0x409660 -> the DLL), the DLL's GDI calls made by this
  machine's real GDI (tests/text_emu.RealGdi): French, Turkish, Japanese, Chinese, Korean, Cuneiform and emoji.
"""
import os
import struct
import subprocess

import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import vf1_game_fonts as gf  # noqa: E402
import vf1_glyph_gdi as g  # noqa: E402
import vf1_text  # noqa: E402
from test_vf1_unicode_text import dll, VCVARS  # noqa: E402,F401  (the module-scoped build)

RUNDLL32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "rundll32.exe")
# (letter, the face the chain picks first on a standard Windows 10/11; GDI draws emoji in black and white, from
# the first face that has them)
SAMPLES = [("\u65e5", "Yu Gothic"), ("\u4e2d", "Yu Gothic"), ("\ud55c", "Malgun Gothic"), ("\U0001202d", "Segoe UI Historic"),
           ("\U0001f600", "Segoe UI Symbol"), ("\u0e01", "Leelawadee UI"), ("\u05d0", "Segoe UI"),
           ("\u2603", "Segoe UI Symbol")]


def need_windows():
    if not g.AVAILABLE or not os.path.isfile(RUNDLL32):
        pytest.skip("needs Windows and 32-bit rundll32")


def dll_letter(dll, tmp_path, face, weight, em, baseline, height, letter):
    out = tmp_path / f"letter-{abs(hash((face, weight, em, letter)))}.bin"
    cps = "+".join(f"{ord(c):X}" for c in letter)
    p = subprocess.Popen([RUNDLL32, f"{dll},VF1Text_TestLetter", f"{out}|{face}|{weight}|{em}|{baseline}|{height}|{cps}"])
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()            # only the process this test started
        raise
    data = out.read_bytes()
    w, h, drawn = struct.unpack_from("<3i", data, 0)
    return w, h, drawn, data[12:]


@pytest.mark.parametrize("font", gf.GAME_FONTS)
def test_the_dll_draws_each_letter_as_the_patcher_does(dll, tmp_path, font):
    need_windows()
    style = gf.load_glyph_file(font).style
    height = {"SegoeUi33": 33, "SegoeUiBold17": 17, "SegoeUiBold18": 18, "SegoeUiBold24": 24}[font]
    r = g.Renderer(style.face, style.weight, style.em, style.baseline, height)
    for letter, _face in SAMPLES + [("e\u0301\u0323", "Segoe UI"), ("\U0001f44d\U0001f3fd", "Segoe UI Symbol")]:
        image, face = r.draw(letter)
        w, h, drawn, rows = dll_letter(dll, tmp_path, style.face, style.weight, style.em, style.baseline, height, letter)
        assert (w, h, bool(drawn)) == (image.width, image.height, bool(face)), letter
        assert rows == bytes(image.data[3::4]), letter


def test_the_chain_picks_the_owners_order():
    need_windows()
    r = g.Renderer("Segoe UI", 400, 31, 26, 33)
    for letter, face in SAMPLES:
        assert r.face_for(letter) == face, letter
    assert r.face_for("\U000effff") is None          # nothing has it: the box


def test_missing_box_is_the_same(dll, tmp_path):
    need_windows()
    w, h, drawn, rows = dll_letter(dll, tmp_path, "Segoe UI", 700, 16, 14, 18, "\U000EFFFF")
    box = g.missing_box(18, 14, 16)
    assert not drawn and (w, h) == (box.width, box.height) and rows == bytes(box.data[3::4])


@pytest.fixture(scope="module")
def world(dll, vanilla_dir):
    need_windows()
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True, real_gdi=True)
    assert w.installed == 1
    return w


@pytest.mark.parametrize("font", gf.GAME_FONTS)
@pytest.mark.parametrize("name", ["Fran\u00e7oise L\u00e9a", "\u015eebnem \u00c7a\u011flar", "\u5c71\u7530 \u82b1\u5b50",
                                  "\u738b\u79c0\u82f1", "\uae40\ubbfc\uc900", "\U0001202d\U00012000 Ninsun",
                                  "Mia \U0001f600\U0001f44d\U0001f3fd"])
def test_names_in_every_script_are_drawn_by_the_game_as_the_tool_draws_them(world, vanilla_dir, font, name):
    """French, Turkish, Japanese, Chinese, Korean, Cuneiform and emoji, through the game's DrawString and GetWidth
    with the DLL, the letters Windows draws made by the DLL's own code: every place, box and pixel is the tool's."""
    f = gf.Fonts(vanilla_dir).font(font)
    data = vf1_text.encode(name)
    blits = world.draw(data, font, x=2, y=3)
    ours = f.layout(name, 2, 3)
    assert len(blits) == len(ours), name
    import vf1_picture_image as pi
    for (kind, surface, box, place), (glyph, x, y) in zip(blits, ours):
        assert kind == "blit" and place == (x, y) and box[2] == glyph.width, name
        if glyph.kind == "game":
            continue
        info = world.surfaces[surface]
        sheet = pi.Image(info["w"], info["h"], world.surface_pixels(surface))
        piece = sheet.sub(*box)
        assert bytes(piece.data[3::4]) == bytes(glyph.image.data[3::4]), (name, glyph.kind)
    assert world.width(data, font) == f.width(name)
