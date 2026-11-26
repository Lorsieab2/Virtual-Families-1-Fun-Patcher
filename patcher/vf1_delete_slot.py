"""Delete Player Slot: send every file tied to one save slot to the Windows Recycle Bin.

The Virtual Villagers Fun Patcher's Delete (its src/vv_delete_slot.py; the owner, 2026-11-23: the Copy Player Slot
window's "Delete" choice sends EVERY file linked to a save slot to the Recycle Bin -- "files linked to save slots =
logs, sidecars, backups, family tree files (NOT images) etc"). Nothing is ever deleted for good: every file goes
through the Windows shell's Recycle Bin (vf1_translations.recycle: SHFileOperationW with FOF_ALLOWUNDO), so the
player can put any of it back from there. No new backup is made (the owner: the Recycle Bin is the way back).

What goes (Move Player Slot's list, patcher/vf1_move_slot.py slot_everything, so the two never disagree)
    * The slot save "Virtual Families<S>.ldw" and the game's older copies "<S+20>.ldw" / "<S+40>.ldw";
      "Slot <S>.ini" and the Children, Outfits and Names files of S, S+20 and S+40 in "Virtual Families 1 Patcher
      Data"; everything in "Virtual Families 1 Patcher\\Save <S>" (the Family History log, the Family Tree Maker's
      files and its Backups folder).
    * In every whole-folder backup in "Backups" (a "Backup <date> ..." folder, or a copy that stopped part-way):
      only that slot's files, found the same way inside the backup, so every other slot of every backup can still
      be restored. And the slot's own "Replaced by copy/move <date> - Save <S> - ..." folders.
    NOT recycled: pictures (.png, .jpg, .jpeg, .bmp, .gif) -- the owner: "NOT images". They stay where they are and
    the list shows them as kept.
    (The Virtual Villagers patcher also keeps the lines of its "Copies Index" files for the recycled repair copies,
    so a Recycle Bin restore finds them again. Virtual Families 1's patcher keeps no repair copies and no index, so
    there is nothing of that kind to keep here; nothing outside the slot's own files is written but the slot menu.)

Order and safety
    * Refused while the game runs. The player sees every file first (`Plan.preview`) and is asked twice; what they
      confirmed is fingerprinted (each file's size and time, the slot menu's bytes), and anything changed since
      refuses.
    * The save folder's own files go first, then each backup's, then the set-aside folders. If Windows refuses a
      batch, everything stops and the result says what went and what did not (every file checked).
    * Fast (the Virtual Villagers patcher's PR #876, the owner 2026-11-25: "almost instant"): one Recycle Bin call
      for each of those parts; a folder that holds nothing but the slot's files (no picture, no other file, no
      link), 30 or more, sent whole as one item; and the drive's "is there a Recycle Bin?" question asked once,
      while the player reads the list (vf1_translations.check_recycle_bins: a drive with none is refused, never a
      permanent delete).
    * The slot menu "Virtual Families0.ldw" is written LAST -- and also after a failure once the slot's save is
      gone -- with only the slot's in-use flag cleared, exactly what the game's own Delete Family does
      (docs/vf1-save-format.md 1.2), so the slot is never listed with no save behind it.
    * The slot's folders left empty are removed (empty folders only).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_copy_slot as cs
import vf1_move_slot as ms
import vf1_rename_family as rename
import vf1_save_backup as save_backup

TITLE = "Delete Player Slot"
PICTURES = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
BATCH = 1000                     # files or whole folders per Recycle Bin call
# A folder costs Windows about as much to recycle as 30 loose files (the Virtual Villagers patcher's PR #876,
# measured 2026-11-25: ~0.2 s a folder whatever it holds, ~5 ms a file), so only a folder of at least that many of
# the slot's files goes whole (the owner approved one Recycle Bin entry per such folder).
WHOLE_FOLDER_FROM = 30
# vf1_copy_slot.set_aside_folder's names: "Replaced by copy|move <YYYY-MM-DD HH-MM-SS> - Save <N> - <old name>".
_ASIDE = re.compile(r"^Replaced by (?:copy|move) \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2} - Save ([1-5]) - ", re.IGNORECASE)


class DeleteError(cs.CopyError):
    """A delete that was refused or failed, with a reason a player can read."""


class GameRunning(DeleteError):
    """The game that uses this save folder is running."""


def is_picture(path: Path) -> bool:
    return Path(path).name.casefold().endswith(PICTURES)


@dataclass
class Group:
    """Files recycled together: the save folder's own, one backup's, or one set-aside folder's."""
    where: str                                   # "" the save folder; else "Backups\\<folder>"
    root: Path | None = None                     # the folder it was found in (never itself recycled)
    files: list[Path] = field(default_factory=list)
    pictures: list[Path] = field(default_factory=list)
    folders: list[Path] = field(default_factory=list)   # the slot's folders to remove once empty
    aside: Path | None = None                    # a whole set-aside folder


@dataclass
class Plan:
    folder: Path
    slot: int
    name: str | None                             # the family (None: its save cannot be read, or there is none)
    options_before: bytes | None
    options_after: bytes | None
    groups: list[Group] = field(default_factory=list)
    fingerprints: tuple = ()

    @property
    def files(self) -> list[Path]:
        return [p for g in self.groups for p in g.files]

    @property
    def pictures(self) -> list[Path]:
        return [p for g in self.groups for p in g.pictures]

    @property
    def backups(self) -> int:
        return sum(1 for g in self.groups if g.where and g.aside is None)

    @property
    def asides(self) -> int:
        return sum(1 for g in self.groups if g.aside is not None)

    def signature(self) -> tuple:
        return (tuple(sorted(str(p).casefold() for p in self.files)), self.fingerprints)

    def preview(self) -> list[str]:
        rel = lambda p: str(Path(p).relative_to(self.folder))            # noqa: E731
        lines = [f"Recycled:  {rel(p)}" for p in self.files]
        lines += [f"Kept (pictures):  {rel(p)}" for p in self.pictures]
        return lines


# ---------------------------------------------------------------------------
# What goes
# ---------------------------------------------------------------------------


def _discover(root: Path, slot: int, where: str) -> Group:
    """Slot ``slot``'s files in the save folder (or the backup) ``root``."""
    group = Group(where, root)
    for relative in ms.slot_everything(root, slot):
        path = root / relative
        (group.pictures if is_picture(path) else group.files).append(path)
    group.folders = [cs.slot_root(root, slot)]
    return group


def _set_aside_groups(folder: Path, slot: int) -> list[Group]:
    """The slot's own "Replaced by copy/move <date> - Save <S> - ..." folders in Backups."""
    backups = folder / save_backup.BACKUPS_FOLDER
    out: list[Group] = []
    if not backups.is_dir():
        return out
    for entry in sorted(backups.iterdir(), key=lambda p: p.name.casefold()):
        match = _ASIDE.match(entry.name)
        if not match or int(match.group(1)) != slot or not entry.is_dir() or save_backup._is_link(entry):
            continue
        group = Group(f"{save_backup.BACKUPS_FOLDER}\\{entry.name}", backups, aside=entry)
        for path in ms.walk(entry):
            (group.pictures if is_picture(path) else group.files).append(path)
        out.append(group)
    return out


def _snapshots(folder: Path) -> list[Path]:
    """Every whole-folder copy in Backups (a backup, or a copy that stopped part-way): never a set-aside folder."""
    backups = folder / save_backup.BACKUPS_FOLDER
    if not backups.is_dir():
        return []
    return [entry for entry in sorted(backups.iterdir(), key=lambda p: p.name.casefold())
            if entry.is_dir() and not save_backup._is_link(entry)
            and not entry.name.casefold().startswith("replaced by ")]


NO_SAVE = "(no save -- leftover files)"
UNREADABLE = "(unreadable save)"


def deletable_slots(folder: Path) -> list[tuple[int, str]]:
    """Every slot Delete can be used on -- any slot with a file plan_delete finds (its save, its leftovers, its files
    in a backup, a set-aside folder of it), not only a slot with a readable save -- with its label: "Save 2: <family>",
    "Save 2: (no save -- leftover files)", "Save 2: (unreadable save)"."""
    out: list[tuple[int, str]] = []
    for slot in cs.SLOTS:
        try:
            plan = plan_delete(folder, slot)
        except (DeleteError, OSError):
            continue
        if plan.name is not None:
            what = plan.name or "(no name)"
        elif rename.save_path(Path(folder), slot).is_file():
            what = UNREADABLE
        else:
            what = NO_SAVE
        out.append((slot, f"Save {slot}: {what}"))
    return out


def plan_delete(folder: Path, slot: int) -> Plan:
    folder = Path(folder)
    if slot not in cs.SLOTS:
        raise DeleteError("There are only save slots 1 to 5.")
    save = rename.save_path(folder, slot)
    name = None
    if save.is_file():
        try:
            stored = rename.save_name(save.read_bytes())
        except OSError as exc:
            raise DeleteError(f"Could not read {save.name}: {exc}") from exc
        if stored is not None:
            import vf1_names
            name = vf1_names.Book(folder).full(slot, stored)
    options_file = rename.options_path(folder)
    before = after = None
    if options_file.is_file():
        before = options_file.read_bytes()
        used = cs._used_offset(before, slot)
        if used is None:
            raise DeleteError(f"The slot menu file {options_file.name} is not one this tool can read.")
        changed = bytearray(before)
        changed[used] = 0
        after = bytes(changed)
    plan = Plan(folder, slot, name, before, after)
    try:
        plan.groups.append(_discover(folder, slot, ""))
        for snapshot in _snapshots(folder):
            group = _discover(snapshot, slot, f"{save_backup.BACKUPS_FOLDER}\\{snapshot.name}")
            if group.files or group.pictures:
                plan.groups.append(group)
        plan.groups += _set_aside_groups(folder, slot)
    except OSError as exc:
        raise DeleteError(f"Could not list the save folder: {exc}") from exc
    if not plan.files:                       # nothing at all, or only pictures (which always stay)
        raise DeleteError(f"Save {slot} has no files to delete.")
    prints = []
    for path in plan.files + plan.pictures:
        try:
            info = path.stat()
            prints.append((str(path).casefold(), info.st_size, info.st_mtime_ns))
        except OSError:
            prints.append((str(path).casefold(), None))
    prints.append(("slot menu", hashlib.sha256(before).hexdigest() if before is not None else None))
    plan.fingerprints = tuple(sorted(prints, key=lambda f: f[0]))
    return plan


# ---------------------------------------------------------------------------
# The delete
# ---------------------------------------------------------------------------


@dataclass
class DeleteResult:
    folder: Path
    slot: int
    name: str | None
    recycled: list[Path] = field(default_factory=list)
    not_recycled: list[Path] = field(default_factory=list)
    pictures: list[Path] = field(default_factory=list)
    backups_touched: int = 0
    asides: list[Path] = field(default_factory=list)
    problem: str | None = None                   # why it stopped (None: everything went)
    notes: list[str] = field(default_factory=list)


def _refuse_if_running(folder: Path, processes) -> None:
    try:
        cs._refuse_if_running(folder, processes)
    except cs.GameRunning as exc:
        raise GameRunning(str(exc).replace("which would write over the copy's place in the slot menu",
                                           "which would write the slot's files again")) from exc
    except cs.CopyError as exc:
        raise DeleteError(str(exc)) from exc


def _remove_empty(folders: list[Path]) -> None:
    for root in folders:
        if not root.is_dir() or save_backup._is_link(root):
            continue
        for dirpath, _dirs, _files in sorted(os.walk(root), key=lambda w: -len(w[0])):
            try:
                os.rmdir(dirpath)                        # only an empty folder: anything left in it stays
            except OSError:
                pass


def _shell(paths: list[Path]) -> None:
    import vf1_translations
    vf1_translations.recycle(paths)


def warm_recycle_bin(folder: Path) -> None:
    """Have Windows' "is there a Recycle Bin on this drive?" answered while the player reads the list (it adds up
    the whole Recycle Bin, which can take a second or more), so the delete itself does not wait for it."""
    import vf1_translations
    vf1_translations.prepare_recycle_bin(folder)


def _linked(entry: os.DirEntry) -> bool:
    return entry.is_symlink() or getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0) == 0xA0000003


def _holds_no_file(folder: Path) -> bool:
    """An empty folder (or only empty folders in it), no link anywhere."""
    with os.scandir(folder) as scan:
        for entry in scan:
            if _linked(entry) or not entry.is_dir(follow_symlinks=False) or not _holds_no_file(folder / entry.name):
                return False
    return True


def _recycle_items(root: Path | None, files: list[Path]) -> list[tuple[Path, list[Path]]]:
    """What to hand Windows for ``files`` (all under ``root``), each with the files it holds: a folder below
    ``root`` that holds nothing but those files -- at any depth: no other file, no picture, no link -- and at least
    WHOLE_FOLDER_FROM of them goes whole, as ONE item; every other file goes by itself. The same files either way,
    and the result is still checked file by file. ``root`` itself (the save folder, a backup, the Backups folder)
    is never sent (the Virtual Villagers patcher's _recycle_items, PR #876)."""
    if root is None:
        return [(p, [p]) for p in files]
    prefix = str(root).rstrip("\\/") + os.sep
    folded_prefix = prefix.casefold()
    listed = {str(p).casefold() for p in files}
    parts_of: list[list[str] | None] = []
    ancestors: dict[str, int] = {}                # each folder holding listed files: how many, at any depth
    for path in files:
        text = str(path)
        if not text.casefold().startswith(folded_prefix):
            parts_of.append(None)
            continue
        parts = text[len(prefix):].split(os.sep)
        parts_of.append(parts)
        for depth in range(1, len(parts)):
            key = (prefix + os.sep.join(parts[:depth])).casefold()
            ancestors[key] = ancestors.get(key, 0) + 1
    whole: dict[str, bool] = {}

    def is_whole(folder: str) -> bool:
        key = folder.casefold()
        if key in whole:
            return whole[key]
        ok = True
        try:
            with os.scandir(folder) as scan:
                entries = list(scan)
        except OSError:
            entries, ok = [], False
        for entry in entries:                    # every entry, so each folder inside is judged too
            here = folder + os.sep + entry.name
            try:
                if _linked(entry):
                    ok = False
                elif entry.is_dir(follow_symlinks=False):
                    if here.casefold() in ancestors:
                        ok = is_whole(here) and ok
                    elif not _holds_no_file(Path(here)):
                        ok = False
                elif here.casefold() not in listed:
                    ok = False
            except OSError:
                ok = False
        whole[key] = ok
        return ok

    items: dict[str, tuple[Path, list[Path]]] = {}
    for path, parts in zip(files, parts_of):
        place = path
        for depth in range(1, len(parts or ())):
            folder = prefix + os.sep.join(parts[:depth])
            if ancestors[folder.casefold()] >= WHOLE_FOLDER_FROM and is_whole(folder):
                place = Path(folder)
                break
        items.setdefault(str(place).casefold(), (place, []))[1].append(path)
    return list(items.values())


def delete_slot(folder: Path, slot: int, processes=None, now: datetime | None = None, expected: tuple | None = None,
                recycle=None) -> DeleteResult:
    """Send slot ``slot``'s files to the Recycle Bin (see the module's notes). ``recycle`` replaces the Windows call
    in tests (a list of paths; raises OSError when they cannot all go)."""
    folder = Path(folder)
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    send = recycle or _shell
    _refuse_if_running(folder, controller)
    plan = plan_delete(folder, slot)
    if expected is not None and plan.signature() != expected:
        raise DeleteError(f"The files of Save {slot} changed after you confirmed, so nothing was deleted. "
                          "Try again to see the list as it is now.")
    result = DeleteResult(folder, slot, plan.name, pictures=plan.pictures)
    for group in plan.groups:
        try:
            items = _recycle_items(group.root, group.files)          # one call per part, whole folders
            for start in range(0, len(items), BATCH):
                batch = items[start:start + BATCH]
                send([place for place, _held in batch])
                held = [p for _place, files in batch for p in files]
                left = [p for p in held if os.path.lexists(p)]           # every file checked afterwards
                if left:
                    raise OSError(f"{len(left)} file(s) were still there afterwards")
                result.recycled += held
            if group.aside is not None:
                _remove_empty([group.aside])
                result.asides.append(group.aside)
            _remove_empty(group.folders)
            if group.where and group.aside is None:
                result.backups_touched += 1
        except (OSError, cs.CopyError) as exc:
            result.recycled = [p for p in plan.files if not os.path.lexists(p)]
            result.not_recycled = [p for p in plan.files if os.path.lexists(p)]
            result.problem = (f"Windows could not send every file to the Recycle Bin ({exc}), so the delete stopped "
                              f"in {group.where or 'the save folder'}.")
            break
    # The slot menu last -- and whenever the slot's save is gone, so it is never listed with no save.
    options_file = rename.options_path(folder)
    if plan.options_after is not None and not os.path.lexists(rename.save_path(folder, slot)):
        try:
            if options_file.read_bytes() == plan.options_before:
                cs._write_atomically(options_file, plan.options_after)
        except (OSError, cs.CopyError) as exc:
            result.notes.append(f"The slot menu could not be updated ({exc}); the game rebuilds it when it starts.")
    return result
