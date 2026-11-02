"""Names fitted to their spot on the screen (native/vf1text/names.inc NameSpots, FitToRoom).

A name that fits its field in bytes can still be far wider than the place the game draws it: a 5-sign Cuneiform name
(5 x U+1208D, 20 bytes of a family member's 24) or 8 Japanese letters (24 bytes) are wider than a child's frame on
the Family Tree screen. Every fixed spot that draws a family member's name has its real room (from the game's own
layout, docs/UNICODE_TEXT.md "Names fitted to their spot"); a wider name is drawn as its start, cut between whole
characters, with "…".

Proved with the REAL vanilla executable and the REAL compiled vf1text.dll and vf1font.dll in Unicorn
(tests/names_emu.py), the DLLs' GDI calls made by this machine's real GDI (tests/text_emu.RealGdi) so Cuneiform and
Japanese have their real widths:
* the Family Tree screen's layout is the game's own (its constructor 0x438AB5..0x438BFE and its draw 0x43A1B0 run
  in tests/ui_emu.py, recording where each name and frame goes); each name is then drawn through the game's own call
  instruction at 0x439C74 / 0x439DB3 (DrawString) and 0x439F49 (the centred draw 0x409D20, which measures with
  GetWidth first), so the DLL sees the game's real return addresses;
* the house screen's bottom bar: the name label, the "Age" caption and the status line are made by the game's own
  constructor calls (0x4446B1.., 0x444744.., 0x444BBE..), given their text by the game's own SetText calls (0x445710,
  0x445866) and drawn by the game's text box draw 0x40D140.
Ordinary names are drawn exactly as before; the old DLL draws the wide names past their room (the test fails on it).
"""
import os
import struct

import pytest

import vf1_text
from test_name_limit import built  # noqa: F401  (the module-scoped build of both DLLs)

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import kids_emu as K  # noqa: E402

CUNEIFORM = "\U0001208D" * 5                      # 20 bytes
JAPANESE = "\u5c71\u7530\u82b1\u5b50\u592a\u90ce\u6b21\u90ce"   # 8 letters, 24 bytes
WS = "W" * 24                                     # 24 bytes, the field's widest stock name
WIDE = [CUNEIFORM, JAPANESE, WS]
ORDINARY = ["Emma", "Jack", "Sophia", "Christopher"]
WHITE = 0xFFFFFFFF
ELLIPSIS = "\u2026"


def need_windows():
    import vf1_glyph_gdi as g
    if os.name != "nt" or not g.AVAILABLE:
        pytest.skip("needs Windows: Cuneiform and Japanese letters are drawn by the real GDI")


@pytest.fixture(scope="module", params=["vf1text.dll", "vf1font.dll"])
def world(request, built, vanilla_dir):  # noqa: F811
    need_windows()
    import names_emu
    w = names_emu.NamesWorld(vanilla_dir / "Virtual Families.exe", built / request.param, vanilla_dir, install=True,
                             real_gdi=True)
    assert w.installed == 1
    w.set_slot(1)
    return w


def fit(w, name, room, font="SegoeUiBold18"):
    """names.inc FitToRoom: the name when it fits, else its longest start of whole characters with "…"."""
    if w.width(name.encode(), font) <= room:
        return name
    head = ""
    for cluster in vf1_text.clusters(name):
        if cluster != " " and w.width((head + cluster + ELLIPSIS).encode(), font) > room:
            break
        head += cluster
    return head.rstrip(" ") + ELLIPSIS


def extent(blits):
    """(left, right) of every letter drawn."""
    return min(b[3][0] for b in blits), max(b[3][0] + b[2][2] for b in blits)


# --------------------------------------------------------------------------- the Family Tree screen
@pytest.fixture(scope="module")
def tree(vanilla_dir):
    """The Family Tree screen's own layout: one family, two parents, three children, drawn by 0x43A1B0 with every
    text draw recorded (return address, text, x, y, colour, font) and every frame blit."""
    import ui_emu
    from unicorn import UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_ESP

    e = ui_emu.UiEmu(vanilla_dir)
    texts = []

    def record(kind):
        def run():
            esp = e.u.reg_read(UC_X86_REG_ESP)
            ra, text, x, y, colour, font = struct.unpack("<IIiiII", e.u.mem_read(esp, 24))
            texts.append({"kind": kind, "ret": ra, "text": bytes(e.u.mem_read(text, 40)).split(b"\0")[0],
                          "x": x, "y": y, "colour": colour, "font": font})
            e._return(0, 0x14)
        return run

    for addr, kind in ((0x409CC0, "left"), (0x409D20, "centre")):
        e.hooks[addr] = record(kind)
    e.u.hook_add(UC_HOOK_CODE, e._code, begin=0x409CC0, end=0x409CC0)
    for addr in (0x439790, 0x439930):                  # the portraits: people pictures, not text
        e.hooks[addr] = e._text(0x1C)
        e.u.hook_add(UC_HOOK_CODE, e._code, begin=addr, end=addr)
    screen = e.alloc(0x200)
    e.run(0x438AB5, 0x438BFE, regs={"esi": screen, "edi": screen + 0x68, "ebx": 0, "ecx": e.mgr})
    db = 0x5AB908                                      # the families (0x481700): a count, then 0x6C8 a family
    e.w32(db, 1)
    rec = db + 4
    e.u.mem_write(rec, bytes(0x6C8))
    e.w8(rec, 1)
    e.u.mem_write(rec + 4, b"Parent1\0")
    e.w32(rec + 0x2C, 5)
    e.w8(rec + 0xF6, 1)
    e.u.mem_write(rec + 0xDC, b"Parent2\0")
    e.w32(rec + 0x104, 6)
    e.w32(rec + 0x1B4, 3)
    for k in range(3):
        e.u.mem_write(rec + 0x1B8 + k * 0xD8, b"Child%d\0" % k)
        e.w32(rec + k * 0xD8 + 0x1E0, 7 + k)
    e.take()
    e.call(0x43A1B0, (), ecx=screen)
    draws = e.take()
    strings = e.r32(e.strings)
    return {"texts": texts, "frames": [d for d in draws if d.get("file", "").startswith("familytree_")
                                       and d["kind"] == "blit"], "font0": strings}


def tree_spots(tree):
    """[(call site, name x or centre x, y, (room left, room right))] from the game's own layout."""
    t = {d["text"]: d for d in tree["texts"]}
    parents = [d for d in tree["frames"] if d["file"] == "familytree_parentframe.png"]
    children = sorted((d for d in tree["frames"] if d["file"] == "familytree_childframe.png"), key=lambda d: d["x"])
    out = []
    for name, site, frame in ((b"Parent1", 0x439C74, parents[0]), (b"Parent2", 0x439DB3, parents[1])):
        d = t[name]
        assert d["ret"] == site + 5 and d["kind"] == "left" and d["colour"] == WHITE
        assert d["font"] == tree["font0"], "drawn in theStringManager's first font, SegoeUiBold18"
        origin = frame["x"] - frame["rect"][0]                 # the frame's own left (the clip cut its first 8)
        out.append((site, d["x"], d["y"], (d["x"], origin + 248)))
    for k, frame in enumerate(children):
        d = t[b"Child%d" % k]
        assert d["ret"] == 0x439F4E and d["kind"] == "centre"
        out.append((0x439F49, d["x"], d["y"], (frame["x"], frame["x"] + 94)))
    return out


def test_the_tree_layout_gives_these_rooms(tree):
    """The numbers in names.inc DrawSpots come from the game's own layout."""
    spots = tree_spots(tree)
    assert [(s, x, room) for s, x, _y, room in spots[:2]] == [(0x439C74, 147, (147, 274)), (0x439DB3, 147, (147, 274))]
    for _s, cx, _y, (left, right) in spots[2:]:
        assert (cx - left, right - left) == (46, 94)


def draw_at(w, site, text, x, y, font="SegoeUiBold18"):
    """The game's own call instruction at `site` (push order: text, x, y, colour, font) on a game window."""
    e = w.e
    holder = e.alloc(8)
    e.w32(holder, w.window)
    base = w.frame()
    w.blits = []
    w.run_window(site, site + 5, {K.UC_X86_REG_ECX: holder}, esp=base,
                 stack={base: w.cstr(text), base + 4: x & 0xFFFFFFFF, base + 8: y, base + 12: WHITE,
                        base + 16: w.fonts[font]})
    return list(w.blits)


def stock_centre(w, text, cx):
    return cx - w.width(text) // 2                     # 0x409D46..0x409D4D: cdq / sub / sar


@pytest.mark.parametrize("name", WIDE + ORDINARY)
def test_family_tree_names_stay_in_their_frames(world, tree, name):
    w = world
    data = vf1_text.encode(name)
    assert len(data) <= 24
    for site, x, y, (left, right) in tree_spots(tree):
        room = 127 if site != 0x439F49 else 93
        blits = draw_at(w, site, data, x, y)
        shown = fit(w, name, room)
        if site == 0x439F49:
            expect = w.draw(shown.encode(), x=stock_centre(w, shown.encode(), x), y=y)
        else:
            expect = w.draw(shown.encode(), x=x, y=y)
        assert blits == expect, (hex(site), name)
        lo, hi = extent(blits)
        assert left <= lo and hi <= right, (hex(site), name, lo, hi, left, right)
        if name in ORDINARY:
            assert shown == name                       # drawn exactly as before
        elif site == 0x439F49:                         # every wide name is wider than a child's frame
            assert shown != name and shown.endswith(ELLIPSIS), (hex(site), name)
        else:                                          # a parent has more room: 5 Cuneiform signs fit there
            assert (shown == name) == (w.width(data) <= 127), (hex(site), name)


def test_a_short_form_on_the_tree_is_the_whole_name_fitted_to_the_frame(world, tree):
    """A long name's short form in the tree's record: its whole name (Names file) fitted to the child's frame."""
    import vf1_names
    w = world
    full = "Maximiliana Theodora Wilhelmina"
    short = vf1_names.short_form(full, 24, {})
    w.fs[w.names_file(1)] = vf1_names.render([vf1_names.Entry(short, 24, full)])
    try:
        site, cx, y, (left, right) = tree_spots(tree)[2]
        blits = draw_at(w, site, short.encode(), cx, y)
        shown = fit(w, full, 93)
        assert shown.startswith("Maxim") and shown.endswith(ELLIPSIS)
        assert blits == w.draw(shown.encode(), x=stock_centre(w, shown.encode(), cx), y=y)
        assert left <= extent(blits)[0] and extent(blits)[1] <= right
    finally:
        del w.fs[w.names_file(1)]


# --------------------------------------------------------------------------- the house screen's bottom bar
def made_label(w, start, stop, regs):
    """A label made by the game's own constructor call (start .. just after it): its ldwTextControl and impl."""
    e = w.e
    holder = e.alloc(8)
    e.w32(holder, w.fonts["SegoeUiBold18"])            # theStringManager: its first font, SegoeUiBold18
    scene = e.alloc(0x200)
    e.w32(scene + 0x1C, holder)
    obj = e.alloc(0x40)
    r = {K.UC_X86_REG_EAX: obj, K.UC_X86_REG_EBP: obj, K.UC_X86_REG_ESI: scene, K.UC_X86_REG_EDI: 0}
    r.update(regs)
    w.run_window(start, stop, r, esp=w.frame())
    impl = e.r32(obj + 0x10)
    e.write(impl + 0x2C, b"\x01")                      # shown
    e.w32(impl + 0x18, 0)                              # no parent offset
    return obj, impl


def set_text_at(w, site, ctl, text):
    """The game's own `call 0x40D700` at `site` (ldwTextControl::SetText) with ecx = the label."""
    base = w.frame()
    w.run_window(site, site + 5, {K.UC_X86_REG_ECX: ctl}, esp=base, stack={base: w.cstr(text)})


def rect(w, impl):
    return tuple(w.e.r32(impl + o) for o in (8, 0xC, 0x10, 0x14))


def test_bottom_bar_layout(world):
    w = world
    _ctl, name = made_label(w, 0x4446B1, 0x4446D8, {})
    _ctl, age = made_label(w, 0x444744, 0x444777, {})
    _ctl, status = made_label(w, 0x444BBE, 0x444BE4, {})
    assert rect(w, name)[:2] == (61, 538) and rect(w, name)[2] - 61 == w.width(b"Joey Joerson")
    assert w.e.read(name + 0x24, 1) == b"\0" and w.e.r32(name + 0x40) == 0    # not editable, left aligned
    assert rect(w, age)[0] == 202                                            # the "Age" caption: 141 after
    assert rect(w, status)[0::2] == (187, 603) and w.e.r32(status + 0x40) == 1
    assert w.e.read(status + 0x24, 1) == b"\0"


@pytest.mark.parametrize("name", WIDE + ORDINARY)
def test_bottom_bar_name_stops_before_the_age_column(world, name):
    w = world
    ctl, impl = made_label(w, 0x4446B1, 0x4446D8, {})
    set_text_at(w, 0x445710, ctl, vf1_text.encode(name))
    blits = w.draw_box(impl)
    shown = fit(w, name, 141)
    assert blits == w.draw(shown.encode(), x=61, y=538)
    assert 61 <= extent(blits)[0] and extent(blits)[1] <= 202
    assert w.box_bytes(impl) == vf1_text.encode(name), "the label keeps its text"
    assert (shown == name) == (w.width(vf1_text.encode(name)) <= 141)
    assert (shown == name) == (name != WS)          # 5 Cuneiform signs and 8 Japanese letters fit here; 24 W do not


def test_a_label_set_elsewhere_is_drawn_as_before(world):
    """Only the listed SetText call sites fit: the same label given a wide name by any other call draws it whole."""
    w = world
    ctl, impl = made_label(w, 0x4446B1, 0x4446D8, {})
    set_text_at(w, 0x445710, ctl, WS.encode())
    set_text_at(w, 0x4456A1, ctl, WS.encode())          # the bar's own "" call site, here with a name
    assert w.draw_box(impl) == w.draw(WS.encode(), x=61, y=538)


def test_a_label_wider_than_it_was_made_is_drawn_whole(world):
    """Every text control starts with the limit 0x4B0 (0x40D851), labels too: only an editable box with it is a name
    box. The bottom bar's activity label, made for "Fishing" (0x444914) and set by 0x445850, shows a longer text
    whole, as the stock game does (the previous code cut it to the width of "Fishing")."""
    w = world
    ctl, impl = made_label(w, 0x4448F2, 0x444919, {})
    assert rect(w, impl)[:2] == (247, 538) and rect(w, impl)[2] - 247 == w.width(b"Fishing")
    set_text_at(w, 0x445850, ctl, b"Master Gardener and Cook")
    assert w.draw_box(impl) == w.draw(b"Master Gardener and Cook", x=247, y=538)
    assert w.box_bytes(impl) == b"Master Gardener and Cook"


@pytest.mark.parametrize("pair", [(CUNEIFORM, JAPANESE), (WS, WS), ("Emma", "Jack")])
def test_status_line_fits_its_box(world, pair):
    w = world
    ctl, impl = made_label(w, 0x444BBE, 0x444BE4, {})
    line = f"{pair[0]} sees {pair[1]}."
    set_text_at(w, 0x445866, ctl, vf1_text.encode(line))
    blits = w.draw_box(impl)
    shown = fit(w, line, 603 - 187)
    x0, y0 = blits[0][3]
    assert x0 == (603 - w.width(shown.encode()) - 187) // 2 + 187        # centred as the stock draw does
    assert blits == w.draw(shown.encode(), x=x0, y=y0)
    assert 187 <= extent(blits)[0] and extent(blits)[1] <= 603
    assert (shown == line) == (w.width(vf1_text.encode(line)) <= 603 - 187)
    assert (shown == line) == (pair != (WS, WS))


# --------------------------------------------------------------------------- the rule itself
def test_fit_keeps_whole_characters_and_drops_trailing_spaces(world):
    w = world
    for unit in ("Abcdefghij Klmno ", "Zoe\u0301 ", "\U0001F44D\U0001F3FD", "\U0001F1EF\U0001F1F5",
                 "\U0001F468\u200D\U0001F469\u200D\U0001F467"):
        name = unit
        while w.width(name.encode()) <= 141:          # wider than the bottom bar's room
            name += unit
        ctl, impl = made_label(w, 0x4446B1, 0x4446D8, {})
        set_text_at(w, 0x445710, ctl, name.encode())
        shown = fit(w, name, 141)
        assert shown.endswith(ELLIPSIS), name
        assert w.draw_box(impl) == w.draw(shown.encode(), x=61, y=538)
        head = shown[:-1]
        assert not head.endswith(" ") and name.startswith(head)
        assert vf1_text.clusters(head) == vf1_text.clusters(name)[:len(vf1_text.clusters(head))]


def test_a_single_byte_name_is_fitted_with_the_windows_1252_ellipsis(world):
    """A name that is not UTF-8 is read one byte per character (Windows-1252): its "…" is the byte 0x85."""
    w = world
    name = b"Ren\xe9e " * 6
    ctl, impl = made_label(w, 0x4446B1, 0x4446D8, {})
    set_text_at(w, 0x445710, ctl, name)
    head = b""
    for k in range(len(name)):
        if name[k:k + 1] != b" " and w.width(name[:k + 1] + b"\x85") > 141:
            break
        head = name[:k + 1]
    assert w.draw_box(impl) == w.draw(head.rstrip(b" ") + b"\x85", x=61, y=538)
