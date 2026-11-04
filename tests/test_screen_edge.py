"""Nothing runs off the screen (the owner, 2026-11-03: "i dont care if things run out of boxes, they just need to not
run off the screen"; option A: left, right, top and bottom; only text the patches or a translation bring).

* vf1text.dll / vf1font.dll (native/vf1text/screen.inc), the REAL DLLs on the REAL exe in Unicorn, real GDI, an
  800 x 600 screen: DrawString (every left, right-aligned and centred draw and every text box ends there) moves a text
  that would leave the screen so that it ends at the edge, cuts one wider than the screen to "…" and one taller to
  the lines that fit, exactly as the model (patcher/vf1_screen_edge.py); the word wrapper moves its box. EVERY line a
  translation can replace (the game's and the patches'), at its longest, and worst-case Japanese, Chinese, Arabic and
  emoji lines, drawn at the screen's edges from the left, the right and the centre: every letter lands on the screen.
  Stock English with no translation chosen, and a text wholly off the screen, are drawn exactly as before.
* vf1tr.dll (native/vf1tr/screen_tr.inc), the REAL DLL on the REAL exe in Unicorn, with neither Unicode DLL: the two
  entry jumps are written only over the stock bytes; the stock DrawString and wrapper run on through the DLL's own
  trampolines (naked code in the DLL's executable section: every instruction the DLL runs is in an executable
  section, so DEP cannot stop it) with the text moved or cut the same way; with no translation installed nothing
  is written.
* The translation editor's check (vf1_screen_edge.too_wide / wrap_to_fit) measures with the game's own fonts."""
from __future__ import annotations

import os
import struct
import subprocess

import pytest

from conftest import ROOT

import vf1_screen_edge as se
import vf1_text

SW, SH = 800, 600
CJK = "\u65e5\u672c\u8a9e\u306e\u6587\u7ae0\u3067\u3059\u3002" * 12
ARABIC = ("\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645 ") * 10
EMOJI = "\U0001F600\U0001F44D\U0001F3FD\U0001F468\u200d\U0001F469\u200d\U0001F467" * 14
WORST = [CJK, ARABIC, EMOJI, "\u00e9" * 150, "W" * 120]


def _build(tmp_path_factory, script):
    vcvars = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat"
    if os.name != "nt" or not os.path.isfile(vcvars):
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("edge_build")
    installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             "Microsoft Visual Studio", "Installer")
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}", VF1_BUILD_DIR=str(out))
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / script)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.fixture(scope="module")
def text_build(tmp_path_factory):
    return _build(tmp_path_factory, "build_text.bat")


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    import vf1_game_fonts as gf
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows GDI")
    return gf.Fonts(vanilla_dir)


def _world(text_build, vanilla_dir, name="vf1text.dll", translation=False):
    pytest.importorskip("unicorn")
    import text_emu
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", text_build / name, vanilla_dir, install=True,
                           real_gdi=True)
    assert w.installed == 1
    w.translation = translation
    w.e.modules["vf1tr.dll"] = 0x6900 if translation else 0
    w.e.dyn_procs["VF1Tr_Active"] = lambda emu: (1 if w.translation else 0, 0)
    w.e.dyn_procs["VF1Tr_EnglishOf"] = lambda emu: (emu.arg(0), 0)
    return w


@pytest.fixture(scope="module")
def world(text_build, vanilla_dir, fonts):
    return _world(text_build, vanilla_dir)


@pytest.fixture(scope="module")
def tr_world(text_build, vanilla_dir, fonts):
    return _world(text_build, vanilla_dir, translation=True)


def blits_of(f, text, x, y):
    return [((gx, gy), g.width) for g, gx, gy in f.layout(text, x, y)]


def placed(blits):
    return [(b[3], b[2][2]) for b in blits]


def inside(blits):
    return all(0 <= b[3][0] and b[3][0] + b[2][2] <= SW and 0 <= b[3][1] and b[3][1] + b[2][3] <= SH for b in blits)


# --------------------------------------------------------------------------- the model
def test_the_rule(fonts):
    f = fonts.font("SegoeUiBold18")
    name = "Zo\u00eb " * 30
    text, x, y = se.on_screen(f, name, 700, 10)
    assert x + f.width(text) <= SW and x >= 0 and text.endswith("\u2026")
    assert se.on_screen(f, "Hello", 790, 10) == ("Hello", 790, 10)                  # stock English: untouched
    assert se.on_screen(f, "Hello", 790, 10, translation=True)[1] == SW - f.width("Hello")
    assert se.on_screen(f, "\u00e9t\u00e9", -500, 10) == ("\u00e9t\u00e9", -500, 10)   # wholly off: untouched
    assert se.on_screen(f, "\u00e9\n\u00e9\n\u00e9", 5, 590)[2] == SH - 3 * f.height
    tall = "\n".join(["\u00e9"] * 50)
    text, x, y = se.on_screen(f, tall, 5, 0)
    assert text.count("\n") + 1 == SH // f.height and text.endswith("\u2026") and y == 0


# --------------------------------------------------------------------------- vf1text.dll
@pytest.mark.parametrize("font", ["SegoeUiBold18", "SegoeUiBold24"])
def test_the_dll_moves_and_cuts_as_the_model(world, tr_world, fonts, font):
    f = fonts.font(font)
    for w, translation in ((world, False), (tr_world, True)):
        for text, x, y in (("Zo\u00eb Ch\u00e2telet " * 6, 600, 20), ("\u00e9" * 150, 0, 10),
                           ("Caf\u00e9\nCaf\u00e9\nCaf\u00e9", 5, 570), ("\u00c9cole", -20, -5),
                           ("Hello there, friend", 760, 300)):
            want = se.on_screen(f, text, x, y, translation=translation)
            got = w.draw(vf1_text.encode(text), font, x=x, y=y)
            assert placed(got) == blits_of(f, *want), (translation, text, x, y)
            if vf1_text.encode(text).isascii() and not translation:
                assert want == (text, x, y)                       # the stock English game: exactly as before
            else:
                assert inside(got), (text, x, y)


def test_a_text_wholly_off_the_screen_is_left_alone(tr_world, fonts):
    f = fonts.font("SegoeUiBold18")
    for x, y in ((-900, 10), (900, 10), (10, -200), (10, 700)):
        got = tr_world.draw(vf1_text.encode("\u00c9cole"), "SegoeUiBold18", x=x, y=y)
        assert placed(got) == blits_of(f, "\u00c9cole", x, y)


def test_the_wrapper_box_moves_up_and_in(tr_world, fonts, vanilla_dir):
    import vf1_line_break as lb
    ratio = lb.justify_ratio((vanilla_dir / "Virtual Families.exe").read_bytes())
    f = fonts.font("SegoeUiBold18")
    text = ("Une tr\u00e8s longue phrase traduite qui ne tient pas sur une ligne. " * 8).strip()
    tall = ("Une tr\u00e8s longue phrase traduite. " * 120).strip()       # wraps far taller than the screen
    for text, x, y, width in ((text, 500, 100, 432), (text, 10, 520, 432), (text, -30, 560, 432), (tall, 10, 40, 160)):
        shown, bx, by = se.wrap_on_screen(f, text, x, y, width, ratio, translation=True)
        got, blits = tr_world.wrap(vf1_text.encode(text), width, x=x, y=y, limit=900_000_000)
        want, draws = lb.wrap(f, shown, bx, by, width, ratio)
        if text is tall:
            assert shown.endswith("\u2026") and want <= SH and len(shown) < len(text)
        assert placed(blits) == [p for piece, px, py in draws for p in blits_of(f, piece, px, py)], (x, y)
        assert inside(blits), (x, y)


def every_line(vanilla_dir):
    """Every line a translation can replace (the game's and the patches'), each at its longest (its room filled with
    its widest plain letter), and the worst-case lines."""
    import vf1_translation_strings as vts
    exe = (vanilla_dir / "Virtual Families.exe").read_bytes()
    out = []
    for e in vts.entries_for(exe) + vts.patch_entries():
        room = min(e.max_length or len(e.english), 600)
        out.append("W" * max(1, room))
    return out


def test_every_line_at_its_longest_stays_on_the_screen(tr_world, vanilla_dir, fonts):
    """Each drawn from the left edge, the right edge and centred on either edge (the right-aligned and centred draws
    end in DrawString with x to the left of their anchor), in the game's two most used fonts."""
    lines = sorted(set(every_line(vanilla_dir))) + WORST
    assert len(lines) > 30
    for font in ("SegoeUiBold18", "SegoeUiBold24"):
        f = fonts.font(font)
        for text in lines:
            data = vf1_text.encode(text)
            w = f.width(text)
            for x, y in ((0, 0), (SW - 1, 300), (-w // 2, 580), (SW - w // 2, 20), (SW - w, SH - 5)):
                got = tr_world.draw(data, font, x=x, y=y)
                assert inside(got), (font, len(text), x, y)


# --------------------------------------------------------------------------- vf1tr.dll on its own
@pytest.fixture(scope="module")
def tr_build(tmp_path_factory):
    return _build(tmp_path_factory, "build_tr.bat")


class TrEdge:
    """vf1tr.dll on the real exe (tests/translations_emu.py) with a translation installed and no Unicode DLL: the
    stock DrawString / wrapper are entered at 0x409660 / 0x409D70, and what reaches their next instruction
    (0x409667 / 0x409D76, through the DLL's trampolines) is recorded. GetWidth 0x402320 is stood in for: 10 pixels a
    byte, the widest line."""

    def __init__(self, exe, dll, installed=True):
        import translations_emu as te
        from test_translations_runtime import INI, ini
        import translation_format as tfmt
        import vf1_translation_strings as vts
        entries = {e.key: e for e in vts.entries_for(exe.read_bytes())}
        key = next(k for k, e in entries.items() if e.english == "Continue")
        tf = tfmt.new_file("vf1", [tfmt.Entry(key, "Continue")], "Test", "fr")
        tf.rows[0].translation = "Continuer"
        files = {INI: ini(), te.CHOSEN: tfmt.to_bytes(tf)} if installed else {}
        self.w = w = te.TranslationWorld(exe, dll, files)
        e = self.e = w.e
        self.reached = []
        self.executed = set()
        from unicorn import UC_HOOK_CODE
        lo, hi = K_DLL_BASE, K_DLL_BASE + e.dll.OPTIONAL_HEADER.SizeOfImage
        e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: self.executed.add(a), begin=lo, end=hi)

        def width(em):
            text = em.read_cstr_bytes(em.arg(0))
            return max(len(line) for line in text.split(b"\n")) * 10, 8
        e.seam(0x402320, width)
        e.imports.setdefault("HeapFree", lambda em: (1, 12))

        def stock_draw(em):
            esp = em.reg(K_ESP)
            text, x, y = struct.unpack("<Iii", em.read(esp + 0x48, 12))
            self.reached.append(("draw", em.read_cstr_bytes(text), x, y))
            return None, None
        self.stop_draw = stock_draw

        def stock_wrap(em):
            esp = em.reg(K_ESP)
            x, y, width_, _c, _f, measure = struct.unpack("<iiiIII", em.read(esp + 0x4DC + 8, 24))
            self.reached.append(("wrap", x, y, width_, measure & 0xFF))
            return None, None
        self.stop_wrap = stock_wrap
        self.started = w.start()
        # a window with an 800 x 600 screen, and a font 18 high
        self.window = e.alloc(0x80)
        surface = e.alloc(0x40)
        e.write(surface, struct.pack("<IIii", 0, 0, SW, SH))
        e.w32(self.window + 0x30, surface)
        impl = e.alloc(0x40)
        e.w32(impl + 4, 18)
        self.font = e.alloc(0x10)
        e.w32(self.font + 4, impl)

    def run_until(self, start, stop, args, ecx):
        e = self.e
        esp = e.sp_top - 0x2000
        e.w32(esp, 0xDEAD0000)
        for k, v in enumerate(args):
            e.w32(esp + 4 + 4 * k, v & 0xFFFFFFFF)
        e.setreg(K_ESP, esp)
        e.setreg(K_ECX, ecx)
        e.uc.emu_start(start, stop)

    def draw(self, text: bytes, x: int, y: int):
        self.reached.clear()
        at = self.e.alloc(len(text) + 4)
        self.e.write(at, text + b"\0")
        self.run_until(0x409660, 0x409667, [at, x, y, 0xFFFFFFFF, self.font], self.window)
        self.stop_draw(self.e)
        return self.reached[-1]

    def wrap(self, text: bytes, x: int, y: int, width: int, height):
        """The box (and text) as they reach the stock wrapper for drawing; its measuring calls are answered with
        height(text) (or `height` itself when it is a number)."""
        self.reached.clear()
        at = self.e.alloc(len(text) + 4)
        self.e.write(at, text + b"\0")
        outer = self.e.alloc(8)
        self.e.w32(outer, self.window)
        e = self.e
        from unicorn import UC_HOOK_CODE
        calls = []

        def at_stock(uc, address, size, user):
            esp = e.reg(K_ESP)
            x_, y_, w_, _c, _f, measure = struct.unpack("<iiiIII", e.read(esp + 0x4DC + 8, 24))
            calls.append((x_, y_, w_, measure & 0xFF))
            self.last_text = e.read_cstr_bytes(e.r32(esp + 0x4DC + 4))
            if measure & 0xFF:                                   # the measuring call: answer it, back to the DLL
                ret = e.r32(esp + 0x4DC)
                e.setreg(K_ESP, esp + 0x4DC + 4 + 0x1C)
                e.setreg(K_EAX, height(self.last_text) if callable(height) else height)
                e.setreg(K_EIP, ret)
            else:
                e.uc.emu_stop()
        h = e.uc.hook_add(UC_HOOK_CODE, at_stock, begin=0x409D76, end=0x409D76)
        try:
            self.run_until(0x409D70, 0xDEAD0000, [at, x, y, width, 0xFFFFFFFF, self.font, 0], outer)
        finally:
            e.uc.hook_del(h)
        return calls


from unicorn.x86_const import UC_X86_REG_EAX as K_EAX, UC_X86_REG_ECX as K_ECX, UC_X86_REG_EIP as K_EIP  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ESP as K_ESP  # noqa: E402
from kids_emu import DLL_BASE as K_DLL_BASE  # noqa: E402


@pytest.fixture(scope="module")
def tr_edge(tr_build, vanilla_dir):
    t = TrEdge(vanilla_dir / "Virtual Families.exe", tr_build / "vf1tr.dll")
    assert t.started == 1, t.w.log()
    return t


def test_vf1tr_writes_its_two_jumps_over_the_stock_bytes(tr_edge, tr_build, vanilla_dir):
    e = tr_edge.e
    for site in (0x409660, 0x409D70):
        code = e.read(site, 5)
        assert code[0] == 0xE9
        target = (site + 5 + struct.unpack("<i", code[1:])[0]) & 0xFFFFFFFF
        assert K_DLL_BASE <= target < K_DLL_BASE + e.dll.OPTIONAL_HEADER.SizeOfImage
    assert "kept on the screen" in tr_edge.w.log()
    untranslated = TrEdge(vanilla_dir / "Virtual Families.exe", tr_build / "vf1tr.dll", installed=False)
    assert untranslated.e.read(0x409660, 7) == bytes.fromhex("83ec448b442458")       # nothing installed: stock
    assert untranslated.e.read(0x409D70, 6) == bytes.fromhex("81ecdc040000")


def test_vf1tr_moves_and_cuts_and_the_stock_code_runs_on(tr_edge):
    t = tr_edge
    assert t.draw(b"Continuer", 10, 10) == ("draw", b"Continuer", 10, 10)            # on the screen: as it was
    assert t.draw(b"Continuer", 760, 10) == ("draw", b"Continuer", SW - 90, 10)     # moved to end at the edge
    assert t.draw(b"Continuer", -900, 10) == ("draw", b"Continuer", -900, 10)       # wholly off: left alone
    kind, text, x, y = t.draw(b"W" * 100, 30, 10)                                   # 1000 px: cut, from the left edge
    assert x == 0 and text.endswith(b"...") and len(text) * 10 <= SW
    kind, text, x, y = t.draw(b"a\nb\nc", 5, 590)
    assert y == SH - 3 * 18
    kind, text, x, y = t.draw(b"\n".join([b"x"] * 40), 5, 0)
    assert text.count(b"\n") + 1 == SH // 18 and text.endswith(b"...")


def test_vf1tr_moves_the_wrappers_box(tr_edge):
    calls = tr_edge.wrap(b"Une phrase traduite.", 600, 560, 432, 90)
    assert calls[0][3] == 1 and calls[-1] == (SW - 432, SH - 90, 432, 0)
    calls = tr_edge.wrap(b"Une phrase traduite.", 100, 100, 432, 90)
    assert calls[-1] == (100, 100, 432, 0)
    tall = b"Une phrase traduite. " * 100                   # a stand-in wrapper: 18 pixels for every 40 bytes
    calls = tr_edge.wrap(tall, 100, 100, 432, lambda t: 18 * (len(t) // 40 + 1))
    shown = tr_edge.last_text
    assert calls[-1] == (100, SH - 18 * (len(shown) // 40 + 1), 432, 0)
    assert shown.endswith(b"...") and 18 * (len(shown) // 40 + 1) <= SH < 18 * ((len(shown) + 40) // 40 + 1)


def test_every_instruction_vf1tr_runs_is_in_an_executable_section(tr_edge):
    """DEP: the trampolines are code in the DLL's own executable section, never data."""
    pe = tr_edge.e.dll
    sections = [(K_DLL_BASE + s.VirtualAddress, K_DLL_BASE + s.VirtualAddress + s.Misc_VirtualSize,
                 bool(s.Characteristics & 0x20000000)) for s in pe.sections]
    assert tr_edge.executed
    for a in tr_edge.executed:
        sec = next((s for s in sections if s[0] <= a < s[1]), None)
        assert sec is not None and sec[2], hex(a)


# --------------------------------------------------------------------------- the editor's check
def test_the_editor_measures_with_the_game_fonts_and_wraps_to_fit(fonts):
    line = "Une tr\u00e8s longue ligne traduite " * 6
    wide = se.too_wide(fonts, line)
    assert wide and wide[0][1] == max(fonts.font(n).width(line) for n in se.DRAWN_FONTS) and wide[0][1] > SW
    wrapped = se.wrap_to_fit(fonts, line)
    assert "\n" in wrapped and not se.too_wide(fonts, wrapped)
    assert wrapped.replace("\n", " ").split() == line.split()
    cjk = se.wrap_to_fit(fonts, CJK)
    assert not se.too_wide(fonts, cjk) and cjk.replace("\n", "") == CJK
    assert se.too_wide(fonts, "Short") == [] and se.wrap_to_fit(fonts, "Short") == "Short"


def test_wrap_to_fit_never_cuts_a_placeholder():
    class Ten:                                            # ten pixels a letter
        spacing, height = 0, 18

        def width(self, text):
            return 10 * max(len(line) for line in text.split("\n"))

    class Fonts:
        def font(self, name):
            return Ten()
    assert se.wrap_to_fit(Fonts(), "W" * 79 + "%s") == "W" * 79 + "\n%s"
    assert se.wrap_to_fit(Fonts(), "W" * 78 + "{name}xyz") == "W" * 78 + "\n{name}xyz"
