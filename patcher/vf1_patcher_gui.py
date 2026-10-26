#!/usr/bin/env python3
"""Tkinter GUI for the Virtual Families 1 Fun Patcher.

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
import vf1_how_to_use as how_to_use  # noqa: E402
import vf1_patcher as patcher  # noqa: E402
import vf1_rename_family as rename_family  # noqa: E402
import vf1_game_mechanics as game_mechanics  # noqa: E402
import vf1_game_speed as game_speed  # noqa: E402
import vf1_save_backup as save_backup  # noqa: E402
from vf1_tree_editor_tools import scrollable_frame  # noqa: E402

APP_DISPLAY_NAME = "Virtual Families 1 Fun Patcher"
# The Tools tab's box: the game its tools work on (the Virtual Villagers patcher's box names its game).
TOOLS_GAME_TITLE = "Virtual Families"
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
    (patcher.EXPERIMENTAL_CATEGORY, "Experimental", "#b30000"),
]
# Shown under the Experimental heading. Experimental settings default off and Enable All leaves them off.
EXPERIMENTAL_WARNING = patcher.EXPERIMENTAL_WARNING
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


def _load_settings_file(path: Path) -> dict:
    """The whole local settings file (every key), or {}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_tree_settings(settings_path: Path | None = None) -> dict:
    """The Family Tree Maker's remembered look and window ("family_tree": {"style", "window"})."""
    tree = _load_settings_file(settings_path or local_settings_path()).get("family_tree")
    return tree if isinstance(tree, dict) else {}


def save_tree_settings(style: dict | None, window: dict | None, settings_path: Path | None = None) -> None:
    path = settings_path or local_settings_path()
    data = _load_settings_file(path)
    data["family_tree"] = {"style": style or {}, "window": window or {}}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def save_saved_paths(
    *,
    vanilla_game_dir: str | None = None,
    modded_output_parent_dir: str | None = None,
    modded_output_dir: str | None = None,
    settings_path: Path | None = None,
) -> None:
    path = settings_path or local_settings_path()
    data = {**_load_settings_file(path), **load_saved_paths(path)}
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


#  The patcher's windows, as the Virtual Villagers Fun Patcher's (src/vv_fun_patcher_gui.py): every window gets
#  Minimize and Maximize, and a dialog holds the patcher the Windows way -- every other window of the patcher is
#  disabled while it is open -- instead of with a Tk grab, which would stop the dialog from being minimized.


def _window_buttons(event) -> None:
    """Every window the patcher opens gets Minimize and Maximize.  Windows draws a window kept above its parent
    (transient) without them, so they are put back on its frame."""
    window = event.widget
    if not isinstance(window, tk.Toplevel) or sys.platform != "win32" or getattr(window, "_vf_buttons", False):
        return
    window._vf_buttons = True                   # once per window: changing the frame maps it again

    def add() -> None:
        try:
            if window.overrideredirect():
                return
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(window.winfo_id(), 2)            # the window's own frame (GA_ROOT)
            if not hwnd:
                return
            style = user32.GetWindowLongW(hwnd, -16)                  # GWL_STYLE
            wanted = style | 0x00020000 | 0x00010000                  # WS_MINIMIZEBOX | WS_MAXIMIZEBOX
            if wanted != style:
                user32.SetWindowLongW(hwnd, -16, wanted)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
            owner = getattr(window, "_vf_owner", None)
            if getattr(window, "_vf_disabled", None) is not None and owner is not None and owner.winfo_exists():
                _owned_by(window, owner)        # Tk drops the owner when the transient is cleared
        except (tk.TclError, OSError, AttributeError):
            pass                                # a window without its buttons is still a window
    # Tk ignores Minimize on a window kept above another (transient), so to Tk the patcher's windows are
    # ordinary ones; _hold makes a dialog's window its owner's in Windows' own terms, which keeps it above.
    try:
        master = window.transient()
        if master:
            window._vf_owner = window.nametowidget(str(master)).winfo_toplevel()
            window.wm_transient("")
            window.update_idletasks()
            if getattr(window, "_vf_disabled", None) is not None:
                _owned_by(window, window._vf_owner)
            else:
                _follow_owner(window, window._vf_owner)
    except (tk.TclError, KeyError, OSError, AttributeError):
        pass
    window.after_idle(add)
    window.after(150, add)
    window.after(600, add)


_TK_GRAB_SET, _TK_GRAB_RELEASE = tk.Misc.grab_set, tk.Misc.grab_release


def _app_windows(widget) -> list:
    """The patcher's own windows: the main one and every Toplevel under it."""
    root = widget._root()
    out = [root]
    todo = list(root.winfo_children())
    while todo:
        w = todo.pop()
        if isinstance(w, tk.Toplevel):
            out.append(w)
        todo.extend(w.winfo_children())
    return out


def _follow_owner(window, owner) -> None:
    """A window kept above another but not holding it (How to Use) hides when that window is minimized and comes
    back with it, without being owned in Windows' terms (which would take its own Minimize away)."""
    def hidden(event) -> None:
        if event.widget is not owner:
            return
        try:
            if owner.state() == "iconic" and window.winfo_exists() and window.state() == "normal":
                window.withdraw()
                window._vf_followed = True
        except tk.TclError:
            pass

    def shown(event) -> None:
        if event.widget is not owner:
            return
        try:
            if getattr(window, "_vf_followed", False) and window.winfo_exists():
                window._vf_followed = False
                window.deiconify()
        except tk.TclError:
            pass

    bound = [(owner, "<Unmap>", owner.bind("<Unmap>", hidden, add="+")),
             (owner, "<Map>", owner.bind("<Map>", shown, add="+"))]

    def gone(event) -> None:
        if event.widget is window:
            for widget, sequence, funcid in bound:
                _unbind_one(widget, sequence, funcid)

    window.bind("<Destroy>", gone, add="+")


def _owned_by(top, owner) -> None:
    """Make `owner` the dialog's owner in Windows' own terms: Windows keeps the dialog above it and hides and
    shows it with its owner, while Tk, which ignores Minimize on its transients, still lets it minimize."""
    import ctypes
    user32 = ctypes.windll.user32
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    top.update_idletasks()
    hwnd = user32.GetAncestor(top.winfo_id(), 2)
    owner_hwnd = user32.GetAncestor(owner.winfo_id(), 2)
    if hwnd and owner_hwnd:
        user32.SetWindowLongPtrW(hwnd, -8, owner_hwnd)              # GWLP_HWNDPARENT: the owner


def _hold_windows(self) -> None:
    """grab_set for a dialog the way Windows holds windows (Tk refuses to minimize anything while a Tk grab is in
    effect): every other window of the patcher is disabled, as Tk's grab blocked them all, each counting the
    dialogs holding it and enabled again when the last one goes."""
    top = self.winfo_toplevel()
    if top is top._root() or top.master is None:
        return _TK_GRAB_SET(self)
    if getattr(top, "_vf_disabled", None) is not None:
        return None                             # already holding (taken back after a "Please wait")
    owner = top.master.winfo_toplevel()
    disabled = []
    for w in _app_windows(top):
        if w is top:
            continue
        try:
            if not w.winfo_exists():
                continue
            w._vf_held = getattr(w, "_vf_held", 0) + 1
            w.wm_attributes("-disabled", True)
            disabled.append(w)
        except tk.TclError:
            pass
    top._vf_disabled = disabled
    top._vf_bindings = []
    if getattr(top, "_vf_owner", None) is None:
        top._vf_owner = owner                   # _window_buttons keeps it owned as it settles
    try:
        _owned_by(top, owner)
    except (OSError, AttributeError, tk.TclError):
        pass
    top._vf_bindings.append((top, "<Destroy>", top.bind(
        "<Destroy>", lambda e: _let_go(top) if e.widget is top else None, add="+")))
    _minimize_together(top, owner)
    return None                                 # focus is left as it is, as Tk's grab left it


def _unbind_one(widget, sequence: str, funcid: str) -> None:
    """Remove one binding: `unbind(sequence, funcid)` removes them all on older Pythons."""
    try:
        script = widget.tk.call("bind", widget._w, sequence)
        kept = "\n".join(line for line in str(script).split("\n") if funcid not in line)
        widget.tk.call("bind", widget._w, sequence, kept)
        widget.deletecommand(funcid)
    except tk.TclError:
        pass


def _let_go(top) -> None:
    disabled = getattr(top, "_vf_disabled", None)
    if disabled is None:
        return
    top._vf_disabled = None
    for widget, sequence, funcid in getattr(top, "_vf_bindings", []):
        if widget is not top:                   # the dialog's own go with it
            _unbind_one(widget, sequence, funcid)
    top._vf_bindings = []
    for w in disabled:
        try:
            w._vf_held = max(0, getattr(w, "_vf_held", 1) - 1)
            if not w._vf_held and w.winfo_exists():
                w.wm_attributes("-disabled", False)
        except tk.TclError:
            pass
    try:
        owner = top.master.winfo_toplevel()
        if owner.winfo_exists():
            if owner.state() == "iconic":
                owner.deiconify()
            owner.lift()
    except tk.TclError:
        pass


def _release_windows(self) -> None:
    top = self.winfo_toplevel()
    if getattr(top, "_vf_disabled", None) is not None:
        _let_go(top)
    else:
        _TK_GRAB_RELEASE(self)


def _minimize_together(top, owner) -> None:
    """A held dialog minimized minimizes its owner (so no disabled window is left on screen), and the owner
    restored brings the dialog back."""
    def unmapped(event) -> None:
        if event.widget is not top:
            return
        try:
            if top.state() == "iconic" and owner.state() != "iconic":
                owner.iconify()
        except tk.TclError:
            pass

    def mapped(event) -> None:
        if event.widget is not owner:
            return
        try:
            if getattr(top, "_vf_disabled", None) is not None and top.winfo_exists() and top.state() == "iconic":
                top.deiconify()
                top.lift()
        except tk.TclError:
            pass

    top._vf_bindings.append((top, "<Unmap>", top.bind("<Unmap>", unmapped, add="+")))
    top._vf_bindings.append((owner, "<Map>", owner.bind("<Map>", mapped, add="+")))


def install_window_behaviour(root: tk.Misc) -> None:
    """Minimize and Maximize on every window, and dialogs that hold the patcher the Windows way."""
    root.bind_class("Toplevel", "<Map>", _window_buttons, add="+")
    if sys.platform == "win32":
        tk.Misc.grab_set, tk.Misc.grab_release = _hold_windows, _release_windows


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
        install_window_behaviour(root)
        self.root.title(APP_DISPLAY_NAME)
        self.root.geometry("920x820")
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
        self.saves_found_var = tk.StringVar(value="")
        self.help_keys: set[str] = set()
        self._help_windows: dict[str, tk.Toplevel] = {}

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
        root_frame.rowconfigure(1, weight=3)
        root_frame.rowconfigure(2, weight=1)
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
        header_links = ttk.Frame(header)
        header_links.grid(row=1, column=2, sticky="e", padx=(12, 0), pady=(2, 0))
        update_link = ttk.Label(header_links, text="Check for updates", style="Link.TLabel", cursor="hand2")
        update_link.pack(side="left")
        self._help_button(header_links, "check_for_updates").pack(side="left", padx=(3, 0))
        update_link.bind("<Button-1>", lambda _event: self._open_updates_url())
        update_link.bind("<Enter>", lambda _event: update_link.configure(style="LinkHover.TLabel"))
        update_link.bind("<Leave>", lambda _event: update_link.configure(style="Link.TLabel"))
        ttk.Label(header, text=SAVE_COMPATIBILITY_NOTE, style="Muted.TLabel", justify="left",
                  wraplength=660).grid(row=2, column=1, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Label(header, text=AI_DISCLOSURE, style="Muted.TLabel", justify="left",
                  wraplength=660).grid(row=3, column=1, columnspan=2, sticky="w", pady=(2, 0))

        # Patches on one tab, the tools (save backups) on another; the Run Log below serves both.
        self.sections = ttk.Notebook(root_frame)
        self.sections.grid(row=1, column=0, sticky="nsew")
        patches_tab = ttk.Frame(self.sections, padding=(0, 10, 0, 0))
        tools_tab = ttk.Frame(self.sections, padding=14)
        self.sections.add(patches_tab, text="Patches")
        self.sections.add(tools_tab, text="Tools")
        patches_tab.columnconfigure(0, weight=1)
        patches_tab.rowconfigure(1, weight=1)
        self._build_file_section(patches_tab).grid(row=0, column=0, sticky="ew")
        self._build_settings_section(patches_tab).grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self._build_action_section(patches_tab).grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._build_tools_tab(tools_tab)
        self._build_log_section(root_frame).grid(row=2, column=0, sticky="nsew", pady=(10, 0))

    def _build_file_section(self, parent: tk.Widget) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Patch Input", style="Section.TLabelframe", padding=10)
        frame.columnconfigure(1, weight=1)
        self._path_row(frame, 0, "Vanilla game folder (optional if reconfiguring an existing modded folder)", self.game_dir_var, self._browse_game_dir, help_key="game_folder")
        self._path_row(frame, 1, "Patch manifest", self.manifest_var, self._browse_manifest, help_key="patch_manifest")
        self._path_row(frame, 2, "Save modified folders under", self.output_parent_dir_var, self._browse_output_parent_dir, optional=True, help_key="output_location")
        self._path_row(frame, 3, "Modded output folder", self.output_dir_var, self._browse_output_dir, optional=True, help_key="output_location")
        self._path_row(frame, 4, "Backup folder", self.backup_dir_var, self._browse_backup_dir, optional=True, help_key="backup_folder")
        self._path_row(frame, 5, "Patch log", self.log_path_var, self._browse_log_path, optional=True, help_key="backup_folder")
        return frame

    def _build_settings_section(self, parent: tk.Widget) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Patch Settings", style="Section.TLabelframe", padding=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(4, weight=1)
        self._with_help(controls, lambda p: self._button(p, "Load Manifest Settings", self.load_manifest_settings),
                        "load_manifest").grid(row=0, column=0, padx=(0, 6))
        self._with_help(controls, lambda p: self._button(p, "Defaults", self.select_default_settings),
                        "defaults").grid(row=0, column=1, padx=(0, 6))
        self._with_help(controls, lambda p: self._button(p, "Enable All", self.select_all_settings),
                        "enable_all").grid(row=0, column=2, padx=(0, 6))
        self._with_help(controls, lambda p: self._button(p, "Disable All", self.clear_all_settings),
                        "disable_all").grid(row=0, column=3, padx=(0, 6))
        self._with_help(controls, lambda p: self._button(p, "Enable All Main Patches",
                                                         lambda: self.select_category_settings("main")),
                        "enable_main").grid(row=1, column=0, padx=(0, 6), pady=(6, 0))
        self._with_help(controls, lambda p: self._button(p, "Enable all Optional Content",
                                                         lambda: self.select_category_settings("optional")),
                        "enable_optional").grid(row=1, column=1, padx=(0, 6), pady=(6, 0))

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
        self.log_text = tk.Text(frame, height=8, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        return frame

    def _build_action_section(self, parent: tk.Widget) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(3, weight=1)
        self._with_help(frame, lambda p: self._button(p, "Dry Run (Validate Only)", lambda: self.start_apply(dry_run=True)),
                        "dry_run").grid(row=0, column=0, padx=(0, 8))
        self._with_help(frame, lambda p: self._apply_button(p, "Enable/Disable Patches", lambda: self.start_apply(dry_run=False)),
                        "enable_disable").grid(row=0, column=1, padx=(0, 8))
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
        self._with_help(restore_frame, lambda p: self._button(p, "Restore Backup", self.start_restore),
                        "restore_backup").grid(row=0, column=3, rowspan=2, sticky="ns")

        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=3, sticky="ew", padx=(8, 0))
        return frame

    def _path_row(self, parent: ttk.LabelFrame, row: int, label: str, variable: tk.StringVar, command: object,
                  *, optional: bool = False, help_key: str | None = None) -> None:
        suffix = " (optional)" if optional else ""
        ttk.Label(parent, text=f"{label}{suffix}").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=3)
        self._button(parent, "Browse", command).grid(row=row, column=2, sticky="ew", pady=3)
        if help_key:
            self._help_button(parent, help_key).grid(row=row, column=3, padx=(4, 0), pady=3)

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
                if _key == patcher.EXPERIMENTAL_CATEGORY:
                    self._markup_label(self.settings_inner, f"**{EXPERIMENTAL_WARNING}**").grid(
                        row=row, column=0, sticky="ew", pady=(0, 4))
                    row += 1
                for setting in category_settings:
                    var = tk.BooleanVar(value=setting.default)
                    self.setting_vars[setting.id] = var
                    item = ttk.Frame(self.settings_inner, padding=(0, 4))
                    item.grid(row=row, column=0, sticky="ew")
                    item.columnconfigure(0, weight=1)
                    head = ttk.Frame(item)
                    head.grid(row=0, column=0, sticky="w")
                    ttk.Checkbutton(head, text=setting.label, variable=var).pack(side="left")
                    if how_to_use.patch_key(setting.id) in how_to_use.guide_lines():
                        self._help_button(head, how_to_use.patch_key(setting.id), setting.label).pack(
                            side="left", padx=(6, 0))
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
        # Enable All leaves Experimental settings off: the player ticks each one deliberately.
        with self._bulk_setting_change():
            for setting_id, var in self.setting_vars.items():
                var.set(not self.settings[setting_id].experimental)

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

    def _work_wait_message(self, label: str) -> str:
        """A patching run's label gets its detail; a tool passes its whole message (the Virtual Villagers
        patcher's wording: "Backing up saves…" and so on)."""
        if label in self._WORK_WAIT_DETAIL or label == "Enable/Disable patches":
            return f"{label} in progress.\n\n{self._work_wait_detail(label)}\nThis can take a minute."
        return label

    def _open_work_wait(self, label: str) -> None:
        """Show the wait popup for a long background run. Never raises."""
        self._work_wait = None
        self._work_wait_previous_close = None
        try:
            wait = WaitWindow(self.root, "Please wait", self._work_wait_message(label))
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

    # ------------------------------------------------------------------ help ("?") guides

    def _help_button(self, parent: tk.Widget, key: str, title: str | None = None) -> ttk.Button:
        """A small "?" button that opens the brief guide for one feature.

        ``key`` names the guide in how_to_use.json; a key with no guide fails
        here, while the window is built, never later on a click.
        """
        how_to_use.guide(key, title)
        self.help_keys.add(key)
        return ttk.Button(parent, text="?", width=2, command=lambda: self._show_how_to_use(key, title))

    def _with_help(self, parent: tk.Widget, make_widget: object, key: str) -> ttk.Frame:
        """A button followed by its "?" in one cell of a grid."""
        frame = ttk.Frame(parent)
        make_widget(frame).pack(side="left")
        self._help_button(frame, key).pack(side="left", padx=(3, 0))
        return frame

    def _show_how_to_use(self, key: str, title: str | None = None) -> tk.Toplevel:
        """The small "How to use" window for one feature."""
        window = self._help_windows.get(key)
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            return window
        guide = how_to_use.guide(key, title)
        window = tk.Toplevel(self.root)
        window.title(f"How to use: {guide.title}")
        window.transient(self.root)
        window.resizable(False, False)
        frame = scrollable_frame(window, padding=16)
        ttk.Label(frame, text=guide.title, font=("Segoe UI", 11, "bold"), wraplength=480, justify="left").pack(
            anchor="w", pady=(0, 8))
        for line in guide.lines:
            ttk.Label(frame, text=line, wraplength=480, justify="left").pack(anchor="w", pady=(0, 6))
        close = ttk.Button(frame, text="Close", command=window.destroy)
        close.pack(anchor="e", pady=(8, 0))
        window.bind("<Escape>", lambda _event: window.destroy())
        self._center_dialog(window)
        close.focus_set()
        self._help_windows[key] = window
        return window

    def _center_dialog(self, window: tk.Toplevel) -> None:
        window.update_idletasks()
        try:
            viewable = bool(self.root.winfo_viewable())
        except tk.TclError:
            viewable = False
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        if viewable:
            x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        else:
            x = max(0, (window.winfo_screenwidth() - width) // 2)
            y = max(0, (window.winfo_screenheight() - height) // 2)
        window.geometry(f"+{x}+{y}")

    def _link(self, parent: tk.Widget, text: str, command: object) -> ttk.Label:
        """A clickable, underlined link label (the same look as Check for updates)."""
        link = ttk.Label(parent, text=text, style="Link.TLabel", cursor="hand2")
        link.bind("<Button-1>", lambda _event: command())
        link.bind("<Enter>", lambda _event: link.configure(style="LinkHover.TLabel"))
        link.bind("<Leave>", lambda _event: link.configure(style="Link.TLabel"))
        return link

    # ------------------------------------------------------------------ Tools tab

    def _build_tools_tab(self, tab: ttk.Frame) -> None:
        """Everything that is not a patch, laid out as the Virtual Villagers Fun Patcher's Tools tab: one box for
        the game, the save folders found in blue, the save tools in one row of links and the family and game tools
        in the next, each link with its "?"; then the guide."""
        box = ttk.LabelFrame(tab, text=TOOLS_GAME_TITLE, padding=10)
        box.pack(fill="x")
        ttk.Label(box, textvariable=self.saves_found_var, foreground="#245a9a", wraplength=760,
                  justify="left").grid(row=0, column=0, sticky="w")
        links = ttk.Frame(box)
        links.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._link(links, "Back Up Saves", self.back_up_saves).pack(side="left")
        self._help_button(links, "back_up_saves").pack(side="left", padx=(3, 0))
        self._link(links, "Restore Saves...", self.restore_saves).pack(side="left", padx=(18, 0))
        self._help_button(links, "restore_saves").pack(side="left", padx=(3, 0))
        self._link(links, "Rename Family...", self.rename_family).pack(side="left", padx=(18, 0))
        self._help_button(links, "rename_family").pack(side="left", padx=(3, 0))
        self._link(links, "Game Speed...", self.game_speed).pack(side="left", padx=(18, 0))
        self._help_button(links, "game_speed").pack(side="left", padx=(3, 0))
        family = ttk.Frame(box)
        family.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._link(family, "Family Tree Maker...", self.open_family_tree).pack(side="left")
        self._help_button(family, "family_tree").pack(side="left", padx=(3, 0))
        self._link(family, "Game Mechanics...", self.game_mechanics).pack(side="left", padx=(18, 0))
        self._help_button(family, "game_mechanics").pack(side="left", padx=(3, 0))

        guide_box = ttk.LabelFrame(tab, text="How to Use", padding=10)
        guide_box.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(guide_box)
        row.pack(anchor="w")
        self._link(row, "Getting started", lambda: self._show_how_to_use("getting_started")).pack(side="left")
        self._help_button(row, "getting_started").pack(side="left", padx=(3, 0))
        # The save folders found are read again whenever the tab is shown, as the Virtual Villagers patcher's
        # game line is always current (no Refresh link).
        self.sections.bind("<<NotebookTabChanged>>", lambda _event: self._refresh_saves_found(), add="+")
        self._refresh_saves_found()

    # ------------------------------------------------------------------ Family Tree Maker

    def open_family_tree(self):
        """The Family Tree Maker (vf1_family_tree_window): choose a save folder and a family, then the editor."""
        import vf1_family_tree_window as tree_window
        saved = load_tree_settings()
        if not hasattr(self, "tree_style"):
            self.tree_style = saved.get("style") or None
        if not hasattr(self, "tree_window"):
            self.tree_window = saved.get("window") or {}
        _documents, folders = self._save_folders()
        documents = save_backup.documents_folder()
        stock = documents / "LDW" / "Virtual Families" if documents is not None else None
        if stock is not None and stock.is_dir() and stock not in folders:
            folders.append(stock)
        return tree_window.open_family_tree(self, folders=folders)

    def _save_settings(self) -> None:
        """The Family Tree Maker's look and window, remembered for the next tree (the patcher's local settings)."""
        with contextlib.suppress(OSError, TypeError, ValueError):
            save_tree_settings(getattr(self, "tree_style", None), getattr(self, "tree_window", None))

    # ------------------------------------------------------------------ Back Up Saves / Restore Saves
    #
    # The tools' windows follow the Virtual Villagers Fun Patcher's (src/vv_fun_patcher_gui.py): the same
    # titles, headings, wording, buttons, waits and result windows, with this game's own family wording.

    def _save_folders(self) -> tuple[Path | None, list[Path]]:
        """(Documents, the modded game's save folders found there)."""
        documents = save_backup.documents_folder()
        extra: list[str] = []
        output = clean_path_text(self.output_dir_var.get())
        if output:
            with contextlib.suppress(OSError):
                extra = [p.stem for p in Path(output).glob("*.exe") if p.is_file()]
        return documents, save_backup.find_save_folders(documents, tuple(extra))

    def _refresh_saves_found(self) -> None:
        documents, folders = self._save_folders()
        if documents is None:
            text = "Windows did not report where your Documents folder is, so the save folders cannot be found."
        elif not folders:
            text = (f"No modded save folders were found in {documents / 'LDW'}. A modded game makes its save "
                    "folder the first time it is played.")
        else:
            text = "Save folders found: " + ", ".join(folder.name for folder in folders)
        self.saves_found_var.set(text)

    def back_up_saves(self) -> None:
        """Let the player pick save folders, then pause the game (if running) and copy."""
        documents, folders = self._save_folders()
        if documents is None:
            messagebox.showerror("Back Up Saves", "Windows did not report where your Documents folder is, so the "
                                 "save folders cannot be found.")
            return
        if not folders:
            messagebox.showinfo(
                "Back Up Saves",
                f"No modded save folders were found for {TOOLS_GAME_TITLE} in {documents / 'LDW'}.\n\nA modded game "
                "makes its save folder the first time it is played.")
            return
        self._show_backup_chooser(folders)

    def _scrolling_dialog(self, title: str) -> tuple[tk.Toplevel, ttk.Frame]:
        """A dialog whose content scrolls once it is taller than the screen."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        return dialog, scrollable_frame(dialog, padding=16)

    def _hold(self, dialog: tk.Toplevel, focus: tk.Widget | None = None) -> None:
        """Hold the patcher behind a dialog (the main window stays inert while it is open).  The dialog opens where
        Windows puts a new window, as the Virtual Villagers patcher's do: a wide one centred on the patcher would
        start off the left of the screen."""
        dialog.update_idletasks()
        with contextlib.suppress(tk.TclError):
            dialog.grab_set()
        with contextlib.suppress(tk.TclError):
            (focus or dialog).focus_set()

    def _show_backup_chooser(self, folders: list[Path]) -> tk.Toplevel:
        dialog, frame = self._scrolling_dialog("Back Up Saves")
        ttk.Label(frame, text="Choose the save folders to back up:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=("Each folder is copied into a new dated folder inside it: <save folder>\\Backups\\Backup <date and "
                  f"time>, with the patcher's own files for each save ({save_backup.PATCHER_DATA_FOLDER}). If the "
                  "game is running it is paused for the copy and then resumes by itself. This game saves when you "
                  "quit normally and autosaves every 10 real-life minutes while running (even paused), so a backup "
                  "made while the game is running holds the family as of its last save or autosave; quit the game "
                  "normally first to be sure the latest state is backed up."),
            wraplength=640, justify="left",
        ).pack(anchor="w", pady=(4, 10))
        ttk.Label(frame, text=TOOLS_GAME_TITLE).pack(anchor="w", pady=(6, 0))
        choices: list[tuple[Path, tk.BooleanVar]] = []
        for folder in folders:
            label = folder.name
            if save_backup.running_game_count(folder):
                label += "   (running: will be paused for the copy)"
            var = tk.BooleanVar(value=save_backup.is_patcher_save_folder(folder.name))
            ttk.Checkbutton(frame, text=label, variable=var).pack(anchor="w", padx=(14, 0))
            choices.append((folder, var))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 0))

        def start() -> None:
            chosen = [folder for folder, var in choices if var.get()]
            if not chosen:
                messagebox.showinfo("Back Up Saves", "Tick at least one save folder.", parent=dialog)
                return
            dialog.destroy()
            self._run_backups(chosen)

        ttk.Button(buttons, text="Back Up Selected", command=start).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=(8, 0))
        dialog._vf1_choices = choices  # type: ignore[attr-defined]
        dialog._vf1_start = start  # type: ignore[attr-defined]
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._hold(dialog)
        return dialog

    def _run_with_wait(self, message: str, func: object) -> object:
        """Run ``func`` off the main thread behind the "Please wait" window showing ``message``; re-raise what
        it raised."""
        box: dict[str, object] = {}

        def target() -> None:
            try:
                box["value"] = func()
            except BaseException as exc:  # handed back to the caller below
                box["error"] = exc

        self._open_work_wait(message)
        try:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            while thread.is_alive():
                with contextlib.suppress(tk.TclError):
                    self.root.update()
                time.sleep(WAIT_POLL_SECONDS)
        finally:
            self._close_work_wait()
        if "error" in box:
            raise box["error"]  # type: ignore[misc]
        return box.get("value")

    def _run_backups(self, folders: list[Path]) -> list[tuple[Path, object, str | None]]:
        def work():
            outcomes = []
            for folder in folders:
                try:
                    outcomes.append((folder, save_backup.back_up_save_folder(folder), None))
                except (save_backup.BackupError, OSError) as exc:
                    outcomes.append((folder, None, str(exc)))
            return outcomes

        outcomes = self._run_with_wait("Backing up saves…\n\nA running game is paused for the copy.", work)
        made = sum(1 for _folder, result, _error in outcomes if result is not None)
        self.status_var.set(f"Back Up Saves: {made} of {len(outcomes)} save folder(s) backed up.")
        self._show_backup_results(outcomes)
        return outcomes

    def _show_backup_results(self, outcomes) -> tk.Toplevel:
        dialog, frame = self._scrolling_dialog("Back Up Saves")
        for folder, result, error in outcomes:
            ttk.Label(frame, text=folder.name, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
            if result is None:
                ttk.Label(frame, text=f"NOT backed up: {error}", wraplength=640, justify="left",
                          foreground="#a01010").pack(anchor="w", padx=(14, 0))
                continue
            lines = [
                f"Backed up {result.file_count} file(s), {save_backup.describe_size(result.total_bytes)}; every copy "
                "was checked against the original (size and SHA-256).",
                f"Backup folder: {result.backup_folder}",
                ("The game was running: it was paused for the copy and has resumed. The backup holds the family as "
                 "of its last save (the game saves by itself every 10 minutes, and when you quit it normally)."
                 if result.paused
                 else "The game was not running."),
            ]
            ttk.Label(frame, text="\n".join(lines), wraplength=640, justify="left").pack(anchor="w", padx=(14, 0))
            if result.resume_problems:
                ttk.Label(
                    frame,
                    text=("The backup is complete, but the game could not be resumed: "
                          + "; ".join(result.resume_problems)
                          + ". If it stays frozen, close it from Task Manager; the backup above is safe."),
                    wraplength=640, justify="left", foreground="#a01010").pack(anchor="w", padx=(14, 0))
            self._link(frame, "Open Backup Folder",
                       lambda path=result.backup_folder: self._open_folder(path)).pack(
                anchor="w", padx=(14, 0), pady=(2, 0))
        ttk.Button(frame, text="Close", command=dialog.destroy).pack(pady=(16, 0))
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._hold(dialog)
        return dialog

    def _open_folder(self, path: Path) -> None:
        """Open a folder (a file's own folder) in Explorer, or say it is not there."""
        target = Path(path).expanduser()
        if target.is_file():
            target = target.parent
        if not target.is_dir():
            self.status_var.set(f"Folder not found: {target}")
            messagebox.showerror("Cannot open folder", self.status_var.get())
            return
        self._open_path(str(target))

    def restore_saves(self) -> None:
        """List the backups of the modded game's saves so the player can restore or delete one."""
        documents, folders = self._save_folders()
        if documents is None:
            messagebox.showerror("Restore Saves", "Windows did not report where your Documents folder is, so the "
                                 "save folders cannot be found.")
            return
        if not any(save_backup.list_backups(folder) for folder in folders):
            messagebox.showinfo("Restore Saves",
                                f"There are no backups of {TOOLS_GAME_TITLE} yet.\n\nUse Back Up Saves to make one.")
            return
        self._show_restore_window(folders)

    @staticmethod
    def _backup_families(info) -> dict[int, str]:
        """Each slot the backup holds, with the family's name in the backup's own save."""
        names = {slot.slot: slot.name for slot in rename_family.read_slots(Path(info.path))}
        return {slot: names.get(slot) or "(no name)" for slot in info.slots}

    def _show_restore_window(self, folders: list[Path]) -> tk.Toplevel:
        dialog, frame = self._scrolling_dialog("Restore Saves")
        ttk.Label(frame, text="Choose a backup to restore:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=("Newest first. The game must be closed: quit it from its own menu before restoring. Your saves as "
                  "they are now are backed up first, as \"Backup <date> (before restore)\", so a restore can be "
                  "undone."),
            wraplength=700, justify="left",
        ).pack(anchor="w", pady=(4, 8))
        listbox = tk.Listbox(frame, width=110, height=12, exportselection=False)
        listbox.pack(fill="both", expand=True)
        details = ttk.Label(frame, text="", wraplength=700, justify="left")
        details.pack(anchor="w", pady=(6, 0))
        scope = tk.StringVar(value="whole")
        slot_choice = tk.StringVar()
        options = ttk.Frame(frame)
        options.pack(anchor="w", pady=(8, 0))
        ttk.Radiobutton(options, text="The whole save folder", value="whole", variable=scope).grid(
            row=0, column=0, sticky="w")
        ttk.Radiobutton(options, text="One save slot only:", value="slot", variable=scope).grid(
            row=1, column=0, sticky="w")
        slots = ttk.Combobox(options, textvariable=slot_choice, state="readonly", width=50)
        slots.grid(row=1, column=1, sticky="w", padx=(8, 0))
        entries: list[tuple[Path, object, dict[int, str]]] = []

        def describe(folder: Path, info, families: dict[int, str]) -> str:
            saves = ", ".join(f"Save {slot}: {name}" for slot, name in families.items()) or "no family saves"
            variant = folder.name.removeprefix(TOOLS_GAME_TITLE + " - ")
            return (f"{info.label}   [{variant}]   {saves}   "
                    f"{info.file_count} files, {save_backup.describe_size(info.size)}")

        def refresh() -> None:
            entries.clear()
            listbox.delete(0, "end")
            listed = [(folder, info) for folder in folders for info in save_backup.list_backups(folder)]
            listed.sort(key=lambda item: item[1].when, reverse=True)
            for folder, info in listed:
                families = self._backup_families(info)
                entries.append((folder, info, families))
                listbox.insert("end", describe(folder, info, families))
            if entries:
                listbox.selection_set(0)
            selected()

        def current():
            chosen = listbox.curselection()
            return entries[chosen[0]] if chosen else None

        def selected(_event=None) -> None:
            item = current()
            if item is None:
                details.configure(text="")
                slots.configure(values=[])
                slot_choice.set("")
                return
            _folder, info, families = item
            details.configure(text=f"Backup folder: {info.path}")
            values = [f"Save {slot}: {name}" for slot, name in families.items()]
            slots.configure(values=values)
            slot_choice.set(values[0] if values else "")

        def chosen_slot():
            if scope.get() != "slot":
                return None
            text = slot_choice.get()
            if not text.startswith("Save "):
                return False
            return int(text.split(":", 1)[0].removeprefix("Save "))

        def restore() -> None:
            item = current()
            if item is None:
                return
            slot = chosen_slot()
            if slot is False:
                messagebox.showinfo("Restore Saves", "This backup holds no family save to choose.", parent=dialog)
                return
            self._run_restore(dialog, item[0], item[1], slot)
            # The "Please wait" window held the patcher and let it go on closing; hold it again, so the main
            # window stays inert behind this one, as it was before the restore.
            if dialog.winfo_exists():
                with contextlib.suppress(tk.TclError):
                    dialog.grab_set()
                refresh()

        def delete() -> None:
            item = current()
            if item is None:
                return
            folder, info, families = item
            if not messagebox.askyesno(
                "Delete Backup",
                f"Delete this backup permanently?\n\n{describe(folder, info, families)}\n\n{info.path}\n\n"
                "Your current saves are not affected.",
                parent=dialog,
            ):
                return
            try:
                save_backup.delete_backup(folder, info.path)
            except (save_backup.BackupError, OSError) as exc:
                messagebox.showerror("Delete Backup", str(exc), parent=dialog)
            refresh()

        listbox.bind("<<ListboxSelect>>", selected)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Restore...", command=restore).pack(side="left")
        ttk.Button(buttons, text="Delete Backup...", command=delete).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left", padx=(8, 0))
        dialog._vf1_listbox = listbox  # type: ignore[attr-defined]
        dialog._vf1_restore = restore  # type: ignore[attr-defined]
        dialog._vf1_delete = delete  # type: ignore[attr-defined]
        dialog._vf1_scope = scope  # type: ignore[attr-defined]
        dialog._vf1_slot_choice = slot_choice  # type: ignore[attr-defined]
        refresh()
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._hold(dialog)
        return dialog

    def _run_restore(self, parent: tk.Toplevel, folder: Path, info, slot: int | None) -> bool:
        """Confirm exactly what will change, then restore with the game closed. True if it restored."""
        if save_backup.running_game_count(folder):
            messagebox.showerror(
                "Restore Saves",
                f"{save_backup.game_exe_name(folder)} is running.\n\nQuit the game from its own menu first, then "
                "restore: a running game writes its family over the restored save the next time it saves (by itself "
                "every 10 minutes, or when it quits). Nothing was changed.",
                parent=parent)
            return False
        try:
            # Hashes both copies of every file, which can take a while: off the main thread, behind the wait.
            plan = self._run_with_wait("Checking the backup…",
                                       lambda: save_backup.plan_restore(folder, info.path, slot))
        except (save_backup.BackupError, OSError) as exc:
            messagebox.showerror("Restore Saves", str(exc), parent=parent)
            return False
        if plan.changes == 0:
            messagebox.showinfo("Restore Saves", "Your saves already match this backup; there is nothing to restore.",
                                parent=parent)
            return False
        what = "the whole save folder" if slot is None else f"Save {slot} only"
        lines = ([f"Replace: {path}" for path in plan.replace] + [f"Add: {path}" for path in plan.add]
                 + [f"Remove: {path}" for path in plan.remove])
        shown = "\n".join(lines[:20])
        if len(lines) > 20:
            shown += f"\n... and {len(lines) - 20} more"
        if not messagebox.askyesno(
            "Restore Saves",
            f"Restore {what} of {folder.name} from the backup of {info.label}?\n\n"
            f"{len(plan.replace)} file(s) will be replaced, {len(plan.add)} added and {len(plan.remove)} removed:"
            f"\n\n{shown}\n\nYour saves as they are now are backed up first, so this can be undone.",
            parent=parent,
        ):
            return False
        try:
            result = self._run_with_wait("Restoring saves…",
                                         lambda: save_backup.restore_backup(folder, info.path, slot))
        except (save_backup.BackupError, OSError) as exc:
            self.status_var.set("Restore Saves: the restore did not complete.")
            messagebox.showerror("Restore Saves", str(exc), parent=parent)
            return False
        undo = (f"\n\nYour saves from before the restore are in:\n{result.before_restore.backup_folder}"
                if result.before_restore else "")
        self.status_var.set(f"Restore Saves: {folder.name} restored from {info.label}.")
        messagebox.showinfo(
            "Restore Saves",
            f"Restored {what} from the backup of {info.label}: every file was checked against the backup.{undo}",
            parent=parent)
        return True

    # ------------------------------------------------------------------ Rename Family

    def rename_family(self) -> tk.Toplevel | None:
        """Pick a save folder and a family, then type the new name (the Virtual Villagers patcher's Rename Tribe).

        The family list is read from the saves and is only for choosing; the counter and every refusal come from
        vf1_rename_family. The rename itself runs off the main thread."""
        documents, folders = self._save_folders()
        if documents is None:
            messagebox.showerror("Rename Family", "Windows did not report where your Documents folder is, so the "
                                 "save folders cannot be found.")
            return None
        folders = [folder for folder in folders if any(s.name is not None for s in rename_family.read_slots(folder))]
        if not folders:
            messagebox.showinfo(
                "Rename Family",
                f"No modded family saves were found in {documents / 'LDW'}.\n\nStart a family in the modded game "
                "first; it makes its save folder then.")
            return None
        return self._show_rename_dialog(folders)

    def _show_rename_dialog(self, folders: list[Path]) -> tk.Toplevel:
        dialog, frame = self._scrolling_dialog("Rename Family")
        ttk.Label(
            frame,
            text=("Changes the family's name inside its save. The game must be closed: it saves when you quit it, "
                  "which would put the old name back. The save folder is backed up first, into <save folder>\\Backups"
                  "\\Backup <date and time> (before rename), and the family's Family History log gets one line "
                  "noting the new name."),
            wraplength=560, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        folder_var = tk.StringVar()
        name_var = tk.StringVar()
        counter_var = tk.StringVar()
        problem_var = tk.StringVar()
        state: dict = {"slots": []}

        ttk.Label(frame, text="Save folder:").grid(row=1, column=0, sticky="w")
        folder_box = ttk.Combobox(frame, textvariable=folder_var, values=[folder.name for folder in folders],
                                  state="readonly", width=48)
        folder_box.grid(row=1, column=1, columnspan=2, sticky="we", pady=2)
        ttk.Label(frame, text="Family:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        slot_list = tk.Listbox(frame, height=5, width=60, exportselection=False)
        slot_list.grid(row=2, column=1, columnspan=2, sticky="we", pady=(4, 2))
        ttk.Label(frame, text="New name:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        name_entry = ttk.Entry(frame, textvariable=name_var, width=36)
        name_entry.grid(row=3, column=1, sticky="w", pady=(8, 0))
        counter = ttk.Label(frame, textvariable=counter_var)
        counter.grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(frame, textvariable=problem_var, foreground="#a01010", wraplength=560, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
        rename_button = ttk.Button(buttons, text="Rename")
        rename_button.pack(side="left")
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left", padx=(8, 0))

        def folder() -> Path | None:
            index = folder_box.current()
            return folders[index] if 0 <= index < len(folders) else None

        def chosen_slot():
            picked = slot_list.curselection()
            return state["slots"][picked[0]] if picked else None

        def refresh_check(*_args) -> None:
            name = name_var.get()
            counter_var.set(f"{len(name)} / {rename_family.MAX_LENGTH} characters")
            counter.configure(foreground="#a01010" if len(name) > rename_family.MAX_LENGTH else "")
            info = chosen_slot()
            problem = None
            if folder() is None:
                problem = "No save folder was found for this game."
            elif info is None:
                problem = "Choose a family."
            elif info.problem:
                problem = info.problem
            elif name:
                problem = rename_family.name_problem(name)
                if problem is None and name == info.name:
                    problem = "That is already this family's name."
            problem_var.set(problem or "")
            ok = problem is None and bool(name)
            rename_button.configure(state="normal" if ok else "disabled")

        def load_slots(*_args) -> None:
            slot_list.delete(0, "end")
            state["slots"] = []
            where = folder()
            if where is not None:
                state["slots"] = rename_family.read_slots(where)
                for info in state["slots"]:
                    slot_list.insert("end", info.label)
                first = next((n for n, info in enumerate(state["slots"]) if not info.problem), None)
                if first is not None:
                    slot_list.selection_set(first)
            refresh_check()

        def start() -> None:
            info = chosen_slot()
            where = folder()
            if info is None or where is None:
                return
            new_name = name_var.get()
            problem = rename_family.name_problem(new_name)
            if problem is not None:
                messagebox.showerror("Rename Family", problem, parent=dialog)
                return
            if not messagebox.askyesno(
                    "Rename Family",
                    f"Rename \"{info.name or '(no name)'}\" (Save {info.slot}) in {where.name} to \"{new_name}\"?\n\n"
                    "The save folder is backed up first.", parent=dialog):
                return
            try:
                result = self._run_with_wait(
                    "Renaming the family…\n\nThe save folder is backed up first.",
                    lambda: rename_family.rename_family(where, info.slot, new_name))
            except (rename_family.RenameError, save_backup.BackupError, OSError) as exc:
                self.status_var.set("Rename Family: nothing was renamed.")
                messagebox.showerror("Rename Family", str(exc), parent=dialog)
                load_slots()
                return
            self.status_var.set(f"Rename Family: {result.old_name or '(no name)'} is now {result.new_name}.")
            messagebox.showinfo(
                "Rename Family",
                f"\"{result.old_name or '(no name)'}\" is now \"{result.new_name}\" (Save {result.slot}, "
                f"{where.name}).\n\n{len(result.changed)} save file(s) changed and read back; {len(result.notes)} "
                f"log(s) noted the rename.\n\nBackup: {result.backup.backup_folder}",
                parent=dialog)
            name_var.set("")
            load_slots()

        def choose(index: int) -> None:          # a click on a family (the tests)
            slot_list.selection_clear(0, "end")
            slot_list.selection_set(index)
            refresh_check()

        rename_button.configure(command=start)
        folder_box.bind("<<ComboboxSelected>>", load_slots)
        slot_list.bind("<<ListboxSelect>>", refresh_check)
        name_var.trace_add("write", refresh_check)
        frame.columnconfigure(1, weight=1)
        folder_box.current(0)
        load_slots()
        dialog._vf1_folder_box = folder_box  # type: ignore[attr-defined]
        dialog._vf1_folder_var = folder_var  # type: ignore[attr-defined]   # kept: a dropped StringVar empties its box
        dialog._vf1_slot_list = slot_list  # type: ignore[attr-defined]
        dialog._vf1_name_var = name_var  # type: ignore[attr-defined]
        dialog._vf1_counter_var = counter_var  # type: ignore[attr-defined]
        dialog._vf1_problem_var = problem_var  # type: ignore[attr-defined]
        dialog._vf1_rename_button = rename_button  # type: ignore[attr-defined]
        dialog._vf1_start = start  # type: ignore[attr-defined]
        dialog._vf1_choose = choose  # type: ignore[attr-defined]
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._hold(dialog, focus=name_entry)
        return dialog

    # ------------------------------------------------------------------ Game Mechanics

    def game_mechanics(self) -> tk.Toplevel:
        """Show how the game works underneath (patcher/vf1_game_mechanics.py). It only reads: no save, game file or
        install is opened or written. One window at a time; asking again brings it to the front."""
        window = getattr(self, "_game_mechanics_window", None)
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            return window
        window = game_mechanics.open_window(self.root)
        window.transient(self.root)
        self._game_mechanics_window = window
        return window

    # ------------------------------------------------------------------ Game Speed

    def game_speed(self) -> tk.Toplevel | None:
        """Pick a save folder and a family, then Paused or Normal, written into the closed game's save (laid out as
        Rename Family)."""
        documents, folders = self._save_folders()
        if documents is None:
            messagebox.showerror("Game Speed", "Windows did not report where your Documents folder is, so the "
                                 "save folders cannot be found.")
            return None
        folders = [folder for folder in folders if any(s.state is not None for s in game_speed.read_slots(folder))]
        if not folders:
            messagebox.showinfo(
                "Game Speed",
                f"No modded family saves were found in {documents / 'LDW'}.\n\nStart a family in the modded game "
                "first; it makes its save folder then.")
            return None
        return self._show_speed_dialog(folders)

    def _show_speed_dialog(self, folders: list[Path]) -> tk.Toplevel:
        dialog, frame = self._scrolling_dialog("Game Speed")
        ttk.Label(
            frame,
            text=("Sets a family's game speed inside its save. The game must be closed: it saves when you quit it, "
                  "which would put the old speed back. The save folder is backed up first, into <save folder>"
                  "\\Backups\\Backup <date and time> (before speed change). Paused works as if you paused just "
                  "before the game last saved; Normal as if you unpaused it now, so the paused time is never aged in. "
                  "Time Controls' Slow, Fast, 5x and 10x are not offered: the game never keeps them in a save and "
                  "always loads a family at Normal (or Paused)."),
            wraplength=560, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        folder_var = tk.StringVar()
        target_var = tk.StringVar(value="")
        problem_var = tk.StringVar()
        state: dict = {"slots": []}

        ttk.Label(frame, text="Save folder:").grid(row=1, column=0, sticky="w")
        folder_box = ttk.Combobox(frame, textvariable=folder_var, values=[folder.name for folder in folders],
                                  state="readonly", width=48)
        folder_box.grid(row=1, column=1, columnspan=2, sticky="we", pady=2)
        ttk.Label(frame, text="Family:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        slot_list = tk.Listbox(frame, height=5, width=60, exportselection=False)
        slot_list.grid(row=2, column=1, columnspan=2, sticky="we", pady=(4, 2))
        ttk.Label(frame, text="New speed:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        targets = ttk.Frame(frame)
        targets.grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 0))
        for name in game_speed.TARGETS:
            ttk.Radiobutton(targets, text=name, value=name, variable=target_var).pack(side="left", padx=(0, 14))
        ttk.Label(frame, textvariable=problem_var, foreground="#a01010", wraplength=560, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))
        set_button = ttk.Button(buttons, text="Set Speed")
        set_button.pack(side="left")
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="left", padx=(8, 0))

        def folder() -> Path | None:
            index = folder_box.current()
            return folders[index] if 0 <= index < len(folders) else None

        def chosen_slot():
            picked = slot_list.curselection()
            return state["slots"][picked[0]] if picked else None

        def check(*_args) -> None:
            info = chosen_slot()
            target = target_var.get()
            if folder() is None:
                problem = "No save folder was found for this game."
            elif info is None or info.state is None:
                problem = info.problem if info is not None and info.problem else "Choose a family."
            elif info.problem:
                problem = info.problem
            elif not target:
                problem = "Choose Paused or Normal."
            elif info.state.label == target:
                problem = f"This family is {target} already."
            else:
                problem = ""
            problem_var.set(problem)
            set_button.configure(state="disabled" if problem else "normal")

        def picked(*_args) -> None:
            info = chosen_slot()
            if info is not None and info.state is not None and info.problem is None:
                target_var.set(game_speed.NORMAL_NAME if info.state.kind == "paused" else game_speed.PAUSED)
            check()

        def load_slots(*_args) -> None:
            slot_list.delete(0, "end")
            state["slots"] = []
            where = folder()
            if where is not None:
                state["slots"] = game_speed.read_slots(where)
                for info in state["slots"]:
                    slot_list.insert("end", info.label)
                first = next((n for n, info in enumerate(state["slots"])
                              if info.state is not None and not info.problem), None)
                if first is not None:
                    slot_list.selection_set(first)
            picked()

        def start() -> None:
            info = chosen_slot()
            where = folder()
            target = target_var.get()
            check()
            if info is None or where is None or problem_var.get():
                return
            if not messagebox.askyesno(
                    "Game Speed",
                    f"Set \"{info.name or '(no name)'}\" (Save {info.slot}) in {where.name} from {info.state.label} "
                    f"to {target}?\n\nThe save folder is backed up first.", parent=dialog):
                return
            try:
                result = self._run_with_wait(
                    "Setting the game speed…\n\nThe save folder is backed up first.",
                    lambda: game_speed.set_speed(where, info.slot, target))
            except (game_speed.SpeedError, save_backup.BackupError, OSError) as exc:
                self.status_var.set("Game Speed: nothing was changed.")
                messagebox.showerror("Game Speed", str(exc), parent=dialog)
                load_slots()
                return
            self.status_var.set(f"Game Speed: Save {info.slot} is now {result.after}.")
            messagebox.showinfo(
                "Game Speed",
                f"\"{info.name or '(no name)'}\" is now {result.after} (Save {info.slot}, {where.name}); it was "
                f"{result.before}.\n\nThe save was changed and read back.\n\nBackup: {result.backup.backup_folder}",
                parent=dialog)
            load_slots()

        def choose(index: int) -> None:          # a click on a family (the tests)
            slot_list.selection_clear(0, "end")
            slot_list.selection_set(index)
            picked()

        set_button.configure(command=start)
        folder_box.bind("<<ComboboxSelected>>", load_slots)
        slot_list.bind("<<ListboxSelect>>", picked)
        target_var.trace_add("write", check)
        frame.columnconfigure(1, weight=1)
        folder_box.current(0)
        load_slots()
        dialog._vf1_folder_box = folder_box  # type: ignore[attr-defined]
        dialog._vf1_folder_var = folder_var  # type: ignore[attr-defined]   # kept: a dropped StringVar empties its box
        dialog._vf1_slot_list = slot_list  # type: ignore[attr-defined]
        dialog._vf1_target_var = target_var  # type: ignore[attr-defined]
        dialog._vf1_problem_var = problem_var  # type: ignore[attr-defined]
        dialog._vf1_set_button = set_button  # type: ignore[attr-defined]
        dialog._vf1_start = start  # type: ignore[attr-defined]
        dialog._vf1_choose = choose  # type: ignore[attr-defined]
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._hold(dialog)
        return dialog

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
