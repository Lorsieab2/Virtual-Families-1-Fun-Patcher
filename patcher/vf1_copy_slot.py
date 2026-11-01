"""Copy Player Slot: copy a family's save slot into another slot (empty, or replacing a family when asked) under a
new name, in a closed game's saves.

The Fish & Plant Tycoon patcher's Copy Slot idea, built on Virtual Families 1's own save layout
(docs/vf1-save-format.md section 1, every file below listed there).

What a slot is (source S, target T; every file is copied with S's numbers changed to T's)
    The game's files, in the save folder:
      * "Virtual Families<S>.ldw", the family, and its two older autosave copies "<S+20>.ldw" and "<S+40>.ldw";
    the patcher's files in "Virtual Families 1 Patcher Data":
      * "Slot <S>.ini" (vf1fun: the bought purchases, Food Club, the price multiplier ...),
      * "Children\\Virtual Families<n>.ldw.dat" for n = S, S+20, S+40, and any "...ldw.unreadable-<k>.dat"
        (vf1kids, Up to 28 Children),
      * "Outfits\\Virtual Families<n>.ldw.dat" and any "...ldw.unreadable-<k>.dat" (vf1fun, each outfit's
        picture);
    and the slot's own folder "Virtual Families 1 Patcher\\Save <S>":
      * "Logs\\Family History\\Family History <k>.txt" (vf1logs, the Family History log),
      * "Data\\Family Tree\\..." (the Family Tree Maker's .tree file and edits).

What changes in the copy, and why each copied file still matches the copied save
    * The family name in the copied save (theGameState+0x1B12C), and in an older copy that holds the source's
      name, is the new name; nothing else in the save changes. The save holds no slot number (the saved range
      ends before theGameState+0x1B188), so the copy is the same family, at the same moment.
    * The options file "Virtual Families0.ldw" gets the target's slot-menu name (gs+0x1B192 + 0x15 x (T - 1))
      and the target's in-use flag (gs+0x1B1FB + (T - 1)) set to 1. The flag is what the slot menu goes by,
      traced in the stock exe: the menu draws a slot's name only when its flag is set (0x41BB1A .. 0x41BDBD)
      and otherwise shows it as empty, a new family sets it (0x41C1A7 ..), and deleting a family clears it and
      deletes "<N>.ldw" (0x41BF21 .., 0x423950 -> 0x4038F0). These two are the only per-slot fields of the
      options file (docs/vf1-save-format.md section 1.2 lists every field), and they are written as the game itself
      would: at every start theGameState::Load 0x4247C0 loads each "<N>.ldw" and gives a save that loads its
      family name and a set flag. No other byte of the options file changes.
    * Nothing of a slot lives outside the save folder: the exe keeps nothing per slot in the registry (its
      registry calls are ATL's COM registrar) or anywhere else, and the patcher keeps nothing per slot outside the
      files above (settings.ini, beside the DLLs, is shared).
    * The Children files are tied to their save's bytes: each names the FNV-1a 64 hash and size of the save it
      was written with, and vf1kids takes the children from it only when the loaded save still has them
      (vf1kids.cpp AfterLoad). The new name changes the save's bytes, so a Children file that described one
      of the source's saves is rewritten to describe its copy (hash, size and the file's own checksum; nothing
      else). One that described no source save is copied as it is, exactly as the source has it.
    * The Outfits files are tied to the tray and the inventory's outfit fields, not to the save's bytes or
      name (outfits.inc DecodeOutfits), and the copy keeps those fields, so they are copied as they are.
    * "Slot <S>.ini" holds nothing about its slot or name; it is copied as it is.
    * The Family Tree Maker's files are named after their slot ("... - Save <S>.tree", "... Edits - Save
      <S>.json"), so they are renamed for T, and the tree file's own "slot" (and, for the family's current
      tree file, "family") are set to T and the new name.
    * The Family History log is copied whole (logs are never rewritten, so old files keep their "Family: ...
      (Save S)" header); its newest file ends with one more record, in the log's own layout:
      "[YYYY-MM-DD HH:MM:SS] Family Copied <n>", "  Copied from: Save <S>", "  Old name: ...", "  New name: ...".
    * Not copied: "Save <S>\\Family Tree" (the Family Tree Maker's page and pictures, made again from the save
      each time; a copy would show the source's name and slot) and "Save <S>\\Backups".

Which slots are empty (the owner, 2026-11-01: "the game sees (game name)1-5.ldw as player slots")
    * A slot is empty when "Virtual Families<T>.ldw" is not there, whatever the options file's name and in-use
      flag for it say; a slot whose save is there holds a family (and can be copied from), whatever they say.
      This is what the game itself does: at every start theGameState::Load 0x4247C0 rebuilds each slot's in-use
      flag from whether "<N>.ldw" loads (0x424891 Load(N); 0x4248B0 flag = 1 on success, 0x4248CB flag = 0 on
      failure), and the Change Player list and its New Player go by that flag (0x41BB1A .. 0x41BDBD, 0x41C1A7 ..).
      A stale name and set flag with no save are cleared by the game's next start; the copy writes the target's
      name and sets its flag, so the menu shows and loads the copy at once.

Replacing a family (the owner, 2026-11-01: "able to overwrite existing slots, with a confirmation prompt")
    * Any slot but the source may be the target. A target that holds a family is replaced only when asked
      (replace=True, after the GUI's Yes / No question names the family that will be replaced).

Safety
    * The game must be closed (the running-game check Rename Family uses): a running game saves by itself
      every 10 minutes and when it quits, and would write the options file over the copy's slot-menu entry.
    * Before anything is written the whole save folder is backed up with Back Up Saves' own copier, labelled
      "(before copy)".
    * Then everything already in the target slot (the replaced family's save, or what a family deleted in the
      game left behind: the older copies <T+20> / <T+40>, "Slot <T>.ini", the Children and Outfits files of
      T, T+20 and T+40, and the whole "Virtual Families 1 Patcher\\Save <T>" folder) is moved, never deleted,
      into "Backups\\Replaced by copy <date>" keeping its path, so nothing of the old family stays attached to the
      copy. No game or patcher code reads that folder (Restore Saves lists only "Backup <date>" folders).
    * Every file is written beside itself and swapped in with os.replace, then read back. The options file is
      written last, so the slot appears in the menu only once everything else is in place. Any failure removes
      everything the copy made, moves every set-aside file back and puts the options file back as it was.
    * Nothing of the source slot or of any slot but the target is written.

Nothing here touches Tk; the GUI runs it on a worker thread, and the tests drive it against a temporary save
folder with a fake process list.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_genealogy as gen
import vf1_rename_family as rename
import vf1_save as save_format
import vf1_save_backup as save_backup
import vf1_tree_memory

SLOTS = rename.SLOTS
BACKUP_LABEL = save_backup.BEFORE_COPY
OPTIONS_SLOT_USED = 0x1B1FB             # theGameState offset of slot 1's in-use flag (one byte per slot)
LOGS_ROOT = rename.LOGS_ROOT             # "Virtual Families 1 Patcher"
DATA = save_format.PATCHER_DATA          # "Virtual Families 1 Patcher Data"
NOT_COPIED = ("Backups", "Family Tree")  # in Save <S>: its backups, and the tree's page and pictures
REPLACED = "Replaced by copy"            # Backups\Replaced by copy <date>: what was in the target slot
_SIDECAR = re.compile(r"^Virtual Families(\d+)\.ldw(\.unreadable-\d+)?\.dat$", re.IGNORECASE)
_COPIED = re.compile(r"^\[[^\]]*\] Family Copied (\d+)\r?$", re.MULTILINE)


class CopyError(Exception):
    """A copy that was refused or failed, with a reason a player can read."""


class GameRunning(CopyError):
    """The game that uses this save folder is running."""


# ---------------------------------------------------------------------------
# Reading the slots
# ---------------------------------------------------------------------------


def _used_offset(options: bytes, slot: int) -> int | None:
    size = rename._header(options, save_format.OPTIONS_SIZE)
    if size is None:
        return None
    return size + OPTIONS_SLOT_USED - save_format.GS_SAVED_END + (slot - 1)


def slot_used(options: bytes, slot: int) -> bool | None:
    """Slot ``slot``'s in-use flag in the options file's bytes, or None if they are not an options file."""
    offset = _used_offset(options, slot)
    return None if offset is None else options[offset] != 0


@dataclass
class SlotInfo:
    slot: int
    name: str | None              # the family name in the slot's save, or None
    has_save: bool                # "Virtual Families<N>.ldw" is there
    used: bool | None             # the slot menu's in-use flag, None when the options file cannot be read
    problem: str | None = None    # why it cannot be copied FROM

    @property
    def empty(self) -> bool:
        """No "Virtual Families<N>.ldw": the game sees no family here, whatever the options file says."""
        return not self.has_save

    @property
    def label(self) -> str:
        if self.empty:
            return f"Save {self.slot}: (empty)"
        if self.name is None:
            return f"Save {self.slot}: (in use, cannot be read)" if self.has_save else f"Save {self.slot}: (in use)"
        return f"Save {self.slot}: {self.name or '(no name)'}"


def read_slots(folder: Path) -> list[SlotInfo]:
    """Each slot: its family name, and whether it is empty."""
    try:
        options = rename.options_path(folder).read_bytes()
    except OSError:
        options = b""
    out: list[SlotInfo] = []
    for slot in SLOTS:
        path = rename.save_path(folder, slot)
        used = slot_used(options, slot) if options else None
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            out.append(SlotInfo(slot, None, False, used, "This slot has no family."))
            continue
        except OSError as exc:
            out.append(SlotInfo(slot, None, True, used, f"The save could not be read: {exc}"))
            continue
        name = rename.save_name(data)
        info = SlotInfo(slot, name, True, used)
        if name is None:
            info.problem = f"{path.name} is not a Virtual Families save this tool can read."
        elif used is None:
            info.problem = f"The slot menu file {rename.options_path(folder).name} could not be read."
        out.append(info)
    return out


# ---------------------------------------------------------------------------
# Which files are a slot's
# ---------------------------------------------------------------------------


def slot_root(folder: Path, slot: int) -> Path:
    return gen.slot_root(folder, slot)


def _numbers(slot: int) -> tuple[int, int, int]:
    return slot, slot + 20, slot + 40


def _renumber(name: str, source: int, target: int) -> str:
    """A game or sidecar file name of save number n (n = S, S+20, S+40) with T's number."""
    match = re.match(r"^(Virtual Families)(\d+)(\..*)$", name, re.IGNORECASE)
    if not match:
        return name
    number = int(match.group(2))
    return f"{match.group(1)}{number - source + target}{match.group(3)}"


def _slot_name(name: str, source: int, target: int) -> str:
    """A file name in Save <S> that names its slot ("... - Save 3.tree") with T's number."""
    return re.sub(rf"(?<=- Save ){source}(?!\d)", str(target), name)


def slot_files(folder: Path, slot: int) -> list[Path]:
    """Every file of ``slot`` in ``folder`` (relative paths): the game's three, the patcher's data files, and
    everything in Save <slot> but its Backups folder."""
    out: list[Path] = []
    for number in _numbers(slot):
        name = f"{save_format.SAVE_PREFIX}{number}.ldw"
        if (folder / name).is_file():
            out.append(Path(name))
    ini = Path(DATA) / f"Slot {slot}.ini"
    if (folder / ini).is_file():
        out.append(ini)
    for sub in ("Children", "Outfits"):
        where = folder / DATA / sub
        try:
            entries = sorted(where.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            entries = []
        for entry in entries:
            match = _SIDECAR.match(entry.name)
            if match and entry.is_file() and int(match.group(1)) in _numbers(slot):
                out.append(Path(DATA) / sub / entry.name)
    root = slot_root(folder, slot)
    if root.is_dir():
        for relative in save_backup.files_to_back_up(root):        # every file there but its Backups folder
            out.append(root.relative_to(folder) / relative)
    return out


def leftovers(folder: Path, slot: int) -> list[Path]:
    """Everything already in ``slot`` (relative paths), which the copy moves aside before it writes: the game's
    "<N>.ldw" / "<N+20>.ldw" / "<N+40>.ldw", "Slot <N>.ini", the Children and Outfits files of those numbers, and
    the whole "Virtual Families 1 Patcher\\Save <N>" folder (its Backups included, kept with it)."""
    out = [path for path in slot_files(folder, slot) if path.parts[0].casefold() != LOGS_ROOT.casefold()]
    root = slot_root(folder, slot)
    if root.exists():
        out.append(root.relative_to(folder))
    return out


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def set_aside_folder(folder: Path, when: datetime, slot: int, old_name: str | None) -> Path:
    """A new "Backups\\Replaced by copy <date> - Save <N> - <old name>" folder name (not made yet)."""
    name = _UNSAFE.sub("_", old_name or "").strip(" .") or "(no name)"
    base = f"{REPLACED} {when.strftime('%Y-%m-%d %H-%M-%S')} - Save {slot} - {name}"
    backups = folder / save_backup.BACKUPS_FOLDER
    for attempt in range(1, 1000):
        candidate = backups / (base if attempt == 1 else f"{base} ({attempt})")
        if not candidate.exists():
            return candidate
    raise CopyError(f"Too many folders named {base} in {backups}.")


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass
class Write:
    path: Path                    # where, in the save folder
    data: bytes
    original: bytes | None        # what was there (None: nothing)
    what: str = ""


@dataclass
class CopyPlan:
    folder: Path
    source: int
    target: int
    old_name: str
    new_name: str
    writes: list[Write] = field(default_factory=list)            # the copy's files
    set_aside: list[Path] = field(default_factory=list)          # what is in the target now, moved aside first
    aside_folder: Path | None = None                              # Backups\Replaced by copy <date> - Save <T> - ...
    replaced_name: str | None = None                              # the family the copy replaces (None: none, or unreadable)
    target_save: bytes | None = None                              # the target's save as read (None: empty slot)
    options: Write | None = None                                   # written last
    left_out: list[Path] = field(default_factory=list)            # the source's files not copied (and why: above)


def _rebind_children(data: bytes, sources: dict[int, bytes], targets: dict[int, bytes]) -> tuple[bytes, bool]:
    """A Children file made to describe the copy of the source save it described; unchanged if it described none."""
    rekeyed = gen.rekey_children_sidecar(data, [(source, targets[number]) for number, source in sources.items()])
    return (data, False) if rekeyed is None else (rekeyed, True)


def _rewrite_tree(data: bytes, name: str, source: int, target: int, new_name: str) -> bytes:
    """A Family Tree Maker tree file for the target: its "slot", and for the current one its "family"."""
    try:
        tree = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data
    if not isinstance(tree, dict) or tree.get("format") != vf1_tree_memory.FORMAT:
        return data
    if tree.get("slot") == source:
        tree["slot"] = target
    if name == f"Virtual Families 1 Family Tree - Save {source}.tree" and "family" in tree:
        tree["family"] = new_name
    return json.dumps(tree, indent=1).encode("utf-8")


def history_record(source: int, old: str, new: str, when: datetime, number: int) -> str:
    return (f"[{when.strftime('%Y-%m-%d %H:%M:%S')}] Family Copied {number}\r\n"
            f"  Copied from: Save {source}\r\n  Old name: {old or '(no name)'}\r\n  New name: {new}\r\n\r\n")


def _history_number(path: Path) -> int | None:
    match = re.match(r"^Family History (\d+)\.txt$", path.name, re.IGNORECASE)
    if match and len(path.parts) >= 3 and [p.casefold() for p in path.parts[-3:-1]] == ["logs", "family history"]:
        return int(match.group(1))
    return None


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CopyError(f"Could not read {path.name}: {exc}") from exc


def plan_copy(folder: Path, source: int, target: int, new_name: str, when: datetime,
              replace: bool = False) -> CopyPlan:
    """Every file the copy writes, and everything in the target it moves aside. A target that holds a family is
    refused unless ``replace``. Raises CopyError (nothing changed) on a refusal."""
    if source not in SLOTS or target not in SLOTS:
        raise CopyError("There are only save slots 1 to 5.")
    if source == target:
        raise CopyError("Choose another slot to copy into.")
    problem = rename.name_problem(new_name)
    if problem is not None:
        raise CopyError(problem)
    save = rename.save_path(folder, source)
    try:
        data = save.read_bytes()
    except FileNotFoundError as exc:
        raise CopyError(f"Save {source} has no family ({save.name} is missing).") from exc
    except OSError as exc:
        raise CopyError(f"Could not read {save.name}: {exc}") from exc
    old = rename.save_name(data)
    if old is None:
        raise CopyError(f"{save.name} is not a Virtual Families save this tool can read.")
    options_file = rename.options_path(folder)
    options = _read(options_file)
    menu_at = rename._menu_name_offset(options, target)
    used_at = _used_offset(options, target)
    if menu_at is None or used_at is None or rename.menu_name(options, target) is None:
        raise CopyError(f"The slot menu file {options_file.name} is not one this tool can read.")
    # The game's own test: a slot holds a family when its "<N>.ldw" is there; the options file's flag and name
    # for it are only what the menu showed at the last start (module docstring).
    target_file = rename.save_path(folder, target)
    target_save = _read(target_file) if target_file.exists() else None
    if target_save is not None and not replace:
        raise CopyError(f"Save {target} holds a family. Copy Player Slot replaces a family only when you answer Yes "
                        "to replacing it; nothing was changed.")

    plan = CopyPlan(folder, source, target, old, new_name)
    plan.target_save = target_save
    if target_save is not None:
        plan.replaced_name = rename.save_name(target_save)
        aside_name = plan.replaced_name
    else:
        aside_name = rename.menu_name(options, target) if options[used_at] else None
    plan.set_aside = leftovers(folder, target)
    if plan.set_aside:
        plan.aside_folder = set_aside_folder(folder, when, target, aside_name)
    # The game's files: the name in each that holds the source's.
    sources: dict[int, bytes] = {}
    targets: dict[int, bytes] = {}
    for number in _numbers(source):
        path = folder / f"{save_format.SAVE_PREFIX}{number}.ldw"
        if not path.is_file():
            continue
        raw = data if number == source else _read(path)
        copy = raw
        at = rename._save_name_offset(raw)
        if at is not None and rename.save_name(raw) == old:
            copy = rename._with_name(raw, at, rename.FAMILY_NAME_FIELD, new_name)
        sources[number], targets[number] = raw, copy
    newest_history: tuple[int, int] | None = None     # (file number, index in writes)
    copied_numbers: list[int] = []
    for relative in slot_files(folder, source):
        parts = relative.parts
        if len(parts) == 1:
            dest = relative.with_name(_renumber(relative.name, source, target))
        elif parts[0].casefold() == LOGS_ROOT.casefold():
            inner = Path(*parts[2:])
            if inner.parts and inner.parts[0].casefold() in (p.casefold() for p in NOT_COPIED) and len(inner.parts) > 1:
                plan.left_out.append(relative)
                continue
            renamed = Path(*[_slot_name(p, source, target) for p in inner.parts])
            dest = Path(LOGS_ROOT) / f"Save {target}" / renamed
        elif len(parts) == 2:                                       # Virtual Families 1 Patcher Data\Slot <S>.ini
            dest = relative.with_name(f"Slot {target}.ini")
        else:                                                       # a game file, or a Children / Outfits file
            dest = relative.with_name(_renumber(relative.name, source, target))
        raw = data if relative == Path(save.name) else _read(folder / relative)
        what = "copied"
        if len(parts) == 1:                                           # a game file
            number = int(re.search(r"(\d+)\.ldw$", relative.name).group(1))
            body = targets.get(number, raw)
            what = "renamed" if body != raw else "copied"
        elif parts[0].casefold() == DATA.casefold() and len(parts) == 3 and parts[1].casefold() == "children":
            body, rebound = _rebind_children(raw, sources, targets)
            what = "matched to the copy" if rebound else "copied"
        elif relative.suffix.lower() == ".tree":
            body = _rewrite_tree(raw, relative.name, source, target, new_name)
            what = "renamed" if body != raw else "copied"
        else:
            body = raw
        plan.writes.append(Write(dest, body, None, what))
        number = _history_number(relative)
        if number is not None:
            copied_numbers.append(len(plan.writes) - 1)
            if newest_history is None or number > newest_history[0]:
                newest_history = (number, len(plan.writes) - 1)
    if newest_history is not None:
        count = 1
        for index in copied_numbers:
            text = plan.writes[index].data.decode("cp1252", errors="replace")
            count = max([count] + [int(n) + 1 for n in _COPIED.findall(text)])
        newest = plan.writes[newest_history[1]]
        prefix = b"" if not newest.data or newest.data.endswith(b"\n") else b"\r\n"
        newest.data += prefix + history_record(source, old, new_name, when, count).encode("ascii")
        newest.what = "copied, with a Family Copied record"

    menu = rename._with_name(options, menu_at, rename.OPTIONS_NAME_STRIDE, new_name)
    menu = menu[:used_at] + b"\x01" + menu[used_at + 1:]
    plan.options = Write(Path(options_file.name), menu, options, "slot menu")
    return plan


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _write_atomically(path: Path, data: bytes) -> None:
    """Replace (or make) ``path`` with ``data`` through a temporary file beside it, then verify."""
    temporary = path.with_name(f"{path.name}.copy-{uuid.uuid4().hex[:12]}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    if path.read_bytes() != data:
        raise CopyError(f"{path.name} did not read back as written.")


@dataclass
class CopyResult:
    folder: Path
    source: int
    target: int
    old_name: str
    new_name: str
    backup: save_backup.BackupResult
    written: list[Path] = field(default_factory=list)
    set_aside: list[Path] = field(default_factory=list)       # what was in the target (relative to the save folder)
    aside_folder: Path | None = None                           # where it went: Backups\Replaced by copy <date> - ...
    replaced: bool = False                                     # the target held a family
    replaced_name: str | None = None
    left_out: list[Path] = field(default_factory=list)


def _refuse_if_running(folder: Path, processes: save_backup.ProcessController) -> None:
    exe = save_backup.game_exe_name(folder)
    try:
        running = processes.find(exe)
    except (OSError, save_backup.BackupError) as exc:
        raise CopyError(f"Could not check whether {exe} is running, so nothing was changed ({exc}).") from exc
    if running:
        raise GameRunning(
            f"{exe} is running. Close the game first (quit it normally from its menu): it saves by itself "
            "every 10 minutes and when it quits, which would write over the copy's place in the slot menu. "
            "Nothing was changed."
        )


def _remove_folders(made: list[Path]) -> None:
    for directory in sorted(made, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def _undo(folder: Path, done: list[Write], made: list[Path], moved: list[tuple[Path, Path]],
          aside_made: list[Path]) -> list[str]:
    """Remove every file the copy wrote (the options file put back), move every set-aside file back, and remove
    the folders the copy made; the ones that could not be."""
    problems: list[str] = []
    for write in reversed(done):
        path = folder / write.path
        try:
            if write.original is None:
                if path.exists():
                    path.unlink()
            elif not path.exists() or path.read_bytes() != write.original:
                _write_atomically(path, write.original)
        except (OSError, CopyError) as exc:
            problems.append(f"{write.path}: {exc}")
    _remove_folders(made)                       # a new "Save <T>" first, so the old one can move back
    for relative, aside in reversed(moved):
        try:
            os.rename(aside, folder / relative)
        except OSError as exc:
            problems.append(f"{relative} (it is in {aside}): {exc}")
    _remove_folders(aside_made)
    return problems


def _make_folders(path: Path, made: list[Path]) -> None:
    missing: list[Path] = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir()
        made.append(directory)


def _target_as_planned(plan: CopyPlan) -> None:
    """The target holds what the plan read: the same save (or none), and the same files to move aside."""
    path = rename.save_path(plan.folder, plan.target)
    now = path.read_bytes() if path.exists() else None
    if now != plan.target_save:
        raise CopyError(f"Save {plan.target} changed while the copy was being made.")
    if {str(p).casefold() for p in leftovers(plan.folder, plan.target)} != {str(p).casefold() for p in plan.set_aside}:
        raise CopyError(f"The files of Save {plan.target} changed while the copy was being made.")


def copy_slot(
    folder: Path,
    source: int,
    target: int,
    new_name: str,
    processes: save_backup.ProcessController | None = None,
    now: datetime | None = None,
    replace: bool = False,
) -> CopyResult:
    """Copy save slot ``source`` of ``folder`` into slot ``target`` as ``new_name``.

    A target that holds a family is replaced only with ``replace`` (the GUI asks first). Refused (CopyError,
    nothing changed) when the name breaks the rule, the game is running, the target holds a family and
    ``replace`` is not set, or the saves cannot be read. Otherwise the folder is backed up first, everything in the
    target is moved into Backups\\Replaced by copy <date> - Save <T> - <old name>, every file is written through a
    temporary file and read back, the options file last, and any failure puts everything back.
    """
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    when = now or datetime.now()
    _refuse_if_running(folder, controller)
    plan = plan_copy(folder, source, target, new_name, when, replace=replace)
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise CopyError(f"The backup before copying failed, so nothing was changed. {exc}") from exc
    # The backup took a moment; the game may have been started meanwhile.
    _refuse_if_running(folder, controller)
    done: list[Write] = []
    made: list[Path] = []
    moved: list[tuple[Path, Path]] = []
    aside_made: list[Path] = []
    try:
        _target_as_planned(plan)
        if plan.aside_folder is not None:
            if plan.aside_folder.exists():
                raise CopyError(f"{plan.aside_folder.name} is already there; try again in a moment.")
            for relative in plan.set_aside:
                aside = plan.aside_folder / relative
                _make_folders(aside, aside_made)
                os.rename(folder / relative, aside)
                moved.append((relative, aside))
        for write in plan.writes:
            path = folder / write.path
            if path.exists():
                raise CopyError(f"{write.path} changed while the copy was being made.")
            _make_folders(path, made)
            done.append(write)
            _write_atomically(path, write.data)
        _refuse_if_running(folder, controller)
        options = plan.options
        assert options is not None
        if (folder / options.path).read_bytes() != options.original:
            raise CopyError(f"{options.path} changed while the copy was being made.")
        done.append(options)
        _write_atomically(folder / options.path, options.data)
        # Read the copy back through the same readers the slot list uses.
        menu = (folder / options.path).read_bytes()
        copied = rename.save_path(folder, target).read_bytes()
        if rename.save_name(copied) != new_name or rename.menu_name(menu, target) != new_name \
                or slot_used(menu, target) is not True:
            raise CopyError(f"Save {target} does not hold the new name.")
        save_format.parse_save(copied)
        for write in plan.writes:
            if (folder / write.path).read_bytes() != write.data:
                raise CopyError(f"{write.path} did not read back as written.")
    except (OSError, CopyError, save_format.SaveFormatError) as exc:
        problems = _undo(folder, done, made, moved, aside_made)
        if problems:
            raise CopyError(
                f"The copy failed ({exc}) and these files could not be put back: {'; '.join(problems)}. "
                f"Your backup is in {backup.backup_folder}."
            ) from exc
        raise CopyError(
            f"The copy failed ({exc}); everything was put back as it was. A backup is in {backup.backup_folder}."
        ) from exc
    return CopyResult(folder, source, target, plan.old_name, new_name, backup,
                      [w.path for w in plan.writes] + [plan.options.path], list(plan.set_aside), plan.aside_folder,
                      plan.target_save is not None, plan.replaced_name, plan.left_out)
