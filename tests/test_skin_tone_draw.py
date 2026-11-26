"""Skin Tones, the drawing prototype (native/vf1skin): one tone drawn on one family member, in emulation.

The game's own drawing code (CVillagerManager::DrawVillager 0x48B4D0 down to BlitRectWithAlpha 0x404C30)
runs on the vanilla executable in Unicorn with the built vf1skin.dll loaded and installed (tests/skin_emu.py).

Needs, or the test skips (nothing of the game or of the workbench is in the repository):
  VF1_VANILLA_DIR      a copy of the vanilla game (only read);
  VF1_SKIN_WORKBENCH   the Skin Tones workbench's VF1 folder (only read): layers\\<sheet>\\Skin mask.png are
                       the masks, and its vfskin.py is the approved recolour the DLL's pixels are held to.
  VF1_SKIN_PICTURE     (optional) a .png to write: the same child drawn by the game's blitter as Default
                       and in the tone.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TONE = 8                     # Deep brown
HEAD, BODY = 7, 12
SHEETS = ("male_heads00.png", "male_heads10.png", "male_bodies00.png")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
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

    sheets, masks = {}, {}
    for name in SHEETS:
        sheets[name] = np.array(image.open(vanilla_dir / "Images" / name).convert("RGBA"))
        masks[name] = np.array(image.open(workbench / "layers" / name[:-4] / "Skin mask.png").convert("RGBA"))
    return np, vfskin, sheets, masks


def _emu(vanilla_dir, built, art):
    import skin_emu

    np, _vfskin, sheets, masks = art

    def pixels(name):
        if name not in sheets:
            from PIL import Image
            sheets[name] = np.array(Image.open(vanilla_dir / "Images" / name).convert("RGBA"))
        a = sheets[name]
        return a.shape[1], a.shape[0], a.tobytes()

    def mask(name):
        if name not in masks:
            return None
        a = masks[name]
        return a.shape[1], a.shape[0], a.tobytes()

    return skin_emu.SkinEmu(vanilla_dir, built, pixels=pixels, masks=mask, wanted=SHEETS + ("peep_shadow1.png",))


def _person(emu, age):
    emu.villager(female=False, age=age, head=HEAD, body=BODY, pose=0, direction=0)


def _key(b):
    return b["x"], b["y"], b["alpha"], b["scale"], b["centre"], b["rect"][0], b["rect"][2]


def test_the_pins_are_the_vanilla_bytes(vanilla_dir):
    import pefile

    image = pefile.PE(str(vanilla_dir / "Virtual Families.exe")).get_memory_mapped_image()
    assert image[0x4C30:0x4C35] == bytes.fromhex("83EC5CD9EE")
    assert image[0x8B4D0:0x8B4D7] == bytes.fromhex("83EC548B442458")


def test_one_tone_drawn_on_one_person(vanilla_dir, built, art):
    np, vfskin, sheets, masks = art
    emu = _emu(vanilla_dir, built, art)
    _person(emu, 600)
    stock = emu.draw_house(1.0)                              # before the DLL is installed: the game's own draw
    assert emu.install() == 1
    opened = [a for a, _n, new in emu.protects if new == 0x40]            # PAGE_EXECUTE_READWRITE
    assert 0x404C30 in opened and 0x48B4D0 in opened and any(DLL_range(a) for a in opened)   # and the trampolines
    assert all(new in (0x40, 0x20) for _a, _n, new in emu.protects)       # 0x20: a site put back as it was

    # no tone: every blit is the game's own, on the game's own surfaces
    plain = emu.draw_house(1.0)
    assert [(b["file"], b["rect"], _key(b)) for b in plain] == [(b["file"], b["rect"], _key(b)) for b in stock]
    assert emu.status()["swapped"] == 0 and emu.status()["made"] == 0 and not emu.asked

    assert emu.set_tone(0, TONE) == 1
    toned = emu.draw_house(1.0)
    assert len(toned) == len(stock)
    swapped = 0
    for was, now in zip(stock, toned):
        assert _key(was) == _key(now)                        # the same place, size, alpha and columns
        if was["file"] not in SHEETS:
            assert now["file"] == was["file"] and now["rect"] == was["rect"]      # the shadow: untouched
            continue
        swapped += 1
        sheet, mask = sheets[was["file"]], masks[was["file"]][..., 3] >= 128
        cell = 56 if "heads" in was["file"] else 91
        row = was["rect"][1] // cell
        assert row == (HEAD if "heads" in was["file"] else BODY)
        assert now["surface"] in emu.made and emu.made[now["surface"]] == (sheet.shape[1], cell)
        assert now["rect"] == (was["rect"][0], was["rect"][1] - row * cell, was["rect"][2], was["rect"][3] - row * cell)
        w, h, data = emu.surface_pixels(now["surface"])
        made = np.frombuffer(data, np.uint8).reshape(h, w, 4).astype(int)
        rows = slice(row * cell, (row + 1) * cell)
        want = vfskin.recolour(sheet, mask, vfskin.TONES[TONE - 1], "VF1")[rows].astype(int)
        skin = mask[rows] & (sheet[rows][..., 3] > 0)
        assert skin.sum() > 200                               # there is skin in this row
        assert (made[~skin] == sheet[rows][~skin]).all()      # every pixel that is not skin: the game's own
        assert (made[..., 3] == sheet[rows][..., 3]).all()    # alpha never changes
        off = np.abs(made[skin][:, :3] - want[skin][:, :3])
        assert off.max() <= 1, off.max()                      # the approved recolour, to one colour level
        assert (made[skin][:, :3] != sheet[rows][skin][:, :3]).any(1).mean() > 0.99
    assert swapped == 2                                       # the body and the head
    status = emu.status()
    assert status["installed"] == 1 and status["swapped"] == 2 and status["made"] == 2 and status["rows"] == 2
    assert sorted(Path(p).name for p in emu.asked) == ["male_bodies00.png", "male_heads00.png"]

    # drawn again: the kept rows, nothing made again; and nobody else is touched
    again = emu.draw_house(1.0)
    assert [b["surface"] for b in again] == [b["surface"] for b in toned] and emu.status()["made"] == 2
    assert emu.set_tone(0, 0) == 1
    back = emu.draw_house(1.0)
    assert [(b["file"], b["rect"]) for b in back] == [(b["file"], b["rect"]) for b in stock]
    assert len(emu.freed) == 2 and not set(emu.freed) & set(emu.made)     # the two mask pictures, once read


def DLL_range(address: int) -> bool:
    import skin_emu

    return skin_emu.DLL_BASE <= address < skin_emu.DLL_BASE + 0x100000


def test_a_child_through_the_games_own_blitter(vanilla_dir, built, art, tmp_path):
    """A child is drawn scaled, by the game's own pixel loop: the tone must come out of it."""
    np, vfskin, sheets, masks = art
    image = pytest.importorskip("PIL.Image")
    emu = _emu(vanilla_dir, built, art)
    assert emu.install() == 1
    _person(emu, 200)
    fx, fy = emu.feet()
    size, origin = 160, (fx - 80, fy - 130)
    plain = emu.draw_house(1.0)
    stock = np.frombuffer(emu.picture((104, 142, 78), plain, size, size, origin), np.uint8).reshape(size, size, 3)
    emu.set_tone(0, TONE)
    toned = emu.draw_house(1.0)
    made = np.frombuffer(emu.picture((104, 142, 78), toned, size, size, origin), np.uint8).reshape(size, size, 3)
    changed = (stock != made).any(-1)
    assert 150 < changed.sum() < 2500                         # the face, neck, arms and hands; not the clothes
    # where it changed, it is darker and brown: Deep brown's lit mid-skin is (114, 76, 50)
    assert made[changed].mean(0)[0] < stock[changed].mean(0)[0] - 60
    r, g, b = made[changed].astype(int).mean(0)
    assert r > g > b
    out = os.environ.get("VF1_SKIN_PICTURE")
    if out:
        both = np.concatenate([stock, made], 1)
        image.fromarray(both).resize((both.shape[1] * 4, both.shape[0] * 4), image.NEAREST).save(out)
