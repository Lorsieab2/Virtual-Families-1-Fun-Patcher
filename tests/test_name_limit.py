"""One character limit for every name box: patcher/vf1_text.NAME_LETTERS (300), the box buffer at the LDW engine's
own cap (1,200 bytes), the short form in the save and the whole name in the save's Names file (patcher/vf1_names.py,
native/vf1text/names.inc).

The game's side is proved with the REAL vf1text.dll and vf1font.dll on the REAL vanilla executable in Unicorn
(tests/names_emu.py): every name box is set up from its own call site, typed into at the limit and one past it, and
read back by the game's own instructions from each GetText call to the end of the copy that follows it, with guard
bytes around every buffer the game writes."""
import os
import random
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

import vf1_names
import vf1_text

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")
UNICODE_KEY = 0x40000000
LETTERS = vf1_text.NAME_LETTERS
BOX = vf1_text.NAME_BOX_BYTES

# (SetEditable call site, the stock limit it passes, what the box is)
NAME_BOXES = [
    (0x41BB4F, 0x14, "slot menu, slot 1"), (0x41BBEF, 0x14, "slot menu, slot 2"),
    (0x41BC91, 0x14, "slot menu, slot 3"), (0x41BD36, 0x14, "slot menu, slot 4"),
    (0x41BDF0, 0x14, "slot menu, slot 5"), (0x41BF15, 0x14, "slot menu, New Player"),
    (0x41C67C, 0x14, "the first family's name"), (0x435AFB, 0x12, "adoption"), (0x437955, 0x12, "a new baby"),
    (0x44A6DE, 0x12, "renaming a family member"),
]
NOT_NAMES = [(0x4172A8, 0x50, "a Job / Likes dialog's 80-byte field"), (0x43F1B0, 0x14, "the animation tool"),
             (0x43F200, 0x1F, "the animation tool")]


def build_env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("names_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=dict(build_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.fixture(params=["vf1text.dll", "vf1font.dll"])
def dll(request, built):
    return built / request.param


def make_world(dll, vanilla_dir, fs=None):
    import names_emu
    # vf1font.dll draws every letter with Windows: its GDI calls are made by the real GDI (text_emu.RealGdi)
    w = names_emu.NamesWorld(vanilla_dir / "Virtual Families.exe", dll, vanilla_dir, install=True,
                             real_gdi=dll.name == "vf1font.dll")
    assert w.installed == 1
    if fs:
        w.fs.update(fs)
    w.set_slot(2)
    return w


@pytest.fixture
def world(dll, vanilla_dir):
    return make_world(dll, vanilla_dir)


def name_box(w, site=0x435AFB, limit=0x12):
    ctl, impl = w.control()
    w.set_editable_from(site, ctl, limit)
    w.e.write(impl + 0x25, b"\x01")           # being typed into
    w.e.write(impl + 0x2C, b"\x01")           # shown
    return ctl, impl


def names_in(w, slot):
    data = w.fs.get(w.names_file(slot))
    return vf1_names.parse(data) if data is not None else []


# --------------------------------------------------------------------------- the constant
def test_the_limit_is_one_constant_in_one_place():
    assert (LETTERS, BOX, vf1_text.NAME_MARK) == (300, 1200, "...")
    assert vf1_names.NAME_LETTERS is LETTERS
    r = subprocess.run(["python", str(ROOT / "scripts" / "build_vf1_text_tables.py"), "--check"], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout
    inc = (ROOT / "native" / "vf1text" / "extenders.inc").read_text(encoding="utf-8")
    assert f"#define VF1_NAME_LETTERS {LETTERS} " in inc and f"#define VF1_NAME_BOX_BYTES {BOX} " in inc
    # nothing else in the DLL sources spells the number
    for src in (ROOT / "native" / "vf1text").glob("*.*"):
        if src.name != "extenders.inc":
            text = src.read_text(encoding="utf-8")
            assert "1200" not in text and " 300" not in text.replace("0x300", ""), src.name


def test_the_engine_caps_every_box_at_1200_bytes(vanilla_dir):
    """The ceiling: SetEditable 0x40D370 clamps the limit to 0x4B0 (cmp edx, 0x4B0 / mov edx, 0x4B0 at 0x40D3B3)."""
    import pefile
    import vf1_patcher
    pe = pefile.PE(str(vanilla_dir / vf1_patcher.VANILLA_EXE), fast_load=True)
    assert pe.get_data(0x40D3B3 - pe.OPTIONAL_HEADER.ImageBase, 13) == bytes.fromhex("81FAB00400007C05BAB0040000")
    assert 0x4B0 == BOX


# --------------------------------------------------------------------------- the boxes
def test_installs_every_site(world):
    assert world.e.r32(world.e.dll_export("VF1Text_Installed")) == 0x3FF


@pytest.mark.parametrize("site,limit,what", NAME_BOXES)
def test_every_name_box_takes_the_limit_and_refuses_one_more(dll, vanilla_dir, site, limit, what):
    w = make_world(dll, vanilla_dir)
    ctl, impl = name_box(w, site, limit)
    assert w.e.r32(impl + 0x28) == BOX, what
    buf, size = w.news[-1]
    assert size == BOX + 1 and w.box_buffer(impl) == buf
    w.type_text(impl, "a" * LETTERS)
    assert w.box_bytes(impl) == b"a" * LETTERS
    w.type_text(impl, "b")
    assert w.box_bytes(impl) == b"a" * LETTERS, "the 301st character is refused"
    # 300 four-byte characters fill the whole buffer exactly; the next one is refused
    ctl, impl = name_box(w, site, limit)
    w.type_text(impl, "\U0001F600" * LETTERS)
    assert w.box_bytes(impl) == ("\U0001F600" * LETTERS).encode()
    w.press(impl, UNICODE_KEY | 0xE9)
    w.press(impl, ord("x"))
    assert len(w.box_bytes(impl)) == BOX
    assert w.guards_intact(), "nothing was written past a buffer"


def test_the_byte_cap_stops_heavy_characters_first(world):
    w = world
    ctl, impl = name_box(w)
    family = "\U0001F469\u200D\U0001F469\u200D\U0001F467"      # 18 bytes, one character
    w.type_text(impl, family * 70)                             # typed a code point at a time, as SDL posts them
    got = w.box_bytes(impl)
    # 66 whole (1,188 bytes), then the 67th's code points while they fit: woman, joiner, woman (1,199 bytes)
    assert got == (family * 66 + "\U0001F469‍\U0001F469").encode()
    w.type_text(impl, "abc")
    assert w.box_bytes(impl) == got + b"a"                    # exactly 1,200 bytes: nothing more fits
    assert w.guards_intact()


def test_combining_marks_do_not_count_as_characters(world):
    w = world
    ctl, impl = name_box(w)
    w.type_text(impl, "a" * (LETTERS - 1) + "e\u0301\u0302")
    assert w.box_bytes(impl).decode() == "a" * (LETTERS - 1) + "e\u0301\u0302"
    w.type_text(impl, "z")
    assert vf1_text.char_count(w.box_bytes(impl).decode()) == LETTERS


def test_backspace_removes_one_whole_character(world):
    w = world
    ctl, impl = name_box(w)
    w.type_text(impl, "Ana e\u0301\U0001F44D\U0001F3FD\U0001F1EF\U0001F1F5")
    for expect in ("Ana e\u0301\U0001F44D\U0001F3FD", "Ana e\u0301", "Ana ", "Ana"):
        w.press(impl, 8)
        assert w.box_bytes(impl).decode() == expect


@pytest.mark.parametrize("site,limit,what", NOT_NAMES)
def test_other_boxes_keep_their_stock_limit(world, site, limit, what):
    w = world
    ctl, impl = w.control()
    w.set_editable_from(site, ctl, limit)
    assert w.e.r32(impl + 0x28) == limit, what
    w.e.write(impl + 0x25, b"\x01")
    w.type_text(impl, "x" * (limit + 5))
    assert w.box_bytes(impl) == b"x" * limit


# --------------------------------------------------------------------------- the game's copies
LONG = "Alexandrina Maximiliana Theodora Wilhelmina " * 7          # 308 characters
MEMBER = (LONG[:LETTERS - 1] + "Z")
FULL = LONG[:LETTERS].strip()               # 299 characters


def member_text_cases():
    return [
        ("fits exactly (18 bytes)", "a" * 18),
        ("one past the field (19 bytes)", "a" * 19),
        ("300 plain characters", MEMBER),
        ("300 four-byte characters (1,200 bytes)", "\U0001F600" * LETTERS),
        ("300 accented characters", "\u00e9" * LETTERS),
    ]


def stored_for(name, room, taken=None):
    return vf1_names.short_form(name, room, dict(taken or {}))


def check_names_file(w, slot, stored, name, room):
    entries = names_in(w, slot)
    if stored == name:
        assert all(e.full != name for e in entries)
    else:
        assert vf1_names.Entry(stored, room, name) in entries


@pytest.mark.parametrize("label,name", member_text_cases())
def test_adoption_stores_the_short_form_and_the_whole_name(world, label, name):
    """0x43681A..0x43684D: GetText(local, 0x13), then strncpy(villager + 0x2A44, local, 0x19)."""
    import kids_emu as K
    w = world
    ctl, impl = name_box(w, 0x435AFB, 0x12)
    w.type_text(impl, name)
    assert w.box_bytes(impl).decode() == name
    dlg = w.e.alloc(0x100)
    w.e.w32(dlg + 0x54, ctl)
    villager = w.e.alloc(0x2C00, fill=0xCC)
    base = w.frame()
    w.run_window(0x43681A, 0x43684D, {K.UC_X86_REG_ECX: w.gs, K.UC_X86_REG_EBP: dlg, K.UC_X86_REG_ESI: villager,
                                       K.UC_X86_REG_EDI: 7}, esp=base)
    expect = stored_for(name, 18)
    raw = expect.encode()
    assert w.e.read(base + 0x14, 0x13) == raw + b"\0" * (0x13 - len(raw))      # GetText's local, zero-padded
    assert w.e.read(base + 0x14 + 0x13, 0x40) == b"\xCC" * 0x40, "nothing past the 0x13-byte local"
    field = w.e.read(villager + 0x2A44, 0x19)
    assert field == raw + b"\0" * (0x19 - len(raw))
    assert w.e.read(villager, 0x2A44) == b"\xCC" * 0x2A44
    assert w.e.read(villager + 0x2A44 + 0x19, 0x100) == b"\xCC" * 0x100
    assert len(raw) <= 18 and vf1_text.is_utf8(raw)
    check_names_file(w, 2, expect, name, 18)
    assert w.guards_intact()


@pytest.mark.parametrize("label,name", member_text_cases())
def test_a_new_baby_stores_the_short_form(world, label, name):
    """0x438291..0x4382BF: GetText(local, 0x13), then strncpy(villager + 0x2A44, local, 0x19)."""
    import kids_emu as K
    w = world
    ctl, impl = name_box(w, 0x437955, 0x12)
    w.type_text(impl, name)
    dlg = w.e.alloc(0x40)
    w.e.w32(dlg + 0x14, ctl)
    villager = w.e.alloc(0x2C00, fill=0xCC)
    base = w.frame()
    w.run_window(0x438291, 0x4382BF, {K.UC_X86_REG_EBX: dlg, K.UC_X86_REG_EBP: villager}, esp=base)
    raw = stored_for(name, 18).encode()
    assert w.e.read(base + 0x18, 0x13) == raw + b"\0" * (0x13 - len(raw))
    assert w.e.read(base + 0x18 + 0x13, 0x40) == b"\xCC" * 0x40
    assert w.e.read(villager + 0x2A44, 0x19) == raw + b"\0" * (0x19 - len(raw))
    assert w.e.read(villager + 0x2A44 + 0x19, 0x100) == b"\xCC" * 0x100
    check_names_file(w, 2, raw.decode(), name, 18)


@pytest.mark.parametrize("start,stop", [(0x44BCD2, 0x44BD13), (0x44BDCF, 0x44BE10)])
@pytest.mark.parametrize("label,name", member_text_cases())
def test_renaming_a_member_stores_the_short_form(world, start, stop, label, name):
    """GetText(local, 0x13), FamilyTree::ChangeName(villager, local) (copies at most 0x19, 0x481C3A), then
    strncpy(villager + 0x2A44, local, 0x19)."""
    import kids_emu as K
    w = world
    ctl, impl = name_box(w, 0x44A6DE, 0x12)
    w.type_text(impl, name)
    dlg = w.e.alloc(0x200)
    w.e.w32(dlg + 0x128, ctl)
    villager = w.e.alloc(0x2C00, fill=0xCC)
    base = w.frame()
    regs = {K.UC_X86_REG_ESI: dlg, K.UC_X86_REG_EAX: villager}
    if start == 0x44BDCF:
        regs[K.UC_X86_REG_ECX] = 0
    w.run_window(start, stop, regs, esp=base)
    raw = stored_for(name, 18).encode()
    assert w.e.read(base + 8, 0x13) == raw + b"\0" * (0x13 - len(raw))
    assert w.e.read(base + 8 + 0x13, 0x40) == b"\xCC" * 0x40
    assert w.change_names == [raw]
    assert w.e.read(villager + 0x2A44, 0x19) == raw + b"\0" * (0x19 - len(raw))
    assert w.e.read(villager + 0x2A44 + 0x19, 0x100) == b"\xCC" * 0x100
    assert w.e.read(villager, 0x2A44) == b"\xCC" * 0x2A44


FAMILY_CASES = [("fits exactly (19 bytes)", "b" * 19), ("one past the field (20 bytes)", "b" * 20),
                ("300 characters", LONG[:LETTERS]), ("1,200 bytes", "\U0001F600" * LETTERS)]


@pytest.mark.parametrize("label,name", FAMILY_CASES)
def test_the_first_family_name_stores_the_short_form(world, label, name):
    """0x41C71F..0x41C74C: GetText(gs + 0x1B12C, 0x14), then strcpy(gs + 0x1B192, gs + 0x1B12C)."""
    import kids_emu as K
    w = world
    ctl, impl = name_box(w, 0x41C67C, 0x14)
    w.type_text(impl, name)
    dlg = w.e.alloc(0x100)
    w.e.w32(dlg + 0x4C, ctl)
    w.e.write(w.gs + 0x1B100, b"\xCC" * 0x200)
    base = w.frame()
    w.run_window(0x41C71F, 0x41C74C, {K.UC_X86_REG_EBP: dlg, K.UC_X86_REG_ESI: w.gs}, esp=base)
    raw = stored_for(name, 19).encode()
    assert len(raw) <= 19
    after = w.e.read(w.gs + 0x1B100, 0x200)
    fam = 0x1B12C - 0x1B100
    menu = 0x1B192 - 0x1B100
    assert after[fam:fam + 0x14] == raw + b"\0" * (0x14 - len(raw))
    assert after[menu:menu + len(raw) + 1] == raw + b"\0"
    assert after[:fam] == b"\xCC" * fam
    assert after[fam + 0x14:menu] == b"\xCC" * (menu - fam - 0x14)
    assert after[menu + len(raw) + 1:] == b"\xCC" * (0x200 - menu - len(raw) - 1), "nothing past slot 1's 21 bytes"
    check_names_file(w, 1, raw.decode(), name, 19)


@pytest.mark.parametrize("slot,start,stop,setup",
                         [(1, 0x41C1AE, 0x41C1DE, 0x41BB4F), (2, 0x41C1FA, 0x41C22E, 0x41BBEF),
                          (3, 0x41C24A, 0x41C27E, 0x41BC91), (4, 0x41C29A, 0x41C2CE, 0x41BD36),
                          (5, 0x41C2E7, 0x41C316, 0x41BDF0)])
@pytest.mark.parametrize("label,name", FAMILY_CASES)
def test_new_player_in_each_slot_stores_the_short_form(world, slot, start, stop, setup, label, name):
    """GetText(gs + 0x1B192 + 0x15 (k - 1), 0x14), then strcpy(gs + 0x1B12C, it)."""
    import kids_emu as K
    w = world
    ctl, impl = name_box(w, setup, 0x14)
    w.type_text(impl, name)
    dlg = w.e.alloc(0x100)
    w.e.w32(dlg + 0x4C, w.gs)
    w.e.write(w.gs + 0x1B100, b"\xCC" * 0x200)
    base = w.frame()
    w.run_window(start, stop, {K.UC_X86_REG_ESI: dlg, K.UC_X86_REG_EDI: ctl, K.UC_X86_REG_EBX: 0}, esp=base)
    raw = stored_for(name, 19).encode()
    after = w.e.read(w.gs + 0x1B100, 0x200)
    menu = 0x1B192 + 0x15 * (slot - 1) - 0x1B100
    fam = 0x1B12C - 0x1B100
    assert after[menu:menu + 0x14] == raw + b"\0" * (0x14 - len(raw))
    assert after[fam:fam + len(raw) + 1] == raw + b"\0"
    keep = set(range(menu, menu + 0x14)) | set(range(fam, fam + len(raw) + 1))
    assert all(after[i] == 0xCC for i in range(0x200) if i not in keep), "nothing else of theGameState"
    check_names_file(w, slot, raw.decode(), name, 19)


# --------------------------------------------------------------------------- the short form
def test_short_forms_are_unique_and_match_the_patcher(world):
    """Names sharing their start get "...", "2...", "3..."; the DLL's rule is vf1_names.short_form."""
    w = world
    rng = random.Random(7)
    taken: dict[str, str] = {}
    names = [LONG[:40] + str(k) for k in range(4)] + ["Zoë " * 30, "日本" * 40, "a" * 18, "b" * 19,
                                                       LONG[:40] + "0"]
    names += ["".join(rng.choice("ab é日😀") for _ in range(rng.randint(10, 60))) for _ in range(20)]
    for name in names:
        ctl, impl = name_box(w)
        w.type_text(impl, name)
        stored = stored_for(name, 18, taken)
        import kids_emu as K
        dlg = w.e.alloc(0x100)
        w.e.w32(dlg + 0x54, ctl)
        villager = w.e.alloc(0x2C00)
        base = w.frame()
        w.run_window(0x43681A, 0x43684D, {K.UC_X86_REG_ECX: w.gs, K.UC_X86_REG_EBP: dlg,
                                           K.UC_X86_REG_ESI: villager, K.UC_X86_REG_EDI: 0}, esp=base)
        assert w.e.read(villager + 0x2A44, 0x19).split(b"\0", 1)[0].decode() == stored, name
        if stored != name:
            taken.setdefault(stored, name)
    entries = names_in(w, 2)
    assert {e.short: e.full for e in entries} == taken
    shorts = [e.short for e in entries]
    assert len(shorts) == len(set(shorts))
    assert LONG[:15] + "..." in shorts and LONG[:14] + "2..." in shorts


def test_the_same_name_again_keeps_its_short_form(world):
    w = world
    import kids_emu as K
    out = []
    for _ in range(2):
        ctl, impl = name_box(w, 0x44A6DE, 0x12)
        w.type_text(impl, LONG)
        dlg = w.e.alloc(0x200)
        w.e.w32(dlg + 0x128, ctl)
        villager = w.e.alloc(0x2C00)
        w.run_window(0x44BCD2, 0x44BD13, {K.UC_X86_REG_ESI: dlg, K.UC_X86_REG_EAX: villager}, esp=w.frame())
        out.append(w.e.read(villager + 0x2A44, 0x19))
    assert out[0] == out[1]
    assert len(names_in(w, 2)) == 1


def test_a_rename_box_opens_with_the_whole_name(world):
    w = world
    w.fs[w.names_file(2)] = vf1_names.render([vf1_names.Entry("Alexandrina Ma...", 18, FULL)])
    ctl, impl = w.control()
    w.set_text(ctl, b"Alexandrina Ma...")
    w.set_editable_from(0x44A6DE, ctl, 0x12)
    assert w.box_bytes(impl).decode() == FULL
    # and SetText on a box that is already a name box
    w.set_text(ctl, b"Alexandrina Ma...")
    assert w.box_bytes(impl).decode() == FULL
    assert w.guards_intact()


# --------------------------------------------------------------------------- drawing
def fitted(w, name, room, font="SegoeUiBold18"):
    """The whole name fitted into the width of `room` W's, with an ellipsis (names.inc FittedName)."""
    width = w.width(b"W" * room, font)
    if w.width(name.encode(), font) <= width:
        return name
    head = ""
    for cluster in vf1_text.clusters(name):
        if w.width((head + cluster + "\u2026").encode(), font) > width:
            break
        head += cluster
    return head.rstrip(" ") + "\u2026"


def with_book(dll, vanilla_dir, entries, slot=2):
    import names_emu
    w = make_world(dll, vanilla_dir)
    w.fs[w.names_file(slot)] = vf1_names.render(entries)
    return w


@pytest.mark.parametrize("font", ["SegoeUiBold18", "SegoeUi33", "SegoeUiBold17", "SegoeUiBold24"])
def test_a_short_form_is_drawn_as_the_whole_name_fitted(dll, vanilla_dir, font):
    full = "Zoë Château-Montclair de la Rivière"
    short = vf1_names.short_form(full, 18, {})
    w = with_book(dll, vanilla_dir, [vf1_names.Entry(short, 18, full)])
    expect = fitted(w, full, 18, font)
    assert w.draw(short.encode(), font) == w.draw(expect.encode(), font)
    assert w.width(short.encode(), font) == w.width(expect.encode(), font)
    line = f"{short} and Sam's baby"
    assert w.draw(line.encode(), font) == w.draw(f"{expect} and Sam's baby".encode(), font)
    short_full = "Bo Li"
    assert w.draw(short_full.encode(), font) == w.draw(b"Bo Li", font)


def test_another_slot_shows_only_family_names(dll, vanilla_dir):
    """The slot menu draws every slot's family name; a member's short form of another slot stays as it is."""
    full = "Family Name Of Four Words And More"
    short = vf1_names.short_form(full, 19, {})
    w = with_book(dll, vanilla_dir, [vf1_names.Entry(short, 19, full)], slot=4)
    w.set_slot(2)
    assert w.draw(short.encode()) == w.draw(fitted(w, full, 19).encode())


def test_the_word_wrapper_wraps_the_whole_name(dll, vanilla_dir):
    full = "Maximiliana Theodora Wilhelmina"
    short = vf1_names.short_form(full, 18, {})
    w = with_book(dll, vanilla_dir, [vf1_names.Entry(short, 18, full)])
    text = f"{short} is going to college! Everyone will miss {short} very much."
    expect = text.replace(short, fitted(w, full, 18))
    assert w.wrap(text.encode(), 200) == w.wrap(expect.encode(), 200)


def test_a_long_name_scrolls_in_its_box_and_is_never_cut(world):
    """The stock draw deletes bytes from the end of the box's text until it fits (0x40D2B7): a name box draws the
    end that fits while it is typed into, its start with an ellipsis otherwise, and keeps its text whole."""
    w = world
    ctl, impl = name_box(w)
    w.e.w32(impl + 8, 0)
    w.e.w32(impl + 0x10, 200)          # right edge
    w.e.w32(impl + 0x40, 0)            # left aligned
    w.e.w32(impl + 0x44, 4)
    w.type_text(impl, FULL)
    w.e.write(impl + 0x26, b"\x00")
    blits = w.draw_box(impl)
    assert w.box_bytes(impl).decode() == FULL, "the box's text is whole"
    tail = FULL
    while w.width(tail.encode()) + 4 > 200:
        tail = tail[1:]
    assert blits == w.draw(tail.encode(), x=4)
    w.e.write(impl + 0x25, b"\x00")    # not typed into: the start, with an ellipsis
    blits = w.draw_box(impl)
    head = ""
    for ch in FULL:
        if w.width((head + ch + "\u2026").encode()) + 4 > 200:
            break
        head += ch
    assert blits == w.draw((head + "\u2026").encode(), x=4)
    assert w.box_bytes(impl).decode() == FULL
    assert w.guards_intact()


def test_the_names_file_is_read_again_after_a_restart(dll, vanilla_dir):
    import kids_emu as K
    w = make_world(dll, vanilla_dir)
    ctl, impl = name_box(w, 0x435AFB, 0x12)
    w.type_text(impl, FULL)
    dlg = w.e.alloc(0x100)
    w.e.w32(dlg + 0x54, ctl)
    villager = w.e.alloc(0x2C00)
    w.run_window(0x43681A, 0x43684D, {K.UC_X86_REG_ECX: w.gs, K.UC_X86_REG_EBP: dlg, K.UC_X86_REG_ESI: villager,
                                       K.UC_X86_REG_EDI: 0}, esp=w.frame())
    stored = w.e.read(villager + 0x2A44, 0x19).split(b"\0", 1)[0]
    w2 = make_world(dll, vanilla_dir, fs=w.fs)
    assert w2.draw(stored) == w2.draw(fitted(w2, FULL, 18).encode())
    full = w2.e.call(w2.e.dll_export("VF1Text_FullName"), (w2.cstr(stored),))
    assert w2.e.cstr(full).encode("latin-1").decode() == FULL


def full_of(w, stored: bytes) -> bytes:
    p = w.e.call(w.e.dll_export("VF1Text_FullName"), (w.cstr(stored),))
    return w.e.read(p, 4000).split(b"\0", 1)[0]


@pytest.mark.parametrize("data", [b"\xff\xfe garbage\n\tx\t",
                                  b"VF1 Names 1\nnot a mark\t18\tWhole\nAb...\t2\tToo small a room\n"
                                  b"Ok...\t18\tBad\x01control\n"])
def test_a_damaged_names_file_is_read_as_empty(dll, vanilla_dir, data):
    w = make_world(dll, vanilla_dir)
    w.fs[w.names_file(2)] = data
    for stored in (b"not a mark", b"Ab...", b"Ok..."):
        assert full_of(w, stored) == stored
    assert vf1_names.parse(data) == []


# --------------------------------------------------------------------------- the patcher's side
def test_names_file_round_trip(tmp_path):
    entries = [vf1_names.Entry("Alexandrina Ma...", 18, FULL),
               vf1_names.Entry("日本日本日...", 18, "日本" * 100)]
    path = vf1_names.names_path(tmp_path, 3)
    vf1_names.write(path, entries)
    assert vf1_names.read(path) == entries
    assert path.relative_to(tmp_path).as_posix() == "Virtual Families 1 Patcher Data/Names/Virtual Families3.ldw.txt"


def test_name_problem():
    assert vf1_names.name_problem("a" * LETTERS) is None
    assert "300" in vf1_names.name_problem("a" * (LETTERS + 1))
    assert vf1_names.name_problem("\U0001F600" * LETTERS) is None
    assert "1,200" in vf1_names.name_problem("\U0001F469\u200D\U0001F469\u200D\U0001F467" * 67)
    assert vf1_names.name_problem("a\tb") is not None
    assert vf1_names.name_problem("") is not None


def test_book_store_and_full(tmp_path):
    book = vf1_names.Book(tmp_path)
    short, entry = book.store(1, FULL, 19)
    assert short == vf1_names.short_form(FULL, 19, {}) and entry.full == FULL
    book.add(1, entry)
    book.write_slot(1)
    again = vf1_names.Book(tmp_path)
    assert again.full(1, short) == FULL
    assert again.full(3, short) == FULL, "a family name shows in every slot's menu"
    assert again.store(1, FULL, 19) == (short, None)
    assert again.store(2, "Short", 19) == ("Short", None)
    s2, e2 = again.store(2, FULL[:30] + "x", 19)
    assert s2 != short and s2.endswith("2...")
