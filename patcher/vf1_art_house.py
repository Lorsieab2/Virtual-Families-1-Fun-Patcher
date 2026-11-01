"""The Picture Maker's house, yard, furniture, weather and night pictures for Virtual Families 1, each drawn as
the game draws it (see vf1_game_art for the catalogue they join).

Where the rules come from (the vanilla Virtual Families.exe 1.01.00; tests/test_art_house.py runs every one of
these in Unicorn, see tests/house_emu.py):

* The map: 16 JPEG tiles of 512 x 512.  The loader 0x495C60 names tile (X, Y) "%sX%01dY%01d.jpg" (0x4D7A0C)
  with "Map" and puts it at (512 X, 512 Y); theMainScene's draw 0x4458B0 draws them first (0x495D90, a plain
  SDL blit through 0x4098C0 -> 0x408680 -> 0x404BC0), in the loader's order (X outer, Y inner).
* The house pictures: the loader 0x41FD50 fetches every picture of the house; the list builder 0x420BC0
  (ending in 0x420200, the house's on/off things) lists what is to be drawn from the room levels (CTech
  0x50C620), what was bought and repaired (theGameState), the food (0x50C550) and the house's on/off things
  (CEnvironment 0x8752F0); the list draw 0x420130 draws them, right after the map (0x44590F), each through
  0x409970 -> 0x4089B0 -> 0x404C30.  Places are on the 2048 x 2048 map.
* The animations: CEnvironment::SetProp 0x4938C0 starts the television (0x493AD5) and the two computer screens
  (0x493B27, 0x493B4D) as effects (AddEffect 0x421810, the table 0x4EB370); the effect draw 0x421A30 draws the
  current frame (-> 0x44EC90 -> 0x404C30) after the house pictures.  The frames run in order, one frame every
  `delay` steps of the effect clock 0x421B50 (one step every 7 of its calls).
* The weather (0x4920F0, after the people): the sunbeams 0x492040, the daytime haze (0x492160: a fill of grey
  0.3 at the weather's haze alpha), the storm's lightning flash 0x4909F0, the rain's splashes 0x491B50.
* The night 0x4919D0: each lamp of Assets\\lsmap.dat copies the screen under its light mask (0x490C90: the copy
  0x4045C0, then the mask's alpha byte into the copy, 0x40AD10 -> 0x40B6D0); the screen is filled with dark
  blue (0, 0, 102) at an alpha A = trunc(178 x darkness + 0.5) (0x491A5F -> 0x408100 -> 0x403B40), and each
  lamp's copy is blitted back (0x491A96).  The fill 0x403B40 does not use the SDL blend: every colour byte d
  becomes (d x (255 - A) >> 8) + (c x A >> 8).  The darkness 0x491810 is 0 by day, rises over the twilight
  after sunset to 0.65 (the first two hours, 0x491690) or 0.85, and is 1.0 from midnight to the morning twilight.
  Those fills and the night are not a plain draw: their pictures are `Computed` layers (below).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import vf1_game_art as ga
import vf1_picture_image as pi

TITLE = "House, yard, weather and night"
MAP_SIZE = 2048
TILE = 512
CHECKED = "Checked against the game's own drawing code ({code}) run in Unicorn."
LIST_DRAW = "Drawn by the house list 0x420130 from the house screen's draw (0x44590F)."


# ------------------------------------------------------------------ a computed layer
@dataclass(frozen=True)
class Computed:
    """A layer whose pixels this module computes (a blend the game does not make with BlitRectWithAlpha).
    It has pi.Draw's fields; `make(files)` returns its pixels (a pi.Image of rect's size) to be drawn at (x, y)
    with the plain "over".  vf1_game_art.render must use `layer.make(files)` in place of
    `pi.game_layer(files.image(layer.file), ...)` when a layer has `make` (see `render` below)."""
    what: str
    file: str
    rect: tuple
    x: int
    y: int
    scale: float = 1.0
    alpha: float = 1.0
    make: object = field(default=None, compare=False, repr=False)


def render(files: ga.GameFiles, art: ga.Art) -> pi.Image:
    """vf1_game_art.render, plus Computed layers."""
    art = ga.resolve(files, art)
    pieces = []
    for layer in art.layers:
        if isinstance(layer, ga.Fill):
            image = pi.Image(max(0, layer.w), max(0, layer.h))
            image.data[:] = bytes(layer.rgba) * (image.width * image.height)
        elif getattr(layer, "make", None) is not None:
            image = layer.make(files)
        else:
            image = pi.game_layer(files.image(layer.file), tuple(layer.rect), layer.scale, layer.alpha)
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


# ------------------------------------------------------------------ the map
def map_tiles() -> list[tuple[str, int, int]]:
    """(file, x, y) of the 16 tiles, in the loader's (and the draw's) order 0x495C60 / 0x495D90."""
    return [(f"MapX{x}Y{y}.jpg", TILE * x, TILE * y) for x in range(4) for y in range(4)]


def map_draws() -> list[pi.Draw]:
    return [pi.Draw("map", name, (0, 0, TILE, TILE), x, y) for name, x, y in map_tiles()]


def map_part(left: int, top: int, right: int, bottom: int) -> list[pi.Draw]:
    """The parts of the tiles inside the map rectangle (left, top, right, bottom), at their places."""
    out = []
    for name, x, y in map_tiles():
        x0, y0 = max(left, x), max(top, y)
        x1, y1 = min(right, x + TILE), min(bottom, y + TILE)
        if x1 > x0 and y1 > y0:
            out.append(pi.Draw("map", name, (x0 - x, y0 - y, x1 - x, y1 - y), x0, y0))
    return out


def map_image(files: ga.GameFiles) -> pi.Image:
    canvas = pi.Image(MAP_SIZE, MAP_SIZE)
    for name, x, y in map_tiles():
        tile = files.image(name)
        canvas.draw(tile, x, y)
    return canvas


# ------------------------------------------------------------------ the fill 0x403B40
def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def fill_bytes(rgb_floats: tuple[float, float, float], alpha: float) -> tuple[tuple[int, int, int], int]:
    """The colour bytes and the alpha 0x403B40 makes from its four float arguments: each colour float x 255
    truncated (0x403BA6..0x403C26), the alpha x 255 + 0.5 truncated (0x403CD6..0x403CE6)."""
    colour = tuple(int(f32(c) * 255.0) for c in rgb_floats)
    return colour, int(f32(alpha) * 255.0 + 0.5)


def blend_fill(image: pi.Image, colour: tuple[int, int, int], a: int) -> None:
    """0x403B40's blend over every pixel: each colour byte d becomes (d x (255 - a) >> 8) + (c x a >> 8)
    (0x403D60..0x403D92); the alpha byte is left alone."""
    for k in range(3):
        add = (colour[k] * a) >> 8
        table = bytes((((d * (255 - a)) >> 8) + add) & 0xFF for d in range(256))
        image.data[k::4] = bytes(image.data[k::4]).translate(table)


def fill_image(base: pi.Image, fills) -> pi.Image:
    out = base.copy()
    for rgb, alpha in fills:
        colour, a = fill_bytes(rgb, alpha)
        blend_fill(out, colour, a)
    return out


HAZE_GREY = (0.3, 0.3, 0.3)                 # 0x492147: the haze's colour, each 0.3 (0x4B6A34)
HAZE = {1: 0.2, 2: 0.3, 3: 0.3}             # 0x4922B8 / 0x4922D8 / 0x4922CC: the haze each weather fades to
FLASH = 0x7FFFF0E0                          # 0x4FDE6C, the lightning's colour as 0x408100 reads it (A R G B)
NIGHT_COLOUR = (0, 0, 0x66, 0xB2)           # 0x49197B: the night's R, G, B, A bytes (+0x658)


def colour_floats(value: int) -> tuple[tuple[float, float, float], float]:
    """0x408100: the colour dword's bytes / 255 as (first, second, third) floats and the alpha (top byte)."""
    a = (value >> 24) & 0xFF
    return (f32((value & 0xFF) / 255.0), f32(((value >> 8) & 0xFF) / 255.0), f32(((value >> 16) & 0xFF) / 255.0)), \
        f32(a / 255.0)


def night_alpha(darkness: float) -> int:
    """0x491A13..0x491A4A: the night colour's alpha byte 0xB2 x darkness + 0.5, truncated."""
    return int(NIGHT_COLOUR[3] * f32(darkness) + 0.5) & 0xFF


def night_fill(darkness: float) -> tuple[tuple[float, float, float], float]:
    r, g, b, _a = NIGHT_COLOUR
    return colour_floats(r | (g << 8) | (b << 16) | (night_alpha(darkness) << 24))


# ------------------------------------------------------------------ the lamps
LIGHT_MASKS = {1: 0xB3, 2: 0xB0, 3: 0xAE, 4: 0xAF, 5: 0xB1, 6: 0xB2, 7: 0xB3, 8: 0xB4, 9: 0xB5, 10: 0xB6,
               11: 0xB7}                    # 0x490ABE..0x490B30: a lamp's kind -> its light mask
LSMAP = "root:Assets/lsmap.dat"


def lamps(files: ga.GameFiles) -> list[tuple[int, int, int, int]]:
    """Assets\\lsmap.dat's 20 entries of 0x50 bytes (kind, x, y, villager), as 0x491550 reads them; kinds
    over 11 are skipped (0x4915F3)."""
    data = files.data(LSMAP)
    out = []
    for k in range(min(20, len(data) // 0x50)):
        kind, x, y, who = struct.unpack_from("<4i", data, k * 0x50)
        if 0 <= kind <= 11:
            out.append((kind, x, y, who))
    return out


def night_plan(files: ga.GameFiles, screen=(0, 0, MAP_SIZE, MAP_SIZE)) -> list[dict]:
    """For each lamp the game lights (0x490C90): its mask, the part of the mask that is on the screen (`rect`,
    in the mask) and where that part goes on the screen (x, y).  A lamp needs a kind with a mask (0x490A80),
    no villager to follow here (all of lsmap.dat's are fixed), and not the fixed kind 1 (0x490CEA)."""
    out = []
    for kind, x, y, who in lamps(files):
        if kind not in LIGHT_MASKS or (who == -1 and kind == 1):
            continue
        name = ga.TABLE[LIGHT_MASKS[kind]][0]
        if not files.has(name):
            continue
        w, h = files.size(name)
        cols = ga.TABLE[LIGHT_MASKS[kind]][1] or 1
        w //= cols
        x0, y0 = x - int(w / 2), y - int(h / 2)
        cx0, cy0 = max(x0, screen[0]), max(y0, screen[1])
        cx1, cy1 = min(x0 + w, screen[2]), min(y0 + h, screen[3])
        if cx1 <= cx0 or cy1 <= cy0:
            continue
        out.append({"mask": name, "rect": (cx0 - x0, cy0 - y0, cx1 - x0, cy1 - y0), "x": cx0, "y": cy0})
    return out


def night_image(files: ga.GameFiles, darkness: float, scene: pi.Image | None = None) -> pi.Image:
    """The whole map at night, as 0x4919D0 composes it over a screen as big as the map."""
    scene = map_image(files) if scene is None else scene
    copies = []
    for lamp in night_plan(files):
        x0, y0, x1, y1 = lamp["rect"]
        piece = scene.sub(lamp["x"], lamp["y"], x1 - x0, y1 - y0)
        mask = files.image(lamp["mask"]).sub(x0, y0, x1 - x0, y1 - y0)
        piece.data[3::4] = mask.data[3::4]               # 0x40B870: the mask's alpha byte, nothing else
        copies.append((piece, lamp["x"], lamp["y"]))
    out = fill_image(scene, [night_fill(darkness)])
    for piece, x, y in copies:
        out.draw(piece, x, y)
    return out


def computed(what: str, key: str, make) -> Computed:
    return Computed(what, f"computed:{key}", (0, 0, MAP_SIZE, MAP_SIZE), 0, 0, make=make)


# ------------------------------------------------------------------ the house pictures 0x420BC0
# (key, category, label, game state, how the test picks the draws, why, draws (file, rect, x, y, alpha)).
# The game state is set over a clean house (every repair done, nothing bought, the room levels 1, no food);
# tests/test_art_house.py runs the list builder for it and compares.
STATES = (
    ('house/tv/old', 'Furniture and objects/Television', 'Old television',
     {}, ('tvOld.png',),
     'Drawn in the living room until the flat-screen television is bought (0x420DB6).',
     (('tvOld.png', (0, 0, 130, 140), 1536, 552, 1.0),)),
    ('house/tv/flat', 'Furniture and objects/Television', 'Flat-screen television',
     {"bytes": {0x2C: 1}}, 'diff',
     'Drawn in the living room once the flat-screen television is bought (0x420DA3).',
     (('tvFlatscreen.png', (0, 0, 99, 104), 1564, 540, 1.0),)),
    ('house/toilet/open', 'Furniture and objects/Bathroom', 'Toilet, lid open',
     {}, ('toiletOpen.png',),
     'Drawn whenever the toilet is not in use (0x420919).',
     (('toiletOpen.png', (0, 0, 61, 114), 608, 727, 1.0),)),
    ('house/toilet/closed', 'Furniture and objects/Bathroom', 'Toilet, lid closed',
     {"props": [0x30]}, ('toiletClosed.png',),
     'Drawn while the toilet is in use (0x420901).',
     (('toiletClosed.png', (0, 0, 55, 119), 664, 727, 1.0),)),
    ('house/shower/curtain', 'Furniture and objects/Bathroom', 'Shower curtain drawn',
     {"props": [0x28]}, 'diff',
     'Drawn while someone showers (0x420563).',
     (('showerCurtain.png', (0, 0, 138, 165), 716, 546, 1.0),)),
    ('house/fridge/1/empty', 'Furniture and objects/Kitchen', 'Fridge open, nearly empty',
     {"food": 0, "props": [0x3]}, ('fridgeStates.png',),
     'Drawn while the fridge is open, with 100 food or less (0x4209B7).',
     (('fridgeStates.png', (0, 0, 39, 126), 1050, 274, 1.0),)),
    ('house/fridge/1/some', 'Furniture and objects/Kitchen', 'Fridge open, some food',
     {"food": 101, "props": [0x3]}, ('fridgeStates.png',),
     'Drawn while the fridge is open, with 101 to 999 food (0x4209FC).',
     (('fridgeStates.png', (39, 0, 78, 126), 1050, 274, 1.0),)),
    ('house/fridge/1/full', 'Furniture and objects/Kitchen', 'Fridge open, full',
     {"food": 1000, "props": [0x3]}, ('fridgeStates.png',),
     'Drawn while the fridge is open, with 1000 food or more (0x4209DD).',
     (('fridgeStates.png', (78, 0, 117, 126), 1050, 274, 1.0),)),
    ('house/fridge/3/empty', 'Furniture and objects/Kitchen', 'Fridge open, nearly empty (top kitchen)',
     {"food": 0, "props": [0x3], "tech": (3, 1, 1)}, ('fridgeStates.png',),
     'Drawn while the fridge of the fully upgraded kitchen is open, with 100 food or less (0x420969).',
     (('fridgeStates.png', (0, 126, 39, 252), 1050, 274, 1.0),)),
    ('house/fridge/3/some', 'Furniture and objects/Kitchen', 'Fridge open, some food (top kitchen)',
     {"food": 101, "props": [0x3], "tech": (3, 1, 1)}, ('fridgeStates.png',),
     'Drawn while the fridge of the fully upgraded kitchen is open, with 101 to 999 food (0x4209FC).',
     (('fridgeStates.png', (39, 126, 78, 252), 1050, 274, 1.0),)),
    ('house/fridge/3/full', 'Furniture and objects/Kitchen', 'Fridge open, full (top kitchen)',
     {"food": 1000, "props": [0x3], "tech": (3, 1, 1)}, ('fridgeStates.png',),
     'Drawn while the fridge of the fully upgraded kitchen is open, with 1000 food or more (0x42098F).',
     (('fridgeStates.png', (78, 126, 117, 252), 1050, 274, 1.0),)),
    ('house/garbage', 'Furniture and objects/Kitchen', 'Kitchen bin, full',
     {"bytes": {0x18C: 1}}, 'diff',
     'Drawn while the kitchen bin is full (0x4212D6).',
     (('kitchenGarbageFull.png', (0, 0, 34, 45), 1003, 354, 1.0),)),
    ('house/lightbulb', 'Furniture and objects/Fixtures', 'Light bulb',
     {}, ('lightbulb.png',),
     'Always drawn, in the laundry room (0x4212F4).',
     (('lightbulb.png', (0, 0, 16, 17), 740, 1010, 1.0),)),
    ('house/remote', 'Furniture and objects/Things left around', 'Remote control (it lies wherever it was put down)',
     {}, ('remote.png',),
     'Drawn where the remote was left, unless someone is holding it (0x42159E).',
     (('remote.png', (0, 0, 22, 17), 0, 0, 1.0),)),
    ('house/laundry/lights', 'Furniture and objects/Fixtures', "Laundry machines' green lights",
     {"props": [0x15]}, 'diff',
     'Drawn while the laundry machines run (0x42044C, 0x42046A).',
     (('greenLight.png', (0, 0, 6, 5), 532, 949, 1.0), ('greenLight.png', (0, 0, 6, 5), 500, 977, 1.0),)),
    ('house/office/redlight', 'Furniture and objects/Fixtures', 'Red light on the office desk',
     {"props": [0x16]}, 'diff',
     "Drawn while the house's red warning light is on (0x420499).",
     (('redLight.png', (0, 0, 6, 5), 952, 1172, 1.0),)),
    ('house/rosepetals', 'Furniture and objects/Bedroom', 'Rose petals on the bed',
     {"props": [0xD]}, 'diff',
     'Drawn while the bed is decorated with rose petals (0x4206DD).',
     (('rosepetalsOnBed.png', (0, 0, 172, 140), 1150, 810, 1.0),)),
    ('house/shed/door', 'House and yard/Repairs', 'Shed door hanging loose',
     {"bytes": {0x16C: 0}, "ints": {0x168: 1}}, 'diff',
     'Drawn until the shed is fixed (0x420FCC).',
     (('shedDoor.png', (0, 0, 102, 127), 303, 121, 1.0),)),
    ('house/shed/knob/door', 'House and yard/Repairs', 'Shed door with its knob back on',
     {"bytes": {0x16C: 0}, "ints": {0x168: 2}}, 'diff',
     'The knob is drawn on the door once it is put back, until the shed is fixed (0x421022).',
     (('shedDoor.png', (0, 0, 102, 127), 303, 121, 1.0), ('doorknob.png', (0, 0, 11, 12), 348, 186, 1.0),)),
    ('house/shed/knob/ground', 'House and yard/Repairs', 'Shed door and its fallen knob (the knob lies where it fell)',
     {"bytes": {0x16C: 0}, "ints": {0x168: 0}}, 'diff',
     'The knob is drawn where it fell while it is off the door (0x421022).',
     (('shedDoor.png', (0, 0, 102, 127), 303, 121, 1.0), ('doorknob.png', (0, 0, 11, 12), 0, 0, 1.0),)),
    ('house/floor/1/0', 'House and yard/Repairs', 'Damaged floor 1',
     {"bytes": {0x11C: 0}}, ('floorDamage.png',),
     'Drawn until this floor is fixed, fading as it is repaired (0x4213E1).',
     (('floorDamage.png', (0, 0, 70, 48), 1203, 620, 1.0),)),
    ('house/floor/1/9', 'House and yard/Repairs', 'Damaged floor 1, half repaired',
     {"bytes": {0x11C: 0}, "ints": {0x118: 9}}, ('floorDamage.png',),
     'Half way through the repair the damage is drawn at half strength (0x4213E1).',
     (('floorDamage.png', (0, 0, 70, 48), 1203, 620, 0.5),)),
    ('house/floor/1/15', 'House and yard/Repairs', 'Damaged floor 1, nearly repaired',
     {"bytes": {0x11C: 0}, "ints": {0x118: 15}}, ('floorDamage.png',),
     'Near the end of the repair the damage is drawn at its weakest, 20% (0x4213BA).',
     (('floorDamage.png', (0, 0, 70, 48), 1203, 620, 0.20000000298023224),)),
    ('house/floor/2/0', 'House and yard/Repairs', 'Damaged floor 2',
     {"bytes": {0x12C: 0}}, ('floorDamage.png',),
     'Drawn until this floor is fixed, fading as it is repaired (0x421489).',
     (('floorDamage.png', (70, 0, 140, 48), 919, 964, 1.0),)),
    ('house/floor/2/9', 'House and yard/Repairs', 'Damaged floor 2, half repaired',
     {"bytes": {0x12C: 0}, "ints": {0x128: 9}}, ('floorDamage.png',),
     'Half way through the repair the damage is drawn at half strength (0x421489).',
     (('floorDamage.png', (70, 0, 140, 48), 919, 964, 0.5),)),
    ('house/floor/2/15', 'House and yard/Repairs', 'Damaged floor 2, nearly repaired',
     {"bytes": {0x12C: 0}, "ints": {0x128: 15}}, ('floorDamage.png',),
     'Near the end of the repair the damage is drawn at its weakest, 20% (0x421462).',
     (('floorDamage.png', (70, 0, 140, 48), 919, 964, 0.20000000298023224),)),
    ('house/floor/3/0', 'House and yard/Repairs', 'Damaged floor 3',
     {"bytes": {0x13C: 0}}, ('floorDamage.png',),
     'Drawn until this floor is fixed, fading as it is repaired (0x421531).',
     (('floorDamage.png', (140, 0, 210, 48), 1020, 1080, 1.0),)),
    ('house/floor/3/9', 'House and yard/Repairs', 'Damaged floor 3, half repaired',
     {"bytes": {0x13C: 0}, "ints": {0x138: 9}}, ('floorDamage.png',),
     'Half way through the repair the damage is drawn at half strength (0x421531).',
     (('floorDamage.png', (140, 0, 210, 48), 1020, 1080, 0.5),)),
    ('house/floor/3/15', 'House and yard/Repairs', 'Damaged floor 3, nearly repaired',
     {"bytes": {0x13C: 0}, "ints": {0x138: 15}}, ('floorDamage.png',),
     'Near the end of the repair the damage is drawn at its weakest, 20% (0x42150A).',
     (('floorDamage.png', (140, 0, 210, 48), 1020, 1080, 0.20000000298023224),)),
    ('house/wall/cracked', 'House and yard/Repairs', 'Cracked walls',
     {"bytes": {0x15C: 0}}, ('stucco.png',),
     'Both cracks are drawn until the walls are fixed (0x420EA0, 0x420FA2).',
     (('stucco.png', (106, 0, 212, 106), 450, 583, 1.0), ('stucco.png', (0, 0, 106, 106), 209, 686, 1.0),)),
    ('house/wall/half', 'House and yard/Repairs', 'Cracked walls, half plastered',
     {"bytes": {0x15C: 0}, "ints": {0x158: 3, 0x160: 12, 0x164: 12}}, ('stucco.png',),
     'While the walls are plastered each crack fades with its own progress (0x420ECA, 0x420F66).',
     (('stucco.png', (106, 0, 212, 106), 450, 583, 0.5), ('stucco.png', (0, 0, 106, 106), 209, 686, 0.5),)),
    ('house/puddle/toilet', 'House and yard/Leaks and puddles', 'Puddle by the toilet',
     {"props": [0x19]}, 'diff',
     'Drawn while the toilet leaks (0x420D61).',
     (('puddles.png', (88, 0, 176, 82), 639, 806, 1.0),)),
    ('house/puddle/bath', 'House and yard/Leaks and puddles', 'Puddle by the bathtub',
     {"props": [0x1A]}, 'diff',
     'Drawn while the bathtub leaks (0x420D8A).',
     (('puddles.png', (88, 0, 176, 82), 775, 665, 1.0),)),
    ('house/puddle/sinks', 'House and yard/Leaks and puddles', 'Puddle by the bathroom sinks',
     {"props": [0x1B]}, 'diff',
     'Drawn while either of the two bathroom leaks is on (0x420CE2, 0x420D0F).',
     (('puddles.png', (0, 0, 88, 82), 879, 689, 1.0),)),
    ('house/puddle/kitchen', 'House and yard/Leaks and puddles', 'Puddle by the kitchen sink',
     {"props": [0x1E]}, 'diff',
     'Drawn while the kitchen sink leaks (0x420D38).',
     (('puddles.png', (0, 0, 88, 82), 1189, 319, 1.0),)),
    ('house/puddle/hose', 'House and yard/Leaks and puddles', 'Puddle by the garden hose',
     {"bytes": {0x1DC: 0}}, ('puddles.png',),
     'Drawn until the garden hose is fixed (0x421693).',
     (('puddles.png', (88, 0, 176, 82), 1503, 425, 1.0),)),
    ('house/fountain', 'House and yard/Repairs', 'Bird bath with water',
     {"bytes": {0x1EC: 1}}, 'diff',
     'Drawn once the bird bath is fixed (0x42126E).',
     (('fountainwater.png', (0, 0, 83, 68), 1718, 1495, 1.0),)),
    ('house/hole/1/small', 'House and yard/Yard holes', 'Small hole in the yard (place 1)',
     {"props": [0x5]}, 'diff',
     'Drawn while this hole is dug (0x42021C).',
     (('holeSM1.png', (0, 0, 74, 60), 1667, 1389, 1.0),)),
    ('house/hole/1/large', 'House and yard/Yard holes', 'Large hole in the yard (place 1)',
     {"props": [0x6]}, 'diff',
     'Drawn while this hole is dug (0x42024B).',
     (('holeLG1.png', (0, 0, 74, 60), 1667, 1389, 1.0),)),
    ('house/hole/1/gopher', 'House and yard/Yard holes', 'Gopher in a hole (place 1)',
     {"props": [0x7]}, 'diff',
     'Drawn while the gopher looks out (0x42027A).',
     (('gopherInHole.png', (0, 0, 74, 60), 1667, 1389, 1.0),)),
    ('house/hole/2/small', 'House and yard/Yard holes', 'Small hole in the yard (place 2)',
     {"props": [0x8]}, 'diff',
     'Drawn while this hole is dug (0x4202A9).',
     (('holeSM1.png', (0, 0, 74, 60), 1897, 1394, 1.0),)),
    ('house/hole/2/large', 'House and yard/Yard holes', 'Large hole in the yard (place 2)',
     {"props": [0x9]}, 'diff',
     'Drawn while this hole is dug (0x4202D8).',
     (('holeLG1.png', (0, 0, 74, 60), 1897, 1394, 1.0),)),
    ('house/hole/2/gopher', 'House and yard/Yard holes', 'Gopher in a hole (place 2)',
     {"props": [0xA]}, 'diff',
     'Drawn while the gopher looks out (0x420307).',
     (('gopherInHole.png', (0, 0, 74, 60), 1897, 1394, 1.0),)),
    ('house/hole/3/small', 'House and yard/Yard holes', 'Small hole in the yard (place 3)',
     {"props": [0xB]}, 'diff',
     'Drawn while this hole is dug (0x420336).',
     (('holeSM1.png', (0, 0, 74, 60), 1513, 1557, 1.0),)),
    ('house/hole/3/large', 'House and yard/Yard holes', 'Large hole in the yard (place 3)',
     {"props": [0xC]}, 'diff',
     'Drawn while this hole is dug (0x420365).',
     (('holeLG1.png', (0, 0, 74, 60), 1513, 1557, 1.0),)),
    ('house/buy/paintings', 'Furniture and objects/Bought for the house', 'Paintings',
     {"bytes": {0x3C: 1}}, 'diff',
     'Drawn once the paintings are bought (0x421150, 0x421170, 0x421190).',
     (('paintings.png', (0, 0, 50, 71), 1114, 791, 1.0), ('paintings.png', (50, 0, 100, 71), 1166, 756, 1.0), ('paintings.png', (100, 0, 150, 71), 963, 309, 1.0),)),
    ('house/buy/airpurifier', 'Furniture and objects/Bought for the house', 'Air purifier',
     {"bytes": {0x4C: 1}}, 'diff',
     'Drawn once the air purifier is bought (0x420DF1).',
     (('airPurifier.png', (0, 0, 37, 57), 804, 1171, 1.0),)),
    ('house/buy/toolbox', 'Furniture and objects/Bought for the house', 'Toolbox',
     {"bytes": {0x5C: 1}}, 'diff',
     'Drawn once the toolbox is bought (0x421214).',
     (('toolbox.png', (0, 0, 58, 54), 146, 518, 1.0),)),
    ('house/buy/bed', 'Furniture and objects/Bought for the house', 'New bed',
     {"bytes": {0x6C: 1}}, 'diff',
     'Drawn once the bed upgrade is bought (0x42131E).',
     (('bedUpgrade.png', (0, 0, 248, 225), 1152, 748, 1.0),)),
    ('house/buy/fishtank', 'Furniture and objects/Bought for the house', 'Fish tank',
     {"bytes": {0x7C: 1}}, 'diff',
     'Drawn once the fish tank is bought (0x4210CD).',
     (('fishtank.png', (0, 0, 69, 83), 898, 366, 1.0),)),
    ('house/buy/towels', 'Furniture and objects/Bought for the house', 'Towels',
     {"bytes": {0x8C: 1}}, 'diff',
     'Drawn once the towels are bought (0x42134D, 0x42136D).',
     (('towelUpgrade.png', (0, 0, 50, 88), 756, 753, 1.0), ('towelUpgrade.png', (50, 0, 100, 88), 857, 622, 1.0),)),
    ('house/buy/treadmill', 'Furniture and objects/Bought for the house', 'Treadmill',
     {"bytes": {0x9C: 1}}, 'diff',
     'Drawn once the treadmill is bought (0x421241).',
     (('treadmill.png', (0, 0, 125, 119), 351, 1007, 1.0),)),
    ('house/buy/radio', 'Furniture and objects/Bought for the house', 'Radio',
     {"bytes": {0xAC: 1}}, 'diff',
     'Drawn once the radio is bought (0x4211EA).',
     (('radio.png', (0, 0, 40, 40), 1569, 782, 1.0),)),
    ('house/buy/pinball', 'Furniture and objects/Bought for the house', 'Pinball machine',
     {"bytes": {0xBC: 1}}, 'diff',
     'Drawn once the pinball machine is bought (0x4211BD).',
     (('pinball.png', (0, 0, 80, 100), 402, 958, 1.0),)),
    ('house/buy/patio', 'Furniture and objects/Bought for the house', 'Patio set',
     {"bytes": {0xCC: 1}}, 'diff',
     'Drawn once the patio set is bought (0x42104C).',
     (('patioSet.png', (0, 0, 240, 240), 39, 1364, 1.0),)),
    ('house/buy/pool', 'Furniture and objects/Bought for the house', 'Pool',
     {"bytes": {0xDC: 1}}, 'diff',
     'Drawn once the pool is bought (0x421079).',
     (('pool.png', (0, 0, 328, 259), 160, 1637, 1.0),)),
    ('house/buy/hammock', 'Furniture and objects/Bought for the house', 'Hammock',
     {"bytes": {0xEC: 1}}, 'diff',
     'Drawn once the hammock is bought (0x4210A3).',
     (('hammock.png', (0, 0, 235, 162), 690, 30, 1.0),)),
    ('house/buy/bbq', 'Furniture and objects/Bought for the house', 'Barbecue',
     {"bytes": {0xFC: 1}}, 'diff',
     'Drawn once the barbecue is bought (0x4210FA).',
     (('bbq.png', (0, 0, 100, 100), 1303, 1425, 1.0),)),
    ('house/buy/birdhouse', 'Furniture and objects/Bought for the house', 'Birdhouse',
     {"bytes": {0x10C: 1}}, 'diff',
     'Drawn once the birdhouse is bought (0x421124).',
     (('birdhouse.png', (0, 0, 60, 100), 91, 203, 1.0),)),
    ('house/buy/balconyflowers', 'Furniture and objects/Bought for the house', 'Balcony flowers',
     {"bytes": {0x1AC: 1}}, 'diff',
     'Drawn once the balcony flowers are bought (0x4215D1, 0x4215F1, 0x421611, 0x421631).',
     (('balconyflowers.png', (0, 0, 45, 28), 1678, 931, 1.0), ('balconyflowers.png', (45, 0, 90, 28), 1768, 905, 1.0), ('balconyflowers.png', (90, 0, 135, 28), 1809, 870, 1.0), ('balconyflowers.png', (135, 0, 180, 28), 1851, 824, 1.0),)),
    ('house/food/cans', 'Food and cooking/In the kitchen', 'Cans on the counter (500 food or more)',
     {"food": 500}, 'diff',
     'Drawn while there are 500 food or more (0x4216E7).',
     (('cans.png', (0, 0, 31, 36), 1021, 276, 1.0),)),
    ('house/food/bread', 'Food and cooking/In the kitchen', 'Bread and cans (1000 food or more)',
     {"food": 1000}, 'diff',
     'Bread is drawn while there are 1000 food or more, with the cans (0x4216BD, 0x4216E7).',
     (('breads.png', (0, 0, 69, 58), 1139, 190, 1.0), ('cans.png', (0, 0, 31, 36), 1021, 276, 1.0),)),
    ('house/food/meal', 'Food and cooking/In the kitchen', 'Meal on the kitchen table',
     {"props": [0x21]}, 'diff',
     'Drawn while a meal is served (0x420505).',
     (('meal.png', (0, 0, 160, 68), 970, 430, 1.0),)),
    ('house/food/bbqmeat', 'Food and cooking/In the kitchen', 'Meat on the barbecue',
     {"props": [0x22]}, 'diff',
     'Drawn while meat is on the barbecue (0x420534).',
     (('bbqmeat.png', (0, 0, 56, 42), 1324, 1449, 1.0),)),
    ('house/food/prep1', 'Food and cooking/In the kitchen', 'Food being prepared (counter, first stage)',
     {"props": [0xE]}, 'diff',
     'Drawn while food is prepared on the counter (0x4207AB).',
     (('foodWork1.png', (0, 0, 60, 60), 1285, 285, 1.0),)),
    ('house/food/prep2', 'Food and cooking/In the kitchen', 'Food being prepared (counter, second stage)',
     {"props": [0xF]}, 'diff',
     'Drawn while food is prepared on the counter (0x4207DC).',
     (('foodWork1.png', (60, 0, 120, 60), 1312, 295, 1.0),)),
    ('house/cook/pan1', 'Food and cooking/In the kitchen', 'Saucepan on the stove (place 1)',
     {"props": [0x25]}, 'diff',
     'Drawn while this pan is on the stove (0x4206E7).',
     (('carrying.png', (560, 56, 616, 112), 1069, 260, 1.0),)),
    ('house/cook/pan2', 'Food and cooking/In the kitchen', 'Saucepan on the stove (place 2)',
     {"props": [0x29]}, 'diff',
     'Drawn while this pan is on the stove (0x42077A).',
     (('carrying.png', (560, 56, 616, 112), 1092, 274, 1.0),)),
    ('house/cook/pan3', 'Food and cooking/In the kitchen', 'Saucepan on the stove (place 3)',
     {"props": [0x2A]}, 'diff',
     'Drawn while this pan is on the stove (0x420592).',
     (('carrying.png', (560, 56, 616, 112), 1076, 242, 1.0),)),
    ('house/cook/fryingpan', 'Food and cooking/In the kitchen', 'Frying pan on the stove',
     {"props": [0x27]}, 'diff',
     'Drawn while the frying pan is on the stove (0x420749).',
     (('carrying.png', (672, 56, 728, 112), 1094, 254, 1.0),)),
    ('house/cook/vegpan', 'Food and cooking/In the kitchen', 'Pan of vegetables on the stove',
     {"props": [0x2D]}, 'diff',
     'Drawn while this pan is on the stove (0x4205C3).',
     (('carrying.png', (112, 112, 168, 168), 1094, 254, 1.0),)),
    ('house/cook/pot1', 'Food and cooking/In the kitchen', 'Pot of stew on the stove',
     {"props": [0x2B]}, 'diff',
     'Drawn while this pot is on the stove (0x4205F4).',
     (('carrying.png', (616, 56, 672, 112), 1064, 250, 1.0),)),
    ('house/cook/pot2', 'Food and cooking/In the kitchen', 'Empty pot on the stove',
     {"props": [0x2C]}, 'diff',
     'Drawn while this pot is on the stove (0x420625).',
     (('carrying.png', (224, 112, 280, 168), 1064, 250, 1.0),)),
    ('house/cook/pots', 'Food and cooking/In the kitchen', 'Pots by the sink',
     {"props": [0x2E]}, 'diff',
     'Drawn while the pots wait by the sink (0x420656).',
     (('carrying.png', (0, 112, 56, 168), 1248, 264, 1.0),)),
    ('house/cook/dishes', 'Food and cooking/In the kitchen', 'Dishes by the sink',
     {"props": [0x2F]}, 'diff',
     'Drawn while the dishes wait by the sink (0x420687).',
     (('carrying.png', (672, 224, 728, 280), 1248, 275, 1.0),)),
    ('house/left/paper', 'Furniture and objects/Things left around', 'Paper on the kitchen counter',
     {"props": [0x11]}, 'diff',
     'Drawn while it is left there (0x42080D).',
     (('carrying.png', (112, 224, 168, 280), 920, 408, 1.0),)),
    ('house/left/basket1', 'Furniture and objects/Things left around', "Laundry basket in the children's room",
     {"props": [0x12]}, 'diff',
     'Drawn while it is left there (0x420394).',
     (('carrying.png', (280, 0, 336, 56), 1448, 1048, 1.0),)),
    ('house/left/basket2', 'Furniture and objects/Things left around', 'Laundry basket in the bedroom',
     {"props": [0x13]}, 'diff',
     'Drawn while it is left there (0x4203C5).',
     (('carrying.png', (280, 0, 336, 56), 1184, 909, 1.0),)),
    ('house/left/basket3', 'Furniture and objects/Things left around', 'Laundry basket in the laundry room',
     {"props": [0x14]}, 'diff',
     'Drawn while it is left there (0x4203F6).',
     (('carrying.png', (280, 0, 336, 56), 475, 924, 1.0),)),
    ('house/left/newspapers', 'Furniture and objects/Things left around', 'Newspapers in the living room',
     {"props": [0x17]}, 'diff',
     'Drawn while they are left there (0x4204A3).',
     (('carrying.png', (560, 168, 616, 224), 1736, 727, 1.0),)),
    ('house/left/boardgame', 'Furniture and objects/Things left around', "Board game in the children's room",
     {"props": [0x18]}, 'diff',
     'Drawn while it is left there (0x4204D4).',
     (('carrying.png', (504, 112, 560, 168), 1263, 1009, 1.0),)),
    ('house/left/bottle', 'Furniture and objects/Things left around', 'Bottle on the lawn by the patio',
     {"props": [0x26]}, 'diff',
     'Drawn while it is left there (0x420718).',
     (('carrying.png', (448, 56, 504, 112), 173, 1505, 1.0),)),
    ('house/workroom/project1', 'Furniture and objects/Workroom', 'Project on the workbench (first stage)',
     {"props": [0x32]}, 'diff',
     'Drawn while a project is under way (0x42083E).',
     (('carrying.png', (112, 224, 168, 280), 385, 508, 1.0), ('workWork1.png', (0, 0, 67, 58), 430, 530, 1.0),)),
    ('house/workroom/project2', 'Furniture and objects/Workroom', 'Project on the workbench (second stage)',
     {"props": [0x33]}, 'diff',
     'Drawn while a project is under way (0x42088F).',
     (('carrying.png', (112, 224, 168, 280), 385, 508, 1.0), ('workWork1.png', (67, 0, 134, 58), 468, 552, 1.0),)),
    ('house/room/kitchen/2', 'House and yard/Rooms', 'Kitchen upgrade, level 2 (picture only)',
     {"tech": (2, 1, 1)}, 'diff',
     'Drawn once the kitchen is at level 2 (0x420C29).',
     (('kitchenUpgrade.png', (0, 0, 582, 512), 838, 137, 1.0),)),
    ('house/room/kitchen/3', 'House and yard/Rooms', 'Kitchen upgrade, level 3 (picture only)',
     {"tech": (3, 1, 1)}, 'diff',
     'Drawn once the kitchen is at level 3 (0x420C29).',
     (('kitchenUpgrade.png', (582, 0, 1164, 512), 838, 137, 1.0),)),
    ('house/room/office/2', 'House and yard/Rooms', 'Office upgrade, level 2 (picture only)',
     {"tech": (1, 2, 1)}, 'diff',
     'Drawn once the office is at level 2 (0x420C86).',
     (('officeUpgrade.png', (0, 0, 375, 241), 820, 1072, 1.0),)),
    ('house/room/office/3', 'House and yard/Rooms', 'Office upgrade, level 3 (picture only)',
     {"tech": (1, 3, 1)}, 'diff',
     'Drawn once the office is at level 3 (0x420C86).',
     (('officeUpgrade.png', (375, 0, 750, 241), 820, 1071, 1.0),)),
    ('house/room/workroom/2', 'House and yard/Rooms', 'Workroom upgrade, level 2 (picture only)',
     {"tech": (1, 1, 2)}, 'diff',
     'Drawn once the workroom is at level 2 (0x420CDD).',
     (('workroomUpgrade.png', (0, 0, 497, 457), 69, 356, 1.0),)),
    ('house/room/workroom/3', 'House and yard/Rooms', 'Workroom upgrade, level 3 (picture only)',
     {"tech": (1, 1, 3)}, 'diff',
     'Drawn once the workroom is at level 3 (0x420CDD).',
     (('workroomUpgrade.png', (497, 0, 994, 457), 67, 357, 1.0),)),
)
# 0x420BC0 with every room at level 3 and every house upgrade bought (EVERYTHING_SETUP), in the draw order.
EVERYTHING = (
    ('kitchenUpgrade.png', (582, 0, 1164, 512), 838, 137, 1.0),
    ('officeUpgrade.png', (375, 0, 750, 241), 820, 1071, 1.0),
    ('workroomUpgrade.png', (497, 0, 994, 457), 67, 357, 1.0),
    ('tvFlatscreen.png', (0, 0, 99, 104), 1564, 540, 1.0),
    ('airPurifier.png', (0, 0, 37, 57), 804, 1171, 1.0),
    ('patioSet.png', (0, 0, 240, 240), 39, 1364, 1.0),
    ('pool.png', (0, 0, 328, 259), 160, 1637, 1.0),
    ('hammock.png', (0, 0, 235, 162), 690, 30, 1.0),
    ('fishtank.png', (0, 0, 69, 83), 898, 366, 1.0),
    ('bbq.png', (0, 0, 100, 100), 1303, 1425, 1.0),
    ('birdhouse.png', (0, 0, 60, 100), 91, 203, 1.0),
    ('paintings.png', (0, 0, 50, 71), 1114, 791, 1.0),
    ('paintings.png', (50, 0, 100, 71), 1166, 756, 1.0),
    ('paintings.png', (100, 0, 150, 71), 963, 309, 1.0),
    ('pinball.png', (0, 0, 80, 100), 402, 958, 1.0),
    ('radio.png', (0, 0, 40, 40), 1569, 782, 1.0),
    ('toolbox.png', (0, 0, 58, 54), 146, 518, 1.0),
    ('treadmill.png', (0, 0, 125, 119), 351, 1007, 1.0),
    ('fountainwater.png', (0, 0, 83, 68), 1718, 1495, 1.0),
    ('lightbulb.png', (0, 0, 16, 17), 740, 1010, 1.0),
    ('bedUpgrade.png', (0, 0, 248, 225), 1152, 748, 1.0),
    ('towelUpgrade.png', (0, 0, 50, 88), 756, 753, 1.0),
    ('towelUpgrade.png', (50, 0, 100, 88), 857, 622, 1.0),
    ('remote.png', (0, 0, 22, 17), 0, 0, 1.0),
    ('balconyflowers.png', (0, 0, 45, 28), 1678, 931, 1.0),
    ('balconyflowers.png', (45, 0, 90, 28), 1768, 905, 1.0),
    ('balconyflowers.png', (90, 0, 135, 28), 1809, 870, 1.0),
    ('balconyflowers.png', (135, 0, 180, 28), 1851, 824, 1.0),
    ('breads.png', (0, 0, 69, 58), 1139, 190, 1.0),
    ('cans.png', (0, 0, 31, 36), 1021, 276, 1.0),
    ('toiletOpen.png', (0, 0, 61, 114), 608, 727, 1.0),
)


EVERYTHING_SETUP = {"bytes": {0x2C: 1, 0x3C: 1, 0x4C: 1, 0x5C: 1, 0x6C: 1, 0x7C: 1, 0x8C: 1, 0x9C: 1, 0xAC: 1,
                              0xBC: 1, 0xCC: 1, 0xDC: 1, 0xEC: 1, 0xFC: 1, 0x10C: 1, 0x1AC: 1, 0x1EC: 1},
                    "tech": (3, 3, 3), "food": 1000}

# The rooms: (name, room index in CTech, level 2 draw, level 3 draw) from 0x420BC0's three room tests.
ROOMS = (
    ("Kitchen", "kitchen", ("kitchenUpgrade.png", 838, 137), ("kitchenUpgrade.png", 838, 137), "0x420C29"),
    ("Office", "office", ("officeUpgrade.png", 820, 1072), ("officeUpgrade.png", 820, 1071), "0x420C86"),
    ("Workroom", "workroom", ("workroomUpgrade.png", 69, 356), ("workroomUpgrade.png", 67, 357), "0x420CDD"),
)

# The animations SetProp starts: (key, label, picture id, columns, rows, frames, place, frame delay, the prop,
# the flat-screen television or not, the code that starts it).
ANIMATIONS = (
    ("tv/old", "Old television showing a picture", 0x81, 6, 3, 18, (1573, 600), 35, 0x31, False, "0x493B06"),
    ("tv/flat", "Flat-screen television showing a picture", 0x80, 6, 3, 18, (1577, 555), 35, 0x31, True, "0x493AE5"),
    ("computer/east", "Office computer screen (left)", 0x84, 6, 2, 12, (910, 1188), 40, 0x23, False, "0x493B27"),
    ("computer/west", "Office computer screen (right)", 0x85, 6, 2, 12, (1094, 1213), 33, 0x24, False, "0x493B4D"),
)
TV_SETS = {False: ("tvOld.png", (0, 0, 130, 140), 1536, 552), True: ("tvFlatscreen.png", (0, 0, 99, 104), 1564, 540)}


def _layers(rows) -> tuple:
    return tuple(pi.Draw("house", f, tuple(r), x, y, 1.0, a) for f, r, x, y, a in rows)


def _have(files: ga.GameFiles, layers) -> bool:
    return all(files.has(layer.file) for layer in layers if not isinstance(layer, Computed))


def _cell(files: ga.GameFiles, image: int, k: int) -> tuple[str, tuple[int, int, int, int]]:
    name, cols, rows, _n = ga.TABLE[image]
    cols = cols or 1
    rows = rows or 1
    return name, ga.cell_rect(files.size(name), cols, rows, k % cols, k // cols)[1]


def effect_frames(files: ga.GameFiles, image: int, frames: int, x: int, y: int, centred: bool,
                  rise: int = 0) -> list[pi.Draw]:
    """Each frame of an effect drawn by 0x421A30 at (x, y): centred effects are moved up and left by half a
    cell (0x421A8E..0x421AA0); a rising one (motion 0, 0x42196F) is 2 higher at every new frame."""
    out = []
    for k in range(frames):
        name, rect = _cell(files, image, k)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        dx, dy = (int(w / 2), int(h / 2)) if centred else (0, 0)
        out.append(pi.Draw("effect", name, rect, x - dx, y - dy - rise * k))
    return out


def arts(files: ga.GameFiles) -> list[ga.Art]:
    out: list[ga.Art] = []

    def add(key, category, label, layers, used, why, checked):
        layers = tuple(layers)
        if _have(files, layers):
            out.append(ga.Art(key, category, label, layers, used, why, checked))

    map_check = CHECKED.format(code="the map loader 0x495C60 and draw 0x495D90")
    list_check = CHECKED.format(code="the house list 0x420BC0 / 0x420200 and its draw 0x420130")
    add("house/map", "House and yard", "The whole house and yard (the 16 map tiles)", map_draws(), True,
        "The house screen's background, drawn first (0x445905 -> 0x495D90).", map_check)

    # the rooms at every level, the map's part under them plus the upgrade picture
    for title, word, two, three, code in ROOMS:
        pics = [(two, 0), (three, 1)]
        boxes = []
        for (name, x, y), cell in pics:
            if not files.has(name):
                break
            _n, rect = _cell(files, _IDS[name], cell)
            boxes.append((x, y, x + rect[2] - rect[0], y + rect[3] - rect[1], name, rect))
        if len(boxes) != 2:
            continue
        region = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                  max(b[3] for b in boxes))
        part = map_part(*region)
        add(f"house/room/{word}/1/assembled", "House and yard/Rooms", f"{title}, level 1 (as the map has it)",
            part, True, f"Level 1 is the map itself; no upgrade picture is drawn ({code}).", map_check)
        for level, box in ((2, boxes[0]), (3, boxes[1])):
            draw = pi.Draw("house", box[4], box[5], box[0], box[1])
            add(f"house/room/{word}/{level}/assembled", "House and yard/Rooms", f"{title}, level {level}",
                part + [draw], True,
                f"The upgrade picture is drawn over the map once the room is at level {level} ({code}). {LIST_DRAW}",
                list_check)

    for key, category, label, _setup, _mode, why, rows in STATES:
        add(key, category, label, _layers(rows), True, f"{why} {LIST_DRAW}", list_check)

    everything = [d for d in _layers(EVERYTHING) if d.file != "remote.png"]
    add("house/everything", "House and yard", "The house with every room upgrade and everything bought",
        map_draws() + everything, True,
        "The map, then the house list with every room at level 3 and every house upgrade bought; the remote is "
        f"left out, as it lies wherever it was put down (0x420BC0). {LIST_DRAW}", list_check)

    # the animations, each frame on its television or alone
    anim_check = CHECKED.format(code="CEnvironment::SetProp 0x4938C0 and the effect draw 0x421A30")
    for key, label, image, _c, _r, frames, (x, y), delay, _prop, flat, code in ANIMATIONS:
        name = ga.TABLE[image][0]
        if not files.has(name):
            continue
        for k, frame in enumerate(effect_frames(files, image, frames, x, y, False)):
            layers = [frame]
            if key.startswith("tv/"):
                f, r, tx, ty = TV_SETS[flat]
                layers = [pi.Draw("house", f, r, tx, ty), frame]
            add(f"house/anim/{key}/{k}", "Furniture and objects/Animations", f"{label}, frame {k + 1} of {frames}",
                layers, True,
                f"Started while it is switched on ({code}); its frames play in order and loop, each for {delay} "
                "steps of the effect clock (one step every 7 calls of 0x421B50, from a random first frame, "
                "0x4218F8); drawn over the house pictures by 0x421A30.", anim_check)

    # weather
    weather_check = CHECKED.format(code="the weather draw 0x4920F0")
    if files.has("sunbeam.png"):
        w, h = files.size("sunbeam.png")
        add("house/weather/sunbeam", "Weather, day and night/Weather", "Sunbeam, at full strength",
            [pi.Draw("weather", "sunbeam.png", (0, 120, w, h), 0, 0, 1.0, 1.0)], True,
            "In sunbeam weather 64 beams hang from the top of the screen (0x492165 -> 0x492040): each is drawn "
            "only while its top is above the screen, at its fade x the weather's strength, and fades in over the "
            "top 120 pixels (0x49206A..0x492088); this is a beam 120 pixels up, fully faded in.",
            CHECKED.format(code="the sunbeam draw 0x492040"))
    for k, rows in (("rain", RAINDROP_FRAMES), ("rainbow", RAINBOW_FRAMES)):
        image = 0x79 if k == "rain" else 0x61
        name = ga.TABLE[image][0]
        if not files.has(name):
            continue
        frames = effect_frames(files, image, len(rows), 0, 0, True, rise=0 if k == "rain" else 2)
        for n, frame in enumerate(frames):
            if k == "rain":
                add(f"house/weather/raindrop/{n}", "Weather, day and night/Weather",
                    f"Raindrop splash, frame {n + 1} of {len(frames)}", [frame], True,
                    "In rain, splashes land at random spots of the yard's ground (0x491CB8..0x491CF3: its material 2; "
                    "on water a ripple is drawn instead); each plays its 3 frames once, one frame per effect-clock "
                    "step, centred on the spot (here at 0, 0).",
                    CHECKED.format(code="AddEffect 0x421810, the clock 0x421B50 and the draw 0x421A30"))
            else:
                add(f"house/weather/rainbow/{n}", "Weather, day and night/Rainbow",
                    f"Rainbow over a villager, frame {n + 1} of {len(frames)}", [frame], True,
                    "Rises over a villager the player clicks, in the branch of 0x4422E0 that raises a need by 10 "
                    "(0x442704): centred on the villager's middle (here at 0, 0), its 10 frames play once, one per "
                    "effect-clock step, 2 pixels higher each frame.",
                    CHECKED.format(code="AddEffect 0x421810, the clock 0x421B50 and the draw 0x421A30"))

    tiles = all(files.has(name) for name, _x, _y in map_tiles())
    if tiles:
        def hazed(kind):
            return lambda f: fill_image(map_image(f), [(HAZE_GREY, HAZE[kind])])

        add("house/weather/haze/1", "Weather, day and night/Weather", "Daytime haze in sunbeam weather (over the map)",
            [computed("haze", "haze/1", hazed(1))], True,
            "By day the screen is filled with grey 76, 76, 76 at the weather's haze, which fades to 0.2 in sunbeam "
            "weather (0x4922B8 -> 0x492160 -> 0x408190 -> 0x403B40, with the fill's own blend).", weather_check)
        add("house/weather/haze/2", "Weather, day and night/Weather", "Daytime haze in rain or storm (over the map)",
            [computed("haze", "haze/2", hazed(2))], True,
            "By day the screen is filled with grey 76, 76, 76 at the weather's haze, which fades to 0.3 in rain "
            "and storms (0x4922CC -> 0x492160 -> 0x408190 -> 0x403B40, with the fill's own blend).", weather_check)
        add("house/weather/lightning", "Weather, day and night/Weather", "Lightning flash in a daytime storm (over the map)",
            [computed("flash", "lightning",
                      lambda f: fill_image(map_image(f), [(HAZE_GREY, HAZE[3]), colour_floats(FLASH)]))], True,
            "In a storm, after the haze, a flash fills the screen with 224, 240, 255 at alpha 127 for 50 of the "
            "game's clock ticks at random times (0x4909F0, 0x490930; 0x408100 -> 0x403B40).", weather_check)
        for level, words in ((1.0, "deep night (midnight to the morning twilight)"),
                             (0.8500000238418579, "night (from two hours after sunset)"),
                             (0.6499999761581421, "evening (the first two hours after sunset)")):
            add(f"house/night/{level:.2f}", "Weather, day and night/Night", f"The map at {words}",
                [computed("night", f"night/{level:.2f}", lambda f, d=level: night_image(f, d))], True,
                f"Darkness {f32(level):.2f} (0x491810): dark blue at alpha {night_alpha(level)} over the screen, "
                "with the lamps of Assets\\lsmap.dat putting back the unlit picture through their light masks "
                "(0x4919D0: 0x490C90, 0x491A5F, 0x491A96).",
                CHECKED.format(code="the night draw 0x4919D0, the darkness 0x491810 and the fill 0x403B40"))

    if files.has("map_fog.png"):
        add("house/weather/fog", "Weather, day and night/Weather", "Map fog", [ga.whole("map_fog.png")], False,
            "Loaded for the fog (GetImage 0xA7 at 0x4908CF, kept at 0x8302D8 + 0x1400) but no code reads it back, so "
            "it is never drawn.", "")
    if files.has("outsideChair.png"):
        for k in range(2):
            name, rect = _cell(files, 0x88, k)
            add(f"house/unused/outsidechair/{k}", "Furniture and objects/Unused", f"Outside chair, picture {k + 1}",
                [pi.Draw("house", name, rect, 0, 0)], False, USAGE[0x88][1], "")
    return out


RAINDROP_FRAMES = (0, 1, 2)                 # effect 0x14: 3 frames, once (0x4EB4B0; 0x491CE2: loop 0)
RAINBOW_FRAMES = tuple(range(10))           # effect 7: 10 frames, once (0x4EB3E0; 0x4426EA: loop 0)
_IDS = {name: image for image, (name, *_r) in ga.TABLE.items() if image != 0x59}

_LIST = "drawn by the house list (0x420BC0 -> 0x420130)"
USAGE = {
    0x14: (True, f"The toilet with its lid open, {_LIST} at 0x420919."),
    0x15: (True, f"The toilet in use, {_LIST} at 0x420901."),
    0x16: (True, f"The open fridge, {_LIST} at 0x420923..0x4209FC."),
    0x17: (True, f"The laundry machines' lights, {_LIST} at 0x42044C."),
    0x18: (True, f"The office's red light, {_LIST} at 0x420499."),
    0x19: (True, f"The drawn shower curtain, {_LIST} at 0x420588."),
    0x21: (True, f"Rose petals on the bed, {_LIST} at 0x4206DD."),
    0x1E: (True, f"The kitchen at level 2 and 3, {_LIST} at 0x420C29."),
    0x1F: (True, f"The office at level 2 and 3, {_LIST} at 0x420C86."),
    0x20: (True, f"The workroom at level 2 and 3, {_LIST} at 0x420CDD."),
    0x82: (True, f"The old television, {_LIST} at 0x420DC7."),
    0x83: (True, f"The flat-screen television, {_LIST} at 0x420DC7."),
    0x86: (True, f"The air purifier, {_LIST} at 0x420DF1."),
    0x87: (True, f"The loose shed door, {_LIST} at 0x420FCC."),
    0x88: (False, "Loaded with the house pictures (0x41FE91, kept at 0x502278 + 0x1854) but no code reads it back, "
                  "so the outside chair is never drawn."),
    0x89: (True, f"The damaged floors, {_LIST} at 0x4213E1, 0x421489 and 0x421531."),
    0x8A: (True, f"The wall cracks, {_LIST} at 0x420EA0 and 0x420FA2."),
    0x59: (False, "No code asks for picture 0x59; the wall cracks in the same file stucco.png are drawn as picture "
                  "0x8A (0x420E93, 0x420F95)."),
    0x8B: (True, f"The fish tank, {_LIST} at 0x4210CD."),
    0x8C: (True, f"The full kitchen bin, {_LIST} at 0x4212D6."),
    0x8D: (True, f"The laundry room's light bulb, {_LIST} at 0x4212F4."),
    0x8E: (True, f"The shed's door knob, {_LIST} at 0x421022."),
    0x8F: (True, f"The new bed, {_LIST} at 0x42131E."),
    0x90: (True, f"The towels, {_LIST} at 0x42134D and 0x42136D."),
    0x91: (True, f"The patio set, {_LIST} at 0x42104C."),
    0x92: (True, f"The pool, {_LIST} at 0x421079."),
    0x93: (True, f"The hammock, {_LIST} at 0x4210A3."),
    0x94: (True, f"The barbecue, {_LIST} at 0x4210FA."),
    0x95: (True, f"The birdhouse, {_LIST} at 0x421124."),
    0x96: (True, f"The paintings, {_LIST} at 0x421150, 0x421170 and 0x421190."),
    0x97: (True, f"The pinball machine, {_LIST} at 0x4211BD."),
    0x98: (True, f"The radio, {_LIST} at 0x4211EA."),
    0x99: (True, f"The toolbox, {_LIST} at 0x421214."),
    0x9A: (True, f"The treadmill, {_LIST} at 0x421241."),
    0x9B: (True, f"The leaks' puddles, {_LIST} at 0x420D0F..0x420D8A and 0x421693."),
    0xBF: (True, f"The remote control, {_LIST} at 0x42159E."),
    0xD4: (True, f"The balcony flowers, {_LIST} at 0x4215D1..0x421631."),
    0xD5: (True, f"The bird bath's water, {_LIST} at 0x42126E."),
    0x80: (True, "The flat-screen television's picture, started by SetProp (0x493AE5) and drawn by the effect draw "
                 "0x421A30."),
    0x81: (True, "The old television's picture, started by SetProp (0x493B06) and drawn by the effect draw 0x421A30."),
    0x84: (True, "The office computer's screen, started by SetProp (0x493B27) and drawn by the effect draw 0x421A30."),
    0x85: (True, "The office computer's screen, started by SetProp (0x493B4D) and drawn by the effect draw 0x421A30."),
    0x79: (True, "Rain's splashes on the ground, added by the rain (0x491CF3) and drawn by the effect draw 0x421A30."),
    0x61: (True, "The rainbow over a clicked villager, added at 0x442704 and drawn by the effect draw 0x421A30."),
    0xA6: (True, "The sunbeams of sunbeam weather, drawn by 0x492040 (0x4920A9)."),
    0xA7: (False, "Loaded for the fog (0x4908CF, kept at 0x8302D8 + 0x1400) but no code reads it back, so it is never "
                  "drawn."),
    0x3E: (False, "No code asks for picture 0x3E; the file map_cloud01.png is missing from the game too."),
    0xAE: (False, "No lamp of this kind (3) exists: Assets\\lsmap.dat has kinds 4, 6, 8, 9 and 11, and the only other "
                  "code that adds a lamp (the light editor, 0x44DBD2) adds kind 7."),
    0xAF: (True, "The light mask of Assets\\lsmap.dat's lamps of kind 4 at night (0x490B3C, applied at 0x490E0C)."),
    0xB0: (False, "No lamp of this kind (2) is ever made (see 0xAE); the file is missing from the game too."),
    0xB1: (False, "No lamp of this kind (5) is ever made (see 0xAE); the file is missing from the game too."),
    0xB2: (True, "The light mask of Assets\\lsmap.dat's lamps of kind 6 at night (0x490B3C, applied at 0x490E0C)."),
    0xB3: (False, "Only the light editor's lamps (kind 7, 0x44DBD2) would use it, and the file is missing from the "
                  "game."),
    0xB4: (True, "The light mask of Assets\\lsmap.dat's lamps of kind 8 at night (0x490B3C, applied at 0x490E0C)."),
    0xB5: (True, "The light mask of Assets\\lsmap.dat's lamp of kind 9 at night (0x490B3C, applied at 0x490E0C)."),
    0xB6: (False, "No lamp of this kind (10) exists (see 0xAE)."),
    0xB7: (True, "The light mask of Assets\\lsmap.dat's lamps of kind 11 at night (0x490B3C, applied at 0x490E0C)."),
}

CELL_LABELS = {
    (0x16, 0): "Open, nearly empty", (0x16, 1): "Open, some food", (0x16, 2): "Open, full",
    (0x16, 3): "Open, nearly empty (top kitchen)", (0x16, 4): "Open, some food (top kitchen)",
    (0x16, 5): "Open, full (top kitchen)",
    (0x1E, 0): "Level 2", (0x1E, 1): "Level 3", (0x1F, 0): "Level 2", (0x1F, 1): "Level 3",
    (0x20, 0): "Level 2", (0x20, 1): "Level 3",
    (0x89, 0): "Floor 1 damage", (0x89, 1): "Floor 2 damage", (0x89, 2): "Floor 3 damage",
    (0x8A, 0): "Wall crack (lower left)", (0x8A, 1): "Wall crack (upper right)",
    (0x90, 0): "Towels (first place)", (0x90, 1): "Towels (second place)",
    (0x96, 0): "Painting 1", (0x96, 1): "Painting 2", (0x96, 2): "Painting 3",
    (0x9B, 0): "Puddle (bathroom sinks, kitchen sink)", (0x9B, 1): "Puddle (toilet, bathtub, garden hose)",
    (0xD4, 0): "Flowers 1", (0xD4, 1): "Flowers 2", (0xD4, 2): "Flowers 3", (0xD4, 3): "Flowers 4",
    **{(0x80, k): f"Frame {k + 1}" for k in range(18)},
    **{(0x81, k): f"Frame {k + 1}" for k in range(18)},
    **{(0x84, k): f"Frame {k + 1}" for k in range(12)},
    **{(0x85, k): f"Frame {k + 1}" for k in range(12)},
    **{(0x79, k): f"Splash frame {k + 1}" for k in range(3)},
    **{(0x61, k): f"Frame {k + 1}" for k in range(10)},
}
CELL_UNUSED = {
    (0x88, 0): USAGE[0x88][1], (0x88, 1): USAGE[0x88][1],
    (0x59, 0): USAGE[0x59][1], (0x59, 1): USAGE[0x59][1],
}
