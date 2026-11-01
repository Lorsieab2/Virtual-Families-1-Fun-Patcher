"""Game Text (Tools tab -> "Game Text..."): type anything, in any of Virtual Families 1's fonts, see it drawn
exactly as the game draws text, and save it as a transparent PNG.

* Font: the game's four fonts (what each is used for), then the ten font sheets in the game's Images folder
  that the game never draws, "(unused in the game; metrics not from the game)": their glyph boxes were
  found from the sheet (scripts/build_vf1_glyphs.py).
* Colour: the game tints its white letters by ANDing every pixel with the colour (vf1_game_fonts); a
  see-through colour (alpha below 255) is drawn as the game's BlitRectWithAlpha draws it. The game draws no
  outline or shadow of its own.
* Characters: search by name ("e acute", "hiragana ka") or code point ("U+00E9", "e9"); every result says
  whether the font has it ("game"), the patcher made it ("patcher-made"), Windows draws it in the font's
  style ("drawn by Windows: <face>") or nothing can ("missing": the box).
* The preview is the game's own layout (vf1_game_fonts: every box, every advance), with the letters
  Render Unicode with In-Game Fonts adds; "As the stock game shows it" draws the same name's UTF-8 bytes
  as the game does without the patch.
* Save PNG: transparent, at the game's size, 2x or 4x (crisp), or any width and height (smooth), with the
  game's own box (its width and lines) or trimmed to the letters.

Only the game folder's fonts are read; nothing is written but the PNGs the player saves.
"""
from __future__ import annotations

import tkinter as tk
import unicodedata
from functools import lru_cache
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

import vf1_game_fonts as gf
import vf1_picture_image as pi
import vf1_text

TITLE = "Game Text"
MAX_RESULTS = 400
QUICK = (
    ("Accents", "à àáâãäåāăąǎ çćč ďđ "
                "èéêëēėęě ğ ìíîïīįı "
                "ł ñńň òóôõöøő ř śšşș "
                "ťț ùúûüūůű ýÿ źżž ßæœ"),
    ("Capitals", "ÀÁÂÃÄÅĀĂĄ ÇĆČ ÈÉÊËĘĚ "
                 "Ğ ÌÍÎÏİ Ł ÑŃŇ ÒÓÔÕÖØŐ "
                 "Ř ŚŠŞȘ Ț ÙÚÛÜŪŮŰ ÝŸ ŹŻŽ ÆŒ"),
    ("Symbols", "€£¥¢ ‘’“”«» –—…• ©®™ "
                "°±×÷ ←↑→↓ ♥♦♣♠ ★☆ ♪♫"),
    ("Greek", "ΑΒΓΔΕΖΗΘ αβγδεζηθλμπσω"),
    ("Cyrillic", "АБВГДЕЁЖЗ абвгдеёжзя"),
    ("Emoji", "\U0001f600\U0001f60d\U0001f622\U0001f44d\U0001f44d\U0001f3fd ❤️ \U0001f3e0\U0001f476\U0001f382\U0001f1eb\U0001f1f7"),
)
PREVIEW_BACKGROUNDS = (("Checkerboard (clear)", None), ("Game blue", (40, 60, 120)), ("White", (255, 255, 255)),
                       ("Black", (0, 0, 0)))


# --------------------------------------------------------------------------- characters
@lru_cache(maxsize=1)
def _all_names() -> tuple[tuple[int, str], ...]:
    out = []
    for cp in list(range(0x20, 0x30000)) + list(range(0xE0000, 0xE0080)):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        name = unicodedata.name(chr(cp), "")
        if name:
            out.append((cp, name))
    return tuple(out)


def parse_code_point(text: str) -> int | None:
    """A code point written as character tables write them, in hex: "U+00E9", "u+1f600", "0xE9", "&#xE9;", "e9"."""
    t = text.strip().upper()
    for prefix in ("U+", "0X", "\\U", "&#X"):
        if t.startswith(prefix):
            t = t[len(prefix):]
    t = t.rstrip(";")
    if not t or len(t) > 6 or any(c not in "0123456789ABCDEF" for c in t):
        return None
    cp = int(t, 16)
    if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
        return None
    return cp


def search(query: str, limit: int = MAX_RESULTS) -> list[int]:
    """Characters whose name has every word of `query` (any order), or the code point it names, or the
    characters typed themselves."""
    query = query.strip()
    if not query:
        return []
    found: list[int] = []
    cp = parse_code_point(query)
    if cp is not None:
        found.append(cp)
    if len(query) <= 4 and not query.isascii():
        found.extend(ord(c) for c in query if ord(c) not in found)
    words = [w for w in query.upper().replace("-", " ").split() if w]
    if words:
        aliases = {"UMLAUT": "DIAERESIS", "HACEK": "CARON", "HÁČEK": "CARON"}
        words = [aliases.get(w, w) for w in words]
        for c, name in _all_names():
            parts = name.replace("-", " ").split()
            if all(any(p == w or (len(w) > 1 and p.startswith(w)) for p in parts) for w in words):
                if c not in found:
                    found.append(c)
                if len(found) >= limit:
                    break
    return found[:limit]


def describe(font: gf.GameFont, cp: int) -> str:
    ch = chr(cp)
    name = unicodedata.name(ch, "(no name)")
    glyph = font.glyph(ch)
    kind = glyph.kind
    if kind == "drawn by Windows":
        kind = f"drawn by Windows: {glyph.face}"
    shown = ch if unicodedata.category(ch)[0] not in "CZ" else " "
    return f"U+{cp:04X}  {shown}  {name.title()}  ({kind})"


# --------------------------------------------------------------------------- pictures
def checkerboard(width: int, height: int, square: int = 8) -> pi.Image:
    return pi.Image(width, height).on_checks(square=square)


def over(background, image: pi.Image) -> pi.Image:
    if background is None:
        return image.on_checks()
    out = pi.Image(image.width, image.height)
    out.data[:] = bytes((*background, 255)) * (image.width * image.height)
    out.draw(image, 0, 0)
    return out


def stock_picture(font: gf.GameFont, text: str, colour: int) -> pi.Image:
    """`text` stored as the patch stores it (UTF-8) and drawn by the stock game: one byte, one game letter."""
    lines = vf1_text.encode(text).split(b"\n")
    widths = [sum(font.game_glyph(b).width + font.spacing for b in line) - (font.spacing if line else 0)
              for line in lines]
    out = pi.Image(max(1, max(widths)), font.height * len(lines))
    for row, line in enumerate(lines):
        x = 0
        for b in line:
            g = font.game_glyph(b)
            if g.width:
                gf.paint(out, g.image, x, row * font.height, colour)
                x += g.width + font.spacing
    return out


def export_options(size: str, width: str = "", height: str = "", trim: bool = False) -> dict:
    options: dict = {"margin": 0}
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
    options["trim"] = trim
    return options


def save_text_png(image: pi.Image, path, *, trim: bool = False, **options) -> Path:
    """The picture as a PNG: the game's own box (width x lines) or, trimmed, just the letters."""
    if not trim:
        # export() crops to the drawn pixels; keep the game's box by drawing one see-through-safe frame
        path = Path(path)
        out = image
        if "size" in options and options["size"] is not None:
            w, h = options["size"]
            if w <= 0:
                w = max(1, round(out.width * h / out.height))
            if h <= 0:
                h = max(1, round(out.height * w / out.width))
            if w > pi.MAX_SIDE or h > pi.MAX_SIDE:
                raise pi.PictureError(f"A picture can be at most {pi.MAX_SIDE} pixels wide or high.")
            out = out.resized(w, h)
        else:
            scale = int(options.get("scale", 1))
            if scale < 1 or out.width * scale > pi.MAX_SIDE or out.height * scale > pi.MAX_SIDE:
                raise pi.PictureError(f"A picture can be at most {pi.MAX_SIDE} pixels wide or high.")
            out = out.scaled(scale)
        import os
        import uuid
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            temp.write_bytes(out.to_png())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
        return path
    return pi.save_png(image, path, **{k: v for k, v in options.items() if k in ("scale", "size", "margin")})


# --------------------------------------------------------------------------- the window
_open_window = None


def open_window(parent: tk.Misc, *, game_folders=(), hold=None, show_help=None) -> "GameTextWindow":
    global _open_window
    if _open_window is not None and _open_window.window.winfo_exists():
        _open_window.window.deiconify()
        _open_window.window.lift()
        return _open_window
    _open_window = GameTextWindow(parent, game_folders=game_folders, hold=hold, show_help=show_help)
    return _open_window


class GameTextWindow:
    def __init__(self, parent: tk.Misc, *, game_folders=(), hold=None, show_help=None) -> None:
        from vf1_tree_editor_tools import tool_fonts
        self.window = tk.Toplevel(parent)
        self.window.title(TITLE)
        self.tk_fonts = tool_fonts(self.window)
        sw, sh = self.window.winfo_screenwidth(), self.window.winfo_screenheight()
        width, height = min(1120, sw - 60), min(800, sh - 110)
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min(640, width), min(420, height))
        self.window.bind("<Escape>", lambda _e: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.show_help = show_help
        self.game_folders = [Path(f) for f in game_folders if f]
        self.game_var = tk.StringVar(master=self.window)
        self.font_var = tk.StringVar(master=self.window)
        self.colour_var = tk.StringVar(master=self.window)
        self.alpha_var = tk.StringVar(master=self.window, value="255")
        self.background_var = tk.StringVar(master=self.window, value=PREVIEW_BACKGROUNDS[0][0])
        self.zoom_var = tk.StringVar(master=self.window, value="2x")
        self.stock_var = tk.BooleanVar(master=self.window, value=False)
        self.unicode_var = tk.BooleanVar(master=self.window, value=False)
        self.unicode_face_var = tk.StringVar(master=self.window, value="Segoe UI")
        self._overrides: dict = {}
        self.size_var = tk.StringVar(master=self.window, value="1x")
        self.width_var = tk.StringVar(master=self.window)
        self.height_var = tk.StringVar(master=self.window)
        self.trim_var = tk.BooleanVar(master=self.window, value=False)
        self.search_var = tk.StringVar(master=self.window)
        self.status_var = tk.StringVar(master=self.window)
        self.info_var = tk.StringVar(master=self.window)
        self.fonts: gf.Fonts | None = None
        self.font_names: list[str] = []
        self.colour = 0xFFFFFFFF
        self.results: list[int] = []
        self.quiet = False
        self.last_message = ""
        self._pending = None
        self._photo = None
        self._build()
        self._fill_games()
        if hold is not None:
            hold(self.window)

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Game folder:").grid(row=0, column=0, sticky="w")
        self.game_box = ttk.Combobox(top, textvariable=self.game_var, width=60)
        self.game_box.grid(row=0, column=1, columnspan=3, sticky="w", padx=4)
        self.game_box.bind("<<ComboboxSelected>>", lambda _e: self._game_changed())
        self.game_box.bind("<Return>", lambda _e: self._game_changed())
        ttk.Button(top, text="Choose...", command=self.choose_game).grid(row=0, column=4, sticky="w")
        ttk.Button(top, text="?", width=2, command=self._help).grid(row=0, column=5, sticky="e", padx=(12, 0))
        ttk.Label(top, text="Font:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.font_box = ttk.Combobox(top, textvariable=self.font_var, state="readonly", width=60)
        self.font_box.grid(row=1, column=1, columnspan=3, sticky="w", padx=4, pady=(6, 0))
        self.font_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Label(top, text="Colour:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.colour_box = ttk.Combobox(top, textvariable=self.colour_var, state="readonly", width=34)
        self.colour_box.grid(row=2, column=1, sticky="w", padx=4, pady=(6, 0))
        self.colour_box.bind("<<ComboboxSelected>>", lambda _e: self._colour_chosen())
        ttk.Button(top, text="Pick a colour...", command=self.pick_colour).grid(row=2, column=2, sticky="w", pady=(6, 0))
        alpha = ttk.Frame(top)
        alpha.grid(row=2, column=3, sticky="w", padx=(10, 0), pady=(6, 0))
        ttk.Label(alpha, text="Solid (255) to see-through (1):").pack(side="left")
        spin = ttk.Spinbox(alpha, from_=1, to=255, textvariable=self.alpha_var, width=5, command=self.refresh)
        spin.pack(side="left", padx=4)
        spin.bind("<KeyRelease>", lambda _e: self.refresh_soon())

        middle = ttk.Panedwindow(outer, orient="horizontal")
        middle.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(middle)
        right = ttk.Frame(middle)
        middle.add(left, weight=3)
        middle.add(right, weight=2)

        ttk.Label(left, text="Your text (Enter starts a new line):").pack(anchor="w")
        self.text = tk.Text(left, height=5, wrap="word", undo=True, font=("Segoe UI", 12))
        self.text.pack(fill="x")
        self.text.insert("1.0", "Hello, Zoë!")
        self.text.bind("<<Modified>>", self._text_modified)
        view = ttk.Frame(left)
        view.pack(fill="x", pady=(6, 0))
        ttk.Label(view, text="Preview on:").pack(side="left")
        bg = ttk.Combobox(view, textvariable=self.background_var, state="readonly", width=20,
                          values=[b[0] for b in PREVIEW_BACKGROUNDS])
        bg.pack(side="left", padx=4)
        bg.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Label(view, text="Zoom:").pack(side="left", padx=(8, 0))
        for z in ("1x", "2x", "4x"):
            ttk.Radiobutton(view, text=z, value=z, variable=self.zoom_var, command=self.refresh).pack(side="left")
        ttk.Checkbutton(view, text="As the stock game shows it (without the patch)", variable=self.stock_var,
                        command=self.refresh).pack(side="left", padx=(12, 0))
        override = ttk.Frame(left)
        override.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(override, text="As Use Unicode Font draws it, with:", variable=self.unicode_var,
                        command=self.refresh).pack(side="left")
        faces = ttk.Combobox(override, textvariable=self.unicode_face_var, width=30, values=self._faces())
        faces.pack(side="left", padx=4)
        faces.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        faces.bind("<Return>", lambda _e: self.refresh())
        holder = ttk.Frame(left)
        holder.pack(fill="both", expand=True, pady=(6, 0))
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, background="#ffffff", highlightthickness=1, highlightbackground="#c0c0c0")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        ttk.Label(left, textvariable=self.info_var, wraplength=640, justify="left").pack(anchor="w", pady=(4, 0))

        saving = ttk.LabelFrame(left, text="Saving", padding=(10, 4))
        saving.pack(fill="x", pady=(6, 0))
        ttk.Label(saving, text="PNG size:").pack(side="left")
        for label, value in (("Game size", "1x"), ("2x", "2x"), ("4x", "4x"), ("Custom:", "custom")):
            ttk.Radiobutton(saving, text=label, value=value, variable=self.size_var).pack(side="left", padx=(4, 0))
        ttk.Entry(saving, textvariable=self.width_var, width=6).pack(side="left", padx=(2, 0))
        ttk.Label(saving, text="x").pack(side="left", padx=2)
        ttk.Entry(saving, textvariable=self.height_var, width=6).pack(side="left")
        ttk.Label(saving, text="px").pack(side="left", padx=(2, 12))
        ttk.Checkbutton(saving, text="Trim to the letters", variable=self.trim_var).pack(side="left")
        ttk.Button(saving, text="Save PNG...", command=self.save_png).pack(side="right")

        ttk.Label(right, text="Accents and any character (search by name or by code, e.g. \"e acute\" or U+00E9):",
                  wraplength=380, justify="left").pack(anchor="w")
        row = ttk.Frame(right)
        row.pack(fill="x", pady=(4, 0))
        entry = ttk.Entry(row, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self.do_search())
        ttk.Button(row, text="Search", command=self.do_search).pack(side="left", padx=(4, 0))
        quick = ttk.Frame(right)
        quick.pack(fill="x", pady=(4, 0))
        for label, chars in QUICK:
            ttk.Button(quick, text=label, command=lambda c=chars: self.show_chars(c)).pack(side="left", padx=(0, 2))
        box = ttk.Frame(right)
        box.pack(fill="both", expand=True, pady=(4, 0))
        self.result_list = tk.Listbox(box, font=("Segoe UI", 11), activestyle="dotbox")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.result_list.yview)
        self.result_list.configure(yscrollcommand=sb.set)
        self.result_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.result_list.bind("<Double-Button-1>", lambda _e: self.insert_selected())
        self.result_list.bind("<Return>", lambda _e: self.insert_selected())
        ttk.Button(right, text="Insert", command=self.insert_selected).pack(anchor="e", pady=(4, 0))
        ttk.Label(right, text="(patcher-made) letters are made by the patcher in the font's own style, and the game "
                              "shows them too when Render Unicode with In-Game Fonts is on.",
                  wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, textvariable=self.status_var, foreground="#245a9a").pack(side="left")
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")

    # ---------------------------------------------------------------- game folder and fonts
    def _fill_games(self) -> None:
        values = [str(g) for g in self.game_folders if (g / gf.EXE_NAME).is_file()]
        self.game_box.configure(values=values)
        if values and not self.game_var.get():
            self.game_var.set(values[0])
        self._game_changed()

    def choose_game(self) -> None:
        folder = filedialog.askdirectory(parent=self.window, title="Choose the Virtual Families game folder")
        if folder:
            self.game_var.set(folder)
            self._game_changed()

    def _game_changed(self) -> None:
        text = self.game_var.get().strip()
        self.fonts = None
        self.font_names = []
        if not text:
            self.status_var.set("Choose the game folder (the one with Virtual Families.exe).")
            self.font_box.configure(values=[])
            return
        try:
            self.fonts = gf.Fonts(Path(text))
            self.font_names = self.fonts.names()
        except (gf.FontError, OSError) as exc:
            self.status_var.set(str(exc))
            self.font_box.configure(values=[])
            return
        labels = []
        for name in self.font_names:
            try:
                labels.append(self.fonts.font(name).label)
            except gf.FontError:
                labels.append(name)
        self.font_box.configure(values=labels)
        self.font_var.set(labels[0] if labels else "")
        presets = [("White (the font as it is)", 0xFFFFFFFF), ("Black", 0xFF000000)]
        try:
            presets.append(("The game's button text", self.fonts.button_colour() | 0xFF000000))
        except Exception:
            pass
        self.colour_presets = presets
        self.colour_box.configure(values=[p[0] for p in presets])
        self.colour_var.set(presets[0][0])
        self.colour = presets[0][1]
        self.status_var.set(f"{len(self.font_names)} fonts.")
        self.refresh()

    def current_font(self) -> gf.GameFont | None:
        if not self.fonts or not self.font_names:
            return None
        labels = list(self.font_box.cget("values"))
        label = self.font_var.get()
        index = labels.index(label) if label in labels else 0
        font = self.fonts.font(self.font_names[index])
        if self.unicode_var.get() and font.style is not None:
            face = self.unicode_face_var.get().strip() or "Segoe UI"
            key = (font.name, face)
            if key not in self._overrides:
                self._overrides[key] = font.with_unicode_font(face)
            return self._overrides[key]
        return font

    @staticmethod
    def _faces() -> list[str]:
        try:
            import vf1_unicode_font
            return vf1_unicode_font.installed_faces()
        except Exception:
            return ["Segoe UI"]

    # ---------------------------------------------------------------- colour
    def _colour_chosen(self) -> None:
        for label, value in getattr(self, "colour_presets", []):
            if label == self.colour_var.get():
                self.colour = value
        self.refresh()

    def pick_colour(self) -> None:
        r, g, b = self.colour & 0xFF, (self.colour >> 8) & 0xFF, (self.colour >> 16) & 0xFF
        chosen = colorchooser.askcolor(color=f"#{r:02x}{g:02x}{b:02x}", parent=self.window, title="Text colour")
        if chosen and chosen[0]:
            r, g, b = (int(v) for v in chosen[0])
            self.colour = 0xFF000000 | r | g << 8 | b << 16
            self.colour_var.set(f"#{r:02X}{g:02X}{b:02X}")
            self.refresh()

    def effective_colour(self) -> int:
        try:
            alpha = max(1, min(255, int(self.alpha_var.get())))
        except ValueError:
            alpha = 255
        return (self.colour & 0xFFFFFF) | alpha << 24

    # ---------------------------------------------------------------- text and preview
    def text_value(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _text_modified(self, _event=None) -> None:
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.refresh_soon()

    def refresh_soon(self) -> None:
        if self._pending is not None:
            self.window.after_cancel(self._pending)
        self._pending = self.window.after(150, self.refresh)

    def picture(self) -> pi.Image | None:
        font = self.current_font()
        if font is None:
            return None
        text = self.text_value()
        if self.stock_var.get():
            return stock_picture(font, text, self.effective_colour())
        return font.render(text, self.effective_colour())

    def refresh(self) -> None:
        self._pending = None
        font = self.current_font()
        self.canvas.delete("all")
        if font is None:
            self.info_var.set("")
            return
        image = self.picture()
        background = dict(PREVIEW_BACKGROUNDS).get(self.background_var.get())
        shown = over(background, image).scaled(int(self.zoom_var.get()[0]))
        self._photo = tk.PhotoImage(master=self.window, data=__import__("base64").b64encode(shown.to_png()))
        self.canvas.create_image(4, 4, image=self._photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, shown.width + 8, shown.height + 8))
        text = self.text_value()
        kinds: dict[str, int] = {}
        for letter in font.letters(text):
            if letter == "\n":
                continue
            kind = font.glyph(letter).kind
            kinds[kind] = kinds.get(kind, 0) + 1
        parts = [f"{image.width} x {image.height} pixels at game size", f"{vf1_text.char_count(text)} characters",
                 f"{len(vf1_text.encode(text))} bytes in a save"]
        made = ", ".join(f"{n} {k}" for k, n in kinds.items() if k != "game")
        if made:
            parts.append("letters: " + made)
        if kinds.get("missing"):
            parts.append("a box is a letter no font on this computer has")
        self.info_var.set("; ".join(parts) + ".")

    # ---------------------------------------------------------------- characters
    def do_search(self) -> None:
        self.show_results(search(self.search_var.get()))

    def show_chars(self, chars: str) -> None:
        cps = []
        for c in chars:
            if c != " " and ord(c) not in cps:
                cps.append(ord(c))
        self.show_results(cps)

    def show_results(self, cps: list[int]) -> None:
        self.results = cps
        self.result_list.delete(0, "end")
        font = self.current_font()
        for cp in cps:
            self.result_list.insert("end", describe(font, cp) if font else f"U+{cp:04X} {chr(cp)}")
        if not cps:
            self.result_list.insert("end", "Nothing found.")

    def insert_selected(self) -> None:
        picked = self.result_list.curselection()
        if not picked or picked[0] >= len(self.results):
            return
        self.insert_text(chr(self.results[picked[0]]))

    def insert_text(self, text: str) -> None:
        self.text.insert("insert", text)
        self.text.focus_set()
        self.refresh_soon()

    # ---------------------------------------------------------------- saving
    def save_png(self, path: str | None = None) -> Path | None:
        image = self.picture()
        if image is None:
            self._message("error", "Choose the game folder first.")
            return None
        try:
            options = export_options(self.size_var.get(), self.width_var.get(), self.height_var.get(),
                                     self.trim_var.get())
        except pi.PictureError as exc:
            self._message("error", str(exc))
            return None
        if path is None:
            stem = pi.safe_file_name(self.text_value().split("\n", 1)[0] or "Game text", 40)
            path = filedialog.asksaveasfilename(parent=self.window, title="Save PNG", defaultextension=".png",
                                                initialfile=f"{stem}.png", filetypes=[("PNG picture", "*.png")])
            if not path:
                return None
        try:
            saved = save_text_png(image, path, **options)
        except (pi.PictureError, OSError) as exc:
            self._message("error", str(exc))
            return None
        self.status_var.set(f"Saved {saved}")
        return saved

    def _message(self, kind: str, text: str) -> None:
        self.last_message = text
        if self.quiet:
            return
        (messagebox.showerror if kind == "error" else messagebox.showinfo)(TITLE, text, parent=self.window)

    def _help(self) -> None:
        if self.show_help is not None:
            self.show_help()

    def close(self) -> None:
        global _open_window
        if _open_window is self:
            _open_window = None
        if self.window.winfo_exists():
            self.window.destroy()
