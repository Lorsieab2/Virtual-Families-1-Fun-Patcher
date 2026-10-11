#!/usr/bin/env python3
"""Virtual Families 1 Patcher: build or reconfigure a modded copy of the game.

Ported from the Virtual Families 2 Restoration/Addition Patcher
(offline_vf2_patcher.py): the same apply / settings / restore commands, the
same backups, logs and settings handling, for VF1's one-executable-plus-DLL
design.

The patched game is written to a SEPARATE folder; the vanilla game folder is
only read. The executable gets one loader and two new sections:

* .vf1fun (read + execute): a stub entered at game start-up (theGame's Init
  vtable slot) and at the end of the store screen's constructor. It loads
  "<game folder>\\Virtual Families 1 Patcher Files\\vf1fun.dll" by full path
  (GetModuleFileNameW + LoadLibraryW, resolved through GetProcAddress) and
  calls into it. A missing DLL or export means the stock game.
* .vf1fud (read + write): the stub's state and path buffer. No page is both
  writable and executable.

Everything else lives in vf1fun.dll. Which patches are on is decided by
"Virtual Families 1 Patcher Files\\settings.ini", section [Patches], Key=1/0,
which the DLL reads. The settings, their descriptions, defaults and
dependencies come from manifest.json. Enable/Disable Patches on an existing
modded folder rewrites settings.ini (and adds or removes a setting's own
files); it never needs to re-patch the executable.

usage:
  vf1_patcher.py apply --game-dir VANILLA [--output-dir NEW] [--enable ID] [--disable ID] [--dry-run]
  vf1_patcher.py apply --output-dir EXISTING_MODDED_FOLDER [--enable ID] [--disable ID]
  vf1_patcher.py apply --exe "<your game folder>/Virtual Families.exe"
  vf1_patcher.py settings [--manifest manifest.json] [--json OUT]
  vf1_patcher.py restore --backup-dir BACKUP
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


VANILLA_EXE = "Virtual Families.exe"
VANILLA_SHA256 = "5db828c3f53c68696c18719aec0eb114be3fd4458ae2cbf185d8d4ef7eca4487"
PATCHER_FOLDER = "Virtual Families 1 Patcher Files"
DLL_NAME = "vf1fun.dll"
SETTINGS_INI = "settings.ini"
SETTINGS_SECTION = "Patches"
DLL_REL = f"{PATCHER_FOLDER}/{DLL_NAME}"
REPLACEABLE_FOLDERS = ("Images",)  # game folders whose files a setting may replace
ORIGINALS_FOLDER = f"{PATCHER_FOLDER}/Original Files"  # the replaced game files' originals, while their setting is on


def original_store_rel(target: str) -> str:
    return f"{ORIGINALS_FOLDER}/{target}"
SETTINGS_REL = f"{PATCHER_FOLDER}/{SETTINGS_INI}"
BACKUP_MANIFEST = "vf1_patch_backup_manifest.json"
DEFAULT_BACKUP_ROOT = ".vf1_patch_backups"
DEFAULT_MANIFEST = Path(__file__).resolve().with_name("manifest.json")
DEFAULT_OUTPUT_FOLDER = "Virtual Families - Modded"
DEFAULT_MODDED_EXE = "Virtual Families - Modded.exe"
VANILLA_SAVE_FOLDER = "Virtual Families"
# What the game needs to run; the patched copy is built from these.
REQUIRED_INSTALL_ENTRIES = (
    VANILLA_EXE, "Assets", "Images", "Sounds", "fmod.dll", "SDL2.dll", "SDL2_image.dll",
)
INVALID_INSTALL_MESSAGE = (
    "No valid Virtual Families installation detected! Are you sure you downloaded it from the official website?\n\n"
    "Links:\n"
    "http://www.ldw.com/\n"
    "http://www.virtualfamilies.com/index.php"
)

# theStoreScene constructor tail: `mov ecx, esi; call 0x448BE0` (8B CE E8 rel32).
HOOK_SITE = 0x4497E6
HOOK_ORIGINAL_TARGET = 0x448BE0
HOOK_EXPECTED = bytes.fromhex("e8 f5 f3 ff ff")
# KERNEL32 imports already present in the vanilla import table.
IAT_GET_MODULE_HANDLE_A = 0x4B21D4
IAT_GET_PROC_ADDRESS = 0x4B21D8


class PatchError(RuntimeError):
    """Raised for any validation or patching failure."""


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


class PE:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        d = self.data
        self.pe = struct.unpack_from("<I", d, 0x3C)[0]
        self.nsec_off = self.pe + 6
        self.opt = self.pe + 24
        self.optsz = struct.unpack_from("<H", d, self.pe + 20)[0]
        self.base = struct.unpack_from("<I", d, self.opt + 28)[0]
        self.sect_align, self.file_align = struct.unpack_from("<II", d, self.opt + 32)

    @property
    def nsec(self):
        return struct.unpack_from("<H", self.data, self.nsec_off)[0]

    def sections(self):
        out = []
        for i in range(self.nsec):
            o = self.opt + self.optsz + i * 40
            name = bytes(self.data[o:o + 8]).rstrip(b"\0").decode()
            vsize, va, rsize, raw = struct.unpack_from("<IIII", self.data, o + 8)
            out.append((name, va, vsize, raw, rsize))
        return out

    def offset(self, va: int) -> int:
        rva = va - self.base
        for _n, sva, vsize, raw, rsize in self.sections():
            if sva <= rva < sva + max(vsize, rsize):
                return raw + rva - sva
        raise PatchError(f"address {va:#x} is not in the file")

    def next_section_va(self) -> int:
        last = self.sections()[-1]
        return self.base + _align(last[1] + max(last[2], last[4]), self.sect_align)

    def add_section(self, name: str, payload: bytes, characteristics: int) -> int:
        hdr = self.opt + self.optsz + self.nsec * 40
        first_raw = min(s[3] for s in self.sections() if s[3])
        if hdr + 40 > first_raw:
            raise PatchError("no room for another section header")
        if any(self.data[hdr:hdr + 40]):
            raise PatchError("section header slot is not empty")
        va = self.next_section_va()
        raw = _align(len(self.data), self.file_align)
        rsize = _align(len(payload), self.file_align)
        self.data.extend(b"\0" * (raw - len(self.data)))
        self.data.extend(payload + b"\0" * (rsize - len(payload)))
        struct.pack_into("<8sIIIIIIHHI", self.data, hdr, name.encode().ljust(8, b"\0"),
                         len(payload), va - self.base, rsize, raw, 0, 0, 0, 0, characteristics)
        struct.pack_into("<H", self.data, self.nsec_off, self.nsec + 1)
        struct.pack_into("<I", self.data, self.opt + 56, _align(va - self.base + len(payload), self.sect_align))
        return va

    def update_checksum(self):
        off = self.opt + 64
        struct.pack_into("<I", self.data, off, 0)
        total = 0
        d = bytes(self.data) + b"\0" * (len(self.data) % 2)
        for (word,) in struct.iter_unpack("<H", d):
            total += word
            total = (total & 0xFFFF) + (total >> 16)
        total = (total & 0xFFFF) + (total >> 16)
        struct.pack_into("<I", self.data, off, (total + len(self.data)) & 0xFFFFFFFF)


STUB = Path(__file__).resolve().with_name("stub.json")
# theGame's vtable slot for Init (slot 4); stock value theGame::Init.
INIT_SLOT = 0x4B5E14
INIT_SLOT_EXPECTED = 0x422AE0
# theGame's vtable slot for GameUpdate (slot 7), called once per frame by
# ldwGame::Run (0x402CC0); stock value theGame::GameUpdate.
UPDATE_SLOT = 0x4B5E20
UPDATE_SLOT_EXPECTED = 0x422D90


def patch_executable(vanilla: bytes) -> bytes:
    """Return the patched executable. The stub (built by tools/build_stub.py
    and stored in stub.json) gets its own read-execute section, its state a
    separate read-write section, and two pointers in the game lead into it."""
    if hashlib.sha256(vanilla).hexdigest() != VANILLA_SHA256:
        raise PatchError("this is not the vanilla Virtual Families 1.01.00 executable")
    stub = json.loads(STUB.read_text())
    code_va, data_va = int(stub["code_va"], 16), int(stub["data_va"], 16)
    pe = PE(vanilla)
    site = pe.offset(HOOK_SITE)
    if bytes(pe.data[site:site + 5]) != HOOK_EXPECTED:
        raise PatchError("unexpected bytes at the store hook")
    slot = pe.offset(INIT_SLOT)
    if struct.unpack_from("<I", pe.data, slot)[0] != INIT_SLOT_EXPECTED:
        raise PatchError("unexpected theGame::Init vtable slot")
    update = pe.offset(UPDATE_SLOT)
    if struct.unpack_from("<I", pe.data, update)[0] != UPDATE_SLOT_EXPECTED:
        raise PatchError("unexpected theGame::GameUpdate vtable slot")
    if pe.next_section_va() != code_va:
        raise PatchError("the stub was built for a different section address")
    pe.add_section(".vf1fun", bytes.fromhex(stub["code"]), 0x60000020)  # code | execute | read
    if pe.add_section(".vf1fud", bytes(stub["data_size"]), 0xC0000040) != data_va:  # data | read | write
        raise PatchError("data section landed at an unexpected address")
    rel = int(stub["store_entry"], 16) - (HOOK_SITE + 5)
    pe.data[site:site + 5] = bytes([0xE8]) + struct.pack("<i", rel)
    struct.pack_into("<I", pe.data, slot, int(stub["init_entry"], 16))
    struct.pack_into("<I", pe.data, update, int(stub["tick_entry"], 16))
    pe.update_checksum()
    return bytes(pe.data)


def executable_patch_state(data: bytes) -> str:
    """What an executable is, without needing the vanilla one to compare with.

    "vanilla": the stock 1.01.00 executable. "current": patched by THIS
    patcher's loader (same stub bytes, both hooks into it). "other_version":
    carries the .vf1fun section but a different loader, so it needs a rebuild
    from the vanilla folder. "unknown": anything else.
    """
    if hashlib.sha256(data).hexdigest() == VANILLA_SHA256:
        return "vanilla"
    try:
        pe = PE(data)
        sections = {s[0]: s for s in pe.sections()}
        if ".vf1fun" not in sections:
            return "unknown"
        stub = json.loads(STUB.read_text())
        code = bytes.fromhex(stub["code"])
        _name, va, _vsize, raw, _rsize = sections[".vf1fun"]
        if pe.base + va != int(stub["code_va"], 16) or bytes(pe.data[raw:raw + len(code)]) != code:
            return "other_version"
        site = pe.offset(HOOK_SITE)
        rel = struct.unpack_from("<i", pe.data, site + 1)[0]
        if pe.data[site] != 0xE8 or HOOK_SITE + 5 + rel != int(stub["store_entry"], 16):
            return "other_version"
        if struct.unpack_from("<I", pe.data, pe.offset(INIT_SLOT))[0] != int(stub["init_entry"], 16):
            return "other_version"
    except (struct.error, PatchError, UnicodeDecodeError, IndexError, ValueError):
        return "unknown"
    return "current"


# --------------------------------------------------------------------- helpers

def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise PatchError("Manifest root must be a JSON object.")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def emit_progress(args: argparse.Namespace, message: str) -> None:
    callback = getattr(args, "progress_callback", None)
    if callback is not None:
        callback(message)
    else:
        print(message)


def log_process_event(process_log: list[dict[str, Any]], *, phase: str, kind: str, status: str,
                      file_path: str | None = None, note: str = "", error: str | None = None,
                      **extra: Any) -> None:
    row: dict[str, Any] = {"timestamp_utc": utc_now(), "phase": phase, "kind": kind, "status": status}
    if file_path is not None:
        row["file_path"] = file_path
    if note:
        row["note"] = note
    if error:
        row["error"] = error
    row.update(extra)
    process_log.append(row)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_setting_id(value: Any, field: str = "setting id") -> str:
    """Setting ids are settings.ini keys, so they stay plain identifiers."""
    if not isinstance(value, str) or not value.strip():
        raise PatchError(f"{field} must be a non-empty string.")
    setting_id = value.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", setting_id):
        raise PatchError(f"{field} contains unsupported characters: {value!r}")
    return setting_id


def split_cli_ids(values: list[str] | None, field: str) -> list[str]:
    ids: list[str] = []
    for value in values or []:
        for part in value.split(","):
            part = part.strip()
            if part:
                ids.append(normalize_setting_id(part, field))
    return ids


def normalize_rel_path(value: Any, field: str = "file path") -> str:
    """A relative path in forward-slash form, with no '.', '..' or drive."""
    if not isinstance(value, str) or not value.strip():
        raise PatchError(f"{field} must be a non-empty relative path.")
    raw = value.replace("\\", "/").strip()
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise PatchError(f"{field} must be relative: {value!r}")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PatchError(f"{field} must not contain '.', '..', or empty segments: {value!r}")
    return "/".join(parts)


def path_key(rel_path: str) -> str:
    """Windows compares file names without case."""
    return rel_path.replace("\\", "/").casefold()


def reject_symlink_components(candidate: Path, root: Path, rel_path: str) -> None:
    current = root
    for part in Path(rel_path).parts:
        current = current / part
        if current.is_symlink():
            raise PatchError(f"Symlink path components are not allowed: {rel_path}")


def resolve_under(root_dir: Path, rel_path: str, what: str = "game directory") -> Path:
    root = root_dir.resolve()
    candidate = root / rel_path
    reject_symlink_components(candidate, root, rel_path)
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise PatchError(f"Path escapes {what}: {rel_path}")
    return resolved


def make_writable(path: Path) -> None:
    """Clear the read-only attribute of a file the patcher is about to replace or delete.

    shutil.copy2 carries the attribute over from the vanilla install, and
    Windows refuses to replace or delete a read-only file. Symlinks are left
    alone so the chmod cannot reach outside the tree.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        return
    if not info.st_mode & stat.S_IWRITE:
        os.chmod(path, stat.S_IMODE(info.st_mode) | stat.S_IWRITE)


def _retry_after_clearing_read_only(func: Callable[..., Any], path: str, exc: Any) -> None:
    error = exc if isinstance(exc, BaseException) else exc[1]
    if not isinstance(error, PermissionError) or os.path.islink(path):
        raise error
    make_writable(Path(path))
    func(path)


def remove_output_entry(path: Path) -> None:
    """Delete one top-level entry of a modded output folder, including read-only files."""
    if path.is_dir() and not path.is_symlink():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_retry_after_clearing_read_only)
        else:
            shutil.rmtree(path, onerror=_retry_after_clearing_read_only)
    else:
        make_writable(path)
        path.unlink()


def atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".vf1patch.tmp")
    if temp.is_symlink():
        raise PatchError(f"Temporary patch path must not be a symlink: {temp}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(data)
    make_writable(path)
    temp.replace(path)


def documents_dir() -> Path:
    """The Documents folder the game saves under (it follows OneDrive redirection)."""
    if sys.platform == "win32":
        buffer = ctypes.create_unicode_buffer(260)
        # CSIDL_PERSONAL = 5
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    return Path.home() / "Documents"


def save_dir_for_exe(exe_name: str) -> Path:
    """LDW games keep their saves in Documents\\LDW\\<executable name>."""
    return documents_dir() / "LDW" / Path(exe_name).stem


# -------------------------------------------------------------------- manifest

@dataclass(frozen=True)
class SettingFile:
    source: str  # relative to the payload folder
    target: str  # relative to the game folder: inside PATCHER_FOLDER, or (replaces) a game file under REPLACEABLE_FOLDERS
    replaces: bool = False  # True: target is a game file; its original is kept in ORIGINALS_FOLDER while this is on


@dataclass(frozen=True)
class PatchSetting:
    id: str
    label: str
    description: str
    default: bool
    category: str = "main"
    requires: tuple[str, ...] = ()
    files: tuple[SettingFile, ...] = ()


def manifest_settings(manifest: dict[str, Any]) -> dict[str, PatchSetting]:
    """The manifest's settings, validated. Adding a setting means adding a row."""
    raw_settings = manifest.get("settings", [])
    if not isinstance(raw_settings, list):
        raise PatchError("Manifest 'settings' must be an array.")
    settings: dict[str, PatchSetting] = {}
    seen_keys: set[str] = set()
    seen_targets: dict[str, str] = {}
    reserved = {path_key(DLL_REL), path_key(SETTINGS_REL)}
    for index, raw in enumerate(raw_settings):
        if not isinstance(raw, dict):
            raise PatchError(f"Setting #{index} must be an object.")
        setting_id = normalize_setting_id(raw.get("id"), f"setting #{index} id")
        if setting_id.casefold() in seen_keys:
            # settings.ini keys are not case-sensitive.
            raise PatchError(f"Duplicate setting id: {setting_id}")
        seen_keys.add(setting_id.casefold())
        default = raw.get("default", False)
        if not isinstance(default, bool):
            raise PatchError(f"Setting {setting_id}: default must be true or false.")
        category = str(raw.get("category", "main")).strip().lower() or "main"
        requires_raw = raw.get("requires", [])
        if not isinstance(requires_raw, list):
            raise PatchError(f"Setting {setting_id}: requires must be an array of setting ids.")
        requires = tuple(normalize_setting_id(r, f"setting {setting_id} requires") for r in requires_raw)
        if setting_id in requires:
            raise PatchError(f"Setting {setting_id} cannot require itself.")
        files_raw = raw.get("files", [])
        if not isinstance(files_raw, list):
            raise PatchError(f"Setting {setting_id}: files must be an array.")
        files = []
        for file_index, row in enumerate(files_raw):
            if not isinstance(row, dict):
                raise PatchError(f"Setting {setting_id}: file #{file_index} must be an object.")
            source = normalize_rel_path(row.get("source"), f"setting {setting_id} file source")
            target = normalize_rel_path(row.get("target"), f"setting {setting_id} file target")
            replaces = row.get("replaces", False)
            if not isinstance(replaces, bool):
                raise PatchError(f"Setting {setting_id}: file #{file_index} replaces must be true or false.")
            if replaces:
                # A few settings change the game's own art by replacing its files in the
                # modded copy (the owner's choice, as in the Virtual Families 2 patcher).
                # The original is kept in ORIGINALS_FOLDER and put back when the setting is off.
                if not any(path_key(target).startswith(path_key(folder) + "/") for folder in REPLACEABLE_FOLDERS):
                    raise PatchError(f"Setting {setting_id}: a replaced game file must be under "
                                     f"{' or '.join(REPLACEABLE_FOLDERS)}: {target}")
            # Every other patcher file lives in its own folder, so switching a setting
            # off simply removes its files: none of them replaces a game file.
            elif not path_key(target).startswith(path_key(PATCHER_FOLDER) + "/"):
                raise PatchError(f"Setting {setting_id}: file targets must be inside {PATCHER_FOLDER}/: {target}")
            if path_key(target) in reserved:
                raise PatchError(f"Setting {setting_id}: {target} belongs to the patcher itself.")
            if path_key(target) in seen_targets:
                raise PatchError(f"{target} is installed by both {seen_targets[path_key(target)]} and {setting_id}.")
            seen_targets[path_key(target)] = setting_id
            files.append(SettingFile(source, target, replaces))
        label = str(raw.get("label", setting_id)).strip() or setting_id
        settings[setting_id] = PatchSetting(
            id=setting_id,
            label=label,
            description=str(raw.get("description", "")).strip(),
            default=default,
            category=category,
            requires=requires,
            files=tuple(files),
        )
    for setting in settings.values():
        unknown = [r for r in setting.requires if r not in settings]
        if unknown:
            raise PatchError(f"Setting {setting.id} requires unknown setting(s): {', '.join(unknown)}")
    setting_prerequisites(settings)  # rejects cycles
    return settings


def setting_dependencies(settings: dict[str, PatchSetting]) -> dict[str, frozenset[str]]:
    """Each setting's direct prerequisites, as the manifest states them."""
    return {setting_id: frozenset(setting.requires) for setting_id, setting in settings.items()}


def setting_prerequisites(settings: dict[str, PatchSetting]) -> dict[str, frozenset[str]]:
    """Each setting's transitive prerequisites. A cycle is a manifest error."""
    direct = setting_dependencies(settings)
    result: dict[str, frozenset[str]] = {}
    for setting_id in settings:
        seen: set[str] = set()
        stack = list(direct.get(setting_id, ()))
        while stack:
            other = stack.pop()
            if other == setting_id:
                raise PatchError(f"Setting {setting_id} depends on itself through its prerequisites.")
            if other in seen:
                continue
            seen.add(other)
            stack.extend(direct.get(other, ()))
        result[setting_id] = frozenset(seen)
    return result


def requires_note(prerequisites: frozenset[str] | tuple[str, ...], settings: dict[str, PatchSetting]) -> str:
    """The bold dependency note shown after a description (the owner's convention)."""
    if not prerequisites:
        return ""
    labels = ", ".join(settings[other].label if other in settings else other for other in sorted(prerequisites))
    return f" **Requires: {labels}.**"


def resolve_enabled_settings(settings: dict[str, PatchSetting], args: argparse.Namespace) -> set[str]:
    """What was ticked: the defaults, then --enable-all/--disable-all, then each --enable/--disable."""
    enabled = {setting_id for setting_id, setting in settings.items() if setting.default}
    if getattr(args, "disable_all", False):
        enabled = set()
    if getattr(args, "enable_all", False):
        enabled = set(settings)
    enable = split_cli_ids(getattr(args, "enable", None), "--enable")
    disable = split_cli_ids(getattr(args, "disable", None), "--disable")
    unknown = sorted({s for s in enable + disable if s not in settings})
    if unknown:
        raise PatchError(f"Unknown setting(s): {', '.join(unknown)}. Known: {', '.join(settings) or '(none)'}")
    both = sorted(set(enable) & set(disable))
    if both:
        raise PatchError(f"Setting(s) both enabled and disabled: {', '.join(both)}")
    enabled |= set(enable)
    enabled -= set(disable)
    return enabled


def effective_settings_report(settings: dict[str, PatchSetting], selected: set[str]) -> dict[str, Any]:
    """What the selection actually does, as opposed to what was ticked.

    A ticked setting whose prerequisite is unticked stays off in settings.ini
    and is reported as "selected but inactive".
    """
    prerequisites = setting_prerequisites(settings)
    enabled: set[str] = set()
    inactive: dict[str, str] = {}
    for setting_id in settings:
        if setting_id not in selected:
            continue
        missing = sorted(prerequisites[setting_id] - selected)
        if missing:
            inactive[setting_id] = "selected but inactive: requires " + ", ".join(
                settings[m].label for m in missing)
        else:
            enabled.add(setting_id)
    return {"enabled": enabled, "inactive": inactive}


def settings_log(settings: dict[str, PatchSetting], selected: set[str],
                 report: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = set(selected) if report is None else set(report["enabled"])
    inactive: dict[str, str] = {} if report is None else dict(report["inactive"])
    log: dict[str, Any] = {
        "enabled": sorted(effective),
        "disabled": sorted(set(settings) - effective - set(inactive)),
        "available": [
            {
                "id": setting.id,
                "label": setting.label,
                "description": setting.description,
                "default": setting.default,
                "category": setting.category,
                "requires": list(setting.requires),
                "files": [f.target for f in setting.files],
                "enabled": setting.id in effective,
                **({"selected": setting.id in selected} if report is not None else {}),
                **({"inactive_reason": inactive[setting.id]} if setting.id in inactive else {}),
            }
            for setting in settings.values()
        ],
    }
    if report is not None:
        log["selected"] = sorted(selected)
        log["selected_but_inactive"] = dict(sorted(inactive.items()))
    return log


def manifest_output_folder_name(manifest: dict[str, Any]) -> str:
    raw = manifest.get("output", {})
    name = str(raw.get("default_folder_name", "")).strip() if isinstance(raw, dict) else ""
    name = name or DEFAULT_OUTPUT_FOLDER
    if "/" in normalize_rel_path(name, "manifest output folder name"):
        raise PatchError("Manifest output folder name must be a single folder name.")
    return name


def validate_exe_name(name: str) -> str:
    """The modded executable's name.

    It must never contain "patch": Windows treats an executable whose name
    contains "patch", "setup", "install" or "update" as an installer and asks
    for administrator rights. It must not be the vanilla name either, so the
    modded game keeps its own save folder.
    """
    name = (name or "").strip()
    if not name or "/" in name.replace("\\", "/") or not name.lower().endswith(".exe") or len(name) <= 4:
        raise PatchError(f"The modded executable name must be a single .exe file name: {name!r}")
    if re.search(r'[<>:"|?*\x00-\x1f]', name):
        raise PatchError(f"The modded executable name contains characters Windows does not allow: {name!r}")
    if "patch" in name.lower():
        raise PatchError(
            f"The modded executable name must not contain \"patch\" (Windows would treat it as an installer): {name!r}")
    if name.lower() == VANILLA_EXE.lower():
        raise PatchError(f"The modded executable name must not be the vanilla {VANILLA_EXE} name.")
    return name


def manifest_output_exe_name(manifest: dict[str, Any]) -> str:
    raw = manifest.get("output", {})
    name = str(raw.get("default_exe_name", "")).strip() if isinstance(raw, dict) else ""
    return validate_exe_name(name or DEFAULT_MODDED_EXE)


def default_output_parent(game_dir: Path) -> Path:
    """Where the modded folder goes when no folder is chosen.

    Next to the vanilla folder, as in the VF2 patcher -- unless the game is
    under Program Files, where a new folder needs administrator rights; then
    in the user's own Games folder.
    """
    game_dir = game_dir.resolve()
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(var)
        if base:
            try:
                base_path = Path(base).resolve()
            except OSError:
                continue
            if base_path == game_dir or base_path in game_dir.parents:
                return Path.home() / "Games"
    return game_dir.parent


def resolve_apply_output_dir(args: argparse.Namespace, game_dir: Path, manifest: dict[str, Any]) -> Path:
    explicit = getattr(args, "output_dir", None)
    if explicit:
        return Path(explicit).resolve()
    parent = getattr(args, "output_parent_dir", None)
    parent_dir = Path(parent).resolve() if parent else default_output_parent(game_dir)
    return (parent_dir / manifest_output_folder_name(manifest)).resolve()


def manifest_payload_pins(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{payload-relative path: {"sha256", "size"}}, written by tools/package_release.py."""
    raw = manifest.get("payload", {})
    if not isinstance(raw, dict):
        raise PatchError("Manifest 'payload' must be an object.")
    pins = {}
    for rel, row in raw.items():
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
            raise PatchError(f"Manifest payload entry {rel!r} must have a sha256.")
        pins[path_key(normalize_rel_path(rel, "payload path"))] = row
    return pins


# --------------------------------------------------------------------- payload

def payload_dir(manifest_path: Path) -> Path:
    return manifest_path.parent / "payload"


def resolve_dll_source(args: argparse.Namespace, manifest_path: Path) -> tuple[Path, bool]:
    """(path of vf1fun.dll to install, whether it comes from the bundle's payload)."""
    override = getattr(args, "dll", None)
    if override:
        return Path(override).resolve(), False
    bundled = payload_dir(manifest_path) / DLL_NAME
    if bundled.is_file():
        return bundled.resolve(), True
    # Running from a source checkout: native\build.bat writes build\vf1fun.dll.
    checkout = manifest_path.parent.parent / "build" / DLL_NAME
    if checkout.is_file():
        return checkout.resolve(), False
    raise PatchError(f"{DLL_NAME} is missing. Expected it at: {bundled}")


def read_payload(path: Path, rel: str, pins: dict[str, dict[str, Any]], pinned: bool) -> bytes:
    if not path.is_file():
        raise PatchError(f"Payload file is missing: {path}")
    data = path.read_bytes()
    pin = pins.get(path_key(rel)) if pinned else None
    if pin is not None:
        actual = sha256_bytes(data)
        if actual != pin["sha256"].lower():
            raise PatchError(f"Payload file {rel} does not match manifest.json (SHA-256 {actual}, expected {pin['sha256']}).")
        if "size" in pin and len(data) != int(pin["size"]):
            raise PatchError(f"Payload file {rel} has size {len(data)}, expected {pin['size']}.")
    return data


# ---------------------------------------------------------------- settings.ini

INI_COMMENT = "; Written by the Virtual Families 1 Patcher: 1 = on, 0 = off. Change these with Enable/Disable Patches."


def _decode_ini(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16"
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    # Windows profile files are ANSI; latin-1 round-trips every byte unchanged.
    return data.decode("latin-1"), "latin-1"


def render_settings_ini(existing: bytes | None, values: dict[str, int]) -> bytes:
    """settings.ini with [Patches] set to `values`, everything else kept as it was.

    The DLL keeps its own values in other sections ([Cheats] InterestRate is
    remembered between sessions), so those are never touched. Keys in
    [Patches] that the manifest does not know are kept too.
    """
    text, encoding = _decode_ini(existing) if existing else ("", "latin-1")
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            blocks.append((stripped[1:stripped.index("]")].strip(), [line]))
        else:
            blocks[-1][1].append(line)

    written: set[str] = set()
    out: list[str] = []
    found = False
    for name, body in blocks:
        if name is None or name.casefold() != SETTINGS_SECTION.casefold():
            out.extend(body)
            continue
        found = True
        kept: list[str] = [body[0]]
        for line in body[1:]:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith(";"):
                key = stripped.split("=", 1)[0].strip()
                match = next((k for k in values if k.casefold() == key.casefold()), None)
                if match is not None:
                    if match not in written:
                        kept.append(f"{match}={values[match]}")
                        written.add(match)
                    continue
            kept.append(line)
        # New keys go after the section's last non-blank line.
        trailing = []
        while len(kept) > 1 and not kept[-1].strip():
            trailing.append(kept.pop())
        for key, value in values.items():
            if key not in written:
                kept.append(f"{key}={value}")
                written.add(key)
        out.extend(kept + trailing)
    if not found:
        while out and not out[-1].strip():
            out.pop()
        if out:
            out.append("")
        out.append(f"[{SETTINGS_SECTION}]")
        out.append(INI_COMMENT)
        out.extend(f"{key}={value}" for key, value in values.items())
    rendered = "\r\n".join(out) + "\r\n"
    return rendered.encode(encoding)


def read_ini_section(data: bytes | None, section: str) -> dict[str, str]:
    """The keys of one section, as GetPrivateProfileString would see them (first wins)."""
    if not data:
        return {}
    text, _ = _decode_ini(data)
    current = None
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            current = stripped[1:stripped.index("]")].strip()
            continue
        if current is not None and current.casefold() == section.casefold() and "=" in stripped \
                and not stripped.startswith(";"):
            key, value = stripped.split("=", 1)
            values.setdefault(key.strip(), value.strip())
    return values


# ------------------------------------------------------------- install checks

def validate_vanilla_install(game_dir: Path) -> bytes:
    """Check the vanilla folder and return its executable's bytes."""
    if not game_dir.is_dir():
        raise PatchError(f"{INVALID_INSTALL_MESSAGE}\n\nDetails: the folder does not exist: {game_dir}")
    if is_recognized_modded_output_dir(game_dir):
        raise PatchError(
            f"{INVALID_INSTALL_MESSAGE}\n\nDetails: this folder holds an already-patched game; choose the original "
            "game folder, or leave the vanilla game folder empty to reconfigure this modded folder.")
    missing = [entry for entry in REQUIRED_INSTALL_ENTRIES if not (game_dir / entry).exists()]
    if missing:
        raise PatchError(f"{INVALID_INSTALL_MESSAGE}\n\nDetails: missing from {game_dir}: {', '.join(missing)}")
    data = (game_dir / VANILLA_EXE).read_bytes()
    state = executable_patch_state(data)
    if state != "vanilla":
        detail = ("this folder holds an already-patched game; choose the original game folder"
                  if state in ("current", "other_version") else
                  f"{VANILLA_EXE} is not the Virtual Families 1.01.00 executable (SHA-256 {sha256_bytes(data)})")
        raise PatchError(f"{INVALID_INSTALL_MESSAGE}\n\nDetails: {detail}")
    return data


def is_recognized_modded_output_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / DEFAULT_BACKUP_ROOT).is_dir() or (path / PATCHER_FOLDER).is_dir()


def check_output_dir_refresh_allowed(game_dir: Path, output_dir: Path) -> None:
    """Refuse an output folder the refresh must not touch.

    Runs BEFORE anything is written: once a backup folder exists inside it,
    any folder would look like a modded output folder, and the refresh would
    move the user's own files into a backup and delete them.
    """
    source_root = game_dir.resolve()
    output_root = output_dir.resolve()
    if output_root == source_root:
        raise PatchError("The modded output folder must be a separate folder, not the vanilla game folder.")
    if output_root in source_root.parents or source_root in output_root.parents:
        raise PatchError("Output directory must be a sibling or separate folder, not inside the vanilla game folder.")
    if output_root.exists() and not output_root.is_dir():
        raise PatchError(f"Output path is a file, not a folder: {output_root}")
    if output_root.exists() and any(output_root.iterdir()) and not is_recognized_modded_output_dir(output_root):
        raise PatchError(
            "Output directory already exists and is not recognized as a Virtual Families modded output folder: "
            f"{output_root}")


def vanilla_rel_files(game_dir: Path) -> list[str]:
    """Every file of the vanilla folder the modded copy gets, except the executable."""
    files = []
    for source in sorted(game_dir.rglob("*")):
        rel = source.relative_to(game_dir)
        if rel.parts[0] == DEFAULT_BACKUP_ROOT:
            continue
        if source.is_file() and not (len(rel.parts) == 1 and rel.name.lower() == VANILLA_EXE.lower()):
            files.append(rel.as_posix())
    return files


def existing_output_files(output_dir: Path) -> list[str]:
    if not output_dir.is_dir():
        return []
    files = []
    for existing in sorted(output_dir.rglob("*")):
        rel = existing.relative_to(output_dir)
        if rel.parts[0] == DEFAULT_BACKUP_ROOT or not existing.is_file():
            continue
        files.append(rel.as_posix())
    return files


def prepare_output_dir(game_dir: Path, output_dir: Path, args: argparse.Namespace) -> int:
    """Empty the output folder (except backups) and copy the vanilla files in. Returns the file count."""
    check_output_dir_refresh_allowed(game_dir, output_dir)
    if output_dir.exists() and any(child.name != DEFAULT_BACKUP_ROOT for child in output_dir.iterdir()):
        emit_progress(args, f"Refreshing modded output folder from vanilla install: {output_dir}")
        for child in output_dir.iterdir():
            if child.name == DEFAULT_BACKUP_ROOT:
                continue
            remove_output_entry(child)
    elif output_dir.exists():
        emit_progress(args, f"Refreshing empty modded output folder from vanilla install: {output_dir}")
    else:
        emit_progress(args, f"Creating modded output folder: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel in vanilla_rel_files(game_dir):
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(game_dir / rel, target)
        # copy2 carries a read-only attribute over from the vanilla file, and
        # the next refresh or reconfigure could then not replace it.
        make_writable(target)
        count += 1
    return count


def find_modded_executable(output_dir: Path, preferred: str) -> tuple[Path, str]:
    """The patched executable in an existing modded folder, and its patch state."""
    candidates = [p for p in output_dir.glob("*.exe") if p.is_file() and p.name.lower() != "uninst.exe"]
    candidates.sort(key=lambda p: (p.name.lower() != preferred.lower(), p.name.lower()))
    other = None
    for path in candidates:
        state = executable_patch_state(path.read_bytes())
        if state == "current":
            return path, state
        if state == "other_version" and other is None:
            other = path
    if other is not None:
        return other, "other_version"
    raise PatchError(f"No executable patched by the Virtual Families 1 Patcher was found in {output_dir}.")


# --------------------------------------------------------------------- backups

def backup_slug(manifest_path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", manifest_path.stem).strip("._") or "vf1_patch"
    return f"{_dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{stem}"


def choose_backup_dir(args: argparse.Namespace, output_dir: Path, manifest_path: Path) -> Path:
    if getattr(args, "backup_dir", None):
        chosen = Path(args.backup_dir).resolve()
        return chosen / backup_slug(manifest_path) if chosen.is_dir() else chosen
    return output_dir / DEFAULT_BACKUP_ROOT / backup_slug(manifest_path)


def create_backup(output_dir: Path, backup_dir: Path, targets: dict[str, bool], source_game_dir: Path | None,
                  manifest_path: Path) -> dict[str, Any]:
    """Copy every file the run will replace or delete; record the ones it will create.

    targets: {path relative to the output folder: whether it exists now}.
    Restoring writes back the copies and deletes the files recorded as new.
    """
    backup_dir.mkdir(parents=True, exist_ok=False)
    files = []
    for rel_path in sorted(targets, key=path_key):
        existed = targets[rel_path]
        row: dict[str, Any] = {"file_path": rel_path, "existed": existed}
        if existed:
            source = resolve_under(output_dir, rel_path)
            if not source.is_file():
                raise PatchError(f"Backup target file does not exist: {rel_path}")
            backup_rel = f"files/{rel_path}"
            destination = resolve_under(backup_dir, backup_rel, "backup directory")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            make_writable(destination)
            backup_sha = sha256_file(destination)
            source_sha = sha256_file(source)
            if backup_sha != source_sha:
                raise PatchError(f"Backup verification failed for {rel_path}: source {source_sha}, backup {backup_sha}")
            row.update({"backup_path": backup_rel, "sha256": source_sha, "size": source.stat().st_size})
        files.append(row)
    manifest = {
        "backup_created_utc": utc_now(),
        "game_dir": str(output_dir.resolve()),
        "source_game_dir": None if source_game_dir is None else str(source_game_dir.resolve()),
        "source_manifest": str(manifest_path.resolve()),
        "files": files,
    }
    write_json(backup_dir / BACKUP_MANIFEST, manifest)
    return manifest


# ----------------------------------------------------------------------- apply

def _planned_writes(settings: dict[str, PatchSetting], effective: set[str], manifest_path: Path,
                    pins: dict[str, dict[str, Any]], dll: tuple[Path, bool]) -> tuple[dict[str, bytes], list[str]]:
    """({target: bytes} for the DLL and every active setting's files, [targets of inactive settings' files])."""
    dll_path, dll_pinned = dll
    writes = {DLL_REL: read_payload(dll_path, DLL_NAME, pins, dll_pinned)}
    removes = []
    for setting in settings.values():
        for f in setting.files:
            if setting.id in effective:
                source = resolve_under(payload_dir(manifest_path), f.source, "payload folder")
                writes[f.target] = read_payload(source, f.source, pins, True)
            elif not f.replaces:
                removes.append(f.target)  # a replaced game file is put back from its saved original instead
    return writes, removes


def apply_manifest(args: argparse.Namespace) -> int:
    """Build a modded folder from the vanilla folder, or reconfigure an existing one.

    With --game-dir: validate the vanilla folder, back up the existing modded
    folder (if any), rebuild it from vanilla, write the patched executable
    under its modded name, install vf1fun.dll and write settings.ini.
    With only --output-dir: an existing modded folder is reconfigured in
    place -- settings.ini is rewritten and setting files added or removed.
    """
    requested_game_dir = Path(args.game_dir).resolve() if getattr(args, "game_dir", None) else None
    requested_output_dir = Path(args.output_dir).resolve() if getattr(args, "output_dir", None) else None
    exe_arg = getattr(args, "exe", None)
    if exe_arg:
        # Apply_Patcher.bat passes the executable the player dragged in: the
        # vanilla one builds a modded folder next to it; a modded one in a
        # modded folder reconfigures that folder.
        exe_path = Path(exe_arg).resolve()
        if exe_path.suffix.lower() != ".exe" or not exe_path.is_file():
            raise PatchError(f"--exe must point to the Virtual Families executable, got {str(exe_path)!r}.")
        if requested_game_dir is not None and requested_game_dir != exe_path.parent:
            raise PatchError("--game-dir and --exe disagree; use the EXE's folder or omit --game-dir.")
        if (requested_game_dir is None and requested_output_dir is None
                and is_recognized_modded_output_dir(exe_path.parent)
                and executable_patch_state(exe_path.read_bytes()) != "vanilla"):
            requested_output_dir = exe_path.parent
        else:
            requested_game_dir = exe_path.parent
    if requested_game_dir is None and requested_output_dir is None:
        raise PatchError("Either --game-dir (the vanilla game folder) or --output-dir (an existing modded folder) is required.")
    reconfigure_output = requested_game_dir is None
    setattr(args, "reconfigure_output", reconfigure_output)
    manifest_path = Path(getattr(args, "manifest", None) or DEFAULT_MANIFEST).resolve()
    dry_run = bool(getattr(args, "dry_run", False))
    process_log: list[dict[str, Any]] = []
    backup_dir: Path | None = None
    backup_manifest = None
    settings: dict[str, PatchSetting] = {}
    selected: set[str] = set()
    game_dir = requested_game_dir
    output_dir = requested_output_dir
    try:
        emit_progress(args, f"Loading manifest: {manifest_path}")
        manifest = read_json(manifest_path)
        settings = manifest_settings(manifest)
        selected = resolve_enabled_settings(settings, args)
        report = effective_settings_report(settings, selected)
        effective = set(report["enabled"])
        pins = manifest_payload_pins(manifest)
        exe_name = validate_exe_name(args.exe_name) if getattr(args, "exe_name", None) else manifest_output_exe_name(manifest)
        dll = resolve_dll_source(args, manifest_path)
        emit_progress(args, f"Checking payload: {dll[0]}")
        writes, removes = _planned_writes(settings, effective, manifest_path, pins, dll)
        emit_progress(args, "Payload files check out.")
        ini_values = {setting_id: int(setting_id in effective) for setting_id in settings}
        copied_count = 0
        actions: dict[str, str] = {}

        if reconfigure_output:
            assert output_dir is not None
            emit_progress(args, f"Reconfiguring existing modded output folder: {output_dir}")
            if not output_dir.is_dir():
                raise PatchError(f"Modded output folder does not exist: {output_dir}")
            if not is_recognized_modded_output_dir(output_dir):
                raise PatchError(
                    "Output-only reconfiguration requires an existing Virtual Families modded output folder. "
                    f"This folder was not recognized as modded: {output_dir}")
            exe_path, state = find_modded_executable(output_dir, exe_name)
            if state != "current":
                raise PatchError(
                    f"{exe_path.name} was patched by a different version of this patcher. Choose your vanilla "
                    "Virtual Families folder too, so the modded folder can be rebuilt from it.")
            exe_name = exe_path.name
            log_process_event(process_log, phase="validate", kind="modded_exe", status="success",
                              file_path=exe_name, note="patched by this patcher's loader")
            emit_progress(args, f"Modded executable verified: {exe_name}")
            for setting in settings.values():
                for f in setting.files:
                    if not f.replaces:
                        continue
                    store = original_store_rel(f.target)
                    store_path = resolve_under(output_dir, store)
                    target_path = resolve_under(output_dir, f.target)
                    if setting.id in effective:
                        if not store_path.is_file():
                            current = target_path.read_bytes() if target_path.is_file() else None
                            if current is None or current == writes.get(f.target):
                                raise PatchError(
                                    f"{setting.label}: the original {f.target} is not saved in this modded folder. "
                                    "Choose your vanilla Virtual Families folder too, so it can be rebuilt from it.")
                            writes[store] = current
                    elif store_path.is_file():
                        writes[f.target] = store_path.read_bytes()
                        removes.append(store)
            ini_path = output_dir / SETTINGS_REL
            old_ini = ini_path.read_bytes() if ini_path.is_file() else None
            writes[SETTINGS_REL] = render_settings_ini(old_ini, ini_values)
            for rel, data in list(writes.items()):
                target = resolve_under(output_dir, rel)
                if target.is_file() and target.read_bytes() == data:
                    del writes[rel]
                    actions[rel] = "up_to_date"
                else:
                    actions[rel] = "replaced" if target.is_file() else "added"
            removes = [rel for rel in removes if resolve_under(output_dir, rel).is_file()]
            for rel in removes:
                actions[rel] = "removed"
            targets = {rel: resolve_under(output_dir, rel).is_file() for rel in [*writes, *removes]}
        else:
            assert game_dir is not None
            emit_progress(args, f"Validating vanilla game folder: {game_dir}")
            vanilla = validate_vanilla_install(game_dir)
            log_process_event(process_log, phase="validate", kind="vanilla_install", status="success",
                              file_path=VANILLA_EXE, sha256=VANILLA_SHA256)
            patched = patch_executable(vanilla)
            log_process_event(process_log, phase="validate", kind="exe_patch", status="success",
                              file_path=VANILLA_EXE, output_file_path=exe_name, sha256=sha256_bytes(patched))
            emit_progress(args, f"{VANILLA_EXE} is the vanilla 1.01.00 executable; the patch fits.")
            output_dir = output_dir or resolve_apply_output_dir(args, game_dir, manifest)
            check_output_dir_refresh_allowed(game_dir, output_dir)
            old_ini_path = output_dir / SETTINGS_REL
            old_ini = old_ini_path.read_bytes() if old_ini_path.is_file() else None
            # Keep what the DLL remembers between sessions ([Cheats]) across a rebuild.
            writes[SETTINGS_REL] = render_settings_ini(old_ini, ini_values)
            writes[exe_name] = patched
            for setting in settings.values():
                for f in setting.files:
                    if f.replaces and setting.id in effective:
                        original = resolve_under(game_dir, f.target)
                        if not original.is_file():
                            raise PatchError(f"{setting.label} replaces {f.target}, which is not in the vanilla folder.")
                        writes[original_store_rel(f.target)] = original.read_bytes()
            removes = []
            for rel in writes:
                actions[rel] = "added"
            existing = existing_output_files(output_dir)
            existing_keys = {path_key(rel) for rel in existing}
            targets = {rel: True for rel in existing}
            for rel in [*vanilla_rel_files(game_dir), *writes]:
                if path_key(rel) not in existing_keys:
                    targets[rel] = False

        if not dry_run:
            assert output_dir is not None
            backup_dir = choose_backup_dir(args, output_dir, manifest_path)
            emit_progress(args, f"Creating backup: {backup_dir}")
            backup_manifest = create_backup(output_dir, backup_dir, targets, game_dir, manifest_path)
            if not reconfigure_output:
                assert game_dir is not None
                copied_count = prepare_output_dir(game_dir, output_dir, args)
                log_process_event(process_log, phase="apply", kind="copy_vanilla", status="success",
                                  file_count=copied_count)
                emit_progress(args, f"Copied {copied_count} vanilla file(s).")
            for rel, data in writes.items():
                atomic_write(resolve_under(output_dir, rel), data)
                log_process_event(process_log, phase="apply", kind="write", status="success", file_path=rel,
                                  action=actions.get(rel, "written"), sha256=sha256_bytes(data), size=len(data))
                emit_progress(args, f"Wrote {rel}")
            for rel in removes:
                target = resolve_under(output_dir, rel)
                if target.is_file():
                    make_writable(target)
                    target.unlink()
                log_process_event(process_log, phase="apply", kind="remove", status="success", file_path=rel)
                emit_progress(args, f"Removed {rel}")

        written_files = [
            {"file_path": rel, "action": actions.get(rel, "written"), "sha256": sha256_bytes(data), "size": len(data)}
            for rel, data in sorted(writes.items(), key=lambda item: path_key(item[0]))
        ]
        unchanged_files = sorted((rel for rel, action in actions.items() if action == "up_to_date"), key=path_key)
        removed_files = sorted(removes, key=path_key)
        save_dir = save_dir_for_exe(exe_name)
        mode = "existing_modded_output" if reconfigure_output else "vanilla_to_modded_output"
        settings_section = settings_log(settings, selected, report)
        summary = {
            "game_dir": "" if game_dir is None else str(game_dir),
            "output_dir": str(output_dir),
            "mode": mode,
            "modded_exe_name": exe_name,
            "modded_save_folder_name": Path(exe_name).stem,
            "modded_save_dir": str(save_dir),
            "enabled_settings": sorted(effective),
            "settings": settings_section,
            "settings_ini": dict(ini_values),
            "written_files": written_files,
            "removed_files": removed_files,
            "unchanged_files": unchanged_files,
            "vanilla_files_copied": copied_count,
            "backup_dir": None if backup_dir is None else str(backup_dir),
            "dry_run": dry_run,
        }
        log = {
            "action": "apply",
            "status": "success",
            "timestamp_utc": utc_now(),
            "manifest": str(manifest_path),
            "manifest_name": manifest.get("name"),
            "version": manifest.get("version"),
            "backup_manifest": backup_manifest,
            "process_log": process_log,
            **summary,
        }
        if getattr(args, "log", None):
            log_path = Path(args.log).resolve()
        elif backup_dir:
            log_path = backup_dir / "patch_log.json"
        else:
            log_path = manifest_path.with_name("patch_dry_run_log.json")
        write_json(log_path, log)
        setattr(args, "last_apply_log_path", str(log_path))
        setattr(args, "last_apply_summary", {"log_path": str(log_path), **summary})

        if settings:
            inactive = report["inactive"]
            print("Enabled settings: " + (", ".join(sorted(effective)) if effective else "(none)"))
            disabled = sorted(set(settings) - effective - set(inactive))
            print("Disabled settings: " + (", ".join(disabled) if disabled else "(none)"))
            if inactive:
                print("Selected but inactive settings: "
                      + "; ".join(f"{sid} ({reason})" for sid, reason in sorted(inactive.items())))
        print(f"Validated {len(writes)} file(s) to write and {len(removed_files)} to remove.")
        if dry_run:
            print(f"Dry run complete. Nothing was written to the game folders. Log: {log_path}")
        else:
            print(f"Patched files successfully. Modded folder: {output_dir}")
            print(f"Play: {Path(str(output_dir)) / exe_name}")
            print(f"Backup: {backup_dir}")
            print(f"Patch log: {log_path}")
        return 0
    except (PatchError, OSError) as exc:
        if getattr(args, "log", None):
            failure_log_path = Path(args.log).resolve()
        elif backup_dir and backup_dir.is_dir():
            failure_log_path = backup_dir / "patch_error_log.json"
        else:
            failure_log_path = manifest_path.with_name("patch_error_log.json")
        error_text = str(exc) if isinstance(exc, PatchError) else f"File operation failed: {exc}"
        failure_log = {
            "action": "apply",
            "dry_run": dry_run,
            "status": "failure",
            "timestamp_utc": utc_now(),
            "game_dir": None if game_dir is None else str(game_dir),
            "output_dir": None if output_dir is None else str(output_dir),
            "manifest": str(manifest_path),
            "backup_dir": None if backup_dir is None else str(backup_dir),
            "settings": settings_log(settings, selected) if settings else None,
            "error": error_text,
            "process_log": process_log,
        }
        try:
            write_json(failure_log_path, failure_log)
            emit_progress(args, f"Patch failed. Failure log: {failure_log_path}")
        except OSError as log_exc:
            emit_progress(args, f"Patch failed. Could not write failure log {failure_log_path}: {log_exc}")
        if backup_dir is not None and backup_manifest is not None:
            emit_progress(args, f"The folder can be put back with Restore Backup: {backup_dir}")
        if isinstance(exc, PatchError):
            raise
        raise PatchError(error_text) from exc


def list_manifest_settings(args: argparse.Namespace) -> int:
    manifest_path = Path(getattr(args, "manifest", None) or DEFAULT_MANIFEST).resolve()
    settings = manifest_settings(read_json(manifest_path))
    defaults = {setting_id for setting_id, setting in settings.items() if setting.default}
    if getattr(args, "json", None):
        write_json(Path(args.json), {"manifest": str(manifest_path), "settings": settings_log(settings, defaults)})
        print(f"Settings JSON written: {Path(args.json).resolve()}")
        return 0
    if not settings:
        print("This manifest does not declare toggleable settings.")
        return 0
    for setting in settings.values():
        state = "default on" if setting.default else "default off"
        line = f"{setting.id} [{state}] - {setting.label}"
        if setting.description:
            line += f": {setting.description}"
        line += requires_note(setting.requires, settings).replace("**", "")
        print(line)
    return 0


def restore_backup(args: argparse.Namespace) -> int:
    backup_dir = Path(args.backup_dir).resolve()
    backup_manifest_path = backup_dir / BACKUP_MANIFEST
    if not backup_manifest_path.is_file():
        raise PatchError(f"Backup manifest not found: {backup_manifest_path}")
    backup_manifest = read_json(backup_manifest_path)
    recorded = backup_manifest.get("game_dir")
    recorded_dir = Path(str(recorded)).resolve() if recorded else None
    if getattr(args, "game_dir", None):
        game_dir = Path(args.game_dir).resolve()
        if (recorded_dir is not None
                and os.path.normcase(str(game_dir)) != os.path.normcase(str(recorded_dir))
                and not getattr(args, "force_game_dir", False)):
            raise PatchError(
                "This backup was taken from a different folder and would overwrite or delete files "
                f"in {game_dir}. It belongs to: {recorded_dir}. Omit the destination to restore it there, "
                "or pass --force-game-dir to restore it elsewhere anyway.")
    elif recorded_dir is not None:
        game_dir = recorded_dir
    else:
        raise PatchError("Backup manifest does not record the folder it was taken from; pass --game-dir.")
    if not game_dir.is_dir():
        raise PatchError(f"Game directory does not exist: {game_dir}")
    source = backup_manifest.get("source_game_dir")
    if source and os.path.normcase(str(Path(source).resolve())) == os.path.normcase(str(game_dir)):
        raise PatchError("Refusing to restore into the vanilla game folder.")

    rows = backup_manifest.get("files", [])
    if not isinstance(rows, list):
        raise PatchError("Backup manifest files must be an array.")
    validated = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise PatchError("Backup manifest contains an invalid file row.")
        rel_path = normalize_rel_path(raw.get("file_path"), "backup file path")
        if path_key(rel_path).split("/")[0] == DEFAULT_BACKUP_ROOT:
            raise PatchError(f"Backup row points into the backup folder: {rel_path}")
        target = resolve_under(game_dir, rel_path)
        if raw.get("existed", True):
            backup_rel = normalize_rel_path(raw.get("backup_path"), "backup path")
            src = resolve_under(backup_dir, backup_rel, "backup directory")
            if not src.is_file():
                raise PatchError(f"Backed-up file is missing: {src}")
            data = src.read_bytes()
            actual = sha256_bytes(data)
            expected = str(raw.get("sha256", "")).lower()
            if actual != expected:
                raise PatchError(f"Backup SHA-256 mismatch for {rel_path}: expected {expected}, got {actual}")
            if raw.get("size") is not None and len(data) != int(raw["size"]):
                raise PatchError(f"Backup size mismatch for {rel_path}: expected {raw['size']}, got {len(data)}")
            validated.append((rel_path, target, True, data))
        else:
            if target.exists() and not target.is_file():
                raise PatchError(f"Restore target is not a regular file: {rel_path}")
            validated.append((rel_path, target, False, None))

    restored = []
    for rel_path, target, existed, data in validated:
        if existed:
            atomic_write(target, data)
            restored.append({"file_path": rel_path, "sha256": sha256_file(target), "size": target.stat().st_size})
        else:
            removed = False
            if target.exists():
                make_writable(target)
                target.unlink()
                removed = True
            restored.append({"file_path": rel_path, "removed": removed, "existed": False})
    log = {
        "action": "restore",
        "status": "success",
        "timestamp_utc": utc_now(),
        "game_dir": str(game_dir),
        "backup_dir": str(backup_dir),
        "restored_files": restored,
    }
    log_path = Path(args.log).resolve() if getattr(args, "log", None) else backup_dir / "restore_log.json"
    write_json(log_path, log)
    print(f"Restored {sum(1 for r in restored if 'sha256' in r)} file(s) and removed "
          f"{sum(1 for r in restored if r.get('removed'))} file(s) the patcher had added.")
    print(f"Restore log: {log_path}")
    return 0


# ---------------------------------------------------------- transparency log

def transparency_log_text(manifest: dict[str, Any]) -> str:
    """The Transparency Log: what the patcher does and every file it writes."""
    settings = manifest_settings(manifest)
    folder = manifest_output_folder_name(manifest)
    exe = manifest_output_exe_name(manifest)
    title = "Virtual Families 1 Patcher Transparency Log"
    lines = [
        title,
        "=" * len(title),
        "",
        "Creation disclosure",
        "-------------------",
        "Created by Lorsieab2. This is a passion project dedicated to improving the \"Virtual Families\" experience!",
        "No copyright infringement intended! Please support the original game creators! :)",
        "This patcher was created with Claude AI (Claude Code) in collaboration with Lorsieab2.",
        "",
        "What this patcher does",
        "----------------------",
        "- Verifies the selected vanilla Virtual Families folder. It must hold",
        f"  {', '.join(REQUIRED_INSTALL_ENTRIES)},",
        f"  and {VANILLA_EXE} must be the official version 1.01.00",
        f"  (SHA-256 {VANILLA_SHA256}).",
        "- Creates a separate, clearly labeled modded game folder. The vanilla game folder is only read.",
        "- With a vanilla folder selected, Enable/Disable Patches rebuilds a recognized modded folder from the",
        "  vanilla folder. With only a modded folder selected, it reconfigures that folder in place.",
        "- Backs up every file it will replace or delete before writing, and records every file it will create,",
        "  so Restore Backup can put the folder back exactly.",
        "- Writes machine-readable success/failure logs.",
        "- Dry Run (Validate Only) checks the vanilla folder, the executable, the patch and the payload files,",
        "  then stops before creating backups, creating the modded folder, or writing any game file.",
        "- Payload files are read-only/copy-only: the patcher never writes into payload/.",
        "",
        "What this patcher does not do",
        "-----------------------------",
        "- Does not inject code into a running game or edit process memory.",
        "- Does not use obfuscation, packers, or admin-only install locations.",
        "- Does not launch the game.",
        "- Does not alter any save. The modded game keeps its own save folder.",
        "",
        "The executable patch",
        "--------------------",
        f"- The modded executable is the vanilla {VANILLA_EXE} plus two new sections:",
        "  .vf1fun (read + execute), a small loader, and .vf1fud (read + write), its state.",
        "  No page is both writable and executable.",
        f"- Two existing values change so the game enters the loader: the call at {HOOK_SITE:#x} (end of the",
        f"  store screen's constructor) and theGame's Init vtable slot at {INIT_SLOT:#x}. The PE checksum is",
        "  updated. Nothing else in the original image changes.",
        f"- The loader loads \"{PATCHER_FOLDER}\\{DLL_NAME}\" by full path. If it is missing, the game runs",
        "  exactly as normal.",
        f"- The modded executable is named \"{exe}\". Its name never contains \"patch\": Windows treats",
        "  such names as installers and asks for administrator rights.",
        "",
        "Every file the patcher writes",
        "-----------------------------",
        f"In the modded game folder (default \"{folder}\"):",
        f"- Every file of the vanilla folder except {VANILLA_EXE}, copied unchanged.",
        f"- {exe}: the patched executable.",
        f"- {PATCHER_FOLDER}\\{DLL_NAME}: the patcher's DLL, copied from payload\\{DLL_NAME}.",
        f"- {PATCHER_FOLDER}\\{SETTINGS_INI}: section [{SETTINGS_SECTION}], one Key=1/0 line per setting below.",
        "  Other sections (written by the DLL, e.g. [Cheats] InterestRate) are kept as they were.",
    ]
    for setting in settings.values():
        for f in setting.files:
            if f.replaces:
                lines.append(f"- {f.target.replace('/', chr(92))}: replaced only while {setting.label} is on "
                             f"(from payload\\{f.source.replace('/', chr(92))}); the original is kept in "
                             f"{original_store_rel(f.target).replace('/', chr(92))} and put back when it is off.")
            else:
                lines.append(f"- {f.target.replace('/', chr(92))}: only while {setting.label} is on "
                             f"(from payload\\{f.source.replace('/', chr(92))}).")
    lines += [
        f"- {DEFAULT_BACKUP_ROOT}\\<date_time>_manifest\\: one folder per run, holding {BACKUP_MANIFEST},",
        "  files\\... (copies of every file the run replaced or deleted), patch_log.json (or",
        "  patch_error_log.json if the run failed) and, after a restore, restore_log.json.",
        "Next to manifest.json (the patcher's own folder):",
        "- patch_dry_run_log.json after a Dry Run, and patch_error_log.json when a run fails before its backup",
        "  exists.",
        "- patcher_local_settings.json: the folders you chose in the window, so they are filled in next time.",
        "The patcher writes nothing else, and it never deletes a backup folder.",
        "",
        "Written by the modded game itself",
        "---------------------------------",
        f"- {PATCHER_FOLDER}\\{SETTINGS_INI}: the DLL saves cheat values it remembers between sessions there.",
        f"- Saves: Documents\\LDW\\{Path(exe).stem}, separate from the vanilla game's",
        f"  Documents\\LDW\\{VANILLA_SAVE_FOLDER}.",
        "",
        "Settings and defaults",
        "---------------------",
        "- Main Patches (green) and Optional Patches (black), as in the patcher window.",
    ]
    for setting in settings.values():
        state = "on" if setting.default else "off"
        lines.append(f"- {setting.id} [{state}] ({setting.category}): {setting.label}")
        lines.append(f"  {setting.description}{requires_note(setting.requires, settings)}")
    lines += [
        "",
        "Restore",
        "-------",
        "- Restore Backup puts back the files a backup recorded, into the folder it was taken from, and deletes",
        "  the files that run had created. It refuses to restore into the vanilla game folder.",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    apply_cmd = sub.add_parser("apply", help="Build or reconfigure a modded game folder.")
    apply_cmd.add_argument("--game-dir", help="The vanilla Virtual Families folder. Omit only when reconfiguring an existing modded --output-dir.")
    apply_cmd.add_argument("--exe", help=f"Path to {VANILLA_EXE} (its folder is the vanilla folder), or to the modded executable of a modded folder to reconfigure.")
    apply_cmd.add_argument("--manifest", help="manifest.json (default: the one next to this script).")
    apply_cmd.add_argument("--output-dir", help="The modded game folder. With --game-dir it is created or rebuilt; without, it must be an existing modded folder to reconfigure.")
    apply_cmd.add_argument("--output-parent-dir", help="Where the manifest-named modded folder goes. Ignored when --output-dir is given.")
    apply_cmd.add_argument("--backup-dir", help="Backup folder. A folder that already exists receives a new per-run subfolder; a new path is used as given. Default: a per-run folder under .vf1_patch_backups in the modded folder.")
    apply_cmd.add_argument("--log", help="Patch log JSON path. Defaults inside the backup folder.")
    apply_cmd.add_argument("--dry-run", action="store_true", help="Validate only; do not back up or write any game file.")
    apply_cmd.add_argument("--enable", action="append", help="Enable a setting. Repeat or comma-separate ids.")
    apply_cmd.add_argument("--disable", action="append", help="Disable a setting. Repeat or comma-separate ids.")
    apply_cmd.add_argument("--enable-all", action="store_true", help="Enable every setting before --enable/--disable.")
    apply_cmd.add_argument("--disable-all", action="store_true", help="Disable every setting before --enable/--disable.")
    apply_cmd.add_argument("--exe-name", help=f"Name of the modded executable (default from the manifest, \"{DEFAULT_MODDED_EXE}\"). Must not contain \"patch\".")
    apply_cmd.add_argument("--dll", help=f"Use this {DLL_NAME} instead of payload\\{DLL_NAME} (for development builds).")
    apply_cmd.set_defaults(func=apply_manifest)

    settings_cmd = sub.add_parser("settings", help="List the settings the manifest declares.")
    settings_cmd.add_argument("--manifest", help="manifest.json (default: the one next to this script).")
    settings_cmd.add_argument("--json", help="Write the settings as JSON to this path.")
    settings_cmd.set_defaults(func=list_manifest_settings)

    restore_cmd = sub.add_parser("restore", help="Restore files from a patcher backup folder.")
    restore_cmd.add_argument("--backup-dir", required=True, help="Backup folder created by apply.")
    restore_cmd.add_argument("--game-dir", help="Restore destination. Defaults to the folder recorded in the backup; a different folder is refused unless --force-game-dir is given.")
    restore_cmd.add_argument("--force-game-dir", action="store_true", help="Allow --game-dir to differ from the folder the backup was taken from.")
    restore_cmd.add_argument("--log", help="Restore log JSON path. Defaults inside the backup folder.")
    restore_cmd.set_defaults(func=restore_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PatchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
