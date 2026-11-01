"""The Picture Maker's "Meters and bars": every bar Virtual Families 1 draws, empty, full and at the levels
where its look changes, each put together from the game's own draws in the game's order.

Where the rules come from (the vanilla Virtual Families.exe 1.01.00; tests/test_art_meters.py runs every
function named here in Unicorn and checks these draws against the game's):

* The bar painter (one object, made on first use by 0x44F1F0 -> constructor 0x44EE20).  Its constructor
  fetches eight pictures: +8 StatusBarSliceB.png (0x38), +0xC StatusBarSliceR.png (0x39),
  +0x10 VD_progressbar-blue.jpg (7), +0x14 VD_progressbar-red.jpg (8), +0x18 VD_fade-01.png (9),
  +0x1C VD_fade-02.png (0xA), +0x20 VD_line-blue.jpg (0xB), +0x24 VD_line-red.jpg (0xC).  Its one drawing
  function 0x44EEA0(kind, value) (a jump table 0x44F1D8 for kinds 8..13):
    - percent: kind 9 (career progress) clamps the value to 3000 and divides by 30; the others clamp it to
      100; below 0 is 0.  The filled width w = percent * 290 / 100 (whole pixels, rounded down);
    - it narrows the window's clip rectangle (0x408410) to (x0, y, x0 + w, y + 30), then draws, each whole
      and each cut by the clip (0x408680 -> clip test 0x407E60 -> plain blit 0x404BC0): the fill picture at
      (x0, y), the start shading VD_fade-01 at (x0, y), the edge line at (x0 - 3 + w, y), the end shading
      VD_fade-02 at (x0 + 271, y); then puts the clip back (0x408440).  So the fill shows w pixels, the start
      shading is complete from 7 percent (w 20), the edge line moves with the end of the fill and is cut to
      nothing at 0 percent, and the end shading appears from 94 percent (w 272 > 271).
    - kind 9 uses the red fill and line; every other kind the blue ones.  StatusBarSliceB / R are never
      drawn: 0x44EEA0 never reads +8 or +0xC, and nothing else reads the painter (its pointer 0x56E814 is
      only touched by 0x44F1F0).
* The Details screen (theVillagerScene's drawing function 0x44B890): its background VD_BG_2.jpg at (0, 0)
  (it has the five empty silver troughs painted in), the portrait, then five bars at x0 = 473:
  Progress (kind 9, y 141: 3000 when the career level +0x2B70 is 7 or more, 0 without a career +0x2B6C,
  else the promotion points +0x2B74), Happiness (10, y 208, +0x2B0C), Fed (11, y 286, 100 - hunger
  +0x2B14), Energy (12, y 326, +0x2B08), Health (8, y 247, +0x2AE0).  Their words ("Progress", "Happiness",
  "Health", "Fed", "Energy", strings 0x2E, 0x2F, 0x431, 0x31, 0x32 at x 458, made in 0x44B282..0x44B4E5)
  are text the game writes.
* The loading screen (theLoadingScene 0x4406D0): loading.jpg, the frame LoadSceneBarBG.png at (250, 500),
  then the painter's kind 13 at x0 = 250, y 500 with the scene's counter (+0x24: 0 at the start, set to
  20, 30 .. 80 as loading goes on (0x423278), one more each update, still counting past 99 until the game
  is ready (0x440660)), then ldwLogo.png.
* An achievement on the Awards screen (one row: 0x412D00, called by 0x4353EA): while the achievement is
  not finished and its goal (0x4E951C + 24 * index) is more than 1, achievement_progress_box.png at
  (row x + 498, row y + 14), then, when the percent 0x412CA0 (count * 100 / goal, rounded down) is above
  0, a solid fill (0x408100 -> 0x403B40) of colour (216, 120, 10) from (row x + 500, row y + 16), 25 high
  and percent * 174 / 100 wide.  The words "count / goal" are text.  The game marks an achievement
  finished the moment its count reaches the goal (0x413210 -> 0x413170) and a finished one shows no bar.
* The bank's "Next 7 Days" chart (CBankingDlg 0x415300): a white panel 210 x 140 centred on the dialog's
  +0x70, top at +0x74; the highest value is the last day's plus a fifth (rounded down); each of the seven
  days a green bar 30 wide, as tall as 140 * its value (rounded down) / that highest (rounded down), with a
  black outline (0x409B70: top, right, bottom, left lines, each line 0x403DD0 a one-pixel fill with both
  ends included); before the first and the last bar a 30-pixel black tick out to the side at the bar's
  top (0x4081D0), next to which the game writes the balance; last the panel's black outline.  The numbers
  and the caption are text.

LoadColor.png (0x3A) is asked for by no code at all.
"""
from __future__ import annotations

import struct

import vf1_game_art as ga
import vf1_picture_image as pi
from vf1_game_art import Art, Fill

TITLE = "Meters and bars"
CAT = "Meters and bars"

BLUE, RED = "VD_progressbar-blue.jpg", "VD_progressbar-red.jpg"
START, END = "VD_fade-01.png", "VD_fade-02.png"
LINE_BLUE, LINE_RED = "VD_line-blue.jpg", "VD_line-red.jpg"
DETAILS_BG = "VD_BG_2.jpg"
LOAD_FRAME = "LoadSceneBarBG.png"
ACH_BOX = "achievement_progress_box.png"

BAR_W, BAR_H, END_AT = 290, 30, 271            # 0x44EEF9 (0x122), the clip's height, fade-02's place
# The painter's kinds (0x44F1D8): name, x0, y, red?
KINDS = {
    9: ("Progress", 473, 141, True),
    10: ("Happiness", 473, 208, False),
    8: ("Health", 473, 247, False),
    11: ("Fed", 473, 286, False),
    12: ("Energy", 473, 326, False),
    13: ("Loading", 250, 500, False),
}
DETAILS_ORDER = (9, 10, 11, 12, 8)             # the order 0x44B890 draws them
PIECE_SIZES = {BLUE: (290, 30), RED: (290, 30), START: (20, 35), END: (19, 33), LINE_BLUE: (3, 30),
               LINE_RED: (3, 30)}

# Levels: the asked-for ones, 1 (the smallest fill), 7 (the start shading complete) and 94 (the end shading
# first shows).
LEVELS = (0, 1, 7, 10, 25, 50, 75, 90, 94, 100)
ACH_LEVELS = (0, 1, 10, 25, 50, 75, 90, 99, 100)
ACH_COLOUR = (216, 120, 10, 255)               # 0x412FAB: the bytes d8 78 0a ff, r g b a
ACH_BOX_AT = (498, 14)                         # row x + 0x1F2, row y + 0xE
ACH_FILL_AT = (500, 16)                        # row x + 0x1F4, row y + 0x10
ACH_FILL_W, ACH_FILL_H = 174, 25               # 0xAE, 0x19

WHITE, GREEN, BLACK = (255, 255, 255, 255), (0, 255, 0, 255), (0, 0, 0, 255)   # 0x4E9FDC, 0x4E9FEC, 0x4E9FD8
CHART_X, CHART_Y = 400, 200                    # where the pictures put the chart (the dialog decides)
# Example balances for the seven days (dollars): the chart's look depends only on how they compare.
CHART_STATES = (
    ("savings", "Savings earning interest, no pay coming",
     (1100.0, 1210.0, 1331.0, 1464.1, 1610.51, 1771.561, 1948.7171)),
    ("pay", "Pay coming in, nothing saved yet",
     (300.0, 630.0, 993.0, 1392.3, 1831.53, 2314.683, 2846.1513)),
    ("both", "Savings and pay",
     (1400.0, 1840.0, 2324.0, 2856.4, 3442.04, 4086.244, 4794.8684)),
    ("flat", "The same every day",
     (500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0)),
)

CHECK_PAINTER = ("Checked against the game's own drawing code (the Details screen 0x44B890 and the bar painter "
                 "0x44EEA0, with its clip 0x407E60) run in Unicorn.")
CHECK_DETAILS = (CHECK_PAINTER[:-1] + ": every bar draw lands inside the picture. The background part is the "
                 "trough measured on VD_BG_2.jpg as the game's own libjpeg decodes it: the silver 290 x 30 and the "
                 "dark lines above and below it, nothing more.")
CHECK_LOADING = ("Checked against the game's own loading screen 0x4406D0 and bar painter 0x44EEA0 run in "
                 "Unicorn.")
CHECK_ACH = "Checked against the game's own achievement row 0x412D00 run in Unicorn."
CHECK_BANK = "Checked against the game's own chart 0x415300 run in Unicorn."
CHECK_PIECE = "Checked against the game's own bar painter 0x44EEA0 run in Unicorn."


# ------------------------------------------------------------------ the game's rules
def percent(kind: int, value: int) -> int:
    """0x44EEA0's percent for a value."""
    if kind == 9:
        value = min(value, 3000)
        p = int(value / 30) if value >= 0 else -(-value // 30)       # idiv rounds toward zero
    else:
        p = min(value, 100)
    return max(p, 0)


def width(p: int) -> int:
    return p * BAR_W // 100


def clip_draw(file: str, size: tuple, x: int, y: int, clip: tuple):
    """0x407E60: the whole picture `size` at (x, y) cut to `clip` (left, top, right, bottom); None when it
    is not drawn at all.  A draw cut to nothing in width is still made (a zero-width blit)."""
    left, top, right, bottom = 0, 0, size[0], size[1]
    cl, ct, cr, cb = clip
    if x >= cr or y >= cb:
        return None
    rx = x - left + right
    by = y - top + bottom
    if rx < cl or by < ct:
        return None
    if x < cl:
        left += cl - x
        x = cl
    if rx > cr:
        right += cr - rx
    if y < ct:
        top += ct - y
        y = ct
    if by > cb:
        bottom += cb - by
    return pi.Draw("bar", file, (left, top, right, bottom), x, y)


def painter_draws(kind: int, value: int) -> list:
    """The draws 0x44EEA0(kind, value) makes, in order."""
    _name, x0, y, red = KINDS[kind]
    w = width(percent(kind, value))
    clip = (x0, y, x0 + w, y + BAR_H)
    out = []
    for file, x in ((RED if red else BLUE, x0), (START, x0), (LINE_RED if red else LINE_BLUE, x0 - 3 + w),
                    (END, x0 + END_AT)):
        d = clip_draw(file, PIECE_SIZES[file], x, y, clip)
        if d is not None:
            out.append(d)
    return out


# The bars' empty troughs as painted in VD_BG_2.jpg (decoded as the game's libjpeg decodes it, vf1_jpeg): the
# silver is the bar's own 290 x 30 (x0 .. x0 + 289, y .. y + 29; the wood touches it left and right) with dark
# lines above and below it, (left, top, right, bottom) on the screen.  tests/test_art_emulated_extras.py measures
# them again on the decoded picture and runs the Details screen 0x44B890 to see every bar draw lands inside.
TROUGHS = {
    9: (473, 138, 763, 173),            # Progress: 3 dark lines above, 2 below
    10: (473, 206, 763, 240),           # Happiness: 2 above, 2 below
    8: (473, 245, 763, 279),            # Health: 2 above, 2 below
    11: (473, 284, 763, 319),           # Fed: 2 above, 3 below
    12: (473, 324, 763, 359),           # Energy: 2 above, 3 below
}


def trough(kind: int) -> pi.Draw:
    """The part of the Details screen's background (drawn whole at (0, 0) by 0x44B8A5) that is the bar's
    empty silver trough with its dark lines above and below."""
    rect = TROUGHS[kind]
    return pi.Draw("background", DETAILS_BG, rect, rect[0], rect[1])


def painter_value(kind: int, p: int) -> int:
    """The value the Details screen hands the painter for its bar `kind` at p percent."""
    return p * 30 if kind == 9 else p


def details_value(kind: int, p: int) -> dict:
    """The family member's numbers that make the Details screen's bar `kind` show p percent."""
    numbers = dict(health=50, energy=50, happiness=50, hunger=50, career=3, level=2, progress=1500)
    field = {8: "health", 10: "happiness", 12: "energy"}.get(kind)
    if field:
        numbers[field] = p
    elif kind == 11:
        numbers["hunger"] = 100 - p
    elif kind == 9:
        numbers["progress"] = p * 30
    return numbers


def achievement_layers(p: int) -> list:
    """0x412F40..0x412FD1 for a row at (0, 0): the box, then the fill when the percent is above 0."""
    out = [pi.Draw("box", ACH_BOX, (0, 0, -1, -1), *ACH_BOX_AT)]
    if p > 0:
        out.append(Fill(ACH_FILL_AT[0], ACH_FILL_AT[1], p * ACH_FILL_W // 100, ACH_FILL_H, ACH_COLOUR))
    return out


def _f32(v: float) -> float:
    return struct.unpack("<f", struct.pack("<f", v))[0]


def _rect_fill(l: int, t: int, r: int, b: int, rgba: tuple) -> Fill:
    return Fill(l, t, r - l, b - t, rgba)


def _line(x0: int, y0: int, x1: int, y1: int, rgba: tuple) -> Fill:
    """0x403DD0 for a level or upright line: a fill with both ends included."""
    return _rect_fill(min(x0, x1), min(y0, y1), max(x0, x1) + 1, max(y0, y1) + 1, rgba)


def _outline(l: int, t: int, r: int, b: int, rgba: tuple) -> list:
    """0x409B70: top, right, bottom, left."""
    return [_line(l, t, r, t, rgba), _line(r, t, r, b, rgba), _line(l, b, r, b, rgba), _line(l, t, l, b, rgba)]


def chart_layers(values, x: int = CHART_X, y: int = CHART_Y) -> list:
    """The fills 0x415300 makes for seven balances (float32, as the dialog keeps them)."""
    values = [_f32(v) for v in values]
    top_value = int(values[6] / 5.0 + values[6])
    left, bottom = x - 105, y + 140
    out = [_rect_fill(left, y, x + 105, bottom, WHITE)]
    for k, v in enumerate(values):
        h = int(v) * 140 // top_value
        l, r, t = left + 30 * k, left + 30 * (k + 1), bottom - h
        if k == 0:
            out.append(_line(l - 30, t, l, t, BLACK))
        elif k == 6:
            out.append(_line(r, t, r + 30, t, BLACK))
        out.append(_rect_fill(l, t, r, bottom, GREEN))
        out += _outline(l, t, r, bottom, BLACK)
    out += _outline(left, y, x + 105, bottom, BLACK)
    return out


# ------------------------------------------------------------------ the catalogue
WORDS = ' The word "{word}" beside it is text the game writes; it is not part of the picture.'
WHY_DETAILS = {
    9: ("The Details screen's Progress bar: how near the career's next promotion is (its promotion points out "
        "of 3,000; full at the top level 7, empty without a career). Drawn red by the bar painter (0x44EEA0, "
        "kind 9) from the Details screen (0x44B922)."),
    10: ("The Details screen's Happiness bar (happiness 0 to 100). Drawn by the bar painter (0x44EEA0, "
         "kind 10) from the Details screen (0x44B937)."),
    11: ("The Details screen's Fed bar: 100 less the hunger, so it empties as the family member gets hungry. "
         "Drawn by the bar painter (0x44EEA0, kind 11) from the Details screen (0x44B953)."),
    12: ("The Details screen's Energy bar (energy 0 to 100). Drawn by the bar painter (0x44EEA0, kind 12) from "
         "the Details screen (0x44B968)."),
    8: ("The Details screen's Health bar (health 0 to 100). Drawn by the bar painter (0x44EEA0, kind 8) from "
        "the Details screen (0x44B97D)."),
}
TROUGH = (" Its empty silver trough is part of the Details screen's background VD_BG_2.jpg (drawn whole first, "
          "0x44B8A5); the picture shows that part of it.")


def _level_words(p: int) -> str:
    if p == 0:
        return "empty"
    if p == 100:
        return "full"
    return f"{p}% full"


def _details_arts() -> list[Art]:
    arts = []
    for kind in DETAILS_ORDER:
        name = KINDS[kind][0]
        for p in LEVELS:
            notes = ""
            if p == 1:
                notes = " At 1 percent the fill, the start shading and the edge line show 2 pixels."
            elif p == 7:
                notes = " From 7 percent the start shading shows complete."
            elif p == 94:
                notes = " From 94 percent the end shading starts to show."
            elif p == 0:
                notes = " At 0 the painter draws only the edge line, cut to nothing."
            arts.append(Art(
                f"meters/details/{name.lower()}/{p}", f"{CAT}/{name} bar", f"{name} bar, {_level_words(p)}",
                (trough(kind), *painter_draws(kind, painter_value(kind, p))),
                True, WHY_DETAILS[kind] + notes + TROUGH + WORDS.format(word=name), CHECK_DETAILS))
    return arts


def _loading_arts() -> list[Art]:
    arts = []
    for p in LEVELS:
        layers = (pi.Draw("frame", LOAD_FRAME, (0, 0, -1, -1), 250, 500), *painter_draws(13, p))
        arts.append(Art(
            f"meters/loading/{p}", f"{CAT}/Loading bar", f"Loading bar, {_level_words(p)}", layers, True,
            "The bar on the loading screen: the frame LoadSceneBarBG.png, then the blue bar of the bar painter "
            "(0x44EEA0, kind 13) at the loading counter, which starts at 0 and keeps counting past 100 until "
            "the game is ready (0x440660); the screen draws it at 0x440706 and 0x440718. "
            "The frame is drawn at the bar's own top-left corner, so it shows 2 pixels to the right of and "
            "below the bar.", CHECK_LOADING))
    return arts


def _achievement_arts() -> list[Art]:
    arts = []
    for p in ACH_LEVELS:
        if p == 100:
            used, why = False, (
                "A full achievement bar: the game marks an achievement finished the moment its count reaches "
                "the goal (0x413210 -> 0x413170), and the Awards screen shows a finished one without the bar "
                "(0x412F2D), so the full bar is never shown.")
        else:
            used, why = True, (
                "The progress bar of an unfinished achievement on the Awards screen: the box "
                "achievement_progress_box.png (0x412F7B), then an orange fill as wide as the count is of the "
                "goal (0x412FD1); only achievements whose goal is more than 1 have one.")
        arts.append(Art(
            f"meters/achievement/{p}", f"{CAT}/Achievement progress bar", f"Achievement progress bar, "
            f"{_level_words(p)}", tuple(achievement_layers(p)), used,
            why + ' The "count / goal" words on it are text the game writes.', CHECK_ACH))
    return arts


def _bank_arts() -> list[Art]:
    arts = []
    for key, words, values in CHART_STATES:
        arts.append(Art(
            f"meters/bank/{key}", f"{CAT}/Bank: next 7 days chart", f"Bank's next 7 days chart: {words}",
            tuple(chart_layers(values)), True,
            "The chart in the bank's window (0x415300): a green bar for each of the next seven days' projected "
            "balance, against the last day's plus a fifth, drawn with solid fills and lines. The balances "
            "here are examples. The amounts beside the first and last bars and the caption \"Next 7 Days\" "
            "are text the game writes.", CHECK_BANK))
    return arts


def _piece_arts() -> list[Art]:
    return [
        Art("meters/pieces/start-shading", f"{CAT}/Bar pieces", "Bar start shading, as the bars show it",
            (pi.Draw("piece", START, (0, 0, 20, 30), 0, 0),), True,
            "VD_fade-01.png is 35 pixels high; every bar cuts it to its top 30 rows (the painter's clip, "
            "0x44EEA0).", CHECK_PIECE),
        Art("meters/pieces/end-shading", f"{CAT}/Bar pieces", "Bar end shading, as a full bar shows it",
            (pi.Draw("piece", END, (0, 0, 19, 30), 0, 0),), True,
            "VD_fade-02.png is 33 pixels high; a full bar shows its top 30 rows at the bar's right end "
            "(0x44EEA0).", CHECK_PIECE),
    ]


def _unused_arts() -> list[Art]:
    return [
        Art("meters/unused/status-slice-blue", f"{CAT}/Unused bar pieces", "Blue status bar slice",
            (ga.whole("StatusBarSliceB.png"),), False, USAGE[0x38][1]),
        Art("meters/unused/status-slice-red", f"{CAT}/Unused bar pieces", "Red status bar slice",
            (ga.whole("StatusBarSliceR.png"),), False, USAGE[0x39][1]),
        Art("meters/unused/load-colour", f"{CAT}/Unused bar pieces", "Loading bar colour slice",
            (ga.whole("LoadColor.png"),), False, USAGE[0x3A][1]),
    ]


def arts(files: ga.GameFiles) -> list[Art]:
    out = _details_arts() + _loading_arts() + _achievement_arts() + _bank_arts() + _piece_arts()
    out += [a for a in _unused_arts() if files.has(a.layers[0].file)]
    needed = {layer.file for a in out for layer in a.layers if isinstance(layer, pi.Draw)}
    missing = sorted(n for n in needed if not files.has(n))
    if missing:
        out = [a for a in out if not any(isinstance(l, pi.Draw) and l.file in missing for l in a.layers)]
    return out


USAGE = {
    0x06: (True, "The loading bar's frame (0x440706)."),
    0x07: (True, "The blue fill of the Details screen's Happiness, Health, Fed and Energy bars and the loading "
                 "bar (bar painter +0x10, 0x44EEA0)."),
    0x08: (True, "The red fill of the Details screen's Progress bar (bar painter +0x14, 0x44EF5F)."),
    0x09: (True, "The shading at the start of every painter bar, top 30 rows (bar painter +0x18, 0x44EEA0)."),
    0x0A: (True, "The shading at the end of a painter bar from 94 percent, top 30 rows (bar painter +0x1C, "
                 "0x44EEA0)."),
    0x0B: (True, "The moving edge of the blue painter bars (bar painter +0x20, 0x44EEA0)."),
    0x0C: (True, "The moving edge of the red Progress bar (bar painter +0x24, 0x44EF81)."),
    0x38: (False, "Fetched into the bar painter (+8, 0x44EE3E) but never drawn: the painter's only drawing "
                  "function 0x44EEA0 never reads +8, and nothing else reads the painter."),
    0x39: (False, "Fetched into the bar painter (+0xC, 0x44EE4A) but never drawn: the painter's only drawing "
                  "function 0x44EEA0 never reads +0xC, and nothing else reads the painter."),
    0x3A: (False, "No code asks for picture 0x3A; the loading bar is painted with VD_progressbar-blue.jpg "
                  "instead (0x44F154)."),
    0xCC: (True, "The frame of an unfinished achievement's progress bar on the Awards screen (0x412F7B)."),
}

CELL_LABELS = {
    (0x06, 0): "Loading bar frame",
    (0x07, 0): "Blue bar fill",
    (0x08, 0): "Red bar fill",
    (0x09, 0): "Shading at a bar's start",
    (0x0A, 0): "Shading at a bar's end",
    (0x0B, 0): "Blue bar's moving edge",
    (0x0C, 0): "Red bar's moving edge",
}

CELL_UNUSED: dict = {}
