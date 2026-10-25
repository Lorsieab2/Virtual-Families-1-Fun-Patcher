"""Check Saves & Logs and Repair Saves & Logs for Virtual Families 1 (the Tools tab).

Ported from the Virtual Villagers Fun Patcher's two log tools (src/vv_log_tools.py check_logs, the
reconciliation of src/vv_reconcile.py, the answered questions of src/vv_answered_questions.py and the
Repair Saves & Logs window), with family wording, for the Family Logs this patcher's vf1logs.dll writes
(docs/FAMILY_LOGS.md) and the save docs/vf1-save-format.md documents (read by vf1_save.py).

CHECK SAVES & LOGS (`check`) only reads. For one save slot it compares every Family Log and data file with
the save (and the game's two older copies of it, "Virtual Families<N+20>.ldw" and "<N+40>.ldw", when they
hold the same family) and lists, in plain words, each contradiction with its verdict:

    OK         agrees with the save
    WRONG      confirmed wrong; "repairable" when Repair Saves & Logs can put it right
    ASK        a contradiction only the player can settle: Repair Saves & Logs asks it
    NOTE       a difference that is not proof of an error
    UNCHECKED  nothing to check it against, or it could not be read

What is checked: every family member in the save is in the logs (Family History, Births) and every child
of the Family Tree has its mother and father in the Parents file; no Death record names a member who is
alive; no record is logged twice; every family member at the last save (the Family Members at Last Save
file) and in the older save copies is still in the save or has a record of how they left (Death, Evict
Family, Divorce Spouse, Unaccounted); the parents agree between the save, the Births log and the Parents
file; the Family Statistics and Family Population pages and their counters add up with the save.

REPAIR SAVES & LOGS (`apply`) puts right what the player chose, with the game closed: the save folder is
backed up first (Back Up Saves' own copier, "Backup <date> (before repair)"), each file is copied into
"Save <N>\\Copies Made Before Repairs" before it changes, and one "Repair <n>" record lists every change
(and every answer) in the slot's Repairs Made log. It backfills missing records, removes false or
duplicated records (each with the reason, and the removed lines kept in the record), writes Unaccounted
records, and rewrites the two pages and the counters from the save.

THE SAVE IS NEVER CHANGED. The Virtual Villagers patcher's save repairs (graves, names the Villager Details
screen cut short, last names and numbering, corrupted skills, game speed) have no Virtual Families 1
counterpart among the problems found here whose save field is VERIFIED in docs/vf1-save-format.md, so
every repair is to the logs and the patcher's own data files.

NEVER GUESSED. What the files cannot decide is a question (`Question`): "Don't know" is always a choice and
changes nothing. A real answer is kept in the slot's Answered Questions file and never asked again (it is
applied as given each time Repair runs); the Answered Questions list changes or clears it.

The words the logs use are the executable's own, as vf1logs.dll writes them (tools/vf1_logs_sites.py
checks each against the vanilla executable): "Male", "Female", "Nursing" and the causes of death.
Nothing here touches Tk.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_save as vs
import vf1_save_backup as save_backup

PATCHER_FOLDER = "Virtual Families 1 Patcher"
SAVE_STEM = "Virtual Families"
COPIES_FOLDER = "Copies Made Before Repairs"
BEFORE_REPAIR = "(before repair)"
BACKFILLED = "[backfilled, no date] "

# The executable's own words (string ids 0x464 / 0x465 / Nursing / 0x507..0x50C), as vf1logs.dll prints them.
SEX_WORDS = {0: "Male", 1: "Female"}
CAUSE_WORDS = ["Unknown causes", "Disease", "Starvation", "Old age", "Work accident", "Act of Nature"]
NURSING = "Nursing"
NAME_MAX = 25                      # vf1logs.dll's Name(..., 25)
FAMILY_NAME_MAX = 0x1C - 1

VERDICTS = ("OK", "WRONG", "ASK", "NOTE", "UNCHECKED")
DONT_KNOW = "Don't know (leave it)"


class LogToolError(Exception):
    """Nothing was done; the message says why."""


class GameRunning(LogToolError):
    """The game that saves in this folder is running."""


# ---------------------------------------------------------------------------
# Where everything is (docs/FAMILY_LOGS.md "Files")
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LogKind:
    sub: str                       # the folder under Logs
    stem: str                      # "<stem> <k>.txt"
    roll: str                      # the lines counted to roll the file (vf1logs.dll kLogs[].roll)
    per: int                       # ... and how many a file holds
    heading: str = ""              # "Death" -> "Death <n>" records


HISTORY = LogKind("Family History", "Family History", "[", 2000)
BIRTHS = LogKind("Births and Conceptions", "Virtual Families 1 Births and Conceptions Log", "Conception ", 256)
DEATHS = LogKind("Deaths", "Virtual Families 1 Deaths Log", "Death ", 256, "Death")
EVENTS = LogKind("Events", "Virtual Families 1 Events Log", "Event ", 256, "Event")
# Written only by Repair Saves & Logs (the Virtual Villagers patcher's Unaccounted and Repairs Made logs).
UNACCOUNTED = LogKind("Unaccounted", "Virtual Families 1 Unaccounted Log", "Unaccounted ", 256, "Unaccounted")
REPAIRS = LogKind("Repairs Made", "Virtual Families 1 Repairs Made Log", "Repair ", 256, "Repair")
DLL_LOGS = (HISTORY, BIRTHS, DEATHS, EVENTS)

POPULATION = "Family Population"
STATISTICS = "Family Statistics"
RECONCILIATION = "Reconciliation"


def slot_root(folder: Path, slot: int) -> Path:
    return Path(folder) / PATCHER_FOLDER / f"Save {slot}"


def log_path(folder: Path, slot: int, kind: LogKind, number: int) -> Path:
    return slot_root(folder, slot) / "Logs" / kind.sub / f"{kind.stem} {number}.txt"


def page_path(folder: Path, slot: int, sub: str) -> Path:
    return slot_root(folder, slot) / "Logs" / sub / f"{sub} - Save {slot}.txt"


def report_path(folder: Path, slot: int) -> Path:
    return slot_root(folder, slot) / "Logs" / RECONCILIATION / f"Virtual Families 1 Reconciliation - Save {slot}.txt"


def data_path(folder: Path, slot: int, kind: str, stem: str) -> Path:
    return slot_root(folder, slot) / "Data" / kind / f"{stem} - Save {slot}.dat"


def parents_path(folder, slot):
    return data_path(folder, slot, "Parents", "Virtual Families 1 Parents")


def members_path(folder, slot):
    return data_path(folder, slot, "Unaccounted Villagers", "Virtual Families 1 Family Members at Last Save")


def counters_path(folder, slot):
    return data_path(folder, slot, "Family Statistics", "Family Statistics")


def backfill_path(folder, slot):
    return data_path(folder, slot, "Log Checks", "Virtual Families 1 Backfill")


def answers_path(folder, slot):
    return data_path(folder, slot, "Log Checks", "Virtual Families 1 Answered Questions")


def save_path(folder: Path, number: int) -> Path:
    return Path(folder) / f"{SAVE_STEM}{number}.ldw"


# ---------------------------------------------------------------------------
# Words and identities
# ---------------------------------------------------------------------------

def sex_word(sex: int | None) -> str:
    return SEX_WORDS[1] if sex == 1 else SEX_WORDS[0]


def sex_of(word: str | None) -> int | None:
    return {w.casefold(): k for k, w in SEX_WORDS.items()}.get((word or "").strip().casefold())


def cause_word(cause: int) -> str:
    k = cause + 1
    return CAUSE_WORDS[k] if 0 <= k < len(CAUSE_WORDS) else CAUSE_WORDS[0]


def log_name(name: str, limit: int = NAME_MAX) -> str:
    """A game name as vf1logs.dll prints it: at most `limit` characters, tabs and line ends dropped."""
    return "".join(c for c in (name or "")[:limit] if c not in "\t\r\n")


def years(units: int) -> int:
    return max(0, units) // vs.AGE_UNITS_PER_YEAR


@dataclass(frozen=True)
class Who:
    """One person, the way the logs and the save can both name them (the VV patcher's identity: name,
    head and body; with the sex the logs also print)."""
    name: str
    sex: int | None
    head: int | None
    body: int | None

    def same(self, other: "Who") -> bool:
        return (self.name == other.name and self.head == other.head and self.body == other.body
                and (self.sex is None or other.sex is None or self.sex == other.sex))

    def describe(self) -> str:
        sex = f"{sex_word(self.sex)}, " if self.sex is not None else ""
        return f"{self.name} ({sex}head {self.head}, body {self.body})"

    @property
    def key(self) -> str:
        return f"{self.name}#{self.sex}#{self.head}#{self.body}"


def who_of(v: vs.Villager) -> Who:
    return Who(log_name(v.name), v.sex if v.sex in (0, 1) else 0, v.head, v.body)


def _int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Reading the logs (never written here)
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    return path.read_bytes().decode("latin-1")


def _lines(text: str) -> list[str]:
    """Lines with their own endings (a rewrite keeps every other byte as it was)."""
    return text.splitlines(keepends=True)


@dataclass
class LogFile:
    kind: LogKind
    number: int
    path: Path
    lines: list[str]                 # with their endings

    @property
    def header(self) -> str | None:
        first = self.lines[0].rstrip("\r\n") if self.lines else ""
        return first if first.startswith("Family: ") else None


RECORD_HEAD = re.compile(r"^(Conception|Birth|Death|Event|Unaccounted|Repair) (\d+)$")
FIELD = re.compile(r"^( +)([^:]+):(?: (.*))?$")


@dataclass
class Record:
    kind: str                        # Conception, Birth, Death, Event, Unaccounted, Repair
    number: int
    file: LogFile
    start: int                       # its heading's line in the file
    end: int                         # after its blank line
    text: list[str]                  # its lines without endings, heading first, no blank line
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def body(self) -> tuple[str, ...]:
        return tuple(self.text[1:])

    def get(self, key: str) -> str | None:
        return self.fields.get(key)

    def who(self, role: str = "") -> Who:
        """The person a record names: "Child" / "Mother" / "Father" (Births), or the record's own Name."""
        if role:
            return Who(self.get(role) or "", sex_of(self.get(f"{role}.Sex")), _int(self.get(f"{role}.Head")),
                       _int(self.get(f"{role}.Body")))
        return Who(self.get("Name") or "", sex_of(self.get("Sex")), _int(self.get("Head")), _int(self.get("Body")))

    @property
    def where(self) -> str:
        return f"{self.kind} {self.number} ({self.file.path.name}, line {self.start + 1})"


def parse_records(log: LogFile) -> list[Record]:
    out: list[Record] = []
    lines = [line.rstrip("\r\n") for line in log.lines]
    i = 0
    while i < len(lines):
        m = RECORD_HEAD.match(lines[i])
        if not m:
            i += 1
            continue
        start, j = i, i + 1
        while j < len(lines) and lines[j].strip() and not RECORD_HEAD.match(lines[j]) \
                and not lines[j].startswith("Family: "):
            j += 1
        text = lines[start:j]
        if j < len(lines) and not lines[j].strip():
            j += 1
        rec = Record(m.group(1), int(m.group(2)), log, start, j, text)
        parent = ""
        for line in text[1:]:
            f = FIELD.match(line)
            if not f:
                continue
            label, value = f.group(2).strip(), (f.group(3) or "").strip()
            if len(f.group(1)) <= 2:
                parent = label
                rec.fields.setdefault(label, value)
            else:
                rec.fields.setdefault(f"{parent}.{label}", value)
        out.append(rec)
        i = j
    return out


@dataclass
class HistoryLine:
    file: LogFile
    index: int
    stamp: str                       # "backfilled, no date" or "YYYY-MM-DD HH:MM:SS"
    text: str

    @property
    def backfilled(self) -> bool:
        return self.stamp == "backfilled, no date"

    @property
    def raw(self) -> str:
        return f"[{self.stamp}] {self.text}"


HISTORY_LINE = re.compile(r"^\[([^\]]*)\] (.*)$")


def read_log(folder: Path, slot: int, kind: LogKind) -> list[LogFile]:
    """Every file of a log, 1, 2, ... while they exist (vf1logs.dll's own NewestFile walk)."""
    files = []
    k = 1
    while k <= 4096:
        path = log_path(folder, slot, kind, k)
        if not path.is_file():
            break
        files.append(LogFile(kind, k, path, _lines(_read_text(path))))
        k += 1
    return files


# ---------------------------------------------------------------------------
# The data files (docs/FAMILY_LOGS.md: tagged text, tab separated)
# ---------------------------------------------------------------------------

@dataclass
class ParentsEntry:
    slot: int
    name: str
    sex: int
    generation: int
    mother: str
    father: str
    how: str
    line: int


@dataclass
class Member:
    slot: int
    name: str
    sex: int
    age: int
    head: int
    body: int
    present: bool
    left_home: bool
    health: int
    death_logged: bool

    @property
    def who(self) -> Who:
        return Who(self.name, self.sex, self.head, self.body)


@dataclass
class MembersFile:
    family: str
    generations: int
    members: list[Member]


class Unreadable(Exception):
    pass


def _data_lines(path: Path, tag: str) -> list[str] | None:
    if not path.is_file():
        return None
    lines = _read_text(path).splitlines()
    if not lines or lines[0].strip() != tag:
        raise Unreadable(f"{path.name} does not start with {tag!r}")
    return lines[1:]


def read_parents(folder, slot) -> list[ParentsEntry] | None:
    lines = _data_lines(parents_path(folder, slot), "VF1LOGS PARENTS 1")
    if lines is None:
        return None
    out = []
    for n, line in enumerate(lines, 2):
        f = line.split("\t")
        if len(f) == 8 and f[0] == "child" and None not in (_int(f[1]), _int(f[3]), _int(f[4])):
            out.append(ParentsEntry(int(f[1]), f[2], int(f[3]), int(f[4]), f[5], f[6], f[7], n))
    return out


def read_members(folder, slot) -> MembersFile | None:
    lines = _data_lines(members_path(folder, slot), "VF1LOGS MEMBERS 1")
    if lines is None:
        return None
    family, generations, members, ended = "", 0, [], False
    for line in lines:
        f = line.split("\t")
        if f[0] == "family" and len(f) >= 2:
            family = f[1]
        elif f[0] == "generations" and len(f) >= 2:
            generations = _int(f[1]) or 0
        elif f[0] == "member" and len(f) == 11 and all(_int(x) is not None for x in f[1:2] + f[3:]):
            v = [int(x) for x in f[3:]]
            members.append(Member(int(f[1]), f[2], v[0], v[1], v[2], v[3], bool(v[4]), bool(v[5]), v[6], bool(v[7])))
        elif f[0] == "end" and len(f) >= 2:
            ended = _int(f[1]) == len(members)
    if not ended:
        raise Unreadable("the Family Members at Last Save file is cut short")
    return MembersFile(family, generations, members)


def read_counters(folder, slot) -> tuple[int, int] | None:
    lines = _data_lines(counters_path(folder, slot), "VF1LOGS STATS 1")
    if lines is None:
        return None
    values = {}
    for line in lines:
        f = line.split("\t")
        if len(f) == 2 and f[0] in ("babies", "deaths") and _int(f[1]) is not None:
            values[f[0]] = int(f[1])
    return values.get("babies", 0), values.get("deaths", 0)


def read_page(folder, slot, sub) -> dict[str, str] | None:
    path = page_path(folder, slot, sub)
    if not path.is_file():
        return None
    out: dict[str, str] = {}
    for line in _read_text(path).splitlines():
        if ": " in line and not line.startswith(" "):
            key, value = line.split(": ", 1)
            out.setdefault(key, value)
    return out


def page_members(folder, slot) -> list[Who] | None:
    path = page_path(folder, slot, POPULATION)
    if not path.is_file():
        return None
    out, cur = [], None
    for line in _read_text(path).splitlines():
        if re.match(r"^Family Member \d+$", line):
            cur = {}
            out.append(cur)
        elif cur is not None and line.startswith("  ") and ": " in line:
            key, value = line.strip().split(": ", 1)
            cur.setdefault(key, value)
    return [Who(c.get("Name", ""), sex_of(c.get("Sex")), _int(c.get("Head")), _int(c.get("Body"))) for c in out]


# ---------------------------------------------------------------------------
# What the pages would say now (vf1logs.dll WritePopulation / WriteStatistics, from the save)
# ---------------------------------------------------------------------------

def header_line(save: vs.VF1Save, slot: int) -> str:
    name = log_name(save.family_name, FAMILY_NAME_MAX)
    return f"Family: {name or '(no name)'} (Save {slot})"


def tree_role(save: vs.VF1Save, v: vs.Villager) -> int:
    """vf1logs.dll TreeRole: 0 parent 1, 1 parent 2, 2.. a child of the current record, -1 not in it."""
    rec = save.current_family
    if rec is None:
        return -1
    peeps = [rec.parent1, rec.parent2] + list(rec.children)
    for k, p in enumerate(peeps):
        if p.used and p.slot == v.slot and p.name[:NAME_MAX] == v.name[:NAME_MAX]:
            return k
    return -1


def role_text(role: int) -> str:
    return {0: "Parent", 1: "Parent (married in)"}.get(role, "Child" if role >= 2 else "(not in the Family Tree)")


def family_members_count(save: vs.VF1Save) -> int:
    return sum(1 for v in save.villagers if v.present and not v.left_home and v.health > 0)


def money_dollars(save: vs.VF1Save) -> int:
    m = save.money
    if not m > 0:
        return 0
    return 4294967040 if m >= 4294967040.0 else int(m)


def population_text(save: vs.VF1Save, slot: int) -> str:
    out = ["Virtual Families 1 Family Population", header_line(save, slot), f"Generation: {save.generation}"]
    k = 0
    for v in save.villagers:
        if not v.present:
            continue
        k += 1
        out += ["", f"Family Member {k}", f"  Name: {log_name(v.name)}", f"  Age: {years(v.age_units)}",
                f"  Sex: {sex_word(v.sex)}", f"  Head: {v.head}", f"  Body: {v.body}",
                f"  Family role: {role_text(tree_role(save, v))}", f"  Health: {v.health}"]
        if v.health <= 0:
            out.append(f"  Cause of death: {cause_word(v.death_cause)}")
        if v.pregnant_since:
            out += [f"  {NURSING}: yes", f"  Babies {NURSING}: {v.babies_carried}"]
        if v.left_home:
            out.append("  Left home: yes")
    if not k:
        out += ["", "(nobody)"]
    return "\r\n".join(out) + "\r\n"


def statistics_text(save: vs.VF1Save, slot: int, counters: tuple[int, int] | None) -> str:
    babies, deaths = counters or (0, 0)
    out = ["Virtual Families 1", "Family Statistics", header_line(save, slot), "",
           f"Generations: {save.generation}", f"Family Members: {family_members_count(save)}",
           f"Babies Born: {babies}", f"Deaths: {deaths}", f"Oldest Family Member Ever: {save.stats.oldest_years}",
           f"Money: ${money_dollars(save)}", f"Food: {save.food}"]
    return "\r\n".join(out) + "\r\n"


def counters_text(babies: int, deaths: int) -> str:
    return f"VF1LOGS STATS 1\r\nbabies\t{babies}\r\ndeaths\t{deaths}\r\n"


def couple_line(g: int, rec: vs.FamilyRecord) -> str:
    """vf1logs.dll Backfill's line for a generation's couple."""
    p1, p2 = rec.parent1, rec.parent2
    h = f"Generation {g}: " + (f"{log_name(p1.name)} ({sex_word(p1.sex)})" if p1.used else "(nobody)")
    if p2.used:
        h += f" and {log_name(p2.name)} ({sex_word(p2.sex)})"
    return h + (" were the parents" if p2.used else " was the parent")


def backfill_lines(save: vs.VF1Save) -> list[str]:
    """The Family History lines vf1logs.dll's first load (Backfill) writes from this save's Family Tree."""
    out = []
    for g, rec in enumerate(save.family_records, 1):
        p1, p2 = rec.parent1, rec.parent2
        out.append(couple_line(g, rec))
        for c in rec.children:
            if c.used:
                out.append(f"Generation {g}: child {log_name(c.name)} ({sex_word(c.sex)})" + (", died" if c.slot == -1 else ""))
        for p in (p1, p2):
            if p.used and p.slot == -1:
                out.append(f"Generation {g}: {log_name(p.name)} died")
    return out


# ---------------------------------------------------------------------------
# One slot, read
# ---------------------------------------------------------------------------

@dataclass
class Family:
    folder: Path
    slot: int
    save: vs.VF1Save
    older: list[tuple[str, vs.VF1Save]]          # (label, save) of the game's older copies of the same family
    logs: dict[str, list[LogFile]]               # by LogKind.sub
    records: dict[str, list[Record]]             # by LogKind.sub
    history: list[HistoryLine]
    parents: list[ParentsEntry] | None
    members: MembersFile | None
    counters: tuple[int, int] | None
    marker: bool
    problems: list[str]                          # data files that could not be read

    @property
    def has_logs(self) -> bool:
        return slot_root(self.folder, self.slot).is_dir()

    def births(self) -> list[Record]:
        return [r for r in self.records.get(BIRTHS.sub, []) if r.kind == "Birth"]

    def deaths(self) -> list[Record]:
        return [r for r in self.records.get(DEATHS.sub, []) if r.kind == "Death"]

    def events(self) -> list[Record]:
        return [r for r in self.records.get(EVENTS.sub, []) if r.kind == "Event"]

    def unaccounted(self) -> list[Record]:
        return [r for r in self.records.get(UNACCOUNTED.sub, []) if r.kind == "Unaccounted"]


def read_family(folder: Path, slot: int) -> Family:
    """Everything the check needs, read only."""
    folder = Path(folder)
    if slot not in (1, 2, 3, 4, 5):
        raise LogToolError(f"There is no save slot {slot}.")
    path = save_path(folder, slot)
    if not path.is_file():
        raise LogToolError(f"Save {slot} has no family in {folder.name} ({path.name} is not there).")
    try:
        data = path.read_bytes()
        save = vs.parse_save(data)
    except OSError as exc:
        raise LogToolError(f"The save could not be read ({exc}). If the game is saving right now, try again in "
                           "a moment. Nothing was changed.") from exc
    except (vs.SaveFormatError, ValueError) as exc:
        raise LogToolError(f"{path.name} is not a save this tool can read ({exc}). Nothing was changed.") from exc
    older = []
    here = {who_of(v) for v in save.villagers if v.name}
    for n, label in ((slot + 20, "the game's newer copy"), (slot + 40, "the game's older copy")):
        try:
            other_data = save_path(folder, n).read_bytes()
            other = vs.parse_save(other_data)
        except (OSError, vs.SaveFormatError, ValueError):
            continue
        if other.payload == save.payload or other.family_name != save.family_name:
            continue
        # A copy is the same family when any family member is in both (the VV owner's rule).
        if not here & {who_of(v) for v in other.villagers if v.name}:
            continue
        older.append((f"{save_path(folder, n).name} ({label} of Save {slot})", other))
    logs, records, history, problems = {}, {}, [], []
    for kind in (*DLL_LOGS, UNACCOUNTED, REPAIRS):
        try:
            files = read_log(folder, slot, kind)
        except OSError as exc:
            problems.append(f"{kind.sub}: {exc}")
            files = []
        logs[kind.sub] = files
        records[kind.sub] = [r for f in files for r in parse_records(f)]
    for f in logs[HISTORY.sub]:
        for i, line in enumerate(f.lines):
            m = HISTORY_LINE.match(line.rstrip("\r\n"))
            if m:
                history.append(HistoryLine(f, i, m.group(1), m.group(2)))

    def data(reader, label):
        try:
            return reader(folder, slot)
        except (Unreadable, OSError, ValueError) as exc:
            problems.append(f"{label}: {exc}")
            return None
    parents = data(read_parents, "Parents file")
    members = data(read_members, "Family Members at Last Save file")
    counters = data(read_counters, "Family Statistics counters")
    return Family(folder, slot, save, older, logs, records, history, parents, members, counters,
                  backfill_path(folder, slot).is_file(), problems)


# ---------------------------------------------------------------------------
# Findings, repairs and questions
# ---------------------------------------------------------------------------

@dataclass
class Repair:
    """One change Repair Saves & Logs can make, with the evidence for it."""
    key: str                         # the fact it is about (stable from one check to the next)
    title: str                       # what will be done, in plain words
    action: str
    data: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)


@dataclass
class Question:
    key: str
    text: str
    options: list[str]               # DONT_KNOW is always the last
    repairs: dict[str, Repair | None]   # what each option does (None: nothing)
    evidence: list[str] = field(default_factory=list)


@dataclass
class Finding:
    verdict: str
    section: str
    text: str
    repair: Repair | None = None
    question: Question | None = None
    evidence: list[str] = field(default_factory=list)
    answered: str | None = None      # a kept answer (the question is not asked again)


SECTIONS = ("Files", "Family members in the logs", "Parents", "Deaths", "Records logged twice",
            "Family members who left", "Family Statistics and Population")


@dataclass
class CheckResult:
    folder: Path
    slot: int
    family_name: str
    findings: list[Finding]

    @property
    def counts(self) -> dict[str, int]:
        out = {v: 0 for v in VERDICTS}
        for f in self.findings:
            out[f.verdict] += 1
        return out

    @property
    def wrong(self) -> int:
        return self.counts["WRONG"]

    @property
    def asked(self) -> int:
        return self.counts["ASK"]

    def repairs(self) -> list[Repair]:
        return [f.repair for f in self.findings if f.repair is not None]

    def questions(self) -> list[Question]:
        return [f.question for f in self.findings if f.question is not None and f.answered is None]

    def answered(self) -> list[tuple[Question, str]]:
        return [(f.question, f.answered) for f in self.findings if f.question is not None and f.answered is not None]

    @property
    def summary(self) -> str:
        c = self.counts
        parts = ", ".join(f"{c[v]} {v}" for v in VERDICTS)
        verdict = "nothing is confirmed wrong" if not c["WRONG"] else f"{c['WRONG']} confirmed wrong"
        if c["ASK"]:
            verdict += f"; {c['ASK']} question(s) only you can answer"
        return f"Save {self.slot}: {verdict} ({parts})."

    @property
    def text(self) -> str:
        lines = []
        for section in SECTIONS:
            found = [f for f in self.findings if f.section == section]
            if not found:
                continue
            lines.append(f"== {section}")
            for f in found:
                tag = f.verdict
                extra = ""
                if f.verdict == "WRONG":
                    extra = " (repairable)" if f.repair is not None else " (Repair Saves & Logs cannot put this right)"
                lines.append(f"{tag:<9} {f.text}{extra}")
                for e in f.evidence + (f.question.evidence if f.question else []) + (f.repair.evidence if f.repair else []):
                    lines.append(f"          {e}")
                if f.question is not None and f.answered is None:
                    lines.append(f"          Repair Saves & Logs asks: {f.question.text}")
                if f.answered is not None:
                    lines.append(f"          You answered: {f.answered} (not asked again; change it in Answered Questions)")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _question(key, text, choices: dict[str, Repair | None], evidence=()) -> Question:
    options = list(choices) + [DONT_KNOW]
    return Question(key, text, options, {**choices, DONT_KNOW: None}, list(evidence))


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _mentioned(family: Family, who: Who) -> bool:
    """Whether the Family History or a Birth record names this person (vf1logs.dll writes every arrival as
    "<name> (<Sex>" -- adoption, marriage, joining, a new generation, a birth -- and the backfill likewise)."""
    pattern = re.compile(r"(?:^|[\s:])" + re.escape(who.name) + r" \((?:" + "|".join(SEX_WORDS.values()) + r")\b")
    if any(pattern.search(h.text) for h in family.history):
        return True
    return any(r.who("Child").same(who) for r in family.births())


def _in_tree(save: vs.VF1Save, v: vs.Villager):
    """(generation, role, peep) of the Family Tree entry that is this villager, or None. The current record
    is matched as the game does (slot, sex, head) plus the name; older records' slots are stale, so name,
    sex and head are used there."""
    for g, rec in reversed(list(enumerate(save.family_records, 1))):
        peeps = [(0, rec.parent1), (1, rec.parent2)] + [(2 + k, c) for k, c in enumerate(rec.children)]
        for role, p in peeps:
            if not p.used or p.name != v.name or p.sex != v.sex or p.head != v.head:
                continue
            if g == save.generation and p.slot != v.slot:
                continue
            return g, role, p
    return None


def _check_files(family: Family, out: list[Finding]) -> bool:
    """False when the logs are not this family's (nothing else is checked then)."""
    sec = "Files"
    want = header_line(family.save, family.slot)
    if not family.has_logs:
        out.append(Finding("UNCHECKED", sec, f"Family Logs has written nothing for Save {family.slot} yet. Tick "
                           "Family Logs on the Patches tab, play this family, and quit the game from its menu."))
        return False
    foreign = []
    for kind in DLL_LOGS:
        files = family.logs[kind.sub]
        if not files:
            repair = Repair(f"create|{kind.sub}", f"Create the {kind.sub} log with its first line ({want})",
                            "create_log", {"sub": kind.sub})
            out.append(Finding("WRONG", sec, f"The {kind.sub} log is missing.", repair))
            continue
        for f in files:
            if f.header != want:
                foreign.append(f"{f.path.relative_to(family.folder)} begins {f.header or 'without a Family line'!r}")
    if foreign:
        out.append(Finding("WRONG", sec, f"Some logs do not name this family ({want}). They may be another "
                           "family's, copied or restored from elsewhere: nothing else was checked, and nothing is "
                           "changed. Restore the logs from a backup made with this family, or start the family over.",
                           evidence=foreign))
        return False
    out.append(Finding("OK", sec, f"Every log names this family: {want}."))
    for p in family.problems:
        out.append(Finding("UNCHECKED", sec, f"Could not be read, so it was not checked: {p}."))
    if family.parents is None and not any("Parents" in p for p in family.problems):
        out.append(Finding("NOTE", sec, "There is no Parents file yet (it is written when a child is born, joins, "
                           "or the family's first load fills in the Family Tree)."))
    if not family.marker and family.save.generation > 0:
        out.append(Finding("NOTE", sec, "The family's first check has not run yet: the earlier generations are "
                           "added to the Family History the next time the game loads this family."))
    if family.members is not None and family.members.family != log_name(family.save.family_name, FAMILY_NAME_MAX):
        out.append(Finding("NOTE", sec, f"The Family Members at Last Save file names another family "
                           f"({family.members.family!r}); it is not used."))
        family.members = None
    return True


def _check_members_logged(family: Family, out: list[Finding]) -> None:
    sec = "Family members in the logs"
    save = family.save
    if not family.history and not family.births():
        out.append(Finding("UNCHECKED", sec, "The Family History has no lines yet, so nobody could be looked up."))
        return
    missing = 0
    for v in save.household():
        who = who_of(v)
        if _mentioned(family, who):
            continue
        missing += 1
        tree = _in_tree(save, v)
        if tree is None:
            line = (f"{who.name} ({sex_word(who.sex)}, {years(v.age_units)}) was in the family "
                    "(how they joined was not recorded)")
            where = "not in the Family Tree"
        else:
            g, role, _p = tree
            if role >= 2:
                line = f"Generation {g}: child {who.name} ({sex_word(who.sex)})"
            else:
                line = couple_line(g, save.family_records[g - 1])
            where = f"in the Family Tree, generation {g}, as {role_text(role).lower()}"
        repair = Repair(f"member-history|{who.key}", f"Add to the Family History: {BACKFILLED}{line}",
                        "append_history", {"lines": [BACKFILLED + line]},
                        [f"The save has {who.describe()} in the house ({where}); no Family History line and no "
                         "Birth record names them."])
        out.append(Finding("WRONG", sec, f"{who.name} is a family member but no log records them.", repair))
    if not missing:
        out.append(Finding("OK", sec, f"All {len(save.household())} family members in the save are in the logs."))


def _bio_parents(v: vs.Villager) -> tuple[str, str, str] | None:
    """(mother, father, how) from the villager's own record, the way vf1logs.dll would have written them;
    None when the father cannot be known from the save (a natural birth: the save keeps "Joey")."""
    p1, p2 = log_name(v.parent1_name), log_name(v.parent2_name)
    if not p1 and not p2:
        return "", "", "adopted"
    if p1 == "Joey":
        return p2, "", "conceived"
    return p2, p1, "joined"


def _check_parents(family: Family, out: list[Finding]) -> None:
    sec = "Parents"
    save = family.save
    if family.parents is None and any("Parents" in p for p in family.problems):
        return
    entries = family.parents or []
    newest: dict[tuple, ParentsEntry] = {}
    for e in entries:
        newest[(e.slot, e.name, e.sex)] = e
    births = family.births()
    checked = 0
    for v in save.household():
        tree = _in_tree(save, v)
        if tree is None or tree[1] < 2:
            continue                  # only the Family Tree's children have parents in the file
        who = who_of(v)
        checked += 1
        entry = newest.get((v.slot, who.name, v.sex))
        birth = next((b for b in reversed(births) if b.who("Child").same(who)), None)
        bio = _bio_parents(v)
        mother = bio[0] if bio else ""
        father = (birth.get("Father") or "") if birth is not None else (bio[1] if bio else "")
        if father == "(unknown)":
            father = ""
        if entry is None:
            how = bio[2] if bio else "backfilled"
            line = f"child\t{v.slot}\t{who.name}\t{v.sex}\t{tree[0]}\t{mother}\t{father}\tbackfilled"
            evidence = [f"The save has {who.describe()} as a child of generation {tree[0]}; the Parents file has no "
                        "entry for them."]
            if how == "adopted":
                evidence.append("The save names no parents for them (adopted): the entry names none.")
            else:
                evidence.append(f"Mother: {mother} (the save's record of {who.name}).")
                if birth is not None and father:
                    evidence.append(f"Father: {father} ({birth.where}).")
                elif father:
                    evidence.append(f"Father: {father} (the save's record of {who.name}).")
                else:
                    evidence.append("Father: left empty. The save does not keep a natural father's name and no "
                                    "Birth record names him, so none is guessed.")
            repair = Repair(f"parents|{who.key}", f"Add {who.name}'s mother and father to the Parents file",
                            "append_parents", {"lines": [line]}, evidence)
            out.append(Finding("WRONG", sec, f"{who.name}'s parents are not in the Parents file.", repair))
            continue
        if bio and bio[2] != "adopted" and mother and entry.mother != mother:
            fix = Repair(f"parents-mother|{who.key}", f"Record {who.name}'s mother as {mother} in the Parents file "
                         "(a newer entry; the old one is kept)", "append_parents",
                         {"lines": [f"child\t{v.slot}\t{who.name}\t{v.sex}\t{entry.generation}\t{mother}\t"
                                    f"{entry.father}\trepaired"]})
            q = _question(f"mother|{who.key}|{entry.mother}|{mother}",
                          f"Who is {who.name}'s mother: {mother} (the save) or {entry.mother or '(nobody)'} (the "
                          "Parents file)?",
                          {f"{mother} (the save is right)": fix, f"{entry.mother or '(nobody)'} (the file is right)": None},
                          [f"The save's record of {who.describe()} names {mother} as the mother; the Parents file "
                           f"(line {entry.line}) names {entry.mother or 'nobody'}."])
            out.append(Finding("ASK", sec, f"{who.name}'s mother is not the same in the save and the Parents file.",
                               question=q))
            continue
        if birth is not None and (birth.get("Father") or "") not in ("", "(unknown)") \
                and entry.father != birth.get("Father"):
            bf = birth.get("Father")
            fix = Repair(f"parents-father|{who.key}", f"Record {who.name}'s father as {bf} in the Parents file "
                         "(a newer entry; the old one is kept)", "append_parents",
                         {"lines": [f"child\t{v.slot}\t{who.name}\t{v.sex}\t{entry.generation}\t{entry.mother}\t"
                                    f"{bf}\trepaired"]})
            q = _question(f"father|{who.key}|{entry.father}|{bf}",
                          f"Who is {who.name}'s father: {bf} ({birth.kind} {birth.number}) or "
                          f"{entry.father or '(nobody)'} (the Parents file)?",
                          {f"{bf} (the Birth record is right)": fix,
                           f"{entry.father or '(nobody)'} (the file is right)": None},
                          [f"{birth.where} names {bf} as the father; the Parents file (line {entry.line}) names "
                           f"{entry.father or 'nobody'}."])
            out.append(Finding("ASK", sec, f"{who.name}'s father is not the same in the Births log and the Parents "
                               "file.", question=q))
            continue
        if birth is not None and mother and (birth.get("Mother") or "") != mother:
            out.append(Finding("NOTE", sec, f"{birth.where} names {birth.get('Mother')} as {who.name}'s mother; the "
                               f"save and the Parents file name {mother}. The Births log is kept as written."))
    if checked and not any(f.section == sec and f.verdict != "OK" for f in out):
        out.append(Finding("OK", sec, f"The parents of all {checked} children in the house agree."))


def _find_villager(save: vs.VF1Save, who: Who, min_units: int | None = None):
    for v in save.villagers:
        if v.name and who_of(v).same(who) and (min_units is None or v.age_units >= min_units):
            yield v


def _death_history_lines(family: Family, number: int) -> list[HistoryLine]:
    return [h for h in family.history if h.text.startswith(f"Death {number}: ")]


def _removal(rec: Record, family: Family, reason: str, history_prefix: str) -> dict:
    lines = [h for h in family.history if h.text.startswith(f"{history_prefix} {rec.number}: ")]
    return {"records": [{"path": str(rec.file.path), "start": rec.start, "end": rec.end, "text": rec.text}],
            "history": [{"path": str(h.file.path), "index": h.index, "raw": h.raw} for h in lines],
            "reason": reason}


def _check_deaths(family: Family, out: list[Finding]) -> None:
    sec = "Deaths"
    save = family.save
    deaths = family.deaths()
    for rec in deaths:
        who = rec.who()
        age = _int(rec.get("Age at death"))
        alive = [v for v in _find_villager(save, who, None if age is None else age * vs.AGE_UNITS_PER_YEAR)
                 if v.present and v.health > 0]
        if not alive:
            continue
        v = alive[0]
        remove = Repair(f"false-death|{who.key}|{age}", f"Remove {rec.kind} {rec.number} ({who.name}) and its "
                        "Family History line", "remove_record",
                        _removal(rec, family, f"{who.name} is alive in the save: the death did not happen", "Death"))
        q = _question(f"alive|{who.key}|{age}|{rec.get('Cause of death')}",
                      f"{rec.where} says {who.name} died at {age}, but the save has them alive. Did they die?",
                      {"No: remove the Death record (it is false)": remove,
                       "Yes: they died and were brought back (keep it)": None},
                      [f"The save has {who.describe()}, age {years(v.age_units)}, health {v.health}, in the house."])
        out.append(Finding("ASK", sec, f"{who.name} has a Death record but is alive in the save.", question=q))
    # Dead in the save, gone from the house, with no Death record.
    previous = _previous_rosters(family)
    for v in save.villagers:
        if not v.name or v.present or v.health > 0:
            continue
        who = who_of(v)
        if any(r.who().same(who) for r in deaths):
            continue
        seen = [label for label, people in previous for p, units in people
                if p.same(who) and units <= v.age_units]
        if not seen:
            continue
        repair = Repair(f"missing-death|{who.key}|{v.age_units}", f"Add a Death record for {who.name} "
                        f"({sex_word(v.sex)}, {years(v.age_units)}, {cause_word(v.death_cause)}), marked backfilled",
                        "add_death", {"slot": v.slot},
                        [f"The save's record of {who.describe()} is dead (health {v.health}, cause "
                         f"{cause_word(v.death_cause)}) and no longer in the house.",
                         f"Alive in: {', '.join(dict.fromkeys(seen))}.", "No Death record names them."])
        out.append(Finding("WRONG", sec, f"{who.name} died but there is no Death record.", repair))
    for v in save.household():
        if v.health <= 0 and not any(r.who().same(who_of(v)) for r in deaths):
            out.append(Finding("NOTE", sec, f"{who_of(v).name} has died and the body is still in the house; Family "
                               "Logs writes the Death record when the body is taken away."))
    if not any(f.section == sec for f in out):
        out.append(Finding("OK", sec, f"All {len(deaths)} Death record(s) agree with the save."))


def _check_duplicates(family: Family, out: list[Finding]) -> None:
    sec = "Records logged twice"
    groups: dict[tuple, list[Record]] = {}
    for rec in family.deaths():
        groups.setdefault(("Death", rec.body), []).append(rec)
    for rec in family.births():
        groups.setdefault(("Birth", rec.body), []).append(rec)
    for (kind, _body), recs in groups.items():
        if len(recs) < 2:
            continue
        first = recs[0]
        who = first.who() if kind == "Death" else first.who("Child")
        for later in recs[1:]:
            remove = Repair(f"duplicate-{kind.lower()}|{who.key}|{hash_body(first.body)}|{later.number}",
                            f"Remove {later.kind} {later.number} (the same as {first.kind} {first.number}) and its "
                            "Family History line", "remove_record",
                            _removal(later, family, f"the same {kind.lower()} as {first.kind} {first.number}, "
                                     "logged twice", kind),
                            [f"{first.where} and {later.where} are the same, line for line."])
            if kind == "Death":
                out.append(Finding("WRONG", sec, f"{who.name}'s death is logged twice ({first.kind} {first.number} "
                                   f"and {later.kind} {later.number}).", remove))
            else:
                q = _question(f"duplicate-birth|{who.key}|{hash_body(first.body)}|{recs.index(later)}",
                              f"{first.kind} {first.number} and {later.kind} {later.number} are the same, line for "
                              f"line. Were there two babies called {who.name} with the same mother, head and body?",
                              {f"No: remove {later.kind} {later.number} (logged twice)": remove,
                               "Yes: two babies (keep both)": None})
                out.append(Finding("ASK", sec, f"{who.name}'s birth may be logged twice.", question=q))
    # The first load's backfill, written twice.
    expected: dict[str, int] = {}
    for line in backfill_lines(family.save):
        expected[line] = expected.get(line, 0) + 1
    seen: dict[str, list[HistoryLine]] = {}
    for h in family.history:
        if h.backfilled:
            seen.setdefault(h.text, []).append(h)
    for text, hs in seen.items():
        allowed = max(1, expected.get(text, 0))
        if len(hs) <= allowed:
            continue
        extra = hs[allowed:]
        repair = Repair(f"duplicate-backfill|{text}|{len(hs)}", f"Remove {len(extra)} repeated Family History "
                        f"line(s): {BACKFILLED}{text}", "remove_history",
                        {"history": [{"path": str(h.file.path), "index": h.index, "raw": h.raw} for h in extra],
                         "reason": "the first load's backfill written more than once"},
                        [f"The line is in the Family History {len(hs)} times; the Family Tree in the save gives it "
                         f"{expected.get(text, 0)} time(s)."])
        out.append(Finding("WRONG", sec, f"A backfilled Family History line is repeated: {text}", repair))
    if not any(f.section == sec for f in out):
        out.append(Finding("OK", sec, "No Birth, Death or backfilled Family History record is logged twice."))


def hash_body(body: tuple[str, ...]) -> str:
    return hashlib.sha1("\n".join(body).encode("latin-1", "replace")).hexdigest()[:12]


def _previous_rosters(family: Family) -> list[tuple[str, list[tuple[Who, int]]]]:
    """Who was alive in the family before the save: the Family Members at Last Save file and the game's
    older copies of the save. Each person with their age then (age units)."""
    out = []
    if family.members is not None:
        people = [(m.who, m.age) for m in family.members.members if m.present and m.health > 0]
        out.append(("the Family Members at Last Save file", people))
    for label, other in family.older:
        out.append((label, [(who_of(v), v.age_units) for v in other.household() if v.health > 0]))
    return out


def _is_family_member(family: Family, who: Who) -> bool:
    """In some generation of the Family Tree, or named by the logs as having joined: a member, not a passing
    marriage or adoption candidate."""
    for save in [family.save] + [other for _label, other in family.older]:
        for rec in save.family_records:
            for p in [rec.parent1, rec.parent2] + list(rec.children):
                if p.used and log_name(p.name) == who.name and p.sex == who.sex and p.head == who.head:
                    return True
    return _mentioned(family, who)


def _left_by_event(family: Family, who: Who) -> Record | None:
    for e in family.events():
        kind = e.get("Event")
        if kind == "Evict Family" and who.name in [n.strip() for n in (e.get("Family members") or "").split(",")]:
            return e
        if kind == "Divorce Spouse" and e.who().same(who):
            return e
    return None


def _check_left(family: Family, out: list[Finding]) -> None:
    sec = "Family members who left"
    save = family.save
    rosters = _previous_rosters(family)
    if not rosters:
        out.append(Finding("UNCHECKED", sec, "There is no earlier list of the family to compare with (the Family "
                           "Members at Last Save file is written at each save; the game's older copies of the save "
                           "hold another family or none)."))
        return
    done: set[str] = set()
    newer_generation = any(label.startswith("the Family Members") and family.members.generations < save.generation
                           for label, _p in rosters) or any(o.generation < save.generation for _l, o in family.older)
    for label, people in rosters:
        for who, units in people:
            if who.key in done:
                continue
            here = list(_find_villager(save, who, units))
            if any(v.present for v in here) or any(v.health <= 0 for v in here):
                continue              # still in the house, or died (the Deaths check covers the record)
            if not _is_family_member(family, who):
                done.add(who.key)
                out.append(Finding("NOTE", sec, f"{who.describe()} was in {label} but is not in the save. They are "
                                   "in no Family Tree generation and no log: most likely a marriage or adoption "
                                   "candidate the game sent away."))
                continue
            done.add(who.key)
            if any(r.who().same(who) for r in family.deaths()):
                continue
            event = _left_by_event(family, who)
            if event is not None:
                continue
            if any(r.who().same(who) for r in family.unaccounted()):
                continue
            repair = Repair(f"unaccounted|{who.key}|{units}", f"Add an Unaccounted record for {who.name} "
                            f"({sex_word(who.sex)}, {years(units)}) and a Family History line", "add_unaccounted",
                            {"who": [who.name, who.sex, who.head, who.body], "units": units, "seen": label},
                            [f"{label} has {who.describe()}, age {years(units)}, alive.",
                             "The save does not have them, and no Death, Evict Family, Divorce Spouse or Unaccounted "
                             "record explains it."])
            text = f"{who.name} is gone from the save with no record of how."
            if newer_generation:
                q = _question(f"unaccounted|{who.key}|{units}",
                              f"{who.name} is gone with no record of how, and a new generation began since. Record "
                              "them as Unaccounted?",
                              {"Yes: add an Unaccounted record": repair,
                               "No: the new generation explains it (leave the logs as they are)": None},
                              repair.evidence)
                out.append(Finding("ASK", sec, text, question=q))
            else:
                out.append(Finding("WRONG", sec, text, repair))
    if not any(f.section == sec for f in out):
        out.append(Finding("OK", sec, "Everyone in the family at the last save is still in the save, or a record "
                           "says how they left."))


def _check_statistics(family: Family, out: list[Finding]) -> None:
    sec = "Family Statistics and Population"
    save, slot = family.save, family.slot
    counters = family.counters
    unreadable = counters is None and any("counters" in p for p in family.problems)
    births, deaths = len(family.births()), len(family.deaths())
    game_babies = max(0, save.stats.babies_born - len(save.unborn()))
    if counters is None and not unreadable:
        if family.marker:
            tree_deaths = sum(1 for rec in save.family_records for p in [rec.parent1, rec.parent2] + list(rec.children)
                              if p.used and p.slot == -1)
            fix = Repair("counters-missing", f"Write the counters as the family's first check would: Babies Born "
                         f"{max(game_babies, births)}, Deaths {max(tree_deaths, deaths)}", "write_counters",
                         {"babies": max(game_babies, births), "deaths": max(tree_deaths, deaths)})
            q = _question(f"counters-missing|{game_babies}|{tree_deaths}",
                          "The Babies Born and Deaths counters are missing, so they start again from 0. Write them "
                          "from the save?", {f"Yes: Babies Born {max(game_babies, births)}, Deaths "
                                             f"{max(tree_deaths, deaths)}": fix, "No: leave them": None},
                          [f"The game counts {save.stats.babies_born} babies ({len(save.unborn())} not born yet); the "
                           f"Family Tree records {tree_deaths} death(s); the logs hold {births} Birth and {deaths} "
                           "Death record(s)."])
            out.append(Finding("ASK", sec, "The Family Statistics counters are missing.", question=q))
        counters = (0, 0)
    elif counters is not None:
        babies, dead = counters
        if babies < births:
            fix = Repair(f"counter-babies|{babies}|{births}", f"Set Babies Born to {max(births, game_babies)}",
                         "write_counters", {"babies": max(births, game_babies)})
            q = _question(f"counter-babies|{babies}|{births}",
                          f"Babies Born says {babies}, but {births} births are logged. Set it to "
                          f"{max(births, game_babies)}?", {f"Yes: set it to {max(births, game_babies)}": fix,
                                                          "No: leave it": None},
                          [f"The game itself counts {save.stats.babies_born} babies ({len(save.unborn())} not born "
                           "yet)."])
            out.append(Finding("ASK", sec, f"Babies Born ({babies}) is less than the births logged ({births}).",
                               question=q))
        elif babies > game_babies:
            fix = Repair(f"counter-babies-game|{babies}|{game_babies}", f"Set Babies Born to {max(game_babies, births)}",
                         "write_counters", {"babies": max(game_babies, births)})
            q = _question(f"counter-babies-game|{babies}|{game_babies}",
                          f"Babies Born says {babies}, more than the game itself counts ({game_babies} born). Set it "
                          f"to {max(game_babies, births)}?", {f"Yes: set it to {max(game_babies, births)}": fix,
                                                             "No: leave it": None})
            out.append(Finding("ASK", sec, f"Babies Born ({babies}) is more than the game counts ({game_babies}).",
                               question=q))
        elif babies < game_babies:
            out.append(Finding("NOTE", sec, f"Babies Born ({babies}) is less than the game's own count "
                               f"({game_babies}): babies lost before birth, or born while Family Logs was off."))
        if dead < deaths:
            fix = Repair(f"counter-deaths|{dead}|{deaths}", f"Set Deaths to {deaths}", "write_counters",
                         {"deaths": deaths})
            q = _question(f"counter-deaths|{dead}|{deaths}", f"Deaths says {dead}, but {deaths} deaths are logged. "
                          f"Set it to {deaths}?", {f"Yes: set it to {deaths}": fix, "No: leave it": None})
            out.append(Finding("ASK", sec, f"Deaths ({dead}) is less than the deaths logged ({deaths}).", question=q))
    page = read_page(family.folder, slot, STATISTICS)
    if page is None:
        out.append(Finding("WRONG", sec, "The Family Statistics page is missing.",
                           Repair("statistics-page", "Write the Family Statistics page from the save", "write_statistics")))
    else:
        want = {"Generations": str(save.generation), "Family Members": str(family_members_count(save)),
                "Oldest Family Member Ever": str(save.stats.oldest_years), "Money": f"${money_dollars(save)}",
                "Food": str(save.food)}
        if not unreadable:
            want.update({"Babies Born": str(counters[0]), "Deaths": str(counters[1])})
        wrong = [f"{k}: the page says {page.get(k, '(nothing)')}, the {'counters say' if k in ('Babies Born', 'Deaths') else 'save says'} {v}"
                 for k, v in want.items() if page.get(k) != v]
        if wrong:
            out.append(Finding("WRONG", sec, "The Family Statistics page does not add up with the save.",
                               Repair("statistics-page", "Rewrite the Family Statistics page from the save",
                                      "write_statistics", evidence=wrong)))
        else:
            out.append(Finding("OK", sec, "The Family Statistics page agrees with the save."))
    listed = page_members(family.folder, slot)
    here = [who_of(v) for v in save.household()]
    if listed is None:
        out.append(Finding("WRONG", sec, "The Family Population page is missing.",
                           Repair("population-page", "Write the Family Population page from the save", "write_population")))
    else:
        extra = [w for w in listed if not any(w.same(h) for h in here)]
        absent = [h for h in here if not any(h.same(w) for w in listed)]
        if extra or absent:
            evidence = ([f"On the page but not in the save: {w.describe()}" for w in extra]
                        + [f"In the save but not on the page: {w.describe()}" for w in absent])
            out.append(Finding("WRONG", sec, "The Family Population page does not list the family in the save.",
                               Repair("population-page", "Rewrite the Family Population page from the save",
                                      "write_population", evidence=evidence)))
        else:
            out.append(Finding("OK", sec, f"The Family Population page lists the {len(here)} people in the save."))


def check(folder: Path, slot: int) -> CheckResult:
    """Check Saves & Logs for one save slot. Only reads."""
    family = read_family(folder, slot)
    return _check_family(family)


def _check_family(family: Family) -> CheckResult:
    out: list[Finding] = []
    if _check_files(family, out):
        _check_members_logged(family, out)
        _check_parents(family, out)
        _check_deaths(family, out)
        _check_duplicates(family, out)
        _check_left(family, out)
        _check_statistics(family, out)
    result = CheckResult(family.folder, family.slot, log_name(family.save.family_name, FAMILY_NAME_MAX), out)
    kept = load_answers(family.folder, family.slot)
    for f in out:
        if f.question is not None:
            entry = kept.get(f.question.key)
            if entry is not None and entry.get("answer") in f.question.options:
                f.answered = entry["answer"]
                f.verdict = "NOTE"
    return result


# ---------------------------------------------------------------------------
# Answered questions (an answer is never asked again)
# ---------------------------------------------------------------------------

ANSWERS_TAG = "VF1LOGS ANSWERS 1"


def load_answers(folder: Path, slot: int) -> dict[str, dict]:
    """key -> {"key", "question", "options", "answer", "date"}; the latest of a key wins. A file that cannot
    be read keeps nothing (every question is asked)."""
    path = answers_path(folder, slot)
    try:
        lines = _read_text(path).splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != ANSWERS_TAG:
        return {}
    out = {}
    for line in lines[1:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("key"), str) and isinstance(entry.get("answer"), str):
            out[entry["key"]] = entry
    return out


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "wb") as handle:
        handle.write(text.encode("latin-1", "replace"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _store_answers(folder: Path, slot: int, entries: dict[str, dict]) -> None:
    body = [ANSWERS_TAG] + [json.dumps(e, ensure_ascii=True) for e in entries.values()]
    _write_atomic(answers_path(folder, slot), "\r\n".join(body) + "\r\n")


def dont_know(answer: str | None) -> bool:
    return not answer or answer.startswith("Don't know")


# ---------------------------------------------------------------------------
# Repair Saves & Logs
# ---------------------------------------------------------------------------

@dataclass
class RepairResult:
    lines: list[str]                 # what was done (also in the Repairs Made record)
    backup: object | None            # vf1_save_backup.BackupResult
    record: int | None               # the "Repair <n>" number
    skipped: list[str] = field(default_factory=list)


def _highest(files: list[LogFile], heading: str) -> int:
    best = 0
    for f in files:
        for line in f.lines:
            m = RECORD_HEAD.match(line.rstrip("\r\n"))
            if m and m.group(1) == heading:
                best = max(best, int(m.group(2)))
    return best


def _target_file(folder: Path, slot: int, kind: LogKind) -> Path:
    """The file the next line or record goes to: the newest, or the next once it is full (vf1logs.dll's rule)."""
    files = read_log(folder, slot, kind)
    if not files:
        return log_path(folder, slot, kind, 1)
    newest = files[-1]
    full = sum(1 for line in newest.lines if line.startswith(kind.roll)) >= kind.per
    return log_path(folder, slot, kind, newest.number + 1) if full else newest.path


class _Changes:
    """Every file changed by one repair: copied once before its first change, then written."""

    def __init__(self, folder: Path, slot: int, copies: Path):
        self.folder, self.slot, self.copies = folder, slot, copies
        self.copied: dict[Path, str | None] = {}

    def before(self, path: Path) -> None:
        if path in self.copied:
            return
        if path.is_file():
            dest = self.copies / path.relative_to(slot_root(self.folder, self.slot))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
            self.copied[path] = str(dest.relative_to(slot_root(self.folder, self.slot)))
        else:
            self.copied[path] = None

    def append(self, path: Path, text: str, header: str) -> None:
        self.before(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        start = "" if path.is_file() else header + "\r\n"
        with open(path, "ab") as handle:
            handle.write((start + text).encode("latin-1", "replace"))

    def write(self, path: Path, text: str) -> None:
        self.before(path)
        _write_atomic(path, text)


def _apply_removals(changes: _Changes, removals: list[dict], done: list[str], skipped: list[str]) -> None:
    """Take out records and history lines, each only if the file still holds exactly what was checked."""
    by_file: dict[str, list[tuple[int, int, list[str] | str, str]]] = {}
    for r in removals:
        for rec in r.get("records", []):
            by_file.setdefault(rec["path"], []).append((rec["start"], rec["end"], rec["text"], r["reason"]))
        for h in r.get("history", []):
            by_file.setdefault(h["path"], []).append((h["index"], h["index"] + 1, h["raw"], r["reason"]))
    for name, cuts in by_file.items():
        path = Path(name)
        lines = _lines(_read_text(path))
        ok = []
        unique = {s: (s, e, list(t) if isinstance(t, list) else [t], why) for s, e, t, why in cuts}
        for start, end, want, reason in sorted(unique.values(), key=lambda cut: cut[0], reverse=True):
            got = [line.rstrip("\r\n") for line in lines[start:end]]
            if got[:len(want)] != want:
                skipped.append(f"Not removed (the file changed since the check): {want[0]} in {path.name}")
                continue
            ok.append((start, end, want, reason))
        if not ok:
            continue
        for start, end, want, reason in ok:          # already from the bottom up
            del lines[start:end]
            done.append(f"Removed: {want[0]} -- from {path.name} -- reason: {reason}")
            done.extend(f"    | {line}" for line in want[1:])
        changes.write(path, "".join(lines))


def _death_record(family: Family, v: vs.Villager, number: int) -> tuple[str, str]:
    who = who_of(v)
    role = tree_role(family.save, v)
    body = [f"Death {number}", f"  Name: {who.name}", f"  Age at death: {years(v.age_units)}",
            f"  Sex: {sex_word(v.sex)}", f"  Cause of death: {cause_word(v.death_cause)}", f"  Head: {v.head}",
            f"  Body: {v.body}", f"  Family role: {role_text(role)}",
            "  Note: backfilled by Repair Saves & Logs from the save (the date and generation were not recorded)"]
    history = (f"{BACKFILLED}Death {number}: {who.name} ({sex_word(v.sex)}, {years(v.age_units)}) died: "
               f"{cause_word(v.death_cause)}")
    return "\r\n".join(body) + "\r\n\r\n", history + "\r\n"


def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M:%S")


def apply(folder: Path, slot: int, chosen: set[str], answers: dict[str, str] | None = None,
          answer_changes: dict[str, str] | None = None, cleared: set[str] | None = None,
          now: datetime | None = None, processes=None) -> RepairResult:
    """Make the chosen repairs (by Repair.key) and the answered questions' repairs (question key -> option).

    The game must be closed. The save folder is backed up first; each file is copied before its first change;
    one Repairs Made record lists everything. The check is run again here, so only what is still found is
    done, at the lines the files hold now. `answer_changes` / `cleared`: the Answered Questions list's edits
    (key -> new answer / keys taken out)."""
    folder = Path(folder)
    now = now or datetime.now()
    answers = dict(answers or {})
    answer_changes = dict(answer_changes or {})
    cleared = set(cleared or ())
    if save_backup.running_game_count(folder, processes):
        raise GameRunning(f"{save_backup.game_exe_name(folder)} is running. Quit the game first (from its own "
                          "menu), then repair: a running game writes its logs again when it saves. Nothing was changed.")
    family = read_family(folder, slot)
    result = _check_family(family)
    kept = load_answers(folder, slot)
    # The kept answers (the questions not asked again), with the list's changes, then this time's answers.
    for key, new in answer_changes.items():
        if key in kept and not dont_know(new):
            answers.setdefault(key, new)
    for f in result.findings:
        q = f.question
        if q is not None and f.answered is not None and q.key not in cleared:
            answers.setdefault(q.key, f.answered)
    todo: list[Repair] = [r for r in result.repairs() if r.key in chosen]
    gone = sorted(set(chosen) - {r.key for r in todo})
    answered_lines: list[str] = []
    new_answers: dict[str, dict] = {}
    for f in result.findings:
        q = f.question
        if q is None:
            continue
        answer = answers.get(q.key)
        if dont_know(answer) or answer not in q.options:
            continue
        if q.repairs.get(answer) is not None:
            todo.append(q.repairs[answer])
        old = kept.get(q.key)
        if old is None or old.get("answer") != answer:
            answered_lines.append(f"Answered: {q.text} -- {answer}" if old is None
                                  else f"Answer changed: {q.text} -- {answer} (was: {old.get('answer')})")
            new_answers[q.key] = {"key": q.key, "question": q.text, "options": q.options, "answer": answer,
                                  "date": _stamp(now)}
    list_lines = []
    for key in cleared:
        if key in kept:
            list_lines.append(f"Answer cleared (asked again): {kept[key].get('question')} -- was: {kept[key].get('answer')}")
    for key, new in answer_changes.items():
        if key in kept and key not in new_answers and not dont_know(new) and new != kept[key].get("answer") \
                and new in kept[key].get("options", []):
            list_lines.append(f"Answer changed: {kept[key].get('question')} -- {new} (was: {kept[key].get('answer')})")
            new_answers[key] = {**kept[key], "answer": new, "date": _stamp(now)}
    if not todo and not new_answers and not list_lines:
        return RepairResult([], None, None, [f"No longer found, so not done: {key.split('|', 1)[0]}" for key in gone])
    try:
        backup = save_backup.copy_save_folder(folder, now, suffix=BEFORE_REPAIR)
    except save_backup.BackupError as exc:
        raise LogToolError(f"The save folder could not be backed up, so nothing was repaired: {exc}") from exc
    repairs_files = family.logs[REPAIRS.sub]
    number = _highest(repairs_files, "Repair") + 1
    copies = slot_root(folder, slot) / COPIES_FOLDER / f"Repair {number} {now.strftime('%Y-%m-%d %H-%M-%S')}"
    changes = _Changes(folder, slot, copies)
    header = header_line(family.save, slot)
    done: list[str] = []
    skipped: list[str] = [f"No longer found, so not done: {key.split('|', 1)[0]}" for key in gone]
    seen_keys: set[str] = set()
    unique = []
    for r in todo:
        if r.key not in seen_keys:
            seen_keys.add(r.key)
            unique.append(r)
    _apply_removals(changes, [r.data for r in unique if r.action in ("remove_record", "remove_history")], done, skipped)
    history_add: list[str] = []
    parents_add: list[str] = []
    counters = family.counters
    for r in unique:
        if r.action == "create_log":
            kind = next(k for k in DLL_LOGS if k.sub == r.data["sub"])
            path = log_path(folder, slot, kind, 1)
            if not path.exists():
                changes.write(path, header + "\r\n")
                done.append(f"Created: {path.relative_to(slot_root(folder, slot))}")
        elif r.action == "append_history":
            history_add += r.data["lines"]
        elif r.action == "append_parents":
            parents_add += r.data["lines"]
        elif r.action == "add_death":
            v = family.save.villagers[r.data["slot"]]
            files = read_log(folder, slot, DEATHS)
            n = _highest(files, "Death") + 1
            record, line = _death_record(family, v, n)
            changes.append(_target_file(folder, slot, DEATHS), record, header)
            history_add.append(line.rstrip("\r\n"))
            done.append(f"Added: Death {n} ({who_of(v).name}), marked backfilled -- {r.evidence[0]}")
        elif r.action == "add_unaccounted":
            name, sex, head, body = r.data["who"]
            files = read_log(folder, slot, UNACCOUNTED)
            n = _highest(files, "Unaccounted") + 1
            text = "\r\n".join([f"Unaccounted {n}", f"  Name: {name}", f"  Age when last seen: {years(r.data['units'])}",
                                f"  Sex: {sex_word(sex)}", f"  Head: {head}", f"  Body: {body}",
                                f"  Last seen: {r.data['seen']}", f"  Generation now: {family.save.generation}",
                                "  Found by: Repair Saves & Logs (no record says how they left)"]) + "\r\n\r\n"
            changes.append(_target_file(folder, slot, UNACCOUNTED), text, header)
            history_add.append(f"[{_stamp(now)}] Unaccounted {n}: {name} ({sex_word(sex)}, {years(r.data['units'])}) is "
                               "gone with no record of how")
            done.append(f"Added: Unaccounted {n} ({name}) -- {r.evidence[0]}")
        elif r.action == "write_counters":
            base = counters or (0, 0)
            counters = (r.data.get("babies", base[0]), r.data.get("deaths", base[1]))
            changes.write(counters_path(folder, slot), counters_text(*counters))
            done.append(f"Counters set: Babies Born {counters[0]}, Deaths {counters[1]} (were "
                        + (f"{base[0]} and {base[1]})" if family.counters is not None else "missing)"))
    if history_add:
        path = _target_file(folder, slot, HISTORY)
        changes.append(path, "".join(line + "\r\n" for line in history_add), header)
        done.extend(f"Added to the Family History: {line}" for line in history_add
                    if not line.startswith(f"{BACKFILLED}Death ") and "] Unaccounted " not in line)
    if parents_add:
        path = parents_path(folder, slot)
        start = "" if path.is_file() else "VF1LOGS PARENTS 1\r\n"
        changes.before(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as handle:
            handle.write((start + "".join(line + "\r\n" for line in parents_add)).encode("latin-1", "replace"))
        done.extend("Added to the Parents file: " + " / ".join(x for x in line.split("\t")[2:3] + line.split("\t")[5:8])
                    for line in parents_add)
    if any(r.action in ("write_statistics", "write_counters") for r in unique):
        changes.write(page_path(folder, slot, STATISTICS), statistics_text(family.save, slot, counters))
        done.append("Rewritten from the save: the Family Statistics page")
    if any(r.action == "write_population" for r in unique):
        changes.write(page_path(folder, slot, POPULATION), population_text(family.save, slot))
        done.append("Rewritten from the save: the Family Population page")
    if new_answers or cleared:
        entries = {k: v for k, v in kept.items() if k not in cleared}
        entries.update(new_answers)
        changes.write(answers_path(folder, slot), "\r\n".join([ANSWERS_TAG] + [json.dumps(e, ensure_ascii=True)
                                                                               for e in entries.values()]) + "\r\n")
    lines = done + answered_lines + list_lines
    # The Repairs Made record (the Virtual Villagers patcher's shape), then the reconciliation report.
    record = [f"Repair {number}", f"  Date: {_stamp(now)}",
              "  Checked: every Family Log and data file of this save slot against the save (Check Saves & Logs)"]
    record += [f"  {line}" for line in lines]
    record += [f"  Not done: {s}" for s in skipped]
    record += [f"  File: {p.relative_to(slot_root(folder, slot))} -- copy kept: {c}" if c else
               f"  File: {p.relative_to(slot_root(folder, slot))} -- new" for p, c in changes.copied.items()]
    record.append(f"  Backup: {Path(backup.backup_folder).name}")
    target = _target_file(folder, slot, REPAIRS)
    last_header = None
    if target.is_file():
        heads = [x.rstrip("\r\n") for x in _lines(_read_text(target)) if x.startswith("Family: ")]
        last_header = heads[-1] if heads else None
    text = ("" if last_header == header or not target.is_file() else header + "\r\n") + "\r\n".join(record) + "\r\n\r\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    start = "" if target.is_file() else header + "\r\n"
    with open(target, "ab") as handle:
        handle.write((start + text).encode("latin-1", "replace"))
    try:
        _write_atomic(report_path(folder, slot), reconciliation_text(result, now, number))
    except OSError:
        pass                          # only the report: the next repair writes it again
    return RepairResult(lines, backup, number, skipped)


def reconciliation_text(result: CheckResult, now: datetime, number: int) -> str:
    head = [f"Family: {result.family_name or '(no name)'} (Save {result.slot})",
            f"Checked by Repair Saves & Logs (Repair {number}) on {_stamp(now)}, before the repair.", result.summary, ""]
    return "\r\n".join(head + result.text.splitlines()) + "\r\n"


# ---------------------------------------------------------------------------
# The save slots of a folder (for the window's list)
# ---------------------------------------------------------------------------

@dataclass
class SlotInfo:
    slot: int
    name: str | None                 # the family name; None: no family in this slot
    generation: int = 0

    @property
    def label(self) -> str:
        if self.name is None:
            return f"Save {self.slot}: (no family)"
        return f"Save {self.slot}: {self.name or '(no name)'} (generation {self.generation})"


def read_slots(folder: Path) -> list[SlotInfo]:
    out = []
    for slot in range(1, 6):
        try:
            save = vs.read_save(save_path(folder, slot))
        except (OSError, vs.SaveFormatError, ValueError):
            out.append(SlotInfo(slot, None))
            continue
        if save.generation == 0 and not any(v.present for v in save.villagers):
            out.append(SlotInfo(slot, None))
            continue
        out.append(SlotInfo(slot, log_name(save.family_name, FAMILY_NAME_MAX), save.generation))
    return out


def main(argv: list[str] | None = None) -> int:
    """python vf1_log_tools.py <save folder> <slot>: print Check Saves & Logs' report (reads only)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or not args[1].isdigit():
        print(main.__doc__)
        return 2
    try:
        result = check(Path(args[0]), int(args[1]))
    except LogToolError as exc:
        print(exc)
        return 1
    print(result.text)
    print(result.summary)
    return 1 if result.wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
