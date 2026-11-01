"""The Picture Maker's "Every picture" catalogue: every picture in Virtual Families 1's Images folder (and
the patcher's own), each sheet whole and cut into the cells the game cuts it into, and the pictures the
game assembles from several draws (meters and bars, buttons in their states, dialogs, the house, fonts),
each drawn as the game draws it.  Read from the chosen game folder at run time; no game art ships with
the patcher, and nothing is written but the PNGs the player saves.

Where the rules come from (the vanilla Virtual Families.exe 1.01.00):

* theGraphicsManager's image table 0x4F2D00 (0x30 bytes an entry, 211 entries to 0x4F5490; looked up by
  0x44F2D0): the id, the file, the columns and rows, and for the people's heads and the big heads two files
  across.  GetImageGrid 0x44F5A0 -> 0x44F3E0 makes, from an entry with columns: an ldwImageGrid
  (0x40AE10: the cell is the file's width / columns by its height / rows, 0x40AE68 / 0x40AE77) when it has
  rows, a strip (0x401000: the same grid with one row) when its rows are 0, and the two-file grid
  0x40AEA0 for the heads; an entry with no columns is a single picture (GetImage 0x44F860 -> 0x44F650).
  ldwImageGrid::GetCellRect 0x40AD40 gives cell (column, row)'s rectangle, clamping a column or row past
  the last to the last.  tests/test_game_art.py runs 0x40AD40 in Unicorn for every cell listed here.
* Every cell is drawn by ldwGameWindowImpl::BlitRectWithAlpha 0x404C30 (vf1_picture_image.game_layer:
  scale 1 and alpha 1 is SDL's own alpha blit, the cell's pixels as they are).

Each catalogue entry is an `Art`: the draws (vf1_picture_image.Draw, and `Fill` for a solid rectangle) in the
order the game makes them, whether the game ever shows it (with the code that does, or why it never does),
and how it was checked against the game.  The assembled pictures come from the vf1_art_*.py modules
(SOURCES below).
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

import vf1_picture_image as pi

IMAGES_DIR = "Images"
PATCHER_FOLDER = "Virtual Families 1 Patcher Files"
PAYLOAD = Path(__file__).resolve().parent / "payload"
TREE_PICTURES = Path(__file__).resolve().parent / "tree_pictures"
CHECK = "Not checked against the game"

# theGraphicsManager's image table 0x4F2D00, in its order: id: (file, columns, rows, files across).
# Columns 0: a single picture (GetImage); rows 0: a strip of `columns` cells in one row.
TABLE = {
    0x00: ('No Graphic', 0, 0, 1),
    0x01: ('hand_open.png', 0, 0, 1),
    0x02: ('hand.png', 0, 0, 1),
    0x03: ('pet_grid.png', 24, 3, 1),
    0x04: ('bigheads', 12, 50, 2),
    0x05: ('highrez_bodies_final2.png', 2, 50, 1),
    0x06: ('LoadSceneBarBG.png', 1, 1, 1),
    0x07: ('VD_progressbar-blue.jpg', 1, 1, 1),
    0x08: ('VD_progressbar-red.jpg', 1, 1, 1),
    0x09: ('VD_fade-01.png', 1, 1, 1),
    0x0A: ('VD_fade-02.png', 1, 1, 1),
    0x0B: ('VD_line-blue.jpg', 1, 1, 1),
    0x0C: ('VD_line-red.jpg', 1, 1, 1),
    0x0D: ('birdhStrip1.png', 10, 1, 1),
    0x0F: ('foodWork1.png', 2, 1, 1),
    0x10: ('workWork1.png', 2, 1, 1),
    0x11: ('holeSM1.png', 1, 1, 1),
    0x12: ('holeLG1.png', 1, 1, 1),
    0x13: ('gopherInHole.png', 1, 1, 1),
    0x21: ('rosepetalsOnBed.png', 1, 1, 1),
    0x14: ('toiletOpen.png', 1, 1, 1),
    0x15: ('toiletClosed.png', 1, 1, 1),
    0x16: ('fridgeStates.png', 3, 2, 1),
    0x17: ('greenLight.png', 1, 1, 1),
    0x18: ('redLight.png', 1, 1, 1),
    0x0E: ('chopGreens1.png', 9, 1, 1),
    0x19: ('showerCurtain.png', 1, 1, 1),
    0x1A: ('breads.png', 1, 1, 1),
    0x1B: ('cans.png', 1, 1, 1),
    0x1C: ('meal.png', 1, 1, 1),
    0x1D: ('bbqmeat.png', 1, 1, 1),
    0x1E: ('kitchenUpgrade.png', 2, 1, 1),
    0x1F: ('officeUpgrade.png', 2, 1, 1),
    0x20: ('workroomUpgrade.png', 2, 1, 1),
    0x22: ('ultra_wide_button.png', 3, 0, 1),
    0x23: ('btn_blue.png', 3, 0, 1),
    0x24: ('btn_brown.png', 3, 0, 1),
    0x25: ('btn_green.png', 3, 0, 1),
    0x26: ('btn_orange.png', 3, 0, 1),
    0x27: ('btn_red.png', 3, 0, 1),
    0x28: ('btn_dollar.png', 3, 0, 1),
    0x29: ('btn_clear.png', 3, 0, 1),
    0x2A: ('btn_orange-big.png', 3, 0, 1),
    0x2B: ('btn_greenlong.png', 3, 0, 1),
    0x2C: ('OrangeDlgTileGrid.png', 9, 1, 1),
    0x2D: ('GreenDlgTileGrid.png', 9, 1, 1),
    0x2E: ('dlgemailgrid.png', 9, 1, 1),
    0x2F: ('VD_btn_left.png', 3, 0, 1),
    0x30: ('VD_btn_right.png', 3, 0, 1),
    0x31: ('radiobuttonstrip.png', 2, 0, 1),
    0x32: ('radioblank.png', 0, 0, 1),
    0x33: ('radioselected.png', 0, 0, 1),
    0x34: ('CheckboxStrip.png', 2, 0, 1),
    0x35: ('checkmark.png', 0, 0, 1),
    0x36: ('WideSlider2.png', 0, 0, 1),
    0x37: ('sliderhandle.png', 0, 0, 1),
    0x38: ('StatusBarSliceB.png', 0, 0, 1),
    0x39: ('StatusBarSliceR.png', 0, 0, 1),
    0x3A: ('LoadColor.png', 0, 0, 1),
    0x3B: ('focus_circle.png', 0, 0, 1),
    0x3C: ('overview_bg.jpg', 0, 0, 1),
    0x3D: ('awards_bg.jpg', 0, 0, 1),
    0x3E: ('map_cloud01.png', 0, 0, 1),
    0x3F: ('loading.jpg', 0, 0, 1),
    0x5A: ('adoptbg.jpg', 0, 0, 1),
    0x40: ('ldwLogo.png', 0, 0, 1),
    0x41: ('logo1.png', 0, 0, 1),
    0x42: ('small_logo.png', 1, 1, 1),
    0x43: ('Hill.png', 1, 1, 1),
    0x44: ('House.png', 1, 1, 1),
    0x45: ('main_BG.png', 0, 0, 1),
    0x46: ('help.jpg', 0, 0, 1),
    0x47: ('vv2_boxshot.jpg', 0, 0, 1),
    0x48: ('empty1.png', 3, 0, 1),
    0x49: ('arrowglow.png', 0, 0, 1),
    0x4A: ('arrowglowdown.png', 0, 0, 1),
    0x4B: ('arrowleftglow.png', 0, 0, 1),
    0x4C: ('arrowrightglow.png', 0, 0, 1),
    0x4F: ('collection_bg.jpg', 0, 0, 1),
    0x50: ('collection_photo-glass.jpg', 0, 0, 1),
    0x51: ('dating_bg.jpg', 0, 0, 1),
    0x52: ('collecting_coins.png', 4, 3, 1),
    0x53: ('collecting_leafs.png', 4, 3, 1),
    0x54: ('collecting_picture.png', 4, 3, 1),
    0x55: ('collecting_insects.png', 4, 3, 1),
    0x57: ('VD_BG_2.jpg', 0, 0, 1),
    0x58: ('store_BG.jpg', 0, 0, 1),
    0x59: ('stucco.png', 2, 1, 1),
    0x5B: ('waves_proto.png', 10, 1, 1),
    0x5C: ('yellow_sparkle.png', 10, 1, 1),
    0x5D: ('sparklestrip2.png', 10, 1, 1),
    0x5E: ('sparklestrip.png', 10, 1, 1),
    0x5F: ('dust2.png', 9, 1, 1),
    0x60: ('algae.png', 4, 4, 1),
    0x61: ('rainbow.png', 10, 1, 1),
    0x62: ('bubble.png', 10, 1, 1),
    0x63: ('candlestrip.png', 9, 1, 1),
    0x64: ('petalstrip.png', 12, 3, 1),
    0x65: ('waterfallanimA.png', 8, 4, 1),
    0x66: ('waterfallanimb.png', 4, 2, 1),
    0x67: ('foam.png', 4, 2, 1),
    0x68: ('carrying.png', 13, 6, 1),
    0x69: ('spray.png', 12, 1, 1),
    0x6A: ('spray_Grid_red.png', 11, 1, 1),
    0x6B: ('sharp_sparkle.png', 10, 1, 1),
    0x6C: ('email_anim.png', 2, 1, 1),
    0x6D: ('email_big_anim.png', 2, 1, 1),
    0x6E: ('water_spray_anim.png', 10, 1, 1),
    0x6F: ('faucet_water_anim.png', 10, 1, 1),
    0x70: ('boiling_water_anim.png', 10, 1, 1),
    0x71: ('salad_anim.png', 10, 1, 1),
    0x72: ('sawdust_anim.png', 10, 1, 1),
    0x73: ('shower_anim.png', 10, 1, 1),
    0x74: ('steam_anim.png', 10, 1, 1),
    0x75: ('dripping_water.png', 10, 1, 1),
    0x76: ('blurry_sparkle.png', 10, 1, 1),
    0x77: ('collectables_small.png', 6, 12, 1),
    0x78: ('footprints.png', 15, 1, 1),
    0x79: ('raindrops.png', 3, 1, 1),
    0x7A: ('smokestriplight.png', 12, 1, 1),
    0x7B: ('reefFish1.png', 5, 6, 1),
    0x7C: ('reefFish2.png', 5, 8, 1),
    0x7D: ('reefFish3.png', 5, 10, 1),
    0x7E: ('beestriplarge_final2.png', 14, 2, 1),
    0x7F: ('bubblestrip.png', 9, 1, 1),
    0x80: ('TVAnimBig.png', 6, 3, 1),
    0x81: ('TVAnimSmall.png', 6, 3, 1),
    0x82: ('tvOld.png', 1, 1, 1),
    0x83: ('tvFlatscreen.png', 1, 1, 1),
    0x84: ('eastCPUAnim.png', 6, 2, 1),
    0x85: ('westCPUAnim.png', 6, 2, 1),
    0x86: ('airPurifier.png', 1, 1, 1),
    0x87: ('shedDoor.png', 1, 1, 1),
    0x88: ('outsideChair.png', 2, 1, 1),
    0x89: ('floorDamage.png', 3, 1, 1),
    0x8A: ('stucco.png', 2, 1, 1),
    0x8B: ('fishtank.png', 1, 1, 1),
    0x8C: ('kitchenGarbageFull.png', 1, 1, 1),
    0x8D: ('lightbulb.png', 1, 1, 1),
    0x8E: ('doorknob.png', 1, 1, 1),
    0x8F: ('bedUpgrade.png', 1, 1, 1),
    0x90: ('towelUpgrade.png', 2, 1, 1),
    0x91: ('patioSet.png', 1, 1, 1),
    0x92: ('pool.png', 1, 1, 1),
    0x93: ('hammock.png', 1, 1, 1),
    0x94: ('bbq.png', 1, 1, 1),
    0x95: ('birdhouse.png', 1, 1, 1),
    0x96: ('paintings.png', 3, 1, 1),
    0x97: ('pinball.png', 1, 1, 1),
    0x98: ('radio.png', 1, 1, 1),
    0x99: ('toolbox.png', 1, 1, 1),
    0x9A: ('treadmill.png', 1, 1, 1),
    0x9B: ('puddles.png', 2, 1, 1),
    0x9C: ('female_heads', 24, 50, 2),
    0x9D: ('female_bodies00.png', 32, 50, 1),
    0x9E: ('female_actions00.png', 15, 50, 1),
    0x9F: ('female_sit00.png', 9, 50, 1),
    0xA0: ('male_heads', 24, 50, 2),
    0xA1: ('male_bodies00.png', 32, 50, 1),
    0xA2: ('male_actions00.png', 15, 50, 1),
    0xA3: ('male_sit00.png', 9, 50, 1),
    0xA4: ('peep_shadow1.png', 0, 0, 1),
    0xA5: ('ripple.png', 4, 1, 1),
    0xA6: ('sunbeam.png', 0, 0, 1),
    0xA7: ('map_fog.png', 0, 0, 1),
    0xA8: ('bird.png', 12, 1, 1),
    0xA9: ('bird_shadow.png', 1, 1, 1),
    0xAA: ('sharkstripfinal.png', 8, 1, 1),
    0xAB: ('dragonflies.png', 6, 4, 1),
    0xAC: ('butterflygreen.png', 4, 5, 1),
    0xAD: ('hummingbirdstrip.png', 4, 2, 1),
    0xAE: ('LightSourceMask100.png', 1, 1, 1),
    0xAF: ('LightSourceMask150.png', 1, 1, 1),
    0xB0: ('LightSourceMask180x8.png', 8, 1, 1),
    0xB1: ('LightSourceMask200x10.png', 10, 1, 1),
    0xB2: ('LightSourceMask250.png', 1, 1, 1),
    0xB3: ('LightSourceMask300x10.png', 10, 1, 1),
    0xB4: ('LightSourceMask350.png', 1, 1, 1),
    0xB5: ('LightSourceMask400.png', 1, 1, 1),
    0xB6: ('LightSourceMask450.png', 1, 1, 1),
    0xB7: ('LightSourceMask500.png', 1, 1, 1),
    0xB8: ('InventoryItems.png', 10, 14, 1),
    0xB9: ('home_grid.png', 5, 3, 1),
    0xBA: ('wedding.jpg', 0, 0, 1),
    0xBB: ('birth.jpg', 0, 0, 1),
    0xBE: ('death.jpg', 0, 0, 1),
    0xBD: ('promotion.jpg', 0, 0, 1),
    0xBC: ('college.jpg', 0, 0, 1),
    0xBF: ('remote.png', 1, 1, 1),
    0xC0: ('familytree_bg.jpg', 0, 0, 1),
    0xC1: ('familytree_parentframe.png', 0, 0, 1),
    0xC2: ('familytree_childframe.png', 0, 0, 1),
    0xC3: ('familytree_scrollknob_top.png', 0, 0, 1),
    0xC4: ('familytree_scrollknob_mid.png', 0, 0, 1),
    0xC5: ('familytree_scrollknob_btm.png', 0, 0, 1),
    0xC6: ('familytree_slidertrack.png', 0, 0, 1),
    0xC7: ('arrowup.png', 3, 1, 1),
    0xC8: ('arrowdown.png', 3, 1, 1),
    0xC9: ('verticalslidertrack.png', 0, 0, 1),
    0xCA: ('achievement_box.png', 0, 0, 1),
    0xCB: ('achievement_complete_box.png', 0, 0, 1),
    0xCC: ('achievement_progress_box.png', 0, 0, 1),
    0xCD: ('main_no-comm.png', 0, 0, 1),
    0xCE: ('store_groceries.png', 4, 2, 1),
    0xCF: ('store_medicines.png', 5, 2, 1),
    0xD0: ('store_homeimprovement.png', 5, 3, 1),
    0xD1: ('checkmark_red.png', 0, 0, 1),
    0xD5: ('fountainwater.png', 1, 1, 1),
    0xD2: ('ball_shadow.png', 0, 0, 1),
    0xD3: ('onsale.png', 0, 0, 1),
    0xD4: ('balconyflowers.png', 4, 1, 1),
}
MULTI_FILE_FORMAT = "{stem}{k}0.png"        # the two-file grids (the heads, the big heads): 0x40AEA0 adds 0x4B2660 ".png"


def table_files(image: int) -> list[str]:
    name, _cols, _rows, files = TABLE[image]
    return [name] if files == 1 else [MULTI_FILE_FORMAT.format(stem=name, k=k) for k in range(files)]


def grid_shape(image: int) -> tuple[int, int] | None:
    """(columns, rows) the game cuts the picture into, or None for a single picture (GetImage)."""
    _name, cols, rows, _files = TABLE[image]
    if cols == 0:
        return None
    return cols, (rows if rows else 1)


def cell_rect(size: tuple[int, int], cols: int, rows: int, column: int, row: int,
              files: int = 1) -> tuple[int, tuple[int, int, int, int]]:
    """(file index, (left, top, right, bottom)): ldwImageGrid::GetCellRect 0x40AD40 for a grid of `cols` x
    `rows` cells over `files` files across, each file `size` (width, height)."""
    width, height = size
    per_file = cols // files if files > 1 else cols
    file_index = 0
    if files > 1:
        file_index = (column // per_file) % files
        column = column % per_file
    cw, ch = width // per_file, height // rows
    column = min(column, per_file - 1)
    row = min(row, rows - 1)
    return file_index, (cw * column, ch * row, cw * column + cw, ch * row + ch)


# ------------------------------------------------------------------ the pieces of a picture
@dataclass(frozen=True)
class Fill:
    """A solid rectangle the game fills (x, y, width, height) with an RGBA colour."""
    x: int
    y: int
    w: int
    h: int
    rgba: tuple


@dataclass(frozen=True)
class Art:
    """One picture in the catalogue.  `layers` are pi.Draw / Fill in the order the game draws them (a draw's
    `file` names a picture in the game's Images folder, or "patcher:<path>" for the patcher's own).
    `used`: the game shows it (`why` names the code that does), or not (`why` says why it never does).
    `checked`: how it was checked against the game; empty when it was not."""
    key: str
    category: str
    label: str
    layers: tuple
    used: bool
    why: str
    checked: str = ""
    patcher: bool = False

    @property
    def title(self) -> str:
        tags = []
        if not self.used:
            tags.append("(unused)")
        if self.patcher:
            tags.append("(patcher)")
        return " ".join([self.label, *tags])

    def note(self) -> str:
        words = [self.why]
        words.append(self.checked if self.checked else f"{CHECK}.")
        return " ".join(w for w in words if w)


# ------------------------------------------------------------------ reading the pictures
def png_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(pi.PNG_MAGIC):
        raise pi.PictureError("not a PNG file")
    return struct.unpack(">II", data[16:24])


def jpeg_size(data: bytes) -> tuple[int, int]:
    at = 2
    while at + 4 <= len(data):
        if data[at] != 0xFF:
            at += 1
            continue
        marker = data[at + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            at += 1 if marker == 0xFF else 2
            continue
        length = struct.unpack(">H", data[at + 2:at + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[at + 5:at + 9])
            return w, h
        at += 2 + length
    raise pi.PictureError("not a JPEG file")


def decode(data: bytes, name: str = "") -> pi.Image:
    """A picture file's pixels as straight RGBA, as the game's loader (SDL2_image) gives them."""
    lower = name.lower()
    if data.startswith(pi.PNG_MAGIC):
        return pi.decode_png(data)
    if data[:2] == b"\xff\xd8":
        import vf1_jpeg
        return vf1_jpeg.decode(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        import vf1_small_formats
        return vf1_small_formats.decode_gif(data)
    if data[:2] == b"BM":
        import vf1_small_formats
        return vf1_small_formats.decode_bmp(data)
    raise pi.PictureError(f"{name or 'the file'} is not a picture the Picture Maker can read ({lower[-4:]})")


class GameFiles:
    """The pictures of one game folder, found as Windows finds them (ignoring case), decoded once."""

    def __init__(self, folder: Path | None) -> None:
        self.folder = Path(folder) if folder else None
        self._names: dict[str, Path] | None = None
        self._cache: dict[str, pi.Image] = {}
        self._sizes: dict[str, tuple[int, int]] = {}

    def problem(self) -> str:
        if self.folder is None:
            return "Choose your Virtual Families game folder."
        if not (self.folder / IMAGES_DIR).is_dir():
            return f"{self.folder} has no Images folder: choose the folder Virtual Families is installed in."
        return ""

    def names(self) -> dict[str, Path]:
        """lower-case path relative to Images ('drm/logo1.gif') -> the file."""
        if self._names is None:
            found: dict[str, Path] = {}
            root = self.folder / IMAGES_DIR if self.folder else None
            if root is not None and root.is_dir():
                for dirpath, _dirs, files in os.walk(root):
                    for f in files:
                        path = Path(dirpath) / f
                        found[path.relative_to(root).as_posix().lower()] = path
            self._names = found
        return self._names

    def path(self, name: str) -> Path | None:
        if name.startswith("patcher:"):
            path = Path(name[len("patcher:"):])
            return path if path.is_file() else None
        if name.startswith("root:"):
            path = self.folder / name[len("root:"):] if self.folder else None
            return path if path is not None and path.is_file() else None
        return self.names().get(name.replace("\\", "/").lower())

    def has(self, name: str) -> bool:
        return self.path(name) is not None

    def data(self, name: str) -> bytes:
        path = self.path(name)
        if path is None:
            raise pi.PictureError(f"The game folder has no {name}.")
        return path.read_bytes()

    def size(self, name: str) -> tuple[int, int]:
        if name not in self._sizes:
            if name in self._cache:
                image = self._cache[name]
                self._sizes[name] = (image.width, image.height)
            else:
                data = self.data(name)
                if data.startswith(pi.PNG_MAGIC):
                    self._sizes[name] = png_size(data)
                elif data[:2] == b"\xff\xd8":
                    self._sizes[name] = jpeg_size(data)
                else:
                    image = self.image(name)
                    self._sizes[name] = (image.width, image.height)
        return self._sizes[name]

    def image(self, name: str) -> pi.Image:
        if name not in self._cache:
            self._cache[name] = decode(self.data(name), name)
        return self._cache[name]

    def forget(self) -> None:
        """Let go of the decoded pictures (Save all frees them as it goes)."""
        self._cache.clear()


# ------------------------------------------------------------------ drawing
def render(files: GameFiles, art: Art) -> pi.Image:
    """The picture as the game draws it, on a transparent canvas as big as all its draws."""
    pieces = []
    tinted: dict = {}
    for layer in art.layers:
        if isinstance(layer, Fill):
            image = pi.Image(max(0, layer.w), max(0, layer.h))
            image.data[:] = bytes(layer.rgba) * (image.width * image.height)
        elif getattr(layer, "make", None) is not None:
            image = layer.make(files)            # pixels a module computes (the house's night and haze)
        else:
            sheet = files.image(layer.file)
            tint = tuple(getattr(layer, "tint", (255, 255, 255)))[:3]
            if tint != (255, 255, 255):          # a font's coloured copy, 0x402940 (vf1_art_fonts.tinted)
                key = (layer.file, tint)
                if key not in tinted:
                    import vf1_art_fonts
                    tinted[key] = vf1_art_fonts.tinted(sheet, tint)
                sheet = tinted[key]
            image = pi.game_layer(sheet, tuple(layer.rect), layer.scale, layer.alpha)
        pieces.append((image, layer.x, layer.y))
    pieces = [p for p in pieces if p[0].width and p[0].height]
    if not pieces:
        return pi.Image(1, 1)
    left = min(x for _i, x, _y in pieces)
    top = min(y for _i, _x, y in pieces)
    right = max(x + i.width for i, x, _y in pieces)
    bottom = max(y + i.height for i, _x, y in pieces)
    canvas = pi.Image(right - left, bottom - top)
    for image, x, y in pieces:
        canvas.draw(image, x - left, y - top)
    return canvas


def whole(name: str) -> pi.Draw:
    """A draw of a whole picture (its rectangle is filled in when it is drawn: see `resolve`)."""
    return pi.Draw("whole", name, (0, 0, -1, -1), 0, 0)


def resolve(files: GameFiles, art: Art) -> Art:
    """`art` with every whole-picture draw given the picture's size."""
    layers = []
    changed = False
    for layer in art.layers:
        if isinstance(layer, pi.Draw) and tuple(layer.rect) == (0, 0, -1, -1):
            w, h = files.size(layer.file)
            layer = pi.Draw(layer.what, layer.file, (0, 0, w, h), layer.x, layer.y, layer.scale, layer.alpha)
            changed = True
        layers.append(layer)
    if not changed:
        return art
    return Art(art.key, art.category, art.label, tuple(layers), art.used, art.why, art.checked, art.patcher)


def draw(files: GameFiles, art: Art) -> pi.Image:
    return render(files, resolve(files, art))


# ------------------------------------------------------------------ the catalogue
@dataclass
class Catalogue:
    arts: list = field(default_factory=list)
    problems: list = field(default_factory=list)       # sources that could not be listed, in words

    def categories(self) -> list[str]:
        seen: list[str] = []
        for art in self.arts:
            if art.category not in seen:
                seen.append(art.category)
        return seen

    def find(self, text: str) -> list[Art]:
        words = [w for w in str(text or "").casefold().split() if w]
        if not words:
            return list(self.arts)
        out = []
        for art in self.arts:
            hay = " ".join((art.category, art.title, art.key, art.why)).casefold()
            if all(w in hay for w in words):
                out.append(art)
        return out

    def by_key(self, key: str) -> Art | None:
        for art in self.arts:
            if art.key == key:
                return art
        return None


def _sources():
    """The catalogue's parts, in the order they are listed (each a module with `arts(files) -> list[Art]`)."""
    import vf1_art_sheets
    out = [vf1_art_sheets]
    for name in ("vf1_art_meters", "vf1_art_ui", "vf1_art_house", "vf1_art_misc", "vf1_art_fonts"):
        try:
            out.append(__import__(name))
        except ImportError:
            continue
    return out


def catalogue(files: GameFiles) -> Catalogue:
    cat = Catalogue()
    if files.problem():
        cat.problems.append(files.problem())
        return cat
    seen = set()
    for source in _sources():
        try:
            arts = source.arts(files)
        except Exception as exc:                   # a part that cannot be listed is said, never raised
            cat.problems.append(f"{getattr(source, 'TITLE', source.__name__)}: {exc}")
            continue
        for art in arts:
            if art.key in seen:
                raise ValueError(f"two pictures have the key {art.key}")
            seen.add(art.key)
            cat.arts.append(art)
    order = {c: k for k, c in enumerate(CATEGORY_ORDER)}
    cat.arts.sort(key=lambda a: order.get(a.category.split("/")[0], len(order)))
    return cat


# The top-level categories, in the order the window lists them ("/" makes a sub-category).
CATEGORY_ORDER = (
    "Meters and bars",
    "Buttons and controls",
    "Dialogs and panels",
    "Icons and cursors",
    "Fonts",
    "House and yard",
    "Furniture and objects",
    "Food and cooking",
    "Weather, day and night",
    "Effects and animations",
    "Animals and insects",
    "People",
    "Store",
    "Collectibles and collections",
    "Screens and backgrounds",
    "Patcher's own pictures",
)
