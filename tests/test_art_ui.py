"""The Picture Maker's interface pictures (patcher/vf1_art_ui.py).

Everywhere: a synthetic game folder (small sheets) checks the catalogue's keys, categories, the cells and the
nine-tile dialog arithmetic, a folder with missing pictures, and that every picture renders.

With VF1_VANILLA_DIR (a copy of the vanilla game; only read): tests/ui_emu.py runs the game's own drawing code
in Unicorn -- the button draw 0x4011D0, the check box draw 0x40BC40, the dialog backdrop 0x40DF90 / 0x40DDD0, the
Options dialog 0x41D9C0, the achievements screen 0x435360 and rows, the family tree's scroll bar, the tip
arrows, the mouse pointer, the e-mail animations, the store icons, the backgrounds' own call sites -- and every
picture's draws (file, cell, place, scale, alpha) must equal the game's.  A scan of the whole .text checks the
image numbers the picture loaders are ever asked for: every "unused" picture is never asked for.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest
import vf1_art_ui as ui
import vf1_game_art as ga
import vf1_picture_image as pi

# ------------------------------------------------------------------ a synthetic game folder
SIZES = {}          # name -> (w, h) of the synthetic sheet


def _names() -> dict:
    """Every picture the module can name, with a small size that cuts into its cells."""
    out = {}
    for image, (name, cols, rows, files) in ga.TABLE.items():
        if files != 1 or image not in ui.USAGE and image not in ui.BUTTONS:
            continue
        cols, rows = cols or 1, rows or 1
        out[name] = (cols * 4, rows * 3)
    for name in ui.GRIDS.values():
        out[name] = (36, 4)                            # nine 4 x 4 tiles
    out.update({"familytree_scrollknob_mid.png": (5, 400), "familytree_scrollknob_top.png": (5, 3),
                "familytree_scrollknob_btm.png": (5, 2), "SPLASH_BG.jpg": (8, 6), "help1.jpg": (8, 6),
                "credits.jpg": (8, 6), "collection_photo-glass.png": (6, 5), "DRM/virtualfamilies_drm.jpg": (6, 4)})
    for missing in ("overview_bg.jpg", "small_logo.png", "collection_photo-glass.jpg"):
        out.pop(missing, None)
    return out


def _sheet(w: int, h: int, seed: int) -> pi.Image:
    img = pi.Image(w, h)
    for y in range(h):
        for x in range(w):
            img.data[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(((seed * 37) % 256, x * 9 % 256, y * 11 % 256, 255))
    return img


@pytest.fixture(scope="module")
def fake(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("game") / "Virtual Families"
    (folder / "Images" / "DRM").mkdir(parents=True)
    for k, (name, (w, h)) in enumerate(_names().items()):
        path = folder / "Images" / name
        path.write_bytes(_sheet(w, h, k).to_png())      # a PNG under any name: GameFiles decodes by content
    return folder


def test_synthetic_catalogue(fake):
    files = ga.GameFiles(fake)
    arts = ui.arts(files)
    keys = [a.key for a in arts]
    assert len(keys) == len(set(keys)) and all(k.startswith("ui/") for k in keys)
    tops = {a.category.split("/")[0] for a in arts}
    assert tops <= set(ga.CATEGORY_ORDER)
    assert tops == {"Buttons and controls", "Dialogs and panels", "Icons and cursors", "Screens and backgrounds"}
    for art in arts:
        assert art.label and art.why and "might" not in art.why and "probably" not in art.why
        for layer in ga.resolve(files, art).layers:
            w, h = files.size(layer.file)
            x0, y0, x1, y1 = layer.rect
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h, (art.key, layer)
        ga.draw(files, art)                             # every picture renders
    by_key = {a.key: a for a in arts}
    # a button's three states are its three cells
    for state, slug, _w in ui.STATES:
        layer = by_key[f"ui/buttons/25/{slug}"].layers[0]
        assert layer.file == "btn_green.png" and layer.rect == (state * 4, 0, state * 4 + 4, 3)
    # unused pictures are marked, missing files leave the picture empty
    assert not by_key["ui/buttons/29/normal"].used and not by_key["ui/screens/3c"].used
    assert by_key["ui/screens/3c"].layers == () and by_key["ui/logos/small"].layers == ()
    assert by_key["ui/screens/50"].layers[0].file == "collection_photo-glass.png"
    # the dialog backdrop: 4 x 4 tiles, a 10 x 3 dialog -> max(2, (4 + 12 + 9) // 4) = 6 columns,
    # max(2, (4 + 18 + 2) // 4) = 6 rows; corners 8, 0, 5, 6, edges 1, 3, 2, 4, the middle 7
    tiles = ui.tiled_backdrop(files, 0x2D, 10, 3)
    assert len(tiles) == 36
    cells = [[t.rect[0] // 4 for t in tiles[r * 6:(r + 1) * 6]] for r in range(6)]
    assert cells[0] == [8, 1, 1, 1, 1, 0] and cells[5] == [5, 4, 4, 4, 4, 6]
    assert all(row == [3, 7, 7, 7, 7, 2] for row in cells[1:5])
    assert [(t.x, t.y) for t in tiles[:2]] == [(0, 0), (4, 0)] and (tiles[-1].x, tiles[-1].y) == (20, 20)
    # a 1 x 1 dialog: (4 + 12) // 4 = 4 columns, (4 + 18) // 4 = 5 rows (the overlaps alone need them)
    assert len(ui.tiled_backdrop(files, 0x2C, 1, 1)) == 20
    # every catalogue picture of this area is noted per sheet
    for image in list(ui.BUTTONS) + [0x29, 0x2C, 0x2D, 0x2E, 0x31, 0x34, 0x35, 0x36, 0x37, 0xBA, 0xCD]:
        assert image in ui.USAGE
    assert ui.CELL_LABELS[(0x2D, 8)] == "Top left corner" and (0x29, 1) in ui.CELL_UNUSED


def test_synthetic_empty_folder(tmp_path):
    (tmp_path / "Images").mkdir()
    arts = ui.arts(ga.GameFiles(tmp_path))            # nothing to draw, nothing raised
    assert all(not a.layers for a in arts)


# ------------------------------------------------------------------ the vanilla game
@pytest.fixture(scope="module")
def vanilla() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    pytest.importorskip("unicorn")
    pytest.importorskip("pefile")
    return Path(value)


@pytest.fixture(scope="module")
def emu(vanilla):
    import ui_emu
    return ui_emu.UiEmu(vanilla)


@pytest.fixture(scope="module")
def catalogue(vanilla):
    files = ga.GameFiles(vanilla)
    out = {}
    for art in ui.arts(files):
        if any(str(getattr(layer, "file", "")).lower().endswith(".gif") for layer in art.layers):
            continue                     # the trial screen's GIF: no draw of it to compare (it is unused)
        out[art.key] = ga.resolve(files, art)
    return files, out


def _rel(draws) -> list:
    """Draws as (file, rect, place relative to the first, scale, alpha)."""
    draws = [d for d in draws if d.get("kind", "blit") == "blit"]
    if not draws:
        return []
    x0, y0 = draws[0]["x"], draws[0]["y"]
    return [(d["file"].lower(), tuple(d["rect"]), d["x"] - x0, d["y"] - y0, pi.f32(d["scale"]), pi.f32(d["alpha"]))
            for d in draws]


def _layers(art) -> list:
    return _rel([{"file": l.file, "rect": l.rect, "x": l.x, "y": l.y, "scale": l.scale, "alpha": l.alpha}
                 for l in art.layers])


def _only(draws, *names) -> list:
    names = {n.lower() for n in names}
    return [d for d in draws if d.get("kind") == "blit" and d["file"].lower() in names]


def _hook(emu, address, fn):
    import ui_emu
    emu.hooks[address] = fn
    emu.u.hook_add(ui_emu.UC_HOOK_CODE, emu._code, begin=address, end=address)


def test_buttons(emu, catalogue):
    _files, arts = catalogue
    for image in list(ui.BUTTONS) + list(ui.UNUSED_BUTTONS):
        for state, slug, _w in ui.STATES:
            draws = emu.button(image, state)
            assert [d["kind"] for d in draws] == ["blit"]          # never the tinted path 0x408EC0, never a fill
            assert _rel(draws) == _layers(arts[f"ui/buttons/{image:02x}/{slug}"]), (hex(image), state)


def test_check_boxes(emu, catalogue):
    _files, arts = catalogue
    for image, slug in ((0x34, "checkbox"), (0x31, "radio")):
        for cell in (0, 1):
            for state in (0, 1, 2):
                assert _rel(emu.toggle(image, bool(cell), state)) == _layers(arts[f"ui/toggles/{slug}/{cell}"])


def _options(emu, volume: float = 1.0, speed: int = 10, reverse: int = 0) -> list:
    dlg = emu.alloc(0x100)
    emu.wf(emu.gs + 0x1B174, volume)
    emu.wf(emu.gs + 0x1B178, volume)
    emu.run(0x41D566, 0x41D5AE, regs={"esi": dlg, "ebp": emu.gs})         # the constructor's slider places
    for field, image in ((0x80, 0x34), (0x88, 0x32), (0x8C, 0x33), (0x90, 0x36), (0x94, 0x37)):
        emu.w32(dlg + field, emu.grid(image))
    for field, value in ((0x70, emu.gs), (0x74, 1000), (0x78, 1320), (0x7C, 1000), (0x98, emu.window),
                         (0xA4, emu.strings)):
        emu.w32(dlg + field, value)
    emu.w32(emu.gs + 0x1B180, speed)
    emu.w8(emu.gs + 0x1B184, reverse)
    emu.take()
    emu.call(0x41D9C0, (), ecx=dlg)
    return emu.take()


def test_options_choices_and_sliders(emu, catalogue):
    _files, arts = catalogue
    # the day / night row (y + 0x172): the flag picks the first choice
    for reverse, picked in ((1, 0), (0, 1)):
        draws = [d for d in _only(_options(emu, reverse=reverse), "radioblank.png", "radioselected.png")
                 if d["y"] == 1000 + 0x172]
        assert _rel(draws) == _layers(arts[f"ui/toggles/choice/{picked}"])
    # the pause row (y + 0x127): paused (speed >= 999) picks the first, speed 10 the second
    for speed, picked in ((999, 0), (10, 1)):
        draws = [d for d in _only(_options(emu, speed=speed), "radioblank.png", "radioselected.png")
                 if d["y"] == 1000 + 0x127]
        assert _rel(draws) == _layers(arts[f"ui/toggles/choice/{picked}"])
    for volume in (0.0, 0.5, 1.0):
        draws = _only(_options(emu, volume=volume), "WideSlider2.png", "sliderhandle.png")
        assert len(draws) == 4                                     # sound and music
        art = arts[f"ui/sliders/volume/{int(volume * 100)}"]
        assert _rel(draws[:2]) == _layers(art) and _rel(draws[2:]) == _layers(art)
        assert draws[0]["x"] == 1000 + 0xF0


def test_achievements_screen(emu, catalogue):
    _files, arts = catalogue
    scene = emu.alloc(0x100)
    emu.run(0x435201, 0x4352B5, regs={"esi": scene, "ebx": 0})              # the constructor's scroll bar
    _hook(emu, 0x412D00, emu._ret(lambda: 0, 0x14))                          # the rows: tested below
    try:
        emu.take()
        emu.call(0x435360, (), ecx=scene)
        draws = emu.take()
    finally:
        del emu.hooks[0x412D00]
    assert _rel(draws[:1]) == _layers(arts["ui/screens/3d"]) and (draws[0]["x"], draws[0]["y"]) == (0, 0)
    bar = _only(draws, "verticalslidertrack.png", "familytree_scrollknob_top.png", "familytree_scrollknob_mid.png",
                "familytree_scrollknob_btm.png")
    assert _rel(bar) == _layers(arts["ui/sliders/achievements"])
    assert (bar[0]["x"], bar[0]["y"]) == (arts["ui/sliders/achievements"].layers[0].x,
                                          arts["ui/sliders/achievements"].layers[0].y)
    bottom = _only(draws, "main_no-comm.png")
    assert _rel(bottom) == _layers(arts["ui/panels/cd"]) and (bottom[0]["x"], bottom[0]["y"]) == (0, 519)


def test_achievement_rows_and_popup(emu, catalogue):
    _files, arts = catalogue
    rows = 0x5008D8
    for earned, key in ((0, "box"), (1, "box-earned")):
        emu.take()
        emu.run(0x412DE5, 0x412E23, regs={"edi": rows},
                stack={0xCC: 0, 0xC4: 1000, 0xC0: 1000, 0x18: earned << 24, 0x2C: emu.mgr})
        draws = emu.take()
        assert _rel(draws) == _layers(arts[f"ui/panels/achievement-{key}"]) and draws[0]["x"] == 1008
    emu.w32(rows + 0x658, 0)
    emu.run(0x412D68, 0x412DBD, regs={"edi": rows, "ebx": emu.mgr}, stack={0xCC: 1})
    emu.take()
    emu.run(0x412E32, 0x412E5D, regs={"edi": rows, "esi": 1000, "ebp": 1000}, stack={0xD0: struct.unpack(
        "<I", struct.pack("<f", 1.0))[0]})
    assert _rel(emu.take()) == _layers(arts["ui/dialogs/achievement-popup"])


def test_family_tree_scroll_bar(emu, catalogue):
    _files, arts = catalogue
    for overflow in (100, 1000):
        scene = emu.alloc(0x100)
        for field, value in ((0x18, 0x2F3), (0x1C, 0xA7), (0x20, 0x308), (0x24, 0x22A), (0x54, overflow)):
            emu.w32(scene + field, value)
        emu.run(0x439318, 0x439366, regs={"esi": scene, "ebx": 0})
        emu.take()
        emu.run(0x43A2AB, 0x43A39F, regs={"esi": scene, "ebx": emu.mgr}, stack={0x10: emu.window})
        draws = emu.take()
        art = arts[f"ui/sliders/family-tree/{overflow}"]
        assert _rel(draws[:-1]) == _layers(art)
        assert (draws[0]["x"], draws[0]["y"]) == (art.layers[0].x, art.layers[0].y)
        assert _rel(draws[-1:]) == _layers(arts["ui/panels/cd"]) and draws[-1]["y"] == 519


def test_dialog_backdrops(emu, catalogue):
    _files, arts = catalogue
    for key, _label, image, width, height, alpha, _where in ui.DIALOGS:
        if key == "achievement-popup":
            continue                                               # its own code: test_achievement_rows_and_popup
        draws = emu.backdrop(image, width, height, alpha=alpha)
        assert _rel(draws) == _layers(arts[f"ui/dialogs/{key}"]), key


def test_tip_arrows(emu, catalogue):
    _files, arts = catalogue
    for image, direction in ((0x49, 1), (0x4A, 2), (0x4B, 3), (0x4C, 4)):
        art = arts[f"ui/arrows/{image:02x}"]
        places = set()
        for phase in (0.0, 30.0, 90.0, 150.0):
            tip = emu.alloc(0x100)
            for field, value in ((0x80, emu.grid(image)), (0x84, 1000), (0x88, 1000), (0x8C, 25), (0x7C, direction),
                                 (0x6C, emu.window)):
                emu.w32(tip + field, value)
            emu.wd(tip + 0xA0, phase)
            emu.take()
            emu.run(0x41F23A, 0x41F2E8, regs={"esi": tip})
            draws = emu.take()
            assert _rel(draws) == _layers(art)
            places.add((draws[0]["x"] - 1000, draws[0]["y"] - 1000))
        # it only moves along its own direction, never more than a quarter of its size
        assert all((dx == 0) if direction <= 2 else (dy == 0) for dx, dy in places)
        assert all(abs(dx) <= 25 and abs(dy) <= 25 for dx, dy in places) and len(places) > 1


def test_mouse_pointers_and_icons(emu, catalogue):
    _files, arts = catalogue
    for image in (1, 2):
        emu.w32(emu.impl + 0x24, emu.grid(image))
        emu.w8(emu.impl + 0x1F, 1)
        emu.w8(emu.impl + 0x20, 0)
        emu.w32(emu.impl + 0x28, emu.r32(0x4F11FC))
        emu.w32(emu.impl + 0x2C, emu.r32(0x4F1200))
        emu.take()
        emu.run(0x409358, 0x40937B, regs={"esi": emu.impl, "ecx": 1000, "edx": 1000})
        draws = emu.take()
        layer = arts[f"ui/cursors/{image:02x}"].layers[0]
        assert _rel(draws) == _layers(arts[f"ui/cursors/{image:02x}"])
        assert (draws[0]["x"] - 1000, draws[0]["y"] - 1000) == (layer.x, layer.y)    # the hot spot
    emu.take()
    emu.call(0x44EC30, (emu.grid(0x3B), 1000, 1000, struct.unpack("<I", struct.pack("<f", 1.0))[0]),
             ecx=0x56B800)
    assert _rel(emu.take()) == _layers(arts["ui/icons/focus"])
    for image, cx, cy in ((0xD3, 500, 500), (0xD1, 640, 300)):
        assert _rel(emu.draw_centred(image, cx, cy)) == _layers(arts[f"ui/icons/{image:02x}"])


def test_email_animations(emu, catalogue):
    _files, arts = catalogue
    anims = 0x503B68
    emu.call(0x4217B0, (), ecx=anims)                            # the animation table's pictures
    for k in range(0x200):
        emu.w32(anims + 4 + k * 0x44, 0xFFFFFFFF)                 # every slot free, as 0x421839 looks for
    for args in ((0x20, 0x2EE, 0x1E, 4, 1, -1, 0xA, 1), (0x1F, 0x457, 0x4B6, 4, 1, -1, 7, 1),
                 (0x1F, 0x3A1, 0x49E, 4, 1, -1, 7, 1)):            # 0x4450D1..0x44512A, ebp = 1 (0x444DCC)
        slot = emu.call(0x421810, args, ecx=anims)
        image = 0x6D if args[0] == 0x20 else 0x6C
        for frame in (0, 1):
            emu.w32(anims + 4 + slot * 0x44 + 0x14, frame)
            emu.take()
            emu.call(0x421A30, (slot,), ecx=anims)
            draws = emu.take()
            assert _rel(draws) == _layers(arts[f"ui/icons/email-{image:02x}/{frame}"])
            w = draws[0]["rect"][2] - draws[0]["rect"][0]
            assert draws[0]["x"] == args[1] - w // 2                # centred on its place
        emu.call(0x421940, (slot,), ecx=anims)                    # the slot is let go


# the backgrounds' own call sites: (art, first instruction, the instruction after the call, registers)
SITES = (
    ("ui/screens/3f", 0x4406D9, 0x4406F0, "eax"), ("ui/logos/ldw", 0x44071D, 0x440735, "esi"),
    ("ui/screens/47", 0x447425, 0x44743A, "eax"), ("ui/screens/4f", 0x43729B, 0x4372B2, "eax"),
    ("ui/screens/51", 0x4380F8, 0x43810D, "eax"), ("ui/screens/57", 0x44B895, 0x44B8AA, "eax"),
    ("ui/screens/58", 0x448C56, 0x448C6B, "ebx"), ("ui/screens/5a", 0x43632F, 0x436344, "edi"),
    ("ui/screens/c0", 0x43A1C7, 0x43A1E1, "eax"), ("ui/screens/46", 0x4400F7, 0x44010C, "edi"),
)


def test_backgrounds_at_their_call_sites(emu, catalogue):
    _files, arts = catalogue
    for key, start, end, reg in SITES:
        emu.take()
        emu.run(start, end, regs={reg: emu.mgr})
        draws = emu.take()
        art = arts[key]
        assert _rel(draws) == _layers(art), key
        assert (draws[0]["x"], draws[0]["y"]) == (art.layers[0].x, art.layers[0].y), key
    # the house screen's background, from the screen's bottom edge (0x440A30..0x440A5B)
    scene = emu.alloc(0x100)
    emu.w32(scene + 0xA0, emu.grid(0x45))
    emu.w32(scene + 0x7C, 0)
    emu.w32(scene + 0x84, 600)
    emu.w32(scene + 0x10, emu.window)
    emu.take()
    emu.run(0x440A30, 0x440A5B, regs={"ecx": scene})
    assert _rel(emu.take()) == _layers(arts["ui/screens/45"])
    # the splash screen: SPLASH_BG.JPG loaded by name, the static splash (+0x19) on picture 0
    scene = emu.alloc(0x40)
    for field, value in ((0x2C, 1), (0x14, 0), (0x1C, emu.picture("SPLASH_BG.jpg")), (0xC, emu.window)):
        emu.w32(scene + field, value)
    emu.w8(scene + 0x19, 1)
    emu.take()
    emu.call(0x448860, (), ecx=scene)
    draws = emu.take()
    assert _rel(draws) == _layers(arts["ui/screens/splash"]) and (draws[0]["x"], draws[0]["y"]) == (0, 0)


def test_picture_numbers_the_loaders_are_asked_for(vanilla):
    """Every call to a picture loader or draw-by-number in .text, with the image number pushed for it: the used
    pictures are asked for, the unused ones never."""
    capstone = pytest.importorskip("capstone")
    import pefile
    pe = pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True)
    image = pe.get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    loaders = {0x44F5A0, 0x44F860, 0x44F590, 0x44F960, 0x44F880, 0x44FA70, 0x44F870}
    asked: set = set()
    recent: list = []
    at = 0x401000
    while at < 0x4B2000:
        for ins in md.disasm(image[at - 0x400000:0x4B2000 - 0x400000], at):
            at = ins.address + ins.size
            if ins.mnemonic == "call" and ins.op_str.startswith("0x") and int(ins.op_str, 16) in loaders:
                for prev in reversed(recent):
                    if prev.mnemonic == "push":
                        op = prev.op_str
                        if op.startswith("0x") or op.isdigit():
                            asked.add(int(op, 0))
                        else:
                            for movs in reversed(recent):
                                if movs.mnemonic == "mov" and movs.op_str.startswith(op + ", 0x"):
                                    asked.add(int(movs.op_str.split(", ")[1], 16))
                                    break
                        break
                recent = []
            else:
                recent = (recent + [ins])[-8:]
        at += 1
        recent = []
    for image_id, (used, _why) in ui.USAGE.items():
        if not used:
            assert image_id not in asked, hex(image_id)
    for image_id in list(ui.BUTTONS) + [0x32, 0x33, 0x34, 0x36, 0x37, 0x3D, 0x3F, 0x40, 0x45, 0x46, 0x47, 0x49,
                                        0x4F, 0x51, 0x57, 0x58, 0x5A, 0xC0, 0xC9, 0xCD, 0xD1, 0xD3]:
        assert image_id in asked, hex(image_id)
