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
    ever stored, so 19 bytes is the limit, exactly what the game itself can make. The stock game never
    stores anything but printable ASCII: SDL_TEXTINPUT text longer than one byte is dropped (0x4049BB) and the
    box refuses keys from 0x80 (0x40DB0F, the key is a signed char). With Render Unicode with In-Game Fonts
    any character is stored, as UTF-8 (patcher/vf1_text.py), so here too: printable ASCII is one byte, any
    other character 2 to 4, and the 19 bytes are counted, never a character cut in two. Control characters
    are refused. Spaces are kept as typed. A name that breaks the rule is refused, never truncated. The
    stock game (or the patch off) shows such a name as other Latin letters, and stores it back unchanged.

Safety
    * The game must be closed: a running game rewrites its saves by itself every 10 minutes and when it
      quits, which would put the old name straight back. Nothing here ever closes or pauses a game.
    * Before anything is written the whole save folder is backed up with Back Up Saves' own copier,
      labelled "(before rename)".
    * Every file is written beside itself and swapped in with os.replace, then read back. Any failure puts
      every file already changed back exactly as it was.

The Family History log (the Family History Log patch)
    The log belongs to a slot, not to a name, and a new log file opens with the family's name as the game
    holds it, so every file made from now on says "Family: <new name> (Save N)". Old files are never
    rewritten (they keep their history and their header). One record is added to the slot's newest Family
    History file, in the log's own layout: "[YYYY-MM-DD HH:MM:SS] Family Renamed <n>", "  Old name: <old>",
    "  New name: <new>", numbered after every earlier rename in the slot's files. The slot settings are addressed
    by slot and never by name, so a rename leaves them exactly as they are.

The Children files (Up to 28 Children)
    Each names the FNV-1a 64 hash and size of the save it was written with, and vf1kids takes the children from
    it only when the loaded save still has them (vf1kids.cpp AfterLoad; otherwise it keeps only the extra
    children still at home). The new name changes the saves' bytes, so each of the slot's Children files
    (N, N+20, N+40) that described one of the renamed saves BEFORE the rename is re-matched to it, exactly as
    Copy Player Slot does (vf1_genealogy.rekey_children_sidecar: the new hash and size and the file's own
    checksum, nothing else), written the same safe way and read back. One that described none of them, or is
    damaged, is left as it is. The Outfits files are tied to the tray and inventory, not to the save's bytes
    (outfits.inc DecodeOutfits), so a rename leaves them alone.

Nothing here touches Tk; the GUI runs it on a worker thread, and the tests drive it against a temporary
copy of a save folder with a fake process list.
"""
from __future__ import annotations

import os
import unicodedata
import uuid
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_genealogy as gen
import vf1_save as save_format
import vf1_save_backup as save_backup
import vf1_text

SLOTS = (1, 2, 3, 4, 5)
BACKUP_LABEL = save_backup.BEFORE_RENAME
# The most characters the tool accepts (see the module notes).
MAX_LENGTH = 19
FAMILY_NAME_FIELD = 0x1C                 # bytes reserved at theGameState+0x1B12C
OPTIONS_FIRST_NAME = 0x1B192             # theGameState offset of slot 1's menu name
OPTIONS_NAME_STRIDE = 0x15               # bytes per slot-menu name
GENERATIONS = (20, 40)                   # slot N's older copies: file numbers N+20 and N+40
LOGS_ROOT = "Virtual Families 1 Patcher"
HISTORY_FOLDER = "Family History"
_HISTORY_FILE = re.compile(r"^Family History (\d+)\.txt$", re.IGNORECASE)
PRINTABLE = frozenset(chr(code) for code in range(0x20, 0x7F))


def printable(ch: str) -> bool:
    """A character a name may hold: anything but control characters, unpaired surrogates and NUL."""
    if ch in PRINTABLE:
        return True
    cat = unicodedata.category(ch)
    return cat not in ("Cc", "Cs", "Zl", "Zp") and ord(ch) != 0xFEFF


def room_used(name: str) -> int:
    """How much of the name field ``name`` fills: its UTF-8 length (one per letter A to Z, 2 to 4 for others)."""
    return len(vf1_text.encode(name))


def room_text(name: str) -> str:
    """The name box's counter: "7 / 19 characters", saying when a letter takes more than one."""
    used = room_used(name)
    text = f"{used} / {MAX_LENGTH} characters"
    if used != len(name):
        text += " (letters beyond A to Z count as 2 to 4)"
    return text


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
    bad = sorted({ch for ch in name if not printable(ch)})
    if bad:
        shown = " ".join(repr(ch) for ch in bad)
        return f"Virtual Families cannot use these characters in a name: {shown}."
    used = room_used(name)
    if used > MAX_LENGTH:
        return (f"{used} characters is too long: a family name can have at most {MAX_LENGTH} "
                f"(an accented or other letter beyond A to Z counts as 2 to 4).")
    if not name.strip(" "):
        return "A name cannot be only spaces."
    return None


# ---------------------------------------------------------------------------
# Reading the saves
# ---------------------------------------------------------------------------


def _c_string(data: bytes, offset: int, width: int) -> str | None:
    """The NUL-terminated string in the field (read by the patcher's one rule, vf1_text), or None when it has
    no NUL or holds control characters."""
    raw = data[offset:offset + width]
    end = raw.find(b"\0")
    if end < 0:
        return None
    text = raw[:end]
    if any(byte < 0x20 or byte == 0x7F for byte in text):
        return None
    name = vf1_text.decode(text)
    if not all(printable(ch) for ch in name):
        return None
    return name


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
    encoded = vf1_text.encode(name)
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
class LogNote:
    path: Path
    original_size: int
    text: bytes


@dataclass
class RenameResult:
    folder: Path
    slot: int
    old_name: str
    new_name: str
    backup: save_backup.BackupResult
    changed: list[Path] = field(default_factory=list)
    notes: list[Path] = field(default_factory=list)
    rematched: list[Path] = field(default_factory=list)     # Children files re-matched to the renamed saves


def _refuse_if_running(folder: Path, processes: save_backup.ProcessController) -> None:
    exe = save_backup.game_exe_name(folder)
    try:
        running = processes.find(exe)
    except (OSError, save_backup.BackupError) as exc:
        raise RenameError(f"Could not check whether {exe} is running, so nothing was changed ({exc}).") from exc
    if running:
        raise GameRunning(
            f"{exe} is running. Close the game first (quit it normally from its menu): it saves by itself "
            "every 10 minutes and when it quits, which would put the old name back. Nothing was changed."
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


def plan_children_changes(folder: Path, slot: int, changes: list[FileChange]) -> list[FileChange]:
    """The slot's Children files that described a save before ``changes``, re-matched to it after."""
    options = options_path(folder)
    saves = [(change.original, change.updated) for change in changes if change.path != options]
    return [FileChange(path, old, new) for path, old, new in gen.children_rekeys(folder, slot, saves)]


def children_match(path: Path, save: bytes) -> bool:
    """True when the Children file at ``path`` validates and names ``save``'s hash and size (what vf1kids checks)."""
    try:
        sidecar = gen.read_children_sidecar(path.read_bytes())
    except OSError:
        return False
    return sidecar is not None and sidecar.save_size == len(save) and sidecar.save_hash == gen.fnv1a64(save)


def history_folder(folder: Path, slot: int) -> Path:
    return folder / LOGS_ROOT / f"Save {slot}" / "Logs" / HISTORY_FOLDER


def newest_history(folder: Path, slot: int) -> Path | None:
    """The slot's newest Family History file, or None when it has none."""
    best: tuple[int, Path] | None = None
    try:
        entries = list(history_folder(folder, slot).iterdir())
    except OSError:
        return None
    for entry in entries:
        match = _HISTORY_FILE.match(entry.name)
        if match and entry.is_file() and (best is None or int(match.group(1)) > best[0]):
            best = (int(match.group(1)), entry)
    return None if best is None else best[1]


_RENAMED = re.compile(r"^\[[^\]]*\] Family Renamed (\d+)\r?$", re.MULTILINE)


def history_record(old: str, new: str, when: datetime, number: int) -> str:
    """The record the Family History log's own layout gives a rename (vf1logs.dll writes the others)."""
    return (f"[{when.strftime('%Y-%m-%d %H:%M:%S')}] Family Renamed {number}\r\n"
            f"  Old name: {old or '(no name)'}\r\n  New name: {new}\r\n\r\n")


def plan_log_notes(folder: Path, slot: int, old: str, new: str, when: datetime) -> list[LogNote]:
    """The record to add to the slot's newest Family History (none when the slot has no history file)."""
    path = newest_history(folder, slot)
    if path is None:
        return []
    number = 1
    try:
        for entry in history_folder(folder, slot).iterdir():
            if _HISTORY_FILE.match(entry.name) and entry.is_file():
                text = vf1_text.decode_lines(entry.read_bytes())
                number = max([number] + [int(n) + 1 for n in _RENAMED.findall(text)])
        data = path.read_bytes()
    except OSError as exc:
        raise RenameError(f"Could not read the log {path.name}: {exc}") from exc
    prefix = b"" if not data or data.endswith(b"\n") else b"\r\n"
    return [LogNote(path, len(data), prefix + vf1_text.encode(history_record(old, new, when, number)))]


def _restore(changes: list[FileChange], notes: list[LogNote]) -> list[str]:
    """Put every changed file back; the reasons any could not be."""
    problems: list[str] = []
    for change in reversed(changes):
        try:
            if change.path.read_bytes() != change.original:
                _write_atomically(change.path, change.original)
        except (OSError, RenameError) as exc:
            problems.append(f"{change.path.name}: {exc}")
    for note in reversed(notes):
        try:
            if note.path.stat().st_size != note.original_size:
                with note.path.open("r+b") as handle:
                    handle.truncate(note.original_size)
        except OSError as exc:
            problems.append(f"{note.path.name}: {exc}")
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
    children = plan_children_changes(folder, slot, changes)
    changes = changes[:-1] + children + changes[-1:]        # the options file stays last
    notes = plan_log_notes(folder, slot, old, new_name, when)
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise RenameError(f"The backup before renaming failed, so nothing was changed. {exc}") from exc
    # The backup took a moment; the game may have been started meanwhile.
    _refuse_if_running(folder, controller)
    done: list[FileChange] = []
    appended: list[LogNote] = []
    try:
        for change in changes:
            if change.path.read_bytes() != change.original:
                raise RenameError(f"{change.path.name} changed while it was being renamed.")
            done.append(change)
            _write_atomically(change.path, change.updated)
        for note in notes:
            appended.append(note)
            with note.path.open("ab") as handle:
                if handle.tell() != note.original_size:
                    raise RenameError(f"{note.path.name} changed while it was being renamed.")
                handle.write(note.text)
                handle.flush()
                os.fsync(handle.fileno())
            with note.path.open("rb") as handle:
                handle.seek(note.original_size)
                if handle.read() != note.text:
                    raise RenameError(f"{note.path.name} did not read back as written.")
        # Read every file back through the same readers the listing uses.
        options = options_path(folder)
        for change in changes:
            data = change.path.read_bytes()
            if change in children:
                if data != change.updated or not any(
                        children_match(change.path, other.updated) for other in changes if other not in children):
                    raise RenameError(f"{change.path.name} does not match the renamed save.")
                continue
            holds = (menu_name(data, slot) if change.path == options else save_name(data)) == new_name
            if not holds:
                raise RenameError(f"{change.path.name} does not hold the new name.")
    except (OSError, RenameError) as exc:
        problems = _restore(done, appended)
        if problems:
            raise RenameError(
                f"The rename failed ({exc}) and these files could not be put back: "
                f"{'; '.join(problems)}. Your backup is in {backup.backup_folder}."
            ) from exc
        raise RenameError(
            f"The rename failed ({exc}); every file was put back as it was. A backup is in {backup.backup_folder}."
        ) from exc
    return RenameResult(folder, slot, old, new_name, backup,
                        [change.path for change in changes if change not in children], [note.path for note in notes],
                        [change.path for change in children])
