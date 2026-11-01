"""The Every picture catalogue's draws that were first only read from the code, now run as the game's own code.

Everywhere (no game): the grey of a family member who is gone follows the tinted blit's rule, the family tree
frames, the birds and the troughs are listed and draw, and every Details bar draw the module plans lies inside
its trough picture.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read):
* the family tree screen 0x43A1B0 and its family row 0x439BA0 (tests/ui_emu.py) for a family with a parent and a
  child gone: every frame draw and every grey (the tinted blit 0x408EC0) equals the module's layers, the clip
  0x407E60 included; the game's own 0x408EC0 run on the frames' pixels (tests/picture_emu.py) over three colours
  equals the module's grey pixels laid on by the blit's own rule, and within 3 levels laid on by "over";
* the family member draw 0x48B4D0 in water (tests/picture_emu.py, the water test 0x495E00 and the ground kind
  0x4928B0 stood in as "water, kind 5"): the ripples' cell for each value of the seconds clock 0x4036D0, their
  place, alpha and size;
* the birds' draw 0x42FDD0 for every place, frame and facing the birds' update 0x4304F0 can give;
* the shark: no code puts it in the draw list (every call of the adder 0x44EBF0 pushes another case), its draw
  0x430850 picks the 8 cells by heading, and its picture is blank;
* the pets: the pets' table built by 0x432E90, the pet draw 0x434550 for every pet, pose and heading, the pets'
  animations built by 0x433550 and the pose picker 0x4333C0: pose 19 is never given;
* the Details screen 0x44B890 (tests/meters_emu.py): every bar draw lands inside its trough picture, and the
  trough pictures' edges are measured again on VD_BG_2.jpg decoded as the game's libjpeg decodes it.
"""
from __future__ import annotations

import math
import os
import struct
from pathlib import Path

import pytest
import vf1_art_meters as meters
import vf1_art_misc as misc
import vf1_art_ui as ui
import vf1_game_art as ga
import vf1_picture_image as pi

SIZES = {"familytree_parentframe.png": (248, 91), "familytree_childframe.png": (94, 74), "bird.png": (600, 25),
         "bird_shadow.png": (51, 25), "ripple.png": (260, 65)}


def _sheet(w: int, h: int, seed: int) -> pi.Image:
    img = pi.Image(w, h)
    row = bytes(b for x in range(w) for b in ((x * 3 + seed) % 256, (x + seed * 5) % 256, seed % 256,
                                               255 if x % 5 else 128))
    img.data[:] = row * h
    return img


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory) -> ga.GameFiles:
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    (folder / "Images").mkdir(parents=True)
    for k, (name, (w, h)) in enumerate(SIZES.items()):
        (folder / "Images" / name).write_bytes(_sheet(w, h, k).to_png())
    return ga.GameFiles(folder)


def _layer(d) -> tuple:
    return (d.file, tuple(d.rect), d.x, d.y, d.scale, d.alpha)


# ------------------------------------------------------------------ everywhere
def test_greyed_pixels_follow_the_tinted_blit():
    img = pi.Image(2, 1)
    img.data[:] = bytes((200, 100, 0, 255, 10, 20, 30, 0))
    g = ui.greyed_pixels(img, (0, 0, 2, 1))
    # colour (c x 127 >> 8) + (128 x 128 >> 8); weight 255 x trunc(0.3 x 255) / 255
    assert bytes(g.data) == bytes((99 + 64, 49 + 64, 64, 76, 4 + 64, 9 + 64, 14 + 64, 0))


def test_tree_frames_listed_and_drawn(synthetic):
    arts = {a.key: a for a in ui.arts(synthetic)}
    c1, c1g, c2, c2g = (arts[f"ui/panels/{k}"] for k in ("c1", "c1-gone", "c2", "c2-gone"))
    assert [_layer(d) for d in c1.layers] == [("familytree_parentframe.png", (8, 0, 248, 91), 8, 0, 1.0, 1.0)]
    assert [_layer(d) for d in c2.layers] == [("familytree_childframe.png", (0, 0, 94, 74), 0, 0, 1.0, 1.0)]
    for plain, gone in ((c1, c1g), (c2, c2g)):
        assert gone.layers[0] == plain.layers[0] and isinstance(gone.layers[1], ui.Greyed)
        assert _layer(gone.layers[1])[:4] == _layer(plain.layers[0])[:4]
        img = ga.draw(synthetic, gone)
        assert (img.width, img.height) == (plain.layers[0].rect[2] - plain.layers[0].rect[0], plain.layers[0].rect[3])
        assert img.data != ga.draw(synthetic, plain).data
    for a in (c1, c1g, c2, c2g):
        assert a.used and a.checked


def test_birds_listed_and_drawn(synthetic):
    arts = {a.key: a for a in misc.arts(synthetic) if a.key.startswith("misc/bird/")}
    assert sorted(arts) == sorted([f"misc/bird/ground/{c}" for c in range(12)]
                                  + [f"misc/bird/flying/{c}" for c in range(4, 12)])
    for a in arts.values():
        assert a.used and a.checked and a.category == "Animals and insects/Birds"
        assert ga.draw(synthetic, a).width == 51
    assert misc.CELL_LABELS[(0xA8, 0)] == "Bird standing, facing right"


def test_planned_bar_draws_lie_inside_their_troughs():
    for kind, (left, top, right, bottom) in meters.TROUGHS.items():
        _name, x0, y, _red = meters.KINDS[kind]
        assert (left, right) == (x0, x0 + meters.BAR_W) and top < y and bottom > y + meters.BAR_H
        for p in range(101):
            for d in meters.painter_draws(kind, meters.painter_value(kind, p)):
                l, t, r, b = d.rect
                assert left <= d.x and d.x + (r - l) <= right and top <= d.y and d.y + (b - t) <= bottom


def test_ripples_shark_and_pet_words(synthetic):
    ripples = [a for a in misc.arts(synthetic) if a.key.startswith("misc/ripple/")]
    assert len(ripples) == 4 and all(a.checked for a in ripples)
    assert all((a.layers[0].x, a.layers[0].y, a.layers[0].alpha) == (-32, -32, misc.RIPPLE_ALPHA) for a in ripples)
    assert misc.USAGE[0xAA][0] is False and "case 7" in misc.USAGE[0xAA][1]
    assert all((0x03, 24 * pet + 19) in misc.CELL_UNUSED for pet in range(3))


# ------------------------------------------------------------------ with the game
@pytest.fixture(scope="module")
def vanilla() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    pytest.importorskip("unicorn")
    pytest.importorskip("pefile")
    return Path(value)


@pytest.fixture(scope="module")
def files(vanilla) -> ga.GameFiles:
    return ga.GameFiles(vanilla)


def _f(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _clip(rect, x, y, clip):
    """0x407E60 on a draw (left, top, right, bottom) at (x, y)."""
    left, top, right, bottom = rect
    cl, ct, cr, cb = clip
    if x < cl:
        left += cl - x
        x = cl
    if y < ct:
        top += ct - y
        y = ct
    right -= max(0, x + (right - left) - cr)
    bottom -= max(0, y + (bottom - top) - cb)
    return (left, top, right, bottom), x, y


@pytest.fixture(scope="module")
def tree(vanilla):
    """The family tree screen with one family: parent 1 here, parent 2 gone, three children, the second gone."""
    import ui_emu
    from unicorn import UC_HOOK_CODE

    e = ui_emu.UiEmu(vanilla)
    for addr in (0x439790, 0x439930):              # the portraits (people pictures, not frames): recorded as text
        e.hooks[addr] = e._text(0x1C)
        e.u.hook_add(UC_HOOK_CODE, e._code, begin=addr, end=addr)
    screen = e.alloc(0x200)
    # the screen's layout, as its constructor sets it (0x438AB5..0x438BFE)
    e.run(0x438AB5, 0x438BFE, regs={"esi": screen, "edi": screen + 0x68, "ebx": 0, "ecx": e.mgr})
    db = 0x5AB908                                  # the families (0x481700): a count, then 0x6C8 a family
    e.w32(db, 1)
    rec = db + 4
    e.u.mem_write(rec, bytes(0x6C8))
    e.w8(rec, 1)
    e.w32(rec + 0x2C, 5)
    e.w8(rec + 0xF6, 1)
    e.w32(rec + 0x104, -1)
    e.w32(rec + 0x1B4, 3)
    for k, number in enumerate((7, -1, 9)):
        e.w32(rec + k * 0xD8 + 0x1E0, number)
    e.take()
    e.call(0x43A1B0, (), ecx=screen)
    clip = tuple(e.r32(screen + o) for o in (8, 0xC, 0x10, 0x14))
    return e.take(), clip


def test_family_tree_frames_as_the_game_draws_them(tree, files):
    draws, clip = tree
    assert clip == (34, 142, 736, 600)
    arts = {a.key: a for a in ui.arts(files)}
    frames = [d for d in draws if d.get("file") in ("familytree_parentframe.png", "familytree_childframe.png")]
    kinds = [(d["kind"], d["file"]) for d in frames]
    P, C = "familytree_parentframe.png", "familytree_childframe.png"
    assert kinds == [("blit", P), ("blit", P), ("tint", P), ("blit", C), ("blit", C), ("tint", C), ("blit", C)]
    for k, d in enumerate(frames):
        key = "c1" if d["file"] == P else "c2"
        gone = k + 1 < len(frames) and frames[k + 1]["kind"] == "tint"
        if d["kind"] == "tint":
            continue
        art = arts[f"ui/panels/{key}-gone" if gone else f"ui/panels/{key}"]
        plain = art.layers[0]
        # the frame's own point: where the game asked for it (the blit is after the clip)
        origin = (d["x"] - plain.x, d["y"] - plain.y)
        assert (tuple(d["rect"]), d["alpha"], d["scale"]) == (tuple(plain.rect), plain.alpha, plain.scale)
        if key == "c1":
            assert origin[0] == clip[0] - ui.TREE_CUT                           # x - 8 against the clip
        if gone:
            t = frames[k + 1]
            rect, x, y = _clip(t["rect"], t["x"], t["y"], clip)
            grey = art.layers[1]
            assert (rect, x - origin[0], y - origin[1]) == (tuple(grey.rect), grey.x, grey.y)
            assert t["colour"] == int.from_bytes(bytes(ui.GREY), "little")
            assert (t["alpha"], t["scale"]) == (grey.alpha, grey.scale)


def _tint_emu(vanilla, files):
    import picture_emu as pe

    def pixels(name):
        im = files.image(name)
        return im.width, im.height, bytes(im.data)

    e = pe.Emu(vanilla, pixels=pixels)

    def mapper(with_alpha: bool):          # SDL_MapRGB / SDL_MapRGBA for the RGBA-in-memory surfaces
        def run(_self):
            esp = e.u.reg_read(pe.UC_X86_REG_ESP)
            n = 5 if with_alpha else 4
            a = struct.unpack("<" + "I" * n, e.u.mem_read(esp + 4, 4 * n))
            alpha = (a[4] & 0xFF) if with_alpha else 0xFF
            e._ret_value((a[1] & 0xFF) | (a[2] & 0xFF) << 8 | (a[3] & 0xFF) << 16 | alpha << 24, 0)(_self)
        return run

    for addr, hook in ((0x4978FE, mapper(False)), (0x4978E6, mapper(True))):
        e._code_hooks[addr] = hook
        e.u.hook_add(pe.UC_HOOK_CODE, e._code, begin=addr, end=addr)
    return e


def test_greyed_pixels_match_the_games_tinted_blit(vanilla, files):
    """0x408EC0 itself on the frames' pixels (a PNG picture: +4 of its picture is 1, 0x40B3CF)."""
    e = _tint_emu(vanilla, files)
    for name in ("familytree_parentframe.png", "familytree_childframe.png"):
        sheet = files.image(name)
        w, h = sheet.width, sheet.height
        grey = ui.greyed_pixels(sheet, (0, 0, w, h))
        impl = e.alloc(16)
        e.w32(impl, e._file_surface(name))
        e.u.mem_write(impl + 4, b"\x01")
        pic = e.alloc(0x40)
        for field, v in ((4, impl), (8, 1), (0xC, 1), (0x10, w), (0x14, h)):
            e.w32(pic + field, v)
        surf = e._surface("backdrop", w, h, alpha=False)
        for colour in ((200, 40, 90), (0, 0, 0), (255, 255, 255)):
            e.w32(e.impl + 8, w)
            e.w32(e.impl + 0xC, h)
            for k, v in enumerate((0, 0, w, h)):
                e.w32(e.impl + 0x60 + 4 * k, v)
            e.w32(e.impl + 0x30, surf)
            px = e.r32(surf + 0x14)
            e.u.mem_write(px, bytes((*colour, 0)) * (w * h))
            e.call(0x408EC0, (pic, 0, 0, 0, 0, w, h, int.from_bytes(bytes(ui.GREY), "little"), _f(ui.GREY_ALPHA),
                              _f(1.0)), ecx=e.impl)
            game = bytes(e.u.mem_read(px, w * h * 4))
            back = pi.Image(w, h)
            back.data[:] = bytes((*colour, 255)) * (w * h)
            back.draw(grey, 0, 0)
            worst = 0
            for i in range(w * h):
                m, a = grey.data[4 * i:4 * i + 3], grey.data[4 * i + 3]
                rule = bytes((((c * (255 - a)) >> 8) + ((g * a) >> 8)) & 0xFF for c, g in zip(colour, m))
                assert game[4 * i:4 * i + 3] == rule, (name, colour, i)
                worst = max(worst, max(abs(p - q) for p, q in zip(game[4 * i:4 * i + 3], back.data[4 * i:4 * i + 3])))
            assert worst <= 3, (name, colour, worst)


def test_ripples_as_the_game_draws_them(vanilla, files):
    import picture_emu as pe

    e = pe.Emu(vanilla)
    state = e.alloc(0x20)
    stand = {0x495E00: e._ret_value(1, 8),          # in water
             0x4928B0: e._ret_value(5, 8),          # ground kind 5
             0x423660: e._ret_value(state, 0),      # theGameState (only 0x4036D0, stood in below, reads it)
             0x403650: e._ret_value(99, 0)}         # GetRandom: no splash this time (0x48B851)
    for addr, hook in stand.items():
        if addr not in e._code_hooks and addr != 0x403650:
            e.u.hook_add(pe.UC_HOOK_CODE, e._code, begin=addr, end=addr)
        e._code_hooks[addr] = hook
    e.u.hook_add(pe.UC_HOOK_CODE, e._code, begin=0x4036D0, end=0x4036D0)
    e.w32(pe.MANAGER + 0x34, e.window)              # the manager's game window (0x48B83F)
    arts = {a.key: a for a in misc.arts(files)}
    for seconds in range(9):
        e._code_hooks[0x4036D0] = e._ret_value(seconds, 0)
        e.villager(female=seconds % 2 == 0, age=30, head=3, body=3, pose=0)
        feet = e.feet()
        blits = e.draw_house()
        ripples = [b for b in blits if b["file"] == "ripple.png"]
        assert len(ripples) == 1
        r = ripples[0]
        mine = arts[f"misc/ripple/{seconds % 4}"].layers[0]
        assert (tuple(r["rect"]), r["x"] - feet[0], r["y"] - feet[1], r["scale"], r["alpha"]) == (
            tuple(mine.rect), mine.x, mine.y, mine.scale, mine.alpha)
        assert not any("bodies" in b["file"] for b in blits)                # only the head shows in the water
    for sitting, pose in ((1, 0), (0, 0x36)):                               # no ripples sitting or in pose 0x36
        v = e.villager(female=True, age=30, head=3, body=3, pose=pose)
        e.u.mem_write(v + 0x13576, bytes([sitting]))
        assert not any(b["file"] == "ripple.png" for b in e.draw_house())


def test_birds_as_the_game_draws_them(vanilla, files):
    import ui_emu

    e = ui_emu.UiEmu(vanilla)
    birds = 0x50C750
    e.w32(birds + 0x2AC, e.grid(0xA8))              # as 0x4307D0 loads them
    e.w32(birds + 0x2B0, e.grid(0xA9))
    arts = {a.key: a for a in misc.arts(files) if a.key.startswith("misc/bird/")}
    seen = set()
    # what the update 0x4304F0 can give: on the ground (1, 2) frames 0..1 and, flapping, 4..7 (+2 facing left);
    # flying (3) frames 0..3; facing 0 (right) or 3 (left)
    for state in (1, 2, 3):
        for facing in (0, 3):
            frames = range(4) if state == 3 else [0, 1] + [f + (2 if facing else 0) for f in range(4, 8)]
            for frame in frames:
                for height in ((0,) if state == 3 else (0, 7)):
                    e.u.mem_write(birds, bytes(0x4C))
                    for field, v in ((0, 1000), (4, 1000), (0x30, frame), (0x38, facing), (0x3C, state),
                                     (0x48, height)):
                        e.w32(birds + field, v)
                    e.wf(birds + 0x34, 1.0)
                    e.take()
                    e.call(0x42FDD0, (0,), ecx=birds)
                    got = [(d["file"], d["rect"], d["x"] - 1000, d["y"] - 1000, d["scale"], d["alpha"])
                           for d in e.take()]
                    flying = state == 3
                    c = misc.bird_cell(flying, facing == 3, frame)
                    key = f"misc/bird/{'flying' if flying else 'ground'}/{c}"
                    want = [_layer(d) for d in misc.bird_layers(files, flying, c, height)]
                    assert got == want, (state, facing, frame, height)
                    if height == 0:
                        assert [_layer(d) for d in arts[key].layers] == want
                    seen.add(key)
    assert seen == set(arts)


def test_the_shark_is_never_drawn(vanilla, files):
    import pefile
    import ui_emu

    pe = pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True)
    image = bytes(pe.get_memory_mapped_image())
    text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
    lo = 0x400000 + text.VirtualAddress
    hi = lo + text.Misc_VirtualSize
    adder = 0x44EBF0
    sites = [a for a in range(lo, hi - 5) if image[a - 0x400000] == 0xE8
             and a + 5 + struct.unpack_from("<i", image, a - 0x400000 + 1)[0] == adder]
    assert struct.pack("<I", adder) not in image                            # no pointer to it anywhere
    cases = {}
    for site in sites:
        before = image[site - 0x400000 - 7:site - 0x400000]
        assert before[0] == 0x6A and before[2:] == b"\xB9\x00\xB8\x56\x00", hex(site)  # push n; mov ecx, 0x56B800
        cases[site] = before[1]
    assert sorted(set(cases.values())) == [1, 2, 3, 5, 8, 9]                # never 7, the shark (0x44EB77)
    table = 0x44EBC4                                                        # the draw list's jump table (0x44EB25)
    assert struct.unpack_from("<I", image, table + 4 * 6 - 0x400000)[0] == 0x44EB77
    # its draw would pick the 8 cells by heading
    e = ui_emu.UiEmu(vanilla)
    shark = 0x50CA60
    e.w32(shark + 0x90, e.grid(0xAA))
    cells = set()
    for k in range(16):
        a = k * math.pi / 8
        for field, v in ((4, 1000), (8, 1000), (0xC, round(100 * math.cos(a))), (0x10, round(100 * math.sin(a)))):
            e.w32(shark + field, v)
        e.take()
        e.call(0x430850, (0,), ecx=shark)
        (d,) = e.take()
        assert (d["x"], d["y"], d["alpha"], d["scale"]) == (1000, 1000, 1.0, 1.0)
        cells.add(d["rect"][0] // 30)
    assert cells == set(range(8))
    strip = files.image("sharkstripfinal.png")
    assert not any(strip.data[3::4])                                        # every pixel fully transparent
    assert misc.USAGE[0xAA][0] is False


def test_pets_as_the_game_draws_them(vanilla, files):
    import ui_emu

    e = ui_emu.UiEmu(vanilla)
    table = 0x50CB10
    e.call(0x433550, (), ecx=table)                 # the pets' animations
    poses = set()
    for s in range(e.r32(table + 0x6654)):
        b = table + s * 0xEC
        poses |= {e.r32(b + 0x20 + 12 * k) for k in range(e.r32(b + 0xE0))}
    poses.discard(-1)                               # -1: keep the pose
    assert -2 not in poses and 19 not in poses and poses <= set(range(18)) | set(range(20, 24))
    picked = set()
    out = e.alloc(8)
    for action in range(24):                        # the pose picker 0x4333C0 (action, &pose, &heading)
        for heading in range(4):
            e.w32(out + 4, heading)
            e.call(0x4333C0, (action, out, out + 4), ecx=table)
            picked.add(e.r32(out))
    assert picked == {0, 4, 8, 12, 16, 17, 18}
    e.call(0x432E90, (), ecx=table)                 # the pets' table (picture 3, each pose's point)
    pets = 0x513CC0
    rec = pets + 0x2BE4
    drawn = set()
    for pet in range(3):
        for pose in range(24):
            for heading in (range(4) if pose <= 3 else (0,)):
                for field, v in ((0x1BA4, 1000), (0x1BA8, 1000), (0x1BC0, pose), (0x1BE0, pet),
                                 (0x1BE8, heading), (0x1BC8, 0)):
                    e.w32(rec + field, v)
                e.take()
                e.call(0x434550, (0,), ecx=pets)
                (d,) = e.take()
                column = pose + 4 * heading if pose <= 3 else pose
                name, rect = misc.cell(files, 0x03, 24 * pet + column)
                assert (d["file"], d["rect"], d["alpha"], d["scale"]) == (name, rect, 1.0, 1.0)
                drawn.add(24 * pet + column)
    assert drawn == set(range(72))
    for c in range(72):
        assert ((0x03, c) in misc.CELL_UNUSED) == (c % 24 == 19)
        assert ((0x03, c) in misc.CELL_CHECKED) == (c % 24 != 19)
    labels = [misc.CELL_LABELS[(0x03, c)] for c in range(24)]
    assert labels[0].startswith("Cat, walking up and to the right") and "store" in labels[16]


def _measure(img: pi.Image, x0: int, y: int) -> tuple:
    """The trough round the bar at (x0, y): its silver (grey: little colour, bright) and the dark lines (mean
    brightness under 32) right above and below it."""
    d, w = img.data, img.width

    def stats(points):
        s = b = 0
        for x, yy in points:
            r, g, bl = d[4 * (yy * w + x):4 * (yy * w + x) + 3]
            s += max(r, g, bl) - min(r, g, bl)
            b += (r + g + bl) / 3
        return s / len(points), b / len(points)

    def row(yy):
        return stats([(x, yy) for x in range(x0 + 8, x0 + 282)])

    def col(x):
        return stats([(x, yy) for yy in range(y + 1, y + 29)])

    def silver_row(yy):
        s, b = row(yy)
        return s <= 15 and b > 80

    def dark_row(yy):
        return row(yy)[1] < 32

    def silver_col(x):
        s, b = col(x)
        return s <= 25 and b > 50

    top = y + 15
    while silver_row(top - 1):
        top -= 1
    while dark_row(top - 1):
        top -= 1
    bottom = y + 15
    while silver_row(bottom):
        bottom += 1
    while dark_row(bottom):
        bottom += 1
    left = x0 + 15
    while silver_col(left - 1):
        left -= 1
    right = x0 + 15
    while silver_col(right):
        right += 1
    return left, top, right, bottom


def test_trough_pictures_are_the_painted_troughs(files):
    bg = files.image(meters.DETAILS_BG)                 # vf1_jpeg: byte for byte the game's libjpeg
    for kind, rect in meters.TROUGHS.items():
        _name, x0, y, _red = meters.KINDS[kind]
        measured = _measure(bg, x0, y)
        assert measured == rect, (kind, measured)
        assert (measured[0], measured[2] - measured[0]) == (x0, meters.BAR_W)    # the silver is the bar's own


def test_details_bar_draws_land_inside_the_troughs(vanilla):
    import meters_emu

    e = meters_emu.MeterEmu(vanilla)
    by_y = {meters.KINDS[k][2]: k for k in meters.TROUGHS}
    count = 0
    for p in meters.LEVELS + (3, 33, 66, 99):
        for kind in meters.TROUGHS:
            events = e.details(**meters.details_value(kind, p))
            for what, b in events:
                if what != "blit" or b["file"] in (meters.DETAILS_BG, "?") or "head" in b["file"]:
                    continue
                kind_of = by_y[next(y for y in by_y if y <= b["y"] < y + meters.BAR_H)]
                left, top, right, bottom = meters.TROUGHS[kind_of]
                l, t, r, bt = b["rect"]
                assert left <= b["x"] and b["x"] + (r - l) * b["scale"] <= right, (kind_of, p, b)
                assert top <= b["y"] and b["y"] + (bt - t) * b["scale"] <= bottom, (kind_of, p, b)
                count += 1
    assert count > 0
