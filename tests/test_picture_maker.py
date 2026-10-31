"""The Picture Maker (patcher/vf1_picture_maker.py, vf1_people_pictures.py, vf1_picture_image.py).

Everywhere: a synthetic game folder (small sheets whose every cell has its own colour, a synthetic
Assets\\animpts.dat) and synthetic saves check the part selection, the life stages, the layer order, every
export size, transparency, the patched and stock looks, a save with no family, and the window.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read): tests/picture_emu.py runs the game's own
drawing code in Unicorn and every draw the renderer plans must equal the game's (file, cell, place, scale,
alpha); the game's own blitter 0x404C30 draws children and ghosts over three colours and the renderer's
pixels must give exactly the same screen; and an adult's PNG must equal, pixel for pixel, the cells
composited by Pillow at the places the emulated game drew them.
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


def _game_house(emu, female, age, head, body, pose, direction, head_turn, ghost, carried, babies):
    emu.villager(female=female, age=age, head=head, body=body, pose=pose, direction=direction, head_turn=head_turn,
                 ghost=ghost, carried=carried, babies=babies)
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
