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
Nothing else is read: no log or data file of the patcher (the owner: the tree comes from the save alone).

What no record says is left unknown and labelled as such (Person.unknowns), never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import vf1_save

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
    family: int | None = None
    expecting: bool = False             # a living mother-to-be
    heathen: bool = False               # (Virtual Villagers only; always False here)
    runner: bool = False                # (Virtual Villagers only; always False here)
    likes: list[str] | None = None      # the words they like, as the Family Tree keeps them; None = not known
    dislikes: list[str] | None = None
    arrived: bool = False               # joined the family from outside: married in or adopted
    how: str = ""                       # "Founder", "Married in", "Adopted", "Adopt New Person"
    first_seen: str | None = None
    upcoming: bool = False              # a baby on the way (conceived, not born yet)
    birth_record: int | None = None     # its place in the family, record by record (birth order)
    generation: int = 1
    number: int | None = None           # its place in the whole tree, oldest first (number_people)
    old_looks: list[tuple[int, int]] = field(default_factory=list)
    placeholder: bool = False
    likes_seen: set = field(default_factory=set)
    former: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    converted: bool = False
    faction_seen: tuple | None = None
    left_heathen: bool = False
    masters: list[str] = field(default_factory=list)
    hidden_parents: dict = field(default_factory=dict)
    # Virtual Families 1
    left_home: bool = False             # alive and left home (the save's left-home flag, VERIFIED)
    adopted: bool = False               # joined as an adopted child (no parents in their bio)
    heir: bool = False                  # inherited the house: parent 1 of a later generation
    cause: str = ""                     # the cause of death, from a body still in the house (wording unconfirmed)
    career: int | None = None
    slot: int | None = None             # the villager record they are matched to, if any
    unknowns: list[str] = field(default_factory=list)   # what the records do not say (shown, never guessed)
    sources: list[str] = field(default_factory=list)    # where each fact came from

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
        name = data[at + 24:at + 24 + 28].split(b"\0", 1)[0].decode("latin-1")
        kids.append(ExtraChild(slot, sex, KIDS_STATES[state], head, body, age, name))
    return ChildrenSidecar(save_hash, save_size, gens, pslot, psex, kids)


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
        name = c.name.encode("latin-1")[:27]
        out[at + 24:at + 24 + len(name)] = name
    struct.pack_into("<Q", out, size - 8, fnv1a64(bytes(out[:-8])))
    return bytes(out)


# ---------------------------------------------------------------------------
# Reading the family
# ---------------------------------------------------------------------------

def _peep_person(pid: int, peep: vf1_save.PeepRecord) -> Person:
    p = Person(pid, peep.name, peep.head, peep.body, sex=SEX_WORDS.get(peep.sex))
    p.career = peep.career
    likes = [w.strip() for w in re.split(r"[,\n]", peep.likes_text) if w.strip()]
    dislikes = [w.strip() for w in re.split(r"[,\n]", peep.dislikes_text) if w.strip()]
    p.likes = likes or None
    p.dislikes = dislikes or None
    return p


def _matching_villager(save: vf1_save.VF1Save, peep: vf1_save.PeepRecord) -> vf1_save.Villager | None:
    """The villager record a Family Tree entry is, if its slot still holds them: the slot, sex and head as the
    game's own FindPeepRecord matches them, and the name.  Older records' slots are stale (reused)."""
    return save.villager_for(peep)


def _apply_villager(p: Person, v: vf1_save.Villager, unborn: set[int]) -> None:
    p.slot = v.slot
    p.age = v.age_units
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
        if not p.cause:
            word = vf1_save.DEATH_CAUSES_UNCONFIRMED.get(v.death_cause)
            if word:
                # The save keeps the cause as a number; its words follow the game's string order only.
                p.cause = f"{word} (the save's cause number {v.death_cause}; the wording is unconfirmed)"
    else:
        p.alive = False
        p.gone = "left"


def load_village(folder: Path, game: int = GAME, slot: int = 1, full_names: bool = True,
                 rename_answers: dict | None = None, identity_answers: dict | None = None,
                 save_file: Path | None = None) -> Village:
    """The slot's family: every person the save's Family Tree and the Children sidecar name.
    `save_file` reads another file than Virtual Families<slot>.ldw (a backup copy)."""
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
    # (generation, role) -> person: role "p1", "p2", or child index
    seat: dict[tuple, int] = {}
    couple_of: dict[int, list[int]] = {}           # generation -> its parents' ids

    def new(peep: vf1_save.PeepRecord) -> Person:
        nonlocal order
        pid = len(people)
        p = _peep_person(pid, peep)
        p.birth_record = order
        order += 1
        people[pid] = p
        return p

    def settle(p: Person, peep: vf1_save.PeepRecord, current: bool) -> None:
        """Alive, dead or gone, from the tree's slot and the villager record (a later record of the same person,
        the heir's, is newer than their entry among the children)."""
        p.unknowns = [u for u in p.unknowns if not u.startswith("Not in the house now")]
        if peep.slot == -1:
            p.alive, p.gone = False, "died"
            p.sources.append("The Family Tree records the death (its slot is -1).")
            return
        v = _matching_villager(save, peep)
        if v is not None:
            _apply_villager(p, v, unborn)
            return
        p.alive, p.gone = False, "left"
        p.unknowns.append("Not in the house now: the save no longer holds them, and does not say whether they "
                          "died or moved away.")

    records = save.family_records
    for rec in records:
        g = rec.generation
        current = g == len(records)
        # Parent 1: the heir (a child of the generation before), or the founder / an Adopt New Person.
        p1 = None
        if rec.parent1.used:
            idx = rec.parent1.parent_child_index
            prev = seat.get((g - 1, idx)) if g > 1 and idx >= 0 else None
            if prev is not None and people[prev].name == rec.parent1.name:
                p1 = people[prev]
                p1.heir = True
            else:
                p1 = new(rec.parent1)
                if g == 1:
                    p1.how = "Founder"
                elif idx >= 0:
                    # A child the previous record could not hold (Up to 28 Children: child 7 or later).
                    p1.heir = True
                    p1.father, p1.mother = _parents_by_sex(people, couple_of.get(g - 1, []))
                    p1.generation = g
                    p1.unknowns.append(f"Child number {idx + 1} of generation {g - 1}: the save's Family Tree "
                                       "keeps only six children, so they are known from this generation's record.")
                else:
                    p1.arrived, p1.how = True, "Adopt New Person"
            p1.likes = _peep_person(-1, rec.parent1).likes or p1.likes
            p1.dislikes = _peep_person(-1, rec.parent1).dislikes or p1.dislikes
            settle(p1, rec.parent1, current)
            seat[(g, "p1")] = p1.id
        p2 = None
        if rec.parent2.used:
            p2 = new(rec.parent2)
            p2.arrived, p2.how = True, "Married in"
            settle(p2, rec.parent2, current)
            seat[(g, "p2")] = p2.id
        couple = [p.id for p in (p1, p2) if p is not None]
        couple_of[g] = couple
        for k, peep in enumerate(rec.children):
            if not peep.used:
                continue
            c = new(peep)
            c.father, c.mother = _parents_by_sex(people, couple)
            settle(c, peep, current)
            v = save.villagers[peep.slot] if current and 0 <= peep.slot < vf1_save.VILLAGER_SLOTS else None
            if c.slot is not None and v is not None and not v.parent1_name and not v.parent2_name and not c.upcoming:
                # Joined with no parents in their bio: The Little Visitor or Adopt Outside Child (docs 2.5).
                c.adopted, c.arrived, c.how = True, True, "Adopted"
            seat[(g, k)] = c.id
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
                c = new(peep)
                c.father, c.mother = _parents_by_sex(people, couple)
                c.sources.append("Children 7 to 28: the Up to 28 Children file.")
                if extra.state == "alive":
                    v = _matching_villager(save, peep)
                    if v is not None:
                        _apply_villager(c, v, unborn)
                    else:
                        c.alive = True
                        c.age = extra.age
                elif extra.state == "dead":
                    c.alive, c.gone, c.age = False, "died", extra.age
                else:
                    c.alive, c.gone, c.age = False, "left", extra.age
                seat[(generations, k)] = c.id

    # Anyone in the house the tree does not hold (alive, present): shown, with no family recorded.
    held = {p.slot for p in people.values() if p.slot is not None}
    for v in save.villagers:
        if v.present and v.health > 0 and v.slot not in held and v.name:
            peep = vf1_save.PeepRecord(v.name, True, v.sex, v.head, v.body, v.slot, 0, v.career, "", "")
            p = new(peep)
            _apply_villager(p, v, unborn)
            p.unknowns.append("In the house, but the save's Family Tree does not record them, so their family is "
                              "not known.")

    village = Village(GAME, slot, save.family_name, people, notes, generations=generations)
    _generations(village, seat, couple_of)
    number_people(village)
    village.notes.append("The save keeps no history: twins and triplets, causes of death (beyond a body still in "
                         "the house), birthdays and earlier marriages are not recorded, so the tree does not show them.")
    return village


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


def _generations(village: Village, seat: dict, couple_of: dict[int, list[int]]) -> None:
    """Row g holds generation g's parents (the game's generation g); their children are in row g + 1, where
    the heir among them is generation g + 1's parent 1 and is joined by the one who married them."""
    people = village.people
    base: dict[int, int] = {}
    for (g, role), pid in seat.items():
        if role in ("p1", "p2"):
            base.setdefault(pid, g)
        else:
            base.setdefault(pid, g + 1)
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
    return "\n".join(lines)
