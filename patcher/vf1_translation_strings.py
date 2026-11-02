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
The lines in "never" are never translated (the Family History log's own words, the lists the game splits).
"""
from __future__ import annotations

import hashlib
import json
import struct
from functools import lru_cache
from pathlib import Path

import translation_format as tfmt

ROOT = Path(__file__).resolve().parents[1]
LIMITS_JSON = ROOT / "data" / "vf1_translation_limits.json"
KEYS_JSON = ROOT / "data" / "vf1_string_keys.json"
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
        if template.variables or template.selects:
            notes.append("the game fills " + ", ".join(sorted("{" + v + "}" for v in template.variables))
                         if template.variables else "the game fills it")
            if template.selects or "name" in template.variables:
                notes.append("{he/she}: the person's sex, written as you like it ({il/elle})")
        if template.conversions:
            notes.append(" ".join(f"%{n} ({c.text})" for n, c in enumerate(template.conversions, 1)))
        if max_length < MAX_LINE:
            notes.append(f"at most {max_length} letters (the game keeps it in a fixed space)")
        out.append(tfmt.Entry(tfmt.make_key("strings", str(sid), english), english, "; ".join(notes), max_length))
    return out


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
