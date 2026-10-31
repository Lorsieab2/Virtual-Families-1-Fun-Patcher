"""The Picture Maker's renderer: Virtual Families 1's family members (and the outfits in the store and the
tool tray) drawn exactly as the game draws them, from the game's own pictures, read at run time from the
chosen game folder.  Nothing here writes a file; vf1_picture_maker.py is the window.

Where every rule comes from (the vanilla Virtual Families.exe 1.01.00; tests/test_picture_maker.py runs
these functions in Unicorn and compares every draw and pixel):

* The pictures (theGraphicsManager's image table 0x4F2D00, 0x30 bytes an entry: id, file, columns, rows,
  files across): heads 0x9C female / 0xA0 male, 24 x 50 cells over two files ("..._heads00.png" columns
  0-11, "..._heads10.png" columns 12-23: ldwImageGrid::GetCellRect 0x40AD40 picks the file by column);
  bodies 0x9D / 0xA1 (32 x 50), actions 0x9E / 0xA2 (15 x 50), sitting 0x9F / 0xA3 (9 x 50), the big
  portrait bodies 0x05 (highrez_bodies_final2.png, 2 x 50: male, female) and heads 0x04 (bigheads00/10,
  12 x 50: three expressions male, three female, the 10 file the older look), the shadow 0xA4
  (peep_shadow1.png), what is carried 0x68 (carrying.png, 13 x 6) and 0x77 (collectables_small.png,
  6 x 12).  A cell is the file's width / columns by height / rows (0x40AE68).
* Where each part goes: Assets\\animpts.dat (loaded at 0x450F99: 4 + 0x2D084 bytes into the animation
  table 0x570408 + 0x76F0, 4 + 0x5EB0 bytes into + 0x34774).  Body table: 57 poses x 0xCA4 bytes, each a
  count and four 0x328-byte blocks (block 0 male, 2 female): picture, column, then per body row the neck
  point (+8) and the foot point (+0x198).  Head table: 30 blocks (gender x 15 + head turn): picture,
  column, per head row the head's point (+0x198).  After loading, 0x45102A..0x451174 overwrite every
  block's picture and column (POSE_SHEETS, HEAD_SHEETS below).
* The family member in the house (CVillagerManager 0x48B4D0): the shadow (0x48B6CA..0x48B730), what is
  carried behind (0x48A100, direction 0 / 3 / 4), the body (0x48B8AD..0x48B908), the head
  (0x48B936..0x48B96E), what is carried in front.  Under 14 (280 age units) the body is drawn at
  age / 700 + 0.5 (0x4868F0) and the head at (age / 14 + 80) / 100 (0x48B5FF); from 45 (900) the head
  column moves 12 on, into the ..._heads10.png file (0x48B5AE).  A ghost (+0x13540) is drawn at
  0.75 x (1 - t / 30) alpha and without a shadow (0x48B510).
* The portrait of the Adoption, Dating and family member screens (0x486B60): the big body (pose 56) and
  a big head, expression 12 + n % 3 (0x486C9C), the older look 6 columns on from 45 (0x486CD2).
* An outfit in the store or the tool tray (0x496A10): the actions sheet's column 14 (standing, facing
  you) at the outfit's picture row, centred.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

import vf1_picture_image as pi
import vf1_save

GAME_TITLE = "Virtual Families"
PATCHER_FOLDER = "Virtual Families 1 Patcher Files"
ORIGINALS = Path(PATCHER_FOLDER) / "Original Files"
ANIMPTS = Path("Assets") / "animpts.dat"
PAYLOAD = Path(__file__).resolve().parent / "payload"
# The patcher's own pictures for people's things (manifest.json): what is carried.
PATCHER_ART = {
    "carrying.png": ("CustomMapImages", "Custom Map/Game Images", Path("CustomImages") / "carrying.png"),
    "collectables_small.png": ("GlowingCollectables", "Glowing Collectables",
                               Path("GlowingCollectables") / "collectables_small.png"),
}

AGE_UNITS_PER_YEAR = vf1_save.AGE_UNITS_PER_YEAR
CHILD_UNTIL = 280            # 0x4868F7 / 0x48B5F4: drawn smaller below this age (14 years)
OLD_FROM = 900               # 0x48B5AE / 0x486CD2: the older head pictures from this age (45 years)

# image id: (file stem or name, columns, rows, files across); one file when files across is 1.
IMAGES = {
    0x9C: ("female_heads", 24, 50, 2), 0xA0: ("male_heads", 24, 50, 2),
    0x9D: ("female_bodies00.png", 32, 50, 1), 0xA1: ("male_bodies00.png", 32, 50, 1),
    0x9E: ("female_actions00.png", 15, 50, 1), 0xA2: ("male_actions00.png", 15, 50, 1),
    0x9F: ("female_sit00.png", 9, 50, 1), 0xA3: ("male_sit00.png", 9, 50, 1),
    0x04: ("bigheads", 12, 50, 2), 0x05: ("highrez_bodies_final2.png", 2, 50, 1),
    0xA4: ("peep_shadow1.png", 1, 1, 1), 0x68: ("carrying.png", 13, 6, 1),
    0x77: ("collectables_small.png", 6, 12, 1),
}
SHADOW, CARRYING, COLLECTABLES = 0xA4, 0x68, 0x77
CARRYING_CELLS, COLLECTABLE_CELLS = 78, 72
BUNDLE = 3                   # 0x48A159: a baby on the way is carrying.png's cell 3, one per baby


def image_files(image: int) -> list[str]:
    stem, _cols, _rows, files = IMAGES[image]
    return [stem] if files == 1 else [f"{stem}{k}0.png" for k in range(files)]


def required_files() -> list[str]:
    return sorted({name for image in IMAGES for name in image_files(image)})


# ------------------------------------------------------------------ poses
POSES = 57                   # 0..31 walking (eight steps in four directions), 32..46 actions, 47..55 sitting, 56 portrait
PORTRAIT_POSE = 56
STANDING_POSE = 46           # actions column 14: standing, facing you (the store's outfit picture, 0x496AF0)
FRONT_HEAD = 5               # head column 5 looks straight out
LOWERED_POSES = (48, 54)     # 0x48B578: drawn 20 pixels lower
HEAD_TURNS = 12
EXPRESSIONS = 3


def pose_sheet(pose: int, female: bool) -> tuple[int, int]:
    """(image, column) 0x45102A..0x451174 put in the pose's block."""
    if pose < 32:
        return (0x9D if female else 0xA1), pose
    if pose < 47:
        return (0x9E if female else 0xA2), pose - 32
    if pose < 56:
        return (0x9F if female else 0xA3), pose - 47
    if pose == PORTRAIT_POSE:
        return 0x05, 1 if female else 0
    raise pi.PictureError(f"There is no pose {pose}.")


def head_sheet(turn: int, female: bool) -> tuple[int, int]:
    """(image, column) of the head block gender x 15 + turn (0..11 the heads, 12..14 the big heads)."""
    if turn < 12:
        return (0x9C if female else 0xA0), turn
    if turn < 15:
        return 0x04, turn - 12 + (3 if female else 0)
    raise pi.PictureError(f"There is no head turn {turn}.")


@dataclass(frozen=True)
class Points:
    """Assets\\animpts.dat, as 0x450F99 loads it."""
    bodies: bytes        # 57 x 0xCA4 (table + 0x76F0)
    heads: bytes         # 30 x 0x328 (table + 0x34774)

    @classmethod
    def parse(cls, data: bytes) -> Points:
        try:
            n1 = struct.unpack_from("<I", data, 0)[0]
            if n1 != 0x2D084:
                raise ValueError
            bodies = data[4:4 + n1]
            n2 = struct.unpack_from("<I", data, 4 + n1)[0]
            if n2 != 0x5EB0:
                raise ValueError
            heads = data[8 + n1:8 + n1 + n2]
            if len(bodies) != n1 or len(heads) != n2:
                raise ValueError
        except (struct.error, ValueError):
            raise pi.PictureError("The game's Assets\\animpts.dat is not the one Virtual Families 1.01 has.") from None
        return cls(bytes(bodies), bytes(heads))

    def _point(self, table: bytes, at: int) -> tuple[int, int]:
        return struct.unpack_from("<ii", table, at)

    def body_points(self, pose: int, female: bool, row: int) -> tuple[tuple[int, int], tuple[int, int]]:
        """(neck, foot) of body row `row` in the pose's block (0x451430 / 0x4514A0)."""
        block = pose * 0xCA4 + 4 + (2 if female else 0) * 0x328
        return self._point(self.bodies, block + 8 + row * 8), self._point(self.bodies, block + 0x198 + row * 8)

    def head_point(self, turn: int, female: bool, row: int) -> tuple[int, int]:
        """The head's point (0x451540: block gender x 15 + turn, + 0x198 + row x 8)."""
        block = ((1 if female else 0) * 15 + turn) * 0x328
        return self._point(self.heads, block + 0x198 + row * 8)


def _round_half(value: int, scale: float) -> int:
    """trunc(value x scale + 0.5), as 0x451430 / 0x4514A0 / 0x451540 round a point (x87 doubles, ftol)."""
    return math.trunc(float(value) * scale + 0.5)


def body_scale(age: int) -> float:
    """CVillager 0x4868F0: age / 700 + 0.5 below 280, else 1 (a 32-bit float)."""
    return pi.f32(age / 700.0 + 0.5) if age < CHILD_UNTIL else 1.0


def head_scale(age: int) -> float:
    """0x48B5FF / 0x486BAF: (age / 14 + 80) / 100 below 280, else 1 (a 32-bit float)."""
    return pi.f32((age / 14.0 + 80.0) / 100.0) if age < CHILD_UNTIL else 1.0


# ------------------------------------------------------------------ life stages (the patcher's names)
STAGES = (("Baby", 0), ("Toddler", 1), ("Child", 4), ("Teen", 13), ("Adult", 18), ("Elder", 45))


def stage_name(age_units: int) -> str:
    years = max(0, age_units) // AGE_UNITS_PER_YEAR
    name = STAGES[0][0]
    for label, start in STAGES:
        if years >= start:
            name = label
    return name


def age_choices() -> list[tuple[int, str]]:
    """(age units, label) for Make your own: every year the game draws differently (each year under 14 is
    smaller), then one age for each look from 14 on."""
    out = [(y * AGE_UNITS_PER_YEAR, f"{stage_name(y * AGE_UNITS_PER_YEAR)}, {y} year{'s' if y != 1 else ''}")
           for y in range(14)]
    out += [(14 * AGE_UNITS_PER_YEAR, "Teen, 14-17 years (full size)"),
            (18 * AGE_UNITS_PER_YEAR, "Adult, 18-44 years"),
            (OLD_FROM, "Elder, 45 years and older (older head pictures)")]
    return out


def pose_choices() -> list[tuple[int, str]]:
    """(pose, label): the poses of the house view.  A walking step is the pose; its direction is a
    separate choice (the body column is step + 8 x direction, 0x48B5CE)."""
    out = [(STANDING_POSE, "Standing, facing you (the store's outfit picture)")]
    out += [(k, f"Walking, step {k + 1}") for k in range(8)]
    out += [(32 + k, f"Action pose {k + 1}") for k in range(15) if 32 + k != STANDING_POSE]
    out += [(47 + k, f"Sitting or lying pose {k + 1}") for k in range(9)]
    return out


# ------------------------------------------------------------------ the pictures


class Art:
    """The game's pictures from a game folder, read at run time (never copied, never shipped).

    look "game": the folder's Images as they are (the patched pictures if its patcher settings are on);
    "stock": the stock pictures (the patcher's backup in Original Files when a setting replaced one);
    "patched": the patcher's own pictures (payload) for what it replaces, else the folder's."""

    def __init__(self, folder: Path | None, look: str = "game", payload: Path | None = None) -> None:
        self.folder = Path(folder) if folder else None
        self.look = look
        self.payload = Path(payload) if payload is not None else PAYLOAD
        self._images: dict[str, pi.Image] = {}
        self._points: Points | None = None
        self._pieces: dict = {}

    def path(self, name: str) -> Path | None:
        if self.folder is None:
            return None
        if self.look == "patched" and name in PATCHER_ART:
            own = self.payload / PATCHER_ART[name][2]
            if own.is_file():
                return own
        if self.look == "stock":
            original = self.folder / ORIGINALS / "Images" / name
            if original.is_file():
                return original
        return self.folder / "Images" / name

    def patched_files(self) -> list[str]:
        """The people pictures this game folder has from the patcher (its Original Files keep the stock ones)."""
        if self.folder is None:
            return []
        return [name for name in PATCHER_ART if (self.folder / ORIGINALS / "Images" / name).is_file()]

    def image(self, name: str) -> pi.Image:
        key = f"{self.look}:{name.casefold()}"
        if key not in self._images:
            path = self.path(name)
            if path is None or not path.is_file():
                raise pi.PictureError(f"The game picture Images\\{name} was not found"
                                      + (f" in {self.folder}." if self.folder else ": pick the game folder."))
            try:
                self._images[key] = pi.decode_png(path.read_bytes())
            except OSError as exc:
                raise pi.PictureError(f"Images\\{name} could not be read: {exc}") from None
        return self._images[key]

    def size(self, name: str) -> tuple[int, int]:
        """(width, height) of a picture, from its PNG header (a plan needs no pixels)."""
        key = f"{self.look}:{name.casefold()}"
        if key in self._images:
            return self._images[key].width, self._images[key].height
        path = self.path(name)
        try:
            head = path.read_bytes()[:24] if path is not None else b""
        except OSError:
            head = b""
        if len(head) < 24 or not head.startswith(pi.PNG_MAGIC):
            self.image(name)                         # says what is wrong
        return struct.unpack(">II", head[16:24])

    def points(self) -> Points:
        if self._points is None:
            if self.folder is None or not (self.folder / ANIMPTS).is_file():
                raise pi.PictureError("The game's Assets\\animpts.dat was not found: pick the game folder.")
            self._points = Points.parse((self.folder / ANIMPTS).read_bytes())
        return self._points

    def problem(self) -> str:
        """"" when everything needed is there, else one line saying what is missing."""
        if self.folder is None:
            return "No game folder chosen: pick your Virtual Families folder to see the pictures."
        missing = [n for n in required_files() if self.path(n) is None or not self.path(n).is_file()]
        if not (self.folder / ANIMPTS).is_file():
            missing.insert(0, str(ANIMPTS))
        if missing:
            return f"Not a Virtual Families folder (missing {', '.join(missing[:3])}): {self.folder}"
        return ""


def cell(art: Art, image: int, column: int, row: int) -> tuple[str, tuple[int, int, int, int]]:
    """(file, cell rect) of a grid cell: ldwImageGrid::GetCellRect 0x40AD40, the file picked by column
    when the grid spans files, the column and row clamped to the grid (0x40AD91..)."""
    stem, cols, rows, files = IMAGES[image]
    per_file = cols // files
    column = min(max(0, column), cols - 1)
    row = min(max(0, row), rows - 1)
    name = image_files(image)[column // per_file]
    width, height = art.size(name)
    cw, ch = width // per_file, height // rows
    x = (column % per_file) * cw
    return name, (x, row * ch, x + cw, row * ch + ch)


def whole(art: Art, image: int) -> tuple[str, tuple[int, int, int, int]]:
    name = image_files(image)[0]
    width, height = art.size(name)
    return name, (0, 0, width, height)


# ------------------------------------------------------------------ what gets drawn


@dataclass(frozen=True)
class Person:
    female: bool
    age: int                 # age units (a year is 20)
    head: int                # bio +0x2C: the head picture row (hair and face)
    body: int                # bio +0x30: the body picture row (the outfit)
    babies: int = 0          # babies carried (0 = not expecting)


@dataclass(frozen=True)
class HouseView:
    pose: int = STANDING_POSE
    direction: int = 0       # 0..3, for the walking steps (villager +0x13580)
    head_turn: int = FRONT_HEAD
    shadow: bool = True
    ghost: bool = False
    carried: int = -1        # -1 nothing; 0..77 carrying.png; 78.. collectables_small.png (villager +0x1358C)


def house_plan(art: Art, person: Person, view: HouseView) -> list[pi.Draw]:
    """The draws of CVillagerManager 0x48B4D0 for one family member, their feet at (0, 0)."""
    if not 0 <= view.pose < PORTRAIT_POSE:
        raise pi.PictureError(f"There is no house pose {view.pose}.")
    points = art.points()
    female, age = person.female, person.age
    s_body, s_head = body_scale(age), head_scale(age)
    alpha = pi.f32(0.75) if view.ghost else 1.0
    pose = view.pose + 8 * view.direction if view.pose <= 7 else view.pose
    if not 0 <= pose < 32 and view.pose <= 7:
        raise pi.PictureError("A walking step has four directions.")
    lowered = 20 if view.pose in LOWERED_POSES else 0
    plan: list[pi.Draw] = []
    # The shadow (0x48B6CA): the shadow picture at the scale of the body, centred on the feet, none for a ghost.
    if view.shadow and not view.ghost:
        file, rect = whole(art, SHADOW)
        plan.append(pi.Draw("shadow", file, rect, -math.trunc(34.0 * s_body), -math.trunc(32.0 * s_body),
                            pi.percent_scale(s_body)[1], alpha))
    # What is carried (0x48A100) is drawn from the family member's place (FeetPos 0x4869C0 backwards).
    carried = _carried_draws(art, person, view, s_body, lowered)
    behind = view.direction in (0, 3, 4)       # 0x48B764: the direction field, whatever the pose
    if behind:
        plan += carried
    neck, foot = points.body_points(pose, female, person.body)
    image, column = pose_sheet(pose, female)
    file, rect = cell(art, image, column, person.body)
    bx, by = -_round_half(foot[0], s_body), lowered - _round_half(foot[1], s_body)
    plan.append(pi.Draw("body", file, rect, bx, by, pi.percent_scale(s_body)[1], alpha))
    hx, hy = bx + _round_half(neck[0], s_body), by + _round_half(neck[1], s_body)
    hp = points.head_point(view.head_turn, female, person.head)
    image, _column = head_sheet(view.head_turn, female)
    file, rect = cell(art, image, view.head_turn + (12 if age >= OLD_FROM else 0), person.head)
    plan.append(pi.Draw("head", file, rect, hx - _round_half(hp[0] + 6, s_head), hy - _round_half(hp[1] + 3, s_head),
                        pi.percent_scale(s_head)[1], alpha))
    if not behind:
        plan += carried
    return plan


def _carried_draws(art: Art, person: Person, view: HouseView, s_body: float, lowered: int) -> list[pi.Draw]:
    """0x48A100: the babies on the way (carrying.png cell 3, one to three) and what is carried, unscaled
    (0x44EC90 at 100%), from the family member's place: (feet x + trunc(-28 x s), feet y + trunc(-81 x s))
    (0x4869C0), lowered as the body is, plus (trunc(s x trunc(7 z)), trunc(s x trunc(33 z))) for the view's
    zoom z (0x56B800 + 0x300C, 1 at the game's size; 0x48B78E..0x48B7D2)."""
    x = math.trunc(-28.0 * s_body) + math.trunc(7 * s_body)
    y = math.trunc(-81.0 * s_body) + math.trunc(33 * s_body) + lowered
    out: list[pi.Draw] = []
    if person.babies > 0:
        spots = [(x - 10, y - 10)]
        if person.babies > 1:
            spots.append((x - 15, y - 5))
        if person.babies == 3:
            spots.append((x - 10, y - 1))
        for sx, sy in spots:
            file, rect = cell(art, CARRYING, BUNDLE % 13, BUNDLE // 13)
            out.append(pi.Draw("baby on the way", file, rect, sx, sy))
    item = view.carried
    if item >= 0 and item != BUNDLE:
        if item >= CARRYING_CELLS:
            k = item - CARRYING_CELLS
            file, rect = cell(art, COLLECTABLES, k % 6, k // 6)
            out.append(pi.Draw("carried", file, rect, x, y))
        else:
            file, rect = cell(art, CARRYING, item % 13, item // 13)
            out.append(pi.Draw("carried", file, rect, x - 10, y - 10))
    return out


def portrait_plan(art: Art, person: Person, expression: int = 0) -> list[pi.Draw]:
    """The draws of CVillager 0x486B60 (the Adoption, Dating and family member screens), its point at (0, 0)."""
    points = art.points()
    female, age = person.female, person.age
    s_body, s_head = body_scale(age), head_scale(age)
    neck, foot = points.body_points(PORTRAIT_POSE, female, person.body)
    image, column = pose_sheet(PORTRAIT_POSE, female)
    file, rect = cell(art, image, column, person.body)
    bx, by = -_round_half(foot[0], s_body), -_round_half(foot[1], s_body)
    plan = [pi.Draw("body", file, rect, bx, by, pi.percent_scale(s_body)[1])]
    hx, hy = bx + _round_half(neck[0], s_body), by + _round_half(neck[1], s_body)
    turn = 12 + expression % EXPRESSIONS
    hp = points.head_point(turn, female, person.head)
    image, column = head_sheet(turn, female)
    file, rect = cell(art, image, column + (6 if age >= OLD_FROM else 0), person.head)
    plan.append(pi.Draw("head", file, rect, hx - _round_half(hp[0] + 6, s_head), hy - _round_half(hp[1] + 3, s_head),
                        pi.percent_scale(s_head)[1]))
    return plan


OUTFIT_PERCENT = 70          # 0x496B5A: the store and the tray draw an outfit at 70%


def outfit_plan(art: Art, female: bool, picture: int) -> list[pi.Draw]:
    """An outfit as the store and the tool tray draw it (0x496A10): actions column 14 (standing, facing
    you), row = the picture, its cell centred on the place and 2 pixels lower (0x496B19..0x496B46), drawn at
    70% (0x409A40 -> 0x408D20) and centred again on the shrunk size, which 0x407F00 rounds
    (trunc(w x 0.7 + 0.5)) and halves toward zero."""
    file, rect = cell(art, 0x9E if female else 0xA2, 14, picture)
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    percent, scale = OUTFIT_PERCENT, pi.f32(OUTFIT_PERCENT / 100.0)
    s = pi.f32(percent / 100.0)

    def shift(size: int) -> int:
        rounded = math.trunc(size * s + 0.5)
        return -int((rounded - size) / 2)
    return [pi.Draw("outfit", file, rect, -int(w / 2) + shift(w), -int(h / 2) + 2 + shift(h), scale)]


def layer(art: Art, call: pi.Draw) -> pi.Image:
    key = (art.look, call.file, call.rect, call.scale, call.alpha)
    if key not in art._pieces:
        art._pieces[key] = pi.game_layer(art.image(call.file), call.rect, call.scale, call.alpha)
    return art._pieces[key]


def render_plan(art: Art, plan: list[pi.Draw]) -> pi.Image:
    """The plan drawn in order on a transparent canvas just big enough for it."""
    pieces = [(call, layer(art, call)) for call in plan]
    if not pieces:
        return pi.Image(1, 1)
    left = min(c.x for c, _p in pieces)
    top = min(c.y for c, _p in pieces)
    right = max(c.x + p.width for c, p in pieces)
    bottom = max(c.y + p.height for c, p in pieces)
    canvas = pi.Image(max(1, right - left), max(1, bottom - top))
    for call, piece in pieces:
        canvas.draw(piece, call.x - left, call.y - top)
    return canvas


# ------------------------------------------------------------------ the save


@dataclass(frozen=True)
class Slot:
    slot: int
    path: Path
    family: str


def save_slots(folder: Path) -> list[Slot]:
    """The family saves in a save folder (slots 1-5), read only."""
    out = []
    for slot in range(1, 6):
        path = Path(folder) / f"{vf1_save.SAVE_PREFIX}{slot}.ldw"
        if not path.is_file():
            continue
        try:
            save = vf1_save.read_save(path)
        except (OSError, vf1_save.SaveFormatError, struct.error):
            continue
        out.append(Slot(slot, path, save.family_name or f"Family {slot}"))
    return out


GS_INVENTORY, GS_TOOL_TRAY = vf1_save.GS_INVENTORY, vf1_save.GS_TOOL_TRAY
MALE_OUTFIT, FEMALE_OUTFIT = 64, 65
TRAY_PLACES = 8
OUTFITS_FOLDER = Path(vf1_save.PATCHER_DATA) / "Outfits"


def _gs(payload: bytes, gs: int) -> int:
    return struct.unpack_from("<i", payload, gs - vf1_save.GS_BASE)[0]


def outfit_sidecar(folder: Path, save_path: Path, payload: bytes) -> list[int] | None:
    """The outfit fix's pictures for the tray's eight places (native/vf1fun/outfits.inc), when its sidecar
    is sound and describes exactly this save's tray and outfit fields; else None (the stock game's)."""
    path = Path(folder) / OUTFITS_FOLDER / f"{save_path.name}.dat"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    size = 24 + TRAY_PLACES * 8 + 5 * 4 + TRAY_PLACES * 4 + 8
    if len(data) != size or data[:8] != b"VF1OUTFT" or data[12:20] != b"VF1V101\0" \
            or struct.unpack_from("<I", data, 8)[0] != 1 or struct.unpack_from("<I", data, 20)[0] != size:
        return None
    h = 0xCBF29CE484222325
    for b in data[:-8]:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    if struct.unpack_from("<Q", data, size - 8)[0] != h:
        return None
    binding = b"".join(struct.pack("<ii", _gs(payload, GS_TOOL_TRAY + k * 8), _gs(payload, GS_TOOL_TRAY + k * 8 + 4))
                       for k in range(TRAY_PLACES))
    binding += b"".join(struct.pack("<i", _gs(payload, GS_INVENTORY + f)) for f in (0x108, 0x10C, 0x110, 0x114, 0x118))
    if data[24:24 + len(binding)] != binding:
        return None
    pictures = list(struct.unpack_from(f"<{TRAY_PLACES}i", data, 24 + len(binding)))
    if any(p != -1 and not 0 <= p < 50 for p in pictures):
        return None
    return pictures


@dataclass(frozen=True)
class SavedThing:
    item: pi.SavedItem
    person: Person | None = None
    outfit: tuple[bool, int] | None = None   # (female, picture)
    dead: bool = False


def saved_things(folder: Path, slot: int) -> list[SavedThing]:
    """Everything the save holds that the game draws: its family members (at home, then those who left
    home), then the outfits in the store and the tool tray.  Read only."""
    path = Path(folder) / f"{vf1_save.SAVE_PREFIX}{slot}.ldw"
    save = vf1_save.read_save(path)
    out: list[SavedThing] = []
    unborn = {s for s in save.pending_babies if 0 <= s < vf1_save.VILLAGER_SLOTS}   # not drawn until born
    members = [v for v in save.household() if not v.is_empty and v.slot not in unborn]
    for v in sorted(members, key=lambda v: (v.left_home, -v.age_units)):
        years = v.years
        stage = stage_name(v.age_units)
        state = []
        if v.dead:
            state.append("deceased")
        if v.pregnant and not v.dead:
            state.append(f"expecting {'twins' if v.babies_carried == 2 else 'triplets' if v.babies_carried == 3 else 'a baby'}")
        sex = "female" if v.sex == 1 else "male"
        label = f"{v.name or 'Unnamed'} ({sex}, {stage.lower()}, {years} year{'s' if years != 1 else ''})"
        detail = (f"{v.name}: {sex}, {years} years ({v.age_units} age units), hair and face {v.head}, outfit {v.body}"
                  + (f"; {', '.join(state)}" if state else "") + ".")
        location = "Left home" if v.left_home else "The family"
        person = Person(female=v.sex == 1, age=max(0, v.age_units), head=v.head, body=v.body,
                        babies=v.babies_carried if v.pregnant and not v.dead else 0)
        out.append(SavedThing(pi.SavedItem(f"member:{v.slot}", label + (" (deceased)" if v.dead else ""), location,
                                           "family member", detail), person=person, dead=v.dead))
    payload = save.payload
    fixed = outfit_sidecar(Path(folder), path, payload)
    store = [(False, _gs(payload, GS_INVENTORY + 0x108)), (True, _gs(payload, GS_INVENTORY + 0x10C))]
    for female, picture in store:
        if 0 <= picture < 50:
            word = "Female" if female else "Male"
            out.append(SavedThing(pi.SavedItem(f"store:{word.lower()}", f"{word} Outfit for sale (outfit {picture})",
                                               "Store and tool tray", "outfit",
                                               f"The store's {word} Outfit: outfit {picture}."), outfit=(female, picture)))
    for place in range(TRAY_PLACES):
        item = _gs(payload, GS_TOOL_TRAY + place * 8)
        if item not in (MALE_OUTFIT, FEMALE_OUTFIT):
            continue
        female = item == FEMALE_OUTFIT
        own = fixed[place] if fixed is not None else -1
        picture = own if own >= 0 else _gs(payload, GS_INVENTORY + (0x114 if female else 0x110))
        if not 0 <= picture < 50:
            continue
        word = "Female" if female else "Male"
        how = ("its own picture, kept by the patcher's outfit fix" if own >= 0 else
               "the last one bought (the stock game shows every outfit of a kind as the last one bought)")
        out.append(SavedThing(pi.SavedItem(f"tray:{place}", f"{word} Outfit in the tool tray, place {place + 1} "
                                           f"(outfit {picture})", "Store and tool tray", "outfit",
                                           f"Tool tray place {place + 1}: a {word} Outfit, outfit {picture}: {how}."),
                              outfit=(female, picture)))
    return out


# ------------------------------------------------------------------ for the window

VIEWS = (("house", "In the house"), ("portrait", "Portrait (Adoption, Dating and family member screens)"),
         ("outfit", "Outfit (as the store and the tool tray show it)"))
DIRECTIONS = tuple((d, f"Direction {d + 1}") for d in range(4))
HEAD_TURN_CHOICES = tuple((t, f"Head turn {t + 1}" + (" (looking at you)" if t == FRONT_HEAD else ""))
                          for t in range(HEAD_TURNS))
EXPRESSION_CHOICES = tuple((e, f"Expression {e + 1}") for e in range(EXPRESSIONS))
LOOKS = (("game", "As this game folder has them"), ("stock", "Stock game"),
         ("patched", "Patched (Custom Map/Game Images, Glowing Collectables)"))


def carried_choices() -> list[tuple[int, str]]:
    """(villager +0x1358C, label): nothing, a carrying.png cell (0-77, the patcher's Custom Map/Game Images
    replaces three) or a collectables_small.png cell (78 on, Glowing Collectables replaces them all)."""
    out = [(-1, "Nothing")]
    out += [(k, f"Carried thing {k + 1} (carrying.png)") for k in range(CARRYING_CELLS) if k != BUNDLE]
    out += [(CARRYING_CELLS + k, f"Collectable {k + 1} (collectables_small.png)") for k in range(COLLECTABLE_CELLS)]
    return out


def render(art: Art, spec: dict) -> pi.Image:
    """A picture from a spec: {"view": "house" | "portrait" | "outfit", "female", "age", "head", "body",
    "babies", "pose", "direction", "head_turn", "shadow", "ghost", "carried", "expression", "picture"}."""
    view = spec.get("view", "house")
    female = bool(spec.get("female"))
    if view == "outfit":
        return render_plan(art, outfit_plan(art, female, int(spec.get("picture", spec.get("body", 0)))))
    person = Person(female=female, age=int(spec.get("age", 600)), head=int(spec.get("head", 0)),
                    body=int(spec.get("body", 0)), babies=int(spec.get("babies", 0)))
    if not (0 <= person.head < 50 and 0 <= person.body < 50):
        raise pi.PictureError("Hair and face and outfit pictures are numbered 0 to 49.")
    if view == "portrait":
        return render_plan(art, portrait_plan(art, person, int(spec.get("expression", 0))))
    house = HouseView(pose=int(spec.get("pose", STANDING_POSE)), direction=int(spec.get("direction", 0)),
                      head_turn=int(spec.get("head_turn", FRONT_HEAD)), shadow=bool(spec.get("shadow", True)),
                      ghost=bool(spec.get("ghost", False)), carried=int(spec.get("carried", -1)))
    return render_plan(art, house_plan(art, person, house))
