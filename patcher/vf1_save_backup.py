"""Back Up Saves / Restore Saves for the Virtual Families 1 Fun Patcher.

Ported from the Virtual Villagers Fun Patcher's save backup tool (src/vv_save_backup.py).

Where the saves are
    Virtual Families saves under Documents\\LDW\\<its exe's name>. The patched
    game is "Virtual Families - Modded.exe", so its saves are in
    Documents\\LDW\\Virtual Families - Modded\\. Documents is resolved through
    the Windows Known Folder API, because it may be redirected (to OneDrive);
    a home-relative guess would name a folder the game never writes to.

What is copied
    Everything in the save folder -- the game's "Virtual Families<N>.ldw" slot
    saves, the patcher's "Virtual Families 1 Patcher Data" folder (each save's
    own data, such as the Children sidecar) and any other file kept beside
    the saves -- except the "Backups" folder itself. The copy goes into a new
    "Backups\\Backup YYYY-MM-DD HH-MM-SS" folder inside that same save folder.
    An existing backup is never written into or replaced, and every copied
    file is read back and checked against the original's size and SHA-256.

Pausing
    If the game that uses the folder is running, every process of it is
    suspended for the copy and always resumed afterwards, even when the copy
    fails. If any of them cannot be suspended the backup is refused rather
    than taken while the game might be writing. The game is never closed.

Restore
    A backup is restored -- the whole save folder, or one save slot -- only
    while the game is closed, and only after the current saves have been
    backed up as "Backup <date> (before restore)". Nothing is ever replaced
    without that safety copy, and a restore that fails part-way puts every
    file back.

Nothing here touches Tk, so the GUI runs it on a worker thread, and the tests
drive it with a fake Documents folder and a fake process controller.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Protocol

# The folder the backups go into, inside each save folder.
BACKUPS_FOLDER = "Backups"
BACKUP_PREFIX = "Backup "

# The stock save folder / executable name of Virtual Families, and the patcher's own data folder.
GAME_NAME = "Virtual Families"
PATCHER_DATA_FOLDER = "Virtual Families 1 Patcher Data"
PATCHER_SAVE_FOLDER = f"{GAME_NAME} - Modded"

HASH_CHUNK = 1024 * 1024


class BackupError(Exception):
    """A backup that could not be made, with a reason a player can read."""


class PauseRefused(BackupError):
    """The game is running and could not be paused, so nothing was copied."""


class RestoreRefused(BackupError):
    """A restore that was not started, with the reason; nothing was changed."""


# ---------------------------------------------------------------------------
# Documents and the save folders
# ---------------------------------------------------------------------------


def documents_folder() -> Path | None:
    """The Documents folder as Windows resolves it, or None if it cannot.

    SHGetKnownFolderPath(FOLDERID_Documents) follows folder redirection, so a
    Documents moved to OneDrive or a network share is found where the game
    actually saves. There is deliberately no home-relative fallback: a guessed
    folder would only make the tool report "no saves found" for a player whose
    saves are elsewhere.
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        folder_id = GUID(
            0xFDD39AD0,
            0x238F,
            0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        result = ctypes.c_wchar_p()
        status = shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(result)
        )
        try:
            if status == 0 and result.value:
                return Path(result.value)
        finally:
            ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))
    except (OSError, AttributeError):
        pass
    return None


def is_patcher_save_folder(name: str) -> bool:
    """Whether ``name`` is the save folder of the game the patcher builds by default."""
    return name.casefold() == PATCHER_SAVE_FOLDER.casefold()


def find_save_folders(documents: Path | None, extra_names: tuple[str, ...] = ()) -> list[Path]:
    """Every Documents\\LDW\\Virtual Families - Modded... folder, the patcher's own first.

    The stock game's own "Virtual Families" folder is not listed: the tool
    backs up the patched game's saves. Any other folder whose name starts with
    "Virtual Families - Modded" (a copy the player made, a renamed build) is
    listed too, because a game run from such an exe saves there. ``extra_names``
    are further folder names to include when they exist (the stems of the
    executables found in the modded output folder).
    """
    if documents is None:
        return []
    ldw = documents / "LDW"
    if not ldw.is_dir():
        return []
    prefix = PATCHER_SAVE_FOLDER.casefold()
    wanted = {name.casefold() for name in extra_names if name and name.casefold() != GAME_NAME.casefold()}
    found = [
        entry
        for entry in ldw.iterdir()
        if entry.is_dir()
        and (entry.name.casefold().startswith(prefix) or entry.name.casefold() in wanted)
    ]

    def order(path: Path) -> tuple[int, str]:
        key = path.name.casefold()
        return (0 if key == prefix else 1, key)

    return sorted(found, key=order)


def game_exe_name(save_folder: Path) -> str:
    """The exe that saves into ``save_folder``: the game names it after itself."""
    return f"{save_folder.name}.exe"


# ---------------------------------------------------------------------------
# What is copied
# ---------------------------------------------------------------------------


_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _is_link(path: Path) -> bool:
    """A symbolic link or junction, which the copy never follows."""
    if path.is_symlink():
        return True
    try:
        tag = getattr(path.lstat(), "st_reparse_tag", 0)
    except OSError:
        return False
    return tag == _IO_REPARSE_TAG_MOUNT_POINT


def files_to_back_up(save_folder: Path) -> list[Path]:
    """Every file under ``save_folder`` except those in its Backups folder.

    Paths are returned relative to the save folder, sorted. A linked folder
    (junction or symbolic link) inside the save folder is not entered, so a
    link can never pull an unrelated tree -- or the save folder itself -- into
    the copy.
    """
    files: list[Path] = []

    def walk(folder: Path, relative: Path) -> None:
        for entry in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
            if relative == Path() and entry.name.casefold() == BACKUPS_FOLDER.casefold():
                continue
            if entry.is_dir():
                if not _is_link(entry):
                    walk(entry, relative / entry.name)
            elif entry.is_file() and not _is_link(entry):
                files.append(relative / entry.name)

    walk(save_folder, Path())
    return files


# ---------------------------------------------------------------------------
# The copy
# ---------------------------------------------------------------------------


@dataclass
class CopiedFile:
    relative: Path
    size: int
    sha256: str
    times: tuple[int, int] | None = None     # the original's (access, modification) in ns, kept on the copy


@dataclass
class BackupResult:
    save_folder: Path
    backup_folder: Path
    files: list[CopiedFile] = field(default_factory=list)
    paused: int = 0          # how many game processes were paused for the copy
    resume_problems: list[str] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files)


def backup_folder_name(now: datetime) -> str:
    return f"{BACKUP_PREFIX}{now.strftime('%Y-%m-%d %H-%M-%S')}"


IN_PROGRESS = " (in progress)"
INCOMPLETE = " INCOMPLETE"
BEFORE_RESTORE = "(before restore)"
BEFORE_RENAME = "(before rename)"
BEFORE_REPAIR = "(before repair)"
DELETE_ATTEMPTS = 5
DELETE_RETRY_SECONDS = 0.5


def _backup_names(now: datetime, suffix: str) -> Iterator[str]:
    base = backup_folder_name(now)
    for attempt in range(1, 1000):
        name = base if attempt == 1 else f"{base} ({attempt})"
        yield f"{name} {suffix}" if suffix else name


def _new_backup_folder(save_folder: Path, now: datetime, suffix: str = "") -> Path:
    """Create and return a new, empty "... (in progress)" folder.

    The backup is made under this name, which list_backups never offers, and
    is renamed to its final name only once every file has been verified -- so
    a copy that fails or is interrupted can never look like a usable backup.
    mkdir(exist_ok=False) is the claim, and a name whose final folder already
    exists is skipped, so an existing backup is never written into.
    """
    backups = save_folder / BACKUPS_FOLDER
    backups.mkdir(exist_ok=True)
    for name in _backup_names(now, suffix):
        if (backups / name).exists():
            continue
        candidate = backups / (name + IN_PROGRESS)
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise BackupError(f"Too many backups named {backup_folder_name(now)} in {backups}.")


def _finish_backup(staging: Path, now: datetime, suffix: str) -> Path:
    """Give a verified backup its final name: the first one still free."""
    for name in _backup_names(now, suffix):
        final = staging.with_name(name)
        if final.exists():
            continue
        for attempt in range(DELETE_ATTEMPTS):
            try:
                staging.rename(final)
                return final
            except FileExistsError:
                break
            except PermissionError:
                # A sync or indexing program (OneDrive) can hold a folder it has just seen created.
                if attempt == DELETE_ATTEMPTS - 1:
                    raise
                time.sleep(DELETE_RETRY_SECONDS)
    raise BackupError(f"No free name for the backup in {staging.parent}.")


def _set_aside(staging: Path, label: str) -> Path:
    """Rename a failed backup "... INCOMPLETE", "... INCOMPLETE (2)" ..."""
    base = staging.name.removesuffix(IN_PROGRESS) + label
    for attempt in range(1, 100):
        target = staging.with_name(base if attempt == 1 else f"{base} ({attempt})")
        if target.exists():
            continue
        try:
            staging.rename(target)
        except OSError:
            continue
        return target
    return staging


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _keep_times(path: Path, times: tuple[int, int]) -> None:
    """Give `path` the access and modification time of the file it is a copy of."""
    try:
        os.utime(path, ns=times)
        kept = os.stat(path).st_mtime_ns
    except OSError as exc:
        raise BackupError(f"The time of {path.name} could not be kept ({exc}).") from exc
    if abs(kept - times[1]) > 2_000_000_000:
        raise BackupError(f"The time of {path.name} could not be kept (it reads back as another time).")


def _copy_one(source: Path, destination: Path) -> CopiedFile:
    """Copy one file, never over an existing one, and verify it by size and hash."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    original = source.stat()
    with source.open("rb") as reader, destination.open("xb") as writer:
        while True:
            chunk = reader.read(HASH_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            writer.write(chunk)
    expected = digest.hexdigest()
    copied_size, copied_hash = _hash_file(destination)
    if copied_size != size or copied_hash != expected:
        raise BackupError(
            f"The copy of {source.name} does not match the original "
            f"({copied_size} of {size} bytes)."
        )
    # The original must still be what was read: a file that changed while it was
    # being copied would leave a backup of neither version.
    source_size, source_hash = _hash_file(source)
    if source_size != size or source_hash != expected:
        raise BackupError(f"{source.name} changed while it was being copied.")
    times = (original.st_atime_ns, original.st_mtime_ns)
    _keep_times(destination, times)
    return CopiedFile(Path(), size, expected, times)


def copy_save_folder(save_folder: Path, now: datetime | None = None, suffix: str = "") -> BackupResult:
    """Copy the save folder into a new Backups\\Backup <date> folder inside it.

    On any failure the partial backup is renamed "... INCOMPLETE" (never
    deleted, and never left looking like a good backup) and BackupError is
    raised.
    """
    if not save_folder.is_dir():
        raise BackupError(f"The save folder does not exist: {save_folder}")
    relatives = files_to_back_up(save_folder)
    if not relatives:
        raise BackupError(f"There is nothing to back up in {save_folder}.")
    when = now or datetime.now()
    staging = _new_backup_folder(save_folder, when, suffix)
    result = BackupResult(save_folder, staging)
    try:
        for relative in relatives:
            copied = _copy_one(save_folder / relative, staging / relative)
            copied.relative = relative
            result.files.append(copied)
        result.backup_folder = _finish_backup(staging, when, suffix)
    except (OSError, BackupError) as exc:
        where = _set_aside(staging, INCOMPLETE)
        reason = exc if isinstance(exc, BackupError) else f"{type(exc).__name__}: {exc}"
        raise BackupError(
            f"The backup could not be completed ({reason}). The partial copy "
            f"was kept as {where} and is NOT a usable backup."
        ) from exc
    return result


# ---------------------------------------------------------------------------
# Pausing the game
# ---------------------------------------------------------------------------


class ProcessController(Protocol):
    def find(self, exe_name: str) -> list[int]: ...
    def suspend(self, pid: int, exe_name: str) -> object: ...
    def resume(self, handle: object) -> None: ...


class WindowsProcesses:
    """Find, suspend and resume game processes with the Windows API."""

    PROCESS_SUSPEND_RESUME = 0x0800
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TH32CS_SNAPPROCESS = 0x00000002
    ERROR_NO_MORE_FILES = 18

    def __init__(self) -> None:
        from ctypes import wintypes

        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._ntdll = ctypes.WinDLL("ntdll")
        k = self._kernel32
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        for name in ("NtSuspendProcess", "NtResumeProcess"):
            function = getattr(self._ntdll, name)
            function.argtypes = [wintypes.HANDLE]
            function.restype = ctypes.c_long

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        self._entry_type = PROCESSENTRY32W
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k.Process32NextW.restype = wintypes.BOOL

    def find(self, exe_name: str) -> list[int]:
        k = self._kernel32
        snapshot = k.CreateToolhelp32Snapshot(self.TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == self._wintypes.HANDLE(-1).value:
            raise BackupError(
                "Could not list the running programs to check whether the game is "
                f"running (error {ctypes.get_last_error()})."
            )
        pids: list[int] = []
        try:
            entry = self._entry_type()
            entry.dwSize = ctypes.sizeof(entry)
            more = k.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.szExeFile.casefold() == exe_name.casefold():
                    pids.append(int(entry.th32ProcessID))
                more = k.Process32NextW(snapshot, ctypes.byref(entry))
            # FALSE means either "no more processes" or a failure; only the first is a complete list.
            error = ctypes.get_last_error()
            if error != self.ERROR_NO_MORE_FILES:
                raise BackupError(
                    "Could not read the whole list of running programs to check "
                    f"whether the game is running (error {error})."
                )
        finally:
            k.CloseHandle(snapshot)
        return pids

    def suspend(self, pid: int, exe_name: str) -> object:
        k = self._kernel32
        handle = k.OpenProcess(
            self.PROCESS_SUSPEND_RESUME | self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            error = ctypes.get_last_error()
            reason = "access was denied" if error == 5 else f"Windows error {error}"
            raise PauseRefused(
                f"{exe_name} (process {pid}) is running but could not be paused: {reason}."
            )
        try:
            # The process list was taken a moment ago; make sure this id still belongs to the game.
            buffer = ctypes.create_unicode_buffer(32768)
            length = self._wintypes.DWORD(len(buffer))
            if not k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                raise PauseRefused(
                    f"{exe_name} (process {pid}) could not be checked before pausing "
                    f"(Windows error {ctypes.get_last_error()})."
                )
            if Path(buffer.value).name.casefold() != exe_name.casefold():
                raise PauseRefused(f"Process {pid} is no longer {exe_name}; try the backup again.")
            status = self._ntdll.NtSuspendProcess(handle)
            if status != 0:
                raise PauseRefused(
                    f"{exe_name} (process {pid}) is running but could not be paused "
                    f"(status 0x{status & 0xFFFFFFFF:08X})."
                )
        except BaseException:
            k.CloseHandle(handle)
            raise
        return handle

    def resume(self, handle: object) -> None:
        try:
            status = self._ntdll.NtResumeProcess(handle)
            if status != 0:
                raise BackupError(
                    f"The game could not be resumed (status 0x{status & 0xFFFFFFFF:08X}). "
                    "Close it from Task Manager if it stays frozen."
                )
        finally:
            self._kernel32.CloseHandle(handle)


@dataclass
class Pause:
    count: int = 0                                   # processes paused
    problems: list[str] = field(default_factory=list)  # resumes that failed


@contextmanager
def paused_game(exe_name: str, processes: ProcessController) -> Iterator[Pause]:
    """Suspend every running process of ``exe_name``; always resume them.

    If any process cannot be paused, the ones already paused are resumed and
    PauseRefused is raised before the caller copies anything. Every paused
    process is resumed even if another's resume fails; a failed resume is
    recorded in ``Pause.problems`` (or noted on the error already on its way
    out), so a backup that succeeded is still reported as made.
    """
    pause = Pause()
    paused: list[object] = []
    failure: BaseException | None = None
    try:
        for pid in processes.find(exe_name):
            paused.append(processes.suspend(pid, exe_name))
        pause.count = len(paused)
        yield pause
    except BaseException as exc:
        failure = exc
        raise
    finally:
        errors: list[str] = []
        for handle in reversed(paused):
            try:
                processes.resume(handle)
            except Exception as exc:  # resume the rest before reporting
                errors.append(str(exc))
        if errors:
            if failure is not None:
                note = "The game could not be resumed: " + "; ".join(errors)
                if hasattr(failure, "add_note"):      # Python 3.11 and newer
                    failure.add_note(note)
                else:
                    failure.args = (*failure.args, note)
            else:
                pause.problems.extend(errors)


def back_up_save_folder(
    save_folder: Path,
    processes: ProcessController | None = None,
    now: datetime | None = None,
) -> BackupResult:
    """Pause the game that uses ``save_folder`` (if running), copy, resume."""
    controller = processes if processes is not None else WindowsProcesses()
    with paused_game(game_exe_name(save_folder), controller) as pause:
        result = copy_save_folder(save_folder, now)
    result.paused = pause.count
    result.resume_problems = list(pause.problems)
    return result


def running_game_count(save_folder: Path, processes: ProcessController | None = None) -> int:
    """How many processes of the game that saves here are running (0 if none or unknown)."""
    try:
        controller = processes if processes is not None else WindowsProcesses()
        return len(controller.find(game_exe_name(save_folder)))
    except (OSError, BackupError, AttributeError):
        return 0


def describe_size(size: int) -> str:
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Listing backups
# ---------------------------------------------------------------------------

_BACKUP_NAME = re.compile(
    r"^Backup (\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})(?: \((\d+)\))?(?: (\(before restore\)|\(before rename\)|\(before repair\)))?$"
)
# "Virtual Families3.ldw" (the slot save), its sidecar "...3.ldw.dat" and "...3.ldw.unreadable-K.dat".
# Files N+20 and N+40 are the game's two older autosave copies of slot N, so they belong to
# slot N; 0 is the shared options file (never rotated: the game rotates only n > 0); 20 and 40 are never written, so they name no slot.
_SLOT_LDW = re.compile(r"^(?:.*\D)?(\d+)\.ldw(?:\.dat|\.unreadable-\d+\.dat)?$", re.IGNORECASE)
# The patcher's per-save files: "Slot 3.ini", "Slot 3 Achievements.ini" ...
_SLOT_NAMED = re.compile(r"^Slot (\d+)\b.*$", re.IGNORECASE)
ENGINE_LOG = "ldwLog.txt"
SHARED = "shared"       # the options file (Virtual Families0.ldw): not any one slot


@dataclass
class BackupInfo:
    path: Path
    when: datetime
    before_restore: bool
    file_count: int
    size: int
    slots: list[int]     # the save slots whose own save file is in the backup
    before_rename: bool = False
    before_repair: bool = False

    @property
    def label(self) -> str:
        text = self.when.strftime("%Y-%m-%d %H:%M:%S")
        if self.before_restore:
            text += " " + BEFORE_RESTORE
        elif self.before_rename:
            text += " " + BEFORE_RENAME
        elif self.before_repair:
            text += " " + BEFORE_REPAIR
        return text


def _parse_backup_name(name: str) -> tuple[datetime, int, str] | None:
    """(when, sequence, label) -- the label "", BEFORE_RESTORE, BEFORE_RENAME or BEFORE_REPAIR."""
    match = _BACKUP_NAME.match(name)
    if not match:
        return None
    try:
        when = datetime.strptime(match.group(1), "%Y-%m-%d %H-%M-%S")
    except ValueError:
        return None
    return when, int(match.group(2) or 1), match.group(3) or ""


def file_slot(relative: Path) -> int | str:
    """The save slot a file belongs to, "engine log", or "unknown" (a file that names no slot)."""
    name = relative.name
    if name.casefold() == ENGINE_LOG.casefold():
        return "engine log"
    match = _SLOT_LDW.match(name)
    if match:
        number = int(match.group(1))
        if number == 0:
            return SHARED
        return number % 20 if number <= 45 and 1 <= number % 20 <= 5 else "unknown"
    match = _SLOT_NAMED.match(name)
    if match:
        return int(match.group(1))
    # A per-save folder: ".../Slot 3/..."
    for part in relative.parts[:-1]:
        folder = _SLOT_NAMED.match(part)
        if folder:
            return int(folder.group(1))
    return "unknown"


def slots_in(folder: Path) -> list[int]:
    """The slots whose own "Virtual Families<N>.ldw" save is directly in ``folder``."""
    slots: set[int] = set()
    try:
        for entry in folder.iterdir():
            match = re.fullmatch(r"(?:.*\D)?(\d+)\.ldw", entry.name, re.IGNORECASE)
            if match and entry.is_file():
                owner = file_slot(Path(entry.name))
                if isinstance(owner, int):
                    slots.add(owner)
    except OSError:
        pass
    return sorted(slots)


def list_backups(save_folder: Path) -> list[BackupInfo]:
    """The usable backups in ``save_folder``\\Backups, newest first.

    Only folders this tool names ("Backup <date>", "Backup <date> (2)",
    "Backup <date> (before restore)") are listed; an "... INCOMPLETE" copy is
    not a usable backup and is never offered.
    """
    backups = save_folder / BACKUPS_FOLDER
    found: list[tuple[datetime, int, BackupInfo]] = []
    if not backups.is_dir():
        return []
    for entry in backups.iterdir():
        parsed = _parse_backup_name(entry.name)
        if parsed is None or not entry.is_dir() or _is_link(entry):
            continue
        when, sequence, label = parsed
        files = files_to_back_up(entry)
        size = sum((entry / relative).stat().st_size for relative in files)
        found.append((when, sequence, BackupInfo(
            entry, when, label == BEFORE_RESTORE, len(files), size, slots_in(entry),
            label == BEFORE_RENAME, label == BEFORE_REPAIR)))
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [info for _when, _sequence, info in found]


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


@dataclass
class RestorePlan:
    save_folder: Path
    backup: Path
    slot: int | None                      # None: the whole save folder
    replace: list[Path] = field(default_factory=list)   # in both; backup's copy wins
    add: list[Path] = field(default_factory=list)       # only in the backup
    remove: list[Path] = field(default_factory=list)    # only in the save folder now
    unchanged: list[Path] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return len(self.replace) + len(self.add) + len(self.remove)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return _hash_file(a) == _hash_file(b)
    except OSError:
        return False


def _require_backup_of(save_folder: Path, backup: Path) -> None:
    """A backup must be a folder this tool made, directly inside Backups."""
    backups = (save_folder / BACKUPS_FOLDER).resolve()
    if (
        backup.resolve().parent != backups
        or _parse_backup_name(backup.name) is None
        or not backup.is_dir()
        or _is_link(backup)
    ):
        raise RestoreRefused(f"{backup} is not one of this save folder's backups.")


def plan_restore(save_folder: Path, backup: Path, slot: int | None = None) -> RestorePlan:
    """Work out exactly which files a restore replaces, adds and removes.

    Whole folder: the save folder becomes the backup -- every file in it is
    restored and every other file (outside Backups) is removed.

    One slot: only files that belong to that slot on both sides are touched.
    It is refused (RestoreRefused, nothing changed) when a file that names no
    slot differs between the backup and the save folder, because restoring the
    slot with or without it would leave the other saves inconsistent.
    """
    _require_backup_of(save_folder, backup)
    in_backup = set(files_to_back_up(backup))
    in_folder = set(files_to_back_up(save_folder))
    plan = RestorePlan(save_folder, backup, slot)
    for relative in sorted(in_backup | in_folder, key=lambda p: str(p).casefold()):
        here = relative in in_folder
        there = relative in in_backup
        if slot is not None:
            owner = file_slot(relative)
            if owner in ("engine log", SHARED):
                continue
            if owner != slot:
                if owner == "unknown" and not (
                    here and there and _same_file(save_folder / relative, backup / relative)
                ):
                    raise RestoreRefused(
                        f"Only the whole save folder can be restored from this backup: "
                        f"{relative} is a file that does not say which save it belongs to, "
                        "and it is different in the backup."
                    )
                continue
        if here and there:
            if _same_file(save_folder / relative, backup / relative):
                plan.unchanged.append(relative)
            else:
                plan.replace.append(relative)
        elif there:
            plan.add.append(relative)
        else:
            plan.remove.append(relative)
    if slot is not None and not any(file_slot(p) == slot for p in in_backup):
        raise RestoreRefused(f"This backup holds nothing for Save {slot}.")
    return plan


def _place(source: Path, target: Path) -> None:
    """Replace ``target`` with a verified copy of ``source``, atomically.

    The copy is written beside the target, checked against the source by size
    and SHA-256, and only then moved over the target with os.replace, so the
    target is at every moment either its old file or the new one.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = _hash_file(source)
    while True:
        temp = target.with_name(f"{target.name}.vf1-restore-{uuid.uuid4().hex[:12]}.tmp")
        try:
            writer = temp.open("xb")     # a name nothing else holds
        except FileExistsError:
            continue
        break
    try:
        with source.open("rb") as reader, writer:
            while True:
                chunk = reader.read(HASH_CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
        if _hash_file(temp) != expected:
            raise BackupError(f"The restored copy of {target.name} did not match the backup.")
        kept = source.stat()
        _keep_times(temp, (kept.st_atime_ns, kept.st_mtime_ns))
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    if _hash_file(target) != expected:
        raise BackupError(f"{target.name} did not match the backup after it was restored.")


@dataclass
class RestoreResult:
    plan: RestorePlan
    before_restore: BackupResult | None


def _game_running(save_folder: Path, processes: ProcessController) -> int:
    return len(processes.find(game_exe_name(save_folder)))


def restore_backup(
    save_folder: Path,
    backup: Path,
    slot: int | None = None,
    processes: ProcessController | None = None,
    now: datetime | None = None,
) -> RestoreResult:
    """Restore ``backup`` (all of it, or one slot) into ``save_folder``.

    Refused while the game is running. First backs the current state up as
    "Backup <date> (before restore)", then applies the plan file by file. On
    any failure every file already changed is put back from that before-
    restore backup, and the error says whether that succeeded.
    """
    controller = processes if processes is not None else WindowsProcesses()
    if _game_running(save_folder, controller):
        raise RestoreRefused(
            f"{game_exe_name(save_folder)} is running. Quit the game from its own "
            "menu first: a running game writes its village over the restored save "
            "when it quits. Nothing was changed."
        )
    plan = plan_restore(save_folder, backup, slot)
    if plan.changes == 0:
        return RestoreResult(plan, None)
    before = None
    if files_to_back_up(save_folder):
        before = copy_save_folder(save_folder, now, suffix=BEFORE_RESTORE)
    # The game could have been started while the safety backup was made.
    if _game_running(save_folder, controller):
        raise RestoreRefused(
            f"{game_exe_name(save_folder)} was started during the restore, so it was "
            f"stopped before anything was changed. Your current saves are also in "
            f"{before.backup_folder if before else 'the save folder'}."
        )
    done: list[Path] = []
    started = (
        f"{game_exe_name(save_folder)} was started during the restore. Quit it from "
        "its own menu and restore again."
    )
    try:
        for relative in plan.replace + plan.add:
            if _game_running(save_folder, controller):
                raise BackupError(started)
            done.append(relative)
            _place(backup / relative, save_folder / relative)
        for relative in plan.remove:
            if _game_running(save_folder, controller):
                raise BackupError(started)
            done.append(relative)
            (save_folder / relative).unlink()
    except (OSError, BackupError) as exc:
        problems = _roll_back(save_folder, before, done)
        if problems:
            raise BackupError(
                f"The restore failed ({exc}) and some files could not be put back: "
                f"{', '.join(problems)}. Your saves as they were before the restore "
                f"are in {before.backup_folder if before else '(no files)'}."
            ) from exc
        raise BackupError(
            f"The restore failed ({exc}). Every file was put back as it was; nothing changed."
        ) from exc
    return RestoreResult(plan, before)


def _roll_back(save_folder: Path, before: BackupResult | None, done: list[Path]) -> list[str]:
    problems: list[str] = []
    for relative in reversed(done):
        target = save_folder / relative
        original = before.backup_folder / relative if before else None
        try:
            if original is not None and original.is_file():
                _place(original, target)
            elif target.exists():
                target.unlink()
        except (OSError, BackupError):
            problems.append(str(relative))
    return problems


DELETING = " (deleting)"


def _clear_read_only(path: str) -> None:
    """Clear the read-only attribute, which OneDrive and Explorer set on folders."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def delete_backup(save_folder: Path, backup: Path) -> None:
    """Delete one backup folder, which must be one of this save folder's backups.

    The folder is first renamed "... (deleting)", which takes it off the list
    in one step, so a delete that is interrupted part-way never leaves a
    half-emptied folder that still looks like a usable backup.
    """
    _require_backup_of(save_folder, backup)
    doomed = backup.with_name(backup.name + DELETING)
    try:
        backup.rename(doomed)
    except OSError as exc:
        raise BackupError(
            f"The backup could not be deleted ({exc}); nothing was deleted. "
            "If another program has it open, close that and try again."
        ) from exc

    def retry_writable(function, path, _error):
        _clear_read_only(path)
        parent = os.path.dirname(path)
        if parent:
            _clear_read_only(parent)
        function(path)

    last: OSError | None = None
    for _attempt in range(DELETE_ATTEMPTS):
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(doomed, onexc=retry_writable)
            else:
                shutil.rmtree(doomed, onerror=retry_writable)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last = exc
            time.sleep(DELETE_RETRY_SECONDS)
    raise BackupError(
        f"The backup was taken off the list but its folder could not be removed "
        f"completely ({last}). You can delete {doomed} yourself; it is no longer "
        "a usable backup."
    )
