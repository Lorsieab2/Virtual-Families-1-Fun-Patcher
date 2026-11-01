"""The Picture Maker's house, yard, furniture, weather and night pictures (patcher/vf1_art_house.py).

Everywhere: a synthetic game folder (plain sheets of the vanilla sizes, a synthetic Assets\\lsmap.dat) checks
the list, the keys and categories, that every draw stays inside its picture, the rooms' map parts, the fill's
blend, the lamps' plan and the night picture against a hand-made composite, and the drawing of a few pictures.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read): tests/house_emu.py runs the game's own code in
Unicorn and every listed draw must equal the game's: the map's loader and draw, the house list for every state
(and the loader's picture ids), the television and computer animations started by SetProp, the rain's splash and
the rainbow through the effect clock, the sunbeam, the haze and lightning fills, the night's lamps (copies, masks,
draws) and colours, the darkness levels, and the fill 0x403B40's own pixels against the module's blend.  The
night picture is checked, over one lamp, against a Pillow composite of the game's own fill and the lamp's mask.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest
import vf1_art_house as h
import vf1_game_art as ga
import vf1_picture_image as pi

# the vanilla sizes of every picture the module draws (w, h)
SIZES = {
    "tvOld.png": (130, 140), "tvFlatscreen.png": (99, 104), "toiletOpen.png": (61, 114), "toiletClosed.png": (55, 119),
    "showerCurtain.png": (138, 165), "fridgeStates.png": (117, 252), "kitchenGarbageFull.png": (34, 45),
    "lightbulb.png": (16, 17), "remote.png": (22, 17), "greenLight.png": (6, 5), "redLight.png": (6, 5),
    "rosepetalsOnBed.png": (172, 140), "shedDoor.png": (102, 127), "doorknob.png": (11, 12),
    "floorDamage.png": (210, 48), "stucco.png": (212, 106), "puddles.png": (176, 82), "fountainwater.png": (83, 68),
    "holeSM1.png": (74, 60), "holeLG1.png": (74, 60), "gopherInHole.png": (74, 60), "paintings.png": (150, 71),
    "airPurifier.png": (37, 57), "toolbox.png": (58, 54), "bedUpgrade.png": (248, 225), "fishtank.png": (69, 83),
    "towelUpgrade.png": (100, 88), "treadmill.png": (125, 119), "radio.png": (40, 40), "pinball.png": (80, 100),
    "patioSet.png": (240, 240), "pool.png": (328, 259), "hammock.png": (235, 162), "bbq.png": (100, 100),
    "birdhouse.png": (60, 100), "balconyflowers.png": (180, 28), "cans.png": (31, 36), "breads.png": (69, 58),
    "meal.png": (160, 68), "bbqmeat.png": (56, 42), "foodWork1.png": (120, 60), "carrying.png": (728, 336),
    "workWork1.png": (134, 58), "kitchenUpgrade.png": (1164, 512), "officeUpgrade.png": (750, 241),
    "workroomUpgrade.png": (994, 457), "TVAnimBig.png": (546, 273), "TVAnimSmall.png": (342, 171),
    "eastCPUAnim.png": (210, 70), "westCPUAnim.png": (210, 70), "raindrops.png": (66, 16), "rainbow.png": (500, 25),
    "sunbeam.png": (214, 800), "map_fog.png": (64, 64), "outsideChair.png": (100, 50),
    "LightSourceMask150.png": (150, 150), "LightSourceMask250.png": (250, 250),
}


def _sheet(w: int, h: int, seed: int) -> pi.Image:
    img = pi.Image(w, h)
    row = bytes(b for x in range(w) for b in ((x * 3 + seed) % 256, (x + seed * 5) % 256, seed % 256,
                                               255 if x % 7 else 0))
    img.data[:] = row * h
    return img


def _mask(size: int) -> pi.Image:
    img = pi.Image(size, size)
    c = size / 2
    for y in range(size):
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            img.data[(y * size + x) * 4:(y * size + x) * 4 + 4] = bytes((255, 255, 255, max(0, 255 - int(d * 510 / size))))
    return img


@pytest.fixture(scope="module")
def game(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    (folder / "Images").mkdir(parents=True)
    (folder / "Assets").mkdir()
    for k, (name, (w, hh)) in enumerate(SIZES.items()):
        img = _mask(w) if name.startswith("LightSource") else _sheet(w, hh, k)
        (folder / "Images" / name).write_bytes(img.to_png())
    for name, x, y in h.map_tiles():               # PNG data under the tiles' names: the reader looks at the bytes
        (folder / "Images" / name).write_bytes(_sheet(512, 512, x // 512 * 4 + y // 512).to_png())
    lsmap = bytearray(20 * 0x50)
    for k, entry in enumerate([(6, 300, 300, -1), (4, 1000, 1000, -1), (1, 500, 500, -1), (4, 30, 2040, -1)]):
        struct.pack_into("<4i", lsmap, k * 0x50, *entry)
    for k in range(4, 20):
        struct.pack_into("<4i", lsmap, k * 0x50, 0, 0, 0, -858993460)
    (folder / "Assets" / "lsmap.dat").write_bytes(bytes(lsmap))
    return folder


@pytest.fixture(scope="module")
def files(game) -> ga.GameFiles:
    return ga.GameFiles(game)


# ------------------------------------------------------------------ everywhere
def test_the_list(files):
    arts = h.arts(files)
    keys = [a.key for a in arts]
    assert len(keys) == len(set(keys))
    assert all(k.startswith("house/") for k in keys)
    tops = {a.category.split("/")[0] for a in arts}
    assert tops <= set(ga.CATEGORY_ORDER)
    assert {"House and yard", "Furniture and objects", "Weather, day and night"} <= tops
    for art in arts:
        assert art.label and art.why and (art.used or not art.checked)
        assert "0x" in art.why
        for layer in ga.resolve(files, art).layers:
            if isinstance(layer, h.Computed):
                continue
            w, hh = files.size(layer.file)
            x0, y0, x1, y1 = layer.rect
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= hh, (art.key, layer)
    assert len([a for a in arts if a.key.startswith("house/anim/")]) == 60
    assert not any(a.used for a in arts if a.key in ("house/weather/fog",))


def test_usage_and_cells():
    for image, (used, why) in h.USAGE.items():
        assert image in ga.TABLE and why.endswith(".") and "0x" in why
    for (image, cell), words in {**h.CELL_LABELS, **h.CELL_UNUSED}.items():
        cols, rows = ga.grid_shape(image)
        assert 0 <= cell < cols * rows and words
    assert all(not h.USAGE[image][0] for image, _cell in h.CELL_UNUSED)


def test_the_map_and_its_parts():
    tiles = h.map_tiles()
    assert len(tiles) == 16 and tiles[0] == ("MapX0Y0.jpg", 0, 0) and tiles[1] == ("MapX0Y1.jpg", 0, 512)
    part = h.map_part(500, 100, 1100, 600)
    covered = sum((d.rect[2] - d.rect[0]) * (d.rect[3] - d.rect[1]) for d in part)
    assert covered == 600 * 500
    for d in part:
        _name, x, y = next(t for t in tiles if t[0] == d.file)
        assert (d.x, d.y) == (x + d.rect[0], y + d.rect[1])
        assert 500 <= d.x and d.x + d.rect[2] - d.rect[0] <= 1100


def test_the_fill_blend():
    img = pi.Image(256, 1)
    img.data[:] = bytes(b for v in range(256) for b in (v, 255 - v, v // 2, 77))
    h.blend_fill(img, (0, 0, 102), 178)
    for v in range(256):
        r, g, b, a = img.pixel(v, 0)
        assert (r, g, b, a) == ((v * 77) >> 8, ((255 - v) * 77) >> 8, ((v // 2) * 77 >> 8) + (102 * 178 >> 8), 77)
    assert h.fill_bytes(h.HAZE_GREY, 0.3) == ((76, 76, 76), 77)
    assert h.fill_bytes(*h.colour_floats(h.FLASH)) == ((224, 240, 255), 127)
    assert [h.night_alpha(d) for d in (1.0, 0.8500000238418579, 0.6499999761581421)] == [178, 151, 116]


def test_the_lamps_and_the_night(files):
    plan = h.night_plan(files)
    # the kind-1 lamp is skipped (0x490CEA); the corner lamp is clipped by the map
    assert [(p["mask"], p["x"], p["y"], p["rect"]) for p in plan] == [
        ("LightSourceMask250.png", 175, 175, (0, 0, 250, 250)),
        ("LightSourceMask150.png", 925, 925, (0, 0, 150, 150)),
        ("LightSourceMask150.png", 0, 1965, (45, 0, 150, 83)),
    ]
    scene = pi.Image(h.MAP_SIZE, h.MAP_SIZE)
    scene.data[:] = bytes((40, 90, 160, 255)) * (h.MAP_SIZE * h.MAP_SIZE)
    out = h.night_image(files, 1.0, scene)
    dark = ((40 * 77) >> 8, (90 * 77) >> 8, ((160 * 77) >> 8) + (102 * 178 >> 8), 255)
    assert out.pixel(600, 600) == dark
    mask = files.image("LightSourceMask150.png")
    for x, y in ((1000, 1000), (930, 940), (1070, 1000)):
        a = mask.pixel(x - 925, y - 925)[3]
        expect = pi.Image(1, 1, bytearray(dark))
        expect.draw(pi.Image(1, 1, bytearray((40, 90, 160, a))), 0, 0)
        assert out.pixel(x, y) == expect.pixel(0, 0)


def test_drawing_a_few(files):
    arts = {a.key: a for a in h.arts(files)}
    tv = h.render(files, arts["house/anim/tv/flat/4"])
    assert (tv.width, tv.height) == (1668 - 1564, 646 - 540)    # the set at (1564, 540), the picture at (1577, 555)
    room = h.render(files, arts["house/room/kitchen/1/assembled"])
    assert (room.width, room.height) == (582, 512)
    haze = h.render(files, arts["house/weather/haze/2"])
    tile = files.image("MapX0Y0.jpg")
    r, g, b, _a = tile.pixel(3, 3)
    assert haze.pixel(3, 3)[:3] == tuple(((c * 178) >> 8) + (76 * 77 >> 8) for c in (r, g, b))


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
def emu(vanilla):
    import house_emu
    e = house_emu.HouseEmu(vanilla)
    e.house_setup()
    e.effects_setup()
    return e


CLEAN_BYTES = {0x11C: 1, 0x12C: 1, 0x13C: 1, 0x15C: 1, 0x16C: 1, 0x1DC: 1}
CLEAN_INTS = {0x168: 1}


def _house(emu, setup) -> list[tuple]:
    import house_emu
    emu.clear_state()
    for off, v in {**CLEAN_BYTES, **setup.get("bytes", {})}.items():
        emu.state_byte(off, v)
    for off, v in {**CLEAN_INTS, **setup.get("ints", {})}.items():
        emu.state_int(off, v)
    for t, level in enumerate(setup.get("tech", (1, 1, 1))):
        emu.w32(house_emu.TECH + 4 * t, level)
    emu.w32(house_emu.FOOD, setup.get("food", 0))
    for p in setup.get("props", ()):
        emu.prop(p)
    return [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in emu.house_draws()]


def _mine(layers) -> list[tuple]:
    return [(d.file, tuple(d.rect), d.x, d.y, pi.f32(d.scale), pi.f32(d.alpha)) for d in layers]


def _less(got, base):
    base = list(base)
    out = []
    for d in got:
        if d in base:
            base.remove(d)
        else:
            out.append(d)
    return out


def test_the_map_matches_the_game(emu, vanilla):
    draws, table = emu.map_draws()
    assert table == h.map_tiles()
    got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in draws]
    assert got == _mine(h.map_draws())
    files = ga.GameFiles(vanilla)
    assert all(files.size(name) == (512, 512) for name, _x, _y in h.map_tiles())


def test_the_house_loader_asks_for_every_picture(emu):
    grids = emu.house_grids()
    ids = set(grids.values())
    assert {0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x21, 0x1E, 0x1F, 0x20, 0x82, 0x83, 0x86, 0x87, 0x88, 0x89, 0x8B,
            0x8C, 0x8D, 0x8E, 0x8F, 0x90, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0x9B, 0xBF,
            0xD4, 0xD5} <= ids
    assert grids[0x1854] == 0x88                     # the outside chair, kept and never read back:
    exe = emu.img
    assert exe.count(struct.pack("<I", 0x1854)) == 1      # the only +0x1854 in the exe is the store at 0x41FE9D
    assert exe.count(struct.pack("<I", 0x502278 + 0x1854)) == 0


def test_every_house_state_matches_the_game(emu):
    clean = _house(emu, {})
    assert [d[0] for d in clean] == ["tvOld.png", "lightbulb.png", "remote.png", "toiletOpen.png"]
    for key, _category, _label, setup, mode, _why, rows in h.STATES:
        got = _house(emu, setup)
        got = _less(got, clean) if mode == "diff" else [d for d in got if d[0] in mode]
        assert got == _mine(h._layers(rows)), key
    # the other bathroom leak draws the same puddle
    assert _less(_house(emu, {"props": [0x1C]}), clean) == _less(_house(emu, {"props": [0x1B]}), clean)


def test_the_assembled_house_matches_the_game(emu, vanilla):
    got = _house(emu, h.EVERYTHING_SETUP)
    assert got == _mine(h._layers(h.EVERYTHING))
    arts = {a.key: a for a in h.arts(ga.GameFiles(vanilla))}
    assert _mine(arts["house/everything"].layers) == _mine(h.map_draws()) + [d for d in got if d[0] != "remote.png"]
    for title, word, two, three, _code in h.ROOMS:
        for level, setup_level in ((2, two), (3, three)):
            tech = [1, 1, 1]
            tech[[r[1] for r in h.ROOMS].index(word)] = level
            drawn = _less(_house(emu, {"tech": tuple(tech)}), _house(emu, {}))
            layers = arts[f"house/room/{word}/{level}/assembled"].layers
            assert _mine(layers[-1:]) == drawn, (title, level)
            assert all(d.file.startswith("Map") for d in layers[:-1])
            assert (drawn[0][2], drawn[0][3]) == setup_level[1:]


def test_the_animations_match_the_game(emu, vanilla):
    files = ga.GameFiles(vanilla)
    arts = {a.key: a for a in h.arts(files)}
    for key, _label, image, cols, rows, frames, (x, y), delay, prop, flat, _code in h.ANIMATIONS:
        emu.effect_clear()
        _house(emu, {"bytes": {0x2C: 1 if flat else 0}})
        emu.set_prop(prop)
        entry = emu.effect_entry(0)
        assert (entry["x"], entry["y"], entry["frames"], entry["delay"], entry["loop"], entry["centred"]) == \
            (x, y, frames, delay, 1, 0), key
        assert ga.grid_shape(image) == (cols, rows)
        tv_set = [d for d in _house(emu, {"bytes": {0x2C: 1 if flat else 0}}) if d[0].startswith("tv")]
        for k in range(frames):
            got = emu.effect_draw(0, k)
            got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in got]
            layers = arts[f"house/anim/{key}/{k}"].layers
            if key.startswith("tv/"):
                assert _mine(layers) == tv_set + got, (key, k)
            else:
                assert _mine(layers) == got, (key, k)


def _played(emu, *args) -> list[list[tuple]]:
    emu.effect_clear()
    index = emu.add_effect(*args)
    seen = []
    for _ in range(500):
        if emu.effect_entry(index)["type"] == -1:
            break
        got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in emu.effect_draw(index)]
        if not seen or seen[-1] != got:
            seen.append(got)
        emu.effect_step()
    return seen


def test_the_rain_and_the_rainbow_match_the_game(emu, vanilla):
    arts = {a.key: a for a in h.arts(ga.GameFiles(vanilla))}
    # 0x491CE2: AddEffect(0x14, x, y, 1, 0, -1, 3, 1); 0x4426EA: AddEffect(7, x, y, 1, 0, 0, 9, 1)
    # (played at 1000, 800 so the window's clip does not cut them; the pictures are anchored at 0, 0)
    def moved(key):
        return [(f, r, x + 1000, y + 800, s, a) for f, r, x, y, s, a in _mine(arts[key].layers)]
    rain = _played(emu, 0x14, 1000, 800, 1, 0, 0xFFFFFFFF, 3, 1)
    assert rain == [moved(f"house/weather/raindrop/{k}") for k in range(3)]
    rainbow = _played(emu, 7, 1000, 800, 1, 0, 0, 9, 1)
    assert rainbow == [moved(f"house/weather/rainbow/{k}") for k in range(10)]


def test_the_sunbeam_matches_the_game(emu, vanilla):
    arts = {a.key: a for a in h.arts(ga.GameFiles(vanilla))}
    got = [(d["file"], d["rect"], d["x"], d["y"], d["scale"], d["alpha"]) for d in emu.sunbeam_draws(0, -120, 1.0, 1.0)]
    assert got == _mine(arts["house/weather/sunbeam"].layers)
    faded = emu.sunbeam_draws(0, -60, 1.0, 1.0)
    assert faded[0]["alpha"] == pytest.approx(0.5) and faded[0]["rect"][1] == 60
    assert emu.sunbeam_draws(0, 10, 1.0, 1.0) == []           # below the screen's top: not drawn


def test_the_haze_and_the_lightning_match_the_game(emu):
    exe = emu.img
    f = lambda a: struct.unpack_from("<f", exe, a - 0x400000)[0]
    # the haze each weather fades to: 0x4922B8 fld [0x4B29B4] (0.2), 0x4922CC / 0x4922D8 fld [0x4B6A34] (0.3)
    assert exe[0x4922B8 - 0x400000:0x4922BE - 0x400000] == b"\xD9\x05" + struct.pack("<I", 0x4B29B4)
    assert exe[0x4922D8 - 0x400000:0x4922DE - 0x400000] == b"\xD9\x05" + struct.pack("<I", 0x4B6A34)
    assert (pi.f32(h.HAZE[1]), pi.f32(h.HAZE[2])) == (f(0x4B29B4), f(0x4B6A34))
    assert struct.unpack_from("<I", exe, 0x4FDE6C - 0x400000)[0] == h.FLASH
    for kind in (1, 2, 3):
        fills = emu.weather_fills(kind, pi.f32(h.HAZE[kind]), True, kind == 3)
        expect = [((0, 0, 800, 561), tuple(pi.f32(c) for c in h.HAZE_GREY) + (pi.f32(h.HAZE[kind]),))]
        if kind == 3:
            rgb, a = h.colour_floats(h.FLASH)
            expect.append(((0, 0, 800, 561), rgb + (a,)))
        assert [(r, tuple(pi.f32(c) for c in col)) for _w, r, col in fills] == expect, kind
    assert emu.weather_fills(1, 0.2, False, False) == []          # no haze at night


def test_the_fill_pixels_match_the_game(emu):
    w, hh = 256, 2
    before = bytes(b for y in range(hh) for x in range(w) for b in (x, (x * 7 + y) % 256, 255 - x, 0))
    cases = [h.night_fill(d) for d in (1.0, 0.8500000238418579, 0.6499999761581421)]
    cases += [(h.HAZE_GREY, h.HAZE[1]), (h.HAZE_GREY, h.HAZE[2]), h.colour_floats(h.FLASH)]
    for rgb, alpha in cases:
        out = emu.fill_pixels(before, w, hh, tuple(rgb) + (alpha,))
        img = pi.Image(w, hh, bytearray(before))
        colour, a = h.fill_bytes(rgb, alpha)
        h.blend_fill(img, colour, a)
        assert bytes(img.data) == out, (rgb, alpha)


@pytest.fixture(scope="module")
def night_emu(vanilla):
    import house_emu
    e = house_emu.HouseEmu(vanilla)
    entries = h.lamps(ga.GameFiles(vanilla))
    e.lights_setup(entries)
    # a screen as big as the map: the screen rectangle 0x4FE180 and the window's clip
    for k, v in enumerate((0, 0, h.MAP_SIZE, h.MAP_SIZE)):
        e.w32(0x4FE180 + 4 * k, v)
    for k, v in enumerate((0, 0, 4000, 4000)):
        e.w32(e.impl + 0x60 + 4 * k, v)
    return e


def test_the_night_matches_the_game(night_emu, vanilla):
    files = ga.GameFiles(vanilla)
    plan = h.night_plan(files)
    lamps = [night_emu.light(k) for k in range(20)]
    lit = [lamp for lamp in lamps if lamp["type"]]
    assert [ga.TABLE[lamp["image"]][0] for lamp in lit] == [p["mask"] for p in plan]
    for darkness in (1.0, 0.8500000238418579, 0.6499999761581421):
        records, blits = night_emu.night(darkness)
        fills = [r for r in records if r[0] == "fill"]
        rgb, a = h.night_fill(darkness)
        assert [(r[1], tuple(pi.f32(c) for c in r[2])) for r in fills] == [((0, 0, h.MAP_SIZE, h.MAP_SIZE), rgb + (a,))]
        masks = [r for r in records if r[0] == "mask"]
        assert [r[5] for r in masks] == [p["rect"] for p in plan]
        assert [(b["rect"], b["x"], b["y"], b["alpha"], b["scale"]) for b in blits] == \
            [(p["rect"], p["x"], p["y"], 1.0, 1.0) for p in plan]
        copies = [r for r in records if r[0] == "copy"]
        assert [(r[4], r[5]) for r in copies] == [(p["rect"][0], p["rect"][1]) for p in plan]
        # every copy comes before the fill, every lamp's draw after it (0x4919D7, 0x491A5F, 0x491A96)
        kinds = [r[0] for r in records]
        assert kinds.index("fill") == len(kinds) - 1


def test_the_darkness_matches_the_game(night_emu):
    d = night_emu.darkness
    assert d(3.0, 6.0, 20.0, 1.0, False) == 1.0
    assert d(23.0, 6.0, 20.0, 1.0, False) == pi.f32(0.85)
    assert d(23.0, 6.0, 20.0, 1.0, True) == pi.f32(0.65)
    assert d(12.0, 6.0, 20.0, 1.0, False) == 0.0
    assert d(20.5, 6.0, 20.0, 1.0, False) == 0.5
    assert d(5.5, 6.0, 20.0, 1.0, False) == 0.5


def test_a_night_lamp_matches_a_pillow_composite(night_emu, vanilla):
    """Over lamp 11 (it touches no other lamp), the module's night picture equals the game's own fill 0x403B40
    run on that part of the screen, with the lamp's copy (the unlit picture, the mask's alpha) composited over it
    by Pillow."""
    Image = pytest.importorskip("PIL.Image")
    files = ga.GameFiles(vanilla)
    plan = h.night_plan(files)
    lamp = plan[11]
    scene = pi.Image(h.MAP_SIZE, h.MAP_SIZE)
    scene.data[:] = bytes(b for x in range(h.MAP_SIZE) for b in (x % 256, (x * 3) % 256, 255 - x % 256, 255)) * h.MAP_SIZE
    out = h.night_image(files, 1.0, scene)
    x0, y0, x1, y1 = lamp["rect"]
    w, hh = x1 - x0, y1 - y0
    part = scene.sub(lamp["x"], lamp["y"], w, hh)
    screen = bytes(b for k in range(w * hh) for b in (*part.data[4 * k:4 * k + 3], 0))
    rgb, a = h.night_fill(1.0)
    dark = night_emu.fill_pixels(screen, w, hh, tuple(rgb) + (a,))
    dark_img = Image.frombytes("RGBA", (w, hh), bytes(b for k in range(w * hh) for b in (*dark[4 * k:4 * k + 3], 255)))
    mask = Image.open(vanilla / "Images" / lamp["mask"]).convert("RGBA").crop((x0, y0, x1, y1))
    light = Image.frombytes("RGBA", (w, hh), bytes(part.data))
    light.putalpha(mask.getchannel("A"))
    expect = Image.alpha_composite(dark_img, light)
    assert out.sub(lamp["x"], lamp["y"], w, hh).data == bytearray(expect.tobytes())
