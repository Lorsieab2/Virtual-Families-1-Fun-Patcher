"""The Family Tree Maker's family: who descends from whom in a Virtual Families 1 save, each family member's
generation, and what the records say about them.

A port of the Virtual Villagers Fun Patcher's genealogy (src/vv_genealogy.py): the same Person and Village
model, so the Family Tree Maker's renderer and editor (vf1_family_tree, vf1_family_tree_window) work on it
unchanged; the data comes from Virtual Families 1's own records instead.  Read only: nothing here writes a file.

Where the family comes from (docs/vf1-save-format.md, docs/UP_TO_28_CHILDREN.md):

* the save's own Family Tree (CFamilyTree, VERIFIED): one record per generation, each with the two parents
  (parent 1 the heir or founder, parent 2 the one who married in) and up to six children in the order they
  joined; record g+1's parent 1 is child number `parent_child_index` of record g (-1: not a child of the
  previous generation -- the founder, or a person adopted with Adopt New Person).  A slot of -1 is a death
  reported to the tree (ReportDeath).  The other slots of older records are stale: a person is matched to a
  villager record only as the game itself does (slot, sex and head, FindPeepRecord) and by name;
* the save's villager records, for the people the tree's slots still point at: age, health, cause of death,
  left home, pregnancy, likes and dislikes;
* the Up to 28 Children sidecar (Virtual Families 1 Patcher Data\\Children\\<save file>.dat), children 7 to 28
  of the current generation, used only when its hash matches the save file;
* when the Family History patch wrote one, the slot's Family History log (vf1_family_history): the spouses,
  deaths, births and events the save forgets;
* the Family Tree Maker's own tree file for the save (vf1_tree_memory), when the tree is opened to remember.

What no record says is left unknown and labelled as such (Person.unknowns), never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import vf1_save
import vf1_text

UNITS_PER_YEAR = vf1_save.AGE_UNITS_PER_YEAR
GAME = 1                                  # the renderer's game number (one head sheet pair, SHEETS[1])
GAME_TITLE = "Virtual Families 1"

PATCHER_FOLDER = "Virtual Families 1 Patcher"                 # the patcher's folder for each save: ...\Save <N>
CHILDREN_FOLDER = vf1_save.PATCHER_DATA + "\\Children"        # vf1kids.cpp SidecarPath

SEX_WORDS = {0: "Male", 1: "Female"}      # bio+4: 0 male, 1 female (VERIFIED)


class GenealogyError(Exception):
    """The family could not be read; the message says why."""


Key = tuple  # (name, head, body)


@dataclass
class Person:
    id: int
    name: str
    head: int | None
    body: int | None
    sex: str | None = None              # "Male" / "Female"
    age: int | None = None              # age units (twentieths of a year): now, or at death
    alive: bool = False
    gone: str = ""                      # "died", "left" (no longer in the house) -- or "" (alive / unknown)
    father: int | None = None
    mother: int | None = None
    litter: int | None = None           # babies born together share one number
    expecting: bool = False             # a living mother-to-be
    runner: bool = False                # likes running (the Family Tree's likes words, is_runner)
    likes: list[str] | None = None      # the words they like, as the Family Tree keeps them; None = not known
    dislikes: list[str] | None = None
    arrived: bool = False               # joined the family from outside: married in or adopted
    how: str = ""                       # "Founder", "Married in", "Adopted", "Adopt New Person", "Spawn Child"
    first_seen: str | None = None
    upcoming: bool = False              # a baby on the way (conceived, not born yet)
    birth_record: int | None = None     # its place in the family, record by record (birth order)
    generation: int = 1
    number: int | None = None           # its place in the whole tree, oldest first (number_people)
    old_looks: list[tuple[int, int]] = field(default_factory=list)
    former: list[str] = field(default_factory=list)     # names they had before (a rename the tree file saw)
    statuses: list[str] = field(default_factory=list)   # (the renderer's automatic marks: none in Virtual Families)
    # Virtual Families 1
    seat: str = ""                      # where the save's Family Tree holds them: "g2.p1", "g2.p2", "g2.c3", "house.7"
    event: str = ""                     # "Event names": the event that brought them in ("Married in", "Spawn Child"...)
    left_home: bool = False             # alive and left home (the save's left-home flag, VERIFIED)
    adopted: bool = False               # joined as an adopted child (no parents in their bio)
    heir: bool = False                  # inherited the house: parent 1 of a later generation
    cause: str = ""                     # the cause of death, from a body still in the house (wording unconfirmed)
    career: int | None = None           # the save's career id (CVillagerSkills +0; the Family Tree's +0x30)
    career_level: int | None = None     # 0 Beginner .. 7 Master (CVillagerSkills +4), from a villager record only
    slot: int | None = None             # the villager record they are matched to, if any
    divorced: bool = False              # left with the patcher's Divorce Spouse (Family History log, or tree memory)
    remarried: bool = False             # the head of the family married again (Family History log, or tree memory)
    spouse_number: int | None = None    # their place in the order of their partner's marriages (1, 2..), when proved
    partner: int | None = None          # the one they married, when no child links them (a spouse the save lost)
    event_title: str = ""               # the Random Event that brought them in or took them away ("Popup Event: ...")
    left_how: str = ""                  # how they left home, as the Family History log says
    unknowns: list[str] = field(default_factory=list)   # what the records do not say (shown, never guessed)
    sources: list[str] = field(default_factory=list)    # where each fact came from
    # Living namesakes (two living family members of one name, head and body): 1 the oldest, 2 the next...; 0
    # none.  What tells them apart for good (their seat in the save's Family Tree), and what their tree edits'
    # key adds to "name|head|body" while they have a living namesake (mark_namesakes, vf1_family_tree.entry_key).
    namesake_rank: int = 0
    marker: str = ""
    edit_suffix: str = ""

    @property
    def key(self) -> Key:
        return (self.name, self.head, self.body)

    @property
    def years(self) -> int | None:
        return None if self.age is None else self.age // UNITS_PER_YEAR

    def age_text(self) -> str:
        if self.age is None:
            return "age unknown"
        text = f"{self.years} years old"
        return f"died at {text}" if self.gone == "died" else text

    def order_key(self) -> tuple:
        """Oldest first: in the order the family's records hold them (generation by generation, each record's
        parents before its children, the children in the order they joined), then the older."""
        return (self.upcoming, (self.first_seen or "")[:16], self.birth_record if self.birth_record is not None else -1,
                -(self.age or 0), self.name)


# The Family Tree's automatic marks: Virtual Families 1 keeps no special titles.
STATUS_ORDER: tuple = ()
GAME_STATUSES: dict = {GAME: ()}


@dataclass
class Village:
    """The family (the name is the Virtual Villagers model's: the renderer and the editor use it)."""
    game: int
    slot: int
    tribe: str                          # the family name the player typed
    people: dict[int, Person]
    notes: list[str] = field(default_factory=list)
    snapshot_dates: list[str] = field(default_factory=list)
    base_generation: dict[int, int] = field(default_factory=dict)
    relooked: dict[Key, Key] = field(default_factory=dict)
    full_names: dict[Key, str] = field(default_factory=dict)
    rename_questions: list = field(default_factory=list)
    identity_questions: list = field(default_factory=list)
    generations: int = 0                # the save's Family Tree records
    couples: dict = field(default_factory=dict)          # generation -> its parents' ids (as the save holds them)
    history_events: list[str] = field(default_factory=list)  # the Family History log's e-mail and pop-up events
    sources: list[str] = field(default_factory=list)     # the files read

    def living(self) -> list[Person]:
        return [p for p in self.people.values() if p.alive]

    def known(self) -> list[Person]:
        """Every family member the records name (the babies on the way are not born yet)."""
        return [p for p in self.people.values() if not p.upcoming]

    def children_of(self, pid: int) -> list[Person]:
        return [p for p in self.people.values() if pid in (p.father, p.mother)]


def without_heathens(village: Village) -> Village:
    """(Virtual Villagers' "Hide unconverted Heathens": Virtual Families has none.)"""
    return village


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def save_path(folder: Path, slot: int) -> Path:
    return Path(folder) / f"{vf1_save.SAVE_PREFIX}{slot}.ldw"


def slot_root(folder: Path, slot: int) -> Path:
    """<save folder>\\Virtual Families 1 Patcher\\Save <N> (the patcher's own folder for the slot)."""
    return Path(folder) / PATCHER_FOLDER / f"Save {slot}"


def children_sidecar_path(folder: Path, slot: int) -> Path:
    return Path(folder) / CHILDREN_FOLDER / f"{vf1_save.SAVE_PREFIX}{slot}.ldw.dat"


# ---- the Up to 28 Children sidecar (vf1kids.cpp ReadSidecar) ----

KIDS_MAGIC = b"VF1KIDS\0"
KIDS_TAG = b"VF1V101\0"
KIDS_VERSION = 1
KIDS_HEADER = 52
KIDS_ENTRY = 64
KIDS_STATES = {1: "alive", 2: "dead", 3: "gone"}
_FNV_BASIS = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3


def fnv1a64(data: bytes) -> int:
    h = _FNV_BASIS
    for b in data:
        h = ((h ^ b) * _FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


@dataclass
class ExtraChild:
    slot: int
    sex: int
    state: str                          # "alive", "dead", "gone"
    head: int
    body: int
    age: int
    name: str


@dataclass
class ChildrenSidecar:
    save_hash: int
    save_size: int
    generations: int
    parent_slot: int
    parent_sex: int
    children: list[ExtraChild]


def read_children_sidecar(data: bytes) -> ChildrenSidecar | None:
    """The sidecar as vf1kids reads it; None for anything it would refuse (wrong tags, size or checksum)."""
    import struct
    if len(data) < KIDS_HEADER + 8 or data[:8] != KIDS_MAGIC or data[12:20] != KIDS_TAG:
        return None
    if struct.unpack_from("<I", data, 8)[0] != KIDS_VERSION or struct.unpack_from("<I", data, 20)[0] != len(data):
        return None
    count = struct.unpack_from("<I", data, 48)[0]
    if count > 28 or len(data) != KIDS_HEADER + count * KIDS_ENTRY + 8:
        return None
    if struct.unpack_from("<Q", data, len(data) - 8)[0] != fnv1a64(data[:-8]):
        return None
    save_hash, save_size, gens, pslot, psex = struct.unpack_from("<QIiii", data, 24)
    kids = []
    for i in range(count):
        at = KIDS_HEADER + i * KIDS_ENTRY
        slot, sex, state, head, body, age = struct.unpack_from("<6i", data, at)
        if not 0 <= slot < vf1_save.VILLAGER_SLOTS or state not in KIDS_STATES:
            return None
        name = vf1_text.decode(data[at + 24:at + 24 + 28])
        kids.append(ExtraChild(slot, sex, KIDS_STATES[state], head, body, age, name))
    return ChildrenSidecar(save_hash, save_size, gens, pslot, psex, kids)


def rekey_children_sidecar(data: bytes, saves) -> bytes | None:
    """``data`` (a Children file) re-matched to a save a tool rewrote, or None when it is left as it is.

    ``saves`` is (bytes before, bytes after) for each save the tool rewrote. vf1kids takes the children from a
    Children file only when it names the FNV-1a 64 hash and size of the loaded save (vf1kids.cpp AfterLoad;
    otherwise it keeps only the extra children still at home), so a file that described one of those saves
    BEFORE the change is given the new bytes' hash and size and its own checksum again; nothing else in it
    changes. A file that is damaged, described none of them, or whose save did not change is left alone.
    """
    import struct
    sidecar = read_children_sidecar(data)
    if sidecar is None:
        return None
    for before, after in saves:
        if sidecar.save_size == len(before) and sidecar.save_hash == fnv1a64(before):
            if after == before:
                return None
            out = bytearray(data)
            struct.pack_into("<QI", out, 24, fnv1a64(after), len(after))
            struct.pack_into("<Q", out, len(out) - 8, fnv1a64(bytes(out[:-8])))
            rekeyed = bytes(out)
            check = read_children_sidecar(rekeyed)
            if check is None or check.save_hash != fnv1a64(after) or check.save_size != len(after):
                return None
            return rekeyed
    return None


def children_rekeys(folder: Path, slot: int, saves, prefix: str = vf1_save.SAVE_PREFIX) -> list[tuple[Path, bytes, bytes]]:
    """(path, bytes now, re-matched bytes) for each of ``slot``'s Children files (save numbers N, N+20, N+40:
    vf1kids also reads the N+20 file for save N) that described one of ``saves`` (see rekey_children_sidecar)
    before a tool rewrote it. Only this slot's files are looked at; nothing is written here. ``prefix`` is the
    save files' name before their number (vf1kids names a Children file after its save)."""
    saves = list(saves)
    out: list[tuple[Path, bytes, bytes]] = []
    for number in (slot, slot + 20, slot + 40):
        path = Path(folder) / CHILDREN_FOLDER / f"{prefix}{number}.ldw.dat"
        try:
            data = path.read_bytes()
        except OSError:
            continue
        rekeyed = rekey_children_sidecar(data, saves)
        if rekeyed is not None:
            out.append((path, data, rekeyed))
    return out


def make_children_sidecar(save_bytes: bytes, generations: int, parent_slot: int, parent_sex: int,
                          children: list[ExtraChild]) -> bytes:
    """A sidecar in vf1kids' format (for tests and synthetic families)."""
    import struct
    states = {v: k for k, v in KIDS_STATES.items()}
    size = KIDS_HEADER + len(children) * KIDS_ENTRY + 8
    out = bytearray(size)
    out[:8] = KIDS_MAGIC
    struct.pack_into("<I", out, 8, KIDS_VERSION)
    out[12:20] = KIDS_TAG
    struct.pack_into("<I", out, 20, size)
    struct.pack_into("<QIiiiI", out, 24, fnv1a64(save_bytes), len(save_bytes), generations, parent_slot, parent_sex,
                     len(children))
    for i, c in enumerate(children):
        at = KIDS_HEADER + i * KIDS_ENTRY
        struct.pack_into("<6i", out, at, c.slot, c.sex, states[c.state], c.head, c.body, c.age)
        name = vf1_text.encode(vf1_text.cut_to_bytes(c.name, 27))
        out[at + 24:at + 24 + len(name)] = name
    struct.pack_into("<Q", out, size - 8, fnv1a64(bytes(out[:-8])))
    return bytes(out)


# ---------------------------------------------------------------------------
# Reading the family
# ---------------------------------------------------------------------------

RUNNING = "running"                     # the likes word (the game's own, as the Family Tree records it)
NATURAL_BIRTH_FATHER = "Joey"           # Impregnate's father name for every natural birth (docs 2.4, bio +0x34)
LITTLE_VISITOR = "The Little Visitor"   # CEventTheLittleVisitor1/2 (0x418828 / 0x4188D8): the only stock AddOffspring
                                        # callers besides the babies (Impregnate 0x48665B / 0x486712 / 0x48677B)


def is_runner(likes: list[str] | None) -> bool:
    """Likes running: the word in the likes the save's Family Tree keeps for them (SPeepRecord +0x34, written by
    UpdatePeepRecord from the villager's own likes; VERIFIED).  Shared with Virtual Families 2 (same words)."""
    return any(w.strip().lower() == RUNNING for w in likes or [])


def _words(text: str) -> list[str] | None:
    words = [w.strip() for w in re.split(r"[,\n]", text or "") if w.strip()]
    return words or None


def _peep_person(pid: int, peep: vf1_save.PeepRecord) -> Person:
    p = Person(pid, peep.name, peep.head, peep.body, sex=SEX_WORDS.get(peep.sex))
    p.career = peep.career
    p.likes = _words(peep.likes_text)
    p.dislikes = _words(peep.dislikes_text)
    p.runner = is_runner(p.likes)
    return p


def _matching_villager(save: vf1_save.VF1Save, peep: vf1_save.PeepRecord) -> vf1_save.Villager | None:
    """The villager record a Family Tree entry is, if its slot still holds them: the slot, sex and head as the
    game's own FindPeepRecord matches them, and the name.  Older records' slots are stale (reused)."""
    return save.villager_for(peep)


def _dead_record(save: vf1_save.VF1Save, peep: vf1_save.PeepRecord) -> vf1_save.Villager | None:
    """A dead member's own villager record, when the save still holds it (a record is never cleared, only reused,
    docs 2.4): the one record with their name, sex, head and body and health 0.  None when there is not exactly
    one (reused, or two alike: never a guess)."""
    hits = [v for v in save.villagers if v.health <= 0 and v.name == peep.name and v.sex == peep.sex
            and v.head == peep.head and v.body == peep.body]
    return hits[0] if len(hits) == 1 else None


def cause_words(cause: int) -> str:
    word = vf1_save.DEATH_CAUSES_UNCONFIRMED.get(cause)
    # The save keeps the cause as a number; its words follow the game's string order only (docs 2.4).
    return f"{word} (the save's cause number {cause}; the wording is unconfirmed)" if word else ""


def _apply_villager(p: Person, v: vf1_save.Villager, unborn: set[int]) -> None:
    p.slot = v.slot
    p.age = v.age_units
    if v.career >= 0:
        p.career, p.career_level = v.career, v.career_level
    if v.slot in unborn and not v.present:
        p.upcoming = True
        p.alive = False
        return
    if v.present and v.health > 0:
        p.alive = True
        p.gone = ""
        p.left_home = v.left_home
        p.expecting = v.pregnant
    elif v.health <= 0:
        p.alive = False
        p.gone = "died"
        p.cause = p.cause or cause_words(v.death_cause)
    else:
        p.alive = False
        p.gone = "left"


def load_village(folder: Path, game: int = GAME, slot: int = 1, full_names: bool = True,
                 rename_answers: dict | None = None, identity_answers: dict | None = None,
                 save_file: Path | None = None, remember: bool = False) -> Village:
    """The slot's family: every person the save's Family Tree and the Children sidecar name, filled in from the
    Family History log when the Family History patch wrote one (vf1_family_history), and -- with `remember` -- from
    and into the Family Tree Maker's own tree file, which keeps every member it has seen in this save
    (vf1_tree_memory).  The save and the logs are only read.  `save_file` reads another file than
    Virtual Families<slot>.ldw (a backup copy)."""
    import vf1_family_history
    import vf1_tree_memory
    folder = Path(folder)
    path = Path(save_file) if save_file is not None else save_path(folder, slot)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GenealogyError(f"The save {path} could not be read: {exc}") from exc
    try:
        save = vf1_save.parse_save(data)
    except (vf1_save.SaveFormatError, ValueError, IndexError) as exc:
        raise GenealogyError(f"{path.name} is not a Virtual Families save the patcher can read: {exc}") from exc
    family = build_family(save, slot, data=data, sidecar=_sidecar(folder, slot, data))
    family.sources.insert(0, str(path))
    # One character limit for every name box: a name the save keeps as its short form is the whole name its Names
    # file keeps (vf1_names) -- before the tree file and the Family History log, which hold whole names.
    import vf1_names
    book = vf1_names.Book(folder)
    if any(book.slots.values()):
        family.tribe = book.full(slot, family.tribe)
        for p in family.people.values():
            p.name = book.full(slot, p.name)
            p.former = [book.full(slot, n) for n in p.former]
    if remember:
        vf1_tree_memory.remember(folder, slot, save, family)
    history = vf1_family_history.read(folder, slot)
    if history is not None:
        vf1_family_history.apply(family, history)
    finish(family)
    return family


def _sidecar(folder: Path, slot: int, data: bytes) -> ChildrenSidecar | None:
    path = children_sidecar_path(folder, slot)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return read_children_sidecar(raw)


def build_family(save: vf1_save.VF1Save, slot: int, data: bytes | None = None,
                 sidecar: ChildrenSidecar | None = None) -> Village:
    """The family from a parsed save (and, when given, the Children sidecar of that very save file)."""
    people: dict[int, Person] = {}
    notes: list[str] = []
    unborn = {s for s in save.pending_babies if 0 <= s < vf1_save.VILLAGER_SLOTS}
    order = 0
    couple_of: dict[int, list[int]] = {}           # generation -> its parents' ids
    by_seat: dict[str, int] = {}

    def new(peep: vf1_save.PeepRecord, seat: str) -> Person:
        nonlocal order
        pid = len(people)
        p = _peep_person(pid, peep)
        p.birth_record = order
        p.seat = seat
        order += 1
        people[pid] = p
        by_seat[seat] = pid
        return p

    def settle(p: Person, peep: vf1_save.PeepRecord) -> None:
        """Alive, dead or gone, from the tree's slot and the villager record (a later record of the same person,
        the heir's, is newer than their entry among the children)."""
        p.unknowns = [u for u in p.unknowns if not u.startswith("Not in the house now")]
        if peep.slot == -1:
            # ReportDeath 0x481CF0 sets the slot of a parent with children, or of a child, to -1 (the current
            # record only): a death.
            p.alive, p.gone = False, "died"
            p.sources.append("The Family Tree records the death (its slot is -1).")
            dead = _dead_record(save, peep)
            if dead is not None:
                p.age = dead.age_units
                p.cause = p.cause or cause_words(dead.death_cause)
            return
        v = _matching_villager(save, peep)
        if v is not None:
            _apply_villager(p, v, unborn)
            return
        p.alive, p.gone = False, "left"
        p.unknowns.append("Not in the house now: the save no longer holds them, and does not say whether they "
                          "died or moved away.")

    def bio_event(c: Person, peep: vf1_save.PeepRecord) -> None:
        """How a child of the current generation joined, from their own bio (only the living's records are
        current): no parents -- adopted (The Little Visitor, or the patcher's Adopt Outside Child); the couple's
        names instead of "Joey" -- the patcher's Spawn Child (vf1fun SpawnChild passes the parents' names)."""
        if c.slot is None or c.upcoming or not 0 <= peep.slot < vf1_save.VILLAGER_SLOTS:
            return
        v = save.villagers[peep.slot]
        if not v.parent1_name and not v.parent2_name:
            c.adopted, c.arrived, c.how = True, True, "Adopted"
            c.event = "Adopted"
            c.unknowns.append(f"Adopted: {LITTLE_VISITOR} event, or the patcher's Adopt Outside Child -- the save "
                              "does not say which.")
        elif v.parent1_name and v.parent1_name != NATURAL_BIRTH_FATHER:
            c.how = c.event = "Spawn Child"

    records = save.family_records
    for rec in records:
        g = rec.generation
        # Parent 1: the heir (a child of the generation before), or the founder / an Adopt New Person.
        p1 = None
        if rec.parent1.used:
            idx = rec.parent1.parent_child_index
            prev = by_seat.get(f"g{g - 1}.c{idx}") if g > 1 and idx >= 0 else None
            # ReportDeath 0x481D44 copies parent 2's whole record over a parent 1 who died with no children, and
            # parent 2's child index was never written (0): a founder's is -1, an heir's names their own place.
            # A renamed heir keeps their sex and head (a new name never makes two people of one).
            shifted = (g == 1 and idx == 0) or (prev is not None and people[prev].name != rec.parent1.name and (
                people[prev].sex != SEX_WORDS.get(rec.parent1.sex) or people[prev].head != rec.parent1.head))
            if prev is not None and not shifted:
                p1 = people[prev]
                p1.heir = True
                if p1.name != rec.parent1.name:
                    p1.former.append(p1.name)
                    p1.name = rec.parent1.name
                by_seat[f"g{g}.p1"] = p1.id
            else:
                p1 = new(rec.parent1, f"g{g}.p1")
                if shifted:
                    p1.arrived, p1.how, p1.event = True, "Married in", "Married in"
                    p1.unknowns.append("Married in: the one they married died with no children, and the game's Family "
                                       "Tree put them in that place (the save no longer names who that was).")
                elif g == 1:
                    p1.how = "Founder"
                elif idx >= 0:
                    # A child the previous record could not hold (Up to 28 Children: child 7 or later).
                    p1.heir = True
                    p1.father, p1.mother = _parents_by_sex(people, couple_of.get(g - 1, []))
                    p1.unknowns.append(f"Child number {idx + 1} of generation {g - 1}: the save's Family Tree "
                                       "keeps only six children, so they are known from this generation's record.")
                else:
                    # StartNextGeneration with no child index: vf1fun's Adopt New Person.
                    p1.arrived, p1.how, p1.event = True, "Adopt New Person", "Adopt New Person"
            fresh = _peep_person(-1, rec.parent1)
            p1.likes, p1.dislikes = fresh.likes or p1.likes, fresh.dislikes or p1.dislikes
            p1.runner = is_runner(p1.likes)
            settle(p1, rec.parent1)
        p2 = None
        if rec.parent2.used:
            p2 = new(rec.parent2, f"g{g}.p2")
            p2.arrived, p2.how, p2.event = True, "Married in", "Married in"
            settle(p2, rec.parent2)
        couple = [p.id for p in (p1, p2) if p is not None]
        couple_of[g] = couple
        for k, peep in enumerate(rec.children):
            if not peep.used:
                continue
            c = new(peep, f"g{g}.c{k}")
            c.father, c.mother = _parents_by_sex(people, couple)
            settle(c, peep)
            if g == len(records):
                bio_event(c, peep)
    generations = len(records)

    # Children 7 to 28 of the current generation (vf1kids), only from the sidecar of this very save file.
    if sidecar is not None and data is not None and generations:
        if sidecar.save_hash != fnv1a64(data) or sidecar.save_size != len(data):
            notes.append("The Up to 28 Children file belongs to another save file (an older or newer save), so "
                         "children 7 to 28 are not shown.")
        elif sidecar.generations != generations:
            notes.append("The Up to 28 Children file is for another generation, so it was not used.")
        else:
            couple = couple_of.get(generations, [])
            for k, extra in enumerate(sidecar.children, start=6):
                peep = vf1_save.PeepRecord(extra.name, True, extra.sex, extra.head, extra.body, extra.slot, 0, -1, "", "")
                c = new(peep, f"g{generations}.c{k}")
                c.father, c.mother = _parents_by_sex(people, couple)
                c.sources.append("Children 7 to 28: the Up to 28 Children file.")
                if extra.state == "alive":
                    v = _matching_villager(save, peep)
                    if v is not None:
                        _apply_villager(c, v, unborn)
                        bio_event(c, peep)
                    else:
                        c.alive = True
                        c.age = extra.age
                elif extra.state == "dead":
                    c.alive, c.gone, c.age = False, "died", extra.age
                else:
                    c.alive, c.gone, c.age = False, "left", extra.age

    # Anyone in the house the tree does not hold (alive, present): shown, with no family recorded.
    held = {p.slot for p in people.values() if p.slot is not None}
    for v in save.villagers:
        if v.present and v.health > 0 and v.slot not in held and v.name:
            peep = vf1_save.PeepRecord(v.name, True, v.sex, v.head, v.body, v.slot, 0, v.career, "", "")
            p = new(peep, f"house.{v.slot}")
            _apply_villager(p, v, unborn)
            p.unknowns.append("In the house, but the save's Family Tree does not record them, so their family is "
                              "not known.")

    # The babies of one pregnancy (theGameState +0x1B120..0x1B128, up to three, VERIFIED): twins or triplets on the way.
    coming = [q for q in people.values() if q.upcoming]
    if len(coming) > 1:
        for q in coming:
            q.litter = 1

    village = Village(GAME, slot, save.family_name, people, notes, generations=generations)
    village.couples = couple_of
    village.notes.append("The save keeps no history: births of twins and triplets, causes of death (beyond a dead "
                         "member's own record), birthdays, divorces and earlier marriages are not recorded in it.")
    return village


def finish(village: Village) -> None:
    """Each member's generation and number (after the Family History and the tree file added what they know)."""
    _generations(village)
    number_people(village)
    mark_namesakes(village)


def mark_namesakes(village: Village) -> None:
    """LIVING NAMESAKES (a port of the Virtual Villagers Fun Patcher v1.35.85): two living family members of one
    name, head and body are two people, each with their own edits on the tree.  The family itself never mixes
    them up -- each is their own seat in the save's Family Tree, and a child's parents are the couple of their
    generation's record, never a name -- so only the tree's edits need telling apart: by the seat (`marker`),
    which stays theirs as they age and as others die, and by the place by age only between two who share it."""
    groups: dict[Key, list[Person]] = {}
    for p in village.people.values():
        p.namesake_rank, p.marker, p.edit_suffix = 0, p.seat or "?", ""
        if p.alive and not p.upcoming:
            groups.setdefault(p.key, []).append(p)
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda q: (-(q.age or 0), q.order_key(), q.id))
        markers = [q.marker for q in members]
        for rank, q in enumerate(members, 1):
            q.namesake_rank = rank
            q.edit_suffix = f"|{q.marker}" + (f"|{rank}" if markers.count(q.marker) > 1 else "")


def _parents_by_sex(people: dict[int, Person], couple: list[int]) -> tuple[int | None, int | None]:
    """(father, mother) from a generation's two parents; a same-sex couple fills both in the tree's order (the order
    the tree holds them)."""
    father = mother = None
    for q in couple:
        if people[q].sex == "Female" and mother is None:
            mother = q
        elif people[q].sex == "Male" and father is None:
            father = q
        elif father is None:
            father = q
        elif mother is None:
            mother = q
    return father, mother


def seat_row(seat: str) -> int | None:
    """The tree row a Family Tree seat is drawn in: generation g's parents in row g, its children in row g + 1."""
    m = re.fullmatch(r"g(\d+)\.(p1(?:#\w+)?|p2(?:#\w+)?|c\d+)", seat or "")
    if not m:
        return None
    return int(m.group(1)) + (1 if m.group(2).startswith("c") else 0)


def _generations(village: Village) -> None:
    """Row g holds generation g's parents (the game's generation g); their children are in row g + 1, where
    the heir among them is generation g + 1's parent 1 and is joined by the one who married them."""
    people = village.people
    base: dict[int, int] = {}
    for pid, p in sorted(people.items(), key=lambda kv: kv[1].birth_record if kv[1].birth_record is not None else 0):
        row = seat_row(p.seat)
        if row is not None:
            base.setdefault(pid, row)
    # Anyone else: below the later of their parents, else beside their partner, else generation 1.
    for _round in range(4):
        for pid, p in people.items():
            if pid in base:
                continue
            parents = [q for q in (p.father, p.mother) if q is not None and q in base]
            if parents:
                base[pid] = 1 + max(base[q] for q in parents)
                continue
            partners = {k.father if k.mother == pid else k.mother for k in village.children_of(pid)} - {None}
            rows = [base[q] for q in partners if q in base]
            if rows:
                base[pid] = max(rows)
    for pid, p in people.items():
        p.generation = base.get(pid, 1)
    village.base_generation = {pid: p.generation for pid, p in people.items()}


# ---------------------------------------------------------------------------
# Numbering and names (the Virtual Villagers Family Tree Maker's, unchanged)
# ---------------------------------------------------------------------------

SORTS = {
    "appearance": "By appearance in the family",
    "age": "By age (oldest first)",
    "family": "By family (brothers and sisters together)",
    "name": "By name",
}


def number_people(village: Village, sort: str = "appearance") -> None:
    """Every family member's number: generation by generation, in the chosen order, never restarting.  A baby
    on the way has none yet, and comes last in its row."""
    n = 0
    people = village.people
    for g in sorted({p.generation for p in village.known()}):
        row = [p for p in village.known() if p.generation == g]
        if sort == "age":
            row.sort(key=lambda q: (-(q.age or 0), q.order_key()))
        elif sort == "name":
            row.sort(key=lambda q: (q.name.casefold(), q.order_key()))
        elif sort == "family":
            def family_key(q: Person) -> tuple:
                parents = sorted(people[r].number or 0 for r in (q.mother, q.father) if r is not None)
                return (tuple(parents) or (0,), q.order_key())
            row.sort(key=family_key)
        else:
            row.sort(key=lambda q: q.order_key())
        for p in row:
            n += 1
            p.number = n


def snapshot_dates(village: Village) -> list[str]:
    return list(village.snapshot_dates)


def is_arrival(p: Person, first_snapshot: str | None = None) -> bool:
    """Someone with no recorded parent who joined the family from outside: married in, adopted, or adopted
    with Adopt New Person."""
    if p.father is not None or p.mother is not None or p.upcoming:
        return False
    return bool(p.arrived and p.how and p.how != "Founder")


ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
         (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def roman(n: int) -> str:
    out = ""
    for value, letters in ROMAN:
        count, n = divmod(n, value)
        out += letters * count
    return out


NUMBER_ORDERS = {
    "oldest": "By age now, oldest first",
    "youngest": "By age now, youngest first",
    "appearance": "Oldest first (order of appearance)",
}


def duplicate_names(village: Village, order: str = "appearance", reserved: set[str] = frozenset(),
                    leave: set[int] = frozenset(), weight: dict[int, int] | None = None,
                    blocks: dict[int, list[str]] | None = None) -> dict[int, str]:
    """Each family member who shares a name with another, numbered ("Happi I", "Happi II"), the dead too, in
    the NUMBER_ORDERS order.  A number already carried is kept; a new namesake gets the next number never
    used.  (The tree's names only: nothing is written to the save.)"""
    keys = {
        "oldest": lambda p: (p.age is None, -(p.age or 0), p.order_key()),
        "youngest": lambda p: (p.age is None, p.age or 0, p.order_key()),
        "appearance": Person.order_key,
    }
    holders: dict[str, list[Person]] = {}
    for p in sorted(village.known(), key=keys[order]):
        if p.id not in leave:
            holders.setdefault(unnumbered(p.name), []).append(p)
    used: dict[str, set[int]] = {}
    for p in village.known():
        base, value = unnumbered(p.name), roman_value(p.name.rsplit(" ", 1)[-1])
        if base != p.name and value:
            used.setdefault(base, set()).add(value)
    for taken_name in reserved:
        base, value = unnumbered(taken_name), roman_value(taken_name.rsplit(" ", 1)[-1])
        if base != taken_name and value:
            used.setdefault(base, set()).add(value)
    out = {}
    for name, ps in holders.items():
        if sum((weight or {}).get(p.id, 1) for p in ps) < 2:
            continue
        numbers = used.setdefault(name, set())
        seen: set[str] = set()
        before = 0
        for p in ps:
            value = roman_value(p.name.rsplit(" ", 1)[-1]) if p.name != name else 0
            given = []
            if value and p.name not in seen:
                seen.add(p.name)
                before = max(before, value)
                given.append(p.name)
            for _ in range((weight or {}).get(p.id, 1) - len(given)):
                n = before + 1
                while n in numbers:
                    n += 1
                numbers.add(n)
                before = n
                given.append(f"{name} {roman(n)}")
            if given[0] != p.name:
                out[p.id] = given[0]
            if blocks is not None and len(given) > 1:
                blocks[p.id] = given
    return out


_ROMAN_VALUES: dict[str, int] = {}


def roman_value(word: str) -> int:
    if not _ROMAN_VALUES:
        _ROMAN_VALUES.update({roman(n): n for n in range(1, 4000)})
    return _ROMAN_VALUES.get(word, 0)


def unnumbered(name: str) -> str:
    words = name.split(" ")
    if len(words) > 1 and re.fullmatch(r"[IVXLCDM]+", words[-1]):
        return " ".join(words[:-1])
    return name


def numbered(p: Person) -> str:
    return f"#{p.number} {p.name}" if p.number is not None else p.name


def status_words(p: Person) -> str:
    """"(deceased)", "(no longer in the house)" or "" for the living."""
    if p.alive or p.upcoming:
        return ""
    return "(deceased)" if p.gone == "died" else "(no longer in the house)"


def describe_person(village: Village, p: Person) -> str:
    if p.upcoming:
        return f"{p.name} (on the way)"
    bits = [p.name, p.sex or "sex unknown", p.age_text()]
    if not p.alive:
        bits.append("dead" if p.gone == "died" else "no longer in the house")
        if p.cause:
            bits.append(f"cause: {p.cause}")
    elif p.left_home:
        bits.append("left home")
    if p.how and p.how != "Founder":
        bits.append(p.how.lower() if p.how != "Adopt New Person" else "adopted (Adopt New Person)")
    return ", ".join(bits)


def report(village: Village, game_title: str = GAME_TITLE) -> str:
    """The family's genealogy as text: every generation, who descends from whom."""
    people = village.people
    lines = [f"{game_title} -- Family Tree",
             f"Family: {village.tribe} (Save {village.slot})" if village.tribe else f"Save {village.slot}",
             "",
             "Generation I is the family's founder and the one who married them; each generation below holds the "
             "children of the one above, the heir who inherited the house and the one who married them.  Only "
             "what the save records is shown; what they do not say is marked unknown.",
             ""]
    for note in village.notes:
        lines.append(f"Note: {note}")
    if village.notes:
        lines.append("")
    by_gen: dict[int, list[Person]] = {}
    for p in people.values():
        by_gen.setdefault(p.generation, []).append(p)
    lines.append("== Generations ==")
    for g in sorted(by_gen):
        group = sorted(by_gen[g], key=lambda q: q.order_key())
        born = [p for p in group if not p.upcoming]
        coming = len(group) - len(born)
        lines.append(f"Generation {roman(g)}: {len(born)} family members ({sum(p.alive for p in born)} living)"
                     + (f", {coming} on the way" if coming else ""))
        for p in group:
            parents = [people[q].name for q in (p.father, p.mother) if q is not None]
            lines.append(f"  {describe_person(village, p)}"
                         + (f" -- child of {' and '.join(parents)}" if parents else ""))
            kids = village.children_of(p.id)
            if kids:
                lines.append(f"    children: {', '.join(k.name for k in sorted(kids, key=lambda q: q.order_key()))}")
            for unknown in p.unknowns:
                lines.append(f"    unknown: {unknown}")
        lines.append("")
    if village.history_events:
        lines.append("== E-mail and pop-up events (Family History log) ==")
        lines.extend(f"  {e}" for e in village.history_events)
        lines.append("")
    return "\n".join(lines)
