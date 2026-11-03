"""The Translations window (Tools tab): choose the game's language, make a translation in a built-in
editor, add one you were sent (button or drag and drop), export it, and share it on GitHub.

The work is in vf1_translations.py (files, the choice, sharing), translation_format.py (the format) and
vf1_translation_strings.py (the game's lines); the game side is vf1tr.dll. Ported from the Fish and Plant
Tycoon Fix Patcher (src/translations_window.py). Nothing here asks for, stores or sends an email address:
the credit name is typed by the player each time, never filled in from anywhere.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser

import translation_format as tfmt
import vf1_translation_strings as tstr
import vf1_translations as tr

TITLE = "Translations"
GAME = "vf1"
GAMES = tfmt.GAME_TITLES
ENGLISH = tfmt.ENGLISH_ORIGINAL
OTHER_LANGUAGE = "Other language..."
AUTOSAVE_MS = 800

HELP = (
    "Translations",
    [
        "Play Virtual Families in another language, or make a translation yourself. Patch the game with the "
        "\"Translations\" setting on (it is on by default), then choose the language here: it applies from the "
        "next game start, without patching again. \"English (original)\" changes nothing.",
        "Make a translation: choose a language and press Make a translation... The patcher writes a file with "
        "every English line of the game, and opens it in the built-in editor: "
        "the English on the left, your translation on the right, search, \"show untranslated only\", how much "
        "is done, and a preview in the game's own font that warns when a line is too long. Placeholders such "
        "as %d and {name} must stay; the editor shows them in colour and says when one is missing. It "
        "saves by itself. The file is plain UTF-8 text, so Notepad or a spreadsheet (as tab-separated text) "
        "work too.",
        "People: in a line the game fills with a name, {he/she} is the person's sex; write it in your "
        "language, e.g. {il/elle}, or {name: m=prêt | f=prête}. Numbers: {award: one=pièce | other=pièces} "
        "(the game shows its other form). docs/translations.md explains everything.",
        "Add translation file... (or drag a .txt file onto this window) checks a file you were sent and adds "
        "it to the list.",
        "The list takes several at once: click one, Ctrl+click to add or remove one, Shift+click for a range, "
        "Ctrl+A or Select All for everything. Selecting never changes the game's language: that is only "
        "\"Language in the game\" at the top.",
        "Export... saves a copy of each selected translation (one file each). Delete... moves the selected "
        "files to the Windows Recycle Bin, after one Yes/No (No does nothing), so you can restore them from "
        "there. \"English (original)\" is part of the game and is never deleted. A translation that came with "
        "the patcher comes back with the next patcher update. Deleting the language the game uses puts the "
        "game back in English from its next start, as choosing English does.",
        "After a patcher update, new lines appear untranslated in the editor and your translation keeps "
        "working; a line whose English changed shows the new English until you translate it again.",
        tr.SHARE_INVITE + " " + tr.SHARE_HOW + " You need a free GitHub account (" + tr.SIGNUP_URL + "). "
        + tfmt.EMAIL_MESSAGE,
    ],
)


def _one_line(text: str) -> str:
    return text.replace("\n", " ⏎ ").replace("\t", " ")


# --------------------------------------------------------------------------- drag and drop


class FileDrop:
    """Windows drag and drop of files onto a Tk window (WM_DROPFILES): DragAcceptFiles on its frame,
    its window procedure subclassed through ctypes; each dropped path goes to `handler`, the same one
    the Add button uses. On any failure the window simply has the button only (`active` is False)."""

    WM_DROPFILES = 0x0233
    GWLP_WNDPROC = -4

    def __init__(self, window: tk.Misc, handler) -> None:
        self.window = window
        self.handler = handler
        self.active = False
        self._old = None
        self._proc = None
        try:
            self._install()
        except Exception:
            self.active = False

    def _install(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.window.update_idletasks()
        hwnd = int(self.window.wm_frame(), 16)
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

        def proc(h, message, wparam, lparam):
            if message == self.WM_DROPFILES:
                paths = []
                try:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    for index in range(count):
                        size = shell32.DragQueryFileW(wparam, index, None, 0) + 1
                        buffer = ctypes.create_unicode_buffer(size)
                        shell32.DragQueryFileW(wparam, index, buffer, size)
                        paths.append(buffer.value)
                finally:
                    shell32.DragFinish(wparam)
                if paths:
                    self.window.after(0, lambda: self.handler([Path(p) for p in paths]))
                return 0
            return user32.CallWindowProcW(self._old, h, message, wparam, lparam)

        self._proc = WNDPROC(proc)
        self._user32, self._hwnd = user32, hwnd
        old = user32.SetWindowLongPtrW(hwnd, self.GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p))
        if not old:
            raise OSError("SetWindowLongPtrW failed")
        self._old = old
        # A patcher run as administrator still takes drops from Explorer.
        try:
            user32.ChangeWindowMessageFilterEx(hwnd, self.WM_DROPFILES, 1, None)
            user32.ChangeWindowMessageFilterEx(hwnd, 0x004A, 1, None)
            user32.ChangeWindowMessageFilterEx(hwnd, 0x0049, 1, None)
        except Exception:
            pass
        shell32.DragAcceptFiles(hwnd, True)
        self.active = True

    def remove(self) -> None:
        if self.active and self._old:
            try:
                self._user32.SetWindowLongPtrW(self._hwnd, self.GWLP_WNDPROC, self._old)
            except Exception:
                pass
        self.active = False


# --------------------------------------------------------------------------- the window


class TranslationsWindow:
    def __init__(self, master, game: str | None, folders: dict[str, list], folder: Path | None = None,
                 choices_path: Path | None = None) -> None:
        self.master = master
        self.folders = {g: [str(f) for f in v if f] for g, v in folders.items()}
        self.folder = folder or tr.TRANSLATIONS_DIR
        self.choices_path = choices_path
        self.entries_cache: dict[str, list[tfmt.Entry]] = {}
        self.items: list[tr.Installed] = []
        self.editors: list[TranslationEditor] = []

        win = self.window = tk.Toplevel(master)
        win.title(TITLE)
        win.geometry("760x620")
        win.minsize(640, 520)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)

        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.game_var = tk.StringVar(master=win, value=GAMES[GAME])
        ttk.Label(row, text="Virtual Families 1", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(row, text="?", width=2, command=self.show_guide).pack(side="right")

        group = ttk.LabelFrame(frame, text="Language in the game", padding=10)
        group.pack(fill="x", pady=(10, 0))
        self.language_var = tk.StringVar(master=win, value=ENGLISH)
        self.language_box = ttk.Combobox(group, textvariable=self.language_var, state="readonly", width=48)
        self.language_box.pack(anchor="w")
        self.language_box.bind("<<ComboboxSelected>>", lambda _e: self.choose())
        self.choice_status = tk.StringVar(master=win, value="")
        ttk.Label(group, textvariable=self.choice_status, wraplength=700, foreground="#245a9a").pack(anchor="w", pady=(4, 0))

        group = ttk.LabelFrame(frame, text="Make a translation", padding=10)
        group.pack(fill="x", pady=(10, 0))
        names = [name for name, _code in tr.LANGUAGES] + [OTHER_LANGUAGE]
        self.new_language = tk.StringVar(master=win, value=names[0])
        ttk.Combobox(group, textvariable=self.new_language, values=names, state="readonly", width=28).pack(side="left")
        ttk.Button(group, text="Make a translation...", command=self.make).pack(side="left", padx=(8, 0))

        group = ttk.LabelFrame(frame, text="Translations in the patcher", padding=10)
        group.pack(fill="both", expand=True, pady=(10, 0))
        # Several at once: click, Ctrl+click, Shift+click (Tk's "extended" mode), Ctrl+A and Select All.
        # Selecting here never changes the game's language; that is only the box above.
        self.listbox = tk.Listbox(group, height=7, activestyle="none", selectmode="extended", exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.edit())
        for sequence in ("<Control-a>", "<Control-A>", "<<SelectAll>>"):
            self.listbox.bind(sequence, self._select_all_key)
            win.bind(sequence, self._select_all_key)
        ttk.Label(group, text="Click to select; Ctrl+click or Shift+click to select more; Ctrl+A or Select All for "
                              "everything. The language the game uses is chosen above, under \"Language in the game\".",
                  wraplength=700, foreground="#666666").pack(anchor="w", pady=(4, 0))
        buttons = ttk.Frame(group)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Add translation file...", command=self.add_dialog).pack(side="left")
        ttk.Button(buttons, text="Edit...", command=self.edit).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Check", command=self.check).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Export...", command=self.export).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Open folder", command=self.open_folder).pack(side="left", padx=(8, 0))
        buttons = ttk.Frame(group)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Select All", command=self.select_all).pack(side="left")
        ttk.Button(buttons, text="Delete...", command=self.delete).pack(side="left", padx=(8, 0))
        self.drop_hint = tk.StringVar(master=win, value="")
        ttk.Label(group, textvariable=self.drop_hint, foreground="#666666").pack(anchor="w", pady=(4, 0))

        group = ttk.LabelFrame(frame, text="Share", padding=10)
        group.pack(fill="x", pady=(10, 0))
        ttk.Label(group, text=tr.SHARE_INVITE, wraplength=700).pack(anchor="w")
        ttk.Label(group, text=tr.SHARE_HOW, wraplength=700).pack(anchor="w", pady=(2, 6))
        share_row = ttk.Frame(group)
        share_row.pack(anchor="w")
        ttk.Button(share_row, text="Share on GitHub...", command=self.share).pack(side="left")
        ttk.Button(share_row, text="?", width=2, command=self.show_guide).pack(side="left", padx=(4, 0))

        ttk.Button(frame, text="Close", command=self.close).pack(anchor="e", pady=(10, 0))
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda _e: self.close())

        self.drop = FileDrop(win, self.add_files)
        self.drop_hint.set("Or drag a translation file (.txt) onto this window." if self.drop.active else "")
        self.refresh()

    # ---------------------------------------------------------------- state
    @property
    def game(self) -> str:
        return GAME

    def refresh(self) -> None:
        game = self.game
        self.items = tr.installed(game, self.folder)
        labels = [ENGLISH] + [i.label + ("  (came with the patcher)" if i.shipped else "") for i in self.items]
        self.language_box.configure(values=labels)
        chosen = tr.chosen_path(game, tr.load_choices(self.choices_path), self.folder)
        index = next((n + 1 for n, i in enumerate(self.items) if chosen and i.path.resolve() == chosen.resolve()), 0)
        self.language_var.set(labels[index])
        self.listbox.delete(0, "end")
        self.listbox.insert("end", f"{ENGLISH}   (part of the game)")
        for item in self.items:
            self.listbox.insert("end", f"{item.label}   [{item.path.name}]" + ("   (came with the patcher)" if item.shipped else ""))
        copies = tr.game_copies(game, self.game_folders(game))
        if copies:
            self.choice_status.set(f"Applies from the next game start ({len(copies)} copy/copies of {GAMES[game]} "
                                   "with the Translations setting).")
        else:
            self.choice_status.set(f"No modded copy of {GAMES[game]} with the Translations setting was found: "
                                   "patch the game with it on, then choose the language here.")

    def game_folders(self, game: str) -> list[str]:
        return self.folders.get(game, [])

    def selected_items(self) -> list[tr.Installed]:
        """The selected translations, in list order (row 0 is "English (original)", not a file)."""
        return [self.items[n - 1] for n in self.listbox.curselection() if 0 < n <= len(self.items)]

    def english_selected(self) -> bool:
        return 0 in self.listbox.curselection()

    def selected(self) -> tr.Installed | None:
        """The one translation Edit, Check and Share work on: the only one selected, or the only one there is."""
        items = self.selected_items()
        if len(items) == 1:
            return items[0]
        if not self.listbox.curselection() and len(self.items) == 1:
            return self.items[0]
        return None

    def select_all(self) -> None:
        self.listbox.selection_set(0, "end")

    def _select_all_key(self, _event=None) -> str:
        self.select_all()
        return "break"

    # ---------------------------------------------------------------- choosing
    def choose(self) -> list[Path]:
        game = self.game
        labels = list(self.language_box.cget("values"))
        index = labels.index(self.language_var.get()) if self.language_var.get() in labels else 0
        path = self.items[index - 1].path if index > 0 else None
        written = tr.apply_choice(game, path, self.game_folders(game), self.choices_path, self.folder)
        language = self.items[index - 1].language if index > 0 else ENGLISH
        if written:
            self.choice_status.set(f"{GAMES[game]} will be in {language} from its next start "
                                   f"({len(written)} copy/copies updated). No patching needed.")
        else:
            self.choice_status.set(f"Remembered: {language}. No copy of {GAMES[game]} with the Translations "
                                   "setting was found yet; the next patch uses it.")
        return written

    # ---------------------------------------------------------------- the English lines
    def entries(self, game: str, ask: bool = True) -> list[tfmt.Entry] | None:
        if game in self.entries_cache:
            return self.entries_cache[game]
        candidates = list(self.game_folders(game))
        exe = tstr.find_vanilla_exe(candidates)
        if exe is None and ask:
            messagebox.showinfo(TITLE, f"Choose your original (unpatched) {GAMES[game]} folder: the patcher reads "
                                       "the game's English lines from it (it never changes it).", parent=self.window)
            folder = filedialog.askdirectory(parent=self.window, title=f"The original {GAMES[game]} folder")
            if folder:
                exe = tstr.find_vanilla_exe([folder])
                if exe is None:
                    messagebox.showerror(TITLE, f"That folder has no {tstr.EXE_NAMES[0]}.", parent=self.window)
        if exe is None:
            return None
        self.entries_cache[game] = tstr.entries_for(exe.read_bytes())
        return self.entries_cache[game]

    # ---------------------------------------------------------------- making and editing
    def make(self) -> Path | None:
        game = self.game
        name = self.new_language.get()
        code = dict(tr.LANGUAGES).get(name, "")
        if name == OTHER_LANGUAGE:
            name = (simpledialog.askstring(TITLE, "The language's own name (as its speakers write it):",
                                           parent=self.window) or "").strip()
            if not name:
                return None
            code = (simpledialog.askstring(TITLE, "Its language code (e.g. fr, tr, ja, zh-Hans); leave empty "
                                                  "if you do not know it:", parent=self.window) or "").strip()
        if tfmt.contains_email(name) or tfmt.contains_email(code):
            messagebox.showerror(TITLE, tfmt.EMAIL_MESSAGE, parent=self.window)
            return None
        entries = self.entries(game)
        if entries is None:
            return None
        path = self.folder / tfmt.file_name(GAMES[game], name)
        if not path.exists():
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tfmt.to_bytes(tfmt.new_file(game, entries, name, code or "und")))
        self.refresh()
        self.open_editor(path)
        return path

    def edit(self) -> None:
        item = self.selected()
        if item is None:
            messagebox.showinfo(TITLE, "Choose one translation in the list first.", parent=self.window)
            return
        if item.shipped and not messagebox.askyesno(
                TITLE, "This translation came with the patcher. Edit a copy of it as your own?", parent=self.window):
            return
        path = item.path
        if item.shipped:
            path = self.folder / item.path.name
            if not path.exists():
                path.write_bytes(item.path.read_bytes())
            self.refresh()
        self.open_editor(path)

    def open_editor(self, path: Path) -> TranslationEditor:
        game = self.game
        editor = TranslationEditor(self.window, game, path, self.entries(game, ask=False),
                                   self.game_folders(game), on_save=self._saved)
        self.editors.append(editor)
        return editor

    def _saved(self, path: Path) -> None:
        """A file the game uses was edited: its copies in the game folders follow."""
        game = self.game
        chosen = tr.chosen_path(game, tr.load_choices(self.choices_path), self.folder)
        if chosen is not None and chosen.resolve() == path.resolve():
            info = tr.read_info(path, game)
            for copy in tr.game_copies(game, self.game_folders(game)):
                tr.write_choice(copy, game, path, info.language if info else "")

    # ---------------------------------------------------------------- adding, checking, exporting
    def add_dialog(self) -> None:
        names = filedialog.askopenfilenames(parent=self.window, title="Add translation file",
                                            filetypes=(("Translation files", "*.txt"), ("All files", "*.*")))
        if names:
            self.add_files([Path(n) for n in names])

    def add_files(self, paths: list[Path]) -> list[Path]:
        """Check each file and add it (the Add button and drag and drop both come here)."""
        added: list[Path] = []
        messages: list[str] = []
        for path in paths:
            game = self._game_of(path)
            if game is None:
                messages.append(f"{path.name}: not a translation for Virtual Families (format 1).")
                continue
            try:
                target, report = tr.install_file(path, game, self.entries(game, ask=False), self.folder)
            except tr.TranslationProblem as exc:
                messages.append(f"{path.name}: {exc}")
                continue
            added.append(target)
            messages.append(f"{path.name}: added for {GAMES[game]} as {target.name}.\n{report.summary()}")
        if paths:
            self.refresh()
            messagebox.showinfo(TITLE, "\n\n".join(messages)[:6000], parent=self.window)
        return added

    @staticmethod
    def _game_of(path: Path) -> str | None:
        try:
            data = path.read_bytes() if path.stat().st_size <= tr.MAX_FILE else b""
        except OSError:
            return None
        parsed = tfmt.parse_bytes(data)
        title = parsed.game.strip()
        return next((g for g, t in GAMES.items() if t == title), None)

    def check(self) -> str:
        item = self.selected()
        if item is None:
            messagebox.showinfo(TITLE, "Choose one translation in the list first.", parent=self.window)
            return ""
        parsed = tfmt.parse_bytes(item.path.read_bytes(), self.game)
        summary = tfmt.validate(parsed, self.entries(self.game, ask=False)).summary()
        messagebox.showinfo(TITLE, summary[:6000], parent=self.window)
        return summary

    def export(self) -> list[Path]:
        """Export...: a copy of each selected translation, one file each. One selected: saved where and as
        the player says; several: into a folder the player chooses, each under its own name."""
        items = self.selected_items()
        if not items and not self.listbox.curselection() and len(self.items) == 1:
            items = list(self.items)
        if not items:
            messagebox.showinfo(TITLE, "Choose the translations to export in the list first (\"English (original)\" "
                                       "is part of the game, not a file).", parent=self.window)
            return []
        if len(items) == 1:
            name = filedialog.asksaveasfilename(parent=self.window, title="Export translation",
                                                initialfile=items[0].path.name, defaultextension=".txt",
                                                filetypes=(("Translation files", "*.txt"),))
            return [tr.export_file(items[0].path, Path(name))] if name else []
        folder = filedialog.askdirectory(parent=self.window, title=f"Export {len(items)} translations to")
        if not folder:
            return []
        targets: list[Path] = []
        for item in items:
            target = Path(folder) / item.path.name
            number = 2
            while target in targets:                # a shipped file and the player's copy share a name
                target = Path(folder) / f"{item.path.stem} ({number}){item.path.suffix}"
                number += 1
            targets.append(target)
        existing = [t for t in targets if t.exists()]
        if existing and not messagebox.askyesno(
                TITLE, "These files are already there:\n\n" + "\n".join(t.name for t in existing)
                + "\n\nReplace them? (No skips them.)", default="no", parent=self.window):
            pairs = [(i, t) for i, t in zip(items, targets) if t not in existing]
        else:
            pairs = list(zip(items, targets))
        written: list[Path] = []
        problems: list[str] = []
        for item, target in pairs:
            try:
                written.append(tr.export_file(item.path, target))
            except OSError as exc:
                problems.append(f"{item.path.name}: {exc.strerror or exc}")
        message = f"Exported {len(written)} translation(s) to {folder}."
        if problems:
            message += "\n\nNot exported:\n" + "\n".join(problems)
        messagebox.showinfo(TITLE, message, parent=self.window)
        return written

    # ---------------------------------------------------------------- deleting
    def delete_prompt(self, items: list[tr.Installed], english: bool, chosen: Path | None) -> str:
        """The one Yes/No question Delete... asks: every file, and what happens."""
        lines = [f"Delete {'this translation' if len(items) == 1 else f'these {len(items)} translations'}? "
                 "The files go to the Windows Recycle Bin, so you can restore them from there.", ""]
        for item in items:
            lines.append(f"    {item.label}   [{item.path.name}]" + ("   (came with the patcher)" if item.shipped else ""))
        notes: list[str] = []
        if any(item.shipped for item in items):
            notes.append("A translation that came with the patcher comes back with the next patcher update.")
        active = next((i for i in items if chosen is not None and i.path.resolve() == chosen.resolve()), None)
        if active is not None:
            notes.append(f"{active.label} is the language in the game now: the game goes back to {ENGLISH} from "
                         "its next start.")
        if english:
            notes.append(f"{ENGLISH} is part of the game and cannot be deleted: it is skipped.")
        return "\n".join(lines + ([""] + notes if notes else []))

    def delete(self) -> list[Path]:
        """Delete...: the selected translations to the Recycle Bin after one Yes/No (No by default; No does
        nothing). English (original) is skipped. When the Recycle Bin fails, nothing is deleted. Deleting the
        language the game uses chooses English, exactly as choosing it in the box does."""
        items = self.selected_items()
        english = self.english_selected()
        if not items:
            messagebox.showinfo(TITLE, f"{ENGLISH} is part of the game and cannot be deleted." if english else
                                "Choose the translations to delete in the list first.", parent=self.window)
            return []
        game = self.game
        chosen = tr.chosen_path(game, tr.load_choices(self.choices_path), self.folder)
        if not messagebox.askyesno("Delete translations", self.delete_prompt(items, english, chosen), default="no",
                                   icon="warning", parent=self.window):
            return []
        paths = [item.path for item in items]
        try:
            tr.recycle(paths)
        except OSError as exc:
            messagebox.showerror(TITLE, f"Nothing was deleted: {exc}", parent=self.window)
            self.refresh()
            return []
        gone = {p.resolve() for p in paths}
        for editor in [e for e in self.editors if e.path.resolve() in gone]:
            editor.discard()                        # an open editor must not save the file back
            self.editors.remove(editor)
        self.refresh()
        if chosen is not None and chosen.resolve() in gone:
            self.language_var.set(ENGLISH)
            self.choose()
        return paths

    def open_folder(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["explorer", str(self.folder)])
        except OSError:
            pass

    # ---------------------------------------------------------------- sharing
    def share(self) -> str | None:
        """Share on GitHub...: the owner's Yes/No first (No does nothing), the credit name typed by the
        player, then the file exported, shown in its folder, and GitHub's form opened."""
        if not messagebox.askyesno("Share on GitHub", tr.SHARE_CONFIRMATION, default="no", icon="warning",
                                   parent=self.window):
            return None
        item = self.selected()
        if item is None:
            messagebox.showinfo(TITLE, "Choose your translation in the list first, then press Share on GitHub... "
                                       "again.", parent=self.window)
            return None
        name = CreditDialog(self.window).result
        if name is None:
            return None
        try:
            name = tr.check_credit_name(name)
        except tr.TranslationProblem as exc:
            messagebox.showerror(TITLE, str(exc), parent=self.window)
            return None
        game = self.game
        parsed = tfmt.parse_bytes(item.path.read_bytes(), game)
        report = tfmt.validate(parsed, self.entries(game, ask=False))
        if not report.usable:
            messagebox.showerror(TITLE, "This file cannot be shared:\n\n" + report.summary()[:4000], parent=self.window)
            return None
        shared = self.folder / "Shared"
        shared.mkdir(parents=True, exist_ok=True)
        target = shared / item.path.name
        tr.export_file(item.path, target)
        tr.set_credit(target, name)
        url = tr.issue_url(game, item.language or item.path.stem.split(" - ", 1)[-1], report.coverage)
        self._show_in_folder(target)
        webbrowser.open(url)
        messagebox.showinfo(TITLE, f"{target.name} is ready in its folder (now open). On the GitHub page that "
                                   "opened, drag the file into the form and press Submit.", parent=self.window)
        return url

    @staticmethod
    def _show_in_folder(path: Path) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError:
            pass

    # ---------------------------------------------------------------- the rest
    def show_guide(self) -> tk.Toplevel:
        window = tk.Toplevel(self.window)
        window.title("How to use: Translations")
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=HELP[0], font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        for line in HELP[1]:
            ttk.Label(frame, text=line, wraplength=520, justify="left").pack(anchor="w", pady=(0, 6))
        link = tk.Label(frame, text="Create a GitHub account: " + tr.SIGNUP_URL, foreground="#0057c2", cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda _e: webbrowser.open(tr.SIGNUP_URL))
        ttk.Button(frame, text="Close", command=window.destroy).pack(anchor="e", pady=(8, 0))
        return window

    def close(self) -> None:
        for editor in self.editors:
            editor.save()
        self.drop.remove()
        self.window.destroy()


class CreditDialog:
    """The credit name: typed by the player, required, never filled in (not from git, Windows,
    GitHub or a save). result is the typed text, or None when cancelled."""

    test_answer = None          # tests only: a function that types into the dialog instead of the player

    def __init__(self, master) -> None:
        self.result: str | None = None
        win = self.window = tk.Toplevel(master)
        win.title("Credit name")
        win.transient(master)
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Credit name (required):", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.var = tk.StringVar(master=win, value="")
        self.entry = ttk.Entry(frame, textvariable=self.var, width=40)
        self.entry.pack(anchor="w", pady=(4, 4))
        ttk.Label(frame, text=tr.CREDIT_HINT, wraplength=420, foreground="#a33").pack(anchor="w")
        self.error = tk.StringVar(master=win, value="")
        ttk.Label(frame, textvariable=self.error, foreground="#c00", wraplength=420).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(anchor="e", pady=(8, 0))
        ttk.Button(row, text="OK", command=self.ok).pack(side="left")
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=(8, 0))
        win.bind("<Return>", lambda _e: self.ok())
        win.bind("<Escape>", lambda _e: win.destroy())
        self.entry.focus_set()
        if CreditDialog.test_answer is not None:
            CreditDialog.test_answer(self)
        else:
            win.grab_set()
            master.wait_window(win)

    def ok(self) -> None:
        try:
            self.result = tr.check_credit_name(self.var.get())
        except tr.TranslationProblem as exc:
            self.error.set(str(exc))
            return
        self.window.destroy()


# --------------------------------------------------------------------------- the editor

PLACEHOLDER_RE = re.compile(tfmt.CONVERSION_RE.pattern + r"|\{[^{}]*\}")
PREVIEW_COLOUR = 0xFFFFFFFF


class TranslationEditor:
    STATUS = {"new": "untranslated", "done": "translated", "error": "check it", "changed": "English changed",
              "old": "not in this version"}

    def __init__(self, master, game: str, path: Path, entries: list[tfmt.Entry] | None, folders: list[str],
                 on_save=None) -> None:
        self.game, self.path, self.on_save = game, Path(path), on_save
        self.entries = {e.key: e for e in (entries or [])}
        self.dirty = False
        self._after = None
        self.fonts = None
        self.font_folder = None
        self.file = tfmt.parse_bytes(self.path.read_bytes(), game)
        self.update_note = ""
        if entries and not self.file.fatal:
            report = tfmt.update_to_inventory(self.file, entries)
            if report.added or report.changed:
                self.update_note = (f"{len(report.added)} new line(s) and {len(report.changed)} with changed English "
                                    "since this file was made are marked untranslated.")
                self.dirty = True
        self.bases = {tfmt.base_key(k) for k in self.entries}
        self.font_candidates = folders

        win = self.window = tk.Toplevel(master)
        win.title(f"Translation editor - {self.path.name}")
        win.geometry("1100x780")
        win.minsize(820, 560)
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        if self.file.fatal:
            ttk.Label(frame, text="This file cannot be edited here: " + self.file.fatal, foreground="#c00",
                      wraplength=900).pack(anchor="w")
            return

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Search:").pack(side="left")
        self.search = tk.StringVar(master=win, value="")
        entry = ttk.Entry(top, textvariable=self.search, width=30)
        entry.pack(side="left", padx=(4, 12))
        self.search.trace_add("write", lambda *_a: self.fill())
        self.untranslated_only = tk.BooleanVar(master=win, value=False)
        ttk.Checkbutton(top, text="Show untranslated only", variable=self.untranslated_only,
                        command=self.fill).pack(side="left")
        self.progress = tk.StringVar(master=win, value="")
        ttk.Label(top, textvariable=self.progress, font=("Segoe UI", 10, "bold")).pack(side="right")
        if self.update_note:
            ttk.Label(frame, text=self.update_note, foreground="#245a9a").pack(anchor="w")

        panes = ttk.PanedWindow(frame, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(6, 0))
        table = ttk.Frame(panes)
        self.tree = ttk.Treeview(table, columns=("status", "english", "translation"), show="headings",
                                 selectmode="browse")
        for column, text, width in (("status", "Status", 120), ("english", "English", 440),
                                    ("translation", "Translation", 440)):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width, stretch=column != "status")
        bar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.tag_configure("error", foreground="#c00")
        self.tree.tag_configure("changed", foreground="#a60")
        self.tree.tag_configure("old", foreground="#888")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_row())
        panes.add(table, weight=3)

        edit = ttk.Frame(panes)
        self.notes = tk.StringVar(master=win, value="")
        ttk.Label(edit, textvariable=self.notes, foreground="#555", wraplength=1000).pack(anchor="w")
        ttk.Label(edit, text="English:").pack(anchor="w")
        self.english_text = tk.Text(edit, height=4, wrap="word", background="#f3f3f3")
        self.english_text.pack(fill="x")
        ttk.Label(edit, text="Translation:").pack(anchor="w", pady=(4, 0))
        self.translation_text = tk.Text(edit, height=5, wrap="word", undo=True)
        self.translation_text.pack(fill="x")
        for widget in (self.english_text, self.translation_text):
            widget.tag_configure("placeholder", foreground="#0057c2", background="#e6efff")
        self.translation_text.bind("<KeyRelease>", lambda _e: self.changed())
        self.translation_text.bind("<<Paste>>", lambda _e: self.window.after(1, self.changed))
        tools = ttk.Frame(edit)
        tools.pack(fill="x", pady=(4, 0))
        ttk.Button(tools, text="Copy English", command=self.copy_english).pack(side="left")
        self.insert_row = ttk.Frame(tools)
        self.insert_row.pack(side="left", padx=(12, 0))
        self.message = tk.StringVar(master=win, value="")
        self.message_label = ttk.Label(edit, textvariable=self.message, wraplength=1000)
        self.message_label.pack(anchor="w", pady=(4, 0))
        self.preview_note = tk.StringVar(master=win, value="")
        ttk.Label(edit, textvariable=self.preview_note, foreground="#555").pack(anchor="w")
        self.preview = tk.Label(edit, background="#18284a")
        self.preview.pack(anchor="w", pady=(2, 0))
        panes.add(edit, weight=2)

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(6, 0))
        self.saved = tk.StringVar(master=win, value="Saved automatically.")
        ttk.Label(bottom, textvariable=self.saved, foreground="#555").pack(side="left")
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", self.close)

        self.current: tfmt.Row | None = None
        self.fill()
        if self.dirty:
            self.save()

    # ---------------------------------------------------------------- rows
    def status(self, row: tfmt.Row) -> str:
        if self.entries and row.key not in self.entries:
            return "changed" if tfmt.base_key(row.key) in self.bases else "old"
        if not row.translation:
            return "new"
        errors, _w = tfmt.check_translation(row.english, row.translation, self.file.code)
        entry = self.entries.get(row.key)
        if errors or (entry and entry.max_length and tfmt.too_long(row.translation, entry.max_length, entry.wide)):
            return "error"
        return "done"

    def fill(self) -> None:
        if not hasattr(self, "tree"):
            return
        query = self.search.get().casefold()
        self.tree.delete(*self.tree.get_children())
        self.visible: dict[str, tfmt.Row] = {}
        for n, row in enumerate(self.file.rows):
            status = self.status(row)
            if self.untranslated_only.get() and status not in ("new", "error"):
                continue
            if query and query not in row.english.casefold() and query not in row.translation.casefold() \
                    and query not in row.key.casefold():
                continue
            iid = f"r{n}"
            self.visible[iid] = row
            self.tree.insert("", "end", iid=iid, values=(self.STATUS[status], _one_line(row.english),
                                                         _one_line(row.translation)), tags=(status,))
        self.update_progress()

    def update_progress(self) -> None:
        rows = [r for r in self.file.rows if not self.entries or r.key in self.entries]
        done = sum(1 for r in rows if self.status(r) == "done")
        percent = 100.0 * done / len(rows) if rows else 0.0
        self.progress.set(f"{done} of {len(rows)} lines translated ({percent:.0f}%)")

    def show_row(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.current = self.visible.get(selection[0])
        if self.current is None:
            return
        row = self.current
        entry = self.entries.get(row.key)
        notes = row.notes or (entry.notes if entry else "")
        self.notes.set(f"{row.key}   {notes}")
        for widget, text in ((self.english_text, row.english), (self.translation_text, row.translation)):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            self._mark(widget)
        self.english_text.configure(state="disabled")
        for child in self.insert_row.winfo_children():
            child.destroy()
        template = tfmt.parse_template(row.english)
        tokens = [c.text for c in template.conversions] + ["{" + v + "}" for v in sorted(template.variables)]
        for token in tokens:
            ttk.Button(self.insert_row, text=f"Insert {token}", command=lambda t=token: self.insert(t)).pack(side="left", padx=(0, 4))
        if template.variables or template.selects:
            ttk.Button(self.insert_row, text="Insert {il/elle}",
                       command=lambda: self.insert("{il/elle}")).pack(side="left", padx=(0, 4))
            ttk.Button(self.insert_row, text="Insert a person choice",
                       command=lambda: self.insert("{name: m=... | f=...}")).pack(side="left", padx=(0, 4))
        numbers = [n for n, c in enumerate(template.conversions, 1) if c.is_number]
        if numbers:
            snippet = f"{{%{numbers[0]}: one=... | other=...}}"
            ttk.Button(self.insert_row, text="Insert a number choice",
                       command=lambda s=snippet: self.insert(s)).pack(side="left", padx=(0, 4))
        self.validate()
        self.schedule_preview()

    def _mark(self, widget: tk.Text) -> None:
        widget.tag_remove("placeholder", "1.0", "end")
        text = widget.get("1.0", "end-1c")
        for match in PLACEHOLDER_RE.finditer(text):
            widget.tag_add("placeholder", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def insert(self, token: str) -> None:
        self.translation_text.insert("insert", token)
        self.changed()

    def copy_english(self) -> None:
        if self.current is None:
            return
        self.translation_text.delete("1.0", "end")
        self.translation_text.insert("1.0", self.current.english)
        self.changed()

    def changed(self) -> None:
        if self.current is None:
            return
        text = self.translation_text.get("1.0", "end-1c")
        if text == self.current.translation:
            return
        self.current.translation = text
        self._mark(self.translation_text)
        status = self.status(self.current)
        iid = next((i for i, r in self.visible.items() if r is self.current), None)
        if iid is not None:
            self.tree.item(iid, values=(self.STATUS[status], _one_line(self.current.english), _one_line(text)),
                           tags=(status,))
        self.validate()
        self.update_progress()
        self.dirty = True
        self.saved.set("Unsaved changes...")
        if self._after is not None:
            self.window.after_cancel(self._after)
        self._after = self.window.after(AUTOSAVE_MS, self.save)
        self.schedule_preview()

    def validate(self) -> list[str]:
        row = self.current
        if row is None:
            return []
        errors, warnings = tfmt.check_translation(row.english, row.translation, self.file.code)
        entry = self.entries.get(row.key)
        if row.translation and entry and entry.max_length and tfmt.too_long(row.translation, entry.max_length, entry.wide):
            errors.append(tfmt.too_long_message(entry.max_length))
        if tfmt.contains_email(row.translation):
            errors.append(tfmt.EMAIL_MESSAGE)
        if any(ord(c) > 0xFF and c not in "€‚ƒ„…†‡ˆ‰Š‹Œ"
               "Ž‘’“”•–—˜™š›œžŸ"
               for c in row.translation):
            warnings.append("some letters are outside Latin-1: the game shows them with the patcher's Unicode font "
                            "setting on, and as ? without it")
        if errors:
            self.message.set("This line will show English: " + "; ".join(errors))
            self.message_label.configure(foreground="#c00")
        elif warnings:
            self.message.set("Note: " + "; ".join(warnings))
            self.message_label.configure(foreground="#a60")
        else:
            self.message.set("OK" if row.translation else "Not translated yet (the game shows the English).")
            self.message_label.configure(foreground="#2a7a2a")
        return errors

    # ---------------------------------------------------------------- the preview
    def schedule_preview(self) -> None:
        self.window.after(150, self.render_preview)

    def render_preview(self) -> None:
        row = self.current
        if row is None or not self.window.winfo_exists():
            return
        try:
            font = self.game_font()
            if font is None:
                self.preview_note.set("Preview: no original Virtual Families folder with its fonts was found.")
                return
            sample = {"name": "Zoë", "name2": "Tom"}
            text = tfmt.evaluate(row.translation or row.english, sexes={"name": "f", "name2": "m"})
            for var, value in sample.items():
                text = text.replace("{" + var + "}", value)
            image = font.render(text, PREVIEW_COLOUR)
            english = font.render(tfmt.evaluate(row.english), PREVIEW_COLOUR)
            self._photo = image.photo(tk, self.window, max_side=1000)
            self.preview.configure(image=self._photo)
            note = f"Preview in the game's {font.name} (as said by Zoë)"
            if row.translation and image.width > english.width * 1.2 + 8:
                note += f" -- wider than the English ({image.width} vs {english.width} pixels): it may not fit its space."
            self.preview_note.set(note)
        except Exception as exc:  # the preview never stops the editor
            self.preview_note.set(f"Preview unavailable ({exc.__class__.__name__}).")

    def game_font(self):
        """The game's own SegoeUiBold18 (vf1_game_fonts, the in-game font of most text), from an original game
        folder the patcher knows; None when there is none."""
        if self.fonts is None:
            self.fonts = []
            import vf1_game_fonts as gf
            for folder in self.font_candidates:
                try:
                    if folder and (Path(folder) / gf.EXE_NAME).is_file():
                        self.fonts = [gf.Fonts(Path(folder)).font("SegoeUiBold18")]
                        break
                except Exception:
                    continue
        return self.fonts[0] if self.fonts else None

    # ---------------------------------------------------------------- saving
    def save(self) -> None:
        if self.file.fatal or not self.dirty:
            return
        self._after = None
        try:
            self.path.write_bytes(tfmt.to_bytes(self.file))
            self.dirty = False
            if hasattr(self, "saved"):
                self.saved.set(f"Saved {self.path.name}.")
            if self.on_save:
                self.on_save(self.path)
        except OSError as exc:
            if hasattr(self, "saved"):
                self.saved.set(f"Could not save: {exc.strerror or exc}")

    def close(self) -> None:
        self.save()
        self.window.destroy()

    def discard(self) -> None:
        """Its file was deleted: close without saving (saving would bring the file back)."""
        self.dirty = False
        if self._after is not None:
            try:
                self.window.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self.window.winfo_exists():
            self.window.destroy()


def open_window(master, folders: list) -> TranslationsWindow:
    """The window, for the game folders the patcher knows (the original and the modded copies)."""
    return TranslationsWindow(master, GAME, {GAME: list(folders)})
