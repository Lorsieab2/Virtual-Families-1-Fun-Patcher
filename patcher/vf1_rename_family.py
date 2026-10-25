"""Rename Family: change a family's name inside a closed game's saves.

Ported from the Virtual Villagers Fun Patcher's Rename Tribe (src/vv_tribe_rename.py).

Where the name lives (docs/vf1-save-format.md; every field below is marked VERIFIED there and was checked
against the owner's real saves, copies only: the five slot-menu names in the options file equal the
slots' own family names)
    * The slot save "Virtual Families<N>.ldw" holds the family name at theGameState+0x1B12C, a 0x1C-byte
      field with a NUL-terminated string (typed in the new-family dialog, 20 characters at most).
    * The game keeps older generations of each slot, "Virtual Families<N+20>.ldw" and "<N+40>.ldw" (its
      save writer rotates a slot to N+20 before every save). The game never loads them back, but they
      are the same family, so one still holding the old name is renamed too; one holding anything else
      is left alone.
    * The shared options file "Virtual Families0.ldw" keeps the five slot-menu names at
      theGameState+0x1B192 + 0x15 x (slot - 1), 0x15 bytes each, so the slot menu shows the new name.
    Only the name bytes change and the rest of the field is zeroed. There is no checksum; the loader
    checks the "ldwg" magic and the payload size.

The limit
    Traced in the vanilla exe (docs/vf1-save-format.md, "The family-name entry rule"): the entry box lets
    you type 20 characters (0x41C67A, 0x40DB03) and the OK handler stores them with GetText(buffer, 0x14)
    (0x41C72B), which strncpy's 20 bytes and forces buffer[19] = 0 (0x40D740): at most 19 characters are
    ever stored, so 19 is the limit, exactly what the game itself can make. The box accepts keys 0x20..0xFF
    (0x40DB0F); only printable ASCII 0x20..0x7E is accepted here. Spaces are kept as typed. A name that
    breaks the rule is refused, never truncated. UNCONFIRMED (not traced): whether non-ASCII keys ever
    reach the box, and which symbols the game's font can draw (cosmetic only).

Safety
    * The game must be closed: a running game rewrites its saves when it quits, which would put the old
      name straight back. Nothing here ever closes or pauses a game.
    * Before anything is written the whole save folder is backed up with Back Up Saves' own copier,
      labelled "(before rename)".
    * Every file is written beside itself and swapped in with os.replace, then read back. Any failure puts
      every file already changed back exactly as it was.

Nothing here touches Tk; the GUI runs it on a worker thread, and the tests drive it against a temporary
copy of a save folder with a fake process list.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_save as save_format
import vf1_save_backup as save_backup

SLOTS = (1, 2, 3, 4, 5)
BACKUP_LABEL = save_backup.BEFORE_RENAME
# The most characters the tool accepts (see the module notes).
MAX_LENGTH = 19
FAMILY_NAME_FIELD = 0x1C                 # bytes reserved at theGameState+0x1B12C
OPTIONS_FIRST_NAME = 0x1B192             # theGameState offset of slot 1's menu name
OPTIONS_NAME_STRIDE = 0x15               # bytes per slot-menu name
GENERATIONS = (20, 40)                   # slot N's older copies: file numbers N+20 and N+40
PRINTABLE = frozenset(chr(code) for code in range(0x20, 0x7F))


class RenameError(Exception):
    """A rename that was refused or failed, with a reason a player can read."""


class GameRunning(RenameError):
    """The game that uses this save folder is running."""


def save_path(folder: Path, number: int) -> Path:
    return folder / f"{save_format.SAVE_PREFIX}{number}.ldw"


def options_path(folder: Path) -> Path:
    return save_path(folder, 0)


# ---------------------------------------------------------------------------
# The name rule
# ---------------------------------------------------------------------------


def name_problem(name: str) -> str | None:
    """Why ``name`` cannot be a family name, or None if it can."""
    if not name:
        return "Type a name."
    bad = sorted({ch for ch in name if ch not in PRINTABLE})
    if bad:
        shown = " ".join(repr(ch) for ch in bad)
        return f"Virtual Families cannot use these characters in a name: {shown}."
    if len(name) > MAX_LENGTH:
        return f"{len(name)} characters is too long: a family name can have at most {MAX_LENGTH}."
    if not name.strip(" "):
        return "A name cannot be only spaces."
    return None


# ---------------------------------------------------------------------------
# Reading the saves
# ---------------------------------------------------------------------------


def _c_string(data: bytes, offset: int, width: int) -> str | None:
    """The NUL-terminated printable-ASCII string in the field, or None."""
    raw = data[offset:offset + width]
    end = raw.find(b"\0")
    if end < 0:
        return None
    text = raw[:end]
    if any(byte < 0x20 or byte > 0x7E for byte in text):
        return None
    return text.decode("ascii")


def _header(data: bytes, payload: int) -> int | None:
    """The header size when ``data`` is a file of ``payload`` bytes of game state, else None."""
    try:
        header = save_format.parse_header(data)
    except save_format.SaveFormatError:
        return None
    if header.payload_size != payload or len(data) != header.size + payload:
        return None
    return header.size


def _save_name_offset(data: bytes) -> int | None:
    size = _header(data, save_format.PAYLOAD_SIZE)
    if size is None:
        return None
    return size + save_format.GS_FAMILY_NAME - save_format.GS_BASE


def _menu_name_offset(data: bytes, slot: int) -> int | None:
    size = _header(data, save_format.OPTIONS_SIZE)
    if size is None:
        return None
    return size + OPTIONS_FIRST_NAME - save_format.GS_SAVED_END + OPTIONS_NAME_STRIDE * (slot - 1)


def save_name(data: bytes) -> str | None:
    """The family name in a slot save's bytes, or None if they are not a save."""
    offset = _save_name_offset(data)
    return None if offset is None else _c_string(data, offset, FAMILY_NAME_FIELD)


def menu_name(data: bytes, slot: int) -> str | None:
    """Slot ``slot``'s name in the options file's bytes, or None."""
    offset = _menu_name_offset(data, slot)
    return None if offset is None else _c_string(data, offset, OPTIONS_NAME_STRIDE)


@dataclass
class SlotInfo:
    slot: int
    name: str | None            # the name in the slot's save, or None
    problem: str | None = None  # why it cannot be renamed, if it cannot

    @property
    def label(self) -> str:
        if self.name is None:
            return f"Save {self.slot}: (empty)"
        return f"Save {self.slot}: {self.name or '(no name)'}"


def read_slots(folder: Path) -> list[SlotInfo]:
    """Each slot's family name, from its save."""
    try:
        options = options_path(folder).read_bytes()
    except OSError:
        options = b""
    options_ok = bool(options) and menu_name(options, 1) is not None
    slots: list[SlotInfo] = []
    for slot in SLOTS:
        path = save_path(folder, slot)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            slots.append(SlotInfo(slot, None, "This slot has no family."))
            continue
        except OSError as exc:
            slots.append(SlotInfo(slot, None, f"The save could not be read: {exc}"))
            continue
        name = save_name(data)
        info = SlotInfo(slot, name)
        if name is None:
            info.problem = f"{path.name} is not a Virtual Families save this tool can read."
        elif not options_ok:
            info.problem = f"The slot menu file {options_path(folder).name} could not be read."
        slots.append(info)
    return slots


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _with_name(data: bytes, offset: int, width: int, name: str) -> bytes:
    """``data`` with the field at ``offset`` holding ``name``, NUL-padded."""
    encoded = name.encode("ascii")
    if len(encoded) + 1 > width:
        raise RenameError(f"{name!r} does not fit a {width}-byte name field.")
    return data[:offset] + encoded + b"\0" * (width - len(encoded)) + data[offset + width:]


def _write_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` through a temporary file, then verify."""
    temporary = path.with_name(f"{path.name}.rename-{uuid.uuid4().hex[:12]}.tmp")   # a leftover never blocks the next one
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
        raise RenameError(f"{path.name} did not read back as written.")


@dataclass
class FileChange:
    path: Path
    original: bytes
    updated: bytes


@dataclass
class RenameResult:
    folder: Path
    slot: int
    old_name: str
    new_name: str
    backup: save_backup.BackupResult
    changed: list[Path] = field(default_factory=list)


def _refuse_if_running(folder: Path, processes: save_backup.ProcessController) -> None:
    exe = save_backup.game_exe_name(folder)
    try:
        running = processes.find(exe)
    except (OSError, save_backup.BackupError) as exc:
        raise RenameError(f"Could not check whether {exe} is running, so nothing was changed ({exc}).") from exc
    if running:
        raise GameRunning(
            f"{exe} is running. Close the game first (quit it normally from its menu): it saves when it "
            "quits, which would put the old name back. Nothing was changed."
        )


def plan_save_changes(folder: Path, slot: int, new_name: str) -> tuple[str, list[FileChange]]:
    """The old name, and the new bytes of every save file that holds it."""
    save = save_path(folder, slot)
    try:
        data = save.read_bytes()
    except FileNotFoundError as exc:
        raise RenameError(f"Save {slot} has no family ({save.name} is missing).") from exc
    except OSError as exc:
        raise RenameError(f"Could not read {save.name}: {exc}") from exc
    old = save_name(data)
    offset = _save_name_offset(data)
    if old is None or offset is None:
        raise RenameError(f"{save.name} is not a Virtual Families save this tool can read.")
    if old == new_name:
        raise RenameError(f"Save {slot} is already called {new_name}.")
    options = options_path(folder)
    try:
        menu = options.read_bytes()
    except OSError as exc:
        raise RenameError(f"Could not read the slot menu file {options.name}: {exc}") from exc
    menu_offset = _menu_name_offset(menu, slot)
    if menu_offset is None or menu_name(menu, slot) is None:
        raise RenameError(f"The slot menu file {options.name} is not one this tool can read.")
    changes = [FileChange(save, data, _with_name(data, offset, FAMILY_NAME_FIELD, new_name))]
    for step in GENERATIONS:
        path = save_path(folder, slot + step)
        try:
            older = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RenameError(f"Could not read {path.name}: {exc}") from exc
        older_offset = _save_name_offset(older)
        if older_offset is None or save_name(older) != old:
            continue        # another family, or not a save: left alone
        changes.append(FileChange(path, older, _with_name(older, older_offset, FAMILY_NAME_FIELD, new_name)))
    changes.append(FileChange(options, menu, _with_name(menu, menu_offset, OPTIONS_NAME_STRIDE, new_name)))
    return old, changes


def _restore(changes: list[FileChange]) -> list[str]:
    """Put every changed file back; the reasons any could not be."""
    problems: list[str] = []
    for change in reversed(changes):
        try:
            if change.path.read_bytes() != change.original:
                _write_atomically(change.path, change.original)
        except (OSError, RenameError) as exc:
            problems.append(f"{change.path.name}: {exc}")
    return problems


def rename_family(
    folder: Path,
    slot: int,
    new_name: str,
    processes: save_backup.ProcessController | None = None,
    now: datetime | None = None,
) -> RenameResult:
    """Rename the family in ``slot`` of ``folder`` to ``new_name``.

    Refused (RenameError, nothing changed) when the name breaks the rule, the game is running, or the
    saves cannot be read. Otherwise the folder is backed up first, every file is replaced atomically and
    read back, and any failure restores every file already changed.
    """
    if slot not in SLOTS:
        raise RenameError(f"There is no save slot {slot}.")
    problem = name_problem(new_name)
    if problem is not None:
        raise RenameError(problem)
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    when = now or datetime.now()
    _refuse_if_running(folder, controller)
    old, changes = plan_save_changes(folder, slot, new_name)
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise RenameError(f"The backup before renaming failed, so nothing was changed. {exc}") from exc
    # The backup took a moment; the game may have been started meanwhile.
    _refuse_if_running(folder, controller)
    done: list[FileChange] = []
    try:
        for change in changes:
            if change.path.read_bytes() != change.original:
                raise RenameError(f"{change.path.name} changed while it was being renamed.")
            done.append(change)
            _write_atomically(change.path, change.updated)
        # Read every file back through the same readers the listing uses.
        options = options_path(folder)
        for change in changes:
            data = change.path.read_bytes()
            holds = (menu_name(data, slot) if change.path == options else save_name(data)) == new_name
            if not holds:
                raise RenameError(f"{change.path.name} does not hold the new name.")
    except (OSError, RenameError) as exc:
        problems = _restore(done)
        if problems:
            raise RenameError(
                f"The rename failed ({exc}) and these files could not be put back: "
                f"{'; '.join(problems)}. Your backup is in {backup.backup_folder}."
            ) from exc
        raise RenameError(
            f"The rename failed ({exc}); every file was put back as it was. A backup is in {backup.backup_folder}."
        ) from exc
    return RenameResult(folder, slot, old, new_name, backup, [change.path for change in changes])
