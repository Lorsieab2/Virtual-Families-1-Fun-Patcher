"""Every line a Virtual Families 1 translation can replace, with its room: the game's own string table, read from
the player's own executable (the patcher never ships the game's text).

The table is the game's static records {id, key*, text*, override*} from 0x4F5618 (theStringManagerImpl's
constructor 0x450200 points its id index 0x56E840 at them; GetString 0x44FD90 and the template filler 0x44FDD0
return the override when it is set, else the text).  vf1tr.dll sets the override of each translated line.

A line's key is "strings/<id>~<hash of its English>".  Its room (Entry.max_length, in UTF-8 bytes):

* where the game copies it with strncpy into a fixed field: that field less its NUL (data/vf1_translation_limits.json,
  "strncpy_room", from tools/build_vf1_translation_limits.py);
* where it goes through sprintf, strncat or a byte-copy loop: its English length ("english_length"), so every
  buffer holds at most what it holds in the English game;
* every line: at most MAX_LINE.
A line is a printf FORMAT ("format": the game hands it to sprintf as the format; Entry.is_format) or not: only a
format's own conversions are placeholders, and a plain '%' in its translation is handed to the game as "%%"
(translation_format.runtime_text). The lines in "never" are never translated (the decimal point). The likes and dislikes lists (ITEM_LISTS) keep every
item, each no longer than its English (Entry.items).

After the game's lines come the patches' own (key source "patch"): every line a player can see that vf1fun.dll adds
(its menus, pages, messages, behaviour captions, ...), from data/vf1_patch_strings.json (tools/vf1_patch_text.py,
which reads native/). Their key is "patch/<dll>.<words>~<hash of its English>"; vf1tr.dll finds a translation by
its English when the DLL asks for it, so a line without one shows English. Room: a line with a printf conversion
keeps its English length, any other wide line three times its English (80 to 600), a line the game draws its own
room (see tools/vf1_patch_text.py).
"""
from __future__ import annotations

import hashlib
import json
import struct
from functools import lru_cache
from pathlib import Path

import translation_format as tfmt

HERE = Path(__file__).resolve().parent
# data/ in the repository; beside this module in the release (tools/package_release.py)
LIMITS_JSON = next((p for p in (HERE / "vf1_translation_limits.json", HERE.parent / "data" / "vf1_translation_limits.json")
                    if p.is_file()), HERE.parent / "data" / "vf1_translation_limits.json")
PATCH_JSON = next((p for p in (HERE / "vf1_patch_strings.json", HERE.parent / "data" / "vf1_patch_strings.json")
                   if p.is_file()), HERE.parent / "data" / "vf1_patch_strings.json")
ITEM_LISTS = (0x45B, 0x45C)      # eSayLikesList, eSayDislikesList: picked by position (0x481E20, 0x481420)
GAME = "vf1"
EXE_NAMES = ("Virtual Families.exe", "Virtual Families - Modded.exe")
VANILLA_SHA256 = "5db828c3f53c68696c18719aec0eb114be3fd4458ae2cbf185d8d4ef7eca4487"
TABLE = 0x4F5618
RECORDS = 0x66C          # the constructor's own bound on the records it searches
MAX_ID = 0x675           # GetString's bound
MAX_LINE = 1000          # vf1tr.dll's absolute limit (VF1TR_MAX_LINE)
IMAGE_BASE = 0x400000


class StringsError(ValueError):
    pass


@lru_cache(maxsize=1)
def limits() -> dict:
    data = json.loads(LIMITS_JSON.read_text(encoding="utf-8"))
    return {
        "strncpy_room": {int(k): int(v) for k, v in data["strncpy_room"].items()},
        "english_length": {int(v) for v in data["english_length"]},
        "never": {int(k): v for k, v in data["never"].items()},
        "format": {int(v) for v in data.get("format", ())},
    }


def _sections(exe: bytes) -> list[tuple[int, int, int]]:
    """(virtual address, raw offset, raw size) of each section (plain PE reading, no pefile needed)."""
    if exe[:2] != b"MZ":
        raise StringsError("not a Windows program")
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    if exe[pe:pe + 4] != b"PE\0\0":
        raise StringsError("not a Windows program")
    count = struct.unpack_from("<H", exe, pe + 6)[0]
    opt = struct.unpack_from("<H", exe, pe + 20)[0]
    table = pe + 24 + opt
    out = []
    for k in range(count):
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", exe, table + 40 * k + 8)
        out.append((IMAGE_BASE + va, raw, rawsize, vsize))
    return out


def _reader(exe: bytes):
    sections = _sections(exe)

    def offset(va: int) -> int:
        for start, raw, rawsize, vsize in sections:
            if start <= va < start + rawsize:
                return raw + (va - start)
        raise StringsError(f"0x{va:X} is not in the program")

    def cstr(va: int) -> bytes:
        o = offset(va)
        end = exe.index(b"\0", o)
        if end - o > 4096:
            raise StringsError("a string runs on")
        return exe[o:end]
    return offset, cstr


def read_table(exe: bytes) -> dict[int, tuple[str, str]]:
    """{id: (key, English)} of the game's string table, from the program's own bytes."""
    offset, cstr = _reader(exe)
    table: dict[int, tuple[str, str]] = {}
    at = offset(TABLE)
    for k in range(RECORDS):
        sid, key, text, override = struct.unpack_from("<IIII", exe, at + 16 * k)
        if not 1 <= sid <= MAX_ID or override != 0:
            continue
        try:
            name = cstr(key).decode("ascii")
            english = cstr(text).decode("cp1252")
        except (StringsError, UnicodeDecodeError, ValueError):
            continue
        if name.startswith("e") and sid not in table:
            table[sid] = (name, english)
    if len(table) < 1000:
        raise StringsError("this is not Virtual Families 1.01 (its string table was not found)")
    return table


def room(sid: int, english: str) -> int:
    lim = limits()
    best = MAX_LINE
    if sid in lim["strncpy_room"]:
        best = min(best, max(lim["strncpy_room"][sid], len(english.encode("utf-8"))))
    if sid in lim["english_length"]:
        best = min(best, len(english.encode("utf-8")))
    return best


def entries_for(exe: bytes) -> list[tfmt.Entry]:
    """The template's lines, in id order: every line the game shows that may be translated."""
    lim = limits()
    out = []
    for sid, (name, english) in sorted(read_table(exe).items()):
        if sid in lim["never"] or english.strip() == "":
            continue
        max_length = room(sid, english)
        notes = [name]
        template = tfmt.parse_template(english)
        is_format = sid in lim["format"]
        template.conversions = list(tfmt.english_source(english, is_format).conversions)
        if template.variables or template.selects:
            notes.append("the game fills " + ", ".join(sorted("{" + v + "}" for v in template.variables))
                         if template.variables else "the game fills it")
            if template.selects or "name" in template.variables:
                notes.append("{he/she}: the person's sex, written as you like it ({il/elle})")
        if template.conversions:
            notes.append(" ".join(f"%{n} ({c.text})" for n, c in enumerate(template.conversions, 1)))
        if max_length < MAX_LINE:
            notes.append(f"at most {max_length} letters (the game keeps it in a fixed space)")
        items = sid in ITEM_LISTS
        if items:
            notes.append(f"a list of {english.count(',') + 1} items: keep every one, in order, separated by commas, "
                         "each no longer than its English")
        out.append(tfmt.Entry(tfmt.make_key("strings", str(sid), english), english, "; ".join(notes), max_length,
                              items=items, is_format=is_format))
    return out + patch_entries()


@lru_cache(maxsize=1)
def _patch_rows() -> tuple:
    try:
        data = json.loads(PATCH_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(data.get("strings", ()))


def patch_entries() -> list[tfmt.Entry]:
    """The patches' own lines a player sees (data/vf1_patch_strings.json), after the game's."""
    out = []
    for row in _patch_rows():
        english, room = row["english"], int(row["room"])
        where = row["id"].split(".", 1)[0]
        notes = [f"{where}: " + ("drawn by the game" if row.get("drawn_by_game")
                                 else "a patcher window or message in the game")]
        is_format = bool(row.get("format"))
        conversions = tfmt.english_source(english, is_format).conversions
        if conversions:
            notes.append(" ".join(f"%{n} ({c.text})" for n, c in enumerate(conversions, 1)))
        notes.append(f"at most {room} letters")
        out.append(tfmt.Entry(tfmt.make_key("patch", row["id"], english), english, "; ".join(notes), room,
                              is_format=is_format))
    return out


def is_format_key(key: str) -> bool | None:
    """Whether the line with this key is a printf format: True for a game line the game hands sprintf as its format
    (data/vf1_translation_limits.json "format"), else None -- its English decides (translation_format.
    english_source; without the game, the English in a file cannot be checked against it); a patch's line by its
    id and English (data/vf1_patch_strings.json "format"); None for any other key. Needs no game: the GitHub
    Action's validator uses it on a submitted file."""
    parts = tfmt.split_key(key)
    if not parts:
        return None
    source, ident, digest = parts
    if source == "strings":
        try:
            return True if int(ident) in limits()["format"] else None
        except (ValueError, OSError, KeyError):
            return None
    if source == "patch":
        for row in _patch_rows():
            if row.get("id") == ident and tfmt.key_hash(row.get("english", "")) == digest:
                return bool(row.get("format"))
    return None


tfmt.set_format_lookup(is_format_key)


def is_game_exe(path: Path) -> bool:
    try:
        data = path.read_bytes()
        read_table(data)
        return True
    except (OSError, StringsError, struct.error, ValueError):
        return False


def find_vanilla_exe(candidates) -> Path | None:
    """The game's program in one of the folders (the original first, else a patched copy: the string table is
    the same in both)."""
    for folder in candidates:
        if not folder:
            continue
        folder = Path(str(folder).strip().strip('"'))
        for name in EXE_NAMES:
            path = folder / name
            if path.is_file() and is_game_exe(path):
                return path
    return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
