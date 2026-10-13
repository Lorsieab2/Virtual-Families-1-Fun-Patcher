#!/usr/bin/env python3
"""Tkinter GUI for the Virtual Families 1 Patcher.

Ported from the Virtual Families 2 Restoration/Addition Patcher's window
(offline_vf2_patcher_gui.py): the same Patch Input, Patch Settings, Run Log
and action sections, the same buttons and wording, around vf1_patcher's
apply/restore commands.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from argparse import Namespace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vf1_patcher as patcher  # noqa: E402

APP_DISPLAY_NAME = "Virtual Families 1 Patcher"
PATCHER_RELEASES_URL = "https://github.com/Lorsieab2/Virtual-Families-1-Patcher/"
PATCHER_ICON_PNG = "patcher_icon.png"
PATCHER_ICON_ICO = "patcher_icon.ico"
LOCAL_SETTINGS_FILE = "patcher_local_settings.json"
PROJECT_CREATOR_MESSAGE = (
    'Created by Lorsieab2. This is a passion project dedicated to improving the '
    '"Virtual Families" experience!\n'
    'No copyright infringement intended! Please support the original game creators! :)'
)
SAVE_COMPATIBILITY_NOTE = "Vanilla Virtual Families saves are compatible with the modded version!"
AI_DISCLOSURE = (
    "Created with Claude AI (Claude Code). Applies a transparent JSON patch manifest to a vanilla "
    "Virtual Families install or an existing modded output folder."
)
SETTING_CATEGORIES = [
    ("main", "Main Patches", "#00802b"),
    ("optional", "Optional Patches", "#000000"),
]
SETTING_CATEGORY_LOOKUP = {key: (label, color) for key, label, color in SETTING_CATEGORIES}


def clean_path_text(value: str | None) -> str:
    return (value or "").strip().strip('"')


def optional_path(value: str | None) -> str | None:
    text = clean_path_text(value)
    return text or None


def required_path(value: str | None, label: str) -> str:
    text = clean_path_text(value)
    if not text:
        raise patcher.PatchError(f"{label} is required.")
    return text


def local_settings_path(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parent
    return root / LOCAL_SETTINGS_FILE


def load_saved_paths(settings_path: Path | None = None) -> dict[str, str]:
    path = settings_path or local_settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    saved: dict[str, str] = {}
    for key in ("vanilla_game_dir", "modded_output_parent_dir", "modded_output_dir"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            saved[key] = value.strip()
    return saved


def save_saved_paths(
    *,
    vanilla_game_dir: str | None = None,
    modded_output_parent_dir: str | None = None,
    modded_output_dir: str | None = None,
    settings_path: Path | None = None,
) -> None:
    path = settings_path or local_settings_path()
    data = load_saved_paths(path)
    vanilla = clean_path_text(vanilla_game_dir)
    parent = clean_path_text(modded_output_parent_dir)
    output = clean_path_text(modded_output_dir)
    if vanilla:
        data["vanilla_game_dir"] = vanilla
    if parent:
        data["modded_output_parent_dir"] = parent
    if output:
        data["modded_output_dir"] = output
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def guess_game_dir() -> str:
    """The usual install folders, for a first run with nothing saved."""
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            for name in ("Virtual Families", r"Last Day of Work\Virtual Families"):
                candidate = Path(base) / name
                if (candidate / patcher.VANILLA_EXE).is_file():
                    return str(candidate)
    return ""


def markup_segments(text: str) -> list[tuple[str, bool]]:
    """Return (text, bold) spans for a tiny **bold** markup subset."""
    spans: list[tuple[str, bool]] = []
    pos = 0
    bold = False
    for match in re.finditer(r"\*\*", text):
        if match.start() > pos:
            spans.append((text[pos:match.start()], bold))
        bold = not bold
        pos = match.end()
    if pos < len(text):
        spans.append((text[pos:], bold))
    return spans


def categorized_settings(
    settings: dict[str, patcher.PatchSetting],
) -> list[tuple[str, str, str, list[patcher.PatchSetting]]]:
    grouped: dict[str, list[patcher.PatchSetting]] = {key: [] for key, _label, _color in SETTING_CATEGORIES}
    grouped["other"] = []
    for setting in settings.values():
        category = (setting.category or "main").lower()
        if category not in grouped:
            category = "other"
        grouped[category].append(setting)
    rows: list[tuple[str, str, str, list[patcher.PatchSetting]]] = []
    for key, label, color in SETTING_CATEGORIES:
        if grouped[key]:
            rows.append((key, label, color, grouped[key]))
    if grouped["other"]:
        rows.append(("other", "Other Patches", "#000000", grouped["other"]))
    return rows


def setting_ids_for_category(settings: dict[str, patcher.PatchSetting], category: str) -> list[str]:
    normalized = category.lower()
    return [setting.id for setting in settings.values() if (setting.category or "main").lower() == normalized]


def manifest_version_label(manifest: dict[str, object]) -> str:
    value = manifest.get("version")
    return value.strip() if isinstance(value, str) and value.strip() else ""


def setting_description_text(setting: patcher.PatchSetting, settings: dict[str, patcher.PatchSetting],
                             prerequisites: frozenset[str]) -> str:
    """The grey line under a checkbox: id, default, description, then the bold dependency note."""
    state = "default on" if setting.default else "default off"
    details = f"{setting.id} - {state} - {setting.description}" if setting.description else f"{setting.id} - {state}"
    return details + patcher.requires_note(prerequisites, settings)


def estimate_wrapped_lines(text: str, pixel_width: int, measure_text: object) -> int:
    width = max(1, int(pixel_width))
    lines = 0
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            lines += 1
            continue
        line_width = 0
        tokens = re.findall(r"\S+\s*", paragraph)
        if not tokens:
            lines += 1
            continue
        for token in tokens:
            token_width = max(1, int(measure_text(token)))
            stripped_width = max(1, int(measure_text(token.strip() or token)))
            if line_width and line_width + token_width > width:
                lines += 1
                line_width = stripped_width
            else:
                line_width += token_width
            if line_width > width:
                extra_lines = max(0, math.ceil(line_width / width) - 1)
                lines += extra_lines
                line_width = line_width - (extra_lines * width)
        lines += 1
    return max(1, lines)


def build_apply_namespace(
    *,
    game_dir: str,
    manifest: str,
    backup_dir: str | None = None,
    log: str | None = None,
    output_dir: str | None = None,
    output_parent_dir: str | None = None,
    dry_run: bool = False,
    settings: dict[str, patcher.PatchSetting] | None = None,
    selected_settings: set[str] | None = None,
) -> Namespace:
    settings = settings or {}
    selected_settings = selected_settings or set()
    unknown = sorted(selected_settings - set(settings))
    if unknown:
        raise patcher.PatchError(f"Unknown selected setting(s): {', '.join(unknown)}")
    game = optional_path(game_dir)
    output = optional_path(output_dir)
    if not game and not output:
        raise patcher.PatchError(
            "Choose your vanilla Virtual Families folder, or an existing modded output folder to reconfigure.")
    return Namespace(
        game_dir=game,
        manifest=required_path(manifest, "Patch manifest"),
        output_dir=output,
        output_parent_dir=optional_path(output_parent_dir),
        backup_dir=optional_path(backup_dir),
        log=optional_path(log),
        dry_run=bool(dry_run),
        enable=sorted(selected_settings) or None,
        disable=None,
        enable_all=False,
        disable_all=True,
        exe_name=None,
        dll=None,
        progress_callback=None,
    )


def setting_closure_maps(settings: dict[str, patcher.PatchSetting]) -> dict[str, frozenset[str]]:
    """Transitive prerequisites for a loaded manifest (empty if the manifest is inconsistent)."""
    try:
        return patcher.setting_prerequisites(settings)
    except patcher.PatchError:
        return {}


def build_restore_namespace(*, backup_dir: str, game_dir: str | None = None, log: str | None = None) -> Namespace:
    return Namespace(
        backup_dir=required_path(backup_dir, "Backup directory"),
        game_dir=optional_path(game_dir),
        log=optional_path(log),
        force_game_dir=False,
    )


def restore_destination_text(backup_dir: str) -> str:
    """' (<folder>)' naming where a backup restores to, or '' if the backup cannot be read."""
    try:
        recorded = patcher.read_json(Path(backup_dir) / patcher.BACKUP_MANIFEST).get("game_dir")
    except (patcher.PatchError, OSError, ValueError, AttributeError):
        return ""
    return f" ({recorded})" if recorded else ""


def success_file_lines(summary: dict[str, object]) -> list[str]:
    """The Modified file log shown after a successful run."""
    lines = []
    for row in summary.get("written_files", []) or []:
        if isinstance(row, dict):
            lines.append(f"- {row.get('file_path')} ({row.get('action', 'written')})")
    for rel in summary.get("removed_files", []) or []:
        lines.append(f"- {rel} (removed)")
    for rel in summary.get("unchanged_files", []) or []:
        lines.append(f"- {rel} (already up to date)")
    copied = summary.get("vanilla_files_copied") or 0
    if copied:
        lines.append(f"- {copied} unchanged game file(s) copied from the vanilla folder")
    return lines or ["(none)"]


# How often the main thread pumps the event loop while a worker runs.
WAIT_POLL_SECONDS = 0.03
# How long to keep retrying the modal grab before giving up loudly.
GRAB_TIMEOUT_SECONDS = 2.0


class WaitWindow(tk.Toplevel):
    """A modal wait popup with a moving progress bar.

    Copying the game and patching runs on a worker thread; this keeps the
    window painting so Windows never relabels it "(Not Responding)".
    """

    def __init__(self, parent: tk.Misc, title: str, message: str, modal: bool = True) -> None:
        super().__init__(parent)
        self._modal = modal
        self.title(title)
        self.resizable(False, False)
        # The X does nothing on purpose: the work cannot be cancelled part way
        # without leaving a half-copied game folder behind.
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        frame = ttk.Frame(self, padding=28)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=message, justify="center").pack()
        self._bar = ttk.Progressbar(frame, mode="indeterminate", length=300)
        self._bar.pack(pady=(18, 0))
        self._bar.start(12)
        if modal:
            self.transient(parent)
        self._center(parent)
        if modal:
            self._take_grab()
        with contextlib.suppress(tk.TclError):
            self.update()

    def _center(self, parent: tk.Misc) -> None:
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        try:
            viewable = bool(parent.winfo_viewable())
        except tk.TclError:
            viewable = False
        if viewable:
            # Not clamped: on a monitor left of or above the primary one these
            # coordinates are legitimately negative.
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        else:
            x = max(0, (self.winfo_screenwidth() - width) // 2)
            y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"+{x}+{y}")

    def _take_grab(self) -> None:
        """Grab input, retrying until the window manager has mapped us.

        The grab is what stops a second click starting a second worker
        against the same output folder, so a failed grab raises.
        """
        deadline = time.monotonic() + GRAB_TIMEOUT_SECONDS
        while True:
            try:
                self.grab_set()
                return
            except tk.TclError:
                if time.monotonic() >= deadline:
                    raise
                with contextlib.suppress(tk.TclError):
                    self.update()
                time.sleep(WAIT_POLL_SECONDS)

    def close(self) -> None:
        with contextlib.suppress(tk.TclError):
            self._bar.stop()
        if self._modal:
            with contextlib.suppress(tk.TclError):
                self.grab_release()
        with contextlib.suppress(tk.TclError):
            self.destroy()


class VF1PatcherGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_DISPLAY_NAME)
        self.root.geometry("920x720")
        self.root.minsize(760, 560)

        self.game_dir_var = tk.StringVar()
        self.manifest_var = tk.StringVar()
        self.backup_dir_var = tk.StringVar()
        self.output_parent_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.log_path_var = tk.StringVar()
        self.restore_backup_var = tk.StringVar()
        self.restore_log_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Choose a vanilla Virtual Families folder, or choose an existing modded output folder, plus a patch manifest.")
        self.version_var = tk.StringVar(value="Version: not loaded")

        self.settings: dict[str, patcher.PatchSetting] = {}
        self.setting_vars: dict[str, tk.BooleanVar] = {}
        self.setting_prerequisites: dict[str, frozenset[str]] = {}
        self._syncing_settings = False
        self.description_widgets: list[tk.Text] = []
        self.loaded_manifest_path: str | None = None
        self.loaded_manifest_data: dict[str, object] | None = None
        self.last_auto_output_dir = ""
        self.busy_controls: list[tk.Widget] = []
        self.window_icon_image: tk.PhotoImage | None = None
        self.title_icon_image: tk.PhotoImage | None = None
        self._work_wait: WaitWindow | None = None
        self._work_wait_previous_close = None

        self._load_saved_paths()
        self._load_icons()
        self._build_styles()
        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _asset_path_candidates(self, name: str) -> list[Path]:
        script_dir = Path(__file__).resolve().parent
        return [script_dir / name, script_dir / "assets" / name]

    def _load_icons(self) -> None:
        for path in self._asset_path_candidates(PATCHER_ICON_ICO):
            if path.is_file():
                try:
                    self.root.iconbitmap(str(path))
                    break
                except tk.TclError:
                    pass
        for path in self._asset_path_candidates(PATCHER_ICON_PNG):
            if path.is_file():
                try:
                    self.window_icon_image = tk.PhotoImage(file=str(path))
                    self.root.iconphoto(True, self.window_icon_image)
                    factor = max(1, (max(self.window_icon_image.width(), self.window_icon_image.height()) + 55) // 56)
                    self.title_icon_image = self.window_icon_image.subsample(factor, factor)
                    break
                except tk.TclError:
                    pass

    def _load_saved_paths(self) -> None:
        saved = load_saved_paths()
        self.game_dir_var.set(saved.get("vanilla_game_dir") or guess_game_dir())
        if saved.get("modded_output_dir"):
            self.output_dir_var.set(saved["modded_output_dir"])
        if saved.get("modded_output_parent_dir"):
            self.output_parent_dir_var.set(saved["modded_output_parent_dir"])

    def _build_styles(self) -> None:
        style = ttk.Style()
        style.configure("Title.TLabel", font=("", 15, "bold"))
        style.configure("Section.TLabelframe.Label", font=("", 10, "bold"))
        style.configure("Muted.TLabel", foreground="#555555")
        style.configure("Status.TLabel", foreground="#333333")
        # Underlined, because a blue label with no underline reads as static text.
        link_font = tkfont.nametofont("TkDefaultFont").copy()
        link_font.configure(underline=True)
        self._link_font = link_font
        style.configure("Link.TLabel", foreground="#0645ad", font=link_font)
        style.configure("LinkHover.TLabel", foreground="#c5350b", font=link_font)

    def _build_layout(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.grid(row=0, column=0, sticky="nsew")
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(3, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        header = ttk.Frame(root_frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)
        if self.title_icon_image is not None:
            ttk.Label(header, image=self.title_icon_image).grid(row=0, column=0, rowspan=4, sticky="w", padx=(0, 10))
        ttk.Label(header, text=APP_DISPLAY_NAME, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, textvariable=self.version_var, style="Muted.TLabel").grid(row=0, column=2, sticky="e", padx=(12, 0))
        ttk.Label(header, text=PROJECT_CREATOR_MESSAGE, style="Muted.TLabel", justify="left",
                  wraplength=660).grid(row=1, column=1, sticky="w", pady=(2, 0))
        update_link = ttk.Label(header, text="Check for updates", style="Link.TLabel", cursor="hand2")
        update_link.grid(row=1, column=2, sticky="e", padx=(12, 0), pady=(2, 0))
        update_link.bind("<Button-1>", lambda _event: self._open_updates_url())
        update_link.bind("<Enter>", lambda _event: update_link.configure(style="LinkHover.TLabel"))
        update_link.bind("<Leave>", lambda _event: update_link.configure(style="Link.TLabel"))
        ttk.Label(header, text=SAVE_COMPATIBILITY_NOTE, style="Muted.TLabel", justify="left",
                  wraplength=660).grid(row=2, column=1, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Label(header, text=AI_DISCLOSURE, style="Muted.TLabel", justify="left",
                  wraplength=660).grid(row=3, column=1, columnspan=2, sticky="w", pady=(2, 0))

        self._build_file_section(root_frame).grid(row=1, column=0, sticky="ew")
        self._build_settings_section(root_frame).grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self._build_log_section(root_frame).grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self._build_action_section(root_frame).grid(row=4, column=0, sticky="ew", pady=(10, 0))

    def _build_file_section(self, parent: tk.Widget) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Patch Input", style="Section.TLabelframe", padding=10)
        frame.columnconfigure(1, weight=1)
        self._path_row(frame, 0, "Vanilla game folder (optional if reconfiguring an existing modded folder)", self.game_dir_var, self._browse_game_dir)
        self._path_row(frame, 1, "Patch manifest", self.manifest_var, self._browse_manifest)
        self._path_row(frame, 2, "Save modified folders under", self.output_parent_dir_var, self._browse_output_parent_dir, optional=True)
        self._path_row(frame, 3, "Modded output folder", self.output_dir_var, self._browse_output_dir, optional=True)
        self._path_row(frame, 4, "Backup folder", self.backup_dir_var, self._browse_backup_dir, optional=True)
        self._path_row(frame, 5, "Patch log", self.log_path_var, self._browse_log_path, optional=True)
        return frame

    def _build_settings_section(self, parent: tk.Widget) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Patch Settings", style="Section.TLabelframe", padding=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(4, weight=1)
        self._button(controls, "Load Manifest Settings", self.load_manifest_settings).grid(row=0, column=0, padx=(0, 6))
        self._button(controls, "Defaults", self.select_default_settings).grid(row=0, column=1, padx=(0, 6))
        self._button(controls, "Enable All", self.select_all_settings).grid(row=0, column=2, padx=(0, 6))
        self._button(controls, "Disable All", self.clear_all_settings).grid(row=0, column=3, padx=(0, 6))
        self._button(controls, "Enable All Main Patches", lambda: self.select_category_settings("main")).grid(row=1, column=0, padx=(0, 6), pady=(6, 0))
        self._button(controls, "Enable all Optional Content", lambda: self.select_category_settings("optional")).grid(row=1, column=1, padx=(0, 6), pady=(6, 0))

        outer = ttk.Frame(frame)
        outer.grid(row=1, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        self.settings_canvas = tk.Canvas(outer, height=170, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.settings_canvas.yview)
        self.settings_canvas.configure(yscrollcommand=scrollbar.set)
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.settings_inner = ttk.Frame(self.settings_canvas)
        self.settings_inner.columnconfigure(0, weight=1)
        self.settings_window = self.settings_canvas.create_window((0, 0), window=self.settings_inner, anchor="nw")
        self.settings_inner.bind(
            "<Configure>",
            lambda event: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")),
        )
        self.settings_canvas.bind("<Configure>", self._on_settings_canvas_configure)
        self._render_settings_placeholder("Load a manifest to see toggleable patch settings.")
        return frame

    def _build_log_section(self, parent: tk.Widget) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Run Log", style="Section.TLabelframe", padding=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(frame, height=11, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return frame

    def _build_action_section(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(3, weight=1)
        self._button(frame, "Dry Run (Validate Only)", lambda: self.start_apply(dry_run=True)).grid(row=0, column=0, padx=(0, 8))
        self._apply_button(frame, "Enable/Disable Patches", lambda: self.start_apply(dry_run=False)).grid(row=0, column=1, padx=(0, 8))
        ttk.Label(
            frame,
            text="Dry Run validates that the patcher's working. It does not actually change or write files.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        restore_frame = ttk.Frame(frame)
        restore_frame.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        restore_frame.columnconfigure(1, weight=1)
        ttk.Label(restore_frame, text="Restore backup").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(restore_frame, textvariable=self.restore_backup_var).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self._button(restore_frame, "Browse", self._browse_restore_backup).grid(row=0, column=2, padx=(0, 8))
        ttk.Label(restore_frame, text="Restore log").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(restore_frame, textvariable=self.restore_log_var).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(6, 0))
        self._button(restore_frame, "Save As", self._browse_restore_log).grid(row=1, column=2, padx=(0, 8), pady=(6, 0))
        self._button(restore_frame, "Restore Backup", self.start_restore).grid(row=0, column=3, rowspan=2, sticky="ns")

        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=3, sticky="ew", padx=(8, 0))
        return frame

    def _path_row(self, parent: ttk.LabelFrame, row: int, label: str, variable: tk.StringVar, command: object,
                  *, optional: bool = False) -> None:
        suffix = " (optional)" if optional else ""
        ttk.Label(parent, text=f"{label}{suffix}").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=3)
        self._button(parent, "Browse", command).grid(row=row, column=2, sticky="ew", pady=3)

    def _button(self, parent: tk.Widget, text: str, command: object) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        self.busy_controls.append(button)
        return button

    def _apply_button(self, parent: tk.Widget, text: str, command: object) -> tk.Button:
        button = tk.Button(parent, text=text, command=command, fg="#00802b", font=("", 10, "bold"), padx=12)
        self.busy_controls.append(button)
        return button

    def _open_updates_url(self) -> None:
        try:
            webbrowser.open(PATCHER_RELEASES_URL)
        except Exception as exc:
            self._set_error(f"Could not open update link: {exc}")

    def _browse_game_dir(self) -> None:
        path = filedialog.askdirectory(title="Select the vanilla Virtual Families game folder")
        if path:
            self.game_dir_var.set(path)
            self._auto_populate_output_dir()
            self._save_current_paths()

    def _browse_manifest(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a Virtual Families 1 patch manifest",
            filetypes=[("JSON manifests", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.manifest_var.set(path)
            self.load_manifest_settings()
            self._auto_populate_output_dir()
            self._save_current_paths()

    def _browse_backup_dir(self) -> None:
        path = filedialog.askdirectory(title="Select a backup output folder")
        if path:
            self.backup_dir_var.set(path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select the modded output folder")
        if path:
            self.output_dir_var.set(path)
            self.output_parent_dir_var.set(str(Path(path).resolve().parent))
            self._save_current_paths()

    def _browse_output_parent_dir(self) -> None:
        path = filedialog.askdirectory(title="Select where to save the modified Virtual Families folder")
        if path:
            self.output_parent_dir_var.set(path)
            self.output_dir_var.set("")
            self.last_auto_output_dir = ""
            self._auto_populate_output_dir()
            self._save_current_paths()

    def _browse_log_path(self) -> None:
        path = filedialog.asksaveasfilename(title="Choose patch log path", defaultextension=".json",
                                            filetypes=[("JSON logs", "*.json"), ("All files", "*.*")])
        if path:
            self.log_path_var.set(path)

    def _browse_restore_backup(self) -> None:
        path = filedialog.askdirectory(title="Select a Virtual Families 1 patch backup folder")
        if path:
            self.restore_backup_var.set(path)

    def _browse_restore_log(self) -> None:
        path = filedialog.asksaveasfilename(title="Choose restore log path", defaultextension=".json",
                                            filetypes=[("JSON logs", "*.json"), ("All files", "*.*")])
        if path:
            self.restore_log_var.set(path)

    def load_manifest_settings(self) -> bool:
        manifest_text = self.manifest_var.get()

        def load():
            path = Path(required_path(manifest_text, "Patch manifest")).resolve()
            data = patcher.read_json(path)
            return path, data, patcher.manifest_settings(data)

        try:
            manifest_path, manifest, settings = load()
        except Exception as exc:
            # The placeholder destroys the setting controls, so the loaded
            # state goes with them: Apply must never read the checkboxes of a
            # manifest nobody can see.
            self.settings = {}
            self.setting_vars = {}
            self.setting_prerequisites = {}
            self.loaded_manifest_path = None
            self.loaded_manifest_data = None
            self.version_var.set("Version: unknown")
            self._render_settings_placeholder("Load a manifest to see toggleable patch settings.")
            self._set_error(f"Could not load manifest settings: {exc}")
            return False

        self.settings = settings
        self.loaded_manifest_path = str(manifest_path)
        self.loaded_manifest_data = manifest
        version = manifest_version_label(manifest)
        self.version_var.set(f"Version: {version}" if version else "Version: unknown")
        self.setting_vars = {}
        self.description_widgets = []
        self.setting_prerequisites = setting_closure_maps(settings)
        for child in self.settings_inner.winfo_children():
            child.destroy()

        if not settings:
            self._render_settings_placeholder("This manifest does not declare toggleable settings.")
        else:
            row = 0
            for _key, label, color, category_settings in categorized_settings(settings):
                self._category_header(self.settings_inner, label, color).grid(row=row, column=0, sticky="ew", pady=(8 if row else 0, 4))
                row += 1
                for setting in category_settings:
                    var = tk.BooleanVar(value=setting.default)
                    self.setting_vars[setting.id] = var
                    item = ttk.Frame(self.settings_inner, padding=(0, 4))
                    item.grid(row=row, column=0, sticky="ew")
                    item.columnconfigure(0, weight=1)
                    ttk.Checkbutton(item, text=setting.label, variable=var).grid(row=0, column=0, sticky="w")
                    details = setting_description_text(
                        setting, settings, self.setting_prerequisites.get(setting.id, frozenset()))
                    self._markup_label(item, details).grid(row=1, column=0, sticky="ew", padx=(22, 0))
                    row += 1
            for setting_id, var in self.setting_vars.items():
                var.trace_add("write", lambda *_args, setting_id=setting_id: self._on_setting_toggled(setting_id))
            self._normalize_setting_selection()
        self.status_var.set(f"Loaded {len(settings)} setting(s) from {manifest_path.name}.")
        self._append_log(f"Loaded manifest settings: {manifest_path}\n")
        self._auto_populate_output_dir()
        return True

    def _on_settings_canvas_configure(self, event: tk.Event) -> None:
        self.settings_canvas.itemconfigure(self.settings_window, width=event.width)
        self.root.after_idle(self._resize_all_markup_labels)

    def _markup_label(self, parent: tk.Widget, text: str) -> tk.Text:
        widget = tk.Text(parent, height=1, wrap="word", borderwidth=0, highlightthickness=0, padx=0, pady=0,
                         background=self.root.cget("background"), foreground="#555555")
        normal_font = tkfont.nametofont("TkDefaultFont").copy()
        bold_font = normal_font.copy()
        bold_font.configure(weight="bold")
        widget.tag_configure("normal", font=normal_font, foreground="#555555")
        widget.tag_configure("bold", font=bold_font, foreground="#555555")
        for segment, bold in markup_segments(text):
            widget.insert("end", segment, "bold" if bold else "normal")
        widget._vf1_description_text = text  # type: ignore[attr-defined]
        widget._vf1_normal_font = normal_font  # type: ignore[attr-defined]
        widget.configure(state="disabled", cursor="arrow")
        widget.bind("<Configure>", lambda _event, text_widget=widget: self._resize_markup_label(text_widget))
        widget.bind("<MouseWheel>", self._scroll_settings_canvas)
        self.description_widgets.append(widget)
        self.root.after_idle(lambda text_widget=widget: self._resize_markup_label(text_widget))
        return widget

    def _category_header(self, parent: tk.Widget, text: str, color: str) -> tk.Label:
        return tk.Label(parent, text=text, fg=color, font=("", 10, "bold"), anchor="w",
                        background=self.root.cget("background"))

    def _resize_markup_label(self, widget: tk.Text) -> None:
        # Reloading a manifest destroys these labels while their idle resize
        # callbacks are still queued; a dead widget here is expected.
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        text = getattr(widget, "_vf1_description_text", "")
        normal_font = getattr(widget, "_vf1_normal_font", tkfont.nametofont("TkDefaultFont"))
        width = widget.winfo_width() - 4
        laid_out = width >= 80
        if not laid_out:
            width = max(80, self.settings_canvas.winfo_width() - 60)
        display_lines = estimate_wrapped_lines(text, width, normal_font.measure)
        if laid_out:
            # Asking Tk to count wrapped lines in a text that is not laid out yet (a 1-pixel-wide, hidden or
            # not-yet-shown window) is pathologically slow and froze the window's main loop (and the GUI tests)
            # on some display settings, so only a label with a real width is counted; the <Configure> event
            # runs this again as soon as it has one.
            try:
                count = widget.count("1.0", "end-1c", "displaylines")
                display_lines = max(display_lines, int(count[0]) if count else 1)
            except tk.TclError:
                display_lines = max(display_lines, int(widget.index("end-1c").split(".", 1)[0]))
        height = max(1, display_lines)
        if int(widget.cget("height")) != height:
            widget.configure(height=height)
            self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))

    def _resize_all_markup_labels(self) -> None:
        for widget in list(self.description_widgets):
            with contextlib.suppress(tk.TclError):
                if widget.winfo_exists():
                    self._resize_markup_label(widget)

    def _scroll_settings_canvas(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        units = -1 * int(delta / 120) if delta else 0
        if units:
            self.settings_canvas.yview_scroll(units, "units")
        return "break"

    def _render_settings_placeholder(self, text: str) -> None:
        for child in self.settings_inner.winfo_children():
            child.destroy()
        ttk.Label(self.settings_inner, text=text, style="Muted.TLabel", padding=(0, 8)).grid(row=0, column=0, sticky="w")

    def select_default_settings(self) -> None:
        with self._bulk_setting_change():
            for setting_id, var in self.setting_vars.items():
                var.set(self.settings[setting_id].default)

    def select_all_settings(self) -> None:
        with self._bulk_setting_change():
            for var in self.setting_vars.values():
                var.set(True)

    def clear_all_settings(self) -> None:
        with self._bulk_setting_change():
            for var in self.setting_vars.values():
                var.set(False)

    def select_category_settings(self, category: str) -> None:
        with self._bulk_setting_change():
            for setting_id in setting_ids_for_category(self.settings, category):
                var = self.setting_vars.get(setting_id)
                if var is not None:
                    var.set(True)
                    self._tick_prerequisites(setting_id)

    @contextlib.contextmanager
    def _bulk_setting_change(self):
        """Set many checkboxes, then make the result consistent once."""
        previous = self._syncing_settings
        self._syncing_settings = True
        try:
            yield
        finally:
            self._syncing_settings = previous
        if not previous:
            self._normalize_setting_selection()

    def _on_setting_toggled(self, setting_id: str) -> None:
        """Dependencies close in both directions.

        Ticking a setting ticks what it needs; unticking a prerequisite
        unticks everything that needs it. The graph comes from the
        manifest's "requires" lists, never from a hardcoded list.
        """
        if self._syncing_settings:
            return
        var = self.setting_vars.get(setting_id)
        if var is None:
            return
        if var.get():
            self._syncing_settings = True
            try:
                self._tick_prerequisites(setting_id)
            finally:
                self._syncing_settings = False
        self._normalize_setting_selection()

    def _tick_prerequisites(self, setting_id: str) -> None:
        for other in sorted(self.setting_prerequisites.get(setting_id, frozenset())):
            other_var = self.setting_vars.get(other)
            if other_var is not None:
                other_var.set(True)

    def _normalize_setting_selection(self) -> None:
        """Untick any setting whose prerequisite is unticked."""
        previous = self._syncing_settings
        self._syncing_settings = True
        try:
            changed = True
            while changed:
                changed = False
                for setting_id, var in self.setting_vars.items():
                    prerequisites = self.setting_prerequisites.get(setting_id, frozenset())
                    satisfied = all(self.setting_vars[o].get() for o in prerequisites if o in self.setting_vars)
                    if not satisfied and var.get():
                        var.set(False)
                        changed = True
        finally:
            self._syncing_settings = previous

    def selected_settings(self) -> set[str]:
        return {setting_id for setting_id, var in self.setting_vars.items() if var.get()}

    def start_apply(self, *, dry_run: bool) -> None:
        if not self._ensure_manifest_settings_loaded():
            return
        self._auto_populate_output_dir()
        self._save_current_paths()
        try:
            args = build_apply_namespace(
                game_dir=self.game_dir_var.get(),
                manifest=self.manifest_var.get(),
                output_dir=self.output_dir_var.get(),
                output_parent_dir=self.output_parent_dir_var.get(),
                backup_dir=self.backup_dir_var.get(),
                log=self.log_path_var.get(),
                dry_run=dry_run,
                settings=self.settings,
                selected_settings=self.selected_settings(),
            )
        except patcher.PatchError as exc:
            self._set_error(str(exc))
            return
        args.progress_callback = lambda message: self.root.after(0, lambda text=message: self._append_log(text + "\n"))

        if not dry_run and not messagebox.askyesno(
            f"Enable/Disable {APP_DISPLAY_NAME}",
            "This will validate the selected folder, then enable checked patches and disable unchecked patches. "
            "With a vanilla folder it refreshes the separate modded output folder first; with only a modded output "
            "folder it reconfigures that existing modded folder. Continue?",
        ):
            return
        label = "Dry run" if dry_run else "Enable/Disable patches"
        self._run_worker(label, lambda: patcher.apply_manifest(args), args=args, dry_run=dry_run)

    def start_restore(self) -> None:
        try:
            # No destination: a backup is restored into the folder it was
            # taken from, which the backup records. Backups are taken of the
            # modded folder; the vanilla folder field is never passed here.
            args = build_restore_namespace(backup_dir=self.restore_backup_var.get(), game_dir=None,
                                           log=self.restore_log_var.get())
        except patcher.PatchError as exc:
            self._set_error(str(exc))
            return
        if not messagebox.askyesno(
            APP_DISPLAY_NAME,
            f"Restore the selected backup into the folder it was taken from{restore_destination_text(args.backup_dir)}?",
        ):
            return
        self._run_worker("Restore backup", lambda: patcher.restore_backup(args))

    def _ensure_manifest_settings_loaded(self) -> bool:
        try:
            current = str(Path(required_path(self.manifest_var.get(), "Patch manifest")).resolve())
        except patcher.PatchError as exc:
            self._set_error(str(exc))
            return False
        if current != self.loaded_manifest_path:
            return self.load_manifest_settings()
        return True

    def _auto_populate_output_dir(self) -> None:
        game_dir_text = clean_path_text(self.game_dir_var.get())
        if not game_dir_text:
            return
        manifest = self.loaded_manifest_data if isinstance(self.loaded_manifest_data, dict) else {}
        try:
            folder_name = patcher.manifest_output_folder_name(manifest)
        except patcher.PatchError:
            folder_name = patcher.DEFAULT_OUTPUT_FOLDER
        game_dir = Path(game_dir_text)
        parent_text = clean_path_text(self.output_parent_dir_var.get())
        parent_dir = Path(parent_text).resolve() if parent_text else patcher.default_output_parent(game_dir)
        default_output = str((parent_dir / folder_name).resolve())
        current = clean_path_text(self.output_dir_var.get())
        if not current or current == self.last_auto_output_dir:
            self.output_dir_var.set(default_output)
            self.last_auto_output_dir = default_output

    def _save_current_paths(self) -> None:
        try:
            save_saved_paths(
                vanilla_game_dir=self.game_dir_var.get(),
                modded_output_parent_dir=self.output_parent_dir_var.get(),
                modded_output_dir=self.output_dir_var.get(),
            )
        except OSError as exc:
            self._append_log(f"Could not save local patcher paths: {exc}\n")

    def _run_worker(self, label: str, func: object, *, args: object | None = None, dry_run: bool = False) -> None:
        self._set_busy(True)
        self.status_var.set(f"{label} running - please wait...")
        self._open_work_wait(label)
        self._append_log(f"\n== {label} ==\n")
        self._append_log("Please wait…\n\nChecking your game files and preparing the patches.\n")

        def worker() -> None:
            stdout = io.StringIO()
            stderr = io.StringIO()
            success = True
            message = ""
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    func()
                except patcher.PatchError as exc:
                    success = False
                    message = f"ERROR: {exc}"
                except Exception:
                    success = False
                    message = traceback.format_exc()
            output = stdout.getvalue()
            err_output = stderr.getvalue()
            summary = getattr(args, "last_apply_summary", None) if args is not None else None
            self.root.after(0, lambda: self._finish_worker(label, success, message, output, err_output, summary, dry_run))

        # If the thread cannot start, nothing would ever call _finish_worker
        # and the modal popup would lock the app; undo the busy state here.
        try:
            threading.Thread(target=worker, daemon=True).start()
        except RuntimeError as exc:
            self._close_work_wait()
            self._set_busy(False)
            self.status_var.set(f"{label} could not start")
            self._append_log(f"ERROR: could not start the {label} thread: {exc}\n")
            messagebox.showerror("Could not start",
                                 f"{label} could not be started because a worker thread could not be created:\n\n{exc}")

    def _finish_worker(self, label: str, success: bool, message: str, stdout: str, stderr: str,
                       summary: dict[str, object] | None = None, dry_run: bool = False) -> None:
        if stdout:
            self._append_log(stdout)
        if stderr:
            self._append_log(stderr)
        if message:
            self._append_log(message + "\n")
        # Closed BEFORE any dialog: a messagebox behind the modal popup's grab
        # would be unreachable and the app would look hung.
        self._close_work_wait()
        self._set_busy(False)
        if success:
            self.status_var.set(f"{label} complete.")
            self._save_current_paths()
            if summary and not dry_run:
                self._show_apply_success(summary)
        else:
            self.status_var.set(f"{label} failed.")
            if message:
                messagebox.showerror(APP_DISPLAY_NAME, message.removeprefix("ERROR: ").strip())

    # What the popup says the run is DOING, keyed on the label _run_worker got.
    _WORK_WAIT_DETAIL = {
        "Dry run": "Checking your game files. Nothing is written in a dry run.",
        "Restore backup": "Restoring the selected backup into the folder it was taken from.",
    }

    def _work_wait_detail(self, label: str) -> str:
        return self._WORK_WAIT_DETAIL.get(label, "Checking your game files and writing the patched game.")

    def _open_work_wait(self, label: str) -> None:
        """Show the wait popup for a long background run. Never raises."""
        self._work_wait = None
        self._work_wait_previous_close = None
        try:
            wait = WaitWindow(self.root, "Please wait",
                              f"{label} in progress.\n\n{self._work_wait_detail(label)}\nThis can take a minute.")
        except tk.TclError:
            for child in self.root.winfo_children():
                if isinstance(child, WaitWindow):
                    with contextlib.suppress(tk.TclError, AttributeError):
                        child.destroy()
            return
        self._work_wait = wait
        # Closing the app from the title bar while the worker writes game
        # files would destroy every widget under it.
        with contextlib.suppress(tk.TclError):
            self._work_wait_previous_close = self.root.protocol("WM_DELETE_WINDOW")
            self.root.protocol("WM_DELETE_WINDOW", lambda: None)

    def _close_work_wait(self) -> None:
        wait = self._work_wait
        if wait is not None:
            wait.close()
        self._work_wait = None
        previous = self._work_wait_previous_close
        if previous is not None:
            with contextlib.suppress(tk.TclError):
                self.root.protocol("WM_DELETE_WINDOW", previous)
        self._work_wait_previous_close = None

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for control in self.busy_controls:
            control.configure(state=state)

    def _set_error(self, message: str) -> None:
        self.status_var.set(message.splitlines()[0] if message else message)
        self._append_log(f"ERROR: {message}\n")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _show_apply_success(self, summary: dict[str, object]) -> None:
        settings = summary.get("settings", {})
        enabled_labels = []
        disabled_labels = []
        if isinstance(settings, dict):
            for row in settings.get("available", []):
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or row.get("id"))
                if row.get("enabled"):
                    enabled_labels.append(label)
                else:
                    if row.get("inactive_reason"):
                        label += f" ({row['inactive_reason']})"
                    disabled_labels.append(label)

        def compact(values: list[str], limit: int = 18) -> str:
            if not values:
                return "(none)"
            shown = values[:limit]
            suffix = "" if len(values) <= limit else f"\n...and {len(values) - limit} more."
            return "\n".join(f"- {value}" for value in shown) + suffix

        vanilla_dir = str(summary.get("game_dir", ""))
        output_dir = str(summary.get("output_dir", ""))
        save_dir = str(summary.get("modded_save_dir", ""))
        log_path = str(summary.get("log_path", ""))
        win = tk.Toplevel(self.root)
        win.title(f"{APP_DISPLAY_NAME} complete")
        win.geometry("780x620")
        win.minsize(620, 430)
        win.transient(self.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        body = ttk.Frame(win, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(7, weight=1)

        ttk.Label(body, text="Enable/Disable complete!", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Patches enabled successfully:", style="Section.TLabelframe.Label").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(body, text=compact(enabled_labels, limit=10), wraplength=720, justify="left").grid(row=2, column=0, sticky="ew")
        ttk.Label(body, text="Patches disabled/restored to vanilla:", style="Section.TLabelframe.Label").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Label(body, text=compact(disabled_labels, limit=10), wraplength=720, justify="left").grid(row=4, column=0, sticky="ew")

        paths = ttk.Frame(body)
        paths.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        paths.columnconfigure(1, weight=1)
        self._path_link_row(paths, 0, "Vanilla Game Folder Path", vanilla_dir)
        self._path_link_row(paths, 1, "Modified Game Folder Path", output_dir)
        self._path_link_row(paths, 2, "Modified Game Saves Folder Path", save_dir)

        ttk.Label(body, text="Modified file log:", style="Section.TLabelframe.Label").grid(row=6, column=0, sticky="w", pady=(12, 0))
        log_frame = ttk.Frame(body)
        log_frame.grid(row=7, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        file_text = tk.Text(log_frame, height=14, wrap="none")
        file_scroll_y = ttk.Scrollbar(log_frame, orient="vertical", command=file_text.yview)
        file_scroll_x = ttk.Scrollbar(log_frame, orient="horizontal", command=file_text.xview)
        file_text.configure(yscrollcommand=file_scroll_y.set, xscrollcommand=file_scroll_x.set)
        file_text.grid(row=0, column=0, sticky="nsew")
        file_scroll_y.grid(row=0, column=1, sticky="ns")
        file_scroll_x.grid(row=1, column=0, sticky="ew")
        file_lines = success_file_lines(summary)
        if log_path:
            file_lines = [f"Patch log: {log_path}", ""] + file_lines
        file_text.insert("end", "\n".join(file_lines))
        file_text.configure(state="disabled")

        footer_text = (
            f"To play existing Virtual Families saves, copy the contents of your original "
            f"Documents/LDW/{patcher.VANILLA_SAVE_FOLDER} save folder into the modded save folder above. "
            "Existing game saves are unaltered in the original game folder.\n\n"
            "Have fun! -Lorsieab2 :)"
        )
        ttk.Label(body, text=footer_text, wraplength=720, justify="left").grid(row=8, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(body, text="Close", command=win.destroy).grid(row=9, column=0, sticky="e", pady=(12, 0))

    def _path_link_row(self, parent: tk.Widget, row: int, label: str, path: str) -> None:
        ttk.Label(parent, text=f"{label}:").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        link = tk.Label(parent, text=path or "(not available)", fg="#0057c2", font=("", 9, "bold"),
                        cursor="hand2" if path else "arrow", anchor="w")
        link.grid(row=row, column=1, sticky="ew", pady=2)
        if path:
            link.bind("<Button-1>", lambda _event, value=path: self._open_path(value))

    def _open_path(self, path: str) -> None:
        try:
            subprocess.Popen(["explorer", path])
        except Exception as exc:
            messagebox.showerror(APP_DISPLAY_NAME, f"Could not open path:\n{path}\n\n{exc}")

    def _on_close(self) -> None:
        self._save_current_paths()
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    app = VF1PatcherGUI(root)
    app.manifest_var.set(argv[0] if argv else str(patcher.DEFAULT_MANIFEST))
    root.after(100, app.load_manifest_settings)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
