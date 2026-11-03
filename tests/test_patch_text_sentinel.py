"""The patches' own text is really translated, each line through its own key (the owner, 2026-11-03: "make sure
patches have their text actually translated as-is instead of copied from other stuff").

Every line in data/vf1_patch_strings.json is translated to a SENTINEL ("[[n]]" plus the line's own placeholders)
and followed to where the player would see it:

1. The REAL vf1tr.dll on the REAL exe in Unicorn (tests/translations_emu.py), given a translation file with every
   patch key set to its sentinel, answers VF1Tr_TextW / VF1Tr_TextA with that sentinel for every line, by its key
   (wide lines; the narrow lines the game draws at their room).
2. vf1fun.dll's own code (a harness DLL that includes native/vf1fun/vf1fun.cpp, native/build.bat's settings) on the
   REAL exe in Unicorn, with vf1tr.dll answering the same sentinels: every page's dialog template (its title and
   every control) holds only sentinels; Message / Confirm show the sentinel; the Services, Special Upgrades and
   Patcher Achievements lists and descriptions are filled with their tables' sentinels; every Behavior Label
   Variants caption, written by the game's own strncpy call sites into the villager's label, is its sentinel; the
   Upgrades button's caption handed to the game's ButtonSetText is its sentinel; the Flea Market's messages and list
   show the game's own (translated) item names as text, never as narrow bytes read in the wrong code page.
3. Every marked line is covered: a TR / TR_A line is translated where it is written (the macro is the Tr call);
   every TR_N / TR_NA line was asked for and answered by its sentinel in part 2.

No English line of a patch reaches a page, a list, a message, a caption or a button untranslated, and no patch text
is a copy of a stock string: a stock string reaching a patch window is the game's own line (its own key)."""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import translation_format as tfmt  # noqa: E402
import vf1_patch_text as pt  # noqa: E402
import vf1_translation_strings as vts  # noqa: E402

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")
VILLAGERS = 0x5B8898 + 0x14640
STRIDE = 0x145FC
LABEL = 0x13594

PAGES = ["UpgradesTemplate", "CheatsTemplate", "VillagerCheatsTemplate", "FleaMarketTemplate",
         "StoreCheatsTemplate", "HouseTemplate", "PurchasesTemplate", "TimeTemplate", "FamilyTemplate",
         "AppearanceTemplate", "ServicesTemplate", "AchievementsTemplate"]

HARNESS = r'''
#include "@SOURCE@"
typedef Template &(*PageFn)();
static const PageFn kPageFns[] = { @PAGES@ };
extern "C" __declspec(dllexport) const WORD *__cdecl T_Page(int i, int *words) {
    Template &t = kPageFns[i]();
    *words = t.Size();
    return (const WORD *)t.Get();
}
extern "C" __declspec(dllexport) void __cdecl T_Message(const wchar_t *text) { Message((HWND)0x77, text); }
extern "C" __declspec(dllexport) int __cdecl T_Confirm(const wchar_t *text) { return Confirm((HWND)0x77, text); }
extern "C" __declspec(dllexport) void __cdecl T_Labels() { InstallBehaviorLabelVariants(true, true); }
extern "C" __declspec(dllexport) void __cdecl T_Private() { gPrivateRomantic = true; gVillage.sameSex = 1; }
extern "C" __declspec(dllexport) void __cdecl T_Services() { FillServices((HWND)0x77); }
extern "C" __declspec(dllexport) void __cdecl T_Purchases() { FillPurchases((HWND)0x77); }
extern "C" __declspec(dllexport) void __cdecl T_Achievements() { AchievementsProc((HWND)0x77, WM_INITDIALOG, 0, 0); }
extern "C" __declspec(dllexport) void __cdecl T_Upgrades(void *scene) { AddUpgradesButton(scene); }
extern "C" __declspec(dllexport) void __cdecl T_FleaList() { FleaProc((HWND)0x77, WM_INITDIALOG, 0, 0); }
extern "C" __declspec(dllexport) void __cdecl T_FleaBuy() { BuyItem((HWND)0x77, false); }
extern "C" __declspec(dllexport) int __cdecl T_FreeRefused() { return FreeCheatsRefused((HWND)0x77); }
'''


def sentinel(i: int, entry) -> str:
    """Line i's sentinel: its number and the English's own placeholders (a translation must keep them)."""
    source = tfmt.english_source(entry.english, entry.is_format)
    parts = [f"[[{i}]]"] + [c.text for c in source.conversions] + (["%%"] if source.double_percent else [])
    return " ".join(parts)


@pytest.fixture(scope="module")
def entries():
    out = vts.patch_entries()
    assert len(out) > 400
    return out


@pytest.fixture(scope="module")
def sentinels(entries):
    return {e.english: sentinel(i, e) for i, e in enumerate(entries)}


def _vanilla_exe() -> Path:
    if not os.environ.get("VF1_VANILLA_DIR"):
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    exe = Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe"
    if not exe.is_file():
        pytest.skip("VF1_VANILLA_DIR has no Virtual Families.exe")
    return exe


def _env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


# ============================================================================ 1. the real vf1tr.dll
@pytest.fixture(scope="module")
def tr_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("tr_sentinel")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_tr.bat")], capture_output=True, text=True,
                       env=dict(_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr
    return out / "vf1tr.dll"


def test_vf1tr_answers_every_patch_line_with_its_own_sentinel(tr_dll, entries, sentinels):
    pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    from test_translations_runtime import text_a, text_w, world
    exe = _vanilla_exe()
    rows = [(e.key, e.english, sentinels[e.english]) for e in entries]
    w, _tf = world(exe, tr_dll, rows)
    assert w.installed == 1, w.log()
    narrow = {row["english"] for row in vts._patch_rows() if row.get("drawn_by_game")}
    for e in entries:
        want = tfmt.runtime_text(sentinels[e.english], e.english, e.is_format)
        if e.english in narrow:
            got = text_a(w, e.english, e.max_length)[2].decode("cp1252")
        else:
            got = text_w(w, e.english)[2]
        assert got == want, e.english


# ============================================================================ 2. vf1fun.dll's own code
@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    tmp = tmp_path_factory.mktemp("sentinel")
    src = tmp / "sentinel_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()).replace("@PAGES@", ", ".join(PAGES)),
                   encoding="utf-8")
    dll = tmp / "sentinel_harness.dll"
    script = tmp / "build.bat"
    script.write_text("@echo off\r\n"
                      f'call "{VCVARS}" >nul || exit /b 1\r\n'
                      f'cl /nologo /O2 /MT /EHsc /W3 /LD "{src}" /Fo"{tmp}\\\\" /Fe"{dll}" '
                      "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n",
                      encoding="ascii")
    r = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return dll


GAME_ITEM_NAME = "Caf\u00e9 \u65e5\u672c \u2615"          # the game's own (translated) item name, UTF-8


@pytest.fixture
def emu(harness_dll, sentinels):
    exe = _vanilla_exe()
    pytest.importorskip("unicorn")
    import kids_emu
    e = kids_emu.Emu(exe, harness_dll)
    e.asked: list[str] = []               # every English vf1fun asked vf1tr for
    e.sinks: list[tuple[str, str]] = []   # (where, text) that reached a window, a list, the game
    cache: dict[str, int] = {}

    def keep(text: str, wide: bool) -> int:
        k = ("w" if wide else "a") + text
        if k not in cache:
            data = text.encode("utf-16-le") + b"\0\0" if wide else text.encode("cp1252") + b"\0"
            cache[k] = e.alloc(len(data) + 4)
            e.write(cache[k], data)
        return cache[k]

    def text_w(emu):
        english = emu.wstr(emu.arg(0))
        emu.asked.append(english)
        s = sentinels.get(english)
        return (keep(tfmt.runtime_text(s, english, None), True) if s else emu.arg(0)), 0

    def text_a(emu):
        english = emu.cstr(emu.arg(0))
        emu.asked.append(english)
        s = sentinels.get(english)
        return (keep(s, False) if s and len(s) <= emu.arg(1) else emu.arg(0)), 0

    e.modules["vf1tr.dll"] = 0x6900
    e.dyn_procs.update({"VF1Tr_TextW": text_w, "VF1Tr_TextA": text_a, "VF1Tr_English": lambda emu: (0, 0),
                        "QueryActCtxW": lambda emu: (1, 28), "FindActCtxSectionStringW": lambda emu: (0, 20)})

    def module_handle_ex(emu):
        emu.w32(emu.arg(2), 0x30000000)
        return 1, 12
    e.dyn_procs["GetModuleHandleExW"] = module_handle_ex

    def message(emu):
        e.sinks.append(("message", emu.wstr(emu.arg(1))))
        e.sinks.append(("title", emu.wstr(emu.arg(2))))
        return 6, 16

    e.cursel = 0xFFFFFFFF

    def send(emu):
        hwnd, msg, wp, lp = (emu.arg(i) for i in range(4))
        if msg == 0x180:                                    # LB_ADDSTRING
            e.sinks.append((f"list {hwnd - 0x1000}", emu.wstr(lp)))
            return 0, 16
        if msg == 0x188:                                    # LB_GETCURSEL
            return e.cursel, 16
        if msg == 0x199:                                    # LB_GETITEMDATA
            return e.itemdata, 16
        return 0, 16

    def virtual_protect(emu):
        if emu.arg(3):
            emu.w32(emu.arg(3), 0x40)
        return 1, 16

    def set_item_text(emu):
        e.sinks.append((f"control {emu.arg(1)}", emu.wstr(emu.arg(2))))
        return 1, 12

    e.imports.update({
        "MessageBoxW": message, "SendMessageW": send, "SetDlgItemTextW": set_item_text,
        "GetDlgItem": lambda emu: (0x1000 + emu.arg(1), 8), "ShowWindow": lambda emu: (1, 8),
        "EnableWindow": lambda emu: (0, 8), "GetLastError": lambda emu: (0, 0),
        "GetTickCount": lambda emu: (12345, 0), "IsDlgButtonChecked": lambda emu: (0, 8),
        "VirtualProtect": virtual_protect, "FlushInstructionCache": lambda emu: (1, 12),
        "GetCurrentProcess": lambda emu: (0xFFFFFFFF, 0),
    })
    name = e.alloc(64)
    e.write(name, GAME_ITEM_NAME.encode("utf-8") + b"\0")
    e.strings = e.alloc(16)
    e.seam(0x450530, lambda emu: (e.strings, 0))           # theStringManager::Get
    e.seam(0x44FD90, lambda emu: (name, 4))                # GetString: the game's own line
    e.itemdata = 0
    return e


def page_texts(e, i: int) -> list[str]:
    """The title and every control's text of page i's dialog template, as the dialog manager reads it."""
    out_words = e.alloc(4)
    at = e.call(e.dll_export("T_Page"), (i, out_words))
    words = struct.unpack(f"<{e.r32(out_words)}H", e.read(at, 2 * e.r32(out_words)))

    def string(n):
        k = n
        while words[k]:
            k += 1
        return "".join(map(chr, words[n:k])), k + 1

    n = 9 + 2                                              # DLGTEMPLATE, menu, class
    title, n = string(n)
    texts = [title]
    n += 1                                                 # point size
    _face, n = string(n)
    count = words[4]                                       # DLGTEMPLATE.cdit
    for _ in range(count):
        if n % 2:
            n += 1
        n += 9                                             # DLGITEMTEMPLATE
        n += 2 if words[n] == 0xFFFF else string(n)[1] - n # class
        text, n = string(n)
        texts.append(text)
        n += 1                                             # creation data
    return texts


def untranslated(text: str, sentinels: dict) -> bool:
    """Text that still holds a patch line's English, or words that are no sentinel."""
    rest = re.sub(r"\[\[\d+\]\]", "", text)
    return text in sentinels or pt.looks_shown(rest)


def test_every_page_holds_only_sentinels(emu, sentinels):
    for i, page in enumerate(PAGES):
        texts = page_texts(emu, i)
        assert len(texts) > 2, page
        bad = [t for t in texts if untranslated(t, sentinels)]
        assert bad == [], (page, bad)
        assert any(t.startswith("[[") for t in texts), page


def test_message_and_confirm_show_the_sentinel(emu, sentinels):
    for english in ("Pick an item first.", "You don't have enough money for that."):
        at = emu.alloc(200)
        emu.write(at, english.encode("utf-16-le") + b"\0\0")
        emu.call(emu.dll_export("T_Message"), (at,))
        emu.call(emu.dll_export("T_Confirm"), (at,))
    shown = [t for _w, t in emu.sinks]
    assert len(shown) == 8 and all(t.startswith("[[") for t in shown), shown


def test_the_lists_and_descriptions_are_their_tables_sentinels(emu, sentinels):
    for k in range(8):                                     # each service picked once: its description
        emu.cursel = k
        emu.call(emu.dll_export("T_Services"))
    for k in range(6):
        emu.cursel = k
        emu.call(emu.dll_export("T_Purchases"))
    emu.call(emu.dll_export("T_Achievements"))
    texts = [t for _w, t in emu.sinks]
    assert len(texts) > 40
    bad = [t for t in texts if untranslated(t, sentinels)]
    assert bad == [], bad


def villager(slot):
    return VILLAGERS + slot * STRIDE


def test_every_caption_the_game_writes_is_its_sentinel(emu, sentinels):
    """Each Behavior Label Variants call site: the game's own strncpy call instruction runs (retargeted by the DLL),
    many times; whatever lands in the villager's 40-byte label is the game's own caption or a sentinel, and every
    caption of the site's tables is asked for and lands at least once as its sentinel."""
    import kids_emu as K
    e = emu
    e.call(e.dll_export("T_Labels"))
    e.call(e.dll_export("T_Private"))
    family = e.alloc(0x200)                                # the current family: two adults of the same sex
    e.write(family, b"\x01")
    for off, slot in ((4, 0), (0xDC, 1)):
        e.write(family + off + 0x1A, b"\x01")
        e.w32(family + off + 0x28, slot)
    e.seam(0x481730, lambda emu: (family, 0))
    clock = [0]

    def is_day(emu):                                       # CNight::IsDay: day and night by turns
        clock[0] += 1
        return clock[0] & 1, 0
    e.seam(0x491630, is_day)
    for slot in (0, 1):
        v = villager(slot)
        e.write(v + 0x13574, b"\x01")
        e.w32(v + 0x2AE0, 80)                             # health: present
        e.w32(v + 0x2A38, 1)                              # female
        e.w32(v + 0x2A34, 0x200)                          # an adult
        e.w32(v + 0x2B6C, 3)                              # with a career
    stock = e.alloc(64)
    e.write(stock, b"The game's own caption\0")
    landed = set()
    labels = (ROOT / "native" / "vf1fun" / "labels.inc").read_text(encoding="utf-8")
    sites = [int(a, 16) for a in re.findall(r"\{ 0x([0-9A-F]+) \+ 5, L_[A-Z]+ \}", labels)]
    assert len(sites) > 40
    profiles = [(age, female, career) for age in (0x60, 0x108, 0x120, 0x200) for female in (0, 1)
                for career in ((-1, 3) if age == 0x200 else (-1,))]
    for (age, female, career), site in [(p, s) for p in profiles for s in sites]:
        for slot in (0, 1):
            e.w32(villager(slot) + 0x2A38, female)
            e.w32(villager(slot) + 0x2A34, age)
            e.w32(villager(slot) + 0x2B6C, career)
        for _ in range(120):
            dest = villager(0) + LABEL
            e.write(dest, b"\0" * 40)
            esp = e.sp_top - 0x100
            e.w32(esp, dest)
            e.w32(esp + 4, stock)
            e.w32(esp + 8, 0x27)
            e.setreg(K.UC_X86_REG_ESP, esp)
            e.uc.emu_start(site, site + 5)
            got = e.read(dest, 40).split(b"\0", 1)[0].decode("cp1252")
            assert got == "The game's own caption" or (got.startswith("[[") and got in sentinels.values()), got
            if got.startswith("[["):
                landed.add(got)
    captions = {lit.text for lit in pt.literals("vf1fun") if lit.marker == "TR_NA" and lit.path.endswith("labels.inc")}
    assert {sentinels[c] for c in captions} <= landed


def test_the_upgrades_button_gets_its_sentinel(emu, sentinels):
    e = emu
    got = []
    e.seam(0x497B14, lambda emu: (emu.alloc(0x40), 0))    # operator new
    e.seam(0x44F7C0, lambda emu: (0x2222, 0))             # theGraphicsManager::Get
    e.seam(0x44F5A0, lambda emu: (0x3333, 4))             # GetImageGrid
    e.seam(0x4019F0, lambda emu: (emu.ecx, 24))           # the button's constructor

    def set_text(emu):                                     # ButtonSetText(text, c1, c2, c3, font)
        got.append(emu.cstr(emu.arg(0)))
        return 0, 20
    e.seam(0x4015D0, set_text)
    e.seam(0x401440, lambda emu: (80, 0))
    e.seam(0x401430, lambda emu: (0, 8))
    e.seam(0x40C4B0, lambda emu: (0, 4))
    e.call(e.dll_export("T_Upgrades"), (e.alloc(0x100),))
    assert got == [sentinels["Upgrades"]]


def test_the_flea_market_shows_the_games_own_item_names_as_text(emu, sentinels):
    """The game's own item name (its own line, translated by its own key, UTF-8 with a Unicode setting) is shown as
    the same characters in the list and in both messages; the message itself is the patch line's sentinel."""
    e = emu
    e.call(e.dll_export("T_FleaList"))
    lines = [t for w, t in e.sinks if w.startswith("list")]
    assert lines and all(t.startswith(GAME_ITEM_NAME + "\t$") for t in lines), lines[:3]
    e.sinks.clear()
    e.cursel, e.itemdata = 0, 1
    e.seam(0x4973E0, lambda emu: (1, 8))                   # TrayAddItem
    e.seam(0x4968E0, lambda emu: (0, 4))                   # GetUseCount
    e.seam(0x422740, lambda emu: (0, 8))                   # CMoney::Adjust
    e.write(0x50C60C, struct.pack("<f", 1e9))
    e.call(e.dll_export("T_FleaBuy"))
    shown = [t for w, t in e.sinks if w == "message"]
    buy, bought = sentinels["Buy %ls for $%d?"].split(" ")[0], sentinels["Purchased: %ls."].split(" ")[0]
    assert len(shown) == 2 and shown[0].startswith(buy + " " + GAME_ITEM_NAME + " ") and \
        shown[1] == bought + " " + GAME_ITEM_NAME, shown


# ============================================================================ 3. every marked line is covered
def test_every_marked_line_is_translated_where_it_is_shown(emu, sentinels):
    """TR / TR_A: the macro is the Tr / TrA call at the line itself. TR_N / TR_NA: asked for (and answered with its
    sentinel) by the runs of part 2, which make every page, list, caption and the button."""
    e = emu
    for i in range(len(PAGES)):
        page_texts(e, i)
    for k in range(8):
        e.cursel = k
        e.call(e.dll_export("T_Services"))
    for k in range(6):
        e.cursel = k
        e.call(e.dll_export("T_Purchases"))
    e.call(e.dll_export("T_Achievements"))
    e.call(e.dll_export("T_FreeRefused"))
    for lit in pt.literals("vf1fun"):                   # a line handed to Message / Confirm as it is
        if lit.marker == "TR_N" and lit.call in ("Message", "Confirm") and lit.argument == 1:
            at = e.alloc(len(lit.text) * 2 + 4)
            e.write(at, lit.text.encode("utf-16-le") + b"\0\0")
            e.sinks.clear()
            e.call(e.dll_export("T_Message" if lit.call == "Message" else "T_Confirm"), (at,))
            assert e.sinks[0] == ("message", tfmt.runtime_text(sentinels[lit.text], lit.text, None)), lit.text
    asked = set(e.asked)
    defs = (ROOT / "native" / "vf1fun" / "translate.inc").read_text(encoding="utf-8")
    assert "#define TR(s) Tr(s)" in defs and "#define TR_A(room, s) TrA(s, room)" in defs
    missing = []
    for lit in pt.literals("vf1fun"):
        if lit.marker in ("TR_N", "TR_NA") and lit.text not in asked:
            if lit.path.endswith("labels.inc"):
                continue                                   # proved by test_every_caption_the_game_writes_is_its_sentinel
            missing.append(f"{lit.path}:{lit.line} {lit.text!r} ({lit.call or 'a table'})")
    assert missing == [], "\n".join(missing)
