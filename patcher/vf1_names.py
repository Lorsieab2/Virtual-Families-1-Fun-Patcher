"""Names longer than their save field: the short form in the save, the whole name in the save's Names file.

Every name box takes up to ``vf1_text.NAME_LETTERS`` characters (300; see vf1_text for why), but the save keeps
each name in a fixed field: the family name 19 bytes (theGameState+0x1B12C, GetText(.., 0x14) at 0x41C72B), the
slot menu's names 20, a family member's name 18 as typed (GetText(.., 0x13) at 0x43682A, 0x43829D, 0x44BCE1,
0x44BDDE) in a 25-byte field. The save format is never changed, so:

* a name that fits its field is stored as it is, exactly as before;
* a longer name is stored as its SHORT FORM: the longest start of it that fits, cut between whole characters, then
  ``NAME_MARK`` ("...") -- or, when that short form already stands for another name in this save, "2...", "3..."
  and so on. A short form therefore names one name only: it follows the family member wherever the game copies
  their name (the parents' names of their children, the family tree's records, a death), and the stock game (or
  the patch off) loads, plays and shows it as it is;
* the whole name is kept in the save's Names file, "Virtual Families 1 Patcher Data\\Names\\Virtual
  Families<N>.ldw.txt" (one per save slot N), one line per short form: ``short<TAB>room<TAB>name``, where room is
  the field's bytes it was made for. The game itself (vf1text.dll / vf1font.dll, either Unicode setting) writes
  it when a name is typed, and draws the whole name wherever its short form is drawn; the patcher's readers and
  tools read and write it here, by the same rule.

A line is never removed by the game: a short form no longer in the save is harmless (a new short form is never
made equal to it), so the older autosave copies "<N+20>" / "<N+40>" stay readable too. A file that cannot be read
is read as empty: the save still shows its short forms.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import vf1_text

NAME_LETTERS = vf1_text.NAME_LETTERS
NAME_BOX_BYTES = vf1_text.NAME_BOX_BYTES
MARK = vf1_text.NAME_MARK
FOLDER = "Names"
HEADER = "VF1 Names 1"
PATCHER_DATA = "Virtual Families 1 Patcher Data"

FAMILY_ROOM = 19          # theGameState+0x1B12C: GetText(.., 0x14) keeps 19 bytes
MEMBER_ROOM = 18          # a family member's name: GetText(.., 0x13) keeps 18 bytes


@dataclass(frozen=True)
class Entry:
    short: str
    room: int
    full: str


def names_path(folder: Path, slot: int) -> Path:
    return Path(folder) / PATCHER_DATA / FOLDER / f"Virtual Families{slot}.ldw.txt"


def name_problem(full: str) -> str | None:
    """Why ``full`` cannot be a name (None when it can): 1..NAME_LETTERS characters, at most NAME_BOX_BYTES bytes,
    no control characters."""
    if not full:
        return "A name needs at least one character."
    for ch in full:
        cp = ord(ch)
        if cp < 0x20 or 0x7F <= cp < 0xA0:
            return "A name cannot hold control characters (tabs, line breaks)."
        if 0xD800 <= cp <= 0xDFFF:
            return "A name cannot hold a lone surrogate."
    if vf1_text.char_count(full) > NAME_LETTERS:
        return f"A name can be at most {NAME_LETTERS} characters."
    if len(full.encode("utf-8")) > NAME_BOX_BYTES:
        return (f"A name can be at most {NAME_BOX_BYTES:,} bytes of UTF-8 (this one is "
                f"{len(full.encode('utf-8')):,}); some characters, such as joined emoji, take many bytes.")
    return None


def parse(data: bytes) -> list[Entry]:
    """A Names file's entries (in file order); anything not valid is left out."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != HEADER:
        return []
    out: list[Entry] = []
    seen: set[str] = set()
    for line in lines[1:]:
        line = line.rstrip("\r")
        parts = line.split("\t")
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        short, room, full = parts[0], int(parts[1]), parts[2]
        if (short in seen or not short or not short.endswith(MARK) or name_problem(full) is not None
                or not 1 <= room < NAME_BOX_BYTES or len(short.encode("utf-8")) > room):
            continue
        seen.add(short)
        out.append(Entry(short, room, full))
    return out


def render(entries: list[Entry]) -> bytes:
    return ("\n".join([HEADER] + [f"{e.short}\t{e.room}\t{e.full}" for e in entries]) + "\n").encode("utf-8")


def read(path: Path) -> list[Entry]:
    try:
        return parse(Path(path).read_bytes())
    except OSError:
        return []


def read_slot(folder: Path, slot: int) -> list[Entry]:
    return read(names_path(folder, slot))


def write(path: Path, entries: list[Entry]) -> None:
    """Write a Names file through a temporary file beside it, then check it reads back."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = render(entries)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    if path.read_bytes() != data:
        raise OSError(f"{path} did not read back as written")


def short_form(full: str, room: int, taken: dict[str, str]) -> str:
    """What the save field of ``room`` bytes stores for ``full``, given the short forms already ``taken`` (short ->
    name, in file order). The same rule as vf1text.dll's ShortFor:

    * a short form already standing for this very name, that fits, is used again;
    * a name that fits and is no short form of another name is stored as it is;
    * else the longest start that fits with the mark (trailing spaces dropped) + "...", then + "2...", "3...", ...
      until one is not taken."""
    for short, name in taken.items():
        if name == full and len(short.encode("utf-8")) <= room:
            return short
    if len(full.encode("utf-8")) <= room and full not in taken:
        return full
    n = 1
    while True:
        tail = MARK if n == 1 else f"{n}{MARK}"
        if len(tail) > room:
            raise ValueError("no room for a short form")
        head = vf1_text.cut_to_bytes(full, room - len(tail)).rstrip(" ")
        short = head + tail
        if short not in taken:
            return short
        n += 1


def full_name(stored: str, entries) -> str:
    """The whole name for a name as the save stores it (itself when it is no short form)."""
    for e in entries:
        if e.short == stored:
            return e.full
    return stored


class Book:
    """Every slot's Names file in one save folder: what the readers show, and what the tools write."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.slots: dict[int, list[Entry]] = {s: read_slot(self.folder, s) for s in range(1, 6)}

    def taken(self) -> dict[str, str]:
        """Every short form of every slot (a family name's short form shows in the slot menu beside the others')."""
        out: dict[str, str] = {}
        for slot in range(1, 6):
            for e in self.slots[slot]:
                out.setdefault(e.short, e.full)
        return out

    def full(self, slot: int, stored: str) -> str:
        """``stored`` as a family member of ``slot`` (or any slot's family name) is called."""
        for e in self.slots.get(slot, []):
            if e.short == stored:
                return e.full
        for s in range(1, 6):
            for e in self.slots[s]:
                if e.short == stored:
                    return e.full
        return stored

    def store(self, slot: int, full: str, room: int) -> tuple[str, Entry | None]:
        """The short form to store for ``full`` in ``slot``'s field of ``room`` bytes, and the new line for the slot's
        Names file (None when none is needed). Nothing is written here."""
        short = short_form(full, room, self.taken())
        if short == full:
            return short, None
        for e in self.slots[slot]:
            if e.short == short:
                return short, None
        return short, Entry(short, room, full)

    def add(self, slot: int, entry: Entry) -> None:
        self.slots[slot] = [e for e in self.slots[slot] if e.short != entry.short] + [entry]

    def write_slot(self, slot: int) -> None:
        write(names_path(self.folder, slot), self.slots[slot])
