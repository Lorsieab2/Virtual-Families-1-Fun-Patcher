"""The Family Tree Maker's family tree picture (vf1_genealogy's family, drawn).

A port of the Virtual Villagers Fun Patcher's renderer (src/vv_family_tree.py, Lorsieab2/Virtual-Villagers-Fun-
Patcher main ede00e7e), kept as close to it as Virtual Families 1 allows, so its shapes, borders, marks,
descriptors, text boxes, colour schemes, per-group settings, pages and picture export work the same.  What
differs for Virtual Families 1:

* The faces are the game's own head sprites, Images\\male_heads00.png and female_heads00.png in the game
  folder: 12 columns x 50 rows of 56 x 56 pixels (the executable's image table, 0x4F4A74 / 0x4F49B4: 24
  columns over the files 00 and 10, 50 rows; the head draw passes the head value as the row, 0x48B964).
  Column 5 is the face looking straight out (seen on the sheet); the young sheet (00) at every age.
* Row g holds the couple of the save's Family Tree generation g; their children are the row below.  The
  descriptors are Founder, Heir, "Married in", "Adopted" and "Left home" (the save keeps no twins).
* The edits are kept per save in Virtual Families 1 Patcher\\Save <N>\\Data\\Family Tree beside the save; the
  page and pictures in Virtual Families 1 Patcher\\Save <N>\\Family Tree.

What follows is the Virtual Villagers description, which still holds.  The owner (2026-10-07) showed a hand-made Secret City tree and asked for the same: one row per
generation, each family member with "the name, age in game units and years", "as many colors as needed
to distinguish the family lines", "pictures of the correct head values", and "twins and triplets
should be connected with a triangle".  Later the same day: the heads are "the same head sprite as
you use for the Origins Change Appearance menus"; "deceased family members should not be faded (hard to
read), just put (deceased) in their entry"; and an expecting mother gets "another child with a
diamond portrait that says Upcoming child".

* Each family member is a frame -- square for a male, round for a female (the owner's example) -- with
  the head Change Appearance shows: the whole 40x65 cell of column 5 of the game's own head sheet
  in the game folder's Images, the row the head value, the young sheet at every age.
  Without the game folder the frame shows the initial instead.
* A baby on the way is a diamond, "Upcoming child", under its mother and the expected father.
* Each family -- a mother and father and their children -- has a colour of its own: the lines from
  the parents to the children, and the children's frames.  Founders' frames are grey.
* Children born together hang from one point of their family's line, which opens into a triangle.
* Family Members with no recorded parent or child sit apart, under "Other Members", level with their
  generation.
* The player's marks and edits (the owner: "mark special family members with a border (any color) with a
  matching key", "make all the fields editable in case there are errors or the player wants to
  type something in a portrait"): every entry's lines, the title and the generation labels may be
  replaced, and any family member may carry a mark of the player's own -- a label and a colour -- drawn
  as a second border, every mark listed in the Key.  They are kept in the save's own
  Virtual Families 1 Patcher\\Save <S>\\Data\\Family Tree Edits (for an older save, Virtual Families
  Fun Patcher Data\\Family Tree Edits), by family member (name, head and body), so a new tree keeps them.

The page is HTML with the tree in SVG; the picture (PNG or JPG) is drawn with Windows' own GDI+
(src/vf1_gdiplus.py): nothing to install.
"""
from __future__ import annotations

import base64
import bisect
import html
import json
import functools
import heapq
import math
import re
import struct
import zlib
from copy import copy as _copy
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import vf1_genealogy as gen

NODE_W = 106
NODE_H = 156
TRANSPARENT = "transparent"             # a colour that shows nothing (the owner asked for it)
LINE_WIDTH = 2.2                        # a family line's weight unless the player says
GAP_X = 22
GAP_MIN, GAP_MAX = 0.0, 400.0           # the player's gap between portraits
TEXT_ALIGNS = {"left": "Left", "centre": "Centre", "right": "Right"}
# The special borders' colours: natural (rope-coloured rope, green vines and leaves, red hibiscus), the
# flowers in a rainbow round the border, the player's own colour for each part, or the player's 2-7
# colours by turns or blending round the border -- always shaded and outlined from each colour.
SPECIAL_COLOUR_MODES = {"natural": "Natural", "rainbow": "Rainbow flowers", "pick": "Pick colours",
                        "alternate": "Alternating colours", "gradient": "Gradient"}
SPECIAL_PARTS = {"rope": "Rope", "vine": "Vine", "leaf": "Leaves", "flower": "Flowers"}
NATURAL = {"rope": "#c9a06a", "vine": "#5b8a35", "leaf": "#6aa83e", "flower": "#e8335a"}
RAINBOW = ("#e53935", "#fb8c00", "#fdd835", "#43a047", "#1e88e5", "#3949ab", "#8e24aa", "#ec407a")
STAMEN = "#f2c230"
# How deep the rainbow is (the owner, 2026-10-09, choosing "15% deeper" for the rope and the flowers alike,
# and as the default): (words, how much of the pure colour is kept).
RAINBOW_STRENGTHS = {"bright": ("Bright", 1.0), "medium": ("Medium", 0.85), "deep": ("Deep", 0.75)}
# Colour schemes for the tree's other parts (the owner, 2026-10-09: rainbow and alternating colours "for
# special marks, plain portrait borders, portrait insides, family lines, detail lines"): as set, a rainbow
# (at the Rainbow strength), or the special borders' 2-7 colours by turns.  Borders and marks run round
# each outline; insides across the tree, villager by villager; family lines family by family; detail
# lines line by line.
COLOUR_SCHEMES = {"own": "Normal", "rainbow": "Rainbow", "alternate": "Alternating colours"}
SCHEME_PARTS = {"borders": "Portrait borders", "marks": "Special marks", "insides": "Portrait insides",
                "details": "Detail lines", "lines": "Family lines"}
# Natural hibiscus colours (the owner, 2026-10-09): each its petals and its darker "eye" in the middle,
# as the flowers grow; or all of them taking turns, or blending from one to the next, round the border
# (in HIBISCUS_ORDER).
HIBISCUS = {"red": ("Red", "#e8335a", "#8c1030"), "pink": ("Pink", "#f48fb6", "#b0124f"),
            "yellow": ("Yellow", "#f7cf3a", "#b3122e"), "orange": ("Orange", "#f5892c", "#a3121f"),
            "white": ("White", "#f8f4ec", "#c2185b"), "purple": ("Purple", "#a86ad0", "#4a1466")}
HIBISCUS_CHOICES = {**{k: v[0] for k, v in HIBISCUS.items()}, "alternate": "Alternating natural colours",
                    "gradient": "Gradient natural colours"}
HIBISCUS_ORDER = ("red", "orange", "yellow", "white", "pink", "purple")


def _colour_ok(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def _mix(a: str, b: str, f: float) -> str:
    """`a` f of the way to `b`."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * f) for x, y in zip(ca, cb))


def _shade(colour: str, f: float) -> str:
    """Darker (f < 1, towards black) or lighter (f > 1, towards white)."""
    return _mix(colour, "#000000", 1 - f) if f <= 1 else _mix(colour, "#ffffff", f - 1)


def _blend_round(colours: list, t: float) -> str:
    """The colour `t` (0-1) of the way round a closed border blending through `colours` and back."""
    n = len(colours)
    x = (t % 1.0) * n
    i = int(x)
    return _mix(colours[i % n], colours[(i + 1) % n], x - i)
TEXT_ROOMS = {"auto": "Automatic", "shape": "Follow the shape", "rect": "Rectangle", "oval": "Oval"}
TEXT_VALIGNS = {"top": "Top", "middle": "Middle", "bottom": "Bottom"}
ROW_GAP_MIN, ROW_GAP_MAX = 0.0, 400.0   # the player's room under each generation's row (Edits.row_gap)
FIT_MIN, FIT_MAX = 400, 100000          # the page width portraits shrink to fit
CANVAS_MIN, CANVAS_MAX = 100, 30000     # a custom canvas's width and height (Edits.canvas_w / canvas_h)
# The ready-made canvas sizes (the owner, 2026-10-09), width x height in pixels; print sizes at 300 dpi.
CANVAS_SIZES = {
    "HD (1920 x 1080)": (1920, 1080),
    "4K (3840 x 2160)": (3840, 2160),
    "Square (2048 x 2048)": (2048, 2048),
    "A4 portrait (2480 x 3508, 300 dpi)": (2480, 3508),
    "A4 landscape (3508 x 2480, 300 dpi)": (3508, 2480),
    "US Letter portrait (2550 x 3300, 300 dpi)": (2550, 3300),
    "US Letter landscape (3300 x 2550, 300 dpi)": (3300, 2550),
    "Phone wallpaper (1080 x 1920)": (1080, 1920),
}
SHRINK_MIN = 0.2                        # never smaller than a fifth
PAGE_GENS, PAGE_GENS_MIN, PAGE_GENS_MAX = 6, 2, 10   # generations on one page: the owner's default and limit
TEXT_SCALE_MIN, TEXT_SCALE_MAX = 25.0, 400.0          # one villager's text size, in percent
# The picture (the face) and the words inside a portrait, apart from the shape (the owner, 2026-10-09: "i
# want to be able to resize the villager's picture and text within the shape"): in percent, for every
# portrait (Edits.picture_size, Edits.text_size) and for one villager (entry "picture_scale", "text_scale").
PICTURE_SCALE_MIN, PICTURE_SCALE_MAX = 25.0, 400.0
# Each generation's row on the tree (the owner, 2026-10-09: "justify portraits ... top middle bottom ...
# left right center"; then: "Line up each row"): the row across the tree, and the portraits in it, of
# different sizes, lined up by their tops, middles or bottoms.
ROW_ALIGNS = {"arranged": "As arranged", "left": "Left", "centre": "Centre", "right": "Right"}
ROW_VALIGNS = {"middle": "Middles", "top": "Tops", "bottom": "Bottoms"}
# The most portraits side by side in a generation's row before it wraps into another row (the owner,
# 2026-10-09: "can I define a max # of portraits per row? ... want to stack portraits to make the tree more
# compact"); 0 is no limit.
ROW_LIMIT_MAX = 99
LEFT = 300                      # the generation labels' column
TOP = 150
OTHER_GAP = 110                 # between the tree and the "Other Members" column

# Virtual Families 1's head sheets: 56 x 56 cells, 12 columns and 50 rows per file (the executable's image
# table: male_heads 0x4F4A74, female_heads 0x4F49B4 -- 24 columns over the files 00 and 10, 50 rows; the head
# draw 0x48B964 passes the head value as the row).  Column 5 is the face looking straight out (seen on the
# sheet), always from the young sheet (00), never the older-looking one (10).
HEAD_W, HEAD_H = 56, 56
HEAD_FRAME = 5
HEAD_SCALE = 3 / 2                # tkinter scales by whole ratios: zoom 3, subsample 2
LINE_H = 13
# The face reaches at most 39 rows down column 5 of either sheet (measured; long hair reaches 52): centring is
# by the face, the cell drawn whole.
FACE_H = 40
MARK_GAP = 6                    # the player's mark: a second border this far outside the frame

# Each game's head sheets: (male, female).  Only the young ones, at every age (the owner: "I don't
# want any 'Old' villager heads to be on the tree. For any game").
SHEETS = {
    gen.GAME: ("male_heads00.png", "female_heads00.png"),
}

BACKGROUND = "#e8f0e0"
PICTURES = Path(__file__).resolve().parent / "tree_pictures"   # the owner's backgrounds and logos, shipped beside the patcher
# The owner: "Generations should not necessarily be on the exact same row.  Feel free to vary
# their position vertically/horizontally like my example for legibility.  (add a toggle: One
# straight row vs dynamic positioning)".
POSITIONING = {"dynamic": "Families under their parents", "rows": "One straight row per generation",
               # The owner's two hand-made trees, 2026-10-09 ("cluster portraits like this", "I want tightly-
               # packed portraits"), packed as tightly as Edits.packing says.  Packed families (their VV5
               # tree): each family's children a small block of short rows nestled into the free space
               # nearest under their parents, at whatever height that is.  Packed generations (their VV3
               # tree): the generations' bands kept, each family a block packed like bricks into as many
               # staggered rows as its band needs.
               "packed_families": "Packed families", "packed_generations": "Packed generations"}
# Where the Other Members go (Edits.others_side) and how many across (Edits.others_columns: 1 is each
# generation's in one row, as before; more is a grid that many across, a generation at a time).
OTHERS_SIDES = {"right": "on the right", "left": "on the left"}
OTHERS_COLUMNS_MAX = 6
PACKING = 60                    # the Packed layouts' packing until the player says (Edits.packing)
CORRIDOR = 20                  # between two families' clusters: room for a line to pass (2 * CLEAR + 6)
NUMBERINGS = {"roman": "Roman numerals (I, II, III)", "numbers": "Numbers (1, 2, 3)"}
# The parts of a generation's label the player may delete one by one (the owner: ""Founders" "I."
# "5 Total: ..." "0 living" etc.").
LABEL_PARTS = {"number": "the number", "name": "the name", "total": "the totals line", "living": "the living line",
               "upcoming": "the upcoming line"}
SUBGAP = 46                     # between two rows of one generation: room for a line to step sideways
SUB_COST = 8                    # how many places a family may move along rather than step down a row
MAX_SUBROWS = 4
FITS = {"contain": "Whole picture (nothing cut off)", "cover": "Fill the page (cuts off the edges)",
        "stretch": "Stretch to the page", "tile": "Repeat (tile)"}
# The classic rainbow ombre the owner showed: every bright hue, red at both ends, drawn across the page
# (left to right) or down it (top to bottom).
RAINBOW = ["#ff0000", "#ff00ff", "#6000ff", "#0060ff", "#00ffff", "#00ff00", "#ffff00", "#ff8000", "#ff0000"]
RAINBOWS = {"rainbow-across": "across", "rainbow-down": "down"}
# Ready-made backgrounds: (name, colour, gradient's lower colour, a RAINBOWS key, or "", picture or "").  A picture
# is "asset:" one of the owner's own, shipped beside the patcher in tree_pictures (the colour is the picture's
# average middle, under its transparent edges), or one of the games' own, never shipped with the patcher: "game:"
# is in this game's Images folder, "vvN:" in game N's (found through the game folders the patcher knows), so a
# preset is offered only when its picture is there.
PRESETS = [
    ("Leaf green (the patcher's own)", BACKGROUND, "", ""),
    ("Parchment", "#f3e7c9", "#e2cfa0", ""),
    ("Sea and sand", "#bfe3ef", "#efe2bb", ""),
    ("Sunset", "#ffd9a8", "#f2a7a0", ""),
    ("Moonlit night", "#2b3550", "#141a2b", ""),
    ("Jungle", "#d7ead0", "#7fa86f", ""),
    ("Lagoon", "#d4f1ee", "#5fa8a6", ""),
    ("Volcano", "#f6d2a2", "#7a3b2e", ""),
    ("White", "#ffffff", "", ""),
    ("Rainbow (across)", "#ffffff", "rainbow-across", ""),
    ("Rainbow (top to bottom)", "#ffffff", "rainbow-down", ""),
    ("The tree in vines", "#abd0b1", "", "asset:tree-in-vines.png"),
    ("The blue board on wood", "#5c8dcf", "", "asset:blue-board-on-wood.png"),
    ("Wood and magnifying glass", "#dc6707", "", "asset:wood-and-magnifier.png"),
    ("Sand in a black frame", "#a88c68", "", "asset:sand-in-black-frame.png"),
    ("Canvas in a wooden frame", "#d0cfcd", "", "asset:canvas-in-wood-frame.png"),
    ("The deck and the hose", "#8c5929", "", "asset:deck-and-hose.png"),
    ("Autumn paving", "#a77647", "", "asset:autumn-paving.png"),
    ("Grass and acorns", "#469f21", "", "asset:grass-and-acorns.png"),
    ("The blue rose", "#767160", "", "asset:blue-rose.png"),
    ("The garden gate", "#88844e", "", "asset:garden-gate.png"),
    ("The stone patio", "#9198a5", "", "asset:stone-patio.png"),
    ("Seeds and a trowel", "#837f70", "", "asset:seeds-and-trowel.png"),
    ("The island map", "#426141", "", "asset:island-map.png"),
    ("Aquarium with a rock arch", "#367f8a", "", "asset:aquarium-rock-arch.png"),
    ("Aquarium with driftwood", "#53918d", "", "asset:aquarium-driftwood.png"),
    ("Aquarium with coral", "#7994c6", "", "asset:aquarium-coral.png"),
]
INK = "#1d2a1d"
LIGHT_INK = "#f4f1e6"
GREY = "#8a8f88"


# The owner: "distinct colors for every single individual unrelated person, siblings that share
# both parents to have the same color.  Each pairing has a single-color connector.  Each set of
# full siblings has a single-color connector that's different from their parents", "I literally
# use all colors in my example - shades of gray, white, red, tan, orange, pink... everything."
# So the colours are every colour of a fine grid -- greys, white, tans and pastels included -- taken
# one at a time, each the one that looks least like every colour already taken and like the
# background (CIE Lab distance), so each is as distinct as any can be and none fades into the
# background.
_LEVELS = (0, 51, 102, 153, 204, 255)
_GRID = ["#%02x%02x%02x" % (r, g, b) for r in _LEVELS for g in _LEVELS for b in _LEVELS] + [
    "#d2b48c", "#c0c0c0", "#808080", "#404040", "#f5deb3", "#ffc0cb", "#ffa500", "#a0522d"]
_SEEN: dict = {}


def _lab(colour: str) -> tuple[float, float, float]:
    if colour == TRANSPARENT:                   # colours are kept apart from the page underneath
        colour = BACKGROUND
    def linear(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(int(colour[i:i + 2], 16)) for i in (1, 3, 5))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def distinct_colours(n: int, background: str = BACKGROUND, avoid: tuple = ()) -> list[str]:
    """n colours, each as unlike the others, the background and the colours to `avoid` as the
    grid allows (they come round again only past the grid's last)."""
    key = (n, background, avoid)
    if key not in _SEEN:
        points = {c: _lab(c) for c in _GRID}
        kept = [_lab(background)] + [_lab(c) for c in avoid]
        nearest = {c: min(math.dist(lab, k) for k in kept) for c, lab in points.items()}
        out: list[str] = []
        while len(out) < n:
            if not nearest:
                out += out[:n - len(out)]
                break
            pick = max(nearest, key=lambda c: (nearest[c], c))
            out.append(pick)
            del nearest[pick]
            for c in nearest:
                nearest[c] = min(nearest[c], math.dist(points[c], points[pick]))
        _SEEN[key] = out
    return list(_SEEN[key])


@dataclass
class Family:
    id: int
    father: int | None
    mother: int | None
    children: list[int]
    colour: str = GREY                  # the full siblings': their connector and their frames
    lane_y: float = 0.0                 # the children's line, between the rows
    couple_y: float = 0.0
    drops: dict = field(default_factory=dict)   # parent -> where the family's line leaves them
    # Packed families only: the children who stand in another cluster (beside a partner) and the
    # parent who stands in another cluster than the one the children hang under; their lines go round.
    away: list = field(default_factory=list)
    far: list = field(default_factory=list)
    way: list = field(default_factory=list)     # Packed families: the way kept for the line from the parents
    # Children all on a later page (_page_members): who they are and that page's number; the family's lines
    # end at a "continued on page N" mark, lane_y where its line down ends.
    onward: list = field(default_factory=list)
    onward_page: int = 0
    stem_x: float = 0.0                 # where its line goes down from the couple's line to those words
    word_dx: float = 0.0                # how far its words' centre stands from the end of its line (0: centred under it;
                                        # otherwise the words run out to one side, when crowded labels would meet)


# How the family lines may be coloured (vf1_line_colours): the Lines tab's "Line colours" and "Order colours by".
LINE_MODES = {"default": "Default (the families' colours)", "auto": "Auto", "rainbow": "Rainbow", "gradient": "Gradient",
              "range": "Range"}
LINE_ORDERS = {"x": "Left to right", "x_rev": "Right to left", "y": "Top to bottom", "y_rev": "Bottom to top",
               "row": "Per row", "generation": "Per generation"}
RANGE_DEFAULT = ("#e63946", "#2a9d8f", "#3a86ff")        # the Range's base colours until the player picks
RANGE_MAX = 12


@dataclass
class Edits:
    """The player's marks and edits for one family's tree.  Blank means the patcher's own."""
    title: str = ""
    subtitle: str = ""
    centre_heads: bool = True           # the head and its lines in the middle of the frame (text_valign "middle")
    # The owner, 2026-10-09: "justify text (left right center + top middle bottom)": the portrait's words
    # across (TEXT_ALIGNS) and the face and words together up and down (TEXT_VALIGNS).
    text_align: str = "centre"
    # The owner, 2026-10-09: "a toggle for the text to fit within the portrait shape's space (in things
    # like crosses and x's it runs off)": the words only as wide as the shape is where each line is.
    text_inside: bool = False
    # Faces and words at one size whatever the portrait's shape and size (the owner, 2026-10-09: the
    # males' turtle shells drew their faces and words a quarter smaller than the females' leaves).
    fixed_face_size: bool = False
    # "Same face and text size for:" (the owner, 2026-10-10: "equalizing villager icons and text = should
    # have the exact same font size and icon dimensions regardless of other settings"): EQUAL_SCOPES ->
    # {"face": percent, "text": percent}.  Every portrait in the scope gets one face size and one font
    # size -- the largest that fits all of them (equal_scale, _equal_words) -- until the player changes a
    # face or text size again.
    equal_sizes: dict = field(default_factory=dict)
    # Whether a turned portrait's words turn with it (the owner, 2026-10-09); off, they stay upright.
    turn_words: bool = False
    # Whether a flipped portrait's words are mirrored with it (the owner, 2026-10-09: "if people want to
    # mirror their text or anything be my guest"); off, they read as usual.
    flip_words: bool = False
    # Where a portrait's words are fitted (the owner, 2026-10-09: "for the more abstract shapes, the
    # auto-generated text boxes should just be a rectangle/oval ... Should be player-selected"): TEXT_ROOMS.
    text_room: str = "auto"
    # The special borders' colours (the owner, 2026-10-09): SPECIAL_COLOUR_MODES; the colours picked for
    # each part ("rope", "vine", "leaf", "flower"); the 7 colours of a palette, of which the first
    # special_count (2-7) are used, by turns or as a gradient.
    special_mode: str = "natural"
    special_pick: dict = field(default_factory=dict)
    special_palette: list = field(default_factory=lambda: list(RAINBOW[:7]))
    special_count: int = 3
    hibiscus: str = "red"               # natural flowers' colour (HIBISCUS_CHOICES)
    special_opacity: float = 100.0      # the special borders' opacity, percent (the owner, 2026-10-09)
    rainbow_strength: str = "medium"    # RAINBOW_STRENGTHS
    schemes: dict = field(default_factory=dict)   # SCHEME_PARTS -> COLOUR_SCHEMES ("own" when absent)
    # The light lines inside a shape (details(): a scallop's ribs, a snail's whorls, a star's points),
    # the owner, 2026-10-09: "with the ability to edit the detailing's color, opacity, line weight".
    detail_lines: bool = True
    detail_colour: str = ""             # "" the portrait's own colour
    detail_opacity: float = 45.0        # percent
    detail_width: float = 1.0
    # The box behind the name and age words of each portrait (the owner, 2026-10-23): its colour and how
    # solid it is (0 % -- the default -- draws none), and whether it is drawn over the shapes (the leaf,
    # tail and flower portraits and their borders) rather than just under its own words.
    text_box_colour: str = "#ffffff"
    text_box_opacity: float = 0.0       # percent
    text_box_over: bool = False
    # Its border, like a portrait's (the owner: "border options for the text boxes, like the portrait
    # shapes"): any BORDERS choice -- the special rope and vines too -- its colour ("" Automatic: the
    # portrait's border colour) and its weight (0 -- the default -- draws none).  Round the box's own rounded
    # corners; drawn even with no box behind the words.
    text_box_border: str = "thin"
    text_box_border_colour: str = ""
    text_box_border_width: float = 0.0
    text_valign: str = "middle"
    row_align: str = "arranged"        # each row across the tree (ROW_ALIGNS)
    row_valign: str = "middle"         # the portraits in a row lined up by (ROW_VALIGNS)
    row_limit: int = 0                 # the most portraits in a row before it wraps (0: no limit)
    keep_families: bool = True         # a wrap falls between families, not through one
    others_columns: int = 1            # the Other Members across (1: each generation's in a row, as before)
    others_side: str = "right"         # OTHERS_SIDES: where the Other Members go
    packing: int = PACKING             # the Packed layouts: how tightly packed, 0 (tidy) to 100 (densest)
    # Family lines straight and behind the portraits (the owner, 2026-10-09: "a toggle for lines run
    # behind portraits"); None until the player says: behind only in a Packed layout packed 98 or more.
    lines_behind: bool | None = None
    # A thin dark or white outline under family lines whose own colour would blend into the background
    # (the owner, 2026-10-10: "make it an optional toggle default off").
    outline_lines: bool = False
    # How the family lines are coloured (the owner, 2026-10-10): LINE_MODES, the order the colours run
    # across the tree (LINE_ORDERS, backwards when line_reverse), the Gradient's two ends and the Range's
    # base colours.  The colours themselves are in family_lines; these are what made them.
    line_mode: str = "default"
    line_order: str = "x"
    line_reverse: bool = False
    gradient_start: str = "#ff7a18"
    gradient_end: str = "#7b2ff7"
    range_colours: list[str] = field(default_factory=lambda: list(RANGE_DEFAULT))
    picture_size: float = 100.0        # every portrait's face, percent (PICTURE_SCALE_MIN..MAX)
    text_size: float = 100.0           # every portrait's words, percent (TEXT_SCALE_MIN..MAX)
    text_wrap: int = 17                 # characters across a portrait before a line wraps (the owner: adjustable)
    portrait_gap: float = 22.0          # pixels between two portraits side by side (the owner: batch-editable)
    row_gap: float = 30.0               # pixels under a generation's row before its children's lines (LANE_TOP)
    # The descriptors each portrait gets by itself where they apply (the owner, 2026-10-22: "villagers get
    # auto-denoted with special descriptors if applicable (tribal chief, founder, runner etc)"): on unless the
    # player unticks them.  descriptors_v2 marks a value saved since then: every earlier build wrote these
    # False whether or not the player ever unticked them, so an earlier file's False reads as the new default.
    show_runner: bool = True            # "Runner" for a villager who likes running (the owner, 2026-10-10)
    show_founder: bool = True           # "Founder" for each founder of the village (the owner, 2026-10-09)
    show_arrived: bool = True           # "Event names": the event that brought them in (arrival_words)
    show_left_home: bool = True         # "Left home" for a living family member who left home (Virtual Families)
    show_heir: bool = True              # "Heir" for whoever inherited the house (Virtual Families)
    show_divorced: bool = True          # "Divorced": a spouse lost to Divorce Spouse
    show_deceased: bool = True          # "Deceased"
    show_career: bool = True            # "Career: Pastry Designer, Novice" (the game's own words)
    show_adopted: bool = True           # "Adopted": joined without being born to the family
    show_remarried: bool = True         # "Remarried": the head of the family married again
    show_spouse_order: bool = True      # "Husband 1", "Wife 2": a spouse's place in the order of marriages
    fit_width: int = 0                  # 0, or shrink every portrait so the widest row fits this many pixels
    # The canvas (the owner, 2026-10-09): 0 x 0 is Automatic, the page as large as the tree; else every
    # page is this many pixels, the tree shrunk evenly to fit it or centred on it at its own size.
    canvas_w: int = 0
    canvas_h: int = 0
    page_generations: int = 6           # the most generations on one page (the owner: 6, up to 10)
    diagonal_lines: bool = False        # a dragged line piece may move any way (else only across itself)
    show_units: bool = False            # "<age> game units" in the portraits (Virtual Families shows years)
    show_years: bool = True             # "<years> years old" in the portraits
    show_twins: bool = True             # "<name>'s twin" / "<name> and <name>'s triplet" after the age
    # Villagers who share a name numbered: "Soda I", "Soda II"... -- on by default (the owner, 2026-10-20:
    # numbering "must be ON BY DEFAULT").  number_names_v2 marks a value saved since then: every earlier
    # build wrote number_names (False) whether or not the player ever changed it, so an earlier file's
    # False cannot be told from "never set" and reads as the new default; a value saved now is kept.
    number_names: bool = True
    number_order: str = "appearance"    # vf1_genealogy.NUMBER_ORDERS: who is "I" (the owner's default)
    sort: str = "appearance"            # vf1_genealogy.SORTS
    positioning: str = "dynamic"        # POSITIONING
    numbering: str = "roman"            # NUMBERINGS: the generations' numbers
    background: str = "#ffffff"         # "#rrggbb" or TRANSPARENT; white until the player says (the owner, 2026-10-08: "to prevent stupid mistakes"); blank the patcher's own
    background2: str = ""               # a gradient's lower colour ("" none)
    rainbow: str = ""                   # a RAINBOWS key instead of that gradient ("" none)
    background_image: str = ""          # a picture file, or "game:<name>" in the game's Images
    background_fit: str = "stretch"     # FITS (the owner's default: "stretch to the page")
    background_opacity: int = 100       # 0-100: how strongly the picture shows over the colour (the owner, 2026-10-08: not see-through unless asked)
    ink: str = ""                       # the text's colour
    font: str = ""                      # the font for every word on the tree ("" the patcher's own)
    styles: dict[str, dict] = field(default_factory=dict)             # ROLES key -> its own style
    family_colours: dict[str, str] = field(default_factory=dict)      # family key -> its pairing's colour
    person_colours: dict[str, str] = field(default_factory=dict)      # entry key -> a parentless villager's
    # Where the player dragged the words around the tree (the owner: "allow the option to move
    # anything by dragging it"): MOVABLE name -> [right, down].  A villager's own is in entries.
    moved: dict[str, list] = field(default_factory=dict)
    # The player's order of a generation (the owner: "allow customizability/reordering of
    # villagers within generations"): "3" -> entry keys, left to right.  A villager's own
    # generation, when the player puts them in another, is in entries.
    orders: dict[str, list] = field(default_factory=dict)
    portrait_fill: str = "#ffffff"      # inside every portrait
    shapes: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SHAPES))     # GROUPS -> shape
    borders: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BORDERS))   # GROUPS -> border
    plate_colour: str = ""              # the boxes behind words on a picture ("" the background's colour)
    opacity: dict[str, int] = field(default_factory=dict)              # OPACITY -> percent (unset: its default)
    sizes: dict[str, list] = field(default_factory=dict)               # GROUPS -> [width, height] of the frame
    line_width: float = LINE_WIDTH      # every family line's weight
    line_dash: str = ""                 # LINE_TYPES: every family line's type
    family_lines: dict[str, dict] = field(default_factory=dict)        # family key -> {"width", "dash", "colour"}
    mark_style: str = "border"          # MARK_STYLES
    mark_glow: float = 14.0             # how far a glow reaches
    mark_opacity: int = 100             # percent
    label_line_width: float = 2.0       # the line beside each generation's label
    label_line_reach: float = 0.0       # how far past the generation's portraits it reaches, each end
    # What the player deleted from the tree (the owner: "omit anything I like"): "word:<MOVABLE
    # name>" and "line:<family key>|<piece>".  A villager deleted is "hidden" in their entry.
    pages: list[int] = field(default_factory=list)                     # the generations that start a new page
    hidden: list[str] = field(default_factory=list)
    # The player's answers to "Keep <current name> or <old name>?" for a renamed-looking villager
    # (vf1_genealogy.RenameQuestion.key -> "current" or "old"); asked once, then remembered.
    renames: dict[str, str] = field(default_factory=dict)
    # Pieces of line the player dragged (the owner: "move individual lines and still keep the
    # connections to portraits"): "<family key>|<piece>" -> how far it was dragged.
    line_moves: dict[str, list | float] = field(default_factory=dict)   # piece -> [right, down]
    # Dragged pieces put down with Alt held: exactly where the player let go, never nudged off a line
    # beside them (like the smart guides, Alt places freely).  Counted only while the piece is in line_moves.
    free_lines: list[str] = field(default_factory=list)
    generations: dict[str, list[str]] = field(default_factory=dict)   # "2" -> the label's lines
    words: dict[str, str] = field(default_factory=dict)                # WORDS -> the player's own words
    marks: dict[str, str] = field(default_factory=dict)               # label -> "#rrggbb", in order
    # The automatic marks (apply_auto_marks): a status's mark the player renamed (status -> the mark's name
    # now), and the statuses whose mark the player removed from everyone (never given again).
    mark_names: dict[str, str] = field(default_factory=dict)
    marks_off: list[str] = field(default_factory=list)
    # entry key -> {"lines", "runs" (those lines formatted word by word: clean_runs), "marks" (every mark
    # they have, in order; "mark" the first, as older builds read it), "unmarked" (automatic marks the
    # player took off them), ...}
    entries: dict[str, dict] = field(default_factory=dict)
    # Living namesakes' edits (settle_namesakes; Codex, PR #653): "name|head|body" -> the group's markers,
    # oldest first, when their edits were last kept; and "name|head|body" -> the marker of the one villager
    # with no namesake whose edits the plain key holds.
    namesakes: dict[str, list] = field(default_factory=dict)
    key_owners: dict[str, str] = field(default_factory=dict)
    # Stickers (the owner: "any image file on the computer where people can drag and place them
    # like a scrapbook", "resize, rotate, transform"): pictures on top of the tree, bottom one first.
    stickers: list[dict] = field(default_factory=list)
    # What belongs to one page only (the owner, preview: "everything placed on a page belongs to that
    # page only"), by the page's first generation ("1", "6"...): {"entries": {entry key -> {field -> value,
    # or None: not set on this page}}, "moved": {name -> [right, down]}, "hidden": [the page's whole list of
    # deleted things], "family_colours": {...}, "person_colours": {...} (None: the patcher's own)}.  Laid over
    # the tree-wide ones above for that page alone (page_view).  A sticker carries its own "page".
    page_edits: dict[str, dict] = field(default_factory=dict)
    # One group's portraits set apart from the rest (the owner, 2026-10-09: "as many options as
    # realistically and logically possible should be by group with options to equalize"): GROUPS ->
    # {GROUP_FIELDS name -> value}, each over the tree's own setting for that group only (opt()).
    group_opts: dict[str, dict] = field(default_factory=dict)
    # Saved since the Monstera leaf and the feather are drawn turned (SHAPE_BAKES); False: their portraits'
    # turns, flips and sizes are still as they were before, and settle_shapes moves them on.
    monstera_v2: bool = True
    feather_v2: bool = True
    # Saved since settle_shapes leaves a portrait with no turn or flip of its own drawn as the shape now is
    # (2026-10-10); False: portraits the earlier moving-on turned back to the old look are put right (settle_shapes).
    bakes_v3: bool = True

    @staticmethod
    def path(folder: Path, game: int, slot: int) -> Path:
        # The save's own "Virtual Families 1 Patcher\Save N\Data\Family Tree\Virtual Families 1 Family Tree
        # Edits - Save N.json" (the patcher's own folder for the save).  The caller makes the folder.
        return data_folder(folder, slot) / f"Virtual Families 1 Family Tree Edits - Save {slot}.json"

    @classmethod
    def load(cls, path: Path) -> "Edits":
        """The saved edits; none when there is no file.  A file that is not this format raises
        ValueError (it is never overwritten unasked)."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{Path(path).name} could not be read: {exc}") from exc
        if not isinstance(data, dict) or data.get("format") != 1:
            raise ValueError(f"{Path(path).name} is not a Family Tree Maker edits file.")
        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: dict) -> "Edits":
        """The edits from their saved form (every value checked); ValueError when the form is damaged."""
        try:
            return cls._from_data(data)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"the saved edits are damaged ({exc})") from exc

    @classmethod
    def _from_data(cls, data: dict) -> "Edits":
        out = cls(str(data.get("title", "")), str(data.get("subtitle", "")),
                  data.get("centre_heads", True) is not False)
        out.text_inside = data.get("text_inside") is True
        out.monstera_v2 = data.get("monstera_v2") is True       # saved before: moved on (settle_shapes)
        out.feather_v2 = data.get("feather_v2") is True
        out.bakes_v3 = data.get("bakes_v3") is True
        out.fixed_face_size = data.get("fixed_face_size") is True
        out.turn_words = data.get("turn_words") is True
        out.flip_words = data.get("flip_words") is True
        mode = data.get("special_mode")
        out.special_mode = mode if mode in SPECIAL_COLOUR_MODES else "natural"
        pick = data.get("special_pick")
        out.special_pick = {k: v for k, v in pick.items() if k in SPECIAL_PARTS and _colour_ok(v)} \
            if isinstance(pick, dict) else {}
        palette = data.get("special_palette")
        if isinstance(palette, list) and len(palette) == 7 and all(_colour_ok(c) for c in palette):
            out.special_palette = list(palette)
        out.special_count = int(_number(data.get("special_count"), 2, 7, 3))
        chosen = "alternate" if data.get("hibiscus") == "random" else data.get("hibiscus")   # "random", before
        out.hibiscus = chosen if chosen in HIBISCUS_CHOICES else "red"
        out.special_opacity = float(_number(data.get("special_opacity"), 0, 100, 100.0))
        strength = data.get("rainbow_strength")
        out.rainbow_strength = strength if strength in RAINBOW_STRENGTHS else "medium"
        schemes = data.get("schemes")
        out.schemes = ({k: v for k, v in schemes.items() if k in SCHEME_PARTS and v in COLOUR_SCHEMES and v != "own"}
                       if isinstance(schemes, dict) else {})
        room = data.get("text_room")
        out.text_room = room if room in TEXT_ROOMS else "auto"
        out.detail_lines = data.get("detail_lines", True) is not False
        colour = data.get("detail_colour")
        out.detail_colour = colour if isinstance(colour, str) and (colour == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", colour)) else ""
        out.detail_opacity = float(_number(data.get("detail_opacity"), 0, 100, 45.0))
        out.detail_width = float(_number(data.get("detail_width"), *LINE_WIDTHS, 1.0))
        box_colour = data.get("text_box_colour")
        out.text_box_colour = box_colour if isinstance(box_colour, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", box_colour) else "#ffffff"
        out.text_box_opacity = float(_number(data.get("text_box_opacity"), 0, 100, 0.0))
        out.text_box_over = data.get("text_box_over") is True
        out.text_box_border = data.get("text_box_border") if data.get("text_box_border") in BORDERS else "thin"
        border_colour = data.get("text_box_border_colour")
        out.text_box_border_colour = border_colour if _border_colour(border_colour) else ""
        out.text_box_border_width = float(_number(data.get("text_box_border_width"), *TEXT_BOX_BORDER_WIDTHS, 0.0))
        align = data.get("text_align")
        out.text_align = align if align in TEXT_ALIGNS else "centre"
        valign = data.get("text_valign")
        out.text_valign = valign if valign in TEXT_VALIGNS else ("middle" if out.centre_heads else "top")
        out.centre_heads = out.text_valign == "middle"     # what an older build reads
        out.diagonal_lines = data.get("diagonal_lines") is True
        out.text_wrap = int(_number(data.get("text_wrap"), WRAP_MIN, WRAP_MAX, WRAP))
        out.row_align = data.get("row_align") if data.get("row_align") in ROW_ALIGNS else "arranged"
        out.row_valign = data.get("row_valign") if data.get("row_valign") in ROW_VALIGNS else "middle"
        out.row_limit = int(_number(data.get("row_limit"), 0, ROW_LIMIT_MAX, 0))
        out.keep_families = data.get("keep_families") is not False
        out.others_columns = int(_number(data.get("others_columns"), 1, OTHERS_COLUMNS_MAX, 1))
        out.others_side = data.get("others_side") if data.get("others_side") in OTHERS_SIDES else "right"
        out.packing = int(_number(data.get("packing"), 0, 100, PACKING))
        out.lines_behind = data.get("lines_behind") if isinstance(data.get("lines_behind"), bool) else None
        out.outline_lines = data.get("outline_lines") is True
        out.line_mode = data.get("line_mode") if data.get("line_mode") in LINE_MODES else "default"
        out.line_order = data.get("line_order") if data.get("line_order") in LINE_ORDERS else "x"
        out.line_reverse = data.get("line_reverse") is True
        out.gradient_start = data.get("gradient_start") if _colour_ok(data.get("gradient_start")) else "#ff7a18"
        out.gradient_end = data.get("gradient_end") if _colour_ok(data.get("gradient_end")) else "#7b2ff7"
        picked = [c for c in data.get("range_colours", []) if _colour_ok(c)] if isinstance(data.get("range_colours"), list) else []
        out.range_colours = picked[:RANGE_MAX] or list(RANGE_DEFAULT)
        out.picture_size = _number(data.get("picture_size"), PICTURE_SCALE_MIN, PICTURE_SCALE_MAX, 100.0)
        out.text_size = _number(data.get("text_size"), TEXT_SCALE_MIN, TEXT_SCALE_MAX, 100.0)
        out.portrait_gap = float(_number(data.get("portrait_gap"), GAP_MIN, GAP_MAX, GAP_X))
        out.row_gap = float(_number(data.get("row_gap"), ROW_GAP_MIN, ROW_GAP_MAX, LANE_TOP))
        kept = data.get("descriptors_v2") is True       # else an earlier build's False: the new default, on
        out.show_founder = data.get("show_founder") is not False if kept else True
        out.show_runner = data.get("show_runner") is not False if kept else True
        out.show_arrived = data.get("show_arrived") is not False
        out.show_left_home = data.get("show_left_home") is not False
        out.show_heir = data.get("show_heir") is not False
        for key in ("show_divorced", "show_deceased", "show_career", "show_adopted", "show_remarried", "show_spouse_order"):
            setattr(out, key, data.get(key) is not False)
        out.page_generations = int(_number(data.get("page_generations"), PAGE_GENS_MIN, PAGE_GENS_MAX, PAGE_GENS))
        fit = data.get("fit_width")
        out.fit_width = int(_number(fit, FIT_MIN, FIT_MAX, 0)) if isinstance(fit, (int, float)) and fit else 0
        cw, ch = data.get("canvas_w"), data.get("canvas_h")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (cw, ch)):
            out.canvas_w = int(_number(cw, CANVAS_MIN, CANVAS_MAX, 0))
            out.canvas_h = int(_number(ch, CANVAS_MIN, CANVAS_MAX, 0))
        out.show_units = data.get("show_units", True) is not False
        out.show_years = data.get("show_years", True) is not False
        out.show_twins = data.get("show_twins") is not False if kept else True
        out.number_names = data.get("number_names") is not False if data.get("number_names_v2") is True else True
        if data.get("number_order") in gen.NUMBER_ORDERS:
            out.number_order = data["number_order"]
        if data.get("sort") in gen.SORTS:
            out.sort = data["sort"]
        if data.get("positioning") in POSITIONING:
            out.positioning = data["positioning"]
        if data.get("numbering") in NUMBERINGS:
            out.numbering = data["numbering"]
        for attr in ("background", "background2", "ink"):
            if is_colour(data.get(attr)):
                setattr(out, attr, data[attr])
        if data.get("rainbow") in RAINBOWS:
            out.rainbow = data["rainbow"]
        out.background_image = str(data.get("background_image", ""))
        if data.get("background_fit") in FITS:
            out.background_fit = data["background_fit"]
        if isinstance(data.get("background_opacity"), int):
            out.background_opacity = max(0, min(100, data["background_opacity"]))
        for key, colour in dict(data.get("family_colours", {})).items():
            if is_colour(colour):
                out.family_colours[str(key)] = colour
        for key, colour in dict(data.get("person_colours", {})).items():
            if is_colour(colour):
                out.person_colours[str(key)] = colour
        for key, lines in dict(data.get("generations", {})).items():
            out.generations[str(key)] = [str(line) for line in lines]
        for key, text in dict(data.get("words", {})).items():
            if (key in WORDS or str(key).startswith("onward:")) and isinstance(text, str):
                out.words[key] = text
        for label, colour in dict(data.get("marks", {})).items():
            if is_colour(colour):
                out.marks[str(label)] = str(colour)
        for status, label in dict(data.get("mark_names", {})).items():
            if isinstance(label, str) and label.strip():
                out.mark_names[str(status)] = label.strip()
        out.marks_off = _clean_labels(data.get("marks_off"))
        for key, entry in dict(data.get("entries", {})).items():
            if not isinstance(entry, dict):     # damaged: that villager's edits are passed over
                continue
            item = {}
            if isinstance(entry.get("lines"), list):
                item["lines"] = [str(line) for line in entry["lines"]]
                runs = runs_data(clean_runs(entry.get("runs"), item["lines"]))
                if runs:
                    item["runs"] = runs
            if "marks" in entry:                # several marks (since 2026-10-22), the first also as "mark"
                labels = _clean_labels(entry.get("marks"))
                if labels:
                    item["marks"], item["mark"] = labels, labels[0]
            elif entry.get("mark"):             # one mark, as every earlier build kept it
                item["mark"] = str(entry["mark"])
            unmarked = _clean_labels(entry.get("unmarked"))
            if unmarked:
                item["unmarked"] = unmarked
            if entry.get("hidden") is True:
                item["hidden"] = True
            if entry.get("shape") in PORTRAIT_SHAPES:
                item["shape"] = entry["shape"]
            if entry.get("border") in BORDERS:
                item["border"] = entry["border"]
            if isinstance(entry.get("generation"), int) and 1 <= entry["generation"] <= 99:
                item["generation"] = entry["generation"]
            for axis in ("dx", "dy"):
                shift = _number(entry.get(axis), -STICKER_MAX, STICKER_MAX, 0.0)
                if shift:
                    item[axis] = shift
            for axis in ("w", "h"):
                if axis in entry:
                    item[axis] = _number(entry[axis], FRAME_MIN, FRAME_MAX, FRAME_MIN)
            angle = _number(entry.get("angle"), 0.0, 360.0, 0.0) % 360
            if angle:
                item["angle"] = angle
            if is_colour(entry.get("fill")):            # this portrait's own inside colour (the owner, 2026-10-09)
                item["fill"] = entry["fill"]
            if is_colour(entry.get("detail")):          # and its own detail lines' colour
                item["detail"] = entry["detail"]
            for flip in ("flip_h", "flip_v"):            # the portrait's shape mirrored (the owner, 2026-10-09)
                if entry.get(flip) is True:
                    item[flip] = True
            text_scale = _number(entry.get("text_scale"), TEXT_SCALE_MIN, TEXT_SCALE_MAX, 100.0)
            if text_scale != 100.0:
                item["text_scale"] = text_scale     # this villager's words, apart from the frame (the owner)
            picture_scale = _number(entry.get("picture_scale"), PICTURE_SCALE_MIN, PICTURE_SCALE_MAX, 100.0)
            if picture_scale != 100.0:
                item["picture_scale"] = picture_scale   # and their face (the owner, 2026-10-09)
            look = entry.get("look")
            if isinstance(look, list) and len(look) == 2 and all(isinstance(v, int) for v in look):
                item["look"] = look             # the look the player chose to show
            if item:
                out.entries[str(key)] = item
        for piece, shift in dict(data.get("line_moves", {})).items():
            if isinstance(shift, list) and len(shift) == 2:
                shift = [_number(v, -STICKER_MAX, STICKER_MAX, 0.0) for v in shift]
            else:                               # saved before lines moved both ways: across itself
                shift = _number(shift, -STICKER_MAX, STICKER_MAX, 0.0)
            if shift:
                out.line_moves[str(piece)] = shift
        out.free_lines = [str(p) for p in data.get("free_lines", []) if str(p) in out.line_moves] \
            if isinstance(data.get("free_lines"), list) else []
        for group, size in dict(data.get("sizes", {})).items():
            if group in GROUPS and isinstance(size, list) and len(size) == 2:
                out.sizes[group] = [_number(v, FRAME_MIN, FRAME_MAX, NODE_H) for v in size]
        out.line_width = _number(data.get("line_width"), *LINE_WIDTHS, LINE_WIDTH)
        if data.get("line_dash") in LINE_TYPES:
            out.line_dash = data["line_dash"]
        for key, style in dict(data.get("family_lines", {})).items():
            item = {}
            if isinstance(style, dict) and "width" in style:
                item["width"] = _number(style["width"], *LINE_WIDTHS, LINE_WIDTH)
            if isinstance(style, dict) and style.get("dash") in LINE_TYPES:
                item["dash"] = style["dash"]
            # The family's lines in a colour of their own, the children's portraits keeping the family's
            # (the owner, 2026-10-09: the Auto-colour family lines button; "lines only").
            if isinstance(style, dict) and _colour_ok(style.get("colour")):
                item["colour"] = style["colour"].lower()
            if item:
                out.family_lines[str(key)] = item
        if data.get("mark_style") in MARK_STYLES:
            out.mark_style = data["mark_style"]
        out.mark_glow = _number(data.get("mark_glow"), 2.0, 60.0, 14.0)
        out.mark_opacity = int(_number(data.get("mark_opacity"), 0, 100, 100))
        out.label_line_width = _number(data.get("label_line_width"), *LINE_WIDTHS, 2.0)
        out.label_line_reach = _number(data.get("label_line_reach"), 0.0, 1000.0, 0.0)
        for part, value in dict(data.get("opacity", {})).items():
            if part in OPACITY:
                out.opacity[part] = int(_number(value, 0, 100, OPACITY[part][1]))
        for attr in ("portrait_fill", "plate_colour"):
            if is_colour(data.get(attr)):
                setattr(out, attr, data[attr])
        for attr, choices in (("shapes", PORTRAIT_SHAPES), ("borders", BORDERS)):
            for group, value in dict(data.get(attr, {})).items():
                if group in GROUPS and value in choices:
                    getattr(out, attr)[group] = value
        if isinstance(data.get("pages"), list):
            out.pages = sorted({int(g) for g in data["pages"] if isinstance(g, int) and 2 <= g <= 99})
        if isinstance(data.get("hidden"), list):
            out.hidden = [str(h) for h in data["hidden"]]
        if isinstance(data.get("renames"), dict):
            out.renames = {str(k): v for k, v in data["renames"].items() if v in ("current", "old")}
        for g, keys in dict(data.get("orders", {})).items():
            if isinstance(keys, list):
                out.orders[str(g)] = [str(k) for k in keys]
        for name, shift in dict(data.get("moved", {})).items():
            if isinstance(shift, list) and len(shift) == 2:
                out.moved[str(name)] = [_number(shift[0], -STICKER_MAX, STICKER_MAX, 0.0),
                                        _number(shift[1], -STICKER_MAX, STICKER_MAX, 0.0)]
        if isinstance(data.get("font"), str):
            out.font = data["font"]
        for role, style in dict(data.get("styles", {})).items():
            if role in ROLES and isinstance(style, dict):
                out.styles[role] = clean_style(style)
        for raw in data.get("stickers", []) if isinstance(data.get("stickers"), list) else []:
            sticker = clean_sticker(raw)
            if sticker is not None:
                out.stickers.append(sticker)
        out.page_edits = clean_page_edits(data.get("page_edits"))
        out.equal_sizes = clean_equal_sizes(data.get("equal_sizes"))
        out.group_opts = clean_group_opts(data.get("group_opts"))
        namesakes = data.get("namesakes")
        out.namesakes = {str(k): [str(m) for m in v] for k, v in namesakes.items() if isinstance(v, list)} \
            if isinstance(namesakes, dict) else {}
        owners = data.get("key_owners")
        out.key_owners = {str(k): v for k, v in owners.items() if isinstance(v, str)} \
            if isinstance(owners, dict) else {}
        return out

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.to_data(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(path)

    def to_data(self) -> dict:
        return {"format": 1, "page_edits": clean_page_edits(self.page_edits), "title": self.title, "subtitle": self.subtitle,
                "centre_heads": self.text_valign == "middle", "text_align": self.text_align, "text_inside": self.text_inside, "fixed_face_size": self.fixed_face_size, "turn_words": self.turn_words, "flip_words": self.flip_words, "text_room": self.text_room, "special_mode": self.special_mode, "special_pick": self.special_pick, "special_palette": self.special_palette, "special_count": self.special_count, "hibiscus": self.hibiscus, "special_opacity": self.special_opacity, "rainbow_strength": self.rainbow_strength, "schemes": self.schemes, "detail_lines": self.detail_lines, "detail_colour": self.detail_colour, "detail_opacity": self.detail_opacity, "detail_width": self.detail_width, "text_box_colour": self.text_box_colour, "text_box_opacity": self.text_box_opacity, "text_box_over": self.text_box_over, "text_box_border": self.text_box_border, "text_box_border_colour": self.text_box_border_colour, "text_box_border_width": self.text_box_border_width, "text_valign": self.text_valign, "text_wrap": self.text_wrap, "row_align": self.row_align, "row_valign": self.row_valign, "row_limit": self.row_limit, "keep_families": self.keep_families, "others_columns": self.others_columns, "others_side": self.others_side, "packing": self.packing, "lines_behind": self.lines_behind, "outline_lines": self.outline_lines, "line_mode": self.line_mode, "line_order": self.line_order, "line_reverse": self.line_reverse, "gradient_start": self.gradient_start, "gradient_end": self.gradient_end, "range_colours": self.range_colours, "picture_size": self.picture_size, "text_size": self.text_size, "portrait_gap": self.portrait_gap, "row_gap": self.row_gap, "show_founder": self.show_founder, "fit_width": self.fit_width, "canvas_w": self.canvas_w, "canvas_h": self.canvas_h,"page_generations": self.page_generations, "diagonal_lines": self.diagonal_lines,
                "show_units": self.show_units, "show_years": self.show_years, "show_twins": self.show_twins, "show_runner": self.show_runner, "number_names": self.number_names,
                "number_names_v2": True, "descriptors_v2": True, "show_arrived": self.show_arrived, "show_left_home": self.show_left_home,
                "show_heir": self.show_heir, "show_divorced": self.show_divorced, "show_deceased": self.show_deceased,
                "show_career": self.show_career, "show_adopted": self.show_adopted, "show_remarried": self.show_remarried,
                "show_spouse_order": self.show_spouse_order,
                "number_order": self.number_order,
                "sort": self.sort, "positioning": self.positioning,
                "numbering": self.numbering,
                "background": self.background, "background2": self.background2, "rainbow": self.rainbow,
                "background_image": self.background_image, "background_fit": self.background_fit,
                "background_opacity": self.background_opacity,
                "ink": self.ink, "family_colours": self.family_colours,
                "person_colours": self.person_colours, "moved": self.moved, "orders": self.orders,
                "portrait_fill": self.portrait_fill, "plate_colour": self.plate_colour, "hidden": self.hidden, "renames": self.renames,
                "pages": self.pages,
                "shapes": self.shapes, "borders": self.borders, "opacity": self.opacity,
                "sizes": self.sizes, "line_width": self.line_width, "line_dash": self.line_dash,
                "family_lines": self.family_lines, "mark_style": self.mark_style, "mark_glow": self.mark_glow,
                "mark_opacity": self.mark_opacity, "label_line_width": self.label_line_width,
                "label_line_reach": self.label_line_reach,
                "line_moves": self.line_moves, "free_lines": self.free_lines,
                "generations": self.generations, "words": self.words, "marks": self.marks,
                "mark_names": self.mark_names, "marks_off": self.marks_off,
                "entries": self.entries,
                "font": self.font, "styles": self.styles, "stickers": self.stickers,
                "group_opts": self.group_opts, "equal_sizes": self.equal_sizes, "monstera_v2": self.monstera_v2,
                "feather_v2": self.feather_v2, "bakes_v3": self.bakes_v3,
                "namesakes": self.namesakes, "key_owners": self.key_owners}


# The settings a group's portraits may have of their own (Edits.group_opts): only what is drawn inside
# one portrait.  Each is checked as the tree's own is (_group_value).
GROUP_FIELDS = ("text_align", "text_valign", "centre_heads", "text_room", "flip_words", "turn_words",
                "text_inside", "fixed_face_size", "picture_size", "text_size", "text_wrap", "show_units", "show_years",
                "show_twins", "show_founder", "show_runner", "show_arrived", "show_heir", "show_left_home",
                "show_divorced", "show_deceased", "show_career", "show_adopted", "show_remarried", "show_spouse_order",
                "detail_lines",
                "detail_colour", "detail_opacity", "detail_width", "portrait_fill", "text_box_colour", "text_box_opacity",
                "text_box_over", "text_box_border", "text_box_border_colour", "text_box_border_width")
TEXT_BOX_BORDER_WIDTHS = (0.0, 20.0)    # a text box border's weight: 0 draws none


def _border_colour(value) -> bool:
    """A good text box border colour: "" (Automatic), #rrggbb, or TRANSPARENT (Codex, #606: a border made
    see-through came back after the tree was saved and opened again)."""
    return isinstance(value, str) and (value in ("", TRANSPARENT)
                                       or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None)


def _group_value(name: str, value) -> tuple[bool, object]:
    """(whether `value` is a good value of the setting `name`, the value as kept): numbers held within
    the tree's own limits, as the tree's own are; anything else not of the setting's kind is bad."""
    choices = {"text_align": TEXT_ALIGNS, "text_valign": TEXT_VALIGNS, "text_room": TEXT_ROOMS,
               "text_box_border": BORDERS}
    numbers = {"picture_size": (PICTURE_SCALE_MIN, PICTURE_SCALE_MAX), "text_size": (TEXT_SCALE_MIN, TEXT_SCALE_MAX),
               "text_wrap": (WRAP_MIN, WRAP_MAX), "detail_opacity": (0, 100), "text_box_opacity": (0, 100), "detail_width": LINE_WIDTHS,
               "text_box_border_width": TEXT_BOX_BORDER_WIDTHS}
    if name in choices:
        return value in choices[name], value
    if name in numbers:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return False, value
        kept = _number(value, *numbers[name], 0.0)
        return True, int(kept) if name == "text_wrap" else float(kept)
    if name == "text_box_border_colour":
        return _border_colour(value), value
    if name == "detail_colour":
        return isinstance(value, str) and (value == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None), value
    if name == "portrait_fill":
        return is_colour(value), value
    if name == "text_box_colour":
        return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None, value
    if name in GROUP_FIELDS:                    # the rest are on or off
        return isinstance(value, bool), value
    return False, value


def clean_group_opts(raw) -> dict[str, dict]:
    """Edits.group_opts as saved, every group and setting checked (_group_value); a bad one is dropped,
    so that group shows the tree's own.  "centre_heads" always follows "text_valign"."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for group, values in raw.items():
        if group not in GROUPS or not isinstance(values, dict):
            continue
        kept = {}
        for name, value in values.items():
            good, value = _group_value(name, value) if name != "centre_heads" else (False, value)
            if good:
                kept[name] = value
        if "text_valign" in kept:
            kept["centre_heads"] = kept["text_valign"] == "middle"
        if kept:
            out[group] = {name: kept[name] for name in GROUP_FIELDS if name in kept}
    return out


def opt(edits: "Edits", p: gen.Person, name: str):
    """The setting `name` for this family member's portrait: their group's own (Edits.group_opts), else the
    tree's."""
    own = edits.group_opts.get(group_of(p))
    if own and name in own:
        return own[name]
    return getattr(edits, name)


def group_view(edits: "Edits", group: str | None) -> "Edits":
    """`edits` as one group's portraits see them (their own settings over the tree's); the tree's own
    for None."""
    own = edits.group_opts.get(group) if group else None
    return replace(edits, **own) if own else edits




def alphabetical(names) -> list[str]:
    """Choices in a list by name, A to Z (the owner, 2026-10-09: "alphabetize the options"); the
    special borders after the plain ones, themselves A to Z."""
    names = list(names)
    plain = sorted((n for n in names if not n.startswith("Special: ")), key=str.casefold)
    return plain + sorted((n for n in names if n.startswith("Special: ")), key=str.casefold)


def is_colour(value) -> bool:
    return isinstance(value, str) and (value == TRANSPARENT or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None)


STICKER_MIN = 6.0                       # the smallest a sticker's side may be
STICKER_MAX = 20000.0
PICTURE_TYPES = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
# The logos offered as stickers: the owner's own pictures, shipped beside the patcher in tree_pictures.
LOGOS = [("Virtual Families logo", "asset:virtual-families-logo.png"),
         ("Virtual Families 2 logo", "asset:virtual-families-2-logo.png"),
         ("Fish Tycoon logo", "asset:fish-tycoon-logo.png"),
         ("Plant Tycoon logo", "asset:plant-tycoon-logo.png")]


def _number(value, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return max(low, min(high, float(value)))


# The words on the tree a player can give their own font, size, style and colour.
ROLES = {
    "title": "Title",
    "subtitle": "Subtitle",
    "key": "Key (the marks)",
    "labels": "Generation labels",
    "names": "Names in the portraits",
    "portraits": "Other words in the portraits",
    "others": "Other Members heading",
    "footer": "Footer",
    "onward": "Continued on page words",
}
ALIGNS = {"left": "Left", "centre": "Centre", "right": "Right"}
# A portrait's shape and border (the owner's lists).
PORTRAIT_SHAPES = {"rectangle": "Rectangle", "rounded_rect": "Rounded rectangle", "rect": "Square",
                   "rounded": "Rounded square", "circle": "Circle", "ellipse": "Oval",
                   "oval_wide": "Oval (horizontal)",
                   "heart": "Heart", "triangle": "Triangle", "diamond": "Diamond", "cross": "Cross", "x": "X",
                   "plus": "Plus", "star": "Star", "hexagon": "Hexagon", "octagon": "Octagon", "trapezoid": "Trapezoid", "pentagon": "Pentagon",
                   "star4": "4-pointed star", "plump_star": "Plump star", "star6": "6-pointed star",
                   "slim_star6": "Slim 6-pointed star", "arrow_h": "Arrow (horizontal)", "arrow_v": "Arrow (vertical)",
                   "arch": "Arch", "scallop": "Scallop shell", "snail": "Snail shell",
                   "hibiscus": "Hibiscus", "sand_dollar": "Sand dollar", "turtle_v": "Turtle shell (upright)",
                   "turtle_h": "Turtle shell (on its side)", "mermaid_tail": "Mermaid tail (upright)",
                   "mermaid_tail_h": "Mermaid tail (on its side)",
                   "fish_right": "Fish (facing right)", "fish_left": "Fish (facing left)",
                   "wave_circle": "Ocean wave in a circle", "conch": "Conch shell", "starfish": "Starfish", "monstera": "Monstera leaf",
                   "ship_wheel": "Ship's wheel", "coconut": "Coconut", "anchor": "Anchor", "bananas": "Bunch of bananas", "paw": "Paw print", "feather": "Feather", "coral": "Coral", "sea_fan": "Sea fan",
                   "brain_coral": "Brain coral",
                   "beetle": "Beetle",
                   "flower": "Flower", "butterfly": "Butterfly", "clover": "Clover", "spade": "Spade", "leaf": "Leaf"}
BORDERS = {"thin": "Thin line", "thick": "Thick line", "extra": "Extra thick line", "dotted": "Dotted",
           "dashed": "Dashed",
           "dashdot": "Dotted and dashed"}
BORDER_WIDTHS = {"thin": 1.5, "thick": 3.0, "extra": 6.0, "dotted": 2.5, "dashed": 2.5, "dashdot": 2.5}
# A special border (the owner, 2026-10-09): a braided rope round the portrait's own shape, whatever
# the shape (special_border).  The stone tablets tried beside it were taken out at the owner's word.
SPECIAL_BORDERS = {"rope": "Special: Braided rope", "vine_leaves": "Special: Vine with leaves",
                   "vine_flowers": "Special: Vine with hibiscus",
                   "vine_both": "Special: Vine with leaves and hibiscus"}
BORDERS.update(SPECIAL_BORDERS)
BORDER_WIDTHS.update({name: 1.5 for name in SPECIAL_BORDERS})
BORDER_WIDTHS.update({name: 0.0 for name in SPECIAL_BORDERS})     # the rope or the vine is the edge
# How see-through each part of the tree is, in percent, until the player says (pictures and text
# boxes have their own).
OPACITY = {"words": ("Words", 100), "plates": ("Boxes behind words", 80), "portraits": ("Portraits", 100),
           "lines": ("Family lines", 100), "onward": ("Continued on page words", 100)}
# The family lines' look (the owner: "I want to change line weights, types, absolutely everything in
# batch!"): every line's, or one family's.
LINE_TYPES = {"": "Solid", "dotted": "Dotted", "dashed": "Dashed", "dashdot": "Dotted and dashed"}
LINE_WIDTHS = (0.25, 20.0)
# How a special mark is drawn (the owner: "can marks be a "glow" around the portrait instead?").
MARK_STYLES = {"border": "A border round the portrait", "glow": "A glow round the portrait"}
GLOW_RINGS = 16
# Who gets which until the player says (males, females, babies on the way).
GROUPS = {"Male": "Males", "Female": "Females", "Upcoming": "Babies on the way"}
DEFAULT_SHAPES = {"Male": "rect", "Female": "circle", "Upcoming": "diamond"}       # the owner's
DEFAULT_BORDERS = {"Male": "thick", "Female": "thick", "Upcoming": "thick"}     # the owner's: all alike
SHAPES = {"rect": "Rectangle", "ellipse": "Oval"}           # a text box's own shape
VALIGNS = {"top": "Top", "middle": "Middle", "bottom": "Bottom"}


# Superscript and subscript: the words this much smaller, raised or lowered by this much of their size.
SCRIPTS = {"super": (0.65, -0.35), "sub": (0.65, 0.2)}


def clean_style(raw: dict) -> dict:
    """A role's style, every value in range: only what the player set."""
    out: dict = {}
    if isinstance(raw.get("font"), str) and raw["font"]:
        out["font"] = raw["font"]
    if raw.get("scale") is not None:
        out["scale"] = int(_number(raw.get("scale"), 25, 400, 100))
    for flag in ("bold", "italic", "underline", "strike"):
        if isinstance(raw.get(flag), bool):
            out[flag] = raw[flag]
    if raw.get("script") in SCRIPTS:
        out["script"] = raw["script"]
    if is_colour(raw.get("colour")):
        out["colour"] = raw["colour"]
    return out


# A portrait's own text formatted word by word (the owner: "please allow text formatting in the family
# tree portrait text section" -- select words, then format them): each of the entry's lines is kept as
# runs, [text, style], the style any of RUN_STYLE's keys.  A run's style beats its role's (the names'
# and the other portrait words'); what it leaves out is the role's.  "normal" script undoes a role's
# superscript or subscript for that run.
RUN_FLAGS = ("bold", "italic", "underline", "strike")
RUN_SCRIPTS = ("super", "sub", "normal")


def clean_run_style(raw) -> dict:
    """A run's style, every value in range: only what the player set."""
    if not isinstance(raw, dict):
        return {}
    out = {flag: raw[flag] for flag in RUN_FLAGS if isinstance(raw.get(flag), bool)}
    if raw.get("script") in RUN_SCRIPTS:
        out["script"] = raw["script"]
    if is_colour(raw.get("colour")) and raw["colour"] != TRANSPARENT:
        out["colour"] = raw["colour"].lower()
    return out


def merge_runs(runs) -> list[tuple[str, dict]]:
    """One line's runs with the empty ones dropped and neighbours of one style joined."""
    out: list[tuple[str, dict]] = []
    for text, style in runs:
        if not text:
            continue
        if out and out[-1][1] == style:
            out[-1] = (out[-1][0] + text, style)
        else:
            out.append((text, dict(style)))
    return out


def clean_runs(raw, lines: list[str]) -> list[list[tuple[str, dict]]] | None:
    """The saved runs of an entry's lines, checked: one list of [text, style] per line, their words
    exactly the line's.  None when there are none, none of them is formatted, or they do not match
    the lines (an older patcher retyped the lines and kept the runs: the words win, unformatted)."""
    if not isinstance(raw, list) or len(raw) != len(lines):
        return None
    out = []
    for line, runs in zip(lines, raw):
        if not isinstance(runs, list):
            return None
        pairs = []
        for run in runs:
            if not (isinstance(run, (list, tuple)) and len(run) == 2 and isinstance(run[0], str)):
                return None
            pairs.append((run[0], clean_run_style(run[1])))
        if "".join(text for text, _s in pairs) != line:
            return None
        out.append(merge_runs(pairs))
    return out if any(style for runs in out for _t, style in runs) else None


def runs_data(runs: list[list[tuple[str, dict]]] | None) -> list | None:
    """The runs as the edits file keeps them (lists, for JSON)."""
    return None if not runs else [[[text, dict(style)] for text, style in line] for line in runs]


def carry_styles(old_lines: list[str], old_runs, new_lines: list[str]) -> list | None:
    """The formatting of `old_lines` carried onto their retyped words (clicking the words on the
    tree and retyping them, or renumbering): every character the retyping kept keeps its style, and
    a typed one takes the style of the one before it.  The runs in their saved form, or None."""
    import difflib
    if not old_runs:
        return None
    old_text = "\n".join(old_lines)
    # The old characters' styles in order, a newline between lines unstyled.
    styles: list[dict] = []
    for k, line in enumerate(old_runs):
        if k:
            styles.append({})
        styles.extend(style for text, style in line for _ch in text)
    new_text = "\n".join(new_lines)
    new_styles: list[dict] = [{}] * len(new_text)
    matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            new_styles[j1:j2] = styles[i1:i2]
        else:
            before = new_styles[j1 - 1] if j1 > 0 and new_text[j1 - 1] != "\n" else (
                styles[i1] if i1 < len(styles) else {})
            new_styles[j1:j2] = [before] * (j2 - j1)
    out, at = [], 0
    for line in new_lines:
        out.append(merge_runs((ch, new_styles[at + k]) for k, ch in enumerate(line)))
        at += len(line) + 1
    return runs_data(out) if any(style for line in out for _t, style in line) else None


def clean_sticker(raw) -> dict | None:
    """A sticker (a picture, or a text box) as the edits file keeps it, every value in range;
    None when it is neither."""
    if not isinstance(raw, dict):
        return None
    kind = "text" if raw.get("kind") == "text" else "picture"
    if kind == "picture" and (not isinstance(raw.get("picture"), str) or not raw["picture"]):
        return None
    out = {"kind": kind}
    if kind == "text":
        out.update({
            "text": str(raw.get("text", "")),
            "font": str(raw.get("font", "")),
            "size": _number(raw.get("size"), 4, 400, 24.0),
            "bold": raw.get("bold") is True,
            "italic": raw.get("italic") is True,
            "underline": raw.get("underline") is True,
            "strike": raw.get("strike") is True,
            "colour": raw["colour"] if is_colour(raw.get("colour")) else INK,
            "align": raw["align"] if raw.get("align") in ALIGNS else "centre",
            "valign": raw["valign"] if raw.get("valign") in VALIGNS else "middle",
            "fill": raw["fill"] if is_colour(raw.get("fill")) else "",
            "fill_opacity": _number(raw.get("fill_opacity"), 0, 100, 100.0),
            "border": raw["border"] if is_colour(raw.get("border")) else "",
            "border_width": _number(raw.get("border_width"), 0, 40, 2.0),
            "shape": raw["shape"] if raw.get("shape") in SHAPES else "rect",
        })
    else:
        out["picture"] = raw["picture"]
    if isinstance(raw.get("page"), int) and not isinstance(raw.get("page"), bool) and 1 <= raw["page"] <= 99:
        out["page"] = raw["page"]       # the page it is on (its first generation); none: every page, as before
    return {
        **out,
        "cx": _number(raw.get("cx"), -STICKER_MAX, STICKER_MAX, 200.0),
        "cy": _number(raw.get("cy"), -STICKER_MAX, STICKER_MAX, 200.0),
        "w": _number(raw.get("w"), STICKER_MIN, STICKER_MAX, 200.0),
        "h": _number(raw.get("h"), STICKER_MIN, STICKER_MAX, 200.0),
        "angle": _number(raw.get("angle"), -1e6, 1e6, 0.0) % 360,
        "flip_h": raw.get("flip_h") is True,
        "flip_v": raw.get("flip_v") is True,
        "opacity": _number(raw.get("opacity"), 0, 100, 100.0),
    }


# What a page keeps of its own (Edits.page_edits).  Everything, a villager's generation (the row they sit
# in) and chosen look too (the owner, 2026-10-13: "everything in the family tree must be per page").  The
# tree-wide value is the default; a page's own only ever changes that page.  Which page a villager is on
# stays the tree's generation, so a page's own generation is one within the page's own generations.


def _clean_entry_field(name: str, value):
    """One saved per-page entry field, or (False, None) when it is not a valid value of its kind."""
    if value is None:
        return True, None
    if name == "generation":
        return (True, value) if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 99 \
            else (False, None)
    if name == "look":
        return (True, value) if isinstance(value, list) and len(value) == 2 \
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value) else (False, None)
    if name in ("marks", "unmarked"):
        return (True, _clean_labels(value) or None) if isinstance(value, list) else (False, None)
    return True, value


def _clean_labels(raw) -> list[str]:
    """A saved list of mark names: words only, each once, in order."""
    out: list[str] = []
    for label in raw if isinstance(raw, list) else []:
        if isinstance(label, str) and label.strip() and label.strip() not in out:
            out.append(label.strip())
    return out


def entry_marks(entry: dict) -> list[str]:
    """Every mark a family member's entry gives them, in order (an older file's one "mark" too)."""
    if "marks" in entry:
        return list(entry.get("marks") or [])
    return [entry["mark"]] if entry.get("mark") else []


# The marks the tree gives by itself: Virtual Families has no special titles, so only the player's own marks.
STATUS_COLOURS: dict[str, str] = {}     # Virtual Families has no special titles
CUSTOM_MARK_COLOURS = ("#c71585", "#2e8b57", "#4169e1", "#d2691e", "#6a5acd", "#228b22", "#dc143c", "#008b8b",
                       "#b8860b", "#8b008b")


def status_colour(status: str) -> str:
    """A status's mark colour: its preset, else one of CUSTOM_MARK_COLOURS by its words (the same each time)."""
    import zlib
    return STATUS_COLOURS.get(status) or CUSTOM_MARK_COLOURS[zlib.crc32(status.encode("utf-8")) % len(CUSTOM_MARK_COLOURS)]


def auto_label(edits: "Edits", status: str) -> str:
    """The name of a status's mark: the status's own, or what the player renamed the mark to."""
    return edits.mark_names.get(status, status)


def auto_labels(edits: "Edits", p: gen.Person) -> list[str]:
    """The automatic marks a family member is given: each status they hold or held (Person.statuses), by its
    mark's name now, but none the player removed from everyone (marks_off)."""
    out = []
    for status in getattr(p, "statuses", []) or []:
        label = auto_label(edits, status)
        if status not in edits.marks_off and label not in edits.marks_off and label not in out:
            out.append(label)
    return out


def apply_auto_marks(edits: "Edits", village: gen.Village) -> bool:
    """Every family member's automatic marks into the tree's edits (the tree's own data, never the save): each one
    the player has not taken off them ("unmarked", the tree's or a page's) added after their own marks, and
    every such mark into the Key's list with its colour.  The player's own marks and edits stay as they are.
    Whether anything changed."""
    changed = False
    for p in village.people.values():
        if p.upcoming:
            continue
        labels = auto_labels(edits, p)
        if not labels:
            continue
        key = entry_key(village, p)
        for part in edits.page_edits.values():
            over = part.get("entries", {}).get(key)
            if over and "mark" in over and "marks" not in over:
                # An earlier build's page mark, one name: as a list, so the tree's list below never hides it.
                over["marks"] = [over["mark"]] if over["mark"] else None
        entry = edits.entries.get(key, {})
        off = set(entry.get("unmarked") or [])
        have = entry_marks(entry)
        add = [label for label in labels if label not in have and label not in off]
        if add:
            entry = edits.entries.setdefault(key, entry)
            entry["marks"] = have + add
            entry["mark"] = entry["marks"][0]
            changed = True
        # A page with marks of its own: the new ones there too, unless taken off on that page.
        for part in edits.page_edits.values():
            over = part.get("entries", {}).get(key)
            if over and over.get("marks"):
                page_off = off | set(over.get("unmarked") or [])
                more = [label for label in labels if label not in over["marks"] and label not in page_off]
                if more:
                    over["marks"] = over["marks"] + more
                    changed = True
        for label in labels:
            if label not in edits.marks and label not in off:
                status = next((s for s in p.statuses if auto_label(edits, s) == label), label)
                edits.marks[label] = status_colour(status)
                changed = True
    return changed


def _clean_line_shift(shift):
    """A dragged line's shift as a page keeps it: [right, down], a number (across itself), or None (not
    moved on this page whatever the tree's own says); False when it is nothing valid."""
    if shift is None:
        return None
    if isinstance(shift, list) and len(shift) == 2 and all(isinstance(v, (int, float)) for v in shift):
        return [_number(v, -STICKER_MAX, STICKER_MAX, 0.0) for v in shift]
    if isinstance(shift, (int, float)) and not isinstance(shift, bool):
        return _number(shift, -STICKER_MAX, STICKER_MAX, 0.0)
    return False


def page_key(edits: Edits, village: gen.Village, page: int) -> int:
    """A page's name in the edits: its first generation (it stays the page's name when pages before it are
    added or joined)."""
    spans = page_spans(edits, village)
    return spans[max(0, min(page, len(spans) - 1))][0]


def clean_page_edits(raw) -> dict[str, dict]:
    """Edits.page_edits as the file keeps it, every part checked; empty pages dropped."""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for key, part in raw.items():
        if not isinstance(part, dict) or not str(key).isdigit():
            continue
        item: dict = {}
        entries = {}
        for ekey, fields in (part.get("entries") or {}).items() if isinstance(part.get("entries"), dict) else []:
            if isinstance(fields, dict) and fields:
                kept = {}
                for f, v in fields.items():
                    ok, v = _clean_entry_field(str(f), v)
                    if ok:
                        kept[str(f)] = v
                if "marks" in kept:                     # one page's marks: the list, its first as "mark"
                    kept["mark"] = kept["marks"][0] if kept["marks"] else None
                if kept:
                    entries[str(ekey)] = kept
        if entries:
            item["entries"] = entries
        if isinstance(part.get("line_moves"), dict):
            shifts = {}
            for piece, shift in part["line_moves"].items():
                shift = _clean_line_shift(shift)
                if shift is not False and (shift is None or any(shift if isinstance(shift, list) else [shift])):
                    shifts[str(piece)] = shift
            if shifts:
                item["line_moves"] = shifts
        if isinstance(part.get("free_lines"), list):
            item["free_lines"] = [str(p) for p in part["free_lines"]]
        moved = {str(n): [_number(s[0], -STICKER_MAX, STICKER_MAX, 0.0), _number(s[1], -STICKER_MAX, STICKER_MAX, 0.0)]
                 for n, s in (part.get("moved") or {}).items()
                 if isinstance(s, list) and len(s) == 2} if isinstance(part.get("moved"), dict) else {}
        if isinstance(part.get("moved"), dict):         # None: not moved on this page, whatever the tree's own says
            moved.update({str(n): None for n, s in part["moved"].items() if s is None})
        if moved:
            item["moved"] = moved
        if isinstance(part.get("hidden"), list):
            item["hidden"] = [str(h) for h in part["hidden"]]
        for name in ("family_colours", "person_colours"):
            colours = {str(k): v for k, v in part[name].items() if v is None or is_colour(v)} \
                if isinstance(part.get(name), dict) else {}
            if colours:
                item[name] = colours
        if isinstance(part.get("generations"), dict):   # a generation label's lines; None: the patcher's own here
            labels = {str(g): ([str(x) for x in lines] if isinstance(lines, list) else None)
                      for g, lines in part["generations"].items()
                      if str(g).isdigit() and (lines is None or isinstance(lines, list))}
            if labels:
                item["generations"] = labels
        if item:
            out[str(int(key))] = item
    return out


def page_view(edits: Edits, village: gen.Village, page: int) -> Edits:
    """The edits as one page shows them: the tree's own with that page's laid over them (a copy; `edits`
    itself when the page keeps nothing of its own).  Nothing placed on one page is seen on another."""
    part = edits.page_edits.get(str(page_key(edits, village, page)))
    if not part:
        return edits
    view = replace(edits)
    entries = {k: dict(v) for k, v in edits.entries.items()}
    for ekey, fields in part.get("entries", {}).items():
        merged = entries.setdefault(ekey, {})
        for name, value in fields.items():
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        if not merged:
            del entries[ekey]
    view.entries = entries
    view.moved = {n: s for n, s in {**edits.moved, **part.get("moved", {})}.items() if s is not None}
    if "hidden" in part:
        view.hidden = list(part["hidden"])
    if "line_moves" in part:                    # None: not dragged on this page, whatever the tree's own says
        view.line_moves = {p: s for p, s in {**edits.line_moves, **part["line_moves"]}.items() if s is not None}
    if "free_lines" in part:
        view.free_lines = list(part["free_lines"])
    if "generations" in part:                   # None: no label of the player's own on this page
        view.generations = {g: list(lines) for g, lines in
                            {**edits.generations, **part["generations"]}.items() if lines is not None}
    for name in ("family_colours", "person_colours"):
        if name in part:
            merged = dict(getattr(edits, name))
            for k, v in part[name].items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            setattr(view, name, merged)
    return view


def page_village(edits: Edits, village: gen.Village, page: int) -> gen.Village:
    """The family as one page shows it: a family member a page puts in another generation (a "generation" in
    that page's own entries) sits in that row on that page alone, the rest of the tree as it was (`family`
    itself when the page moves nobody).  Who is on which page stays the tree's: a page only moves family members
    between the generations it already shows, and keeps the tree's pages (span_generations)."""
    part = edits.page_edits.get(str(page_key(edits, village, page)))
    if not part or not any("generation" in f for f in part.get("entries", {}).values()):
        return village
    spans = page_spans(edits, village)
    lo, hi = spans[max(0, min(page, len(spans) - 1))]
    entries = page_view(edits, village, page).entries
    changed: dict[int, int] = {}
    for pid, p in village.people.items():
        if not lo <= p.generation <= hi:
            continue
        g = entries.get(entry_key(village, p), {}).get("generation") or village.base_generation.get(pid, p.generation)
        if g != p.generation and lo <= g <= hi:
            changed[pid] = g
    if not changed:
        return village
    out = _copy(village)
    out.people = {pid: _copy(p) for pid, p in village.people.items()}
    for pid, g in changed.items():
        out.people[pid].generation = g
    out.span_generations = sorted({p.generation for p in village.people.values()}) or [1]
    _renumber(out, replace(edits, entries=entries))
    return out


def localise_stickers(edits: Edits, village: gen.Village) -> bool:
    """Stickers saved before pages kept their own (no "page") were drawn on every page: one copy for each
    page now, in the same stacking, so each is moved or deleted on its own page.  True when any changed."""
    if all("page" in s for s in edits.stickers):
        return False
    keys = sorted({lo for lo, _hi in page_spans(edits, village)})
    out = []
    for raw in edits.stickers:
        if "page" in raw:
            out.append(raw)
        else:
            out.extend({**raw, "page": k} for k in keys)
    edits.stickers = out
    return True


def turn(x: float, y: float, angle: float) -> tuple[float, float]:
    """(x, y) turned clockwise (on the screen, y down) by `angle` degrees about the origin."""
    a = math.radians(angle)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def is_dark(colour: str) -> bool:
    """Whether dark words would be hard to read on this colour (nothing shows through transparent)."""
    if colour == TRANSPARENT:
        return False
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b < 110


def parse_colour(text: str) -> str | None:
    """A colour the player typed: "#d4a017", "d4a017", red, green and blue 0-255 ("212, 160, 23"
    or "rgb(212, 160, 23)"), or "transparent" (or "none").  None when it is neither."""
    text = text.strip()
    if text.lower() in ("transparent", "none", "clear"):
        return TRANSPARENT
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", text)
    if m:
        return "#" + m.group(1).lower()
    m = re.fullmatch(r"(?:rgb\s*\()?\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*\)?", text, re.I)
    if m and all(int(v) <= 255 for v in m.groups()):
        return "#%02x%02x%02x" % tuple(int(v) for v in m.groups())
    return None


def family_key(village: gen.Village, fam: "Family") -> str:
    """Which family a colour is for: its father's and mother's keys."""
    def one(pid):
        return entry_key(village, village.people[pid]) if pid is not None else "-"
    return f"{one(fam.father)}||{one(fam.mother)}"


# Where Save keeps the editable tree file (".tree"), and where the page and pictures go: the patcher's own
# folder for the save (vf1_genealogy.slot_root).
TREES = "Family Tree"
TREE_SUFFIX = ".tree"
TREE_FORMAT = "Virtual Families 1 Patcher family tree"


def data_folder(folder: Path, slot: int) -> Path:
    """Virtual Families 1 Patcher\\Save <N>\\Data\\Family Tree: the edits and the .tree file."""
    return gen.slot_root(folder, slot) / "Data" / TREES


def reports_folder(folder: Path, slot: int) -> Path:
    """Virtual Families 1 Patcher\\Save <N>\\Family Tree: the page, the pictures and the report."""
    return gen.slot_root(folder, slot) / TREES


# The tree's look as a whole, which the Family Tree Maker remembers when it closes and gives a tree
# that has no edits of its own yet (the owner, 2026-10-08: "Save the player's settings on close and
# reopen (portrait shape/any other changes)").  Never a village's own things: its title, moved
# portraits, pages, words, families' colours, villagers' entries or stickers.
STYLE_KEYS = (
    "centre_heads", "text_align", "text_inside", "fixed_face_size", "turn_words", "flip_words", "text_room", "special_mode", "special_pick", "special_palette",
    "special_count", "hibiscus", "special_opacity", "rainbow_strength", "schemes", "detail_lines", "detail_colour", "detail_opacity", "detail_width", "text_box_colour", "text_box_opacity", "text_box_over", "text_box_border", "text_box_border_colour", "text_box_border_width", "text_valign", "text_wrap", "row_align", "row_valign", "row_limit", "keep_families", "others_columns", "others_side", "packing", "lines_behind", "picture_size", "text_size", "portrait_gap", "row_gap", "show_founder", "fit_width", "canvas_w", "canvas_h", "page_generations", "diagonal_lines",
    "show_units", "show_years", "show_twins", "show_runner", "show_arrived", "show_heir", "show_left_home",
    "show_divorced", "show_deceased", "show_career", "show_adopted", "show_remarried", "show_spouse_order",
    "descriptors_v2",
    "number_names", "number_names_v2", "number_order", "sort", "positioning", "numbering",
    "background", "background2", "rainbow", "background_image", "background_fit", "background_opacity",
    "ink", "font", "styles", "portrait_fill", "shapes", "borders", "plate_colour", "opacity", "sizes",
    "line_width", "line_dash", "mark_style", "mark_glow", "mark_opacity", "label_line_width",
    "label_line_reach", "marks", "group_opts", "equal_sizes", "monstera_v2", "feather_v2",
)


def style_of(edits: "Edits") -> dict:
    """The look of `edits` (STYLE_KEYS), as the settings file keeps it."""
    data = edits.to_data()
    return {key: data[key] for key in STYLE_KEYS if key in data}


def styled(style: dict | None) -> "Edits":
    """A new tree's edits with a remembered look; the patcher's own where it has none or it does not
    read (an older or damaged settings file never stops the tree from opening)."""
    base = Edits().to_data()
    if isinstance(style, dict):
        base.update({key: value for key, value in style.items() if key in STYLE_KEYS})
        if style.get("number_names_v2") is not True:   # a look an earlier build kept: numbering's new default
            base["number_names"] = True
        if style.get("descriptors_v2") is not True:     # and the descriptors' new default: on
            base.update(show_founder=True, show_runner=True, show_twins=True)
        shapes = style.get("shapes") if isinstance(style.get("shapes"), dict) else {}
        for name in SHAPE_BAKES:                # a look remembered before, with that shape: moved on
            if f"{name}_v2" not in style and name in shapes.values():
                base[f"{name}_v2"] = False
    try:
        return Edits.from_data(base)
    except ValueError:
        return Edits()


def renamed_keys(text: str, renames: dict[tuple, str]) -> str:
    """Saved edits (an edits file or a .vvtree, as text) with each renamed family member's key --
    "<name>|<head>|<body>", in an entry, a family, an order, a line piece -- under their new name."""
    for (name, head, body), new in renames.items():
        key = json.dumps(new)[1:-1] + f"|{head}|{body}"
        text = re.sub(rf'(?<=["|: ]){re.escape(json.dumps(name)[1:-1])}\|{head}\|{body}(?=["| ])',
                      lambda _found, key=key: key, text)
    return _renamed_lines(text, renames)


def _name_pattern(name: str, numbered: bool = False) -> re.Pattern:
    """`name` as a whole name in a line of words: never inside a longer word, and never the start of
    a longer numbered name ("Iruwa Bahati I" is not in "Iruwa Bahati II").  `numbered`: with any
    Roman number after it too."""
    tail = r"(?: [IVXLCDM]+)?(?!\w)" if numbered else r"(?! [IVXLCDM]+(?!\w))(?!\w)"
    return re.compile(rf"(?<!\w){re.escape(name)}{tail}")


def _rename_in_lines(lines: list, runs, pattern: re.Pattern, new: str) -> tuple[list, object]:
    """The player's own lines (and their formatted runs) with the name the pattern finds put as `new`.
    A name the formatting splits across runs is renamed in the lines and the runs dropped for that
    line, so the words always win (clean_runs)."""
    out = [pattern.sub(new, line) if isinstance(line, str) else line for line in lines]
    if isinstance(runs, list) and len(runs) == len(lines):
        runs = [[[pattern.sub(new, r[0]), r[1]] if isinstance(r, list) and len(r) == 2 and isinstance(r[0], str)
                 else r for r in line_runs] if isinstance(line_runs, list) else line_runs
                for line_runs in runs]
        runs = [line_runs if isinstance(line_runs, list) and isinstance(line, str)
                and "".join(r[0] for r in line_runs if isinstance(r, list) and r and isinstance(r[0], str)) == line
                else [[line, {}]] for line, line_runs in zip(out, runs)]
    return out, runs


def _renamed_lines(text: str, renames: dict[tuple, str]) -> str:
    """The edits (as text) with each renamed family member's name put right in the words the player typed
    for their portrait (the owner, 2026-10-08: "the family tree still carries the old names").  Only
    in that family member's own entry: two namesakes can be renamed apart."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    entries = data.get("entries") if isinstance(data.get("entries"), dict) else \
        (data.get("edits") or {}).get("entries") if isinstance(data.get("edits"), dict) else None
    if not isinstance(entries, dict):
        return text
    changed = False
    for (name, head, body), new in renames.items():
        entry = entries.get(f"{new}|{head}|{body}")
        if not isinstance(entry, dict) or not isinstance(entry.get("lines"), list) or name == new:
            continue
        lines, runs = _rename_in_lines(entry["lines"], entry.get("runs"), _name_pattern(name), new)
        if lines != entry["lines"] or runs != entry.get("runs"):
            entry["lines"] = lines
            if "runs" in entry:
                entry["runs"] = runs
            changed = True
    if not changed:
        return text
    # Written back as it was written: a .vvtree (indent 1), an edits file (indent 2), or one line.
    if not text.startswith("{\n"):
        return json.dumps(data)
    if text.startswith('{\n "'):
        return json.dumps(data, indent=1)
    return json.dumps(data, indent=2, ensure_ascii=False) + ("\n" if text.endswith("\n") else "")


def relooked_keys(text: str, relooked: dict[tuple, tuple]) -> str:
    """Saved edits (as text) with each key of a family member's old look -- before Change Appearance --
    moved to the look they have now, so their edits follow them (as renamed_keys for a new name)."""
    for (name, head, body), (_name, new_head, new_body) in relooked.items():
        old = re.escape(json.dumps(name)[1:-1]) + rf"\|{head}\|{body}"
        new = json.dumps(name)[1:-1] + f"|{new_head}|{new_body}"
        text = re.sub(rf'(?<=["|: ]){old}(?=["| ])', lambda _found, new=new: new, text)
    return text


def full_name_edits(edits: "Edits", village: gen.Village) -> "Edits":
    """The edits with each family member's key under a name the Family Member Details screen cut moved to the
    full name the tree shows them by (vv_cut_names; the owner: "Family trees will use the full names
    from the logs"), so marks made while the tree showed the cut name follow them.  The same edits
    when nothing moves."""
    if not village.full_names:
        return edits
    text = json.dumps(edits.to_data())
    moved = renamed_keys(text, village.full_names)
    # Edits kept under both the cut key and the full one become one villager's: merged, never one
    # dropped for the other (review, 2026-10-07).
    return edits if moved == text else Edits.from_data(json.loads(moved, object_pairs_hook=_merge_pairs))


def _merge_pairs(pairs: list) -> dict:
    """A JSON object whose key repeats after re-keying: dictionaries merged (the first one's values
    kept where both have one), lists of names joined without repeats, any other value -- a [dx, dy]
    move among them -- the first one's (review, 2026-10-07)."""
    out: dict = {}
    for key, value in pairs:
        if key not in out:
            out[key] = value
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = {**value, **out[key]}
        elif (isinstance(out[key], list) and isinstance(value, list)
              and all(isinstance(v, str) for v in out[key] + value)):
            out[key] = out[key] + [v for v in value if v not in out[key]]
    return out


def look_of(edits: "Edits", village: gen.Village, p: gen.Person) -> tuple:
    """The (head, body) the tree shows: the one the player chose after Change Appearance, else now."""
    look = edits.entries.get(entry_key(village, p), {}).get("look")
    return tuple(look) if look else (p.head, p.body)


def entry_key(village: gen.Village, p: gen.Person) -> str:
    """Who an edit is for: the family member's name, head and body; a baby on the way by its mother."""
    if p.upcoming:
        m = village.people[p.mother]
        return f"upcoming|{m.name}|{m.head}|{m.body}|{-(p.body or 0)}"
    # Two living family members of one name and look are two people, each with their own edits, kept by what
    # tells them apart for good -- their place in the save's Family Tree ("|<seat>", vf1_genealogy.
    # mark_namesakes; "|<rank>" after it only between namesakes sharing it) -- never by their place by age
    # alone, which moves to another member when an older namesake dies (a port of the Virtual Villagers Fun
    # Patcher v1.35.85; settle_namesakes).  A family member with no living namesake: "name|head|body", as always.
    suffix = getattr(p, "edit_suffix", "") if getattr(p, "namesake_rank", 0) else ""
    return f"{p.name}|{p.head}|{p.body}" + suffix


PARKED = "parked|"


def _rekeyed(value, old: str, new: str):
    """`value` (an edits file's data) with the family member's key `old` -- a dictionary key, a list item, or a
    deleted member ("villager:<key>") -- made `new`.  Keys that only contain it (a family's) are left as they are."""
    if isinstance(value, dict):
        return {(new if k == old else k): _rekeyed(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [new if v == old else f"villager:{new}" if v == f"villager:{old}" else _rekeyed(v, old, new)
                for v in value]
    return value


def _keys_used(value, out: set) -> set:
    """Every family member's key `value` (an edits file's data) uses: entries, colours, orders, deleted members."""
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k)
            _keys_used(v, out)
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, str):
                out.add(v[len("villager:"):] if v.startswith("villager:") else v)
            else:
                _keys_used(v, out)
    return out


def settle_namesakes(village: gen.Village, edits: "Edits") -> bool:
    """Keep each living namesake's tree edits with that family member (a port of the Virtual Villagers Fun
    Patcher v1.35.85).  Nothing is ever deleted or given to another member: an edit that cannot be told to be
    someone's is PARKED -- kept in the file under "parked|<its key>", applied to nobody.
      * While two or more living family members share a name and look, each one's edits are under "name|head|
        body|<seat>" (entry_key).  The plain key an earlier build used for all of them cannot be told to be
        anyone's now: parked (unless it is recorded as one member's, below).
      * Namesakes sharing a marker are told apart by their place by age; their edits are kept only while the
        group is exactly as it was (`edits.namesakes`, the markers oldest first), else parked.
      * A member whose namesakes are gone takes back their own marker's edits under the plain key (when the
        plain key holds nothing of anyone's).
      * The plain key's edits of a member with no namesake are recorded as theirs (`edits.key_owners`), so
        when a namesake appears they stay that member's (under their marker); unrecorded, they are parked.
    True when the edits changed."""
    data = edits.to_data()
    data.pop("namesakes", None)                 # this function's own records: not villager keys
    data.pop("key_owners", None)
    used = _keys_used(data, set())
    kept = dict(edits.namesakes)
    owners = dict(edits.key_owners)
    moves: list[tuple[str, str]] = []

    def park(key: str) -> None:
        target, n = PARKED + key, 2
        while target in used or any(t == target for _k, t in moves):
            target, n = f"{PARKED}{key}#{n}", n + 1
        moves.append((key, target))

    groups: dict[str, list] = {}
    for p in village.people.values():
        if p.alive and not p.upcoming and getattr(p, "namesake_rank", 0):
            groups.setdefault(f"{p.name}|{p.head}|{p.body}", []).append(p)

    def kind(key: str, plain: str) -> str | None:
        """What a family member's key of `plain` is: "plain", "rank" ("|2"), "marker" ("|<seat>"), "tied"
        ("|<seat>|<rank>"); None for anything else (a family's key holds "||")."""
        if key == plain:
            return "plain"
        if not key.startswith(plain + "|") or "||" in key:
            return None
        rest = key[len(plain) + 1:].split("|")
        if len(rest) == 1:
            return "rank" if rest[0].isdigit() else "marker"
        if len(rest) == 2 and rest[1].isdigit():
            return "tied"
        return None

    for plain, members in groups.items():
        members.sort(key=lambda p: p.namesake_rank)
        sig = [p.marker for p in members]
        same_group = kept.get(plain) == sig
        mine = {entry_key(village, p) for p in members}
        owner = owners.pop(plain, None)
        heir = [p for p in members if owner and p.marker == owner]
        for key in sorted(used):
            what = kind(key, plain)
            if what == "plain" and len(heir) == 1 and entry_key(village, heir[0]) not in used:
                moves.append((key, entry_key(village, heir[0])))    # the one who had it alone keeps it
            elif what in ("plain", "rank") or (what == "tied" and not same_group):
                park(key)               # an earlier build's shared key, or a tie the group no longer holds
            elif what == "tied" and key not in mine:
                park(key)
        kept[plain] = sig
    for plain in [k for k in kept if k not in groups]:
        alone = [p for p in village.people.values()
                 if p.alive and not p.upcoming and f"{p.name}|{p.head}|{p.body}" == plain]
        own = f"{plain}|{alone[0].marker}" if len(alone) == 1 else None
        for key in sorted(used):
            what = kind(key, plain)
            if what == "marker" and key == own and plain not in used:
                moves.append((key, plain))      # their own edits, back under the plain key
            elif what in ("marker", "tied"):
                park(key)
        del kept[plain]
    # Whose the plain key's edits are while they have no namesake: given to them alone when a namesake
    # appears (a file first read while a group already lives has no such record: its plain key is parked).
    for p in village.people.values():
        plain = f"{p.name}|{p.head}|{p.body}"
        if (p.alive and not p.upcoming and not getattr(p, "namesake_rank", 0) and p.marker and plain not in groups
                and (plain in used or any(new == plain for _old, new in moves))):
            owners[plain] = p.marker
    if not moves and kept == edits.namesakes and owners == edits.key_owners:
        return False
    for old, new in moves:
        data = _rekeyed(data, old, new)
    fresh = Edits.from_data(data)
    fresh.namesakes, fresh.key_owners = kept, owners
    edits.__dict__.update(fresh.__dict__)
    return True


@dataclass
class Layout:
    village: gen.Village
    rows: dict[int, list[int]]                    # generation -> person ids, left to right
    x: dict[int, float]
    y: dict[int, float]
    families: list[Family]
    others: list[int]
    others_left: float
    width: float
    height: float
    tops: dict[int, float] = field(default_factory=dict)         # generation -> its row's top
    bands: dict[int, float] = field(default_factory=dict)        # generation -> its rows' height
    birth_colour: dict[int, str] = field(default_factory=dict)
    edits: Edits = field(default_factory=Edits)
    page: int = 0                       # which page of the tree this is (page_spans)
    names: dict[int, str] = field(default_factory=dict)          # Number Duplicate Names: id -> "Soda II"
    pages: int = 1
    shrink: float = 1.0                 # this page's Shrink to fit (each page its own; Codex, #575)
    label_left: float = 0.0             # how far right the generation labels sit (the Other Members on the left)
    row_keys: dict = field(default_factory=dict)    # portrait -> its row, where a row is not its generation's
    subs: dict = field(default_factory=dict)        # portrait -> which of its generation's rows it was laid in
    _spans: list = field(default_factory=list, repr=False)

    @property
    def background(self) -> str:
        return self.edits.background or BACKGROUND

    @property
    def ink(self) -> str:
        """The words on the background: the player's colour, else dark on a light background and
        light on a dark one."""
        return self.edits.ink or (LIGHT_INK if is_dark(self.background) else INK)

    @property
    def portrait_ink(self) -> str:
        """The words in the portraits, which are white: the player's colour, else dark."""
        return self.edits.ink or INK

    def entry(self, p: gen.Person) -> dict:
        return self.edits.entries.get(entry_key(self.village, p), {})

    def opt(self, p: gen.Person, name: str):
        """A setting for this family member's portrait: their group's own, else the tree's (opt())."""
        return opt(self.edits, p, name)

    def shape(self, p: gen.Person) -> str:
        """The portrait's shape, as drawn: mirrored when the player flipped it ("heart~h")."""
        entry = self.entry(p)
        return flipped_kind(shape_of(self.edits, self.village, p), entry.get("flip_h", False), entry.get("flip_v", False))

    def border(self, p: gen.Person) -> str:
        return self.entry(p).get("border") or self.edits.borders[group_of(p)]

    def frame(self, q: int) -> tuple[float, float, float, float, float]:
        """q's portrait frame (left, top, width, height, angle): its shape at the shape's own
        proportions, as tall as a portrait, unless the player resized it; centred on the portrait;
        turned `angle` degrees about its middle."""
        p = self.village.people[q]
        w, h = frame_size(self.edits, self.village, p, shrink=self.shrink)
        top = self.y[q] + NODE_H / 2 - h / 2
        if self.edits.row_valign != "middle":   # lined up with the tallest in their row (Edits.row_valign)
            tallest = self.row_heights().get(q, h)
            top += (h - tallest) / 2 if self.edits.row_valign == "top" else (tallest - h) / 2
        return self.x[q] + NODE_W / 2 - w / 2, top, w, h, self.entry(p).get("angle", 0.0)

    def row_heights(self) -> dict[int, float]:
        """Each portrait's row's tallest frame (worked out once: every frame asks).  A row: one
        generation of the tree, or of the Other Members."""
        heights = self.__dict__.get("_row_heights")
        if heights is None:
            tallest: dict[tuple, float] = {}
            rows = {}
            others = set(self.others)
            for q in self.x:
                p = self.village.people[q]
                rows[q] = self.row_keys.get(q, (p.generation, q in others))
                h = frame_size(self.edits, self.village, p, shrink=self.shrink)[1]
                tallest[rows[q]] = max(tallest.get(rows[q], 0.0), h)
            heights = {q: tallest[row] for q, row in rows.items()}
            self.__dict__["_row_heights"] = heights
        return heights

    def spans(self) -> list[tuple[float, float, float]]:
        """Every portrait's frame across (left, right) and its top: what a line keeps clear of
        (worked out once: every route asks)."""
        if not self._spans:
            for q in self.x:
                xs = [px for px, _py in self.frame_points(q)]
                self._spans.append((min(xs), max(xs), self.y[q]))
        return self._spans

    def frame_points(self, q: int) -> list[tuple[float, float]]:
        kind = self.shape(self.village.people[q])
        x, y, w, h, angle = self.frame(q)
        return shape_points(kind, x, y, w, h, corner_radius(kind), angle)

    def mark(self, p: gen.Person) -> str | None:
        """The colour of the family member's first mark, if any."""
        found = self.marks(p)
        return found[0][1] if found else None

    def marks(self, p: gen.Person) -> list[tuple[str, str]]:
        """Every mark the family member has that the Key lists, (name, colour), in their order."""
        return drawn_marks(self.edits, self.entry(p))


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def tidy_rows(lay: "Layout") -> tuple[dict[int, int], dict[str, list[str]]]:
    """For Reorganize portraits: the generation whose band each portrait was left nearest, and each such
    generation's order -- row by row of the generation (a wrapped generation's rows, a band's staggered
    rows), left to right in each -- so a tree nobody dragged is put back exactly as it was.  A dragged
    portrait counts in the row it was left nearest."""
    v = lay.village
    gen_of: dict[int, int] = {}
    for q in lay.x:
        if q not in lay.others:
            # The band it stands in, else the nearest band's edge (a wrapped band is tall: its middle
            # may be further from its own first row than the band above is).
            middle = lay.y[q] + NODE_H / 2
            gen_of[q] = min(lay.tops, key=lambda g: (max(0.0, lay.tops[g] - middle,
                                                         middle - lay.tops[g] - lay.bands.get(g, NODE_H)), g))
    moved = {q for q in gen_of if lay.entry(v.people[q]).get("dx") or lay.entry(v.people[q]).get("dy")}
    orders: dict[str, list[str]] = {}
    for g in sorted(set(gen_of.values())):
        qs = [q for q in gen_of if gen_of[q] == g]
        row_y: dict[int, float] = {}            # each row's height, from those left where they were laid
        for q in qs:
            if q not in moved and v.people[q].generation == g:
                row_y.setdefault(lay.subs.get(q, 0), lay.y[q])

        def row(q: int) -> int:
            if q not in moved and v.people[q].generation == g:
                return lay.subs.get(q, 0)
            return min(row_y, key=lambda k: (abs(row_y[k] - lay.y[q]), k)) if row_y else 0
        orders[str(g)] = [entry_key(v, v.people[q]) for q in sorted(qs, key=lambda q: (row(q), lay.x[q]))]
    return gen_of, orders


def arrange(village: gen.Village, edits: Edits) -> None:
    """Each family member's generation and number as the tree shows them: the records' generation
    unless the player put them in another; numbered generation by generation in the tree's sort,
    or in the player's own order of a generation, left to right.  A family member deleted from the
    tree has no number, so the others' run on without a gap."""
    settle_namesakes(village, edits)            # each living namesake's edits with that family member
    for pid, p in village.people.items():
        own = edits.entries.get(entry_key(village, p), {}).get("generation")
        p.generation = own or village.base_generation.get(pid, p.generation)
    _renumber(village, edits)


def _renumber(village: gen.Village, edits: Edits) -> None:
    """The family members' numbers, given the generations they now have (the rest of arrange)."""
    gen.number_people(village, edits.sort)
    gone = {pid for pid, p in village.people.items() if edits.entries.get(entry_key(village, p), {}).get("hidden")}
    if not edits.orders and not gone:
        return
    for pid in gone:
        village.people[pid].number = None
    n = 0
    for g in sorted({p.generation for p in village.known()}):
        row = sorted((p for p in village.known() if p.generation == g and p.id not in gone), key=lambda p: p.number)
        order = {key: i for i, key in enumerate(edits.orders.get(str(g), []))}
        row.sort(key=lambda p: (order.get(entry_key(village, p), len(order)), p.number))
        for p in row:
            n += 1
            p.number = n


def _place(p: gen.Person) -> tuple:
    """A row's order is its numbers' (vf1_genealogy.number_people); babies on the way last."""
    return (p.upcoming, p.number or 0, p.order_key())


def group_of(p: gen.Person) -> str:
    """GROUPS: a baby on the way, a female or a male."""
    return "Upcoming" if p.upcoming else ("Female" if p.sex == "Female" else "Male")


def shape_of(edits: Edits, village: gen.Village, p: gen.Person) -> str:
    """The family member's portrait shape: their own, else their group's."""
    return edits.entries.get(entry_key(village, p), {}).get("shape") or edits.shapes[group_of(p)]


def _baked_turn(name: str, angle: float, flip_h: bool, flip_v: bool) -> tuple[float, bool]:
    """A portrait's (turn, flip across) drawing a shape drawn turned (SHAPE_BAKES) as (angle, flip_h, flip_v)
    drew it before: composed with the undoing of the shape's own turn and mirroring.  A flip up and down
    is a flip across turned half round."""
    degrees, mirrored = SHAPE_BAKES[name]
    angle += 180.0 if flip_v else 0.0
    if (flip_h != flip_v) == mirrored:          # mirrored as often as the shape: no flip left
        return (angle - degrees) % 360, False
    return (angle + degrees) % 360, True


def _baked_size(name: str, size) -> list[float]:
    """A frame's (width, height) drawing a shape drawn turned (SHAPE_BAKES) as (width, height) drew it before."""
    b = BAKED[name]
    s = math.sqrt(size[0] / b["old_w"] * size[1] / b["old_h"])
    return [max(FRAME_MIN, min(FRAME_MAX, s * b["new_w"])), max(FRAME_MIN, min(FRAME_MAX, s * b["new_h"]))]


def settle_shapes(edits: Edits, village: gen.Village) -> None:
    """Edits saved before a shape was drawn turned (SHAPE_BAKES; its marker, Edits.<shape>_v2, False)
    moved on once, so every portrait looks as it did (the owner, 2026-10-10): each such portrait's turn
    and flips composed with the shape's own (_baked_turn) -- the owner's Monstera leaves, turned 45 and
    flipped across, now neither -- and its sizes the box the same picture now fills (_baked_size)."""
    for name in SHAPE_BAKES:
        if not getattr(edits, f"{name}_v2"):
            _settle_shape(edits, village, name)
            setattr(edits, f"{name}_v2", True)
    if not edits.bakes_v3:
        _unturn_new_portraits(edits, village)
        edits.bakes_v3 = True


def _unturn_new_portraits(edits: Edits, village: gen.Village) -> None:
    """Moved on before 2026-10-10, a portrait of a shape drawn turned (SHAPE_BAKES) that had no turn or flip of
    its own -- a family member born or arrived since the player turned the others, never the look the player chose --
    was given the turn that drew the old look (the owner: "Newly generated ones are still in the wrong
    orientation"): that turn taken off again, so it is drawn as the shape now is, straight up."""
    edits.entries = dict(edits.entries)
    for p in village.people.values():
        key = entry_key(village, p)
        entry = edits.entries.get(key)
        name = (entry or {}).get("shape") or edits.shapes.get(group_of(p))
        if not entry or name not in SHAPE_BAKES:
            continue
        old = (round(entry.get("angle", 0.0), 6) % 360, entry.get("flip_h", False), entry.get("flip_v", False))
        angle, flip_h = _baked_turn(name, 0.0, False, False)
        if old == (round(angle, 6) % 360, flip_h, False):
            entry = {k: v for k, v in entry.items() if k not in ("angle", "flip_h", "flip_v")}
            if entry:
                edits.entries[key] = entry
            else:
                edits.entries.pop(key, None)


def _settle_shape(edits: Edits, village: gen.Village, name: str) -> None:
    old_sizes = {g: list(v) for g, v in edits.sizes.items()}
    edits.sizes, edits.entries = dict(edits.sizes), dict(edits.entries)    # never a dictionary shared elsewhere
    for g, size in old_sizes.items():
        if edits.shapes.get(g) == name:
            edits.sizes[g] = _baked_size(name, size)
    done = set()
    for p in village.people.values():
        key = entry_key(village, p)
        if key in done:
            continue
        done.add(key)
        entry = dict(edits.entries.get(key, {}))
        this = (entry.get("shape") or edits.shapes[group_of(p)]) == name
        group_size = old_sizes.get(group_of(p))
        group_this = edits.shapes[group_of(p)] == name
        if group_size and "w" not in entry and "h" not in entry and this != group_this:
            # The group's size, which the group's change (or not) would change for this one: their own.
            entry["w"], entry["h"] = _baked_size(name, group_size) if this else group_size
        elif this and ("w" in entry or "h" in entry):
            b = BAKED[name]                     # the side not their own: the group's, else the shape's as it was
            w, h = group_size or (NODE_H * round(b["old_w"] / b["old_h"], 3), NODE_H)
            entry["w"], entry["h"] = _baked_size(name, (entry.get("w", w), entry.get("h", h)))
        if this and any(entry.get(flip) for flip in ("angle", "flip_h", "flip_v")):
            # Only a turn or flip of the portrait's own (the look the player chose) is kept as it looked: one
            # with none is drawn as the shape now is (the owner: newly generated ones in the old orientation
            # were "the wrong orientation").
            angle, flip_h = _baked_turn(name, entry.get("angle", 0.0), entry.get("flip_h", False),
                                        entry.get("flip_v", False))
            for flip in ("angle", "flip_h", "flip_v"):
                entry.pop(flip, None)
            if round(angle, 6) % 360:
                entry["angle"] = round(angle, 6) % 360
            if flip_h:
                entry["flip_h"] = True
        if entry:
            edits.entries[key] = entry
        else:
            edits.entries.pop(key, None)

def frame_size(edits: Edits, village: gen.Village, p: gen.Person, own: bool = True,
               unscaled: bool = False, shrink: float = 1.0) -> tuple[float, float]:
    """A portrait frame's width and height: the family member's own (`own`), else their group's default
    size, else their shape's own proportions, a portrait tall -- shrunk to fit the page when the
    player asked (Edits.fit_width; `unscaled`: the sizes as the player set them)."""
    kind = shape_of(edits, village, p)
    gw, gh = edits.sizes.get(group_of(p)) or (natural_width(kind), natural_height(kind))
    entry = edits.entries.get(entry_key(village, p), {}) if own else {}
    s = 1.0 if unscaled else shrink
    return entry.get("w", gw) * s, entry.get("h", gh) * s


def keep_aspect(now: tuple[float, float], axis: int, value: float) -> tuple[float, float]:
    """`now` (width, height) with side `axis` (0 width, 1 height) made `value` and the other side
    following, so the shape keeps its proportions (Keep aspect ratio); the other side within
    FRAME_MIN..FRAME_MAX, rounded to a tenth."""
    w, h = now
    if w <= 0 or h <= 0:
        return (value, h) if axis == 0 else (w, value)
    # The proportions always kept: when the side that follows would pass a limit, it stops there and the
    # typed side gives way (the owner's "800" typed into a turtle shell's box: its "8" made it 8 by 8
    # before, a square for good).
    ratio = (h / w) if axis == 0 else (w / h)
    other = value * ratio
    if other < FRAME_MIN or other > FRAME_MAX:
        other = max(FRAME_MIN, min(FRAME_MAX, other))
        value = max(FRAME_MIN, min(FRAME_MAX, other / ratio))
    value, other = round(value, 1), round(other, 1)
    return (value, other) if axis == 0 else (other, value)


def page_spans(edits: Edits, village: gen.Village) -> list[tuple[int, int]]:
    """Each page's first and last generation (the generations as arrange gives them).  A page ends
    with the generation the next one starts at, and that page shows it again as its founders (the
    owner: "page 1 has generations 1-6.  The second page should have generations 6-12, with the 6th
    generation on the second page being treated as "founders" on the second page")."""
    # (a page laid out with generations of its own keeps the tree's pages: page_village)
    gens = getattr(village, "span_generations", None) or sorted({p.generation for p in village.people.values()}) or [1]
    starts = [gens[0]] + sorted({g for g in edits.pages if g in gens and g > gens[0]})   # Codex, #557
    spans = [(lo, starts[k + 1] if k + 1 < len(starts) else gens[-1]) for k, lo in enumerate(starts)]
    # No page holds more than the player's number of generations (the owner, 2026-10-08: 6 until they
    # say, 10 at most, so every page stays legible): a longer span goes on over the next pages, each
    # starting with the generation the one before ends with.
    most = edits.page_generations
    out = []
    for lo, hi in spans:
        while hi - lo + 1 > most:
            out.append((lo, lo + most - 1))
            lo += most - 1
        out.append((lo, hi))
    return out


def layout(village: gen.Village, edits: Edits | None = None, page: int = 0) -> Layout:
    """The page laid out.  With Shrink to fit (Edits.fit_width), the portraits shrink until the whole
    page -- the generation labels, the widest row and the Other Members -- fits that width, or until
    they are as small as they go (SHRINK_MIN)."""
    if edits is not None:
        settle_shapes(edits, village)           # saved before a shape was drawn turned: moved on once
        village = page_village(edits, village, page)    # (before the view: it names the page by the tree's)
        edits = page_view(edits, village, page)     # this page's own things laid over the tree's
    lay = _layout(village, edits, page)
    e = lay.edits
    if not e.fit_width:
        return lay
    for _ in range(8):
        if lay.width <= e.fit_width * 1.005 or lay.shrink <= SHRINK_MIN:
            break
        # What does not shrink (the labels' column and the margins) is left as it is.
        fixed = LEFT + 60
        wanted = lay.shrink * max(0.05, (e.fit_width - fixed) / max(1.0, lay.width - fixed))
        lay = _layout(village, edits, page, max(SHRINK_MIN, min(1.0, wanted)))
    return lay


def _page_members(village: gen.Village, edits: Edits, page: int) -> tuple:
    """Who is on a page of the tree and its families: (page, spans, off, families, in_tree, others, onward).
    `onward`: the families whose parents are on this page and whose children are all on a later page (the
    page's last generation is the next page's founders) -- drawn here as far as the page allows."""
    people = village.people
    gone = {pid for pid, p in people.items()
            if edits.entries.get(entry_key(village, p), {}).get("hidden")}
    spans = page_spans(edits, village)
    page = max(0, min(page, len(spans) - 1))
    first, last = spans[page]
    off = {pid for pid, p in people.items() if not first <= p.generation <= last}     # on another page
    fam_of: dict[tuple, Family] = {}
    for p in sorted(people.values(), key=lambda q: (q.generation, q.upcoming, -(q.age or 0), q.id)):
        if p.father is None and p.mother is None or p.id in gone:
            continue
        key = (p.father, p.mother)
        if key not in fam_of:
            fam_of[key] = Family(len(fam_of) + 1, p.father, p.mother, [])
        fam_of[key].children.append(p.id)
    # A spouse no child links to their partner (one who died before any child, or was divorced): a couple's line
    # of its own, so they read as the spouse.
    for p in sorted(people.values(), key=lambda q: q.id):
        q = people.get(getattr(p, "partner", None)) if getattr(p, "partner", None) is not None else None
        if q is None or p.id in gone or q.id in gone or any({p.id, q.id} == {f.father, f.mother} for f in fam_of.values()):
            continue
        father, mother = (p.id, q.id) if p.sex == "Male" and q.sex != "Male" or q.sex == "Female" and p.sex != "Female" \
            else (q.id, p.id)
        fam_of[(father, mother)] = Family(len(fam_of) + 1, father, mother, [])
    families = list(fam_of.values())
    in_tree = set()
    for fam in families:
        in_tree.update(fam.children)
        in_tree.update(q for q in (fam.father, fam.mother) if q is not None)
    in_tree -= gone
    others = sorted((pid for pid in people if pid not in in_tree and pid not in gone and pid not in off),
                    key=lambda q: (people[q].generation, _place(people[q])))
    onward: list[Family] = []
    if off:                             # one page of a longer tree: its own generations, not joined to others
        in_tree -= off
        for fam in families:
            kids = [c for c in fam.children if c not in off]
            later = [c for c in fam.children if c in off and people[c].generation > last]
            here = [q for q in (fam.father, fam.mother) if q in in_tree]
            if later and not kids and here:
                # Its children are on a later page: the page that shows both a parent and the children.
                to = next((k for k, (lo, hi) in enumerate(spans) if k > page
                           and any(lo <= people[q].generation <= hi for q in here)
                           and all(lo <= people[c].generation <= hi for c in later)), None)
                if to is not None:
                    onward.append(Family(fam.id, fam.father, fam.mother, [], onward=later, onward_page=to + 1))
            fam.children = kids
        families = [f for f in families if f.children and any(q in in_tree for q in (f.father, f.mother))]
    return page, spans, off, families, in_tree, others, onward


def _page_colours(village: gen.Village, edits: Edits, page: int) -> dict[str, str]:
    """Each family's colour on a page, by its family_key, worked out as _layout does (without laying it out)."""
    people = village.people
    _page, _spans, off, families, in_tree, others, _onward = _page_members(village, edits, page)
    shown = in_tree | set(others)
    alone = [q for q in shown if all(r is None or r in off for r in (people[q].father, people[q].mother))]
    pool = iter(distinct_colours(len(alone) + len(families), edits.background or BACKGROUND))
    for _q in alone:
        next(pool)
    return {family_key(village, f): edits.family_colours.get(family_key(village, f), next(pool)) for f in families}


def _layout(village: gen.Village, edits: Edits | None = None, page: int = 0,
            shrink: float | None = None) -> Layout:
    people = village.people
    page, spans, off, families, in_tree, others, onward = _page_members(village, edits or Edits(), page)
    # Each row in age order, oldest on the left (the owner: "oldest on the left, youngest on the
    # right"), numbered so (vf1_genealogy.number_people).
    rows: dict[int, list[int]] = {}
    for pid in sorted(in_tree, key=lambda q: (people[q].generation, _place(people[q]))):
        rows.setdefault(people[pid].generation, []).append(pid)
    edits = edits or Edits()
    # Every portrait shrunk alike, faces and words with them, so the widest row fits the page width
    # the player chose (the owner, 2026-10-08: "auto resizing of portraits and text to accommodate
    # lots of portraits per page"); the gap between two portraits is the player's.
    shrink_now = 1.0
    shown = in_tree | set(others)
    # A shape drawn turned (SHAPE_BAKES) spaced by its traced box, as before it was (the owner's trees keep their
    # look); its drawing's real reach is measured as drawn (outline, drawn_reach), so none overlap.
    widest_frame = max([NODE_W] + [own_box(shape_of(edits, village, people[q]),
                                           *frame_size(edits, village, people[q], own=False))[0] for q in shown])
    # The Packed layouts close the player's gaps as the packing nears 100 (squeeze): touching there.
    tight = squeeze(edits)
    gap = edits.portrait_gap * (1 - tight)
    if edits.positioning in PACKED:
        # Never so near that two portraits' drawings overlap: their borders' strokes (and a special
        # border's leaves, a mark) at least meet (frame_pad).
        gap = max(gap, 2 * max([0.0] + [frame_pad(edits, edits.entries.get(entry_key(village, people[q]), {}),
                                                  group_of(people[q]), *own_box(shape_of(edits, village, people[q]),
                                                                                   *frame_size(edits, village, people[q])))
                                        for q in shown]))
    subgap = SUBGAP * (1 - tight)
    widest_row_n = max([len(r) for r in rows.values()] + [1])
    if shrink is not None:
        shrink_now = shrink
    elif edits.fit_width and LEFT + widest_row_n * (widest_frame + gap) > edits.fit_width:
        room = (edits.fit_width - LEFT) / widest_row_n - gap
        shrink_now = max(SHRINK_MIN, min(1.0, room / widest_frame))
    step = widest_frame * shrink_now + gap

    def outline(q: int) -> tuple:
        """q's frame's outline, column by column (_profile), as drawn."""
        p = people[q]
        entry = edits.entries.get(entry_key(village, p), {})
        kind = flipped_kind(shape_of(edits, village, p), entry.get("flip_h", False), entry.get("flip_v", False))
        w, h = frame_size(edits, village, p, shrink=shrink_now)
        words = None
        if is_fixed(edits, p) and not p.upcoming:
            # Faces and words at one size: they may reach past a short frame -- counted as drawn.
            top, bottom = fixed_words_reach(probe, p, w, h)
            words = (-w / 2, w / 2, top, bottom)
        return _profile(kind, w, h, entry.get("angle", 0.0), frame_pad(edits, entry, group_of(p), *own_box(kind, w, h)), words)

    # (A layout with no places yet, for measuring portraits' words as they will be drawn.)
    probe = Layout(village, rows, {}, {}, [], [], 0.0, 0.0, 0.0, edits=edits, shrink=shrink_now,
                   names=gen.duplicate_names(village, edits.number_order) if edits.number_names else {})

    # The Packed layouts' family blocks: short rows, plain or each second row set along into the dips
    # of the one above, whichever takes less room; rows as close as the frames' outlines let them.
    block_shape = functools.partial(_arrange, step=step, offset=brick(edits) * step / 2, rowh=NODE_H + subgap,
                                    tight=tight, outline=outline, align=edits.row_align, gap=gap,
                                    nest=edits.packing >= NEST)
    x: dict[int, float] = {}
    sub: dict[int, int] = {q: 0 for q in in_tree}
    cl = None
    if edits.positioning == "packed_families" and rows:
        cl = _clusters(people, in_tree, families, step, gap, edits, block_shape)
        x = dict(cl.x)
        tree_right = max(x.values()) + NODE_W / 2 + max(NODE_W, step - gap) / 2
    elif edits.positioning in ("dynamic", "packed_generations") and rows:
        if edits.positioning == "packed_generations":   # each family a block of short rows, packed like bricks
            # Edits.packing: how many in a family's row, how wide a band may grow before its families
            # step down into its further rows (none at 0; a 16:9 page at 100) and how soon they step down.
            packing = edits.packing / 100
            # (page_room, never page: that is the page of the tree shown, and the window indexes by it)
            page_room = math.sqrt(len(in_tree) * step * (NODE_H + subgap) * 1.6 * 16 / 9)
            cap = page_room * (1 + 2 * (1 - packing)) if packing else math.inf
            best = None
            # The family row width (within what the packing allows) that makes the smallest tree near a
            # pleasing page shape -- unless the player set their own.
            for limit in _limits(edits):
                tx, tsub = _dynamic(people, rows, families, step,
                                    blocks=(limit, edits.row_align, gap, cap, SUB_COST * (1 - 0.75 * packing),
                                            CORRIDOR * (1 - tight), block_shape))
                width = max(tx.values()) - min(tx.values()) + step
                height = sum((max((tsub[q] for q in row), default=0) + 1) * (NODE_H + subgap) for row in rows.values())
                score = _page_score(width, height + len(rows) * (NODE_H / 2) * (1 - tight))
                if best is None or score < best[0]:
                    best = (score, tx, tsub)
            _score, x, sub = best
        else:
            x, sub = _dynamic(people, rows, families, step)
        # The right edge of the widest frame, not of a standard portrait: a wide shape (a butterfly) or
        # a big frame must not reach into the Other Members column.
        tree_right = max(x.values()) + NODE_W / 2 + max(NODE_W, step - gap) / 2
    else:
        # Every row centred under the widest (the owner: "center everything ... both
        # horizontally and vertically").
        widest_row = max((len(row) for row in rows.values()), default=1)
        for row in rows.values():
            indent = (widest_row - len(row)) * step / 2
            for i, pid in enumerate(row):
                x[pid] = LEFT + indent + i * step
        tree_right = LEFT + widest_row * step - gap
    if edits.row_limit and rows and edits.positioning in ("dynamic", "rows"):
        # (The two Packed layouts wrap each family on its own, inside its cluster.)
        x, sub = _wrap_rows(people, rows, x, sub, edits.row_limit, edits.keep_families, step,
                            keep_fitting=edits.positioning == "dynamic")
        tree_right = max(x.values()) + NODE_W / 2 + max(NODE_W, step - gap) / 2
    if edits.row_align != "arranged" and rows and cl is None:
        # (Packed families have no rows across the tree: there each family's rows are lined up
        # inside its own cluster.)
        # Each row to the tree's left edge, its middle or its right edge (Edits.row_align); the player's
        # drags still count from there.
        left_edge = min(x[q] for row in rows.values() for q in row)
        right_edge = max(x[q] for row in rows.values() for q in row)
        for row in rows.values():
            lo, hi = min(x[q] for q in row), max(x[q] for q in row)
            shift = (left_edge - lo if edits.row_align == "left" else right_edge - hi if edits.row_align == "right"
                     else (left_edge + right_edge) / 2 - (lo + hi) / 2)
            for q in row:
                x[q] += shift
    # The Other Members: each generation's in a row of its own (Edits.others_columns 1, as always), or in a
    # grid that many across, a generation at a time; on the right of the tree, or down its left edge
    # (Edits.others_side), the tree and its generation labels then moved right to make room.
    columns = edits.others_columns
    by_gen: dict[int, list[int]] = {}
    for pid in others:
        by_gen.setdefault(people[pid].generation, []).append(pid)
    grid_row: dict[int, int] = {}
    grid_rows: dict[int, int] = {}
    widest = 0
    for g, qs in by_gen.items():
        for i, q in enumerate(qs):
            grid_row[q] = 0 if columns <= 1 else i // columns
        grid_rows[g] = 1 if columns <= 1 else -(-len(qs) // columns)
        widest = max(widest, len(qs) if columns <= 1 else min(columns, len(qs)))
    label_left = 0.0
    move = 0.0
    if others and edits.others_side == "left":
        others_left = float(LEFT - 260)
        label_left = others_left + widest * step - gap + 28     # the labels' plate 40 past the grid
        # (Packed families has no label column: the tree starts just past the grid.)
        move = widest * step - gap + OTHER_GAP / 2 if cl is not None else label_left
        label_left = 0.0 if cl is not None else label_left
        for q in x:
            x[q] += move
        tree_right += move
    else:
        others_left = tree_right + OTHER_GAP
    for g, qs in by_gen.items():
        for i, q in enumerate(qs):
            x[q] = others_left + (i if columns <= 1 else i % columns) * step
    width = (others_left + widest * step + 40) if others and edits.others_side != "left" else tree_right + 60
    # Where the player dragged villagers.
    shifts = {q: edits.entries.get(entry_key(village, people[q]), {}) for q in x}
    for q, entry in shifts.items():
        x[q] = max(MARGIN, x[q] + entry.get("dx", 0.0))
    width = max([width] + [x[q] + NODE_W + 40 for q in x])
    # The page holds all of every portrait: a frame wider than a portrait's place (a butterfly's wings),
    # whatever it draws beside its outline, its border's stroke, a special border, a mark or a glow, and
    # its words' place -- nowhere nearer the page's edge than PAGE_MARGIN.  A tree that would reach past
    # the left edge moves right, its Other Members and labels with it.
    reach = {q: drawn_reach(edits, village, people[q], outline(q)) for q in x}
    left_most = min([x[q] + NODE_W / 2 - reach[q][0] for q in x], default=PAGE_MARGIN)
    if left_most < PAGE_MARGIN:
        nudge = PAGE_MARGIN - left_most
        for q in x:
            x[q] += nudge
        others_left += nudge
        if label_left or (others and edits.others_side == "left"):
            label_left += nudge
        move += nudge
    width = max([width] + [x[q] + NODE_W / 2 + reach[q][1] + PAGE_MARGIN for q in x])
    # The generation labels' column as wide as its widest label (label_box: a long line, a large font):
    # the tree -- and the Other Members on its right -- moved right by as much as a plate is wider than
    # the usual 228, so no label runs into a portrait.  (Packed families draws no labels.)
    labels = label_boxes(village, edits, x) if cl is None else {}
    wider = max([0.0] + [b.width - LABEL_PLATE_W for b in labels.values()])
    if wider:
        on_left = set(others) if edits.others_side == "left" else set()
        for q in x:
            if q not in on_left:
                x[q] += wider
        if others and edits.others_side != "left":
            others_left += wider
        width += wider
    # One lane per family (the owner: "spread the lines connecting parents to children a bit more
    # vertically"): every family whose children are in a row has a line of its own between that
    # row and the one above, shared only with families whose lines do not overlap it; the gap
    # between the rows is as tall as its lanes need.
    _drops(people, families, x)
    lanes = _cluster_lanes(cl) if cl is not None else _lanes(people, families, x)
    _order_lanes(people, families, x, lanes)
    gens = sorted({people[q].generation for q in x})
    grid_gap = gap                      # between two rows of an Other Members grid
    bands = {g: NODE_H + max((sub[q] for q in x if q in sub and people[q].generation == g), default=0)
             * (NODE_H + SUBGAP) for g in gens}
    # Packed generations: each band's rows as close under each other as the packing and the frames'
    # outlines let them (Packed families works its rows out block by block, in _clusters).
    sub_top: dict[int, list[float]] = {}
    if edits.positioning == "packed_generations" and (tight or brick(edits)):
        for g in gens:
            members = [q for q in in_tree if people[q].generation == g]
            deep = max((sub.get(q, 0) for q in members), default=0)
            tops_g = [0.0]
            subrows = [[(x[q] + NODE_W / 2, outline(q)) for q in members if sub.get(q, 0) == k]
                       for k in range(deep + 1)]
            for k in range(1, deep + 1):
                need = _pitch(subrows[k - 1], subrows[k], edits.packing >= NEST)
                rowh = NODE_H + subgap
                top_k = tops_g[-1] + (need if need >= rowh else rowh - tight * (rowh - need))
                # Never into a row further up either (a row nestled into the dips of the one above
                # stands under the row above that: a diamond under a diamond).
                for j in range(k - 1):
                    top_k = max(top_k, tops_g[j] + _pitch(subrows[j], subrows[k], edits.packing >= NEST))
                tops_g.append(top_k)
            sub_top[g] = tops_g
            bands[g] = tops_g[-1] + NODE_H
    if columns > 1:                     # a generation's band is as tall as its Other Members' grid
        for g, n in grid_rows.items():
            bands[g] = max(bands[g], n * NODE_H + (n - 1) * grid_gap)
    # A generation's band at least as tall as its label (label_box), from where the label starts -- the
    # top of its tallest frame, which stands in the middle of its place -- so a label of many lines or a
    # large font never reaches the next generation's label or portraits.
    for g, box in labels.items():
        tallest = max([frame_size(edits, village, people[q], shrink=shrink_now)[1]
                       for q in in_tree if people[q].generation == g], default=NODE_H)
        bands[g] = max(bands[g], max(0.0, (NODE_H - tallest) / 2) + box.bottom)
    tops: dict[int, float] = {}
    others_top: dict[int, float] = {}   # Packed families: where each generation's Other Members start
    row_keys: dict[int, tuple] = {}
    if cl is not None:
        # No generation rows.  A generation's top, where its label and its Other Members go: its highest
        # portraits that are under the generation before's top -- when it has none there, just under it.
        # The Other Members also start under the generation before's.
        gap_tops = cl.gap_top
        row_y = {q: cl.y[q] for q in in_tree}
        below, end = None, float(TOP)
        for g in gens:
            levels = sorted({row_y[q] for q in in_tree if people[q].generation == g})
            level = next((h for h in levels if below is None or h >= below), None)
            if level is None:
                level = float(TOP) if below is None else below + 10
            tops[g] = level
            below = level + NODE_H
            if g in grid_rows:
                others_top[g] = max(level, end)
                end = others_top[g] + grid_rows[g] * (NODE_H + grid_gap)
            bands[g] = NODE_H
        for q in in_tree:
            row_keys[q] = ("cluster", round(row_y[q]))
    else:
        top = float(TOP)
        for k, g in enumerate(gens):
            if k:
                couples = lanes.couple_count.get(g, 0)
                # The room under the row above is the player's (Edits.row_gap: "vertical portrait clustering").
                # (Packed generations closes it as the packing nears 100: the lines go behind there.)
                top += bands[gens[k - 1]] + (1 - tight) * (
                    edits.row_gap + couples * LANE + (BAND_GAP if couples else 0)
                    + max(1, lanes.count.get(g, 0)) * LANE + LANE_BOTTOM)
                if sub_top:
                    # Never so near that the band's first row runs into the last row of the band above (a
                    # butterfly's feelers reach up above its frame, a mark round it).
                    # Every row of the band above against every row of this one (not only the last and the
                    # first: a nestled row may reach past the row before it).
                    prev = gens[k - 1]

                    def band_rows(gg):
                        return [[(x[q] + NODE_W / 2, outline(q)) for q in in_tree
                                 if people[q].generation == gg and sub.get(q, 0) == j]
                                for j in range(len(sub_top[gg]))]
                    rows_above, rows_here = band_rows(prev), band_rows(g)
                    for j, upper in enumerate(rows_above):
                        for i, lower in enumerate(rows_here):
                            if upper and lower:
                                top = max(top, tops[prev] + sub_top[prev][j] - sub_top[g][i]
                                          + _pitch(upper, lower, edits.packing >= NEST))
            tops[g] = top
        gap_tops = tops
        row_y = {pid: tops[people[pid].generation] + (sub_top[people[pid].generation][sub.get(pid, 0)]
                                                      if sub_top else sub.get(pid, 0) * (NODE_H + SUBGAP))
                 for pid in in_tree}
    for q in others:
        row_y[q] = others_top.get(people[q].generation, tops[people[q].generation]) + grid_row[q] * (NODE_H + grid_gap)
        if columns > 1:
            row_keys[q] = ("others", people[q].generation, grid_row[q])
    for fam in families:
        g = lanes.row.get(fam.id)
        if g is None:
            continue
        kids_band = lanes.count[g] * LANE
        k = 1 - tight                       # the lanes close up with the room for them (Packed layouts)
        fam.lane_y = gap_tops[g] - k * (LANE_BOTTOM + (lanes.count[g] - lanes.index[fam.id]) * LANE - LANE / 2)
        if fam.id in lanes.couple_index:
            fam.couple_y = gap_tops[g] - k * (LANE_BOTTOM + kids_band + BAND_GAP
                                              + (lanes.couple_count[g] - lanes.couple_index[fam.id]) * LANE - LANE / 2)
            if cl is not None and fam.id in cl.couple_y:    # Packed families: just under the parents
                fam.couple_y = cl.couple_y[fam.id]
    # Dragged up, never so far that anything the portrait draws (a frame taller than its place, a special
    # border, a mark or a glow) goes nearer the page's top than PAGE_MARGIN.
    y = {pid: max(MARGIN, PAGE_MARGIN - reach[pid][2], row_y[pid] + shifts[pid].get("dy", 0.0)) for pid in x}
    # A family's lines go with its children when they are dragged up or down (the owner: "so they're
    # neat and not overlapping when moved to a new position").
    for fam in families:
        kids = [c for c in fam.children if c in y and c not in fam.away]
        if kids and fam.lane_y:
            fam.lane_y += min(y[c] for c in kids) - min(row_y[c] for c in kids)
            parents = [q for q in (fam.father, fam.mother) if q in y and q not in fam.far]
            if fam.couple_y and parents:        # just under the parents, above the children's line
                lift = max(y[q] - row_y[q] for q in parents)
                fam.couple_y = min(fam.couple_y + lift, fam.lane_y - LANE)
    lower: dict[int, int] = {}                  # the childless couples so far under each family member
    for fam in families:
        # A couple with no child: their line just under them, from the middle of each, each such couple of one
        # family member a lane lower than the one before, so two lost spouses' lines never lie on each other.
        parents = [q for q in (fam.father, fam.mother) if q in y]
        if not fam.children and len(parents) == 2:
            k = max(lower.get(q, 0) for q in parents)
            for q in parents:
                lower[q] = k + 1
            fam.couple_y = max(y[q] for q in parents) + NODE_H + LANE * (1 + k)
            fam.drops = {q: x[q] + NODE_W / 2 for q in parents}
    if cl is not None:
        # Packed families: each family's line from its parents takes the way kept for it, unless the
        # player moved one of them (then the lines find their own way, as always).
        for fam in families:
            mine = [q for q in (fam.father, fam.mother, *fam.children) if q in shifts]
            if fam.id in cl.ways and not any(shifts[q].get("dx") or shifts[q].get("dy") for q in mine):
                fam.way = [(px + move, py) for px, py in cl.ways[fam.id]]
    onward = _place_onward(people, onward, x, y, in_tree, families, edits, village)
    height = tops[gens[-1]] + bands[gens[-1]] + 190 if gens else TOP + NODE_H + 190
    height = max([height] + [y[q] + NODE_H + 190 for q in y] + [y[q] + reach[q][3] + FOOTER_ROOM + PAGE_MARGIN for q in y]
                 + [f.lane_y + ONWARD_TEXT + FOOTER_ROOM + PAGE_MARGIN for f in onward])
    families = families + onward
    out = Layout(village, rows, x, y, families, others, others_left, width, height, tops=tops, bands=bands, shrink=shrink_now,
                 edits=edits, page=page, pages=len(spans), label_left=label_left, row_keys=row_keys,
                 subs={q: sub.get(q, 0) for q in in_tree},
                 names=gen.duplicate_names(village, edits.number_order) if edits.number_names else {})
    # One colour each: every villager with no recorded parents, every pairing, every set of full
    # brothers and sisters -- oldest first, so the most distinct go to the founders.
    e = out.edits
    alone = sorted((q for q in x if all(r is None or r in off for r in (people[q].father, people[q].mother))),
                   key=lambda q: (people[q].generation, _place(people[q])))   # a later page's founders too
    own = [f for f in families if not f.onward]
    pool = iter(distinct_colours(len(alone) + len(own), out.background))
    for q in alone:
        out.birth_colour[q] = e.person_colours.get(entry_key(village, people[q]), next(pool))
    for fam in own:
        fam.colour = e.family_colours.get(family_key(village, fam), next(pool))
        for c in fam.children:
            out.birth_colour[c] = fam.colour
    later: dict[int, dict] = {}
    for fam in onward:                  # the colour the family has on the page its children are on
        if fam.onward_page not in later:
            later[fam.onward_page] = _page_colours(village, e, fam.onward_page - 1)
        fam.colour = later[fam.onward_page].get(family_key(village, fam), GREY)
    _settle_onward(out)
    return out


ONWARD_PIECE = "onward "        # before the name of each line piece drawn above a page break (lines())
ONWARD_SIZE = 12              # the "continued on page N" words' size (before their role's scale)
ONWARD_ROW = 20                 # between two rows of those words, where they would run into each other
ONWARD_TEXT = 40                # the room under a family's line for its words
ONWARD_GAP = 4                  # from the end of a family's line down to the top of its words
ONWARD_CLEAR = 8                # the least room beside a family's words: other words, another family's line


def onward_key(village: gen.Village, fam: Family) -> str:
    """The name of a family's "continued on page N" words: what moves, hides and retypes those words alone."""
    return f"onward:{family_key(village, fam)}"


def onward_words(edits: Edits, village: gen.Village, fam: Family) -> str:
    """The words under a family whose children are on a later page: the player's for these words, else the
    player's for every such family's, else the tree's own -- "{page}" in them the page's number."""
    text = edits.words.get(onward_key(village, fam)) or edits.words.get("onward") or WORDS["onward"]
    return text.replace("{page}", str(fam.onward_page))


def onward_width(edits: Edits, village: gen.Village, fam: Family) -> float:
    """How wide the family's words are drawn, in their role's look."""
    style = edits.styles.get("onward", {})
    size = ONWARD_SIZE * style.get("scale", 100) / 100
    text = onward_words(edits, village, fam)
    # (Never less than the page's own reckoning of words' width, _extent, so the page is sized round them.)
    return max(text_width(text, size, style.get("bold", False), style.get("font") or edits.font or None,
                          style.get("italic", False)), len(text) * size * 0.55)


def _stagger_onward(fams: list[Family], span: dict, halves: dict, pitch: float, start: float, backwards: bool,
                    prefer: tuple, last_resort: bool = False):
    """Rows for the words of the families whose children are on a later page when they will not all stand
    centred under their own lines: {family id: (line x, line's lowest y, words' centre less line x)}.  Each
    family in turn (from the right or the left) takes the highest row, and a place along its stretch, where
    its line goes down clear of the words above, its words (centred under the line, or running out to the
    , in that order: 0, 1, -1) clear of the words in their row and of every line
    going lower.  None if some family finds no place (last_resort: it is put in a row of its own)."""
    out: dict = {}
    words: list[tuple[float, float, int]] = []
    downs: list[tuple[float, int]] = []
    inset = 6
    order = sorted(fams, key=lambda f: (span[f.id][1], span[f.id][0], f.id), reverse=backwards)
    for f in order:
        lo, hi = span[f.id]
        tw = halves[f.id]
        mid = (lo + hi) / 2
        found = None
        for row in range(len(fams) + 1):
            above = [(a - 2, b + 2) for a, b, r in words if r < row]
            xs = [mid] + [b for _a, b in above] + [a for a, _b in above] + [lo, hi]
            xs = sorted({x for x in xs if lo <= x <= hi and not any(a < x < b for a, b in above)},
                        key=lambda x: (abs(x - mid), x))
            for x in xs:
                for side in prefer:
                    # (0: centred; 1, -1: running out to the right or left with the line at the words' end;
                    # 2, -2: beside the line's end, for lines that fall at the very same place)
                    dx = (0 if not side else (1 if side > 0 else -1) * (max(tw - inset, 0) if abs(side) == 1 else tw + 4))
                    a, b = x + dx - tw, x + dx + tw
                    if any(a < rb + ONWARD_CLEAR and ra - ONWARD_CLEAR < b for ra, rb, r in words if r == row):
                        continue
                    if any(a - 16 < d < b + 16 for d, r in downs if r > row):
                        continue
                    found = (x, row, dx, a, b)
                    break
                if found:
                    break
            if found:
                break
        if found is None:
            if not last_resort:
                return None
            found = ((lo + hi) / 2, len(fams) + 1, 0.0, mid - tw, mid + tw)
        x, row, dx, a, b = found
        words.append((a, b, row))
        downs.append((x, row))
        out[f.id] = (x, start + row * pitch, dx)
    return out


def _spread_drops(taken: list[float], n: int, centre: float, reach: float) -> list[float]:
    """n places along a portrait's bottom (centre +- reach), spread evenly across it and clear of the places
    already taken by at least 3 px (down to 1.5 where it is crowded), each line leaving the portrait itself."""
    ideals = [centre] if n == 1 else [centre - reach + 2 * reach * i / (n - 1) for i in range(n)]
    for gap in (3.0, 2.0, 1.5):
        steps = int(2 * reach / 0.5) + 1
        free = [centre - reach + 0.5 * i for i in range(steps)]
        free = [p for p in free if all(abs(p - t) >= gap for t in taken)]
        chosen: list[float] = []
        for want in ideals:
            ok = [p for p in free if all(abs(p - c) >= gap for c in chosen)]
            if not ok:
                break
            chosen.append(min(ok, key=lambda p: (abs(p - want), p)))
        if len(chosen) == n:
            return chosen
    return [min(max(want, centre - reach), centre + reach) for want in ideals]


def _place_onward(people: dict, onward: list[Family], x: dict, y: dict, in_tree: set, families: list[Family],
                  edits: Edits, village: gen.Village) -> list[Family]:
    """Where the lines go for the families whose children are on a later page (_page_members), nothing else
    moved: each parent's line leaves at a point of its own along their frame's bottom (past the points their
    other families' lines take), each couple has a level of its own under the lowest row at or below the
    parents, and from the couple's line (a lone parent: from them) one line goes down to the words saying
    which page the children are on, the words centred under it.  Where along the couple's line it goes down
    is chosen so every family's words stand under their own line in one row, side by side (the owner: no
    "stacked cluster"); only those that cannot go a row lower, never on another's words or line."""
    fams = [f for f in onward if any(q is not None and q in x and q in in_tree for q in (f.father, f.mother))]
    if not fams:
        return []
    taken: dict[int, list[float]] = {}
    for f in families:
        for q, at in f.drops.items():
            taken.setdefault(q, []).append(at)

    def here(f: Family) -> list[int]:
        return [q for q in (f.father, f.mother) if q is not None and q in x and q in in_tree]
    fams.sort(key=lambda f: (sum(x[q] for q in here(f)) / len(here(f)), f.id))
    by_parent: dict[int, list[Family]] = {}
    for f in fams:
        for q in here(f):
            by_parent.setdefault(q, []).append(f)
    for q, group in by_parent.items():
        mine = taken.setdefault(q, [])
        centre = x[q] + NODE_W / 2
        reach = NODE_W / 2 - 16             # every line leaves from the portrait's own bottom, never past its sides
        trial, got = list(mine), []
        for _f in group:
            at = centre if not trial else max(trial) + 16
            if at > centre + reach:
                at = min(trial) - 16
            trial.append(at)
            got.append(at)
        if any(abs(at - centre) > reach + 1e-6 for at in got):
            got = _spread_drops(mine, len(group), centre, reach)     # so many lines: set closer, all on the portrait
        for f, at in zip(group, got):
            mine.append(at)
            f.drops[q] = at
    couples = [f for f in fams if len(here(f)) == 2]
    couples.sort(key=lambda f: (min(f.drops.values()), f.id))
    lowest: dict[int, float] = {}
    for f in fams:
        g = max(people[q].generation for q in here(f))
        if g not in lowest:
            lowest[g] = max(y[q] + NODE_H for q in in_tree if q in y and people[q].generation >= g)
    base = {f.id: lowest[max(people[q].generation for q in here(f))] for f in fams}
    for k, f in enumerate(couples):
        f.couple_y = base[f.id] + LANE_TOP + k * LANE
    start = max(base.values()) + LANE_TOP + len(couples) * LANE + LANE
    # (Rows of words stand far enough apart for the words, at whatever size the player has given them.)
    pitch = max(ONWARD_ROW, ONWARD_SIZE * edits.styles.get("onward", {}).get("scale", 100) / 100 * 1.5)
    # Each family's line down may leave its couple's line anywhere along it, 12 in from its ends (a lone
    # parent's: where it leaves them).  Families taken by where that stretch ends, each put in the highest row
    # and as near its stretch's middle as it can be with its words clear of the words already in that row, its
    # line clear of the words in the rows above and its words clear of the lines going on to rows below.
    span = {}
    for f in fams:
        ds = sorted(f.drops.values())
        lo, hi = (ds[0] + 12, ds[-1] - 12) if len(ds) == 2 and ds[-1] - ds[0] > 24 else (sum(ds) / len(ds),) * 2
        span[f.id] = (lo, hi)
    half = {f.id: onward_width(edits, village, f) / 2 + ONWARD_CLEAR for f in fams}
    words: list[tuple[float, float, int]] = []     # (left, right, row) of the words placed
    downs: list[tuple[float, int]] = []            # (x, row) of the lines down to them
    failed = False
    for f in sorted(fams, key=lambda f: (span[f.id][1], span[f.id][0], f.id)):
        lo, hi = span[f.id]
        w = half[f.id]
        placed = None
        for row in range(len(fams) + 1):
            # The places along the stretch where the line down is clear of the words above, and the words
            # clear of the words in this row and of the lines going lower: nearest the middle first.
            blocked = [(a - 2, b + 2) for a, b, r in words if r < row] \
                + [(a - w, b + w) for a, b, r in words if r == row] \
                + [(d - w - ONWARD_CLEAR, d + w + ONWARD_CLEAR) for d, r in downs if r > row]
            mid = (lo + hi) / 2
            options = [mid] + [b for _a, b in blocked] + [a for a, _b in blocked] + [lo, hi]
            free = [c for c in options if lo <= c <= hi and not any(a < c < b for a, b in blocked)]
            if free:
                placed = (min(free, key=lambda c: (abs(c - mid), c)), row)
                break
        if placed is None:              # (the words are too crowded to stand centred under their lines)
            failed = True
            break
        at, row = placed
        words.append((at - w + ONWARD_CLEAR, at + w - ONWARD_CLEAR, row))
        downs.append((at, row))
        f.stem_x = at
        f.lane_y = start + row * pitch
        f.word_dx = 0.0
    if failed:
        # Crowded labels are laid out as portraits are, each in a place of its own: a family's words may run
        # out to one side of its line (still under it), so a staircase of them stands side by side down the
        # rows without one on another or a line through any.  Tried from the right and from the left, the
        # words centred wherever they can be.
        halves = {f.id: onward_width(edits, village, f) / 2 for f in fams}
        for backwards, prefer in ((True, (0, 1, -1, 2, -2)), (False, (0, -1, 1, -2, 2)), (True, (0, 1)), (False, (0, -1)),
                                  (True, (1, 2)), (False, (-1, -2)), (True, (2,)), (False, (-2,))):
            got = _stagger_onward(fams, span, halves, pitch, start, backwards, prefer)
            if got is not None:
                break
        else:
            got = _stagger_onward(fams, span, halves, pitch, start, True, (2,), last_resort=True)
        for f in fams:
            f.stem_x, f.lane_y, f.word_dx = got[f.id]
    return fams


def _onward_ends(lay: Layout) -> dict:
    """Where each "continued on page N" family's line really ends (lines() may have turned it aside to
    keep clear of portraits), by family id."""
    mine = {f.id for f in lay.families if f.onward}
    found: dict = {}
    for _c, pts, fid, _k in lines(lay):
        if fid in mine:
            found.setdefault(fid, []).extend(pts)
    return {fid: max(pts, key=lambda pt: (pt[1], pt[0])) for fid, pts in found.items()}


def _settle_onward(lay: Layout) -> None:
    """The words saying which page a family's children are on are laid out as portraits are: none on another.
    Lines turn aside to keep clear of portraits, so where they really end is known only once they are
    drawn; if the words then meet (or run into the row below), they are laid out again from those ends
    (_stagger_onward), the words running out to one side of their lines where they must, and the lines
    lengthened to the rows they are given."""
    fams = [f for f in lay.families if f.onward]
    if len(fams) < 2:
        return
    v, e = lay.village, lay.edits
    halves = {f.id: onward_width(e, v, f) / 2 for f in fams}
    pitch = max(ONWARD_ROW, ONWARD_SIZE * e.styles.get("onward", {}).get("scale", 100) / 100 * 1.5)

    def meeting() -> dict | None:
        ends = _onward_ends(lay)
        if len(ends) < 2:
            return None
        boxes = [(f, ends[f.id][0] + f.word_dx - halves[f.id], ends[f.id][0] + f.word_dx + halves[f.id]) for f in fams
                 if f.id in ends]
        for i, (f, a, b) in enumerate(boxes):
            for g, c, d in boxes[:i]:
                if abs(f.lane_y - g.lane_y) < pitch - 1 and a < d + 4 and c < b + 4:
                    return ends
        return None
    for _round in range(3):
        ends = meeting()
        if ends is None:
            break
        start = min(f.lane_y for f in fams)
        span = {fid: (pt[0], pt[0]) for fid, pt in ends.items()}
        mine = [f for f in fams if f.id in ends]
        for backwards, prefer in ((True, (0, 1, -1, 2, -2)), (False, (0, -1, 1, -2, 2)), (True, (0, 1)), (False, (0, -1)),
                                  (True, (1, 2)), (False, (-1, -2)), (True, (2,)), (False, (-2,))):
            got = _stagger_onward(mine, span, halves, pitch, start, backwards, prefer)
            if got is not None:
                break
        else:
            got = _stagger_onward(mine, span, halves, pitch, start, True, (2,), last_resort=True)
        for f in mine:
            f.lane_y, f.word_dx = got[f.id][1], got[f.id][2]
    lay.height = max(lay.height, max(f.lane_y for f in fams) + ONWARD_TEXT + FOOTER_ROOM + PAGE_MARGIN)


def _wrap_rows(people: dict, rows: dict[int, list[int]], x: dict[int, float], sub: dict[int, int], limit: int,
               keep_families: bool, step: float, keep_fitting: bool = False) -> tuple[dict[int, float], dict[int, int]]:
    """Every generation at most `limit` portraits side by side (Edits.row_limit), the rest in further rows
    under it, as they stood left to right; with keep_families, a row ends between two families -- brothers
    and sisters with the same recorded parents -- unless one family alone is longer than a row.  Each row
    is centred on the widest row actually made (never on a band `limit` portraits wide: a limit far over
    any generation would push the tree off to the right).  With keep_fitting (Families under their
    parents), a generation no longer than the limit keeps the place its families were given."""
    x, sub = dict(x), dict(sub)
    left = min(x.values())
    made: dict[int, list[list[int]]] = {}
    for g, row in rows.items():
        if keep_fitting and len(row) <= limit:
            continue
        order = sorted(row, key=lambda q: (sub.get(q, 0), x[q]))
        groups: list[list[int]] = []
        for q in order:
            parents = (people[q].father, people[q].mother)
            same = (keep_families and groups and None not in parents
                    and (people[groups[-1][-1]].father, people[groups[-1][-1]].mother) == parents)
            if same:
                groups[-1].append(q)
            else:
                groups.append([q])
        lines: list[list[int]] = [[]]
        for group in groups:
            pieces = [group[i:i + limit] for i in range(0, len(group), limit)]
            for piece in pieces:
                if lines[-1] and len(lines[-1]) + len(piece) > limit:
                    lines.append([])
                lines[-1] += piece
        made[g] = lines
    widest = min(limit, max((len(line) for lines in made.values() for line in lines), default=0))
    for lines in made.values():
        for k, line in enumerate(lines):
            indent = (widest - len(line)) * step / 2
            for i, q in enumerate(line):
                x[q], sub[q] = left + indent + i * step, k
    return x, sub


def _block_rows(atoms: list[list], limit: int, size=len) -> list[list]:
    """A family's children wrapped into rows of at most `limit` portraits (0: one row), oldest first,
    left to right and top to bottom.  An atom -- babies born together, or a family member with the partners
    beside them -- is never split: it starts a new row when it does not fit, and one longer than a row
    has a row of its own.  `size`: an atom's portraits.  Each row: the atoms in it."""
    out: list[list] = [[]]
    used = 0
    for atom in atoms:
        if limit and out[-1] and used + size(atom) > limit:
            out.append([])
            used = 0
        out[-1].append(atom)
        used += size(atom)
    return out


def _row_indent(n: int, widest: int, step: float, align: str) -> float:
    """How far in from a block's left a row of n portraits starts, in a block widest portraits across:
    centred, unless the player lines rows up on the left or the right (Edits.row_align)."""
    return 0.0 if align == "left" else (widest - n) * step if align == "right" else (widest - n) * step / 2


def _litters(people: dict, kids: list[int]) -> list[list[int]]:
    """Brothers and sisters as atoms for _block_rows: babies born together as one, each other alone."""
    atoms: list[list[int]] = []
    for q in kids:
        litter = people[q].litter
        if litter and atoms and people[atoms[-1][-1]].litter == litter:
            atoms[-1].append(q)
        else:
            atoms.append([q])
    return atoms


def _dynamic(people: dict, rows: dict[int, list[int]], families: list[Family],
             step: float, blocks: tuple | None = None) -> tuple[dict[int, float], dict[int, int]]:
    """Each family member's x and row within their generation, families placed under their parents
    (the owner's example): the founders in a row; then, generation by generation, each set of
    brothers and sisters together, as near the middle of their parents as the room allows, and a
    family member without recorded parents beside their partner.  A family that would be pushed more
    than a few places from its parents steps down into another row of its generation instead.

    With `blocks` (Packed generations: the most portraits in a family's row, the
    rows' alignment and the gap between portraits), each family is a block of short rows (_block_rows)
    and the blocks are packed like bricks, as many rows deep as the generation needs, with room
    between two blocks for a line to pass."""
    x: dict[int, float] = {}
    sub: dict[int, int] = {}
    gens = sorted(rows)
    for i, q in enumerate(rows[gens[0]]):
        x[q], sub[q] = i * step, 0
    partners: dict[int, set] = {}
    for f in families:
        if f.father is not None and f.mother is not None:
            partners.setdefault(f.father, set()).add(f.mother)
            partners.setdefault(f.mother, set()).add(f.father)

    def centre(qs) -> float | None:
        points = [x[q] + NODE_W / 2 for q in qs if q is not None and q in x]
        return sum(points) / len(points) if points else None

    born = {c for f in families for c in f.children}
    middle = centre(rows[gens[0]]) - NODE_W / 2 + step / 2     # the middle of the founders' row
    for g in gens[1:]:
        members = rows[g]
        groups: list[list] = []
        grouped: set[int] = set()
        for f in families:
            kids = [c for c in members if c in f.children]
            if kids:
                if blocks is None:
                    groups.append([centre((f.father, f.mother)), kids])
                else:
                    # In a block, a partner with no recorded parents stands beside the one they married.
                    atoms = _litters(people, kids)
                    for atom in atoms:
                        for c in list(atom):
                            atom += [r for r in sorted(partners.get(c, ())) if r in members and r not in grouped
                                     and r not in atom and r not in born and people[r].father is None
                                     and people[r].mother is None]
                            grouped.update(atom)
                    kids = [q for atom in atoms for q in atom]
                    groups.append([centre((f.father, f.mother)), kids, atoms])
                grouped.update(kids)
        groups += [[None, [q]] for q in members if q not in grouped]
        taken: list[list[tuple[float, float]]] = []     # each row's places taken, (left, right)

        def nearest(row: list, ideal: float, span: float, low: float = -math.inf,
                    high: float = math.inf) -> float | None:
            """The free place in `row` for `span` nearest `ideal`, between `low` and `high` (None: none)."""
            def fits(left: float) -> bool:
                return low <= left and left + span <= high and all(left + span <= lo or hi <= left for lo, hi in row)
            places = [ideal] + [hi for _lo, hi in row] + [lo - span for lo, _hi in row]
            return min((p for p in places if fits(p)), key=lambda p: (abs(p - ideal), p), default=None)

        def put(group: list) -> None:
            wanted, kids = group[0], group[1]
            if blocks is None:
                shape = [kids]
            else:
                atoms = group[2] if len(group) > 2 else _litters(people, kids)
                shape = [[q for atom in row for q in atom] for row in _block_rows(atoms, blocks[0])]
            across = max(len(r) for r in shape)
            pad = max(0.0, blocks[5] - blocks[2]) if blocks is not None else 0.0
            span = across * step
            if blocks is not None:      # plain rows or each second row set along, whichever is smaller
                arranged = blocks[6]([list(r) for r in shape])
                low_x = min(v[0] for v in arranged.values())
                span = max(v[0] for v in arranged.values()) - low_x + step
            if wanted is None:                  # nobody to stand near: the end of the first row
                ends = [hi for row in taken[:1] for _lo, hi in row]
                wanted = max(ends, default=0.0) + span / 2
            # The children's middle under their parents' whatever the gap and shrink (Codex, #575): at
            # the default spacing (step = NODE_W + GAP_X) this is the old wanted - (span - GAP_X) / 2.
            ideal = wanted - NODE_W / 2 - (span - step) / 2
            best = None
            deep = len(shape)
            low, high, sub_cost = -math.inf, math.inf, SUB_COST
            if blocks is not None:
                # Packed generations: every band within the width the packing allows (a block that is
                # wider on its own may overrun it), the blocks stepping down into the band's further
                # rows the sooner the tighter the packing.
                sub_cost = blocks[4]
                if span + pad <= blocks[3]:
                    low, high = middle - blocks[3] / 2, middle + blocks[3] / 2 + pad
                    ideal = min(max(ideal, low), high - span - pad)
            for k in range(min(len(taken) + 1, MAX_SUBROWS if blocks is None else len(taken) + 1)):
                busy = [s for row in taken[k:k + deep] for s in row]
                left = nearest(busy, ideal, span + pad, low, high) if busy else ideal
                if left is None:
                    continue
                cost = abs(left - ideal) / step + k * sub_cost
                if best is None or cost < best[0]:
                    best = (cost, k, left)
            _cost, k, left = best
            while len(taken) < k + deep:
                taken.append([])
            for r, line in enumerate(shape):
                if blocks is not None:
                    xs = [arranged[q][0] - low_x for q in line]
                    taken[k + r].append((left + min(xs), left + max(xs) + step + pad))
                    for q, rx in zip(line, xs):
                        x[q], sub[q] = left + rx, k + r
                    continue
                taken[k + r].append((left, left + len(line) * step + pad))
                for i, q in enumerate(line):
                    x[q], sub[q] = left + i * step, k + r

        waiting = []
        for group in sorted((gr for gr in groups if gr[0] is not None), key=lambda gr: gr[0]):
            put(group)
        for group in groups:
            if group[0] is None:
                group[0] = centre(r for q in group[1] for r in partners.get(q, ()))
                if group[0] is None:
                    waiting.append(group)
                else:
                    put(group)
        for group in waiting:
            put(group)
    shift = LEFT - min(x.values())
    return {q: v + shift for q, v in x.items()}, sub


PACKED = ("packed_families", "packed_generations")
BEHIND = 98                     # from this packing on, lines go behind the portraits, straight


def squeeze(edits: Edits) -> float:
    """How far the Packed layouts close the gaps (0 none, 1 touching): nothing up to packing 60, then
    smoothly to portraits touching at 100 (the owner: "portraits literally touching each other"), so 90
    to 99 still leave a sliver.  The player's own portrait gap and row gap give way by as much."""
    return 0.0 if edits.positioning not in PACKED else min(1.0, max(0.0, (edits.packing - 60) / 40))


def brick(edits: Edits) -> float:
    """How far each second row of a family is set along (0 none, 1 half a portrait: the owner's "more
    compact packing" of sand grains, each row in the dips of the one above), growing with the packing."""
    return 0.0 if edits.positioning not in PACKED else edits.packing / 100


def behind(edits: Edits) -> bool:
    """Whether the family lines go straight, behind the portraits (Edits.lines_behind): as the player
    ticked it, in any layout; until they do, only in a Packed layout packed so tightly (BEHIND) there is
    no room to go round."""
    if edits.lines_behind is not None:
        return edits.lines_behind
    return edits.positioning in PACKED and edits.packing >= BEHIND


def lines_behind(lay: "Layout") -> bool:
    """The family lines go straight, behind the portraits (behind())."""
    return behind(lay.edits)


_PROFILES: dict = {}


def frame_pad(edits: Edits, entry: dict, group: str, w: float, h: float) -> float:
    """How far a portrait's drawing reaches past its frame's shape: half its border's stroke; a special
    border's leaves, flowers or rope (special_border, as measured over every shape and size: the rope up
    to 0.9 of its size outside the outline, a vine's leaves and flowers up to 1.3); the player's mark, a
    second border MARK_GAP outside (a glow is a soft light, and may meet another)."""
    border = entry.get("border") or edits.borders.get(group, "thick")
    if border in SPECIAL_BORDERS:           # (in BORDER_WIDTHS too, at 0: checked first)
        pad = (1.0 if border == "rope" else 1.4) * max(6.0, 0.1 * min(w, h))
    else:
        pad = BORDER_WIDTHS.get(border, 3.0) / 2
    shown = drawn_marks(edits, entry)
    if shown and edits.mark_style == "border":
        pad += MARK_GAP + 3.0 + MARK_STEP * (len(shown) - 1)
    return pad


# A villager with several marks (the owner, 2026-10-22: "show all"): the first drawn as the tree draws a mark
# (a border or a glow), each other one a ring of its own this much further out.
MARK_STEP = 6.0


def drawn_marks(edits: Edits, entry: dict) -> list[tuple[str, str]]:
    """(name, colour) of each mark an entry gives that the Key has a colour for, in order."""
    return [(label, edits.marks[label]) for label in entry_marks(entry) if edits.marks.get(label)]


def extra_mark_reach(edits: Edits, entry: dict) -> float:
    """How far past a glow the further marks' rings reach (a glow style's second and later marks)."""
    shown = drawn_marks(edits, entry)
    return MARK_GAP + 3.0 + MARK_STEP * (len(shown) - 2) if len(shown) > 1 else 0.0


PAGE_MARGIN = 10                # nothing a portrait draws comes nearer a page's edge than this (as MARGIN)
FOOTER_ROOM = 110               # the footer's plate starts this far above the page's bottom


def drawn_reach(edits: Edits, village, p, profile: tuple) -> tuple[float, float, float, float]:
    """How far all a portrait draws reaches from its place's middle across (left, right) and from its top
    down (top, bottom): its frame as drawn (_profile, _reach: outline, decorations, stroke, special
    border, mark), a glow round it, and its place's own box, where its words go."""
    left, right, top, bottom = _reach(profile)
    entry = edits.entries.get(entry_key(village, p), {})
    if drawn_marks(edits, entry) and edits.mark_style == "glow":
        reach = max(edits.mark_glow, extra_mark_reach(edits, entry))
        left, right, top, bottom = left + reach, right + reach, top - reach, bottom + reach
    return max(left, NODE_W / 2), max(right, NODE_W / 2), min(top, 0.0), max(bottom, float(NODE_H))


def _profile(kind: str, w: float, h: float, angle: float, pad: float = 0.0,
             words: tuple | None = None) -> tuple[int, list, list]:
    """A frame as drawn, column by column across it: (half its width in whole columns, each column's top,
    each column's bottom), centred on 0 across and with a portrait's top at 0 down.  Everything the shape
    draws counts, not only its outline: the parts drawn like its border beside it (decor: a paw print's
    toes, a beetle's legs, a butterfly's feelers) -- and `pad` round it all, for its border's stroke and
    anything else drawn outside it (a special border's leaves, a mark).  `words`: (left, right, top,
    bottom) of a face and words drawn past the frame (fixed_face_size), counted as part of it."""
    key = (kind, round(w, 1), round(h, 1), round(angle, 1), round(pad, 1),
           tuple(round(v, 1) for v in words) if words else None)
    if key not in _PROFILES:
        x0, y0 = -w / 2, (NODE_H - h) / 2
        outline_pts = shape_points(kind, x0, y0, w, h, corner_radius(kind), angle)
        paths = [outline_pts + outline_pts[:1]]
        if words:
            wl, wr, wt, wb = words
            paths.append([(wl, wt), (wr, wt), (wr, wb), (wl, wb), (wl, wt)])
        for line in decor(kind):                 # in the frame's box, turned with it
            pts = [(x0 + u * w, y0 + v * h) for u, v in line]
            if angle:
                pts = [turn(px, py - NODE_H / 2, angle) for px, py in pts]
                pts = [(px, py + NODE_H / 2) for px, py in pts]
            paths.append(pts)
        xs = [p[0] for path in paths for p in path]
        half = int(math.ceil(max(-min(xs), max(xs)) + pad)) + 2
        tops, bottoms = [math.inf] * (2 * half + 1), [-math.inf] * (2 * half + 1)
        for path in paths:                       # every stroke walked half a pixel at a time
            for (ax, ay), (bx, by) in zip(path, path[1:]):
                n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / 0.5)))
                for i in range(n + 1):
                    px, py = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
                    k = int(round(px)) + half
                    if py < tops[k]:
                        tops[k] = py
                    if py > bottoms[k]:
                        bottoms[k] = py
        xs = [px for path in paths for px, _py in path]
        exact = (-min(xs) + pad, max(xs) + pad)   # how far it reaches across, to the hundredth
        if pad > 0:                              # grown by `pad` every way
            r = int(math.ceil(pad))
            grown_t, grown_b = list(tops), list(bottoms)
            for k in range(len(tops)):
                near = range(max(0, k - r), min(len(tops), k + r + 1))
                t = min(tops[j] for j in near)
                if t < math.inf:
                    grown_t[k] = t - pad
                    grown_b[k] = max(bottoms[j] for j in near) + pad
            tops, bottoms = grown_t, grown_b
        _PROFILES[key] = (half, tops, bottoms)
        _ACROSS[id(_PROFILES[key])] = exact
    return _PROFILES[key]


_ACROSS: dict = {}                      # a profile's id -> how far it reaches left and right, exactly


def frames_overlap(lay: "Layout", a: int, b: int, tolerance: float = 0.5) -> bool:
    """Whether portraits a's and b's frames, as drawn, overlap by more than `tolerance` (touching is not
    overlapping): column by column through their outlines (_profile)."""
    def placed(q):
        x, top, w, h, angle = lay.frame(q)
        half, tops, bottoms = _profile(lay.shape(lay.village.people[q]), w, h, angle)
        return x + w / 2, top - (NODE_H - h) / 2, half, tops, bottoms
    ax, ay, ah, atops, abottoms = placed(a)
    bx, by, bh, btops, bbottoms = placed(b)
    if abs(ax - bx) >= ah + bh:
        return False

    def inner(tops: list) -> tuple[int, int]:      # (frames side by side may share their edge column)
        filled = [k for k, t in enumerate(tops) if t < math.inf]
        return (filled[0], filled[-1]) if filled else (0, -1)
    a0, a1 = inner(atops)
    b0, b1 = inner(btops)
    for i in range(a0 + 1, a1):
        j = int(round(ax + i - ah - bx)) + bh
        if b0 < j < b1:
            lo = max(ay + atops[i], by + btops[j])
            hi = min(ay + abottoms[i], by + bbottoms[j])
            if hi - lo > tolerance and abs(ax + i - ah - (bx + j - bh)) < 0.5:
                return True
    return False


NEST = 90                       # from this packing on, a row may nestle into the dips of the one above


def _pitch(upper: list, lower: list, nest: bool = True) -> float:
    """How far below a row of frames the next row's portraits must stand so no two frames overlap
    (they may touch): `upper` and `lower` are (middle across, profile) each.  Nestling (`nest`), a frame
    goes as far up into the dips of the row above as what both draw lets it; else it stays below the
    whole of each frame above it that it stands under (their boxes never overlap)."""
    need = -math.inf
    for ux, uprof in upper:
        uh, utop, ubottom = uprof
        ul, ur, _ut, ub = _reach(uprof)
        for lx, lprof in lower:
            lh, ltop, _lbottom = lprof
            ll, lr, lt, _lb = _reach(lprof)
            if ux + ur <= lx - ll or lx + lr <= ux - ul:
                continue                         # not one above the other
            if not nest:
                need = max(need, ub - lt)
                continue
            for c in range(-uh, uh + 1):
                k = int(round(c + ux - lx)) + lh
                if 0 <= k < len(ltop) and ubottom[c + uh] > -math.inf and ltop[k] < math.inf:
                    need = max(need, ubottom[c + uh] - ltop[k])
    return need + 1.0 if need > -math.inf else 0.0       # (a pixel more: the outline between columns)


def _limits(edits: Edits) -> list[int]:
    """The family row widths worth trying for the whole tree (the owner: "think optimization of space"):
    the player's own when they set one; else the packing's, and one either side of it."""
    limit = packed_limit(edits)
    if edits.row_limit or not limit:
        return [limit]
    return sorted({max(2, limit - 1), limit, min(8, limit + 1)})


def _page_score(width: float, height: float) -> float:
    """Smaller is better: a tree's area, made worse the further its shape is from a page between 4:3
    and 16:9."""
    shape = width / max(1.0, height)
    off = 0.0 if 4 / 3 <= shape <= 16 / 9 else abs(math.log(shape / (4 / 3 if shape < 4 / 3 else 16 / 9)))
    return width * height * (1 + 2 * off)


_REACHES: dict = {}


def _reach(profile: tuple) -> tuple[float, float, float, float]:
    """How far a frame's drawing reaches left and right of its middle, and how high and low from its
    portrait's top (a frame resized taller than a portrait reaches past it)."""
    if id(profile) in _REACHES and _REACHES[id(profile)][0] is profile:
        return _REACHES[id(profile)][1]
    _REACHES[id(profile)] = (profile, _reach_of(profile))
    return _REACHES[id(profile)][1]


def _reach_of(profile: tuple) -> tuple[float, float, float, float]:
    half, tops, bottoms = profile
    filled = [k for k, t in enumerate(tops) if t < math.inf]
    if not filled:
        return 0.0, 0.0, 0.0, float(NODE_H)
    left, right = _ACROSS.get(id(profile), (half - filled[0] + 0.5, filled[-1] - half + 0.5))
    return left, right, min(tops[k] for k in filled), max(bottoms[k] for k in filled)


def _arrange(rows: list[list[int]], step: float, offset: float, rowh: float, tight: float, outline,
             align: str, gap: float = 0.0, nest: bool = True) -> dict[int, tuple[float, float, float, float]]:
    """A family block's portraits, each (across, down, reach left, reach right) from its first row's
    middle and top: its short rows either straight under each other or each second row set along by
    `offset` into the dips of the one above (the owner's sand grains: "packing like this"), whichever
    takes the smaller area.  Side by side, portraits a step apart, closing up as `tight` grows until their
    real outlines touch; each row as close under the one above as `tight` lets it, never so close that two
    frames' real outlines overlap (they may touch)."""
    best = None
    reach = {m: _reach(outline(m)) for row in rows for m in row}

    def spaced(row: list[int]) -> list[float]:
        xs = [0.0]
        for a, b in zip(row, row[1:]):
            touch = reach[a][1] + reach[b][0]           # their drawings touching
            snug = touch + gap
            # A step apart, closing in to snug as the packing nears 100 -- never nearer than touching
            # (a frame wider than a step stands further off).
            xs.append(xs[-1] + max(touch, step if snug >= step else step - tight * (step - snug)))
        return xs

    widths = [spaced(row)[-1] for row in rows]
    widest = max(widths)
    for shift in ((0.0, offset) if offset and len(rows) > 1 else (0.0,)):
        pos: dict[int, tuple[float, float, float, float]] = {}
        y = 0.0
        done: list[tuple[float, list]] = []      # the rows placed so far, each (its top, its frames)
        for k, row in enumerate(rows):
            spare = widest - widths[k]
            left = (0.0 if align == "left" else spare if align == "right" else spare / 2) - widest / 2
            left += shift if k % 2 else 0.0
            here = [(cx, outline(m)) for m, cx in ((m, left + dx) for m, dx in zip(row, spaced(row)))]
            if done:
                need = _pitch(done[-1][1], here, nest)
                y += need if need >= rowh else rowh - tight * (rowh - need)
                # A row nestled into the dips of the one above may stand under the row above that, set
                # along the same way: never into it either (a diamond under a diamond two rows up).
                for top, earlier in done[:-1]:
                    y = max(y, top + _pitch(earlier, here, nest))
            for m, (cx, _prof) in zip(row, here):
                pos[m] = (cx, y, *reach[m])
            done.append((y, here))
        first = [pos[m][0] for m in rows[0]]
        middle = (min(first) + max(first)) / 2
        pos = {m: (cx - middle, cy, *rest) for m, (cx, cy, *rest) in pos.items()}
        span = max(v[0] + v[3] for v in pos.values()) - min(v[0] - v[2] for v in pos.values())
        area = span * (y + NODE_H)
        if best is None or area < best[0] - 1e-6:
            best = (area, pos)
    return best[1]


def packed_limit(edits: Edits) -> int:
    """The most portraits in a family's row in the Packed layouts: the player's (Edits.row_limit), else
    from Edits.packing -- no wrap at all when barely packed, 2 when packed tightest (4 at the default)."""
    if edits.row_limit:
        return edits.row_limit
    return 0 if edits.packing < 10 else max(2, round(8 - 6 * edits.packing / 100))


@dataclass
class _Clusters:
    """Packed families laid out (_clusters): each portrait's x and y, and for the lines, each
    unit's families and where its children's blocks start."""
    x: dict[int, float]
    y: dict[int, float]
    hosted: dict[int, list]             # unit -> the families whose children hang under it
    gap_top: dict[tuple, float]         # ("unit", unit) -> the top of its children's first row
    local: dict[int, list]              # family -> its parents in the unit the children hang under
    lane_key: dict[int, tuple] = field(default_factory=dict)    # family -> its gap_top key
    couple_y: dict[int, float] = field(default_factory=dict)    # packed: family -> its couple's line, under the parents
    ways: dict[int, list] = field(default_factory=dict)         # packed: family -> the way kept for its line down


def _clusters(people: dict, placed: set, families: list[Family], step: float, gap: float,
              edits: Edits, block_shape=None) -> _Clusters:
    """Packed families (the owner's hand-made VV5 tree, 2026-10-09).

    A unit is a family member with the partners beside them, in one row: partners stand side by side, the
    most-children couples first, a family member with no recorded parents (married in) always with a partner
    when one has a free side, and never more than two who have parents in the tree (each would be taken
    from their own brothers and sisters).  A family's children hang under the unit of its parents --
    under the lower of the two when they stand in different units.  At packing 0 it is a tidy tree:
    every subtree whole under its parents, packed outline against outline.  Packed any tighter, each
    family is a small block of short rows nestled into the free space nearest under its parents (packed()).
    A family member's height follows their parents', not a generation row.  Two families keep room between
    them (CORRIDOR) for a line to pass; brothers and sisters keep the player's gap.  The children who
    stand with a partner elsewhere, and the parent who stands apart from the unit the children hang
    under, are joined by lines that go round (Family.away, Family.far)."""
    cell = step - gap                   # a portrait's room across
    give = 1 - squeeze(edits)           # the room between things, closing up as the packing nears 100
    subgap, clear_px = SUBGAP * give, CLEAR * give
    straight = behind(edits)            # lines behind the portraits (Edits.lines_behind): no ways kept round them
    fams = [f for f in families if any(c in placed for c in f.children)]
    parent_fam: dict[int, Family] = {}
    for f in fams:
        if any(q in placed for q in (f.father, f.mother) if q is not None):
            for c in f.children:
                if c in placed:
                    parent_fam.setdefault(c, f)

    def order(q: int) -> tuple:
        return (people[q].generation, _place(people[q]))

    # Units: paths of partners, each joined end to end.
    path: dict[int, list[int]] = {q: [q] for q in placed}
    couples = sorted((f for f in fams if f.father in placed and f.mother in placed),
                     key=lambda f: (-sum(1 for c in f.children if c in placed), f.id))
    for f in couples:
        a, b = f.father, f.mother
        pa, pb = path[a], path[b]
        if pa is pb or a not in (pa[0], pa[-1]) or b not in (pb[0], pb[-1]):
            continue
        if sum(1 for q in pa + pb if q in parent_fam) > 2:
            continue
        pa = pa if pa[-1] == a else pa[::-1]
        pb = pb if pb[0] == b else pb[::-1]
        joined = pa + pb
        for q in joined:
            path[q] = joined
    units: dict[int, list[int]] = {}
    unit_of: dict[int, int] = {}
    for q in sorted(placed, key=order):
        if q not in unit_of:
            units[len(units)] = path[q]
            for m in path[q]:
                unit_of[m] = len(units) - 1

    # Depths: a unit hangs under the family of its deepest member who has parents in the tree, and a
    # family under the deepest of its parents' units.  A loop in the records (never in a game's own)
    # is cut where it is found.
    depth: dict[int, int] = {}
    home: dict[int, Family] = {}
    hosts: dict[int, int] = {}
    busy: set[int] = set()

    def host_of(f: Family) -> int | None:
        if f.id in hosts:
            return hosts[f.id]
        best = None
        for q in (f.father, f.mother):
            if q is None or q not in unit_of:
                continue
            d = deep(unit_of[q])
            if d is not None and (best is None or d > best[0]):
                best = (d, unit_of[q])
        if best is not None:
            hosts[f.id] = best[1]
        return None if best is None else best[1]

    def deep(u: int) -> int | None:
        if u in depth:
            return depth[u]
        if u in busy:
            return None
        busy.add(u)
        best = None
        for m in units[u]:
            f = parent_fam.get(m)
            h = host_of(f) if f is not None else None
            if h is not None and depth.get(h) is not None and (best is None or depth[h] + 1 > best[0]):
                best = (depth[h] + 1, f)
        busy.discard(u)
        depth[u] = best[0] if best else 0
        if best:
            home[u] = best[1]
        return depth[u]

    for u in units:
        deep(u)
    hosted: dict[int, list[Family]] = {u: [] for u in units}
    for f in fams:
        h = host_of(f)
        if h is not None:
            hosted[h].append(f)
    local: dict[int, list[int]] = {}
    for f in fams:
        h = hosts.get(f.id)
        parents = [q for q in (f.father, f.mother) if q is not None and q in placed]
        local[f.id] = [q for q in parents if unit_of[q] == h]
        f.far = [q for q in parents if unit_of[q] != h]
        f.away = [c for c in f.children if c in placed and home.get(unit_of[c]) is not f]
    kids_of: dict[int, list[int]] = {f.id: [] for f in fams}
    for u in sorted(units, key=lambda u: min(order(m) for m in units[u])):
        if u in home:
            kids_of[home[u].id].append(u)
    for u, fs in hosted.items():               # each family under the middle of its parents in the unit
        spot = {m: i for i, m in enumerate(units[u])}
        fs.sort(key=lambda f: (sum(spot[q] for q in local[f.id]) / max(1, len(local[f.id])), f.id))

    # The room for a unit's lines between it and its children.
    room: dict[int, float] = {}
    for u, fs in hosted.items():
        if fs:
            couples_here = sum(1 for f in fs if len(local[f.id]) == 2)
            room[u] = give * (edits.row_gap + couples_here * LANE + (BAND_GAP if couples_here else 0)
                              + len(fs) * LANE + LANE_BOTTOM)

    # Outlines: boxes (top, bottom, left, right, whose).  Brothers and sisters keep the player's gap;
    # anything else keeps room for a line to pass.
    # Edits.packing drives it all: how many portraits in a family's row (unless the player set
    # Edits.row_limit), how far sideways a row may go to fill a gap (none at 0: a tidy tree), and the
    # room kept between two families' clusters.
    packing = edits.packing / 100
    # (Packed tightest, none: two families' boxes already reach as far as their frames draw.)
    corridor = max(gap, CORRIDOR * (2 - packing)) * give
    reach = 4 * step * packing

    def apart(a: tuple, b: tuple) -> float:
        return gap if a[4] == b[4] and a[4][0] == "kin" else corridor

    def clear_of(left: list, right: list) -> float | None:
        """How far right `right` must move to stand clear of `left` (None: they never meet)."""
        need = None
        for a in left:
            for b in right:
                if a[0] < b[1] and b[0] < a[1]:
                    s = a[3] + apart(a, b) - b[2]
                    if need is None or s > need:
                        need = s
        return need

    def hits(placed_boxes: list, new: list) -> bool:
        """Whether `new` would touch what is placed, keeping a row's gap (SUBGAP, squeezed) above each new box for
        the lines that come down to it."""
        for b in new:
            top = b[0] - subgap
            for a in placed_boxes:
                if a[0] < b[1] and top < a[1]:
                    sep = apart(a, b)
                    if a[2] - sep < b[3] and b[2] < a[3] + sep:
                        return True
        return False

    def merged(boxes: list) -> list:
        out: dict[tuple, list] = {}
        for b in boxes:
            k = (b[0], b[1], b[4])
            if k in out:
                out[k][2] = min(out[k][2], b[2])
                out[k][3] = max(out[k][3], b[3])
            else:
                out[k] = list(b)
        return [tuple(b) for b in out.values()]

    def moved(part: tuple, dx: float, dy: float = 0.0) -> tuple:
        pos, ys, boxes, gaps = part
        return ({q: v + dx for q, v in pos.items()}, {q: v + dy for q, v in ys.items()},
                [(b[0] + dy, b[1] + dy, b[2] + dx, b[3] + dx, b[4]) for b in boxes],
                {k: v + dy for k, v in gaps.items()})

    def joined(parts: list) -> tuple:
        pos, ys, boxes, gaps = {}, {}, [], {}
        for p in parts:
            pos.update(p[0])
            ys.update(p[1])
            boxes += p[2]
            gaps.update(p[3])
        return pos, ys, merged(boxes), gaps

    def side_by_side(parts: list) -> tuple:
        out: list = []
        boxes: list = []
        for p in parts:
            d = clear_of(boxes, p[2]) if boxes else 0.0
            p = moved(p, d or 0.0)
            out.append(p)
            boxes += p[2]
        return joined(out)

    def first_row_middle(part: tuple) -> float:
        row = [b for b in part[2] if b[0] == 0 and b[4][0] in ("kin", "root")]
        return (min(b[2] for b in row) + max(b[3] for b in row)) / 2

    def build(u: int, limit: int) -> tuple:
        """Unit u and everything under it, its first member's middle at 0 and its top at 0: (each
        portrait's x, each portrait's y, the outline, each unit's children's first row's top)."""
        members = units[u]
        whose = ("kin", home[u].id) if u in home else ("root", u)
        pos = {m: i * step for i, m in enumerate(members)}
        part = (pos, {m: 0.0 for m in members},
                [(0.0, NODE_H, -cell / 2, (len(members) - 1) * step + cell / 2, whose)], {})
        if not hosted[u]:
            return part
        bt = NODE_H + room[u]
        blocks, shifts, boxes = [], [], []
        for f in hosted[u]:
            stem = sum(pos[q] for q in local[f.id]) / max(1, len(local[f.id]))
            b = block(f, limit)
            if b is None:
                continue
            b = moved(b, stem, bt)
            need = clear_of(boxes, b[2]) if boxes else None
            if need is not None and need > 0:
                b = moved(b, need)
            shifts.append(need if need is not None and need > 0 else 0.0)
            boxes += b[2]
            blocks.append((stem, b))
        # Pushed apart, the families stay as near under their parents as they can, together.
        even = -sum(shifts) / len(shifts) if shifts else 0.0
        lo, hi = part[2][0][2], part[2][0][3]
        parts = [part]
        for (stem, b), f in zip(blocks, [f for f in hosted[u] if kids_of[f.id]]):
            b = moved(b, even)
            parts.append(b)
            # Every child hangs from the family's line, whichever row they stand in.
            hangs = [b[0][m] for v in kids_of[f.id] for m in units[v]]
            lo = min([lo, stem - cell / 2] + [h - cell / 2 for h in hangs])
            hi = max([hi, stem + cell / 2] + [h + cell / 2 for h in hangs])
        out = joined(parts)
        out[3][("unit", u)] = bt
        # The lines' room between the unit and its children's first row: nobody else's portraits there.
        out[2].append((NODE_H, bt, lo, hi, ("lines", u)))
        return out

    def block(f: Family, limit: int) -> tuple | None:
        """A family's children in short rows of at most `limit` portraits, those with no children of
        their own first: each row as high as it goes without touching the rows above or what hangs
        under them, centred (or lined up, Edits.row_align) under the first.  The first row's middle at 0
        and its top at 0."""
        kids = kids_of[f.id]
        if not kids:
            return None
        ordered = [u for u in kids if not hosted[u]] + [u for u in kids if hosted[u]]
        atoms: list[list[int]] = []
        for u in ordered:               # babies born together kept in one row
            litter = people[units[u][0]].litter
            if litter and len(units[u]) == 1 and atoms and len(units[atoms[-1][-1]]) == 1 \
                    and people[units[atoms[-1][-1]][0]].litter == litter:
                atoms[-1].append(u)
            else:
                atoms.append([u])
        rows = _block_rows(atoms, limit, lambda atom: sum(len(units[u]) for u in atom))
        placed_boxes: list = []
        parts: list = []
        first = None
        above = None
        for row in rows:
            part = side_by_side([build(u, limit) for atom in row for u in atom])
            part = moved(part, -first_row_middle(part))
            lo = min(b[2] for b in part[2] if b[0] == 0)
            hi = max(b[3] for b in part[2] if b[0] == 0)
            if first is None:
                first = (lo, hi)
            elif edits.row_align == "left":
                part = moved(part, first[0] - lo)
            elif edits.row_align == "right":
                part = moved(part, first[1] - hi)
            if above is not None:
                part = moved(part, *nestle(placed_boxes, part, above + NODE_H + subgap))
            placed_boxes += part[2]
            parts.append(part)
            above = min(b[0] for b in part[2])
        return joined(parts)

    def nestle(placed_boxes: list, part: tuple, base: float) -> tuple[float, float]:
        """Where a family's next row goes (right, down): as high as it fits from `base` down without
        touching anything placed, as near under the first row as it can, never further sideways than
        `reach`.  A tidy tree (packing 0) puts it under everything, straight down."""
        if not reach:
            return 0.0, max([base] + [b[1] + subgap for b in placed_boxes])
        for y in sorted({base} | {b[1] + subgap for b in placed_boxes if b[1] + subgap > base}):
            new = [(b[0] + y, b[1] + y, b[2], b[3], b[4]) for b in part[2]]
            shifts = {0.0}
            for a in placed_boxes:
                for b in new:
                    if a[0] < b[1] and b[0] - subgap < a[1]:
                        sep = apart(a, b)
                        shifts.add(a[3] + sep - b[2])
                        shifts.add(a[2] - sep - b[3])
            for dx in sorted((s for s in shifts if abs(s) <= reach), key=abs):
                if not hits(placed_boxes, [(b[0], b[1], b[2] + dx, b[3] + dx, b[4]) for b in new]):
                    return dx, y
        return 0.0, max([base] + [b[1] + subgap for b in placed_boxes])

    roots = sorted((u for u in units if u not in home), key=lambda u: min(order(m) for m in units[u]))

    def packed(limit: int) -> tuple[dict, dict, dict]:
        """Packed families (the owner's hand-made VV5 tree): the founders in a row; then, from the top of
        the page down, each family's children as a small block of short rows (at most `limit` across)
        put in the nearest free place under their parents -- straight under them when it is free, else a
        little lower or to one side, into any gap between the families already placed, so families sit
        at different heights and the page fills densely.  The room a family's lines take, between the
        parents and the block, is kept clear of every portrait.  Each portrait's x and y, and the top of
        each family's first row."""
        rowh = NODE_H + subgap
        couples.clear()
        ways.clear()
        down = 6 * (1 - packing) + packing           # a row lower costs this many places sideways, n rows n * n times
        pos: dict[int, float] = {}
        ys: dict[int, float] = {}
        gaps: dict[tuple, float] = {}
        portraits: list = []
        room_kept: list = []
        def root_part(u: int) -> tuple:
            """A founding couple (or a later root) in a row as close as the packing lets them stand, boxed
            as far as they draw (_arrange), like any family's row."""
            laid = block_shape([units[u]])
            box = lambda m, k: max(laid[m][k], cell / 2 - (1 - give) * (cell / 2 - laid[m][k]))  # noqa: E731
            return ({m: laid[m][0] for m in units[u]}, {m: 0.0 for m in units[u]},
                    [(min([0.0] + [laid[m][4] for m in units[u]]), max([NODE_H] + [laid[m][5] for m in units[u]]),
                      min(laid[m][0] - box(m, 2) for m in units[u]), max(laid[m][0] + box(m, 3) for m in units[u]),
                      ("root", u))], {})
        top_row = side_by_side([root_part(u) for u in roots])
        pos.update(top_row[0])
        ys.update(top_row[1])
        portraits += top_row[2]
        # The page the families fill: as wide as makes a 16:9 page at the tightest packing, wider the
        # looser; the founders in its middle.  A block wider than the page may overrun it.
        page = math.sqrt(len(placed) * step * rowh * 1.6 * 16 / 9) * (1.6 - 0.6 * packing)
        middle = (min(top_row[0].values()) + max(top_row[0].values())) / 2
        low, high = middle - page / 2, middle + page / 2
        waiting = [(0.0, pos[units[u][0]], u) for u in roots if hosted[u]]
        heapq.heapify(waiting)

        def free(new: list, lines: tuple) -> bool:
            for b in new:
                top = b[0] - subgap
                for a in portraits:
                    if a[0] < b[1] and top < a[1]:
                        sep = apart(a, b)
                        if a[2] - sep < b[3] and b[2] < a[3] + sep:
                            return False
                for a in room_kept:
                    if a[0] < b[1] and b[0] < a[1] and a[2] - clear_px < b[3] and b[2] < a[3] + clear_px:
                        return False
            for a in portraits:
                if a[0] < lines[1] and lines[0] < a[1] and a[2] - clear_px < lines[3] and lines[2] < a[3] + clear_px:
                    return False
            return True

        def clear(x0: float, x1: float, y0: float, y1: float) -> bool:
            """No portrait in the way of a line from (x0, y0) to (x1, y1), level or upright."""
            lo_x, hi_x, lo_y, hi_y = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
            return not any(a[2] - clear_px < hi_x and lo_x < a[3] + clear_px and a[0] - clear_px < hi_y and lo_y < a[1] + clear_px
                           for a in portraits)

        def elbow(stem: float, start: float, end: float, lo: float, hi: float) -> list | None:
            """A tidy way for the line from the parents (at `stem`, from `start` under them) down to the
            children's lines (at `end`, across lo..hi), clear of every portrait: down to a level between
            the rows, across, and down; or, when no one level will do, down, across to a gap, down that gap,
            across and down.  Its points; None when none is clear."""
            to = min(max(stem, lo), hi)
            levels = sorted({start, end} | {v for a in portraits for v in (a[0] - clear_px - 4, a[1] + clear_px + 4)
                                            if start < v < end})
            # The levels the line can reach straight down from the parents: down to the first portrait in
            # its way; and those from which it can drop straight onto the children's line: from the last
            # portrait in that way.  (Each worked out once, not level by level: Codex-free speed.)
            down = min([math.inf] + [a[0] - clear_px for a in portraits
                                     if a[2] - clear_px < stem < a[3] + clear_px and start < a[1] + clear_px])
            up = max([-math.inf] + [a[1] + clear_px for a in portraits
                                    if a[2] - clear_px < to < a[3] + clear_px and a[0] - clear_px < end])
            highs = [h for h in levels if h <= down]
            lows = [h for h in reversed(levels) if h >= up]
            check = functools.lru_cache(maxsize=None)(clear)    # the same piece is asked often
            if start > end:                 # packed so tight the children's line is above the start:
                highs, lows = [], []        # level by level, as the line goes up
                for h in levels:
                    if not clear(stem, stem, start, h):
                        break
                    highs.append(h)
                for h in reversed(levels):
                    if not clear(to, to, h, end):
                        break
                    lows.append(h)
            for h in highs:                 # one level, the highest that works
                if h in lows and check(stem, to, h, h):
                    return [(stem, start), (stem, h), (to, h), (to, end)]
            gaps = sorted({v for a in portraits if a[1] > start and a[0] < end
                           for v in (a[2] - clear_px - 4, a[3] + clear_px + 4)},
                          key=lambda v: abs(v - stem) + abs(v - to))[:10]
            best = None
            for h1 in highs[-4:]:
                for xc in gaps:
                    if not check(stem, xc, h1, h1):
                        continue
                    for h2 in lows[-4:]:
                        if check(xc, xc, h1, h2) and check(xc, to, h2, h2):
                            length = abs(xc - stem) + abs(to - xc) + abs(h2 - h1)
                            if best is None or length < best[0]:
                                best = (length, [(stem, start), (stem, h1), (xc, h1), (xc, h2), (to, h2), (to, end)])
            return None if best is None else best[1]

        def kept(pts: list) -> list:
            """A way's pieces as thin boxes no later portrait may cover."""
            return [(min(a[1], b[1]) - 2, max(a[1], b[1]) + 2, min(a[0], b[0]) - 2, max(a[0], b[0]) + 2)
                    for a, b in zip(pts, pts[1:]) if a != b]

        def hold(v: int) -> None:
            """The room under a unit with families of its own for its couples' lines, kept from the moment
            it is placed, so nobody else's block is nestled there first."""
            pairs_v = sum(1 for f in hosted[v] if len(local[f.id]) == 2)
            xs = [pos[m] for m in units[v]]
            below = ys[units[v][0]] + NODE_H
            room_kept.append((below, below + give * (edits.row_gap + pairs_v * LANE + LANE),
                              min(xs) - cell / 2, max(xs) + cell / 2))

        for u in roots:
            if hosted[u]:
                hold(u)
        while waiting:
            _y, _x, u = heapq.heappop(waiting)
            bottom = ys[units[u][0]] + NODE_H
            # The couples' lines just under the parents, each its own level, and their room kept.
            pairs = [f for f in hosted[u] if len(local[f.id]) == 2]
            for k, f in enumerate(pairs):
                couples[f.id] = bottom + give * (edits.row_gap + k * LANE + LANE / 2)
            if pairs:
                xs = [pos[m] for m in units[u]]
                room_kept.append((bottom, bottom + give * (edits.row_gap + len(pairs) * LANE),
                                  min(xs) - cell / 2, max(xs) + cell / 2))
            band = give * (LANE_BOTTOM + len(hosted[u]) * LANE + BAND_GAP)    # the children's lines over a block
            for f in hosted[u]:
                stem = sum(pos[q] for q in local[f.id]) / max(1, len(local[f.id]))
                top0 = bottom + room[u]
                gaps[("family", f.id)] = top0
                if not kids_of[f.id]:
                    continue
                atoms: list[list[int]] = []
                # Those with no family of their own first, so the last row -- with room under it -- holds
                # those whose families hang under them.
                kids = [v for v in kids_of[f.id] if not hosted[v]] + [v for v in kids_of[f.id] if hosted[v]]
                for v in kids:              # babies born together kept in one row
                    litter = people[units[v][0]].litter
                    if litter and len(units[v]) == 1 and atoms and len(units[atoms[-1][-1]]) == 1 \
                            and people[units[atoms[-1][-1]][0]].litter == litter:
                        atoms[-1].append(v)
                    else:
                        atoms.append([v])
                # Those with families of their own all in the last row, with nothing under them but room
                # for their own families.
                size = (lambda atom: sum(len(units[v]) for v in atom))
                leaves = [a for a in atoms if not any(hosted[v] for v in a)]
                branches = [a for a in atoms if any(hosted[v] for v in a)]
                rows = _block_rows(leaves, limit, size) if leaves else []
                if branches:
                    if rows and sum(size(a) for a in rows[-1]) + sum(size(a) for a in branches) <= limit:
                        rows[-1] += branches
                    else:
                        rows.append(branches)
                # The block's short rows, plain or brick-wise, as close as the frames allow (_arrange).
                lines_of = [[m for atom in row for v in atom for m in units[v]] for row in rows]
                rel = block_shape(lines_of)
                shape: list = []
                for line in lines_of:
                    # Each row a portrait's room across at each end, closing in as the packing nears 100 --
                    # never inside what its frames draw (_reach: their decorations, borders, a frame
                    # resized wider or taller than a portrait).
                    top = rel[line[0]][1]

                    def side(m: int, k: int) -> float:
                        return max(rel[m][k], cell / 2 - (1 - give) * (cell / 2 - rel[m][k]))
                    shape.append((min([top] + [top + rel[m][4] for m in line]),
                                  max([top + NODE_H] + [top + rel[m][5] for m in line]),
                                  min(rel[m][0] - side(m, 2) for m in line),
                                  max(rel[m][0] + side(m, 3) for m in line),
                                  ("kin", f.id)))
                hangs = [v[0] for v in rel.values()]
                shape_lo, shape_hi = min(b[2] for b in shape), max(b[3] for b in shape)
                best = None
                # (A block may draw above its first row's top -- a butterfly's feelers, a border's stroke:
                # its slot goes that much lower to clear what is above.)
                reach_up = min(b[0] for b in shape)
                levels = sorted({top0} | {a[1] + subgap - reach_up for a in portraits if a[1] + subgap - reach_up > top0})
                for y in levels:
                    lower = ((y - top0) / rowh) ** 2 * down
                    if best is not None and lower >= best[0]:
                        break
                    new = [(b[0] + y, b[1] + y, b[2] + stem, b[3] + stem, b[4]) for b in shape]
                    shifts = {0.0, low - stem - shape_lo, high - stem - shape_hi}
                    for a in portraits:
                        for b in new:
                            if a[0] < b[1] and b[0] - subgap < a[1]:
                                sep = apart(a, b)
                                shifts.add(a[3] + sep - b[2])
                                shifts.add(a[2] - sep - b[3])
                    for a in room_kept:
                        for b in new:
                            if a[0] < b[1] and b[0] < a[1]:
                                shifts.add(a[3] + clear_px - b[2])
                                shifts.add(a[2] - clear_px - b[3])
                    wide = shape_hi - shape_lo <= high - low
                    for dx in sorted(shifts, key=abs):
                        cost = lower + abs(dx) / step
                        if best is not None and cost >= best[0]:
                            break
                        if wide and (stem + dx + shape_lo < low or stem + dx + shape_hi > high):
                            continue
                        lo_h, hi_h = min(stem + dx + h for h in hangs), max(stem + dx + h for h in hangs)
                        lines = (max(bottom, y - band), y, lo_h - cell / 2, hi_h + cell / 2)
                        if free([(b[0], b[1], b[2] + dx, b[3] + dx, b[4]) for b in new], lines):
                            way = [] if straight else elbow(stem, bottom + give * (edits.row_gap + len(pairs) * LANE) + 2,
                                                          lines[0], lo_h, hi_h)
                            if way is not None:
                                best = (cost, dx, y, lines, way)
                                break
                if best is None:            # nowhere free: under everything, straight down
                    y = max(top0, max(a[1] for a in portraits) + subgap + room[u] - reach_up)
                    best = (0.0, 0.0, y, (y - band, y, min([stem] + [stem + h for h in hangs]) - cell / 2,
                                          max([stem] + [stem + h for h in hangs]) + cell / 2), [])
                _cost, dx, y, lines, way = best
                room_kept.extend(kept(way))
                if way:
                    ways[f.id] = way
                gaps[("family", f.id)] = y
                for m, (mx, my, *_reaches) in rel.items():
                    pos[m], ys[m] = stem + dx + mx, y + my
                portraits.extend((b[0] + y, b[1] + y, b[2] + stem + dx, b[3] + stem + dx, b[4]) for b in shape)
                room_kept.append(lines)
                for atom in (a for row in rows for a in row):
                    for v in atom:
                        if hosted[v]:
                            heapq.heappush(waiting, (ys[units[v][0]], pos[units[v][0]], v))
                            hold(v)
        return pos, ys, gaps

    couples: dict[int, float] = {}
    ways: dict[int, list] = {}

    lane_key: dict[int, tuple] = {}
    if not packing:
        # Packing 0: a tidy tree, every subtree whole under its parents.
        pos, ys, _boxes, gaps = side_by_side([build(u, packed_limit(edits)) for u in roots])
        for u, fs in hosted.items():
            for f in fs:
                lane_key[f.id] = ("unit", u)
    else:
        # The family row width (within what the packing allows) that makes the smallest tree near a
        # pleasing page shape (the owner: "think optimization of space"), unless the player set their own.
        best = None
        for limit in _limits(edits):
            trial = packed(limit)
            width = max(trial[0].values()) - min(trial[0].values()) + step
            height = max(trial[1].values()) + NODE_H
            score = _page_score(width, height)
            if best is None or score < best[0]:
                best = (score, trial, dict(couples), dict(ways))
        _score, (pos, ys, gaps), kept_couples, kept_ways = best
        couples.clear()
        couples.update(kept_couples)
        ways.clear()
        ways.update(kept_ways)
        for u, fs in hosted.items():
            for f in fs:
                lane_key[f.id] = ("family", f.id)
    shift = LEFT - 260 + NODE_W / 2 - min(pos.values())       # (no generation labels: see scene)
    x = {q: v - NODE_W / 2 + shift for q, v in pos.items()}
    y = {q: v + TOP for q, v in ys.items()}
    gap_top = {k: v + TOP for k, v in gaps.items()}
    return _Clusters(x, y, hosted, gap_top, local, lane_key, {f: v + TOP for f, v in couples.items()},
                     {f: [(px + shift, py + TOP) for px, py in pts] for f, pts in ways.items()})


def _cluster_lanes(cl: _Clusters) -> "_Lanes":
    """Packed families' lanes: the gap under each unit holds its families' lines, a couple's
    line for each family whose two parents stand in the unit and a children's line for each family."""
    out = _Lanes({}, {}, {})
    for u, fs in cl.hosted.items():
        if not fs:
            continue
        # Every family of the unit has a lane of its own in the room under it, whether their children
        # all start at one height (a tidy tree) or each at its own (packed: one key per family).
        pairs = [f for f in fs if len(cl.local[f.id]) == 2]
        for k, f in enumerate(fs):
            key = cl.lane_key[f.id]
            out.row[f.id] = key
            out.index[f.id] = k
            out.count[key] = len(fs)
            out.couple_count[key] = len(pairs)
        for k, f in enumerate(pairs):
            out.couple_index[f.id] = k
    return out


LANE = 14                       # between two families' lines
BAND_GAP = 10                   # between the couples' lines and the children's
LANE_TOP = 30                   # under the row above, before the first lane
LANE_BOTTOM = 46                # under the last lane: the children's drops and the triangles


@dataclass
class _Lanes:
    row: dict[int, int]         # family -> its children's generation
    index: dict[int, int]       # family -> its children's lane in that gap (0 the highest)
    count: dict[int, int]       # generation -> children's lanes in the gap above it
    couple_index: dict[int, int] = field(default_factory=dict)  # family -> its couple's lane
    couple_count: dict[int, int] = field(default_factory=dict)  # generation -> couples' lanes


def _pack(spans: list[tuple[float, float, int]], index: dict[int, int]) -> int:
    """Lines side by side share a lane when they do not overlap: each line's lane, and how many."""
    ends: list[float] = []
    for lo, hi, fid in sorted(spans):
        for k, end in enumerate(ends):
            if end + GAP_X < lo:
                ends[k] = hi
                index[fid] = k
                break
        else:
            ends.append(hi)
            index[fid] = len(ends) - 1
    return len(ends)


def _lanes(people: dict, families: list[Family], x: dict[int, float]) -> _Lanes:
    """The gap above each row: the couples' lines above, the children's lines below."""
    out = _Lanes({}, {}, {})
    kids_by_row: dict[int, list[tuple[float, float, int]]] = {}
    couples_by_row: dict[int, list[tuple[float, float, int]]] = {}
    for fam in families:
        kids = [c for c in fam.children if c in x]
        if not kids:
            continue
        g = min(people[c].generation for c in kids)
        out.row[fam.id] = g
        parents = [fam.drops[q] for q in (fam.father, fam.mother) if q is not None and q in x]
        xs = _hangs(people, fam, x)
        if len(parents) == 2:
            couples_by_row.setdefault(g, []).append((min(parents), max(parents), fam.id))
            xs.append(sum(parents) / 2)
        else:
            xs += parents
        kids_by_row.setdefault(g, []).append((min(xs), max(xs), fam.id))
    for g, spans in kids_by_row.items():
        out.count[g] = _pack(spans, out.index)
    # Every couple has a level of its own: couples' lines are often one colour, and two side by
    # side on one level would read as one line.
    for g, spans in couples_by_row.items():
        for k, (_lo, _hi, fid) in enumerate(sorted(spans)):
            out.couple_index[fid] = k
        out.couple_count[g] = len(spans)
    return out


def _drops(people: dict, families: list[Family], x: dict[int, float]) -> None:
    """Where each family's line leaves each parent: a parent of several families (one father,
    many mothers) gets one point each along the bottom of their frame, in the order of the
    families' children, so no two families' lines lie on top of each other."""
    by_parent: dict[int, list[Family]] = {}
    for fam in families:
        if not any(c in x for c in fam.children):
            continue
        for q in (fam.father, fam.mother):
            if q is not None and q in x:
                by_parent.setdefault(q, []).append(fam)
    for q, fams in by_parent.items():
        fams.sort(key=lambda f: sum(_hangs(people, f, x)) / max(1, len(_hangs(people, f, x))))
        span = min(NODE_W - 30, 16 * (len(fams) - 1))
        for k, fam in enumerate(fams):
            dx = -span / 2 + span * k / (len(fams) - 1) if len(fams) > 1 else 0.0
            fam.drops[q] = x[q] + NODE_W / 2 + dx


def _hangs(people: dict, fam: Family, x: dict[int, float]) -> list[float]:
    """Where the family's children hang from its line: one point each, or one for twins."""
    groups: dict[object, list[int]] = {}
    for c in fam.children:
        if c in x:
            groups.setdefault(people[c].litter or ("one", c), []).append(c)
    return [sum(x[c] + NODE_W / 2 for c in members) / len(members) for members in groups.values()]


def _stem(fam: Family, parents: list[int]) -> float:
    return sum(fam.drops[q] for q in parents) / len(parents)


def _order_lanes(people: dict, families: list[Family], x: dict[int, float], lanes: _Lanes) -> None:
    """The order of the lines in each gap that crosses the fewest other lines (the owner: "at
    most a single point of intersection between lines"): lanes are swapped while a swap helps."""
    for g in set(lanes.row.values()):
        fams = [f for f in families if lanes.row.get(f.id) == g]
        couples = lanes.couple_count.get(g, 0)
        kids = lanes.count.get(g, 0)
        couple_order = list(range(couples))
        kid_order = list(range(kids))
        # SPEED (v1.35.85), the same answer as counting every pair at every swap: the lines' places across (x)
        # never change while the lanes are swapped, only their heights.  So the pairs of an upright and a level
        # line of two families that meet across are found ONCE, each height a slot of `heights` (0: above all,
        # 1: below all, 2+c: couple lane c, 2+couples+k: children's lane k, each slot holding the height that
        # lane's place in its order gives); and a swap of two lanes recounts only the pairs that touch them.
        LOW, HIGH = 0, 1
        vertical, horizontal = [], []
        for f in fams:
            parents = [q for q in (f.father, f.mother) if q is not None and q in x]
            hangs = _hangs(people, f, x)
            ky = 2 + couples + lanes.index[f.id]
            if f.id in lanes.couple_index:
                cy = 2 + lanes.couple_index[f.id]
                stem = _stem(f, parents)
                vertical += [(f.id, f.drops[q], LOW, cy) for q in parents]
                vertical.append((f.id, stem, cy, ky))
                horizontal.append((f.id, min(f.drops[q] for q in parents), max(f.drops[q] for q in parents), cy))
                xs = hangs + [stem]
            else:
                vertical += [(f.id, f.drops[q], LOW, ky) for q in parents]
                xs = hangs + [f.drops[q] for q in parents]
            vertical += [(f.id, h, ky, HIGH) for h in hangs]
            horizontal.append((f.id, min(xs), max(xs), ky))
        meeting = [(y0, y1, hy) for fv, vx, y0, y1 in vertical for fh, x0, x1, hy in horizontal
                   if fv != fh and x0 < vx < x1]
        touching: dict[int, list[int]] = {}
        for n, slots in enumerate(meeting):
            for slot in set(slots):
                touching.setdefault(slot, []).append(n)
        heights = [-1e9, 1e9] + list(range(couples)) + [couples + 1 + k for k in range(kids)]

        def crossed(pairs) -> int:
            return sum(1 for n in pairs if heights[meeting[n][0]] < heights[meeting[n][2]] < heights[meeting[n][1]])

        best = crossed(range(len(meeting)))
        for _pass in range(30):
            better = False
            for order, first in ((couple_order, 2), (kid_order, 2 + couples)):
                for k in range(len(order) - 1):
                    a, b = first + order[k], first + order[k + 1]
                    pairs = set(touching.get(a, ())) | set(touching.get(b, ()))
                    was = crossed(pairs)
                    order[k], order[k + 1] = order[k + 1], order[k]
                    heights[a], heights[b] = heights[b], heights[a]
                    now = best - was + crossed(pairs)
                    if now < best:
                        best, better = now, True
                    else:
                        order[k], order[k + 1] = order[k + 1], order[k]
                        heights[a], heights[b] = heights[b], heights[a]
            if not better:
                break
        for f in fams:
            lanes.index[f.id] = kid_order.index(lanes.index[f.id])
            if f.id in lanes.couple_index:
                lanes.couple_index[f.id] = couple_order.index(lanes.couple_index[f.id])


def _leave_y(lay: "Layout", q: int, at: float) -> float:
    """Where a line leaving the bottom of q's portrait at x `at` starts, on its edge."""
    return _edge_y(lay, q, at, bottom=True)


def _arrive_y(lay: "Layout", q: int, at: float) -> float:
    """Where a line reaching the top of q's portrait at x `at` ends, on its edge."""
    return _edge_y(lay, q, at, bottom=False)


CLEAR = 7                                # how far a line keeps from a frame it passes


def _nearest_free(x: float, row: list) -> float:
    """The point a whole number of pixels from x, nearest it (the right first when both are as near),
    inside none of the open spans in `row` -- found span by span, not pixel by pixel."""
    def steps(sign: int) -> int:
        d = 0
        while True:
            at = x + sign * d
            inside = [hi if sign > 0 else lo for lo, hi in row if lo < at < hi]
            if not inside:
                return d
            edge = max(inside) if sign > 0 else min(inside)
            d = max(d + 1, math.ceil(abs(edge - x) - 1e-9))
    right, left = steps(1), steps(-1)
    return x + right if right <= left else x - left


def _route(lay: "Layout", at: float, y0: float, y1: float, jogs: dict, back: bool = False,
           start: float | None = None) -> list[list]:
    """A line down from (at, y0) to y1 that never runs through a frame: straight while nothing is
    in the way; at each row of frames in the way, it steps sideways just above that row into the
    nearest gap between its frames and carries on down; a line that must end at a frame (`back`)
    steps back just above y1.  Each step in a gap has a height of its own.  `start` is where the
    drawn line begins when that is above y0 (the curve of a circle's frame).  Packed tightest
    (lines_behind), straight: it passes behind the portraits."""
    if lines_behind(lay):
        return [[(at, start if start is not None else y0), (at, y1)]]
    frames = lay.spans()
    legs: list[list] = []
    x, y, low = at, (start if start is not None else y0), y0
    for _step in range(40):
        blocking = [fy for fx0, fx1, fy in frames
                    if fx0 - CLEAR < x < fx1 + CLEAR and fy < y1 - 1 and fy + NODE_H > low + 1]
        if not blocking:
            break
        top = min(blocking)
        row = [(fx0 - CLEAR, fx1 + CLEAR) for fx0, fx1, fy in frames if fy < top + NODE_H and fy + NODE_H > top]
        gap = _nearest_free(x, row)
        k = jogs.get(round(top), 0)
        jogs[round(top)] = k + 1
        side = max(low + 4, top - 12 - 5 * (k % 3))
        legs += [[(x, y), (x, side)], [(x, side), (gap, side)]]
        x, y, low = gap, side, side
    if back and x != at:
        k = jogs.get(round(y1), 0)
        jogs[round(y1)] = k + 1
        up = max(low + 4, y1 - 12 - 5 * (k % 3))
        return legs + [[(x, y), (x, up)], [(x, up), (at, up)], [(at, up), (at, y1)]]
    return legs + [[(x, y), (x, y1)]]


def _tidy(pts: list) -> list:
    """A line's points with no repeats and no point in the middle of a straight run."""
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return [p for k, p in enumerate(out) if k in (0, len(out) - 1)
            or not (out[k - 1][0] == p[0] == out[k + 1][0] or out[k - 1][1] == p[1] == out[k + 1][1])]


def _go_round(lay: "Layout", rects: list, pt: tuple, q: int | None, lane: float, span: tuple,
              from_portrait: bool) -> list | None:
    """A line between q's portrait (pt, on its top or bottom) and a family's children's line (at `lane`,
    drawn across `span`) that crosses no portrait: straight up or down from the portrait to a clear level,
    along it, and up or down again to the children's line, which reaches out to meet it.  The points from
    the portrait (`from_portrait`) or from the children's line; None when no such way is clear."""
    if lines_behind(lay):                   # packed tightest: no going round, the line goes behind
        return None
    px, py = pt
    obst = [r for r in rects if not (r[0] <= px <= r[1] and r[2] <= py <= r[3])]     # q's own frame
    # From a portrait's bottom edge, or a couple's line (no portrait), down; from a top edge, up.
    way = 1 if q is None or abs(py - _leave_y(lay, q, px)) < 0.5 else -1

    across: dict[float, list] = {}          # x -> the frames' spans down it; y -> the frames' spans along it
    along: dict[float, list] = {}

    def v_clear(x: float, a: float, b: float) -> bool:
        lo, hi = (a, b) if a < b else (b, a)
        spans = across.get(x)
        if spans is None:
            spans = across[x] = [(r[2], r[3]) for r in obst if r[0] < x < r[1]]
        return not any(s0 < hi and lo < s1 for s0, s1 in spans)

    def h_clear(y: float, a: float, b: float) -> bool:
        lo, hi = (a, b) if a < b else (b, a)
        spans = along.get(y)
        if spans is None:
            spans = along[y] = [(r[0], r[1]) for r in obst if r[2] < y < r[3]]
        return not any(s0 < hi and lo < s1 for s0, s1 in spans)

    # (Below the children's line too: in tightly packed trees the clear way may pass under them and come
    # up beside their block.)
    low, high = min(py, lane) - NODE_H, max(py, lane) + 3 * NODE_H
    levels = {lane} | {v for r in obst for v in (r[2] - 4, r[3] + 4) if low < v < high}
    levels = sorted((h for h in levels if (h - py) * way > 0), key=lambda h: (abs(h - lane), h))
    near = sorted({px, span[0], span[1]} | {v for r in obst if r[2] < lane + NODE_H and r[3] > lane - NODE_H
                                             for v in (r[0] - 4, r[1] + 4)},
                  key=lambda v: (max(span[0] - v, v - span[1], 0.0), abs(v - px)))
    near = [v for v in near if h_clear(lane, v, min(max(v, span[0]), span[1]))][:12]
    for h in levels:
        if not v_clear(px, py, h):
            continue
        for xc in near:
            if h_clear(h, px, xc) and v_clear(xc, h, lane):
                pts = [(px, py), (px, h), (xc, h), (xc, lane)]
                out = [pts[0]]
                for p in pts[1:]:
                    if p != out[-1]:
                        out.append(p)
                # No point in the middle of a straight run.
                out = [p for k, p in enumerate(out) if k in (0, len(out) - 1)
                       or not (out[k - 1][0] == p[0] == out[k + 1][0] or out[k - 1][1] == p[1] == out[k + 1][1])]
                return out if from_portrait else out[::-1]
    # No one level will do: down to a level, across to a gap between the portraits, along that gap to
    # another level, and across to the children's line (Packed families nestles families in tight).
    highs = [h for h in levels if v_clear(px, py, h)][:6]
    lows = [h for h in sorted(levels, key=lambda h: abs(h - lane))
            if any(v_clear(xl, h, lane) for xl in near)][:6]
    gaps = sorted({v for r in obst if r[2] < max(py, lane) + NODE_H and r[3] > min(py, lane) - NODE_H
                   for v in (r[0] - 4, r[1] + 4)}, key=lambda v: abs(v - px))[:12]
    best = None
    for h1 in highs:
        for xc in gaps:
            if not h_clear(h1, px, xc):
                continue
            for h2 in lows:
                if not v_clear(xc, h1, h2):
                    continue
                for xl in near:
                    if h_clear(h2, xc, xl) and v_clear(xl, h2, lane):
                        length = abs(h1 - py) + abs(xc - px) + abs(h2 - h1) + abs(xl - xc) + abs(lane - h2)
                        if best is None or length < best[0]:
                            best = (length, [(px, py), (px, h1), (xc, h1), (xc, h2), (xl, h2), (xl, lane)])
    if best is None:
        return None
    out = _tidy(best[1])
    return out if from_portrait else out[::-1]


def lines(lay: Layout) -> list[tuple[str, list[tuple[float, float]], int, str]]:
    """Every connector as (colour, polyline, family id, which piece it is), all in the pairing's
    one colour (the owner: the siblings' and the parents' connector lines "should be the same
    color").  Two parents drop to their couple's line; from its middle a stem falls to the
    children's line, and each child hangs straight down from that (babies born together from one
    point that opens into a triangle).  A lone parent drops straight to the children's line.
    Pieces the player dragged are where they put them (still joined, still touching the
    portraits), and no two families' pieces lie on each other."""
    people = lay.village.people
    # [colour, points, family id, piece, {end: (side, villager) of a portrait it is on},
    #  {end: the piece that end is attached to}]
    drawn: list[list] = []
    jogs: dict = {}

    def add(points: list, piece: str, anchors: dict | None = None, up: dict | None = None) -> str:
        if fam.onward:
            # The pieces drawn above a page break are named apart from the same family's on the page its
            # children are on, so dragging one never moves the other (the owner, 2026-10-10).
            piece = ONWARD_PIECE + piece
            up = {end: ONWARD_PIECE + name for end, name in (up or {}).items()}
        drawn.append([fam.colour, points, fam.id, piece, anchors or {}, up or {}])
        return piece

    def cx(pid: int) -> float:
        return lay.x[pid] + NODE_W / 2

    def key(pid: int) -> str:
        return entry_key(lay.village, people[pid])

    clusters = lay.edits.positioning in ("packed_families", "packed_generations")
    # (Lines behind the portraits take the straight way, never the ways kept round them.)
    behind_all = lines_behind(lay)
    packed = lay.edits.positioning == "packed_families" and lay.edits.packing > 0 and not behind_all
    rects = None
    frames = None                       # (lines behind: every frame, for keeping joints off strangers)
    for fam in lay.families:
        kids = [c for c in fam.children if c in lay.x and c not in fam.away]
        away = [c for c in fam.away if c in lay.x]
        onward = bool(fam.onward) and not kids and not away
        if not kids and not away and not onward and fam.children:
            continue
        lane = fam.lane_y
        row = min(lay.y[c] for c in kids) if kids else lane + LANE_BOTTOM
        parents = [q for q in (fam.father, fam.mother) if q is not None and q in lay.x and q not in fam.far]
        far = [q for q in fam.far if q in lay.x]

        def planned(x0: float, y0: float, end: float, fam=fam) -> list:
            """The way kept for this family's line (Family.way), from (x0, y0) to the children's line at `end`."""
            way = fam.way
            return _tidy([(x0, y0), (x0, way[1][1])] + way[1:] + [(way[-1][0], end)])
        groups: dict[object, list[int]] = {}
        for c in kids:
            groups.setdefault(people[c].litter or ("one", c), []).append(c)
        def clearest_down(c: int, at: float, lane: float) -> float:
            """Where along child c's portrait their line from the children's line comes down with the
            fewest steps aside: `at` (their middle) when its way is clear."""
            xs = [px for px, _py in lay.frame_points(c)]
            low, high = min(xs) + 12, max(xs) - 12

            def steps(x: float) -> int:
                return len(_route(lay, x, lane, lay.y[c], dict(jogs), back=True))
            best, fewest = at, steps(at)
            for k in range(1, int((high - low) / 4) + 1):
                if fewest == 1:
                    break
                for x in (at + 4 * k, at - 4 * k):
                    if low <= x <= high and steps(x) < fewest:
                        best, fewest = x, steps(x)
            return best

        hang = [sum(cx(c) for c in members) / len(members) if len(members) > 1
                else clearest_down(members[0], cx(members[0]), fam.lane_y) for members in groups.values()]
        target = "couple" if len(parents) == 2 else "lane"

        def clearest(q: int, at: float, end: float) -> float:
            """Where along q's portrait the line to `end` leaves with the fewest steps aside (the
            owner: "minimize line bumps"): `at` when its way is clear, else the nearest clearer place."""
            xs = [px for px, _py in lay.frame_points(q)]
            low, high = min(xs) + 12, max(xs) - 12

            def steps(x: float) -> int:
                if lay.y[q] > end:
                    return len(_route(lay, x, end, _arrive_y(lay, q, x), dict(jogs), back=True))
                return len(_route(lay, x, lay.y[q] + NODE_H, end, dict(jogs), start=_leave_y(lay, q, x)))
            best, fewest = at, steps(at)
            for k in range(1, int((high - low) / 4) + 1):
                if fewest == 1:
                    break
                for x in (at + 4 * k, at - 4 * k):
                    if low <= x <= high and steps(x) < fewest:
                        best, fewest = x, steps(x)
            return best

        def leave(q: int, end: float) -> float:
            """The parent's line to `end` (the couple's line, or for a lone parent the children's);
            where it arrives.  A parent below it (put in a later generation by the player) leaves
            from the top of their frame and goes up."""
            at = clearest(q, fam.drops[q], end)
            if packed and target == "lane" and lay.y[q] + NODE_H < end and hang:
                # Packed families: the children's block may stand off to one side; the line goes round.
                nonlocal rects
                if rects is None:
                    rects = [(lo - CLEAR, hi + CLEAR, top - CLEAR, top + NODE_H + CLEAR) for lo, hi, top in lay.spans()]
                pts = planned(at, _leave_y(lay, q, at), end) if fam.way else \
                    _go_round(lay, rects, (at, _leave_y(lay, q, at)), q, end, (min(hang), max(hang)), True)
                if pts:
                    names = [f"from {key(q)} {k}" for k in range(len(pts) - 1)]
                    for k, leg in enumerate(zip(pts, pts[1:])):
                        add(list(leg), names[k], {0: ("bottom", q)} if k == 0 else None,
                            {1: names[k + 1] if k < len(names) - 1 else target})
                    return pts[-1][0]
            if lay.y[q] > end:
                legs = _route(lay, at, end, _arrive_y(lay, q, at), jogs, back=True)
                names = [f"from {key(q)} {k}" for k in range(len(legs))]
                for k, leg in enumerate(legs):
                    add(leg, names[k], {1: ("top", q)} if k == len(legs) - 1 else None,
                        {0: names[k - 1] if k else target})
                return at
            legs = _route(lay, at, lay.y[q] + NODE_H, end, jogs, start=_leave_y(lay, q, at))
            names = [f"from {key(q)} {k}" for k in range(len(legs))]
            for k, leg in enumerate(legs):
                add(leg, names[k], {0: ("bottom", q)} if k == 0 else None,
                    {1: names[k + 1] if k < len(legs) - 1 else target})
            return legs[-1][-1][0]

        if not fam.children:
            # A couple with no child (a spouse lost before any child): only the couple's line, so they read as
            # husband and wife.
            if len(parents) == 2 and fam.couple_y:
                ends = [leave(q, fam.couple_y) for q in parents]
                add([(min(ends), fam.couple_y), (max(ends), fam.couple_y)], "couple")
            continue
        if onward:
            # The children are on a later page: the couple joined as any couple is, and from the couple's
            # line, where its words have room (_place_onward; a lone parent: from them), one line down to
            # where the words say which page.
            if len(parents) == 2:
                couple = fam.couple_y
                ends = [leave(q, couple) for q in parents]
                add([(min(ends), couple), (max(ends), couple)], "couple")
                legs = _route(lay, min(max(fam.stem_x, min(ends)), max(ends)), couple, lane, jogs)
                names = ["stem"] + [f"stem {k}" for k in range(1, len(legs))]
                for k, leg in enumerate(legs):
                    add(leg, names[k], up={0: names[k - 1] if k else "couple", **({1: names[k + 1]} if k < len(legs) - 1 else {})})
            elif parents:
                leave(parents[0], lane)
            continue
        if len(parents) == 2:
            couple = fam.couple_y
            ends = [leave(q, couple) for q in parents]
            add([(min(ends), couple), (max(ends), couple)], "couple")
            stem = sum(ends) / 2
            legs = [[(stem, couple), (stem, lane)]]
            if packed and fam.way:          # the way kept for it when the families were packed
                pts = planned(stem, couple, lane)
                legs = [list(leg) for leg in zip(pts, pts[1:])]
            elif packed:                    # the children may stand lower down or to one side
                if rects is None:
                    rects = [(lo - CLEAR, hi + CLEAR, top - CLEAR, top + NODE_H + CLEAR) for lo, hi, top in lay.spans()]
                pts = _go_round(lay, rects, (stem, couple), None, lane,
                                (min(hang), max(hang)) if hang else (stem, stem), True)
                legs = [list(leg) for leg in zip(pts, pts[1:])] if pts else _route(lay, stem, couple, lane, jogs)
            if len(legs) == 1:
                add(legs[0], "stem", up={0: "couple", 1: "lane"})
            else:                           # Packed families: the children may stand lower down, round others
                names = ["stem"] + [f"stem {k}" for k in range(1, len(legs))]
                for k, leg in enumerate(legs):
                    add(leg, names[k], up={0: names[k - 1] if k else "couple",
                                           1: names[k + 1] if k < len(legs) - 1 else "lane"})
            stem = legs[-1][-1][0]
            xs = hang + [stem]
        else:
            xs = hang + [leave(q, lane) for q in parents]
        add([(min(xs), lane), (max(xs), lane)], "lane")
        # Packed families: a parent standing in another cluster, and children standing with a
        # partner in another, are joined to the children's line by a line that goes round the portraits.
        if far or away:
            if rects is None:
                rects = [(lo - CLEAR, hi + CLEAR, top - CLEAR, top + NODE_H + CLEAR) for lo, hi, top in lay.spans()]
            span = (min(xs), max(xs))
            for q in far:
                at = fam.drops[q]
                below = lay.y[q] + NODE_H / 2 < lane
                start = (at, _leave_y(lay, q, at) if below else _arrive_y(lay, q, at))
                pts = _go_round(lay, rects, start, q, lane, span, from_portrait=True)
                if pts is None:             # nothing clear: the way the tree has always gone
                    leave(q, lane)
                    continue
                names = [f"from {key(q)} {k}" for k in range(len(pts) - 1)]
                for k, leg in enumerate(zip(pts, pts[1:])):
                    add(list(leg), names[k], {0: ("bottom" if below else "top", q)} if k == 0 else None,
                        {1: names[k + 1] if k < len(names) - 1 else "lane"})
            for c in away:
                at = cx(c)
                above = lay.y[c] + NODE_H / 2 < lane
                end = (at, _leave_y(lay, c, at) if above else _arrive_y(lay, c, at))
                pts = _go_round(lay, rects, end, c, lane, span, from_portrait=False)
                if pts is None:
                    legs = _route(lay, at, lane, lay.y[c], jogs, back=True)
                    legs[-1][-1] = (legs[-1][-1][0], end[1])
                    pts = [legs[0][0]] + [leg[-1] for leg in legs]
                names = [f"to {key(c)} {k}" for k in range(len(pts) - 1)]
                for k, leg in enumerate(zip(pts, pts[1:])):
                    add(list(leg), names[k], {1: ("bottom" if above else "top", c)} if k == len(names) - 1 else None,
                        {0: names[k - 1] if k else "lane"})
        for members, apex in zip(groups.values(), hang):
            first = key(members[0])
            if len(members) == 1:
                c = members[0]
                legs = _route(lay, apex, lane, lay.y[c], jogs, back=True)
                (ex, _ey) = legs[-1][-1]            # the last stretch ends on the frame as drawn
                legs[-1][-1] = (ex, _arrive_y(lay, c, ex))
                names = [f"to {first} {k}" for k in range(len(legs))]
                for k, leg in enumerate(legs):
                    add(leg, names[k], {1: ("top", c)} if k == len(legs) - 1 else None,
                        {0: names[k - 1] if k else "lane"})
                continue
            tip, base = row - LANE_BOTTOM + 14, row - 8
            if clusters:
                # Each family's babies where they are: a block's lower row may hold them.
                own = min(lay.y[c] for c in members)
                tip, base = own - LANE_BOTTOM + 14, own - 8
                if own > row + 1 or (lay.edits.positioning == "packed_generations"
                                     and own > lay.tops[people[members[0]].generation] + 1):
                    tip = own - SUBGAP + 14
            elif row > lay.tops[people[members[0]].generation]:       # babies in a lower row
                tip = row - SUBGAP + 14
            if behind_all:              # their point never behind a stranger (_clear_joints)
                if frames is None:
                    frames = _frames(lay)
                family = {fam.father, fam.mother, *fam.children}
                while abs(tip - lane) > 8 and _behind_stranger(lay, frames, family, apex, tip):
                    tip += 2 if lane > tip else -2       # towards the children's line
            legs = _route(lay, apex, lane, tip, jogs, back=True)
            names = [f"to {first} {k}" for k in range(len(legs))]
            for k, leg in enumerate(legs):
                add(leg, names[k], up={0: names[k - 1] if k else "lane"})
            for c in members:
                add([(apex, tip), (cx(c), base), (cx(c), _arrive_y(lay, c, cx(c)))], f"leg {key(c)}",
                    {2: ("top", c)}, {0: names[-1]})
            add([(min(cx(c) for c in members), base), (max(cx(c) for c in members), base)], f"bar {first}")
    families = {f.id: family_key(lay.village, f) for f in lay.families}
    for s in list(drawn):
        shift = lay.edits.line_moves.get(f"{families[s[2]]}|{s[3]}")
        if shift and len(s[1]) == 2 and not s[3].startswith("bar "):
            (x0, y0), (x1, y1) = s[1]
            upright = x0 == x1 and y0 != y1
            if not isinstance(shift, list):     # across itself: an upright piece sideways, else up or down
                shift = [shift, 0.0] if upright else [0.0, shift]
            elif not lay.edits.diagonal_lines:  # only across itself, so every line stays square
                shift = [shift[0], 0.0] if upright else [0.0, shift[1]]
            _move_piece(drawn, s, *shift, lay=lay)
    widths = {f.id: lay.edits.family_lines.get(families[f.id], {}).get("width", lay.edits.line_width)
              for f in lay.families}
    behind = lines_behind(lay)
    free = {(s[2], s[3]) for s in drawn if f"{families[s[2]]}|{s[3]}" in lay.edits.free_lines
            and f"{families[s[2]]}|{s[3]}" in lay.edits.line_moves}
    if behind:
        _clear_joints(drawn, lay, widths, free)
    _fit(drawn)
    for _pass in range(2):              # last: never two lines on each other, whatever moved them
        _separate(drawn, lay, widths, free)
        _fit(drawn)
    for _pass in range(3 if behind else 0):
        # Lines behind: a joint the separating put behind a stranger moved off them again where the 1 px
        # room is kept, and the room kept again after (the room is the rule; the joints the most it allows).
        before = [list(s[1]) for s in drawn]
        _clear_joints(drawn, lay, widths, free)
        _fit(drawn)
        _separate(drawn, lay, widths, free)
        _fit(drawn)
        if [s[1] for s in drawn] == before:
            break
    return [(colour, points, fid, piece) for colour, points, fid, piece, _anchors, _up in drawn]


def _behind_stranger(lay: "Layout", frames: dict, members: set, x: float, y: float) -> bool:
    """Whether (x, y) -- a joint of a family's lines -- lies behind (or within 2 of) the frame of a
    portrait not of that family (`frames`: each portrait's frame box and outline)."""
    for q, (x0, y0, x1, y1, pts) in frames.items():
        if q not in members and x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1 and any(
                inside(pts, x + dx, y + dy) for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))):
            return True
    return False


def _frames(lay: "Layout") -> dict:
    out = {}
    for q in lay.x:
        pts = lay.frame_points(q)
        xs, ys = [px for px, _py in pts], [py for _px, py in pts]
        out[q] = (min(xs), min(ys), max(xs), max(ys), pts)
    return out


def _clear_joints(drawn: list, lay: "Layout", widths: dict | None = None, free: set = frozenset()) -> None:
    """Lines behind the portraits (lines_behind) pass behind anyone's portrait -- but where a family's
    lines join (a parent's or a child's line meeting the couple's or the children's line) never behind a
    portrait not of the family, where the line would look as if it came from that stranger (the owner's
    tree: Alawa's line seemed to come out of Layla).  Each couple's and children's line with a joint
    behind a stranger is moved up or down -- never past what hangs from it -- to the nearest place where
    none is, its lines kept joined (_move_piece); left as it is when nowhere near is clear."""
    frames = _frames(lay)
    fams = {f.id: f for f in lay.families}
    for s in drawn:
        if s[3] not in ("couple", "lane") or len(s[1]) != 2 or not _same(s[1][0][1], s[1][1][1]) \
                or (s[2], s[3]) in free:
            continue
        f = fams.get(s[2])
        if f is None:
            continue
        members = {f.father, f.mother, *f.children}
        attached = [(o, end) for o in drawn if o is not s and o[2] == s[2] for end, name in o[5].items() if name == s[3]]

        def joints() -> list:
            return list(s[1]) + [o[1][end] for o, end in attached]
        if not any(_behind_stranger(lay, frames, members, x, y) for x, y in joints()):
            continue
        y = s[1][0][1]
        lo, hi = -math.inf, math.inf                # never past the far end of a line hanging from it
        for o, end in attached:
            other = o[1][1 - end] if len(o[1]) == 2 else o[1][0 if end else -1]
            if other[1] < y - 0.5:
                lo = max(lo, other[1] + 1)
            elif other[1] > y + 0.5:
                hi = min(hi, other[1] - 1)
        x0, x1 = sorted((s[1][0][0], s[1][1][0]))
        # (Keeping LINE_GAP between its drawn edge and any level line alongside, each line's width counted.)
        width_of = (widths or {}).get
        level = [(o[1][0][1], (width_of(s[2], LINE_WIDTH) + width_of(o[2], LINE_WIDTH)) / 2 + LINE_GAP)
                 for o in drawn if o is not s and (o[2] != s[2] or o[3] != s[3]) and len(o[1]) == 2
                 and _same(o[1][0][1], o[1][1][1]) and min(o[1][0][0], o[1][1][0]) < x1 - 0.5
                 and max(o[1][0][0], o[1][1][0]) > x0 + 0.5]
        xs = [x for x, _y in joints()]
        for d in sorted(range(-200, 201), key=abs):
            ny = y + d
            if d and lo <= ny <= hi and all(abs(ny - v) >= need for v, need in level) \
                    and not any(_behind_stranger(lay, frames, members, x, ny) for x in xs):
                _move_piece(drawn, s, 0.0, float(d), lay=lay)
                break


def _fit(drawn: list) -> None:
    """Each straight piece that others are attached to runs exactly between the outermost of them
    (and its own attached ends): no stub left sticking out past a line moved inward, and no gap."""
    for s in drawn:
        if len(s[1]) != 2 or s[1][0] == s[1][1]:
            continue
        a, b = s[1]
        points = [o[1][end] for o in drawn if o is not s and o[2] == s[2]
                  for end, name in o[5].items() if name == s[3]]
        if not points:
            continue
        points += [s[1][end] for end in (0, 1) if end in s[4] or end in s[5]]
        ts = [_along(pt, a, b) for pt in points]
        lo, hi = min(ts), max(ts)
        s[1] = [(a[0] + lo * (b[0] - a[0]), a[1] + lo * (b[1] - a[1])),
                (a[0] + hi * (b[0] - a[0]), a[1] + hi * (b[1] - a[1]))]


def _along(pt: tuple, a: tuple, b: tuple) -> float:
    """Where pt is along the piece from a to b: 0 at a, 1 at b."""
    (px, py), (ax, ay), (bx, by) = pt, a, b
    length = (bx - ax) ** 2 + (by - ay) ** 2
    return 0.0 if length < 1e-9 else ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length


def _onto(pt: tuple, piece: list, mover: str | None = None) -> tuple:
    """pt slid onto a straight piece's line (the piece made longer when it lands past an end)."""
    a, b = piece[1][0], piece[1][-1]
    t = _along(pt, a, b)
    if a == b:                                  # no length: a level line, stretched to reach it
        landed = (pt[0], a[1])
        if len(piece[1]) == 2:
            piece[1] = [(min(a[0], landed[0]), a[1]), (max(a[0], landed[0]), a[1])]
        return landed
    # Past an end the piece is made longer -- unless that end is held (on a portrait or another piece):
    # then the point stops at it, so the piece never comes away from what holds it.
    held = [end for end in (0, 1) if end in piece[4] or (end in piece[5] and piece[5][end] != mover)] \
        if len(piece) > 5 else []
    if t < 0 and 0 in held or t > 1 and 1 in held:
        t = min(max(t, 0.0), 1.0)
    landed = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    if t < 0 and len(piece[1]) == 2:
        piece[1] = [landed, b]
    elif t > 1 and len(piece[1]) == 2:
        piece[1] = [a, landed]
    return landed


def _move_piece(drawn: list, s: list, dx: float, dy: float, lay: Layout | None = None) -> None:
    """A straight piece dragged (dx, dy), its lines kept whole (the owner: "Keep. The. Lines.
    Connected. No. matter. How. they. are. moved."): an end attached to another piece slides along
    that piece, an end on a portrait slides along the portrait's edge, and every piece attached to
    it follows, turning diagonal if it must (the owner: "diagonal is ok")."""
    pieces = {(o[2], o[3]): o for o in drawn}
    old = list(s[1])
    new = []
    for end, (x, y) in enumerate(old):
        moved = (x + dx, y + dy)
        if end in s[4] and lay is not None:
            side, q = s[4][end]
            xs = [px for px, _py in lay.frame_points(q)]
            lo, hi = min(xs) + 12, max(xs) - 12
            nx = min(max(moved[0], lo), hi) if lo < hi else (min(xs) + max(xs)) / 2
            moved = (nx, _leave_y(lay, q, nx) if side == "bottom" else _arrive_y(lay, q, nx))
        elif end in s[5] and (s[2], s[5][end]) in pieces:
            moved = _onto(moved, pieces[(s[2], s[5][end])], s[3])
        new.append(moved)
    s[1] = new
    _follow(drawn, s, old, new, set())


def _follow(drawn: list, s: list, old: list, new: list, seen: set) -> None:
    """The pieces attached to s, which moved from `old` to `new`, keep their ends on it: each end
    stays the same way along it, and whatever is attached to them follows in turn."""
    seen = seen | {s[3]}
    for other in drawn:
        if other is s or other[2] != s[2] or other[3] in seen:
            continue
        before = list(other[1])
        points = list(other[1])
        for end, name in other[5].items():
            if name == s[3]:
                t = _along(points[end], old[0], old[-1])
                points[end] = (new[0][0] + t * (new[-1][0] - new[0][0]), new[0][1] + t * (new[-1][1] - new[0][1]))
        if points != before:
            other[1] = points
            _follow(drawn, other, before, points, seen)


LINE_GAP = 1.0                          # the least room between two lines' drawn edges (the owner)


def _same(a: float, b: float) -> bool:
    """Two places one (a run's ends worked out two ways differ in the last digits)."""
    return abs(a - b) < 1e-6


def _separate(drawn: list, lay: Layout | None = None, widths: dict | None = None,
              free: set = frozenset()) -> None:
    """No two lines lie on top of each other (the owner: "lines should try not to overlap exactly ever.
    (min 1 pixel distance between them in any position)"): two straight runs side by side -- two
    families', or one family's that do not start from one point -- with less than LINE_GAP between their
    drawn edges (each line's width counted) along any stretch they share: one moves the least it can, an
    upright one sideways, a level one up or down, keeping its line whole as any dragged piece does
    (_move_piece).  Lines crossing are not touched.  Where it can, a run moves where it goes through no
    portrait it did not go through already -- and, with the lines behind the portraits, puts no joint
    behind a stranger's portrait (_clear_joints)."""
    widths = widths or {}
    width_of = lambda r: widths.get(r[2], LINE_WIDTH)      # noqa: E731
    behind = lay is not None and lines_behind(lay)
    frames = _frames(lay) if lay is not None else {}
    fams = {f.id: f for f in lay.families} if lay is not None else {}

    def axis_of(r) -> int | None:
        pts = r[1]
        # (A twins' bar is held by its legs; a piece put down with Alt stays where the player put it.)
        if len(pts) != 2 or r[3].startswith("bar ") or (r[2], r[3]) in free:
            return None
        if _same(pts[0][0], pts[1][0]) and not _same(pts[0][1], pts[1][1]):
            return 0                        # upright: placed across by x
        if _same(pts[0][1], pts[1][1]) and not _same(pts[0][0], pts[1][0]):
            return 1                        # level: placed by y
        return None

    def runs_of(r) -> list:
        """(axis, place across, from, to) of each straight stretch of a piece (a twins' leg has three)."""
        out = []
        for a, b in zip(r[1], r[1][1:]):
            if _same(a[0], b[0]) and not _same(a[1], b[1]):
                out.append((0, a[0], min(a[1], b[1]), max(a[1], b[1])))
            elif _same(a[1], b[1]) and not _same(a[0], b[0]):
                out.append((1, a[1], min(a[0], b[0]), max(a[0], b[0])))
        return out

    def shared_start(a, b) -> bool:
        """One family's two pieces from one point (two children's lines from the one place on the
        children's line, the stem and a leg): one path by design."""
        return a[2] == b[2] and any(abs(p[0] - q[0]) < 0.5 and abs(p[1] - q[1]) < 0.5
                                    for p in (a[1][0], a[1][-1]) for q in (b[1][0], b[1][-1]))

    def clashes(r, axis: int, at: float, lo: float, hi: float, index: dict) -> bool:
        need = width_of(r) / 2 + LINE_GAP
        for key in range(int(at // 8) - 2, int(at // 8) + 3):
            for o, (ax, oat, olo, ohi) in index.get((axis, key), ()):
                if o is r or (o[2] == r[2] and o[3] == r[3]):
                    continue
                if abs(oat - at) < need + width_of(o) / 2 - 1e-6 and min(hi, ohi) - max(lo, olo) > 0.5 \
                        and not shared_start(r, o):
                    return True
        return False

    def through(r, axis: int, at: float, lo: float, hi: float) -> set:
        """The portraits a run would go through (their frames' boxes, a little inside)."""
        out = set()
        for q, (x0, y0, x1, y1, _pts) in frames.items():
            if axis == 0 and x0 + 2 < at < x1 - 2 and min(hi, y1 - 2) > max(lo, y0 + 2):
                out.add(q)
            elif axis == 1 and y0 + 2 < at < y1 - 2 and min(hi, x1 - 2) > max(lo, x0 + 2):
                out.add(q)
        return out

    def stranger_joint(r, axis: int, shift: float) -> bool:
        f = fams.get(r[2])
        if f is None:
            return False
        members = {f.father, f.mother, *f.children}
        _a, at, lo, hi = runs_of(r)[0]
        joints = [r[1][0], r[1][-1]] + [p for o in drawn if o is not r and o[2] == r[2] for p in (o[1][0], o[1][-1])
                                        if abs(p[axis] - at) < 0.5 and lo - 0.5 <= p[1 - axis] <= hi + 0.5]
        return any(_behind_stranger(lay, frames, members, x + (shift if axis == 0 else 0.0),
                                    y + (shift if axis == 1 else 0.0)) for x, y in joints)

    def clashing(r, axis: int, at: float, lo: float, hi: float, index: dict) -> list:
        """The runs r is too close to (each piece once, in the order drawn)."""
        need, out = width_of(r) / 2 + LINE_GAP, []
        for key in range(int(at // 8) - 2, int(at // 8) + 3):
            for o, (_ax, oat, olo, ohi) in index.get((axis, key), ()):
                if o is not r and not (o[2] == r[2] and o[3] == r[3]) and o not in out \
                        and abs(oat - at) < need + width_of(o) / 2 - 1e-6 and min(hi, ohi) - max(lo, olo) > 0.5 \
                        and not shared_start(r, o):
                    out.append(o)
        return out

    def place(r, axis: int, index: dict) -> tuple:
        """(how far r moves across itself to be clear of every run near it, whether that place is fine: through
        no portrait it did not go through already, and -- lines behind -- no joint behind a stranger).  The
        nearest fine place within 60, else the nearest clear one (not fine); (None, False) when none is."""
        _ax, at, lo, hi = runs_of(r)[0]
        was = through(r, axis, at, lo, hi) if not behind and frames else set()
        best = None
        # (The portraits r's length passes along, found once -- only where across moves with a shift: through()'s
        # answer for any spot, testing only these.)
        along: list = []

        def through_at(spot: float) -> set:
            if not along:
                along.append([(q, x0, x1) if axis == 0 else (q, y0, y1) for q, (x0, y0, x1, y1, _pts) in frames.items()
                              if (min(hi, y1 - 2) > max(lo, y0 + 2) if axis == 0 else min(hi, x1 - 2) > max(lo, x0 + 2))])
            return {q for q, a0, a1 in along[0] if a0 + 2 < spot < a1 - 2}
        # SPEED (v1.35.85), the same answer as clashes(): every shift below asks it of the same runs, only `at`
        # moving.  The runs it could ever find (in the buckets any shift's clashes() reads, overlapping r along
        # its length, not r's own piece, not from r's start) are gathered once by the bucket they are kept in,
        # each with how near it may come; a shift then reads exactly the buckets clashes() would.
        # Where it may go (`places`): just clear of each run near it, either side (the nearest first) -- read in
        # the same walk over the buckets.
        need = width_of(r) / 2 + LINE_GAP
        base = int(at // 8)
        near_runs: dict[int, list] = {}
        places = set()
        for key in range(base - 11, base + 12):
            nearby = base - 8 <= key <= base + 8
            for o, (_a, oat, olo, ohi) in index.get((axis, key), ()):
                if o is r or min(hi, ohi) - max(lo, olo) <= 0.5:
                    continue
                if nearby:
                    room = width_of(r) / 2 + width_of(o) / 2 + LINE_GAP + 0.01
                    places.update((oat - room - at, oat + room - at))
                if not (o[2] == r[2] and o[3] == r[3]) and not shared_start(r, o):
                    near_runs.setdefault(key, []).append((oat, need + width_of(o) / 2 - 1e-6))
        # Each bucket's runs in order across, with the farthest any of them may reach: a spot looks only at the
        # runs that could be near it (bisect), and tests each exactly as clashes() does.
        sorted_runs = {}
        for key, found in near_runs.items():
            found.sort()
            sorted_runs[key] = ([oat for oat, _reach in found], [reach for _oat, reach in found],
                                max(reach for _oat, reach in found))

        def clear_at(spot: float) -> bool:
            """not clashes(r, axis, spot, lo, hi, index), for a spot within 60 of `at`."""
            k = int(spot // 8)
            for key in range(k - 2, k + 3):
                found = sorted_runs.get(key)
                if found is None:
                    continue
                oats, reaches, widest = found
                i = bisect.bisect_left(oats, spot - widest - 1.0)
                while i < len(oats) and oats[i] <= spot + widest + 1.0:
                    if abs(oats[i] - spot) < reaches[i]:
                        return False
                    i += 1
            return True
        if behind:                          # (a joint may need a place a few pixels further on, clear of a stranger)
            places.update(float(d) for d in range(-24, 25))
        # (The nearest first; of two as near, right or down.)
        for shift in sorted((d for d in places if 0 < abs(d) <= 60), key=lambda d: (abs(d), -d)):
            if not clear_at(at + shift):
                continue
            if best is None:
                best = shift                    # the nearest clear place, whatever else
            if frames and not behind and not through_at(at + shift) <= was:
                continue
            if behind and stranger_joint(r, axis, shift):
                continue
            return shift, True
        return best, False

    near = None                             # after the first round: only runs near one that moved
    for _round in range(16):
        index: dict = {}
        for r in drawn:
            if (r[2], r[3]) in free:        # (put down with Alt: nothing moves for it, nor it for anything)
                continue
            for run in runs_of(r):
                index.setdefault((run[0], int(run[1] // 8)), []).append((r, run))
        before = {id(r): list(r[1]) for r in drawn}
        moved = False
        for r in drawn:
            if near is not None and not any((run[0], int(run[1] // 8)) in near for run in runs_of(r)):
                continue
            axis = axis_of(r)
            if axis is None:
                continue
            _ax, at, lo, hi = runs_of(r)[0]
            if not clashes(r, axis, at, lo, hi, index):
                continue
            best, fine = place(r, axis, index)
            if not fine:
                # Nowhere near is clear of portraits (or, lines behind, of strangers' portraits for its joints):
                # one it is too close to moves instead when that one can go somewhere fine.
                for o in clashing(r, axis, at, lo, hi, index):
                    if axis_of(o) == axis:
                        other, ok = place(o, axis, index)
                        if ok:
                            r, best = o, other
                            break
            if best is None:
                continue
            _move_piece(drawn, r, best if axis == 0 else 0.0, best if axis == 1 else 0.0, lay)
            moved = True
            for run in runs_of(r):          # where it is now, for the runs still to be looked at
                index.setdefault((run[0], int(run[1] // 8)), []).append((r, run))
        if not moved:
            break
        near = set()
        for r in drawn:
            if r[1] != before.get(id(r)):
                for pts in (before.get(id(r), []), r[1]):
                    for a, b in zip(pts, pts[1:]):
                        axis = 0 if _same(a[0], b[0]) else 1
                        at = a[axis]
                        near.update((axis, k) for k in range(int(at // 8) - 2, int(at // 8) + 3))


# ---------------------------------------------------------------------------
# Head pictures
# ---------------------------------------------------------------------------

def sheet_name(game: int, p: gen.Person) -> str | None:
    if p.upcoming or p.sex not in ("Male", "Female"):
        return None
    return SHEETS[game][0] if p.sex == "Male" else SHEETS[game][1]


def sheets_present(game: int, images: Path | None) -> dict[str, Path]:
    if images is None:
        return {}
    out = {}
    for name in SHEETS[game]:
        path = Path(images) / name
        if path.is_file():
            out[name] = path
    return out


_BOXES: dict[str, dict[int, tuple[int, int, int, int]]] = {}
DEFAULT_BOX = (0, 0, HEAD_W, FACE_H)


def head_boxes(path: Path) -> dict[int, tuple[int, int, int, int]]:
    """Each head row's visible pixels in the column the tree draws (x0, y0, x1, y1 inside the
    40x65 cell): the head is centred by what shows, not by the cell (A New Home's male faces fill
    only its top 25 rows).  Read with the standard library: an 8-bit RGBA PNG, not interlaced --
    the games' own head sheets; anything else gives no boxes (the tree then uses DEFAULT_BOX)."""
    key = str(path)
    if key in _BOXES:
        return _BOXES[key]
    out: dict[int, tuple[int, int, int, int]] = {}
    try:
        data = Path(path).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError
        at, idat, width, height = 8, [], 0, 0
        while at < len(data):
            length, kind = struct.unpack(">I4s", data[at:at + 8])
            body = data[at + 8:at + 8 + length]
            if kind == b"IHDR":
                width, height, depth, colour, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
                if depth != 8 or colour != 6 or interlace != 0:
                    raise ValueError
            elif kind == b"IDAT":
                idat.append(body)
            at += 12 + length
        raw = zlib.decompress(b"".join(idat))
        stride, bpp = width * 4, 4
        prev = bytearray(stride)
        alpha = []
        for row in range(height):
            filt = raw[row * (stride + 1)]
            line = bytearray(raw[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if filt == 1:
                    line[i] = (line[i] + a) & 255
                elif filt == 2:
                    line[i] = (line[i] + b) & 255
                elif filt == 3:
                    line[i] = (line[i] + ((a + b) >> 1)) & 255
                elif filt == 4:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                    line[i] = (line[i] + pred) & 255
            alpha.append(line[3::4])
            prev = line
        left = HEAD_FRAME * HEAD_W
        for r in range(height // HEAD_H):
            box = None
            for y in range(HEAD_H):
                row_alpha = alpha[r * HEAD_H + y][left:left + HEAD_W]
                xs = [x for x, value in enumerate(row_alpha) if value > 24]
                if xs:
                    _SPANS.setdefault((key, r), []).append((y, xs[0], xs[-1] + 1))
                    if box is None:
                        box = [xs[0], y, xs[-1] + 1, y + 1]
                    else:
                        box = [min(box[0], xs[0]), box[1], max(box[2], xs[-1] + 1), y + 1]
            if box is not None:
                out[r] = tuple(box)
    except (OSError, ValueError, zlib.error, struct.error, IndexError):
        out = {}
    _BOXES[key] = out
    return out


def face_box(present: dict, sheet: str | None, row: int | None) -> tuple[int, int, int, int]:
    if sheet in present and row is not None:
        return head_boxes(present[sheet]).get(row, DEFAULT_BOX)
    return DEFAULT_BOX


_SPANS: dict = {}                       # (head sheet, row) -> each visible pixel row's (y, left, right)
FACE_BANDS = 12                         # a face's outline, as this many bands across it, top to bottom


def face_bands(present: dict, sheet: str | None, row: int | None) -> list[tuple[int, int, int, int]]:
    """A face's visible pixels as bands (x0, y0, x1, y1 inside its cell), top to bottom: how wide the
    head is at each height -- what is kept inside a portrait's shape (face_anchor), not its box's empty
    corners."""
    box = face_box(present, sheet, row)
    spans = _SPANS.get((str(present[sheet]), row)) if sheet in present and row is not None else None
    if not spans:                       # no picture: the round stand-in _node draws (26 across, scaled), as bands
        x0, y0, x1, y1 = box
        r, mx, my = 26 / HEAD_SCALE, (x0 + x1) / 2, (y0 + y1) / 2
        out = []
        for k in range(FACE_BANDS):
            a, b = -1 + 2 * k / FACE_BANDS, -1 + 2 * (k + 1) / FACE_BANDS
            half = math.sqrt(max(0.0, 1 - min(a * a, b * b))) * r
            out.append((mx - half, my + a * r, mx + half, my + b * r))
        return out
    out = []
    step = max(1, -(-len(spans) // FACE_BANDS))
    for k in range(0, len(spans), step):
        part = spans[k:k + step]
        out.append((min(s[1] for s in part), part[0][0], max(s[2] for s in part), part[-1][0] + 1))
    return out


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


# ---------------------------------------------------------------------------
# Words around the tree
# ---------------------------------------------------------------------------

def generation_label(lay: Layout, g: int) -> list[str]:
    return [text for _part, text in label_lines(lay, g)]


def label_lines(lay: Layout, g: int) -> list[tuple[str, str]]:
    """The generation's label as drawn, line by line: (which part it is, its words).  The player's
    own lines are "custom<k>"; otherwise "first" (the number and the name) and the LABEL_PARTS
    lines, less the parts the player deleted (from this generation or from every one)."""
    if lay.edits.generations.get(str(g)):
        return [(f"custom{k}", text) for k, text in enumerate(lay.edits.generations[str(g)])]
    parts = default_label_parts(lay, g)
    shown = [part for part in parts
             if f"label:{g}:{part}" not in lay.edits.hidden and f"label:*:{part}" not in lay.edits.hidden]
    first = " ".join(parts[part] for part in ("number", "name") if part in shown)
    return ([("first", first)] if first else []) + [(part, parts[part]) for part in ("total", "living", "upcoming")
                                                     if part in parts and part in shown]


def default_generation_label(lay: Layout, g: int) -> list[str]:
    """The label the tree draws when the player has written none of their own."""
    return [text for _part, text in label_lines(replace(lay, edits=replace(lay.edits, generations={})), g)]


def generation_number(lay: Layout, g: int) -> str:
    return gen.roman(g) if lay.edits.numbering == "roman" else str(g)


def default_label_parts(lay: Layout, g: int) -> dict[str, str]:
    v = lay.village
    members = [v.people[q] for q in lay.x if v.people[q].generation == g]
    people = [p for p in members if not p.upcoming]
    upcoming = len(members) - len(people)
    women = sum(p.sex == "Female" for p in people)
    men = sum(p.sex == "Male" for p in people)
    alive = sum(p.alive for p in people)
    # Every row is "Generation <n>", the first too (the owner: "Just use Generation 1.  Players can type
    # FOUNDERS if they want to").
    # One of each is said so ("1 male", not "1 males"; the owner, 2026-10-10).
    out = {"number": f"{generation_number(lay, g)}.", "name": f"Generation {g}",
           "total": f"{len(people)} total: {women} female{'' if women == 1 else 's'}, "
                    f"{men} male{'' if men == 1 else 's'}",
           "living": f"{alive} living"}
    if upcoming:
        out["upcoming"] = f"{upcoming} upcoming"
    return out


LABEL_PLATE_W = 228                     # a generation label's plate as wide as it always was, at least
LABEL_PLATE_TOP = 6                     # the plate's top under the generation's top
LABEL_TEXT_X = 24                       # the words' left, past the label column's left (12 inside the plate)
LABEL_PAD = 10                          # under the label's last line, inside its plate


@dataclass
class LabelBox:
    """Where a generation label's lines go and how big its plate is, from the generation's top and the
    label column's left: each line's baseline (before a superscript or subscript moves it) and its size
    as the tree first draws it (the player's font size is put on after, by _apply_styles), the plate's
    width and how far down its bottom reaches."""
    baselines: list[float]
    sizes: list[float]
    width: float
    bottom: float

    @property
    def line_x(self) -> float:
        """The label's upright line, just past its plate (250 for a plate of the usual width)."""
        return 12 + self.width + 10


def label_box(edits: Edits, lines: list[str]) -> LabelBox:
    """A generation label's place, as big as every line it shows (the owner, 2026-10-10: the "2 upcoming"
    line was drawn below its box): its lines as far apart as their font size makes them, its plate as
    tall as the last line's bottom and as wide as the widest line -- at the player's font, size, bold,
    italic and superscript or subscript ("labels" in Edits.styles).  The usual label at the usual size
    is where it always was: baselines 40, 62, 84 ... under the top, a 228-wide plate."""
    style = edits.styles.get("labels", {})
    scale = style.get("scale", 100) / 100
    shrink, shift = SCRIPTS.get(style.get("script"), (1.0, 0.0))
    font = style.get("font") or edits.font
    italic = bool(style.get("italic", False))
    sizes = [18.0 if k == 0 else 14.0 for k in range(len(lines))]
    first = 22 + 18 * scale
    baselines = [first + 22 * scale * k for k in range(len(lines))]
    bottom = 0.0
    widest = 0.0
    for k, (text, size, base) in enumerate(zip(lines, sizes, baselines)):
        drawn = size * scale * shrink
        bottom = max(bottom, base + size * scale * shift + drawn * 0.3)
        widest = max(widest, text_width(text, drawn, bool(style.get("bold", k == 0)), font, italic))
    return LabelBox(baselines, sizes, max(float(LABEL_PLATE_W), widest + 2 * 12),
                    bottom + LABEL_PAD if lines else 0.0)


def label_boxes(village: gen.Village, edits: Edits, shown) -> dict[int, LabelBox]:
    """Every generation label a page draws (`shown`: the family members on the page), as label_box sizes it --
    for the layout to keep room for (a generation whose label the player deleted keeps none)."""
    probe = Layout(village, {}, dict.fromkeys(shown, 0.0), {}, [], [], 0.0, 0.0, 0.0, edits=edits)
    gens = sorted({village.people[q].generation for q in shown})
    return {g: label_box(edits, generation_label(probe, g)) for g in gens
            if f"word:label{g}" not in edits.hidden}


def title_lines(lay: Layout, game_title: str) -> tuple[str, str]:
    first, second = default_title_lines(lay, game_title)
    page = f" -- Page {lay.page + 1} of {lay.pages}" if lay.pages > 1 else ""
    return (fresh_title(lay, lay.edits.title) or first) + page, fresh_title(lay, lay.edits.subtitle) or second


# The facts a title line the tree wrote carries, kept current in a line the player retyped (a port of the
# Virtual Villagers Fun Patcher v1.35.85: "keep the owner's own words, but refresh the counts and the date each
# time the tree is made").  Only these words, where the player's line still has them; every other word is the
# player's.
TITLE_KNOWN = re.compile(r"(?<![\w.])\d+ family members known(?!\w)")
TITLE_LIVING = re.compile(r"(?<![\w.])\d+ living(?!\w)")
TITLE_DATE = re.compile(r"(?<![\w-])\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?![\w:])")


def title_counts(lay: Layout) -> tuple[int, int, str]:
    """(family members known, living, the date and time) as the title says them now."""
    v = lay.village
    return len(v.known()), len(v.living()), f"{datetime.now():%Y-%m-%d %H:%M}"


def fresh_title(lay: Layout, text: str) -> str:
    """The player's own title line with its counts and date as they are now; "" stays ""."""
    if not text:
        return text
    known, living, when = title_counts(lay)
    text = TITLE_KNOWN.sub(f"{known} family members known", text)
    text = TITLE_LIVING.sub(f"{living} living", text)
    return TITLE_DATE.sub(when, text)


def default_title_lines(lay: Layout, game_title: str) -> tuple[str, str]:
    v = lay.village
    name = v.tribe or f"Save {v.slot}"
    known, living, when = title_counts(lay)
    return (f"{game_title} -- Family Tree",
            f"{name} (Save {v.slot}) -- {known} family members known, {living} living -- {when}")


# Words the tree writes that the player may retype (the owner: "I wanna rename "unrelated
# individuals" to something else").  The footer's own words are footer(lay).
# The owner: "And default: "Other Members"" (the heading over the villagers with no recorded family).
WORDS = {"others": "Other Members", "others_note": "no recorded parent or child", "footer": "",
         "onward": "continued on page {page}"}     # (and "onward:<family key>": one family's: onward_words)


def words(lay: Layout, key: str) -> str:
    return lay.edits.words.get(key) or (footer(lay) if key == "footer" else WORDS[key])


FOOTER = ("Each unrelated family member has a colour of their own and full brothers and sisters share one; each "
          "couple has its own connector; a triangle joins twins and triplets.  Generation I is the founder and the "
          "one who married them; each generation's heir and the one who married them stand with their brothers and "
          "sisters.  Made by the Virtual Families 1 Patcher's Family Tree Maker from the save.")


# Plurals English does not make by adding "s" (the owner, 2026-10-09: "monstera leafs; ... butterflys.
# ahem. grammar.").
IRREGULAR_PLURALS = {"leaf": "leaves", "fish": "fish", "starfish": "starfish", "hibiscus": "hibiscus flowers",
                     "bunch": "bunches", "x": "Xs"}


def plural(shape: str) -> str:
    """A portrait shape's name for many of them, as the Key says it: the noun before any "(...)", "in ..."
    or "of ..." made plural ("ovals (horizontal)", "ocean waves in a circle", "bunches of bananas")."""
    name = PORTRAIT_SHAPES.get(shape, shape)
    name = name if name.startswith("Monstera") else name.lower()
    head, rest = re.match(r"(.+?)((?: \(| in | of ).*)?$", name).groups()
    words = head.split(" ")
    last = words[-1]
    if last in IRREGULAR_PLURALS:
        last = IRREGULAR_PLURALS[last]
    elif last.endswith("y") and last[-2:-1] not in ("a", "e", "i", "o", "u"):
        last = last[:-1] + "ies"
    elif last.endswith(("s", "x", "ch", "sh")):
        last += "es"
    else:
        last += "s"
    return " ".join(words[:-1] + [last]) + (rest or "").replace("(on its side)", "(on their sides)")


def footer(lay: Layout) -> str:
    """The Key: which portrait shape each group is drawn in (as the player set them), then FOOTER."""
    groups = "; ".join(f"{label}: {plural(lay.edits.shapes[group])}" for group, label in GROUPS.items())
    return f"{groups}.  {FOOTER}"


def node_text(lay: Layout, p: gen.Person) -> list[str]:
    """The entry's lines: the player's own, or the patcher's (default_text)."""
    lines = lay.entry(p).get("lines")
    return _shown_name_in(lay, p, lines, None)[0] if lines else default_text(lay, p)


def _shown_name_in(lay: Layout, p: gen.Person, lines: list, runs) -> tuple[list, object]:
    """The player's lines for a family member with their name -- with or without a Roman number -- as the
    tree shows it now (the owner, 2026-10-08: the tree's numbering is the rule, "Hawa Awanata II" is
    "Hawa Awanata" when there is no other).  Other words are never touched."""
    if p.upcoming or not p.name:
        return lines, runs
    lines, runs = _rename_in_lines(lines, runs, _name_pattern(gen.unnumbered(p.name), numbered=True),
                                   lay.names.get(p.id, p.name))
    # The facts the records keep changing: the age, in years and in game units, and whether the villager
    # is still here (the owner, 2026-10-09: Kalea Salongo, 16 in the game, still "5 years old" on the tree
    # after Update from the Save).  Only those words, where the player's lines already have them.
    if p.age is not None:
        lines, runs = _rename_in_lines(lines, runs, AGE_YEARS, f"{p.years} years old")
        lines, runs = _rename_in_lines(lines, runs, AGE_UNITS, f"{p.age} game units")
    if not p.alive and not deceased_label(lay, p):
        status = gen.status_words(p)
        lines, runs = _rename_in_lines(lines, runs, STATUS_WORDS, status)
    else:
        # Alive again -- reanimated in New Believers -- after their words were saved while they were gone
        # (Codex, #577), or dead with the Deceased label ticked (it says so in place of "(deceased)"): the line
        # the tree wrote for the status goes.  Only a line that is the status alone,
        # as default_text writes it: words the player typed ("Son of Ago (deceased)") stay.
        keep = [i for i, line in enumerate(lines) if not (isinstance(line, str) and STATUS_WORDS.fullmatch(line.strip()))]
        if len(keep) < len(lines):
            if isinstance(runs, list) and len(runs) == len(lines):
                runs = [runs[i] for i in keep]
            lines = [lines[i] for i in keep]
    return lines, runs


AGE_YEARS = re.compile(r"(?<![\w.])\d+ years old(?!\w)")
AGE_UNITS = re.compile(r"(?<![\w.])\d+ game units(?!\w)")
STATUS_WORDS = re.compile(r"\((?:deceased|no longer in the house)\)")


def default_text(lay: Layout, p: gen.Person) -> list[str]:
    """Name, age in game units and years, and what else there is to say: "(deceased)" for the
    dead (the owner: deceased family members are not faded, their entry says so)."""
    if p.upcoming:
        size = sum(1 for q in lay.village.people.values() if p.litter is not None and q.litter == p.litter)
        return ["Upcoming child"] + ([{2: "(twins)", 3: "(triplets)"}[size]] if size in (2, 3) else [])
    units, years = lay.opt(p, "show_units"), lay.opt(p, "show_years")     # the villager's group's
    ages = (["age unknown"] if p.age is None and (units or years) else
            [] if p.age is None else
            ([f"{p.age} game units"] if units else []) + ([f"{p.years} years old"] if years else []))
    extra = "" if deceased_label(lay, p) else gen.status_words(p)
    return [f"{p.number}. {lay.names.get(p.id, p.name)}"] + ages + descriptors(lay, p) + ([extra] if extra else [])


def deceased_label(lay: Layout, p: gen.Person) -> str:
    """"Deceased: Old age" -- in place of the "(deceased)" line, when the Deceased label is ticked (as the Virtual
    Families 2 tree words it): the game's own cause from the Family History log, else "(unconfirmed)" (the save's
    cause number alone is not a confirmed word); "" for the living or when the label is unticked."""
    if p.alive or p.upcoming or p.gone != "died" or not lay.opt(p, "show_deceased"):
        return ""
    cause = p.cause if p.cause and "unconfirmed" not in p.cause else "(unconfirmed)"
    return f"Deceased: {cause}"


def is_founder(village: gen.Village, p: gen.Person) -> bool:
    """One of the family's founders: generation I, no parents recorded, and not a later arrival (an Arrived
    record with a known "How" other than Founder, or first seen after the family's first snapshot)."""
    if p.upcoming or p.generation != 1 or p.father is not None or p.mother is not None:
        return False
    return not gen.is_arrival(p, min(gen.snapshot_dates(village), default=None))


def arrival_words(village: gen.Village, p: gen.Person) -> str:
    """The Random Event that brought them into the family or took them away, as the Family History log names it
    ("Popup Event: The Little Visitor", "Popup Event: The Talent Scout"); "" when no record names one (the save
    alone never says which event it was)."""
    if p.upcoming:
        return ""
    return getattr(p, "event_title", "") or ""


ADOPTED_HOWS = ("Adopted", "Spawn Child", "Adopt New Person")


def is_adopted(p: gen.Person) -> bool:
    """Joined without being born to the family: Adopt Outside Child, The Little Visitor, Spawn Child, Adopt New
    Person (the save's bio, the Family Tree's own place, or the Family History log proves which)."""
    return not p.upcoming and (p.adopted or p.how in ADOPTED_HOWS)


def career_words(p: gen.Person) -> str:
    """"Career: Pastry Designer, Novice": the executable's own words (career string 0x112 + id; level 0x1C1 + level),
    as the Game Mechanics page reads them; "" without a career."""
    import vf1_game_mechanics as gm
    if p.career is None or not 0 <= p.career < len(gm.CAREER_LIST):
        return ""
    words = f"Career: {gm.CAREER_LIST[p.career].name}"
    level = getattr(p, "career_level", None)
    return words + (f", {gm.LEVELS[level]}" if level is not None and 0 <= level < len(gm.LEVELS) else "")


def spouse_words(p: gen.Person) -> str:
    """"Wife 1", "Husband 2": a spouse's place in the order of their partner's marriages, by the spouse's own sex
    (a same-sex marriage the same way); "Married in" when no record proves the order, as the save only shows that."""
    n = getattr(p, "spouse_number", None)
    if n and p.sex in ("Male", "Female"):
        return f"{'Wife' if p.sex == 'Female' else 'Husband'} {n}"
    return "Married in" if p.how == "Married in" and not p.upcoming else ""   # all the save proves


def status_descriptors(lay: Layout, p: gen.Person) -> list[str]:
    """The special family member statuses this portrait says in words: each automatic mark the family member has (the
    mark and its words are one: a mark taken off them, or removed from everyone, takes its words too)."""
    auto = auto_labels(lay.edits, p)
    return [label for label in entry_marks(lay.entry(p)) if label in auto]


def descriptors(lay: Layout, p: gen.Person) -> list[str]:
    """The descriptors after the age (the owner, 2026-10-22: "family members get auto-denoted with special descriptors
    if applicable"): Founder, Heir, Runner, twins and triplets, how they arrived, left home, and their special
    family member statuses -- each where it applies and its option is ticked.  Never a job or skill line (the
    Virtual Villagers Family Tree Maker dropped its "Master Farmer" lines, 555023e0; Virtual Families has none)."""
    v = lay.village
    out = ["Founder"] if lay.opt(p, "show_founder") and is_founder(v, p) else []
    out += ["Heir"] if lay.opt(p, "show_heir") and getattr(p, "heir", False) else []
    out += [spouse_words(p)] if lay.opt(p, "show_spouse_order") and spouse_words(p) else []
    out += ["Remarried"] if lay.opt(p, "show_remarried") and getattr(p, "remarried", False) else []
    out += ["Divorced"] if lay.opt(p, "show_divorced") and getattr(p, "divorced", False) else []
    out += [deceased_label(lay, p)] if deceased_label(lay, p) else []
    out += ["Adopted"] if lay.opt(p, "show_adopted") and is_adopted(p) else []
    out += ["Runner"] if lay.opt(p, "show_runner") and p.runner else []
    out += born_with(lay, p)
    arrived = arrival_words(v, p) if lay.opt(p, "show_arrived") else ""
    out += [arrived] if arrived else []
    out += [career_words(p)] if lay.opt(p, "show_career") and career_words(p) else []
    out += ["Left home"] if lay.opt(p, "show_left_home") and getattr(p, "left_home", False) and p.alive else []
    return out + [s for s in status_descriptors(lay, p) if s not in out]


# The descriptor options (the Faces & Text tab's tick boxes): (Edits field, words).
DESCRIPTOR_OPTIONS = (("show_founder", "Founder (the one who started the family)"),
                      ("show_heir", "Heir (inherited the house)"),
                      ("show_runner", "Runner (likes running)"),
                      ("show_twins", "Twins and triplets (\"Happi's twin\")"),
                      ("show_spouse_order", "Husband 1 / Wife 1 (the order of marriages)"),
                      ("show_remarried", "Remarried"),
                      ("show_divorced", "Divorced"),
                      ("show_deceased", "Deceased: <cause> (unticked: \"(deceased)\")"),
                      ("show_adopted", "Adopted"),
                      ("show_arrived", "Event title (\"Popup Event: The Little Visitor\")"),
                      ("show_career", "Career (\"Career: Pastry Designer, Novice\")"),
                      ("show_left_home", "Left home"))


def status_options(edits: Edits, village: gen.Village) -> list[tuple[str, bool]]:
    """The special family member statuses this tree can describe, (the mark's name now, ticked): the game's own
    (gen.GAME_STATUSES) and every status a family member of the family has (their Custom titles too).  Ticked
    unless the player took the status off everyone (marks_off) -- the mark and its words together."""
    statuses = list(gen.GAME_STATUSES.get(village.game, ()))
    for p in village.people.values():
        statuses += [s for s in p.statuses if s not in statuses]
    out, seen = [], set()
    for status in statuses:
        label = auto_label(edits, status)
        if label not in seen:
            seen.add(label)
            out.append((label, status not in edits.marks_off and label not in edits.marks_off))
    return out


def set_status_option(edits: Edits, village: gen.Village, label: str, on: bool) -> None:
    """A status's descriptor option ticked or unticked -- and its mark with it, on everyone: off, the status is
    kept off (marks_off) and its mark taken off every family member (the tree's and each page's); on, given again
    to everyone who has it (each family member's own "unmarked" still kept)."""
    if on:
        edits.marks_off = [m for m in edits.marks_off if m != label and auto_label(edits, m) != label]
        apply_auto_marks(edits, village)
        return
    if label not in edits.marks_off:
        edits.marks_off.append(label)
    own = {id(e) for e in edits.entries.values()}
    entries = list(edits.entries.values()) + [e for part in edits.page_edits.values()
                                              for e in part.get("entries", {}).values()]
    for entry in entries:
        if label in entry_marks(entry):
            left = [m for m in entry_marks(entry) if m != label]
            if left or id(entry) not in own:
                entry["marks"], entry["mark"] = left or None, left[0] if left else None
            else:
                entry.pop("marks", None)
                entry.pop("mark", None)
    for key in [k for k, e in edits.entries.items() if not e]:
        del edits.entries[key]


def born_with(lay: Layout, p: gen.Person) -> list[str]:
    """With "Twins and triplets" on (Edits.show_twins), the line after the age naming who the
    family member was born with (the owner, 2026-10-09: "X's twin/triplet"): "Kalea's twin", "Kalea and
    Hana's triplet".  Nothing for a family member born alone, or with the setting off."""
    if not lay.opt(p, "show_twins") or p.litter is None or p.upcoming:
        return []
    others = sorted((q for q in lay.village.people.values()
                     if q.litter == p.litter and q.id != p.id and not q.upcoming), key=lambda q: (q.number or 0, q.id))
    if not others or len(others) > 2:
        return []
    names = [lay.names.get(q.id, q.name) or "(unnamed)" for q in others]
    return [f"{' and '.join(names)}'s {'twin' if len(others) == 1 else 'triplet'}"]


def inner_sizes(lay: Layout, p: gen.Person) -> tuple[float, float]:
    """(the face's size, the words' size) inside this family member's portrait, as factors: every portrait's
    setting (their group's, else the tree's) times their own -- or, made the same for their scope
    ("Same face and text size for:", Edits.equal_sizes), the scope's one size, whatever else is set."""
    scope = equal_scope(lay.edits, p)
    if scope:
        sizes = lay.edits.equal_sizes[scope]
        return sizes["face"] / 100, sizes["text"] / 100
    entry = lay.entry(p)
    return (lay.opt(p, "picture_size") / 100 * entry.get("picture_scale", 100.0) / 100,
            lay.opt(p, "text_size") / 100 * entry.get("text_scale", 100.0) / 100)


FACE_ROOM = 8                           # a face at one size keeps this far inside its frame (fixed_face_size)


EQUAL_SCOPES = ("all",) + tuple(GROUPS)       # Edits.equal_sizes: everyone, or one group


def clean_equal_sizes(raw) -> dict:
    """Edits.equal_sizes as saved, each scope's sizes checked; a bad one is dropped."""
    out = {}
    if isinstance(raw, dict):
        for scope, sizes in raw.items():
            if scope in EQUAL_SCOPES and isinstance(sizes, dict):
                face, text = sizes.get("face"), sizes.get("text")
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (face, text)):
                    out[scope] = {"face": max(PICTURE_SCALE_MIN, min(PICTURE_SCALE_MAX, float(face))),
                                  "text": max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX, float(text)))}
    return out


def equal_scope(edits: "Edits", p: gen.Person) -> str | None:
    """The "Same face and text size for:" scope this family member's portrait is in (their group's, else
    everyone's), or None."""
    if not edits.equal_sizes:
        return None
    group = group_of(p)
    return group if group in edits.equal_sizes else "all" if "all" in edits.equal_sizes else None


def is_fixed(edits: "Edits", p: gen.Person) -> bool:
    """Whether this portrait's face and words keep one size (fixed_face_size, or made the same)."""
    return bool(opt(edits, p, "fixed_face_size") or equal_scope(edits, p))


def _own_fixed_scale(lay: Layout, p: gen.Person, fw: float, fh: float) -> float:
    """One portrait's own scale with its face and words at one size (fixed_scale)."""
    pic, words = inner_sizes(lay, p)
    face = FACE_H * HEAD_SCALE * pic
    room = min(fw, fh) - 2 * FACE_ROOM
    scale = 1.0 if p.upcoming or face <= room else max(0.2, room / face)
    if lay.opt(p, "text_inside") and not p.upcoming:
        # Words kept inside the shape: the face and words together as large as the frame's height holds
        # them (else the words, run on below a short frame, would be made all but unreadably small).
        _left, _top, _text, lines = placement(lay, p)
        block = face + 8 + len(lines) * LINE_H * words
        scale = min(scale, max(0.2, (fh - 2 * FACE_ROOM) / block))
    return scale


def equal_scale(lay: Layout, scope: str) -> float:
    """One scale for every portrait in a "Same face and text size" scope: the largest at which every
    one of their faces (and, kept inside the shape, their words) fits its frame -- so none is shrunk
    and the others not (the owner, 2026-10-10)."""
    cache = lay.__dict__.setdefault("_equal_scales", {})
    if scope not in cache:
        edits, village = lay.edits, lay.village
        scales = [_own_fixed_scale(lay, q, *frame_size(edits, village, q, shrink=lay.shrink))
                  for q in village.people.values()
                  if not q.upcoming and equal_scope(edits, q) == scope
                  and not edits.entries.get(entry_key(village, q), {}).get("hidden")]
        cache[scope] = min(scales, default=1.0)
    return cache[scope]


def fixed_scale(lay: Layout, p: gen.Person, fw: float, fh: float) -> float:
    """Faces and words at one size (Edits.fixed_face_size, the owner, 2026-10-09: the males' faces and
    words looked a quarter smaller than the females'): 1 for every portrait, whatever its shape and size --
    unless the frame is too small for the face, which then shrinks just enough to stay inside it (the
    face never leaves its portrait), and the words with it.  Made the same for a scope: the scope's
    one scale (equal_scale)."""
    scope = equal_scope(lay.edits, p)
    if scope:
        return equal_scale(lay, scope)
    return _own_fixed_scale(lay, p, fw, fh)


def face_inside(lay: Layout, p: gen.Person, present: dict, y: float, fy: float, fh: float, scale: float) -> float:
    """How far down (or up) a portrait's face and words move so the face, at one size, is inside its
    frame -- a frame shorter than a portrait (a turtle shell on its side, a butterfly) would otherwise
    have the face standing out over its top.  The words keep their place under the face; where the
    frame is too short for them they run on below it, or, kept inside the shape (Edits.text_inside),
    are made smaller by the usual fitting."""
    sheet = sheet_name(lay.village.game, p)
    box = face_box(present, sheet, look_of(lay.edits, lay.village, p)[0])
    _left, head_top, _text_top, _lines = placement(lay, p, box)
    pic, _words = inner_sizes(lay, p)
    middle = y + NODE_H / 2
    top = middle + (y + head_top + box[1] * HEAD_SCALE * pic - middle) * scale
    bottom = top + (box[3] - box[1]) * HEAD_SCALE * pic * scale
    if top < fy + FACE_ROOM:
        return min(fy + FACE_ROOM - top, max(0.0, fy + fh - FACE_ROOM - bottom))
    if bottom > fy + fh - FACE_ROOM:
        return -min(bottom - (fy + fh - FACE_ROOM), max(0.0, top - fy - FACE_ROOM))
    return 0.0


def fixed_words_reach(lay: Layout, p: gen.Person, fw: float, fh: float, present: dict | None = None) -> tuple[float, float]:
    """For a portrait whose face and words keep one size (fixed_face_size): how high its face and how low
    its words reach from its place's top -- past a frame shorter than the face and words, where the words
    run on below it.  As _node draws them."""
    scale = fixed_scale(lay, p, fw, fh)
    pic, words = inner_sizes(lay, p)
    sheet = sheet_name(lay.village.game, p)
    box = face_box(present or {}, sheet, look_of(lay.edits, lay.village, p)[0])
    _left, head_top, text_top, lines = placement(lay, p, box)
    shift = face_inside(lay, p, present or {}, 0.0, (NODE_H - fh) / 2, fh, scale)
    mid = NODE_H / 2
    top = mid + (head_top + box[1] * HEAD_SCALE * pic - mid) * scale + shift
    bottom = mid + (text_top + max(0, len(lines) - 1) * LINE_H * words + 4 * words - mid) * scale + shift
    return top, bottom


def placement(lay: Layout, p: gen.Person, box: tuple = None) -> tuple[float, float, float, list]:
    """(the head cell's left and top inside the frame, the first line's baseline, the lines as
    drawn): the face (the head's visible pixels, `box`) and the lines centred together (the owner:
    "center the heads within the portrait shapes vertically and horizontally"), or the head at the
    top when the player turns centring off ("in case players type a lot of stuff")."""
    x0, y0, x1, y1 = box or DEFAULT_BOX
    pic, words = inner_sizes(lay, p)
    face = (y1 - y0) * HEAD_SCALE * pic
    lh = LINE_H * words                     # the lines spaced as the words are sized
    valign = lay.opt(p, "text_valign")
    face_top = 10.0 if valign == "top" else 6.0
    lines = shown_text(lay, p, int(max(LINE_H, NODE_H - face_top - face - 8 - 6) // lh))
    block = face + 8 + len(lines) * lh
    if valign == "middle":
        face_top = max(face_top, (NODE_H - block) / 2)
    elif valign == "bottom":                # the last line just above the frame's foot
        face_top = max(face_top, NODE_H - block - 6)
    left = NODE_W / 2 - (x0 + x1) / 2 * HEAD_SCALE * pic
    return left, face_top - y0 * HEAD_SCALE * pic, face_top + face + 8 + lh - 3, lines


WRAP = 17                               # characters across a portrait, until the player says
WRAP_MIN, WRAP_MAX = 8, 60


def _wrap(text: str, n: int = WRAP) -> list[str]:
    """A line as it fits across a portrait: broken between words, a word too long for one line
    broken where it must."""
    out: list[str] = []
    line = ""
    for word in text.split(" "):
        while len(word) > n:
            if line:
                out.append(line)
                line = ""
            out.append(word[:n])
            word = word[n:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= n:
            line += " " + word
        else:
            out.append(line)
            line = word
    out.append(line)
    return out


AUX_STYLE = {"bold": True, "italic": True}     # the tree's extra lines, by default (the owner, 2026-10-10)


def is_aux_line(k: int, line: str) -> bool:
    """Whether a portrait's line is an extra one -- "Golden Child", "Founder", "X's twin", how they
    came, a title, "(deceased)" on its own -- rather than the main text: the name (the first line)
    and the age."""
    text = line.strip() if isinstance(line, str) else ""
    return (k > 0 and bool(text) and text != "age unknown"
            and not AGE_YEARS.fullmatch(text) and not AGE_UNITS.fullmatch(text))


def default_runs(lay: Layout, p: gen.Person) -> list[list[tuple[str, dict]]] | None:
    """The patcher's own lines (default_text) formatted: every extra line (is_aux_line) bold and
    italic (the owner, 2026-10-10: "please bold and italicize 'auxillary text' by default").  None
    when there is none, or for an upcoming child."""
    if p.upcoming:
        return None
    lines = default_text(lay, p)
    if not any(is_aux_line(k, line) for k, line in enumerate(lines)):
        return None
    return [[(line, dict(AUX_STYLE) if is_aux_line(k, line) else {})] for k, line in enumerate(lines)]


def bold_italic_aux(lines: list, runs) -> list | None:
    """The Faces & Text button (the owner, 2026-10-10: "add a button to retroactively update that
    text too"): a player's own lines with every extra line (is_aux_line) made bold and italic, each run
    keeping its other formatting; the name and age lines untouched.  The runs in their saved form."""
    have = clean_runs(runs, lines) or [[(line, {})] for line in lines]
    out = [[(text, {**style, **AUX_STYLE}) if is_aux_line(k, line) else (text, dict(style)) for text, style in line_runs]
           for k, (line, line_runs) in enumerate(zip(lines, have))]
    return runs_data([merge_runs(line) for line in out])


def status_label(p: gen.Person) -> str:
    """The saved record's status for a portrait, as default_text words it: "(deceased)", "(no longer in the
    house)", else "" (a living family member, or a baby on the way)."""
    return gen.status_words(p)


def shows_status(lines: list) -> bool:
    """Whether portrait lines (as drawn) already say a status: "(deceased)" or "(no longer in the house)"."""
    return any(isinstance(line, str) and STATUS_WORDS.search(line) for line in lines)


def with_status_label(p: gen.Person, lines: list, runs, shown: list | None = None) -> tuple[list, list | None] | None:
    """A portrait's lines with the family member's status (status_label) added as an extra line, as the
    tree words it (bold and italic like the other extra lines); None when there is no status to add or
    the portrait already says it (`shown`, the lines as drawn -- else `lines`).  Only the displayed words:
    the family member's records are never touched."""
    label = status_label(p)
    if not label or shows_status(lines if shown is None else shown):
        return None
    have = clean_runs(runs, lines) or [[(line, {})] for line in lines]
    return list(lines) + [label], runs_data(have + [[(label, dict(AUX_STYLE))]])


def status_for_portrait(lay: Layout, p: gen.Person) -> tuple[list, list | None] | None:
    """What the Faces & Text "Add status labels" button saves for one portrait, or None when it changes
    nothing.  The portrait is judged by the words it shows now (node_text): the player's own lines, or --
    with none typed -- the patcher's (default_text, which already ends with the status of the dead and of a
    Heathen, so such a portrait is left alone).  If the shown words lack the status it is added as a bold
    italic last line, to the player's lines or to the patcher's own lines and their default formatting."""
    entry = lay.entry(p)
    typed = entry.get("lines")
    shown = node_text(lay, p)
    if typed:
        return with_status_label(p, typed, entry.get("runs"), shown)
    return with_status_label(p, shown, runs_data(default_runs(lay, p)), shown)


def node_runs(lay: Layout, p: gen.Person) -> list[list[tuple[str, dict]]] | None:
    """The entry's lines formatted word by word (clean_runs), or None when they are plain.  The
    patcher's own lines have their extra lines bold and italic (default_runs); the player's own lines
    keep exactly what the player chose."""
    entry = lay.entry(p)
    lines = entry.get("lines")
    if not lines:
        return default_runs(lay, p)
    lines, runs = _shown_name_in(lay, p, lines, entry.get("runs"))
    return clean_runs(runs, lines)


BOLD_WIDTH = 1.1                        # how much wider a bold letter is, near enough

# Segoe UI's own letter widths, in thousandths of its size (Windows' font, measured): space to "~", then
# no-break space to "ÿ".  A portrait's words are fitted by these, the same in the editor and in every
# saved picture -- a fixed width a letter (0.55 of the size) let a bold "75. Mamba Chuchip" run 11 pixels
# past its frame.
_WIDTH_CHARS = "".join(map(chr, range(32, 127))) + "".join(map(chr, range(160, 256)))
_WIDTHS = {False: dict(zip(_WIDTH_CHARS, map(int, (
    "274 284 392 591 539 818 800 230 302 302 417 684 217 400 217 390 539 539 539 539 539 539 539 539 539 539 "
    "217 217 684 684 684 448 955 645 573 619 701 506 488 686 710 266 357 580 471 898 748 754 560 754 598 531 "
    "524 687 621 934 590 553 570 302 379 302 684 415 268 509 588 462 589 523 313 589 566 242 242 497 242 861 "
    "566 586 588 589 348 424 339 566 479 723 459 484 452 302 239 302 684 274 284 539 539 556 539 239 448 414 "
    "890 392 506 684 400 890 415 377 684 366 366 282 577 458 217 205 351 431 506 906 931 952 448 645 645 645 "
    "645 645 645 860 619 506 506 506 506 266 266 266 266 701 748 754 754 754 754 754 684 754 687 687 687 687 "
    "553 560 544 509 509 509 509 509 509 832 462 523 523 523 523 242 242 242 242 559 566 586 586 586 586 586 "
    "684 586 566 566 566 566 484 588 484").split()))),
    True: dict(zip(_WIDTH_CHARS, map(int, (
    "276 327 493 592 575 867 850 293 369 369 455 707 271 404 271 443 575 575 575 575 575 575 575 575 575 575 "
    "271 271 707 707 707 438 954 703 641 624 737 532 520 711 766 317 445 649 511 957 790 758 614 758 653 561 "
    "586 723 667 1005 655 607 607 369 436 369 707 415 314 538 620 480 619 541 383 619 602 284 284 559 284 916 "
    "605 611 620 619 398 440 389 605 542 797 552 538 479 369 326 369 707 276 327 575 575 556 575 326 485 462 "
    "874 410 581 707 404 874 415 380 707 404 404 303 613 509 271 215 394 456 581 952 965 979 438 703 703 703 "
    "703 703 703 935 624 532 532 532 532 317 317 317 317 737 790 758 758 758 758 758 707 758 723 723 723 723 "
    "607 614 628 538 538 538 538 538 538 828 480 541 541 541 541 284 284 284 284 593 605 611 611 611 611 611 "
    "707 611 605 605 605 605 538 620 538").split())))}
WIDTH_SPARE = 1.04                      # small sizes are drawn a little wider than the font's own widths
OTHER_FONT_SPARE = 1.15                 # a font of the player's own, measured as Segoe UI and a little more
ITALIC_SPARE = 1.05                     # italic letters about as wide, leaning past their ends (measured)


def text_width(text: str, size: float, bold: bool = False, font: str | None = None, italic: bool = False) -> float:
    """How wide a line of words is drawn, in pixels, at `size` (Segoe UI's letter widths; a letter beyond
    them -- a symbol, another alphabet -- as wide as the font's size, or the widest of them)."""
    widths = _WIDTHS[bool(bold)]
    em = sum(widths.get(ch, 1000 if ord(ch) >= 0x2E80 else 760) for ch in text) / 1000
    spare = WIDTH_SPARE * (1.0 if not font or font.lower() == "segoe ui" else OTHER_FONT_SPARE)
    return em * size * spare * (ITALIC_SPARE if italic else 1.0)


def run_width(style: dict, base: dict) -> float:
    """How wide a letter of a run is against one of its line's own look (`base`: the role's bold
    and script): a bolder letter wider, a superscript or subscript one narrower."""
    def width(bold: bool, script: str) -> float:
        return (BOLD_WIDTH if bold else 1.0) * (SCRIPTS[script][0] if script in SCRIPTS else 1.0)
    bold = style.get("bold", base.get("bold", False))
    script = style.get("script", base.get("script", ""))
    return width(bold, script) / width(base.get("bold", False), base.get("script", ""))


def _wrap_cells(cells: list[tuple[str, float, dict]], n: float = WRAP) -> list[list[tuple[str, float, dict]]]:
    """_wrap for formatted words: each letter (letter, width, style) as wide as its font makes it,
    a plain letter 1 -- so plain words wrap exactly as _wrap wraps them."""
    def wide(cs) -> float:
        return sum(c[1] for c in cs)
    words: list[tuple[tuple | None, list]] = [(None, [])]       # (the space before it, its letters)
    for cell in cells:
        if cell[0] == " ":
            words.append((cell, []))
        else:
            words[-1][1].append(cell)
    out: list[list] = []
    line: list = []
    for space, word in words:
        while wide(word) > n + 1e-9:
            if line:
                out.append(line)
                line = []
            k, used = 0, 0.0
            while k < len(word) and (k == 0 or used + word[k][1] <= n + 1e-9):
                used += word[k][1]
                k += 1
            out.append(word[:k])
            word = word[k:]
        if not line:
            line = word
        elif wide(line) + space[1] + wide(word) <= n + 1e-9:
            line = line + [space] + word
        else:
            out.append(line)
            line = word
    out.append(line)
    return out


def _joined(lines: list[str], n: int) -> list[str]:
    """The patcher's own lines under the name, put side by side while they fit in `n` characters
    (the owner, 2026-10-08: "1379 game units, 68 years old"): the ages with a comma, a note in
    brackets after a space."""
    out: list[str] = []
    for line in lines:
        if out and line and out[-1]:
            joint = _joint(out[-1], line)
            if len(out[-1]) + len(joint) + len(line) <= n:
                out[-1] += joint + line
                continue
        out.append(line)
    return out


def _joint(before: str, after: str) -> str:
    """What goes between two lines put side by side: a space beside a bracketed note -- "(deceased)
    Founder" -- else a comma -- "1379 game units, 68 years old"."""
    return " " if after.startswith("(") or before.endswith(")") else ", "


def _joined_runs(lines: list, n: int, edits: "Edits") -> list:
    """_joined for formatted lines: each keeps its own words' formatting; they are measured as
    wide as their fonts make them (run_width)."""
    base = line_base(edits, False)

    def wide(line) -> float:
        return sum(run_width(style, base) * len(text) for text, style in line)

    def plain(line) -> str:
        return "".join(text for text, _style in line)
    out: list = []
    for line in lines:
        if out and plain(line) and plain(out[-1]):
            joint = _joint(plain(out[-1]), plain(line))
            if wide(out[-1]) + len(joint) + wide(line) <= n + 1e-9:
                out[-1] = list(out[-1]) + [(joint, {})] + list(line)
                continue
        out.append(list(line))
    return out


def _cells_runs(cells: list) -> list[tuple[str, dict]]:
    return merge_runs((c[0], c[2]) for c in cells)


def shown_text(lay: Layout, p: gen.Person, room: int) -> list[tuple[str, bool, list | None]]:
    """The portrait's lines as drawn, each with whether it is bold (the first line, the name) and
    its runs when the player formatted it (else None): every line wrapped to fit across, and as many
    as fit below the head -- the last of them ending in ... when some did not.  Formatted words wrap
    by how wide their fonts make them (run_width), so they never run past the portrait."""
    n = lay.opt(p, "text_wrap")
    runs = node_runs(lay, p)
    if runs is None:
        lines = node_text(lay, p)
        if n > WRAP:                    # widened: side by side while they fit (the owner's picture); at the
            lines = lines[:1] + _joined(lines[1:], n)       # default every line stays as typed (Codex, #575)
        out = [(piece, k == 0, None) for k, text in enumerate(lines) for piece in _wrap(text, n)]
        room = max(1, room)
        if len(out) > room:
            last, bold, _r = out[room - 1]
            out = out[:room - 1] + [(last[:n - 1] + "…", bold, None)]
        return out
    pieces: list[tuple[list, bool]] = []
    if n > WRAP:
        runs = runs[:1] + _joined_runs(runs[1:], n, lay.edits)
    for k, line in enumerate(runs):
        base = line_base(lay.edits, k == 0)
        cells = [(ch, run_width(style, base), style) for text, style in line for ch in text]
        pieces.extend((cells_line, k == 0) for cells_line in _wrap_cells(cells, n))
    room = max(1, room)
    if len(pieces) > room:
        last, bold = pieces[room - 1]
        kept, used = [], 0.0
        for cell in last:
            if used + cell[1] > n - 1 + 1e-9:
                break
            kept.append(cell)
            used += cell[1]
        pieces = pieces[:room - 1] + [(kept + [("…", 1.0, kept[-1][2] if kept else {})], bold)]
    out = []
    for cells, bold in pieces:
        line_runs = _cells_runs(cells)
        text = "".join(t for t, _s in line_runs)
        out.append((text, bold, line_runs if any(s for _t, s in line_runs) else None))
    return out


def line_base(edits: "Edits", name: bool) -> dict:
    """A portrait line's own look before its runs': its role's bold, italic, underline, strike and
    script (the name's line -- the first -- bold unless the player said otherwise)."""
    style = edits.styles.get("names" if name else "portraits", {})
    return {"bold": style.get("bold", name), "italic": style.get("italic", False),
            "underline": style.get("underline", False), "strike": style.get("strike", False),
            "script": style.get("script", "")}


def run_effect(style: dict, base: dict) -> dict:
    """How a run looks (its own style over its line's: line_base): every flag, its script ("" none)
    and its own colour ("" its role's)."""
    out = {flag: style.get(flag, base[flag]) for flag in RUN_FLAGS}
    script = style.get("script", base["script"])
    out["script"] = "" if script == "normal" else script
    out["colour"] = style.get("colour", "")
    return out


def format_styles(styles: list[dict], bases: list[dict], what: str, colour: str = "") -> list[dict]:
    """The selected letters' styles (each with its line's line_base) after a format button: a flag
    or superscript / subscript turned on for all of them unless all of them have it already (then
    off), as a word processor does; "colour" (`colour`, or "" back to the role's), "plain" every
    setting off.  A letter keeps only what differs from its line's own look."""
    if what == "plain":
        return [{} for _s in styles]
    if what == "colour":
        return [{**{k: v for k, v in s.items() if k != "colour"}, **({"colour": colour} if colour else {})}
                for s in styles]
    looks = [run_effect(s, b) for s, b in zip(styles, bases)]
    out = []
    if what in RUN_FLAGS:
        target = not all(look[what] for look in looks)
        for s, b in zip(styles, bases):
            new = {k: v for k, v in s.items() if k != what}
            if target != b[what]:
                new[what] = target
            out.append(new)
    elif what in SCRIPTS:
        target = what if not all(look["script"] == what for look in looks) else ""
        for s, b in zip(styles, bases):
            new = {k: v for k, v in s.items() if k != "script"}
            if target != b["script"]:
                new["script"] = target or "normal"
            out.append(new)
    else:
        raise ValueError(f"no such format: {what}")
    return out


def _unit_outlines() -> dict[str, list[tuple[float, float]]]:
    """Each many-sided shape in a 1 x 1 box."""
    def fit(points: list) -> list:
        xs, ys = zip(*points)
        return [((px - min(xs)) / (max(xs) - min(xs)), (py - min(ys)) / (max(ys) - min(ys))) for px, py in points]

    plus = [(0.33, 0), (0.67, 0), (0.67, 0.33), (1, 0.33), (1, 0.67), (0.67, 0.67), (0.67, 1), (0.33, 1),
            (0.33, 0.67), (0, 0.67), (0, 0.33), (0.33, 0.33)]
    turned = [((px - 0.5) * math.cos(math.pi / 4) - (py - 0.5) * math.sin(math.pi / 4),
               (px - 0.5) * math.sin(math.pi / 4) + (py - 0.5) * math.cos(math.pi / 4)) for px, py in plus]
    star = [(math.sin(k * math.pi / 5) * (0.5 if k % 2 == 0 else 0.2),
             -math.cos(k * math.pi / 5) * (0.5 if k % 2 == 0 else 0.2)) for k in range(10)]
    # The owner, 2026-10-09: 4- and 6-pointed stars too (the 6-pointed one two crossed triangles' outline).
    star6 = [(math.sin(k * math.pi / 6) * (0.5 if k % 2 == 0 else 0.5 / math.sqrt(3)),
              -math.cos(k * math.pi / 6) * (0.5 if k % 2 == 0 else 0.5 / math.sqrt(3))) for k in range(12)]
    # The owner's pictures (2026-10-09): a plumper 5-pointed star, and a 6-pointed one with long thin points.
    plump = [(math.sin(k * math.pi / 5) * (0.5 if k % 2 == 0 else 0.26),
              -math.cos(k * math.pi / 5) * (0.5 if k % 2 == 0 else 0.26)) for k in range(10)]
    slim6 = [(math.sin(k * math.pi / 6) * (0.5 if k % 2 == 0 else 0.19),
              -math.cos(k * math.pi / 6) * (0.5 if k % 2 == 0 else 0.19)) for k in range(12)]
    heart = [(16 * math.sin(t) ** 3, -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
             for t in (k * 2 * math.pi / 72 for k in range(72))]
    return {
        "diamond": [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)],
        "triangle": [(0.5, 0), (1, 1), (0, 1)],
        "plus": plus,
        "cross": [(0.35, 0), (0.65, 0), (0.65, 0.25), (1, 0.25), (1, 0.5), (0.65, 0.5), (0.65, 1), (0.35, 1),
                  (0.35, 0.5), (0, 0.5), (0, 0.25), (0.35, 0.25)],
        "x": fit(turned),
        "star": fit(star),
        # The owner's picture (2026-10-09): taller than wide, a narrow waist.
        "star4": [(0.5, 0), (0.636, 0.385), (1, 0.5), (0.636, 0.615), (0.5, 1), (0.364, 0.615), (0, 0.5),
                  (0.364, 0.385)],
        "star6": fit(star6),
        "plump_star": fit(plump),
        "slim_star6": fit(slim6),
        # The owner, 2026-10-09: horizontal and vertical arrows (a portrait turns to point any other way).
        "arrow_h": [(0, 0.3), (0.6, 0.3), (0.6, 0), (1, 0.5), (0.6, 1), (0.6, 0.7), (0, 0.7)],
        "arrow_v": [(0.5, 0), (1, 0.4), (0.7, 0.4), (0.7, 1), (0.3, 1), (0.3, 0.4), (0, 0.4)],
        "hexagon": [(0.5, 0), (1, 0.25), (1, 0.75), (0.5, 1), (0, 0.75), (0, 0.25)],
        "octagon": [(0.3, 0), (0.7, 0), (1, 0.3), (1, 0.7), (0.7, 1), (0.3, 1), (0, 0.7), (0, 0.3)],
        "trapezoid": [(0.2, 0), (0.8, 0), (1, 1), (0, 1)],           # the owner, 2026-10-09
        # A wide oval (the owner, 2026-10-09, in place of the leafy oval): "Oval" fills a tall portrait.
        "oval_wide": [(0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)) for a in (2 * math.pi * k / 96 for k in range(96))],
        "pentagon": [(0.5, 0), (1, 0.382), (0.809, 1), (0.191, 1), (0, 0.382)],     # regular; the owner, 2026-10-09
        "heart": fit(heart),
        # The owner's picture (2026-10-09): straight sides, a half-circle top, about two thirds as wide as tall.
        "arch": [(0, 1), (0, 0.327)] + [(0.5 - 0.5 * math.cos(math.pi * k / 36), 0.327 - 0.327 * math.sin(math.pi * k / 36))
                                          for k in range(1, 36)] + [(1, 0.327), (1, 1)],
        **{name: shape[0] for name, shape in SHELLS.items()},     # the shells and the owner's other pictures
    }


def _traced(inside_at, centre: tuple[float, float], rays: int = 240) -> list[tuple[float, float]]:
    """The edge of a shape given as a test of whether a point is in it: along each ray from
    `centre`, the farthest point inside it (so parts that do not touch the centre, a butterfly's
    wings, are traced too)."""
    out = []
    for k in range(rays):
        t = 2 * math.pi * k / rays
        dx, dy = math.cos(t), math.sin(t)
        far = 0.0
        for step in range(1, 700):
            r = step * 0.003
            if inside_at(centre[0] + r * dx, centre[1] + r * dy):
                far = r
        out.append((centre[0] + far * dx, centre[1] + far * dy))
    return out


def _outlined(pieces: list, reach: float = 1.25, n: int = 280) -> list[tuple[float, float]]:
    """The edge of a shape made of overlapping `pieces` -- each a test of whether a point is in it and
    the box (x0, y0, x1, y1) it lies in -- walked round on a fine grid (Moore neighbours), so branching
    shapes, a coral, keep every gap between their branches; then smoothed. The shape must be one piece
    inside the square of half-width `reach`. Each piece fills only its own box's cells, so it is quick."""
    step = 2 * reach / n
    grid = [[False] * n for _ in range(n)]
    cell = lambda v: min(n - 1, max(0, int((v + reach) / step)))
    for inside_at, (x0, y0, x1, y1) in pieces:
        for j in range(cell(y0), cell(y1) + 1):
            row, y = grid[j], -reach + (j + 0.5) * step
            for i in range(cell(x0), cell(x1) + 1):
                if not row[i] and inside_at(-reach + (i + 0.5) * step, y):
                    row[i] = True
    filled = lambda x, y: 0 <= x < n and 0 <= y < n and grid[y][x]
    start = next((x, y) for y in range(n) for x in range(n) if grid[y][x])
    ways = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    cells, here, back = [start], start, 4              # entered from the west, which is outside
    for _ in range(8 * n * n):
        for k in range(1, 9):
            d = (back + k) % 8
            nxt = (here[0] + ways[d][0], here[1] + ways[d][1])
            if filled(*nxt):
                before = (here[0] + ways[(d - 1) % 8][0], here[1] + ways[(d - 1) % 8][1])
                back = ways.index((before[0] - nxt[0], before[1] - nxt[1]))
                here = nxt
                break
        else:
            break                                      # a single cell
        if here == start:
            break
        cells.append(here)
    pts = [(-reach + (x + 0.5) * step, -reach + (y + 0.5) * step) for x, y in cells]
    m = len(pts)
    soft = [(sum(pts[(i + k) % m][0] for k in range(-3, 4)) / 7, sum(pts[(i + k) % m][1] for k in range(-3, 4)) / 7)
            for i in range(m)]
    return soft[::2]


@functools.lru_cache(maxsize=1)
def _drawn_outlines() -> dict[str, list[tuple[float, float]]]:
    """The owner's shapes of 2026-10-08 -- a flower, a butterfly, a leaf and the playing-card suits'
    clover and spade -- traced from simple parts (circles, ellipses, a heart, a stem), y downward."""
    def disc(cx, cy, r):
        return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def oval(cx, cy, rx, ry, turn_deg=0.0):
        c, s = math.cos(math.radians(turn_deg)), math.sin(math.radians(turn_deg))
        return lambda x, y: (((x - cx) * c + (y - cy) * s) / rx) ** 2 + ((-(x - cx) * s + (y - cy) * c) / ry) ** 2 <= 1

    def stem(top, bottom, half_top, half_bottom, cx=0.0):
        def at(x, y):
            if not top <= y <= bottom:
                return False
            half = half_top + (half_bottom - half_top) * (y - top) / (bottom - top)
            return abs(x - cx) <= half
        return at

    def union(*parts):
        return lambda x, y: any(part(x, y) for part in parts)

    # A six-petalled flower, the owner's picture: six long oval petals from the middle, one
    # straight up and one straight down.
    petals = [oval(0.25 * math.cos(math.radians(-90 + 60 * k)), 0.25 * math.sin(math.radians(-90 + 60 * k)),
                   0.25, 0.165, -90 + 60 * k) for k in range(6)]
    flower = union(disc(0, 0, 0.2), *petals)
    # A butterfly, kept simple (the owner): two round upper wings and two smaller lower ones,
    # meeting in the middle.
    butterfly = union(oval(-0.36, -0.18, 0.4, 0.32, -20), oval(0.36, -0.18, 0.4, 0.32, 20),
                      oval(-0.26, 0.28, 0.28, 0.24, 25), oval(0.26, 0.28, 0.28, 0.24, -25),
                      oval(0, 0.02, 0.2, 0.36))
    # The club (clover) of a deck of cards: three round leaves round a wide middle and a short
    # stem, with room inside for the face and the words (the owner).
    clover = union(disc(0, -0.3, 0.34), disc(-0.36, 0.14, 0.34), disc(0.36, 0.14, 0.34), disc(0, 0.05, 0.32),
                   stem(0.3, 0.68, 0.06, 0.2))
    # The spade: an upside-down heart and a flared stem.
    heart = [(16 * math.sin(t) ** 3, (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t)
                                          - math.cos(4 * t))) for t in (k * 2 * math.pi / 120 for k in range(120))]
    spade_heart = [(px / 28, py / 28 - 0.12) for px, py in heart]      # a wide body: room inside
    def in_heart(x, y):                 # inside() is defined further down the module
        hit = False
        for (ax, ay), (bx, by) in zip(spade_heart, spade_heart[1:] + spade_heart[:1]):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                hit = not hit
        return hit
    def flared(x, y):                   # the stem, flaring in a smooth curve to its foot, from inside the body
        if not 0.0 <= y <= 0.58:
            return False
        return abs(x) <= 0.03 + 0.13 * (y / 0.58) ** 2    # a little smaller (the owner, 2026-10-09)
    spade = union(in_heart, flared)     # the owner, 2026-10-09: no bumps where the stem meets the body
    # A leaf, the owner's picture: a broad blade pointing up to the right, fullest towards its
    # base at the lower left, both ends pointed -- and a stalk from the base "so it's clear".
    leaf_c, leaf_s = math.cos(math.radians(-40)), math.sin(math.radians(-40))

    def along(x, y):                    # (towards the tip, across)
        return x * leaf_c + y * leaf_s, -x * leaf_s + y * leaf_c

    def blade(x, y):
        u, v = along(x, y)
        s = u / 0.62
        return abs(s) <= 1 and abs(v) <= 0.36 * (1 - s * s) ** 0.75 * (1 - 0.22 * s)

    def stalk(x, y):
        u, v = along(x, y)
        return -0.86 <= u <= -0.5 and abs(v) <= 0.028
    leaf = union(blade, stalk)
    return {"flower": _traced(flower, (0, 0)), "butterfly": _traced(butterfly, (0, 0)),
            "clover": _traced(clover, (0, 0)), "spade": _traced(spade, (0, 0.05)),
            "leaf": _traced(leaf, (0, 0))}


# Shapes drawn as the owner straightened them (2026-10-10): (degrees turned, mirrored across first), as a
# portrait so turned and flipped drew it before.  The Monstera leaf as every leaf of the owner's tree was set
# ("treat this current monstera position as straight up and horizontal"); the feather lying across, its tip
# to the left and its quill to the right.  Each with a marker in the edits (Edits.<shape>_v2): a tree saved
# before is moved on once (settle_shapes).
SHAPE_BAKES = {"monstera": (45.0, True), "feather": (270.0, False)}
BAKED: dict = {}                        # each one's traced box's and its own box's sides, the traced height 1 (_shells)


def _shells() -> dict[str, tuple[list, list]]:
    """The owner's shells (2026-10-09, from their pictures): a scallop -- seven rounded lobes fanned
    over a hinge, a small ear either side below -- and a snail's shell, its last whorl round a
    spiral.  Each (outline, detail lines) in a 1 x 1 box, y downward; the details are the ribs and
    the whorls' spiral, drawn light (Edits.detail_lines)."""
    out = {}
    # The scallop, its hinge at (0, 0), the fan's radius 1.
    rim, lobes, ribs = [], 7, []
    for k in range(141):
        t = k / 140
        phi = math.radians(165 - 150 * t)
        part = (lobes * t) % 1.0 if k < 140 else 0.0
        r = 0.88 + 0.12 * math.sqrt(math.sin(math.pi * part))
        rim.append((r * math.cos(phi), -r * math.sin(phi)))
    scallop = rim + [(0.34, -0.1), (0.34, 0.02), (-0.34, 0.02), (-0.34, -0.1)]
    for k in range(1, lobes):
        phi = math.radians(165 - 150 * k / lobes)
        ribs.append([(0.0, -0.02), (0.86 * math.cos(phi), -0.86 * math.sin(phi))])
    ribs += [[(0.0, -0.02), (0.34, -0.1)], [(0.0, -0.02), (-0.34, -0.1)]]
    # Taller than the fan's own circle (the owner, 2026-10-09: the first was "too squashed").
    tall = lambda pt: (pt[0], pt[1] * 1.35)
    out["scallop"] = ([tall(pt) for pt in scallop], [[tall(pt) for pt in rib] for rib in ribs])
    # The snail's shell: a spiral growing 1.8 times a turn; its last whorl is the outline, closed by
    # the opening's lip, and the turns inside it the detail line.  Turned so the opening is at the
    # lower right, as in the owner's picture.
    b = math.log(1.8) / (2 * math.pi)
    turn_by = math.radians(35)

    def at(theta):
        r = math.exp(b * theta)
        x, y = r * math.cos(theta), r * math.sin(theta)
        return (x * math.cos(turn_by) - y * math.sin(turn_by), x * math.sin(turn_by) + y * math.cos(turn_by))
    whorl = [at(2 * math.pi * k / 120) for k in range(121)]
    inner = [at(-5 * math.pi + 5 * math.pi * k / 200) for k in range(201)]
    out["snail"] = (whorl, [inner])
    out.update(_more_shapes())
    fitted = {}
    for name, value in out.items():
        edge, lines = value[0], value[1]
        decor = value[2] if len(value) > 2 else []
        xs, ys = zip(*(edge + ([q for line in decor for q in line] if name in FIT_EVERYTHING else [])))
        x0, y0, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        if name in SHAPE_BAKES:
            # Drawn as the owner straightened it (SHAPE_BAKES): mirrored across (when it is) and turned about
            # its box's middle, as a portrait turned and flipped so drew it, then fitted about that middle,
            # so the face and words stay where they were on it.  BAKED keeps the boxes' sides (the old box
            # one tall), for own_box and for moving a tree saved before (settle_shapes).
            degrees, mirrored = SHAPE_BAKES[name]
            cx, cy, m = x0 + w / 2, y0 + h / 2, -1 if mirrored else 1
            moved = lambda line: [turn(m * (x - cx) / h, (y - cy) / h, degrees) for x, y in line]
            edge = moved(edge)[::-1] if mirrored else moved(edge)    # the same way round (outline())
            lines, decor = [moved(line) for line in lines], [moved(line) for line in decor]
            xs, ys = zip(*(edge + ([q for line in decor for q in line] if name in FIT_EVERYTHING else [])))
            BAKED[name] = {"old_w": w / h, "old_h": 1.0, "new_w": 2 * max(map(abs, xs)), "new_h": 2 * max(map(abs, ys))}
            x0, y0 = -BAKED[name]["new_w"] / 2, -BAKED[name]["new_h"] / 2
            w, h = BAKED[name]["new_w"], BAKED[name]["new_h"]
        unit = lambda p: ((p[0] - x0) / w, (p[1] - y0) / h)
        fitted[name] = ([unit(p) for p in edge], [[unit(p) for p in line] for line in lines], w / h,
                        [[unit(p) for p in line] for line in decor])
    return fitted


def _smooth(points: list[tuple[float, float]], closed: bool = False, steps: int = 8) -> list[tuple[float, float]]:
    """A curve through `points` (Catmull-Rom), `steps` points between each two."""
    pts = list(points)
    n = len(pts)
    out = []
    last = n if closed else n - 1
    for i in range(last):
        p0 = pts[(i - 1) % n] if closed or i > 0 else pts[i]
        p1, p2 = pts[i], pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed or i + 2 < n else p2
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    if not closed:
        out.append(pts[-1])
    return out


def _ring(cx: float, cy: float, rx: float, ry: float, n: int = 48) -> list[tuple[float, float]]:
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]


def _envelope(polygons: list, centre: tuple[float, float], rays: int = 360) -> list[tuple[float, float]]:
    """The outer edge of several overlapping polygons together, seen from `centre` (inside them): along
    each ray, the farthest place any polygon's edge crosses it."""
    out = []
    cx, cy = centre
    for k in range(rays):
        a = 2 * math.pi * k / rays
        dx, dy = math.cos(a), math.sin(a)
        far = 0.0
        for poly in polygons:
            for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
                ex, ey = bx - ax, by - ay
                den = dx * ey - dy * ex
                if abs(den) < 1e-12:
                    continue
                s = ((ax - cx) * ey - (ay - cy) * ex) / den        # along the ray
                u = ((ax - cx) * dy - (ay - cy) * dx) / den        # along the edge
                if s > 0 and 0 <= u <= 1:
                    far = max(far, s)
        out.append((cx + far * dx, cy + far * dy))
    return out


def _inside_poly(poly, x, y) -> bool:
    hit = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


# Shapes whose box takes in their border-drawn parts too: a paw print's toes stand apart from its pad.
FIT_EVERYTHING = ("paw", "feather", "beetle")
FILLED_DECOR = ("paw",)


def _more_shapes() -> dict:
    """The owner's pictures of 2026-10-09: a hibiscus, a sand dollar, a turtle's shell
    (upright and on its side) and a mermaid's tail -- each (outline, light detail lines, lines drawn
    like the border), y downward, before fitting to the 1 x 1 box."""
    out = {}


    # A hibiscus: five broad petals, one straight up; the stamen out to the upper right with its
    # pollen, and light streaks from the middle.
    petals = []
    for k in range(200):
        a = 2 * math.pi * k / 200
        lobe = abs(math.cos(5 * (a + math.pi / 2) / 2)) ** 0.45
        r = 0.5 + 0.5 * lobe + 0.025 * math.cos(15 * (a + math.pi / 2))
        petals.append((r * math.cos(a), r * math.sin(a)))
    streaks = [[(0.1 * math.cos(a), 0.1 * math.sin(a)), (0.36 * math.cos(a), 0.36 * math.sin(a))]
               for a in (2 * math.pi * k / 10 + math.pi / 10 for k in range(10))]
    stamen = _smooth([(0.02, 0.02), (0.25, -0.25), (0.42, -0.55), (0.5, -0.85)], steps=6)
    pollen = [_ring(x, y, 0.045, 0.045, 12) for x, y in ((0.4, -0.92), (0.52, -1.0), (0.62, -0.88), (0.6, -0.75))]
    out["hibiscus"] = (petals, streaks, [stamen] + pollen)

    # A sand dollar: round, a small dip at the top; five petal loops round a centre dot, and five
    # slots between them towards the edge.
    disc = []
    for k in range(120):
        a = 2 * math.pi * k / 120
        dip = 0.06 * math.exp(-((math.atan2(math.sin(a + math.pi / 2), math.cos(a + math.pi / 2))) / 0.3) ** 2)
        disc.append(((1 - dip) * math.cos(a), (1 - dip) * math.sin(a)))
    marks = [_ring(0, 0, 0.07, 0.07, 16)]
    for k in range(5):
        a = math.radians(-90 + 72 * k)
        ca, sa = math.cos(a), math.sin(a)
        loop = []
        for s in range(41):
            u = s / 40 * 2
            along = u if u <= 1 else 2 - u
            across = (1 if u <= 1 else -1) * 0.12 * math.sin(math.pi * along)
            r = 0.12 + 0.5 * along
            loop.append((r * ca - across * sa, r * sa + across * ca))
        marks.append(loop)
        b = math.radians(90 + 72 * k)
        reach = 0.95 if k == 0 else 0.85
        marks.append([(0.62 * math.cos(b), 0.62 * math.sin(b)), (reach * math.cos(b), reach * math.sin(b))])
    out["sand_dollar"] = (disc, marks)

    # A turtle's shell, upright: an oval with a notched rim, an inner rim, three hexagons down the
    # middle and the side plates between them and the rim.
    a_x, a_y = 0.8, 1.0
    shell = []
    for k in range(168):
        a = 2 * math.pi * k / 168
        notch = 0.97 if (k % 12) in (0, 1) else 1.0
        shell.append((notch * a_x * math.cos(a), notch * a_y * math.sin(a)))
    rim_s = 0.86

    def to_rim(x, y, dx, dy):
        for s in range(1, 400):
            px, py = x + dx * s * 0.005, y + dy * s * 0.005
            if (px / (a_x * rim_s)) ** 2 + (py / (a_y * rim_s)) ** 2 >= 1:
                return (px, py)
        return (x, y)
    plates = [_ring(0, 0, a_x * rim_s, a_y * rim_s, 96)]
    w, h = 0.27, 0.2
    for cy in (-0.4, 0.0, 0.4):
        plates.append([(-w, cy), (-w / 2, cy - h), (w / 2, cy - h), (w, cy), (w / 2, cy + h), (-w / 2, cy + h), (-w, cy)])
        for sx in (-1, 1):
            plates.append([(sx * w, cy), to_rim(sx * w, cy, sx, 0)])
    for sx in (-1, 1):
        plates.append([(sx * w / 2, -0.6), to_rim(sx * w / 2, -0.6, sx * 0.45, -1)])
        plates.append([(sx * w / 2, 0.6), to_rim(sx * w / 2, 0.6, sx * 0.45, 1)])
    out["turtle_v"] = (shell, plates)
    out["turtle_h"] = ([(y, x) for x, y in shell], [[(y, x) for x, y in line] for line in plates])

    # A mermaid's tail, traced from the owner's picture (1600 pixels square): two fins over a narrow
    # waist, a wide foot; the fins' lines and five rows of scales.
    tail = _smooth([(108, 40), (330, 110), (560, 210), (680, 330), (705, 410), (760, 300), (930, 190), (1130, 110),
                    (1290, 30), (1280, 200), (1180, 400), (1000, 560), (860, 650), (845, 760), (930, 960),
                    (1040, 1180), (1100, 1400), (1150, 1525), (900, 1490), (600, 1495), (300, 1560), (360, 1350),
                    (450, 1120), (560, 930), (600, 790), (560, 690), (380, 570), (210, 410), (120, 230)],
                   closed=True, steps=6)
    fins = [_smooth([(240, 250), (330, 410), (480, 530), (640, 690)], steps=8),
            _smooth([(1230, 150), (1150, 310), (960, 450), (830, 580)], steps=8)]

    def scales(y, x0, x1, n):
        row, step = [], (x1 - x0) / n
        for i in range(n):
            row += [(x0 + step * (i + s / 10), y - 70 * math.sin(math.pi * s / 10)) for s in range(11)]
        return row
    rows = [scales(840, 650, 830, 1), scales(960, 560, 910, 2), scales(1110, 470, 990, 3),
            scales(1260, 420, 1030, 4), scales(1410, 440, 1040, 3)]
    out["mermaid_tail"] = ([(x / 1000, y / 1000) for x, y in tail],
                           [[(x / 1000, y / 1000) for x, y in line] for line in fins + rows])
    # On its side too (the owner, 2026-10-09): the fins to the left, the foot to the right.
    out["mermaid_tail_h"] = ([(y, x) for x, y in out["mermaid_tail"][0]], [[(y, x) for x, y in line] for line in out["mermaid_tail"][1]])

    # A fish, the owner's picture (540 pixels square), facing right: a smooth body to a rounded nose,
    # a forked tail with sharp tips; an eye and a gill, light.  And the same fish facing left.
    body = _smooth([(148, 240), (230, 200), (330, 178), (430, 192), (500, 230), (525, 272), (500, 315), (430, 352),
                    (330, 372), (230, 355), (142, 292)], steps=8)
    lower = _smooth([(142, 292), (90, 327), (15, 355)], steps=6)
    upper = _smooth([(15, 180), (85, 205), (148, 240)], steps=6)
    fish = body + lower[1:] + [(70, 268)] + upper[:-1]
    face = [_ring(452, 252, 11, 11, 16), _smooth([(395, 215), (410, 272), (395, 330)], steps=8)]
    out["fish_right"] = ([(x / 540, y / 540) for x, y in fish], [[(x / 540, y / 540) for x, y in l] for l in face])
    out["fish_left"] = ([(-x / 540, y / 540) for x, y in fish], [[(-x / 540, y / 540) for x, y in l] for l in face])

    # An ocean wave in a circle, the owner's picture: the circle the outline, the wave across it,
    # curling over at the top, a light detail (the owner, 2026-10-09).
    cx, cy, r = 195, 240, 185
    wave = _smooth([(12, 268), (60, 276), (120, 242), (180, 202), (228, 192), (256, 200), (230, 212), (216, 240),
                    (226, 274), (252, 288), (300, 271), (350, 255), (378, 252)], steps=8)
    out["wave_circle"] = (_ring(0, 0, 1, 1, 96), [[((x - cx) / r, (y - cy) / r) for x, y in wave]])   # the wave light

    # A conch (the owner, 2026-10-09: the first was "too fat for a conch shell"): a slim shell, a
    # pointed stepped spire on top, widest at the shoulder, tapering to a point below, its lip flaring a
    # little on the right; the spire's steps and the opening, light.
    conch = _smooth([(0, 0), (35, 70), (55, 82), (82, 150), (110, 162), (142, 228), (185, 245), (232, 268),
                     (262, 305), (285, 390), (298, 485), (272, 600), (205, 722), (125, 842), (52, 948), (14, 1000),
                     (-18, 960), (-60, 850), (-128, 700), (-196, 545), (-238, 405), (-248, 322), (-222, 272),
                     (-188, 250), (-142, 234), (-110, 162), (-78, 150), (-55, 82), (-32, 70)], closed=True, steps=6)
    bands = [_smooth(band, steps=8) for band in (
        [(-55, 82), (0, 92), (55, 82)], [(-110, 162), (0, 176), (110, 162)], [(-188, 250), (0, 268), (185, 245)])]
    mouth = _smooth([(150, 320), (222, 450), (205, 620), (125, 780), (42, 905), (78, 760), (118, 600),
                     (128, 450), (150, 320)], steps=6)
    out["conch"] = ([(x / 1000, y / 1000) for x, y in conch],
                    [[(x / 1000, y / 1000) for x, y in line] for line in bands + [mouth]])

    # A starfish, the owner's picture: five plump arms with rounded tips and curved sides between
    # them; a ring in the middle, a band and a row of dots down each arm, a line into each gap.
    body = []
    for k in range(250):
        a = 2 * math.pi * k / 250
        # 0 at an arm's tip, 1 halfway to the next: arms tapering to a rounded tip, plump sides.
        off = abs(((a + math.pi / 2) / (2 * math.pi / 5) + 0.5) % 1 - 0.5) * 2
        r = 0.5 + 0.5 * (1 - off) ** 1.25 - 0.06 * max(0.0, 1 - off / 0.12) ** 2
        body.append((r * math.cos(a), r * math.sin(a)))
    marks = [_ring(0, 0, 0.13, 0.13, 32)]
    for k in range(5):
        a = math.radians(-90 + 72 * k)
        ca, sa = math.cos(a), math.sin(a)
        for side in (1, -1):
            marks.append([((0.13 + 0.8 * u) * ca - side * 0.075 * math.sin(math.pi * min(1, u * 1.15)) * sa,
                           (0.13 + 0.8 * u) * sa + side * 0.075 * math.sin(math.pi * min(1, u * 1.15)) * ca)
                          for u in (s / 20 for s in range(21))])
        marks += [_ring((0.2 + 0.12 * d) * ca, (0.2 + 0.12 * d) * sa, 0.022, 0.022, 10) for d in range(6)]
        b = math.radians(-54 + 72 * k)
        marks.append([(0.14 * math.cos(b), 0.14 * math.sin(b)), (0.42 * math.cos(b), 0.42 * math.sin(b))])
    out["starfish"] = (body, marks)

    # A ship's wheel, the owner's picture: the rim with eight rounded handles out from it the outline;
    # the inner rim, the hub and the eight spokes (each a pair of lines), light.
    wheel, half, reach, cap = [], 0.075, 1.3, 0.095
    d = math.asin(half)
    for k in range(8):
        a = math.radians(-90 + 45 * k)
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        wheel.append((math.cos(a - d), math.sin(a - d)))
        # out along the handle, round its end, and back (a half circle about its end's middle)
        wheel += [(reach * ux + cap * (-math.cos(s) * nx + math.sin(s) * ux),
                   reach * uy + cap * (-math.cos(s) * ny + math.sin(s) * uy)) for s in
                  (math.pi * j / 12 for j in range(13))]
        wheel.append((math.cos(a + d), math.sin(a + d)))
        b = a + math.radians(45)
        wheel += [(math.cos(a + d + (b - a - 2 * d) * j / 12), math.sin(a + d + (b - a - 2 * d) * j / 12))
                  for j in range(1, 12)]
    hub = [_ring(0, 0, 0.75, 0.75, 72), _ring(0, 0, 0.17, 0.17, 32), _ring(0, 0, 0.1, 0.1, 24)]
    for k in range(8):
        a = math.radians(45 * k)
        ca, sa = math.cos(a), math.sin(a)
        for side in (-0.045, 0.045):
            hub.append([(0.19 * ca - side * sa, 0.19 * sa + side * ca), (0.74 * ca - side * sa, 0.74 * sa + side * ca)])
    out["ship_wheel"] = (wheel, hub)

    # A coconut, the owner's picture: nearly round, its three eyes right at the top drawn like the
    # border, and short hair-like fibres all over it, light.
    nut = [(0.96 * math.cos(a), math.sin(a)) for a in (2 * math.pi * k / 120 for k in range(120))]
    eyes = [_ring(x, y, 0.1, 0.08, 20) for x, y in ((-0.2, -0.8), (0.2, -0.8), (0.0, -0.6))]
    fibres = []
    for row in range(-3, 5):
        y = row * 0.2
        across = 0.96 * math.sqrt(max(0.0, 1 - (y / 0.98) ** 2))
        n = max(1, int(across / 0.17))
        for i in range(n):
            x = -across + (2 * across) * (i + 0.5 + 0.3 * ((row + i) % 2)) / (n + 0.3)
            if y < -0.45 and abs(x) < 0.35:
                continue                        # leave the eyes clear
            lean = x * 0.12                     # following the coconut's round
            fibres.append([(x - lean * 0.5, y - 0.06), (x, y), (x + lean * 0.5, y + 0.06)])
    out["coconut"] = (nut, fibres, eyes)


    # A bunch of three bananas (the owner, 2026-10-09: the traced one "doesnt look natural"): three
    # curved bananas from one stem at the upper left, each tapering to a blunt tip at the right, the
    # lower ones longer and lower; the outline is all of them together, and the edges where one lies
    # over the next and their ridges are light.
    def banana(c1, end, width):
        sx, sy = 0.0, 0.0
        centre = [((1 - u) ** 2 * sx + 2 * (1 - u) * u * c1[0] + u * u * end[0],
                   (1 - u) ** 2 * sy + 2 * (1 - u) * u * c1[1] + u * u * end[1]) for u in (k / 40 for k in range(41))]
        upper, lower = [], []
        for k, (x, y) in enumerate(centre):
            a, b = centre[max(0, k - 1)], centre[min(40, k + 1)]
            tx, ty = b[0] - a[0], b[1] - a[1]
            n = math.hypot(tx, ty) or 1.0
            nx, ny = ty / n, -tx / n                                   # to the banana's upper side
            u = k / 40
            w = width * (min(1.0, u / 0.25) ** 0.7) * (1 - 0.55 * max(0.0, (u - 0.75) / 0.25) ** 2)
            w = max(w, 0.018)
            upper.append((x + nx * w, y + ny * w))
            lower.append((x - nx * w, y - ny * w))
        return upper + lower[::-1], upper, centre
    stalk = [(-0.07, -0.02), (-0.11, -0.1), (-0.04, -0.13), (0.03, -0.04)]
    b1 = banana((0.18, 0.42), (0.98, 0.12), 0.095)
    b2 = banana((0.14, 0.66), (1.02, 0.36), 0.105)
    b3 = banana((0.1, 0.9), (0.96, 0.62), 0.115)
    outline_b = _envelope([stalk, b1[0], b2[0], b3[0]], (0.35, 0.42), rays=480)
    seams = [b2[1][6:39], b3[1][6:39]]                                  # where one lies over the next
    ridges = [b1[2][8:38], b2[2][8:38], b3[2][8:38]]
    def nub(centre_line: list, k: int, length: float, width: float) -> list:
        """The dark nub at a banana's end (the owner, 2026-10-09: "the dark spots on the banana's edges and
        stem ... as details (outlined not filled in)"): a small rounded spot reaching just past the tip,
        a little uneven, as the dried flower end is."""
        (cx, cy), (ax, ay) = centre_line[40], centre_line[k]
        tx, ty = cx - ax, cy - ay
        m = math.hypot(tx, ty) or 1.0
        tx, ty = tx / m, ty / m
        nx, ny = -ty, tx
        mx, my = cx - tx * length * 0.25, cy - ty * length * 0.25
        out_pts = []
        for s in range(24):
            a = 2 * math.pi * s / 24
            r = 1 + 0.12 * math.sin(3 * a + 0.7)
            out_pts.append((mx + tx * length * 0.5 * r * math.cos(a) + nx * width * r * math.sin(a),
                            my + ty * length * 0.5 * r * math.cos(a) + ny * width * r * math.sin(a)))
        return out_pts + out_pts[:1]
    spots = [nub(b[2], 36, 0.07, 0.03) for b in (b1, b2, b3)]
    # The stem's dark cut end: a ragged spot over the top of the stalk.
    top = [(-0.112, -0.098), (-0.09, -0.118), (-0.06, -0.13), (-0.035, -0.128), (-0.03, -0.108), (-0.05, -0.092),
           (-0.075, -0.083), (-0.1, -0.084)]
    spots.append(_smooth(top, closed=True, steps=4) + [top[0]])
    # The owner, 2026-10-09, of this drawn bunch with its outlined nubs over the one traced from a photo:
    # "I like these bananas better".
    out["bananas"] = (outline_b, seams + ridges + spots)

    # An anchor, traced from the owner's picture (550 pixels across): the ring on top, the stock with its
    # round ends, the shank, the curved arms with their barbs; the ring's hole and the shank's middle
    # line, light.
    half = [(275, 18), (300, 24), (316, 48), (312, 78), (296, 98), (297, 150), (378, 150), (395, 143), (413, 152),
            (416, 170), (402, 185), (380, 180), (300, 180), (302, 300), (306, 372), (335, 385), (382, 368),
            (410, 330), (395, 318), (455, 272), (462, 335), (442, 326), (424, 372), (380, 420), (320, 447), (275, 462)]
    whole = half + [(550 - x, y) for x, y in reversed(half[1:-1])]
    ring_hole = _ring(275, 60, 22, 22, 28)
    whole = _smooth(whole, closed=True, steps=4)
    out["anchor"] = ([(x / 550, y / 550) for x, y in whole],
                     [[(x / 550, y / 550) for x, y in line] for line in (ring_hole, [(275, 100), (275, 456)])])

    # A paw print (the owner, 2026-10-09: "add a new shape: paw print!"): the big pad, three soft lobes at its
    # foot, and four oval toes in an arc above it -- the outer two lower and leaning out -- drawn like the
    # border, each its own circle (one flower each on a vine of flowers).  The portrait's box takes in the
    # toes (FIT_EVERYTHING).
    pad = _smooth([(-0.36, 0.0), (0.0, -0.07), (0.36, 0.0), (0.56, 0.22), (0.58, 0.48), (0.44, 0.7),
                   (0.22, 0.68), (0.0, 0.78), (-0.22, 0.68), (-0.44, 0.7), (-0.58, 0.48), (-0.56, 0.22)],
                  closed=True, steps=8)

    def toe(cx: float, cy: float, lean: float) -> list:
        a = math.radians(lean)
        return [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a))
                for x, y in _ring(0, 0, 0.16, 0.22, 36)]
    out["paw"] = (pad, [], [toe(-0.64, -0.2, -28), toe(-0.23, -0.47, -8), toe(0.23, -0.47, 8), toe(0.64, -0.2, 28)])

    # The owner, 2026-10-09: "New portrait shapes: Feather, Coral, Beetle".
    # A feather, upright and gently curved: a rounded tip, the vane wider on one side of the shaft than the
    # other, a split in each edge, and the bare quill below drawn like the border; the shaft and barbs light.
    def bow(y: float) -> float:
        return 0.08 * (1 - ((y - 0.0) / 1.05) ** 2)       # the shaft's gentle curve
    def half(s: float, wide: float, split: float) -> float:   # s: 0 at the vane's foot, 1 at its tip
        w = wide * min(1.0, s / 0.2) ** 0.6 * (1 - s) ** 0.42
        return w * (1 - 0.32 * max(0.0, 1 - abs(s - split) / 0.035))
    foot, tip = 0.6, -1.0
    ys = [foot + (tip - foot) * k / 60 for k in range(61)]
    s_of = lambda y: (foot - y) / (foot - tip)
    right = [(bow(y) + half(s_of(y), 0.42, 0.42), y) for y in ys]
    left = [(bow(y) - half(s_of(y), 0.55, 0.6), y) for y in reversed(ys)]
    vane = right + left[1:-1]
    shaft = [(bow(y), y) for y in ys[:-4]]
    barbs = []
    for k in range(1, 12):
        s = k * 0.075
        y = foot + (tip - foot) * s
        for wide, split, side in ((0.42, 0.42, 1), (0.55, 0.6, -1)):
            y2 = foot + (tip - foot) * min(0.97, s + 0.07)
            barbs.append([(bow(y), y), (bow(y2) + side * 0.88 * half(s_of(y2), wide, split), y2)])
    quill = _smooth([(bow(foot), foot), (bow(0.8) - 0.01, 0.8), (bow(1.0) - 0.05, 1.0)], steps=6)
    out["feather"] = (vane, [shaft] + barbs, [quill])

    # Three corals (the owner picked all three, 2026-10-09). Each is traced from overlapping pieces: a test
    # of whether a point is in it, and the box it lies in.
    def tapered(ax, ay, bx, by, ra, rb):          # a branch thinning from ra to rb, its ends round
        def inside(x, y):
            dx, dy = bx - ax, by - ay
            u = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            r = ra + (rb - ra) * u
            return (x - ax - u * dx) ** 2 + (y - ay - u * dy) ** 2 <= r * r
        r = max(ra, rb)
        return inside, (min(ax, bx) - r, min(ay, by) - r, max(ax, bx) + r, max(ay, by) + r)

    def oval(cx, cy, rx, ry):
        return (lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1), (cx - rx, cy - ry, cx + rx, cy + ry)

    # A branching (staghorn) coral on a rounded rock: uneven branches thinning to round tips, forking as they
    # grow; each branch's middle line light.
    chains = [([(0.0, 0.82), (-0.04, 0.45), (-0.08, 0.28)], [0.2, 0.18, 0.17]),
              ([(-0.08, 0.28), (-0.36, 0.04), (-0.5, -0.3), (-0.6, -0.72)], [0.16, 0.13, 0.1, 0.07]),
              ([(-0.36, 0.04), (-0.18, -0.34), (-0.24, -0.82)], [0.12, 0.09, 0.065]),
              ([(-0.08, 0.28), (0.24, 0.0), (0.34, -0.42), (0.28, -0.9)], [0.16, 0.13, 0.1, 0.07]),
              ([(0.24, 0.0), (0.55, -0.18), (0.74, -0.56)], [0.11, 0.085, 0.065]),
              ([(-0.5, -0.3), (-0.78, -0.42), (-0.86, -0.64)], [0.08, 0.06, 0.05]),
              ([(0.34, -0.42), (0.08, -0.62)], [0.08, 0.055])]
    parts = [oval(0.0, 0.86, 0.46, 0.16)]
    for pts, radii in chains:
        parts += [tapered(*pts[i], *pts[i + 1], radii[i], radii[i + 1]) for i in range(len(pts) - 1)]
    out["coral"] = (_outlined(parts), [_smooth(pts, steps=6) for pts, _radii in chains])

    # A sea fan: a wide, gently scalloped fan on a thin stem and a little foot, its branches spreading from
    # the stem and forking to the rim, crossed by rings of its mesh -- light.
    def fan(x, y):
        return (x / 0.9) ** 2 + ((y + 0.18) / 0.72) ** 2 <= 1 - 0.035 * math.sin(11 * math.atan2(y + 0.18, x)) and y < 0.36
    blade = _outlined([(fan, (-0.9, -0.9, 0.9, 0.36)), tapered(0.0, 0.3, 0.0, 0.84, 0.1, 0.12),
                       oval(0.0, 0.9, 0.34, 0.11)])
    veins = [[(0.0, 0.7), (0.0, 0.3)]]
    def grow(x, y, angle, length, depth):
        x2, y2 = x + length * math.cos(angle), y + length * math.sin(angle)
        if (x2 / 0.82) ** 2 + ((y2 + 0.18) / 0.64) ** 2 > 1:
            return
        veins.append([(x, y), (x2, y2)])
        if depth:
            grow(x2, y2, angle - 0.2, length * 0.85, depth - 1)
            grow(x2, y2, angle + 0.2, length * 0.85, depth - 1)
    for spread in (-1.0, -0.5, 0.0, 0.5, 1.0):
        grow(0.0, 0.3, -math.pi / 2 + spread, 0.34, 3)
    for k in range(2, 5):
        veins.append([(0.84 * k / 5 * math.cos(a), -0.18 + 0.66 * k / 5 * math.sin(a))
                      for a in (math.pi + math.pi * i / 40 for i in range(41))])
    out["sea_fan"] = (blade, veins)

    # A brain coral: a round dome on a flat foot, its winding grooves -- light.
    dome = _outlined([(lambda x, y: (x / 0.95) ** 2 + ((y - 0.15) / 0.82) ** 2 <= 1 and y <= 0.7,
                       (-0.95, -0.7, 0.95, 0.7))])
    grooves = []
    for k, y0 in enumerate((-0.5, -0.28, -0.06, 0.16, 0.38, 0.6)):
        run = []
        for i in range(81):
            x = -1 + 2 * i / 80
            y = y0 + 0.06 * math.sin(x * 8.5 + k * 1.7) + 0.03 * math.sin(x * 19 + k * 2.3)
            if (x / 0.86) ** 2 + ((y - 0.15) / 0.74) ** 2 < 1 and y < 0.62:
                run.append((x, y))
            elif run:
                grooves.append(run)
                run = []
        if len(run) > 1:
            grooves.append(run)
    out["brain_coral"] = (dome, [g for g in grooves if len(g) > 1])

    # A beetle seen from above, head up: the round head, the shield behind it and the two wing cases meeting
    # down the middle, a few spots on them -- light; six legs and two antennae drawn like the border.
    def oval(cy, rx, ry):
        return (lambda x, y: (x / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1), (-rx, cy - ry, rx, cy + ry)
    shell = _outlined([oval(0.2, 0.48, 0.7), oval(-0.52, 0.36, 0.2), oval(-0.74, 0.22, 0.14)])
    seam = [(0.0, -0.36), (0.0, 0.88)]
    shield = _smooth([(-0.4, -0.38), (0.0, -0.32), (0.4, -0.38)], steps=6)
    spots = [_ring(x, y, 0.07, 0.08, 16) for x, y in ((-0.2, -0.05), (0.2, -0.05), (-0.24, 0.3), (0.24, 0.3),
                                                      (-0.17, 0.6), (0.17, 0.6))]
    legs = []
    for side in (1, -1):
        for (sx, sy), (kx, ky), (fx, fy) in (((0.38, -0.3), (0.62, -0.42), (0.74, -0.6)),
                                             ((0.46, 0.08), (0.74, 0.08), (0.86, -0.04)),
                                             ((0.42, 0.45), (0.68, 0.62), (0.76, 0.86))):
            legs.append([(side * sx, sy), (side * kx, ky), (side * fx, fy)])
    antennae = [_smooth([(side * 0.08, -0.86), (side * 0.2, -1.02), (side * 0.36, -1.1)], steps=4) for side in (1, -1)]
    out["beetle"] = (shell, [seam, shield] + spots, legs + antennae)

    # A monstera leaf, traced from the owner's picture (1920 pixels square): four slits cut in from the
    # right and lower edges and two from the left, four holes (drawn like the border); the midrib and the
    # curved vein marks, light.
    mon = _smooth([(600, 270), (625, 260), (750, 280), (860, 330), (912, 405), (906, 560), (897, 650), (907, 672),
                   (945, 620), (970, 520), (970, 420), (960, 340), (1000, 335), (1100, 370), (1182, 445),
                   (1160, 600), (1120, 750), (1116, 850), (1142, 880), (1200, 820), (1240, 700), (1272, 580),
                   (1285, 478), (1400, 540), (1500, 650), (1530, 740), (1450, 880), (1350, 1000), (1280, 1100),
                   (1272, 1165), (1300, 1170), (1400, 1110), (1530, 980), (1612, 842), (1642, 900), (1650, 1050),
                   (1640, 1200), (1590, 1290), (1500, 1330), (1350, 1370), (1212, 1412), (1170, 1480),
                   (1120, 1580), (1020, 1650), (870, 1680), (700, 1640), (660, 1598), (760, 1560), (900, 1500),
                   (945, 1460), (930, 1425), (880, 1410), (820, 1430), (720, 1500), (620, 1535), (500, 1500),
                   (400, 1400), (330, 1250), (292, 1050), (286, 885), (305, 875), (380, 940), (470, 980),
                   (560, 970), (640, 905), (672, 862), (600, 850), (480, 830), (395, 790), (370, 730),
                   (375, 620), (420, 500), (500, 440), (560, 390)], closed=True, steps=5)

    def hole(cx, cy, rx, ry, deg):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        return [(cx + rx * math.cos(a) * c - ry * math.sin(a) * s, cy + rx * math.cos(a) * s + ry * math.sin(a) * c)
                for a in (2 * math.pi * k / 24 for k in range(25))]
    holes = [hole(540, 695, 65, 45, 22), hole(985, 795, 24, 68, 12), hole(1312, 915, 48, 70, 32),
             hole(800, 1225, 90, 44, -25)]
    veins = [[(655, 310), (1190, 1385)]] + [_smooth(v, steps=6) for v in (
        [(585, 525), (630, 565), (682, 575)], [(822, 388), (842, 470), (828, 565)], [(1125, 500), (1090, 590), (1050, 660)],
        [(1395, 618), (1385, 690), (1350, 742)], [(665, 762), (740, 786), (820, 786)], [(660, 1010), (750, 1045), (830, 1022)],
        [(405, 1118), (480, 1165), (568, 1170)], [(1220, 990), (1180, 1080), (1140, 1150)],
        [(1575, 1110), (1530, 1200), (1435, 1260)], [(950, 1280), (1010, 1305), (1083, 1302)],
        [(405, 1338), (560, 1390), (715, 1348)], [(960, 1563), (1010, 1560), (1058, 1527)])]
    scale = lambda line: [(x / 1920, y / 1920) for x, y in line]
    # The holes are inside the leaf: light, like the veins (the owner: words may cross them, not the edge).
    # (Drawn turned: SHAPE_BAKES.)
    out["monstera"] = (scale(mon), [scale(v) for v in veins] + [scale(h) for h in holes])

    return out


SHELLS = _shells()


def _spokes(kind: str) -> list[list[tuple[float, float]]]:
    """Light lines from a shape's middle out towards each of its points, petals or wings: the
    outline's corners farthest from the middle, each standing well out from its neighbours."""
    pts = OUTLINES.get(kind)
    if not pts:
        return []
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    wide = ASPECTS.get(kind, 1.0)             # its own proportions, not the 1 x 1 box's
    dist = [math.hypot((px - cx) * wide, py - cy) for px, py in pts]
    n, mean = len(pts), sum(dist) / len(dist)
    near = max(1, n // 16)
    tips = [i for i in range(n) if dist[i] > mean * 1.12
            and all(dist[i] >= dist[(i + j) % n] for j in range(1, near + 1))
            and all(dist[i] > dist[(i - j) % n] for j in range(1, near + 1))]     # one line per flat tip
    out = []
    for i in tips:
        px, py = pts[i]
        start = 0.32 if kind == "flower" else 0.18          # the flower's lines begin outside its middle
        out.append([(cx + (px - cx) * start, cy + (py - cy) * start), (cx + (px - cx) * 0.86, cy + (py - cy) * 0.86)])
    return out


# The shapes that carry detail lines (the owner, 2026-10-09: "you can add detailing to the other
# shapes too", its colour, opacity and weight the player's: Edits.detail_*).
SPOKE_SHAPES = ("star", "plump_star", "star4", "star6", "slim_star6", "flower")


def _leaf_veins() -> list[list[tuple[float, float]]]:
    """The leaf's veins (the owner, 2026-10-09: "more interior detail veins"): the midrib from where the
    stalk meets the blade to the tip, and side veins from it towards the tip on both sides, each
    ending a little short of the edge -- in the leaf's 1 x 1 box, measured at its own proportions."""
    pts = OUTLINES.get("leaf")
    if not pts:
        return []
    wide = ASPECTS.get("leaf", 1.0)
    real = [(x * wide, y) for x, y in pts]
    # The tip and the stalk's end: the two corners farthest apart.
    best = (0.0, 0, 0)
    for i in range(0, len(real), 2):
        for j in range(i + 1, len(real), 2):
            d = (real[i][0] - real[j][0]) ** 2 + (real[i][1] - real[j][1]) ** 2
            if d > best[0]:
                best = (d, i, j)
    a, b = real[best[1]], real[best[2]]
    tip, stalk = (a, b) if a[1] < b[1] else (b, a)          # the tip is the upper one (it points up to the right)
    length = math.hypot(tip[0] - stalk[0], tip[1] - stalk[1])
    ux, uy = (tip[0] - stalk[0]) / length, (tip[1] - stalk[1]) / length
    nx, ny = -uy, ux

    def at(f, v=0.0):
        return (stalk[0] + ux * f * length + nx * v, stalk[1] + uy * f * length + ny * v)

    def inside_leaf(x, y):
        hit = False
        for (ax, ay), (bx, by) in zip(real, real[1:] + real[:1]):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                hit = not hit
        return hit
    base = 0.2                                                  # where the stalk meets the blade
    while base < 0.5 and not inside_leaf(*at(base, 0.04)):
        base += 0.01
    veins = [[at(base), at(0.96)]]
    for k in range(7):
        f = base + (0.9 - base) * (k + 0.6) / 7.5
        for side in (1, -1):
            sx, sy = at(f)
            dx, dy = ux * 0.75 + nx * side * 0.66, uy * 0.75 + ny * side * 0.66      # slanting towards the tip
            n = math.hypot(dx, dy)
            dx, dy = dx / n, dy / n
            reach = 0.0
            while reach < 1.0 and inside_leaf(sx + dx * (reach + 0.01), sy + dy * (reach + 0.01)):
                reach += 0.01
            if reach > 0.05:
                end = reach * 0.85
                mid = (sx + dx * end * 0.5 - ux * end * 0.06, sy + dy * end * 0.5 - uy * end * 0.06)
                veins.append([(sx, sy), mid, (sx + dx * end, sy + dy * end)])
    return [[(x / wide, y) for x, y in line] for line in veins]


@functools.lru_cache(maxsize=1)
def _butterfly_lines() -> tuple[list, list]:
    """The butterfly's lines (the owner, 2026-10-09: "should have curly antennae and lines for each
    part of its wings"), on the parts _drawn_outlines makes it of: (light lines -- the body, where
    each upper wing meets the lower, three veins in each wing --, the curly antennae, drawn like the
    border), in its 1 x 1 box."""
    wings = [(-0.36, -0.18, 0.4, 0.32, -20), (0.36, -0.18, 0.4, 0.32, 20),
             (-0.26, 0.28, 0.28, 0.24, 25), (0.26, 0.28, 0.28, 0.24, -25)]
    body = (0, 0.02, 0.2, 0.36, 0)

    def edge(part, t):
        cx, cy, rx, ry, turn_deg = part
        c, s = math.cos(math.radians(turn_deg)), math.sin(math.radians(turn_deg))
        u, v = rx * math.cos(t), ry * math.sin(t)
        return (cx + u * c - v * s, cy + u * s + v * c)

    def within(part, x, y):
        cx, cy, rx, ry, turn_deg = part
        c, s = math.cos(math.radians(turn_deg)), math.sin(math.radians(turn_deg))
        return (((x - cx) * c + (y - cy) * s) / rx) ** 2 + ((-(x - cx) * s + (y - cy) * c) / ry) ** 2 <= 1
    rim = [edge(part, 2 * math.pi * k / 180) for part in wings + [body] for k in range(180)]
    x0, x1 = min(p[0] for p in rim), max(p[0] for p in rim)
    y0, y1 = min(p[1] for p in rim), max(p[1] for p in rim)
    unit = lambda p: ((p[0] - x0) / (x1 - x0), (p[1] - y0) / (y1 - y0))
    light = [[unit(p) for p in _ring(0, 0.02, 0.06, 0.34, 40)]]                  # the body
    for upper, lower in ((wings[0], wings[2]), (wings[1], wings[3])):            # upper meets lower
        seam = [edge(upper, 2 * math.pi * k / 240) for k in range(240)]
        seam = [p for p in seam if within(lower, *p) and abs(p[0]) > 0.06]
        seam.sort(key=lambda p: p[0])
        if seam:
            light.append([unit(p) for p in seam])
    for part in wings:                                                       # three veins in each
        cx, cy = part[0], part[1]
        root = (0.06 if cx > 0 else -0.06, cy * 0.4)
        for k in (-1, 0, 1):
            far = (cx + (cx - root[0]) * 0.55 + k * 0.12 * (1 if cy < 0 else -1), cy + (cy - root[1]) * 0.55 + k * 0.12)
            if within(part, *far):
                light.append([unit(root), unit(far)])
    curls = []
    for side in (-1, 1):                                                     # curly antennae
        stalk = [(side * 0.02 + side * 0.22 * u ** 1.3, -0.3 - 0.42 * u) for u in (k / 20 for k in range(21))]
        ex, ey = stalk[-1]
        # The stalk, and its curled tip a little circle of its own (the owner, 2026-10-09: a special
        # border puts its rope or vine on the stalk and one flower or leaf on the circle).
        curls.append([unit(p) for p in stalk])
        curls.append([unit(p) for p in _ring(ex + side * 0.035, ey - 0.03, 0.04, 0.04, 16)])
    return light, curls


@functools.lru_cache(maxsize=None)
def details(kind: str) -> tuple:
    """A shape's detail lines in its 1 x 1 box, each a tuple of points; none for most shapes."""
    base, flip_h, flip_v = _unflipped(kind)
    if base != kind:
        return tuple(tuple(_mirror(line, flip_h, flip_v)) for line in details(base))
    if kind in SHELLS:
        return tuple(tuple(line) for line in SHELLS[kind][1])
    if kind == "flower":                # its petals' lines and a little circle in the middle, a daisy's
        r, wide = 0.12, ASPECTS.get("flower", 1.0)
        middle = tuple((0.5 + r / wide * math.cos(a), 0.5 + r * math.sin(a)) for a in (2 * math.pi * k / 32 for k in range(33)))
        return tuple(tuple(line) for line in _spokes(kind)) + (middle,)
    if kind in SPOKE_SHAPES:
        return tuple(tuple(line) for line in _spokes(kind))
    if kind == "leaf":
        return tuple(tuple(line) for line in _leaf_veins())
    if kind == "butterfly":
        return tuple(tuple(line) for line in _butterfly_lines()[0])
    return ()


def decor(kind: str) -> tuple:
    base, flip_h, flip_v = _unflipped(kind)
    if base != kind:
        return tuple(tuple(_mirror(line, flip_h, flip_v)) for line in decor(base))
    """Lines drawn like a shape's border, beside its outline: the hibiscus's
    stamen and pollen."""
    if kind == "butterfly":
        return tuple(tuple(line) for line in _butterfly_lines()[1])
    return tuple(tuple(line) for line in SHELLS[kind][3]) if kind in SHELLS else ()


def _raw_aspect(kind: str) -> float:
    xs, ys = zip(*_drawn_outlines()[kind])
    return (max(xs) - min(xs)) / (max(ys) - min(ys))


DRAWN_SHAPES = ("flower", "butterfly", "clover", "spade", "leaf")
# Their widths for their heights as traced (_raw_aspect), fixed so nothing is traced at start-up.
FLOWER_ASPECT, BUTTERFLY_ASPECT, CLOVER_ASPECT, SPADE_ASPECT, LEAF_ASPECT = 0.897, 1.447, 1.06, 0.872, 1.171


class _Outlines(dict):
    """The unit outlines; the traced ones (DRAWN_SHAPES) are worked out the first time one is
    asked for, not as the patcher starts (Codex, #575: tracing takes a noticeable moment)."""
    def __missing__(self, kind: str):
        if kind not in DRAWN_SHAPES:
            raise KeyError(kind)
        # Traced once, ahead of time, into data/tree_shapes.json (scripts/build_tree_shapes.py): tracing
        # here froze the window for seconds the first time a new shape was picked (Codex, #575).
        try:
            stored = json.loads(TREE_SHAPES_FILE.read_text(encoding="utf-8"))
            for name in DRAWN_SHAPES:
                self[name] = [(float(x), float(y)) for x, y in stored[name]]
        except (OSError, ValueError, KeyError, TypeError):
            for name, points in traced_unit_outlines().items():   # the file is missing: trace them
                self[name] = points
        return self[kind]

    def get(self, kind, default=None):
        try:
            return self[kind]
        except KeyError:
            return default


def traced_unit_outlines() -> dict[str, list[tuple[float, float]]]:
    """DRAWN_SHAPES traced and fitted to a 1 x 1 box (what data/tree_shapes.json holds)."""
    out = {}
    for name, points in _drawn_outlines().items():
        xs, ys = zip(*points)
        out[name] = [((px - min(xs)) / (max(xs) - min(xs)), (py - min(ys)) / (max(ys) - min(ys)))
                     for px, py in points]
    return out


TREE_SHAPES_FILE = Path(__file__).resolve().parents[1] / "data" / "tree_shapes.json"


OUTLINES = _Outlines(_unit_outlines())


SVG_DASHES = {"dotted": "1.5 4", "dashed": "8 5", "dashdot": "8 4 1.5 4"}
# Tk on Windows draws only its own patterns faithfully: a number pattern for "dashed" came out as dots, so the
# editor showed dotted, dashed and dotted-and-dashed borders alike (the owner, 2026-10-09: "i want the dots and
# dashes to alternate, not overlap").
TK_DASHES = {"dotted": ".", "dashed": "-", "dashdot": "-."}
GDI_DASHES = {"dotted": 2, "dashed": 1, "dashdot": 3}       # GDI+'s dash styles


# Each shape's own width for its height (the owner: "I want the shapes to not look so squashed
# horizontally. or vertically, by default"): a portrait's frame is drawn this wide for a portrait's
# height until the player resizes it.  The heart's and the star's are their outlines' own; a
# diamond is a playing card's.  A rectangle, a rounded rectangle and an oval fill the portrait.
ASPECTS = {"rect": 1.0, "rounded": 1.0, "circle": 1.0, "heart": 1.107, "star": 1.051, "triangle": 1.155, "diamond": 0.7, "cross": 0.75, "x": 1.0,
           "plus": 1.0, "hexagon": 0.866, "octagon": 1.0, "trapezoid": 1.2, "pentagon": 1.051, "star4": 0.863, "star6": 0.866, "plump_star": 1.051, "slim_star6": 0.866,
                "arrow_h": 1.6, "arrow_v": 0.625, "arch": 0.655,
                "oval_wide": 1.5}
ASPECTS.update({name: round(shape[2], 3) for name, shape in SHELLS.items()})
# The owner's shapes of 2026-10-08 take their own drawn proportions.
ASPECTS.update({"flower": FLOWER_ASPECT, "butterfly": BUTTERFLY_ASPECT, "clover": CLOVER_ASPECT, "spade": SPADE_ASPECT,
                "leaf": LEAF_ASPECT})      # _raw_aspect's, fixed (tests/test_tree_new_shapes.py checks them)
FRAME_MIN, FRAME_MAX = 8.0, 1200.0      # a resized frame's sides
# What the size boxes step through (the owner: "values correspond to typical font sizes"): a word
# processor's font sizes, on up to a whole portrait and beyond; line weights as a word processor's.
SIZE_STEPS = (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72, 96, 106, 120, 144, 156, 180, 200,
              240, 300, 400, 500, 600, 800, 1000, 1200)
LINE_STEPS = (0.25, 0.5, 0.75, 1, 1.5, 2.2, 2.25, 3, 4.5, 6, 8, 10, 12, 16, 20)


def own_box(kind: str, w: float, h: float) -> tuple[float, float]:
    """A frame's shape's own length and width: the frame's, but a shape drawn turned (SHAPE_BAKES) its
    traced box's, as it was before, in the box it now fills -- what a special border's leaves and a words'
    room measure, so they are as they were."""
    b = BAKED.get(base_kind(kind))
    if b is None:
        return w, h
    return w * b["old_w"] / b["new_w"], h * b["old_h"] / b["new_h"]


def natural_height(kind: str) -> float:
    """A portrait tall; a shape drawn turned (SHAPE_BAKES) as tall as it reached turned so from a
    portrait's height, so it is the size it was drawn turned (the owner's Monstera leaves, 2026-10-10)."""
    return NODE_H * BAKED[kind]["new_h"] if kind in BAKED else NODE_H


def natural_width(kind: str) -> float:
    return natural_height(kind) * ASPECTS[kind] if kind in ASPECTS else NODE_W


def shape_points(kind: str, x: float, y: float, w: float, h: float, radius: float = 0.0,
                 angle: float = 0.0) -> list[tuple[float, float]]:
    """Any shape's edge as corners (an oval by 48, each rounded corner by 6), turned `angle` degrees
    about the box's middle."""
    corners = outline(kind, x, y, w, h)
    if corners is None and kind in ("ellipse", "circle"):
        ox, oy, ow, oh = oval_box(kind, x, y, w, h)
        corners = [(ox + ow / 2 * (1 + math.cos(t)), oy + oh / 2 * (1 + math.sin(t)))
                   for t in (k * 2 * math.pi / 48 for k in range(48))]
    elif corners is None:
        r = min(radius, w / 2, h / 2)
        corners = [(cx + r * math.cos(math.radians(start + k * 18)), cy + r * math.sin(math.radians(start + k * 18)))
                   for cx, cy, start in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90),
                                         (x + r, y + r, 180))
                   for k in range(6)]
    if not angle:
        return corners
    mx, my = x + w / 2, y + h / 2
    return [(mx + dx, my + dy) for dx, dy in (turn(px - mx, py - my, angle) for px, py in corners)]


def inside(corners: list[tuple[float, float]], x: float, y: float) -> bool:
    """Whether (x, y) is inside the shape these corners outline."""
    hit = False
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def box_corners(cx: float, cy: float, w: float, h: float, angle: float) -> list[tuple[float, float]]:
    """A box's top left, top right, bottom right and bottom left, turned about its middle."""
    out = []
    for lx, ly in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        dx, dy = turn(lx * w / 2, ly * h / 2, angle)
        out.append((cx + dx, cy + dy))
    return out


def flipped_kind(kind: str, flip_h: bool, flip_v: bool) -> str:
    """A shape mirrored across (h) and/or up and down (v): "heart~h", "anchor~v", "star~hv".  A
    rectangle, rounded square, circle or oval looks the same flipped, so it keeps its own name."""
    if not (flip_h or flip_v) or OUTLINES.get(kind) is None:
        return kind
    return f"{kind}~{'h' if flip_h else ''}{'v' if flip_v else ''}"


def base_kind(kind: str) -> str:
    """A shape's own name, without its flips."""
    return kind.partition("~")[0]


def _unflipped(kind: str) -> tuple[str, bool, bool]:
    base, _, how = kind.partition("~")
    return base, "h" in how, "v" in how


def _mirror(points, flip_h: bool, flip_v: bool):
    return [((1 - px) if flip_h else px, (1 - py) if flip_v else py) for px, py in points]


def outline(kind: str, x: float, y: float, w: float, h: float) -> list[tuple[float, float]] | None:
    """A many-sided shape's corners in the box, or None for a square, rounded square, circle or oval
    (a flipped one, flipped_kind, mirrored)."""
    base, flip_h, flip_v = _unflipped(kind)
    unit = OUTLINES.get(base)
    if unit and (flip_h or flip_v):
        unit = _mirror(unit, flip_h, flip_v)
        if flip_h != flip_v:
            unit = unit[::-1]                     # the same way round as before (the special borders' outside)
    return [(x + px * w, y + py * h) for px, py in unit] if unit else None


def oval_box(kind: str, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """The box an oval fills: the whole box, or for a circle the largest square in its middle."""
    if kind != "circle":
        return x, y, w, h
    d = min(w, h)
    return x + (w - d) / 2, y + (h - d) / 2, d, d


def corner_radius(kind: str) -> float:
    return 24.0 if kind in ("rounded", "rounded_rect") else 0.0


def _edge_y(lay: "Layout", q: int, at: float, bottom: bool) -> float:
    """Where a straight up-and-down line at x `at` meets the edge of q's portrait: its bottom edge
    (`bottom`) or its top -- whatever its shape."""
    corners = lay.frame_points(q)
    meets = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        if min(ax, bx) <= at <= max(ax, bx) and ax != bx:
            meets.append(ay + (at - ax) / (bx - ax) * (by - ay))
    if not meets:                       # a frame made narrower than where the line comes down
        _x, y, _w, h, _a = lay.frame(q)
        return y + h if bottom else y
    return max(meets) if bottom else min(meets)


def key_marks(lay: Layout) -> list[tuple[str, str]]:
    """The Key: every mark someone in this tree has, in the player's order."""
    used = {label for q in lay.x for label in entry_marks(lay.entry(lay.village.people[q]))}
    return [(label, colour) for label, colour in lay.edits.marks.items() if label in used]


# ---------------------------------------------------------------------------
# The scene: everything the tree draws, once, for every way of drawing it (the page's SVG, the
# editor's canvas, the picture GDI+ saves).  Each item that belongs to a villager carries its id.
# ---------------------------------------------------------------------------

@dataclass
class Shape:
    kind: str                           # "rect", "ellipse" or "diamond"
    x: float
    y: float
    w: float
    h: float
    stroke: str
    width: float = 3.0
    fill: str | None = "#ffffff"
    radius: float = 8.0                 # a rect's corners
    dash: str = ""                      # BORDERS: "dotted", "dashed", "dashdot" or "" solid
    pid: int | None = None
    opacity: float = 1.0                # a plate behind words on a picture
    target: tuple | None = None         # what a right click recolours
    move: str = ""                      # MOVABLE: what dragging it moves
    angle: float = 0.0                  # turned this many degrees about its middle

    def points(self) -> list[tuple[float, float]]:
        return shape_points(self.kind, self.x, self.y, self.w, self.h, self.radius, self.angle)


@dataclass
class Line:
    points: list
    colour: str
    width: float = LINE_WIDTH
    target: tuple | None = None
    move: str = ""
    piece: str = ""                     # a family line's piece: "<family key>|<piece>", draggable
    opacity: float = 1.0
    dash: str = ""                      # LINE_TYPES
    pid: int | None = None              # the villager whose portrait it is part of (a border, a vine)
    casing: bool = False                # the thin outline under a family line that would blend into the background


@dataclass
class Poly:
    """A filled outline of any corners -- a special border's rope, vine, leaves and flowers (the owner,
    2026-10-09: "I want the vines to be vines, not just lines"); no `stroke` / `width`: fill only."""
    points: list
    fill: str | None
    stroke: str = ""
    width: float = 0.0
    opacity: float = 1.0
    pid: int | None = None              # the villager whose portrait it is part of
    target: tuple | None = None


@dataclass
class Text:
    x: float
    y: float                            # the baseline
    text: str
    size: float
    colour: str
    bold: bool = False
    centre: bool = False                # x is the middle (else the start)
    end: bool = False                   # x is the end: right-aligned words (Edits.text_align)
    angle: float = 0.0                  # turned this many degrees (clockwise) about (x, y): Edits.turn_words
    mirror_h: bool = False              # mirrored across, about x (Edits.flip_words)
    mirror_v: bool = False              # mirrored up and down, about the middle of its letters
    pid: int | None = None
    role: str = ""                      # ROLES: whose style the player may change
    font: str = ""
    italic: bool = False
    underline: bool = False
    strike: bool = False
    target: tuple | None = None
    move: str = ""
    part: str = ""                      # a generation label's line: "<generation>|<label_lines part>"
    edit: str = ""                      # what retyping it changes (the editor's _edit_in_place)
    opacity: float = 1.0
    # The words formatted word by word (a portrait's own text: node_runs): (text, style) pieces drawn
    # one after another as run_look says; None when every word has the item's own look.
    runs: list | None = None
    script: str = ""                    # the role's superscript or subscript, for runs (run_look)


@dataclass
class Head:
    x: float
    y: float
    sheet: str
    row: int
    pid: int | None = None
    opacity: float = 1.0
    scale: float = 1.0                  # of a resized portrait (HEAD_SCALE times this)


@dataclass
class Sticker:
    """A picture or a text box laid on the tree: its middle, size, turn (degrees clockwise),
    mirrorings and opacity (0-1).  `index` is its place in the edits' stickers; `picture` is None
    for a text box."""
    index: int
    picture: Path | None
    cx: float
    cy: float
    w: float
    h: float
    angle: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    opacity: float = 1.0
    text: str = ""
    font: str = ""
    size: float = 24.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    colour: str = INK
    align: str = "centre"
    valign: str = "middle"
    fill: str = ""
    fill_opacity: float = 100.0
    border: str = ""
    border_width: float = 0.0
    shape: str = "rect"

    def corners(self) -> list[tuple[float, float]]:
        """Top left, top right, bottom right, bottom left, turned."""
        return box_corners(self.cx, self.cy, self.w, self.h, self.angle)

    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = zip(*self.corners())
        return min(xs), min(ys), max(xs), max(ys)

    def contains(self, x: float, y: float) -> bool:
        lx, ly = turn(x - self.cx, y - self.cy, -self.angle)
        return abs(lx) <= self.w / 2 and abs(ly) <= self.h / 2


@dataclass
class Backdrop:
    colour: str
    colour2: str = ""                   # a gradient to this colour at the bottom, or a RAINBOWS key
    picture: Path | None = None
    fit: str = "cover"
    soften: int = 0                     # percent the picture fades (into the colour or gradient under it)


@dataclass
class Scene:
    width: float
    height: float
    background: str
    items: list = field(default_factory=list)
    boxes: dict = field(default_factory=dict)       # pid -> (x, y, w, h), what a click selects
    stickers: list = field(default_factory=list)    # the Sticker items, bottom one first
    # How the tree sits on a custom canvas (Edits.canvas_w / canvas_h): (scale, left, top), a point
    # (x, y) of the laid-out tree drawn at (x * scale + left, y * scale + top).  (1, 0, 0) on Automatic.
    fit: tuple = (1.0, 0.0, 0.0)


def to_page(sc: "Scene", x: float, y: float) -> tuple[float, float]:
    """A point of the laid-out tree (Layout's x / y / frames) where the page draws it (Scene.fit)."""
    s, ox, oy = sc.fit
    return x * s + ox, y * s + oy


def to_tree(sc: "Scene", x: float, y: float) -> tuple[float, float]:
    """A point of the page back in the laid-out tree's own units (to_page undone)."""
    s, ox, oy = sc.fit
    return (x - ox) / s, (y - oy) / s


def picture_path(name: str, images: Path | None, library: dict | None = None) -> Path | None:
    """A background picture's file: the player's own, one in this game's Images ("game:<file>"),
    or one in game N's ("vvN:<file>", `library` holding each known game's Images folder)."""
    if not name:
        return None
    path = None
    if name.startswith("asset:"):
        path = PICTURES / name[6:]
    elif name.startswith("game:"):
        path = Path(images) / name[5:] if images is not None else None
    elif name[:2] == "vv" and name[3:4] == ":" and name[2:3].isdigit():
        folder = (library or {}).get(int(name[2]))
        path = Path(folder) / name[4:] if folder is not None else None
    else:
        path = Path(name)
    return path if path is not None and path.is_file() else None


def presets_available(images: Path | None, library: dict | None = None) -> list[tuple]:
    """The ready-made backgrounds whose picture (if any) this computer has."""
    return [p for p in PRESETS if not p[3] or picture_path(p[3], images, library) is not None]


def scene(lay: Layout, game_title: str, present: dict, images: Path | None = None,
          library: dict | None = None) -> Scene:
    """The whole tree as shapes, lines, text and heads.  `present` names the head sheets found;
    `images` is the game's Images folder and `library` each known game's (for the games' own
    background pictures)."""
    v = lay.village
    ink = lay.ink
    out = Scene(lay.width, lay.height, lay.background)
    add = out.items.append
    add(Backdrop(lay.background, lay.edits.rainbow or lay.edits.background2, picture_path(lay.edits.background_image, images, library),
                 lay.edits.background_fit, 100 - lay.edits.background_opacity))
    t1, t2 = title_lines(lay, game_title)
    middle = lay.width / 2
    # The tree's heading over its founders (the owner: "the heading of the tree should preferably
    # be centered with the founders' portraits").
    first = lay.rows[min(lay.rows)] if lay.rows else []
    head = (min(lay.x[q] for q in first) + max(lay.x[q] for q in first) + NODE_W) / 2 if first else middle
    plate = out.items[0].picture is not None        # words on a picture get a plate behind them
    plate_colour = lay.edits.plate_colour or lay.background
    if plate:
        span = max(len(t1) * 17, len(t2) * 8) + 60
        add(Shape("rect", head - span / 2, 14, span, 104, plate_colour, width=0, fill=plate_colour, move="title",
                  radius=14, target=("plate",)))
    add(Text(head, 48, t1, 30, ink, bold=True, centre=True, role="title", move="title", edit="title"))
    add(Text(head, 78, t2, 15, ink, centre=True, role="subtitle", move="subtitle", edit="subtitle"))
    keys = key_marks(lay)
    kx = head - sum(50 + 8 * len(label) for label, _c in keys) / 2
    for label, colour in keys:
        add(Shape("rect", kx, 94, 26, 16, colour, width=4, radius=4, target=("mark", label), move="key"))
        add(Text(kx + 34, 107, label, 14, ink, role="key", move="key", edit=f"mark:{label}"))
        kx += 50 + 8 * len(label)
    # Packed families has no generation rows -- a generation's portraits stand at many heights, among
    # other generations' -- so a label beside any of them would name the others too: no labels there.
    # Every plate on the page as wide as the widest label needs (one column, its lines in one line).
    column = max([float(LABEL_PLATE_W)] + [b.width for b in label_boxes(v, lay.edits, lay.x).values()])
    for g in sorted({v.people[q].generation for q in lay.x}) if lay.edits.positioning != "packed_families" else []:
        # Beside the generation's portraits as drawn, wherever they are (the owner: "so they're
        # actually accurate"); its rows' place when it has none drawn.
        members = [q for q in lay.x if v.people[q].generation == g and q not in lay.others]
        ys = [py for q in members for _px, py in lay.frame_points(q)]
        top, bottom = (min(ys), max(ys)) if ys else (lay.tops[g], lay.tops[g] + lay.bands.get(g, NODE_H))
        reach = lay.edits.label_line_reach
        lx = lay.label_left
        parts = label_lines(lay, g)
        box = replace(label_box(lay.edits, [text for _part, text in parts]), width=column)
        # The plate and its line as tall as the portraits beside it, and taller when the label's lines
        # need it (the layout keeps the room for that: label_boxes).
        plate_bottom = max(bottom - LABEL_PLATE_TOP, top + box.bottom)
        if plate:
            add(Shape("rect", lx + 12, top + LABEL_PLATE_TOP, box.width, plate_bottom - top - LABEL_PLATE_TOP,
                      plate_colour, width=0, fill=plate_colour, move=f"label{g}", radius=12, target=("plate",)))
        for k, (part, text) in enumerate(parts):
            add(Text(lx + LABEL_TEXT_X, top + box.baselines[k], text, box.sizes[k], ink, bold=k == 0, role="labels",
                     move=f"label{g}", part=f"{g}|{part}", edit=f"label:{g}"))
        line_bottom = max(bottom, plate_bottom + LABEL_PLATE_TOP)
        add(Line([(lx + box.line_x, top - reach), (lx + box.line_x, line_bottom + reach)], ink,
                 lay.edits.label_line_width, target=("ink",), move=f"label{g}"))
    if lay.others:
        # Off to the right, level with the tree's heading (the owner).
        add(Text(lay.others_left, 48, words(lay, "others"), 24, ink, bold=True, role="others", move="others",
                 edit="word:others"))
        add(Text(lay.others_left, 72, words(lay, "others_note"), 13, ink, role="others", move="others_note",
                 edit="word:others_note"))
    fams = {f.id: f for f in lay.families}
    turn_of = {f.id: k for k, f in enumerate(lay.families)}
    drawn_lines = lines(lay)
    for colour, points, fid, piece in drawn_lines:
        key = family_key(v, fams[fid])
        style = lay.edits.family_lines.get(key, {})
        colour = (style.get("colour") or scheme_colour(lay.edits, "lines", turn_of[fid] / max(1, len(turn_of)), turn_of[fid])
                  or colour)
        if f"line:{key}|{piece}" not in lay.edits.hidden:
            add(Line(points, colour, style.get("width", lay.edits.line_width), target=("family", key),
                     piece=f"{key}|{piece}", dash=style.get("dash", lay.edits.line_dash)))
    for fam in lay.families:
        # A family whose children are on a later page (the page's last generation is the next one's founders):
        # beside the end of its line, which page (the owner, 2026-10-10: "these guys have children but no
        # button will make a proper family tree for them with lines!").
        # Centred under the end of its line; words like any others on the tree: their role's font, size, style
        # and colour ("onward"), their own opacity, retyped, dragged and deleted each on its own (onward_key) or
        # all together ("word:onward").
        ends = [pt for s in drawn_lines if s[2] == fam.id for pt in s[1]] \
            if fam.onward and "word:onward" not in lay.edits.hidden else []
        if ends:
            ex, ey = max(ends, key=lambda pt: (pt[1], pt[0]))
            scale = lay.edits.styles.get("onward", {}).get("scale", 100) / 100
            name = onward_key(v, fam)
            add(Text(ex + fam.word_dx, ey + ONWARD_GAP + ONWARD_SIZE * scale * 0.8, onward_words(lay.edits, v, fam), ONWARD_SIZE,
                     ink, centre=True, role="onward", move=name, edit=f"word:{name}"))
    for pid in lay.x:
        _node(lay, v.people[pid], present, add)
        xs, ys = zip(*lay.frame_points(pid))
        x0, y0 = min(min(xs), lay.x[pid]), min(min(ys), lay.y[pid])
        x1, y1 = max(max(xs), lay.x[pid] + NODE_W), max(max(ys), lay.y[pid] + NODE_H)
        out.boxes[pid] = (x0, y0, x1 - x0, y1 - y0)
    _equal_words(lay, out.items)
    key_text = words(lay, "footer")
    # With Shrink to fit, the footer goes onto as many lines as keep it inside that width, rather than
    # widening the page again (Codex, #575); otherwise it is the one line it always was.
    footer_lines = (_wrap(key_text, max(20, int((lay.edits.fit_width - 80) / 6.8)))
                    if lay.edits.fit_width and len(key_text) * 6.8 > lay.edits.fit_width - 80 else [key_text])
    longest = max(len(line) for line in footer_lines)
    if plate:
        add(Shape("rect", middle - longest * 3.4, lay.height - 110, longest * 6.8, 30 + 18 * (len(footer_lines) - 1),
                  plate_colour, move="footer", width=0, fill=plate_colour, radius=10, target=("plate",)))
    for k, line in enumerate(footer_lines):
        add(Text(middle, lay.height - 90 + 18 * k, line, 13, ink, centre=True, role="footer", move="footer",
                 edit="word:footer"))
    hidden = {h for h in lay.edits.hidden if isinstance(h, str)}
    if hidden:                                  # (a special border's thousands of pieces never hidden this way)
        blank = "word:" in hidden
        out.items[:] = [i for i in out.items
                        if type(i) is Poly and not blank or f"word:{getattr(i, 'move', '')}" not in hidden]
    _apply_styles(out.items, lay.edits)
    _text_boxes(lay, out.items)                 # after the words' own sizes are known, before they are made see-through
    _apply_opacity(out.items, lay.edits)
    _apply_moves(out.items, lay.edits)
    canvas = (lay.edits.canvas_w, lay.edits.canvas_h) if lay.edits.canvas_w and lay.edits.canvas_h else None
    if canvas:
        _fit_page(out)                  # the tree's own page, everything drawn on it ...
        _to_canvas(out, *canvas)        # ... shrunk onto the canvas, or centred on it
    here = page_key(lay.edits, lay.village, lay.page)
    for k, raw in enumerate(lay.edits.stickers):
        if raw.get("page", here) != here:       # on another page (none: on every page, as saved before)
            continue
        item = sticker_item(k, raw, images, library)
        if item is not None:
            add(item)
            out.stickers.append(item)
    if not canvas:
        _fit_page(out)
    # The thin casings under family lines whose own colour would blend into the background somewhere
    # (Auto-colour family lines; the owner, 2026-10-10: an option, "Outline lines that blend into the
    # background", off unless the player ticks it), under every family line.
    if lay.edits.outline_lines:
        import vf1_line_colours              # here: it draws on this module
        cased = vf1_line_colours.casings(lay, out)
        if cased:
            at = next(k for k, i in enumerate(out.items) if isinstance(i, Line) and i.piece)
            out.items[at:at] = cased
    return out


def _to_canvas(out: "Scene", width: int, height: int) -> None:
    """The tree on a canvas of the player's size (the owner, 2026-10-09): larger than the canvas, every
    part of it -- portraits, lines, words, labels, the Key, title and footer -- shrunk evenly to fit and
    centred; smaller, centred at its own size.  The background fills the canvas; the pictures and text
    boxes the player placed (added after) keep their own places and sizes."""
    # The tree's page and everything drawn, even words a little wider than it (the footer centred on it):
    # all of it on the canvas.
    boxes = [b for b in map(_extent, out.items) if b is not None] + [(0.0, 0.0, out.width, out.height)]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    s = min(1.0, width / max(1.0, x1 - x0), height / max(1.0, y1 - y0))
    ox, oy = (width - (x1 - x0) * s) / 2 - x0 * s, (height - (y1 - y0) * s) / 2 - y0 * s

    def at(x: float, y: float) -> tuple[float, float]:
        return x * s + ox, y * s + oy

    for item in out.items:
        if isinstance(item, (Line, Poly)):
            item.points = [at(px, py) for px, py in item.points]
            item.width *= s
        elif isinstance(item, Shape):
            item.x, item.y = at(item.x, item.y)
            item.w, item.h, item.width, item.radius = item.w * s, item.h * s, item.width * s, item.radius * s
        elif isinstance(item, Text):
            item.x, item.y = at(item.x, item.y)
            item.size *= s
        elif isinstance(item, Head):
            item.x, item.y = at(item.x, item.y)
            item.scale *= s
    out.boxes = {q: (*at(x, y), w * s, h * s) for q, (x, y, w, h) in out.boxes.items()}
    out.width, out.height, out.fit = float(width), float(height), (s, ox, oy)


MOVABLE = {"title": "the title", "subtitle": "the subtitle", "key": "the Key", "others": "the Other "
           "Members heading", "others_note": "the line under the Other Members heading",
           "footer": "the footer"}   # and "label<generation>": that generation's label


MARGIN = 10                             # nothing dragged goes nearer the page's edge than this


def _extent(item) -> tuple[float, float, float, float] | None:
    """An item's box on the page (words by their likely width)."""
    if isinstance(item, Line):
        xs, ys = zip(*item.points)
        return min(xs), min(ys), max(xs), max(ys)
    if isinstance(item, Poly):
        xs, ys = zip(*item.points)
        return min(xs), min(ys), max(xs), max(ys)
    if isinstance(item, Shape):
        xs, ys = zip(*item.points())
        return min(xs), min(ys), max(xs), max(ys)
    if isinstance(item, Text):
        width = len(item.text) * item.size * 0.55
        left = item.x - width / 2 if item.centre else item.x - width if item.end else item.x
        box = (left, item.y - item.size, left + width, item.y + item.size * 0.3)
        if item.angle:
            # Turned words, turned about their anchor as they are drawn (Codex, #577: the page was sized to
            # their unturned box and cut them off).
            corners = [turn(px - item.x, py - item.y, item.angle) for px in (box[0], box[2]) for py in (box[1], box[3])]
            xs = [item.x + dx for dx, _dy in corners]
            ys = [item.y + dy for _dx, dy in corners]
            return min(xs), min(ys), max(xs), max(ys)
        return box
    if isinstance(item, Sticker):
        return item.bounds()
    return None


def _apply_moves(items: list, edits: Edits) -> None:
    """The words the player dragged, where they dragged them -- never off the top or left of the
    page (the owner: the words go "ON TOP OF THE PICTURE, NOT OUTSIDE")."""
    groups: dict[str, list] = {}
    blank = edits.moved.get("")
    for item in items:
        if type(item) is Poly and not blank:    # no Poly is moved by name (a special border's pieces)
            continue
        if edits.moved.get(getattr(item, "move", "")):
            groups.setdefault(item.move, []).append(item)
    for name, group in groups.items():
        dx, dy = edits.moved[name]
        boxes = [b for b in map(_extent, group) if b is not None]
        dx = max(dx, MARGIN - min(b[0] for b in boxes))
        dy = max(dy, MARGIN - min(b[1] for b in boxes))
        for item in group:
            if isinstance(item, Line):
                item.points = [(px + dx, py + dy) for px, py in item.points]
            else:
                item.x += dx
                item.y += dy


def _fit_page(out: "Scene") -> None:
    """The page as large as everything on it (words, pictures and lines dragged right or down), so
    the background lies under all of it."""
    right = bottom = None
    blocks = set()
    for item in out.items:
        block = item.__dict__.get("block")
        if block in blocks:
            continue
        reach = _SPECIAL_EXTENT.get(block, False) if block is not None else False
        if reach is not False:                  # a special border: its reach worked out once
            blocks.add(block)
            if reach is not None:
                right = reach[0] if right is None else max(right, reach[0])
                bottom = reach[1] if bottom is None else max(bottom, reach[1])
            continue
        b = _extent(item)
        if b is not None:
            right = b[2] if right is None else max(right, b[2])
            bottom = b[3] if bottom is None else max(bottom, b[3])
    if right is not None:
        out.width = max(out.width, right + 2 * MARGIN)
        out.height = max(out.height, bottom + 2 * MARGIN)


def see_through(edits: Edits, part: str) -> float:
    """How opaque a part of the tree is (OPACITY), 0 to 1."""
    return edits.opacity.get(part, OPACITY[part][1]) / 100


def _equal_words(lay: Layout, items: list) -> None:
    """Every portrait in a "Same face and text size" scope with its words at one font size: the
    smallest that any of them was fitted to (_node's fitting into the shape), so none is made smaller
    and the others not (the owner, 2026-10-10)."""
    fits = lay.__dict__.get("_word_fits", {})
    people = lay.village.people
    scope_of = {pid: equal_scope(lay.edits, people[pid]) for pid in lay.x}
    common: dict[str, float] = {}
    for pid, scope in scope_of.items():
        if scope:
            common[scope] = min(common.get(scope, 1.0), fits.get(pid, 1.0))
    if not common:
        return
    for item in items:
        if isinstance(item, Text) and item.role in ("names", "portraits") and scope_of.get(item.pid):
            fit = fits.get(item.pid, 1.0)
            item.size *= common[scope_of[item.pid]] / fit


TEXT_BOX_PAD = 4.0                      # pixels the box reaches past its words on every side


def _words_extent(item: "Text") -> tuple[float, float, float, float]:
    """The box one line of a portrait's words is drawn in: its width by the font's letter widths (run by
    run for formatted words), from above its capitals to below its descenders; turned words by their corners."""
    pieces = [(t, run_look(item, look)) for t, look in item.runs or [] if isinstance(look, dict)]
    if pieces:
        width = sum(text_width(t, lk["size"], lk["bold"], item.font or None, lk["italic"]) for t, lk in pieces)
    else:
        width = text_width(item.text, item.size, item.bold, item.font or None, item.italic)
    left = item.x - width / 2 if item.centre else item.x - width if item.end else item.x
    box = (left, item.y - item.size * 0.85, left + width, item.y + item.size * 0.3)
    if item.angle:
        corners = [turn(px - item.x, py - item.y, item.angle) for px in (box[0], box[2]) for py in (box[1], box[3])]
        xs, ys = [item.x + dx for dx, _dy in corners], [item.y + dy for _dx, dy in corners]
        return min(xs), min(ys), max(xs), max(ys)
    return box


TEXT_BOX_RADIUS = 5.0                   # a text box's rounded corners


def text_box_border(edits: "Edits", border: str, colour: str, width: float, box: tuple, pid: int) -> list:
    """The border round a portrait's text box (x, y, w, h), as a portrait's border of that kind is drawn:
    a line of `width` (dotted, dashed...) round its rounded corners, or a special border -- the rope or a
    vine, in the special borders' own colours and opacity -- along the same outline."""
    x, y, w, h = box
    if border in SPECIAL_BORDERS:
        return special_border_items(border, "rect", (x, y, w, h, 0.0), TEXT_BOX_RADIUS, edits, pid,
                                    edits.special_opacity / 100)
    if colour == TRANSPARENT:                   # a see-through border: nothing to draw
        return []
    dash = border if border in ("dotted", "dashed", "dashdot") else ""
    return [Shape("rect", x, y, w, h, colour, width=width, fill=None, radius=TEXT_BOX_RADIUS, dash=dash, pid=pid)]


def _text_boxes(lay: "Layout", items: list) -> None:
    """The box behind each portrait's name and age words (Edits.text_box_colour / text_box_opacity, by group;
    none at 0 %): one rectangle round all of that portrait's lines, put just before its words -- so under
    them, over its own shape -- or, with Edits.text_box_over, every such box and its words moved up to after
    every portrait's shapes, borders, vines and faces, so no neighbour's shape covers them."""
    people = lay.village.people
    words: dict[int, list] = {}
    for item in items:
        if isinstance(item, Text) and item.pid in people and item.role in ("names", "portraits") and item.text:
            words.setdefault(item.pid, []).append(item)
    boxes: dict[int, list] = {}                 # each portrait's box, then its border
    for pid, lines in words.items():
        p = people[pid]
        opacity = lay.opt(p, "text_box_opacity")
        border_width = lay.opt(p, "text_box_border_width")
        if opacity <= 0 and border_width <= 0:
            continue
        extents = [_words_extent(t) for t in lines]
        left, top = min(b[0] for b in extents) - TEXT_BOX_PAD, min(b[1] for b in extents) - TEXT_BOX_PAD
        right, bottom = max(b[2] for b in extents) + TEXT_BOX_PAD, max(b[3] for b in extents) + TEXT_BOX_PAD
        drawn = boxes[pid] = []
        if opacity > 0:
            colour = lay.opt(p, "text_box_colour")
            drawn.append(Shape("rect", left, top, right - left, bottom - top, colour, width=0, fill=colour,
                               radius=TEXT_BOX_RADIUS, pid=pid, opacity=opacity / 100))
        if border_width > 0:
            drawn += text_box_border(lay.edits, lay.opt(p, "text_box_border"),
                                     lay.opt(p, "text_box_border_colour") or lay.birth_colour.get(pid, GREY),
                                     border_width, (left, top, right - left, bottom - top), pid)
    if not boxes:
        return
    over = {pid for pid in boxes if lay.opt(people[pid], "text_box_over")}
    out: list = []
    lifted: list = []                       # the boxes drawn over the shapes, then their words
    lifted_words: list = []
    seen: set = set()
    for item in items:
        pid = getattr(item, "pid", None)
        if isinstance(item, Text) and pid in boxes and item.role in ("names", "portraits") and item.text:
            if pid in over:
                if pid not in seen:
                    lifted += boxes[pid]
                    seen.add(pid)
                lifted_words.append(item)
                continue
            if pid not in seen:
                out += boxes[pid]
                seen.add(pid)
        out.append(item)
    if lifted:
        last = max((k for k, i in enumerate(out) if getattr(i, "pid", None) is not None), default=-1)
        out[last + 1:last + 1] = lifted + lifted_words
    items[:] = out


def _apply_opacity(items: list, edits: Edits) -> None:
    """Each item as see-through as its part of the tree: the boxes behind words, the portraits (everything
    drawn for one family member -- frame, border, rope or vine with its leaves and flowers, detail lines, mark
    or glow, face and words), the family lines and every other word (with the Key's swatches and the
    generation labels' lines).  A portrait's own lines once went with the Words and its vines with
    nothing at all."""
    plates, portraits = see_through(edits, "plates"), see_through(edits, "portraits")
    lines_, words_ = see_through(edits, "lines"), see_through(edits, "words")
    onward = see_through(edits, "onward")
    for item in items:
        if isinstance(item, Text) and item.role == "onward":
            item.opacity *= onward
        elif isinstance(item, Shape) and item.target == ("plate",):
            item.opacity *= plates
        elif getattr(item, "pid", None) is not None:
            item.opacity *= portraits
        elif isinstance(item, Line) and item.piece:
            item.opacity *= lines_
        elif isinstance(item, (Text, Line)) or isinstance(item, Shape) and item.move == "key":
            item.opacity *= words_


def _apply_styles(items: list, edits: Edits) -> None:
    """The player's fonts: one for every word, and each role's own font, size, style and colour."""
    for item in items:
        if type(item) is Poly or not isinstance(item, Text) or not item.role:
            continue
        style = edits.styles.get(item.role, {})
        item.font = style.get("font") or edits.font
        item.size = item.size * style.get("scale", 100) / 100
        item.bold = style.get("bold", item.bold)
        item.italic = style.get("italic", False)
        item.underline = style.get("underline", False)
        item.strike = style.get("strike", False)
        item.colour = style.get("colour", item.colour)
        if style.get("script") in SCRIPTS and item.runs:      # each run raised or lowered on its own
            item.script = style["script"]
        elif style.get("script") in SCRIPTS:    # smaller, raised or lowered: drawn so everywhere
            shrink, shift = SCRIPTS[style["script"]]
            item.y += item.size * shift
            item.size *= shrink


def run_look(item: "Text", style: dict) -> dict:
    """How one run of a formatted Text is drawn: its own style over the item's (its role's) look --
    bold, italic, underline, strike, colour -- and its size and how far its baseline is moved
    (superscript and subscript as SCRIPTS draws a role's)."""
    script = style.get("script", item.script)
    shrink, shift = SCRIPTS.get(script, (1.0, 0.0))
    return {"bold": style.get("bold", item.bold), "italic": style.get("italic", item.italic),
            "underline": style.get("underline", item.underline), "strike": style.get("strike", item.strike),
            "colour": style.get("colour", item.colour), "size": item.size * shrink, "dy": item.size * shift}


def sticker_item(index: int, raw: dict, images: Path | None, library: dict | None = None) -> Sticker | None:
    """A sticker to draw; None when its picture is not on this computer."""
    common = (raw["cx"], raw["cy"], raw["w"], raw["h"], raw["angle"], raw["flip_h"], raw["flip_v"],
              raw["opacity"] / 100)
    if raw["kind"] == "text":
        return Sticker(index, None, *common, text=raw["text"], font=raw["font"], size=raw["size"],
                       bold=raw["bold"], italic=raw["italic"], underline=raw["underline"], strike=raw["strike"],
                       colour=raw["colour"],
                       align=raw["align"], valign=raw["valign"], fill=raw["fill"],
                       fill_opacity=raw["fill_opacity"], border=raw["border"], border_width=raw["border_width"],
                       shape=raw["shape"])
    path = picture_path(raw["picture"], images, library)
    if path is None:
        return None
    return Sticker(index, path, *common)


def new_shape(shape: str, cx: float, cy: float) -> dict:
    """A plain shape (an empty text box with a fill and a border), to type in if wished."""
    return clean_sticker({"kind": "text", "text": "", "shape": shape, "cx": cx, "cy": cy, "w": 180, "h": 120,
                          "fill": "#ffffff", "border": INK, "border_width": 2})


def new_text_box(cx: float, cy: float, text: str = "Type here", font: str = "") -> dict:
    return clean_sticker({"kind": "text", "text": text, "font": font, "cx": cx, "cy": cy, "w": 260, "h": 90,
                          "size": 24})


def new_sticker(picture: str, path: Path, cx: float, cy: float, longest: float = 300.0) -> dict:
    """A sticker for a picture just added: its own shape, its longer side `longest` (or the
    picture's own size when smaller)."""
    pw, ph = _picture_size(path)
    pw, ph = max(1, pw), max(1, ph)
    scale = min(1.0, longest / max(pw, ph))
    return clean_sticker({"picture": picture, "cx": cx, "cy": cy, "w": max(STICKER_MIN, pw * scale),
                          "h": max(STICKER_MIN, ph * scale)})


def _resample(points: list[tuple[float, float]], step: float) -> list[tuple[float, float, float, float]]:
    """A closed outline walked in steps of `step`: (x, y, and the outward normal's dx, dy) at each."""
    pts = points + points[:1]
    lengths = [math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(pts, pts[1:])]
    total = sum(lengths)
    if total <= 0:
        return []
    area = sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(pts, pts[1:]))
    turn_out = 1 if area > 0 else -1             # which side is outside, whichever way the corners run
    n = max(12, int(total / step))
    out, i, walked = [], 0, 0.0
    for k in range(n):
        d = total * k / n
        while i < len(lengths) - 1 and walked + lengths[i] < d:
            walked += lengths[i]
            i += 1
        (ax, ay), (bx, by) = pts[i], pts[i + 1]
        f = (d - walked) / lengths[i] if lengths[i] else 0.0
        tx, ty = (bx - ax) / (lengths[i] or 1), (by - ay) / (lengths[i] or 1)
        out.append((ax + (bx - ax) * f, ay + (by - ay) * f, ty * turn_out, -tx * turn_out))
    return out


@functools.lru_cache(maxsize=512)
def _open_places(kind: str, w: float, h: float, radius: float, angle: float, size: float = 0.0) -> tuple:
    """The places along a vine border's outline (its _resample steps) where leaves and flowers may go:
    not in a narrow notch -- a gap of the outside too narrow for them on both its sides, a Monstera's
    slit, a heart's dip, a star's inner corner -- but in a wide one, the anchor's (the owner,
    2026-10-09: "move some of the bottom leaves/flowers to those giant notches").  The same for a
    portrait of the same shape and size wherever it is, so worked out once."""
    outline_points = shape_points(kind, 0.0, 0.0, w, h, radius, angle)
    size = size or max(6.0, 0.1 * min(w, h))      # a toe's: its pad's (special_border)
    walk = _resample(outline_points, size / 8)
    n = len(walk)
    pts = [(x, y) for x, y, _nx, _ny in walk]
    apart = 24                                    # three leaves' lengths along the outline
    near = size * 2.6                            # room for leaves and flowers on both sides of the gap
    out = []
    for k in range(n):
        x, y = pts[k]
        narrow = False
        for j in range(0, n, 2):
            if min(abs(j - k), n - abs(j - k)) <= apart:
                continue
            qx, qy = pts[j]
            if (qx - x) ** 2 + (qy - y) ** 2 < near * near and not inside(outline_points, (x + qx) / 2, (y + qy) / 2):
                narrow = True                     # across a gap of the outside, close by: a narrow notch
                break
        if not narrow or _room_straight_out(outline_points, walk, k, size):
            out.append(k)
    return tuple(out)


def _room_straight_out(outline_points: list, walk: list, k: int, size: float) -> bool:
    """Clear room straight out from step k, and a little either side of straight: the heart's dip, which
    opens wide (the owner, 2026-10-09: a flower there), not a Monstera's slit."""
    n = len(walk)
    nx = sum(walk[(k + d) % n][2] for d in range(-3, 4))
    ny = sum(walk[(k + d) % n][3] for d in range(-3, 4))
    m = math.hypot(nx, ny)
    if m == 0:
        return False
    nx, ny = nx / m, ny / m
    x, y = walk[k][0], walk[k][1]
    for turn_deg in (-30, 0, 30):
        c, s = math.cos(math.radians(turn_deg)), math.sin(math.radians(turn_deg))
        dx, dy = nx * c - ny * s, nx * s + ny * c
        for f in (0.5, 1.0, 1.6, 2.2):
            if inside(outline_points, x + dx * size * f, y + dy * size * f):
                return False
    return True


def _band(path: list[tuple[float, float]], normals: list, half: float, colours: list) -> list:
    """A band `half` wide either side of a closed path, in one filled piece per stretch (each its own
    colour), with its two darker edges."""
    n = len(path)
    out = []
    left = [(x + nx * half, y + ny * half) for (x, y), (nx, ny) in zip(path, normals)]
    right = [(x - nx * half, y - ny * half) for (x, y), (nx, ny) in zip(path, normals)]
    for k in range(n):
        j = (k + 1) % n
        out.append(Poly([left[k], left[j], right[j], right[k]], colours[k], colours[k], 0.6))   # no gaps between
    edge = _shade(colours[0], 0.55)
    out.append(Line(left + left[:1], edge, 1.1))
    out.append(Line(right + right[:1], edge, 1.1))
    return out


def _leaf_items(x: float, y: float, dx: float, dy: float, own: float, base: str) -> list:
    """A leaf `own` long from (x, y) along (dx, dy): filled, its far half shaded, outlined, its midrib."""
    px, py = -dy, dx

    def half(side):
        return [(x + dx * own * u + px * own * 0.32 * math.sin(math.pi * u) * side,
                 y + dy * own * u + py * own * 0.32 * math.sin(math.pi * u) * side) for u in (k / 10 for k in range(11))]
    a, b = half(1), half(-1)
    return [Poly(a + b[::-1][1:-1], base), Poly(b + [(x + dx * own, y + dy * own)], _shade(base, 0.8)),
            Poly(a + b[::-1][1:-1], None, _shade(base, 0.5), 0.9),
            Line([(x, y), (x + dx * own * 0.9, y + dy * own * 0.9)], _shade(base, 0.5), 0.7)]


def _flower_items(cx: float, cy: float, r: float, base: str, turned: float = 0.0, eye: str | None = None) -> list:
    """A hibiscus `r` across at (cx, cy), turned `turned` radians (the owner, 2026-10-09: the flowers
    pointing different ways): its petals outlined, its throat shaded, its deep centre, its stamen."""
    petals = [(cx + r * (0.45 + 0.55 * abs(math.cos(2.5 * (a + 0.3 - turned)))) ** 0.5 * math.cos(a),
               cy + r * (0.45 + 0.55 * abs(math.cos(2.5 * (a + 0.3 - turned)))) ** 0.5 * math.sin(a))
              for a in (2 * math.pi * k / 60 for k in range(60))]
    sx, sy = cx + r * 0.42 * math.cos(turned - math.pi / 4), cy + r * 0.42 * math.sin(turned - math.pi / 4)
    return [Poly(petals, base, _shade(base, 0.55), 0.9),
            Poly(_ring(cx, cy, r * 0.42, r * 0.42, 20)[:-1], _mix(base, eye, 0.35) if eye else _shade(base, 0.85)),
            Poly(_ring(cx, cy, r * 0.2, r * 0.2, 14)[:-1], eye or _shade(base, 0.45)),
            Line([(cx, cy), (sx, sy)], STAMEN, 0.9), Poly(_ring(sx, sy, r * 0.09, r * 0.09, 10)[:-1], STAMEN)]


def _open_band(path: list[tuple[float, float]], half: float, colour: str) -> list:
    """A band `half` wide either side of an open path (a stamen, an antenna), with its darker edges."""
    if len(path) < 2:
        return []
    normals = []
    for k in range(len(path)):
        (ax, ay), (bx, by) = path[max(0, k - 1)], path[min(len(path) - 1, k + 1)]
        m = math.hypot(bx - ax, by - ay) or 1.0
        normals.append(((by - ay) / m, -(bx - ax) / m))
    left = [(x + nx * half, y + ny * half) for (x, y), (nx, ny) in zip(path, normals)]
    right = [(x - nx * half, y - ny * half) for (x, y), (nx, ny) in zip(path, normals)]
    out = [Poly([left[k], left[k + 1], right[k + 1], right[k]], colour, colour, 0.6) for k in range(len(path) - 1)]
    edge = _shade(colour, 0.55)
    return out + [Line(left, edge, 1.0), Line(right, edge, 1.0)]


def sticking_out(kind: str, frame: tuple, outline_points: list) -> list:
    """The shape's lines drawn like its border that stand outside it -- the hibiscus's stamen and pollen,
    the butterfly's antennae -- placed in the frame: (their index in decor(kind), their points, whether
    each is a small circle).  Lines inside the shape (the wave, the coconut's eyes) are not among them."""
    x0, y0, w, h, angle = frame
    cx, cy = x0 + w / 2, y0 + h / 2
    out = []
    for i, line in enumerate(decor(kind)):
        pts = [(x0 + u * w, y0 + v * h) for u, v in line]
        if angle:
            pts = [(cx + dx, cy + dy) for dx, dy in (turn(px - cx, py - cy, angle) for px, py in pts)]
        outside = sum(not inside(outline_points, px, py) for px, py in pts)
        if outside < 0.25 * len(pts):          # mostly inside: an inside detail (the wave), left as it is
            continue
        closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 0.02 * max(w, h)
        out.append((i, pts, closed))
    return out


def _is_toe(pts: list, frame: tuple) -> bool:
    """A closed part standing outside its shape big enough to be a shape of its own -- a paw print's toe --
    not a small dot like the hibiscus's pollen."""
    cx = sum(px for px, _py in pts) / len(pts)
    cy = sum(py for _px, py in pts) / len(pts)
    return sum(math.hypot(px - cx, py - cy) for px, py in pts) / len(pts) > 0.06 * max(frame[2], frame[3])


def _near(polygons: list, x: float, y: float, reach: float) -> bool:
    """Whether (x, y) is within `reach` of any corner of these outlines (dense ones: a ring, a toe)."""
    return any(math.hypot(px - x, py - y) < reach for poly in polygons for px, py in poly)


def _sticking_out(border: str, kind: str, frame: tuple, outline_points: list, size: float, colour_of,
                 flower_look=None, edits: "Edits | None" = None) -> list:
    """The special border on the parts standing outside the shape (the owner, 2026-10-09): the rope or
    the vine along each line, and on each small circle one flower -- a leaf on a vine of leaves only --
    or, for the rope, a rope ring."""
    items = []
    parts = sticking_out(kind, frame, outline_points)
    toes = [pts for _i, pts, closed in parts if closed and _is_toe(pts, frame)]
    for n_out, (_i, pts, closed) in enumerate(parts):
        if closed:
            cx = sum(px for px, _py in pts) / len(pts)
            cy = sum(py for _px, py in pts) / len(pts)
            r = sum(math.hypot(px - cx, py - cy) for px, py in pts) / len(pts)
            if border == "rope":
                ring = _ring(cx, cy, max(r, size * 0.6), max(r, size * 0.6), 24)[:-1]
                items += _open_band(ring + ring[:2], size * 0.3, colour_of("rope", 0.0, 0))
            elif _is_toe(pts, frame) and edits is not None:
                # A big circle -- a paw print's toe -- takes the vine as a whole shape does, its leaves and
                # flowers spread round it the same way and as big as the pad's (the owner, 2026-10-09: "they
                # should be like the other normal shapes").  The toe as the oval that fits it.
                sxx = sum((px - cx) ** 2 for px, _py in pts)
                syy = sum((py - cy) ** 2 for _px, py in pts)
                sxy = sum((px - cx) * (py - cy) for px, py in pts)
                lean = 0.5 * math.atan2(2 * sxy, sxx - syy)
                ux, uy = math.cos(lean), math.sin(lean)
                a = max(abs((px - cx) * ux + (py - cy) * uy) for px, py in pts)
                b = max(abs(-(px - cx) * uy + (py - cy) * ux) for px, py in pts)
                # None in the gaps it shares with the pad or another toe.
                others = [outline_points] + [toe for toe in toes if toe is not pts]
                items += special_border(border, "ellipse", (cx - a, cy - b, 2 * a, 2 * b, math.degrees(lean)), 0.0,
                                        edits, size=size, clear=others)
            elif border == "vine_leaves":
                ox, oy = cx - (frame[0] + frame[2] / 2), cy - (frame[1] + frame[3] / 2)
                m = math.hypot(ox, oy) or 1.0
                items += _leaf_items(cx, cy, ox / m, oy / m, max(r * 2.2, size * 0.7), colour_of("leaf", 0.0, 0))
            else:
                petals, eye = flower_look(0.0, n_out, 3.0) if flower_look else (colour_of("flower", 0.0, 0), None)
                items += _flower_items(cx, cy, max(r * 1.3, size * 0.3), petals,
                                       turned=(cx * 7.31 + cy * 3.17) % (2 * math.pi), eye=eye)
        else:
            if border == "rope":
                items += _open_band(pts, size * 0.35, colour_of("rope", 0.0, 0))
            else:
                items += _open_band(pts, max(0.9, size * 0.07), colour_of("vine", 0.0, 0))
    return items


def special_border(border: str, kind: str, frame: tuple, radius: float, edits: "Edits | None" = None,
                   size: float | None = None, clear: list | None = None) -> list:
    """A special border round a portrait framed (x, y, w, h, angle), along its own outline whatever the
    shape (the owner, 2026-10-09): the braided rope, or a vine -- a real stem -- with leaves, hibiscus
    or both, filled, shaded and outlined in its colours (Edits.special_*), the leaves and flowers small,
    on the outside and never in a notch.  Items to draw (Poly and Line), already turned."""
    e = edits or Edits()
    x0, y0, w, h, angle = frame
    outline_points = shape_points(kind, x0, y0, w, h, radius, angle)
    mode, pick = e.special_mode, e.special_pick
    palette = list(e.special_palette[:e.special_count])

    def flower_look(t: float, j: int, salt: float = 0.0) -> tuple[str, str | None]:
        """A flower's petals and eye: in natural colours, the chosen hibiscus -- or all of them by
        turns or blending round the border; else the mode's colour, its eye shaded from it."""
        if mode == "natural":
            name = e.hibiscus
            if name == "alternate":               # by turns round the border
                name = HIBISCUS_ORDER[j % len(HIBISCUS_ORDER)]
            elif name == "gradient":              # blending from one to the next round the border
                return (_blend_round([HIBISCUS[k][1] for k in HIBISCUS_ORDER], t),
                        _blend_round([HIBISCUS[k][2] for k in HIBISCUS_ORDER], t))
            _words, petals, eye = HIBISCUS[name]
            return petals, eye
        return colour_of("flower", t, j), None

    def colour_of(part: str, t: float, j: int) -> str:
        if mode == "pick":
            return pick.get(part, NATURAL[part])
        decorated = part == "flower" or (part == "leaf" and border == "vine_leaves") or part == "rope"
        if mode == "rainbow" and decorated:
            return _shade(_blend_round(list(RAINBOW), t), RAINBOW_STRENGTHS[e.rainbow_strength][1])
        if mode == "alternate" and decorated:
            return palette[j % len(palette)]
        if mode == "gradient" and decorated:
            return _blend_round(palette, t)
        return NATURAL[part]

    if border == "rope":
        thick = max(5.0, 0.07 * min(own_box(kind, w, h)))
        walk = _resample(outline_points, thick / 3)
        if not walk:
            return []
        path = [(x, y) for x, y, _nx, _ny in walk]
        normals = [(nx, ny) for _x, _y, nx, ny in walk]
        n = len(walk)
        twists = max(1, n // 3)
        colours = [colour_of("rope", (k // 3) / twists, k // 3) for k in range(n)]
        items = _band(path, normals, thick / 2, colours)
        r = thick / 2
        for k in range(0, n - 3, 3):                 # a strand crossing from the inner edge to the outer
            x0_, y0_, nx0, ny0 = walk[k]
            x1_, y1_, nx1, ny1 = walk[k + 3]
            mx, my = (x0_ + x1_) / 2, (y0_ + y1_) / 2
            items.append(Line([(x0_ - nx0 * r, y0_ - ny0 * r), (mx + (nx0 + nx1) * r * 0.1, my + (ny0 + ny1) * r * 0.1),
                               (x1_ + nx1 * r, y1_ + ny1 * r)], _shade(colours[k], 0.6), 1.0))
        return items + _sticking_out(border, kind, frame, outline_points, thick, colour_of, flower_look)

    size = size or max(6.0, 0.1 * min(own_box(kind, w, h)))         # a leaf's length: small, outside the portrait (a toe: its pad's)
    walk = _resample(outline_points, size / 8)
    if not walk:
        return []
    n = len(walk)
    wave = size * 0.12
    path = [(x + nx * wave * (1 + math.sin(2 * math.pi * k / 16)) / 2, y + ny * wave * (1 + math.sin(2 * math.pi * k / 16)) / 2)
            for k, (x, y, nx, ny) in enumerate(walk)]
    normals = [(nx, ny) for _x, _y, nx, ny in walk]
    stem = colour_of("vine", 0.0, 0)
    items = _band(path, normals, max(0.9, size * 0.07), [stem] * n)
    leaves, flowers = border in ("vine_leaves", "vine_both"), border in ("vine_flowers", "vine_both")
    pattern = ["leaf", "leaf", "flower"] if leaves and flowers else ["leaf"] if leaves else ["flower"]
    # Leaves alone or flowers alone sparser than the mix, like it (the owner, 2026-10-09: "similar but
    # different, not too many clustered").
    spacing = {("leaf",): 12, ("flower",): 16}.get(tuple(pattern), 10)
    jitter = 0.32 if len(pattern) > 1 else 0.24
    # Only where the outline is not in a notch (the owner: none there), and spread evenly over those
    # stretches, so a star or an anchor is as full as a circle (the owner: "more on the sparser shapes").
    open_places = list(_open_places(kind, round(w, 1), round(h, 1), round(radius, 2), round(angle, 1), round(size, 2)))
    count = max(3, len(open_places) // spacing) if open_places else 0
    if open_places and len(open_places) < 0.75 * n:
        count += 4                                    # a sparse shape: just a few more (the owner, 2026-10-09)
    def wobble(j: int, salt: float) -> float:
        """-1 to 1, the same for the same leaf or flower every time it is drawn."""
        v = math.sin((j + 1) * 12.9898 + salt * 78.233) * 43758.5453
        return (v - math.floor(v)) * 2 - 1
    placed_at = []
    flowers_drawn = 0
    if clear is None:                               # a paw print's pad: its toes are its neighbours
        clear = [pts for _i, pts, closed in sticking_out(kind, frame, outline_points) if closed and _is_toe(pts, frame)]
    # The bunch of bananas' far tip takes a flower among its leaves (the owner, 2026-10-09): the spot
    # nearest the outline's farthest point along the bunch.
    tip_flower = None
    if leaves and flowers and _unflipped(kind)[0] == "bananas" and count:
        far = max(range(n), key=lambda i: walk[i][0])     # the middle banana's end, the bunch's rightmost
        spots_even = [open_places[min(len(open_places) - 1, max(0, int((j + 0.5 + jitter * wobble(j, 1.0))
                                                                         * len(open_places) / count)))]
                      for j in range(count)]
        tip_flower = min(range(count), key=lambda j: min(abs(spots_even[j] - far), n - abs(spots_even[j] - far)))
    for j in range(count):
        # Irregularly even (the owner, 2026-10-09): each a little off its even place, a little bigger or
        # smaller, leaning a little more or less.
        spot = (j + 0.5 + jitter * wobble(j, 1.0)) * len(open_places) / count
        k = open_places[min(len(open_places) - 1, max(0, int(spot)))]
        if len(pattern) == 1 and placed_at and min(abs(k - placed_at[-1]), n - abs(k - placed_at[-1])) < 0.6 * n / count:
            continue                                  # never two bunched together
        placed_at.append(k)
        own = size * (1 + 0.12 * wobble(j, 2.0))
        x, y = path[k]
        # Outward as the outline runs a few steps either side: at a sharp corner -- the heart's dip --
        # one step's own direction can point inside (the owner, 2026-10-09: the dip's flower above it).
        nx = sum(normals[(k + d) % n][0] for d in range(-3, 4))
        ny = sum(normals[(k + d) % n][1] for d in range(-3, 4))
        m = math.hypot(nx, ny)
        if m == 0:
            continue
        nx, ny = nx / m, ny / m
        if inside(outline_points, x + nx * size * 0.7, y + ny * size * 0.7):
            nx, ny = -nx, -ny
            if inside(outline_points, x + nx * size * 0.7, y + ny * size * 0.7):
                continue                              # no outside here at all
        if clear and _near(clear, x + nx * size * 0.6, y + ny * size * 0.6, size * 1.1):
            continue                                  # in a gap with a neighbouring toe or the pad
        tx, ty = -ny, nx
        what = "flower" if j == tip_flower else pattern[j % len(pattern)]
        tpos = j / count
        if what == "leaf":
            lean = (0.6 if j % 2 == 0 else -0.6) * (1 + 0.3 * wobble(j, 3.0))        # outward, leaning one way then the other
            dx, dy = nx * 0.8 + tx * lean, ny * 0.8 + ty * lean
            m = math.hypot(dx, dy)
            if m == 0:
                continue
            dx, dy = dx / m, dy / m
            items += _leaf_items(x, y, dx, dy, own, colour_of("leaf", tpos, j))
        else:
            r = own * 0.55
            cx, cy = x + nx * r * 0.95, y + ny * r * 0.95                         # just outside the vine
            petals, eye = flower_look(tpos, flowers_drawn)             # by the flowers alone, not the leaves
            flowers_drawn += 1
            items += _flower_items(cx, cy, r, petals, turned=math.pi * wobble(j, 4.0), eye=eye)
    return items + _sticking_out(border, kind, frame, outline_points, size, colour_of, flower_look, e)


_SPECIAL_CACHE: dict = {}                # special_border_items: its key -> the border's pieces
_SPECIAL_EXTENT: dict = {}               # its key -> the farthest right and down any piece reaches
_SPECIAL_CACHE_MAX = 4096


def _fresh(item):
    """A shallow copy of a drawn item (its points shared: nothing changes them in place) -- far quicker
    than copy.copy for the tens of thousands of a special border's pieces."""
    new = object.__new__(type(item))
    new.__dict__.update(item.__dict__)
    return new


def special_border_items(border: str, kind: str, frame: tuple, radius: float, edits: "Edits | None",
                         pid: int, see: float) -> list:
    """A portrait's special border (special_border) as its portrait draws it -- `see` times as opaque,
    every piece the family member's -- worked out once for each border, shape, frame, corner, colours, family member
    and opacity (the owner's tree of vines took a second for every change: every portrait's thousands of
    leaves and petals made again).  Fresh (shallow) copies each time: _apply_opacity fades them with the
    portrait and _to_canvas moves and shrinks them onto a canvas of the player's size.
    Every piece's `block` (not a field) is the same tuple, so the editor can keep the canvas items of a
    border that has not changed, and _fit_page can take the border's extent at once."""
    e = edits or Edits()
    # (own_box: a shape drawn turned, SHAPE_BAKES, sizes its leaves by the box it had before -- a pure
    # function of the shape and the frame, kept in the key all the same.)
    key = (border, kind, tuple(frame), own_box(kind, frame[2], frame[3]), radius, e.special_mode, repr(sorted(e.special_pick.items())),
           tuple(e.special_palette[:e.special_count]), e.special_count, e.rainbow_strength, e.hibiscus, pid, see)
    made = _SPECIAL_CACHE.get(key)
    if made is None:
        made = special_border(border, kind, frame, radius, e)
        for item in made:
            if see < 1:
                item.opacity = item.opacity * see
            item.pid = pid
            item.target = ("person", pid) if item.target is None else item.target
            item.__dict__["block"] = key
        extents = [b for b in map(_extent, made) if b is not None]
        if len(_SPECIAL_CACHE) >= _SPECIAL_CACHE_MAX:
            _SPECIAL_CACHE.clear()
            _SPECIAL_EXTENT.clear()
        _SPECIAL_EXTENT[key] = (max(b[2] for b in extents), max(b[3] for b in extents)) if extents else None
        _SPECIAL_CACHE[key] = made = tuple(made)
    return [_fresh(item) for item in made]


def scheme_colour(e: "Edits", part: str, t: float, j: int) -> str | None:
    """The colour `part` (SCHEME_PARTS) takes at `t` (0-1 of the way round or across) or by turn `j`, or
    None when the player keeps it as set."""
    mode = e.schemes.get(part, "own")
    if mode == "rainbow":
        return _shade(_blend_round(list(RAINBOW), t), RAINBOW_STRENGTHS[e.rainbow_strength][1])
    if mode == "alternate":
        palette = list(e.special_palette[:e.special_count]) or ["#000000"]
        return palette[j % len(palette)]
    return None


def scheme_outline(e: "Edits", part: str, kind: str, frame: tuple, radius: float, width: float,
                   opacity: float = 1.0, dash: str = "", target: tuple | None = None, pieces: int = 48) -> list:
    """An outline drawn in `part`'s colour scheme, piece by piece round it: a rainbow, or the colours by
    turns in even arcs."""
    x, y, w, h, angle = frame
    walk = _resample(shape_points(kind, x, y, w, h, radius, angle), max(1.0, sum(own_box(kind, w, h)) / (pieces * 2)))
    n = len(walk)
    if n < 2:
        return []
    count = max(1, e.special_count)
    arcs = 2 * count if count > 2 else 6
    out = []
    for i in range(pieces):
        a, b = i * n // pieces, (i + 1) * n // pieces
        pts = [walk[k % n][:2] for k in range(a, b + 1)]
        colour = scheme_colour(e, part, i / pieces, i * arcs // pieces) or "#000000"
        if out and out[-1].colour == colour:
            out[-1].points += pts[1:]          # the same colour runs on: one line (fewer to draw; the owner: no lag)
        else:
            out.append(Line(pts, colour, width, target=target, opacity=opacity, dash=dash))
    return out


def _rank(lay: Layout, pid: int) -> tuple[float, int]:
    """Where a family member comes across the tree, in number order: (0-1, their turn)."""
    ranks = lay.__dict__.get("_ranks")
    if ranks is None:
        people = lay.village.people
        order = sorted(lay.x, key=lambda q: (people[q].number or 0, q))
        ranks = {q: (k / max(1, len(order)), k) for k, q in enumerate(order)}
        lay.__dict__["_ranks"] = ranks
    return ranks.get(pid, (0.0, 0))


def _node(lay: Layout, p: gen.Person, present: dict, add) -> None:
    x, y = lay.x[p.id], lay.y[p.id]
    colour = lay.birth_colour.get(p.id, GREY)
    ink = lay.portrait_ink
    kind = lay.shape(p)
    border = lay.border(p)
    shown = lay.marks(p)
    mark = shown[0][1] if shown else None
    fx, fy, fw, fh, angle = lay.frame(p.id)
    see = lay.edits.mark_opacity / 100
    target = ("mark", shown[0][0] if shown else None)
    # Their second and later marks: a ring each, outside the first (MARK_STEP apart; the owner: "show all").
    first = MARK_GAP + MARK_STEP if lay.edits.mark_style == "border" else MARK_GAP
    for k, (label, colour) in reversed(list(enumerate(shown[1:]))):
        m = first + k * MARK_STEP
        add(Shape(kind, fx - m, fy - m, fw + 2 * m, fh + 2 * m, colour, width=4, fill=None,
                  radius=corner_radius(kind) + m, pid=p.id, target=("mark", label), angle=angle, opacity=see))
    marks_scheme = mark and lay.edits.schemes.get("marks", "own") != "own"
    if mark and lay.edits.mark_style == "glow" and marks_scheme:      # a rainbow or alternating glow
        reach = lay.edits.mark_glow
        for k in range(GLOW_RINGS, 0, -1):
            m = reach * (k - 0.5) / GLOW_RINGS
            for line in scheme_outline(lay.edits, "marks", kind, (fx - m, fy - m, fw + 2 * m, fh + 2 * m, angle),
                                       corner_radius(kind) + m, 2 * reach / GLOW_RINGS + 0.6,
                                       opacity=see * (1 - (k - 1) / GLOW_RINGS), target=target, pieces=32):
                line.pid = p.id                 # part of the portrait, like a one-colour glow
                add(line)
    elif mark and marks_scheme:
        m = MARK_GAP
        for line in scheme_outline(lay.edits, "marks", kind, (fx - m, fy - m, fw + 2 * m, fh + 2 * m, angle),
                                   corner_radius(kind) + m, 4, opacity=see, target=target):
            line.pid = p.id                     # part of the portrait, like a one-colour mark
            add(line)
    elif mark and lay.edits.mark_style == "glow":
        reach = lay.edits.mark_glow
        for k in range(GLOW_RINGS, 0, -1):     # outermost (faintest) first
            m = reach * (k - 0.5) / GLOW_RINGS
            add(Shape(kind, fx - m, fy - m, fw + 2 * m, fh + 2 * m, mark, width=2 * reach / GLOW_RINGS + 0.6, fill=None,
                      radius=corner_radius(kind) + m, pid=p.id, target=target, angle=angle,
                      # The player's colour at full strength against the portrait, fading out to
                      # nothing: "a vibrant red halo of light radiating out from the portrait"
                      # (the owner, 2026-10-08; it was capped at 45%, so red came out pale pink).
                      opacity=see * (1 - (k - 1) / GLOW_RINGS)))
    elif mark:
        m = MARK_GAP
        add(Shape(kind, fx - m, fy - m, fw + 2 * m, fh + 2 * m, mark, width=4, fill=None,
                  radius=corner_radius(kind) + m, pid=p.id, target=target, angle=angle, opacity=see))
    put = add                                   # as it is: a special border's pieces are already the villager's

    def add(item, _add=add):
        """Whatever is drawn for this portrait is theirs (Codex, #577: a leaf or a rope beyond the shape
        could not be clicked or dragged)."""
        if isinstance(item, (Line, Poly)):
            if item.pid is None:
                item.pid = p.id
            if item.target is None:
                item.target = ("person", p.id)
        _add(item)
    rank_t, rank_j = _rank(lay, p.id)
    inside_colour = (lay.entry(p).get("fill") or scheme_colour(lay.edits, "insides", rank_t, rank_j)
                     or lay.opt(p, "portrait_fill"))       # their own, else the scheme's, else their group's or the tree's
    border_scheme = border not in SPECIAL_BORDERS and lay.edits.schemes.get("borders", "own") != "own"
    dash = border if border in ("dotted", "dashed", "dashdot") else ""
    add(Shape(kind, fx, fy, fw, fh, colour, width=0 if border_scheme else BORDER_WIDTHS[border],
              radius=corner_radius(kind), dash=dash, pid=p.id, target=("person", p.id), fill=inside_colour,
              angle=angle))
    if border_scheme:                           # a rainbow or alternating colours round the outline
        for line in scheme_outline(lay.edits, "borders", kind, (fx, fy, fw, fh, angle), corner_radius(kind),
                                   BORDER_WIDTHS[border], dash=dash, target=("person", p.id)):
            add(line)
    e = lay.edits
    mx, my = fx + fw / 2, fy + fh / 2

    def placed(line):
        pts = [(fx + u * fw, fy + v * fh) for u, v in line]
        if angle:
            pts = [(mx + dx, my + dy) for dx, dy in (turn(px - mx, py - my, angle) for px, py in pts)]
        return pts
    if base_kind(kind) in FILLED_DECOR and is_colour(inside_colour) and inside_colour != TRANSPARENT:
        # A paw print's toes filled like its pad (the owner, 2026-10-09: "include the extra toes for the
        # portrait background"), under their borders.
        for line in decor(kind):
            add(Poly(placed(line), inside_colour))      # faded with the portrait by _apply_opacity
    if border in SPECIAL_BORDERS:              # the braided rope or a vine, round any shape, in its own colours
        see = e.special_opacity / 100            # as see-through as the player says
        for item in special_border_items(border, kind, (fx, fy, fw, fh, angle), corner_radius(kind), e, p.id, see):
            put(item)
    replaced = ({i for i, _pts, _closed in sticking_out(kind, (fx, fy, fw, fh, angle), lay.frame_points(p.id))}
                if border in SPECIAL_BORDERS else set())
    for i, line in enumerate(decor(kind)):      # drawn like the border (a stamen, an antenna, the wave)
        if i not in replaced:                   # unless the special border is on it
            add(Line(placed(line), colour, max(1.6, BORDER_WIDTHS[border] * 0.8)))
    detail_opacity = lay.opt(p, "detail_opacity")     # the villager's group's, else the tree's
    if lay.opt(p, "detail_lines") and detail_opacity > 0:   # light, under the face and the words
        lines_inside = details(kind)
        detail_colour, detail_width = lay.opt(p, "detail_colour"), lay.opt(p, "detail_width")
        for i, line in enumerate(lines_inside):
            add(Line(placed(line), lay.entry(p).get("detail")
                     or scheme_colour(e, "details", i / max(1, len(lines_inside)), i) or detail_colour or colour,
                     detail_width, opacity=detail_opacity / 100))
    # The face and words grow or shrink with a frame the player resized, about its middle, and
    # never turn (the owner: "shrink/grow with the frame, stay upright").
    # Measured against the shape's own natural size, never the group's: a villager sized on their own
    # kept a giant face when their group was made tiny (the owner, 2026-10-09: 8-pixel males, faces 4x).
    w0, h0 = natural_width(base_kind(kind)), natural_height(base_kind(kind))
    scale = max(0.2, min(4.0, fw / w0, fh / h0)) if (round(fw, 3), round(fh, 3)) != (round(w0, 3), round(h0, 3)) else 1.0
    fixed = is_fixed(lay.edits, p)
    if fixed:
        scale = fixed_scale(lay, p, fw, fh)
    # The face and words go with the frame when the row lines portraits up by their tops or bottoms
    # (Edits.row_valign; Codex, #577: a short frame moved and left its face and words behind).
    y += (fy + fh / 2) - (y + NODE_H / 2)
    if fixed and not p.upcoming:
        y += face_inside(lay, p, present, y, fy, fh, scale)
    middle = (x + NODE_W / 2, y + NODE_H / 2)
    # The face and words moved (and, where no place in the shape holds them, made smaller) about the
    # face's middle, so the face is inside its shape (face_anchor): set below, once the face is known.
    pivot, shift, shrink = middle, (0.0, 0.0), 1.0
    frame_xs = [px for px, _py in lay.frame_points(p.id)]

    flip_h, flip_v = lay.entry(p).get("flip_h", False), lay.entry(p).get("flip_v", False)
    flip_words, turn_words = lay.opt(p, "flip_words"), lay.opt(p, "turn_words")

    def moved(px: float, py: float) -> tuple[float, float]:
        """A point of the face and words as drawn: grown or shrunk with the frame, then to its anchor."""
        px, py = middle[0] + (px - middle[0]) * scale, middle[1] + (py - middle[1]) * scale
        return pivot[0] + (px - pivot[0]) * shrink + shift[0], pivot[1] + (py - pivot[1]) * shrink + shift[1]

    def put(item) -> None:
        if scale * shrink != 1.0 or shift != (0.0, 0.0):
            item.x, item.y = moved(item.x, item.y)
            if isinstance(item, Head):
                item.scale *= scale * shrink
            elif isinstance(item, Text):
                item.size *= scale * shrink
            else:
                item.w, item.h = item.w * scale * shrink, item.h * scale * shrink
        centre = moved(*middle)
        words = isinstance(item, Text) and item.role in ("names", "portraits")
        if words and flip_words and (flip_h or flip_v):
            # Mirrored with the flipped portrait, about its middle (the owner, 2026-10-09).
            if flip_h:
                item.x, item.mirror_h = 2 * centre[0] - item.x, True
            if flip_v:
                item.y, item.mirror_v = 2 * centre[1] - item.y + item.size * 0.7, True
        if angle and turn_words and words:
            # The words turn with the portrait, about its middle (the owner, 2026-10-09); the face does not.
            dx, dy = turn(item.x - centre[0], item.y - centre[1], angle)
            item.x, item.y, item.angle = centre[0] + dx, centre[1] + dy, angle
        add(item)

    def drawn_width(text: str, size: float, bold: bool, runs) -> float:
        """How wide a portrait's line is drawn: in its role's font, size, boldness and slant (Edits.styles),
        a formatted line run by run, each in its own (a bold and italic "X's twin" wider)."""
        style = e.styles.get("names" if bold else "portraits", {})
        size, font = size * style.get("scale", 100) / 100, style.get("font") or e.font
        bold, italic = style.get("bold", bold), style.get("italic", False)
        pieces = [(t, look) for t, look in runs or [] if isinstance(look, dict)] or [(text, {})]
        return sum(text_width(t, size * SCRIPTS.get(look.get("script"), (1.0, 0))[0], look.get("bold", bold),
                              font, look.get("italic", italic)) for t, look in pieces)

    def within_frame(at_x: float, room: float) -> float:
        """No wider than the frame from where the line is centred (words never leave the portrait's frame)."""
        return min(room, 2 * min(at_x - min(frame_xs), max(frame_xs) - at_x) - 4)

    pic, own = inner_sizes(lay, p)          # the face's and the words' sizes inside the shape
    if p.upcoming:
        texts = node_text(lay, p)
        # Made the same as others' (Edits.equal_sizes): their names' and lines' font sizes too.
        sizes = (11.5, 10) if equal_scope(lay.edits, p) else (12, 11)
        points = text_room_points(lay.opt(p, "text_room"), kind, lay.frame_points(p.id), (fx, fy, fw, fh, angle))
        fit = 1.0
        if lay.opt(p, "text_inside") and texts:
            # Kept inside the shape: the words where the outline holds them (face_anchor, the words as the
            # face), a little in from it -- a paw's middle is the gap between its toes and its pad.
            wide = min(fw * 0.9, max(drawn_width(t, sizes[k > 0] * own * scale, k == 0, None)
                                     for k, t in enumerate(texts)))
            top_y = moved(0, y + NODE_H / 2 + 4 - 12 * own)[1]
            foot_y = moved(0, y + NODE_H / 2 + 4 + (len(texts) - 1) * 15 * own + 4 * own)[1]
            block = (middle[0] - wide / 2 - TEXT_MARGIN, top_y - 2, middle[0] + wide / 2 + TEXT_MARGIN, foot_y + 2)
            dx, dy, shrink = face_anchor(kind, (fx, fy, fw, fh, angle), lay.frame_points(p.id), [block], block, keep=False)
            pivot, shift = ((block[0] + block[2]) / 2, (block[1] + block[3]) / 2), (dx, dy)
        for k, text in enumerate(texts):
            size = sizes[k > 0] * own * scale * shrink
            at_x, baseline = moved(x + NODE_W / 2, y + NODE_H / 2 + 4 + k * 15 * own)
            chord = min(_chord(points, baseline - size * 0.75), _chord(points, baseline + size * 0.2))
            room = within_frame(at_x, max(chord, fw * 0.5) - 8)
            needed = drawn_width(text, size, k == 0, None)
            if text and room > 0 and needed > room:
                fit = min(fit, room / needed)
        lay.__dict__.setdefault("_word_fits", {})[p.id] = fit     # (made the same for a scope: _equal_words)
        for k, text in enumerate(texts):
            put(Text(x + NODE_W / 2, y + NODE_H / 2 + 4 + k * 15 * own, text, sizes[k > 0] * own * fit, ink,
                     bold=k == 0, centre=True, pid=p.id, role="names" if k == 0 else "portraits",
                     edit=f"person:{p.id}"))
        return
    sheet = sheet_name(lay.village.game, p)
    head = look_of(lay.edits, lay.village, p)[0]
    box = face_box(present, sheet, head)
    head_left, head_top, text_top, lines = placement(lay, p, box)
    k0 = HEAD_SCALE * pic
    fa = moved(x + head_left + box[0] * k0, y + head_top + box[1] * k0)
    fb = moved(x + head_left + box[2] * k0, y + head_top + box[3] * k0)
    texts = [(t, b, r) for t, b, r in lines if t]
    if texts:
        wide = min(fw * 0.9, max(drawn_width(t, (11.5 if b else 10) * own * scale, b, r) for t, b, r in texts))
        top_y = moved(0, y + text_top - 11 * own)[1]
        foot_y = moved(0, y + text_top + (len(lines) - 1) * LINE_H * own + 3 * own)[1]
        words_box = (middle[0] - wide / 2, top_y, middle[0] + wide / 2, foot_y)
    else:
        words_box = (*fa, *fb)
    bands = [(*moved(x + head_left + b[0] * k0, y + head_top + b[1] * k0), *moved(x + head_left + b[2] * k0, y + head_top + b[3] * k0))
             for b in face_bands(present, sheet, head)]
    # Words kept inside the shape: the face and words where the words are (nearly) all inside it, made a
    # little smaller if they must be, rather than the face alone inside and the words crushed into a point.
    dx, dy, shrink = face_anchor(kind, (fx, fy, fw, fh, angle), lay.frame_points(p.id), bands, words_box,
                                 WORDS_NEED if lay.opt(p, "text_inside") else 0.0)
    pivot, shift = ((fa[0] + fb[0]) / 2, (fa[1] + fb[1]) / 2), (dx, dy)
    if sheet in present and head is not None and head >= 0:
        put(Head(x + head_left, y + head_top, sheet, head, pid=p.id, scale=pic))
    else:
        mid = y + head_top + FACE_H * HEAD_SCALE * pic / 2
        r = 26 * pic
        put(Shape("ellipse", x + NODE_W / 2 - r, mid - r, 2 * r, 2 * r, colour, width=1, fill=colour, pid=p.id,
                  target=("person", p.id)))
        put(Text(x + NODE_W / 2, mid + 10 * pic, p.name[:1], 28 * pic, "#ffffff", bold=True, centre=True, pid=p.id))
    # Every line inside its shape (Codex, #575; the owner, 2026-10-08: "text should fit within the shape as
    # much as possible"): each line is measured against the shape's own width where it is drawn -- a
    # circle or a heart is narrower towards its edges -- and this portrait's words made only as much
    # smaller as the tightest line needs.  Then the player's own text size for this villager.
    points = text_room_points(lay.opt(p, "text_room"), kind, lay.frame_points(p.id), (fx, fy, fw, fh, angle))
    text_inside = lay.opt(p, "text_inside")
    fit = 1.0
    spans: dict = {}
    own_fit: dict = {}                      # a line kept inside the shape made smaller on its own
    slide = (text_inside and lay.opt(p, "text_align") == "centre" and not (angle and turn_words)
             and not (flip_words and (flip_h or flip_v)))
    for k, (text, bold, runs) in enumerate(lines):
        if not text:
            continue
        size = (11.5 if bold else 10) * scale * shrink
        at_x, baseline = moved(x + NODE_W / 2, y + text_top + k * LINE_H * own)
        # The narrowest the shape is across the whole line, from the tops of its letters to below them.
        chord = min(_chord(points, baseline - size * 0.75), _chord(points, baseline + size * 0.2))
        # Half the frame at least, unless the player keeps the words inside the shape (a cross's arm).
        # (Faces and words at one size: as wide as the frame, not half of it, so a narrow shape's words keep
        # their size too -- unless they are kept inside the shape.)
        room = max(chord - 8, 12.0) if text_inside else max(chord, fw if fixed else fw * 0.5) - 8
        room = within_frame(at_x, room)
        # Measured by the font's own letter widths (text_width), in the role's own font and size, at the
        # group's (or the tree's) text size; a villager's own text size is theirs, on top.
        needed = drawn_width(text, size * lay.opt(p, "text_size") / 100, bold, runs)
        if slide:
            # Kept inside the shape: no wider than the outline across the line, a little in from it, and slid
            # sideways to stay inside it (below) -- a leaf is not as wide on one side of its middle.
            span = _line_span(lay.frame_points(p.id), baseline - size * 0.75, baseline + size * 0.2, at_x, needed)
            if span:
                # Each line on its own: one line where the shape narrows (a leaf's tip) made smaller, not all.
                inner = max(12.0, span[1] - span[0] - 2 * TEXT_MARGIN)
                if needed > inner:
                    own_fit[k] = inner / needed
                spans[k] = (span, needed, at_x)
        if room > 0 and needed > room:
            fit = min(fit, room / needed)
    lay.__dict__.setdefault("_word_fits", {})[p.id] = fit     # (made the same for a scope: _equal_words)
    nudge = {}                              # how far each line kept inside the shape slides sideways
    for k, (span, needed, at_x) in spans.items():
        w = needed * min(fit, own_fit.get(k, 1.0)) * own / (lay.opt(p, "text_size") / 100)
        lo, hi = span[0] + TEXT_MARGIN, span[1] - TEXT_MARGIN - w
        left = at_x - w / 2
        nudge[k] = ((span[0] + span[1]) / 2 - at_x if hi < lo else lo - left if left < lo else hi - left if left > hi
                    else 0.0) / (scale * shrink)
    # Left or right: every line from (or to) one edge, the narrowest the shape is across the words,
    # so no line leaves a round or pointed portrait (Edits.text_align).
    align = lay.opt(p, "text_align")
    total = scale * shrink
    half = fw / total / 2 - 8           # the frame's own width (Codex, #577: not the standard portrait's)
    if align != "centre":
        for k, (text, bold, _r) in enumerate(lines):
            if text:
                size = (11.5 if bold else 10) * total
                at_x, baseline = moved(x + NODE_W / 2, y + text_top + k * LINE_H * own)
                chord = min(_chord(points, baseline - size * 0.75), _chord(points, baseline + size * 0.2))
                wide = max(chord - 4, 16.0) if text_inside else max(chord, fw if fixed else fw * 0.5)
                half = min(half, (within_frame(at_x, wide) - 12) / 2 / total)
    at = x + NODE_W / 2 + (-half if align == "left" else half if align == "right" else 0)
    for k, (text, bold, runs) in enumerate(lines):
        put(Text(at + nudge.get(k, 0.0), y + text_top + k * LINE_H * own, text,
                 (11.5 if bold else 10) * min(fit, own_fit.get(k, 1.0)) * own, ink,
                 bold=bold, centre=align == "centre", end=align == "right", pid=p.id,
                 role="names" if bold else "portraits", edit=f"person:{p.id}", runs=runs))


def text_room_points(room: str, kind: str, outline_points: list, frame: tuple) -> list:
    """The outline a portrait's words are fitted in: the shape's own, or a rectangle or an oval in its
    middle (Edits.text_room; "auto", for every shape -- the owner, 2026-10-09 --: the oval filling a
    circle or an oval, else the rectangle filling the frame)."""
    if room == "auto":
        room = "oval" if kind in ("circle", "ellipse") else "rect"
    if room == "shape":
        return outline_points
    x, y, w, h, angle = frame
    cx, cy = x + w / 2, y + h / 2
    base, flip_h, flip_v = _unflipped(kind)
    if base in SHAPE_BAKES:
        # The shape's own length and width, turned with it (own_box): its room as it was before it was
        # drawn turned (the owner's trees look as they did).
        w, h = own_box(kind, w, h)
        degrees = SHAPE_BAKES[base][0]
        angle = angle + (-degrees if flip_h != flip_v else degrees)
    if room == "rect":
        # The words may pass the drawn outline but stay within the shape's own width and height (the
        # owner, 2026-10-09): the frame's rectangle, a little in from its sides, or the oval filling it.
        pts = [(cx - 0.47 * w, cy - 0.47 * h), (cx + 0.47 * w, cy - 0.47 * h), (cx + 0.47 * w, cy + 0.47 * h),
               (cx - 0.47 * w, cy + 0.47 * h)]
    else:
        pts = [(cx + 0.5 * w * math.cos(a), cy + 0.5 * h * math.sin(a)) for a in (2 * math.pi * k / 48 for k in range(48))]
    if angle:
        pts = [(cx + dx, cy + dy) for dx, dy in (turn(px - cx, py - cy, angle) for px, py in pts)]
    return pts


def _chord(points: list[tuple[float, float]], y: float) -> float:
    """How wide the shape these corners outline is at height `y` (0 above or below it)."""
    xs = []
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        if (ay > y) != (by > y):
            xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
    return max(xs) - min(xs) if len(xs) >= 2 else 0.0


# Where a shape's face and words go when its middle is not inside it (the owner, 2026-10-09: a paw's face
# sat in the gap between its toes and its pad, a mermaid's tail's on its top edge, a coral's beside its
# branches): a hint, in the frame's own 0-1 box, the face and words are kept nearest to -- the paw's pad,
# the coral's trunk and fork, the fluke's body.  A shape not listed keeps the frame's middle as its hint.
FACE_HINTS = {"paw": (0.5, 0.62), "coral": (0.5, 0.62), "mermaid_tail_h": (0.4, 0.5)}
# Shapes whose faces stay just where they always were, the owner's own tree's (2026-10-09: keep them).
FACE_KEPT = {"turtle_h", "monstera", "butterfly"}
_ANCHORS: dict = {}
_GRIDS: dict = {}
WORDS_NEED = 0.9                        # words kept inside a shape: this much of their box inside, where a face moves
WORDS_INSIDE = 20.0                     # pixels further a face moves for its words all inside, not none


def _inside_grid(points: list, cell: float) -> tuple:
    """The shape these corners outline as cells `cell` across: (its left, its top, the columns, the rows,
    the running count of cells inside -- sums[r][c] the cells inside above row r and left of column c)."""
    xs, ys = [px for px, _ in points], [py for _, py in points]
    left, top = min(xs), min(ys)
    cols, rows = max(1, int(math.ceil((max(xs) - left) / cell))), max(1, int(math.ceil((max(ys) - top) / cell)))
    edges = list(zip(points, points[1:] + points[:1]))
    sums = [[0] * (cols + 1)]
    for r in range(rows):
        row = [1] * cols
        # A cell is inside when its top, middle and bottom all are (no cell half over a gap counts).
        for y in (top + (r + 0.02) * cell, top + (r + 0.5) * cell, top + (r + 0.98) * cell):
            cross = sorted(ax + (y - ay) * (bx - ax) / (by - ay) for (ax, ay), (bx, by) in edges if (ay > y) != (by > y))
            here = [0] * cols
            for a, b in zip(cross[::2], cross[1::2]):
                c0, c1 = int(math.ceil((a - left) / cell)), int(math.floor((b - left) / cell))
                for c in range(max(0, c0), min(cols, c1)):
                    here[c] = 1
            row = [u & v for u, v in zip(row, here)]
        above, run, line = sums[-1], 0, [0]
        for c in range(cols):
            run += row[c]
            line.append(above[c + 1] + run)
        sums.append(line)
    return left, top, cols, rows, sums, cell


def _cells_inside(grid: tuple, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int]:
    """(how many of the cells a box touches are inside the shape, how many it touches)."""
    left, top, cols, rows, sums, cell = grid
    c0, c1 = int(math.floor((x0 - left) / cell)), int(math.ceil((x1 - left) / cell))
    r0, r1 = int(math.floor((y0 - top) / cell)), int(math.ceil((y1 - top) / cell))
    total = max(0, c1 - c0) * max(0, r1 - r0)
    c0, c1, r0, r1 = max(0, c0), min(cols, c1), max(0, r0), min(rows, r1)
    if c1 <= c0 or r1 <= r0:
        return 0, total
    return sums[r1][c1] - sums[r0][c1] - sums[r1][c0] + sums[r0][c0], total


def face_anchor(kind: str, frame: tuple, points: list, bands: list, words: tuple,
                words_need: float = 0.0, keep: bool = True) -> tuple[float, float, float]:
    """How far (dx, dy) a portrait's face and words move, and how much smaller (a factor) they are made, so
    the face is inside its shape's outline and the words as much inside as can be: (0, 0, 1) when the face
    already is -- a shape whose middle holds it never moves.  `bands` are the face's visible pixels as boxes
    (face_bands) and `words` the words' box (left, top, right, bottom), as drawn; `points` the outline
    (turned and flipped as drawn).  `words_need`: the share of the words' box that must be inside too
    (words kept inside the shape); `keep`: a FACE_KEPT shape's face left where it is.  Worked out once for
    each shape, size and turn."""
    x, y, w, h, angle = frame
    cx, cy = x + w / 2, y + h / 2
    bands = [(b[0] - cx, b[1] - cy, b[2] - cx, b[3] - cy) for b in bands]
    wx0, wy0, wx1, wy1 = (words[0] - cx, words[1] - cy, words[2] - cx, words[3] - cy)
    key = (kind, round(w, 1), round(h, 1), round(angle, 1), words_need, keep, tuple(round(v, 1) for b in bands for v in b),
           round(wx0, 1), round(wy0, 1), round(wx1, 1), round(wy1, 1))
    if key in _ANCHORS:
        return _ANCHORS[key]
    rel = [(px - cx, py - cy) for px, py in points]
    fx0, fy0 = min(b[0] for b in bands), min(b[1] for b in bands)
    fx1, fy1 = max(b[2] for b in bands), max(b[3] for b in bands)

    def held(b) -> bool:
        """A band inside the outline: its corners and middles are, and no corner of the outline pokes into it."""
        x0, y0, x1, y1 = b
        return (all(inside(rel, px, py) for px in (x0 + 0.5, (x0 + x1) / 2, x1 - 0.5) for py in (y0 + 0.25, y1 - 0.25))
                and not any(x0 + 0.5 < px < x1 - 0.5 and y0 + 0.25 < py < y1 - 0.25 for px, py in rel))
    if keep and base_kind(kind) in FACE_KEPT or all(held(b) for b in bands):
        out = (0.0, 0.0, 1.0)
    else:
        cell = max(0.75, min(w, h) / 90)
        gkey = (kind, round(w, 1), round(h, 1), round(angle, 1))
        grid = _GRIDS.get(gkey)
        if grid is None:
            if len(_GRIDS) > 512:
                _GRIDS.clear()
            grid = _GRIDS[gkey] = _inside_grid(rel, cell)
        if base_kind(kind) in FACE_HINTS:
            hu, hv = FACE_HINTS[base_kind(kind)]
            _b, flip_h, flip_v = _unflipped(kind)
            hint = turn(((1 - hu) if flip_h else hu) * w - w / 2, ((1 - hv) if flip_v else hv) * h - h / 2, angle)
        else:                                   # else as near where the face was as can be
            hint = ((fx0 + fx1) / 2, (fy0 + fy1) / 2)
        mx, my = (fx0 + fx1) / 2, (fy0 + fy1) / 2
        top, foot = min(py for _px, py in rel), max(py for _px, py in rel)
        out = fallback = None
        k = 1.0
        while out is None and k > 0.3:
            # The face and words made smaller about the face's middle, when no place in the shape holds them.
            def small(b, m=0.0):
                return (mx + (b[0] - mx) * k - m, my + (b[1] - my) * k - m, mx + (b[2] - mx) * k + m, my + (b[3] - my) * k + m)
            wd = small((wx0, wy0, wx1, wy1))
            f = small((fx0, fy0, fx1, fy1))
            for margin in (3.0, 0.0):
                # The widest bands first: most places fail on them, at once.
                bs = sorted((small(b, margin) for b in bands), key=lambda b: b[0] - b[2])
                best = None
                # Moves by every other cell, from none (a symmetrical shape keeps its face in its middle):
                # near enough, and four times as fast.
                r0, r1 = math.floor((grid[1] - f[1]) / cell / 2), math.ceil((grid[1] + grid[3] * cell - f[3]) / cell / 2)
                c0, c1 = math.floor((grid[0] - f[0]) / cell / 2), math.ceil((grid[0] + grid[2] * cell - f[2]) / cell / 2)
                # Each band as the cells it touches, unmoved: a move by whole cells moves those by whole cells.
                left, gtop, cols, rows, sums, _cell = grid
                need = [(math.floor((b[0] - left) / cell), math.ceil((b[2] - left) / cell),
                         math.floor((b[1] - gtop) / cell), math.ceil((b[3] - gtop) / cell)) for b in bs]
                for r in range(r0, r1 + 1):
                    dy = 2 * r * cell
                    for c in range(c0, c1 + 1):
                        dx = 2 * c * cell
                        for bc0, bc1, br0, br1 in need:
                            a0, a1, b0, b1 = bc0 + 2 * c, bc1 + 2 * c, br0 + 2 * r, br1 + 2 * r
                            # Every cell it touches inside the shape (none of them beyond the grid).
                            if a0 < 0 or b0 < 0 or a1 > cols or b1 > rows or a1 <= a0 or b1 <= b0 or \
                                    sums[b1][a1] - sums[b0][a1] - sums[b1][a0] + sums[b0][a0] < (a1 - a0) * (b1 - b0):
                                break
                        else:
                            wn, wt = _cells_inside(grid, wd[0] + dx, wd[1] + dy, wd[2] + dx, wd[3] + dy)
                            # The words never below or above the frame (else smaller), then nearest the hint,
                            # the words a little more inside the outline worth moving a little further.
                            framed = wd[1] + dy >= top + 1 and wd[3] + dy <= foot - 1
                            share = wn / wt if wt else 1.0
                            here = (framed and share >= words_need, framed,
                                    WORDS_INSIDE * share - math.hypot(dx + mx - hint[0], dy + my - hint[1]))
                            if best is None or here > best[0]:
                                best = (here, dx, dy)
                if best and best[0][0]:
                    out = (best[1], best[2], k)
                    break
                if best and best[0][1] and fallback is None:
                    fallback = (best[1], best[2], k)
            if out is None:
                k *= 0.9
        out = out or fallback or (0.0, 0.0, 1.0)
    if len(_ANCHORS) > 4096:
        _ANCHORS.clear()
    _ANCHORS[key] = out
    return out


TEXT_MARGIN = 4.0                       # words kept inside a shape stay this far in from its outline


def _stretches(points: list[tuple[float, float]], y: float) -> list[tuple[float, float]]:
    """Each stretch of the shape these corners outline at height `y`, left to right."""
    xs = sorted(ax + (y - ay) * (bx - ax) / (by - ay)
                for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]) if (ay > y) != (by > y))
    return list(zip(xs[::2], xs[1::2]))


def _line_span(points: list, top: float, foot: float, x: float, wide: float) -> tuple[float, float] | None:
    """The stretch of a shape a line of words `wide` across, centred at `x`, is kept in, from its letters'
    tops to below them: of the stretches inside the shape all the way down (a leaf's slit or a paw's gap
    between them), the one that holds the most of the line, nearest `x` -- None when there is none."""
    best = None
    for a0, b0 in _stretches(points, top):
        for a1, b1 in _stretches(points, foot):
            a, b = max(a0, a1), min(b0, b1)
            if b > a:
                here = (min(b - a, wide + 2 * TEXT_MARGIN), -max(0.0, a - x, x - b))
                if best is None or here > best[0]:
                    best = (here, (a, b))
    return best[1] if best else None


def _svg_opacity(item) -> str:
    return f' opacity="{item.opacity:g}"' if item.opacity < 1 else ""


def gradient_stops(b: Backdrop) -> list[tuple[str, float]]:
    """A background gradient's colours and where each sits (0 the top or left, 1 the bottom or right)."""
    if b.colour2 in RAINBOWS:
        return [(c, k / (len(RAINBOW) - 1)) for k, c in enumerate(RAINBOW)]
    return [(b.colour, 0.0), (b.colour2, 1.0)]


def _svg_backdrop(b: Backdrop, sc: Scene) -> str:
    out = []
    if b.colour2:
        stops = gradient_stops(b)
        end = 'x2="1" y2="0"' if RAINBOWS.get(b.colour2) == "across" else 'x2="0" y2="1"'
        out.append(f'<defs><linearGradient id="bg" x1="0" y1="0" {end}>'
                   + "".join(f'<stop offset="{at:g}" stop-color="{c}"/>' for c, at in stops)
                   + '</linearGradient></defs><rect width="100%" height="100%" fill="url(#bg)"/>')
    if b.picture is not None:
        href = _href(b.picture)
        if b.fit == "tile":
            w, h = _picture_size(b.picture)
            out.append(f'<defs><pattern id="tile" width="{w}" height="{h}" patternUnits="userSpaceOnUse">'
                       f'<image width="{w}" height="{h}" href="{href}"/></pattern></defs>'
                       f'<rect width="100%" height="100%" fill="url(#tile)"/>')
        else:
            aspect = {"stretch": "none", "cover": "xMidYMid slice"}.get(b.fit, "xMidYMid meet")
            out.append(f'<image width="{sc.width:.0f}" height="{sc.height:.0f}" preserveAspectRatio="{aspect}" '
                       f'href="{href}"/>')
        if b.soften:
            out[-1] = out[-1].replace("<image ", f'<image opacity="{1 - b.soften / 100:.2f}" ', 1)
    return "".join(out)


def _href(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    kind = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{kind};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _svg_sticker(s: Sticker) -> str:
    fx, fy = (-1 if s.flip_h else 1), (-1 if s.flip_v else 1)
    fade = f' opacity="{s.opacity:.3f}"' if s.opacity < 1 else ""
    head = f'<g transform="translate({s.cx:.1f} {s.cy:.1f}) rotate({s.angle:.2f}) scale({fx} {fy})"{fade}>'
    x, y = -s.w / 2, -s.h / 2
    if s.picture is not None:
        return (f'{head}<image x="{x:.1f}" y="{y:.1f}" width="{s.w:.1f}" height="{s.h:.1f}" '
                f'preserveAspectRatio="none" href="{_href(s.picture)}"/></g>')
    out = [head]
    box = (f'<ellipse cx="0" cy="0" rx="{s.w / 2:.1f}" ry="{s.h / 2:.1f}"' if s.shape == "ellipse"
           else f'<rect x="{x:.1f}" y="{y:.1f}" width="{s.w:.1f}" height="{s.h:.1f}"')
    if s.fill:
        out.append(f'{box} fill="{s.fill}" fill-opacity="{s.fill_opacity / 100:.3f}"/>')
    if s.border and s.border_width > 0:
        out.append(f'{box} fill="none" stroke="{s.border}" stroke-width="{s.border_width:g}"/>')
    pad = s.border_width + 4 if s.border else 4
    css = (f"box-sizing:border-box;width:100%;height:100%;padding:{pad:g}px;display:flex;flex-direction:column;"
           f"justify-content:{ {'top': 'flex-start', 'middle': 'center', 'bottom': 'flex-end'}[s.valign] };"
           f"text-align:{ {'left': 'left', 'centre': 'center', 'right': 'right'}[s.align] };"
           f"font-family:'{html.escape(s.font or 'Segoe UI')}', 'Segoe UI', Arial, sans-serif;font-size:{s.size:g}px;"
           f"color:{s.colour};white-space:pre-wrap;overflow-wrap:anywhere;overflow:hidden;line-height:1.2;"
           + ("font-weight:bold;" if s.bold else "") + ("font-style:italic;" if s.italic else "")
           + (f"text-decoration:{' '.join(d for d, on in (('underline', s.underline), ('line-through', s.strike)) if on)};"
              if s.underline or s.strike else ""))
    out.append(f'<foreignObject x="{x:.1f}" y="{y:.1f}" width="{s.w:.1f}" height="{s.h:.1f}">'
               f'<div xmlns="http://www.w3.org/1999/xhtml" style="{css}"><div>{html.escape(s.text)}</div></div>'
               f'</foreignObject></g>')
    return "".join(out)


def _picture_size(path: Path) -> tuple[int, int]:
    """A PNG's or JPEG's width and height, read from its header."""
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:4] in (b"GIF8",):
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"BM":
        w, h = struct.unpack("<ii", data[18:26])
        return w, abs(h)
    at = 2
    while at < len(data) - 9:
        if data[at] != 0xFF:
            at += 1
            continue
        marker = data[at + 1]
        length = struct.unpack(">H", data[at + 2:at + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[at + 5:at + 9])
            return w, h
        at += 2 + length
    return 800, 600


def _svg_runs(item: Text) -> str:
    """A formatted Text's runs as tspans, one after another: each its own weight, style, lines,
    colour and size, a superscript or subscript raised or lowered (dy) and the next put back."""
    out, at = [], 0.0
    for text, style in item.runs:
        look = run_look(item, style)
        decor = " ".join(d for d, on in (("underline", look["underline"]), ("line-through", look["strike"])) if on)
        attrs = (f' font-weight="{"bold" if look["bold"] else "normal"}"'
                 f' font-style="{"italic" if look["italic"] else "normal"}"'
                 f' text-decoration="{decor or "none"}" fill="{look["colour"]}" font-size="{look["size"]:g}"')
        if look["dy"] != at:
            attrs += f' dy="{look["dy"] - at:g}"'
            at = look["dy"]
        out.append(f"<tspan{attrs}>{html.escape(text)}</tspan>")
    return "".join(out)


def to_svg(sc: Scene, present: dict, describe=None) -> str:
    """The scene as SVG, the head sheets embedded once each."""
    e = html.escape
    ids = {name: f"sheet{k}" for k, name in enumerate(present)}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{sc.width:.0f}" height="{sc.height:.0f}" '
           f'viewBox="0 0 {sc.width:.0f} {sc.height:.0f}" font-family="Segoe UI, Arial, sans-serif">',
           f'<rect width="100%" height="100%" fill="{sc.background}"/>', "<defs>"]
    for name, path in present.items():
        w, h = _png_size(path)
        data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        out.append(f'<image id="{ids[name]}" width="{w}" height="{h}" '
                   f'style="image-rendering:pixelated" href="data:image/png;base64,{data}"/>')
    out.append("</defs>")
    hw, hh = HEAD_W * HEAD_SCALE, HEAD_H * HEAD_SCALE
    for item in sc.items:
        if isinstance(item, Backdrop):
            out.append(_svg_backdrop(item, sc))
        elif isinstance(item, Line):
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in item.points)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{item.colour}" stroke-width="{item.width}"'
                       f' stroke-linejoin="round"{_svg_opacity(item)}'
                       + (f' stroke-dasharray="{SVG_DASHES[item.dash]}"' if item.dash else "") + "/>")
        elif isinstance(item, Poly):
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in item.points)
            stroke = f'stroke="{item.stroke}" stroke-width="{item.width}"' if item.width else 'stroke="none"'
            out.append(f'<polygon points="{pts}" fill="{item.fill or "none"}" fill-rule="evenodd" {stroke}'
                       f' stroke-linejoin="round"{_svg_opacity(item)}/>')
        elif isinstance(item, Shape):
            fill = item.fill or "none"
            dash = f' stroke-dasharray="{SVG_DASHES[item.dash]}"' if item.dash else ""
            dash += f' opacity="{item.opacity}"' if item.opacity < 1 else ""
            if item.angle:
                dash += f' transform="rotate({item.angle:g} {item.x + item.w / 2:.1f} {item.y + item.h / 2:.1f})"'
            common = f'fill="{fill}" stroke="{item.stroke}" stroke-width="{item.width}"{dash}'
            corners = outline(item.kind, item.x, item.y, item.w, item.h)
            if item.kind in ("ellipse", "circle"):
                ox, oy, ow, oh = oval_box(item.kind, item.x, item.y, item.w, item.h)
                out.append(f'<ellipse cx="{ox + ow / 2:.1f}" cy="{oy + oh / 2:.1f}" '
                           f'rx="{ow / 2:.1f}" ry="{oh / 2:.1f}" {common}/>')
            elif corners is not None:
                pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in corners)
                out.append(f'<polygon points="{pts}" {common}/>')
            else:
                out.append(f'<rect x="{item.x:.1f}" y="{item.y:.1f}" width="{item.w:.1f}" height="{item.h:.1f}" '
                           f'rx="{item.radius}" {common}/>')
        elif isinstance(item, Head):
            out.append(f'<svg x="{item.x:.1f}" y="{item.y:.1f}" width="{hw * item.scale:.1f}" '
                       f'height="{hh * item.scale:.1f}" '
                       f'viewBox="{HEAD_FRAME * HEAD_W} {item.row * HEAD_H} {HEAD_W} {HEAD_H}" '
                       f'style="image-rendering:pixelated"{_svg_opacity(item)}><use href="#{ids[item.sheet]}"/></svg>')
        elif isinstance(item, Sticker):
            out.append(_svg_sticker(item))
        elif isinstance(item, Text):
            weight = ' font-weight="bold"' if item.bold else ""
            weight += ' font-style="italic"' if item.italic else ""
            lines = " ".join(d for d, on in (("underline", item.underline), ("line-through", item.strike)) if on)
            weight += f' text-decoration="{lines}"' if lines else ""
            weight += f' font-family="{e(item.font)}, Segoe UI, Arial, sans-serif"' if item.font else ""
            anchor = ' text-anchor="middle"' if item.centre else ' text-anchor="end"' if item.end else ""
            words = _svg_runs(item) if item.runs else e(item.text)
            moves = []
            if item.angle:
                moves.append(f"rotate({item.angle:g} {item.x:.1f} {item.y:.1f})")
            if item.mirror_h or item.mirror_v:
                my = item.y - item.size * 0.35
                moves.append(f"translate({item.x:.1f} {my:.1f}) scale({-1 if item.mirror_h else 1} "
                             f"{-1 if item.mirror_v else 1}) translate({-item.x:.1f} {-my:.1f})")
            if moves:
                anchor += f' transform="{" ".join(moves)}"'
            keep = ' xml:space="preserve"' if item.runs else ""     # the spaces between runs
            out.append(f'<text x="{item.x:.1f}" y="{item.y:.1f}" font-size="{item.size}"{weight}{anchor} '
                       f'fill="{item.colour}"{_svg_opacity(item)}{keep}>{words}</text>')
    out.append("</svg>")
    return "\n".join(out)


def html_page(svg_text: str, title: str, report_text: str, background: str = BACKGROUND) -> str:
    e = html.escape
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{e(title)}</title>"
            "<style>body{margin:0;background:" + background + ";font-family:Segoe UI,Arial,sans-serif}"
            ".bar{position:sticky;top:0;background:#1d2a1d;color:#fff;padding:6px 12px;z-index:2}"
            ".bar button{margin-left:6px}#wrap{overflow:auto}"
            "pre{background:#fff;margin:12px;padding:12px;white-space:pre-wrap;font-size:13px}</style>"
            "</head><body>"
            f"<div class=\"bar\">{e(title)} <button onclick=\"zoom(1.25)\">Zoom in</button>"
            "<button onclick=\"zoom(0.8)\">Zoom out</button><button onclick=\"zoom(0)\">Fit</button></div>"
            f"<div id=\"wrap\">{svg_text}</div>"
            f"<h2 style=\"margin:12px\">The Genealogy report</h2><pre>{e(report_text)}</pre>"
            "<script>var p=[].slice.call(document.querySelectorAll('#wrap svg')),f=1,"
            "w=Math.max.apply(null,p.map(function(s){return +s.getAttribute('width')}));"
            "function zoom(k){f=k?f*k:Math.min(1,(innerWidth-20)/w);"
            "p.forEach(function(s){s.style.width=(+s.getAttribute('width')*f)+'px';s.style.height='auto'})}"
            "zoom(0)</script>"
            "</body></html>\n")


# ---------------------------------------------------------------------------
# Writing it all
# ---------------------------------------------------------------------------

@dataclass
class Written:
    report: Path
    page: Path
    picture: Path | None


def build(folder: Path, game: int, slot: int, edits: Edits | None = None) -> tuple[gen.Village, Edits, Layout]:
    """The family, its edits (the saved ones unless given) and its tree."""
    folder = Path(folder)
    if edits is None:
        edits = Edits.load(Edits.path(folder, game, slot))
    village = gen.load_village(folder, game, slot, rename_answers=edits.renames)
    edits = full_name_edits(edits, village)
    apply_auto_marks(edits, village)            # every special villager marked, as the editor shows them
    arrange(village, edits)
    return village, edits, layout(village, edits)


def write(folder: Path, game: int, slot: int, images: Path | None, game_title: str = gen.GAME_TITLE,
          out: Path | None = None, edits: Edits | None = None, library: dict | None = None) -> Written:
    """The family's report, the tree's page and (on Windows) its picture, in the patcher's own folder for the
    save (Virtual Families 1 Patcher\\Save <N>\\Family Tree, or `out`) -- each run replaces the slot's last
    ones.  Nothing else is written; the save is only read."""
    import vf1_gdiplus
    folder = Path(folder)
    village, edits, lay = build(folder, game, slot, edits)
    present = sheets_present(game, images)
    pages = [scene(layout(village, edits, k), game_title, present, images, library)     # as the player arranged it
             for k in range(lay.pages)]
    title = title_lines(replace(lay, pages=1), game_title)[0]
    arrange(village, Edits(sort=edits.sort))         # the report: the records' generations
    text = gen.report(village, game_title)
    out = Path(out) if out is not None else reports_folder(folder, slot)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"Virtual Families 1 Family Tree - Save {slot}"
    report_path = out / f"{stem}.txt"
    report_path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    page_path = out / f"{stem}.html"
    page_path.write_bytes(html_page("\n".join(to_svg(sc, present) for sc in pages), title, text,
                                    lay.background).encode("utf-8"))
    picture = out / f"{stem}.png"
    made = vf1_gdiplus.save_scene(pages[0], present, picture)
    for k, sc in enumerate(pages[1:], 2):        # the later pages beside the first
        vf1_gdiplus.save_scene(sc, present, out / f"{stem} - Page {k}.png")
    for old in out.glob(f"{stem} - Page *.png"):  # pages an earlier, longer tree had
        number = old.stem.rpartition(" ")[2]
        if number.isdigit() and int(number) > len(pages):
            old.unlink(missing_ok=True)
    return Written(report_path, page_path, picture if made else None)
