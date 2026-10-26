"""The Family Tree Maker (the interactive family tree editor) for Virtual Families 1.

A port of the Virtual Villagers Fun Patcher's editor (src/vv_genealogy_window.py, main ede00e7e): the same canvas,
panels, toolbar, shortcuts, hover tips, marks, descriptors, text boxes, per-group settings, pages, export and
.tree files.  Not ported: the Village Matchmaker, numbering names in the save, the Heathens and "started over"
filters and the renamed-villager questions (Virtual Villagers only).  Nothing here writes the save: the tree's
edits and .tree file go to Virtual Families 1 Patcher\\Save <N>\\Data\\Family Tree beside it.

The Virtual Villagers description, which still holds:

The owner (2026-10-07): "make the family tree editor interactive and offer to send a png/jpg file
to whatever place the player wants"; "support shift click, ctrl click, ctrl a"; "there should be
a continuous color picker for everything ... You can also enter rgb or hex codes"; "add the
option for custom backgrounds or preset backgrounds"; "get rid of the pairings on the family
tree.  there should be a separate button for pairing suggestions".

* The editor draws the tree (src/vf1_family_tree.py's scene) on a canvas.  Click a family member to
  select them; Ctrl+click adds or removes one, Shift+click selects the run from the last one
  clicked, Ctrl+A selects everyone, dragging over empty space selects everyone in the box, Esc
  clears.  The panel beside it edits the selection (its lines, its mark, its family's colour) and
  the whole tree (marks, title, generation labels, sort, colours, background).  Every change is
  drawn again and saved with Save to Save Folder (Ctrl+S): the editable tree file and the family's
  edits file; closing asks "Save changes to the tree before exiting?".
* Export as Picture... writes a PNG or JPG anywhere the player chooses (src/vf1_gdiplus.py).
"""
from __future__ import annotations

import json
import os
from fractions import Fraction
import re
from datetime import datetime
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from tkinter import colorchooser, filedialog, font as tkfont, messagebox, simpledialog, ttk

import vf1_family_tree as ft
import vf1_gdiplus
import vf1_genealogy as gen
import vf1_line_colours
import vf1_member_info
import vf1_save
import vf1_save_backup as save_backup
import vf1_tree_memory
from vf1_tree_editor_tools import BOLD_ROLES, CanvasTools, ScrollingTab, picture_scene, panel_colour, scrollable_frame, tool_text

SELECT = "#1f6fd1"
OUTSIDE = "#9a9a9a"                     # the canvas around the page
TREES = ft.TREES                        # the folder in the save folder the tree files go to
_WRITING: list = []                     # the tree outputs being written in the background (_write_outputs)


def faded(colour: str, opacity: float, under: str) -> str:
    """A colour as it looks `opacity` opaque over `under` (the canvas cannot blend: the saved
    picture is truly see-through)."""
    if opacity >= 1 or not ft.is_colour(colour) or colour == ft.TRANSPARENT:
        return colour
    under = under if ft.is_colour(under) and under != ft.TRANSPARENT else "#ffffff"
    mix = [round(int(colour[i:i + 2], 16) * opacity + int(under[i:i + 2], 16) * (1 - opacity)) for i in (1, 3, 5)]
    return "#" + "".join(f"{v:02x}" for v in mix)


def tk_colour(colour: str, otherwise: str = "") -> str:
    """A colour for tkinter, which knows no "transparent": nothing drawn (or `otherwise`)."""
    return otherwise if colour == ft.TRANSPARENT else colour


# ---- hover tips --------------------------------------------------------------------------------------------
# The owner: "TOOLTIP all labels and text that could be cut off!"  Every label, button, tick box, choice,
# list box and typing box in a Family Tree Maker window (the editor and every window it opens) shows, when
# the mouse rests on it, its full words if they are cut off at its present width -- and its shortcut key, if
# `tip` gave it one, always.  Bound once to the widget CLASSES, so a widget made later (a tab, a dialog)
# has it without being walked.
TIP_CLASSES = ("TLabel", "Label", "TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton",
               "Radiobutton", "TMenubutton", "Menubutton", "TCombobox", "TEntry", "Entry", "TSpinbox", "Spinbox")
TIP_DELAY = 500                         # ms the mouse rests before a tip shows
_TIP: dict = {"win": None, "over": None, "job": None}


def tip(widget, text: str) -> None:
    """`widget`'s shortcut key (or other short help), shown in its hover tip (where a longer label would
    crowd the toolbar)."""
    widget.tip_text = text
    install_tips(widget)


def install_tips(widget) -> None:
    """The hover tips, once for `widget`'s whole application."""
    root = widget._root()
    if getattr(root, "_tree_tips", False):
        return
    root._tree_tips = True
    for cls in TIP_CLASSES:
        root.bind_class(cls, "<Enter>", _tip_enter, add="+")
        root.bind_class(cls, "<Leave>", _tip_hide, add="+")
        root.bind_class(cls, "<ButtonPress>", _tip_hide, add="+")


def _in_tree_window(widget) -> bool:
    """`widget` is in the Family Tree Maker or a window it opened (the patcher's own windows are left alone)."""
    try:
        w = widget.winfo_toplevel()
    except (tk.TclError, AttributeError):
        return False
    while w is not None:
        if getattr(w, "tree_tips", False):
            return True
        w = getattr(w, "master", None)
    return False


def _words(widget) -> str:
    """The words `widget` shows."""
    try:
        if widget.winfo_class() in ("TCombobox", "TEntry", "Entry", "TSpinbox", "Spinbox"):
            return str(widget.get())
        var = str(widget.cget("textvariable") or "")
        return str(widget.getvar(var)) if var else str(widget.cget("text"))
    except (tk.TclError, AttributeError):
        return ""


def _font(widget):
    try:
        name = str(widget.cget("font") or "")
    except tk.TclError:
        name = ""
    if not name:
        try:
            name = str(ttk.Style(widget).lookup(widget.winfo_class(), "font") or "")
        except tk.TclError:
            name = ""
    try:
        return tkfont.nametofont(name or "TkDefaultFont", root=widget)
    except (tk.TclError, RuntimeError):
        return tkfont.Font(root=widget, font=name or "TkDefaultFont")


def is_cut_off(widget) -> bool:
    """`widget`'s words do not all show at its present size."""
    words = _words(widget)
    if not words.strip():
        return False
    try:
        if widget.winfo_class() in ("TCombobox", "TEntry", "Entry", "TSpinbox", "Spinbox"):
            room = widget.winfo_width() - (26 if widget.winfo_class() in ("TCombobox", "TSpinbox", "Spinbox")
                                           else 8)
            return _font(widget).measure(words) > room or clipped(widget)
        if (widget.winfo_width() < widget.winfo_reqwidth() - 1
                or widget.winfo_height() < widget.winfo_reqheight() - 1):
            return True
    except tk.TclError:
        return False
    return clipped(widget)


def clipped(widget) -> bool:
    """`widget` runs past the right edge of a frame (or window) it is in, so its end is hidden."""
    try:
        right = widget.winfo_rootx() + widget.winfo_width()
        w = widget.master
        while w is not None:
            if w.winfo_rootx() + w.winfo_width() < right - 1:
                return True
            if w.winfo_class() in ("Toplevel", "Tk"):
                break
            w = w.master
    except (tk.TclError, AttributeError):
        pass
    return False


def tip_words(widget) -> str:
    """What `widget`'s hover tip says: its full words when they are cut off, and its shortcut; "" for none."""
    lines = []
    if is_cut_off(widget):
        lines.append(_words(widget))
    extra = getattr(widget, "tip_text", "")
    if extra and extra not in lines:
        lines.append(extra)
    return "\n".join(lines)


def _tip_enter(event) -> None:
    widget = event.widget
    if isinstance(widget, str) or not _in_tree_window(widget):
        return
    _tip_hide()
    _TIP["over"] = widget
    _TIP["job"] = widget.after(TIP_DELAY, lambda: show_tip(widget))


def show_tip(widget) -> None:
    """The hover tip under `widget`, if it has anything to say and the mouse is still on it."""
    _TIP["job"] = None
    if _TIP["over"] is not widget:
        return
    try:
        words = tip_words(widget)
        if not words or not widget.winfo_exists():
            return
        win = tk.Toplevel(widget)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 2}")
        tk.Label(win, text=words, justify="left", background="#ffffe1", foreground="#000000", relief="solid",
                 borderwidth=1, padx=4, pady=1, wraplength=max(300, widget.winfo_screenwidth() // 2)).pack()
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        _TIP["win"] = win
    except tk.TclError:
        pass


def _tip_hide(_event=None) -> None:
    over, job, win = _TIP["over"], _TIP["job"], _TIP["win"]
    _TIP.update(over=None, job=None, win=None)
    try:
        if job is not None and over is not None:
            over.after_cancel(job)
    except tk.TclError:
        pass
    try:
        if win is not None:
            win.destroy()
    except tk.TclError:
        pass


WRAP_MIN = 220                          # a wrapping hint narrower than this goes onto its own line


def flow_row(frame, natural: bool = True) -> None:
    """Lay the widgets packed (side="left") in `frame` out like words in a paragraph: along a line while they
    fit, then onto the next line -- so a toolbar never squeezes or cuts off its last controls when the window
    is narrow or the display scaled (the owner: the Hide panel button was squeezed to a sliver).  Each keeps
    its pack padx; a fill="y" one (a separator) is as tall as its line; a Label with `flow_wrap` set wraps
    its words to the rest of its line.  The frame asks for the width of everything on one line (`natural`),
    or only of its widest widget -- for one its parent stretches (fill="x", sticky="ew") that must not
    widen the parent itself."""
    items = []
    for w in frame.pack_slaves():
        info = w.pack_info()
        pad = info.get("padx", 0)
        pad = [int(float(p)) for p in (pad if isinstance(pad, (tuple, list)) else str(pad).split())] or [0]
        items.append((w, pad[0], pad[-1], info.get("fill") in ("y", "both")))
        w.pack_forget()
    seen = {"height": None}

    def lay(_e=None) -> None:
        width = frame.winfo_width()
        if width <= 1 or not frame.winfo_exists():
            return
        lines, line, x = [], [], 0
        for w, before, after, stretch in items:
            gap = before if line else 0
            if getattr(w, "flow_wrap", False):
                room = width - x - gap - after
                if line and room < WRAP_MIN:
                    lines.append(line)
                    line, x, gap = [], 0, 0
                    room = width - after
                room = max(60, room)
                if int(float(str(w.cget("wraplength") or 0))) != room - 6:      # its padding: room to spare
                    w.configure(wraplength=room - 6)
                line.append((w, x + gap, room, stretch))
                x += gap + room + after
                continue
            need = w.winfo_reqwidth()
            if line and x + gap + need > width:
                lines.append(line)
                line, x, gap = [], 0, 0
            if stretch and not line:            # no separator at the start of a line
                w.place_forget()
                continue
            # Never wider than the line (a row of its own, like a colour field, wraps inside it then).
            line.append((w, x + gap, None if stretch else min(need, width), stretch))
            x += gap + need + after
        if line:
            lines.append(line)
        y = 0
        for line in lines:
            while line and line[-1][3]:         # ... or at its end
                line.pop()[0].place_forget()
            if not line:
                continue
            tall = max([w.winfo_reqheight() for w, _x, _wd, stretch in line if not stretch] or [20])
            for w, left, wide, stretch in line:
                if stretch:
                    w.place(x=left, y=y, height=tall)
                else:
                    w.place(x=left, y=y + max(0, tall - w.winfo_reqheight()) // 2, width=wide)
            y += tall + 2
        height = max(1, y - 2)
        if seen["height"] != height:
            seen["height"] = height
            frame.configure(height=height)
        ask_width()

    def ask_width() -> None:
        """The frame asks for the width of everything on one line (it is given less when there is less)."""
        sizes = [(WRAP_MIN if getattr(w, "flow_wrap", False) else w.winfo_reqwidth()) + before + after
                 for w, before, after, stretch in items]
        wide = sum(sizes) if natural else max(sizes or [1])
        if seen.get("width") != wide:
            seen["width"] = wide
            frame.configure(width=max(1, wide))

    frame.bind("<Configure>", lay, add="+")
    for w, *_ in items:          # a wrapped hint's height (or a relabelled button's width) changes: lay again
        w.bind("<Configure>", lambda _e: frame.after_idle(lay), add="+")
    frame.configure(height=max([w.winfo_reqheight() for w, *_ in items] or [1]))
    ask_width()
    frame.flow_lay = lay
GUIDE = "#e0218a"                       # a smart guide while dragging
GRID_SIZES = ("10", "20", "40", "80")
SNAP_REACH = 7                          # screen pixels: how near a guide pulls
ALT = 0x20000                           # Alt held: place freely
# Ready-made special marks (the owner asked for marks "eg Tribal Chief"); any other can be typed.
CUSTOM_MARK = "Custom (type here...)"
EVERYONE = "Everyone"                   # the "Settings for:" pickers: every portrait, else one group's
# The editable tree file Save to Save Folder writes (the owner: "an editable file to be worked on later").
TREE_SUFFIX = ft.TREE_SUFFIX
TREE_FORMAT = ft.TREE_FORMAT
PRESET_MARKS = {"Founder": "#2e8b57", "Heir": "#d4a017", "Married in": "#7b68ee", "Adopted": "#1e90ff",
                "Twins": "#ffb000", "Favourite": "#ff1493", "Left home": "#8b5a2b"}
# Every special status the tree marks by itself (ft.STATUS_COLOURS) is a ready-made mark too, in its colour.
PRESET_MARKS.update({label: colour for label, colour in ft.STATUS_COLOURS.items() if label not in PRESET_MARKS})
CONTROLS = """\
SELECTING
  Click a family member                select them
  Ctrl+click                      add or remove one
  Shift+click                     select everyone from the last one clicked
  Ctrl+A                          select everyone
  Shift+drag (or Ctrl+drag)       a box: select everyone in it
  Esc                             select nothing

MOVING AND ZOOMING
  Drag anything                   move it: family members (every selected one together; their lines
                                  follow), the title, subtitle, Key, generation labels, the
                                  Other Members heading, the footer, pictures, text boxes
  Drag empty space                move around the tree (or drag with the middle button)
  Mouse wheel, or + and -         zoom in and out (Ctrl+0: 100%)
  Shift+wheel / Alt+wheel         scroll sideways / up and down
  Fit                             the whole tree's width in the window

COLOURS
  Right-click anything            change its colour: a family member (and their full brothers and
                                  sisters), a family's lines, a mark, any words, the background
                                  -- or put it back in its own place
  Right-click one of several      the colour of every selected family member at once
  selected family members

GENERATIONS AND ORDER (Selected tab)
  Move to generation              the selected family members into the generation you choose
  Reset                           back to the generation the records give
  Move left / Move right          one place along their generation (the numbers follow)

LINING THINGS UP (the toolbar)
  Smart guides                    while dragging, snap to other family members' and pictures' edges and
                                  middles, and the middle of the tree (a pink line shows it)
  Snap to grid                    while dragging, snap to the grid (10, 20, 40 or 80); Show grid
  Allow diagonal lines            a dragged line may move any way (off: only across itself, so
                                  every line stays square)
  Alt while dragging              no snapping; a line let go with Alt held stays exactly there (without
                                  Alt it is nudged to keep a pixel from any line it would lie on)
  Align                           line up the selected family members (lefts, centres, rights, tops,
                                  middles, bottoms), centre them on the tree, or space them evenly

LINES
  Drag a piece of a line          move it (the pieces joined to it follow and it stays on the
                                  portraits it touches); across itself only, unless Allow diagonal
                                  lines is ticked
  Right-click it                  Reset this line, or Delete this line
  Layout tab, Family lines   every line's weight and type (solid, dotted, dashed)
  Selected tab          the selected family members' family's lines: weight and type

PORTRAITS
  Click one family member              circles round the portrait: drag a corner to resize it (Keep
                                  aspect ratio ticked: keeps its shape; Shift: the other way), a
                                  side to stretch it, the curved arrow on top to turn it (Shift:
                                  steps of 15 degrees)
  Selected tab, "Their  shape, border, and the size of every selected family member (Keep
  portrait shape..."              aspect ratio ticked: the other side follows); Reset size and turn;
                                  their inside and detail colours; flip and turn
  Selected tab, "Their  their own face size and text size, and their words
  face and words"
  Shapes tab, Flip and   every portrait of a group flipped or turned at once (Ctrl+Z undoes;
  turn (by group)                 Reset puts them back); each family member can still be changed alone
  Shapes tab             each group's shape, border and size (Keep aspect ratio as above;
                                  a group's size resizes everyone in it); the inside colour;
                                  rainbow or alternating colours for borders, insides, detail lines,
                                  family lines and marks; detail lines; rope and vine colours
  Faces & Text tab                text left / centre / right, the face and text at the top /
                                  middle / bottom; the text area; picture and text size; ages in
                                  units / years; twins and triplets; "Founder"; the text colour;
                                  numbered names; a box behind the words and its border (any
                                  portrait border, the rope and vines too; weight 0: none)
  "Settings for:"                 Everyone, or one group (Males, Females, Babies on the way) to give
                                  its own faces, words, detail lines and inside colour; "Same as
                                  everyone" / "Make every group the same" clear them (Ctrl+Z undoes)
  Layout tab                      the title; the order and layout (Packed families / Packed
                                  generations, and how tightly packed), rows to the left / centre /
                                  right, portraits lined up by their tops / middles / bottoms; the
                                  most portraits in a row (a long generation wraps into more rows);
                                  Other Members in columns, on the left or right;
                                  spacing; family lines; generation labels; opacity; page size;
                                  pages; deleted items
  Marks tab               every mark as a border or a glow, its size and opacity
  The size and weight boxes       change the tree as you type or click the arrows

ADDING AND DELETING
  Right-click empty space         Add here: a text box, a picture, a rectangle, an oval, a logo
  Right-click anything            Delete it: a family member, a line, the title, a generation label or
                                  one line of it (the number, the name, the totals...) here or from
                                  every generation
  Layout tab, Deleted items  Restore what was deleted

PAGES (Layout tab)
  A new page starts at generation split a long family onto pages; a page ends with the generation
                                  the next one starts at, which that page shows again at its top, as
                                  its first family members (no lines up to their parents).  Pick the page
                                  on the toolbar.
                                  Saving a picture saves every page.

NUMBERS
  Layout tab                 Roman numerals or numbers for the generations
  Faces & Text tab                Renumber edited portraits
  Number duplicate names          namesakes numbered, in order of appearance (Soda I, Soda II...); it offers
  (Faces & Text tab, Tools menu)  to number them in the game's save and logs too

PICTURES AND TEXT BOXES (Pictures tab)
  Drag its middle                 move it                 Arrow keys      nudge it (Shift: by 10)
  Drag a corner circle            resize (Keep aspect ratio ticked: keeps its shape; Shift: the other way)
  Drag a side circle              stretch one side
  Drag the curved arrow           rotate it (Shift: in steps of 15 degrees)
  Double-click a text box, or F2  type in it
  Click (or double-click) words   retype them where they are: the title, subtitle, a portrait, a
                                  generation label, "Other Members", the footer, a mark in
                                  the Key (Enter keeps them; Ctrl+Enter for several lines; Esc)
  Ctrl+B / Ctrl+I / Ctrl+U        bold / italic / underline the selected text box
  Right-click any words           bold, italic, underline, strikethrough, superscript, subscript
                                  (every word of that kind: every name, every label...)
  Selected tab, "Their  select some words (a line, a word, part of a word), then the
  face and words"                 B I U S x² x₂ Colour buttons, a right click on them, or Ctrl+B /
                                  Ctrl+I / Ctrl+U format just those words (Plain takes it off);
                                  Save text puts them on the tree, Reset text the patcher's own
  Right-click it                  cut, copy, duplicate, delete, bring forward / to the front, send
                                  backward / to the back, rotate 90, reset proportions, reset to
                                  default
  Ctrl+] / Ctrl+[                 bring forward / send backward (with Shift: to the front / back)
  Delete                          remove it

EVERYWHERE
  Ctrl+C / Ctrl+X / Ctrl+V        copy, cut, paste (a picture or file copied anywhere, or words,
                                  which become a text box)
  Ctrl+D                          duplicate        Ctrl+Z / Ctrl+Y      undo / redo (and the buttons)
  Reset buttons (under every tab) Reset Portrait Shapes, Portrait Places, Lines, Everything --
                                  each asks first
  Ctrl+S                          Save to Save Folder: the editable tree file, in the save folder's
                                  Virtual Families 1 Patcher Family Trees folder (File, Open Tree
                                  File... opens one); closing asks whether to save changes
  Ctrl+Shift+S                    Export as Picture: a PNG or JPG anywhere (every page)
  F5                              Update Family Tree from the Save (every edit kept)
  F1                              these controls   F4  hide or show the panel   F11  full screen
                                  (Help, Full screen and Hide panel: the right end of the Find row)
  Ctrl+F                          Find a family member (the row under the toolbar)
"""
# How far the tree can be zoomed, and for each how the canvas scales a head (tkinter scales a
# picture only by whole numbers: up by the first, then down by the second).  A head is drawn at
# 4/3 of its size, so each zoom's head scale is 4/3 of it.
ZOOMS = {0.25: (1, 3), 0.5: (2, 3), 0.75: (1, 1), 1.0: (4, 3), 1.25: (5, 3), 1.5: (2, 1), 2.0: (8, 3),
         3.0: (4, 1), 4.0: (16, 3)}
# The Portrait text box's formatting (what, its button, the button's font): the selected words only.
TEXT_FORMATS = (("bold", "B", ("Segoe UI", 9, "bold")), ("italic", "I", ("Segoe UI", 9, "italic")),
                ("underline", "U", ("Segoe UI", 9, "underline")), ("strike", "S", ("Segoe UI", 9, "overstrike")),
                ("super", "x²", ("Segoe UI", 9)), ("sub", "x₂", ("Segoe UI", 9)),
                ("colour", "Colour", ("Segoe UI", 9)), ("plain", "Plain", ("Segoe UI", 9)))
FORMAT_NAMES = {"bold": "Bold", "italic": "Italic", "underline": "Underline", "strike": "Strikethrough",
                "super": "Superscript", "sub": "Subscript", "colour": "Colour...", "plain": "Remove formatting"}
FX = "fx:"                              # a Portrait text tag holding one setting: "fx:bold:1", "fx:colour:#..."
LOOK = "look:"                          # a Portrait text tag drawing the words as their settings say


# ---------------------------------------------------------------------------
# Picking a village
# ---------------------------------------------------------------------------

def _master(app):
    """The patcher window's Tk root (the Virtual Families 1 patcher window is not itself a widget)."""
    return getattr(app, "root", app)


def slot_families(folder: Path) -> list[SimpleNamespace]:
    """The five save slots of a save folder: (slot, name -- None for an empty or unreadable slot --, label)."""
    out = []
    for slot in range(1, 6):
        path = gen.save_path(folder, slot)
        name, label = None, f"Save {slot}: (empty)"
        if path.is_file():
            try:
                save = vf1_save.read_save(path)
                name = save.family_name or f"Save {slot}"
                label = f"Save {slot}: {name} ({save.generation} generation{'' if save.generation == 1 else 's'})"
            except (OSError, vf1_save.SaveFormatError, ValueError, IndexError) as exc:
                label = f"Save {slot}: cannot be read ({exc})"
        out.append(SimpleNamespace(slot=slot, name=name, label=label))
    return out


def images_folder(game_folder: str | Path | None) -> Path | None:
    """The game folder's Images (the head sprites), or None."""
    text = str(game_folder or "").strip()
    if not text:
        return None
    path = Path(text)
    if (path / "Images").is_dir():
        return path / "Images"
    return path if path.name.lower() == "images" and path.is_dir() else None


def _guess_game_folder(app) -> str:
    """The game folder the patcher already knows: the modded output folder, else the vanilla game folder."""
    for name in ("output_dir_var", "game_dir_var"):
        var = getattr(app, name, None)
        try:
            text = var.get().strip() if var is not None else ""
        except Exception:               # a closed window's variable
            text = ""
        if text and images_folder(text) is not None:
            return text
    return ""


def pick_village(app, build, title: str, intro: str, go_text: str, on_go, ask_game_folder: bool,
                 folders: list[Path] | None = None) -> tk.Toplevel | None:
    """A save folder and a family (and the game folder the faces come from), then
    on_go(dialog, folder, game number, slot info, game title, images or None)."""
    master = _master(app)
    if folders is None:
        documents = save_backup.documents_folder()
        if documents is None:
            messagebox.showerror(title, "Windows did not report where your Documents folder is, so the "
                                        "save folders cannot be found.", parent=master)
            return None
        folders = save_backup.find_save_folders(documents)
        stock = documents / "LDW" / "Virtual Families"       # the unmodded game's own saves can be drawn too
        if stock.is_dir() and stock not in folders:
            folders.append(stock)
    dialog = tk.Toplevel(master)
    dialog.title(title)
    dialog.transient(master)
    frame = scrollable_frame(dialog, padding=16)
    ttk.Label(frame, text=intro, wraplength=560, justify="left").grid(row=0, column=0, columnspan=3,
                                                                       sticky="w", pady=(0, 10))
    folder_var = tk.StringVar()
    images_var = tk.StringVar(value=_guess_game_folder(app))
    problem_var = tk.StringVar()
    state: dict = {"folders": list(folders), "slots": []}
    ttk.Label(frame, text="Save folder:").grid(row=1, column=0, sticky="w")
    folder_box = ttk.Combobox(frame, textvariable=folder_var, state="readonly", width=48,
                              values=[f.name for f in state["folders"]])
    folder_box.grid(row=1, column=1, sticky="we", pady=2)

    def browse_saves() -> None:
        chosen = filedialog.askdirectory(parent=dialog, title="A Virtual Families save folder (Documents\\LDW\\...)")
        if chosen:
            state["folders"].append(Path(chosen))
            folder_box.configure(values=[f.name for f in state["folders"]])
            folder_box.current(len(state["folders"]) - 1)
            load_slots()

    ttk.Button(frame, text="Other...", command=browse_saves).grid(row=1, column=2, padx=(6, 0))
    ttk.Label(frame, text="Family:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
    slot_list = tk.Listbox(frame, height=5, width=60, exportselection=False)
    slot_list.grid(row=2, column=1, columnspan=2, sticky="we", pady=(4, 2))
    row = 3
    if ask_game_folder:
        ttk.Label(frame, text="Game folder (for the faces):").grid(row=row, column=0, sticky="w")
        ttk.Entry(frame, textvariable=images_var, width=48).grid(row=row, column=1, sticky="we", pady=2)

        def browse() -> None:
            chosen = filedialog.askdirectory(parent=dialog, title="The game's folder (the one with Images in it)",
                                             initialdir=images_var.get() or str(Path.home()))
            if chosen:
                images_var.set(chosen)
                refresh()

        ttk.Button(frame, text="Choose...", command=browse).grid(row=row, column=2, padx=(6, 0))
        row += 1
    ttk.Label(frame, textvariable=problem_var, foreground="#a01010", wraplength=560,
              justify="left").grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))
    buttons = ttk.Frame(frame)
    buttons.grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(12, 0))
    go_button = ttk.Button(buttons, text=go_text)
    go_button.pack(side="left")
    ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left", padx=(8, 0))

    def chosen():
        picked = slot_list.curselection()
        if not picked or not state["folders"]:
            return None
        info = state["slots"][picked[0]]
        return info if info.name is not None else None

    def images() -> Path | None:
        return images_folder(images_var.get())

    def refresh(*_args) -> None:
        problem = None
        if not state["folders"]:
            problem = "No save folder was found. Choose one with Other... (Documents\\LDW\\<the game's name>)."
        elif chosen() is None:
            problem = "Choose a family."
        elif ask_game_folder and images() is None:
            problem_var.set("The faces are drawn from the game folder's Images; without it each "
                            "family member shows their initial.")
            go_button.configure(state="normal")
            return
        problem_var.set(problem or "")
        go_button.configure(state="normal" if problem is None else "disabled")

    def load_slots(*_args) -> None:
        slot_list.delete(0, "end")
        state["slots"] = []
        index = folder_box.current()
        if 0 <= index < len(state["folders"]):
            state["slots"] = slot_families(state["folders"][index])
            for info in state["slots"]:
                slot_list.insert("end", info.label)
            first = next((n for n, info in enumerate(state["slots"]) if info.name is not None), None)
            if first is not None:
                slot_list.selection_set(first)
        refresh()

    def start() -> None:
        info = chosen()
        if info is None:
            return
        on_go(dialog, state["folders"][folder_box.current()], gen.GAME, info, gen.GAME_TITLE, images())

    go_button.configure(command=start)
    # Kept with the dialog: a StringVar no longer referenced is deleted, which empties the Save folder box, and
    # then folder_box.current() is -1 and Open would take the LAST folder in the list, not the one chosen.
    dialog._folder_var = folder_var
    folder_box.bind("<<ComboboxSelected>>", load_slots)
    slot_list.bind("<<ListboxSelect>>", refresh)
    images_var.trace_add("write", lambda *_a: refresh())
    frame.columnconfigure(1, weight=1)
    if state["folders"]:
        folder_box.current(0)
    load_slots()
    dialog._vf1_start = start               # for the tests
    dialog._vf1_slots = slot_list
    return dialog


def game_libraries(app) -> dict[int, Path]:
    """The game's Images folder the patcher knows (for the game's own pictures as backgrounds)."""
    images = images_folder(_guess_game_folder(app))
    return {gen.GAME: images} if images is not None else {}


# ---------------------------------------------------------------------------
# A colour field: a swatch, the colour as text (hex or red, green, blue), and the picker
# ---------------------------------------------------------------------------

def parse_page_range(text: str, count: int) -> list[int]:
    """Pages typed as "3", "2-5", or "1,3-4" -> their 0-based numbers, in order, no repeats.  ValueError
    (with words for the player) when nothing sensible or a page that is not there."""
    pages: list[int] = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        lo, dash, hi = part.partition("-")
        try:
            first, last = int(lo), int(hi) if dash else int(lo)
        except ValueError:
            raise ValueError(f"\"{part}\" is not a page number or a range like 2-5.") from None
        if first > last:
            first, last = last, first
        if first < 1 or last > count:
            raise ValueError(f"This tree has pages 1 to {count}." if count > 1 else "This tree has one page.")
        pages += [k - 1 for k in range(first, last + 1) if k - 1 not in pages]
    if not pages:
        raise ValueError("Type a page number, or a range like 2-5.")
    return pages


class ColourField(ttk.Frame):
    def __init__(self, master, value: str, on_change, allow_default: bool = True, default_text="Automatic"):
        super().__init__(master)
        self.on_change = on_change
        self.value = value
        self.swatch = tk.Label(self, width=3, relief="solid", borderwidth=1)
        self.swatch.pack(side="left")
        self.text = tk.StringVar(value=value)
        entry = ttk.Entry(self, textvariable=self.text, width=16)
        entry.pack(side="left", padx=(4, 0))
        entry.bind("<Return>", self._typed)
        entry.bind("<FocusOut>", self._typed)
        ttk.Button(self, text="Choose...", command=self._pick).pack(side="left", padx=(4, 0))
        if allow_default:
            ttk.Button(self, text=default_text, command=lambda: self._set("")).pack(side="left", padx=(4, 0))
        ttk.Button(self, text="Transparent", command=lambda: self._set(ft.TRANSPARENT)).pack(side="left", padx=(4, 0))
        # Its buttons wrap onto a second line in a narrow panel rather than being cut off (the owner's
        # screenshot: "Automa..." cut at the panel's edge).
        flow_row(self)
        self._show()

    def _show(self) -> None:
        shown = self.value if self.value and self.value != ft.TRANSPARENT else "SystemButtonFace"
        self.swatch.configure(background=shown, text="x" if self.value == ft.TRANSPARENT else "")
        self.text.set(self.value)

    def _typed(self, _event=None) -> None:
        text = self.text.get().strip()
        if not text:
            self._set("")
            return
        colour = ft.parse_colour(text)
        if colour is None:
            messagebox.showerror("Colour", "Type a colour as #rrggbb (for example #d4a017) or as red, green "
                                           "and blue from 0 to 255 (for example 212, 160, 23).", parent=self)
            self._show()
            return
        self._set(colour)

    def _pick(self) -> None:
        chosen = colorchooser.askcolor(color=tk_colour(self.value) or None, parent=self, title="Choose a colour")
        if chosen and chosen[1]:
            self._set(chosen[1].lower())

    def _set(self, colour: str) -> None:
        if colour != self.value:
            self.value = colour
            self._show()
            self.on_change(colour)
        else:
            self._show()

    def set_quietly(self, colour: str) -> None:
        self.value = colour
        self._show()


RANGE_PRESETS = ("#e63946", "#f77f00", "#f2c200", "#3aa655", "#2a9d8f", "#1d9bf0", "#3a56d4", "#8a4fff",
                 "#d63fa6", "#8b5a2b", "#808080", "#202020")


def ask_colour(parent, title: str, initial: str = "") -> str | None:
    """A colour from the picker, or typed: None when cancelled."""
    chosen = colorchooser.askcolor(color=tk_colour(initial) or None, parent=parent, title=title)
    return chosen[1].lower() if chosen and chosen[1] else None


# ---------------------------------------------------------------------------
# The family tree editor
# ---------------------------------------------------------------------------

def open_family_tree(app, build=None, folders: list[Path] | None = None):
    return pick_village(
        app, build, "Family Tree Maker",
        "Draws the chosen family's tree from its save (the game's own Family Tree, up to six children a "
        "generation, and children 7 to 28 when Up to 28 Children keeps them), and lets you mark and edit "
        "it.  The save is only read: your marks and edits, and the .tree file, are kept in Virtual Families 1 "
        "Patcher\\Save <N>\\Data\\Family Tree beside the save.  Export as Picture saves the tree where you choose.",
        "Open Family Tree Maker", lambda dialog, folder, game, info, title, images:
        _open_editor(app, dialog, folder, game, info, title, images),
        ask_game_folder=True, folders=folders)


def _saved_renames(folder: Path, game: int, slot: int) -> dict:
    """The renamed-family member answers the saved edits keep; none when there is no readable file."""
    try:
        path = ft.Edits.path(folder, game, slot)
        return ft.Edits.load(path).renames if path.is_file() else {}
    except ValueError:
        return {}


def ask_renames(parent, folder: Path, game: int, slot: int, village, edits):
    """Ask "Keep <current name> or <old name>?" for each family member the logs name differently from the save
    (same sex, looks and likes: the player renamed them).  Yes keeps the current name (one person, the old
    name noted); No keeps them apart as the tree showed them; Cancel asks again next time.  An answer is
    kept in the tree's edits, so it is not asked again, and the tree is read again with it."""
    answered = False
    for q in list(village.rename_questions):
        got = messagebox.askyesnocancel(
            "Family Tree Maker",
            f"Keep {q.current} or {q.old}?\n\nThe save has {q.current}, the logs also name {q.old}, and "
            "both have the same sex, looks and likes.\n\nYes: keep the current name, {0} (one person, "
            "formerly {1}).\nNo: keep {1} as a separate family member.\nCancel: ask me later.".format(q.current, q.old),
            parent=parent)
        if got is None:
            continue
        edits.renames[q.key] = "current" if got else "old"
        answered = True
    if answered:
        try:
            edits.save(ft.Edits.path(folder, game, slot))
            village = gen.load_village(folder, game, slot, rename_answers=edits.renames)
        except (OSError, gen.GenealogyError):
            pass
    return village


IDENTITY_DONT_KNOW = "Don't know"


def _identity_face(editor, master, p: gen.Person):
    """The face a family member's head shows (the game's own art), or None: as the Family Member Info tab draws it."""
    try:
        sheet = ft.sheet_name(editor.game, p)
        path = (getattr(editor, "present", None) or {}).get(sheet) if sheet else None
        row = ft.look_of(editor.edits, editor.village, p)[0]
        if path is None or row is None or row < 0:
            return None
        source = tk.PhotoImage(master=master, file=str(path))
        if (row + 1) * ft.HEAD_H > source.height():
            return None
        cell = tk.PhotoImage(master=master)
        x0, y0 = ft.HEAD_FRAME * ft.HEAD_W, row * ft.HEAD_H
        bx0, by0, bx1, by1 = ft.head_boxes(path).get(row, ft.DEFAULT_BOX)
        cell.tk.call(cell, "copy", source, "-from", x0 + bx0, y0 + by0, x0 + bx1, y0 + by1, "-zoom", 2)
        return cell
    except (tk.TclError, OSError, AttributeError, KeyError, TypeError, ValueError):
        return None


def ask_identities(editor, questions: list | None = None):
    """(Virtual Villagers asks whether a changed villager is the same one; a Virtual Families family has no such
    questions.)"""
    return None


def _open_editor(app, parent, folder: Path, game: int, info, title: str, images: Path | None) -> None:
    try:
        village = app._run_with_wait("Reading the family from the save...\n\nNothing is changed.",
                                     lambda: gen.load_village(folder, game, info.slot, remember=True,
                                                              rename_answers=_saved_renames(
                                         folder, game, info.slot)))
    except (gen.GenealogyError, OSError) as exc:
        messagebox.showerror("Family Tree Maker", str(exc), parent=parent)
        return
    path = ft.Edits.path(folder, game, info.slot)
    try:
        # A village with no tree of its own yet starts with the look last used (ft.STYLE_KEYS).
        edits = ft.Edits.load(path) if path.is_file() else ft.styled(getattr(app, "tree_style", None))
    except ValueError as exc:
        if not messagebox.askyesno("Family Tree Maker", f"{exc}\n\nStart with no marks or edits?  (The file is "
                                                  "kept as it is until you change something.)", parent=parent):
            return
        edits = ft.Edits()
    village = ask_renames(parent, folder, game, info.slot, village, edits)
    editor = TreeEditor(app, folder, game, info.slot, title, images, village, edits)
    # The same villager, or two? Asked once the tree is open, in one window beside it (never blocking it).
    if getattr(village, "identity_questions", None):
        editor.after(200, lambda: ask_identities(editor, village.identity_questions))


def find_villagers(village: gen.Village, edits: ft.Edits, query: str) -> list[int]:
    """The family members matching what was typed, best first: every word typed must be somewhere in the family member's
    name, "head N" / "body N", sex, age, generation, parents' names, mark, status, or a like or dislike by its
    name ("running", "laundry", "snakes"; only where the save or the logs give them -- never guessed, see
    unknown_preferences).  Names that start with the first word come before names that only contain it."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    people = village.people
    hits = []
    for pid, p in people.items():
        status = ["alive" if p.alive else "", "baby on the way upcoming" if p.upcoming else "",
                  {"died": "died dead deceased", "disappeared": "disappeared gone", "left": "left gone"}.get(p.gone, p.gone),
                  "expecting pregnant" if p.expecting else "", "runner running" if p.runner else "",
                  "adopted" if getattr(p, "adopted", False) else "", "heir" if getattr(p, "heir", False) else "",
                  "left home" if getattr(p, "left_home", False) else "",
                  (p.how or "").lower(), (getattr(p, "cause", "") or "").lower()]
        parents = " ".join(people[q].name for q in (p.father, p.mother) if q in people)
        mark = " ".join(ft.entry_marks(edits.entries.get(ft.entry_key(village, p), {})) + list(p.statuses))
        text = " ".join([p.name, f"head {p.head}", f"body {p.body}", f"head{p.head} body{p.body}", p.sex or "",
                         f"{p.age} units" if p.age is not None else "", f"{p.years} years" if p.years is not None else "",
                         f"generation {p.generation} gen {p.generation} {gen.roman(p.generation)}", parents,
                         mark, " ".join(status), ", ".join(p.likes or []), ", ".join(p.dislikes or [])]).lower()
        if all(w in text for w in words):
            name = p.name.lower()
            hits.append((0 if name.startswith(words[0]) else 1 if words[0] in name else 2, p.generation, name, pid))
    return [pid for *_rank, pid in sorted(hits)]


def unknown_preferences(village: gen.Village) -> list[int]:
    """The family members whose likes and dislikes neither the save nor the logs give, so a search by them cannot
    find (or rule out) these."""
    return [pid for pid, p in village.people.items()
            if p.likes is None or p.dislikes is None]


class TreeEditor(CanvasTools, tk.Toplevel):
    ColourField = ColourField           # the tools' colour fields
    tree_tips = True                    # hover tips for cut-off words here and in every window it opens

    def __init__(self, app, folder: Path, game: int, slot: int, game_title: str, images: Path | None,
                 village: gen.Village, edits: ft.Edits) -> None:
        tk.Toplevel.__init__(self, _master(app))
        self.app, self.folder, self.game, self.slot = app, Path(folder), game, slot
        self.game_title, self.images, self.village, self.edits = game_title, images, village, edits
        # The edits the window opened with, and whether they came from a saved file: "No" on closing a
        # tree never saved goes back to them (it went to the factory look, and made that the look
        # remembered for every new tree).
        self.opened_edits = json.dumps(edits.to_data())
        self.opened_from_file = ft.Edits.path(self.folder, game, slot).is_file()
        self.present = ft.sheets_present(game, images)
        self.library = game_libraries(app)
        self.selected: list[int] = []
        self.dirty = False                      # changes not saved yet (the owner's Yes / No / Cancel on closing)
        self.press_words: int | None = None     # words pressed on: retyped if the press is a click
        self.page = 0                           # the page of the tree shown (ft.page_spans)
        self.anchor: int | None = None
        self.band = None
        self.pan: tuple | None = None
        self.photos: dict = {}
        self.backdrop_key = None
        self.z = 1.0
        self.title(f"Family Tree Maker - {village.tribe or ''} (Save {slot}) - {game_title}")
        self.window = dict(getattr(app, "tree_window", {}) or {})
        # One Keep aspect ratio for every size the player changes -- dragging a corner and the width and
        # height boxes alike (the owner, 2026-10-09: "especially for the arrows that change portrait
        # height and width, but for everything else too"); remembered with the window.
        self.lock_shape = tk.BooleanVar(value=self.window.get("keep_aspect", True) is not False)
        # "Hide villagers not in the current save" (the owner, v1.35.73; on by default): the villagers of a
        # tribe started over with the same name, proven gone by src/vv_history_revision.py, are left out of
        # the tree -- the tree only; the logs keep them until Repair Saves & Logs removes them.
        self.full_village = village
        self.hide_gone = tk.BooleanVar(value=self.window.get("hide_not_in_save", True) is not False)
        self.village = self._shown_village(village)
        self.geometry(self.window.get("geometry", "1400x860"))
        install_tips(self)
        self._build()
        self._follow_looks()
        self.redraw()
        self.written = None
        # Virtual Families 1: the page, picture and report are written only when asked (Open in Browser, Export as
        # Picture) -- never by themselves on opening or closing; the only file kept is the tree's own edits.
        self.protocol("WM_DELETE_WINDOW", self._close)

    def destroy(self) -> None:
        """Closed: nothing left waiting to run on it (the background picture still being drawn, say)."""
        done = self.__dict__.get("_backdrop_done", {})
        done["closed"] = True
        if "ok" in done and done.get("temp") is not None:     # drawn, but not yet shown
            done["temp"].unlink(missing_ok=True)
        for name in ("_backdrop_poll", "_write_job", "_backdrop_job"):
            job = self.__dict__.pop(name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()

    # ---- the window -------------------------------------------------------
    # ---- finding a villager ---------------------------------------------------------------
    def _build_find(self, bar) -> None:
        """A search row under the toolbar: type, press Enter (again for the next one) or pick from the list."""
        row = self.find_row = ttk.Frame(self)
        row.pack(side="top", fill="x", after=bar, padx=6, pady=(0, 3))
        # The window buttons, right-aligned on this row (the owner: on the crowded toolbar above, the Hide panel
        # button was squeezed to a sliver).  Packed FIRST, so pack gives them their full width before anything
        # else on the row, at any window width and display scaling; the find controls beside them wrap instead.
        buttons = self.window_buttons = ttk.Frame(row)
        buttons.pack(side="right", anchor="n")
        self.panel_button = ttk.Button(buttons, text="Hide panel (F4)", command=self._toggle_panel)
        self.panel_button.pack(side="right")
        ttk.Button(buttons, text="Full screen (F11)", command=self._toggle_full).pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="Help (F1)", command=self._help).pack(side="right", padx=(0, 6))
        row = self.find_controls = ttk.Frame(row)
        row.pack(side="left", fill="x", expand=True, anchor="n", padx=(0, 8))
        ttk.Label(row, text="Find a family member (Ctrl+F):").pack(side="left")
        self.find_var = tk.StringVar()
        self.find_entry = ttk.Entry(row, textvariable=self.find_var, width=30)
        self.find_entry.pack(side="left", padx=(4, 0))
        self.find_box = ttk.Combobox(row, state="readonly", width=46, values=[])
        self.find_box.pack(side="left", padx=(4, 0))
        find = ttk.Button(row, text="Find", command=self._find_next)
        find.pack(side="left", padx=(4, 0))
        tip(find, "The next match (Enter)")
        hint = ttk.Label(row, justify="left",
                         text="Name, head or body number, parent, generation, mark, like or dislike, or status (died, "
                              "left, expecting, adopted...).  Enter: the first match, again: the next.")
        hint.pack(side="left", padx=(8, 0))
        hint.flow_wrap = True           # wraps to the room left rather than being cut off
        flow_row(row, natural=False)
        self.find_hits: list[int] = []
        self.find_at = -1
        self.find_entry.bind("<Return>", lambda _e: self._find_next())
        self.find_entry.bind("<KeyRelease>", self._find_typed)
        self.find_box.bind("<<ComboboxSelected>>", lambda _e: self._find_picked())
        self.bind("<Control-f>", self._find_focus)
        self.bind("<Control-F>", self._find_focus)

    def _find_focus(self, _event=None) -> str:
        """Ctrl+F: into the Find a family member box, its words selected to type over."""
        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")
        return "break"

    def _find_typed(self, event) -> None:
        if event.keysym in ("Return", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return
        self._find_refresh()

    def _find_refresh(self) -> list[int]:
        """The matches for what is typed, shown in the list; the next Enter starts at the first."""
        self.find_hits = find_villagers(self.village, self.edits, self.find_var.get())
        self.find_at = -1
        self.find_box.configure(values=[self._find_words(q) for q in self.find_hits[:60]])
        self.find_box.set("")
        return self.find_hits

    def _find_words(self, pid: int) -> str:
        p = self.village.people[pid]
        return (f"{p.name} - generation {gen.roman(p.generation)}" + ("" if p.alive or p.upcoming else f" ({p.gone or 'gone'})")
                + ("" if p.likes is not None and p.dislikes is not None else " [likes and dislikes not known]"))

    def _find_next(self) -> None:
        if not self.find_var.get().strip():
            self.status.set("Type a name (or a head or body number, a parent, a mark, died, left, expecting, adopted...) "
                            "to find a family member.")
            return
        if self.find_at < 0 or not self.find_hits:
            self._find_refresh()
        if not self.find_hits:
            unknown = len(unknown_preferences(self.village))
            self.status.set(f"No family member matches \"{self.find_var.get().strip()}\"." + (
                f"  {unknown} family member{'s' if unknown != 1 else ''} have no likes and dislikes in the save, "
                "so a like or dislike could not be searched for in them." if unknown else ""))
            return
        self.find_at = (self.find_at + 1) % len(self.find_hits)
        self._find_go(self.find_hits[self.find_at], f"{self.find_at + 1} of {len(self.find_hits)}")

    def _find_picked(self) -> None:
        k = self.find_box.current()
        if 0 <= k < len(self.find_hits):
            self.find_at = k
            self._find_go(self.find_hits[k], f"{k + 1} of {len(self.find_hits)}")

    def _find_go(self, pid: int, which: str) -> None:
        """The tree on the family member's page, they selected."""
        if vf1_member_info.go_to(self, pid):
            self.status.set(f"{self.village.people[pid].name} (match {which}) is selected on page {self.page + 1}.")

    def _build(self) -> None:
        bar = self.toolbar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=6, pady=4)
        # Shortcut keys on this crowded row are in hover tips, not longer labels (the owner: "you may put
        # shortcut keys in the taskbar too").
        # The toolbar wraps onto a second line when the window is too narrow (flow_row, below): controls that
        # belong together sit in one frame so they wrap together.
        zooms = ttk.Frame(bar)
        zooms.pack(side="left")
        out = ttk.Button(zooms, text="-", width=3, command=lambda: self._zoom_step(-1))
        out.pack(side="left")
        tip(out, "Zoom out (-)")
        self.zoom_var = tk.StringVar(value="100%")
        zoom = ttk.Combobox(zooms, textvariable=self.zoom_var, values=[f"{int(z * 100)}%" for z in ZOOMS] + ["Fit"],
                            state="readonly", width=6)
        zoom.pack(side="left", padx=2)
        zoom.bind("<<ComboboxSelected>>", lambda _e: self._zoom_choice())
        tip(zoom, "Zoom (Ctrl+0: 100%)")
        into = ttk.Button(zooms, text="+", width=3, command=lambda: self._zoom_step(1))
        into.pack(side="left")
        tip(into, "Zoom in (+)")
        ttk.Button(bar, text="Fit", command=self._zoom_fit).pack(side="left", padx=(6, 0))
        ttk.Label(bar, text="Zoom: wheel or + -    Move around: drag empty space").pack(side="left", padx=(8, 0))
        # Snapping (the owner: 'a "snap to grid" thing? (center vertical/horizontal, etc)').
        self.smart_var = tk.BooleanVar(value=self.window.get("smart", True))
        self.snap_var = tk.BooleanVar(value=self.window.get("snap", False))
        self.grid_size = tk.StringVar(value=str(self.window.get("grid", 20)))
        self.show_grid = tk.BooleanVar(value=self.window.get("show_grid", False))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Checkbutton(bar, text="Smart guides", variable=self.smart_var).pack(side="left")
        snap = ttk.Frame(bar)
        snap.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(snap, text="Snap to grid", variable=self.snap_var).pack(side="left")
        size = ttk.Combobox(snap, textvariable=self.grid_size, values=GRID_SIZES, state="readonly", width=3)
        size.pack(side="left", padx=(2, 0))
        size.bind("<<ComboboxSelected>>", lambda _e: self._draw_grid())
        ttk.Checkbutton(bar, text="Show grid", variable=self.show_grid, command=self._draw_grid
                        ).pack(side="left", padx=(6, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        pages = ttk.Frame(bar)
        pages.pack(side="left")
        ttk.Label(pages, text="Page:").pack(side="left")
        self.page_var = tk.StringVar()
        self.page_box = ttk.Combobox(pages, textvariable=self.page_var, state="readonly", width=22)
        self.page_box.pack(side="left", padx=(2, 0))
        self.page_box.bind("<<ComboboxSelected>>", lambda _e: self._show_page(self.page_box.current()))
        self.diagonal_var = tk.BooleanVar(value=self.edits.diagonal_lines)
        ttk.Checkbutton(bar, text="Allow diagonal lines", variable=self.diagonal_var,
                        command=lambda: self._change(diagonal_lines=bool(self.diagonal_var.get()))
                        ).pack(side="left", padx=(6, 0))
        align = ttk.Menubutton(bar, text="Align")
        menu = tk.Menu(align, tearoff=0)
        for words, how in (("Lefts", "left"), ("Centres", "centre"), ("Rights", "right"), (None, None),
                           ("Tops", "top"), ("Middles", "middle"), ("Bottoms", "bottom"), (None, None),
                           ("Centre on the tree, across", "page_x"), ("Centre on the tree, up and down", "page_y"),
                           (None, None), ("Space evenly across", "spread_x"), ("Space evenly up and down", "spread_y")):
            if words is None:
                menu.add_separator()
            else:
                menu.add_command(label=words, command=lambda h=how: self._align(h))
        align["menu"] = menu
        align.pack(side="left", padx=(6, 0))
        flow_row(bar, natural=False)
        self._build_find(bar)           # the row under it, with Help, Full screen and Hide panel at its right end
        self.status = tk.StringVar(value="Click to select, drag anything to move it, right-click anything to "
                                         "change its colour.  F1 lists every control.")
        ttk.Label(self, textvariable=self.status, anchor="w", padding=(8, 2)).pack(side="bottom", fill="x")
        body = self.body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        self.canvas = tk.Canvas(left, background=OUTSIDE, highlightthickness=0)
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.canvas.xview)
        ys = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        body.add(left, weight=4)
        right = self.panel = ttk.Frame(body, padding=8)
        body.add(right, weight=1)
        # Under every tab, always in view (packed first, at the bottom).
        bottom = ttk.Frame(right)
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Save to Save Folder", command=self._save_tree).pack(side="left")
        ttk.Button(bottom, text="Export as Picture...", command=self._export).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="Open in Browser", command=self._open_page).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="Close", command=self._close).pack(side="right")
        resets = ttk.Frame(right)
        resets.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(resets, text="Reset Portrait Shapes", command=self._reset_shapes).pack(side="left")
        ttk.Button(resets, text="Reset Portrait Places", command=self._reset_portraits).pack(side="left", padx=(6, 0))
        ttk.Button(resets, text="Reset Lines", command=self._reset_lines).pack(side="left", padx=(6, 0))
        ttk.Button(resets, text="Reset Everything", command=self._reset_everything).pack(side="left", padx=(6, 0))
        tidy = ttk.Frame(right)
        tidy.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(tidy, text="Reorganize Portraits", command=self._reorganize_portraits).pack(side="left")
        ttk.Button(tidy, text="Reorganize Lines", command=self._reorganize_lines).pack(side="left", padx=(6, 0))
        ttk.Button(tidy, text="Reorganize Generation Labels", command=self._reorganize_labels).pack(
            side="left", padx=(6, 0))
        undo = ttk.Frame(right)
        undo.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(undo, text="Undo (Ctrl+Z)", command=self._undo).pack(side="left")
        ttk.Button(undo, text="Redo (Ctrl+Y)", command=self._redo).pack(side="left", padx=(6, 0))
        ttk.Button(undo, text="Update Family Tree from the Save (F5)", command=self._update_from_game).pack(
            side="left", padx=(6, 0))
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        self._selected_tab()
        self.info_tab = vf1_member_info.VillagerInfoTab(self)     # read-only: who the one selected is
        self._marks_tab()
        self._tree_tab()
        self._background_tab()
        self._tools_setup()
        self._order_tabs()
        self._fit_lists(self)
        c = self.canvas
        c.bind("<Button-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        # The owner: "zoom in/out with the scroll wheel or plus and minus on the keyboard", and
        # "click and drag on empty space to pan".
        c.bind("<MouseWheel>", self._zoom_wheel)
        c.bind("<Control-MouseWheel>", self._zoom_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: c.xview_scroll(-1 * (e.delta // 120), "units"))
        c.bind("<Alt-MouseWheel>", lambda e: c.yview_scroll(-1 * (e.delta // 120), "units"))
        c.bind("<Button-2>", lambda e: self._pan_start(e))
        c.bind("<B2-Motion>", lambda e: self._pan_move(e))
        c.bind("<ButtonRelease-2>", lambda e: self._pan_end(e))
        for key in ("<Control-equal>", "<Control-plus>", "<Control-KP_Add>", "<plus>", "<equal>", "<KP_Add>"):
            self.bind(key, lambda _e: None if self._typing() else self._zoom_step(1))
        for key in ("<Control-minus>", "<Control-KP_Subtract>", "<minus>", "<KP_Subtract>"):
            self.bind(key, lambda _e: None if self._typing() else self._zoom_step(-1))
        self.bind("<Control-0>", lambda _e: None if self._typing() else self._zoom_to(1.0))
        self.bind("<F4>", lambda _e: self._toggle_panel())
        self.bind("<F11>", lambda _e: self._toggle_full())
        self.bind("<F1>", lambda _e: self._help())
        self.bind("<F5>", self._update_from_game)
        self._menus()
        c.bind("<Button-3>", self._context)
        c.bind("<Motion>", self._hover)
        if self.window.get("sash"):
            self.after(150, lambda: self._restore_sash(self.window["sash"]))
        if self.window.get("panel_hidden"):
            self.after(160, self._toggle_panel)
        self.bind("<Control-a>", self._select_all)
        self.bind("<Control-A>", self._select_all)
        self.bind("<Escape>", self._escape)

    def _selected_tab(self) -> None:
        # Scrolls when its controls are taller than the window (the owner, 2026-10-08: "please have a
        # scroll bar for the side panel options! it's cut off!"), like the other tabs.
        tab = ScrollingTab(self.notebook, "Selected")
        self.sel_label = tk.StringVar()
        ttk.Label(tab, textvariable=self.sel_label, wraplength=320, justify="left").pack(anchor="w")

        box = ttk.LabelFrame(tab, text="Their face and words", padding=6)
        box.pack(fill="x", pady=(8, 0))
        # The owner, 2026-10-09: "differentiate editing Portrait SHAPES vs villager faces and text within the
        # portraits" -- the face's and the words' own sizes here, the shape's below.
        sizes = ttk.Frame(box)
        sizes.pack(fill="x", pady=(0, 4))
        # Select words, then format them (the owner: "please allow text formatting in the family tree
        # portrait text section"): these buttons, the right-click menu or Ctrl+B / Ctrl+I / Ctrl+U.
        tools = ttk.Frame(box)
        tools.pack(fill="x", pady=(0, 4))
        self.format_buttons = {}
        for what, label, look in TEXT_FORMATS:
            button = tk.Button(tools, text=label, font=look, width=3 if len(label) < 3 else 0, padx=4,
                               relief="groove", takefocus=False, command=lambda w=what: self._format_text(w))
            button.pack(side="left", padx=(0, 2))
            self.format_buttons[what] = button
        self.lines_text = tool_text(box, height=5, width=34, undo=True)
        self.lines_text.pack(fill="x")
        self.lines_text.bind("<Button-3>", self._format_menu)
        self.lines_text.bind("<Control-b>", lambda _e: self._format_text("bold"))
        self.lines_text.bind("<Control-i>", lambda _e: self._format_text("italic"))
        self.lines_text.bind("<Control-u>", lambda _e: self._format_text("underline"))
        self.lines_text.bind("<Key>", self._type_formatted)
        self.lines_text.bind("<KeyRelease>", lambda _e: self._show_looks())
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Save text", command=self._apply_text).pack(side="left")
        ttk.Button(row, text="Reset text", command=self._restore_text).pack(side="left", padx=(6, 0))

        box = ttk.LabelFrame(tab, text="Their special mark", padding=6)
        box.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.mark_var = tk.StringVar()
        self.mark_box = ttk.Combobox(row, textvariable=self.mark_var, state="readonly", width=20)
        self.mark_box.pack(side="left")
        ttk.Button(row, text="Give mark", command=self._apply_mark).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Remove mark", command=lambda: self._apply_mark(clear=True)).pack(side="left", padx=(6, 0))
        # Each mark they have, ticked (the owner, 2026-10-22: every special status is marked by itself -- a
        # Tribal Chief, a Former Heathen...; untick one to take it off them, and it stays off).
        self.mark_checks = ttk.Frame(box)
        self.mark_checks.pack(fill="x", pady=(4, 0))
        self.mark_check_vars: dict[str, tk.BooleanVar] = {}

        box = ttk.LabelFrame(tab, text="Their family colour", padding=6)
        box.pack(fill="x", pady=(8, 0))
        ttk.Label(box, text="Shared with full brothers and sisters, and their family's lines.",
                  wraplength=300).pack(anchor="w")
        self.family_field = ColourField(box, "", self._own_colour)
        self.family_field.pack(anchor="w", pady=(2, 0))

        box = ttk.LabelFrame(tab, text="Their portrait shape: border, size, turn and colours", padding=6)
        box.pack(fill="x", pady=(8, 0))
        self.own_vars: dict[str, tk.StringVar] = {}
        for row_no, (attr, label, choices) in enumerate((("shape", "Shape:", ft.PORTRAIT_SHAPES),
                                                        ("border", "Border:", ft.BORDERS))):
            ttk.Label(box, text=label).grid(row=row_no, column=0, sticky="w", pady=1)
            var = tk.StringVar()
            self.own_vars[attr] = var
            combo = ttk.Combobox(box, textvariable=var, values=ft.alphabetical(choices.values()), state="readonly", width=18)
            combo.grid(row=row_no, column=1, sticky="w", padx=(6, 0), pady=1)
            combo.bind("<<ComboboxSelected>>", lambda _e, a=attr, c=choices, v=var: self._own_style(
                a, next(k for k, n in c.items() if n == v.get())))
            ttk.Button(box, text="Reset to default", command=lambda a=attr: self._own_style(a, "")).grid(
                row=row_no, column=2, sticky="w", padx=(6, 0), pady=1)
        ttk.Label(box, text="Click one family member, then drag the circles round their portrait to resize the shape or "
                            "the arrow above it to turn it.  The face and words have their own sizes, above.",
                  wraplength=300, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Button(box, text="Reset size and turn", command=self._reset_frames).grid(row=3, column=0, columnspan=2,
                                                                                    sticky="w")
        ttk.Checkbutton(box, text="Keep aspect ratio", variable=self.lock_shape).grid(row=3, column=2, sticky="w")
        row = ttk.Frame(box)
        row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(row, text="Size:  width").pack(side="left")
        self.own_w, self.own_h = tk.StringVar(), tk.StringVar()
        for var, label, axis in ((self.own_w, None, 0), (self.own_h, "height", 1)):
            if label:
                ttk.Label(row, text=label).pack(side="left", padx=(4, 0))
            self._live(ttk.Spinbox(row, textvariable=var, values=ft.SIZE_STEPS, width=6),
                       lambda a=axis: self._own_size(a)).pack(side="left", padx=(2, 0))
        # The face's and the words' own sizes, apart from the frame (the owner, 2026-10-08: "Should be able to
        # resize text independently of the portrait shape it's in too"), in "Their face and words" above;
        # 100% is the size that fits the shape.
        ttk.Label(sizes, text="Face size %").pack(side="left")             # the owner, 2026-10-09
        self.own_picture = tk.StringVar()
        self._live(ttk.Spinbox(sizes, textvariable=self.own_picture, from_=ft.PICTURE_SCALE_MIN,
                               to=ft.PICTURE_SCALE_MAX, increment=10, width=5),
                   self._own_picture_size).pack(side="left", padx=(2, 0))
        ttk.Label(sizes, text="Text size %").pack(side="left", padx=(10, 0))
        self.own_text = tk.StringVar()
        self._live(ttk.Spinbox(sizes, textvariable=self.own_text, from_=ft.TEXT_SCALE_MIN, to=ft.TEXT_SCALE_MAX,
                               increment=10, width=5), self._own_text_size).pack(side="left", padx=(2, 0))
        ttk.Button(sizes, text="Reset", width=6, command=self._own_inner_reset).pack(side="left", padx=(6, 0))
        # The owner, 2026-10-09: "an option to recolor the inside of the portraits" -- each selected
        # villager's own; Automatic is the whole tree's (the Shapes tab).
        # A row each, wrapping in a narrow panel (side by side they ran past the panel's edge).
        row = ttk.Frame(box)
        row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(row, text="Inside colour:").pack(side="left")
        self.own_fill = ColourField(row, "", self._own_fill)
        self.own_fill.pack(side="left", padx=(4, 0))
        flow_row(row, natural=False)
        row = ttk.Frame(box)
        row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Label(row, text="Detail colour:").pack(side="left")       # the lines inside it
        self.own_detail = ColourField(row, "", self._own_detail)
        self.own_detail.pack(side="left", padx=(4, 0))
        flow_row(row, natural=False)
        box.columnconfigure(2, weight=1)
        # The owner, 2026-10-09: flip the portrait's shape either way, and turn it to an exact angle.
        row = ttk.Frame(box)
        row.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.own_flips = {flip: tk.BooleanVar() for flip in ("flip_h", "flip_v")}
        for flip, words in (("flip_h", "Flip horizontally"), ("flip_v", "Flip vertically")):
            ttk.Checkbutton(row, text=words, variable=self.own_flips[flip],
                            command=lambda f=flip: self._own_flip(f)).pack(side="left", padx=(0, 8))
        ttk.Label(row, text="Turn (degrees)").pack(side="left")
        self.own_turn = tk.StringVar()
        self._live(ttk.Spinbox(row, textvariable=self.own_turn, from_=0, to=345, increment=15, width=5, wrap=True),
                   self._own_turn).pack(side="left", padx=(4, 0))
        row = ttk.Frame(box)
        row.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(row, text="Their family's lines:  weight").pack(side="left")
        self.own_line_w = tk.StringVar()
        self._live(ttk.Spinbox(row, textvariable=self.own_line_w, values=ft.LINE_STEPS, width=5),
                   lambda: self._own_lines(part="width")).pack(side="left", padx=(2, 0))
        self.own_line_dash = tk.StringVar()
        kind = ttk.Combobox(row, textvariable=self.own_line_dash, values=ft.alphabetical(ft.LINE_TYPES.values()),
                            state="readonly", width=16)
        kind.pack(side="left", padx=(4, 0))
        kind.bind("<<ComboboxSelected>>", lambda _e: self._own_lines(part="dash"))
        ttk.Button(row, text="Reset to default", command=lambda: self._own_lines(reset=True)).pack(side="left",
                                                                                               padx=(4, 0))

        # The owner: "allow customizability/reordering of villagers within generations.  Perhaps I
        # would like to put Huata in the 4th generation".
        box = ttk.LabelFrame(tab, text="Their generation and place", padding=6)
        box.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.gen_choice = tk.StringVar()
        spin = ttk.Spinbox(row, textvariable=self.gen_choice, from_=1, to=99, width=5)
        spin.pack(side="left")
        spin.bind("<Return>", lambda _e: self._set_generation())
        ttk.Button(row, text="Move to generation", command=self._set_generation).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Reset", command=lambda: self._set_generation(back=True)).pack(side="left", padx=(6, 0))
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="< Move left", command=lambda: self._shift_place(-1)).pack(side="left")
        ttk.Button(row, text="Move right >", command=lambda: self._shift_place(1)).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Reset order", command=self._reset_order).pack(side="left", padx=(6, 0))

        ttk.Button(tab, text="Reset everything for them", command=self._clear_selected).pack(anchor="w", pady=(10, 0))
        self._refresh_selected()

    def _marks_tab(self) -> None:
        # Scrolls when its controls are taller than the window (the owner, 2026-10-08: "please have a
        # scroll bar for the side panel options! it's cut off!"), like the other tabs.
        tab = ScrollingTab(self.notebook, "Marks")      # the owner, 2026-10-09
        ttk.Label(tab, text="A special mark is a coloured border or glow around a family member, named in the Key "
                            "under the title.  Add your own (Founder, Heir, Favourite...) and give it to the family members you "
                            "choose on the Selected tab.",
                  wraplength=320, justify="left").pack(anchor="w")
        box = ttk.LabelFrame(tab, text="How every mark looks", padding=6)
        box.pack(fill="x", pady=(6, 0))
        self.mark_style_var = tk.StringVar(value=ft.MARK_STYLES[self.edits.mark_style])
        style = ttk.Combobox(box, textvariable=self.mark_style_var, values=ft.alphabetical(ft.MARK_STYLES.values()),
                             state="readonly", width=28)
        style.grid(row=0, column=0, columnspan=3, sticky="w")
        style.bind("<<ComboboxSelected>>", lambda _e: self._change(
            mark_style=next(k for k, v in ft.MARK_STYLES.items() if v == self.mark_style_var.get())))
        ttk.Label(box, text="Glow size:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.glow_var = tk.StringVar(value=f"{self.edits.mark_glow:g}")
        self._live(ttk.Spinbox(box, textvariable=self.glow_var, values=ft.SIZE_STEPS[:ft.SIZE_STEPS.index(72)],
                               width=5), self._glow_size).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(4, 0))
        shown = tk.StringVar(value=f"Opacity: {self.edits.mark_opacity}%")
        ttk.Label(box, textvariable=shown, width=14).grid(row=2, column=0, sticky="w", pady=(4, 0))
        scale = self.mark_opacity_scale = ttk.Scale(
            box, from_=0, to=100, orient="horizontal", command=lambda v: shown.set(f"Opacity: {int(float(v))}%"))
        scale.set(self.edits.mark_opacity)
        scale.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=(4, 0))
        for event in ("<ButtonRelease-1>", "<KeyRelease>"):
            scale.bind(event, lambda _e: self.edits.mark_opacity != int(scale.get())
                       and self._change(mark_opacity=int(scale.get())))
        box.columnconfigure(2, weight=1)
        ttk.Label(box, text="Each mark's colour: Change colour... below.", wraplength=300).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        # The owner, 2026-10-08: "please allow me to delete the key for marks" (right-click it >
        # Delete does the same; Deleted items on the Layout tab brings it back).
        self.key_var = tk.BooleanVar(value="word:key" not in self._hidden_now())
        ttk.Checkbutton(box, text="Show the Key (each mark's name and colour, under the title)",
                        variable=self.key_var, command=self._show_key).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(tab, text="1. Pick or type a mark.\n2. Select family members on the tree.\n3. Click Add.",
                  justify="left").pack(anchor="w", pady=(6, 0))
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 0))
        self.preset_mark = tk.StringVar(value=next(iter(PRESET_MARKS)))
        marks = ttk.Combobox(row, textvariable=self.preset_mark, values=ft.alphabetical(PRESET_MARKS) + [CUSTOM_MARK], width=22)
        marks.pack(side="left")

        def custom(_event=None) -> None:
            if self.preset_mark.get() == CUSTOM_MARK:       # type its name in the box
                self.preset_mark.set("")
                marks.focus_set()

        marks.bind("<<ComboboxSelected>>", custom)
        ttk.Button(row, text="Add", command=self._add_preset_mark).pack(side="left", padx=(6, 0))
        ttk.Label(tab, text="Your marks (in Key order):").pack(anchor="w", pady=(10, 0))
        self.marks_list = tk.Listbox(tab, height=8, exportselection=False)
        self.marks_list.pack(fill="both", expand=True, pady=(2, 4))
        for text, command in (("New mark...", self._add_mark), ("Rename...", self._rename_mark),
                              ("Change colour...", self._recolour_mark), ("Delete", self._remove_mark),
                              ("Move up", lambda: self._move_mark(-1)), ("Move down", lambda: self._move_mark(1))):
            ttk.Button(tab, text=text, command=command).pack(anchor="w", pady=1)
        self._refresh_marks()

    def _tree_tab(self) -> None:
        # Scrolls when its controls are taller than the window (the owner, 2026-10-08: "please have a
        # scroll bar for the side panel options! it's cut off!"), like the other tabs.
        # The owner, 2026-10-09: "organize the tree options better. Portrait editing in one place, text in
        # another. Why not have tabs?" -- the one long Whole Tree tab, split by what each option changes.
        portraits_tab = ScrollingTab(self.notebook, "Shapes")
        text_tab = ScrollingTab(self.notebook, "Faces & Text")
        layout_tab = ScrollingTab(self.notebook, "Layout")
        # The owner, 2026-10-09: "organize everything where it makes sense.  and name things in a natural way
        # that describes what the feature does succinctly" -- each tab's sections made first, in the order they
        # stand; each part below fills its own.
        def slot(parent, title: str = ""):
            frame = ttk.LabelFrame(parent, text=title, padding=6) if title else ttk.Frame(parent)
            frame.pack(fill="x", pady=(10, 0) if title else 0)
            return frame
        p_shape, p_size, p_colour, p_schemes, p_details, p_special = (
            slot(portraits_tab), slot(portraits_tab), slot(portraits_tab, "Colours"), slot(portraits_tab),
            slot(portraits_tab), slot(portraits_tab))
        t_words, t_colour, t_numbers, t_box = (slot(text_tab), slot(text_tab, "Text colour"),
                                               slot(text_tab, "Numbered names"), slot(text_tab, "Text box background"))
        l_title, l_arrange, l_spacing, l_lines, l_labels, l_label_line, l_opacity, l_page_size, l_pages, l_deleted = (
            slot(layout_tab, "Title"), slot(layout_tab, "Arrangement"), slot(layout_tab), slot(layout_tab),
            slot(layout_tab, "Generation labels"), slot(layout_tab), slot(layout_tab), slot(layout_tab, "Page size"),
            slot(layout_tab), slot(layout_tab))
        tab = l_title
        e = self.edits
        self.title_var = tk.StringVar(value=e.title)
        self.subtitle_var = tk.StringVar(value=e.subtitle)
        for label, var in (("Title (empty = automatic):", self.title_var),
                           ("Subtitle (empty = automatic):", self.subtitle_var)):
            ttk.Label(tab, text=label).pack(anchor="w", pady=(6, 1))
            entry = ttk.Entry(tab, textvariable=var, width=40)
            entry.pack(fill="x")
            entry.bind("<Return>", lambda _e: self._titles())
            entry.bind("<FocusOut>", lambda _e: self._titles())
        tab = l_arrange
        ttk.Label(tab, text="Order in each generation:").pack(anchor="w", pady=(0, 1))
        self.sort_var = tk.StringVar(value=gen.SORTS[e.sort])
        sort = ttk.Combobox(tab, textvariable=self.sort_var, values=ft.alphabetical(gen.SORTS.values()), state="readonly")
        sort.pack(fill="x")
        sort.bind("<<ComboboxSelected>>", lambda _e: self._change(sort=next(k for k, v in gen.SORTS.items()
                                                                            if v == self.sort_var.get())))
        tab = t_numbers
        ttk.Button(tab, text="Renumber edited portraits", command=self._renumber).pack(anchor="w")
        ttk.Button(tab, text="Number duplicate names", command=self._number_names).pack(anchor="w", pady=(4, 0))
        self.number_names_var = tk.BooleanVar(value=e.number_names)
        ttk.Checkbutton(tab, text="Show duplicate names numbered (Happi I, Happi II...)", variable=self.number_names_var,
                        command=lambda: self._change(number_names=bool(self.number_names_var.get()))).pack(anchor="w")
        ttk.Label(tab, text="Number duplicates in this order:").pack(anchor="w", pady=(2, 1))
        self.number_order_var = tk.StringVar(value=gen.NUMBER_ORDERS[e.number_order])
        orders = ttk.Combobox(tab, textvariable=self.number_order_var, values=ft.alphabetical(gen.NUMBER_ORDERS.values()),
                              state="readonly")
        orders.pack(fill="x")
        orders.bind("<<ComboboxSelected>>", lambda _e: self._change(number_order=next(
            k for k, v in gen.NUMBER_ORDERS.items() if v == self.number_order_var.get())))
        tab = l_arrange
        ttk.Label(tab, text="Layout:").pack(anchor="w", pady=(6, 1))
        self.position_var = tk.StringVar(value=ft.POSITIONING[e.positioning])
        positions = ttk.Combobox(tab, textvariable=self.position_var, values=ft.alphabetical(ft.POSITIONING.values()),
                                 state="readonly")
        positions.pack(fill="x")
        positions.bind("<<ComboboxSelected>>", lambda _e: (self._change(
            positioning=next(k for k, v in ft.POSITIONING.items() if v == self.position_var.get())),
            self._show_packing()))
        # The owner, 2026-10-09: "an adjustable degree of packing" -- the Packed layouts only, the tree
        # following the slider as it moves.
        self.positions_box = positions
        self.packing_row = ttk.Frame(tab)
        self.packing_var = tk.StringVar()
        ttk.Label(self.packing_row, textvariable=self.packing_var).pack(anchor="w")
        self.packing_scale = ttk.Scale(self.packing_row, from_=0, to=100, orient="horizontal",
                                       command=self._packing_moved)
        self.packing_scale.set(e.packing)
        self.packing_scale.pack(fill="x")
        self.packing_scale.bind("<ButtonRelease-1>", self._packing_done)
        self.packing_scale.bind("<KeyRelease>", self._packing_done)
        self._show_packing()
        # The owner, 2026-10-09: "justify portraits" -- each row across the tree, and the portraits of
        # different sizes in a row lined up by their tops, middles or bottoms.
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=(6, 0))
        ttk.Label(row, text="Rows across the tree:").pack(side="left")
        self.row_align_var = tk.StringVar(value=ft.ROW_ALIGNS[e.row_align])
        across = ttk.Combobox(row, textvariable=self.row_align_var, values=list(ft.ROW_ALIGNS.values()),
                              state="readonly", width=12)
        across.pack(side="left", padx=(6, 12))
        across.bind("<<ComboboxSelected>>", lambda _e: self._change(
            row_align=next(k for k, v in ft.ROW_ALIGNS.items() if v == self.row_align_var.get())))
        ttk.Label(row, text="Line up portraits by their:").pack(side="left")
        self.row_valign_var = tk.StringVar(value=ft.ROW_VALIGNS[e.row_valign])
        down = ttk.Combobox(row, textvariable=self.row_valign_var, values=list(ft.ROW_VALIGNS.values()),
                            state="readonly", width=9)
        down.pack(side="left", padx=(6, 0))
        down.bind("<<ComboboxSelected>>", lambda _e: self._change(
            row_valign=next(k for k, v in ft.ROW_VALIGNS.items() if v == self.row_valign_var.get())))
        self._reset_button(row, "row_align", "row_valign").pack(side="left", padx=(6, 0))
        # The owner, 2026-10-09: "a max # of portraits per row ... to make the tree more compact".
        limit_row = ttk.Frame(tab)
        limit_row.pack(anchor="w", pady=(6, 0))
        ttk.Label(limit_row, text="Most portraits in a row (0 = no limit):").pack(side="left")
        self.row_limit_var = tk.StringVar(value=str(e.row_limit))
        self._live(ttk.Spinbox(limit_row, textvariable=self.row_limit_var, from_=0, to=ft.ROW_LIMIT_MAX, width=4),
                   self._row_limit).pack(side="left", padx=(6, 4))
        self._reset_button(limit_row, "row_limit", "keep_families").pack(side="left", padx=(0, 12))
        self.keep_families_var = tk.BooleanVar(value=e.keep_families)
        ttk.Checkbutton(limit_row, text="Keep families together", variable=self.keep_families_var,
                        command=lambda: self._change(keep_families=bool(self.keep_families_var.get()))).pack(side="left")
        # The owner's hand-made tree, 2026-10-09: the unrelated members "in a compact 2-column grid down
        # the left edge".
        others_row = ttk.Frame(tab)
        others_row.pack(anchor="w", pady=(6, 0))
        ttk.Label(others_row, text="Other Members: columns").pack(side="left")
        self.others_columns_var = tk.StringVar(value=str(e.others_columns))
        self._live(ttk.Spinbox(others_row, textvariable=self.others_columns_var, from_=1, to=ft.OTHERS_COLUMNS_MAX,
                               width=3), self._others_columns).pack(side="left", padx=(6, 12))
        self.others_side_var = tk.StringVar(value=ft.OTHERS_SIDES[e.others_side])
        side = ttk.Combobox(others_row, textvariable=self.others_side_var, values=list(ft.OTHERS_SIDES.values()),
                            state="readonly", width=12)
        side.pack(side="left")
        self._reset_button(others_row, "others_columns", "others_side").pack(side="left", padx=(6, 0))
        side.bind("<<ComboboxSelected>>", lambda _e: self._change(
            others_side=next(k for k, v in ft.OTHERS_SIDES.items() if v == self.others_side_var.get())))
        # The owner, 2026-10-09: "there should be a toggle for lines run behind portraits".  Reset: the
        # tree's own choice again (behind only when a Packed layout is packed 98 or more).
        behind_row = ttk.Frame(tab)
        behind_row.pack(anchor="w", pady=(6, 0))
        self.lines_behind_var = tk.BooleanVar(value=ft.behind(e))
        ttk.Checkbutton(behind_row, text="Lines run behind portraits", variable=self.lines_behind_var,
                        command=lambda: self._change(lines_behind=bool(self.lines_behind_var.get()))).pack(side="left")
        ttk.Button(behind_row, text="Reset", width=6,
                   command=lambda: (self._change(lines_behind=None), self._show_packing())).pack(side="left", padx=(8, 0))
        tab = t_words
        # The owner, 2026-10-09: the portrait's face and words options together, "Portrait pictures/text".
        words = ttk.LabelFrame(tab, text="Faces and words in every portrait", padding=6)
        words.pack(fill="x", pady=(10, 0))
        # The owner, 2026-10-09: "make all these options by group" -- everyone's, or one group's own.
        self.scope_var = tk.StringVar(value=EVERYONE)
        self.scope_note = tk.StringVar(value="")
        self._scope_picker(words).pack(anchor="w", fill="x", pady=(0, 6))
        # The owner, 2026-10-09: "justify text (left right center + top middle bottom)".
        row = ttk.Frame(words)
        row.pack(anchor="w")
        ttk.Label(row, text="Align text:").pack(side="left")
        self.align_var = tk.StringVar(value=ft.TEXT_ALIGNS[e.text_align])
        across = ttk.Combobox(row, textvariable=self.align_var, values=list(ft.TEXT_ALIGNS.values()),
                              state="readonly", width=7)
        across.pack(side="left", padx=(6, 0))
        across.bind("<<ComboboxSelected>>", lambda _e: self._change(
            text_align=next(k for k, v in ft.TEXT_ALIGNS.items() if v == self.align_var.get())))
        ttk.Label(row, text="Face and text sit at the:").pack(side="left", padx=(8, 0))
        row2 = ttk.Frame(words)
        row2.pack(anchor="w", pady=(4, 0))
        ttk.Label(row2, text="Text area:").pack(side="left")
        self.room_var = tk.StringVar(value=ft.TEXT_ROOMS[e.text_room])
        room = ttk.Combobox(row2, textvariable=self.room_var, values=ft.alphabetical(ft.TEXT_ROOMS.values()), state="readonly",
                            width=16)
        room.pack(side="left", padx=(6, 0))
        room.bind("<<ComboboxSelected>>", lambda _e: self._change(
            text_room=next(k for k, v in ft.TEXT_ROOMS.items() if v == self.room_var.get())))
        self._reset_button(row2, "text_room").pack(side="left", padx=(6, 0))
        self.flip_words_var = tk.BooleanVar(value=e.flip_words)          # the owner, 2026-10-09
        ttk.Checkbutton(words, text="Mirror text with a flipped portrait", variable=self.flip_words_var,
                        command=lambda: self._change(flip_words=bool(self.flip_words_var.get()))).pack(anchor="w")
        self.turn_words_var = tk.BooleanVar(value=e.turn_words)          # the owner, 2026-10-09
        ttk.Checkbutton(words, text="Turn text with a turned portrait (the face stays upright)",
                        variable=self.turn_words_var,
                        command=lambda: self._change(turn_words=bool(self.turn_words_var.get()))).pack(anchor="w")
        self.inside_var = tk.BooleanVar(value=e.text_inside)
        ttk.Checkbutton(words, text="Keep text inside the shape",
                        variable=self.inside_var,
                        command=lambda: self._change(text_inside=bool(self.inside_var.get()))).pack(anchor="w")
        # The owner, 2026-10-09: the males' turtle shells drew faces and words a quarter smaller than the
        # females' leaves -- one size for everyone, whatever the shape and size.
        fixed_row = ttk.Frame(words)
        fixed_row.pack(anchor="w")
        self.fixed_face_var = tk.BooleanVar(value=e.fixed_face_size)
        ttk.Checkbutton(fixed_row, text="Faces and words keep one size, whatever the portrait's shape and size",
                        variable=self.fixed_face_var,
                        command=lambda: self._change(fixed_face_size=bool(self.fixed_face_var.get()))).pack(side="left")
        self._reset_button(fixed_row, "fixed_face_size").pack(side="left", padx=(6, 0))
        self.valign_var = tk.StringVar(value=ft.TEXT_VALIGNS[e.text_valign])
        down = ttk.Combobox(row, textvariable=self.valign_var, values=list(ft.TEXT_VALIGNS.values()),
                            state="readonly", width=7)
        down.pack(side="left", padx=(6, 0))
        down.bind("<<ComboboxSelected>>", lambda _e: self._valign(
            next(k for k, v in ft.TEXT_VALIGNS.items() if v == self.valign_var.get())))
        self._reset_button(row, "text_align", "text_valign", "centre_heads").pack(side="left", padx=(6, 0))
        # The owner, 2026-10-09: "i want to be able to resize the villager's picture and text within the
        # shape" -- every portrait's here, each villager's own on the Selected tab.
        row = ttk.Frame(words)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Face size (%):").pack(side="left")
        self.picture_size_var = tk.StringVar(value=f"{e.picture_size:g}")
        self._live(ttk.Spinbox(row, textvariable=self.picture_size_var, from_=ft.PICTURE_SCALE_MIN,
                               to=ft.PICTURE_SCALE_MAX, increment=10, width=5),
                   lambda: self._detail_number("picture_size", self.picture_size_var, ft.PICTURE_SCALE_MIN,
                                               ft.PICTURE_SCALE_MAX)).pack(side="left", padx=(6, 0))
        self._reset_button(row, "picture_size").pack(side="left", padx=(4, 12))
        ttk.Label(row, text="Text size (%):").pack(side="left")
        self.text_size_var = tk.StringVar(value=f"{e.text_size:g}")
        self._live(ttk.Spinbox(row, textvariable=self.text_size_var, from_=ft.TEXT_SCALE_MIN,
                               to=ft.TEXT_SCALE_MAX, increment=10, width=5),
                   lambda: self._detail_number("text_size", self.text_size_var, ft.TEXT_SCALE_MIN,
                                               ft.TEXT_SCALE_MAX)).pack(side="left", padx=(6, 0))
        self._reset_button(row, "text_size").pack(side="left", padx=(4, 0))
        row = ttk.Frame(words)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Same face and text size for:").pack(side="left")
        ttk.Button(row, text="Everyone", command=lambda: self._equalize(None)).pack(side="left", padx=(6, 0))
        for group, label in ft.GROUPS.items():
            ttk.Button(row, text=label, command=lambda g=group: self._equalize(g)).pack(side="left", padx=(4, 0))
        # The owner, 2026-10-08: the words in a portrait spread wider, adjustable.
        row = ttk.Frame(words)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Characters per line:").pack(side="left")
        self.wrap_var = tk.StringVar(value=str(e.text_wrap))
        wrap_spin = self._live(ttk.Spinbox(row, textvariable=self.wrap_var, from_=ft.WRAP_MIN, to=ft.WRAP_MAX,
                                           width=4), self._text_wrap)
        wrap_spin.bind("<KeyRelease>", lambda _e: self._text_wrap())      # in real time, as typed (the owner)
        wrap_spin.bind("<MouseWheel>", lambda e: (self.wrap_var.set(str(max(ft.WRAP_MIN, min(
            ft.WRAP_MAX, self._view().text_wrap + (1 if e.delta > 0 else -1))))), self._text_wrap(), "break")[-1])
        wrap_spin.pack(side="left", padx=(6, 0))
        self._reset_button(row, "text_wrap").pack(side="left", padx=(6, 0))
        tab = l_spacing
        # The owner, 2026-10-08: the spacing between portraits batch-editable, and portraits and their
        # words shrinking by themselves to fit many to a page.
        # The owner, 2026-10-09: "controls for horizontal/vertical portrait clustering and amount in
        # pixels" -- how close portraits sit side by side, and how close the generations stack.
        box = ttk.LabelFrame(tab, text="Spacing", padding=6)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(box, text="Side by side (pixels):").grid(row=0, column=0, sticky="w")
        self.gap_var = tk.StringVar(value=f"{e.portrait_gap:g}")
        self._live(ttk.Spinbox(box, textvariable=self.gap_var, from_=ft.GAP_MIN, to=ft.GAP_MAX, increment=2, width=5),
                   self._portrait_gap).grid(row=0, column=1, sticky="w", padx=(6, 0))
        self._reset_button(box, "portrait_gap").grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Label(box, text="Between generations (pixels):").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.row_gap_var = tk.StringVar(value=f"{e.row_gap:g}")
        self._live(ttk.Spinbox(box, textvariable=self.row_gap_var, from_=ft.ROW_GAP_MIN, to=ft.ROW_GAP_MAX, increment=2,
                               width=5), self._row_gap).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
        self._reset_button(box, "row_gap").grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(4, 0))
        tab = l_page_size
        row = ttk.Frame(tab)
        row.pack(anchor="w")
        ttk.Label(row, text=f"Generations per page ({ft.PAGE_GENS_MIN}-{ft.PAGE_GENS_MAX}):").pack(side="left")
        self.page_gens_var = tk.StringVar(value=str(e.page_generations))
        self._live(ttk.Spinbox(row, textvariable=self.page_gens_var, from_=ft.PAGE_GENS_MIN, to=ft.PAGE_GENS_MAX,
                               width=4), self._page_generations).pack(side="left", padx=(6, 0))
        self._reset_button(row, "page_generations").pack(side="left", padx=(6, 0))
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Shrink portraits to fit a width of (pixels, 0 = off):").pack(side="left")
        self.portrait_fit_var = tk.StringVar(value=str(e.fit_width))      # not fit_var: the background picture's (Codex, #575)
        self._live(ttk.Spinbox(row, textvariable=self.portrait_fit_var, from_=0, to=ft.FIT_MAX, increment=200, width=7),
                   self._fit_width).pack(side="left", padx=(6, 0))
        self._reset_button(row, "fit_width").pack(side="left", padx=(6, 0))
        self.units_var = tk.BooleanVar(value=e.show_units)
        ttk.Checkbutton(words, text="Show age in age units (twentieths of a year)", variable=self.units_var,
                        command=lambda: self._change(show_units=bool(self.units_var.get()))).pack(anchor="w")
        self.years_var = tk.BooleanVar(value=e.show_years)
        ttk.Checkbutton(words, text="Show age in years", variable=self.years_var,
                        command=lambda: self._change(show_years=bool(self.years_var.get()))).pack(anchor="w")
        # The special descriptors after the age, each where it applies (the owner, 2026-10-22: "villagers get
        # auto-denoted with special descriptors if applicable (tribal chief, founder, runner etc)"): ticked
        # unless the player unticks them.  "X's twin/triplet" (2026-10-09), Founder (2026-10-09), Runner
        # (2026-10-10), how they arrived; then each special villager status of this game.
        box = ttk.LabelFrame(words, text="Special descriptors (shown where they apply)", padding=4)
        box.pack(fill="x", anchor="w", pady=(4, 0))
        self.descriptor_vars: dict[str, tk.BooleanVar] = {}
        for attr, text in ft.DESCRIPTOR_OPTIONS:
            var = self.descriptor_vars[attr] = tk.BooleanVar(value=getattr(e, attr))
            ttk.Checkbutton(box, text=text, variable=var,
                            command=lambda attr=attr, var=var: self._change(**{attr: bool(var.get())})).pack(anchor="w")
        self.twins_var, self.founder_var, self.runner_var = (self.descriptor_vars[k] for k in
                                                             ("show_twins", "show_founder", "show_runner"))
        # A special villager status's words and its mark are one (ft.set_status_option).
        self.status_checks = ttk.Frame(box)
        self.status_checks.pack(fill="x", anchor="w")
        self.status_check_vars: dict[str, tk.BooleanVar] = {}
        # The owner, 2026-10-10: "add a button to retroactively update that text too".
        ttk.Button(words, text="Bold and italic for extra lines (Founder, Heir, twins...)",
                   command=self._bold_italic_extra_lines).pack(anchor="w", pady=(4, 0))
        ttk.Button(words, text="Add status labels (Deceased, No longer in the house) to the portraits",
                   command=self._add_status_labels).pack(anchor="w", pady=(4, 0))
        tab = t_colour
        ttk.Label(tab, text="Every word on the tree (a part's own colour: Fonts tab):").pack(anchor="w", pady=(0, 1))
        self.ink_field = ColourField(tab, e.ink, lambda c: self._change(ink=c))
        self.ink_field.pack(anchor="w")
        # The owner, 2026-10-23: a box behind each portrait's name and age words -- its colour, how solid
        # it is (0 %: none, as a tree has it), and whether it is drawn over the shapes.  By group.
        tab = t_box
        self._scope_picker(tab).pack(anchor="w", fill="x", pady=(0, 6))
        # Each row wraps in a narrow panel (flow_row) rather than cutting its last buttons off.
        row = ttk.Frame(tab)
        row.pack(anchor="w", fill="x")
        ttk.Label(row, text="Colour:").pack(side="left")
        self.text_box_field = ColourField(row, e.text_box_colour, lambda c: self._change(text_box_colour=c or "#ffffff"))
        self.text_box_field.pack(side="left", padx=(6, 0))
        self._reset_button(row, "text_box_colour").pack(side="left", padx=(6, 0))
        flow_row(row)
        row = ttk.Frame(tab)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(row, text="Opacity (%, 0: no box):").pack(side="left")
        self.text_box_opacity_var = tk.StringVar(value=f"{e.text_box_opacity:g}")
        self._live(ttk.Spinbox(row, textvariable=self.text_box_opacity_var, from_=0, to=100, increment=5, width=5),
                   lambda: self._detail_number("text_box_opacity", self.text_box_opacity_var, 0, 100)).pack(
            side="left", padx=(6, 0))
        self._reset_button(row, "text_box_opacity").pack(side="left", padx=(6, 0))
        flow_row(row)
        self.text_box_over_var = tk.BooleanVar(value=e.text_box_over)
        ttk.Checkbutton(tab, text="Draw the box over the shapes (leaves, tails, flowers...)",
                        variable=self.text_box_over_var,
                        command=lambda: self._change(text_box_over=bool(self.text_box_over_var.get()))).pack(
            anchor="w", pady=(4, 0))
        # The owner: "border options for the text boxes, like the portrait shapes" -- the portraits' border
        # choices (the special rope and vines too), a weight (0: none, as a tree has it) and a colour
        # (Automatic: the portrait's own); for the group picked in "Settings for:" above.
        box = ttk.LabelFrame(tab, text="Text box border", padding=6)
        box.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(anchor="w", fill="x")
        ttk.Label(row, text="Border:").pack(side="left")
        self.text_box_border_var = tk.StringVar(value=ft.BORDERS[e.text_box_border])
        kind = ttk.Combobox(row, textvariable=self.text_box_border_var, values=ft.alphabetical(ft.BORDERS.values()),
                            state="readonly", width=18)
        kind.pack(side="left", padx=(6, 0))
        kind.bind("<<ComboboxSelected>>", lambda _e: self._change(text_box_border=next(
            k for k, n in ft.BORDERS.items() if n == self.text_box_border_var.get())))
        self.text_box_kind = kind
        ttk.Label(row, text="Weight (0: none):").pack(side="left", padx=(10, 0))
        self.text_box_border_width_var = tk.StringVar(value=f"{e.text_box_border_width:g}")
        self._live(ttk.Spinbox(row, textvariable=self.text_box_border_width_var, from_=0,
                               to=ft.TEXT_BOX_BORDER_WIDTHS[1], increment=0.5, width=5),
                   lambda: self._detail_number("text_box_border_width", self.text_box_border_width_var,
                                               *ft.TEXT_BOX_BORDER_WIDTHS)).pack(side="left", padx=(6, 0))
        self._reset_button(row, "text_box_border", "text_box_border_width").pack(side="left", padx=(6, 0))
        flow_row(row, natural=False)
        row = ttk.Frame(box)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(row, text="Colour (Automatic: the portrait's):").pack(side="left")
        self.text_box_border_field = ColourField(row, e.text_box_border_colour,
                                                 lambda c: self._change(text_box_border_colour=c or ""))
        self.text_box_border_field.pack(side="left", padx=(6, 0))
        self._reset_button(row, "text_box_border_colour").pack(side="left", padx=(6, 0))
        flow_row(row, natural=False)
        ttk.Label(box, text="Special borders take the rope and vine colours (Shapes tab).", foreground="#555555",
                  wraplength=360, justify="left").pack(anchor="w", pady=(4, 0))
        tab = p_colour
        self._scope_picker(tab).pack(anchor="w", fill="x", pady=(0, 6))
        ttk.Label(tab, text="Inside every portrait:").pack(anchor="w", pady=(0, 1))
        self.fill_field = ColourField(tab, e.portrait_fill, lambda c: self._change(portrait_fill=c or "#ffffff"))
        self.fill_field.pack(anchor="w")
        tab = l_opacity                         # how see-through each part of the tree is
        box = ttk.LabelFrame(tab, text="Opacity", padding=6)
        box.pack(fill="x", pady=(12, 0))
        self.opacity_vars: dict[str, ttk.Scale] = {}
        for row_no, (part, (label, default)) in enumerate(ft.OPACITY.items()):
            shown = tk.StringVar(value=f"{label}: {e.opacity.get(part, default)}%")
            ttk.Label(box, textvariable=shown, width=26).grid(row=row_no, column=0, sticky="w")
            scale = ttk.Scale(box, from_=0, to=100, orient="horizontal",
                              command=lambda value, s=shown, n=label: s.set(f"{n}: {int(float(value))}%"))
            scale.set(e.opacity.get(part, default))
            scale.grid(row=row_no, column=1, sticky="ew", padx=(6, 0))
            scale.bind("<ButtonRelease-1>", lambda _e, part=part, s=scale: self._set_opacity(part, int(s.get())))
            scale.bind("<KeyRelease>", lambda _e, part=part, s=scale: self._set_opacity(part, int(s.get())))
            self.opacity_vars[part] = scale
        box.columnconfigure(1, weight=1)
        tab = p_shape
        box = ttk.LabelFrame(tab, text="Shape and border (by group)", padding=6)
        box.pack(fill="x", pady=(12, 0))
        self.group_vars: dict[tuple[str, str], tk.StringVar] = {}
        widest = max(len(label) for label in ft.GROUPS.values()) + 1
        for group, label in ft.GROUPS.items():
            row = ttk.Frame(box)                # wraps in a narrow panel (flow_row)
            row.pack(anchor="w", fill="x", pady=1)
            ttk.Label(row, text=label + ":", width=widest).pack(side="left")
            for attr, choices in (("shapes", ft.PORTRAIT_SHAPES), ("borders", ft.BORDERS)):
                var = tk.StringVar(value=choices[getattr(e, attr)[group]])
                self.group_vars[(attr, group)] = var
                combo = ttk.Combobox(row, textvariable=var, values=ft.alphabetical(choices.values()), state="readonly", width=16)
                combo.pack(side="left", padx=(6, 0))
                combo.bind("<<ComboboxSelected>>", lambda _e, a=attr, g=group, c=choices, v=var: self._group_style(
                    a, g, next(k for k, n in c.items() if n == v.get())))
            # The owner, 2026-10-08: change ALL male, female or unborn portraits at once -- the ones
            # given their own shape or border one by one too.
            ttk.Button(row, text="Apply to all", command=lambda g=group: self._group_all(g)).pack(
                side="left", padx=(6, 0))
            flow_row(row, natural=False)
        # The owner, 2026-10-09: "batch rotate/transform portraits by group" -- every portrait of a group
        # flipped or turned at once (each villager's own flip and turn, so any can still be changed alone).
        box = ttk.LabelFrame(tab, text="Flip and turn (by group)", padding=6)
        box.pack(fill="x", pady=(10, 0))
        self.group_turns: dict[str, tk.StringVar] = {}
        for row_no, (group, label) in enumerate(ft.GROUPS.items()):
            ttk.Label(box, text=label + ":").grid(row=row_no, column=0, sticky="w", pady=1)
            ttk.Button(box, text="Flip ↔", width=7, command=lambda g=group: self._group_flip(g, "flip_h")).grid(
                row=row_no, column=1, sticky="w", padx=(6, 0), pady=1)
            ttk.Button(box, text="Flip ↕", width=7, command=lambda g=group: self._group_flip(g, "flip_v")).grid(
                row=row_no, column=2, sticky="w", padx=(4, 0), pady=1)
            var = tk.StringVar(value="0")
            ttk.Spinbox(box, textvariable=var, from_=0, to=345, increment=15, width=5, wrap=True).grid(
                row=row_no, column=3, sticky="w", padx=(10, 0), pady=1)
            ttk.Button(box, text="Turn (°)", command=lambda g=group: self._group_turn(g)).grid(
                row=row_no, column=4, sticky="w", padx=(4, 0), pady=1)
            ttk.Button(box, text="Reset", command=lambda g=group: self._group_unturn(g)).grid(
                row=row_no, column=5, sticky="w", padx=(4, 0), pady=1)
            self.group_turns[group] = var
        # The owner, 2026-10-09: detailing inside the shapes, its colour, opacity and line weight.
        tab = p_details
        box = ttk.LabelFrame(tab, text="Detail lines (shells, stars, flowers...)", padding=6)
        box.pack(fill="x", pady=(12, 0))
        # A row each, wrapping in a narrow panel (flow_row) rather than running past its edge.
        self._scope_picker(box).pack(anchor="w", fill="x", pady=(0, 6))
        self.detail_var = tk.BooleanVar(value=e.detail_lines)
        ttk.Checkbutton(box, text="Show detail lines", variable=self.detail_var,
                        command=lambda: self._change(detail_lines=bool(self.detail_var.get()))).pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(row, text="Colour (Automatic: the border's):").pack(side="left")
        self.detail_field = ColourField(row, e.detail_colour, lambda c: self._change(detail_colour=c or ""))
        self.detail_field.pack(side="left", padx=(6, 0))
        flow_row(row, natural=False)
        row = ttk.Frame(box)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(row, text="Opacity (%):").pack(side="left")
        self.detail_opacity_var = tk.StringVar(value=f"{e.detail_opacity:g}")
        self._live(ttk.Spinbox(row, textvariable=self.detail_opacity_var, from_=0, to=100, increment=5, width=5),
                   lambda: self._detail_number("detail_opacity", self.detail_opacity_var, 0, 100)).pack(
            side="left", padx=(6, 0))
        self._reset_button(row, "detail_opacity").pack(side="left", padx=(6, 0))
        ttk.Label(row, text="Line weight:").pack(side="left", padx=(12, 0))
        self.detail_width_var = tk.StringVar(value=f"{e.detail_width:g}")
        self._live(ttk.Spinbox(row, textvariable=self.detail_width_var, values=ft.LINE_STEPS, width=5),
                   lambda: self._detail_number("detail_width", self.detail_width_var, *ft.LINE_WIDTHS)).pack(
            side="left", padx=(6, 0))
        self._reset_button(row, "detail_width").pack(side="left", padx=(6, 0))
        flow_row(row, natural=False)
        # The owner, 2026-10-09: the special borders' colours -- natural, rainbow flowers, picked for each
        # part, or 2-7 colours by turns or as a gradient.
        tab = p_special
        box = ttk.LabelFrame(tab, text="Rope and vine colours (special borders)", padding=6)
        box.pack(fill="x", pady=(12, 0))
        self.special_mode_var = tk.StringVar(value=ft.SPECIAL_COLOUR_MODES[e.special_mode])
        mode = ttk.Combobox(box, textvariable=self.special_mode_var, values=ft.alphabetical(ft.SPECIAL_COLOUR_MODES.values()),
                            state="readonly", width=20)
        mode.grid(row=0, column=0, columnspan=2, sticky="w")
        mode.bind("<<ComboboxSelected>>", lambda _e: self._change(
            special_mode=next(k for k, v in ft.SPECIAL_COLOUR_MODES.items() if v == self.special_mode_var.get())))
        # The owner, 2026-10-09: the natural flowers' colour.
        ttk.Label(box, text="Natural flowers:").grid(row=0, column=2, sticky="e", padx=(8, 4))
        self.hibiscus_var = tk.StringVar(value=ft.HIBISCUS_CHOICES[e.hibiscus])
        flower = ttk.Combobox(box, textvariable=self.hibiscus_var, values=ft.alphabetical(ft.HIBISCUS_CHOICES.values()),
                              state="readonly", width=20)
        flower.grid(row=0, column=3, sticky="w")
        flower.bind("<<ComboboxSelected>>", lambda _e: self._change(
            hibiscus=next(k for k, v in ft.HIBISCUS_CHOICES.items() if v == self.hibiscus_var.get())))
        ttk.Label(box, text="Pick colours (each part):").grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        # Side by side when there is room, else one under another (two to a row ran past the panel's edge).
        self.special_pick_fields = {}
        picks = ttk.Frame(box)
        picks.grid(row=2, column=0, rowspan=2, columnspan=4, sticky="ew")
        for part, words in ft.SPECIAL_PARTS.items():
            pair = ttk.Frame(picks)
            pair.pack(side="left", padx=(0, 8))
            ttk.Label(pair, text=words, width=max(len(w) for w in ft.SPECIAL_PARTS.values())).pack(side="left")
            fieldw = ColourField(pair, e.special_pick.get(part, ft.NATURAL[part]),
                                 lambda c, part=part: self._special_pick(part, c), allow_default=False)
            fieldw.pack(side="left", padx=(4, 0))
            self.special_pick_fields[part] = fieldw
        flow_row(picks, natural=False)
        box.columnconfigure(3, weight=1)
        row = ttk.Frame(box)
        row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(row, text="Alternating or gradient colours, how many (2-7):").pack(side="left")
        self.special_count_var = tk.StringVar(value=str(e.special_count))
        self._live(ttk.Spinbox(row, textvariable=self.special_count_var, from_=2, to=7, width=3),
                   self._special_count).pack(side="left", padx=(4, 0))
        row = ttk.Frame(box)
        row.grid(row=9, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(row, text="Rainbow strength:").pack(side="left")              # the owner, 2026-10-09
        self.rainbow_var = tk.StringVar(value=ft.RAINBOW_STRENGTHS[e.rainbow_strength][0])
        strength = ttk.Combobox(row, textvariable=self.rainbow_var, state="readonly", width=8,
                                values=[words for words, _f in ft.RAINBOW_STRENGTHS.values()])
        strength.pack(side="left", padx=(4, 10))
        strength.bind("<<ComboboxSelected>>", lambda _e: self._change(rainbow_strength=next(
            k for k, (words, _f) in ft.RAINBOW_STRENGTHS.items() if words == self.rainbow_var.get())))
        ttk.Label(row, text="Opacity (%):").pack(side="left")          # the owner, 2026-10-09
        self.special_opacity_var = tk.StringVar(value=f"{e.special_opacity:g}")
        self._live(ttk.Spinbox(row, textvariable=self.special_opacity_var, from_=0, to=100, increment=5, width=5),
                   lambda: self._detail_number("special_opacity", self.special_opacity_var, 0, 100)).pack(
            side="left", padx=(4, 0))
        self._reset_button(row, "rainbow_strength", "special_opacity").pack(side="left", padx=(6, 0))
        self.special_palette_fields = []
        palette = ttk.Frame(box)
        palette.grid(row=5, column=0, rowspan=4, columnspan=4, sticky="ew", pady=1)
        for k in range(7):
            fieldw = ColourField(palette, e.special_palette[k], lambda c, k=k: self._special_palette(k, c),
                                 allow_default=False)
            fieldw.pack(side="left", padx=(0, 8))
            self.special_palette_fields.append(fieldw)
        flow_row(palette, natural=False)
        # The owner, 2026-10-09: rainbow and alternating colours for the special marks, plain portrait
        # borders, portrait insides, family lines and detail lines too.
        tab = p_schemes
        box = ttk.LabelFrame(tab, text="Rainbow and alternating colours", padding=6)
        box.pack(fill="x", pady=(12, 0))
        self.scheme_vars: dict[str, tk.StringVar] = {}
        # Two to a line when there is room, else one (side by side they ran past a narrow panel's edge).
        pairs = ttk.Frame(box)
        pairs.pack(anchor="w", fill="x")
        widest = max(len(words) for words in ft.SCHEME_PARTS.values()) + 1
        for part, words in ft.SCHEME_PARTS.items():
            pair = ttk.Frame(pairs)
            pair.pack(side="left", padx=(0, 10))
            ttk.Label(pair, text=words + ":", width=widest).pack(side="left")
            var = tk.StringVar(value=ft.COLOUR_SCHEMES[e.schemes.get(part, "own")])
            pick = ttk.Combobox(pair, textvariable=var, values=list(ft.COLOUR_SCHEMES.values()), state="readonly",
                                width=18)
            pick.pack(side="left", padx=(4, 0), pady=1)
            pick.bind("<<ComboboxSelected>>", lambda _e, part=part: self._scheme(part))
            self.scheme_vars[part] = var
        flow_row(pairs, natural=False)
        note = ttk.Label(box, text="The rainbow strength and the alternating colours are set below, under Rope and vine "
                                   "colours.  A family member's own inside or detail colour still wins.",
                         foreground="#555555", justify="left")
        note.pack(anchor="w", fill="x", pady=(4, 0))
        note.bind("<Configure>", lambda ev: note.configure(wraplength=max(120, ev.width - 4)))
        tab = p_size
        box = ttk.LabelFrame(tab, text="Size (by group)", padding=6)
        box.pack(fill="x", pady=(12, 0))
        self.group_sizes: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        for row_no, (group, label) in enumerate(ft.GROUPS.items()):
            ttk.Label(box, text=label + ":").grid(row=row_no, column=0, sticky="w", pady=1)
            pair = (tk.StringVar(), tk.StringVar())
            for col, var in enumerate(pair, 1):
                self._live(ttk.Spinbox(box, textvariable=var, values=ft.SIZE_STEPS, width=6),
                           lambda g=group, a=col - 1: self._group_size(g, axis=a)).grid(
                    row=row_no, column=col, sticky="w", padx=(4, 0))
            ttk.Button(box, text="Default size", command=lambda g=group: self._group_size(g, reset=True)).grid(
                row=row_no, column=3, sticky="w", padx=(6, 0))
            self.group_sizes[group] = pair
        ttk.Label(box, text="width and height").grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Checkbutton(box, text="Keep aspect ratio", variable=self.lock_shape).grid(row=3, column=3, sticky="w",
                                                                                     padx=(6, 0))
        ttk.Button(box, text="Everyone back to their group's size", command=self._equalize_sizes).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self._show_group_sizes()
        tab = l_label_line
        box = ttk.LabelFrame(tab, text="Line beside generation labels", padding=6)
        box.pack(fill="x", pady=(12, 0))
        ttk.Label(box, text="Weight:").pack(side="left")
        self.label_w_var = tk.StringVar(value=f"{e.label_line_width:g}")
        self._live(ttk.Spinbox(box, textvariable=self.label_w_var, values=ft.LINE_STEPS, width=5),
                   lambda: self._label_line("label_line_width", self.label_w_var, *ft.LINE_WIDTHS)).pack(
            side="left", padx=(2, 0))
        ttk.Label(box, text="  Longer by:").pack(side="left")
        self.label_reach_var = tk.StringVar(value=f"{e.label_line_reach:g}")
        self._live(ttk.Spinbox(box, textvariable=self.label_reach_var, values=(0,) + ft.SIZE_STEPS, width=5),
                   lambda: self._label_line("label_line_reach", self.label_reach_var, 0.0, 1000.0)).pack(
            side="left", padx=(2, 0))
        ttk.Label(box, text="at each end").pack(side="left", padx=(2, 0))
        tab = l_lines
        box = ttk.LabelFrame(tab, text="Family lines", padding=6)
        box.pack(fill="x", pady=(12, 0))
        ttk.Label(box, text="Weight:").pack(side="left")
        self.line_w_var = tk.StringVar(value=f"{e.line_width:g}")
        self._live(ttk.Spinbox(box, textvariable=self.line_w_var, values=ft.LINE_STEPS, width=5),
                   self._line_weight).pack(side="left", padx=(2, 0))
        self.line_dash_var = tk.StringVar(value=ft.LINE_TYPES[e.line_dash])
        kind = ttk.Combobox(box, textvariable=self.line_dash_var, values=ft.alphabetical(ft.LINE_TYPES.values()),
                            state="readonly", width=16)
        kind.pack(side="left", padx=(6, 0))
        kind.bind("<<ComboboxSelected>>", lambda _e: self._change(
            line_dash=next(k for k, v in ft.LINE_TYPES.items() if v == self.line_dash_var.get())))
        # Each family's lines in a colour of their own (the owner, 2026-10-09: "auto-coloring family lines
        # ... distinct from other line colors and not blend into the background"); lines only, the
        # children's portraits keep their family's colour.  Right-click a line to change one by hand.
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 0))
        # Line colours: Default / Auto / Rainbow / Gradient / Range (the owner, 2026-10-10), the order the
        # colours run across the tree, the Gradient's two ends and the Range's base colours.
        ttk.Label(row, text="Line colours:").pack(side="left")
        self.line_mode_var = tk.StringVar(value=ft.LINE_MODES[e.line_mode])
        mode = ttk.Combobox(row, textvariable=self.line_mode_var, values=list(ft.LINE_MODES.values()),
                            state="readonly", width=26)
        mode.pack(side="left", padx=(4, 0))
        mode.bind("<<ComboboxSelected>>", lambda _e: self._line_mode_picked())
        ttk.Button(row, text="Reset to family colours", command=self._reset_line_colours).pack(side="left",
                                                                                              padx=(6, 0))
        self.line_opts = ttk.Frame(tab)
        self.line_opts.pack(fill="x", pady=(4, 0))
        self.line_order_row = ttk.Frame(self.line_opts)
        ttk.Label(self.line_order_row, text="Order colours by:").pack(side="left")
        self.line_order_var = tk.StringVar(value=ft.LINE_ORDERS[e.line_order])
        order = ttk.Combobox(self.line_order_row, textvariable=self.line_order_var,
                             values=list(ft.LINE_ORDERS.values()), state="readonly", width=16)
        order.pack(side="left", padx=(4, 0))
        order.bind("<<ComboboxSelected>>", lambda _e: self._line_option(line_order=next(
            k for k, v in ft.LINE_ORDERS.items() if v == self.line_order_var.get())))
        self.line_reverse_var = tk.BooleanVar(value=e.line_reverse)
        ttk.Checkbutton(self.line_order_row, text="Reverse", variable=self.line_reverse_var,
                        command=lambda: self._line_option(line_reverse=bool(self.line_reverse_var.get()))).pack(
            side="left", padx=(8, 0))
        self.gradient_row = ttk.Frame(self.line_opts)
        ttk.Label(self.gradient_row, text="Gradient from").pack(side="left")
        self.gradient_start_btn = tk.Button(self.gradient_row, width=4, command=lambda: self._gradient_end("start"))
        self.gradient_start_btn.pack(side="left", padx=(4, 4))
        ttk.Label(self.gradient_row, text="to").pack(side="left")
        self.gradient_end_btn = tk.Button(self.gradient_row, width=4, command=lambda: self._gradient_end("end"))
        self.gradient_end_btn.pack(side="left", padx=(4, 0))
        self.range_row = ttk.Frame(self.line_opts)
        ttk.Label(self.range_row, text="Base colours (click to pick or drop):").pack(anchor="w")
        self.range_swatches = tk.Frame(self.range_row)
        self.range_swatches.pack(anchor="w", pady=(2, 0))
        ttk.Button(self.range_row, text="Add a colour...", command=self._range_add).pack(anchor="w", pady=(2, 0))
        self._show_line_options()
        # A thin dark or white outline under lines whose own colour would blend into the background (the
        # owner, 2026-10-10: "make it an optional toggle default off").
        self.outline_var = tk.BooleanVar(value=e.outline_lines)
        ttk.Checkbutton(tab, text="Outline lines that blend into the background", variable=self.outline_var,
                        command=lambda: self._change(outline_lines=bool(self.outline_var.get()))).pack(
            anchor="w", pady=(4, 0))
        tab = l_deleted
        box = ttk.LabelFrame(tab, text="Deleted items", padding=6)
        box.pack(fill="x", pady=(12, 0))
        ttk.Label(box, text="Right-click anything on the tree to delete it.  Restore it here:",
                  wraplength=300, justify="left").pack(anchor="w")
        self.hidden_list = tk.Listbox(box, height=5, exportselection=False, selectmode="extended")
        self.hidden_list.pack(fill="x", pady=(4, 4))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        ttk.Button(row, text="Restore", command=self._restore_hidden).pack(side="left")
        ttk.Button(row, text="Restore all", command=lambda: self._restore_hidden(every=True)).pack(side="left", padx=(6, 0))
        self.hidden_keys: list[str] = []
        self.after_idle(self._refresh_hidden)
        tab = l_pages
        box = ttk.LabelFrame(tab, text="Pages", padding=6)
        box.pack(fill="x", pady=(10, 0))
        self.pages_label = tk.StringVar()
        ttk.Label(box, textvariable=self.pages_label, wraplength=320, justify="left").pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="A new page starts at generation").pack(side="left")
        self.break_var = tk.StringVar()
        ttk.Spinbox(row, textvariable=self.break_var, from_=2, to=99, width=4).pack(side="left", padx=(4, 0))
        ttk.Button(row, text="Add page", command=self._add_page_break).pack(side="left", padx=(6, 0))
        ttk.Button(box, text="Join this page onto the one before", command=self._remove_page_break).pack(
            anchor="w", pady=(4, 0))
        ttk.Label(box, text="Each page is its own tree; a child whose parents are on an earlier page starts its "
                            "page.  Saving a picture saves every page.", wraplength=320, justify="left").pack(
            anchor="w", pady=(4, 0))
        tab = l_labels
        ttk.Label(tab, text="Numbering:").pack(anchor="w", pady=(0, 1))
        self.numbering_var = tk.StringVar(value=ft.NUMBERINGS[e.numbering])
        numbering = ttk.Combobox(tab, textvariable=self.numbering_var, values=list(ft.NUMBERINGS.values()),
                                 state="readonly")
        numbering.pack(fill="x")
        numbering.bind("<<ComboboxSelected>>", lambda _e: self._change(
            numbering=next(k for k, v in ft.NUMBERINGS.items() if v == self.numbering_var.get())))
        ttk.Label(tab, text="Edit a label (right-click a line on the tree to delete it):",
                  wraplength=320, justify="left").pack(anchor="w", pady=(10, 1))
        gens = sorted({p.generation for p in self.village.people.values()})
        self.gen_var = tk.StringVar(value=gen.roman(gens[0]) if gens else "I")
        gen_box = ttk.Combobox(tab, textvariable=self.gen_var, values=[gen.roman(g) for g in gens], state="readonly", width=8)
        gen_box.pack(anchor="w")
        gen_box.bind("<<ComboboxSelected>>", lambda _e: self._show_generation())
        self.gen_text = tool_text(tab, height=4, width=34)
        self.gen_text.pack(fill="x", pady=(2, 2))
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Button(row, text="Save label", command=self._apply_generation).pack(side="left")
        ttk.Button(row, text="Reset label", command=self._restore_generation).pack(side="left", padx=(6, 0))
        self.after_idle(self._show_generation)

    def _background_tab(self) -> None:
        tab = ScrollingTab(self.notebook, "Background")
        e = self.edits
        ttk.Label(tab, text="Click a background:").pack(anchor="w")
        self.presets = ft.presets_available(self.images, self.library)
        grid = ttk.Frame(tab)
        grid.pack(anchor="w")
        self.preset_labels = self._thumb_grid(
            grid, [(name, lambda c=colour, c2=colour2, pic=picture: ft.Scene(
                96, 64, c, [ft.Backdrop(c, c2, ft.picture_path(pic, self.images, self.library), "cover", 0)]))
                   for name, colour, colour2, picture in self.presets], self._preset, (96, 64), 3)
        if len(self.presets) < len(ft.PRESETS):
            ttk.Label(tab, text="Set each game's folder on the All 5 Games tab to see its pictures here.",
                      wraplength=320, justify="left").pack(anchor="w", pady=(2, 0))
        ttk.Label(tab, text="Colour:").pack(anchor="w", pady=(10, 1))
        self.bg_field = ColourField(tab, e.background, lambda c: self._change(background=c))
        self.bg_field.pack(anchor="w")
        ttk.Label(tab, text="Second colour (fades top to bottom):").pack(anchor="w", pady=(10, 1))
        self.bg2_field = ColourField(tab, e.background2, lambda c: self._change(background2=c, rainbow=""),
                                     default_text="None")
        self.bg2_field.pack(anchor="w")
        ttk.Label(tab, text="Your own picture:").pack(anchor="w", pady=(10, 1))
        self.picture_var = tk.StringVar(value=e.background_image)
        self.picture_thumb = tk.Label(tab, bd=0, textvariable=self.picture_var, compound="top", wraplength=300)
        self.picture_thumb.pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Choose...", command=self._choose_picture).pack(side="left")
        ttk.Button(row, text="Remove", command=lambda: self._change(background_image="")).pack(side="left", padx=(4, 0))
        ttk.Label(tab, text="Picture fit:").pack(anchor="w", pady=(10, 1))
        self.fit_var = tk.StringVar(value=ft.FITS[e.background_fit])
        fit = ttk.Combobox(tab, textvariable=self.fit_var, values=ft.alphabetical(ft.FITS.values()), state="readonly")
        fit.pack(fill="x")
        fit.bind("<<ComboboxSelected>>", lambda _e: self._change(
            background_fit=next(k for k, v in ft.FITS.items() if v == self.fit_var.get())))
        self.opacity_var = tk.IntVar(value=e.background_opacity)
        opacity_text = tk.StringVar()

        def show_opacity(*_a) -> None:
            opacity_text.set(f"Picture opacity: {int(self.opacity_var.get())}%")

        show_opacity()
        ttk.Label(tab, textvariable=opacity_text, wraplength=320, justify="left").pack(anchor="w", pady=(10, 1))
        scale = self.opacity_scale = ttk.Scale(tab, from_=0, to=100, orient="horizontal",
                          command=lambda value: (self.opacity_var.set(int(float(value))), show_opacity()))
        scale.set(e.background_opacity)
        scale.pack(fill="x")

        def opacity_done(_e=None) -> None:
            if int(self.opacity_var.get()) != self.edits.background_opacity:
                self._change(background_opacity=int(self.opacity_var.get()))

        scale.bind("<ButtonRelease-1>", opacity_done)
        scale.bind("<KeyRelease>", opacity_done)
        ttk.Label(tab, text="Boxes behind the words on the picture (Transparent: the picture shows through):",
                  wraplength=320, justify="left").pack(anchor="w", pady=(10, 1))
        self.plate_field = ColourField(tab, e.plate_colour, lambda c: self._change(plate_colour=c))
        self.plate_field.pack(anchor="w")
        self._canvas_controls(tab)

    # ---- the canvas size (the owner, 2026-10-09) ---------------------------------------
    CANVAS_AUTO, CANVAS_CUSTOM = "Automatic (fits the tree)", "Custom"

    def _canvas_controls(self, tab) -> None:
        """Canvas size: Automatic (the page as large as the tree), a ready-made size, or a width and
        height typed; the tree shrinks to fit a smaller canvas and is centred on a larger one."""
        ttk.Label(tab, text="Canvas size (every page; the tree shrinks to fit or is centred):",
                  wraplength=320, justify="left").pack(anchor="w", pady=(10, 1))
        row = ttk.Frame(tab)
        row.pack(anchor="w")
        self.canvas_mode_var = tk.StringVar()
        mode = ttk.Combobox(row, textvariable=self.canvas_mode_var, state="readonly", width=40,
                            values=[self.CANVAS_AUTO] + list(ft.CANVAS_SIZES) + [self.CANVAS_CUSTOM])
        mode.pack(side="left")
        mode.bind("<<ComboboxSelected>>", lambda _e: self._canvas_mode())
        self._reset_button(row, "canvas_w", "canvas_h").pack(side="left", padx=(6, 0))
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=(4, 0))
        self.canvas_w_var, self.canvas_h_var = tk.StringVar(), tk.StringVar()
        ttk.Label(row, text="Width").pack(side="left")
        self._live(ttk.Spinbox(row, textvariable=self.canvas_w_var, from_=ft.CANVAS_MIN, to=ft.CANVAS_MAX,
                               increment=100, width=7), self._canvas_typed).pack(side="left", padx=(4, 8))
        ttk.Label(row, text="x  Height").pack(side="left")
        self._live(ttk.Spinbox(row, textvariable=self.canvas_h_var, from_=ft.CANVAS_MIN, to=ft.CANVAS_MAX,
                               increment=100, width=7), self._canvas_typed).pack(side="left", padx=(4, 4))
        ttk.Label(row, text="pixels").pack(side="left")
        self._show_canvas()

    def _show_canvas(self) -> None:
        """The canvas controls showing the edits' canvas size."""
        if not hasattr(self, "canvas_mode_var"):
            return
        e = self.edits
        size = (e.canvas_w, e.canvas_h)
        if not all(size):
            self.canvas_mode_var.set(self.CANVAS_AUTO)
            self.canvas_w_var.set("")
            self.canvas_h_var.set("")
            return
        self.canvas_mode_var.set(next((name for name, s in ft.CANVAS_SIZES.items() if s == size), self.CANVAS_CUSTOM))
        self.canvas_w_var.set(str(e.canvas_w))
        self.canvas_h_var.set(str(e.canvas_h))

    def _canvas_mode(self) -> None:
        choice = self.canvas_mode_var.get()
        if choice == self.CANVAS_AUTO:
            size = (0, 0)
        elif choice in ft.CANVAS_SIZES:
            size = ft.CANVAS_SIZES[choice]
        else:                                   # Custom: what is typed, else the page as it is now
            size = self._canvas_numbers() or (int(round(self.sc.width)), int(round(self.sc.height)))
        self._set_canvas(*size)

    def _canvas_numbers(self) -> tuple[int, int] | None:
        try:
            w, h = int(float(self.canvas_w_var.get())), int(float(self.canvas_h_var.get()))
        except ValueError:
            return None
        if w < ft.CANVAS_MIN or h < ft.CANVAS_MIN:     # still being typed, or too small: nothing yet
            return None
        return min(ft.CANVAS_MAX, w), min(ft.CANVAS_MAX, h)

    def _canvas_typed(self) -> None:
        size = self._canvas_numbers()
        if size is not None:
            self._set_canvas(*size)

    def _set_canvas(self, w: int, h: int) -> None:
        """The canvas this size (0 x 0: Automatic), one step to undo."""
        if (w, h) != (self.edits.canvas_w, self.edits.canvas_h):
            self._change(everyone=True, canvas_w=int(w), canvas_h=int(h))
        self._show_canvas()

    # ---- drawing ------------------------------------------------------------
    def _scene(self) -> ft.Scene:
        self.lay, sc = self._page_scene(self.page)
        self.page = self.lay.page
        return sc

    def _page_scene(self, page: int) -> tuple[ft.Layout, ft.Scene]:
        """One page of the tree, as drawn and saved."""
        ft.arrange(self.village, self.edits)
        ft.localise_stickers(self.edits, self.village)
        lay = ft.layout(self.village, self.edits, page)
        return lay, ft.scene(lay, self.game_title, self.present, self.images, self.library)

    def _view_anchor(self) -> tuple | None:
        """What the view is on before the tree is drawn again: the first selected family member (or else
        the point in the middle of the view), and where on the window it is."""
        if not hasattr(self, "sc"):
            return None
        c = self.canvas
        q = next((q for q in self.selected if q in self.lay.x), None)
        if q is not None:
            px, py = ft.to_page(self.sc, self.lay.x[q] + ft.NODE_W / 2, self.lay.y[q] + ft.NODE_H / 2)
            return q, px * self.z - c.canvasx(0), py * self.z - c.canvasy(0)
        sx, sy = c.winfo_width() / 2, c.winfo_height() / 2
        return None, c.canvasx(sx) / self.z, c.canvasy(sy) / self.z, sx, sy

    def _keep_view(self, anchor: tuple | None) -> None:
        """The view back on what it was on (the owner: "whenever I change the portrait shape the view
        shouldn't shift somewhere else"): the tree may have grown or moved round it."""
        if anchor is None:
            return
        if anchor[0] is not None:
            q, sx, sy = anchor
            if q not in self.lay.x:
                return
            px, py = ft.to_page(self.sc, self.lay.x[q] + ft.NODE_W / 2, self.lay.y[q] + ft.NODE_H / 2)
        else:
            _none, px, py, sx, sy = anchor
        width, height = self.sc.width * self.z, self.sc.height * self.z
        self.canvas.xview_moveto(max(0.0, (px * self.z - sx) / width))
        self.canvas.yview_moveto(max(0.0, (py * self.z - sy) / height))

    def redraw(self, rescene: bool = True) -> None:
        anchor = self._view_anchor()
        self._same_scene = not rescene
        self._draw_tree()
        self._keep_view(anchor)
        self._refresh_pages()

    def _refresh_pages(self) -> None:
        """The page list on the toolbar and the Layout tab."""
        spans = ft.page_spans(self.edits, self.village)
        names = [f"{k + 1} of {len(spans)}: generation {gen.roman(lo)}" + (f" to {gen.roman(hi)}" if hi != lo else "")
                 for k, (lo, hi) in enumerate(spans)]
        # As wide as the longest name: at 22 letters "2 of 2: generation VI to VII" was cut to
        # "... VI to VI" (the owner, 2026-10-10).
        self.page_box.configure(values=names, width=max(22, max(len(n) for n in names) + 2))
        self.page_var.set(names[self.page])
        if hasattr(self, "pages_label"):
            self.pages_label.set("Pages: " + ";  ".join(names))

    def _show_page(self, page: int) -> None:
        if page == self.page or page < 0:
            return
        self.page = page
        self.selected = []
        self.obj = None
        self._draw_tree()
        self._refresh_pages()
        self._refresh_selected()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _add_page_break(self) -> None:
        """A new page from the generation typed (the owner: "MULTIPLE PAGES of the family tree")."""
        try:
            g = int(self.break_var.get())
        except ValueError:
            g = 0
        gens = sorted({p.generation for p in self.village.people.values()})
        if not gens or not gens[0] < g <= gens[-1]:
            self.status.set(f"A new page can start at generation {gens[0] + 1} to {gens[-1]}." if len(gens) > 1
                            else "This tree has one generation: it fits one page.")
            return
        if g in self.edits.pages:
            return
        self.edits.pages = sorted(self.edits.pages + [g])
        self._saved()
        self.status.set(f"Generation {gen.roman(g)} now starts a new page.  Pick the page on the toolbar.")

    def _remove_page_break(self) -> None:
        """This page joined back onto the one before it."""
        first = ft.page_spans(self.edits, self.village)[self.page][0]
        if self.page == 0 or first not in self.edits.pages:
            self.status.set("Show the page to join onto the one before it (not the first page).")
            return
        self.edits.pages = [g for g in self.edits.pages if g != first]
        self.page -= 1
        self._saved()

    def _draw_tree(self) -> None:
        """The tree on the canvas.  Only what changed is drawn again (the owner's tree of vines took well
        over a second for every change, edit, undo and zoom: some 60,000 leaves, petals and stems made
        again each time): every item -- or a portrait's whole special border -- keeps its canvas items
        while the scene draws it just the same, what is new goes into its place among them, what has
        gone is deleted, and a zoom scales what is kept.  The page, background, grid, stickers,
        selection and handles are drawn again every time, as they always were."""
        # The scene as it was when only the zoom or the background picture changed (_same_scene).
        sc = self.sc if self.__dict__.pop("_same_scene", False) and hasattr(self, "sc") else self._scene()
        self.sc = sc
        c = self.canvas
        z = self.z
        c.addtag_withtag("doomed", "all")
        c.dtag("tree", "doomed")
        c.delete("doomed")
        self.targets: dict[int, tuple] = {}
        self.editable: dict[int, str] = {}                  # canvas item -> what retyping it changes
        self.pieces: dict[int, str] = {}                    # canvas item -> its line piece, draggable
        c.configure(scrollregion=(0, 0, sc.width * z, sc.height * z), background=OUTSIDE)
        # The page itself, in its colour (the space around it is grey, as around a slide).
        page = c.create_rectangle(0, 0, sc.width, sc.height, fill=tk_colour(sc.background, "#ffffff"), width=0,
                                  tags=("backdrop", "fresh"))
        backdrop = None
        # What the tree is drawn as, in order: (what it is drawn as -- its canvas items' types, places,
        # options and tags -- and, once drawn, its canvas items).
        units: list[list] = []
        items = sc.items
        old_ops = self.__dict__.get("_block_ops", {})
        block_ops: dict = {}
        k, n = 0, len(items)
        while k < n:
            item = items[k]
            block = item.__dict__.get("block")
            if block is not None:               # a portrait's special border: worked out once (ft.special_border_items)
                j = k + len(ft._SPECIAL_CACHE.get(block, ()))
                if not (k < j <= n and items[j - 1].__dict__.get("block") is block
                        and (j == n or items[j].__dict__.get("block") is not block)):
                    j = k + 1                   # not as worked out (another thread's tree emptied the cache): counted
                    while j < n and items[j].__dict__.get("block") is block:
                        j += 1
                group = items[k:j]
                # (its pieces as faded -- by the portraits' opacity and the special borders' own -- and as moved
                # and shrunk onto a canvas of the player's size: Scene.fit)
                sig = ("border", block, sc.background, getattr(sc, "fit", None),
                       frozenset((type(i), i.opacity) for i in group), j - k)
                drawn = old_ops.get(sig) or block_ops.get(sig)
                if drawn is None:
                    ops = tuple(op for i in group for op in self._ops(i, sc))
                    metas = {op[2] for op in ops}
                    drawn = (ops, frozenset(op[1] for op in ops if op[1] is not None),
                             next(iter(metas)) if len(metas) == 1 else None)
                block_ops[sig] = drawn
                units.append([sig, drawn[0], (), drawn[1], drawn[2]])
                k = j
                continue
            k += 1
            if isinstance(item, ft.Backdrop):
                backdrop = self._draw_backdrop(item, sc)
                if backdrop is not None:
                    self.targets[backdrop] = ("background",)
                continue
            ops = tuple(self._ops(item, sc))
            units.append([ops, ops, (), {op[1] for op in ops if op[1] is not None}, None])
        self._block_ops = block_ops
        self._place_units(units)
        if backdrop is not None:
            c.tag_lower(backdrop)
        c.tag_lower(page)
        c.scale("fresh", 0, 0, z, z)
        c.dtag("fresh", "fresh")
        targets, editable, pieces = self.targets, self.editable, self.pieces
        for _sig, ops, iids, _wbases, same in units:
            if same is not None:                # every piece of a special border is the same thing
                _tags, target, piece, edit = same
                if target is not None:
                    targets.update(dict.fromkeys(iids, target))
                if piece:
                    pieces.update(dict.fromkeys(iids, piece))
                if edit:
                    editable.update(dict.fromkeys(iids, edit))
                continue
            for iid, op in zip(iids, ops):
                _tags, target, piece, edit = op[2]
                if target is not None:
                    targets[iid] = target
                if piece:
                    pieces[iid] = piece
                if edit:
                    editable[iid] = edit
        self._draw_grid()
        self._draw_stickers()
        self._draw_selection()
        if hasattr(self, "preset_labels"):
            self._show_background()

    def _place_units(self, units: list) -> None:
        """Each unit's canvas items: the last drawing's when it drew the unit the same (and nothing on it
        was dragged since), else made now and put in their place in the stacking order; the last
        drawing's items no longer drawn deleted, and those kept scaled to a new zoom."""
        c, z = self.canvas, self.z
        old = self.__dict__.get("_units", [])
        moved = set(c.find_withtag("moved")) if old else set()
        pool: dict = {}
        for idx, (sig, _ops, iids, _wbases, _same) in enumerate(old):
            if moved and any(i in moved for i in iids):
                continue                        # dragged on the canvas since: drawn again where it is
            pool.setdefault(sig, []).append(idx)
        kept = []
        last, in_order = -1, True
        for unit in units:
            same = pool.get(unit[0])
            idx = same.pop(0) if same else None
            if idx is not None:
                in_order = in_order and idx > last
                last = idx
            kept.append(idx)
        if not in_order:                        # the order changed (lines brought in front, say): all again
            kept = [None] * len(units)
        used = {idx for idx in kept if idx is not None}
        stale = [i for idx, unit in enumerate(old) if idx not in used for i in unit[2]]
        for at in range(0, len(stale), 4000):
            c.delete(*stale[at:at + 4000])
        c.dtag("moved", "moved")
        z_was = self.__dict__.get("_drawn_z", z)
        if used and z_was != z:                 # zoomed: what is kept scaled, its lines as thick as the zoom says
            c.scale("tree", 0, 0, 1 / z_was, 1 / z_was)
            c.scale("tree", 0, 0, z, z)
            for wbase in self.__dict__.get("_wbases", ()):
                c.itemconfigure(f"w{float(wbase)!r}", width=wbase * z)
        self._drawn_z = z
        # Where each new unit goes: under the first kept unit after it (on top when none is).
        under = [None] * len(units)
        anchor = None
        for at in range(len(units) - 1, -1, -1):
            under[at] = anchor
            idx = kept[at]
            if idx is not None and old[idx][2]:
                anchor = old[idx][2][0]
        call, w, getint = c.tk.call, c._w, c.tk.getint
        wbases = set()
        for unit, idx, below in zip(units, kept, under):
            if idx is not None:
                unit[2] = old[idx][2]
            else:
                iids = []
                for head, wbase, _meta, tags in unit[1]:
                    if wbase is None:
                        iid = getint(call(w, *head, "-tags", tags))
                    else:
                        iid = getint(call(w, *head, "-width", wbase * z, "-tags", tags))
                    if below is not None:
                        call(w, "lower", iid, below)
                    iids.append(iid)
                unit[2] = iids
            wbases |= unit[3]
        self._units = units
        self._wbases = wbases

    def _ops(self, item, sc: ft.Scene) -> list:
        """_item_ops ready to make: (the canvas's create command but its width and tags, the line width
        before the zoom or None, what it is -- _tag -- and its tags)."""
        out = []
        for kind, coords, opts, wbase, meta in self._item_ops(item, sc):
            tags = meta[0] + ("tree", "fresh") + ((f"w{float(wbase)!r}",) if wbase is not None else ())
            out.append((("create", kind) + coords + opts, wbase, meta, tags))
        return out

    def _faded(self, colour: str, opacity: float, under: str) -> str:
        """tk_colour(faded(...)), remembered (a special border's thousands of pieces share a few colours)."""
        memo = self.__dict__.setdefault("_faded_memo", {})
        key = (colour, opacity, under)
        if key not in memo:
            if len(memo) > 20000:
                memo.clear()
            memo[key] = tk_colour(faded(colour, opacity, under))
        return memo[key]

    def _item_ops(self, item, sc: ft.Scene) -> list:
        """How a scene item is drawn on the canvas, before the zoom scales it: (item type, its points,
        its options, its line width before the zoom or None, and what it is -- _tag) for each canvas item."""
        c = self.canvas
        z = self.z
        opts = c._options
        meta = self._tag(item)
        if isinstance(item, ft.Line):
            flat = tuple(v for point in item.points for v in point)
            dash = ft.TK_DASHES.get(item.dash)          # (as tkinter passes these: plain words, none left out)
            return [("line", flat, ("-fill", self._faded(item.colour, item.opacity, sc.background), "-joinstyle", "round")
                     + (("-dash", dash) if dash is not None else ()), item.width, meta)]
        if isinstance(item, ft.Poly):
            flat = tuple(v for point in item.points for v in point)
            return [("polygon", flat,
                     ("-fill", self._faded(item.fill, item.opacity, sc.background) if item.fill else "",
                      "-outline", self._faded(item.stroke, item.opacity, sc.background) if item.width else "",
                      "-joinstyle", "round"), item.width, meta)]
        if isinstance(item, ft.Shape):
            fill = tk_colour(item.fill or "")
            dash = ft.TK_DASHES.get(item.dash)
            width = item.width or 0
            outline = tk_colour(item.stroke) if width else ""
            # The canvas cannot blend: a see-through fill is drawn as a fine dot pattern.
            see = item.opacity
            stipple = "" if see >= 1 else ("gray75" if see >= 0.7 else "gray50" if see >= 0.4 else "gray25")
            if see < 1:                     # the border fades with it, into what is really under it:
                # the background picture's own colour there, not a plain white (the owner,
                # 2026-10-08: a mark is the colour chosen, never washed out to white)
                under = self._colour_under(item.x + item.w / 2, item.y, sc)
                outline = tk_colour(faded(item.stroke, see, under)) if width else ""
            look = opts({"fill": fill, "outline": outline, "dash": dash, "stipple": stipple})
            corners = ft.outline(item.kind, item.x, item.y, item.w, item.h)
            if item.angle:                  # the canvas cannot turn a shape: its corners, turned
                return [("polygon", tuple(v for point in item.points() for v in point), look, width, meta)]
            if item.kind in ("ellipse", "circle"):
                ox, oy, ow, oh = ft.oval_box(item.kind, item.x, item.y, item.w, item.h)
                return [("oval", (ox, oy, ox + ow, oy + oh), look, width, meta)]
            if corners is not None:
                return [("polygon", tuple(v for point in corners for v in point), look, width, meta)]
            if item.radius > 0:             # rounded corners: the canvas has no rounded rectangle
                return [("polygon", tuple(v for point in item.points() for v in point), look, width, meta)]
            return [("rectangle", (item.x, item.y, item.x + item.w, item.y + item.h), look, width, meta)]
        if isinstance(item, ft.Head):
            image = self._head(item.sheet, item.row, item.scale)
            if image is None:
                return []
            return [("image", (item.x, item.y), opts({"image": str(image), "anchor": "nw"}), None, meta)]
        if isinstance(item, ft.Text) and (item.mirror_h or item.mirror_v):
            op = self._mirrored_words(item)     # the canvas cannot mirror words: drawn as a picture
            return [op + (None, meta)] if op is not None else []
        elif isinstance(item, ft.Text) and item.runs:
            return [run + (None, meta) for run in self._draw_runs(item, sc.background)]
        elif isinstance(item, ft.Text):
            style = ["bold" if item.bold else "normal"] + (["italic"] if item.italic else []) \
                + (["underline"] if item.underline else []) + (["overstrike"] if item.strike else [])
            font = (item.font or vf1_gdiplus.FONT, -max(1, int(round(item.size * z))), *style)
            ox, oy = ft.turn(0.0, item.size * 0.24, item.angle) if item.angle else (0.0, item.size * 0.24)
            return [("text", (item.x + ox, item.y + oy),
                     opts({"text": item.text, "fill": tk_colour(faded(item.colour, item.opacity, sc.background)),
                           "font": font, "anchor": "s" if item.centre else "se" if item.end else "sw",
                           "angle": -item.angle}), None, meta)]          # the canvas turns the other way round
        return []

    def _mirrored_words(self, item: ft.Text):
        """Mirrored words (Edits.flip_words), drawn by Windows into a see-through picture at the zoom and
        placed where they belong (the picture kept for the next drawing): its canvas image, as
        _item_ops gives it, without its width and what it is."""
        if not vf1_gdiplus.available():
            return None
        import dataclasses
        span = max(item.size * 2, len(item.text) * item.size * 0.75 + item.size * 2)
        left, top = item.x - span, item.y - item.size * 2
        key = (item.text, item.size, item.bold, item.italic, item.font, item.colour, item.opacity, item.centre, item.end,
               item.angle, item.mirror_h, item.mirror_v, str(item.runs), round(item.x - left, 1), round(self.z, 3))
        cache = self.__dict__.setdefault("mirror_photos", {})
        if key not in cache:
            local = dataclasses.replace(item, x=item.x - left, y=item.y - top)
            path = self._scratch() / f"words{len(cache)}.png"
            try:
                ok = vf1_gdiplus.save_scene(ft.Scene(span * 2, item.size * 4, "#ffffff", [local]), {}, path,
                                           scale=self.z, transparent=True)
                cache[key] = tk.PhotoImage(master=self, file=str(path)) if ok else None
            except (OSError, ValueError, tk.TclError):
                cache[key] = None
        photo = cache[key]
        if photo is None:
            return None
        return ("image", (left, top), self.canvas._options({"image": str(photo), "anchor": "nw"}))

    def _draw_runs(self, item: ft.Text, background: str) -> list[tuple]:
        """A portrait's formatted words: each run in its own font (ft.run_look), measured, the whole
        line centred where the Text says and each run drawn after the one before it (a superscript
        or subscript smaller, raised or lowered).  Their canvas texts, as _item_ops gives them,
        without their width and what they are."""
        c, z = self.canvas, self.z
        pieces = []
        for text, style in item.runs:
            look = ft.run_look(item, style)
            font = (item.font or vf1_gdiplus.FONT, -max(1, int(round(look["size"] * z))),
                    "bold" if look["bold"] else "normal", *(["italic"] if look["italic"] else []),
                    *(["underline"] if look["underline"] else []), *(["overstrike"] if look["strike"] else []))
            pieces.append((text, look, font, self._measure(font, text) / z))
        total = sum(p[3] for p in pieces)
        x = item.x - total / 2 if item.centre else item.x - total if item.end else item.x
        out = []
        for text, look, font, width in pieces:
            # Along the line, turned about where it starts when the words turn with the portrait.
            dx, dy = ft.turn(x - item.x, look["dy"] + look["size"] * 0.24, item.angle)
            out.append(("text", (item.x + dx, item.y + dy),
                        c._options({"text": text, "font": font, "angle": -item.angle,
                                    "fill": tk_colour(faded(look["colour"], item.opacity, background)), "anchor": "sw"})))
            x += width
        return out

    def _measure(self, font: tuple, text: str) -> int:
        """How wide `text` is in `font`, in screen pixels (its Font kept for the next time)."""
        fonts = self.__dict__.setdefault("measure_fonts", {})
        if font not in fonts:
            fonts[font] = tkfont.Font(self, font=font)
        return fonts[font].measure(text)

    def _tag(self, item) -> tuple:
        """What a canvas item is (for a right click) and what dragging it moves: (its tags, what a right
        click on it changes, its line piece when it can be dragged, what retyping it changes)."""
        tags = []
        pid = getattr(item, "pid", None)
        if pid is not None:
            tags.append(f"p{pid}")
        if getattr(item, "move", ""):
            tags.append(f"m_{item.move}")
        if getattr(item, "part", ""):
            tags.append(f"lp_{item.part}")
        piece = getattr(item, "piece", "")
        if not (piece and len(item.points) == 2 and item.points[0] != item.points[1]):
            piece = ""
        target = getattr(item, "target", None)
        if target is None and isinstance(item, ft.Text) and item.role:
            target = ("role", item.role)
        if target is None and pid is not None:
            target = ("person", pid)
        if target is None and isinstance(item, ft.Backdrop):
            target = ("background",)
        return tuple(tags), target, piece, getattr(item, "edit", "") or ""

    def _grab(self, event) -> int | None:
        """What a press picks up: the topmost item exactly under the pointer (a line within a few
        pixels, so it can be caught), never the box behind words or the page itself (the owner: "i
        can literally drag headers when i'm not even clicking on their text")."""
        c = self.canvas
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        exact = set(c.find_overlapping(x, y, x, y))
        for iid in reversed(c.find_overlapping(x - 3, y - 3, x + 3, y + 3)):
            if iid not in exact and c.type(iid) != "line":
                continue
            if self.targets.get(iid) == ("plate",) or "backdrop" in c.gettags(iid):
                continue
            if iid in self.targets or any(tag.startswith(("p", "m_")) for tag in c.gettags(iid)):
                return iid
        return None

    def _under(self, event) -> int | None:
        """The topmost tree item under the pointer."""
        c = self.canvas
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        for iid in reversed(c.find_overlapping(x - 4, y - 4, x + 4, y + 4)):
            if iid in self.targets or any(tag.startswith(("p", "m_")) for tag in c.gettags(iid)):
                return iid
        return None

    def _hover(self, event) -> None:
        """A double arrow over a line piece that can be dragged."""
        if self.pan is not None or getattr(self, "move", None) is not None:
            return
        iid = self._under(event)
        shape = "fleur" if iid in self.pieces else ""
        if self.canvas.cget("cursor") != shape:
            self.canvas.configure(cursor=shape)

    # ---- right click: a colour for anything -----------------------------------
    def _context(self, event) -> None:
        st = self._sticker_at(*self._where(event))
        if st is not None:
            self._select_obj(st.index)
            target = ("sticker", st.index)
        else:
            iid = self._under(event)
            target = self.targets.get(iid, ("background",)) if iid is not None else ("background",)
        words, current, setter = self._colour_of(target)
        menu = tk.Menu(self, tearoff=0)
        here = self._where(event)
        adding = tk.Menu(menu, tearoff=0)
        adding.add_command(label="Text box", command=lambda: self._add_here("text", here))
        adding.add_command(label="Picture...", command=lambda: self._add_here("picture", here))
        adding.add_command(label="Rectangle", command=lambda: self._add_here("rect", here))
        adding.add_command(label="Oval", command=lambda: self._add_here("ellipse", here))
        if self.logos:
            logos = tk.Menu(adding, tearoff=0)
            for name, ref in self.logos:
                logos.add_command(label=name, command=lambda r=ref: self._add_here(r, here))
            adding.add_cascade(label="Logo", menu=logos)
        menu.add_cascade(label="Add here", menu=adding)
        menu.add_separator()
        if st is not None:                      # a picture or text box: what PowerPoint's menu offers
            for words_, command in (("Cut", self._cut), ("Copy", self._copy), ("Duplicate", self._duplicate),
                                    ("Delete", self._delete), (None, None),
                                    ("Bring to front", lambda: self._layer("front")),
                                    ("Bring forward", lambda: self._layer("forward")),
                                    ("Send backward", lambda: self._layer("backward")),
                                    ("Send to back", lambda: self._layer("back")), (None, None),
                                    ("Rotate left 90", lambda: self._turn(-90)),
                                    ("Rotate right 90", lambda: self._turn(90))):
                if words_ is None:
                    menu.add_separator()
                else:
                    menu.add_command(label=words_, command=command)
            if self.edits.stickers[st.index]["kind"] == "picture":
                menu.add_command(label="Reset proportions", command=self._original_shape)
            menu.add_command(label="Reset to default", command=self._reset_sticker)
            menu.add_separator()
        if setter is not None:
            menu.add_command(label=f"Change the colour of {words}...",
                             command=lambda: self._recolour(words, current, setter))
            if target[0] in ("person", "family", "role", "ink", "background", "plate"):
                menu.add_command(label="Reset colour", command=lambda: (setter(""), None))
            if target[0] == "person":
                fill_words, fill_now, fill_set = self._colour_of(("person_fill",))
                menu.add_command(label=f"Change the colour of {fill_words}...",
                                 command=lambda: self._recolour(fill_words, fill_now, fill_set))
        iid = self._under(event) if st is None else None
        tags = self.canvas.gettags(iid) if iid is not None else ()
        moved = [tag[2:] for tag in tags if tag.startswith("m_")]
        people = [int(tag[1:]) for tag in tags if tag[:1] == "p" and tag[1:].isdigit()]
        if iid in self.pieces:
            piece = self.pieces[iid]
            menu.add_separator()
            menu.add_command(label="Delete this line", command=lambda: self._hide(f"line:{piece}"))
            if piece in self._line_moves_now():
                menu.add_command(label="Reset this line", command=lambda: self._unmove_line(piece))
        label_part = next((tag[3:] for tag in tags if tag.startswith("lp_")), "")
        if moved and not people:
            menu.add_separator()
            menu.add_command(label="Delete the whole label" if label_part else "Delete",
                             command=lambda: self._hide(f"word:{moved[0]}"))
        if moved and moved[0].startswith("onward:") and iid is not None:
            # A family's "continued on page N" words: these, or every family's (the owner, 2026-10-10).
            name = moved[0]
            menu.add_command(label="Change these words...", command=lambda: self._edit_in_place(iid, f"word:{name}"))
            menu.add_command(label="Change the words of every \"continued on page\" label...",
                             command=lambda: self._edit_in_place(iid, f"every_onward:{name}"))
            menu.add_command(label="Delete every \"continued on page\" label", command=lambda: self._hide("word:onward"))
            menu.add_command(label="Reset these words", command=lambda: self._onward_reset(name))
            menu.add_command(label="Reset every \"continued on page\" label", command=lambda: self._onward_reset(None))
        if label_part:                          # one line, or the number or the name, of a generation's label
            g, _, part = label_part.partition("|")
            if part.startswith("custom"):
                menu.add_command(label="Delete this line", command=lambda: self._drop_label_line(int(g), int(part[6:])))
            for name in ("number", "name") if part == "first" else (part,) if part in ft.LABEL_PARTS else ():
                words_ = ft.LABEL_PARTS[name]
                menu.add_command(label=f"Delete {words_}", command=lambda n=name: self._hide(f"label:{g}:{n}"))
                menu.add_command(label=f"Delete {words_} from every generation",
                                 command=lambda n=name: self._hide(f"label:*:{n}"))
        if target is not None and target[0] == "role":      # any words: their style
            self._style_menu(menu, target[1])
        if moved or people:
            menu.add_separator()
            menu.add_command(label="Reset position",
                             command=lambda: self._unmove(moved[0] if moved else None, people[:1]))
        if people:
            menu.add_command(label=f"Select {self.village.people[people[0]].name}",
                             command=lambda: self._select([people[0]]))
            menu.add_command(label="Reset to default", command=lambda: self._reset_people(people[:1]))
            menu.add_command(label="Delete" if not (people[0] in self.selected and len(self.selected) > 1)
                             else f"Delete the {len(self.selected)} selected",
                             command=lambda: self._delete_people(people[:1]))
        menu.add_separator()
        menu.add_command(label="Reset all positions", command=lambda: self._unmove_all())
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _colour_of(self, target: tuple):
        """(words for it, its colour now, a function giving it a colour -- "" for automatic)."""
        kind = target[0]
        e = self.edits
        if kind == "person" and target[1] in self.selected and len(self.selected) > 1:
            pids = list(self.selected)          # batch editing: every one selected
            return (f"the {len(pids)} selected family members", self.lay.birth_colour.get(target[1], ""),
                    lambda c: self._own_colour(c, pids))
        if kind == "person":
            p = self.village.people[target[1]]
            fam = self._family(p)
            words = f"{p.name} and their full brothers and sisters" if fam is not None else p.name
            return words, self.lay.birth_colour.get(p.id, ""), lambda c: self._own_colour(c, [p.id])
        if kind == "family":
            fam = next((f for f in self.lay.families if ft.family_key(self.village, f) == target[1]), None)
            names = " and ".join(self.village.people[q].name for q in (fam.father, fam.mother) if q is not None) \
                if fam is not None else "this family"
            own = e.family_lines.get(target[1], {}).get("colour")
            if own:     # lines of a colour of their own (Auto-colour family lines); Reset colour: the family's
                return (f"the lines of {names}", own,
                        lambda c: self._line_colour(target[1], c))
            return (f"the lines and children of {names}", fam.colour if fam is not None else "",
                    lambda c: self._set_chosen_colour(e.family_colours, target[1], c))
        if kind == "mark" and target[1] in e.marks:
            return (f"the mark {target[1]}", e.marks[target[1]],
                    lambda c: self._set_chosen_colour(e.marks, target[1], c or e.marks[target[1]]))
        if kind == "role":
            role = target[1]
            words = "the " + ft.ROLES[role][0].lower() + ft.ROLES[role][1:]
            return (words, e.styles.get(role, {}).get("colour", self.lay.ink),
                    lambda c: self._set_role_colour(role, c))
        if kind == "person_fill":
            return ("the inside of every portrait", e.portrait_fill,
                    lambda c: (self._change(everyone=True, portrait_fill=c or "#ffffff"), self._refresh_panels()))
        if kind == "plate":
            return ("the boxes behind the words", e.plate_colour or self.lay.background,
                    lambda c: self._change(plate_colour=c))
        if kind == "ink":
            return "the generation lines and the words", self.lay.ink, lambda c: self._change(ink=c)
        if kind == "background":
            return "the background", self.lay.background, lambda c: self._change(background=c)
        if kind == "sticker" and e.stickers[target[1]]["kind"] == "text":
            return "the text box's words", e.stickers[target[1]]["colour"], lambda c: self._set_obj(colour=c or ft.INK)
        return "it", "", None

    def _recolour(self, words: str, current: str, setter) -> None:
        colour = ask_colour(self, f"The colour of {words}", current)
        if colour:
            setter(colour)

    def _set_chosen_colour(self, chosen: dict, key: str, colour: str) -> None:
        if colour:
            chosen[key] = colour
        else:
            chosen.pop(key, None)
        self._refresh_marks()
        self._saved()

    def _style_menu(self, menu: tk.Menu, role: str) -> None:
        """Bold, italic, underline, strikethrough, superscript and subscript for these words (every
        word of their kind -- every name, every label...), ticked as they are now."""
        style = self.edits.styles.get(role, {})
        menu.add_separator()
        self.style_vars = []                    # kept while the menu is open
        for flag, label in (("bold", "Bold"), ("italic", "Italic"), ("underline", "Underline"),
                            ("strike", "Strikethrough")):
            var = tk.BooleanVar(value=style.get(flag, flag == "bold" and role in BOLD_ROLES))
            self.style_vars.append(var)
            menu.add_checkbutton(label=label, variable=var,
                                 command=lambda f=flag, v=var: self._word_style(role, f, bool(v.get())))
        for script, label in (("super", "Superscript"), ("sub", "Subscript")):
            var = tk.BooleanVar(value=style.get("script") == script)
            self.style_vars.append(var)
            menu.add_checkbutton(label=label, variable=var,
                                 command=lambda s=script, v=var: self._word_style(role, "script", s if v.get() else None))

    def _word_style(self, role: str, flag: str, value) -> None:
        style = dict(self.edits.styles.get(role, {}))
        if value is None:
            style.pop(flag, None)
        else:
            style[flag] = value
        style = ft.clean_style(style)
        if style:
            self.edits.styles[role] = style
        else:
            self.edits.styles.pop(role, None)
        self._saved()
        self._show_role()

    def _set_role_colour(self, role: str, colour: str) -> None:
        style = dict(self.edits.styles.get(role, {}))
        if colour:
            style["colour"] = colour
        else:
            style.pop("colour", None)
        if style:
            self.edits.styles[role] = style
        else:
            self.edits.styles.pop(role, None)
        self._saved()
        self._show_role()

    # ---- dragging anything -------------------------------------------------------
    def _unmove(self, name: str | None, pids: list) -> None:
        if name:
            self._move_to(name, None)
        for q in pids:
            self._set_entry(self.village.people[q], dx=None, dy=None)
        self._saved()

    def _unmove_line(self, piece: str) -> None:
        self._set_line_move(piece, None)
        self._saved()

    def _menus(self) -> None:
        """The menu bar (the owner: "a file > save, delete tree, export as... header")."""
        bar = tk.Menu(self, tearoff=0)
        items = {
            "File": [("Save to Save Folder", "Ctrl+S", self._save_tree),
                     ("Open Tree File...", "", self._open_tree),
                     ("Export as Picture...", "Ctrl+Shift+S", self._export),
                     ("Open in Browser", "", self._open_page), None,
                     ("Update Family Tree from the Save", "F5", self._update_from_game), None,
                     ("Delete Tree...", "", self._delete_tree), None,
                     ("Close", "", self._close)],
            "Edit": [("Undo", "Ctrl+Z", self._undo), ("Redo", "Ctrl+Y", self._redo), None,
                     ("Find a Family Member", "Ctrl+F", self._find_focus), None,
                     ("Reorganize Portraits", "", self._reorganize_portraits),
                     ("Reorganize Lines", "", self._reorganize_lines),
                     ("Reorganize Generation Labels", "", self._reorganize_labels), None,
                     ("Reset Portrait Shapes...", "", self._reset_shapes),
                     ("Reset Portrait Places...", "", self._reset_portraits),
                     ("Reset Lines...", "", self._reset_lines),
                     ("Reset Everything...", "", self._reset_everything)],
            "View": [("Zoom In", "+", lambda: self._zoom_step(1)), ("Zoom Out", "-", lambda: self._zoom_step(-1)),
                     ("Fit", "", self._zoom_fit), ("100%", "Ctrl+0", lambda: self._zoom_to(1.0)), None,
                     ("Hide or Show the Panel", "F4", self._toggle_panel), ("Full Screen", "F11", self._toggle_full)],
            "Tools": [("Number Duplicate Names...", "", self._number_names)],
            "Help": [("Controls", "F1", self._help)],
        }
        for name, entries in items.items():
            menu = tk.Menu(bar, tearoff=0)
            for entry in entries:
                if entry is None:
                    menu.add_separator()
                else:
                    label, keys, command = entry
                    menu.add_command(label=label, accelerator=keys, command=command)
            bar.add_cascade(label=name, menu=menu)
        self.configure(menu=bar)

    def _export(self) -> None:
        """The tree as a picture, PNG or JPG, anywhere (every page of it)."""
        if not vf1_gdiplus.available():
            messagebox.showerror("Export as Picture", "Pictures are saved with Windows' own graphics; this "
                                                      "computer does not have them.", parent=self)
            return
        folder = self._trees_folder()
        path = filedialog.asksaveasfilename(
            parent=self, title="Export the family tree as a picture", initialdir=str(folder) if folder else None,
            initialfile=f"{self._tree_name()}.png", defaultextension=".png",
            filetypes=[("PNG picture", "*.png"), ("JPG picture", "*.jpg *.jpeg")])
        if not path:
            return
        choice = self._export_options(len(ft.page_spans(self.edits, self.village)))
        if choice is None:
            return
        pages, big = choice
        self._save_as(Path(path), 2.0 if big else 1.0, pages=pages)

    def _export_options(self, count: int) -> tuple | None:
        """What to save (a dialog): whole pages -- one, a range such as 2-5, or all of them -- and at
        double size or not.  A picture is always whole pages, never the part the window shows.  (pages
        (0-based), double size); None when cancelled."""
        win = tk.Toplevel(self)
        win.title("Export as Picture")
        win.transient(self)
        frame = scrollable_frame(win, padding=10)
        pick = tk.StringVar(value="all")
        number = tk.StringVar(value=str(self.page + 1))
        span = tk.StringVar(value=f"1-{count}")
        big = tk.BooleanVar(value=False)
        result: list = []
        ttk.Label(frame, text="Whole pages:").pack(anchor="w")
        box = ttk.Frame(frame, padding=(22, 0, 0, 0))
        box.pack(anchor="w")
        ttk.Radiobutton(box, text=f"All {count} page(s)", variable=pick, value="all").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(box, text="One page:", variable=pick, value="one").grid(row=1, column=0, sticky="w")
        ttk.Entry(box, textvariable=number, width=6).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Radiobutton(box, text="Pages (for example 2-5):", variable=pick, value="range").grid(row=2, column=0, sticky="w")
        ttk.Entry(box, textvariable=span, width=10).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Checkbutton(frame, text="Double size (sharper when you zoom in)", variable=big).pack(anchor="w", pady=(8, 0))
        ttk.Label(frame, text="Pages after the first are saved beside it as \"<name> - Page N\".",
                  foreground="#555555").pack(anchor="w", pady=(2, 8))
        message = ttk.Label(frame, text="", foreground="#aa0000")
        message.pack(anchor="w")

        def ok() -> None:
            try:
                pages = parse_page_range(
                    {"all": f"1-{count}", "one": number.get(), "range": span.get()}[pick.get()], count)
            except ValueError as exc:
                message.configure(text=str(exc))
                return
            result.append((pages, big.get()))
            win.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Save...", command=ok).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.grab_set()
        win.wait_window()
        return result[0] if result else None

    def _delete_tree(self) -> None:
        """This tree deleted -- its tree file and its edits -- and drawn as the patcher first draws it
        (the pictures already exported stay; Ctrl+Z brings the edits back while the editor is open, and
        Ctrl+S saves them again)."""
        if not self._sure("Delete this family tree's look -- every mark, colour, move, picture, text box and page -- "
                          "and start again from the save?  (Exported pictures, and the family members the tree "
                          "remembers, are kept.)"):
            return
        tree = self._tree_file()
        try:
            data = vf1_tree_memory.read_tree_file(tree) if tree is not None else {}
            if data.pop("edits", None) is not None:
                vf1_tree_memory.write_tree_file(tree, data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Family Tree Maker", f"The tree file could not be changed: {exc}", parent=self)
            return
        for path in (ft.Edits.path(self.folder, self.game, self.slot),):
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except OSError as exc:
                messagebox.showerror("Family Tree Maker", f"{path.name} could not be deleted: {exc}", parent=self)
                return
        # As a tree with no edits file opens: in the look last used (it was the factory look, which
        # closing then made the look remembered for every new tree).
        self.edits = ft.styled(getattr(self.app, "tree_style", None))
        ft.apply_auto_marks(self.edits, self.full_village)     # as a new tree opens: its special villagers marked
        self.obj = None
        self.selected = []
        self.page = 0
        self._saved()
        self._refresh_panels()
        self.status.set("The tree is deleted and drawn fresh from the save.  Ctrl+Z brings it back.")

    def _follow_looks(self) -> None:
        """After Change Appearance (the owner: "ask the player if they wish to update the family member's
        appearance in the family tree or not"): the family member's edits, saved under their old look,
        follow them to the new one, and each changed family member not yet decided is asked about."""
        if self.village.relooked:
            for name, head, body in self.village.relooked:   # changed again since the player chose
                self.edits.entries.get(f"{name}|{head}|{body}", {}).pop("look", None)
                for part in self.edits.page_edits.values():     # a page's own choice too
                    part.get("entries", {}).get(f"{name}|{head}|{body}", {}).pop("look", None)
            text = json.dumps(self.edits.to_data())
            moved = ft.relooked_keys(text, self.village.relooked)
            if moved != text:
                self.edits = ft.Edits.from_data(json.loads(moved))
                self.dirty = True
                # The old keys are gone: an undo step from before would bring them back (Codex, #558).
                self.history.clear()
                self.future.clear()
                self.last_state = self._state()
        # A villager the tree showed by a name the Villager Details screen cut is shown by the full
        # name the logs keep (vv_cut_names): their edits follow them, as for a change of looks.
        moved = ft.full_name_edits(self.edits, self.village)
        if moved is not self.edits:
            self.edits = moved
            self.dirty = True
            self.history.clear()
            self.future.clear()
            self.last_state = self._state()
        self._auto_marks()                      # under the keys the villagers have now
        changed = [p for p in self.village.known() if p.old_looks and "look" not in self._entry(p)]
        if changed:
            self.after_idle(lambda: self._ask_looks(changed))

    def _ask_looks(self, changed: list) -> None:
        """Each family member whose look Change Appearance changed: show the new look on the tree, or keep
        the old one.  The answer is kept with the tree, so it is asked once."""
        window = tk.Toplevel(self)
        window.title("Appearance changed")
        window.transient(self)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="These family members' looks were changed with Change Appearance.  Update their "
                              "portraits on the tree to the new look?", wraplength=460).pack(anchor="w", pady=(0, 8))
        # A whole village at once scrolls (Codex, #558).
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True)
        canvas = tk.Canvas(box, highlightthickness=0, borderwidth=0, height=min(420, 34 * len(changed)), width=520)
        bar = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        rows = ttk.Frame(canvas)
        canvas.create_window(0, 0, window=rows, anchor="nw")
        rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        both = ttk.Frame(frame)
        both.pack(anchor="w", pady=(6, 0))
        choices = {}
        for p in changed:
            old = p.old_looks[-1]
            var = tk.StringVar(value="new")
            choices[p.id] = (var, old)
            row = ttk.Frame(rows)
            row.pack(anchor="w", pady=2)
            ttk.Label(row, text=gen.numbered(p), width=24).pack(side="left")
            ttk.Radiobutton(row, text=f"New look (head {p.head})", value="new", variable=var).pack(side="left")
            ttk.Radiobutton(row, text=f"Old look (head {old[0]})", value="old", variable=var).pack(side="left",
                                                                                                  padx=(8, 0))

        def done() -> None:
            for pid, (var, old) in choices.items():
                p = self.village.people[pid]
                # (the villager's look on the whole tree: every page, as it was before pages kept their own)
                look = list(old) if var.get() == "old" else [p.head, p.body]
                self.edits.entries.setdefault(ft.entry_key(self.village, p), {})["look"] = look
            window.destroy()
            self._saved()

        for label, value in (("All new looks", "new"), ("All old looks", "old")):
            ttk.Button(both, text=label, command=lambda value=value: [var.set(value) for var, _old in choices.values()]
                       ).pack(side="left", padx=(0, 8))
        ttk.Button(frame, text="OK", command=done).pack(anchor="e", pady=(10, 0))
        window.protocol("WM_DELETE_WINDOW", done)
        window.grab_set()

    def _shown_village(self, village: gen.Village) -> gen.Village:
        """The family as the tree shows it: with "Hide family members not in the current save" on, without the
        family members of a family started over that src/vv_history_revision.py proves gone."""
        return village

    def _toggle_hide_gone(self) -> None:
        self.village = self._shown_village(self.full_village)
        self.window["hide_not_in_save"] = bool(self.hide_gone.get())
        self.selected = []
        self._follow_looks()
        self.redraw()
        self._refresh_selected()
        self._refresh_hidden()
        self.status.set(f"{len(self.village.known())} family members shown"
                        + ("; family members of a family started over are hidden." if self.hide_gone.get() else "."))

    def _update_from_game(self, _event=None, ask: bool = True) -> None:
        """The save and the patcher's logs read again (the game played on since the tree opened);
        every edit is kept, and a family member's edits follow them.  Asked first when the player chose it
        (the owner, 2026-10-09: "before actually updating when the update button is clicked, please
        have a confirm prompt")."""
        if ask and not messagebox.askyesno(
                "Family Tree Maker",
                "Update the family tree from the save now?\n\nThe family members, their ages and "
                "everything the game has changed since are read again; your own edits are kept.",
                parent=self):
            return
        try:
            village = gen.load_village(self.folder, self.game, self.slot, rename_answers=self.edits.renames,
                                       remember=True)
        except gen.GenealogyError as exc:
            messagebox.showerror("Family Tree Maker", str(exc), parent=self)
            return
        village = ask_renames(self, self.folder, self.game, self.slot, village, self.edits)
        before = len(self.village.known())
        self.full_village = village
        self.village = village = self._shown_village(village)
        self.selected = []
        self._follow_looks()
        self.redraw()
        self._refresh_selected()
        self._refresh_hidden()
        self.status.set(f"Updated from the save: {len(village.known())} family members known "
                        f"({len(village.known()) - before:+d}).")
        if ask and getattr(self.full_village, "identity_questions", None):
            ask_identities(self, self.full_village.identity_questions)    # the same villager, or two?

    def _words_of(self, what: str) -> tuple[str, str, object]:
        """(the words as they are now, as the tree writes them, a function taking the new words) for
        anything the tree writes that the player may retype."""
        kind, _, name = what.partition(":")
        lay, e = self.lay, self.edits
        if kind in ("title", "subtitle"):
            k = 0 if kind == "title" else 1
            own = ft.default_title_lines(lay, self.game_title)[k]
            return getattr(e, kind) or own, own, lambda new: self._change(**{kind: "" if new == own else new})
        if kind == "word" and name.startswith("onward:"):
            return self._onward_words_of(name)
        if kind == "every_onward":              # every family's "continued on page N" words at once
            return self._onward_words_of(name, every=True)
        if kind == "word":
            own = ft.footer(lay) if name == "footer" else ft.WORDS[name]

            def set_words(new: str) -> None:
                if new and new != own:
                    e.words[name] = new
                else:
                    e.words.pop(name, None)
                self._saved()
            return ft.words(lay, name), own, set_words
        if kind == "mark":
            return name, name, lambda new: self._rename_mark(name, new)
        if kind == "label":
            g = int(name)
            own = "\n".join(ft.default_generation_label(lay, g))

            def set_label(new: str) -> None:
                self._set_generation_label(g, None if new == own else new.split("\n"))
                self._saved()
                self._show_generation()
            return "\n".join(ft.generation_label(lay, g)), own, set_label
        p = self.village.people[int(name)]
        own = "\n".join(ft.default_text(lay, p))

        def set_person(new: str) -> None:
            # The words' formatting kept where the retyping kept them (ft.carry_styles).
            runs = ft.carry_styles(ft.node_text(lay, p), ft.node_runs(lay, p), new.split("\n"))
            # (The patcher's own words, untouched and formatted as the tree formats them by default --
            # ft.default_runs -- stay the patcher's.)
            plain = new == own and runs in (None, ft.runs_data(ft.default_runs(lay, p)))
            self._set_entry(p, lines=None if plain else new.split("\n"), runs=runs)
            self._saved()
        return "\n".join(ft.node_text(lay, p)), own, set_person

    def _onward_family(self, name: str):
        """The family whose "continued on page N" words are `name` ("onward:<family key>"), or None."""
        return next((f for f in self.lay.families if f.onward and ft.onward_key(self.village, f) == name), None)

    def _onward_words_of(self, name: str, every: bool = False) -> tuple[str, str, object]:
        """(the words now, the default, a function taking new words) for one family's "continued on page N"
        words -- or, `every`, for every such family's: retyped with the page's number in them, that number
        stays the page's (kept as "{page}")."""
        e, fam = self.edits, self._onward_family(name)
        page = str(fam.onward_page) if fam is not None else ""
        if every:
            own_template = ft.WORDS["onward"]
            now_template = e.words.get("onward") or own_template
        else:
            own_template = e.words.get("onward") or ft.WORDS["onward"]
            now_template = e.words.get(name) or own_template

        def set_words(new: str) -> None:
            template = re.sub(rf"(?<!\d){re.escape(page)}(?!\d)", "{page}", new, count=1) if page else new
            key = "onward" if every else name
            if new.strip() and template != own_template:
                e.words[key] = template
            else:
                e.words.pop(key, None)
            self._saved()
        return now_template.replace("{page}", page), own_template.replace("{page}", page), set_words

    def _onward_reset(self, name: str | None) -> None:
        """One family's "continued on page N" words (or, None, every family's) back to the tree's own:
        their words, place and deletion."""
        e = self.edits
        names = [name] if name else ["onward"] + [k for k in e.words if k.startswith("onward:")]
        for k in names:
            e.words.pop(k, None)
        for k in [k for k in e.moved if k.startswith("onward:") and (name is None or k == name)]:
            del e.moved[k]
        e.hidden = [h for h in e.hidden if not (h == f"word:{name}" if name else h.startswith("word:onward"))]
        if name is None:
            e.styles.pop("onward", None)
            e.opacity.pop("onward", None)
        self._saved()
        self._refresh_hidden()

    def _edit_in_place(self, iid: int, what: str) -> None:
        """A box over the words, to retype them where they are (the owner: "DIRECTLY EDIT THE TEXT OF
        EVERYTHING BY CLICKING ON THEM AND RETYPING AS IF THEY WERE TEXT BOXES").  Enter (Ctrl+Enter
        for words of several lines) or clicking away keeps it; Esc leaves it as it was."""
        self.canvas.delete("editing")
        now, _own, commit = self._words_of(what)
        many = what.startswith(("label:", "person:"))
        font = tkfont.Font(font=self.canvas.itemcget(iid, "font"))
        if what.startswith("person:"):
            x, y, w, h, _a = self.lay.frame(int(what.partition(":")[2]))
            x, y = ft.to_page(self.sc, x, y + h / 3)
            x0, y0 = x * self.z, y * self.z
        else:
            x0, y0, _x1, _y1 = self.canvas.bbox(iid)
        lines = now.split("\n")
        box = tk.Text(self.canvas, font=font, width=max(12, max(len(line) for line in lines) + 2),
                      height=len(lines) + (1 if many else 0), wrap="none", undo=True, relief="solid", borderwidth=1)
        box.insert("1.0", now)
        box.tag_add("sel", "1.0", "end-1c")
        self.canvas.create_window(x0, y0, anchor="nw", window=box, tags="editing")
        done = {"yet": False}

        def finish(keep: bool) -> str:
            if done["yet"]:
                return "break"
            done["yet"] = True
            new = box.get("1.0", "end-1c").strip("\n")
            self.canvas.delete("editing")
            box.destroy()
            if keep and new.strip() and new != now:
                commit(new)
            return "break"

        box.bind("<Escape>", lambda _e: finish(False))
        box.bind("<FocusOut>", lambda _e: finish(True))
        box.bind("<Control-Return>", lambda _e: finish(True))
        if not many:
            box.bind("<Return>", lambda _e: finish(True))
        box.focus_set()
        self.status.set("Type the new words, then Enter" + (" (Ctrl+Enter: there may be several lines)" if many else "")
                        + " -- or Esc to leave them.")

    def _reorganize_portraits(self) -> None:
        """Every portrait dragged out of place put back neatly into the rows: each in the generation
        whose row it was left nearest, in the order, left to right, it was left in; and every line
        drawn afresh (Ctrl+Z puts them back as they were)."""
        lay, v = self.lay, self.village
        if self.edits.positioning == "packed_families":
            # No generation rows to put them back into: every portrait goes back under its parents, in
            # its own generation and order.
            for q in lay.x:
                self._set_entry(v.people[q], dx=None, dy=None)
            self._clear_line_moves()
            self._saved()
            self.status.set("Every portrait is back in its family's cluster.  Ctrl+Z undoes it.")
            return
        # Row by row of each generation, left to right in each (ft.tidy_rows): a wrapped generation's rows
        # are not interleaved (self-review, #578).
        gen_of, orders = ft.tidy_rows(lay)
        for q in lay.x:
            if q in lay.others:
                self._set_entry(v.people[q], dx=None, dy=None)
                continue
            g, p = gen_of[q], v.people[q]
            self._set_entry(p, dx=None, dy=None, generation=None if g == v.base_generation.get(q, p.generation) else g)
        self.edits.orders.update(orders)
        self._clear_line_moves()
        self._saved()
        self.status.set("Every portrait is back in a neat row, in the order and generation you left it.  "
                        "Ctrl+Z undoes it.")

    def _reorganize_lines(self) -> None:
        """Every line drawn afresh as a family tree has them (the owner: "they should reorganize all
        lines regardless"), moving portraits only where it must ("preferably not change portrait
        placement unless necessary"): a generation dragged so near the one above that its lines have
        no room goes down, with every generation below it, by just what the lines need."""
        lay, people = self.lay, self.village.people
        rows: dict[int, list[int]] = {}
        for q in lay.x:
            if q not in lay.others and self.edits.positioning != "packed_families":    # (no generation rows there)
                rows.setdefault(people[q].generation, []).append(q)
        gens = sorted(rows)
        top = {q: lay.frame(q)[1] for q in lay.x}                # each frame's top, as it will be
        moved = 0
        for above, g in zip(gens, gens[1:]):
            room = lay.tops[g] - (lay.tops[above] + lay.bands.get(above, ft.NODE_H))   # what its lines take
            needed = max(top[q] + lay.frame(q)[3] for q in rows[above]) + room
            for q in rows[g]:                   # only those too near the row above, just far enough
                if top[q] < needed:
                    entry = self._entry(people[q])
                    self._set_entry(people[q], dy=entry.get("dy", 0.0) + needed - top[q])
                    top[q] = needed
                    moved += 1
        self._clear_line_moves()
        self._saved()
        self.status.set("Every line is drawn afresh" + (f"; {moved} portrait(s) moved down to make room for them"
                                                       if moved else ", with no portrait moved") + ".  Ctrl+Z undoes it.")

    def _reorganize_labels(self) -> None:
        """Each generation's label back beside its generation's portraits."""
        for name in [n for n in self._moved_now() if n.startswith("label")]:
            self._move_to(name, None)
        self._saved()
        self.status.set("Each generation's label is beside its portraits.  Ctrl+Z undoes it.")

    def _sure(self, question: str) -> bool:
        return messagebox.askyesno("Family Tree Maker", question + "  (Undo brings it back.)", parent=self)

    def _reset_shapes(self) -> None:
        """Every portrait's shape and border as the patcher draws them, not resized (on their own or by
        their group), turned or flipped -- as the question says (the groups' sizes and the flips stayed)."""
        if not self._sure("Put every portrait's shape and border back, and undo every resize and turn?"):
            return
        self.edits.shapes, self.edits.borders = dict(ft.DEFAULT_SHAPES), dict(ft.DEFAULT_BORDERS)
        self.edits.sizes.clear()
        for p in self.village.people.values():
            self._set_entry(p, shape=None, border=None, w=None, h=None, angle=None, flip_h=None, flip_v=None)
        self._saved()
        self._refresh_panels()
        self.status.set("Every portrait has its own shape and border again.  Ctrl+Z undoes it.")

    def _reset_lines(self) -> None:
        """Every line where the tree draws it."""
        if not self._sure("Put every line back where the tree draws it?"):
            return
        self._clear_line_moves()
        self._saved()
        self.status.set("Every line is back where the tree draws it.  Ctrl+Z undoes it.")

    def _reset_portraits(self) -> None:
        """Every family member back in their own place, generation and order (their text, marks and
        colours stay)."""
        if not self._sure("Put every family member back in their own place, generation and order?"):
            return
        for p in self.village.people.values():
            self._set_entry(p, dx=None, dy=None, generation=None)
        self.edits.orders.clear()
        self._saved()
        self.status.set("Every family member is back in their own place, generation and order.  Ctrl+Z undoes it.")

    def _reset_everything(self) -> None:
        """The tree as the patcher first draws it: every edit, mark, colour, font, background,
        picture, text box and move gone."""
        if not self._sure("Reset the whole tree to its default settings?  Every mark, colour, font, background, "
                          "picture, text box and move goes."):
            return
        self.edits = ft.Edits()
        self.obj = None
        self._saved()
        self._refresh_panels()
        self.status.set("The tree is back to its default settings.  Ctrl+Z undoes it.")

    def _unmove_all(self) -> None:
        for name in list(self._moved_now()):
            self._move_to(name, None)
        self._clear_line_moves()
        for q in self.village.people:
            self._set_entry(self.village.people[q], dx=None, dy=None)
        self._saved()

    def _move_start(self, event, iid: int) -> bool:
        """A press on something that moves: what the drag will move."""
        tags = self.canvas.gettags(iid)
        x, y = self._where(event)
        named = [tag[2:] for tag in tags if tag.startswith("m_")]
        if named:
            x0, y0, x1, y1 = self.canvas.bbox(f"m_{named[0]}")
            self.move = {"name": named[0], "x": x, "y": y, "dx": 0.0, "dy": 0.0, "started": False,
                         "box": (x0 / self.z, y0 / self.z, x1 / self.z, y1 / self.z)}
            return True
        return False

    def _move_drag(self, event) -> None:
        m = self.move
        x, y = self._where(event)
        dx, dy = x - m["x"], y - m["y"]
        if not m["started"] and abs(dx) * self.z < 4 and abs(dy) * self.z < 4:
            return
        m["started"] = True
        if "piece" in m:                        # a line piece (the joined ones follow on release)
            if not self.edits.diagonal_lines:   # only across itself
                x0, y0, x1, y1 = self.canvas.coords(m["iid"])[:4]
                dx, dy = (dx, 0.0) if x0 == x1 and y0 != y1 else (0.0, dy)
            self.canvas.move(m["iid"], (dx - m["dx"]) * self.z, (dy - m["dy"]) * self.z)
            self.canvas.addtag_withtag("moved", m["iid"])      # drawn again where it belongs (_place_units)
            m["dx"], m["dy"] = dx, dy
            return
        if "box" not in m:                      # villagers: the box round every one moving
            boxes = [self.sc.boxes[q] for q in m["pids"]]
            m["box"] = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                        max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes))
        dx, dy = self._snap(m["box"], dx, dy, event, pids=set(m.get("pids", ())))
        step_x, step_y = (dx - m["dx"]) * self.z, (dy - m["dy"]) * self.z
        if "name" in m:
            self.canvas.move(f"m_{m['name']}", step_x, step_y)
            self.canvas.addtag_withtag("moved", f"m_{m['name']}")   # drawn again where it belongs (_place_units)
        else:
            for q in m["pids"]:
                self.canvas.move(f"p{q}", step_x, step_y)
                self.canvas.addtag_withtag("moved", f"p{q}")
            self.canvas.move("selection", step_x, step_y)
        m["dx"], m["dy"] = dx, dy

    def _move_end(self, event=None) -> None:
        m, self.move = self.move, None
        self.canvas.delete("guide")
        if not m["started"]:
            if "pids" in m and m.get("only") is not None:
                self._select([m["only"]])           # a plain click on one of several selected
            words, self.press_words = self.press_words, None
            if words is not None and words in self.editable:
                self._edit_in_place(words, self.editable[words])
            return
        k = self.sc.fit[0]                      # page distances back in the tree's own (a shrunk canvas)
        m["dx"], m["dy"] = m["dx"] / k, m["dy"] / k
        if "piece" in m:
            old = self._line_moves_now().get(m["piece"], [0.0, 0.0])
            if not isinstance(old, list):       # saved before lines moved both ways: across itself
                x0, y0, x1, y1 = self.canvas.coords(m["iid"])[:4]
                old = [old, 0.0] if x0 == x1 and y0 != y1 else [0.0, old]
            shift = [old[0] + m["dx"], old[1] + m["dy"]]
            # On the shown page alone.  Put down with Alt: exactly there (ft.Edits.free_lines); else nudged off
            # any line it would lie on.
            self._set_line_move(m["piece"], shift if any(shift) else None,
                                free=event is not None and bool(event.state & ALT))
        elif "name" in m:
            old = self._moved_now().get(m["name"], [0.0, 0.0])
            self._move_to(m["name"], [old[0] + m["dx"], old[1] + m["dy"]])
        else:
            for q in m["pids"]:
                p = self.village.people[q]
                entry = self._entry(p)
                self._set_entry(p, dx=entry.get("dx", 0.0) + m["dx"], dy=entry.get("dy", 0.0) + m["dy"])
        self._saved()

    # ---- snapping and aligning ------------------------------------------------------
    def _snap(self, box: tuple, dx: float, dy: float, event, pids: set = frozenset(),
              sticker: int | None = None) -> tuple[float, float]:
        """A drag of `box` by (dx, dy), pulled onto a smart guide -- another family member's or
        picture's edge or middle, or the middle of the tree -- and else onto the grid, with the
        guide shown.  Alt held: as dragged."""
        c = self.canvas
        c.delete("guide")
        if event.state & ALT:
            return dx, dy
        x0, y0, x1, y1 = box
        reach = SNAP_REACH / self.z
        found = {}
        if self.smart_var.get():
            others = [(bx, by, bx + bw, by + bh) for q, (bx, by, bw, bh) in self.sc.boxes.items() if q not in pids]
            others += [st.bounds() for st in self.sc.stickers if st.index != sticker]
            middle = (self.sc.width / 2, self.sc.height / 2)
            for axis, moved, shift in ((0, (x0, (x0 + x1) / 2, x1), dx), (1, (y0, (y0 + y1) / 2, y1), dy)):
                lines = [v for b in others for v in (b[axis], (b[axis] + b[axis + 2]) / 2, b[axis + 2])]
                lines.append(middle[axis])
                best = None
                for edge in moved:
                    for line in lines:
                        gap = line - (edge + shift)
                        if abs(gap) <= reach and (best is None or abs(gap) < abs(best[0])):
                            best = (gap, line)
                if best is not None:
                    found[axis] = best
        if 0 in found:
            dx += found[0][0]
        elif self.snap_var.get():
            g = int(self.grid_size.get())
            dx += round((x0 + dx) / g) * g - (x0 + dx)
        if 1 in found:
            dy += found[1][0]
        elif self.snap_var.get():
            g = int(self.grid_size.get())
            dy += round((y0 + dy) / g) * g - (y0 + dy)
        z = self.z
        if 0 in found:
            v = found[0][1] * z
            c.create_line(v, 0, v, self.sc.height * z, fill=GUIDE, dash=(6, 4), width=1, tags="guide")
        if 1 in found:
            v = found[1][1] * z
            c.create_line(0, v, self.sc.width * z, v, fill=GUIDE, dash=(6, 4), width=1, tags="guide")
        return dx, dy

    def _draw_grid(self) -> None:
        c = self.canvas
        c.delete("grid")
        if not self.show_grid.get():
            return
        g = int(self.grid_size.get()) * self.z
        width, height = self.sc.width * self.z, self.sc.height * self.z
        colour = "#c8d2c0" if not ft.is_dark(self.lay.background) else "#3a4a3a"
        for k in range(1, int(width / g) + 1):
            c.create_line(k * g, 0, k * g, height, fill=colour, tags="grid")
        for k in range(1, int(height / g) + 1):
            c.create_line(0, k * g, width, k * g, fill=colour, tags="grid")
        c.tag_lower("grid")
        c.tag_lower("backdrop")

    def _align(self, how: str) -> None:
        """Line the selected family members up (or the selected picture or text box, on the tree)."""
        if self.obj is not None and not self.selected:
            st = self._sticker()
            if st is None:
                return
            x0, y0, x1, y1 = st.bounds()
            boxes = {None: (x0, y0, x1 - x0, y1 - y0)}
        else:
            boxes = {q: self.sc.boxes[q] for q in self.selected if q in self.sc.boxes}
        if not boxes or (len(boxes) < 2 and how not in ("page_x", "page_y")):
            self.status.set("Select two or more family members to line them up (one to centre it on the tree).")
            return
        if how.startswith("spread") and len(boxes) < 3:
            self.status.set("Select three or more family members to space them evenly.")
            return
        lefts = {k: b[0] for k, b in boxes.items()}
        tops = {k: b[1] for k, b in boxes.items()}
        rights = {k: b[0] + b[2] for k, b in boxes.items()}
        bottoms = {k: b[1] + b[3] for k, b in boxes.items()}
        moves: dict = {}
        if how == "left":
            moves = {k: (min(lefts.values()) - lefts[k], 0) for k in boxes}
        elif how == "right":
            moves = {k: (max(rights.values()) - rights[k], 0) for k in boxes}
        elif how == "centre":
            mid = (min(lefts.values()) + max(rights.values())) / 2
            moves = {k: (mid - (lefts[k] + rights[k]) / 2, 0) for k in boxes}
        elif how == "top":
            moves = {k: (0, min(tops.values()) - tops[k]) for k in boxes}
        elif how == "bottom":
            moves = {k: (0, max(bottoms.values()) - bottoms[k]) for k in boxes}
        elif how == "middle":
            mid = (min(tops.values()) + max(bottoms.values())) / 2
            moves = {k: (0, mid - (tops[k] + bottoms[k]) / 2) for k in boxes}
        elif how == "page_x":
            shift = self.sc.width / 2 - (min(lefts.values()) + max(rights.values())) / 2
            moves = {k: (shift, 0) for k in boxes}
        elif how == "page_y":
            shift = self.sc.height / 2 - (min(tops.values()) + max(bottoms.values())) / 2
            moves = {k: (0, shift) for k in boxes}
        else:
            axis = 0 if how == "spread_x" else 1
            centre = {k: b[axis] + b[axis + 2] / 2 for k, b in boxes.items()}
            order = sorted(boxes, key=lambda k: centre[k])
            first, last = centre[order[0]], centre[order[-1]]
            for i, k in enumerate(order):
                want = first + (last - first) * i / (len(order) - 1)
                moves[k] = (want - centre[k], 0) if axis == 0 else (0, want - centre[k])
        for k, (mx, my) in moves.items():
            if k is None:
                raw = self.edits.stickers[self.obj]
                raw["cx"] += mx
                raw["cy"] += my
            else:                               # page distances back in the tree's own (a shrunk canvas)
                p = self.village.people[k]
                entry = self._entry(p)
                s = self.sc.fit[0]
                self._set_entry(p, dx=entry.get("dx", 0.0) + mx / s, dy=entry.get("dy", 0.0) + my / s)
        self._saved()

    def _head(self, sheet: str, row: int, scale: float = 1.0):
        """A head at the zoom, `scale` times its size (a resized portrait's); the canvas can only
        scale a picture by whole ratios, so the nearest small one."""
        key = (sheet, row, self.z, scale)
        if key not in self.photos:
            source = self.photos.get(sheet)
            if source is None:
                source = self.photos[sheet] = tk.PhotoImage(master=self, file=str(self.present[sheet]))
            ratio = (Fraction(*ZOOMS[self.z]) * Fraction(scale).limit_denominator(8)).limit_denominator(8)
            up, down = ratio.numerator, ratio.denominator
            cell = tk.PhotoImage(master=self)
            x0, y0 = ft.HEAD_FRAME * ft.HEAD_W, row * ft.HEAD_H
            cell.tk.call(cell, "copy", source, "-from", x0, y0, x0 + ft.HEAD_W, y0 + ft.HEAD_H, "-zoom", up)
            small = tk.PhotoImage(master=self)
            small.tk.call(small, "copy", cell, "-subsample", down)
            self.photos[key] = small
        return self.photos[key]

    def _colour_under(self, x: float, y: float, sc: ft.Scene) -> str:
        """The colour the page shows at (x, y) of the tree: the drawn background picture or
        gradient there, else the background colour."""
        photo = self.photos.get("backdrop")
        if photo is not None:
            try:
                px = min(max(0, int(x * self.z)), photo.width() - 1)
                py = min(max(0, int(y * self.z)), photo.height() - 1)
                pixel = photo.get(px, py)
                r, g, b = (int(v) for v in (pixel.split() if isinstance(pixel, str) else pixel)[:3])
                return f"#{r:02x}{g:02x}{b:02x}"
            except (tk.TclError, TypeError, ValueError):
                pass
        return sc.background

    def _draw_backdrop(self, item: ft.Backdrop, sc: ft.Scene) -> int | None:
        """The background as GDI+ draws it into the picture, shown as an image (its canvas item)."""
        key = (item.colour, item.colour2, str(item.picture), item.fit, item.soften, int(sc.width), int(sc.height),
               self.z)
        if key != self.backdrop_key:
            pending = getattr(self, "_backdrop_job", None)
            if pending is not None:
                self.after_cancel(pending)
                self._backdrop_job = None
            same_picture = (self.backdrop_key is not None and self.backdrop_key[:5] == key[:5]
                            and "backdrop" in self.photos)
            if same_picture:
                # Only the page's size or the zoom changed (everyone dragged, say): the background as it was
                # for now, and drawn again a moment later -- a picture background takes a second to draw,
                # and every move waited for it (the owner: "less lag especially when selecting all").
                self._backdrop_job = self.after(250, lambda: self._redraw_backdrop(item, sc, key))
            else:
                self._make_backdrop(item, sc, key)
        self._backdrop_iid = None
        if "backdrop" in self.photos:
            self._backdrop_iid = self.canvas.create_image(0, 0, image=self.photos["backdrop"], anchor="nw",
                                                          tags="backdrop")
        return self._backdrop_iid

    def _make_backdrop(self, item: ft.Backdrop, sc: ft.Scene, key: tuple, keep: bool = False) -> None:
        """The background picture or gradient drawn by GDI+ in the background, and the tree drawn again
        with it when it is ready (a picture took over a second to draw, and opening the editor waited
        for it); the page's colour meanwhile -- or, `keep`, the picture as it was."""
        self.backdrop_key = key
        if not keep:
            self.photos.pop("backdrop", None)
        if not ((item.colour2 or item.picture is not None) and vf1_gdiplus.available()):
            self.photos.pop("backdrop", None)
            return
        self._backdrop_n = number = self.__dict__.get("_backdrop_n", 0) + 1
        temp = Path(tempfile.gettempdir()) / f"vvfp-tree-backdrop-{os.getpid()}-{number}.png"
        plain, z, done = ft.Scene(sc.width, sc.height, item.colour, [item]), self.z, {"temp": temp}

        def work() -> None:
            try:
                done["ok"] = vf1_gdiplus.save_scene(plain, {}, temp, scale=z)
            except (OSError, ValueError):
                done["ok"] = False
            if done.get("closed"):              # the editor closed meanwhile: nobody will show it
                temp.unlink(missing_ok=True)
        self._backdrop_done = done
        thread = threading.Thread(target=work, name="Family Tree background", daemon=True)
        thread.start()
        self._backdrop_ready(thread, done, temp, key)

    def _backdrop_ready(self, thread, done: dict, temp: Path, key: tuple) -> None:
        """The background picture shown once GDI+ has drawn it (unless the background changed again)."""
        self._backdrop_poll = None
        if thread.is_alive():
            self._backdrop_poll = self.after(30, lambda: self._backdrop_ready(thread, done, temp, key))
            return
        try:
            if done.get("ok") and key == self.backdrop_key:
                self.photos["backdrop"] = tk.PhotoImage(master=self, file=str(temp))
                self._same_scene = True         # see-through marks fade into it (_colour_under)
                self._draw_tree()
        except tk.TclError:
            pass                                # the editor was closed meanwhile
        finally:
            try:
                temp.unlink()
            except OSError:
                pass

    def _redraw_backdrop(self, item: ft.Backdrop, sc: ft.Scene, key: tuple) -> None:
        """The background drawn again at the page's new size or zoom, put in place of the old one."""
        self._backdrop_job = None
        if self.sc is not sc and (int(self.sc.width), int(self.sc.height)) != key[5:7]:
            return                              # the page changed again: its own redraw has asked
        self._make_backdrop(item, sc, key, keep=True)

    def _draw_selection(self) -> None:
        self.canvas.delete("selection")
        z = self.z
        for pid in self.selected:
            x, y, w, h = self.sc.boxes[pid]
            self.canvas.create_rectangle((x - 9) * z, (y - 9) * z, (x + w + 9) * z, (y + h + 9) * z, outline=SELECT,
                                         width=3, dash=(5, 3), tags="selection")
        self._draw_handles()

    # ---- selecting ----------------------------------------------------------
    def _at(self, event) -> int | None:
        """The family member clicked: inside their portrait's shape, or on their head or words -- never the
        empty corners round them (the owner: "make the click area for things limited to the object
        themselves")."""
        x, y = ft.to_tree(self.sc, *self._where(event))
        for pid in reversed(list(self.lay.x)):
            if ft.inside(self.lay.frame_points(pid), x, y):
                return pid
        c = self.canvas
        cx, cy = c.canvasx(event.x), c.canvasy(event.y)
        for iid in reversed(c.find_overlapping(cx, cy, cx, cy)):
            if c.type(iid) in ("text", "image"):
                tag = next((t for t in c.gettags(iid) if t[:1] == "p" and t[1:].isdigit()), None)
                if tag is not None:
                    return int(tag[1:])
        return None

    def _order(self) -> list[int]:
        return sorted(self.sc.boxes, key=lambda q: (self.sc.boxes[q][1], self.sc.boxes[q][0]))

    def _press(self, event) -> None:
        self.canvas.focus_set()
        if self._tools_press(event):
            return
        self.move = None
        iid = self._grab(event)
        # Words clicked (not dragged) are retyped where they are, once the press is let go.
        plain = not event.state & 0x5
        self.press_words = iid if plain and iid in self.editable and self.canvas.type(iid) == "text" else None
        if iid in self.pieces:
            x, y = self._where(event)
            self.move = {"piece": self.pieces[iid], "iid": iid, "x": x, "y": y, "dx": 0.0, "dy": 0.0,
                         "started": False}
            return
        if iid is not None and self._move_start(event, iid):
            return
        pid = self._at(event)
        ctrl, shift = bool(event.state & 0x4), bool(event.state & 0x1)
        if pid is None:
            if ctrl or shift:                   # Shift or Ctrl and drag: a box around villagers
                self.band = (*self._where(event), True)
            else:                               # drag: move around the tree; a click clears
                self._pan_start(event)
            return
        self.band = None
        if shift and self.anchor in self.sc.boxes:
            order = self._order()
            a, b = sorted((order.index(self.anchor), order.index(pid)))
            run = order[a:b + 1]
            self._select(list(dict.fromkeys((self.selected if ctrl else []) + run)), keep_anchor=True)
        elif ctrl:
            self._select([q for q in self.selected if q != pid] if pid in self.selected else self.selected + [pid])
            self.anchor = pid
        elif pid in self.selected and len(self.selected) > 1:
            self.anchor = pid                   # keep the others: they may be dragged together
        else:
            self._select([pid])
            self.anchor = pid
        if pid in self.selected:                # dragging moves every selected villager
            x, y = self._where(event)
            self.move = {"pids": list(self.selected), "x": x, "y": y, "dx": 0.0, "dy": 0.0, "started": False,
                         "only": pid if len(self.selected) > 1 and not (ctrl or shift) else None}

    def _drag(self, event) -> None:
        if self._tools_drag(event):
            return
        if getattr(self, "move", None) is not None:
            self._move_drag(event)
            return
        if self.pan is not None:
            self._pan_move(event)
            return
        if self.band is None:
            return
        x0, y0, _add = self.band
        x1, y1 = self._where(event)
        z = self.z
        self.canvas.delete("band")
        self.canvas.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z, outline=SELECT, dash=(3, 3), tags="band")

    def _release(self, event) -> None:
        if self._tools_release(event):
            return
        if getattr(self, "move", None) is not None:
            self._move_end(event)
            return
        if self.pan is not None:
            if not self._pan_end(event):
                self._select([])                # a click on empty space, not a drag
            return
        if self.band is None:
            return
        x0, y0, add = self.band
        x1, y1 = self._where(event)
        self.canvas.delete("band")
        self.band = None
        lo_x, hi_x, lo_y, hi_y = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
        if hi_x - lo_x < 4 and hi_y - lo_y < 4:
            if not add:
                self._select([])
            return
        inside = [pid for pid, (bx, by, bw, bh) in self.sc.boxes.items()
                  if bx + bw >= lo_x and bx <= hi_x and by + bh >= lo_y and by <= hi_y]
        self._select(list(dict.fromkeys((self.selected if add else []) + inside)))

    def _select_all(self, _event=None):
        if self._typing():
            return None
        self.obj = None
        self._select(self._order())
        self._draw_handles()
        self._refresh_obj_panel()
        return "break"

    def _escape(self, _event=None) -> None:
        self.obj = None
        self._select([])
        self._draw_handles()
        self._refresh_obj_panel()

    def _flush_live(self) -> None:
        """What was typed in a size box and not yet applied (_live waits 800 ms), applied now -- to
        those it was typed for.  Clicking another family member within the wait showed their sizes in the
        boxes first, and the value typed was lost."""
        waiting = self.__dict__.get("live_waiting", {})
        while waiting:
            waiting.popitem()[1]()

    def _select(self, pids: list[int], keep_anchor: bool = False) -> None:
        self._flush_live()
        self.selected =[q for q in pids if q in self.sc.boxes]
        if not keep_anchor and len(self.selected) == 1:
            self.anchor = self.selected[0]
        self._draw_selection()
        self._refresh_selected()

    def _refresh_selected(self) -> None:
        people = [self.village.people[q] for q in self.selected]
        if not people:
            self.sel_label.set("Click a family member on the tree to edit them.  Ctrl+click or Shift+click to pick several.")
        elif len(people) == 1:
            self.sel_label.set(gen.describe_person(self.village, people[0]))
        else:
            names = ", ".join(p.name for p in people[:8]) + ("..." if len(people) > 8 else "")
            self.sel_label.set(f"{len(people)} selected: {names}")
        self.lines_text.configure(state="normal")
        self.lines_text.delete("1.0", "end")
        if len(people) == 1 and hasattr(self, "lay"):
            self._box_load(ft.node_text(self.lay, people[0]), ft.node_runs(self.lay, people[0]))
        else:
            self.lines_text.configure(state="disabled")
        marks = ["(none)"] + list(self.edits.marks)
        self.mark_box.configure(values=marks)
        current = {(ft.entry_marks(self._entry(p)) or ["(none)"])[0] for p in people}
        self.mark_var.set(current.pop() if len(current) == 1 else "")
        self._refresh_mark_checks(people)
        gens = {p.generation for p in people}
        self.gen_choice.set(str(gens.pop()) if len(gens) == 1 else "")
        colours = {self._colours_now("family_colours").get(self._family(p), "") if self._family(p) is not None
                   else self._colours_now("person_colours").get(ft.entry_key(self.village, p), "") for p in people}
        self.family_field.set_quietly(colours.pop() if len(colours) == 1 else "")
        for attr, choices in (("shape", ft.PORTRAIT_SHAPES), ("border", ft.BORDERS)):
            if hasattr(self, "lay"):
                now = {ft.base_kind(getattr(self.lay, attr)(p)) if attr == "shape" else getattr(self.lay, attr)(p)
                       for p in people}
                self.own_vars[attr].set(choices[now.pop()] if len(now) == 1 else "")
        sizes = [ft.frame_size(self.edits, self.village, p, unscaled=True) for p in people]
        styles = [self.edits.family_lines.get(self._family(p) or "", {}) for p in people]
        for var, values in ((self.own_w, {w for w, _h in sizes}), (self.own_h, {h for _w, h in sizes}),
                            (self.own_line_w, {s.get("width", self.edits.line_width) for s in styles})):
            var.set(f"{values.pop():g}" if len(values) == 1 else "")      # blank where they differ
        dashes = {s.get("dash", self.edits.line_dash) for s in styles}
        self.own_line_dash.set(ft.LINE_TYPES[dashes.pop()] if len(dashes) == 1 else "")
        texts = {self._entry(p).get("text_scale", 100.0) for p in people}
        self.own_text.set(f"{texts.pop():g}" if len(texts) == 1 else "")
        pictures = {self._entry(p).get("picture_scale", 100.0)
                    for p in people}
        self.own_picture.set(f"{pictures.pop():g}" if len(pictures) == 1 else "")
        for flip, var in self.own_flips.items():         # ticked when every one selected is flipped
            var.set(bool(people) and all(self._entry(q).get(flip, False) for q in people))
        fills = {self._entry(q).get("fill", "") for q in people}
        self.own_fill.set_quietly(fills.pop() if len(fills) == 1 else "")
        details_ = {self._entry(q).get("detail", "") for q in people}
        self.own_detail.set_quietly(details_.pop() if len(details_) == 1 else "")
        turns = {round(self._entry(q).get("angle", 0.0), 1) for q in people}
        self.own_turn.set(f"{turns.pop():g}" if len(turns) == 1 else "")
        if hasattr(self, "info_tab"):
            self.info_tab.refresh()

    # ---- changing -----------------------------------------------------------
    def _group_style(self, attr: str, group: str, value: str) -> None:
        """Every male's, female's or upcoming baby's portrait shape or border."""
        getattr(self.edits, attr)[group] = value
        self._saved()

    def _text_wrap(self) -> None:
        """How many characters fit across a portrait before a line wraps."""
        try:
            n = max(ft.WRAP_MIN, min(ft.WRAP_MAX, int(float(self.wrap_var.get()))))
        except ValueError:
            return
        if n != self._view().text_wrap:
            self._change(text_wrap=n)

    def _portrait_gap(self) -> None:
        """The pixels between two portraits side by side, for every portrait."""
        gap = self._number(self.gap_var.get(), ft.GAP_MIN, ft.GAP_MAX)
        if gap is not None and gap != self.edits.portrait_gap:
            self._change(portrait_gap=gap)

    def _detail_number(self, attr: str, var: tk.StringVar, low: float, high: float) -> None:
        value = self._number(var.get(), low, high)
        if value is not None and value != getattr(self._view(), attr):    # the picked group's (Settings for:)
            self._change(**{attr: value})

    def _own_fill(self, colour: str) -> None:
        """Every selected family member's portrait filled with this colour inside ("": the whole tree's)."""
        if not self.selected:
            return
        for q in self.selected:
            self._set_entry(self.village.people[q], fill=colour or None)
        self._saved()

    def _own_detail(self, colour: str) -> None:
        """Every selected family member's detail lines (inside the portrait) this colour ("": the whole tree's)."""
        if not self.selected:
            return
        for q in self.selected:
            self._set_entry(self.village.people[q], detail=colour or None)
        self._saved()

    def _own_flip(self, flip: str) -> None:
        """Every selected family member's portrait shape flipped (or not), its words never mirrored."""
        if not self.selected:
            return
        on = bool(self.own_flips[flip].get())
        for q in self.selected:
            self._flip_as_seen(self.village.people[q], flip, on)     # as seen on the page (the owner)
        self._saved()

    def _reset_button(self, parent, *fields: str) -> ttk.Button:
        """A small Reset putting these settings back as a new tree has them (the owner, 2026-10-09: "please
        add reset buttons beside anything you can change"); with a group picked ("Settings for:"), that
        group's own settings cleared, so it is the same as everyone's again."""
        import copy

        def reset() -> None:
            group = self._scope()
            if group and all(name in ft.GROUP_FIELDS for name in fields):
                self._clear_group(group, fields)
                return
            fresh = ft.Edits()
            values = {name: copy.deepcopy(getattr(fresh, name)) for name in fields}
            if any(values[name] != getattr(self.edits, name) for name in fields):
                self._change(everyone=True, **values)
                self._refresh_panels()
        return ttk.Button(parent, text="Reset", width=6, command=reset)

    # ---- settings by group ("Settings for:") -----------------------------------
    def _scope_picker(self, parent) -> ttk.Frame:
        """"Settings for:" Everyone or one group (one choice, shown in every place it is), with "Same as
        everyone" (the picked group's own settings cleared) and "Make every group the same" (every
        group's), and a note when the picked group's settings differ from everyone's."""
        frame = ttk.Frame(parent)
        row = ttk.Frame(frame)
        row.pack(anchor="w", fill="x")
        ttk.Label(row, text="Settings for:").pack(side="left")
        combo = ttk.Combobox(row, textvariable=self.scope_var, values=[EVERYONE] + list(ft.GROUPS.values()),
                             state="readonly", width=17)
        combo.pack(side="left", padx=(6, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_panels())
        ttk.Button(row, text="Same as everyone", command=lambda: self._clear_group(self._scope())).pack(
            side="left", padx=(6, 0))
        ttk.Button(row, text="Make every group the same", command=self._all_groups_same).pack(side="left", padx=(4, 0))
        flow_row(row)           # wraps in a narrow panel (the owner's screenshot: "Make every..." cut off)
        ttk.Label(frame, textvariable=self.scope_note, foreground="#8a4b00").pack(anchor="w")
        return frame

    def _scope(self) -> str | None:
        """The group picked in "Settings for:" (ft.GROUPS), or None for everyone."""
        label = self.scope_var.get() if hasattr(self, "scope_var") else EVERYONE
        return next((g for g, name in ft.GROUPS.items() if name == label), None)

    def _view(self) -> ft.Edits:
        """The settings as the picked group's portraits have them (everyone's when none is picked)."""
        return ft.group_view(self.edits, self._scope())

    def _show_scope_note(self) -> None:
        group = self._scope()
        if not hasattr(self, "scope_note"):
            return
        if group is None:
            own = [ft.GROUPS[g] for g in ft.GROUPS if self.edits.group_opts.get(g)]
            self.scope_note.set(f"{' and '.join(own)} have settings of their own." if own else "")
        else:
            differ = [n for n, v in self.edits.group_opts.get(group, {}).items()
                      if n != "centre_heads" and v != getattr(self.edits, n)]
            self.scope_note.set(f"{ft.GROUPS[group]}: {len(differ)} setting{'' if len(differ) == 1 else 's'} "
                                "differ from everyone's." if differ else f"{ft.GROUPS[group]}: the same as everyone.")

    def _clear_group(self, group: str | None, fields=None) -> None:
        """A group's own settings (all, or `fields`) cleared: everyone's again.  One step to undo."""
        if group is None:
            return
        own = dict(self.edits.group_opts.get(group, {}))
        names = [n for n in own if fields is None or n in fields]
        if not names:
            return
        for name in names:
            own.pop(name)
        if {"picture_size", "text_size"} & set(names):
            self._end_equal(group)
        if "text_valign" not in own:
            own.pop("centre_heads", None)
        groups = {g: v for g, v in self.edits.group_opts.items() if g != group}
        if own:
            groups[group] = own
        self.edits.group_opts = groups
        self._saved()
        self._refresh_panels()

    def _all_groups_same(self) -> None:
        """Every group's own settings cleared: every portrait as everyone's.  One step to undo."""
        if self.edits.group_opts:
            for group, own in self.edits.group_opts.items():
                if {"picture_size", "text_size"} & set(own):
                    self._end_equal(group)
            self.edits.group_opts = {}
            self._saved()
            self._refresh_panels()

    def _equalize(self, group: str | None) -> None:
        """Every family member's face and text at the tree's own sizes -- everyone's, or one group's: each one's own
        face size and text size cleared (the owner, 2026-10-09: "buttons to "equalize" text/face sizes etc
        across the entire family tree or by group").  Exactly the same (the owner, 2026-10-10: "should
        have the exact same font size and icon dimensions regardless of other settings"): faces and words
        keep one size, the scope's own face and text sizes are cleared, and the scope keeps one face size
        and one font size, the largest that fits every one of its portraits (Edits.equal_sizes), whatever
        is resized or added later -- until a face or text size is changed again.  One undo step."""
        e = self.edits
        groups = list(ft.GROUPS) if group is None else [group]
        for p in self.village.people.values():
            if ft.group_of(p) in groups and {"picture_scale", "text_scale"} & set(self._entry(p)):
                self._set_entry(p, picture_scale=None, text_scale=None)
        opts = {g: dict(v) for g, v in e.group_opts.items()}
        for g in groups:
            own = opts.get(g, {})
            for name in ("picture_size", "text_size", "fixed_face_size"):
                own.pop(name, None)
            if group is not None and not e.fixed_face_size:
                own["fixed_face_size"] = True
            opts[g] = own
        e.group_opts = {g: v for g, v in opts.items() if v}
        if group is None:
            e.fixed_face_size = True
            e.equal_sizes = {}
        sizes = {"face": float(e.picture_size), "text": float(e.text_size)}
        e.equal_sizes = dict(e.equal_sizes, **{group or "all": sizes})
        self._saved()
        self._refresh_panels()
        self.status.set(f"{'Everyone' if group is None else ft.GROUPS[group]}: every face and every name the same "
                        "size.  Changing a face or text size again ends it.  Ctrl+Z undoes it.")

    def _end_own_equal(self) -> None:
        """The selected family members' own face or text size changed: their groups no longer kept the same."""
        for group in {ft.group_of(self.village.people[q]) for q in self.selected}:
            self._end_equal(group)

    def _end_equal(self, group: str | None) -> None:
        """A face or text size changed for everyone (None) or one group: those portraits are no longer
        kept the same ("Same face and text size for:"); the other groups made the same with everyone stay so."""
        sizes = self.edits.equal_sizes
        if not sizes:
            return
        if group is None:
            self.edits.equal_sizes = {}
            return
        sizes = dict(sizes)
        everyone = sizes.pop("all", None)
        if everyone is not None:
            for g in ft.GROUPS:
                sizes.setdefault(g, dict(everyone))
        sizes.pop(group, None)
        self.edits.equal_sizes = sizes

    def _equalize_sizes(self) -> None:
        """Every family member back to their group's portrait size: each one's own width and height cleared."""
        changed = [p for p in self.village.people.values() if {"w", "h"} & set(self._entry(p))]
        for p in changed:
            self._set_entry(p, w=None, h=None)
        if changed:
            self._saved()

    def _own_inner_reset(self) -> None:
        """The selected family members' own face and text sizes cleared: the tree's sizes again."""
        if not self.selected:
            return
        for q in self.selected:
            self._set_entry(self.village.people[q], picture_scale=None, text_scale=None)
        self._end_own_equal()
        self.own_picture.set("100")
        self.own_text.set("100")
        self._saved()

    def _row_limit(self) -> None:
        """The most portraits in a row before a generation wraps (0: no limit)."""
        value = self._number(self.row_limit_var.get(), 0, ft.ROW_LIMIT_MAX)
        if value is not None and int(value) != self.edits.row_limit:
            self._change(row_limit=int(value))

    def _show_packing(self) -> None:
        """How tightly packed: shown under the Layout list while a Packed layout is chosen."""
        self.packing_var.set(f"How tightly packed: {self.edits.packing}  (0 tidy, 100 tightest)")
        if hasattr(self, "lines_behind_var"):   # the tree's own choice follows the layout and the packing
            self.lines_behind_var.set(ft.behind(self.edits))
        if self.edits.positioning in ("packed_families", "packed_generations"):
            self.packing_row.pack(fill="x", pady=(6, 0), after=self.positions_box)
        else:
            self.packing_row.pack_forget()

    def _packing_moved(self, value) -> None:
        """The tree follows the slider as it moves (a moment after each step, so dragging stays smooth);
        it becomes one step to undo when the slider is let go."""
        value = int(round(float(value)))
        if value == self.edits.packing:
            return
        self.edits.packing = value
        self.packing_var.set(f"How tightly packed: {value}  (0 tidy, 100 tightest)")
        if getattr(self, "_packing_job", None):
            self.after_cancel(self._packing_job)
        self._packing_job = self.after(40, self._packing_draw)

    def _packing_draw(self) -> None:
        self._packing_job = None
        self.redraw()

    def _packing_done(self, _e=None) -> None:
        if getattr(self, "_packing_job", None):
            self.after_cancel(self._packing_job)
            self._packing_job = None
        self._saved()
        self._show_packing()

    def _others_columns(self) -> None:
        """How many Other Members side by side (1: each generation's in a row)."""
        value = self._number(self.others_columns_var.get(), 1, ft.OTHERS_COLUMNS_MAX)
        if value is not None and int(value) != self.edits.others_columns:
            self._change(others_columns=int(value))

    def _group_members(self, group: str) -> list:
        return [p for p in self.village.people.values() if ft.group_of(p) == group]

    def _group_flip(self, group: str, flip: str) -> None:
        """Every portrait of a group flipped one way -- or, when every one already is, back (Ctrl+Z undoes)."""
        people = self._group_members(group)
        if not people:
            return
        on = not all(self._entry(p).get(flip, False) for p in people)
        for p in people:
            self._flip_as_seen(p, flip, on)
        self._saved()

    def _flip_as_seen(self, p, flip: str, on: bool) -> None:
        """A portrait flipped as it is seen on the page, its present turn taken as straight (the owner,
        2026-10-09: "treating the current rotation as straight horizontal"): the shape mirrored and its turn
        reversed -- a fish turned 30 degrees and flipped left-right is the same fish facing the other way,
        turned -30 degrees.  Nothing changes for one already flipped that way."""
        entry = self._entry(p)
        if bool(entry.get(flip, False)) == on:
            return
        angle = entry.get("angle", 0.0)
        self._set_entry(p, **{flip: on, "angle": round((-angle) % 360, 1) or None})

    def _group_turn(self, group: str) -> None:
        """Every portrait of a group turned to the angle in its box."""
        angle = self._number(self.group_turns[group].get(), -3600, 3600)
        people = self._group_members(group)
        if angle is None or not people:
            return
        angle = round(angle % 360, 1)
        for p in people:
            self._set_entry(p, angle=angle or None)
        self._saved()

    def _group_unturn(self, group: str) -> None:
        """Every portrait of a group unflipped and upright again."""
        people = self._group_members(group)
        if not people:
            return
        for p in people:
            self._set_entry(p, flip_h=None, flip_v=None, angle=None)
        self.group_turns[group].set("0")
        self._saved()

    def _own_turn(self) -> None:
        """Every selected family member's portrait turned to this many degrees (as the curved arrow turns it)."""
        angle = self._number(self.own_turn.get(), -3600, 3600)
        if not self.selected or angle is None:
            return
        angle %= 360
        changed = False
        for q in self.selected:
            p = self.village.people[q]
            if round(self._entry(p).get("angle", 0.0), 1) != round(angle, 1):
                self._set_entry(p, angle=round(angle, 1))
                changed = True
        if changed:
            self._saved()

    def _special_pick(self, part: str, colour: str) -> None:
        if colour:
            self._change(special_pick={**self.edits.special_pick, part: colour})

    def _special_palette(self, k: int, colour: str) -> None:
        if colour:
            palette = list(self.edits.special_palette)
            palette[k] = colour
            self._change(special_palette=palette)

    def _special_count(self) -> None:
        n = self._number(self.special_count_var.get(), 2, 7)
        if n is not None and int(n) != self.edits.special_count:
            self._change(special_count=int(n))

    # Short enough that all eight show whole in the side panel (the owner, 2026-10-09: the names were cut off).
    TAB_ORDER = ("Selected", "Family Member Info", "Shapes", "Faces & Text", "Fonts", "Layout", "Marks", "Background", "Pictures")

    def _order_tabs(self) -> None:
        """The tabs from the family members outwards: the selected ones, every portrait, the words, the tree, then
        the extras (the tools add Fonts and Pictures last)."""
        tabs = {self.notebook.tab(t, "text"): t for t in self.notebook.tabs()}
        for place, name in enumerate(n for n in self.TAB_ORDER if n in tabs):
            self.notebook.insert(place, tabs[name])
        self.notebook.select(0)

    LIST_WIDTH_MAX = 30                     # characters: a drop-down box no wider than this in the panel

    def _fit_lists(self, widget) -> None:
        """Every drop-down's choices readable whole (the owner, 2026-10-09: "I can't read the full labels"):
        the box as wide as its longest choice (up to LIST_WIDTH_MAX), and its opened list always as wide as
        the longest -- measured each time it opens, as some lists change."""
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                longest = max((len(str(v)) for v in child.cget("values") or ()), default=0)
                if longest + 1 > int(child.cget("width")):
                    child.configure(width=min(self.LIST_WIDTH_MAX, longest + 1))
                child.configure(postcommand=self._widen_popdown(child, child.cget("postcommand")))
            self._fit_lists(child)

    @staticmethod
    def _widen_popdown(combo: ttk.Combobox, before):
        """The opened list sized to its longest choice: ttk always opens it as wide as the box, plus the
        style's postoffset -- so each box gets a style of its own whose postoffset adds what is missing."""
        style = f"List{str(combo).replace('.', '_')}.TCombobox"

        def post() -> None:
            if before:
                combo.tk.eval(before) if isinstance(before, str) else before()
            try:
                font = tkfont.nametofont("TkDefaultFont")
                need = max((font.measure(str(v)) for v in combo.cget("values") or ()), default=0) + 30
                extra = max(0, need - combo.winfo_width())
                ttk.Style(combo).configure(style, postoffset=(0, 0, extra, 0))
                if combo.cget("style") != style:
                    combo.configure(style=style)
            except tk.TclError:
                pass
        return post

    def _scheme(self, part: str) -> None:
        """One part of the tree (ft.SCHEME_PARTS) as set, a rainbow, or alternating colours."""
        mode = next(k for k, v in ft.COLOUR_SCHEMES.items() if v == self.scheme_vars[part].get())
        schemes = {k: v for k, v in self.edits.schemes.items() if k != part}
        if mode != "own":
            schemes[part] = mode
        if schemes != self.edits.schemes:
            self._change(schemes=schemes)

    def _valign(self, valign: str) -> None:
        """The face and words at the top, middle or bottom of every portrait (Centre faces, before)."""
        self._change(text_valign=valign, centre_heads=valign == "middle")

    def _row_gap(self) -> None:
        """The pixels under each generation's row before the lines down to its children, for every row."""
        gap = self._number(self.row_gap_var.get(), ft.ROW_GAP_MIN, ft.ROW_GAP_MAX)
        if gap is not None and gap != self.edits.row_gap:
            self._change(row_gap=gap)

    def _page_generations(self) -> None:
        """The most generations on one page; a longer tree goes on over more pages (the owner: 6, up to 10)."""
        n = self._number(self.page_gens_var.get(), ft.PAGE_GENS_MIN, ft.PAGE_GENS_MAX)
        if n is not None and int(n) != self.edits.page_generations:
            self.page = 0
            self._change(page_generations=int(n))
            self._refresh_pages()

    def _fit_width(self) -> None:
        """Portraits (faces and words too) shrink alike so the widest row fits this page width; 0 is off."""
        try:
            width = int(float(self.portrait_fit_var.get()))
        except ValueError:
            return
        width = 0 if width <= 0 else max(ft.FIT_MIN, min(ft.FIT_MAX, width))
        if width != self.edits.fit_width:
            self._change(fit_width=width)

    def _group_all(self, group: str) -> None:
        """The group's shape and border on every one of its portraits: those given their own one by
        one go back to the group's (undo puts them back)."""
        changed = 0
        for p in self.village.people.values():
            if ft.group_of(p) != group:
                continue
            entry = self._entry(p)
            if "shape" in entry or "border" in entry:
                self._set_entry(p, shape="", border="")     # a copy: the undo steps keep the old one
                changed += 1
        if changed:
            self._saved()
        self.status.set(f"{ft.GROUPS[group]}: every portrait is now {ft.PORTRAIT_SHAPES[self.edits.shapes[group]]}, "
                            f"{ft.BORDERS[self.edits.borders[group]].lower()} ({changed} had their own).")

    def _live(self, spin: ttk.Spinbox, apply) -> ttk.Spinbox:
        """A size box that changes the tree as it is used (the owner: "should have a live preview"):
        at once for the arrows, Enter and leaving it; a moment after typing stops."""
        pending = {}
        waiting = self.__dict__.setdefault("live_waiting", {})     # every box with typing not yet applied

        def soon(_event=None) -> None:
            if pending.get("job"):
                self.after_cancel(pending["job"])
            pending["job"] = self.after(800, now)       # long enough to type "80" without "8" taking first
            waiting[id(now)] = now

        def now(_event=None) -> None:
            if pending.get("job"):
                self.after_cancel(pending["job"])
            pending["job"] = None
            waiting.pop(id(now), None)
            apply()

        spin.configure(command=now)
        spin.bind("<KeyRelease>", lambda e: None if e.keysym in ("Return", "Tab") else soon())
        spin.bind("<Return>", now)
        spin.bind("<FocusOut>", now)
        return spin

    @staticmethod
    def _number(text: str, low: float, high: float) -> float | None:
        try:
            value = float(text)
        except ValueError:
            return None
        return max(low, min(high, value))

    def _show_group_sizes(self) -> None:
        for group, (w_var, h_var) in self.group_sizes.items():
            w, h = self.edits.sizes.get(group) or ("", "")
            w_var.set(f"{w:g}" if w != "" else "")
            h_var.set(f"{h:g}" if h != "" else "")

    def _group_size(self, group: str, reset: bool = False, axis: int | None = None) -> None:
        """Every male's, female's or upcoming baby's frame this size, those resized on their own too.
        With Keep aspect ratio, the box changed (`axis`) sets that side and the other follows."""
        # The owner, 2026-10-09, of these boxes: "seems to do nothing even if changed" -- every villager in
        # the tree had been resized on their own, and their own size wins.  "Every portrait's size" means
        # every one: their own sizes go (Ctrl+Z brings them back).
        resized = [p for p in self.village.people.values()
                   if ft.group_of(p) == group and {"w", "h"} & set(self._entry(p))]
        if reset:
            if self.edits.sizes.pop(group, None) is not None or resized:
                for p in resized:
                    self._set_entry(p, w=None, h=None)
                self._saved()
            self._show_group_sizes()
            return
        w_var, h_var = self.group_sizes[group]
        p = next((p for p in self.village.people.values() if ft.group_of(p) == group), None)
        now = (ft.frame_size(self.edits, self.village, p, own=False, unscaled=True) if p is not None
               else tuple(self.edits.sizes.get(group) or (ft.NODE_W, ft.NODE_H)))
        if axis is not None and self.lock_shape.get():
            value = self._number((w_var if axis == 0 else h_var).get(), ft.FRAME_MIN, ft.FRAME_MAX)
            if value is None:
                return
            w, h = ft.keep_aspect(now, axis, value)
        else:
            natural = None
            if not w_var.get().strip() or not h_var.get().strip():      # one typed: the other as the shape has it
                natural = now
            w = self._number(w_var.get(), ft.FRAME_MIN, ft.FRAME_MAX) or (natural[0] if natural else None)
            h = self._number(h_var.get(), ft.FRAME_MIN, ft.FRAME_MAX) or (natural[1] if natural else None)
        # Only a real change of the group's size: leaving or pressing Enter in a box left as it was
        # wiped every own size and added an undo step.
        if (w is None or h is None or self.edits.sizes.get(group) == [w, h]
                or (round(w, 3), round(h, 3)) == (round(now[0], 3), round(now[1], 3))):
            return
        self.edits.sizes[group] = [w, h]
        for p in resized:
            self._set_entry(p, w=None, h=None)
        self._saved()
        self._show_group_sizes()

    def _own_text_size(self) -> None:
        """Every selected family member's words this size, in percent, whatever their frame's size."""
        percent = self._number(self.own_text.get(), ft.TEXT_SCALE_MIN, ft.TEXT_SCALE_MAX)
        if not self.selected or percent is None:
            return
        changed = False
        for q in self.selected:
            p = self.village.people[q]
            if self._entry(p).get("text_scale", 100.0) != percent:
                self._set_entry(p, text_scale=percent if percent != 100.0 else None)
                changed = True
        if changed:
            self._end_own_equal()
            self._saved()

    def _own_picture_size(self) -> None:
        """Every selected family member's face this size, in percent, whatever their frame's size."""
        percent = self._number(self.own_picture.get(), ft.PICTURE_SCALE_MIN, ft.PICTURE_SCALE_MAX)
        if not self.selected or percent is None:
            return
        changed = False
        for q in self.selected:
            p = self.village.people[q]
            if self._entry(p).get("picture_scale", 100.0) != percent:
                self._set_entry(p, picture_scale=percent if percent != 100.0 else None)
                changed = True
        if changed:
            self._end_own_equal()
            self._saved()

    def _own_size(self, axis: int | None = None) -> None:
        """Every selected family member's frame this size (the owner: "batch-changing portrait shape sizes").
        With Keep aspect ratio, the box changed (`axis`: 0 width, 1 height) sets that side and each
        frame's other side follows its own shape."""
        w = self._number(self.own_w.get(), ft.FRAME_MIN, ft.FRAME_MAX)
        h = self._number(self.own_h.get(), ft.FRAME_MIN, ft.FRAME_MAX)
        if not self.selected or w is None and h is None:
            return
        keep = axis is not None and bool(self.lock_shape.get())
        changed, others = False, set()
        for q in self.selected:                 # a width alone leaves each one's height as it is
            p = self.village.people[q]
            now = ft.frame_size(self.edits, self.village, p, unscaled=True)
            if keep and (w if axis == 0 else h) is not None:
                size = ft.keep_aspect(now, axis, w if axis == 0 else h)
            else:
                size = (w if w is not None else now[0], h if h is not None else now[1])
            others.add(size[1 - axis] if keep else None)
            if size != now:
                self._set_entry(p, w=size[0], h=size[1])
                changed = True
        if keep:                                # the other box shows the side that followed, when it is one
            other = self.own_h if axis == 0 else self.own_w
            other.set(f"{others.pop():g}" if len(others) == 1 else "")
        if changed:
            self._saved()

    def _label_line(self, attr: str, var: tk.StringVar, low: float, high: float) -> None:
        value = self._number(var.get(), low, high)
        if value is not None and value != getattr(self.edits, attr):
            self._change(**{attr: value})

    def _line_weight(self) -> None:
        width = self._number(self.line_w_var.get(), *ft.LINE_WIDTHS)
        if width is not None and width != self.edits.line_width:
            self._change(line_width=width)

    def _own_lines(self, reset: bool = False, part: str = "") -> None:
        """The selected family members' families' lines this weight ("width") or type ("dash") -- or like
        every other line (`reset`)."""
        keys = {self._family(self.village.people[q]) for q in self.selected} - {None}
        if not keys:
            self.status.set("Select family members with parents: their family's lines change.")
            return
        value = (self._number(self.own_line_w.get(), *ft.LINE_WIDTHS) if part == "width" else
                 next((k for k, v in ft.LINE_TYPES.items() if v == self.own_line_dash.get()), None))
        if not reset and value is None:
            return
        before = json.dumps(self.edits.family_lines, sort_keys=True)
        for key in keys:
            style = {} if reset else {**self.edits.family_lines.get(key, {}), part: value}
            if style:
                self.edits.family_lines[key] = style
            else:
                self.edits.family_lines.pop(key, None)
        if json.dumps(self.edits.family_lines, sort_keys=True) != before:
            self._saved()

    def _line_colour(self, key: str, colour: str) -> None:
        """One family's lines in their own colour ("": the family's colour again)."""
        style = {k: v for k, v in self.edits.family_lines.get(key, {}).items() if k != "colour"}
        if colour:
            style["colour"] = colour
        if style:
            self.edits.family_lines[key] = style
        else:
            self.edits.family_lines.pop(key, None)
        self._saved()

    def _auto_line_colours(self) -> None:
        """Auto-colour family lines: every family's lines a vivid colour clearly different from every
        other family's -- the most different where lines cross or run close -- that stands out at least 3:1
        against the background under them (vf1_line_colours).  One step to undo."""
        self._colour_lines("auto")

    def _colour_lines(self, mode: str, **settings) -> None:
        """The family lines in a mode (Auto, Rainbow, Gradient or Range; vf1_line_colours), with these
        settings first (the order, reverse, the gradient's ends or the range's colours).  One step to undo."""
        before = json.dumps([self.edits.family_lines, self.edits.line_mode, self.edits.to_data()], sort_keys=True)
        for name, value in settings.items():
            setattr(self.edits, name, value)
        self.status.set("Choosing the family lines' colours...")
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            pages = [self._page_scene(k) for k in range(max(1, self.lay.pages))]
            e = self.edits
            result = vf1_line_colours.mode_colours(pages, mode, e.line_order, e.line_reverse, e.gradient_start,
                                                  e.gradient_end, e.range_colours, outline=e.outline_lines)
        finally:
            self.configure(cursor="")
        if not result.colours:
            self.status.set("There are no family lines to colour.")
            return
        self.edits.line_mode = mode
        vf1_line_colours.apply(self.edits, result.colours)
        if json.dumps([self.edits.family_lines, self.edits.line_mode, self.edits.to_data()], sort_keys=True) != before:
            self._saved()
        words = f"{len(result.colours)} families' lines coloured" + (", each its own colour." if mode == "auto" else ".")
        if result.cased and self.edits.outline_lines:
            words += (f"  {len(result.cased)} would blend into the background in places, so they have a thin "
                      "outline.")
        elif result.cased:
            words += (f"  {len(result.cased)} blend into the background in places: tick \"Outline lines that "
                      "blend into the background\" to outline them.")
        self.status.set(words + "  Ctrl+Z undoes it.")

    def _line_mode_picked(self) -> None:
        """"Line colours:" changed: Default puts the families' colours back; the others colour the lines."""
        mode = next(k for k, v in ft.LINE_MODES.items() if v == self.line_mode_var.get())
        if mode == "default":
            self._reset_line_colours()
        else:
            self._colour_lines(mode)
        self._show_line_options()

    def _line_option(self, **settings) -> None:
        """An order, reverse, gradient or range setting changed: a mode already colouring the lines is drawn again
        (one step to undo); otherwise only the setting is kept."""
        if self.edits.line_mode in ("rainbow", "gradient", "range"):
            self._colour_lines(self.edits.line_mode, **settings)
        else:
            self._change(**settings)
        self._show_line_options()

    def _gradient_end(self, which: str) -> None:
        name = "gradient_" + which
        colour = ask_colour(self, "Gradient " + ("start" if which == "start" else "end") + " colour",
                            getattr(self.edits, name))
        if colour and colour != getattr(self.edits, name):
            self._line_option(**{name: colour})

    def _range_add(self) -> None:
        colour = ask_colour(self, "Add a base colour", "")
        if colour and colour not in self.edits.range_colours and len(self.edits.range_colours) < ft.RANGE_MAX:
            self._line_option(range_colours=self.edits.range_colours + [colour])

    def _range_toggle(self, colour: str) -> None:
        now = list(self.edits.range_colours)
        if colour in now:
            if len(now) > 1:                     # at least one base colour stays
                now.remove(colour)
        elif len(now) < ft.RANGE_MAX:
            now.append(colour)
        if now != self.edits.range_colours:
            self._line_option(range_colours=now)

    def _show_line_options(self) -> None:
        """Only the settings of the mode picked: the order (Rainbow, Gradient, Range), the gradient's ends,
        the range's base colours."""
        e = self.edits
        for frame in (self.line_order_row, self.gradient_row, self.range_row):
            frame.pack_forget()
        if e.line_mode in ("rainbow", "gradient", "range"):
            self.line_order_row.pack(anchor="w")
        if e.line_mode == "gradient":
            self.gradient_row.pack(anchor="w", pady=(4, 0))
            self.gradient_start_btn.configure(bg=e.gradient_start, activebackground=e.gradient_start)
            self.gradient_end_btn.configure(bg=e.gradient_end, activebackground=e.gradient_end)
        if e.line_mode == "range":
            self.range_row.pack(anchor="w", pady=(4, 0))
            for child in self.range_swatches.winfo_children():
                child.destroy()
            shown = list(RANGE_PRESETS) + [c for c in e.range_colours if c not in RANGE_PRESETS]
            for k, colour in enumerate(shown):
                on = colour in e.range_colours
                tk.Button(self.range_swatches, width=2, bg=colour, activebackground=colour, text="x" if on else "",
                          fg="white", relief="sunken" if on else "raised",
                          command=lambda c=colour: self._range_toggle(c)).grid(row=k // 8, column=k % 8, padx=1, pady=1)

    def _reset_line_colours(self) -> None:
        """Every family's lines back in their family's colour.  One step to undo."""
        if vf1_line_colours.reset(self.edits):
            self._saved()
            self._refresh_panels()
            self.line_mode_var.set(ft.LINE_MODES["default"])
            self._show_line_options()
            self.status.set("The family lines are in their families' colours again.")
        else:
            self.status.set("The family lines are already in their families' colours.")

    def _set_opacity(self, part: str, percent: int) -> None:
        if self.edits.opacity.get(part, ft.OPACITY[part][1]) != percent:
            self.edits.opacity[part] = percent
            self._saved()

    def _glow_size(self) -> None:
        reach = self._number(self.glow_var.get(), 2.0, 60.0)
        if reach is not None and reach != self.edits.mark_glow:
            self._change(mark_glow=reach)

    def _renumber(self) -> None:
        """The number starting each family member's own text made their number on the tree now (the
        patcher's own text is numbered as the tree changes)."""
        changed = 0
        for p in self.village.known():
            lines = ft.node_text(self.lay, p) if self._entry(p).get("lines") else None   # as shown
            match = re.match(r"\s*\d+\.\s*", lines[0]) if lines else None
            if match is None or p.number is None:
                continue
            first = f"{p.number}. {lines[0][match.end():]}"
            if first != lines[0]:
                runs = ft.carry_styles(lines, ft.node_runs(self.lay, p), [first] + lines[1:])
                self._set_entry(p, lines=[first] + lines[1:], runs=runs)
                changed += 1
        if changed:
            self._saved()
        self.status.set(f"{changed} family member(s) renumbered." if changed else
                        "Every number in your own text already matches the tree.")

    def _number_names(self) -> None:
        """Number Duplicate Names on the tree ("Happi I", "Happi II"): only the tree's names -- the save is
        never changed."""
        if not gen.duplicate_names(self.village, self.edits.number_order):
            self.status.set("No two family members share a name.")
            return
        if not self.edits.number_names:
            self._change(number_names=True)
        self.status.set(f"Duplicate names are numbered on the tree, "
                        f"{gen.NUMBER_ORDERS[self.edits.number_order].lower()}.  The save is not changed.")

    def _reset_frames(self) -> None:
        """The selected family members' portraits back to their shape's own size, not turned."""
        if not self.selected:
            return
        for q in self.selected:
            self._set_entry(self.village.people[q], w=None, h=None, angle=None)
        self._saved()

    def _own_style(self, attr: str, value: str) -> None:
        """The selected family members' own portrait shape or border ("" = like the rest of their group)."""
        if not self.selected:
            return
        for p in (self.village.people[q] for q in self.selected):
            self._set_entry(p, **{attr: value})
        self._saved()

    # ---- what belongs to the page shown alone (ft.Edits.page_edits) ------------------------------
    def _pkey(self) -> str:
        """The shown page's name in the edits (its first generation)."""
        return str(ft.page_key(self.edits, self.village, self.page))

    def _ov(self) -> dict:
        """The shown page's own edits, made if it has none yet."""
        return self.edits.page_edits.setdefault(self._pkey(), {})

    def _entry(self, p: gen.Person) -> dict:
        """A family member's edits as the shown page has them: the tree's, with this page's laid over."""
        return self._entry_by_key(ft.entry_key(self.village, p))

    def _entry_by_key(self, key: str) -> dict:
        base = self.edits.entries.get(key, {})
        over =self.edits.page_edits.get(self._pkey(), {}).get("entries", {}).get(key)
        if not over:
            return base
        merged = dict(base)
        for name, value in over.items():
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        return merged

    def _moved_now(self) -> dict:
        return {**self.edits.moved, **{n: s for n, s in self.edits.page_edits.get(self._pkey(), {}).get("moved", {}).items()
                                       if s is not None}} if self.edits.page_edits.get(self._pkey()) else self.edits.moved

    def _move_to(self, name: str, shift: list | None) -> None:
        """Words or a group moved on the shown page alone (None: back where the tree puts them)."""
        moved = self._ov().setdefault("moved", {})
        if shift is not None:
            moved[name] = shift
        elif name in self.edits.moved:
            moved[name] = None          # the tree's own move stays on the other pages
        else:
            moved.pop(name, None)

    def _hidden_now(self) -> list:
        """What is deleted on the shown page."""
        part = self.edits.page_edits.get(self._pkey(), {})
        return part["hidden"] if "hidden" in part else self.edits.hidden

    def _set_hidden(self, hidden: list) -> None:
        self._ov()["hidden"] = list(hidden)

    def _generations_now(self) -> dict:
        """The generation labels the player wrote, as the shown page has them."""
        return ft.page_view(self.edits, self.village, self.page).generations

    def _set_generation_label(self, g: int, lines: list | None) -> None:
        """A generation label's lines on the shown page alone (None: the patcher's own words here)."""
        over = self._ov().setdefault("generations", {})
        if lines is not None:
            over[str(g)] = list(lines)
        elif str(g) in self.edits.generations:
            over[str(g)] = None         # the tree's own label stays on the other pages
        else:
            over.pop(str(g), None)
        if not over:
            self._ov().pop("generations", None)

    def _line_moves_now(self) -> dict:
        """The family lines dragged on the shown page (the tree's own, with this page's laid over)."""
        return ft.page_view(self.edits, self.village, self.page).line_moves

    def _set_line_move(self, piece: str, shift, free: bool = False) -> None:
        """A line dragged on the shown page alone (shift None: back where the tree puts it; free: put down
        with Alt, exactly there)."""
        moves = self._ov().setdefault("line_moves", {})
        if shift and self.edits.line_moves.get(piece) != shift:
            moves[piece] = shift
        elif shift:                         # the tree's own drag: nothing of this page's
            moves.pop(piece, None)
        elif piece in self.edits.line_moves:
            moves[piece] = None             # the tree's own drag stays on the other pages
        else:
            moves.pop(piece, None)
        part = self._ov()
        if not moves:
            part.pop("line_moves", None)
        kept = [p for p in ft.page_view(self.edits, self.village, self.page).free_lines if p != piece]
        if free and shift:
            kept.append(piece)
        if kept != self.edits.free_lines or "free_lines" in part:
            part["free_lines"] = kept
        if part.get("free_lines") == self.edits.free_lines:
            part.pop("free_lines", None)

    def _clear_line_moves(self) -> None:
        """Every line put back where the tree draws it, on the shown page alone."""
        part = self._ov()
        if self.edits.line_moves:
            part["line_moves"] = {p: None for p in self.edits.line_moves}
        else:
            part.pop("line_moves", None)
        if self.edits.free_lines:
            part["free_lines"] = []
        else:
            part.pop("free_lines", None)

    def _colours_now(self, name: str) -> dict:
        """family_colours or person_colours as the shown page has them."""
        return getattr(ft.page_view(self.edits, self.village, self.page), name)

    def _set_colour(self, name: str, key: str, colour: str) -> None:
        """A family's or family member's own colour on the shown page alone ("": the patcher's)."""
        over = self._ov().setdefault(name, {})
        if colour:
            over[key] = colour
        elif key in getattr(self.edits, name):
            over[key] = None
        else:
            over.pop(key, None)

    def _family(self, p: gen.Person) -> str | None:
        if p.father is None and p.mother is None:
            return None
        fam = ft.Family(0, p.father, p.mother, [])
        return ft.family_key(self.village, fam)

    def _set_entry(self, p: gen.Person, **values) -> None:
        self._set_entry_key(ft.entry_key(self.village, p), self._entry(p), **values)

    def _set_entry_key(self, key: str, current: dict, **values) -> None:
        """Changes to one family member's edits, kept for the shown page alone: what differs from the tree's own
        (None: not set on this page).  Their generation and chosen look too."""
        entry = dict(current)
        for name, value in values.items():
            if value:
                entry[name] = value
            else:
                entry.pop(name, None)
        base = dict(self.edits.entries.get(key, {}))
        over = {n: v for n, v in entry.items() if base.get(n) != v}
        over.update({n: None for n in base if n not in entry})
        part = self.edits.page_edits.setdefault(self._pkey(), {})
        entries = part.setdefault("entries", {})
        if over:
            entries[key] = over
        else:
            entries.pop(key, None)

    def _saved(self) -> None:
        """Every change: a step to undo, the tree drawn again, and a change to save."""
        self.edits.page_edits = ft.clean_page_edits(self.edits.page_edits)    # a page that keeps nothing is dropped
        self._record()
        self.dirty = True
        self.redraw()
        self._refresh_selected()
        self._refresh_obj_panel()

    def _refresh_panels(self) -> None:
        """Every control showing the edits as they now are (after undo or redo); the portraits' own
        settings as the group picked in "Settings for:" has them."""
        e = self._view()
        self._show_scope_note()
        self.title_var.set(e.title)
        self.subtitle_var.set(e.subtitle)
        self.sort_var.set(gen.SORTS[e.sort])
        self.position_var.set(ft.POSITIONING[e.positioning])
        self.row_align_var.set(ft.ROW_ALIGNS[e.row_align])
        self.row_valign_var.set(ft.ROW_VALIGNS[e.row_valign])
        self.row_limit_var.set(str(e.row_limit))
        self.keep_families_var.set(e.keep_families)
        self.others_columns_var.set(str(e.others_columns))
        self.others_side_var.set(ft.OTHERS_SIDES[e.others_side])
        self.packing_scale.set(e.packing)
        self._show_packing()
        self.lines_behind_var.set(ft.behind(e))
        self.outline_var.set(e.outline_lines)
        self.line_mode_var.set(ft.LINE_MODES[e.line_mode])
        self.line_order_var.set(ft.LINE_ORDERS[e.line_order])
        self.line_reverse_var.set(e.line_reverse)
        self._show_line_options()
        self.numbering_var.set(ft.NUMBERINGS[e.numbering])
        for part, scale in self.opacity_vars.items():
            scale.set(e.opacity.get(part, ft.OPACITY[part][1]))
        self._show_group_sizes()
        self.line_w_var.set(f"{e.line_width:g}")
        self.line_dash_var.set(ft.LINE_TYPES[e.line_dash])
        self.label_w_var.set(f"{e.label_line_width:g}")
        self.label_reach_var.set(f"{e.label_line_reach:g}")
        self.mark_style_var.set(ft.MARK_STYLES[e.mark_style])
        self.glow_var.set(f"{e.mark_glow:g}")
        self.mark_opacity_scale.set(e.mark_opacity)
        self.align_var.set(ft.TEXT_ALIGNS[e.text_align])
        self.inside_var.set(e.text_inside)
        self.fixed_face_var.set(e.fixed_face_size)
        self.turn_words_var.set(e.turn_words)
        self.flip_words_var.set(e.flip_words)
        self.room_var.set(ft.TEXT_ROOMS[e.text_room])
        self.special_mode_var.set(ft.SPECIAL_COLOUR_MODES[e.special_mode])
        self.hibiscus_var.set(ft.HIBISCUS_CHOICES[e.hibiscus])
        for part, fieldw in self.special_pick_fields.items():
            fieldw.set_quietly(e.special_pick.get(part, ft.NATURAL[part]))
        for k, fieldw in enumerate(self.special_palette_fields):
            fieldw.set_quietly(e.special_palette[k])
        self.special_count_var.set(str(e.special_count))
        self.special_opacity_var.set(f"{e.special_opacity:g}")
        self.rainbow_var.set(ft.RAINBOW_STRENGTHS[e.rainbow_strength][0])
        for part, var in self.scheme_vars.items():
            var.set(ft.COLOUR_SCHEMES[e.schemes.get(part, "own")])
        self.picture_size_var.set(f"{e.picture_size:g}")
        self.text_size_var.set(f"{e.text_size:g}")
        self.detail_var.set(e.detail_lines)
        self.detail_field.set_quietly(e.detail_colour)
        self.detail_opacity_var.set(f"{e.detail_opacity:g}")
        self.detail_width_var.set(f"{e.detail_width:g}")
        self.text_box_field.set_quietly(e.text_box_colour)
        self.text_box_opacity_var.set(f"{e.text_box_opacity:g}")
        self.text_box_over_var.set(e.text_box_over)
        self.text_box_border_var.set(ft.BORDERS[e.text_box_border])
        self.text_box_border_width_var.set(f"{e.text_box_border_width:g}")
        self.text_box_border_field.set_quietly(e.text_box_border_colour)
        self.valign_var.set(ft.TEXT_VALIGNS[e.text_valign])
        self.wrap_var.set(str(e.text_wrap))
        self.gap_var.set(f"{e.portrait_gap:g}")
        self.row_gap_var.set(f"{e.row_gap:g}")
        self.portrait_fit_var.set(str(e.fit_width))
        self._show_canvas()
        self.page_gens_var.set(str(e.page_generations))
        self.units_var.set(e.show_units)
        self.years_var.set(e.show_years)
        for attr, var in self.descriptor_vars.items():
            var.set(getattr(e, attr))
        self._refresh_status_checks()
        self.number_names_var.set(e.number_names)
        self.number_order_var.set(gen.NUMBER_ORDERS[e.number_order])
        self.diagonal_var.set(e.diagonal_lines)
        self.ink_field.set_quietly(e.ink)
        self.fill_field.set_quietly(e.portrait_fill)
        for (attr, group), var in self.group_vars.items():
            var.set((ft.PORTRAIT_SHAPES if attr == "shapes" else ft.BORDERS)[getattr(e, attr)[group]])
        self.plate_field.set_quietly(e.plate_colour)
        self._refresh_hidden()
        self.bg_field.set_quietly(e.background)
        self.bg2_field.set_quietly(e.background2)
        self.fit_var.set(ft.FITS[e.background_fit])
        self.opacity_scale.set(e.background_opacity)
        self.all_font.set(e.font or "(the patcher's own)")
        self._refresh_marks()
        self._refresh_selected()
        self._refresh_obj_panel()
        self._show_role()
        self._show_generation()

    def _change(self, everyone: bool = False, **values) -> None:
        """Settings changed, one step to undo.  With a group picked in "Settings for:" (and not
        `everyone`), settings a group may have of its own (ft.GROUP_FIELDS) are that group's: a value
        the same as everyone's is no setting of its own."""
        group = None if everyone else self._scope()
        if {"picture_size", "text_size"} & set(values):    # a face or text size changed: no longer kept the same
            self._end_equal(group if group and all(name in ft.GROUP_FIELDS for name in values) else None)
        if group and values and all(name in ft.GROUP_FIELDS for name in values):
            own = dict(self.edits.group_opts.get(group, {}))
            for name, value in values.items():
                if value == getattr(self.edits, name):
                    own.pop(name, None)
                else:
                    own[name] = value
            if "text_valign" in own:
                own["centre_heads"] = own["text_valign"] == "middle"
            else:
                own.pop("centre_heads", None)
            groups = {g: v for g, v in self.edits.group_opts.items() if g != group}
            if own:
                groups[group] = own
            self.edits.group_opts = groups
        else:
            for name, value in values.items():
                setattr(self.edits, name, value)
        self._saved()
        self._show_scope_note()

    def _apply_text(self) -> None:
        if len(self.selected) != 1:
            return
        p = self.village.people[self.selected[0]]
        lines, runs = self._box_text()
        default = ft.default_text(self.lay, p)
        # Formatted words are the player's own even when they are the patcher's (they are kept) -- unless
        # formatted just as the tree formats its own lines by default (ft.default_runs).
        plain = lines == default and runs in (None, ft.runs_data(ft.default_runs(self.lay, p)))
        self._set_entry(p, lines=None if plain else lines, runs=runs)
        self._saved()

    def _bold_italic_extra_lines(self, ask: bool = True) -> int:
        """Every portrait's extra lines (ft.is_aux_line) bold and italic -- the player's own formatted
        lines too, their other formatting kept -- for everyone, or the group picked in "Settings for:".
        One step to undo.  The tree's own lines already are, by default (ft.default_runs).  How many
        portraits changed."""
        if ask and not messagebox.askyesno(
                "Family Tree Maker", "Make the extra lines bold and italic in every portrait?  Your other "
                "text formatting is kept.", parent=self):
            return 0
        group = self._scope()
        changed = 0
        for p in self.village.people.values():
            if group is not None and ft.group_of(p) != group:
                continue
            entry = self._entry(p)
            lines = entry.get("lines")
            if not lines:
                continue
            runs = ft.bold_italic_aux(lines, entry.get("runs"))
            if runs != entry.get("runs"):
                self._set_entry(p, runs=runs)
                changed += 1
        if changed:
            self._saved()
        self.status.set(f"Extra lines made bold and italic in {changed} portrait(s)." if changed else
                        "Every extra line is already bold and italic.")
        return changed

    def _add_status_labels(self, ask: bool = True) -> int:
        """Each family member's status from the saved records -- "(deceased)", "(disappeared)", "(left the family)",
        "Heathen" -- added as a last line to every portrait whose words (typed, or the patcher's own) do not
        already say it -- see ft.status_for_portrait.  For everyone, or the group picked in "Settings for:".  Only the tree's
        displayed text changes -- never a record.  One step to undo.  How many portraits changed."""
        if ask and not messagebox.askyesno(
                "Family Tree Maker", "Add each family member's status (deceased, no longer in the house) "
                "to the words on their portrait?  Only the tree's words change, never the family members' records.",
                parent=self):
            return 0
        group = self._scope()
        changed = 0
        for p in self.village.people.values():
            if group is not None and ft.group_of(p) != group:
                continue
            done = ft.status_for_portrait(self.lay, p)
            if done is not None:
                self._set_entry(p, lines=done[0], runs=done[1])
                changed += 1
        if changed:
            self._saved()
        self.status.set(f"Status labels added to {changed} portrait(s).  Ctrl+Z undoes it." if changed else
                        "Every portrait already says its family member's status.")
        return changed

    def _restore_text(self) -> None:
        for q in self.selected:
            self._set_entry(self.village.people[q], lines=None, runs=None)
        self._saved()

    # ---- the Portrait text box's formatting ---------------------------------
    def _box_styles(self) -> list[tuple[str, dict]]:
        """Every letter in the Portrait text box with its own style (its fx: tags)."""
        box = self.lines_text
        text = box.get("1.0", "end-1c")
        out = []
        for k, ch in enumerate(text):
            style: dict = {}
            for tag in box.tag_names(f"1.0+{k}c"):
                if tag.startswith(FX):
                    name, _, value = tag[len(FX):].partition(":")
                    style[name] = value == "1" if name in ft.RUN_FLAGS else value
            out.append((ch, ft.clean_run_style(style)))
        return out

    def _box_text(self) -> tuple[list[str], list | None]:
        """The box's lines (each without the spaces at its end, as ever) and their runs in the edits
        file's form (None when nothing is formatted)."""
        letters = self._box_styles()
        while letters and letters[-1][0] == "\n":
            letters.pop()
        lines: list[list] = [[]]
        for ch, style in letters:
            if ch == "\n":
                lines.append([])
            else:
                lines[-1].append((ch, style))
        for line in lines:
            while line and line[-1][0].isspace():
                line.pop()
        runs = [ft.merge_runs(line) for line in lines]
        texts = ["".join(ch for ch, _s in line) for line in lines]
        return texts, ft.runs_data(ft.clean_runs(ft.runs_data(runs), texts))

    def _box_load(self, lines: list[str], runs) -> None:
        """The box showing these lines, formatted as `runs` (node_runs) say."""
        box = self.lines_text
        box.delete("1.0", "end")
        for k, line in enumerate(lines):
            if k:
                box.insert("end", "\n")
            for text, style in (runs[k] if runs else [(line, {})]):
                box.insert("end", text, self._fx_tags(style))
        self._show_looks()
        box.edit_reset()

    @staticmethod
    def _fx_tags(style: dict) -> tuple:
        return tuple(f"{FX}{name}:{int(value) if isinstance(value, bool) else value}" for name, value in style.items())

    def _show_looks(self) -> None:
        """The box's words drawn as they will look on the tree: each letter's own style over its
        line's (the first line is the name's).  A Text's tags cannot mix fonts, so each look that
        is wanted is a tag of its own."""
        box = self.lines_text
        for tag in box.tag_names():
            if tag.startswith(LOOK):
                box.tag_remove(tag, "1.0", "end")
        family = box.tk.call("font", "actual", box.cget("font"), "-family")
        size = int(box.tk.call("font", "actual", box.cget("font"), "-size")) or 10     # below 0: pixels
        line, start, last = 0, 0, None
        letters = self._box_styles() + [("\n", {})]
        for k, (ch, style) in enumerate(letters):
            look = None if ch == "\n" else ft.run_effect(style, ft.line_base(self.edits, line == 0))
            key = None if look is None else tuple(sorted(look.items()))
            if key != last:
                if last is not None:
                    box.tag_add(self._look_tag(dict(last), family, size), f"1.0+{start}c", f"1.0+{k}c")
                start, last = k, key
            if ch == "\n":
                line += 1

    def _look_tag(self, look: dict, family: str, size: int) -> str:
        name = LOOK + "|".join(f"{k}={v}" for k, v in sorted(look.items()))
        small = look["script"] in ft.SCRIPTS
        font = (family, round(size * 0.7) if small else size, "bold" if look["bold"] else "normal",
                *(["italic"] if look["italic"] else []), *(["underline"] if look["underline"] else []),
                *(["overstrike"] if look["strike"] else []))
        self.lines_text.tag_configure(name, font=font, foreground=look["colour"] or "",
                                      offset={"super": round(abs(size) * 0.35), "sub": -round(abs(size) * 0.25)}.get(
                                          look["script"], 0))
        return name

    def _format_text(self, what: str) -> str:
        """The selected words in the Portrait text box formatted (the owner: "select words, then
        format"); Save text puts them on the tree."""
        box = self.lines_text
        if str(box.cget("state")) == "disabled":
            self.status.set("Click one family member to format their portrait's words.")
            return "break"
        try:
            first, last = box.index("sel.first"), box.index("sel.last")
        except tk.TclError:
            self.status.set("Select some words in the Portrait text box first, then format them.")
            return "break"
        colour = ""
        if what == "colour":
            chosen = ask_colour(self, "The colour of the selected words")
            if chosen is None:
                return "break"
            colour = chosen
        start = len(box.get("1.0", first))
        end = start + len(box.get(first, last))
        letters = self._box_styles()
        picked = [k for k in range(start, end) if letters[k][0] != "\n"]
        if not picked:
            return "break"
        line_of = [0]
        for ch, _s in letters:
            line_of.append(line_of[-1] + (ch == "\n"))
        bases = [ft.line_base(self.edits, line_of[k] == 0) for k in picked]
        new = ft.format_styles([letters[k][1] for k in picked], bases, what, colour)
        box.edit_separator()
        for k, style in zip(picked, new):
            at, after = f"1.0+{k}c", f"1.0+{k + 1}c"
            for tag in box.tag_names(at):
                if tag.startswith(FX):
                    box.tag_remove(tag, at, after)
            for tag in self._fx_tags(style):
                box.tag_add(tag, at, after)
        self._show_looks()
        box.tag_add("sel", first, last)
        self.status.set(f"{FORMAT_NAMES[what].rstrip('.')}: done.  Save text puts it on the tree.")
        return "break"

    def _format_menu(self, event) -> str:
        """A right click on the Portrait text box: format the selected words."""
        menu = tk.Menu(self, tearoff=False)
        for what, _label, _look in TEXT_FORMATS:
            if what == "plain":
                menu.add_separator()
            menu.add_command(label=FORMAT_NAMES[what], command=lambda w=what: self._format_text(w))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _type_formatted(self, event) -> str | None:
        """A letter typed into the box takes the look of the one before it (as in a word processor:
        typing on after bold words is bold)."""
        box = self.lines_text
        if len(event.char) != 1 or not event.char.isprintable() or event.state & 0x4 or event.state & ALT:
            return None
        if box.tag_ranges("sel"):
            box.delete("sel.first", "sel.last")
        before = box.index("insert -1c") if box.compare("insert", ">", "1.0") and \
            box.get("insert -1c") != "\n" else None
        tags = tuple(t for t in box.tag_names(before) if t.startswith(FX)) if before else ()
        box.insert("insert", event.char, tags)
        box.see("insert")
        self._show_looks()
        return "break"

    def _apply_mark(self, clear: bool = False) -> None:
        """Give mark: the mark picked, beside any they have.  Remove mark: the mark picked, or every
        mark when none is picked.  An automatic mark taken off stays off (_take_mark)."""
        label = "" if self.mark_var.get() in ("", "(none)") else self.mark_var.get()
        if not clear and not label:
            return
        for q in self.selected:
            p = self.village.people[q]
            if not clear:
                self._give_mark(p, label)
            for gone in ([label] if label else ft.entry_marks(self._entry(p))) if clear else []:
                self._take_mark(p, gone)
        self._saved()

    def _set_marks(self, p: gen.Person, marks: list[str], unmarked: list[str]) -> None:
        self._set_entry(p, marks=list(marks) or None, mark=marks[0] if marks else None,
                        unmarked=list(unmarked) or None)

    def _give_mark(self, p: gen.Person, label: str) -> None:
        entry = self._entry(p)
        have = ft.entry_marks(entry)
        self._set_marks(p, have + ([label] if label not in have else []),
                        [u for u in entry.get("unmarked") or [] if u != label])

    def _take_mark(self, p: gen.Person, label: str) -> None:
        """A mark off a family member.  One the tree gives by itself (their status) is kept as taken off --
        in the tree's own edits, never the save -- so it is not given back the next time the tree opens."""
        entry = self._entry(p)
        unmarked = list(entry.get("unmarked") or [])
        if label in ft.auto_labels(self.edits, p) and label not in unmarked:
            unmarked.append(label)
        self._set_marks(p, [m for m in ft.entry_marks(entry) if m != label], unmarked)

    def _refresh_mark_checks(self, people: list) -> None:
        """A tick box for each mark the selected family member has, or that the tree gives them by itself."""
        for child in self.mark_checks.winfo_children():
            child.destroy()
        self.mark_check_vars = {}
        if len(people) != 1:
            return
        p = people[0]
        have = ft.entry_marks(self._entry(p))
        auto = ft.auto_labels(self.edits, p)
        for label in have + [a for a in auto if a not in have]:
            var = tk.BooleanVar(value=label in have)
            self.mark_check_vars[label] = var
            ttk.Checkbutton(self.mark_checks, variable=var,
                            text=label + ("  (special family member status)" if label in auto else ""),
                            command=lambda label=label, var=var: self._tick_mark(label, var.get())
                            ).pack(anchor="w")

    def _tick_mark(self, label: str, on: bool) -> None:
        for q in self.selected[:1]:
            p = self.village.people[q]
            if on:
                self.edits.marks.setdefault(label, PRESET_MARKS.get(label) or ft.status_colour(label))
                self._give_mark(p, label)
            else:
                self._take_mark(p, label)
        self._saved()

    def _refresh_status_checks(self) -> None:
        """A tick box for each special family member status this game (and this family) has: ticked, its words
        and its mark show on everyone who has it; unticked, on nobody (ft.set_status_option)."""
        if not hasattr(self, "status_checks"):
            return
        options = ft.status_options(self.edits, getattr(self, "full_village", self.village))
        if [label for label, _on in options] == list(self.status_check_vars):
            for label, on in options:
                self.status_check_vars[label].set(on)
            return
        for child in self.status_checks.winfo_children():
            child.destroy()
        self.status_check_vars = {}
        for label, on in options:
            var = self.status_check_vars[label] = tk.BooleanVar(value=on)
            ttk.Checkbutton(self.status_checks, text=label, variable=var,
                            command=lambda label=label, var=var: self._tick_status(label, var.get())).pack(anchor="w")

    def _tick_status(self, label: str, on: bool) -> None:
        if on:
            status = next((s for p in self.full_village.people.values() for s in p.statuses
                           if ft.auto_label(self.edits, s) == label), label)
            self.edits.marks.setdefault(label, PRESET_MARKS.get(label) or ft.status_colour(status))
        ft.set_status_option(self.edits, self.full_village, label, on)
        self._refresh_marks()
        self._saved()

    def _auto_marks(self) -> None:
        """Every family member's special statuses marked on the tree by itself (ft.apply_auto_marks): on opening,
        on Update from the save and logs, and on a saved tree opened -- the player's own marks kept."""
        if ft.apply_auto_marks(self.edits, getattr(self, "full_village", self.village)) and hasattr(self, "history"):
            self.last_state = self._state()     # given by the tree, not a step of the player's to undo

    def _set_generation(self, back: bool = False) -> None:
        """The selected family members into the generation chosen (or back to the records')."""
        if not self.selected:
            return
        try:
            g = None if back else int(self.gen_choice.get())
        except ValueError:
            self.bell()
            return
        if g is not None and not 1 <= g <= 99:
            self.bell()
            return
        for q in self.selected:
            p = self.village.people[q]
            if p.upcoming:
                continue
            same = g == self.village.base_generation.get(q)
            self._set_entry(p, generation=None if back or same else g)
        self._saved()

    def _row_keys(self, g: int) -> list[str]:
        """Generation g's family members, left to right as the tree numbers them."""
        shown = self.lay.village                # the generations as the shown page has them
        row = sorted((p for p in shown.known() if p.generation == g), key=lambda p: p.number or 0)
        return [ft.entry_key(self.village, p) for p in row]

    def _shift_place(self, step: int) -> None:
        """The selected family members one place left or right in their generation."""
        chosen = [self.lay.village.people[q] for q in self.selected if not self.village.people[q].upcoming]
        if not chosen:
            return
        for g in sorted({p.generation for p in chosen}):
            keys = self._row_keys(g)
            moving = [ft.entry_key(self.village, p) for p in chosen if p.generation == g]
            for key in (moving if step < 0 else reversed(moving)):
                i = keys.index(key)
                j = i + step
                if 0 <= j < len(keys) and keys[j] not in moving:
                    keys[i], keys[j] = keys[j], keys[i]
            self.edits.orders[str(g)] = keys
        self._saved()

    def _reset_order(self) -> None:
        for g in {str(self.lay.village.people[q].generation) for q in self.selected} or set(self.edits.orders):
            self.edits.orders.pop(g, None)
        self._saved()

    def _own_colour(self, colour: str, pids: list | None = None) -> None:
        """The selected family members' own colour: a parentless family member's alone, else their set of full
        brothers and sisters' (blank: the patcher's)."""
        for q in self.selected if pids is None else pids:
            p = self.village.people[q]
            fam = self._family(p)
            name, key = (("family_colours", fam) if fam is not None
                         else ("person_colours", ft.entry_key(self.village, p)))
            self._set_colour(name, key, colour)
        self._saved()

    def _add_here(self, what: str, at: tuple) -> None:
        """Something new where the player right-clicked."""
        x, y = at
        if what == "text":
            self._place_new(ft.new_text_box(x, y, font=self.edits.font))
            self._edit_text()
        elif what in ("rect", "ellipse"):
            self._place_new(ft.new_shape(what, x, y))
        elif what == "picture":
            chosen = filedialog.askopenfilename(parent=self, title="A picture to put on the tree",
                                                filetypes=[("Pictures", "*.png *.jpg *.jpeg *.bmp *.gif"),
                                                           ("All files", "*.*")])
            if chosen:
                self._place_new(ft.new_sticker(chosen, Path(chosen), x, y))
        else:                                   # a logo
            path = ft.picture_path(what, self.images, self.library)
            if path is not None:
                self._place_new(ft.new_sticker(what, path, x, y))

    def _show_key(self) -> None:
        """The marks' Key shown or deleted (a new list: the undo steps keep the old one)."""
        hidden = [h for h in self._hidden_now() if h != "word:key"]
        if not self.key_var.get():
            hidden.append("word:key")
        self._set_hidden(hidden)
        self._saved()
        self._refresh_hidden()

    def _hide(self, what: str) -> None:
        """A line piece or words deleted from the tree (brought back from the Layout tab)."""
        if what not in self._hidden_now():
            self._set_hidden(list(self._hidden_now()) + [what])
        self._saved()
        self._refresh_hidden()
        self.status.set("Deleted.  Ctrl+Z, or Deleted items on the Layout tab, brings it back.")

    def _drop_label_line(self, g: int, k: int) -> None:
        """One line of a generation label the player wrote, deleted (the last one: the whole label)."""
        lines = list(self._generations_now().get(str(g), []))
        if not 0 <= k < len(lines):
            return
        del lines[k]
        if lines:
            self._set_generation_label(g, lines)
            self._saved()
        else:
            self._set_generation_label(g, None)
            self._hide(f"word:label{g}")
        self._show_generation()

    def _delete_people(self, pids: list) -> None:
        """Family Members deleted from the tree (the one right-clicked, or every one selected)."""
        targets = list(self.selected) if pids and pids[0] in self.selected else pids
        for q in targets:
            self._set_entry(self.village.people[q], hidden=True)
        self.selected = []
        self._saved()
        self._refresh_hidden()
        self.status.set(f"{len(targets)} family member(s) deleted from the tree.  Ctrl+Z, or Deleted items on the "
                        "Layout tab, brings them back.")

    def _hidden_items(self) -> list[tuple[str, str]]:
        """(what it is, its words) for everything deleted from the tree."""
        out = [(f"family member:{ft.entry_key(self.village, p)}", f"Family Member: {p.name}")
               for p in self.village.people.values() if self._entry(p).get("hidden")]
        for what in self._hidden_now():
            kind, _, name = what.partition(":")
            if kind == "label":
                g, _, part = name.partition(":")
                whose = "Every generation label" if g == "*" else f"The generation {gen.roman(int(g))} label"
                out.append((what, f"{whose}: {ft.LABEL_PARTS.get(part, part)}"))
            elif kind == "word" and name.startswith("onward"):
                fam = self._onward_family(name) if name != "onward" else None
                whose = " and ".join(self.village.people[q].name for q in (fam.father, fam.mother) if q is not None) \
                    if fam is not None else ""
                out.append((what, f"\"Continued on page\" words of {whose}" if whose
                            else "Every \"continued on page\" label"))
            elif kind == "word":
                words = ft.MOVABLE.get(name) or (f"the generation {gen.roman(int(name[5:]))} label"
                                                 if name.startswith("label") and name[5:].isdigit() else name)
                out.append((what, words[0].upper() + words[1:]))
            else:
                out.append((what, self._line_words(name)))
        return out

    def _line_words(self, name: str) -> str:
        """A line piece ("<family key>|<piece>") in words: whose line it is."""
        family = next((ft.family_key(self.village, f) for f in self.lay.families
                       if name.startswith(ft.family_key(self.village, f) + "|")), "")
        piece = name[len(family) + 1:] if family else name
        piece = piece[len(ft.ONWARD_PIECE):] if piece.startswith(ft.ONWARD_PIECE) else piece    # above a page break
        parents = " and ".join(part.split("|")[0] for part in family.split("||") if part and part != "-") or "a family"
        kind, _, rest = piece.partition(" ")
        who = rest.rsplit(" ", 1)[0].split("|")[0] if rest else ""
        return {"couple": f"The line joining {parents}",
                "stem": f"The line down from {parents} to their children",
                "lane": f"The line joining {parents}'s children",
                "from": f"{who}'s line to {parents}'s family",
                "to": f"The line to {who}",
                "leg": f"The line to {who}",
                "bar": f"The bar between {parents}'s twins or triplets"}.get(kind, f"A line of {parents}'s family")

    def _refresh_hidden(self) -> None:
        if hasattr(self, "key_var"):            # the Key's tick box follows a right-click Delete and undo
            self.key_var.set("word:key" not in self._hidden_now())
        if not hasattr(self, "hidden_list"):
            return
        self.hidden_list.delete(0, "end")
        self.hidden_keys = []
        for what, words in self._hidden_items():
            self.hidden_list.insert("end", words)
            self.hidden_keys.append(what)

    def _restore_hidden(self, every: bool = False) -> None:
        picked = range(len(self.hidden_keys)) if every else self.hidden_list.curselection()
        for k in picked:
            what = self.hidden_keys[k]
            if what.startswith("family member:"):
                key = what.partition(":")[2]
                self._set_entry_key(key, self._entry_by_key(key), hidden=None)
            elif what in self._hidden_now():
                self._set_hidden([h for h in self._hidden_now() if h != what])
        self._saved()
        self._refresh_hidden()

    def _reset_people(self, pids: list) -> None:
        """Everything the player changed for these family members undone (one Ctrl+Z brings it back)."""
        targets = list(self.selected) if pids and pids[0] in self.selected else pids
        for q in targets:
            key = ft.entry_key(self.village, self.village.people[q])
            # this page's own undone; the tree's own generation and chosen look (Change Appearance) stay
            self._set_entry_key(key, {n: v for n, v in self.edits.entries.get(key, {}).items()
                                      if n in ("generation", "look")}, **{})
        self._saved()

    def _clear_selected(self) -> None:
        if not self.selected:
            return
        if not messagebox.askyesno("Family Tree Maker", f"Reset everything for the {len(self.selected)} selected "
                                                  "family member(s)?  (Ctrl+Z undoes it.)", parent=self):
            return
        self._reset_people(list(self.selected))

    def _titles(self) -> None:
        if (self.title_var.get(), self.subtitle_var.get()) != (self.edits.title, self.edits.subtitle):
            self._change(title=self.title_var.get().strip(), subtitle=self.subtitle_var.get().strip())

    def _gen_number(self) -> int:
        romans = {gen.roman(g): g for g in range(1, 60)}
        return romans.get(self.gen_var.get(), 1)

    def _show_generation(self) -> None:
        g = self._gen_number()
        self.gen_text.delete("1.0", "end")
        if hasattr(self, "lay"):
            self.gen_text.insert("1.0", "\n".join(ft.generation_label(self.lay, g)))

    def _apply_generation(self) -> None:
        g = self._gen_number()
        lines = [line.rstrip() for line in self.gen_text.get("1.0", "end").rstrip("\n").split("\n")]
        self._set_generation_label(g, None if lines == ft.default_generation_label(self.lay, g) else lines)
        self._saved()

    def _restore_generation(self) -> None:
        self._set_generation_label(self._gen_number(), None)
        self._saved()
        self._show_generation()

    # marks
    def _refresh_marks(self) -> None:
        self.marks_list.delete(0, "end")
        for label, colour in self.edits.marks.items():
            self.marks_list.insert("end", f"{label}   ({colour})")
            self.marks_list.itemconfigure("end", foreground=tk_colour(colour, "#888888"))
        self._refresh_status_checks()       # a status's mark removed or renamed: its descriptor with it

    def _mark_at(self) -> str | None:
        picked = self.marks_list.curselection()
        return list(self.edits.marks)[picked[0]] if picked else None

    def _add_preset_mark(self) -> None:
        """A ready-made mark (or the name typed in its box), given to the selected family members."""
        label = self.preset_mark.get().strip()
        if not label or label == CUSTOM_MARK:
            label = (simpledialog.askstring("Special mark", "Name the mark (for example: Favourite):",
                                            parent=self) or "").strip()
            if not label:
                return
        self.edits.marks.setdefault(label, PRESET_MARKS.get(label) or ask_colour(self, f"The colour for {label}")
                                    or "#d4a017")
        if label in self.edits.marks_off:      # removed from everyone before, wanted again: given by the tree again
            self.edits.marks_off.remove(label)
            ft.apply_auto_marks(self.edits, self.full_village)
        for q in self.selected:
            self._give_mark(self.village.people[q], label)
        self._refresh_marks()
        self._saved()
        self.status.set(f"{label}: {len(self.selected)} family member(s) marked." if self.selected
                        else f"{label} added.  Select family members, then click Give mark on the Family Members tab.")

    def _add_mark(self) -> None:
        label = simpledialog.askstring("New mark", "What is the mark for?  (for example: Favourite)", parent=self)
        if not label or not label.strip():
            return
        label = label.strip()
        colour = ask_colour(self, f"The colour for {label}") or "#d4a017"
        self.edits.marks[label] = colour
        self._refresh_marks()
        self._saved()

    def _rename_mark(self, old: str | None = None, new: str | None = None) -> None:
        """A mark renamed: the one picked in the list (asked for), or `old` to `new` (retyped in the Key)."""
        old = old or self._mark_at()
        if old is None:
            return
        if new is None:
            new = simpledialog.askstring("Rename mark", "The mark's new name:", initialvalue=old, parent=self)
        if not new or not new.strip() or new.strip() == old or new.strip() in self.edits.marks:
            return
        new = new.strip()
        self.edits.marks = {(new if k == old else k): v for k, v in self.edits.marks.items()}
        for entry in self._all_entries():
            for name in ("marks", "unmarked"):
                if entry.get(name):
                    entry[name] = list(dict.fromkeys(new if m == old else m for m in entry[name]))
            if entry.get("mark") == old:
                entry["mark"] = new
        # A status's automatic mark keeps the player's name for it (Edits.mark_names).
        for status in {s for p in self.full_village.people.values() for s in p.statuses}:
            if ft.auto_label(self.edits, status) == old:
                self.edits.mark_names[status] = new
        self.edits.marks_off = [new if m == old else m for m in self.edits.marks_off]
        self._refresh_marks()
        self._saved()

    def _all_entries(self) -> list[dict]:
        """Every family member's edits: the tree's and each page's own."""
        return list(self.edits.entries.values()) + [entry for part in self.edits.page_edits.values()
                                                    for entry in part.get("entries", {}).values()]

    def _recolour_mark(self) -> None:
        label = self._mark_at()
        if label is None:
            return
        colour = ask_colour(self, f"The colour for {label}", self.edits.marks[label])
        if colour:
            self.edits.marks[label] = colour
            self._refresh_marks()
            self._saved()

    def _remove_mark(self) -> None:
        label = self._mark_at()
        if label is None or not messagebox.askyesno("Remove mark", f"Remove the mark {label} from everyone?",
                                                    parent=self):
            return
        del self.edits.marks[label]
        own = {id(e) for e in self.edits.entries.values()}
        for entry in self._all_entries():
            if label in ft.entry_marks(entry):
                left = [m for m in ft.entry_marks(entry) if m != label]
                entry["marks"], entry["mark"] = left or None, left[0] if left else None
            if label in (entry.get("unmarked") or []):
                entry["unmarked"] = [m for m in entry["unmarked"] if m != label] or None
            for name in ("marks", "mark", "unmarked"):
                if name in entry and entry[name] is None and id(entry) in own:
                    del entry[name]         # the tree's own: nothing; a page's own None still says "none here"
        for key, entry in list(self.edits.entries.items()):
            if not entry:
                del self.edits.entries[key]
        # A special status's mark removed from everyone stays removed: the tree does not give it again.
        if any(ft.auto_label(self.edits, s) == label for p in self.full_village.people.values() for s in p.statuses) \
                and label not in self.edits.marks_off:
            self.edits.marks_off.append(label)
        self._refresh_marks()
        self._saved()

    def _move_mark(self, step: int) -> None:
        label = self._mark_at()
        if label is None:
            return
        order = list(self.edits.marks)
        i = order.index(label)
        j = max(0, min(len(order) - 1, i + step))
        order[i], order[j] = order[j], order[i]
        self.edits.marks = {k: self.edits.marks[k] for k in order}
        self._refresh_marks()
        self.marks_list.selection_set(j)
        self._saved()

    # background
    def _preset(self, k: int) -> None:
        _title, colour, colour2, picture = self.presets[k]
        self.bg_field.set_quietly(colour)
        rainbow = colour2 if colour2 in ft.RAINBOWS else ""
        self.bg2_field.set_quietly("" if rainbow else colour2)
        # Every ready-made picture is stretched to the page (the owner's default): the frames then run round it all.
        changes = {"background_fit": "stretch"} if picture else {}
        if changes:
            self.fit_var.set(ft.FITS[changes["background_fit"]])
        self._change(background=colour, background2="" if rainbow else colour2, rainbow=rainbow,
                     background_image=picture, **changes)

    def _show_background(self) -> None:
        """The ready-made background in use outlined, and your own picture's thumbnail."""
        e = self.edits
        for label, (_t, colour, colour2, picture) in zip(self.preset_labels, self.presets):
            chosen = ((e.background or ft.BACKGROUND) == colour and (e.rainbow or e.background2) == colour2
                      and e.background_image == picture)
            label.configure(highlightbackground=SELECT if chosen else panel_colour(label))
        path = ft.picture_path(e.background_image, self.images, self.library)
        photo = (self._thumb(("background", str(path)), picture_scene(path, 160, 100, panel_colour(self.picture_thumb)))
                 if path is not None else None)
        self.picture_thumb.configure(image=photo or "")
        self.picture_thumb.photo = photo
        self.picture_var.set("" if not e.background_image else
                             ("" if photo is not None else Path(e.background_image).name))

    def _choose_picture(self) -> None:
        chosen = filedialog.askopenfilename(parent=self, title="A picture for the background",
                                            filetypes=[("Pictures", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")])
        if chosen:
            self._change(background_image=chosen)

    # ---- output ---------------------------------------------------------------
    def _write_outputs(self, later: bool = False) -> None:
        """The tree's page, picture and report in the save folder's Family Trees\\Reports (as Family Tree
        always writes them), with the edits as they are now.  `later`: in the background, from a copy of
        the edits (opening and closing the editor waited over two seconds for them); whatever writes them
        next waits for that first."""
        job = self.__dict__.pop("_write_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._wait_outputs()
        if later:
            edits = ft.Edits.from_data(json.loads(json.dumps(self.edits.to_data())))
            args = (self.folder, self.game, self.slot, self.images, self.game_title)
            library, done = self.library, {}

            def work() -> None:
                try:
                    done["written"] = ft.write(*args, edits=edits, library=library)
                except (OSError, ValueError) as exc:
                    done["error"] = exc
            self._writer = (threading.Thread(target=work, name="Family Tree outputs"), done)
            _WRITING[:] = [self._writer[0]]     # an editor opened again soon after waits for it too
            self._writer[0].start()
            return
        try:
            self.written = ft.write(self.folder, self.game, self.slot, self.images, self.game_title,
                                    edits=self.edits, library=self.library)
        except (OSError, ValueError) as exc:
            self.written = None
            self.status.set(f"The tree's page could not be written: {exc}")

    def _wait_outputs(self) -> None:
        """The outputs being written in the background (_write_outputs), finished; what came of it shown."""
        for thread in _WRITING:                # another editor's (closed on this save, say)
            thread.join()
        writer = self.__dict__.pop("_writer", None)
        if writer is None:
            return
        writer[0].join()
        if "written" in writer[1]:
            self.written = writer[1]["written"]
        elif "error" in writer[1]:
            self.written = None
            try:
                self.status.set(f"The tree's page could not be written: {writer[1]['error']}")
            except tk.TclError:
                pass

    def _trees_folder(self) -> Path | None:
        """The patcher's own folder for this save's tree, Virtual Families 1 Patcher\\Save <N>\\Data\\Family Tree
        beside the save (made when first needed)."""
        folder = ft.data_folder(self.folder, self.slot)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return folder

    def _tree_name(self) -> str:
        tribe = "".join(ch for ch in (self.village.tribe or "Family") if ch not in '\\/:*?"<>|')
        return f"{tribe} (Save {self.slot}) family tree {datetime.now():%Y-%m-%d %H-%M-%S}"

    def _tree_file(self) -> Path | None:
        """The editable tree file, one per save: Virtual Families 1 Family Tree - Save <N>.tree in the patcher's
        own folder for the save (it also keeps every member the tree has seen: vf1_tree_memory)."""
        folder = self._trees_folder()
        return vf1_tree_memory.tree_file(self.folder, self.slot) if folder else None

    def _save_tree(self) -> bool:
        """The tree saved to be worked on later (the owner: "Save to Save Folder - should save the
        family tree as an editable file"): its tree file, and the edits file the tool opens it from."""
        path = self._tree_file()
        if path is None:
            messagebox.showerror("Family Tree Maker", f"The folder {ft.data_folder(self.folder, self.slot)} could not be made.",
                                 parent=self)
            return False
        try:
            data = vf1_tree_memory.read_tree_file(path)       # the members it remembers are kept
        except ValueError:
            data = {}
        data.update({"format": TREE_FORMAT, "game": self.game, "slot": self.slot, "family": self.village.tribe,
                     "edits": self.edits.to_data()})
        try:
            vf1_tree_memory.write_tree_file(path, data)
            self.edits.save(ft.Edits.path(self.folder, self.game, self.slot))
        except OSError as exc:
            messagebox.showerror("Family Tree Maker", f"The tree could not be saved: {exc}", parent=self)
            return False
        self.dirty = False
        self.status.set(f"Saved the tree to {path}")
        return True

    def _open_tree(self) -> None:
        """A saved tree file opened into the editor (its marks, colours, moves, pictures and pages)."""
        folder = self._trees_folder()
        path = filedialog.askopenfilename(parent=self, title="Open a saved family tree",
                                          initialdir=str(folder) if folder else None,
                                          filetypes=[("Family tree", f"*{TREE_SUFFIX}")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("format") != TREE_FORMAT:
                raise ValueError("it is not a Family Tree Maker tree file")
            edits = ft.Edits.from_data(data.get("edits", {}))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Family Tree Maker", f"{Path(path).name} could not be opened: {exc}", parent=self)
            return
        if (data.get("game"), data.get("slot")) != (self.game, self.slot) and not self._sure(
                f"{Path(path).name} was made for another game or save.  Use its look on this tree?"):
            return
        self.edits = edits
        self.obj = None
        self.selected = []
        self.page = 0
        self._follow_looks()
        self._saved()
        self._refresh_panels()
        self.status.set(f"Opened {Path(path).name}.  Ctrl+S saves it as this tree.")

    def _save_as(self, path: Path, scale: float, pages: list | None = None) -> None:
        """The tree as a picture: the pages asked for (0-based; every page when None), each the whole page
        -- "<name> - Page 2" and so on beside the first.  Never the part of it the window shows."""
        if pages is None:
            pages = list(range(len(ft.page_spans(self.edits, self.village))))
        try:
            for k in pages:
                target = path if k == 0 else path.with_name(f"{path.stem} - Page {k + 1}{path.suffix}")
                vf1_gdiplus.save_scene(self._page_scene(k)[1], self.present, target, scale=scale)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save Picture", f"The picture could not be saved: {exc}", parent=self)
            return
        self.status.set(f"Saved {path}" + (f" and {len(pages) - 1} more page(s) beside it" if len(pages) > 1 else ""))
        self._preview_picture(path, pages[0])

    def _preview_picture(self, path: Path, page: int = 0) -> None:
        """The picture just saved, shown as it is (the owner, 2026-10-08: "there should be a fucking image
        preview built in"): drawn by the same graphics as the file, fitted to the screen, over a
        checkerboard so anything see-through in the file shows as see-through, never as the window's
        white."""
        sc = self._page_scene(page)[1]
        fit = min(1.0, (self.winfo_screenwidth() - 120) / max(1.0, sc.width),
                  (self.winfo_screenheight() - 220) / max(1.0, sc.height))
        temp = Path(tempfile.gettempdir()) / f"vvfp-tree-preview-{os.getpid()}.png"
        try:
            # A PNG keeps what is see-through; a JPG has none, so it is shown on its own colour.
            ok = vf1_gdiplus.save_scene(sc, self.present, temp, scale=fit)
            photo = tk.PhotoImage(master=self, file=str(temp)) if ok else None
        except (OSError, tk.TclError):
            photo = None
        finally:
            try:
                temp.unlink()
            except OSError:
                pass
        window = tk.Toplevel(self)
        window.title(f"Preview - {path.name}")
        frame = scrollable_frame(window, padding=8)
        ttk.Label(frame, text=f"Saved {path}.  This is the picture as saved"
                  + (f" (page {page + 1})" if len(ft.page_spans(self.edits, self.village)) > 1 else "")
                  + ".  A checkerboard shows through anything see-through.", wraplength=900).pack(anchor="w")
        if photo is not None:
            w, h = photo.width(), photo.height()
            canvas = tk.Canvas(frame, width=w, height=h, highlightthickness=0)
            canvas.pack(pady=(6, 6))
            for y in range(0, h, 16):
                for x in range(0, w, 16):
                    canvas.create_rectangle(x, y, x + 16, y + 16, width=0,
                                            fill="#cccccc" if (x // 16 + y // 16) % 2 else "#ffffff")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.image = photo                # kept while the window is open
        else:
            ttk.Label(frame, text="(The preview could not be drawn; the picture itself was saved.)").pack(pady=6)
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Open the folder",
                   command=lambda: os.startfile(str(path.parent))).pack(side="left")  # noqa: S606
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="left", padx=(6, 0))
        window.transient(self)
        window.focus_set()

    def _open_page(self) -> None:
        self._write_outputs()
        if self.written is not None:
            os.startfile(str(self.written.page))  # noqa: S606

    # ---- moving around ---------------------------------------------------------
    def _pan_start(self, event) -> None:
        self.pan = (event.x, event.y)
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.configure(cursor="fleur")

    def _pan_move(self, event) -> None:
        if self.pan is not None:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _pan_end(self, event) -> bool:
        """Whether the press was a drag (it moved the view) rather than a click."""
        start, self.pan = self.pan, None
        self.canvas.configure(cursor="")
        return start is not None and (abs(event.x - start[0]) > 3 or abs(event.y - start[1]) > 3)

    # ---- zoom and panes -------------------------------------------------------
    def _zoom_to(self, z: float, around: tuple | None = None) -> None:
        """Zoom the view (never the saved picture), keeping the point `around` (on the canvas's
        window) where it is, else the middle of the view."""
        if z == self.z:
            return
        c = self.canvas
        ax, ay = around if around is not None else (c.winfo_width() / 2, c.winfo_height() / 2)
        sx, sy = (c.canvasx(ax) / self.z, c.canvasy(ay) / self.z)
        self.z = z
        self.zoom_var.set(f"{int(z * 100)}%")
        self.redraw(rescene=False)                # the same tree, only bigger or smaller
        width, height = self.sc.width * z, self.sc.height * z
        c.xview_moveto(max(0.0, (sx * z - ax) / width))
        c.yview_moveto(max(0.0, (sy * z - ay) / height))

    def _zoom_step(self, step: int) -> None:
        levels = list(ZOOMS)
        here = levels.index(self.z)
        self._zoom_to(levels[max(0, min(len(levels) - 1, here + step))])

    def _zoom_wheel(self, event) -> str:
        levels = list(ZOOMS)
        here = levels.index(self.z)
        step = 1 if event.delta > 0 else -1
        self._zoom_to(levels[max(0, min(len(levels) - 1, here + step))], (event.x, event.y))
        return "break"

    def _zoom_choice(self) -> None:
        if self.zoom_var.get() == "Fit":
            self._zoom_fit()
        else:
            self._zoom_to(int(self.zoom_var.get().rstrip("%")) / 100)

    def _zoom_fit(self) -> None:
        """The largest zoom showing the whole tree's width."""
        room = max(100, self.canvas.winfo_width())
        fits = [z for z in ZOOMS if self.sc.width * z <= room]
        self._zoom_to(max(fits) if fits else min(ZOOMS))
        self.zoom_var.set(f"{int(self.z * 100)}%")

    def _toggle_panel(self) -> None:
        if str(self.panel) in self.body.panes():
            self.window["sash"] = self.body.sashpos(0)
            self.body.forget(self.panel)
            self.panel_button.configure(text="Show panel (F4)")
        else:
            self.body.add(self.panel, weight=1)
            self.panel_button.configure(text="Hide panel (F4)")
            if self.window.get("sash"):
                self.after(50, lambda: self._restore_sash(self.window["sash"]))

    def _restore_sash(self, where) -> None:
        try:
            if str(self.panel) in self.body.panes():
                self.body.sashpos(0, int(where))
        except (tk.TclError, ValueError):
            pass

    def _toggle_full(self) -> None:
        self.attributes("-fullscreen", not self.attributes("-fullscreen"))

    def _remember_window(self, keep_look: bool = False) -> None:
        """The window's size and place, the panel's width and whether it shows, for next time -- and the
        tree's look for the next new tree, unless `keep_look`."""
        shown = str(self.panel) in self.body.panes()
        if shown:
            self.window["sash"] = self.body.sashpos(0)
        self.window["panel_hidden"] = not shown
        self.window.update(smart=bool(self.smart_var.get()), snap=bool(self.snap_var.get()),
                           grid=int(self.grid_size.get()), show_grid=bool(self.show_grid.get()),
                           keep_aspect=bool(self.lock_shape.get()), hide_not_in_save=bool(self.hide_gone.get()))
        if not self.attributes("-fullscreen"):
            self.window["geometry"] = self.geometry()
        if hasattr(self.app, "_save_settings"):
            self.app.tree_window = dict(self.window)
            if not keep_look:
                self.app.tree_style = ft.style_of(self.edits)     # the look, for the next new tree
            try:
                self.app._save_settings()
            except OSError:
                pass

    def _help(self) -> None:
        window = tk.Toplevel(self)
        window.title("Family Tree Maker: the controls")
        window.transient(self)
        frame = scrollable_frame(window, padding=8)
        box = tk.Text(frame, width=96, height=44, wrap="none", font=("Consolas", 10))
        box.insert("1.0", CONTROLS)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(frame, text="Close", command=window.destroy).pack(pady=(0, 8))

    def _close(self) -> None:
        """Closing: "Save changes to the tree before exiting?" when there are any (the owner)."""
        keep_look = False
        if self.dirty:
            answer = messagebox.askyesnocancel("Family Tree Maker", "Save changes to the tree before exiting?",
                                               parent=self)
            if answer is None or answer and not self._save_tree():
                return
            if not answer:                      # the tree as last saved
                path = ft.Edits.path(self.folder, self.game, self.slot)
                keep_look = True                # nothing saved: the remembered look stays as it was
                try:
                    if path.is_file():
                        self.edits, keep_look = ft.Edits.load(path), False
                    elif self.opened_from_file:     # deleted (Delete This Tree): as a new tree opens
                        self.edits = ft.styled(getattr(self.app, "tree_style", None))
                    else:                           # never saved: as it opened
                        self.edits = ft.Edits.from_data(json.loads(self.opened_edits))
                except ValueError:
                    self.edits = ft.Edits.from_data(json.loads(self.opened_edits))
        self._remember_window(keep_look=keep_look)
        self._wait_outputs()
        self._tools_close()
        self.destroy()
