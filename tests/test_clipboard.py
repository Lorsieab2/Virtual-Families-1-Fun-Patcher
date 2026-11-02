"""Copy and Paste in Text Boxes (setting CopyPasteInTextBoxes, on by default; native/vf1fun/clipboard.inc).

Proved by running the vanilla game's own event loop (its SDL_KEYDOWN case from 0x404826, the message manager's
listener walk 0x401DA0 and the text box's own HandleMessage 0x40DA70) with vf1fun.dll's code installed, in Unicorn
(tests/kids_emu.py): a harness DLL that includes native/vf1fun/vf1fun.cpp exports the install. The clipboard itself
(OpenClipboard / GetClipboardData / SetClipboardData) is the only stand-in: the DLL reads and writes it through two
exported pointers, pointed here at Python. Every box buffer is the game's size (limit + 1 bytes) with 16 guard bytes
after it."""
import json
import os
import re
import struct
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from conftest import ROOT

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
CPP = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
INC = (ROOT / "native" / "vf1fun" / "clipboard.inc").read_text(encoding="utf-8").replace("\r\n", "\n")
MANIFEST = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

SITE = 0x404826
STOCK = bytes.fromhex("8b4c243881f93a000040")
DONE = 0x404A87
TEXT_VTABLE = 0x4B2950
CTRL, SHIFT, ALT = 0x0040, 0x0001, 0x0100
INSERT = 0x40000049

HARNESS = r'''
#include "@SOURCE@"
static const char *__cdecl SameName(const char *s) { return s; }
extern "C" __declspec(dllexport) void __cdecl T_Install() { InstallClipboard(); }
extern "C" __declspec(dllexport) int __cdecl T_On() { return gClipboardOn; }
extern "C" __declspec(dllexport) void __cdecl T_Unicode(int on) { TextFullName = on ? &SameName : 0; }
'''


# ===================================================================== always
def test_the_setting_is_on_by_default_and_documented():
    row = next(s for s in MANIFEST["settings"] if s["id"] == "CopyPasteInTextBoxes")
    assert row["default"] is True
    for words in ("Ctrl+V", "Shift+Insert", "Ctrl+C", "Ctrl+Insert", "Ctrl+X", "300 characters", "Windows-1252"):
        assert words in row["description"], words


def test_owners_defaults_tick_it():
    import vf1_patcher_gui as gui
    assert "CopyPasteInTextBoxes" not in gui.OWNERS_DEFAULT_OFF_SETTING_IDS


def test_it_is_installed_only_by_its_setting_after_the_text_dlls():
    start = CPP[CPP.index("VF1Fun_Startup() {"):]
    assert CPP.count("InstallClipboard();") == 1
    assert re.search(r'if \(SettingOn\(L"CopyPasteInTextBoxes", true\)\)[^\n]*\n\s+InstallClipboard\(\);', start)
    assert start.index("LoadTextCompanion(L\"vf1font.dll\")") < start.index("InstallClipboard();")


def test_the_site_is_checked_before_anything_is_written():
    body = re.search(r"static void InstallClipboard\(\) \{(.*?)\n\}", INC, re.S).group(1)
    code = bytes(int(b, 16) for line in body.split("if (")[0].splitlines()
                 for b in re.findall(r"0x([0-9A-F]{2})\b", line.split("//")[0]))
    assert code == STOCK
    assert body.index("BytesAre(kKeyDownSite") < body.index("InstallJump(kKeyDownSite")


def test_the_game_mechanics_page_lists_the_keys():
    import vf1_game_mechanics as gm
    keys = [f for f in gm.facts() if f.group == gm.KEYS]
    assert any(f.text.startswith(gm.with_patcher("CopyPasteInTextBoxes", "")) and "Ctrl+V" in f.text for f in keys)
    assert gm.setting("CopyPasteInTextBoxes") == "Copy and Paste in Text Boxes, on by default"


def _vanilla() -> Path:
    if not os.environ.get("VF1_VANILLA_DIR"):
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    return Path(os.environ["VF1_VANILLA_DIR"])


def test_vanilla_site_and_keys(vanilla_dir):
    """The stock switch: V, C and X do nothing (0x404A87); Insert posts (6, 0x3F4)."""
    pefile = pytest.importorskip("pefile")
    img = pefile.PE(str(vanilla_dir / "Virtual Families.exe")).get_memory_mapped_image()
    at = lambda va, n: bytes(img[va - 0x400000:va - 0x400000 + n])  # noqa: E731
    assert at(SITE, len(STOCK)) == STOCK
    for key in (ord("v"), ord("c"), ord("x")):
        index = img[0x404ADC - 0x400000 + key - 8]
        assert struct.unpack("<I", at(0x404AC4 + 4 * index, 4))[0] == DONE
    assert struct.unpack("<I", at(0x404B54 + 4 * (INSERT - 0x4000003B), 4))[0] == 0x404940
    assert at(0x404940, 5) == bytes.fromhex("b8f4030000")
    assert at(0x4B2958, 4) == struct.pack("<I", 0x40DA70)     # the text box's HandleMessage, vtable slot 2


def test_sdl_makes_no_text_for_ctrl_keys(vanilla_dir):
    """Ctrl+V reaches SDL 2.0.3 as WM_KEYDOWN, whose ToUnicode answers 0x16 (Ctrl+C 0x03, Ctrl+X 0x18): the real
    SDL_SendKeyboardText drops anything below a space, so no letter is typed."""
    pytest.importorskip("unicorn")
    import sdl_emu
    keys = sdl_emu.WindowsKeys(vanilla_dir)
    assert keys.type_units([0x16, 0x03, 0x18]) == []
    assert keys.type_units([ord("v")]) == [b"v"]


# ===================================================================== emulated
@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    tmp_path = tmp_path_factory.mktemp("clipboard")
    src = tmp_path / "clipboard_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    dll = tmp_path / "clipboard_harness.dll"
    script = tmp_path / "build_harness.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 /LD "{src}" /Fo"{tmp_path}\\\\" /Fe"{dll}" '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n",
        encoding="ascii")
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer"
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")
    build = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=env)
    assert build.returncode == 0, build.stdout + build.stderr
    return dll


class Game:
    """The exe and the harness in one Unicorn; a message manager whose listeners are a scene and text boxes."""

    def __init__(self, dll: Path, unicode: bool, install: bool = True):
        pytest.importorskip("unicorn")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import kids_emu as K
        self.K = K
        exe = _vanilla() / "Virtual Families.exe"
        e = self.e = K.Emu(exe, dll)

        def virtual_protect(em):
            em.w32(em.arg(3), 0x20)
            return 1, 16

        def wide(em):
            cp, flags, src, n, dst, cap = (em.arg(i) for i in range(6))
            data = em.read(src, n)
            try:
                text = data.decode("utf-8") if flags & 8 else data.decode("utf-8", "replace")
            except UnicodeDecodeError:
                return 0, 24
            out = text.encode("utf-16-le", "surrogatepass")
            if dst and cap:
                em.write(dst, out[:cap * 2])
            return len(out) // 2, 24

        def fold(em):                                     # FoldStringW(MAP_PRECOMPOSED, ...): Windows composes
            flags, src, n, dst, cap = (em.arg(i) for i in range(5))
            assert flags == 0x20
            text = em.read(src, n * 2).decode("utf-16-le", "surrogatepass")
            out = unicodedata.normalize("NFC", text).encode("utf-16-le", "surrogatepass")
            em.write(dst, out[:cap * 2])
            return len(out) // 2, 20
        e.imports.update({"VirtualProtect": virtual_protect, "GetCurrentProcess": lambda em: (0xFFFFFFFF, 0),
                          "FlushInstructionCache": lambda em: (1, 12), "MultiByteToWideChar": wide,
                          "FoldStringW": fold})
        # the message manager: 0x402140 returns it; *it is the list's holder; *holder is the first listener node
        self.holder = e.alloc(0x10)
        self.manager = e.alloc(0x10)
        e.w32(self.manager, self.holder)
        e.seam(0x402140, lambda em: (self.manager, 0))
        self.changed: list[int] = []

        def changed(em):                                  # thiscall(message, control id)
            assert em.arg(1) == 55, "the box's own id"
            self.changed.append(em.arg(0))
            return 0, 8
        e.seam(0x401EA0, changed)
        # a scene listener that records every message it gets and never takes one
        self.scene_got: list[tuple] = []
        scene_proc = e.fake_code(b"\xC2\x0C\x00")

        def scene(em):
            self.scene_got.append((em.arg(0), em.arg(1), em.arg(2)))
            return 0, 12
        e.seam_live(scene_proc, scene)
        scene_vt = e.alloc(0x20)
        e.w32(scene_vt + 8, scene_proc)
        self.scene = e.alloc(0x20)
        e.w32(self.scene, scene_vt)
        self.nodes: list[int] = []
        self.add_listener(self.scene)
        # the clipboard
        self.clipboard = ""
        self.writes: list[str] = []
        read = e.fake_code(b"\xC3")
        write = e.fake_code(b"\xC3")

        def clip_read(em):
            p = em.alloc(len(self.clipboard.encode("utf-16-le", "surrogatepass")) + 2)
            em.write(p, self.clipboard.encode("utf-16-le", "surrogatepass") + b"\0\0")
            return p, 0

        def clip_write(em):
            text = em.wstr(em.arg(0))
            self.writes.append(text)
            self.clipboard = text
            return 1, 0
        e.seam_live(read, clip_read)
        e.seam_live(write, clip_write)
        e.w32(e.dll_export("VF1Fun_ClipRead"), read)
        e.w32(e.dll_export("VF1Fun_ClipWrite"), write)
        e.call(e.dll_export("T_Unicode"), (1 if unicode else 0,))
        if install:
            e.call(e.dll_export("T_Install"))
            assert e.call(e.dll_export("T_On")) == 1
            assert e.read(SITE, 1) == b"\xE9"
        self.stops: list[int] = []

        def stop(uc, address, size, user):
            if self.running:
                self.stops.append(address)
                uc.emu_stop()
        self.running = False
        e.uc.hook_add(K.UC_HOOK_CODE, stop, begin=DONE, end=DONE)

    def add_listener(self, obj: int):
        node = self.e.alloc(0x10)
        self.e.w32(node, obj)
        self.e.w32(node + 4, 2)
        if self.nodes:
            self.e.w32(self.nodes[-1] + 0xC, node)
        else:
            self.e.w32(self.holder, node)
        self.nodes.append(node)

    def box(self, limit: int, text: bytes = b"", editing: bool = True, shown: bool = True, numeric: bool = False):
        """An ldwTextControlImpl as the game makes one: its buffer limit + 1 bytes, guard bytes after."""
        e = self.e
        impl = e.alloc(0x80)
        e.w32(impl, TEXT_VTABLE)
        owner = e.alloc(0x10)
        e.write(owner + 8, b"\x01" if shown else b"\x00")
        e.w32(impl + 4, 55)
        e.w32(impl + 0x1C, owner)
        e.write(impl + 0x24, b"\x01")
        e.write(impl + 0x25, b"\x01" if editing else b"\x00")
        e.write(impl + 0x2D, b"\x01" if numeric else b"\x00")
        e.w32(impl + 0x28, limit)
        buf = e.alloc(limit + 1 + 16, fill=0xCC)
        e.write(buf, text + b"\0")
        e.w32(impl + 0x30, buf)
        self.add_listener(impl)
        return impl

    def text(self, impl: int) -> bytes:
        return self.e.read(self.e.r32(impl + 0x30), self.e.r32(impl + 0x28) + 1).split(b"\0", 1)[0]

    def guard_ok(self, impl: int) -> bool:
        return self.e.read(self.e.r32(impl + 0x30) + self.e.r32(impl + 0x28) + 1, 16) == b"\xCC" * 16

    def key(self, sym: int, mod: int = 0):
        """The event loop's SDL_KEYDOWN case from 0x404826, the key's code and modifiers in the event, to 0x404A87."""
        K, e = self.K, self.e
        frame = e.sp_top - 0x400
        e.write(frame, b"\0" * 0x60)
        e.w32(frame + 0x24, 0x300)
        e.w32(frame + 0x38, sym)
        e.w32(frame + 0x3C, mod)
        e.setreg(K.UC_X86_REG_ESP, frame)
        e.setreg(K.UC_X86_REG_EAX, 0x300)
        e.setreg(K.UC_X86_REG_EBX, 0)
        e.setreg(K.UC_X86_REG_EDI, 0xA)
        self.stops = []
        self.running = True
        try:
            e.uc.emu_start(SITE, 0xFFFFFFFF, count=5_000_000)
        finally:
            self.running = False
        assert self.stops == [DONE], "the event loop goes on to its next event"
        assert e.reg(K.UC_X86_REG_ESP) == frame, "the stack is as the event loop left it"

    def paste(self, impl: int, text: str):
        self.clipboard = text
        self.key(ord("v"), CTRL)


def cut_utf8(text: str, room: int, letters: int = 300) -> bytes:
    import vf1_text
    out = b""
    n = 0
    for cluster in vf1_text.clusters(text):
        b = cluster.encode("utf-8")
        if len(out) + len(b) > room or n == letters:
            break
        out += b
        n += 1
    return out


@pytest.fixture
def uni(harness_dll):
    return Game(harness_dll, unicode=True)


@pytest.fixture
def plain(harness_dll):
    return Game(harness_dll, unicode=False)


# ---- paste with a Unicode setting on: a name box (300 characters, 1,200 bytes)
@pytest.mark.parametrize("label,clip,expect", [
    ("300 characters", "a" * 300, b"a" * 300),
    ("301 characters: one past", "a" * 301, b"a" * 300),
    ("300 four-byte characters: 1,200 bytes", "\U0001F4A9" * 300, ("\U0001F4A9" * 300).encode()),
    ("301 four-byte characters", "\U0001208D" * 301, ("\U0001208D" * 300).encode()),
    ("joined emoji stop at whole ones", "\U0001F469\u200D\U0001F469\u200D\U0001F467" * 70,
     ("\U0001F469\u200D\U0001F469\u200D\U0001F467" * 66).encode()),
    ("CR, LF and Tab become spaces", "Ann\r\nMarie\tLee", b"Ann  Marie Lee"),
    ("control characters and lone surrogates are dropped", "Zo\u0001e\x7f\ud800\U0001F4A9", "Zoe\U0001F4A9".encode()),
    ("accents, Japanese, Cuneiform", "Zoë 日本 𒂍", "Zoë 日本 𒂍".encode()),
])
def test_paste_into_a_name_box(uni, label, clip, expect):
    g = uni
    box = g.box(1200)
    g.paste(box, clip)
    assert g.text(box) == expect, label
    assert g.guard_ok(box)
    assert g.changed == [0xC]
    assert g.scene_got == [], "the key never reaches the game"


def test_paste_adds_after_the_typed_text_and_stops_at_the_limit(uni):
    g = uni
    box = g.box(1200, b"x" * 290)
    g.paste(box, "abcdefghijklmnop")
    assert g.text(box) == b"x" * 290 + b"abcdefghij"
    g.changed.clear()
    g.paste(box, "more")
    assert g.text(box) == b"x" * 290 + b"abcdefghij", "a full box takes nothing"
    assert g.changed == []
    assert g.guard_ok(box)


def test_paste_at_the_byte_limit_and_one_past(uni):
    g = uni
    box = g.box(1200, ("\U0001F4A9" * 299).encode())
    g.paste(box, "é")                           # 1,198 bytes: room for 2
    assert g.text(box) == ("\U0001F4A9" * 299 + "é").encode()
    g.paste(box, "\U0001F4A9")                   # 4 more would be 1,202: refused whole
    assert len(g.text(box)) == 1198
    assert g.guard_ok(box)


def test_paste_never_splits_a_mark_from_its_letter(uni):
    g = uni
    box = g.box(1200, b"a" * 1199)
    g.paste(box, "e\u0301")                      # 3 bytes, one character: does not fit whole
    assert g.text(box) == b"a" * 1199
    assert g.guard_ok(box)


@pytest.mark.parametrize("limit", [0x14, 0x50])
def test_paste_into_other_boxes_keeps_their_byte_limit(uni, limit):
    g = uni
    box = g.box(limit)
    clip = "日本語のテキスト" * 20
    g.paste(box, clip)
    assert g.text(box) == cut_utf8(clip, limit)
    assert g.guard_ok(box)


def test_a_numbers_only_box_takes_digits(uni):
    g = uni
    box = g.box(10, numeric=True)
    g.paste(box, "-12a3 4\r\n56789012")
    assert g.text(box) == b"-123456789"
    assert g.guard_ok(box)


# ---- paste with both Unicode settings off: what the stock game can store and draw, one byte each
@pytest.mark.parametrize("label,clip,expect", [
    ("Latin-1 letters", "Zoë Château", "Zoë Château".encode("latin-1")),
    ("accents composed first", "Zoe\u0308", "Zoë".encode("latin-1")),
    ("what the stock fonts cannot draw is dropped", "A€B…C日D💩E\u00a0F\u00a1G", b"ABCDEFG"),
    ("cut to the box's limit (20 bytes)", "abcdefghijklmnopqrstuvwxyz", b"abcdefghijklmnopqrst"),
    ("CR, LF, Tab", "a\rb\nc\td", b"a b c d"),
])
def test_paste_with_unicode_off(plain, label, clip, expect):
    g = plain
    box = g.box(0x14)
    g.paste(box, clip)
    assert g.text(box) == expect, label
    assert g.guard_ok(box)


def test_paste_with_unicode_off_at_the_limit_and_one_past(plain):
    g = plain
    box = g.box(0x14, b"a" * 19)
    g.paste(box, "éx")
    assert g.text(box) == b"a" * 19 + "é".encode("latin-1")
    g.paste(box, "y")
    assert g.text(box) == b"a" * 19 + "é".encode("latin-1")
    assert g.guard_ok(box)


@pytest.mark.parametrize("mod", [SHIFT, 0x0002])
def test_shift_insert_pastes(uni, mod):
    g = uni
    box = g.box(1200)
    g.clipboard = "Insert"
    g.key(INSERT, mod)
    assert g.text(box) == b"Insert"
    assert g.scene_got == [], "the stock Insert message (6, 0x3F4) is not sent while a box has the focus"


# ---- copy and cut
def test_copy_gives_the_whole_text(uni):
    g = uni
    name = "Zoë 日本 \U0001208D\U0001F4A9 " + "Alexandrina " * 20
    box = g.box(1200, name.encode())
    g.key(ord("c"), CTRL)
    assert g.writes == [name]
    assert g.text(box) == name.encode(), "copy leaves the box as it is"
    g.key(INSERT, CTRL)
    assert g.writes == [name, name]
    assert g.changed == [] and g.scene_got == []


def test_copy_with_unicode_off_reads_windows_1252(plain):
    g = plain
    box = g.box(0x14, "Zoë Ž".encode("cp1252"))
    g.key(ord("c"), CTRL)
    assert g.writes == ["Zoë Ž"]


def test_cut_copies_then_empties(uni):
    g = uni
    box = g.box(1200, "Hanako 花子".encode())
    g.key(ord("x"), CTRL)
    assert g.writes == ["Hanako 花子"]
    assert g.text(box) == b""
    assert g.changed == [0xC]
    assert g.guard_ok(box)


# ---- nowhere else
def test_without_a_focused_box_the_keys_go_on_as_in_the_stock_game(harness_dll):
    stock = Game(harness_dll, unicode=True, install=False)
    patched = Game(harness_dll, unicode=True)
    for g in (stock, patched):
        g.box(1200, b"idle", editing=False)               # a box not being typed into
        g.box(1200, b"hidden", shown=False)               # one on a hidden page
        g.clipboard = "PASTE"
        for sym, mod in ((ord("v"), CTRL), (ord("c"), CTRL), (ord("x"), CTRL), (INSERT, SHIFT), (INSERT, CTRL),
                         (INSERT, 0)):
            g.key(sym, mod)
    assert patched.scene_got == stock.scene_got == [(6, 0x3F4, INSERT)] * 3
    assert patched.writes == [] and patched.changed == []
    boxes = [patched.e.r32(node) for node in patched.nodes[1:]]
    assert [patched.text(b) for b in boxes] == [b"idle", b"hidden"]


def test_the_box_texts_are_untouched_without_focus(uni):
    g = uni
    idle = g.box(1200, b"idle", editing=False)
    g.paste(idle, "PASTE")
    g.key(ord("x"), CTRL)
    assert g.text(idle) == b"idle" and g.writes == []


@pytest.mark.parametrize("sym,mod", [(ord("v"), CTRL | ALT), (ord("v"), 0x0080 | 0x0200), (ord("v"), 0),
                                     (ord("v"), CTRL | SHIFT), (ord("b"), CTRL)])
def test_other_keys_are_left_alone(uni, sym, mod):
    g = uni
    box = g.box(1200, b"keep")
    g.clipboard = "PASTE"
    g.key(sym, mod)
    assert g.text(box) == b"keep" and g.writes == [] and g.changed == []
