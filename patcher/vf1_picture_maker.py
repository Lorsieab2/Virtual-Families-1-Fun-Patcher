"""The Picture Maker (Tools tab -> "Picture Maker..."): the family in a save, and family members you make
yourself, drawn exactly as Virtual Families draws them, saved as transparent PNG pictures.

Laid out as the Fish and Plant Tycoon patcher's Picture Studio (src/picture_studio.py):

* "From my save": the save folder and the family (read only); the family members, at home and those who
  left home, then the outfits in the store and the tool tray, each drawn as the game draws them now (their
  age, hair and face, outfit, a baby on the way); "Save PNG..." and "Save all in this group...".
* "Make your own": a family member from parts (gender, age, hair and face 0-49, outfit 0-49), in the
  house (every pose, direction and head turn, a shadow, as a ghost, carrying something) or as the
  portrait, or an outfit as the store shows it; the pictures as this game folder has them, the stock
  game's or the patcher's own.
* PNGs: transparent, cut to the drawn pixels with a small margin (or none), at the game's size, 2x or 4x
  (crisp), or any width and height (smooth).

The pictures are read from the chosen game folder at run time (vf1_people_pictures); no game art ships
with the patcher, and nothing is written but the PNGs the player saves.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import vf1_people_pictures as pp
import vf1_picture_image as pi

TITLE = "Picture Maker"
PREVIEW = 320                         # the preview's side, in pixels
CHECK = "Not checked against the game"
SAVE_LOCATIONS = ("The family", "Left home", "Store and tool tray")


def export_options(size: str, width: str = "", height: str = "", margin: bool = True) -> dict:
    """picture_image.export's options from the window's choices: "1x" / "2x" / "4x", or "custom" with a
    width and/or height in pixels."""
    options: dict = {"margin": pi.MARGIN if margin else 0}
    if size == "custom":
        def number(text: str) -> int:
            text = str(text or "").strip()
            if not text:
                return 0
            if not text.isdigit() or int(text) <= 0:
                raise pi.PictureError("A width or height is a whole number of pixels, 1 or more.")
            return int(text)
        options["size"] = (number(width), number(height))
    else:
        options["scale"] = dict(pi.SIZES).get(size, 1)
    return options


def game_folder_problem(folder: Path | None) -> str:
    return pp.Art(folder).problem()


# Make your own: (spec key, label, choices) -- choices are (value, label) pairs.
def custom_fields() -> list[tuple[str, str, list]]:
    rows = range(50)
    return [
        ("view", "Picture", list(pp.VIEWS)),
        ("female", "Gender", [(True, "Female"), (False, "Male")]),
        ("age", "Age", pp.age_choices()),
        ("head", "Hair and face", [(k, f"Hair and face {k}") for k in rows]),
        ("body", "Outfit", [(k, f"Outfit {k}") for k in rows]),
        ("pose", "Pose", pp.pose_choices()),
        ("direction", "Direction", list(pp.DIRECTIONS)),
        ("head_turn", "Head turn", list(pp.HEAD_TURN_CHOICES)),
        ("animation", "Animation", pp.animation_choices()),
        ("expression", "Expression", list(pp.EXPRESSION_CHOICES)),
        ("babies", "Babies on the way", [(0, "None"), (1, "One"), (2, "Twins"), (3, "Triplets")]),
        ("carried", "Carrying", pp.carried_choices()),
        ("shadow", "Shadow", [(True, "Shadow"), (False, "No shadow")]),
        ("ghost", "Ghost", [(False, "Alive"), (True, "Ghost (as the game draws one rising)")]),
        ("look", "Pictures", list(pp.LOOKS)),
    ]


CUSTOM_DEFAULTS = {"view": "house", "female": True, "age": 18 * 20, "head": 0, "body": 0,
                   "pose": pp.STANDING_POSE, "direction": 0, "head_turn": pp.FRONT_HEAD, "expression": 0,
                   "babies": 0, "carried": -1, "shadow": True, "ghost": False, "look": "game",
                   "animation": pp.NO_ANIMATION}
# Which fields each picture uses (the others are greyed out).
USES = {
    "house": {"view", "female", "age", "head", "body", "pose", "direction", "head_turn", "babies", "carried",
              "animation", "shadow", "ghost", "look"},
    "portrait": {"view", "female", "age", "head", "body", "expression", "look"},
    "outfit": {"view", "female", "body", "look"},
}
# From my save: the drawing choices for a family member (the save keeps no pose and nothing carried).
SAVED_FIELDS = ("view", "pose", "direction", "head_turn", "animation", "carried", "expression", "shadow", "ghost")


def animation_greys(spec: dict) -> set[str]:
    """The fields an animation sets for itself (greyed out while it is picked): its pose, and its direction when it
    has one of its own (not a walking direction the game picks at random)."""
    animation = spec.get("animation", pp.NO_ANIMATION)
    if animation is None or animation == pp.NO_ANIMATION:
        return set()
    pose, direction = pp.ANIMATIONS[animation]
    return ({"pose"} if pose >= 0 else set()) | ({"direction"} if direction != -2 else set())


def carried_text(spec: dict) -> str:
    """The words under the picture for what is carried and the animation, with the not-checked mark where the
    picture is not the game's own draw."""
    words = []
    if spec.get("view", "house") == "house":
        note = pp.carried_note(spec.get("carried", -1))
        thing = pp.carried_thing(spec.get("carried", -1))
        if thing is not None and not thing.from_game:
            note = f"{CHECK}: {note}"
        if note:
            words.append(note)
        animation = spec.get("animation", pp.NO_ANIMATION)
        if animation is not None and animation != pp.NO_ANIMATION and pp.ANIMATIONS[animation][0] < 0:
            words.append(f"{CHECK}: animation {animation + 1} has no pose of its own (the game never plays it); "
                         "it is drawn with the pose picked above.")
    return " ".join(words)

_open_window: PictureMaker | None = None


def open_window(parent: tk.Misc, *, save_folders=(), game_folders=(), hold=None, show_help=None) -> PictureMaker:
    """Open (or raise) the Picture Maker.  `save_folders` and `game_folders` are the folders offered first;
    `hold(dialog)` is the patcher's Windows-style hold; `show_help()` opens its "?" guide."""
    global _open_window
    if _open_window is not None and _open_window.window.winfo_exists():
        _open_window.window.deiconify()
        _open_window.window.lift()
        return _open_window
    _open_window = PictureMaker(parent, save_folders=save_folders, game_folders=game_folders, hold=hold,
                                show_help=show_help)
    return _open_window


class PictureMaker:
    def __init__(self, parent: tk.Misc, *, save_folders=(), game_folders=(), hold=None, show_help=None) -> None:
        from vf1_tree_editor_tools import tool_fonts
        self.window = tk.Toplevel(parent)
        self.window.title(TITLE)
        self.fonts = tool_fonts(self.window)
        screen_w, screen_h = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        width, height = min(1120, screen_w - 60), min(780, screen_h - 110)
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min(640, width), min(420, height))
        self.window.bind("<Escape>", lambda _e: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.show_help = show_help
        self.save_folders = [Path(f) for f in save_folders]
        self.game_folders = [Path(f) for f in game_folders if f]
        self.game_var = tk.StringVar(master=self.window)
        self.folder_var = tk.StringVar(master=self.window)
        self.slot_var = tk.StringVar(master=self.window)
        self.status_var = tk.StringVar(master=self.window)
        self.size_var = tk.StringVar(master=self.window, value="1x")
        self.width_var = tk.StringVar(master=self.window)
        self.height_var = tk.StringVar(master=self.window)
        self.margin_var = tk.BooleanVar(master=self.window, value=True)
        self.slots: list[pp.Slot] = []
        self.things: list[pp.SavedThing] = []
        self.thing_nodes: dict[str, pp.SavedThing] = {}
        self.shown: dict[str, pi.Image] = {}
        self.arts: dict[tuple, pp.Art] = {}
        self.quiet = False                            # tests: messages are kept, not shown
        self.last_message = ""
        self._build()
        self._fill_games()
        self._fill_folders()
        if hold is not None:
            hold(self.window)

    # ---------------------------------------------------------------- layout
    def _scrolling(self) -> ttk.Frame:
        """The frame everything goes in: it scrolls both ways once the window is smaller than it (scroll bars
        at the right and the bottom, the wheel scrolls up and down), and fills the window when it is bigger."""
        holder = ttk.Frame(self.window)
        holder.pack(fill="both", expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0,
                           background=ttk.Style(self.window).lookup("TFrame", "background") or "#f0f0f0")
        down = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        across = ttk.Scrollbar(holder, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        frame = ttk.Frame(canvas, padding=12)
        item = canvas.create_window((0, 0), window=frame, anchor="nw")

        def fit(_event=None) -> None:
            width = max(frame.winfo_reqwidth(), canvas.winfo_width())
            height = max(frame.winfo_reqheight(), canvas.winfo_height())
            canvas.itemconfigure(item, width=width, height=height)
            canvas.configure(scrollregion=(0, 0, width, height))

        def wheel(event) -> None:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        frame.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)
        self.window.bind("<MouseWheel>", wheel, add="+")
        self.scroll_canvas = canvas
        return frame

    def _build(self) -> None:
        outer = self._scrolling()
        self.outer = outer
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Game folder:", font=self.fonts["text"]).grid(row=0, column=0, sticky="w")
        self.game_box = ttk.Combobox(top, textvariable=self.game_var, width=60)
        self.game_box.grid(row=0, column=1, sticky="w", padx=(4, 4))
        self.game_box.bind("<<ComboboxSelected>>", lambda _e: self._game_changed())
        self.game_box.bind("<Return>", lambda _e: self._game_changed())
        ttk.Button(top, text="Choose...", command=self.choose_game).grid(row=0, column=2, sticky="w")
        ttk.Button(top, text="?", width=2, command=self._help).grid(row=0, column=3, sticky="e", padx=(12, 0))
        ttk.Label(top, text="Save folder:", font=self.fonts["text"]).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.folder_box = ttk.Combobox(top, textvariable=self.folder_var, state="readonly", width=60)
        self.folder_box.grid(row=1, column=1, sticky="w", padx=(4, 4), pady=(6, 0))
        self.folder_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_slots())
        ttk.Button(top, text="Choose...", command=self.choose_save_folder).grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Label(top, text="Family:", font=self.fonts["text"]).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.slot_box = ttk.Combobox(top, textvariable=self.slot_var, state="readonly", width=40)
        self.slot_box.grid(row=2, column=1, sticky="w", padx=(4, 4), pady=(6, 0))
        self.slot_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_save_list())
        ttk.Label(outer, textvariable=self.status_var, foreground="#245a9a", wraplength=1000, justify="left",
                  font=self.fonts["text"]).pack(anchor="w", pady=(6, 0))

        options = ttk.LabelFrame(outer, text="Saving", padding=(10, 4))
        options.pack(fill="x", pady=(6, 0))
        ttk.Label(options, text="PNG size:").pack(side="left")
        for label, value in (("Game size", "1x"), ("2x", "2x"), ("4x", "4x"), ("Custom:", "custom")):
            ttk.Radiobutton(options, text=label, value=value, variable=self.size_var).pack(side="left", padx=(4, 0))
        ttk.Entry(options, textvariable=self.width_var, width=6).pack(side="left", padx=(2, 0))
        ttk.Label(options, text="x").pack(side="left", padx=2)
        ttk.Entry(options, textvariable=self.height_var, width=6).pack(side="left")
        ttk.Label(options, text="px").pack(side="left", padx=(2, 12))
        ttk.Checkbutton(options, text="Small margin", variable=self.margin_var).pack(side="left")

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True, pady=(8, 0))
        self._build_save_tab()
        self._build_custom_tab()
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")

    def _help(self) -> None:
        if self.show_help is not None:
            self.show_help()

    def close(self) -> None:
        global _open_window
        if _open_window is self:
            _open_window = None
        if self.window.winfo_exists():
            self.window.destroy()

    def _preview_pane(self, parent) -> dict:
        pane = ttk.Frame(parent, padding=(10, 0))
        canvas = tk.Canvas(pane, width=PREVIEW, height=PREVIEW, highlightthickness=1, highlightbackground="#c0c0c0",
                           background="#ffffff")
        canvas.pack(anchor="n")
        info = ttk.Label(pane, text="", wraplength=PREVIEW, justify="left", font=self.fonts["text"])
        info.pack(anchor="w", pady=(6, 0))
        return {"pane": pane, "canvas": canvas, "info": info}

    def _combo(self, parent, row: int, key: str, label: str, choices: list, value, on_change) -> dict:
        ttk.Label(parent, text=f"{label}:").grid(row=row, column=0, sticky="w", pady=2)
        box = ttk.Combobox(parent, values=[c[1] for c in choices], state="readonly", width=46)
        box.grid(row=row, column=1, sticky="w", padx=(6, 0), pady=2)
        values = [c[0] for c in choices]
        box.current(values.index(value) if value in values else 0)
        box.bind("<<ComboboxSelected>>", lambda _e: on_change())
        longest = max(len(c[1]) for c in choices)
        if longest > 46:                              # the list opens wide enough for its longest line
            def widen(box=box, longest=longest) -> None:
                try:
                    popdown = box.tk.call("ttk::combobox::PopdownWindow", box)
                    box.tk.call(f"{popdown}.f.l", "configure", "-width", longest + 2)
                except tk.TclError:
                    pass
            box.configure(postcommand=widen)
        return {"box": box, "choices": choices}

    @staticmethod
    def _value(entry: dict):
        index = entry["box"].current()
        choices = entry["choices"]
        return choices[index][0] if 0 <= index < len(choices) else choices[0][0]

    # ---------------------------------------------------------------- From my save
    def _build_save_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="From my save")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True)
        style = ttk.Style(self.window)
        style.configure("Picture.Treeview", font=self.fonts["text"],
                        rowheight=int(self.fonts["text"].metrics("linespace") * 1.35))
        self.save_tree = ttk.Treeview(left, columns=("what",), show="tree headings", selectmode="browse", height=18,
                                      style="Picture.Treeview")
        self.save_tree.heading("#0", text="In the save")
        self.save_tree.heading("what", text="Kind")
        self.save_tree.column("#0", width=380)
        self.save_tree.column("what", width=110, stretch=False)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.save_tree.yview)
        self.save_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.save_tree.pack(side="left", fill="both", expand=True)
        self.save_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_saved())
        right = ttk.Frame(tab)
        right.pack(side="left", fill="y")
        self.save_preview = self._preview_pane(right)
        self.save_preview["pane"].pack(fill="x")
        ways = ttk.Frame(right, padding=(10, 6))
        ways.pack(fill="x")
        fields = {k: (label, choices) for k, label, choices in custom_fields()}
        self.saved_boxes = {}
        for row, key in enumerate(SAVED_FIELDS):
            label, choices = fields[key]
            if key == "view":
                choices = [c for c in choices if c[0] != "outfit"]
            if key == "ghost":
                choices = [(None, "As the save has them (a deceased one as a ghost)"), (False, "Alive"),
                           (True, "Ghost")]
            default = None if key == "ghost" else CUSTOM_DEFAULTS[key]
            self.saved_boxes[key] = self._combo(ways, row, key, label, choices, default, self._show_saved)
        buttons = ttk.Frame(right, padding=(10, 6))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Save PNG...", command=lambda: self.save_png("save")).pack(anchor="w")
        ttk.Button(buttons, text="Save all in this group...", command=self.save_all).pack(anchor="w", pady=(6, 0))

    def _fill_games(self) -> None:
        seen, values = set(), []
        for folder in self.game_folders:
            key = str(folder).casefold()
            if key not in seen and (folder / pp.ANIMPTS).is_file():
                seen.add(key)
                values.append(str(folder))
        self.game_box.configure(values=values)
        if values and not self.game_var.get():
            self.game_var.set(values[0])
        self._game_changed()

    def choose_game(self, chosen: str | None = None) -> str:
        if chosen is None:
            chosen = filedialog.askdirectory(parent=self.window, title="Choose your Virtual Families game folder")
        if not chosen:
            return ""
        problem = game_folder_problem(Path(chosen))
        if problem:
            self._tell("warning", problem)
            return problem
        self.game_folders.insert(0, Path(chosen))
        self.game_var.set(str(Path(chosen)))
        self._fill_games()
        return ""

    def game_folder(self) -> Path | None:
        text = self.game_var.get().strip().strip('"')
        return Path(text) if text else None

    def art(self, look: str = "game") -> pp.Art:
        key = (str(self.game_folder()), look)
        if key not in self.arts:
            self.arts[key] = pp.Art(self.game_folder(), look)
        return self.arts[key]

    def _game_changed(self) -> None:
        art = self.art()
        problem = art.problem()
        if problem:
            self.status_var.set(problem)
        else:
            patched = art.patched_files()
            look = ("This game folder has the patcher's own " + " and ".join(
                pp.PATCHER_ART[n][1] for n in patched) + " pictures; From my save shows them, as the game does."
                    if patched else "This game folder has the stock pictures.")
            self.status_var.set(f"Pictures from {art.folder}. {look}")
        if hasattr(self, "save_tree"):
            self._show_saved()
            self._show_custom()

    def _fill_folders(self) -> None:
        values = [str(f) for f in self.save_folders]
        self.folder_box.configure(values=values)
        if values and not self.folder_var.get():
            self.folder_box.current(0)
        self._fill_slots()

    def choose_save_folder(self, chosen: str | None = None) -> None:
        if chosen is None:
            chosen = filedialog.askdirectory(parent=self.window, title="Choose a Virtual Families save folder")
        if not chosen:
            return
        self.save_folders.insert(0, Path(chosen))
        self.folder_var.set("")
        self._fill_folders()

    def current_folder(self) -> Path | None:
        text = self.folder_var.get()
        return Path(text) if text else None

    def _fill_slots(self) -> None:
        folder = self.current_folder()
        self.slots = pp.save_slots(folder) if folder is not None else []
        self.slot_box.configure(values=[f"Family {s.slot}: the {s.family} family" for s in self.slots])
        if self.slots:
            self.slot_box.current(0)
        else:
            self.slot_var.set("")
        self._fill_save_list()

    def current_slot(self) -> pp.Slot | None:
        index = self.slot_box.current()
        return self.slots[index] if 0 <= index < len(self.slots) else None

    def _fill_save_list(self) -> None:
        tree = self.save_tree
        tree.delete(*tree.get_children())
        self.things, self.thing_nodes = [], {}
        slot = self.current_slot()
        info = self.save_preview["info"]
        if slot is None:
            info.configure(text="Pick a save folder and a family to see who is in it.", foreground="")
            return
        try:
            self.things = pp.saved_things(self.current_folder(), slot.slot)
        except Exception as exc:                 # an unreadable save is said, never raised
            info.configure(text=f"The save could not be read: {exc}", foreground="#a01010")
            return
        groups: dict[str, str] = {}
        for thing in self.things:
            parent = groups.get(thing.item.location)
            if parent is None:
                parent = tree.insert("", "end", text=thing.item.location, open=True)
                groups[thing.item.location] = parent
            node = tree.insert(parent, "end", text=thing.item.label, values=(thing.item.kind,))
            self.thing_nodes[node] = thing
        if not any(t.person for t in self.things):
            info.configure(text="This save has no family members to draw (a family is started in the game).",
                           foreground="")
        else:
            info.configure(text="Pick someone to see them as the game draws them now.", foreground="")
        first = next((node for node, t in self.thing_nodes.items() if t.person is not None), None)
        if first is not None:
            tree.selection_set(first)
            self._show_saved()

    def selected_thing(self) -> pp.SavedThing | None:
        selection = self.save_tree.selection()
        return self.thing_nodes.get(selection[0]) if selection else None

    def saved_spec(self, thing: pp.SavedThing) -> dict:
        if thing.outfit is not None:
            return {"view": "outfit", "female": thing.outfit[0], "picture": thing.outfit[1]}
        p = thing.person
        spec = {k: self._value(b) for k, b in self.saved_boxes.items()}
        if spec["ghost"] is None:
            spec["ghost"] = thing.dead          # the save keeps no ghost: the look of one rising
        spec.update({"female": p.female, "age": p.age, "head": p.head, "body": p.body, "babies": p.babies})
        return spec

    def render_thing(self, thing: pp.SavedThing) -> pi.Image:
        return pp.render(self.art(), self.saved_spec(thing))

    def _show_saved(self) -> None:
        thing = self.selected_thing()
        if thing is None:
            return
        chosen = {k: self._value(b) for k, b in self.saved_boxes.items()}
        uses = (USES[chosen["view"]] | {"ghost"}) - animation_greys(chosen)
        for key, entry in self.saved_boxes.items():
            entry["box"].configure(state="readonly" if thing.person is not None and key in uses else "disabled")
        text = thing.item.detail
        if thing.person is not None:
            extra = carried_text(chosen)
            text += f" {extra}" if extra else ""
        if thing.dead:
            text += (f" {CHECK}: how the game shows a deceased family member when this save is opened (shown "
                     "here as the ghost the game draws when one dies).")
        if thing.person is not None:
            text += " The save keeps no pose and nothing carried: pick them below."
        self._render_into("save", self.save_preview, lambda: self.render_thing(thing), text)

    def _render_into(self, which: str, preview: dict, make, text: str) -> None:
        self.window.configure(cursor="watch")
        self.window.update_idletasks()
        try:
            image = make()
        except Exception as exc:
            self.shown.pop(which, None)
            self._show(preview, None, f"This cannot be drawn: {exc}")
            return
        finally:
            self.window.configure(cursor="")
        self.shown[which] = image
        self._show(preview, image, text)

    def _show(self, preview: dict, image: pi.Image | None, text: str) -> None:
        canvas = preview["canvas"]
        canvas.delete("all")
        preview["info"].configure(text=text, foreground="" if image is not None else "#a01010")
        if image is None:
            return
        shown = image.cropped(pi.MARGIN)
        factor = max(1, min(4, PREVIEW // max(shown.width, shown.height, 1)))
        board = shown.on_checks()
        photo = board.photo(tk, self.window, max_side=PREVIEW)
        if factor > 1 and max(shown.width, shown.height) * factor <= PREVIEW:
            photo = photo.zoom(factor)
        canvas.create_image(PREVIEW // 2, PREVIEW // 2, image=photo)
        canvas.photo = photo

    # ---------------------------------------------------------------- Make your own
    def _build_custom_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Make your own")
        left = ttk.Frame(tab, padding=(4, 4))
        left.pack(side="left", fill="both", expand=True)
        self.custom_boxes = {}
        for row, (key, label, choices) in enumerate(custom_fields()):
            self.custom_boxes[key] = self._combo(left, row, key, label, choices, CUSTOM_DEFAULTS[key],
                                                 self._show_custom)
        ttk.Label(left, text=("Ages: the game draws everyone under 14 a little smaller each year younger, and "
                              "from 45 with the older hair and face pictures; the stage names are the patcher's. "
                              "A walking step's direction picks its column; the direction also puts what is "
                              "carried behind (1 and 4) or in front (2 and 3). An animation sets the pose and "
                              "direction the game gives it, and five of them draw what is carried (and the babies "
                              "on the way) 10 or 20 pixels lower. Carrying lists every picture a family member can "
                              "be drawn holding: the ones the game shows first, then the ones it never shows."),
                  wraplength=480, justify="left", foreground="#555555").grid(
            row=len(self.custom_boxes), column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(left, text=(f"{CHECK}: whether the game itself ever shows a given pose with a given head turn "
                              "or a given thing with a given animation (it picks them as family members move "
                              "about)."),
                  wraplength=480, justify="left", foreground="#a05000").grid(
            row=len(self.custom_boxes) + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        right = ttk.Frame(tab)
        right.pack(side="left", fill="y")
        self.custom_preview = self._preview_pane(right)
        self.custom_preview["pane"].pack(fill="x")
        buttons = ttk.Frame(right, padding=(10, 6))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Save PNG...", command=lambda: self.save_png("custom")).pack(anchor="w")

    def custom_spec(self) -> dict:
        spec = {k: self._value(b) for k, b in self.custom_boxes.items()}
        spec["picture"] = spec["body"]
        return spec

    def set_custom(self, **values) -> None:
        """Pick values in Make your own (the tests, and the window itself)."""
        for key, value in values.items():
            entry = self.custom_boxes[key]
            entry["box"].current([c[0] for c in entry["choices"]].index(value))
        self._show_custom()

    def _show_custom(self) -> None:
        if not hasattr(self, "custom_boxes"):
            return
        spec = self.custom_spec()
        uses = USES[spec["view"]] - animation_greys(spec)
        for key, entry in self.custom_boxes.items():
            entry["box"].configure(state="readonly" if key in uses else "disabled")
        note = "" if spec["look"] == "game" else (
            "Stock pictures (the patcher's backups of the ones it replaced)." if spec["look"] == "stock"
            else "The patcher's own pictures for what is carried.")
        note = " ".join(w for w in (note, carried_text(spec)) if w)
        self._render_into("custom", self.custom_preview, lambda: pp.render(self.art(spec["look"]), spec), note)

    # ---------------------------------------------------------------- saving
    def export_choice(self) -> dict:
        return export_options(self.size_var.get(), self.width_var.get(), self.height_var.get(), self.margin_var.get())

    def picture_name(self, which: str) -> str:
        if which == "save":
            thing = self.selected_thing()
            label = thing.item.label if thing else "picture"
            carried = pp.carried_thing(self._value(self.saved_boxes["carried"]))
            if thing is not None and thing.person is not None and carried is not None \
                    and self._value(self.saved_boxes["view"]) == "house":
                label += f" carrying {carried.name}"
            return pi.safe_file_name(label)
        names = []
        for key in ("female", "age", "head", "body", "pose", "carried"):
            if key == "carried" and self.custom_spec()["carried"] == -1:
                continue
            if key in USES[self.custom_spec()["view"]]:
                entry = self.custom_boxes[key]
                names.append(entry["choices"][max(0, entry["box"].current())][1])
        return pi.safe_file_name(" - ".join(names) or "picture")

    def save_png(self, which: str, path: str | None = None) -> Path | None:
        image = self.shown.get(which)
        if image is None:
            self._tell("info", "Pick a picture first.")
            return None
        try:
            options = self.export_choice()
        except pi.PictureError as exc:
            self._tell("warning", str(exc))
            return None
        if path is None:
            path = filedialog.asksaveasfilename(parent=self.window, title="Save PNG", defaultextension=".png",
                                                initialfile=self.picture_name(which) + ".png",
                                                filetypes=[("PNG picture", "*.png")])
        if not path:
            return None
        try:
            return pi.save_png(image, path, **options)
        except (OSError, pi.PictureError) as exc:
            self._tell("warning", f"The picture could not be saved: {exc}")
            return None

    def save_all(self, folder: str | None = None) -> Path | None:
        selection = self.save_tree.selection()
        if not selection:
            self._tell("info", "Pick a group (or anyone in it) first.")
            return None
        node = selection[0]
        thing = self.thing_nodes.get(node)
        location = thing.item.location if thing is not None else self.save_tree.item(node, "text")
        try:
            options = self.export_choice()
        except pi.PictureError as exc:
            self._tell("warning", str(exc))
            return None
        if folder is None:
            folder = filedialog.askdirectory(parent=self.window, title="Save the pictures in...")
        if not folder:
            return None
        slot = self.current_slot()
        stem = pi.safe_file_name(f"The {slot.family} family - {location}" if slot else location)
        target = Path(folder) / stem
        n = 2
        while target.exists():
            target = Path(folder) / f"{stem} ({n})"
            n += 1
        try:
            target.mkdir(parents=True)
        except OSError as exc:
            self._tell("warning", f"The folder could not be made: {exc}")
            return None
        saved, failed = 0, []
        for item in self.things:
            if item.item.location != location:
                continue
            try:
                pi.save_png(self.render_thing(item), pi.unique_path(target, pi.safe_file_name(item.item.label)),
                            **options)
                saved += 1
            except (OSError, pi.PictureError) as exc:
                failed.append(f"{item.item.label}: {exc}")
        text = f"{saved} picture(s) saved in {target}."
        if failed:
            text += "\nNot saved:\n" + "\n".join(failed[:10])
        self._tell("info", text)
        return target

    def _tell(self, kind: str, text: str) -> None:
        self.last_message = text
        if not self.quiet:
            (messagebox.showwarning if kind == "warning" else messagebox.showinfo)(TITLE, text, parent=self.window)
