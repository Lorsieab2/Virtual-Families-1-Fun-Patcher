#!/usr/bin/env python3
"""Virtual Families 1 Patcher: a small window around vf1_patcher.apply().

Pick your Virtual Families folder and where the patched copy should go.
Your game folder is only read; the patched game is a separate folder.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vf1_patcher  # noqa: E402

TITLE = "Virtual Families 1 Patcher"
MODDED_EXE = "Virtual Families - Modded.exe"
DLL = Path(__file__).resolve().parent / vf1_patcher.DLL_NAME


def guess_game_dir() -> str:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            for name in ("Virtual Families", r"Last Day of Work\Virtual Families"):
                p = Path(base) / name
                if (p / vf1_patcher.VANILLA_EXE).is_file():
                    return str(p)
    return ""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.resizable(False, False)
        frame = ttk.Frame(self, padding=14)
        frame.grid()
        self.game = tk.StringVar(value=guess_game_dir())
        self.out = tk.StringVar()
        self.separate = tk.BooleanVar(value=True)
        self.game.trace_add("write", lambda *_: self.suggest_output())
        self.suggest_output()

        ttk.Label(frame, text="Your Virtual Families folder (the one with \"Virtual Families.exe\"):").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(frame, textvariable=self.game, width=70).grid(row=1, column=0, sticky="we")
        ttk.Button(frame, text="Browse...", command=self.pick_game).grid(row=1, column=1, padx=(6, 0))
        ttk.Label(frame, text="Put the patched game in this NEW folder:").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.out, width=70).grid(row=3, column=0, sticky="we")
        ttk.Button(frame, text="Browse...", command=self.pick_out).grid(row=3, column=1, padx=(6, 0))
        ttk.Checkbutton(frame, variable=self.separate,
                        text=f"Name it \"{MODDED_EXE}\" so it keeps its own saves (recommended)").grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(frame, foreground="#555", wraplength=520, justify="left",
                  text="Your game folder is never changed. Open the store in the patched game "
                       "and click the new Upgrades button.").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(frame, text="Patch", command=self.patch).grid(row=6, column=1, sticky="e", pady=(12, 0))

    def suggest_output(self):
        # The game usually lives under Program Files, where a new folder needs
        # administrator rights, so the default is in the user's own folder.
        self.out.set(str(Path.home() / "Games" / "Virtual Families - Modded"))

    def pick_game(self):
        d = filedialog.askdirectory(title="Your Virtual Families folder")
        if d:
            self.game.set(d)

    def pick_out(self):
        d = filedialog.askdirectory(title="Folder for the patched game")
        if d:
            self.out.set(d)

    def patch(self):
        game, out = Path(self.game.get().strip()), Path(self.out.get().strip())
        if not (game / vf1_patcher.VANILLA_EXE).is_file():
            messagebox.showerror(TITLE, f"\"{vf1_patcher.VANILLA_EXE}\" is not in that folder.")
            return
        if not DLL.is_file():
            messagebox.showerror(TITLE, f"{vf1_patcher.DLL_NAME} is missing next to this patcher.")
            return
        try:
            exe = vf1_patcher.apply(game, out, DLL)
            if self.separate.get():
                exe = exe.rename(exe.with_name(MODDED_EXE))
        except (vf1_patcher.PatchError, OSError) as e:
            messagebox.showerror(TITLE, str(e))
            return
        messagebox.showinfo(TITLE, f"Done!\n\nPlay the patched game with:\n{exe}")


if __name__ == "__main__":
    App().mainloop()
