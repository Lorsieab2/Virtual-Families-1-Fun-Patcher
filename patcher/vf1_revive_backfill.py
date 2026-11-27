"""Revive a Family Member: the snapshot sidecar (native/vf1revive/vf1revive.cpp) and the backfill that makes a snapshot,
afterwards, for every family member who died before the patch was on (docs/REVIVE.md).

The sidecar
    "<save folder>\\Virtual Families 1 Patcher Data\\Revive\\Virtual Families<n>.ldw.dat", one per save FILE (n = N,
    N+20, N+40), in the Up to 28 Children sidecar's layout: "VF1REVV\\0", version 1, "VF1V101\\0", file size, the
    FNV-1a 64 hash and size of the save it was written with, generations, parent 1's slot and sex, the entry count,
    the entries (ENTRY bytes each, the table below), the FNV-1a 64 of everything before it. vf1revive takes the
    snapshots from it only while the save beside it is still the one it names, so it never holds a death the save
    never had.

The backfill (read-only sources, in this order)
    1. a stale record in the save itself: the dead person's own villager record (health 0, the cause kept), which the
       game keeps until the slot is reused: every field EXACT;
    2. the same person in an older save of the family -- the game's own "<N+20>" / "<N+40>" copies and the patcher's
       Backups -- a stale dead record there (EXACT), else the newest copy taken while they were alive: who they are
       (name, sex, head, body, parents, voice) EXACT, what can change in a life (likes, dislikes, career, fertility,
       "Wants kids?") INFERRED, as when that save was made;
    3. the save's Family Tree entry: name, sex, head and body EXACT, the rest UNKNOWN (the revival keeps the new
       villager's own values there);
    4. the Family History log (age at death in years, the cause, the generation, the family role) and the Names file
       (the whole name).
    Every field of every snapshot is marked exact, inferred or unknown. A person whose age at death is not found
    anywhere is marked "unknown -> 20" and comes back at 20 (the owner, 2026-11-26).

    Only the dead are backfilled: the Family Tree's entries the game marked dead (slot -1) and the log's Death
    records; never a divorce, the Talent Scout or an eviction.

Safety
    Every save and log is only read. A sidecar is written with a temporary file and an atomic replace, after the file
    it replaces is copied to "Revive\\Before Backfill <date>\\"; when any write of a folder fails, every file written
    in that folder is put back as it was. A sidecar that is damaged or names another save is left exactly as it is.
    Running the backfill again changes nothing (a person who already has a snapshot gets no other; a snapshot taken at
    the death always wins). The backup folders ("Backups\\Backup ...") are repaired even while the game runs: the game
    never reads them. The live save folder waits while the game runs (the running game's own snapshots would replace
    the file at its next save).
"""
from __future__ import annotations

import os
import shutil
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_family_history as history_log
import vf1_genealogy as gen
import vf1_names
import vf1_save
import vf1_text

FOLDER = "Revive"
MAGIC = gen.REVIVE_MAGIC
TAG = gen.KIDS_TAG
VERSION = 1
HEADER = 52
ENTRY = gen.REVIVE_ENTRY
MAX_ENTRIES = gen.REVIVE_MAX

# The entry, exactly as vf1revive.cpp's E_* table.
E_STATE, E_SOURCE, E_MARKS, E_SLOT, E_ROLE, E_GENERATION, E_DEATH_NUMBER = 0, 4, 8, 16, 20, 24, 28
E_TIME, E_REVIVED_SLOT, E_HOW = 32, 40, 44
E_BIO, E_VSTATE, E_SKILLS, E_LIKES, E_PEEP, E_PARENT1, E_PARENT2, E_WHOLE = 48, 208, 360, 376, 400, 616, 832, 1048
WHOLE_SIZE = 1204
BIO_SIZE, VSTATE_SIZE, SKILLS_SIZE, LIKES_SIZE, PEEP_SIZE = 0xA0, 0x98, 0x10, 0x18, 0xD8

STATE_DEAD, STATE_REVIVED = 1, 2
SOURCES = {1: "captured at the death", 2: "a stale record in the save", 3: "an older save of the family",
           4: "a backup", 5: "the Family Tree", 6: "the Family History log"}
SOURCE_CAPTURED, SOURCE_STALE, SOURCE_OLDER, SOURCE_BACKUP, SOURCE_TREE, SOURCE_LOG = 1, 2, 3, 4, 5, 6
FIELDS = ("name", "sex", "head", "body", "voice", "name index", "parents", "likes", "dislikes", "career", "fertility",
          "wants kids", "age at death", "cause of death", "family tree", "whole name", "generation")
UNKNOWN, INFERRED, EXACT = 0, 1, 2
UNKNOWN_ADULT = 3                       # the age at death only: not found, so they come back at 20 (the owner, 2026-11-26)
MARK_WORDS = {UNKNOWN: "unknown", INFERRED: "inferred", EXACT: "exact", UNKNOWN_ADULT: "unknown -> 20"}
UNITS_PER_YEAR = vf1_save.AGE_UNITS_PER_YEAR
REVIVE_ADULT_UNITS = 20 * UNITS_PER_YEAR          # died at 20 or older: back at exactly 20 (younger: their age at death)

ROLE_WORDS = {"Parent": 0, "Parent (married in)": 1, "Child": 2}
CAUSES = {v: k for k, v in vf1_save.DEATH_CAUSES_UNCONFIRMED.items()}


class BackfillError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- the sidecar
def sidecar_path(folder: Path, number: int) -> Path:
    return Path(folder) / vf1_save.PATCHER_DATA / FOLDER / f"{vf1_save.SAVE_PREFIX}{number}.ldw.dat"


@dataclass
class Sidecar:
    save_hash: int
    save_size: int
    generations: int
    parent_slot: int
    parent_sex: int
    entries: list[bytes]


def read_sidecar(data: bytes) -> Sidecar | None:
    """The file as vf1revive reads it (ReadSidecar); None for anything it would refuse."""
    if gen.sidecar_key(data) is None or data[:8] != MAGIC:
        return None
    count = struct.unpack_from("<I", data, 48)[0]
    entries = [data[HEADER + i * ENTRY:HEADER + (i + 1) * ENTRY] for i in range(count)]
    for e in entries:
        state, slot = struct.unpack_from("<i", e, E_STATE)[0], struct.unpack_from("<i", e, E_SLOT)[0]
        if state not in (STATE_DEAD, STATE_REVIVED) or not -1 <= slot < vf1_save.VILLAGER_SLOTS \
                or e[E_WHOLE + WHOLE_SIZE - 1] != 0:
            return None
    save_hash, save_size, gens, pslot, psex = struct.unpack_from("<QIiii", data, 24)
    return Sidecar(save_hash, save_size, gens, pslot, psex, entries)


def render_sidecar(save_bytes: bytes, generations: int, parent_slot: int, parent_sex: int,
                   entries: list[bytes]) -> bytes:
    if len(entries) > MAX_ENTRIES:
        raise BackfillError(f"a Revive file holds at most {MAX_ENTRIES} people")
    size = HEADER + len(entries) * ENTRY + 8
    out = bytearray(size)
    out[:8] = MAGIC
    struct.pack_into("<I", out, 8, VERSION)
    out[12:20] = TAG
    struct.pack_into("<I", out, 20, size)
    struct.pack_into("<QIiiiI", out, 24, gen.fnv1a64(save_bytes), len(save_bytes), generations, parent_slot,
                     parent_sex, len(entries))
    for i, e in enumerate(entries):
        if len(e) != ENTRY:
            raise BackfillError("a snapshot of the wrong size")
        out[HEADER + i * ENTRY:HEADER + (i + 1) * ENTRY] = e
    struct.pack_into("<Q", out, size - 8, gen.fnv1a64(bytes(out[:-8])))
    return bytes(out)


# ---------------------------------------------------------------------------------------------- one snapshot
def i32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<i", raw, off)[0]


@dataclass
class Snapshot:
    """One entry, read."""
    raw: bytes

    @property
    def state(self) -> int:
        return i32(self.raw, E_STATE)

    @property
    def source(self) -> int:
        return i32(self.raw, E_SOURCE)

    def mark(self, name: str) -> int:
        bits = struct.unpack_from("<Q", self.raw, E_MARKS)[0]
        return (bits >> (2 * FIELDS.index(name))) & 3

    def marks(self) -> dict[str, str]:
        return {f: MARK_WORDS[self.mark(f)] for f in FIELDS}

    @property
    def name(self) -> str:
        return vf1_text.decode(self.raw[E_BIO + 0x10:E_BIO + 0x2C])

    @property
    def whole_name(self) -> str:
        return vf1_text.decode(self.raw[E_WHOLE:E_WHOLE + WHOLE_SIZE])

    @property
    def sex(self) -> int:
        return i32(self.raw, E_BIO + 4)

    @property
    def head(self) -> int:
        return i32(self.raw, E_BIO + 0x2C)

    @property
    def body(self) -> int:
        return i32(self.raw, E_BIO + 0x30)

    @property
    def age_units(self) -> int:
        return i32(self.raw, E_BIO)

    @property
    def cause(self) -> int:
        return i32(self.raw, E_VSTATE + 0x10)

    @property
    def generation(self) -> int:
        return i32(self.raw, E_GENERATION)

    @property
    def role(self) -> int:
        return i32(self.raw, E_ROLE)

    def revive_units(self) -> int:
        """The age they come back at (vf1revive.cpp ReviveAge): 20 years for anyone who died at 20 or older, and for
        anyone whose age at death is not known."""
        if self.mark("age at death") in (UNKNOWN, UNKNOWN_ADULT):
            return REVIVE_ADULT_UNITS
        return min(max(self.age_units, 0), REVIVE_ADULT_UNITS)

    def key(self) -> tuple:
        return (self.name, self.sex, self.head, self.body)


@dataclass
class Dead:
    """A family member the save or the log says died."""
    name: str                     # as stored in the save (a short form for a long name)
    sex: int
    head: int | None
    body: int | None
    generation: int
    role: int                     # -1, 0, 1, 2..7
    peep: bytes | None            # their Family Tree entry, when the tree has one
    parent1: bytes                # the generation's parent entries, when known
    parent2: bytes
    age_years: int | None = None  # the log's age at death
    cause: int | None = None
    death_number: int = 0
    from_log: bool = False


def _marks(values: dict[str, int]) -> int:
    bits = 0
    for name, mark in values.items():
        bits |= (mark & 3) << (2 * FIELDS.index(name))
    return bits


def _peep_bytes(name: str, sex: int, head: int, body: int) -> bytes:
    raw = bytearray(PEEP_SIZE)
    raw[0:0x1A] = vf1_text.encode_field(name, 0x1A)
    raw[0x1A] = 1
    struct.pack_into("<iiii", raw, 0x1C, sex, head, body, -1)
    return bytes(raw)


def build_entry(d: Dead, record: vf1_save.Villager | None, source: int, record_is_dead: bool, whole: str) -> bytes:
    """One snapshot of `d`, from `record` (their villager record, dead or from an older save) when there is one."""
    raw = bytearray(ENTRY)
    marks = {f: UNKNOWN for f in FIELDS}
    if record is not None:
        rec = record.raw
        raw[E_BIO:E_BIO + BIO_SIZE] = rec[8:8 + BIO_SIZE]
        raw[E_VSTATE:E_VSTATE + VSTATE_SIZE] = rec[0xA8:0xA8 + VSTATE_SIZE]
        raw[E_SKILLS:E_SKILLS + SKILLS_SIZE] = rec[0x140:0x140 + SKILLS_SIZE]
        raw[E_LIKES:E_LIKES + LIKES_SIZE] = rec[0x150:0x150 + LIKES_SIZE]
        lived = EXACT if record_is_dead else INFERRED          # what can change in a life
        for f in ("name", "sex", "head", "body", "voice", "name index", "parents"):
            marks[f] = EXACT
        for f in ("likes", "dislikes", "career", "fertility", "wants kids"):
            marks[f] = lived
        if record_is_dead:
            marks["age at death"] = marks["cause of death"] = EXACT
        struct.pack_into("<i", raw, E_SLOT, record.slot)
    else:
        raw[E_BIO + 0x10:E_BIO + 0x2C] = vf1_text.encode_field(vf1_text.cut_to_bytes(d.name, 24), 0x1C)
        struct.pack_into("<i", raw, E_BIO + 4, d.sex)
        marks["name"] = EXACT if len(vf1_text.encode(d.name)) <= 24 else INFERRED
        marks["sex"] = EXACT
        for f, v in (("head", d.head), ("body", d.body)):
            if v is not None:
                struct.pack_into("<i", raw, E_BIO + (0x2C if f == "head" else 0x30), v)
                marks[f] = EXACT
        struct.pack_into("<i", raw, E_VSTATE + 0x10, -1)
        struct.pack_into("<i", raw, E_SLOT, -1)
    if not record_is_dead:
        # The age at death and the cause: the log's. An older save's age is only a lower bound, which is enough
        # when it is 18 or more (the revival age is then 18 whatever the age at death was).
        if d.age_years is not None:
            struct.pack_into("<i", raw, E_BIO, d.age_years * UNITS_PER_YEAR)
            marks["age at death"] = INFERRED                    # whole years: the units within the year are not known
        elif record is not None and record.age_units >= REVIVE_ADULT_UNITS:
            marks["age at death"] = INFERRED
        else:
            struct.pack_into("<i", raw, E_BIO, REVIVE_ADULT_UNITS)
            marks["age at death"] = UNKNOWN_ADULT              # not found anywhere: they come back at 20
        if d.cause is not None:
            struct.pack_into("<i", raw, E_VSTATE + 0x10, d.cause)
            marks["cause of death"] = EXACT
        else:
            struct.pack_into("<i", raw, E_VSTATE + 0x10, -1)
            marks["cause of death"] = UNKNOWN
        struct.pack_into("<i", raw, E_VSTATE + 0xC, 0)           # dead
    struct.pack_into("<i", raw, E_STATE, STATE_DEAD)
    struct.pack_into("<i", raw, E_SOURCE, source)
    struct.pack_into("<i", raw, E_ROLE, d.role)
    struct.pack_into("<i", raw, E_GENERATION, d.generation)
    struct.pack_into("<i", raw, E_DEATH_NUMBER, d.death_number)
    struct.pack_into("<i", raw, E_REVIVED_SLOT, -1)
    marks["generation"] = EXACT
    marks["family tree"] = EXACT if d.peep is not None else (INFERRED if d.role >= 0 else UNKNOWN)
    if d.peep is not None:
        raw[E_PEEP:E_PEEP + PEEP_SIZE] = d.peep
    elif d.role >= 0 and d.head is not None and d.body is not None:
        raw[E_PEEP:E_PEEP + PEEP_SIZE] = _peep_bytes(d.name, d.sex, d.head, d.body)
    raw[E_PARENT1:E_PARENT1 + PEEP_SIZE] = d.parent1
    raw[E_PARENT2:E_PARENT2 + PEEP_SIZE] = d.parent2
    encoded = vf1_text.encode(whole)[:WHOLE_SIZE - 1]
    raw[E_WHOLE:E_WHOLE + len(encoded)] = encoded
    marks["whole name"] = EXACT
    struct.pack_into("<Q", raw, E_MARKS, _marks(marks))
    return bytes(raw)


# ---------------------------------------------------------------------------------------------- who died
def _tree_bytes(save: vf1_save.VF1Save) -> bytes:
    at = vf1_save.GS_FAMILY_TREE - vf1_save.GS_BASE
    return save.payload[at:at + vf1_save.FAMILY_RECORDS * vf1_save.FAMILY_RECORD]


def _peep_raw(tree: bytes, generation: int, which: int) -> bytes:
    rec = (generation - 1) * vf1_save.FAMILY_RECORD
    off = 4 if which == 0 else 0xDC if which == 1 else 0x1B8 + (which - 2) * PEEP_SIZE
    return tree[rec + off:rec + off + PEEP_SIZE]


def dead_in_tree(save: vf1_save.VF1Save) -> list[Dead]:
    """Every Family Tree entry the game marked dead (ReportDeath sets the slot to -1; nothing else does)."""
    tree = _tree_bytes(save)
    out = []
    for rec in save.family_records:
        g = rec.generation
        people = [(0, rec.parent1), (1, rec.parent2)] + [(2 + k, c) for k, c in enumerate(rec.children)]
        for which, peep in people:
            if peep.used and peep.slot == -1:
                out.append(Dead(peep.name, peep.sex, peep.head, peep.body, g, which, _peep_raw(tree, g, which),
                                _peep_raw(tree, g, 0), _peep_raw(tree, g, 1)))
    return out


def _log_when(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _saved_at(save: vf1_save.VF1Save) -> datetime:
    return save.header.real_time(save.time.saved_at).astimezone().replace(tzinfo=None)


def dead_in_log(entries: list[history_log.Entry], save: vf1_save.VF1Save, stored_of) -> list[Dead]:
    """The log's Death records of the family in `save` made before it was saved (a backfilled one has no date and is
    taken), of people not alive in it. Only the records after the last eviction belong to this family."""
    tree = _tree_bytes(save)
    out = []
    when_saved = _saved_at(save)
    for e in entries:
        if e.kind == "Evict Family":
            out = []
            continue
        if e.kind != "Death":
            continue
        when = _log_when(e.when)
        if when is not None and when > when_saved:
            continue
        g = e.generation() or 0
        if not 1 <= g <= len(save.family_records):
            continue
        name = stored_of(e.get("Name", ""))
        sex = 1 if e.get("Sex") == "Female" else 0
        head = e.get("Head")
        body = e.get("Body")
        age = e.get("Age at death")
        cause = CAUSES.get(e.get("Cause of death", ""))
        role = ROLE_WORDS.get(e.get("Family role", ""), -1)
        out.append(Dead(name, sex, int(head) if head and head.lstrip("-").isdigit() else None,
                        int(body) if body and body.lstrip("-").isdigit() else None, g, role, None,
                        _peep_raw(tree, g, 0), _peep_raw(tree, g, 1),
                        int(age) if age and age.isdigit() else None, cause, e.number, True))
    return out


def _same(d: Dead, name: str, sex: int, head: int, body: int) -> bool:
    return d.name == name and d.sex == sex and (d.head is None or d.head == head) and (d.body is None or d.body == body)


def _alive(save: vf1_save.VF1Save, d: Dead) -> bool:
    return any(v.present and v.health > 0 and _same(d, v.name, v.sex, v.head, v.body) for v in save.villagers)


def dead_people(save: vf1_save.VF1Save, log: list[history_log.Entry], stored_of) -> list[Dead]:
    """The tree's dead, then the log's dead the tree does not hold (a childless spouse's death frees the entry)."""
    people = [d for d in dead_in_tree(save) if not _alive(save, d)]
    for d in dead_in_log(log, save, stored_of):
        if _alive(save, d):
            continue
        same = [p for p in people if p.name == d.name and p.sex == d.sex and p.generation == d.generation]
        if same:
            p = same[0]
            p.age_years = p.age_years if p.age_years is not None else d.age_years
            p.cause = p.cause if p.cause is not None else d.cause
            p.death_number = p.death_number or d.death_number
            continue
        if d.role == 2:                         # a child the tree no longer holds: their place is not known
            d.role = -1
        people.append(d)
    return people


# ---------------------------------------------------------------------------------------------- the sources
@dataclass
class SaveFile:
    path: Path
    data: bytes
    save: vf1_save.VF1Save
    source: int                   # SOURCE_OLDER (this folder) or SOURCE_BACKUP

    @property
    def saved_at(self) -> datetime:
        return _saved_at(self.save)


def _read_save(path: Path, source: int) -> SaveFile | None:
    try:
        data = path.read_bytes()
        return SaveFile(path, data, vf1_save.parse_save(data), source)
    except (OSError, vf1_save.SaveFormatError, struct.error, ValueError):
        return None


def _who(d: Dead, villagers) -> vf1_save.Villager | None:
    """The one of ``villagers`` that is ``d``: the same name, sex and head (what never changes in a life). The body
    is only a tiebreak, then the age at death the log gives: the Family Tree keeps the body it had when the person
    was entered, and a body (or an outfit's) changes as they grow (the end-to-end check, 2026-11-27: an heir dead in
    the house was missed from her own record)."""
    found = [v for v in villagers if v.name and v.name == d.name and v.sex == d.sex
             and (d.head is None or v.head == d.head)]
    if len(found) > 1 and d.body is not None and any(v.body == d.body for v in found):
        found = [v for v in found if v.body == d.body]
    if len(found) > 1 and d.age_years is not None and any(v.age_units // UNITS_PER_YEAR == d.age_years for v in found):
        found = [v for v in found if v.age_units // UNITS_PER_YEAR == d.age_years]
    return found[0] if found else None


def _stale(save: vf1_save.VF1Save, d: Dead) -> vf1_save.Villager | None:
    """The dead person's own record, still in the save: health 0, matching who they were (_who)."""
    return _who(d, [v for v in save.villagers if v.health <= 0])


def best_source(d: Dead, here: SaveFile, others: list[SaveFile]) -> tuple[vf1_save.Villager | None, int, bool]:
    """(record, source, the record is the dead one) for `d`: the save's own stale record, then an older save's stale
    record, then the newest older save in which they were alive; else no record (the tree or the log)."""
    v = _stale(here.save, d)
    if v is not None:
        return v, SOURCE_STALE, True
    older = sorted((o for o in others if o.saved_at <= here.saved_at), key=lambda o: o.saved_at, reverse=True)
    for o in older:
        v = _stale(o.save, d)
        if v is not None:
            return v, o.source, True
    for o in older:
        v = _who(d, [v for v in o.save.villagers if v.present and v.health > 0])
        if v is not None:
            return v, o.source, False
    return None, SOURCE_TREE if d.peep is not None else SOURCE_LOG, False


# ---------------------------------------------------------------------------------------------- planning
@dataclass
class Planned:
    path: Path
    old: bytes | None
    new: bytes
    added: list[Snapshot]


@dataclass
class FolderResult:
    folder: Path
    planned: list[Planned] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    left: list[tuple[Path, str]] = field(default_factory=list)      # (path, why it was left as it is)
    waiting: bool = False                                           # the live folder, while the game runs
    backed_up: list[Path] = field(default_factory=list)


def _slot_saves(folder: Path, slot: int, source: int) -> dict[int, SaveFile]:
    out = {}
    for number in (slot, slot + 20, slot + 40):
        f = _read_save(Path(folder) / f"{vf1_save.SAVE_PREFIX}{number}.ldw", source)
        if f is not None:
            out[number] = f
    return out


def sibling_folders(folder: Path) -> list[Path]:
    """The other copies of the same saves: for the live folder its Backups, for a backup the live folder and the other
    backups."""
    folder = Path(folder)
    if folder.parent.name == "Backups":
        live = folder.parent.parent
        return [live] + [b for b in sorted(folder.parent.iterdir()) if b.is_dir() and b != folder]
    backups = folder / "Backups"
    return sorted(b for b in backups.iterdir() if b.is_dir()) if backups.is_dir() else []


def plan_folder(folder: Path) -> FolderResult:
    """What the backfill would write in one save folder (live or a backup); nothing is written here."""
    folder = Path(folder)
    result = FolderResult(folder)
    siblings = sibling_folders(folder)
    book = vf1_names.Book(folder)
    for slot in range(1, 6):
        saves = _slot_saves(folder, slot, SOURCE_OLDER)
        if not saves:
            continue
        others_all = list(saves.values())
        for s in siblings:
            others_all += list(_slot_saves(s, slot, SOURCE_BACKUP).values())
        log: list[history_log.Entry] = []
        for p in history_log.files(folder, slot):
            try:
                log += history_log.entries(vf1_text.decode_lines(p.read_bytes()))
            except OSError:
                continue
        whole_to_short = {e.full: e.short for e in book.slots.get(slot, [])}
        stored_of = lambda name: whole_to_short.get(name, name)  # noqa: E731
        for number, here in saves.items():
            path = sidecar_path(folder, number)
            entries: list[bytes] = []
            old = None
            if path.exists():
                try:
                    old = path.read_bytes()
                except OSError as exc:
                    result.left.append((path, f"could not be read ({exc})"))
                    continue
                sidecar = read_sidecar(old)
                if sidecar is None:
                    result.left.append((path, "is damaged; it is left as it is"))
                    continue
                if (sidecar.save_hash, sidecar.save_size) != (gen.fnv1a64(here.data), len(here.data)):
                    result.left.append((path, "describes another save; it is left as it is"))
                    continue
                entries = list(sidecar.entries)
            known = {Snapshot(e).key() for e in entries}
            known_loose = {(Snapshot(e).name, Snapshot(e).sex, Snapshot(e).generation) for e in entries}
            others = [o for o in others_all if o.path != here.path]
            added = []
            for d in dead_people(here.save, log, stored_of):
                if (d.name, d.sex, d.generation) in known_loose and (d.head is None or d.body is None):
                    continue
                record, source, is_dead = best_source(d, here, others)
                whole = book.full(slot, d.name)
                entry = build_entry(d, record, source, is_dead, whole)
                snap = Snapshot(entry)
                if snap.key() in known or (snap.name, snap.sex, snap.generation) in known_loose:
                    continue
                if len(entries) >= MAX_ENTRIES:
                    result.left.append((path, f"is full ({MAX_ENTRIES} people); {snap.name} was not added"))
                    break
                entries.append(entry)
                known.add(snap.key())
                known_loose.add((snap.name, snap.sex, snap.generation))
                added.append(snap)
            if not added:
                continue
            rec = here.save.current_family
            new = render_sidecar(here.data, here.save.generation, rec.parent1.slot if rec else -1,
                                 rec.parent1.sex if rec else -1, entries)
            result.planned.append(Planned(path, old, new, added))
    return result


# ---------------------------------------------------------------------------------------------- writing
def _replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    if path.read_bytes() != data:
        raise BackfillError(f"{path.name} did not read back as written")


def apply_folder(result: FolderResult, now: datetime | None = None, writer=_replace) -> FolderResult:
    """Writes what plan_folder planned: every replaced file copied first; all or none."""
    if not result.planned:
        return result
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H-%M-%S")
    backup = Path(result.folder) / vf1_save.PATCHER_DATA / FOLDER / f"Before Backfill {stamp}"
    done: list[Planned] = []
    try:
        for p in result.planned:
            if p.old is not None:
                backup.mkdir(parents=True, exist_ok=True)
                kept = backup / p.path.name
                shutil.copy2(p.path, kept)
                if kept.read_bytes() != p.old:
                    raise BackfillError(f"the copy of {p.path.name} did not read back")
                result.backed_up.append(kept)
            if (p.path.read_bytes() if p.path.exists() else None) != p.old:
                raise BackfillError(f"{p.path.name} changed while the backfill ran; nothing was written")
            done.append(p)                       # from here on it is put back on any failure, its own write too
            writer(p.path, p.new)
            result.written.append(p.path)
    except (OSError, BackfillError) as exc:
        problems = []
        for p in reversed(done):
            try:
                if p.old is None:
                    p.path.unlink(missing_ok=True)
                else:
                    _replace(p.path, p.old)
            except OSError as undo:
                problems.append(f"{p.path.name}: {undo}")
        result.written = []
        extra = f" Could not put back: {'; '.join(problems)}" if problems else ""
        raise BackfillError(f"The backfill of {result.folder} failed and every file was put back ({exc}).{extra}") \
            from exc
    return result


def backfill(save_folder: Path, game_running: bool, now: datetime | None = None, writer=_replace) -> list[FolderResult]:
    """The backfill of a save folder and every backup in it. The live folder waits while the game runs."""
    save_folder = Path(save_folder)
    out = []
    folders = [save_folder] + sibling_folders(save_folder)
    for folder in folders:
        result = plan_folder(folder)
        if folder == save_folder and game_running:
            result.waiting = bool(result.planned)
            result.planned = []
            out.append(result)
            continue
        out.append(apply_folder(result, now, writer))
    return out


def report(results: list[FolderResult]) -> str:
    """What was done, in words: each person added, where from, and how each field is known."""
    lines = []
    for r in results:
        if r.waiting:
            lines.append(f"{r.folder}: waits until the game is closed (the running game uses these saves).")
        for path, why in r.left:
            lines.append(f"{path.name} in {r.folder}: {why}.")
        for p in r.planned if r.written else []:
            for s in p.added:
                known = ", ".join(f"{f} {w}" for f, w in s.marks().items())
                lines.append(f"{p.path.name} in {r.folder}: {s.whole_name or s.name} (generation {s.generation}, "
                             f"from {SOURCES.get(s.source, '?')}): {known}.")
    return "\n".join(lines) if lines else "Nothing to backfill: every death already has a snapshot."
