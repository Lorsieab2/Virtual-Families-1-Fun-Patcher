"""Move Player Slot: move one save slot's family, with EVERYTHING tied to that slot, into another slot of the same
save folder, and leave the slot it came from empty.

The Virtual Villagers Fun Patcher's Move (its src/vv_move_slot.py, PR #847; the owner, 2026-11-22: "transfer save
files AND BACKUPS AND LOGS AND ALL DATA FILES TIED TO A SAVE SLOT TO A DIFFERENT SLOT (CAN BE EXTRA DIALOGUES IN
COPY PLAYER SLOT)"), built on Copy Player Slot's own idea of a slot (patcher/vf1_copy_slot.py). It is the "Move"
choice of the Copy Player Slot window. The family keeps its name and every file; only the slot changes.

What moves (source S, target T; Copy Player Slot's file list, and here nothing of the slot is left behind)
    * The game's files: "Virtual Families<S>.ldw" and its two older autosave copies "<S+20>.ldw" / "<S+40>.ldw",
      renamed "<T>", "<T+20>", "<T+40>". Their bytes do not change: a save holds no slot number (vf1_copy_slot).
    * The patcher's files in "Virtual Families 1 Patcher Data": "Slot <S>.ini" (as "Slot <T>.ini"), and the
      Children, Outfits and Names files of S, S+20 and S+40 (renumbered). None of them names its slot inside:
      the Children files name the save's hash and size, which do not change; the Outfits files the tray; the
      Names files only the names.
    * Everything in "Virtual Families 1 Patcher\\Save <S>" -- its Family History log, the Family Tree Maker's
      files, the tree's page and pictures, and its Backups folder -- into "Save <T>", a " - Save <S>" in a file's
      name becoming " - Save <T>".
    * The slot menu "Virtual Families0.ldw": the target gets the family's name and its in-use flag; the source's
      flag is cleared, exactly what the game's own Delete Family does to it (docs/vf1-save-format.md 1.2; its name
      stays, unseen, until the game's next start rebuilds the menu from the saves).
    The whole-folder backups in "Backups" are not moved: each is a snapshot of every slot at once, and restoring
    one puts the whole folder back as it was then (the family in Save <S>).

What changes inside a moved file (the slot number, nowhere else)
    * A Family History file's first line "Family: <name> (Save <S>)" says "(Save <T>)".
    * A Family Tree Maker tree file's "slot".

Safety
    * The game must be closed (Copy Player Slot's check).
    * The whole save folder is backed up first ("Backups\\Backup <date> (before move)").
    * The target's files -- its family when it holds one (the player said Yes to replacing it), or what a family
      deleted in the game left -- are MOVED, never deleted, into "Backups\\Replaced by move <date> - Save <T> -
      <old name>", keeping their paths (Copy Player Slot's own set-aside).
    * Files are moved with a rename on the same disk, never over another file; a file whose slot number changes is
      then rewritten through a temporary file, keeping its times. The slot menu is written last.
    * What the player was shown is fingerprinted; a file changed since refuses the move.
    * A file the move must rewrite (a log header, a tree file, the slot menu) that is read-only refuses the move
      before anything is moved.
    * Afterwards the moved save is read back, the source is checked empty and every moved file is read back. Any
      failure moves every file back, puts every changed byte back and returns the set-aside files.

Nothing here touches Tk; the GUI runs it on a worker thread, and the tests drive it against throwaway save folders
and a fake process list.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_copy_slot as cs
import vf1_names
import vf1_rename_family as rename
import vf1_save as save_format
import vf1_save_backup as save_backup
import vf1_tree_memory

TITLE = "Move Player Slot"
BACKUP_LABEL = save_backup.BEFORE_MOVE
REPLACED = "Replaced by move"            # Backups\Replaced by move <date> - Save <T> - <old name>
SLOTS = cs.SLOTS
LOGS_ROOT = cs.LOGS_ROOT
DATA = cs.DATA


class MoveError(cs.CopyError):
    """A move that was refused or failed, with a reason a player can read."""


class GameRunning(MoveError):
    """The game that uses this save folder is running."""


# ---------------------------------------------------------------------------
# Every file of one slot
# ---------------------------------------------------------------------------


def walk(root: Path) -> list[Path]:
    """Every file under ``root`` (absolute), its Backups folder included; a linked folder is never entered."""
    out: list[Path] = []
    if not root.is_dir() or save_backup._is_link(root):
        return out

    def visit(folder: Path) -> None:
        for entry in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
            if save_backup._is_link(entry):
                continue
            if entry.is_dir():
                visit(entry)
            elif entry.is_file():
                out.append(entry)

    visit(root)
    return out


def slot_everything(folder: Path, slot: int) -> list[Path]:
    """Every file tied to slot ``slot`` (relative to ``folder``): Copy Player Slot's list (vf1_copy_slot.slot_files)
    and everything in "Virtual Families 1 Patcher\\Save <slot>", its Backups folder too. Never anything in the save
    folder's own Backups."""
    folder = Path(folder)
    out = [p for p in cs.slot_files(folder, slot) if p.parts[0].casefold() != LOGS_ROOT.casefold()]
    out += [p.relative_to(folder) for p in walk(cs.slot_root(folder, slot))]
    return sorted(out, key=lambda p: str(p).casefold())


# ---------------------------------------------------------------------------
# Where each file goes
# ---------------------------------------------------------------------------


def moved_relative(relative: Path, source: int, target: int) -> Path:
    """Where the slot's file ``relative`` goes in the target slot."""
    parts = relative.parts
    if len(parts) == 1:                                                 # Virtual Families<n>.ldw
        return Path(cs._renumber(parts[0], source, target))
    if parts[0].casefold() == LOGS_ROOT.casefold():                     # Virtual Families 1 Patcher\Save <S>\...
        inner = [cs._slot_name(p, source, target) for p in parts[2:]]
        return Path(LOGS_ROOT, f"Save {target}", *inner)
    if len(parts) == 2:                                                 # ...Patcher Data\Slot <S>.ini
        return Path(parts[0], f"Slot {target}.ini")
    return Path(*parts[:-1], cs._renumber(parts[-1], source, target))  # a Children / Outfits / Names file


_HEADER = re.compile(rb"\A(Family: [^\r\n]*)\(Save (\d+)\)(\r?\n|\Z)")


def moved_history(data: bytes, source: int, target: int) -> bytes | None:
    """A Family History file whose first line is "Family: <name> (Save <S>)" with "(Save <T>)"; None: unchanged."""
    match = _HEADER.match(data)
    if not match or int(match.group(2)) != source:
        return None
    return match.group(1) + f"(Save {target})".encode("ascii") + match.group(3) + data[match.end():]


def moved_tree(data: bytes, source: int, target: int) -> bytes | None:
    """A Family Tree Maker tree file with its "slot" made the target; None: not one, or not the source's."""
    try:
        tree = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(tree, dict) or tree.get("format") != vf1_tree_memory.FORMAT or tree.get("slot") != source:
        return None
    return json.dumps({**tree, "slot": target}, indent=1).encode("utf-8")


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass
class Move:
    source: Path                   # the file now (absolute)
    target: Path                   # where it goes (absolute)
    original: bytes                # its bytes now
    data: bytes | None = None      # its new bytes; None: as they are


@dataclass
class Plan:
    folder: Path
    source: int
    target: int
    name: str                                   # the family (its whole name)
    stored: str                                 # as the save and the slot menu keep it
    options_before: bytes
    options_after: bytes
    moves: list[Move] = field(default_factory=list)
    removals: list[Path] = field(default_factory=list)          # the target's files (relative), set aside
    overwritten: str | None = None                              # the family replaced ("" unreadable; None none)
    fingerprints: tuple = ()

    def signature(self) -> tuple:
        """What the player was shown: every move and every file set aside, and what each of them and the slot
        menu WERE (a path-only list would miss a file changed in place while the question was open)."""
        return (tuple(sorted((str(m.source).casefold(), str(m.target).casefold()) for m in self.moves)),
                tuple(sorted(str(p).casefold() for p in self.removals)),
                self.fingerprints)

    def preview(self) -> list[str]:
        """Every change, one line each: "<from>  ->  <to>"."""
        rel = lambda p: str(Path(p).relative_to(self.folder))            # noqa: E731
        lines = []
        for m in self.moves:
            changed = " (slot updated inside)" if m.data is not None else ""
            lines.append(f"{rel(m.source)}  ->  {rel(m.target)}{changed}")
        lines.append(f"{rename.options_path(self.folder).name} (the slot menu: Save {self.target} gets "
                     f"{self.name}, Save {self.source} is empty)")
        return lines


def _fingerprint(path: Path, data: bytes | None = None) -> tuple:
    try:
        info = path.stat()
    except OSError:
        return (str(path).casefold(), None)
    digest = hashlib.sha256(data).hexdigest() if data is not None else ""
    return (str(path).casefold(), info.st_size, info.st_mtime_ns, digest)


def _read_only(path: Path) -> bool:
    """``path`` is marked read-only (Windows' Read-only box), so it can be renamed but not rewritten."""
    try:
        return not os.access(path, os.W_OK)
    except OSError:
        return False


def _refuse_read_only(plan: Plan, options_file: Path) -> None:
    """Every file the move must rewrite (a log header, a tree file, the slot menu) can be written, checked before
    anything moves: a read-only one would stop the move half way (the end-to-end check, 2026-11-26)."""
    rewrite = [m.source for m in plan.moves if m.data is not None] + [options_file]
    locked = [p for p in rewrite if _read_only(p)]
    if locked:
        shown = "; ".join(str(p.relative_to(plan.folder)) for p in locked[:8])
        more = f" and {len(locked) - 8} more" if len(locked) > 8 else ""
        raise MoveError(f"These files are read-only, and the move must write the slot number inside them: "
                        f"{shown}{more}. Clear Read-only in each file's Properties (right-click it in File "
                        f"Explorer) and try again. Nothing was moved.")


def _refuse_if_running(folder: Path, processes) -> None:
    try:
        cs._refuse_if_running(folder, processes)
    except cs.GameRunning as exc:
        raise GameRunning(str(exc).replace("the copy's place", "the moved family's place")) from exc
    except cs.CopyError as exc:
        raise MoveError(str(exc)) from exc


def plan_move(folder: Path, source: int, target: int) -> Plan:
    """Everything the move would do, worked out and checked before anything is written. Raises MoveError (nothing
    changed) on a refusal."""
    folder = Path(folder)
    if source not in SLOTS or target not in SLOTS:
        raise MoveError("There are only save slots 1 to 5.")
    if source == target:
        raise MoveError("Choose another slot to move to.")
    save = rename.save_path(folder, source)
    try:
        data = save.read_bytes()
    except FileNotFoundError as exc:
        raise MoveError(f"Save {source} has no family ({save.name} is missing).") from exc
    except OSError as exc:
        raise MoveError(f"Could not read {save.name}: {exc}") from exc
    stored = rename.save_name(data)
    if stored is None:
        raise MoveError(f"{save.name} is not a Virtual Families save this tool can read.")
    book = vf1_names.Book(folder)
    name = book.full(source, stored)
    destination = rename.save_path(folder, target)
    if os.path.lexists(destination) and not destination.is_file():
        raise MoveError(f"{destination.name} is not a file, so nothing can be moved into Save {target}.")
    overwritten = None
    if destination.is_file():
        try:
            old = rename.save_name(destination.read_bytes())
        except OSError as exc:
            raise MoveError(f"Could not read {destination.name}: {exc}") from exc
        overwritten = book.full(target, old) if old is not None else ""
    options_file = rename.options_path(folder)
    try:
        options = options_file.read_bytes()
    except OSError as exc:
        raise MoveError(f"Could not read the slot menu {options_file.name}: {exc}") from exc
    menu_at = rename._menu_name_offset(options, target)
    used_to, used_from = cs._used_offset(options, target), cs._used_offset(options, source)
    if menu_at is None or used_to is None or used_from is None or rename.menu_name(options, target) is None:
        raise MoveError(f"The slot menu file {options_file.name} is not one this tool can read.")
    after = bytearray(rename._with_name(options, menu_at, rename.OPTIONS_NAME_STRIDE, stored))
    after[used_to], after[used_from] = 1, 0

    plan = Plan(folder, source, target, name, stored, options, bytes(after), overwritten=overwritten)
    try:
        everything = slot_everything(folder, source)
        plan.removals = cs.leftovers(folder, target)
    except OSError as exc:
        raise MoveError(f"Could not list the save folder: {exc}") from exc
    for relative in everything:
        path = folder / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MoveError(f"Could not read {relative}: {exc}") from exc
        move = Move(path, folder / moved_relative(relative, source, target), raw)
        if cs._history_number(relative) is not None:
            move.data = moved_history(raw, source, target)
        elif relative.suffix.lower() == ".tree" and relative.parts[0].casefold() == LOGS_ROOT.casefold():
            move.data = moved_tree(raw, source, target)
        plan.moves.append(move)

    # Every place a file goes must be free once the target's files are set aside.
    removing = {str(folder / p).casefold() for p in plan.removals}
    root_t = str(cs.slot_root(folder, target)).casefold() + os.sep

    def set_aside(place: Path) -> bool:
        key = str(place).casefold()
        return key in removing or (str(cs.slot_root(folder, target)).casefold() in removing and key.startswith(root_t))

    taken = [m.target for m in plan.moves if os.path.lexists(m.target) and not set_aside(m.target)]
    if taken:
        shown = "; ".join(str(p.relative_to(folder)) for p in taken[:8])
        more = f" and {len(taken) - 8} more" if len(taken) > 8 else ""
        raise MoveError(f"These files the move would make are already there and are not Save {target}'s: "
                        f"{shown}{more}. Nothing is ever written over, so nothing was moved.")
    places = [str(m.target).casefold() for m in plan.moves]
    if len(places) != len(set(places)):
        raise MoveError("Two of the slot's files would go to the same place, so nothing was moved.")
    _refuse_read_only(plan, options_file)
    removed_files = []
    for relative in plan.removals:
        place = folder / relative
        removed_files += walk(place) if place.is_dir() else [place]
    plan.fingerprints = tuple(sorted(
        [_fingerprint(m.source, m.original) for m in plan.moves]
        + [_fingerprint(p) for p in removed_files]
        + [_fingerprint(options_file, options)],
        key=lambda f: f[0]))
    return plan


# ---------------------------------------------------------------------------
# The move
# ---------------------------------------------------------------------------


@dataclass
class MoveResult:
    folder: Path
    source: int
    target: int
    name: str
    backup: save_backup.BackupResult
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)            # moved files whose content names the target now
    removed: list[Path] = field(default_factory=list)            # the target's files, set aside (relative)
    set_aside: Path | None = None
    overwritten: str | None = None


@dataclass
class _Done:
    made: list[Path] = field(default_factory=list)               # folders the move made
    aside_made: list[Path] = field(default_factory=list)         # folders made in the set-aside folder
    aside: list[tuple[Path, Path]] = field(default_factory=list)  # (relative, where it was set aside)
    moved: list = field(default_factory=list)                    # [Move, rewritten?]
    removed_dirs: list[Path] = field(default_factory=list)       # the source's folders left empty, removed
    options: bool = False


def _rewrite(path: Path, data: bytes, times: tuple[int, int]) -> None:
    """``path``'s content replaced through a temporary file beside it (read back), its times kept."""
    cs._write_atomically(path, data)
    os.utime(path, ns=times)


def _move_one(move: Move, done: _Done, fail: bool = False) -> None:
    info = move.source.stat()
    times = (info.st_atime_ns, info.st_mtime_ns)
    cs._make_folders(move.target, done.made)
    os.rename(move.source, move.target)            # never over anything: FileExistsError on Windows
    done.moved.append([move, False])
    if fail:
        raise MoveError("stopped for the test")
    if move.data is not None:
        done.moved[-1][1] = True
        _rewrite(move.target, move.data, times)
    if move.target.read_bytes() != (move.data if move.data is not None else move.original):
        raise MoveError(f"{move.target.name} did not read back after the move.")


def _remove_empty_folders(plan: Plan, done: _Done) -> None:
    """The source's own "Save <S>" folders, emptied by the move, removed (deepest first)."""
    root = cs.slot_root(plan.folder, plan.source)
    if not root.is_dir() or save_backup._is_link(root):
        return
    folders = [Path(dirpath) for dirpath, _dirs, _files in os.walk(root)]
    for sub in sorted(folders, key=lambda p: -len(p.parts)):
        try:
            if not any(sub.iterdir()):
                sub.rmdir()
                done.removed_dirs.append(sub)
        except OSError:
            pass


def _roll_back(plan: Plan, done: _Done) -> list[str]:
    problems: list[str] = []
    options_file = rename.options_path(plan.folder)
    if done.options:
        try:
            if options_file.read_bytes() != plan.options_before:
                cs._write_atomically(options_file, plan.options_before)
        except (OSError, cs.CopyError) as exc:
            problems.append(f"{options_file.name}: {exc}")
    for folder in reversed(done.removed_dirs):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            problems.append(f"{folder}: {exc}")
    for move, rewritten in reversed(done.moved):
        # A file whose rewrite failed (read-only) still holds its original bytes: it is only renamed back. A rewrite
        # that cannot be undone never stops the rename, so the file is always back in its own place.
        try:
            if rewritten and move.target.read_bytes() != move.original:
                info = move.target.stat()
                _rewrite(move.target, move.original, (info.st_atime_ns, info.st_mtime_ns))
        except (OSError, cs.CopyError) as exc:
            problems.append(f"{move.source.name} (now {move.target}): {exc}")
        try:
            move.source.parent.mkdir(parents=True, exist_ok=True)
            os.rename(move.target, move.source)
        except OSError as exc:
            problems.append(f"{move.source.name} (now {move.target}): {exc}")
    cs._remove_folders(done.made)                  # a new "Save <T>" first, so the old one can move back
    for relative, aside in reversed(done.aside):
        place = plan.folder / relative
        try:
            if place.is_dir() and not save_backup._is_link(place) and not any(place.iterdir()):
                place.rmdir()                      # an empty folder left in its way never blocks it (WinError 183)
            os.rename(aside, place)
        except OSError as exc:
            problems.append(f"{relative} (it is in {aside}): {exc}")
    cs._remove_folders(done.aside_made)
    return problems


def verify(plan: Plan) -> None:
    """The source left empty, the moved save the family that was moved, every file read back, and the slot menu
    read back."""
    folder = plan.folder
    if os.path.lexists(rename.save_path(folder, plan.source)):
        raise MoveError(f"Save {plan.source} still has a save after the move.")
    moved = rename.save_path(folder, plan.target)
    data = moved.read_bytes()
    original = next(m.original for m in plan.moves if m.target == moved)
    if data != original:
        raise MoveError("The moved save is not the family that was moved.")
    save_format.parse_save(data)
    if vf1_names.Book(folder).full(plan.target, rename.save_name(data) or "") != plan.name:
        raise MoveError(f"The moved save does not read back with the name {plan.name}.")
    for m in plan.moves:
        if os.path.lexists(m.source):
            raise MoveError(f"{m.source.name} is still in Save {plan.source}.")
        if m.target.read_bytes() != (m.data if m.data is not None else m.original):
            raise MoveError(f"{m.target.name} did not read back after the move.")
    menu = rename.options_path(folder).read_bytes()
    if menu != plan.options_after or cs.slot_used(menu, plan.target) is not True \
            or cs.slot_used(menu, plan.source) is not False:
        raise MoveError("The slot menu does not read back as written.")


def move_slot(
    folder: Path,
    source: int,
    target: int,
    processes: save_backup.ProcessController | None = None,
    now: datetime | None = None,
    expected: tuple | None = None,
    _fail_after: int | None = None,
) -> MoveResult:
    """Move the family in ``source`` and everything tied to that slot into ``target``.

    Refused (MoveError, nothing changed) when the game is running, the source cannot be read, or a place a file
    would go is taken by something that is not the target's. Otherwise the folder is backed up first, the target's
    files are set aside, and every file is moved; on any failure everything is put back. ``expected`` is the plan
    the player was shown (Plan.signature): a different plan now refuses the move. ``_fail_after`` (tests only) makes
    the move fail after that many files."""
    folder = Path(folder)
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    when = now or datetime.now()
    _refuse_if_running(folder, controller)
    plan = plan_move(folder, source, target)
    if expected is not None and plan.signature() != expected:
        raise MoveError(f"The files of Save {source} or Save {target} changed after you confirmed, so nothing was "
                        "moved. Try again to see the list as it is now.")
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise MoveError(f"The backup before moving failed, so nothing was moved. {exc}") from exc
    _refuse_if_running(folder, controller)        # the backup took a moment
    done = _Done()
    aside = None
    try:
        if plan.removals:
            aside = cs.set_aside_folder(folder, when, target, plan.overwritten, prefix=REPLACED)
            if aside.exists():
                raise MoveError(f"{aside.name} is already there; try again in a moment.")
            for relative in plan.removals:
                place = aside / relative
                cs._make_folders(place, done.aside_made)
                os.rename(folder / relative, place)
                done.aside.append((relative, place))
        for count, move in enumerate(plan.moves):
            _move_one(move, done, fail=_fail_after is not None and count >= _fail_after)
        _refuse_if_running(folder, controller)
        options_file = rename.options_path(folder)
        if options_file.read_bytes() != plan.options_before:
            raise MoveError(f"{options_file.name} changed while the slot was being moved.")
        done.options = True
        cs._write_atomically(options_file, plan.options_after)
        _remove_empty_folders(plan, done)
        verify(plan)
    except Exception as exc:  # noqa: BLE001 -- every failure is rolled back
        problems = _roll_back(plan, done)
        if problems:
            raise MoveError(
                f"The move failed ({exc}) and these could not be put back: {'; '.join(problems)}. "
                f"Your backup is in {backup.backup_folder}.") from exc
        raise MoveError(
            f"The move failed ({exc}); every file was put back and Save {source} and Save {target} are as they "
            f"were. A backup is in {backup.backup_folder}.") from exc
    return MoveResult(folder, source, target, plan.name, backup,
                      [(m.source, m.target) for m in plan.moves], [m.target for m in plan.moves if m.data is not None],
                      list(plan.removals), aside, plan.overwritten)
