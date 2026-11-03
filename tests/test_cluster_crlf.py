"""The shared Unicode spec's cluster rule, row 2 (unicode-audit diff_vf1.md item 4): CR LF is one character, and a
ZERO WIDTH JOINER joins the next character unless that is CR or LF (the Virtual Families 2 patcher's rule).

Proved for the patcher's rule (vf1_text.clusters) and for the REAL vf1text.dll / vf1font.dll on the REAL exe in
Unicorn (tests/text_emu.py): a box's cut (GetText 0x40D740) and Backspace (0x40DA70) take CR LF whole, while every
draw and measure of text with a line break is exactly what it was: the draw loops take CR and then LF
(`DrawEnd` = vf1_text.clusters(draw=True)), which is the old split for every text without a joiner before a line
break."""
import os
import subprocess

import pytest

from conftest import ROOT

import vf1_text

VCVARS_OK = os.name == "nt"


def old_clusters(text: str) -> list[str]:
    """vf1_text.clusters as it was before this change (origin/main 7fdc533), kept here as the reference."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = i + 1
        if vf1_text._regional(ord(text[i])) and j < n and vf1_text._regional(ord(text[j])):
            j += 1
        while j < n:
            cp = ord(text[j])
            if cp == 0x200D:
                j += 1
                if j < n:
                    j += 1
                continue
            if vf1_text.is_cluster_extender(cp):
                j += 1
                continue
            break
        out.append(text[i:j])
        i = j
    return out


SAMPLES = ["ab\r\ncd", "\r\n", "\r\r\n\n", "a\rb\nc", "\r\n\u0301x", "x\r\n\U0001F44D\U0001F3FD",
           "Line one.\r\nLine two.\nThree", "\U0001F1EF\U0001F1F5\r\n\U0001F1EB\U0001F1F7", "e\u0301\r\n"]


@pytest.mark.parametrize("text,clusters", [
    ("ab\r\ncd", ["a", "b", "\r\n", "c", "d"]),
    ("\r\n", ["\r\n"]),
    ("\r\r\n\n", ["\r", "\r\n", "\n"]),
    ("a\rb\nc", ["a", "\r", "b", "\n", "c"]),               # a lone CR or LF is one character, as before
    ("\r\n\u0301x", ["\r\n\u0301", "x"]),                   # VF2's rule: a mark after CR LF stays with it
    ("a\u200d\nb", ["a\u200d", "\n", "b"]),                 # a joiner never takes a line break
    ("a\u200d\r\nb", ["a\u200d", "\r\n", "b"]),
    ("\U0001F468\u200d\U0001F469", ["\U0001F468\u200d\U0001F469"]),   # it still joins anything else
])
def test_the_rule(text, clusters):
    assert vf1_text.clusters(text) == clusters
    assert vf1_text.char_count(text) == len(clusters)
    assert "".join(vf1_text.clusters(text, draw=True)) == text


def test_cr_lf_is_never_cut_and_backspace_takes_it_whole_in_python():
    assert vf1_text.cut_to_bytes("ab\r\n", 3) == "ab"
    assert vf1_text.cut_to_bytes("ab\r\n", 4) == "ab\r\n"


@pytest.mark.parametrize("text", SAMPLES)
def test_the_draw_split_is_the_old_split(text):
    """Every text without a joiner right before a line break is drawn in exactly the pieces it was drawn in before."""
    assert vf1_text.clusters(text, draw=True) == old_clusters(text)


def test_the_draw_split_differs_only_for_a_joiner_before_a_line_break():
    assert old_clusters("a\u200d\nb") == ["a\u200d\n", "b"]           # before: the line break was swallowed
    assert vf1_text.clusters("a\u200d\nb", draw=True) == ["a\u200d", "\n", "b"]


# --------------------------------------------------------------------------- the real DLLs in the emulator
def _build(tmp_path_factory, name):
    vcvars = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat"
    if not VCVARS_OK or not os.path.isfile(vcvars):
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("crlf_build")
    installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             "Microsoft Visual Studio", "Installer")
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}", VF1_BUILD_DIR=str(out))
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return out / name


@pytest.fixture(scope="module", params=["vf1text.dll", "vf1font.dll"])
def world(request, tmp_path_factory, vanilla_dir):
    pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    import text_emu
    dll = _build(tmp_path_factory, request.param)
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True,
                           real_gdi=True)
    assert w.installed == 1
    w.font_mode = request.param == "vf1font.dll"
    return w


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    import vf1_game_fonts as gf
    return gf.Fonts(vanilla_dir)


def _box_with(world, data: bytes, limit: int = 20) -> int:
    box = world.text_box(limit)
    world.e.write(world.e.r32(box + 0x30), data + b"\0")
    return box


def test_get_text_never_cuts_between_cr_and_lf(world):
    box = _box_with(world, b"ab\r\n")
    assert world.get_text(box, 4).split(b"\0", 1)[0] == b"ab"           # 3 bytes of room: CR LF is one character
    assert world.get_text(box, 5).split(b"\0", 1)[0] == b"ab\r\n"


def test_backspace_removes_cr_lf_whole(world):
    box = _box_with(world, b"ab\r\n")
    world.key(box, 8)
    assert world.box_text(box) == b"ab" and not world.overrun(box)
    box = _box_with(world, b"a\r\r\n")
    world.key(box, 8)
    assert world.box_text(box) == b"a\r"


LINE_TEXTS = ["Line one.\r\nLine two.", "ab\r\ncd\r\n", "x\r\ny", "Zoë\r\nŁ", "é\r\nb"]


@pytest.mark.parametrize("font", ["SegoeUiBold18", "SegoeUi33"])
def test_text_with_line_breaks_is_drawn_and_measured_in_the_old_pieces(world, fonts, font):
    """Each blit of a text with CR LF line breaks is one old piece (CR drawn as the game's row 0, as the stock game
    draws a byte with no row; LF a line break), at the place the patcher's model gives, and the width is the
    model's. The model's pieces are the old ones (test_the_draw_split_is_the_old_split)."""
    f = fonts.font(font)
    for text in LINE_TEXTS:
        data = vf1_text.encode(text)
        blits = world.draw(data, font, x=2, y=3)
        if world.font_mode:
            # vf1font.dll draws every letter in the chosen face: the pieces and lines are what is checked
            assert len(blits) == len([p for p in old_clusters(text) if p != "\n"]), text
            assert len({b[3][1] for b in blits}) == len([ln for ln in text.split("\n") if ln]), text
            continue
        ours = [(g.width, (gx, gy)) for g, gx, gy in f.layout(text, 2, 3)]
        assert [(b[2][2], b[3]) for b in blits] == ours, text
        assert world.width(data, font) == f.width(text), text


def test_a_joiner_before_a_line_break_now_breaks_the_line(world):
    blits = world.draw("a\u200d\nb".encode("utf-8"), "SegoeUiBold18", x=0, y=0)
    ys = sorted({b[3][1] for b in blits})
    assert len(ys) == 2                                 # "b" is on the next line
