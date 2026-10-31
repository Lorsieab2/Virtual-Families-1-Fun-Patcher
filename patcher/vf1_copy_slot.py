"""Copy Player Slot: copy a family's save slot into an empty slot under a new name, in a closed game's saves.

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
      deletes "<N>.ldw" (0x41BF21 .., 0x423950 -> 0x4038F0). Without it the copy would look empty and a new
      family started there would replace it. No other byte of the options file changes.
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

Safety
    * The game must be closed (the running-game check Rename Family uses): a running game saves by itself
      every 10 minutes and when it quits, and would write the options file over the copy's slot-menu entry.
    * The target must be empty: its in-use flag clear and no "Virtual Families<T>.ldw". A slot in use is never
      written. Files a family deleted in the game left behind in an empty slot (its older copies, its patcher
      files, its folder) would mix with the copy, so they are cleared; they are in the backup first.
    * Before anything is written the whole save folder is backed up with Back Up Saves' own copier, labelled
      "(before copy)".
    * Every file is written beside itself and swapped in with os.replace, then read back. The options file is
      written last, so the slot appears in the menu only once everything else is in place. Any failure puts
      every file back as it was and removes everything the copy made.
    * Nothing of the source slot or of any other slot is written.

Nothing here touches Tk; the GUI runs it on a worker thread, and the tests drive it against a temporary save
folder with a fake process list.
"""
from __future__ import annotations

import json
import os
import re
import struct
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
        """A slot a copy may go into: the menu shows it empty and it has no save."""
        return self.used is False and not self.has_save

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
    clear: list[tuple[Path, bytes]] = field(default_factory=list)  # a deleted family's leftovers in the target
    options: Write | None = None                                   # written last
    left_out: list[Path] = field(default_factory=list)            # the source's files not copied (and why: above)


def _rebind_children(data: bytes, sources: dict[int, bytes], targets: dict[int, bytes]) -> tuple[bytes, bool]:
    """A Children file made to describe the copy of the source save it described; unchanged if it described none."""
    sidecar = gen.read_children_sidecar(data)
    if sidecar is None:
        return data, False
    for number, source in sources.items():
        if sidecar.save_size == len(source) and sidecar.save_hash == gen.fnv1a64(source):
            copy = targets[number]
            if copy == source:
                return data, False
            out = bytearray(data)
            struct.pack_into("<QI", out, 24, gen.fnv1a64(copy), len(copy))
            struct.pack_into("<Q", out, len(out) - 8, gen.fnv1a64(bytes(out[:-8])))
            return bytes(out), True
    return data, False


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


def plan_copy(folder: Path, source: int, target: int, new_name: str, when: datetime) -> CopyPlan:
    """Every file the copy writes, and every leftover it clears. Raises CopyError (nothing changed) on a refusal."""
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
    if options[used_at] != 0 or rename.save_path(folder, target).exists():
        raise CopyError(f"Save {target} is in use. Copy Player Slot only copies into an empty slot; nothing was changed.")

    plan = CopyPlan(folder, source, target, old, new_name)
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

    # What a family deleted in the game left in the target: cleared (it is in the backup first).
    written = {str(w.path).casefold() for w in plan.writes}
    for relative in slot_files(folder, target):
        raw = _read(folder / relative)
        if str(relative).casefold() in written:
            next(w for w in plan.writes if str(w.path).casefold() == str(relative).casefold()).original = raw
        else:
            plan.clear.append((relative, raw))
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
    cleared: list[Path] = field(default_factory=list)
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


def _undo(folder: Path, done: list[Write], cleared: list[tuple[Path, bytes]], made: list[Path]) -> list[str]:
    """Put back every file the copy wrote or cleared and remove the folders it made; the ones that could not be."""
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
    for relative, original in reversed(cleared):
        path = folder / relative
        try:
            if not path.exists() or path.read_bytes() != original:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_atomically(path, original)
        except (OSError, CopyError) as exc:
            problems.append(f"{relative}: {exc}")
    for directory in sorted(made, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
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


def copy_slot(
    folder: Path,
    source: int,
    target: int,
    new_name: str,
    processes: save_backup.ProcessController | None = None,
    now: datetime | None = None,
) -> CopyResult:
    """Copy save slot ``source`` of ``folder`` into the empty slot ``target`` as ``new_name``.

    Refused (CopyError, nothing changed) when the name breaks the rule, the game is running, the target is in
    use, or the saves cannot be read. Otherwise the folder is backed up first, every file is written through a
    temporary file and read back, the options file last, and any failure puts everything back.
    """
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    when = now or datetime.now()
    _refuse_if_running(folder, controller)
    plan = plan_copy(folder, source, target, new_name, when)
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise CopyError(f"The backup before copying failed, so nothing was changed. {exc}") from exc
    # The backup took a moment; the game may have been started meanwhile.
    _refuse_if_running(folder, controller)
    done: list[Write] = []
    cleared: list[tuple[Path, bytes]] = []
    made: list[Path] = []
    try:
        for write in plan.writes:
            path = folder / write.path
            current = path.read_bytes() if path.exists() else None
            if current != write.original:
                raise CopyError(f"{write.path} changed while the copy was being made.")
            _make_folders(path, made)
            done.append(write)
            _write_atomically(path, write.data)
        for relative, original in plan.clear:
            path = folder / relative
            if path.read_bytes() != original:
                raise CopyError(f"{relative} changed while the copy was being made.")
            cleared.append((relative, original))
            path.unlink()
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
        problems = _undo(folder, done, cleared, made)
        if problems:
            raise CopyError(
                f"The copy failed ({exc}) and these files could not be put back: {'; '.join(problems)}. "
                f"Your backup is in {backup.backup_folder}."
            ) from exc
        raise CopyError(
            f"The copy failed ({exc}); everything was put back as it was. A backup is in {backup.backup_folder}."
        ) from exc
    # Folders the cleared leftovers emptied (never the slot's Backups) are tidied away.
    for relative, _original in plan.clear:
        parent = (folder / relative).parent
        while parent != folder and parent.name.casefold() not in (DATA.casefold(), LOGS_ROOT.casefold()):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return CopyResult(folder, source, target, plan.old_name, new_name, backup,
                      [w.path for w in plan.writes] + [plan.options.path], [r for r, _ in plan.clear], plan.left_out)
