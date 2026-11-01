"""The Picture Maker's interface pictures for Virtual Families 1: the buttons in every state the game draws,
check boxes and choices, the sliders and scroll bars put together, the dialog backdrops built from their nine
tiles at the sizes real dialogs use, the mouse pointers, icons and logos, and the full-screen backgrounds --
each drawn as the game draws it, and the interface pictures no code ever shows, marked unused with the reason.

How the game draws them (the vanilla Virtual Families.exe 1.01.00; every draw ends in
ldwGameWindowImpl::BlitRectWithAlpha 0x404C30 or the plain SDL blit 0x404BC0):

* Buttons (ldwButtonImpl, built by 0x4018E0 from a strip of three cells): 0x4011D0 draws cell `state`
  (0x408920 -> 0x4087C0): 0 normal (0x401630), 1 mouse over (0x401640), 2 pressed (0x401620), the state
  0x401710 keeps in +0x30.  A button that is not shown (+0x28) is not drawn at all; the tinted draw
  0x401265 -> 0x408EC0 needs +0x29 = 0, and the only write to +0x29 is the constructor's 1 (0x401938), so
  no button is ever drawn greyed out.  The label is text (pressed: 2 pixels lower and right, 0x401314).
* Check boxes and radio buttons (ldwRadioButtonImpl, built by 0x40BF50): 0x40BC40 draws cell
  min(mouse state, columns/2 - 1) + (ticked ? columns/2 : 0); with two cells that is cell 0 unticked,
  cell 1 ticked, whatever the mouse does.
* Dialog backdrops (ldwTiledBackground 0x40DF90): the 64 x 64 tiles of a nine-cell sheet, never stretched:
  columns = max(2, (tile + 12 + width - 1) / tile), rows = max(2, (tile + 18 + height - 1) / tile)
  (0x40DD50, the 12 and 18 set at 0x422B25 / 0x422B2F); 0x40DDD0 draws the top row 8, 1 ..., 0, each middle
  row 3, 7 ..., 2, the bottom row 5, 4 ..., 6.  0x44F5B0 picks the sheet from the dialog's style: 1 the
  e-mail grid, 2 orange, anything else green.  A dialog fades in (0x40E220 adds 0.1 or 0.2 a frame to its
  alpha) and is then drawn fully opaque (0x40E2F0), at 70% when it was opened without stopping the game
  (0x401B10's second argument, +0xC, 0x40E356).
* The pictures drawn by image number go through theGraphicsManager 0x44F960 (id, x, y, alpha, percent),
  0x44F880 (centred) or a picture object's 0x4098C0 (whole, at x, y).

USAGE / CELL_LABELS / CELL_UNUSED cover this area's image numbers.  tests/test_art_ui.py runs the game's own
drawing code for every picture listed here (tests/ui_emu.py) and compares the draws.
"""
from __future__ import annotations

import vf1_game_art as ga
import vf1_picture_image as pi

TITLE = "Interface"

BTN = "Buttons and controls/Buttons"
TOGGLE = "Buttons and controls/Check boxes and choices"
SLIDE = "Buttons and controls/Sliders and scroll bars"
ARROW = "Buttons and controls/Tip arrows"
DLG = "Dialogs and panels/Dialog backdrops"
PANEL = "Dialogs and panels/Panels"
CURSOR = "Icons and cursors/Mouse pointers"
ICON = "Icons and cursors/Icons"
LOGO = "Icons and cursors/Logos"
SCREEN = "Screens and backgrounds"

EMU = "Checked against the game's own drawing code"
REACH = "reach.py: reached"

STATES = ((0, "normal", "Normal"), (1, "over", "Mouse over"), (2, "pressed", "Pressed"))

# image id: (label, where it is drawn: (plain words, addresses of the constructors that make the button))
BUTTONS = {
    0x22: ("Wide button", "the island event dialog's choices", "0x41ABAD, 0x41ABEB"),
    0x23: ("Blue button", "the family tree screen", "0x4389DD"),
    0x24: ("Brown button", "the adoption screen", "0x435858, 0x435917"),
    0x25: ("Green button", "the dialogs' buttons (Options 0x41D5DF, Banking 0x41571D, Tip 0x41ECED, message "
           "boxes 0x41C8AC / 0x41CBCE, Purchase 0x41E4E7) and the house screen", "0x44417A"),
    0x26: ("Orange button", "the achievements, collection, family tree, help, store and villager screens and the "
           "house screen", "0x435122, 0x436AE2, 0x43895B, 0x43FEB4, 0x44977E, 0x44A4F5, 0x4440CD"),
    0x27: ("Red button", "the Change Player, nickname, message box and Purchase dialogs and the dating screen",
           "0x41BA33, 0x41C450, 0x41CD84, 0x41E60D, 0x437724"),
    0x28: ("Dollar button", "the house screen", "0x4444E2"),
    0x2A: ("Big orange button", "the main menu", "0x447992"),
    0x2B: ("Long green button", "the main menu", "0x447A16, 0x447A9C, 0x447B22, 0x447BA8"),
    0x2F: ("Left arrow button", "the villager details screen", "0x44A5CF"),
    0x30: ("Right arrow button", "the villager details screen", "0x44A57A"),
    0x48: ("Empty button", "the house screen", "0x444590"),
    0xC7: ("Up arrow button", "the achievements, family tree and help screens' scroll bars",
           "0x435193, 0x438A51, 0x43FF24"),
    0xC8: ("Down arrow button", "the achievements, family tree and help screens' scroll bars",
           "0x4351E2, 0x438A9E, 0x43FF71"),
}
UNUSED_BUTTONS = {0x29: ("Clear button", "No code asks for picture 0x29 (btn_clear.png): no call to the picture "
                         "loaders 0x44F5A0 / 0x44F860 / 0x44F590 passes 0x29.")}

GRIDS = {0x2C: "OrangeDlgTileGrid.png", 0x2D: "GreenDlgTileGrid.png", 0x2E: "dlgemailgrid.png"}
TILE_CELLS = {0: "Top right corner", 1: "Top edge", 2: "Right edge", 3: "Left edge", 4: "Bottom edge",
              5: "Bottom left corner", 6: "Bottom right corner", 7: "Middle", 8: "Top left corner"}
OVERLAP_X, OVERLAP_Y = 12, 18                      # 0x5008B8 / 0x5008B4, set at 0x422B25 / 0x422B2F

# (key, label, grid, width, height, alpha, where)
DIALOGS = (
    ("options", "Options dialog (640 x 498)", 0x2D, 640, 498, 1.0,
     "theOptionsDialog 0x41D4A5..0x41D4C0, opened from the main menu with style 0 (0x448349)"),
    ("diagnosis", "Diagnosis dialog (600 x 340)", 0x2D, 600, 340, 1.0, "theDiagnosisDialog 0x416863..0x416880"),
    ("nickname", "Nickname dialog (360 x 200)", 0x2D, 360, 200, 1.0,
     "theCreateNickNameDlg 0x41C3CE..0x41C3E7, style 0 (0x448475)"),
    ("family-info", "Family tree info dialog (710 x 250)", 0x2D, 710, 250, 1.0,
     "CFamilyTreeInfoDlg 0x416D3F..0x416D5A, style 0"),
    ("achievement-popup", "Achievement earned pop-up (703 x 60)", 0x2D, 703, 60, pi.f32(0.7),
     "the achievement pop-up 0x412D90..0x412DA3, drawn at 70% of its fade (0x412E3F)"),
    ("banking", "Banking dialog (560 x 440)", 0x2C, 560, 440, 1.0, "CBankingDlg 0x4157E0..0x4157F4"),
    ("island-orange", "Island event dialog (512 wide; the height follows the text, shown 256)", 0x2C, 512, 256,
     1.0, "CIslandEventDialog 0x41AECE..0x41AEE6 (style 2)"),
    ("island-email", "E-mail dialog (512 wide; the height follows the text, shown 256)", 0x2E, 512, 256, 1.0,
     "CIslandEventDialog 0x41AECE..0x41AEE6 (style 1, an e-mail)"),
    ("island-email-tall", "E-mail dialog (512 wide, shown 384 tall)", 0x2E, 512, 384, 1.0,
     "CIslandEventDialog 0x41AECE..0x41AEE6 (style 1, an e-mail)"),
)

SLIDER_SCALE = 263                                 # 0x4B5B90: the handle travels trunc(volume x 263) pixels


def _size(files: ga.GameFiles, name: str):
    try:
        return files.size(name) if files.has(name) else None
    except Exception:                               # a picture that cannot be read is left out, never raised
        return None


def _cell(files: ga.GameFiles, image: int, index: int):
    name, cols, rows, _n = ga.TABLE[image]
    size = _size(files, name)
    if size is None:
        return None
    cols, rows = cols or 1, rows or 1
    return name, ga.cell_rect(size, cols, rows, index % cols, index // cols)[1]


def tiled_backdrop(files: ga.GameFiles, image: int, width: int, height: int, x: int = 0, y: int = 0,
                   alpha: float = 1.0) -> tuple:
    """The draws of ldwTiledBackground 0x40DF90 / 0x40DDD0 for a dialog of width x height."""
    name = ga.TABLE[image][0]
    w, h = files.size(name)
    tw, th = w // 9, h
    cols = max(2, (tw + OVERLAP_X + width - 1) // tw)
    rows = max(2, (th + OVERLAP_Y + height - 1) // th)

    def tile(cell, tx, ty):
        return pi.Draw("tile", name, (cell * tw, 0, cell * tw + tw, th), tx, ty, 1.0, alpha)

    out = []
    for r in range(rows):
        left, mid, right = (8, 1, 0) if r == 0 else (5, 4, 6) if r == rows - 1 else (3, 7, 2)
        ty = y + r * th
        out.append(tile(left, x, ty))
        out.extend(tile(mid, x + (k + 1) * tw, ty) for k in range(cols - 2))
        out.append(tile(right, x + (cols - 1) * tw, ty))
    return tuple(out)


def family_tree_bar(files: ga.GameFiles, overflow: int) -> tuple:
    """The family tree's scroll bar: the knob set up by 0x439318..0x439366 (the track at 0x2F3, 0xA7 ..
    0x22A from 0x438AE0), drawn by 0x43A2AB..0x43A384 at the top of its travel."""
    tx, ty, bottom = 0x2F3, 0xA7, 0x22A
    kx, top = tx - 10, ty
    length = bottom - ty - overflow if overflow < bottom - ty - 0x18 else 0x18
    end = top + length + 2
    th = files.size("familytree_scrollknob_top.png")[1]
    mw = files.size("familytree_scrollknob_mid.png")[0]
    out = [pi.Draw("track", "familytree_slidertrack.png", (0, 0, -1, -1), tx, ty),
           pi.Draw("knob top", "familytree_scrollknob_top.png", (0, 0, -1, -1), kx, top - 2)]
    mid = (end - top) - 2 * th
    if mid > 0:
        out.append(pi.Draw("knob middle", "familytree_scrollknob_mid.png", (0, 0, mw, mid), kx, top + th - 2))
    out.append(pi.Draw("knob bottom", "familytree_scrollknob_btm.png", (0, 0, -1, -1), kx, end - th - 2))
    return tuple(out)


def achievements_bar(files: ga.GameFiles) -> tuple:
    """The achievements screen's scroll bar as its constructor 0x435201..0x4352B5 sets it up (the list is
    6,702 pixels long, so the knob has its least length, 28) and 0x43540E..0x4354EE draws it."""
    tx, ty, bottom, content = 0x2E9, 0x79, 0x22D, 0x1A2E + 0x51 - 0x258
    kx, top = tx - 6, ty
    length = bottom - ty - content if content < bottom - ty - 0x1C else 0x1C
    end = top + length + 2
    th = files.size("familytree_scrollknob_top.png")[1]
    mw = files.size("familytree_scrollknob_mid.png")[0]
    out = [pi.Draw("track", "verticalslidertrack.png", (0, 0, -1, -1), tx, ty),
           pi.Draw("knob top", "familytree_scrollknob_top.png", (0, 0, -1, -1), kx, top)]
    mid = (end - top) - 2 * th
    if mid > 0:
        out.append(pi.Draw("knob middle", "familytree_scrollknob_mid.png", (0, 0, mw, mid), kx, top + th))
    out.append(pi.Draw("knob bottom", "familytree_scrollknob_btm.png", (0, 0, -1, -1), kx, end - th))
    return tuple(out)


def _resolve_layers(files: ga.GameFiles, layers: tuple) -> tuple:
    return ga.resolve(files, ga.Art("x", "x", "x", layers, True, "")).layers


# ------------------------------------------------------------------ the catalogue
def arts(files: ga.GameFiles) -> list:
    out: list = []

    def add(key, category, label, layers, used, why, checked=""):
        out.append(ga.Art("ui/" + key, category, label, tuple(layers), used, why, checked))

    # buttons
    for image, (label, where, sites) in BUTTONS.items():
        for state, slug, words in STATES:
            cell = _cell(files, image, state)
            if cell is None:
                continue
            name, rect = cell
            why = (f"Drawn as a button on {where} in its {words.lower()} state: the button draw 0x4011D0 uses "
                   f"cell {state} ({sites}).")
            if state == 0:
                why += " There is no greyed-out look: a hidden button is not drawn (0x4011DA)."
            add(f"buttons/{image:02x}/{slug}", BTN, f"{label}, {words.lower()}",
                [pi.Draw("button", name, rect, 0, 0)], True, why,
                f"{EMU} 0x4018E0 / 0x4011D0 run in Unicorn.")
    for image, (label, why) in UNUSED_BUTTONS.items():
        for state, slug, words in STATES:
            cell = _cell(files, image, state)
            if cell is not None:
                add(f"buttons/{image:02x}/{slug}", BTN, f"{label}, {words.lower()}",
                    [pi.Draw("button", cell[0], cell[1], 0, 0)], False, why)

    # check boxes and choices
    toggles = ((0x34, "checkbox", "Options check box", True,
                "Drawn as the Options dialog's four check boxes (made at 0x41D6B7, 0x41D722, 0x41D78D, 0x41D7F8) by "
                "0x40BC40, cell {cell}; the mouse does not change the cell (columns / 2 = 1)."),
               (0x31, "radio", "Editor radio button", True,
                "Drawn by 0x40BC40, cell {cell}, as the radio buttons of the animation-alignment editor screen "
                "(theAlignVillagerScene, made at 0x43E6FE / 0x43E762), a developer tool; reach.py counts that code "
                "as reached, though no write of its game state 5 (0x422E74) was found."))
    for image, slug, label, used, why in toggles:
        for cell, words in ((0, "not ticked"), (1, "ticked")):
            c = _cell(files, image, cell)
            if c is not None:
                add(f"toggles/{slug}/{cell}", TOGGLE, f"{label}, {words}", [pi.Draw("toggle", c[0], c[1], 0, 0)],
                    used, why.format(cell=cell), f"{EMU} 0x40BF50 / 0x40BC40 run in Unicorn, every mouse state.")
    for picked, words in ((0, "first picked"), (1, "second picked")):
        if _size(files, "radioblank.png") and _size(files, "radioselected.png"):
            first, second = ("radioselected.png", "radioblank.png") if picked == 0 else \
                ("radioblank.png", "radioselected.png")
            add(f"toggles/choice/{picked}", TOGGLE, f"Options choice pair, {words}",
                [pi.Draw("choice", first, (0, 0, -1, -1), 0, 0), pi.Draw("choice", second, (0, 0, -1, -1), 0x58, 0)],
                True, "Drawn by the Options dialog 0x41D9C0 for its yes / no rows (0x41DB65..0x41DC48): the picked "
                "choice is radioselected.png (0x33), the other radioblank.png (0x32), 88 pixels apart.",
                f"{EMU} 0x41D9C0 run in Unicorn.")
    add("toggles/checkmark", TOGGLE, "Check mark", [ga.whole("checkmark.png")] if _size(files, "checkmark.png") else [],
        False, "No code asks for picture 0x35 (checkmark.png): no call to the picture loaders passes 0x35; the "
        "Options check boxes use CheckboxStrip.png (0x34, 0x41D461).")

    # sliders and scroll bars
    if _size(files, "WideSlider2.png") and _size(files, "sliderhandle.png"):
        for volume, words in ((0.0, "off"), (0.5, "half"), (1.0, "full")):
            add(f"sliders/volume/{int(volume * 100)}", SLIDE, f"Options volume slider, {words}",
                [pi.Draw("track", "WideSlider2.png", (0, 0, -1, -1), 0, 0),
                 pi.Draw("handle", "sliderhandle.png", (0, 0, -1, -1), 4 + int(volume * SLIDER_SCALE), 0)],
                True, "Drawn by the Options dialog 0x41D9C0 for the sound and music volumes (0x41DD9D..0x41DE2C): the "
                "track at +0xF0, the handle at +0xF4 plus trunc(volume x 263) (0x41D588..0x41D5AB).",
                f"{EMU} 0x41D566..0x41D5AE and 0x41D9C0 run in Unicorn.")
    knob = all(_size(files, n) for n in ("familytree_scrollknob_top.png", "familytree_scrollknob_mid.png",
                                         "familytree_scrollknob_btm.png"))
    if knob and _size(files, "verticalslidertrack.png"):
        add("sliders/achievements", SLIDE, "Achievements scroll bar", achievements_bar(files), True,
            "Drawn by the achievements screen 0x435360 (0x435418..0x4354E9): the track verticalslidertrack.png, "
            "then the knob's top, middle (a piece of familytree_scrollknob_mid.png as long as needed, 0x4354CF) "
            "and bottom; the list is so long that the knob has no middle.",
            f"{EMU} 0x435201..0x4352B5 and 0x435360 run in Unicorn.")
    if knob and _size(files, "familytree_slidertrack.png"):
        for overflow, words in ((100, "long knob"), (1000, "short knob")):
            add(f"sliders/family-tree/{overflow}", SLIDE, f"Family tree scroll bar, {words}",
                family_tree_bar(files, overflow), True,
                "Drawn by the family tree screen 0x43A1B0 (0x43A2AB..0x43A37F): the knob's length is the track's "
                f"less what does not fit (here {overflow} pixels), at least 24 (0x439318..0x439366).",
                f"{EMU} 0x439318..0x439366 and 0x43A2AB..0x43A384 run in Unicorn.")

    # tip arrows
    for image, words in ((0x49, "up"), (0x4A, "down"), (0x4B, "left"), (0x4C, "right")):
        name = ga.TABLE[image][0]
        if _size(files, name):
            add(f"arrows/{image:02x}", ARROW, f"Tip arrow pointing {words}", [ga.whole(name)], True,
                "Drawn whole and fully opaque by the tip dialog 0x41F050 (0x41F2E3), bobbing along its direction by "
                "up to a quarter of its size (0x41F248..0x41F2A3); picked at 0x41EE2B..0x41EEE0.",
                f"{EMU} 0x41F23A..0x41F2E8 run in Unicorn.")

    # dialogs
    for key, label, image, width, height, alpha, where in DIALOGS:
        if _size(files, GRIDS[image]):
            add(f"dialogs/{key}", DLG, label, tiled_backdrop(files, image, width, height, 0, 0, alpha), True,
                f"Built from {GRIDS[image]}'s nine tiles by ldwTiledBackground 0x40DF90 / 0x40DDD0 for {where}.",
                f"{EMU} 0x40DF90 / 0x40DDD0 run in Unicorn" + (" (0x412D68..0x412E5D for the pop-up)."
                                                                 if key == "achievement-popup" else "."))

    # panels
    for image, words, key in ((0xCA, "Achievement, not yet earned", "box"),
                              (0xCB, "Achievement, earned", "box-earned")):
        name = ga.TABLE[image][0]
        if _size(files, name):
            add(f"panels/achievement-{key}", PANEL, words, [ga.whole(name)], True,
                "Drawn behind each row of the achievements list by 0x412D00 (0x412E1E: picture 0xCA, or 0xCB when the "
                "achievement is earned), 8 pixels right of the row.", f"{EMU} 0x412DE5..0x412E23 run in Unicorn.")
    for image, words, why, checked in (
            (0xCD, "Screen bottom bar",
             "Drawn at the bottom of the achievements, family tree, help and store screens at (0, 519) "
             "(0x435504, 0x43A39A, 0x44024D, 0x448E8D).", f"{EMU} 0x435360 and 0x43A384..0x43A39F run in Unicorn."),
            (0xC1, "Family tree parent frame", "Drawn around the parents on the family tree screen (0x439C4D, "
             "0x439D90, picture 0xC1).", ""),
            (0xC2, "Family tree child frame", "Drawn around each child on the family tree screen (0x439F16, "
             "picture 0xC2).", "")):
        name = ga.TABLE[image][0]
        if _size(files, name):
            add(f"panels/{image:02x}", PANEL, words, [ga.whole(name)], True, why, checked)

    # mouse pointers: SetCursor 0x408340 with the hot spot (21, 24) from 0x4F11FC / 0x4F1200; 0x409358 draws it
    for image, words, why in (
            (0x01, "Mouse pointer, open hand", "The game's mouse pointer, set by the house screen's constructor "
             "(0x444089) and again when the mouse button is let go (0x445A22, event 3 of 0x447220), drawn whole "
             "with its hot spot 21 pixels in and 24 down (0x409358..0x409376)."),
            (0x02, "Mouse pointer, closed hand", "The pointer while the mouse button is held down on the house "
             "screen (set at 0x446310, event 2 of 0x447220), drawn whole with its hot spot 21 pixels in and 24 "
             "down (0x409358..0x409376).")):
        name = ga.TABLE[image][0]
        if _size(files, name):
            add(f"cursors/{image:02x}", CURSOR, words, [pi.Draw("pointer", name, (0, 0, -1, -1), -21, -24)], True,
                why, f"{EMU} 0x409358..0x40937B run in Unicorn.")

    # icons
    if _size(files, "focus_circle.png"):
        add("icons/focus", ICON, "Selected villager ring", [ga.whole("focus_circle.png")], True,
            "Drawn under the selected villager by the focus ring 0x44EC30 (from 0x48B757).",
            f"{EMU} 0x44EC30 run in Unicorn.")
    for image, words, slot_args in (
            (0x6C, "E-mail icon, small", "(1111, 1206) and (929, 1182) (0x44510A, 0x44512A)"),
            (0x6D, "E-mail icon, big", "(750, 30) (0x4450EC)")):
        name = ga.TABLE[image][0]
        for frame in (0, 1):
            c = _cell(files, image, frame)
            if c is not None:
                add(f"icons/email-{image:02x}/{frame}", ICON, f"{words}, frame {frame + 1}",
                    [pi.Draw("icon", c[0], c[1], 0, 0)], True,
                    f"Played as a two-frame animation (anim 0x{image - 0x4D:X} of the table 0x4EB370) by the house "
                    f"screen's update 0x444DB0 at {slot_args}; 0x421A30 draws the frame centred, fully opaque.",
                    f"{EMU} 0x4217B0 / 0x421810 / 0x421A30 run in Unicorn.")
    for image, words, site in ((0xD3, "On sale tag", "0x448E16"), (0xD1, "Red check mark", "0x448E5C")):
        name = ga.TABLE[image][0]
        if _size(files, name):
            add(f"icons/{image:02x}", ICON, words, [ga.whole(name)], True,
                f"Drawn centred on store items by the store screen 0x448C10 ({site}).",
                f"{EMU} 0x44F880 run in Unicorn.")

    # logos
    if _size(files, "ldwLogo.png"):
        add("logos/ldw", LOGO, "LDW logo", [pi.Draw("logo", "ldwLogo.png", (0, 0, -1, -1), 0x2F, 0x190)], True,
            "Drawn on the loading screen at (47, 400) (0x440730).", f"{EMU} 0x44071D..0x440735 run in Unicorn.")
    if _size(files, "logo1.png"):
        add("logos/logo1", LOGO, "Virtual Families logo", [ga.whole("logo1.png")], False,
            "No code asks for picture 0x41 (logo1.png): no call to the picture loaders passes 0x41.")
    add("logos/small", LOGO, "Small logo", [ga.whole("small_logo.png")] if _size(files, "small_logo.png") else [],
        False, "No code asks for picture 0x42 (small_logo.png); the file is missing from the game too.")
    for name, words, site in (("menu_logo.png", "Menu logo", "0x425104"),
                              ("loading_logo.png", "Loading logo", "0x425149")):
        add(f"logos/{name[:-4]}", LOGO, words, [ga.whole(name)] if _size(files, name) else [], False,
            f"Loaded by name only when the file exists ({site}); the game ships without {name}.")

    # screens and backgrounds (0x44F960 id, 0, 0, alpha 1, 100%)
    screens = ((0x3D, "Achievements background", "the achievements screen 0x435360 (0x435387)", True),
               (0x3F, "Loading screen", "the loading screen 0x4406D0 (0x4406EB)", True),
               (0x5A, "Adoption background", "the adoption screen 0x4362D0 (0x43633F)", True),
               (0x45, "House screen background", "the house screen 0x440A20 (0x440A56), from its bottom edge", False),
               (0x46, "Help page", "the help screen 0x4400B0 (0x440107), scrolled with the page (0x440143)", True),
               (0x47, "Main menu background", "the main menu 0x447420 (0x447435)", True),
               (0x4F, "Collection background", "the collection screen 0x437290 (0x4372AD)", True),
               (0x51, "Dating background", "the dating screen 0x4380F0 (0x438108)", True),
               (0x57, "Villager details background", "the villager screen 0x44B890 (0x44B8A5)", True),
               (0x58, "Store background", "the store screen 0x448C10 (0x448C66)", True),
               (0xC0, "Family tree background", "the family tree screen 0x43A1B0 (0x43A1DC)", True))
    for image, words, where, emulated in screens:
        name = ga.TABLE[image][0]
        if _size(files, name):
            add(f"screens/{image:02x}", SCREEN, words, [ga.whole(name)], True, f"Drawn whole by {where}.",
                f"{EMU} at its call site run in Unicorn." if emulated else
                f"{EMU} 0x440A30..0x440A5B run in Unicorn.")
    if _size(files, "SPLASH_BG.jpg"):
        add("screens/splash", SCREEN, "Splash screen", [ga.whole("SPLASH_BG.jpg")], True,
            "Loaded by name (0x448569) and drawn at (0, 0) by the splash screen 0x448860 when the LDW flash intro is "
            "not played: ForceStaticSplash is set, Windows 2000, or the intro does not start (0x448A30).",
            f"{EMU} 0x448860 run in Unicorn.")
    for name, site in (("SPLASH1_BG.JPG", "0x4485BC"), ("SPLASH2_BG.JPG", "0x448603"), ("SPLASH3_BG.JPG", "0x44864A")):
        add(f"screens/{name[:-4].lower()}", SCREEN, f"Extra splash picture {name[6]}",
            [ga.whole(name)] if _size(files, name) else [], False,
            f"Loaded by name only when the file exists ({site}); the game ships without {name}.")
    unused_table = (
        (0x3C, "Overview map background", "No code asks for picture 0x3C (overview_bg.jpg); the file is missing from "
         "the game too."),
        (0x50, "Collection photo glass", "No code asks for picture 0x50 (collection_photo-glass.jpg, missing; the "
         "folder's collection_photo-glass.png is never opened by name either)."),
        (0xBA, "Wedding picture", "No code asks for picture 0xBA: the story player's pictures are only added by "
         "0x44D170, which only the intro pages' set-up 0x44C8E0 calls, and no code builds an intro page."),
        (0xBB, "Birth picture", "No code asks for picture 0xBB (see the wedding picture: the story player 0x44D170 "
         "is only filled by the never-built intro pages)."),
        (0xBC, "College picture", "No code asks for picture 0xBC (the story player 0x44D170 is only filled by the "
         "never-built intro pages)."),
        (0xBD, "Promotion picture", "No code asks for picture 0xBD (the story player 0x44D170 is only filled by the "
         "never-built intro pages)."),
        (0xBE, "Death picture", "No code asks for picture 0xBE (the story player 0x44D170 is only filled by the "
         "never-built intro pages)."),
        (0x43, "Intro hill", "Only the intro pages' set-up 0x44C8E0 adds picture 0x43 (0x44C9AE, 0x44CC19), and no "
         "code builds an intro page (CIntroPage1..3, vtables 0x4B92AC..0x4B92EC, are never stored)."),
        (0x44, "Intro house", "Only the intro pages' set-up 0x44C8E0 adds picture 0x44 (0x44CC2B), and no code "
         "builds an intro page (vtables 0x4B92AC..0x4B92EC are never stored)."),
    )
    for image, words, why in unused_table:
        name = ga.TABLE[image][0]
        if image == 0x50:
            name = "collection_photo-glass.png"
        add(f"screens/{image:02x}", SCREEN, words, [ga.whole(name)] if _size(files, name) else [], False, why)
    nobody = "No string in the game names it; the only picture names the game builds are the map tiles " \
             "(%sX%01dY%01d.jpg, 0x4D7A0C) and the two-file head sheets."
    for name, words in (("help1.jpg", "Help page 1"), ("help2.jpg", "Help page 2"), ("help3.jpg", "Help page 3"),
                        ("help4.jpg", "Help page 4"), ("credits.jpg", "Credits"),
                        ("DRM/virtualfamilies_drm.jpg", "Trial screen picture"),
                        ("DRM/logo1.gif", "Trial screen logo")):
        if files.has(name):
            add(f"screens/{name.lower().replace('/', '-')[:-4]}", SCREEN, words, [ga.whole(name)], False, nobody)
    scanned = "Checked by a scan of every picture-loader call in the game's code for the image number it is given."
    return [ga.Art(a.key, a.category, a.label, a.layers, a.used, a.why, scanned) if a.key in SCANNED else a
            for a in out]


# the unused pictures whose "no code asks for it" the test's scan of every loader call checks
SCANNED = {"ui/buttons/29/normal", "ui/buttons/29/over", "ui/buttons/29/pressed", "ui/toggles/checkmark",
           "ui/logos/logo1", "ui/logos/small", "ui/screens/3c", "ui/screens/50", "ui/screens/ba", "ui/screens/bb",
           "ui/screens/bc", "ui/screens/bd", "ui/screens/be"}


# ------------------------------------------------------------------ per-sheet notes
USAGE = {
    **{image: (True, f"Buttons on {where} ({sites}), drawn by 0x4011D0.") for image, (_l, where, sites)
       in BUTTONS.items()},
    0x29: (False, UNUSED_BUTTONS[0x29][1]),
    0x01: (True, "The mouse pointer (set at 0x444089 and on mouse up 0x445A22), drawn by 0x409376."),
    0x02: (True, "The mouse pointer while the mouse button is held down (0x446310), drawn by 0x409376."),
    0x2C: (True, "The orange dialog backdrop (style 2, 0x44F5CC; the Banking dialog 0x4157EC)."),
    0x2D: (True, "The green dialog backdrop (0x44F5BE; most dialogs and the achievement pop-up 0x412D9B)."),
    0x2E: (True, "The e-mail dialog backdrop (style 1, 0x44F5DA; island events that are e-mails 0x41AEDE)."),
    0x31: (True, "Radio buttons on the animation-alignment editor screen only (0x43E6FE, 0x43E762)."),
    0x32: (True, "The Options dialog's unpicked choice (0x41D44D, drawn by 0x41D9C0)."),
    0x33: (True, "The Options dialog's picked choice (0x41D456, drawn by 0x41D9C0)."),
    0x34: (True, "The Options dialog's check boxes (0x41D46B, drawn by 0x40BC40)."),
    0x35: (False, "No code asks for picture 0x35."),
    0x36: (True, "The Options dialog's volume slider track (0x41D47A, drawn at 0x41DDBB / 0x41DE05)."),
    0x37: (True, "The Options dialog's volume slider handle (0x41D489, drawn at 0x41DDE2 / 0x41DE2C)."),
    0x3B: (True, "The selected villager's ring (0x4898C8, drawn by 0x44EC30 from 0x48B757)."),
    0x3C: (False, "No code asks for picture 0x3C; the file is missing from the game too."),
    0x3D: (True, "The achievements screen's background (0x435387)."),
    0x3F: (True, "The loading screen (0x4406EB)."),
    0x40: (True, "The LDW logo on the loading screen (0x440730)."),
    0x41: (False, "No code asks for picture 0x41."),
    0x42: (False, "No code asks for picture 0x42; the file is missing from the game too."),
    0x43: (False, "Only the never-built intro pages (0x44C8E0) use picture 0x43."),
    0x44: (False, "Only the never-built intro pages (0x44C8E0) use picture 0x44."),
    0x45: (True, "The house screen's background (0x44404E, drawn at 0x440A56)."),
    0x46: (True, "The help page (0x440107, 0x440143)."),
    0x47: (True, "The main menu's background (0x447435)."),
    0x49: (True, "The tip dialog's up arrow (0x41EE31)."),
    0x4A: (True, "The tip dialog's down arrow (0x41EE74)."),
    0x4B: (True, "The tip dialog's left arrow (0x41EEC1)."),
    0x4C: (True, "The tip dialog's right arrow (0x41EEE0)."),
    0x4F: (True, "The collection screen's background (0x4372AD)."),
    0x50: (False, "No code asks for picture 0x50 (collection_photo-glass.jpg is missing; the .png is never opened)."),
    0x51: (True, "The dating screen's background (0x438108)."),
    0x57: (True, "The villager details screen's background (0x44B8A5)."),
    0x58: (True, "The store screen's background (0x448C66)."),
    0x5A: (True, "The adoption screen's background (0x43633F)."),
    0x6C: (True, "The small e-mail animation (anim 31 of 0x4EB370, played at 0x44510A / 0x44512A)."),
    0x6D: (True, "The big e-mail animation (anim 32 of 0x4EB370, played at 0x4450EC)."),
    **{image: (False, "No code asks for this picture: the story player 0x44D170 is only filled by the never-built "
                      "intro pages (0x44C8E0).") for image in (0xBA, 0xBB, 0xBC, 0xBD, 0xBE)},
    0xC0: (True, "The family tree screen's background (0x43A1DC)."),
    0xC1: (True, "The family tree's parent frame (0x439C4D, 0x439D90)."),
    0xC2: (True, "The family tree's child frame (0x439F16)."),
    0xC3: (True, "The scroll knob's top (0x43543B, 0x43A2CE, 0x44017C)."),
    0xC4: (True, "The scroll knob's middle (0x43544D, 0x43A2DC, 0x44018E)."),
    0xC5: (True, "The scroll knob's bottom (0x43545D, 0x43A2EC, 0x44019E)."),
    0xC6: (True, "The family tree's scroll bar track (0x43A2C2)."),
    0xC9: (True, "The achievements and help screens' scroll bar track (0x43542F, 0x440170)."),
    0xCA: (True, "An achievement row not yet earned (0x412E1E)."),
    0xCB: (True, "An earned achievement row (0x412E1E)."),
    0xCD: (True, "The bottom bar of the achievements, family tree, help and store screens (0x435504)."),
    0xD1: (True, "The store's red check mark (0x448E5C)."),
    0xD3: (True, "The store's on-sale tag (0x448E16)."),
}

CELL_LABELS = {
    **{(image, state): words for image in list(BUTTONS) + list(UNUSED_BUTTONS) for state, _s, words in STATES},
    **{(image, cell): words for image in GRIDS for cell, words in TILE_CELLS.items()},
    (0x31, 0): "Not picked", (0x31, 1): "Picked",
    (0x34, 0): "Not ticked", (0x34, 1): "Ticked",
    (0x6C, 0): "Frame 1", (0x6C, 1): "Frame 2",
    (0x6D, 0): "Frame 1", (0x6D, 1): "Frame 2",
}

CELL_UNUSED = {(0x29, state): UNUSED_BUTTONS[0x29][1] for state in range(3)}
