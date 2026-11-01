"""The Picture Maker's effects, animals, store, collectibles and people's sheets (patcher/vf1_art_misc.py).

Everywhere: a synthetic game folder (plain sheets of the vanilla sizes) checks the list, the keys and categories,
that every draw stays inside its picture, that the per-cell words fit the sheets, the frame and fade models, and
the drawing of a few pictures.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read):
* the effect table 0x4EB370 in the exe equals EFFECT_TABLE;
* tests/house_emu.py runs AddEffect 0x421810, the effect clock 0x421B50 and the effect draw 0x421A30 for every
  effect the module lists and for the dropped-thing fade: the frames the game draws equal the module's;
* tests/ui_emu.py runs the store's item picture 0x496A10 for every item and the ball's draw 0x41F4E0;
* a scan of the exe's .text: every picture the module calls unused is never pushed for a picture getter, the
  used ones the code asks for by number are; every effect number pushed for AddEffect 0x421810, the wrapper
  0x421DA0 and the plan-step builders 0x48D150 / 0x48D1C0 is one the module lists as added, and the effects it
  calls never added are never pushed; the house list pushes the repair items' cells.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest
import vf1_art_misc as m
import vf1_game_art as ga
import vf1_picture_image as pi

AREA = (
    [0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67, 0x69, 0x6A, 0x6B]
    + list(range(0x6E, 0x77)) + [0x78, 0x7A, 0x7F, 0xA5, 0xD2,
                                 0x0D, 0x7B, 0x7C, 0x7D, 0x7E, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD, 0x03,
                                 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x1A, 0x1B, 0x1C, 0x1D,
                                 0xB8, 0xB9, 0xCE, 0xCF, 0xD0, 0x52, 0x53, 0x54, 0x55, 0x77,
                                 0x04, 0x05, 0x9C, 0x9D, 0x9E, 0x9F, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0x68, 0x00])
SIZES = {
    "waves_proto.png": (500, 50), "yellow_sparkle.png": (300, 30), "sparklestrip2.png": (120, 12),
    "sparklestrip.png": (250, 25), "dust2.png": (270, 30), "algae.png": (240, 240), "petalstrip.png": (600, 300),
    "foam.png": (192, 96), "spray_Grid_red.png": (649, 47), "sharp_sparkle.png": (200, 20),
    "water_spray_anim.png": (1000, 100), "faucet_water_anim.png": (1000, 100), "salad_anim.png": (1000, 100),
    "sawdust_anim.png": (1000, 100), "shower_anim.png": (1000, 100), "steam_anim.png": (1000, 100),
    "dripping_water.png": (1000, 100), "blurry_sparkle.png": (200, 20), "footprints.png": (150, 8),
    "smokestriplight.png": (1440, 120), "ripple.png": (260, 65), "ball_shadow.png": (30, 23),
    "birdhStrip1.png": (340, 28), "reefFish1.png": (188, 150), "beestriplarge_final2.png": (826, 140),
    "pet_grid.png": (1440, 180), "chopGreens1.png": (177, 19), "InventoryItems.png": (700, 980),
    "home_grid.png": (400, 240), "carrying.png": (728, 336), "collectables_small.png": (240, 480),
}


def _sheet(w: int, h: int, seed: int) -> pi.Image:
    img = pi.Image(w, h)
    row = bytes(b for x in range(w) for b in ((x * 3 + seed) % 256, (x + seed * 5) % 256, seed % 256,
                                               255 if x % 5 else 128))
    img.data[:] = row * h
    return img


@pytest.fixture(scope="module")
def game(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    (folder / "Images").mkdir(parents=True)
    for k, (name, (w, h)) in enumerate(SIZES.items()):
        (folder / "Images" / name).write_bytes(_sheet(w, h, k).to_png())
    return folder


@pytest.fixture(scope="module")
def files(game) -> ga.GameFiles:
    return ga.GameFiles(game)


def _mine(layers, dx: int = 0, dy: int = 0) -> list[tuple]:
    return [(d.file, tuple(d.rect), d.x + dx, d.y + dy, d.scale, d.alpha) for d in layers]


# ------------------------------------------------------------------ everywhere
def test_the_list(files):
    arts = m.arts(files)
    keys = [a.key for a in arts]
    assert len(keys) == len(set(keys)) and all(k.startswith("misc/") for k in keys)
    assert {a.category.split("/")[0] for a in arts} <= set(ga.CATEGORY_ORDER)
    for art in arts:
        assert art.label and "0x" in art.why and art.used
        assert "0x" not in art.label
        for layer in ga.resolve(files, art).layers:
            w, h = files.size(layer.file)
            x0, y0, x1, y1 = layer.rect
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h, (art.key, layer)
    for effect, key, *_rest in m.EFFECTS:
        assert len([a for a in arts if a.key.startswith(f"misc/effect/{key}/")]) == m.EFFECT_TABLE[effect][1]
    assert len([a for a in arts if a.key.startswith("misc/item/")]) == 58 + 3 + 15
    assert m.arts(ga.GameFiles(files.folder.parent / "nothing")) == []


def test_usage_cells_and_draws_fit():
    assert set(m.USAGE) == set(AREA)
    for image, (used, why) in m.USAGE.items():
        assert why and "0x" in why and not any(w in why for w in ("might", "probably", "seems")), hex(image)
    for table in (m.CELL_LABELS, m.CELL_UNUSED):
        for (image, k), words in table.items():
            shape = ga.grid_shape(image)
            assert shape is not None and 0 <= k < shape[0] * shape[1], (hex(image), k)
            assert words
    assert not set(m.CELL_UNUSED) & {(0x68, 21), (0x68, 24), (0x68, 3)}     # the house and the babies draw these
    for (image, _k) in m.CELL_UNUSED:
        assert m.USAGE[image][0]                                        # unused cells of used sheets only
    for image, (scale, alpha, why) in m.CELL_DRAW.items():
        assert image in m.USAGE and "0x" in why and 0 < alpha <= 1 and scale > 0
    # every effect the module lists is added somewhere; every unused effect picture's effect never is
    for effect, *_r in m.EFFECTS:
        assert m.EFFECT_ADDED[effect]
    for effect, (image, _frames, _rnd) in m.EFFECT_TABLE.items():
        if image in m.USAGE:
            assert m.USAGE[image][0] == (effect in m.EFFECT_ADDED), hex(effect)


def test_the_models_by_hand(files):
    assert m.frame_cells(0x6A, 12) == list(range(11)) + [0]          # the 12th frame: row 1 clamped to row 0
    assert m.frame_cells(0x64, 36) == list(range(36))
    assert [round(m.fade_alpha(k), 6) for k in range(12)] == [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1,
                                                               0.0, 0.0]
    assert m.item_picture(3) == (0xB8, 4) and m.item_picture(46, True) == (0xB8, 91)
    assert m.item_picture(62) == (0x03, 40) and m.item_picture(80) == (0xB9, 14) and m.item_picture(18) is None
    assert m.cell(files, 0xB8, 4)[1] == (280, 0, 350, 70)


def test_drawing(files):
    arts = {a.key: a for a in m.arts(files)}
    ball = ga.draw(files, arts["misc/ball/30"])
    assert (ball.width, ball.height) == (70, (35 + 30) + (23 - 8))    # ball top -65, shadow bottom 15
    ripple = ga.draw(files, arts["misc/ripple/0"])
    sheet = files.image("ripple.png")
    assert ripple.data[3] == int(sheet.data[3] * m.RIPPLE_ALPHA + 0.5) or abs(ripple.data[3] - sheet.data[3] * 0.4) <= 1
    frame = ga.draw(files, arts["misc/effect/redspray/11"])
    first = ga.draw(files, arts["misc/effect/redspray/0"])
    assert frame.data == first.data


# ------------------------------------------------------------------ with the game
@pytest.fixture(scope="module")
def vanilla() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    import faulthandler
    was_on = faulthandler.is_enabled()
    faulthandler.disable()
    yield Path(value).resolve()
    if was_on:
        faulthandler.enable()


@pytest.fixture(scope="module")
def exe(vanilla) -> bytes:
    pefile = pytest.importorskip("pefile")
    pe = pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True)
    return bytes(pe.get_memory_mapped_image())


def _u32(image: bytes, a: int) -> int:
    return struct.unpack_from("<I", image, a - 0x400000)[0]


def test_the_effect_table_is_the_exes(exe):
    for effect in range(0x2A):
        a = 0x4EB370 + 16 * effect
        assert (_u32(exe, a), _u32(exe, a + 4), exe[a + 8 - 0x400000]) == m.EFFECT_TABLE[effect], hex(effect)
    assert _u32(exe, 0x4EB370 + 16 * 0x2A) > 0x200          # the loader 0x4217B0 stops at 0x4EB610
    assert struct.unpack_from("<d", exe, 0x4B4520 - 0x400000)[0] == m.FADE_STEP
    assert struct.unpack_from("<f", exe, 0x4D6EDC - 0x400000)[0] == pytest.approx(m.RIPPLE_ALPHA, abs=0)
    assert exe[0x48B815 - 0x400000:0x48B81B - 0x400000] == b"\xD9\x05" + struct.pack("<I", 0x4D6EDC)


@pytest.fixture(scope="module")
def hemu(vanilla):
    import house_emu
    e = house_emu.HouseEmu(vanilla)
    e.house_setup()
    e.effects_setup()
    return e


def _played(emu, *args) -> list[list[tuple]]:
    emu.effect_clear()
    index = emu.add_effect(*args)
    seen = []
    for _ in range(2000):
        if emu.effect_entry(index)["type"] in (-1, 0xFFFFFFFF):
            break
        got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in emu.effect_draw(index)]
        if not seen or seen[-1] != got:
            seen.append(got)
        emu.effect_step()
    return seen


def test_every_listed_effect_plays_as_the_game_plays_it(hemu, vanilla):
    files = ga.GameFiles(vanilla)
    arts = {a.key: a for a in m.arts(files)}
    for effect, key, *_r in m.EFFECTS:
        frames = m.EFFECT_TABLE[effect][1]
        played = _played(hemu, effect, 1000, 800, 1, 0, 0xFFFFFFFF, 3, 0)
        mine = [_mine(arts[f"misc/effect/{key}/{k}"].layers, 1000, 800) for k in range(frames)]
        # consecutive equal frames merge in `played` (the red spray's 12th frame is not its 11th)
        merged = [f for k, f in enumerate(mine) if k == 0 or mine[k - 1] != f]
        assert played == merged, key


def test_the_dropped_thing_fades_as_the_game_fades_it(hemu, vanilla):
    files = ga.GameFiles(vanilla)
    arts = {a.key: a for a in m.arts(files)}
    played = _played(hemu, 0x0E, 1000, 800, 1, 0, 0, 6, 0)
    mine = [_mine(arts[f"misc/fade/{k}"].layers, 1000, 800) for k in range(10)]
    assert played[:10] == mine
    assert played[10:] == [[(f, r, x, y, s, 0.0) for f, r, x, y, s, _a in mine[0]]]
    whole = [_mine([d], 1000, 800) for d in m.fade_frames(files, 0x12, 5)]
    played = _played(hemu, 0x12, 1000, 800, 1, 0, 5, 6, 0)
    assert played == [f for k, f in enumerate(whole) if k == 0 or whole[k - 1] != f]


@pytest.fixture(scope="module")
def uemu(vanilla):
    import ui_emu
    return ui_emu.UiEmu(vanilla)


def test_store_pictures_are_the_games(uemu, vanilla):
    files = ga.GameFiles(vanilla)
    arts = {a.key: a for a in m.arts(files)}
    store = uemu.alloc(0x200)
    for off in (0x108, 0x10C, 0x110, 0x114):
        uemu.w32(store + off, 7)
    for item in range(1, 81):
        for second in (0, 1):
            uemu.take()
            uemu.call(0x496A10, (1000, 1000, item, second, 0, 0), ecx=store)
            got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in uemu.take()]
            plan = m.item_picture(item, bool(second))
            if plan is None:
                assert len(got) == 1 and got[0][0].endswith("_actions00.png") and got[0][4] == \
                    pytest.approx(m.OUTFIT_SCALE), item
                continue
            name, rect = m.cell(files, *plan)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            assert got == [(name, rect, 1000 - w // 2, 1000 - h // 2, 1.0, 1.0)], (item, second)
            if not second and f"misc/item/{item}" in arts:
                assert _mine(arts[f"misc/item/{item}"].layers, 1000, 1000) == got
            if plan[0] == 0xB8:
                assert (0xB8, plan[1]) not in m.CELL_UNUSED


def test_the_ball_is_the_games(uemu, vanilla):
    arts = {a.key: a for a in m.arts(ga.GameFiles(vanilla))}
    ball = uemu.alloc(0x40)
    uemu.w8(uemu.gs + 0x19C, 1)
    for height in (0, 30):
        uemu.wf(ball, 1000.0)
        uemu.wf(ball + 4, 800.0)
        uemu.wf(ball + 0x20, float(height))
        uemu.take()
        uemu.call(0x41F4E0, (0,), ecx=ball)
        got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in uemu.take()]
        assert got == _mine(ga.resolve(ga.GameFiles(vanilla), arts[f"misc/ball/{height}"]).layers, 1000, 800)


# ------------------------------------------------------------------ the exe scan
@pytest.fixture(scope="module")
def code(exe):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = []
    at = 0x401000
    while at < 0x4B2000:
        for ins in md.disasm(exe[at - 0x400000:0x4B2000 - 0x400000], at):
            out.append((ins.address, ins.mnemonic, ins.op_str))
            at = ins.address + ins.size
        at += 1
    return out


def _value(op: str, before: list) -> int | None:
    if op.startswith("0x") or op.isdigit():
        return int(op, 0)
    if op.startswith("-"):
        return None
    for _a, mn, ops in reversed(before):
        if mn == "mov" and ops.startswith(op + ", "):
            v = ops.split(", ")[1]
            return int(v, 0) if v.startswith("0x") or v.isdigit() else None
        if ops.startswith(op + ",") or ops == op:
            return None
    return None


def test_unused_pictures_are_never_asked_for(code):
    loaders = {0x44F5A0, 0x44F860, 0x44F590, 0x44F960, 0x44F880, 0x44FA70, 0x44F870}
    asked: set = set()
    for k, (_a, mn, op) in enumerate(code):
        if mn == "call" and op.startswith("0x") and int(op, 16) in loaders:
            recent = code[max(0, k - 8):k]
            for j in range(len(recent) - 1, -1, -1):
                if recent[j][1] == "push":
                    v = _value(recent[j][2], recent[:j])
                    if v is not None:
                        asked.add(v)
                    break
    for image, (used, _why) in m.USAGE.items():
        if not used and image not in [img for img, _f, _r in m.EFFECT_TABLE.values()]:
            assert image not in asked, hex(image)
    for image in (0x62, 0x63, 0x65, 0x66, 0x70, 0x7C, 0x7D, 0x7F):     # only the effect table names these
        assert image not in asked, hex(image)
    for image in (0xA8, 0xA9, 0xAA, 0xD2, 0xB8, 0x03, 0x77, 0x68, 0xA5, 0xB9, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x1A,
                  0x1B, 0x1C, 0x1D, 0xA4, 0x05):
        assert image in asked, hex(image)


def test_effect_numbers_pushed_are_the_listed_ones(code):
    targets = {0x421810: 1, 0x421DA0: 1, 0x48D150: 1, 0x48D1C0: 1}
    index = {a: k for k, (a, _m, _o) in enumerate(code)}
    calls = [k for k, (a, mn, op) in enumerate(code) if mn == "call" and op.startswith("0x")
             and int(op, 16) in targets]
    pushed: set = set()

    def last_push(lo: int, hi: int):
        for j in range(hi - 1, lo - 1, -1):
            if code[j][1] == "push":
                return _value(code[j][2], code[max(0, j - 12):j])
            if code[j][1] in ("call", "ret", "jmp") or code[j][1].startswith("j"):
                return "?"
        return "?"

    starts = {code[k][0] for k in calls}
    for k in calls:
        v = last_push(max(0, k - 3), k)
        if isinstance(v, int):
            pushed.add(v)
    # the paths that jump in just before a call bring their own number (the TV, the outfits of 0x471CF2, ...)
    for k, (a, mn, op) in enumerate(code):
        if mn.startswith("j") and op.startswith("0x"):
            t = int(op, 16)
            for c in starts:
                if c - 6 <= t <= c and not (c - 0x40 <= a <= c) and t in index:
                    v = last_push(max(0, k - 3), k)
                    if isinstance(v, int):
                        pushed.add(v)
    pushed &= set(range(0x2A))
    added = set(m.EFFECT_ADDED)
    assert pushed <= added, sorted(hex(v) for v in pushed - added)
    for effect, (image, _f, _r) in m.EFFECT_TABLE.items():
        if image in m.USAGE and not m.USAGE[image][0]:
            assert effect not in pushed, hex(effect)


def test_the_house_list_pushes_the_repair_items(exe):
    for site, cell_number in ((0x420E57, 0x55), (0x421296, 0x5B), (0x421402, 0x57), (0x4214AA, 0x57),
                              (0x421552, 0x57), (0x421660, 0x59)):
        assert exe[site - 0x400000:site - 0x400000 + 2] == bytes((0x6A, cell_number)), hex(site)
    for c in m.HOUSE_ITEM_CELLS:
        assert (0xB8, c) in m.CELL_LABELS and (0xB8, c) not in m.CELL_UNUSED
