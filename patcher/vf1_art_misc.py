"""The Picture Maker's effects and animations, animals and insects, food and yard work, store pictures,
collectibles and people's sheets that no other part covers, for Virtual Families 1: whether the game ever
draws each picture (and each cell), what a cell shows, and the pictures the game assembles from them (see
vf1_game_art for the catalogue they join).

Where the rules come from (the vanilla Virtual Families.exe 1.01.00; tests/test_art_misc.py runs the effect
machinery, the store's item picture and the ball in Unicorn, see tests/house_emu.py and tests/ui_emu.py;
tests/test_art_emulated_extras.py runs the ripples, the birds, the shark and the pets):

* The effects: the table 0x4EB370 (16 bytes an effect: picture id, frames, random first frame, height) is
  loaded into picture grids by 0x4217B0.  AddEffect 0x421810 (effect, x, y, delay, loop, motion or cell,
  layer, centred) starts one; the clock 0x421B50 moves every effect one frame every 7 of its calls, from frame
  0 (or a random one) to the last, then loops or ends; the draw 0x421A30 draws cell `frame` of the strip
  (ldwImageGrid: column frame % columns, row frame // columns, a row past the last clamped to the last), or,
  for effects 0x0E and 0x12, one fixed cell at alpha 1 - frame x 0.1 (none below 0).  Every effect in a layer
  but 0xA goes through the draw list 0x44EBF0 / 0x4219B0; layer 0xA is drawn by 0x421DD0 on top.
* Who adds which effect: the AddEffect calls with a fixed number, the wrapper 0x421DA0 (3, 0x21, 0x15), the
  family members' plan steps 0x16 / 0x17 (builders 0x48D150 / 0x48D1C0, run by ProcessCurrentPlan 0x48E350 at
  0x48ECD3 / 0x48ED1B), the dropped-thing fades 0x0E / 0x12 (0x445D79).  The pets' plan steps 10 / 11
  (0x434E4D / 0x434E93) are never made: the pets' only step builders 0x434A50..0x434C70 make steps 1..5 and 8.
  The smoke emitters CSmoke 0x50C378 (0x421E50, which adds its effect at 0x421EEC) are never switched on: no
  code sets an emitter's on byte (only 0x421E10 clears them).
* Pictures asked for by number: every call to theGraphicsManager's getters (GetImageGrid 0x44F5A0, GetImage
  0x44F860, 0x44F870, 0x44F880, 0x44F590, 0x44F960, 0x44FA70) with the number pushed for it; the effect table;
  the pets' table (0x432E90 fills it with picture 3 only); the title-screen sprite list 0x56AB68 (0x43, 0x44
  and 0, where 0 means "draw a family member", 0x44CE44); the people's tables (vf1_people_pictures).
* The store and the item tray draw an item with 0x496A10 (x, y, item, picture, ...): items 18, 19, 64 and 65
  (the outfits) from the people's action sheets at 70%, 61..63 (the pets) from pet_grid.png column 16 of rows
  0..2, 66..80 (home improvements) from home_grid.png cell item - 66, every other item from
  InventoryItems.png cell 2 x item - 2 + picture (0x496AD1).  The tray draws an item's second picture while it is
  dragged (+0xA5, set at 0x49772A) and when its table entry 0x4FE1B0 + 0x18 is 1 (0x49701E -> 0x496920); the
  house list draws the repair items' second pictures where they are used (0x420E6A, 0x4212A1, 0x42140D,
  0x4214B5, 0x42155D, 0x42166B); the ball in the yard is item 3's first picture (0x41F572 -> 0x496C50).
"""
from __future__ import annotations

import struct

import vf1_game_art as ga
import vf1_picture_image as pi

TITLE = "Effects, animals, store and collectibles"
CHECKED = "Checked against the game's own drawing code ({code}) run in Unicorn."
EFFECT_CHECK = CHECKED.format(code="AddEffect 0x421810, the effect clock 0x421B50 and the effect draw 0x421A30")
STEPS_PER_FRAME = 7                 # 0x421B56: the clock moves the effects every 7th call
FADE_STEP = 0.10000000149011612     # 0x4B4520 (a double holding the float 0.1)
RIPPLE_ALPHA = 0.4000000059604645   # 0x4D6EDC
RIPPLE_AT = 32                      # 0x48B81F / 0x48B833: the ripples' corner, 32 pixels up and left of the feet
RIPPLE_CHECK = CHECKED.format(code="the family member draw 0x48B4D0, standing in water of ground kind 5, "
                                   "for each value of the seconds clock")

# The birds (0x42FDD0, one bird record of 0x4C bytes): +0 / +4 its place, +0x30 its frame, +0x34 its size,
# +0x38 its facing (0 right, 3 left: 0x4306E9..0x4306FB), +0x3C what it does (1 on the ground, 2 waiting, both
# drawn alike; 3 flying), +0x48 its hop's height.  On the ground the cell is frame + 2 when facing left (frames
# 0..1 standing / pecking; frames 4..7, plus 2 facing left, flapping: 0x43067D..0x430699); flying it is
# frame + 4, plus 4 facing left (frames 0..3, 0x43079C).  The shadow 0xA9 and then the bird 0xA8 are drawn by
# 0x44ED70 at the bird's size (rand(40) + 80 percent, 0x42FB9D / 0x42FC1D): on the ground the shadow 3 pixels
# below the bird, both lifted by the hop; flying the shadow 37 pixels below it.
BIRD_GROUND = (-23, -19, 3)         # 0x42FE1E / 0x42FE21 and 0x42FE7F: bird corner, shadow 3 lower
BIRD_FLYING = (-23, -19, 37)        # 0x42FE40: the shadow 0x25 lower
BIRD_CELLS_GROUND = {0: "standing", 1: "pecking"}
BIRD_WHY = ("The birds that land in the yard, drawn by the birds' draw 0x42FDD0 (shadow 0x42FE5B / 0x42FE94, "
            "bird 0x42FEC0) each at its own size, 80% to 119% (0x42FB9D); shown here at 100%.")
BIRD_CHECK = CHECKED.format(code="the birds' draw 0x42FDD0, for every place, frame and facing listed")

# The pets (0x434550): row = the pet (cat, dog, turtle), column = the pose +0x1BC0, plus 4 x the heading +0x1BE8
# (0 up-right, 1 down-right, 2 down-left, 3 up-left: 0x4311A0) when the pose is 0..3 (0x4345A3..0x4345C6).  The
# poses come from the pets' animations (0x433550: "Walk NE" 0..3, "Walk SE" 4..7, "Walk SW" 8..11, "Walk NW"
# 12..15, "Sit SE" 16, "Lie SW" 17, a second "Walk NW" 20..23) and the pose picker 0x4333C0 (16, 17, 18 or a
# walking column); no code ever sets pose 19.
_WALK = ("walking up and to the right", "walking down and to the right", "walking down and to the left",
         "walking up and to the left")
PET_POSES = ([f"{_WALK[c // 4]}, step {c % 4 + 1} of 4" for c in range(16)]
             + ["sitting", "lying down", "sitting, second picture", "lying down, second picture"]
             + [f"pawing, picture {k + 1} of 4" for k in range(4)])
PET_NEVER = 19
PET_CHECK = ("The pet draw 0x434550, with the pets' table built by the game's own 0x432E90, run in Unicorn for every "
             "pet, pose and heading draws this cell.")
OUTFIT_SCALE = 0.699999988079071    # 0x496B5A: 70 (percent) -> 0x409A40

# The effect table 0x4EB370: effect: (picture id, frames, random first frame).
EFFECT_TABLE = {
    0x00: (0x5B, 10, 0), 0x01: (0x0E, 9, 0), 0x02: (0x5C, 10, 0), 0x03: (0x5D, 10, 0), 0x04: (0x5E, 10, 0),
    0x05: (0x5F, 9, 0), 0x06: (0x60, 16, 0), 0x07: (0x61, 10, 0), 0x08: (0x62, 10, 0), 0x09: (0x63, 9, 1),
    0x0A: (0x64, 36, 0), 0x0B: (0x65, 32, 1), 0x0C: (0x66, 8, 1), 0x0D: (0x67, 8, 1), 0x0E: (0x68, 39, 0),
    0x0F: (0x6A, 12, 1), 0x10: (0x6B, 10, 0), 0x11: (0x76, 10, 0), 0x12: (0x77, 54, 0), 0x13: (0x78, 15, 0),
    0x14: (0x79, 3, 0), 0x15: (0x7A, 12, 0), 0x16: (0x7B, 30, 0), 0x17: (0x7C, 40, 0), 0x18: (0x7D, 50, 0),
    0x19: (0x7E, 28, 1), 0x1A: (0x7F, 9, 0), 0x1B: (0x80, 18, 1), 0x1C: (0x81, 18, 1), 0x1D: (0x84, 12, 1),
    0x1E: (0x85, 12, 1), 0x1F: (0x6C, 2, 0), 0x20: (0x6D, 2, 0), 0x21: (0x6E, 10, 0), 0x22: (0x6F, 10, 0),
    0x23: (0x70, 10, 0), 0x24: (0x71, 10, 0), 0x25: (0x72, 10, 0), 0x26: (0x73, 10, 0), 0x27: (0x74, 10, 0),
    0x28: (0x75, 10, 0), 0x29: (0x0D, 10, 0),
}
# Every effect number some code adds, and where (the rest are never added).  Plan steps: the builder calls.
EFFECT_ADDED = {
    0x00: (0x432365, 0x4327AA, 0x441591, 0x4462B2, 0x487686, 0x487BF6, 0x4880E1, 0x4886BA, 0x48B89C),
    0x01: (0x457A19, 0x4581E7, 0x458220, 0x458259),
    0x02: (0x4132DF, 0x413315, 0x41334B, 0x471C0B, 0x471C25, 0x471C59, 0x471C66, 0x471C73),
    0x03: (0x414CE3, 0x44648A, 0x4464E1, 0x446535, 0x4932C4, 0x471CCB, 0x471CF2),
    0x04: (0x446589, 0x4465DD, 0x471C18, 0x471CF2),
    0x05: (0x4323FA, 0x441544, 0x445C1D, 0x445F47, 0x48817A, 0x4713A2, 0x4713DC, 0x4713FE, 0x47A6AC, 0x47AA49),
    0x06: (0x442E40,),
    0x07: (0x442704, 0x443BBB),
    0x0A: (0x478E7E, 0x478EEB),
    0x0D: (0x4463CD, 0x493541, 0x49358F, 0x443ABA, 0x45B269, 0x45B8E5, 0x466370),
    0x0E: (0x445D79,), 0x12: (0x445D79,),
    0x0F: (0x442841, 0x442869, 0x442891),
    0x10: (0x471CA4, 0x471FD6, 0x47205C),
    0x11: (0x4718A1, 0x471CB1),
    0x13: (0x43232D, 0x4880A9),
    0x14: (0x491CF3,),
    0x15: (0x4934AF, 0x4934F3, 0x45D4D1, 0x471246, 0x47EF22),
    0x16: (0x493281,),
    0x19: (0x4931F8,),
    0x1B: (0x493B74, 0x493EF3), 0x1C: (0x493B74, 0x493EF3), 0x1D: (0x493EF3,), 0x1E: (0x493B74,),
    0x1F: (0x44510A, 0x44512A), 0x20: (0x4450EC,),
    0x21: (0x4933E3, 0x493427, 0x49346B),
    0x22: (0x493336,),
    0x24: (0x47D565, 0x47DBEE, 0x47F1A3),
    0x25: (0x47157F,),
    0x26: (0x493662, 0x493698),
    0x27: (0x4935E0, 0x493618, 0x4936E1, 0x49372F, 0x49377D, 0x4937C4),
    0x28: (0x4427C7, 0x45F38E, 0x46607D, 0x466351),
    0x29: (0x4944A6,),
}
NEVER_ADDED = (
    "every AddEffect 0x421810 call passes a fixed effect number, the wrapper 0x421DA0 is given 3, 0x21 or 0x15, "
    "the family members' plan steps 0x16 / 0x17 (0x48D150 / 0x48D1C0) are built with 1, 2, 3, 4, 5, 7, 0xA, 0xD, "
    "0x10, 0x11, 0x15, 0x24, 0x25 or 0x28, the fades are 0xE / 0x12 (0x445D79), and the pets' effect steps and "
    "the smoke emitters (0x421EEC) are never started")

# The effects this module lists frame by frame: effect -> (key, label, category, why).
EFFECTS = (
    (0x00, "waves", "Splash rings in the water", "Effects and animations/Water and steam",
     "Added where a family member or a pet walks in water (0x487686, 0x4880E1, 0x48B89C; 0x432365, 0x4327AA) "
     "and by the item drops (0x441591, 0x4462B2)."),
    (0x0D, "foam", "Foam", "Effects and animations/Water and steam",
     "Added by the house's water spots (0x493541, 0x49358F), an item drop (0x4463CD) and the family members' "
     "plan step 0x17 (0x443ABA, 0x45B269, 0x466370)."),
    (0x21, "waterspray", "Water spray", "Effects and animations/Water and steam",
     "Added by the house's running water (0x4933E3, 0x493427, 0x49346B through 0x421DA0)."),
    (0x22, "faucet", "Running tap", "Effects and animations/Water and steam",
     "Added by the house's running water (0x493336)."),
    (0x26, "shower", "Shower water", "Effects and animations/Water and steam",
     "Added while the shower runs (0x493662, 0x493698)."),
    (0x27, "steam", "Steam", "Effects and animations/Water and steam",
     "Added over the house's hot spots (0x4935E0, 0x493618, 0x4936E1, 0x49372F, 0x49377D, 0x4937C4); "
     "the first three rise 2 pixels a frame."),
    (0x28, "drips", "Dripping water", "Effects and animations/Water and steam",
     "Added over a family member by the plan step 0x17 (0x4427C7, 0x45F38E, 0x46607D, 0x466351)."),
    (0x06, "algae", "Algae", "Effects and animations/Water and steam",
     "Added at 20 random spots when an item is used where the map's ground is of kind 2 (0x442DFA..0x442E40)."),
    (0x02, "yellowsparkle", "Yellow sparkle", "Effects and animations/Sparkles",
     "Added when a collection is completed (0x4132DF, 0x413315, 0x41334B, drawn on top) and over family members "
     "by the plan step 0x17 (0x471C0B..0x471C73)."),
    (0x03, "sparkle2", "Small sparkle", "Effects and animations/Sparkles",
     "Added over collectibles lying in the yard (0x414CE3), by the item drops (0x44648A, 0x4464E1, 0x446535), "
     "the house (0x4932C4) and the plan step 0x17 (0x471CCB, 0x471CF2)."),
    (0x04, "sparkle", "Sparkle", "Effects and animations/Sparkles",
     "Added by the item drops (0x446589, 0x4465DD) and the plan step 0x17 (0x471C18)."),
    (0x10, "sharpsparkle", "Sharp sparkle", "Effects and animations/Sparkles",
     "Added over family members by the plan step 0x17 (0x471CA4, 0x471FD6..0x472076)."),
    (0x11, "blurrysparkle", "Soft sparkle", "Effects and animations/Sparkles",
     "Added over family members by the plan step 0x17 (0x4718A1, 0x4718C3, 0x471CB1, 0x471CD8)."),
    (0x05, "dust", "Dust puff", "Effects and animations/Dust and smoke",
     "Added where a family member or a pet walks (0x48817A, 0x4323FA), by the house screen's clicks and drops "
     "(0x441544, 0x445C1D, 0x445F47) and the plan step 0x17 (0x4713A2, 0x47A6AC, 0x47AA49)."),
    (0x15, "smoke", "Smoke", "Effects and animations/Dust and smoke",
     "Added by the house (0x4934AF, 0x4934F3 through 0x421DA0) and over family members by the plan step 0x17 "
     "(0x45D4D1, 0x471246, 0x47EF22)."),
    (0x25, "sawdust", "Sawdust", "Effects and animations/Dust and smoke",
     "Added over a family member by the plan step 0x17 (0x47157F)."),
    (0x13, "footprints", "Footprints", "Effects and animations/Dust and smoke",
     "Added where a family member or a pet walks on ground of kind 3 (0x4880A9, 0x43232D)."),
    (0x0A, "petals", "Falling petals", "Effects and animations/Dust and smoke",
     "Added over a family member by the plan step 0x17 (0x478E7E..0x478F12)."),
    (0x0F, "redspray", "Red spray", "Effects and animations/Dust and smoke",
     "Added over a family member an item is used on (0x442841, 0x442869, 0x442891)."),
    (0x01, "chopgreens", "Chopping greens", "Food and cooking/Animations",
     "Added at a fixed spot by the plan step 0x16 (0x457A19, 0x4581E7, 0x458220, 0x458259)."),
    (0x24, "salad", "Tossing a salad", "Food and cooking/Animations",
     "Added over a family member by the plan step 0x17 (0x47D565, 0x47DBEE, 0x47F1A3)."),
    (0x16, "reeffish", "Reef fish", "Animals and insects/Fish",
     "Added at random spots by the house screen's environment update 0x493210 (0x493281)."),
    (0x19, "bees", "Bees", "Animals and insects/Insects",
     "Added at random spots by the house screen's environment update 0x4930D0 (0x4931F8)."),
    (0x29, "birdhouse", "Birds flying from the birdhouse", "Animals and insects/Birds",
     "Added when the bought birdhouse is clicked (0x494450, its click handler in the yard's table 0x8754C8: "
     "0x4944A6)."),
)


# ------------------------------------------------------------------ cells and frames
def _shape(image: int) -> tuple[int, int]:
    _name, cols, rows, _n = ga.TABLE[image]
    return (cols or 1), (rows or 1)


def cell(files: ga.GameFiles, image: int, k: int) -> tuple[str, tuple[int, int, int, int]]:
    """Cell number k of a picture as ldwImageGrid hands it out (column k % columns, row k // columns, a row past
    the last clamped to the last: GetCellRect 0x40AD40)."""
    name = ga.TABLE[image][0]
    cols, rows = _shape(image)
    return name, ga.cell_rect(files.size(name), cols, rows, k % cols, k // cols)[1]


def frame_cells(image: int, frames: int) -> list[int]:
    """The cell each frame 0..frames-1 shows, as a grid number (row clamped)."""
    cols, rows = _shape(image)
    return [(k % cols) + cols * min(k // cols, rows - 1) for k in range(frames)]


def effect_frames(files: ga.GameFiles, effect: int, x: int = 0, y: int = 0) -> list[pi.Draw]:
    """Every frame of an effect drawn by 0x421A30 at (x, y), not centred, not moving."""
    image, frames, _rnd = EFFECT_TABLE[effect]
    out = []
    for k in range(frames):
        name, rect = cell(files, image, k)
        out.append(pi.Draw("effect", name, rect, x, y))
    return out


def bird_cell(flying: bool, facing_left: bool, frame: int) -> int:
    """The cell of bird.png 0x42FDD0 draws (0x42FDE2..0x42FE15, 0x42FE60..0x42FEA0)."""
    if flying:
        return frame + 4 + (4 if facing_left else 0)
    return frame + (2 if facing_left else 0)


def bird_layers(files: ga.GameFiles, flying: bool, cell_index: int, height: int = 0) -> tuple:
    """The shadow and the bird as 0x42FDD0 draws them at 100%, relative to the bird's place (+0 / +4)."""
    x, y, shadow = BIRD_FLYING if flying else BIRD_GROUND
    y -= 0 if flying else height
    sw, sh = files.size("bird_shadow.png")
    name, rect = cell(files, 0xA8, cell_index)
    return (pi.Draw("shadow", "bird_shadow.png", (0, 0, sw, sh), x, y + shadow),
            pi.Draw("bird", name, rect, x, y))


def bird_arts(files: ga.GameFiles) -> list[tuple[str, str, tuple]]:
    """Every picture of a bird the game shows: on the ground standing, pecking or flapping, and flying."""
    out = []
    for left in (False, True):
        side = "left" if left else "right"
        for frame in (0, 1):
            c = bird_cell(False, left, frame)
            out.append((f"ground/{c}", f"Bird {BIRD_CELLS_GROUND[frame]}, facing {side}",
                        bird_layers(files, False, c)))
        for frame in range(4):
            c = bird_cell(False, left, frame + 4 + (2 if left else 0))        # 0x43067D..0x430699
            out.append((f"ground/{c}", f"Bird flapping on the ground, facing {side}, picture {frame + 1} of 4",
                        bird_layers(files, False, c)))
        for frame in range(4):
            c = bird_cell(True, left, frame)
            out.append((f"flying/{c}", f"Bird flying {side}, picture {frame + 1} of 4", bird_layers(files, True, c)))
    return out


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def fade_alpha(frame: int) -> float:
    """0x421ACC..0x421B23: alpha 1 - frame x 0.1 (as a float), 0 when below 0."""
    a = f32(1.0 - frame * FADE_STEP)
    return a if a >= 0.0 else 0.0


def fade_frames(files: ga.GameFiles, effect: int, picture: int, x: int = 0, y: int = 0) -> list[pi.Draw]:
    """Effects 0x0E / 0x12: a fixed cell `picture` faded over the effect's frames (0x421AC4)."""
    image, frames, _rnd = EFFECT_TABLE[effect]
    name, rect = cell(files, image, picture)
    return [pi.Draw("fade", name, rect, x, y, 1.0, fade_alpha(k)) for k in range(frames)]


# ------------------------------------------------------------------ the store's item pictures 0x496A10
def item_picture(item: int, second: bool = False) -> tuple[int, int] | None:
    """(image id, cell) 0x496A10 draws for an item, or None for the outfits (drawn from the people's sheets)."""
    if item in (18, 19, 64, 65):
        return None
    if item in (61, 62, 63):
        return 0x03, 16 + 24 * (item - 61)
    if item >= 66:
        return 0xB9, item - 66
    return 0xB8, 2 * item - 2 + (1 if second else 0)


try:                                                   # the item names as the exe's item table holds them
    from vf1_game_mechanics import ITEMS as _ITEMS
except Exception:                                      # pragma: no cover - the patcher ships it
    _ITEMS = {}


def item_name(item: int) -> str:
    return _ITEMS.get(item, (f"Item {item}", 0))[0]


try:
    import vf1_people_pictures as _pp
    _CARRYING_NAMES = tuple(_pp.CARRYING_NAMES)
    _CARRIED = {t.value: t for t in _pp.carried_things()}
except Exception:                                      # pragma: no cover
    _pp = None
    _CARRYING_NAMES = ()
    _CARRIED = {}

HOUSE_ITEM_CELLS = {      # the house list's InventoryItems cells (0x4200D0 adds them)
    0x55: "Wall Repair Compound, on the cracked wall while it is plastered (0x420E6A)",
    0x57: "Floor Repair Kit, on a damaged floor while it is repaired (0x42140D, 0x4214B5, 0x42155D)",
    0x59: "Waterproof Tape, at the leaking garden hose while it is fixed (0x42166B)",
    0x5B: "Fountain Pump, at the bird bath while it is fixed (0x4212A1)",
}


# ------------------------------------------------------------------ the catalogue
def _have(files: ga.GameFiles, layers) -> bool:
    return all(files.has(layer.file) for layer in layers)


def arts(files: ga.GameFiles) -> list[ga.Art]:
    out: list[ga.Art] = []

    def add(key, category, label, layers, used, why, checked):
        layers = tuple(layers)
        if _have(files, layers):
            out.append(ga.Art(key, category, label, layers, used, why, checked))

    for effect, key, label, category, why in EFFECTS:
        image, frames, rnd = EFFECT_TABLE[effect]
        if not files.has(ga.TABLE[image][0]):
            continue
        start = "from a random frame" if rnd else "from the first frame"
        for k, draw in enumerate(effect_frames(files, effect)):
            add(f"misc/effect/{key}/{k}", category, f"{label}, frame {k + 1} of {frames}", [draw], True,
                f"{why} It plays its {frames} frames {start}, one every {STEPS_PER_FRAME} calls of the effect clock "
                "0x421B50, drawn by 0x421A30.", EFFECT_CHECK)

    # a dropped thing fading away (effects 0x0E / 0x12 at 0x445D79): the first carrying.png picture as a sample
    if files.has("carrying.png") and _CARRYING_NAMES:
        for k, draw in enumerate(fade_frames(files, 0x0E, 0)[:10]):
            add(f"misc/fade/{k}", "Effects and animations/Fading", f"A dropped thing fading away "
                f"({_CARRYING_NAMES[0].lower()}), frame {k + 1} of 10", [draw], True,
                "When a family member's carried thing is taken away its picture is left behind and fades: alpha "
                f"1 - frame x 0.1 ({draw.alpha:.1f} here), invisible from frame 11 on (0x445D79 -> 0x421AC4).",
                EFFECT_CHECK)

    # the ripples round a family member standing in water (0x48B842: alpha 0.4, a cell by the game clock & 3),
    # placed with their top-left 32 pixels up and left of the feet (0x48B81F, 0x48B833)
    if files.has("ripple.png"):
        for k in range(4):
            name, rect = cell(files, 0xA5, k)
            add(f"misc/ripple/{k}", "Effects and animations/Water and steam", f"Ripples round a family member in "
                f"the water, picture {k + 1} of 4",
                [pi.Draw("ripple", name, rect, -RIPPLE_AT, -RIPPLE_AT, 1.0, RIPPLE_ALPHA)], True,
                USAGE[0xA5][1] + f" Picture {k + 1} shows while the game's seconds clock (0x4036D0) is {k} more than "
                "a multiple of 4; the family member's body is not drawn while in the water, only the head.",
                RIPPLE_CHECK)

    # the birds (0x42FDD0): the shadow, then the bird, at its own size (100% here)
    if files.has("bird.png") and files.has("bird_shadow.png"):
        for key, label, layers in bird_arts(files):
            add(f"misc/bird/{key}", "Animals and insects/Birds", label, layers, True, BIRD_WHY, BIRD_CHECK)

    # the ball in the yard (0x41F4E0): its shadow, then item 3's first picture, 30 pixels up and on the ground
    if files.has("ball_shadow.png") and files.has("InventoryItems.png"):
        w, h = files.size("ball_shadow.png")
        name, rect = cell(files, 0xB8, 4)
        for height in (0, 30):
            add(f"misc/ball/{height}", "Animals and insects/Pets and toys",
                "Ball in the yard" + (f" ({height} pixels up)" if height else " (on the ground)"),
                [pi.Draw("ball", "ball_shadow.png", (0, 0, w, h), -15, -8),
                 pi.Draw("ball", name, rect, -35, -35 - height)], True,
                "Once the ball is bought it is drawn in the yard: its shadow at the ground (0x41F53B) and the ball "
                "above it by its height (0x41F58F).", CHECKED.format(code="the ball's draw 0x41F4E0"))

    # the store's pictures of the items (0x496A10), centred
    if files.has("InventoryItems.png"):
        for item in sorted(set(range(1, 64)) - {18, 19, 61, 62, 63}):
            image, k = item_picture(item)
            name, rect = cell(files, image, k)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            add(f"misc/item/{item}", "Store/Items", f"{item_name(item)} (in the store and the item tray)",
                [pi.Draw("item", name, rect, -(w // 2), -(h // 2))], True,
                "Drawn centred on its place in the store and the item tray (0x496A10 -> 0x409960).",
                CHECKED.format(code="the item picture draw 0x496A10"))
    for item in (61, 62, 63):
        image, k = item_picture(item)
        if files.has(ga.TABLE[image][0]):
            name, rect = cell(files, image, k)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            add(f"misc/item/{item}", "Store/Items", f"{item_name(item)} (in the store and the item tray)",
                [pi.Draw("item", name, rect, -(w // 2), -(h // 2))], True,
                "A pet's picture in the store and the item tray is pet_grid.png's column 16 (0x496A97..0x496AA2).",
                CHECKED.format(code="the item picture draw 0x496A10"))
    if files.has("home_grid.png"):
        for item in range(66, 81):
            image, k = item_picture(item)
            name, rect = cell(files, image, k)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            add(f"misc/item/{item}", "Store/Home improvements", f"{item_name(item)} (in the store)",
                [pi.Draw("item", name, rect, -(w // 2), -(h // 2))], True,
                "A home improvement's picture in the store is home_grid.png's cell item - 66 (0x496AC3).",
                CHECKED.format(code="the item picture draw 0x496A10"))
    return out


# ------------------------------------------------------------------ usage of every picture in this area
def _effect_why(effect: int) -> str:
    sites = ", ".join(f"0x{a:X}" for a in EFFECT_ADDED[effect][:4])
    more = ", ..." if len(EFFECT_ADDED[effect]) > 4 else ""
    return f"Effect {effect:#x}, added at {sites}{more} and drawn by the effect draw 0x421A30."


def _never(effect: int) -> str:
    return (f"Loaded as effect {effect:#x} (0x4217B0) but no code adds that effect: {NEVER_ADDED}.")


_HOUSE = "drawn by the house list (0x420BC0 -> 0x420130)"
_PEOPLE = "drawn by the family member draw 0x48B4D0 (see the people pictures)"
USAGE = {
    # effects
    0x5B: (True, "The splash rings in the water. " + _effect_why(0x00)),
    0x5C: (True, "Yellow sparkles. " + _effect_why(0x02)),
    0x5D: (True, "Small sparkles. " + _effect_why(0x03)),
    0x5E: (True, "Sparkles. " + _effect_why(0x04)),
    0x5F: (True, "Dust puffs. " + _effect_why(0x05)),
    0x60: (True, "Algae. " + _effect_why(0x06)),
    0x62: (False, "Bubbles. " + _never(0x08)),
    0x63: (False, "A candle flame. " + _never(0x09)),
    0x64: (True, "Falling petals. " + _effect_why(0x0A)),
    0x65: (False, "A waterfall. " + _never(0x0B)),
    0x66: (False, "A waterfall. " + _never(0x0C)),
    0x67: (True, "Foam. " + _effect_why(0x0D)),
    0x69: (False, "No code asks for picture 0x69, and it is not in the effect table 0x4EB370 (the red spray "
                  "effect uses spray_Grid_red.png, 0x6A)."),
    0x6A: (True, "Red spray. " + _effect_why(0x0F) + " It plays 12 frames from 11 cells: the 12th frame asks "
                 "for row 1, which is clamped to row 0, so the first picture shows again (0x40AD40)."),
    0x6B: (True, "Sharp sparkles. " + _effect_why(0x10)),
    0x6E: (True, "Water spray. " + _effect_why(0x21)),
    0x6F: (True, "A running tap. " + _effect_why(0x22)),
    0x70: (False, "Boiling water. " + _never(0x23)),
    0x71: (True, "Tossing a salad. " + _effect_why(0x24)),
    0x72: (True, "Sawdust. " + _effect_why(0x25)),
    0x73: (True, "Shower water. " + _effect_why(0x26)),
    0x74: (True, "Steam. " + _effect_why(0x27)),
    0x75: (True, "Dripping water. " + _effect_why(0x28)),
    0x76: (True, "Soft sparkles. " + _effect_why(0x11)),
    0x78: (True, "Footprints. " + _effect_why(0x13)),
    0x7A: (True, "Smoke. " + _effect_why(0x15)),
    0x7F: (False, "A bubble strip. " + _never(0x1A)),
    0xA5: (True, "Ripples round a family member standing in water (map ground 5, 0x48B65E..0x48B67E), drawn at "
                 "alpha 0.4 with the cell the game's seconds clock picks (its count & 3), centred on the feet "
                 "(0x48B815..0x48B842 -> 0x409970), but not while sitting or lying (+0x13576) or in pose 0x36; "
                 "loaded at 0x4898EF."),
    0xD2: (True, "The ball's shadow in the yard, drawn by the ball's draw 0x41F4E0 (0x41F530 -> 0x44EC30)."),
    # animals
    0x0D: (True, "Birds flying out of the birdhouse. " + _effect_why(0x29)),
    0x7B: (True, "Reef fish in the yard's water. " + _effect_why(0x16)),
    0x7C: (False, "Reef fish. " + _never(0x17)),
    0x7D: (False, "Reef fish. " + _never(0x18)),
    0x7E: (True, "Bees. " + _effect_why(0x19)),
    0xA8: (True, "The birds in the yard, on the ground and flying, drawn by the birds' draw 0x42FDD0 (0x42FEC0 -> "
                 "0x44ED70); loaded at 0x4307E2."),
    0xA9: (True, "The birds' shadows, drawn by 0x42FDD0 (0x42FE5B, 0x42FE94) under each bird; loaded at 0x4307F4."),
    0xAA: (False, "The shark is never drawn: its draw 0x430850 is only the draw list's case 7 (0x44EB77), and no "
                  "code ever puts a case 7 in the draw list (the only adder 0x44EBF0 is called with 1, 2, 3, 5, 8 "
                  "and 9). Its picture is loaded (0x43083F) but every pixel of sharkstripfinal.png is fully "
                  "transparent."),
    0xAB: (False, "No code asks for picture 0xAB (no getter call names it and no table holds it), so the "
                  "dragonflies are never drawn."),
    0xAC: (False, "No code asks for picture 0xAC (no getter call names it and no table holds it), so the green "
                  "butterfly is never drawn."),
    0xAD: (False, "No code asks for picture 0xAD (no getter call names it and no table holds it), so the "
                  "hummingbird is never drawn."),
    0x03: (True, "The pets: the pets' table holds picture 3 for every pose (0x432E90) and the pet draw 0x434550 "
                 "draws row pet, column pose (0x43460E -> 0x44ED70), placed by the table's point for that pet and "
                 "pose; the store and tray draw a pet as column 16 of its row (0x496A97)."),
    # food and yard work (the house list draws them: vf1_art_house)
    0x0E: (True, "Chopping greens. " + _effect_why(0x01)),
    0x0F: (True, f"Food being prepared on the counter, {_HOUSE} at 0x4207AB and 0x4207DC."),
    0x10: (True, f"A project on the workbench, {_HOUSE} at 0x42083E and 0x42088F."),
    0x11: (True, f"A small hole in the yard, {_HOUSE} at 0x42021C, 0x4202A9 and 0x420336."),
    0x12: (True, f"A large hole in the yard, {_HOUSE} at 0x42024B, 0x4202D8 and 0x420365."),
    0x13: (True, f"The gopher in a hole, {_HOUSE} at 0x42027A and 0x420307."),
    0x1A: (True, f"Bread on the counter (1000 food or more), {_HOUSE} at 0x4216BD."),
    0x1B: (True, f"Cans on the counter (500 food or more), {_HOUSE} at 0x4216E7."),
    0x1C: (True, f"A meal on the kitchen table, {_HOUSE} at 0x420505."),
    0x1D: (True, f"Meat on the barbecue, {_HOUSE} at 0x420534."),
    # store and items
    0xB8: (True, "The items' pictures: the store and the item tray (0x496A10 -> 0x496AD1), the ball in the yard "
                 "(0x41F584) and the repair items in the house (0x420E6A, 0x4212A1, 0x42140D, 0x4214B5, 0x42155D, "
                 "0x42166B)."),
    0xB9: (True, "The home improvements' pictures in the store (0x496A10: items 66 to 80, cell item - 66, "
                 "0x496AC3)."),
    0xCE: (False, "No code asks for picture 0xCE (no getter call names it and no table holds it); the store draws "
                  "each item's own picture instead (0x496A10)."),
    0xCF: (False, "No code asks for picture 0xCF (no getter call names it and no table holds it); the store draws "
                  "each item's own picture instead (0x496A10)."),
    0xD0: (False, "No code asks for picture 0xD0 (no getter call names it and no table holds it); the store draws "
                  "each item's own picture instead (0x496A10)."),
    # collectibles
    0x52: (False, "No code asks for picture 0x52 (no getter call names it and no table holds it); collectibles are "
                  "drawn from collectables_small.png (0x77)."),
    0x53: (False, "No code asks for picture 0x53 (no getter call names it and no table holds it); collectibles are "
                  "drawn from collectables_small.png (0x77)."),
    0x54: (False, "No code asks for picture 0x54 (no getter call names it and no table holds it); collectibles are "
                  "drawn from collectables_small.png (0x77)."),
    0x55: (False, "No code asks for picture 0x55 (no getter call names it and no table holds it); collectibles are "
                  "drawn from collectables_small.png (0x77)."),
    0x77: (True, "Collectibles and messes lying in the house and yard (0x413E40 -> 0x44EC90: cell number - 78, "
                 "loaded at 0x413A2C), carried by a family member (0x48A100) and fading when dropped (effect 0x12, "
                 "0x445D79)."),
    # people
    0x04: (True, "The big heads of the Adoption, Dating and family member screens' portraits (0x486B60)."),
    0x05: (True, "The big bodies of the portraits (0x486B60; loaded at 0x450B86)."),
    0x9C: (True, f"Female heads, {_PEOPLE} (0x48B936..0x48B96E)."),
    0x9D: (True, f"Female bodies, {_PEOPLE} (0x48B8AD..0x48B908)."),
    0x9E: (True, f"Female actions, {_PEOPLE}, and the outfits in the store (0x496A8D)."),
    0x9F: (True, f"Female sitting poses, {_PEOPLE}."),
    0xA0: (True, f"Male heads, {_PEOPLE} (0x48B936..0x48B96E)."),
    0xA1: (True, f"Male bodies, {_PEOPLE} (0x48B8AD..0x48B908)."),
    0xA2: (True, f"Male actions, {_PEOPLE}, and the outfits in the store (0x496A5F)."),
    0xA3: (True, f"Male sitting poses, {_PEOPLE}."),
    0xA4: (True, f"The shadow under a family member, {_PEOPLE} (0x48B6CA..0x48B730)."),
    0x68: (True, "What a family member carries (0x48A100), the pans, dishes and things left around in the house "
                 f"({_HOUSE}) and dropped things fading (effect 0xE, 0x445D79)."),
    0x00: (False, "Not a picture: entry 0 of the image table names no file; in the title screen's sprite list "
                  "0x56AB68 the number 0 means \"draw a family member\" (0x44CE44), and no getter is asked for it."),
}

# Cells the game always draws see-through or scaled: image id -> (scale, alpha, why).
CELL_DRAW = {
    0xA5: (1.0, RIPPLE_ALPHA, "The ripples are only ever drawn at alpha 0.4 (0x48B815: the float at 0x4D6EDC)."),
}


# ------------------------------------------------------------------ per-cell words
def _cell_labels() -> dict:
    out: dict = {}
    for effect, _key, label, _cat, _why in EFFECTS:
        image, frames, _rnd = EFFECT_TABLE[effect]
        for k, c in enumerate(frame_cells(image, frames)):
            out.setdefault((image, c), f"{label}, frame {k + 1}")
    for k in range(4):
        out[(0xA5, k)] = f"Ripples {k + 1}"
    for k in range(8):
        out[(0xAA, k)] = f"Shark heading {k + 1} of 8"
    out[(0x0F, 0)] = "Food being prepared (first stage)"
    out[(0x0F, 1)] = "Food being prepared (second stage)"
    out[(0x10, 0)] = "Workbench project (first stage)"
    out[(0x10, 1)] = "Workbench project (second stage)"
    for item in range(1, 64):
        if item in (18, 19, 61, 62, 63):
            continue
        out[(0xB8, 2 * item - 2)] = item_name(item)
        out[(0xB8, 2 * item - 1)] = f"{item_name(item)} (second picture)"
    for c, words in HOUSE_ITEM_CELLS.items():
        out[(0xB8, c)] = f"{out[(0xB8, c)]}: {words}"
    for item in (18, 19, 64, 65):
        out[(0xB8, 2 * item - 2)] = item_name(item)
        out[(0xB8, 2 * item - 1)] = f"{item_name(item)} (second picture)"
    for item in (61, 62, 63):
        out[(0xB8, 2 * item - 2)] = item_name(item)
        out[(0xB8, 2 * item - 1)] = f"{item_name(item)} (second picture)"
        pet = item_name(item)[4:]
        for col in range(24):
            out[(0x03, 24 * (item - 61) + col)] = f"{pet}, {PET_POSES[col]}"
        out[(0x03, 24 * (item - 61) + 16)] += " (also the store and item tray picture)"
        if item != 61:
            for col in range(20, 24):
                out[(0x03, 24 * (item - 61) + col)] = f"{pet}: blank (only the cat has pictures here)"
    for c, words in enumerate(("standing, facing right", "pecking, facing right", "standing, facing left",
                               "pecking, facing left")):
        out[(0xA8, c)] = f"Bird {words}"
    for k in range(4):
        out[(0xA8, 4 + k)] = f"Bird flapping, facing right, picture {k + 1} of 4"
        out[(0xA8, 8 + k)] = f"Bird flapping, facing left, picture {k + 1} of 4"
    out[(0xA9, 0)] = "Bird's shadow"
    for item in range(66, 81):
        out[(0xB9, item - 66)] = item_name(item)
    for value, thing in _CARRIED.items():
        if thing.file == "carrying.png":
            out[(0x68, thing.cell)] = thing.name
        else:
            out[(0x77, thing.cell)] = thing.name
    return out


CELL_LABELS = _cell_labels()

# How a cell's draw was checked, added to its "cut where GetCellRect cuts it" (vf1_art_sheets).
CELL_CHECKED = {
    **{(0x03, c): PET_CHECK for c in range(72) if c % 24 != PET_NEVER},
    **{(0xA8, c): BIRD_CHECK for c in range(12)},
    (0xA9, 0): BIRD_CHECK,
    **{(0xA5, c): RIPPLE_CHECK for c in range(4)},
    **{(0xAA, c): ("The shark's draw 0x430850, run in Unicorn for 16 headings, picks each of the 8 cells (the game "
                   "never runs it).") for c in range(8)},
}

_OUTFIT = ("The outfits are drawn from the people's action sheets with their outfit row (0x496A55..0x496A92), and "
           "that row is always set (0x496C8C..0x496CA8), so this picture is never used.")
_PET = "A pet's store and tray picture is pet_grid.png's column 16 (0x496A97..0x496AA2), never this cell."
_NO_ITEM = ("No item has this picture: 0x496A10 sends items 66 to 80 to home_grid.png (0x496AC3) and the ball's "
            "lookup 0x496C50 refuses items from 66 on.")
CARRYING_NEVER = (12, 32, 33, 43, 45)      # vf1_people_pictures.CARRYING_UNUSED less 21 and 24 (the house draws those)
CELL_UNUSED = {
    **{(0xB8, 2 * item - 2 + v): _OUTFIT for item in (18, 19, 64, 65) for v in (0, 1)},
    **{(0xB8, 2 * item - 2 + v): _PET for item in (61, 62, 63) for v in (0, 1)},
    **{(0xB8, c): _NO_ITEM for c in range(130, 140)},
    **{(0x68, c): ("No action carries it (see the people pictures' carried things) and no other code draws this "
                   "cell of carrying.png.") for c in CARRYING_NEVER},
    **{(0x03, 24 * pet + PET_NEVER): ("No code ever gives a pet pose 19: the pets' animations (0x433550) use "
                                      "poses 0..17 and 20..23 and the pose picker 0x4333C0 gives 16, 17, 18 or "
                                      "a walking pose, so the pet draw 0x434550 never draws this cell.")
       for pet in range(3)},
    (0x77, 63): "A cobweb is always number 0x8C, the first cobweb picture (0x414ED4); this second one is never drawn.",
    **{(0x77, c): ("This cell of collectables_small.png is blank, and the game refuses any number above 0x90 "
                   "(0x4135C0): nothing is drawn.") for c in range(67, 72)},
}
