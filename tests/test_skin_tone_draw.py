"""Skin Tones (native/vf1skin): every draw of a person, in emulation, with the real DLL on the vanilla executable.

The game's own drawing code (the house, the held baby, the portrait, the event pop-up's portrait and the Family Tree,
down to BlitRectWithAlpha 0x404C30) runs on the vanilla executable in Unicorn with the built vf1skin.dll loaded and
installed through its own VF1Skin_Startup (tests/skin_emu.py). The masks are the ones the patcher ships
(patcher/payload/SkinMasks); the sheets are the vanilla Images folder's.

Needs, or the test skips (nothing of the game or of the workbench is in the repository):
  VF1_VANILLA_DIR      a copy of the vanilla game (only read);
  VF1_SKIN_WORKBENCH   the Skin Tones workbench's VF1 folder (only read): its vfskin.py is the approved recolour the
                       DLL's pixels are held to, and its layers\\<sheet>\\Skin mask.png the masks the shipped ones are
                       made from.
  VF1_SKIN_PICTURES    (optional) a folder: a toned family drawn by the game's own blitter is saved there.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
TONE = 8                     # Deep brown
HEAD, BODY = 7, 12
SHEETS = ("male_heads00.png", "male_heads10.png", "male_bodies00.png", "male_actions00.png", "male_sit00.png",
          "female_heads00.png", "female_heads10.png", "female_bodies00.png", "female_actions00.png", "female_sit00.png",
          "bigheads00.png", "bigheads10.png", "highrez_bodies_final2.png", "carrying.png")
TOOLCHAIN = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    if not TOOLCHAIN.is_file():
        pytest.skip("needs the Visual Studio 18 32-bit toolchain")
    out = tmp_path_factory.mktemp("skin_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_skin.bat")], capture_output=True, text=True,
                       env=dict(os.environ, VF1_BUILD_DIR=str(out)))
    assert (out / "vf1skin.dll").is_file(), r.stdout + r.stderr
    return out / "vf1skin.dll"


@pytest.fixture(scope="module")
def workbench() -> Path:
    value = os.environ.get("VF1_SKIN_WORKBENCH")
    if not value or not (Path(value) / "vfskin.py").is_file():
        pytest.skip("set VF1_SKIN_WORKBENCH to the Skin Tones workbench's VF1 folder")
    return Path(value)


@pytest.fixture(scope="module")
def art(vanilla_dir, workbench):
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    image = pytest.importorskip("PIL.Image")
    image.MAX_IMAGE_PIXELS = None
    sys.path.insert(0, str(workbench))
    import vfskin
    import vf1_skin_masks as M

    sheets, masks = {}, {}

    def sheet(name):
        if name not in sheets:
            sheets[name] = np.array(image.open(vanilla_dir / "Images" / name).convert("RGBA"))
        return sheets[name]

    def mask(name):
        if name not in masks:
            w, h, rows = M.read_mask_bits((ROOT / "patcher" / "payload" / "SkinMasks" / name).read_bytes())
            masks[name] = np.unpackbits(np.frombuffer(b"".join(rows), np.uint8).reshape(h, -1), axis=1)[:, :w] == 1
        return masks[name]
    return np, vfskin, sheet, mask


def _emu(vanilla_dir, built, art, setting=1):
    import skin_emu

    np, _vfskin, sheet, _mask = art

    def pixels(name):
        a = sheet(name)
        return a.shape[1], a.shape[0], a.tobytes()
    return skin_emu.SkinEmu(vanilla_dir, built, pixels=pixels, wanted=SHEETS + ("peep_shadow1.png",), setting=setting)


def _key(b):
    return b["x"], b["y"], b["alpha"], b["scale"], b["centre"], b["rect"][0], b["rect"][2]


def _check_row(art, was, now, tone=TONE):
    """`now` draws a kept copy of `was`'s row with the skin in `tone`: everything not skin, and all alpha, the game's
    own; the skin the approved recolour to one colour level."""
    np, vfskin, sheet, mask = art
    name = was["file"]
    a, m = sheet(name), mask(name)
    top, bottom = was["rect"][1], was["rect"][3]
    w, h, data = now["emu"].surface_pixels(now["surface"])
    cell = h
    row = top // cell
    assert now["rect"] == (was["rect"][0], top - row * cell, was["rect"][2], bottom - row * cell)
    made = np.frombuffer(data, np.uint8).reshape(h, w, 4).astype(int)
    rows = slice(row * cell, (row + 1) * cell)
    want = vfskin.recolour(a, m, vfskin.TONES[tone - 1], "VF1")[rows].astype(int)
    skin = m[rows] & (a[rows][..., 3] > 0)
    assert (made[~skin] == a[rows][~skin]).all()          # every pixel that is not skin: the game's own
    assert (made[..., 3] == a[rows][..., 3]).all()        # alpha never changes
    if skin.any():
        off = np.abs(made[skin][:, :3] - want[skin][:, :3])
        assert off.max() <= 1, off.max()                  # the approved recolour, to one colour level
    return int(skin.sum())


def _compare(emu, art, stock, toned, sheets, tone=TONE):
    """Every blit of `toned` is the same draw as `stock`'s; the ones from `sheets` draw a recoloured row."""
    assert len(toned) == len(stock)
    swapped = []
    for was, now in zip(stock, toned):
        assert _key(was) == _key(now)
        if was["file"] in sheets:
            assert now["surface"] in emu.made, was["file"]
            swapped.append(was["file"])
            _check_row(art, was, dict(now, emu=emu), tone)
        else:
            assert now["file"] == was["file"] and now["rect"] == was["rect"]
    return swapped


# ------------------------------------------------------------------------------------------------ the pins and masks
def test_the_pins_are_the_vanilla_bytes_and_the_header_is_fresh(vanilla_dir):
    import vf1_skin_sites as S
    data = (vanilla_dir / "Virtual Families.exe").read_bytes()
    assert S.render_header(S.validate(data)) == S.HEADER.read_text()


def test_the_shipped_masks_are_shape_only_and_fresh(vanilla_dir, workbench):
    """Each mask is a 1-bit black-and-white picture (no game pixel can be in it), made from the workbench's mask for
    the vanilla sheet it names; the held baby is the only skin of carrying.png."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL.Image")
    import json
    import vf1_skin_masks as M
    files = M.build(workbench, vanilla_dir / "Images")
    for name, data in files.items():
        target = M.HEADER if name == "skin_masks.h" else M.OUT / name
        assert target.read_bytes() == data, f"{name}: run tools/vf1_skin_masks.py --write"
    table = json.loads(files["masks.json"])["masks"]
    assert [t["sheet"] for t in table] == [s[0] for s in M.SHEETS]
    for t in table:
        png = (M.OUT / t["sheet"]).read_bytes()
        assert png[24:29] == bytes([1, 0, 0, 0, 0])              # 1 bit, greyscale, no interlace
        w, h, rows = M.read_mask_bits(png)
        assert (w, h) == (t["width"], t["height"]) and t["skin_pixels"] > 0
    w, h, rows = M.read_mask_bits((M.OUT / "carrying.png").read_bytes())
    cell = w // M.CARRYING_COLUMNS
    for y, row in enumerate(rows):
        for x in range(w):
            if row[x >> 3] >> (7 - (x & 7)) & 1:
                assert y < h // 6 and M.BABY_CELL * cell <= x < (M.BABY_CELL + 1) * cell


# ------------------------------------------------------------------------------------------------ installing
def test_installing_opens_every_hook_and_trampoline_executable(vanilla_dir, built, art):
    import vf1_skin_sites as S
    emu = _emu(vanilla_dir, built, art)
    assert emu.install() == 1
    status = emu.status()
    assert status["requested"] == status["resolved"] == status["installed"] == 1
    opened = {a for a, _n, new in emu.protects if new == 0x40}           # PAGE_EXECUTE_READWRITE
    sites = {S.FUNCTIONS[k] for k, _p, _s in S.ENTRY_HOOKS} | {site for _p, site, _t in S.CALL_HOOKS}
    assert sites <= opened
    trampolines = [a for a, n, new in emu.protects if new == 0x40 and emu.in_dll(a)]
    assert trampolines and all(n >= 4096 and a % 4096 == 0 for a, n, new in emu.protects
                               if new == 0x40 and emu.in_dll(a))
    for site in sites:                                    # each one's protection given back after the write
        assert any(a == site and new == 0x20 for a, _n, new in emu.protects)
    # each entry is now a jmp into the DLL, each call a call into it
    for key, _pin, stolen in S.ENTRY_HOOKS:
        va = S.FUNCTIONS[key]
        code = bytes(emu.u.mem_read(va, stolen))
        assert code[0] == 0xE9 and emu.in_dll((va + 5 + int.from_bytes(code[1:5], "little", signed=True)) & 0xFFFFFFFF)
        assert code[5:] == b"\x90" * (stolen - 5)
    for _pin, site, _target in S.CALL_HOOKS:
        code = bytes(emu.u.mem_read(site, 5))
        assert code[0] == 0xE8 and emu.in_dll((site + 5 + int.from_bytes(code[1:], "little", signed=True)) & 0xFFFFFFFF)


def test_with_the_setting_off_nothing_is_written(vanilla_dir, built, art):
    emu = _emu(vanilla_dir, built, art, setting=0)
    before = bytes(emu.u.mem_read(0x401000, 0xB1000))
    assert emu.install() == 0
    assert emu.status()["requested"] == 0 and not emu.protects
    assert bytes(emu.u.mem_read(0x401000, 0xB1000)) == before


def test_a_changed_executable_installs_nothing(vanilla_dir, built, art):
    emu = _emu(vanilla_dir, built, art)
    emu.u.mem_write(0x439CCB, b"\x90")                     # one byte inside a pin
    before = bytes(emu.u.mem_read(0x401000, 0xB1000))
    assert emu.install() == 0
    assert emu.status()["resolved"] == 0 and not emu.protects
    assert bytes(emu.u.mem_read(0x401000, 0xB1000)) == before


# ------------------------------------------------------------------------------------------------ the house
def test_the_house_default_is_the_games_own_and_a_tone_recolours_head_and_body(vanilla_dir, built, art):
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=600, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Bob")
    stock = emu.draw_house()                             # before the DLL is installed: the game's own draw
    assert emu.install() == 1
    assert 1 <= emu.get_tone(0)[0] <= 10                   # a newcomer: a random tone, which is also the birth tone
    assert emu.get_tone(0)[0] == emu.get_tone(0)[1]
    assert emu.set_tone(0, 15) == 1                       # Default: exactly the game's own draw
    plain = emu.draw_house()
    assert [(b["file"], b["rect"], _key(b)) for b in plain] == [(b["file"], b["rect"], _key(b)) for b in stock]
    assert emu.status()["swapped"] == 0 and not emu.opened
    assert emu.set_tone(0, TONE) == 1
    toned = emu.draw_house()
    assert sorted(_compare(emu, art, stock, toned, SHEETS)) == ["male_bodies00.png", "male_heads00.png"]
    status = emu.status()
    assert status["swapped"] == 2 and status["made"] == 2 and status["rows"] == 2 and status["sheets"] == 2
    # the sheet files were checked and the shipped masks read, once each
    names = sorted(Path(p).name for p in emu.opened)
    assert names == ["male_bodies00.png", "male_bodies00.png", "male_heads00.png", "male_heads00.png"]
    assert {p.split("\\")[-2] for p in emu.opened} == {"Images", "Skin Masks"}
    again = emu.draw_house()                             # the kept rows: nothing is made again
    assert [b["surface"] for b in again] == [b["surface"] for b in toned] and emu.status()["made"] == 2
    assert not emu.freed
    assert emu.get_tone(0) == (TONE, emu.get_tone(0)[1])


def test_an_old_villager_uses_the_older_heads(vanilla_dir, built, art):
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=1000, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Bob")
    stock = emu.draw_house()
    assert emu.install() == 1 and emu.set_tone(0, 3) == 1
    assert sorted(_compare(emu, art, stock, emu.draw_house(), SHEETS, 3)) == ["male_bodies00.png", "male_heads10.png"]


@pytest.mark.parametrize("pose,sheet", [(46, "male_actions00.png"), (50, "male_sit00.png")])
def test_actions_and_sitting(vanilla_dir, built, art, pose, sheet):
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=600, head=HEAD, body=BODY, pose=pose)
    emu.name(0, "Bob")
    stock = emu.draw_house()
    assert emu.install() == 1 and emu.set_tone(0, 10) == 1
    swapped = _compare(emu, art, stock, emu.draw_house(), SHEETS, 10)
    assert sheet in swapped and "male_heads00.png" in swapped


def test_a_sheet_file_that_is_not_the_vanilla_one_is_drawn_as_the_game_draws_it(vanilla_dir, built, art):
    import skin_emu
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=600, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Bob")
    stock = emu.draw_house()
    data = bytearray((vanilla_dir / "Images" / "male_bodies00.png").read_bytes())
    data[-20] ^= 1                                          # a modded sheet: the mask no longer fits it
    emu.files_override[skin_emu.GAME + "Images\\male_bodies00.png"] = bytes(data)
    emu.files_override[skin_emu.FOLDER + "Skin Masks\\male_heads00.png"] = b"not a picture"
    assert emu.install() == 1 and emu.set_tone(0, TONE) == 1
    toned = emu.draw_house()
    assert [(b["file"], b["rect"]) for b in toned] == [(b["file"], b["rect"]) for b in stock]
    assert emu.status()["refused"] == 2 and emu.status()["swapped"] == 0


def test_a_child_through_the_games_own_blitter(vanilla_dir, built, art):
    """A child is drawn scaled, by the game's own pixel loop: the tone must come out of it."""
    np, vfskin, sheet, mask = art
    emu = _emu(vanilla_dir, built, art)
    assert emu.install() == 1
    emu.villager(female=False, age=200, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Cid")
    fx, fy = emu.feet()
    size, origin = 160, (fx - 80, fy - 130)
    emu.set_tone(0, 15)
    plain = emu.draw_house()
    stock = np.frombuffer(emu.picture((104, 142, 78), plain, size, size, origin), np.uint8).reshape(size, size, 3)
    emu.set_tone(0, TONE)
    toned = emu.draw_house()
    made = np.frombuffer(emu.picture((104, 142, 78), toned, size, size, origin), np.uint8).reshape(size, size, 3)
    changed = (stock != made).any(-1)
    assert 150 < changed.sum() < 2500                       # the face, neck, arms and hands; not the clothes
    assert made[changed].mean(0)[0] < stock[changed].mean(0)[0] - 60
    r, g, b = made[changed].astype(int).mean(0)
    assert r > g > b


# ------------------------------------------------------------------------------------------------ the held baby
def test_the_held_baby_is_drawn_in_the_babys_tone_and_nothing_else_of_carrying_changes(vanilla_dir, built, art):
    import picture_emu as pe
    import skin_emu
    np, vfskin, sheet, mask = art
    emu = _emu(vanilla_dir, built, art)
    mother = emu.villager(female=True, age=600, head=HEAD, body=BODY, pose=0, babies=2)
    emu.name(0, "Ann")
    baby = pe.VILLAGER0 + 0x145FC
    emu.w32(baby + 0x2A38, 1)
    emu.name(1, "Bea")                                      # the baby's record, hidden until the birth (present 0)
    state = emu.alloc(0x1C000)
    for k, slot in enumerate((1, -1, -1)):
        emu.w32(state + 0x1B120 + 4 * k, slot)
    emu.w32(skin_emu.GAME_STATE_INSTANCE, state)
    stock = emu.draw_house()
    assert emu.install() == 1
    assert emu.set_tone(0, 15) == 1 and emu.set_tone(1, 9) == 1      # the mother Default, the baby Dark
    toned = emu.draw_house()
    swapped = _compare(emu, art, stock, toned, ("carrying.png",), 9)
    assert swapped == ["carrying.png", "carrying.png"]              # twins: the bundle twice
    del mother
    # a carried thing that is not the baby (a cell of carrying.png other than 3) is never touched
    emu.villager(female=True, age=600, head=HEAD, body=BODY, pose=0, carried=5)
    emu.name(0, "Ann")
    emu.w32(skin_emu.GAME_STATE_INSTANCE, 0)
    stock = emu.draw_house()
    assert all(not (b["file"] == "carrying.png" and b["surface"] in emu.made) for b in stock)


# ------------------------------------------------------------------------------------------------ the portraits
def test_the_portrait_big_head_and_big_body(vanilla_dir, built, art):
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=600, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Bob")
    stock = emu.draw_portrait()
    assert emu.install() == 1 and emu.set_tone(0, 5) == 1
    swapped = _compare(emu, art, stock, emu.draw_portrait(), SHEETS, 5)
    assert "bigheads00.png" in swapped and "highrez_bodies_final2.png" in swapped


def test_the_event_popups_portrait(vanilla_dir, built, art):
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=True, age=600, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Ann")
    stock = emu.draw_event_portrait()
    assert emu.install() == 1 and emu.set_tone(0, 2) == 1
    swapped = _compare(emu, art, stock, emu.draw_event_portrait(), SHEETS, 2)
    assert "female_heads00.png" in swapped and set(swapped) <= {"female_heads00.png", "female_bodies00.png",
                                                                 "female_actions00.png"}


def _tree(emu, people):
    """Generation 1 of the Family Tree: `people` (place, name, sex, head, body, slot)."""
    import skin_emu
    tree = skin_emu.TREE
    emu.w32(tree, 1)
    record = tree + 1 * 0x6C8 - 0x6C4
    emu.u.mem_write(record, b"\x01")
    children = 0
    for place, name, sex, head, body, slot in people:
        peep = record + (4 if place == 0 else 0xDC if place == 1 else 0x1B8 + (place - 2) * 0xD8)
        emu.u.mem_write(peep, name.encode() + b"\0")
        emu.u.mem_write(peep + 0x1A, b"\x01")
        for off, v in ((0x1C, sex), (0x20, head), (0x24, body), (0x28, slot)):
            emu.w32(peep + off, v)
        children = max(children, place - 1)
    emu.w32(record + 0x1B4, children)
    return record


def test_the_family_tree_parents_and_children(vanilla_dir, built, art):
    import picture_emu as pe
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=600, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Bob")
    v1 = pe.VILLAGER0 + 0x145FC
    emu.u.mem_write(v1, bytes(emu.u.mem_read(pe.VILLAGER0, 0x145FC)))
    emu.w32(v1 + 0x2A38, 1)
    emu.name(1, "Ann")
    v2 = pe.VILLAGER0 + 2 * 0x145FC
    emu.u.mem_write(v2, bytes(emu.u.mem_read(pe.VILLAGER0, 0x145FC)))
    emu.name(2, "Cid")
    record = _tree(emu, [(0, "Bob", 0, HEAD, BODY, 0), (1, "Ann", 1, HEAD, BODY, 1), (2, "Cid", 0, HEAD, BODY, 2)])
    sites = ((0x439CC6, record + 4), (0x439E01, record + 0xDC), (0x439FA0, record + 0x1B8))
    stock = [emu.draw_tree_person(site, record, peep) for site, peep in sites]
    assert emu.install() == 1
    for slot, tone in ((0, 4), (1, 7), (2, 10)):
        assert emu.set_tone(slot, tone) == 1
    for (site, peep), was, tone in zip(sites, stock, (4, 7, 10)):
        swapped = _compare(emu, art, was, emu.draw_tree_person(site, record, peep), SHEETS, tone)
        assert swapped, hex(site)


def test_a_draw_with_no_person_noted_is_never_touched(vanilla_dir, built, art):
    """After every hooked draw the tone noted is back to none: a blit of a sheet of people from anywhere else (the
    Picture Maker's catalogue does it in the game too) is the game's own."""
    import struct
    emu = _emu(vanilla_dir, built, art)
    emu.villager(female=False, age=600, head=HEAD, body=BODY, pose=0)
    emu.name(0, "Bob")
    assert emu.install() == 1 and emu.set_tone(0, TONE) == 1
    emu.draw_house()
    made = emu.status()["made"]
    emu.blits = []
    grid = emu.grid(0xA1)
    surface = emu.r32(emu.r32(grid + 4))
    one = struct.unpack("<I", struct.pack("<f", 1.0))[0]
    emu.call(0x404C30, (surface, 10, 10, 0, 91 * BODY, 91, 91 * (BODY + 1), one, one, 0), ecx=emu.impl)
    assert emu.blits[0]["surface"] == surface and emu.status()["made"] == made


# ------------------------------------------------------------------------------------------------ the pictures
def test_a_toned_family_picture(vanilla_dir, built, art, tmp_path):
    """A family of five in five tones, each next to the game's own, drawn by the game's own blitter. Saved to
    VF1_SKIN_PICTURES when it is set."""
    np, vfskin, sheet, mask = art
    image = pytest.importorskip("PIL.Image")
    emu = _emu(vanilla_dir, built, art)
    assert emu.install() == 1
    people = [(False, 700, 7, 12, 3), (True, 650, 21, 30, 8), (True, 300, 4, 2, 5), (False, 200, 33, 18, 10),
              (True, 90, 15, 40, 1)]
    columns = []
    for female, age, head, body, tone in people:
        emu.villager(female=female, age=age, head=head, body=body, pose=0)
        emu.name(0, "Pat")
        fx, fy = emu.feet()
        size, origin = 120, (fx - 60, fy - 110)
        pair = []
        for t in (15, tone):
            emu.set_tone(0, t)
            blits = emu.draw_house(0.999)        # see-through by a hair: the game's own pixel loop draws it
            pair.append(np.frombuffer(emu.picture((104, 142, 78), blits, size, size, origin), np.uint8)
                        .reshape(size, size, 3))
        assert (pair[0] != pair[1]).any()
        columns.append(np.concatenate(pair, 0))
    picture = np.concatenate(columns, 1)
    out = os.environ.get("VF1_SKIN_PICTURES")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        image.fromarray(picture).resize((picture.shape[1] * 3, picture.shape[0] * 3), image.NEAREST).save(
            Path(out) / "vf1_toned_family_house.png")
