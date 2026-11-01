"""The Picture Maker (patcher/vf1_picture_maker.py, vf1_people_pictures.py, vf1_picture_image.py).

Everywhere: a synthetic game folder (small sheets whose every cell has its own colour, a synthetic
Assets\\animpts.dat) and synthetic saves check the part selection, the life stages, the layer order, every
export size, transparency, the patched and stock looks, a save with no family, and the window.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read): tests/picture_emu.py runs the game's own
drawing code in Unicorn and every draw the renderer plans must equal the game's (file, cell, place, scale,
alpha); the game's own blitter 0x404C30 draws children and ghosts over three colours and the renderer's
pixels must give exactly the same screen; and an adult's PNG must equal, pixel for pixel, the cells
composited by Pillow at the places the emulated game drew them.  The same for everything that can be carried:
every carried number under every animation, every carried picture's PNG, the game's own animation start
0x485D50, and the carried numbers read from the exe's carry steps.
"""
from __future__ import annotations

import os
import random
import struct
import tkinter as tk
from pathlib import Path

import pytest
import vf1_people_pictures as pp
import vf1_picture_image as pi
import vf1_picture_maker as pm
import vf1_save as vs
from test_vf1_save import build_save, villager_record

ROOT = Path(__file__).resolve().parents[1]
CELL = {}          # synthetic sheets: (cell w, cell h) per image id


# ------------------------------------------------------------------ a synthetic game folder
def _sheet(image: int, file_index: int) -> pi.Image:
    _stem, cols, rows, files = pp.IMAGES[image]
    per_file = cols // files
    cw, ch = CELL.get(image, (6, 5))
    img = pi.Image(per_file * cw, rows * ch)
    for r in range(rows):
        for c in range(per_file):
            colour = ((image * 7) % 256, (file_index * per_file + c) * 4 % 256, r * 5 % 256, 255)
            for y in range(r * ch, r * ch + ch):
                for x in range(c * cw + 1, c * cw + cw):       # column 0 of each cell is see-through
                    at = (y * img.width + x) * 4
                    img.data[at:at + 4] = bytes(colour)
    return img


def _animpts() -> bytes:
    bodies = bytearray(57 * 0xCA4)
    for pose in range(57):
        for k in range(4):
            block = pose * 0xCA4 + 4 + k * 0x328
            for row in range(50):
                struct.pack_into("<ii", bodies, block + 8 + row * 8, 2, 1)          # the neck
                struct.pack_into("<ii", bodies, block + 0x198 + row * 8, 3, 4)      # the feet
    heads = bytearray(30 * 0x328)
    for block in range(30):
        for row in range(50):
            struct.pack_into("<ii", heads, block * 0x328 + 0x198 + row * 8, -5, -1)
    return struct.pack("<I", len(bodies)) + bytes(bodies) + struct.pack("<I", len(heads)) + bytes(heads)


@pytest.fixture(scope="module")
def game(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    (folder / "Images").mkdir(parents=True)
    (folder / "Assets").mkdir()
    (folder / "Assets" / "animpts.dat").write_bytes(_animpts())
    for image in pp.IMAGES:
        for k, name in enumerate(pp.image_files(image)):
            (folder / "Images" / name).write_bytes(_sheet(image, k).to_png())
    return folder


@pytest.fixture
def art(game) -> pp.Art:
    return pp.Art(game)


ADULT = pp.Person(female=True, age=600, head=7, body=9)


# ------------------------------------------------------------------ part selection
def test_part_selection(art):
    plan = pp.house_plan(art, ADULT, pp.HouseView(pose=pp.STANDING_POSE))
    by = {d.what: d for d in plan}
    assert by["body"].file == "female_actions00.png" and by["body"].rect == (14 * 6, 9 * 5, 15 * 6, 10 * 5)
    assert by["head"].file == "female_heads00.png" and by["head"].rect == (5 * 6, 7 * 5, 6 * 6, 8 * 5)
    male = pp.house_plan(art, pp.Person(False, 600, 3, 4), pp.HouseView(pose=2, direction=3, head_turn=0))
    body = next(d for d in male if d.what == "body")
    assert body.file == "male_bodies00.png" and body.rect[0] == (2 + 8 * 3) * 6      # step + 8 x direction
    sit = next(d for d in pp.house_plan(art, ADULT, pp.HouseView(pose=50)) if d.what == "body")
    assert sit.file == "female_sit00.png" and sit.rect[0] == 3 * 6
    old = next(d for d in pp.house_plan(art, pp.Person(True, 900, 7, 9), pp.HouseView()) if d.what == "head")
    assert old.file == "female_heads10.png" and old.rect[0] == 5 * 6          # column 5 + 12: the 10 file
    portrait = {d.what: d for d in pp.portrait_plan(art, ADULT, expression=2)}
    assert portrait["body"].file == "highrez_bodies_final2.png" and portrait["body"].rect[0] == 6   # female: column 1
    assert portrait["head"].file == "bigheads00.png" and portrait["head"].rect[0] == (3 + 2) * 6
    old_portrait = {d.what: d for d in pp.portrait_plan(art, pp.Person(False, 950, 1, 1), expression=4)}
    assert old_portrait["head"].file == "bigheads10.png" and old_portrait["head"].rect[0] == 1 * 6
    (outfit,) = pp.outfit_plan(art, False, 33)
    assert outfit.file == "male_actions00.png" and outfit.rect == (14 * 6, 33 * 5, 15 * 6, 34 * 5)
    assert outfit.scale == pi.f32(0.7)
    carried = [d for d in pp.house_plan(art, ADULT, pp.HouseView(carried=pp.CARRYING_CELLS + 8)) if d.what == "carried"]
    assert carried[0].file == "collectables_small.png" and carried[0].rect == (2 * 6, 1 * 5, 3 * 6, 2 * 5)


def test_every_choice_draws(art):
    for pose, _label in pp.pose_choices():
        for direction in range(4):
            assert pp.render(art, {"view": "house", "female": True, "age": 300, "pose": pose, "direction": direction})
    for turn in range(pp.HEAD_TURNS):
        assert pp.render(art, {"view": "house", "female": False, "age": 900, "head_turn": turn})
    for value, _label in pp.carried_choices():
        assert pp.render(art, {"view": "house", "female": True, "age": 600, "carried": value})
    with pytest.raises(pi.PictureError):
        pp.render(art, {"view": "house", "female": True, "head": 50})


# ------------------------------------------------------------------ life stages
def test_life_stage_by_age():
    assert [pp.stage_name(y * 20) for y in (0, 1, 3, 4, 12, 13, 17, 18, 44, 45, 90)] == [
        "Baby", "Toddler", "Toddler", "Child", "Child", "Teen", "Teen", "Adult", "Adult", "Elder", "Elder"]
    assert pp.body_scale(0) == 0.5 and pp.head_scale(0) == pi.f32(0.8)
    assert pp.body_scale(280) == pp.head_scale(280) == 1.0                   # full size from 14
    assert pi.percent_scale(pp.body_scale(279)) == (89, pi.f32(0.89))        # 279 / 700 + 0.5, cut to a percent
    assert pi.percent_scale(pp.head_scale(279)) == (99, pi.f32(0.99))
    sizes = [pi.percent_scale(pp.body_scale(age))[0] for age in range(0, 280, 20)]
    assert sizes == sorted(sizes) and sizes[0] == 50                        # smaller each year younger
    ages = [a for a, _label in pp.age_choices()]
    assert ages[:14] == [y * 20 for y in range(14)] and ages[-1] == pp.OLD_FROM


def test_children_are_drawn_smaller(art):
    child = pp.render(art, {"view": "house", "female": True, "age": 0, "shadow": False})
    adult = pp.render(art, {"view": "house", "female": True, "age": 600, "shadow": False})
    assert child.bbox() is not None and child.width < adult.width and child.height < adult.height


# ------------------------------------------------------------------ layer order
def test_layer_order(art):
    behind = pp.house_plan(art, pp.Person(True, 600, 1, 1, babies=2), pp.HouseView(direction=0, carried=5))
    assert [d.what for d in behind] == ["shadow", "baby on the way", "baby on the way", "carried", "body", "head"]
    front = pp.house_plan(art, pp.Person(True, 600, 1, 1, babies=1), pp.HouseView(direction=1, carried=5))
    assert [d.what for d in front] == ["shadow", "body", "head", "baby on the way", "carried"]
    ghost = pp.house_plan(art, ADULT, pp.HouseView(ghost=True))
    assert [d.what for d in ghost] == ["body", "head"] and {d.alpha for d in ghost} == {pi.f32(0.75)}
    assert [d.what for d in pp.portrait_plan(art, ADULT)] == ["body", "head"]
    # the head is drawn over the body: where both are, the head's colour shows
    picture = pp.render_plan(art, [d for d in pp.house_plan(art, ADULT, pp.HouseView(shadow=False))])
    head_colour = (0x9C * 7 % 256, 5 * 4, 7 * 5, 255)
    assert head_colour in {picture.pixel(x, y) for x in range(picture.width) for y in range(picture.height)}


# ------------------------------------------------------------------ everything that can be carried
NEVER_SHOWN = {pp.UNSHOWN_BUNDLE, 12, 21, 24, 32, 33, 43, 45, 78 + 48, 78 + 63, *range(78 + 67, 78 + 72)}


def test_every_carried_picture_is_offered():
    """All 78 cells of carrying.png and all 72 of collectables_small.png, each once, each named, the ones the game
    never shows marked so (with the reason) and listed after the ones it shows."""
    things = pp.carried_things()
    assert len(things) == 150 and len({t.value for t in things}) == 150
    assert sorted((t.file, t.cell) for t in things) == sorted(
        [("carrying.png", k) for k in range(78)] + [("collectables_small.png", k) for k in range(72)])
    assert {t.value for t in things if not t.shown} == NEVER_SHOWN
    for t in things:
        assert t.name and t.kind and (t.shown or t.why)
        assert ("(never shown in the game)" in t.label()) == (not t.shown)
        assert t.value == pp.UNSHOWN_BUNDLE or t.value == (t.cell if t.file == "carrying.png" else 78 + t.cell)
        assert ("Position not from the game" in t.note()) == (t.value == pp.UNSHOWN_BUNDLE)
        assert all(a in pp.ACTION_CAPTIONS for a in t.actions)
        assert t.shown == bool(t.actions) or t.value == 78 + 48          # the blue sock has an action, vanishes
    choices = pp.carried_choices()
    assert choices[0] == (-1, "Nothing") and len(choices) == 151
    shown = [v for v, label in choices[1:] if "never shown" not in label]
    assert choices[1:len(shown) + 1] == [(v, l) for v, l in choices[1:] if "never shown" not in l]   # shown first
    assert len(pp.CARRYING_NAMES) == 78 and len(set(pp.CARRYING_NAMES)) == 78
    assert sorted(c for cells in pp.CARRYING_KINDS.values() for c in cells) == list(range(78))


def test_carried_action_captions_are_the_games():
    import vf1_game_mechanics as gm
    captions = {k: c.strip() for k, c, _outs in gm.ACTION_LIST}
    for action, caption in pp.ACTION_CAPTIONS.items():
        if action not in (91, 92):                     # the drops on the TV remote and the shed door
            assert captions[action] == caption, action
    assert {91, 92} <= {a for acts in pp.CARRIED_BY.values() for a in acts}
    assert set(pp.CARRIED_BY) | set(pp.CARRYING_UNUSED) | {pp.BUNDLE} == set(range(78))
    assert not set(pp.CARRIED_BY) & set(pp.CARRYING_UNUSED)


def test_animations(art):
    choices = pp.animation_choices()
    assert len(choices) == 25 and len(pp.ANIMATION_EXAMPLES) == 24 and choices[0][0] == pp.NO_ANIMATION
    for k, label in choices[1:]:
        assert ("px lower" in label) == (k in pp.CARRY_LOWER)
        assert ("never played" in label) == (k in pp.UNPLAYED_ANIMATIONS)
    base = pp.HouseView(pose=3, direction=1, carried=5)
    assert pp.view_pose(base) == (3, 1)
    assert pp.view_pose(pp.HouseView(pose=3, direction=1, animation=23)) == (55, 2)
    assert pp.view_pose(pp.HouseView(pose=3, direction=1, animation=0)) == (2, 1)       # keeps the walking direction
    assert pp.view_pose(pp.HouseView(pose=50, direction=2, animation=4)) == (50, 2)     # keeps both
    person = pp.Person(True, 600, 1, 1, babies=3)

    def spots(animation):
        return [(d.what, d.x, d.y) for d in pp.house_plan(art, person, pp.HouseView(carried=5, animation=animation))
                if d.what != "body" and d.what != "head" and d.what != "shadow"]
    plain = spots(pp.NO_ANIMATION)
    for animation, lower in pp.CARRY_LOWER.items():
        pose = pp.ANIMATIONS[animation][0]
        body_lower = 20 if pose in pp.LOWERED_POSES else 0
        assert spots(animation) == [(w, x, y + lower + body_lower) for w, x, y in plain], animation
    shadows = [d.what for d in pp.house_plan(art, person, pp.HouseView(animation=pp.NO_SHADOW_ANIMATION))]
    assert "shadow" not in shadows
    bundle = [d for d in pp.house_plan(art, ADULT, pp.HouseView(carried=pp.UNSHOWN_BUNDLE))
              if d.what.startswith("carried")]
    one_baby = [d for d in pp.house_plan(art, pp.Person(True, 600, 7, 9, babies=1), pp.HouseView())
                if d.what == "baby on the way"]
    assert [(d.file, d.rect, d.x, d.y) for d in bundle] == [(d.file, d.rect, d.x, d.y) for d in one_baby]
    for value, _label in pp.carried_choices():
        assert pp.render(art, {"view": "house", "female": True, "age": 600, "carried": value, "animation": 23})


# ------------------------------------------------------------------ sizes and transparency
@pytest.mark.parametrize("size, expect", [("1x", 1), ("2x", 2), ("4x", 4)])
def test_every_scale_gives_its_size(art, size, expect):
    image = pp.render(art, {"view": "house", "female": True, "age": 600})
    cropped = image.cropped(pi.MARGIN)
    out = pi.export(image, **pm.export_options(size))
    assert (out.width, out.height) == (cropped.width * expect, cropped.height * expect)
    bare = pi.export(image, **pm.export_options(size, margin=False))
    box = image.bbox()
    assert (bare.width, bare.height) == ((box[2] - box[0]) * expect, (box[3] - box[1]) * expect)


def test_a_custom_size(art):
    image = pp.render(art, {"view": "portrait", "female": False, "age": 600})
    cropped = image.cropped(pi.MARGIN)
    assert (lambda o: (o.width, o.height))(pi.export(image, **pm.export_options("custom", "300", "200"))) == (300, 200)
    wide = pi.export(image, **pm.export_options("custom", "150", ""))
    assert wide.width == 150 and wide.height == max(1, round(cropped.height * 150 / cropped.width))
    tall = pi.export(image, **pm.export_options("custom", "", "90"))
    assert tall.height == 90
    for bad in (("x", ""), ("0", "")):
        with pytest.raises(pi.PictureError):
            pm.export_options("custom", *bad)
    with pytest.raises(pi.PictureError):
        pi.export(image, **pm.export_options("custom", "", ""))
    with pytest.raises(pi.PictureError):
        pi.export(image, **pm.export_options("custom", str(pi.MAX_SIDE + 1), ""))


def test_transparency(art, tmp_path):
    path = pi.save_png(pp.render(art, {"view": "house", "female": True, "age": 600}), tmp_path / "a.png")
    data = path.read_bytes()
    assert data[:8] == pi.PNG_MAGIC and data[24:26] == bytes([8, 6])       # 8-bit RGBA
    image = pi.decode_png(data)
    corners = [image.pixel(x, y) for x in (0, image.width - 1) for y in (0, image.height - 1)]
    assert all(c[3] == 0 for c in corners)
    assert any(image.data[3::4]) and 0 in image.data[3::4]
    shown = image.on_checks()
    assert all(shown.data[3::4][k] == 255 for k in range(0, shown.width * shown.height, 97))


def test_the_ghost_is_see_through(art):
    for draw in pp.house_plan(art, ADULT, pp.HouseView(ghost=True)):
        layer = pp.layer(art, draw)
        assert set(layer.data[3::4]) == {0, (255 * 191 + 0x7F) >> 8}        # alpha 0.75: 191 of 255, then (a A + 127) >> 8
    ghost = pp.render(art, {"view": "house", "female": True, "age": 600, "ghost": True})
    assert 0 < max(ghost.data[3::4]) < 255                                  # head over body: still see-through


def test_png_round_trip_and_over_rule():
    rng = random.Random(3)
    image = pi.Image(17, 9, bytes(rng.randrange(256) for _ in range(17 * 9 * 4)))
    assert pi.decode_png(image.to_png()) == image
    canvas = pi.Image(2, 1, bytes([10, 20, 30, 255, 0, 0, 0, 0]))
    canvas.draw(pi.Image(2, 1, bytes([200, 100, 0, 128, 7, 8, 9, 64])), 0, 0)
    assert canvas.pixel(1, 0) == (7, 8, 9, 64)                              # onto nothing: itself
    assert canvas.pixel(0, 0)[3] == 255 and 10 < canvas.pixel(0, 0)[0] < 200


# ------------------------------------------------------------------ patched and stock looks
def test_patched_and_stock_looks(game, tmp_path):
    folder = tmp_path / "patched game"
    import shutil
    shutil.copytree(game, folder)
    stock = (folder / "Images" / "carrying.png").read_bytes()
    originals = folder / pp.ORIGINALS / "Images"
    originals.mkdir(parents=True)
    (originals / "carrying.png").write_bytes(stock)                        # the patcher's backup of the stock one
    patched = pi.Image(13 * 6, 6 * 5)
    patched.data[:] = bytes([1, 2, 3, 255]) * (13 * 6 * 6 * 5)
    (folder / "Images" / "carrying.png").write_bytes(patched.to_png())     # what Custom Map/Game Images installs
    spec = {"view": "house", "female": True, "age": 600, "shadow": False, "carried": 0, "direction": 1}
    looks = {look: pp.render(pp.Art(folder, look), spec) for look in ("game", "stock", "patched")}
    plain = pp.render(pp.Art(game), spec)
    assert looks["stock"] == plain                                          # the backup: the stock picture
    assert looks["game"] != plain and (1, 2, 3, 255) in {looks["game"].pixel(x, y)
                                                         for x in range(looks["game"].width)
                                                         for y in range(looks["game"].height)}
    assert pp.Art(folder).patched_files() == ["carrying.png"] and pp.Art(game).patched_files() == []
    # the patcher's own picture (payload, shipped with the patcher) is used for the patched look
    payload = tmp_path / "payload"
    (payload / "CustomImages").mkdir(parents=True)
    (payload / "CustomImages" / "carrying.png").write_bytes(patched.to_png())
    assert pp.render(pp.Art(game, "patched", payload=payload), spec) == looks["game"]
    assert (ROOT / "patcher" / "payload" / "CustomImages" / "carrying.png").is_file()
    assert pp.Art(game, "patched").path("carrying.png") == ROOT / "patcher" / "payload" / "CustomImages" / "carrying.png"


# ------------------------------------------------------------------ saves
def _save(folder: Path, slot: int, villagers: dict, tray=(), inventory=None, **gs) -> Path:
    data = bytearray(build_save(villagers, [], family="Picture", **gs))
    head = 24

    def put(gs: int, value: int):
        struct.pack_into("<i", data, head + gs - vs.GS_BASE, value)
    for place, (item, uses) in enumerate(tray):
        put(vs.GS_TOOL_TRAY + place * 8, item)
        put(vs.GS_TOOL_TRAY + place * 8 + 4, uses)
    for field, value in (inventory or {}).items():
        put(vs.GS_INVENTORY + field, value)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Virtual Families{slot}.ldw"
    path.write_bytes(bytes(data))
    return path


def _sidecar(folder: Path, save: Path, pictures: list[int]):
    payload = vs.read_save(save).payload
    gs = lambda o: struct.unpack_from("<i", payload, o - vs.GS_BASE)[0]
    body = b"VF1OUTFT" + struct.pack("<I", 1) + b"VF1V101\0" + struct.pack("<I", 148)
    body += b"".join(struct.pack("<ii", gs(vs.GS_TOOL_TRAY + k * 8), gs(vs.GS_TOOL_TRAY + k * 8 + 4)) for k in range(8))
    body += b"".join(struct.pack("<i", gs(vs.GS_INVENTORY + f)) for f in (0x108, 0x10C, 0x110, 0x114, 0x118))
    body += struct.pack("<8i", *pictures)
    h = 0xCBF29CE484222325
    for b in body:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    out = folder / vs.PATCHER_DATA / "Outfits" / f"{save.name}.dat"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body + struct.pack("<Q", h))


def test_the_family_in_a_save(art, tmp_path):
    folder = tmp_path / "Virtual Families - Modded"
    _save(folder, 2, {
        0: villager_record(name="Mama", sex=1, age=640, head=4, body=6, preg=630, babies=2),
        1: villager_record(name="Papa", sex=0, age=950, head=8, body=10),
        2: villager_record(name="Tot", sex=1, age=45, head=2, body=1),
        3: villager_record(name="Away", sex=0, age=400, left=1),
        4: villager_record(name="Gran", sex=1, age=1300, health=0),
        5: villager_record(name="Gone", present=0, age=300),
        6: villager_record(name="Unborn", sex=1, age=0),
    }, pending=(6, -1, -1), tray=[(64, 1), (65, 1), (12, 3)], inventory={0x108: 3, 0x10C: 4, 0x110: 21, 0x114: 22})
    assert [(s.slot, s.family) for s in pp.save_slots(folder)] == [(2, "Picture")]
    things = pp.saved_things(folder, 2)
    labels = [t.item.label for t in things]
    assert labels[:5] == ["Gran (female, elder, 65 years) (deceased)", "Papa (male, elder, 47 years)",
                          "Mama (female, adult, 32 years)", "Tot (female, toddler, 2 years)",
                          "Away (male, adult, 20 years)"]
    assert [t.item.location for t in things[:5]] == ["The family"] * 4 + ["Left home"]
    mama = things[2]
    assert mama.person == pp.Person(True, 640, 4, 6, babies=2) and "expecting twins" in mama.item.detail
    assert things[0].dead and things[0].person.babies == 0
    outfits = [(t.item.id, t.outfit) for t in things if t.outfit]
    # the stock game: every outfit in the tray shows the last one bought of its kind
    assert outfits == [("store:male", (False, 3)), ("store:female", (True, 4)), ("tray:0", (False, 21)),
                       ("tray:1", (True, 22))]
    for thing in things:
        spec = {"view": "outfit", "female": thing.outfit[0], "picture": thing.outfit[1]} if thing.outfit else \
            {"view": "house", "female": thing.person.female, "age": thing.person.age, "head": thing.person.head,
             "body": thing.person.body, "babies": thing.person.babies, "ghost": thing.dead}
        assert pp.render(art, spec).bbox() is not None


def test_the_outfit_fix_keeps_each_outfits_own_picture(tmp_path):
    folder = tmp_path / "saves"
    save = _save(folder, 1, {0: villager_record(name="A", sex=1, age=500)}, tray=[(64, 1), (64, 1), (65, 1)],
                 inventory={0x110: 21, 0x114: 22})
    _sidecar(folder, save, [5, 6, -1, -1, -1, -1, -1, -1])
    tray = {t.item.id: t.outfit for t in pp.saved_things(folder, 1) if t.item.id.startswith("tray")}
    assert tray == {"tray:0": (False, 5), "tray:1": (False, 6), "tray:2": (True, 22)}   # the patched look
    # a sidecar for another state of the save is not used: the stock look
    _save(folder, 1, {0: villager_record(name="A", sex=1, age=500)}, tray=[(64, 1), (64, 2), (65, 1)],
          inventory={0x110: 21, 0x114: 22})
    tray = {t.item.id: t.outfit for t in pp.saved_things(folder, 1) if t.item.id.startswith("tray")}
    assert tray == {"tray:0": (False, 21), "tray:1": (False, 21), "tray:2": (True, 22)}


def test_a_save_with_no_family(tmp_path, tk_root, game):
    folder = tmp_path / "empty"
    _save(folder, 1, {})
    assert [t for t in pp.saved_things(folder, 1) if t.person is not None] == []   # only the store's outfits
    maker = pm.PictureMaker(tk_root, save_folders=[folder], game_folders=[game])
    try:
        maker.quiet = True
        assert maker.current_slot().slot == 1
        assert "no family members" in maker.save_preview["info"].cget("text")
        assert maker.save_png("save") is None and maker.last_message == "Pick a picture first."
    finally:
        maker.close()


# ------------------------------------------------------------------ the window
@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def test_the_window(tk_root, game, tmp_path):
    folder = tmp_path / "saves"
    _save(folder, 3, {0: villager_record(name="Ann", sex=1, age=500, head=3, body=4),
                      1: villager_record(name="Bo", sex=0, age=100, head=5, body=6)}, tray=[(64, 1)],
          inventory={0x110: 8})
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    held = []
    maker = pm.open_window(tk_root, save_folders=[folder], game_folders=[game], hold=held.append)
    try:
        maker.quiet = True
        assert held == [maker.window] and pm.open_window(tk_root) is maker
        assert [maker.notebook.tab(t, "text") for t in maker.notebook.tabs()] == ["From my save", "Make your own"]
        assert "Pictures from" in maker.status_var.get()
        assert maker.selected_thing().item.label.startswith("Ann") and maker.shown["save"].bbox()
        out = maker.save_png("save", str(tmp_path / "ann.png"))
        assert out.is_file() and pi.decode_png(out.read_bytes()).width == maker.shown["save"].cropped().width
        maker.size_var.set("2x")
        target = maker.save_all(str(tmp_path / "all"))
        assert sorted(p.name for p in target.iterdir()) == ["Ann (female, adult, 25 years).png",
                                                            "Bo (male, child, 5 years).png"]
        maker.set_custom(view="portrait", female=False, age=900, head=10, body=11)
        assert str(maker.custom_boxes["pose"]["box"].cget("state")) == "disabled"
        assert maker.shown["custom"].bbox() and "Hair and face 10" in maker.picture_name("custom")
        maker.set_custom(view="outfit", body=12)
        assert maker.shown["custom"].height == 3                    # a 5-pixel cell at 70%
        maker.size_var.set("custom")
        maker.width_var.set("abc")
        assert maker.save_png("custom", str(tmp_path / "x.png")) is None and "whole number" in maker.last_message
    finally:
        maker.close()
    assert {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before     # saves only read


def test_carrying_in_both_tabs(tk_root, game, tmp_path):
    folder = tmp_path / "saves"
    _save(folder, 1, {0: villager_record(name="Ann", sex=1, age=500, head=3, body=4)})
    maker = pm.PictureMaker(tk_root, save_folders=[folder], game_folders=[game])
    try:
        maker.quiet = True
        boxes = maker.saved_boxes
        assert "carried" in boxes and "animation" in boxes
        plain = maker.shown["save"]
        boxes["carried"]["box"].current([c[0] for c in boxes["carried"]["choices"]].index(48))
        boxes["animation"]["box"].current([c[0] for c in boxes["animation"]["choices"]].index(23))
        maker._show_saved()
        info = maker.save_preview["info"].cget("text")
        assert "Newspaper" in info and "Reading the newspaper" in info and "20 pixels lower" in info
        assert maker.shown["save"] != plain and "carrying Newspaper" in maker.picture_name("save")
        assert str(boxes["pose"]["box"].cget("state")) == "disabled"            # the animation's own pose
        out = maker.save_png("save", str(tmp_path / "ann.png"))
        assert out.is_file()
        maker.set_custom(view="house", carried=pp.UNSHOWN_BUNDLE, animation=pp.NO_ANIMATION)
        info = maker.custom_preview["info"].cget("text")
        assert info.startswith(pm.CHECK) and "never shown" in info.lower() and "Position not from the game" in info
        assert str(maker.custom_boxes["pose"]["box"].cget("state")) == "readonly"
        maker.set_custom(carried=78 + 70, animation=0)                           # an empty cell; a walking animation
        assert "blank" in maker.custom_preview["info"].cget("text")
        assert str(maker.custom_boxes["direction"]["box"].cget("state")) == "readonly"    # a random walking direction
        maker.set_custom(carried=-1, animation=4)
        assert pm.CHECK in maker.custom_preview["info"].cget("text") and maker.shown["custom"].bbox()
        for value, _label in pp.carried_choices():
            maker.set_custom(carried=value, animation=23)
            assert maker.shown["custom"].bbox()
    finally:
        maker.close()


def test_the_tools_tab_opens_it():
    source = (ROOT / "patcher" / "vf1_patcher_gui.py").read_text(encoding="utf-8")
    assert 'self._link(family, "Picture Maker...", self.picture_maker)' in source
    assert 'self._help_button(family, "picture_maker")' in source


# ------------------------------------------------------------------ against the game itself
@pytest.fixture(scope="module")
def vanilla() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    # Unicorn's memory set-up raises access violations it handles itself; pytest's faulthandler would print
    # each one as "Windows fatal exception" (a vectored handler sees them first), so it is off meanwhile.
    import faulthandler
    was_on = faulthandler.is_enabled()
    faulthandler.disable()
    yield Path(value).resolve()
    if was_on:
        faulthandler.enable()


def _game_house(emu, female, age, head, body, pose, direction, head_turn, ghost, carried, babies, animation=0):
    emu.villager(female=female, age=age, head=head, body=body, pose=pose, direction=direction, head_turn=head_turn,
                 ghost=ghost, carried=carried, babies=babies, animation=animation)
    fx, fy = emu.feet()
    return [(b["file"], b["rect"], b["x"] - fx, b["y"] - fy, b["scale"], b["alpha"]) for b in emu.draw_house(1.0)], (fx, fy)


def _mine(plan):
    return [(d.file, d.rect, d.x, d.y, pi.f32(d.scale), pi.f32(d.alpha)) for d in plan]


def test_image_table_matches_the_game(vanilla):
    """theGraphicsManager's image table 0x4F2D00 (0x30 bytes an entry: id, file, columns, rows, the name's
    number format, files across) names every picture as the renderer and the emulator use them."""
    import pefile
    import picture_emu
    image = pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True).get_memory_mapped_image()
    table = {struct.unpack_from("<I", image, a - 0x400000)[0]: a - 0x400000 for a in range(0x4F2D00, 0x4F5520, 0x30)}
    for image_id, (stem, cols, rows, files) in pp.IMAGES.items():
        name_at, t_cols, t_rows, fmt, across = struct.unpack_from("<5I", image, table[image_id] + 4)
        name = bytes(image[name_at - 0x400000:image.index(b"\0", name_at - 0x400000)]).decode()
        assert name == stem, image_id
        assert (max(1, t_cols), max(1, t_rows), across if fmt else 1) == (cols, rows, files), image_id
        assert picture_emu.IMAGES[image_id][0] == stem
        assert (max(1, picture_emu.IMAGES[image_id][1]), max(1, picture_emu.IMAGES[image_id][2]),
                picture_emu.IMAGES[image_id][3]) == (cols, rows, files)


def test_every_draw_matches_the_game(vanilla):
    import picture_emu
    art = pp.Art(vanilla)
    rng = random.Random(11)
    cases = [(bool(age % 2), age, age % 50, age * 7 % 50, 46, age % 4, 5, False, -1, 0) for age in range(0, 1200, 2)]
    cases += [(rng.random() < 0.5, rng.randrange(1200), rng.randrange(50), rng.randrange(50), rng.randrange(56),
               rng.randrange(4), rng.randrange(12), rng.random() < 0.2,
               rng.choice([-1, 3] + list(range(150))), rng.randrange(4)) for _ in range(700)]
    for precision in (53, 64):          # the x87's precision changes nothing
        emu = picture_emu.Emu(vanilla, precision=precision)
        for case in cases if precision == 53 else cases[::10]:
            female, age, head, body, pose, direction, turn, ghost, carried, babies = case
            got, _feet = _game_house(emu, *case)
            plan = pp.house_plan(art, pp.Person(female, age, head, body, babies),
                                 pp.HouseView(pose, direction, turn, True, ghost, carried))
            assert got == _mine(plan), case
        for age in range(0, 1000, 37 if precision == 53 else 111):
            emu.villager(female=bool(age % 2), age=age, head=age % 50, body=age * 3 % 50, pose=0)
            got = [(b["file"], b["rect"], b["x"] - 2000, b["y"] - 2000, b["scale"], b["alpha"])
                   for b in emu.draw_portrait(2000, 2000, age % 5)]
            assert got == _mine(pp.portrait_plan(art, pp.Person(bool(age % 2), age, age % 50, age * 3 % 50), age % 5))


def test_every_carried_thing_matches_the_game(vanilla):
    """Every carried number the game can hold (nothing, 0-149; the bundle's own picture is the Babies on the way
    choice) under every animation (none and the 24, each with the pose and direction it puts in place), at a
    child's and an adult's size, alive and as a ghost, with and without babies on the way: the game's
    CVillagerManager 0x48B4D0 run in Unicorn draws exactly what the renderer plans."""
    import picture_emu
    art = pp.Art(vanilla)
    emu = picture_emu.Emu(vanilla)
    rng = random.Random(23)
    values = [-1] + [t.value for t in pp.carried_things() if t.value != pp.UNSHOWN_BUNDLE]
    assert len(values) == 150
    checked = 0
    for value in values:
        for animation in [pp.NO_ANIMATION] + list(range(len(pp.ANIMATIONS))):
            female, age = rng.random() < 0.5, rng.choice([0, 120, 279, 600, 950])
            head, body, turn = rng.randrange(50), rng.randrange(50), rng.randrange(12)
            view = pp.HouseView(rng.choice([46, rng.randrange(8), rng.randrange(32, 56)]), rng.randrange(4), turn,
                                True, rng.random() < 0.15, value, animation)
            babies = rng.choice([0, 0, 1, 2, 3])
            pose, direction = pp.view_pose(view)
            got, _feet = _game_house(emu, female, age, head, body, pose, direction, turn, view.ghost, value, babies,
                                     animation)
            plan = pp.house_plan(art, pp.Person(female, age, head, body, babies), view)
            assert got == _mine(plan), (value, animation, female, age, view)
            checked += 1
    assert checked == 150 * 25


def test_animations_put_the_pose_in_place_as_the_game(vanilla):
    """CVillager 0x485D50 (start an animation, with no direction or head turn of its own: -1, -1) run in Unicorn
    for all 24: the animation number, pose and direction it leaves are view_pose's."""
    import picture_emu
    emu = picture_emu.Emu(vanilla)
    for animation in range(len(pp.ANIMATIONS)):
        for pose, direction in ((46, 1), (5, 3), (50, 0), (2, 2)):
            v = emu.villager(female=True, age=600, head=1, body=1, pose=pose, direction=direction, animation=99)
            # GetRandom stands in for the walk: rand(4) picks the walking direction (0x451350, table 0x4D6A64)
            emu._code_hooks[0x403650] = emu._ret_value(direction, 0)
            try:
                emu.call(0x485D50, (animation, 0xFFFFFFFF, 0xFFFFFFFF), ecx=v)
            finally:
                del emu._code_hooks[0x403650]
            got = (emu.r32(v + 0x13588), emu.r32(v + 0x13560), emu.r32(v + 0x13580))
            want = pp.view_pose(pp.HouseView(pose=pose, direction=direction, animation=animation))
            if animation == 4:                        # no pose of its own: the game leaves -1 (never played)
                assert got == (4, -1, want[1]) and want[0] == pose
            else:
                assert got == (animation, *want), (animation, pose, direction)


def test_the_carried_numbers_are_the_games(vanilla):
    """Read from the exe: every carry step (0x48CE70) and every start of a carry (0x486A10) takes its number from
    a push of a constant, a rand(n) + c, the grocery picker 0x47C1F0, or what was dropped on (0x413420); together
    they cover exactly the carrying.png pictures the catalog says the game shows."""
    import pefile
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    image = bytes(pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True).get_memory_mapped_image())
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    text, at = [], 0x401000
    while at < 0x4B1B59:                               # capstone stops at a byte it cannot read: step over it
        before = len(text)
        for ins in md.disasm(image[at - 0x400000:0xB1B59], at):
            text.append(ins)
            at = ins.address + ins.size
        if len(text) == before:
            at += 1
    groceries = {int(i.op_str.split(", ")[1], 0) for i in md.disasm(image[0x7C1F0:0x7C37D], 0x47C1F0)
                 if i.mnemonic == "mov" and i.op_str.startswith("esi, 0x") or i.op_str in ("esi, 8", "esi, 9")}
    found, unread = set(groceries), []
    for k, ins in enumerate(text):
        if ins.mnemonic != "call" or ins.op_str not in ("0x48ce70", "0x486a10"):
            continue
        j = k - 1
        while text[j].mnemonic not in ("push", "call") or (text[j].mnemonic == "call" and text[j].op_str == "0x403650"):
            j -= 1
        push = text[j]
        if push.mnemonic == "call":                     # the push sits before a jump into this call
            unread.append(ins.address)
            continue
        arg = push.op_str
        if arg.lstrip("-").startswith("0x") or arg.lstrip("-").isdigit():
            found.add(int(arg, 0))
            continue
        before = text[j - 4:j]
        if [b.mnemonic for b in before] == ["push", "call", "add", "add"] and before[1].op_str == "0x403650":
            n, c = int(before[0].op_str, 0), int(before[3].op_str.split(", ")[1], 0)
            found |= set(range(c, c + n))
        elif any(b.mnemonic == "call" and b.op_str == "0x47c1f0" for b in text[j - 3:j]):
            pass                                          # the groceries, read above
        else:
            unread.append(ins.address)
    # the push before a jump (0x455C00 -> 0x455EC9: push 0x16 at 0x455BFC); the dropped-on numbers
    assert struct.unpack_from("<B", image, 0x55BFD)[0] == 0x16
    found.add(0x16)
    found |= {0x32, 0x33}                                 # 0x442B1D / 0x442AD1: the TV remote, the shed door
    assert image[0x42B1D:0x42B22] == b"\xB8\x32\x00\x00\x00" and image[0x42AD1:0x42AD6] == b"\xB8\x33\x00\x00\x00"
    carrying = {v for v in found if 0 <= v < 78}
    assert carrying - {pp.BUNDLE} == set(pp.CARRIED_BY), sorted(carrying ^ set(pp.CARRIED_BY))
    # The rest pass a number on from a register: the drop (0x41359B), the pick-ups of a collectible or mess
    # (behaviours 0x34..0x38 and 0x132: 0x4E..0x90), the jump into 0x455EC9 (above), and the plan's own step.
    assert set(unread) == READ_ELSEWHERE, sorted(hex(a) for a in set(unread) ^ READ_ELSEWHERE)
    # a number above 0x90 is refused (0x4135C5 cmp ebp, 0x90; ja); a cobweb is always 0x8C (0x414ED4)
    assert image[0x135C5:0x135CB] == b"\x81\xFD\x90\x00\x00\x00" and image[0x135CB] == 0x77
    assert image[0x14ED4:0x14EDA] == b"\xC7\x07\x8C\x00\x00\x00"
    # the animation table 0x4FBE90 (id, pose, direction) and the lowering 0x48A105..0x48A138
    table = [struct.unpack_from("<3i", image, 0xFBE90 + 12 * k) for k in range(24)]
    assert [t[0] for t in table] == list(range(24)) and [t[1:] for t in table] == list(pp.ANIMATIONS)
    lowered = {}
    for ins in md.disasm(image[0x8A10B:0x8A13D], 0x48A10B):
        if ins.mnemonic == "cmp":
            pending = int(ins.op_str.split(", ")[1], 0)
            lowered[pending] = 10
    lowered[0x17] = 20                                    # the last compare: jne past the +0x14
    assert lowered == pp.CARRY_LOWER
    assert image[0x8A131:0x8A136] == b"\x83\x44\x24\x14\x14" and image[0x8A138:0x8A13D] == b"\x83\x44\x24\x14\x0A"


READ_ELSEWHERE = {0x41359B, 0x455EC9, 0x45E43C, 0x45E567, 0x45E65C, 0x45E77C, 0x45E859, 0x479957, 0x4799EB,
                  0x48C528, 0x48E465}


def test_the_store_and_tray_outfits_match_the_game(vanilla):
    """The store's and the tool tray's outfit draw 0x496A10, run on the vanilla game for both kinds of every
    outfit item (the store's 18 / 19 and the tray's 64 / 65) and every picture."""
    import picture_emu
    emu = picture_emu.Emu(vanilla)
    art = pp.Art(vanilla)
    inventory = 0x8957A0
    for item, field, female in ((64, 0x110, False), (65, 0x114, True), (18, 0x108, False), (19, 0x10C, True)):
        for picture in range(50):
            emu.w32(inventory + field, picture)
            emu.blits = []
            emu.call(0x496A10, (500, 400, item, 0, 0, 0), ecx=inventory)
            got = [(b["file"], b["rect"], b["x"] - 500, b["y"] - 400, b["scale"], b["alpha"]) for b in emu.blits]
            assert got == _mine(pp.outfit_plan(art, female, picture)), (item, picture)


@pytest.fixture(scope="module")
def pillow():
    return pytest.importorskip("PIL.Image")


def test_children_and_ghosts_match_the_games_blitter(vanilla, pillow):
    """The game's 0x404C30 draws them over three screen colours; the renderer's layers, blended by the
    game's rule (c a + d (255 - a) + 127) >> 8, must give the same screen to the last pixel."""
    import picture_emu
    sheets = {}

    def pixels(name):
        if name not in sheets:
            im = pillow.open(vanilla / "Images" / name).convert("RGBA")
            sheets[name] = (im.width, im.height, im.tobytes())
        return sheets[name]
    emu = picture_emu.Emu(vanilla, pixels=pixels)
    art = pp.Art(vanilla)
    cases = [(True, 0, 1, 2, 46, False), (False, 37, 20, 30, 3, False), (True, 140, 44, 12, 40, False),
             (False, 279, 49, 49, 50, False), (True, 600, 17, 33, 46, True), (False, 100, 9, 9, 12, True),
             ]
    scenes = []
    for female, age, head, body, pose, ghost in cases:
        _got, (fx, fy) = _game_house(emu, female, age, head, body, pose, 1, 5, ghost, -1, 0)
        plan = pp.house_plan(art, pp.Person(female, age, head, body), pp.HouseView(pose, 1, 5, True, ghost))
        scenes.append(((female, age, pose, ghost), emu.draw_house(1.0), plan, fx, fy))
    for female, picture in ((False, 3), (True, 41)):                # the store's outfits, at 70%
        emu.w32(0x8957A0 + (0x10C if female else 0x108), picture)
        emu.blits = []
        emu.call(0x496A10, (2000, 2000, 19 if female else 18, 0, 0, 0), ecx=0x8957A0)
        scenes.append((("outfit", female, picture), list(emu.blits), pp.outfit_plan(art, female, picture), 2000, 2000))
    for what, blits, plan, fx, fy in scenes:
        origin, size = (fx - 120, fy - 180), 240
        for colour in ((0, 0, 0), (255, 255, 255), (40, 160, 90)):
            game = emu.blit_onto(colour, blits, size, size, origin)
            screen = bytearray(bytes(colour) * (size * size))
            for d in plan:
                piece, touched = pi.game_layer_and_touched(art.image(d.file), d.rect, d.scale, d.alpha)
                for j in range(piece.height):
                    for i in range(piece.width):
                        k = j * piece.width + i
                        if touched[k]:
                            r, g, b, a = piece.data[k * 4:k * 4 + 4]
                            at = ((d.y + fy - origin[1] + j) * size + d.x + fx - origin[0] + i) * 3
                            for c, v in enumerate((r, g, b)):
                                screen[at + c] = (v * a + screen[at + c] * (255 - a) + 0x7F) >> 8
            assert bytes(screen) == game, (what, colour)


def test_every_carried_png_matches_a_pillow_composite(vanilla, pillow):
    """Every carried picture, on an adult standing and lying (animation 24, drawn 20 pixels lower) and with babies
    on the way: the cells the emulated game drew, cut and composited by Pillow at its places (all at scale 1 and
    alpha 1: SDL's own alpha blit), equal the Picture Maker's picture to the last pixel."""
    import picture_emu
    emu = picture_emu.Emu(vanilla)
    art = pp.Art(vanilla)
    sheets = {}

    def sheet(name):
        if name not in sheets:
            sheets[name] = pillow.open(vanilla / "Images" / name).convert("RGBA")
        return sheets[name]
    values = [t.value for t in pp.carried_things() if t.value != pp.UNSHOWN_BUNDLE]
    for k, value in enumerate(values):
        animation = (pp.NO_ANIMATION, 23)[k % 2]
        babies = k % 4
        view = pp.HouseView(46, k % 4, 5, True, False, value, animation)
        pose, direction = pp.view_pose(view)
        got, _feet = _game_house(emu, True, 600, k % 50, (k * 3) % 50, pose, direction, 5, False, value, babies,
                                 animation)
        assert all(g[4] == 1.0 and g[5] == 1.0 for g in got)
        left, top = min(g[2] for g in got), min(g[3] for g in got)
        right = max(g[2] + g[1][2] - g[1][0] for g in got)
        bottom = max(g[3] + g[1][3] - g[1][1] for g in got)
        reference = pillow.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        for file, rect, x, y, _scale, _alpha in got:
            layer = pillow.new("RGBA", reference.size, (0, 0, 0, 0))
            layer.paste(sheet(file).crop(rect), (x - left, y - top))
            reference = pillow.alpha_composite(reference, layer)
        mine = pp.render_plan(art, pp.house_plan(art, pp.Person(True, 600, k % 50, (k * 3) % 50, babies), view))
        box = reference.getbbox()
        assert mine.cropped(0).to_png() == pi.Image(box[2] - box[0], box[3] - box[1],
                                                    reference.crop(box).tobytes()).to_png(), value


def test_an_adults_png_matches_a_pillow_composite(vanilla, pillow, tmp_path):
    """An adult in the house and a portrait: the cells, cut and composited by Pillow at the places the emulated
    game drew them (scale 1 and alpha 1 is SDL's own alpha blit of the cell), equal the saved PNG exactly."""
    import picture_emu
    emu = picture_emu.Emu(vanilla)
    art = pp.Art(vanilla)
    for kind, female, age, head, body, extra in (("house", True, 600, 3, 7, 46), ("house", False, 950, 30, 30, 21),
                                                  ("portrait", True, 500, 11, 12, 1)):
        if kind == "house":
            got, _feet = _game_house(emu, female, age, head, body, extra, 1, 5, False, -1, 0)
            spec = {"view": "house", "female": female, "age": age, "head": head, "body": body, "pose": extra,
                    "direction": 1}
        else:
            emu.villager(female=female, age=age, head=head, body=body, pose=0)
            got = [(b["file"], b["rect"], b["x"] - 2000, b["y"] - 2000, b["scale"], b["alpha"])
                   for b in emu.draw_portrait(2000, 2000, extra)]
            spec = {"view": "portrait", "female": female, "age": age, "head": head, "body": body, "expression": extra}
        assert all(g[4] == 1.0 and g[5] == 1.0 for g in got)
        left = min(g[2] for g in got)
        top = min(g[3] for g in got)
        right = max(g[2] + g[1][2] - g[1][0] for g in got)
        bottom = max(g[3] + g[1][3] - g[1][1] for g in got)
        reference = pillow.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        for file, rect, x, y, _scale, _alpha in got:
            cell = pillow.open(vanilla / "Images" / file).convert("RGBA").crop(rect)
            layer = pillow.new("RGBA", reference.size, (0, 0, 0, 0))
            layer.paste(cell, (x - left, y - top))
            reference = pillow.alpha_composite(reference, layer)
        box = reference.getbbox()
        m = pi.MARGIN
        expected = pillow.new("RGBA", (box[2] - box[0] + 2 * m, box[3] - box[1] + 2 * m), (0, 0, 0, 0))
        expected.paste(reference.crop(box), (m, m))
        path = pi.save_png(pp.render(art, spec), tmp_path / f"{kind}.png")
        saved = pillow.open(path)
        assert saved.mode == "RGBA" and saved.size == expected.size
        assert saved.tobytes() == expected.tobytes(), (kind, female, age)
