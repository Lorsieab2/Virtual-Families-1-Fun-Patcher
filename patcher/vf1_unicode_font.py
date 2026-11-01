"""Unicode Font (Tools tab -> "Unicode Font..."): pick the font Use Unicode Font (overrides in-game fonts) draws all of
Virtual Families 1's text with.

Any font installed in Windows, or a .ttf / .otf / .ttc file. The choice is written into the modded game folder's
"Virtual Families 1 Patcher Files\\settings.ini", section [UnicodeFont]:

    Face=<the font's name, as Windows knows it>
    File=<a font file copied into "Virtual Families 1 Patcher Files\\Unicode Font", or empty>

which vf1font.dll reads when the game starts (ReadChosenFont: a file is loaded for the game only, never installed
in Windows). No section means Segoe UI. Each of the game's four fonts keeps its height, baseline and weight, and
its size is fitted so a line is as wide as the game's own (vf1_game_fonts.fit_unicode_font); the preview here is
drawn exactly as the game will draw it. The [Patches] switches and every other section are kept as they are.
Nothing but settings.ini and the copied font file is written; the game's own files and the saves are not touched.
"""
from __future__ import annotations

import os
import shutil
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import vf1_game_fonts as gf
import vf1_glyph_gdi as gdi
import vf1_patcher as patcher

TITLE = "Unicode Font"
SECTION = "UnicodeFont"
FONT_FOLDER = "Unicode Font"
DEFAULT_FACE = "Segoe UI"
SAMPLE = "The Smith Family – Zoë, İlkay, Łukasz 日本 \U0001f44d"
FONT_FILES = (("Font files", "*.ttf *.otf *.ttc"), ("All files", "*.*"))


class FontChoiceError(Exception):
    """A choice that cannot be written, with a reason a player can read."""


def settings_path(game_dir: Path) -> Path:
    return Path(game_dir) / patcher.PATCHER_FOLDER / patcher.SETTINGS_INI


def read_choice(game_dir: Path) -> tuple[str, str]:
    """(face, file) from the folder's settings.ini; (Segoe UI, "") when nothing was chosen."""
    path = settings_path(game_dir)
    data = path.read_bytes() if path.is_file() else None
    values = patcher.read_ini_section(data, SECTION)
    return values.get("Face") or DEFAULT_FACE, values.get("File", "")


def is_on(game_dir: Path) -> bool:
    path = settings_path(game_dir)
    data = path.read_bytes() if path.is_file() else None
    return patcher.read_ini_section(data, patcher.SETTINGS_SECTION).get("UseUnicodeFont") == "1"


def with_section(existing: bytes | None, values: dict[str, str]) -> bytes:
    """settings.ini with [UnicodeFont] holding exactly `values`, everything else kept as it was."""
    text, encoding = patcher._decode_ini(existing) if existing else ("", "latin-1")
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            skipping = stripped[1:stripped.index("]")].strip().casefold() == SECTION.casefold()
            if skipping:
                continue
        if not skipping:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    if out:
        out.append("")
    out.append(f"[{SECTION}]")
    out.append("; Written by the Virtual Families 1 Fun Patcher's Unicode Font tool (Use Unicode Font).")
    out.extend(f"{key}={value}" for key, value in values.items())
    rendered = "\r\n".join(out) + "\r\n"
    try:
        return rendered.encode(encoding)
    except UnicodeEncodeError as exc:
        raise FontChoiceError("This font's name cannot be written for the game; choose another font, or the "
                              "font's file instead.") from exc


def write_choice(game_dir: Path, face: str, font_file: Path | None = None) -> Path:
    """Write the choice into the modded folder; a font file is copied into its Unicode Font folder first."""
    game_dir = Path(game_dir)
    ini = settings_path(game_dir)
    if not ini.is_file():
        raise FontChoiceError("This folder has not been patched yet: patch it first, then choose the font.")
    face = (face or "").strip()
    if not face:
        raise FontChoiceError("Choose a font.")
    try:
        face.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise FontChoiceError("This font's name cannot be written for the game; choose the font's file "
                              "instead.") from exc
    file_name = ""
    if font_file is not None:
        font_file = Path(font_file)
        if font_file.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            raise FontChoiceError("Choose a .ttf, .otf or .ttc font file.")
        family = gdi.font_file_family(font_file.read_bytes())
        if not family:
            raise FontChoiceError(f"{font_file.name} is not a font file Windows can use.")
        face = family
        folder = game_dir / patcher.PATCHER_FOLDER / FONT_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        file_name = font_file.name
        try:
            file_name.encode("latin-1")
        except UnicodeEncodeError:
            file_name = f"font-{uuid.uuid4().hex[:8]}{font_file.suffix.lower()}"
        target = folder / file_name
        if target.resolve() != font_file.resolve():
            temp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
            shutil.copyfile(font_file, temp)
            os.replace(temp, target)
    data = with_section(ini.read_bytes(), {"Face": face, "File": file_name})
    patcher.atomic_write(ini, data)
    return ini


def installed_faces() -> list[str]:
    """Every font family Windows has, as Tk lists them (vertical "@" faces and names the game cannot be told left
    out)."""
    import tkinter.font as tkfont
    names = set()
    for name in tkfont.families():
        if name.startswith("@"):
            continue
        try:
            name.encode("latin-1")
        except UnicodeEncodeError:
            continue
        names.add(name)
    return sorted(names, key=str.casefold)


def preview(game_dir: Path, face: str, font_file: Path | None = None, text: str = SAMPLE):
    """[(label, picture)] for the game's four fonts drawn with the chosen font, as vf1font.dll will draw them."""
    if font_file is not None:
        gdi.add_private_font(font_file)
    fonts = gf.Fonts(Path(game_dir))
    out = []
    for name in gf.GAME_FONTS:
        if name in fonts.found:
            f = fonts.font(name).with_unicode_font(face)
            out.append((f"{name}: {face} at {f.override[1]} px", f.render(text)))
    return out


# --------------------------------------------------------------------------- the window
_open_window = None


def open_window(parent: tk.Misc, *, game_folders=(), hold=None, show_help=None) -> "UnicodeFontWindow":
    global _open_window
    if _open_window is not None and _open_window.window.winfo_exists():
        _open_window.window.deiconify()
        _open_window.window.lift()
        return _open_window
    _open_window = UnicodeFontWindow(parent, game_folders=game_folders, hold=hold, show_help=show_help)
    return _open_window


class UnicodeFontWindow:
    def __init__(self, parent: tk.Misc, *, game_folders=(), hold=None, show_help=None) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title(TITLE)
        self.window.geometry("900x640")
        self.window.bind("<Escape>", lambda _e: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.show_help = show_help
        self.game_folders = [Path(f) for f in game_folders if f]
        self.game_var = tk.StringVar(master=self.window)
        self.search_var = tk.StringVar(master=self.window)
        self.status_var = tk.StringVar(master=self.window)
        self.face = DEFAULT_FACE
        self.font_file: Path | None = None
        self.quiet = False
        self.last_message = ""
        self._photos = []
        self.faces = installed_faces()
        self._build()
        values = [str(g) for g in self.game_folders if (g / gf.EXE_NAME).is_file() or settings_path(g).is_file()]
        self.game_box.configure(values=values)
        if values:
            self.game_var.set(values[0])
        self.folder_changed()
        if hold is not None:
            hold(self.window)

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Modded game folder:").grid(row=0, column=0, sticky="w")
        self.game_box = ttk.Combobox(top, textvariable=self.game_var, width=70)
        self.game_box.grid(row=0, column=1, sticky="w", padx=4)
        self.game_box.bind("<<ComboboxSelected>>", lambda _e: self.folder_changed())
        self.game_box.bind("<Return>", lambda _e: self.folder_changed())
        ttk.Button(top, text="Choose...", command=self.choose_folder).grid(row=0, column=2)
        ttk.Button(top, text="?", width=2, command=self._help).grid(row=0, column=3, padx=(12, 0))
        ttk.Label(outer, textvariable=self.status_var, foreground="#245a9a", wraplength=860,
                  justify="left").pack(anchor="w", pady=(6, 0))
        middle = ttk.Frame(outer)
        middle.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(middle)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Installed fonts (search):").pack(anchor="w")
        entry = ttk.Entry(left, textvariable=self.search_var, width=34)
        entry.pack(anchor="w", fill="x")
        self.search_var.trace_add("write", lambda *_a: self.fill_faces())
        box = ttk.Frame(left)
        box.pack(fill="y", expand=True, pady=(4, 0))
        self.face_list = tk.Listbox(box, width=34, height=20, exportselection=False)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.face_list.yview)
        self.face_list.configure(yscrollcommand=sb.set)
        self.face_list.pack(side="left", fill="y")
        sb.pack(side="left", fill="y")
        self.face_list.bind("<<ListboxSelect>>", lambda _e: self.face_picked())
        ttk.Button(left, text="Choose a font file...", command=self.choose_file).pack(anchor="w", pady=(6, 0))
        ttk.Button(left, text="Segoe UI (the default)", command=lambda: self.set_face(DEFAULT_FACE)).pack(
            anchor="w", pady=(4, 0))
        right = ttk.Frame(middle)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        ttk.Label(right, text="How the game's four fonts will look (drawn as the game will draw them):").pack(
            anchor="w")
        self.canvas = tk.Canvas(right, background="#28407a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(4, 0))
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="Save", command=self.save).pack(side="right")
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right", padx=(0, 8))
        self.fill_faces()

    def fill_faces(self) -> None:
        term = self.search_var.get().strip().casefold()
        self.shown_faces = [f for f in self.faces if term in f.casefold()]
        self.face_list.delete(0, "end")
        for f in self.shown_faces:
            self.face_list.insert("end", f)

    def face_picked(self) -> None:
        picked = self.face_list.curselection()
        if picked:
            self.font_file = None
            self.set_face(self.shown_faces[picked[0]])

    def set_face(self, face: str, font_file: Path | None = None) -> None:
        self.face = face
        self.font_file = font_file
        self.refresh()

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.window, title="Choose the modded Virtual Families folder")
        if folder:
            self.game_var.set(folder)
            self.folder_changed()

    def choose_file(self, path: str | None = None) -> None:
        if path is None:
            path = filedialog.askopenfilename(parent=self.window, title="Choose a font file", filetypes=FONT_FILES)
            if not path:
                return
        try:
            family = gdi.font_file_family(Path(path).read_bytes())
        except OSError as exc:
            self._message("error", str(exc))
            return
        if not family:
            self._message("error", f"{Path(path).name} is not a font file Windows can use.")
            return
        self.set_face(family, Path(path))

    def folder(self) -> Path | None:
        text = self.game_var.get().strip()
        return Path(text) if text else None

    def folder_changed(self) -> None:
        folder = self.folder()
        if folder is None:
            self.status_var.set("Choose the modded game folder (the one the patcher made).")
            return
        face, file_name = read_choice(folder)
        font_file = folder / patcher.PATCHER_FOLDER / FONT_FOLDER / file_name if file_name else None
        on = is_on(folder)
        self.status_var.set(
            ("Use Unicode Font is on in this folder. " if on else
             "Use Unicode Font is off in this folder: tick it on the Patches tab and patch, or the game keeps its "
             "own letters. ") + f"Chosen now: {face}" + (f" (from {file_name})" if file_name else "") + ".")
        self.set_face(face, font_file if font_file and font_file.is_file() else None)

    def refresh(self) -> None:
        self.canvas.delete("all")
        self._photos = []
        folder = self.folder()
        if folder is None or not (folder / gf.EXE_NAME).is_file():
            return
        try:
            rows = preview(folder, self.face, self.font_file)
        except (gf.FontError, OSError) as exc:
            self.status_var.set(str(exc))
            return
        y = 8
        for label, picture in rows:
            self.canvas.create_text(8, y, text=label, anchor="nw", fill="#ffffff")
            y += 18
            photo = picture.photo(tk, self.window)
            self._photos.append(photo)
            self.canvas.create_image(8, y, image=photo, anchor="nw")
            y += picture.height + 12

    def save(self) -> Path | None:
        folder = self.folder()
        if folder is None:
            self._message("error", "Choose the modded game folder first.")
            return None
        try:
            path = write_choice(folder, self.face, self.font_file)
        except (FontChoiceError, OSError) as exc:
            self._message("error", str(exc))
            return None
        self.status_var.set(f"Saved: the game uses {self.face} from its next start.")
        return path

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
