"""The Family History log, when the Family History patch wrote one: what the save forgets and the Family Tree Maker
needs (docs/FAMILY_HISTORY.md; native/vf1logs/vf1logs.cpp writes every line read here).  Optional: the tree works
from the save alone when there is no log, and then says what is not known.  Only read.

    <save folder>\\Virtual Families 1 Patcher\\Save <N>\\Logs\\Family History\\Family History <k>.txt

Each line is "[YYYY-MM-DD HH:MM:SS] <event>", or "[backfilled, no date] <event>" for what the save's Family Tree
held when the log began.  The events (the sex words, the causes of death and the event titles are the game's own
strings, as the DLL read them):

    Married: <a> (<sex>[, <years>]) and <b> (<sex>[, <years>]), generation <g>
    Remarried: <a> (<sex>, <years>) and <b> (<sex>, <years>), generation <g>; earlier spouse: <c>
    Divorced: <b> (<sex>, <years>) left the family, divorced from <a>, generation <g> (Divorce Spouse)
    Died: <name> (<sex>[, <years>]), <parent|spouse|child|not in the family tree>, generation <g>[: <cause>]
    [Twins |Triplets ]Born to <mother> and <father|an unknown father>, generation <g>: <child> (<sex>)[, ...][ and ...]
    Child: <name> (<sex>), generation <g>                                          (backfilled only)
    Joined: <name> (<sex>, <years>) as a child of <a>[ and <b>], generation <g> (Spawn Child)
    Joined: <name> (<sex>, <years>), adopted, generation <g> (Adopt Outside Child)
    E-mail: "<subject line>"[; <change>]...      Pop-up: "<title>"[; <change>]...
        a change: <name> (<sex>, <years>) joined the family as a child, generation <g> | joined the household |
                  left home | left the house
    Evicted: <names> left the house (Evict Family); the next family's history follows

In the first person (<a>) of a marriage is the one already in the family; <b> married in.  Only the lines after the
last eviction belong to the family in the save.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import vf1_genealogy as gen

_STAMP = re.compile(r"^\[(?P<when>[^\]]*)\] (?P<text>.*)$")
_WHO = r"(.+?) \((\w+)(?:, (\d+))?\)"
_MARRIED = re.compile(rf"^(Married|Remarried): {_WHO} and {_WHO}, generation (\d+)(?:; earlier spouse: (.+))?$")
_DIVORCED = re.compile(rf"^Divorced: {_WHO} left the family, divorced from (.+), generation (\d+) \(Divorce Spouse\)$")
_DIED = re.compile(rf"^Died: {_WHO}, (parent|spouse|child|not in the family tree), generation (\d+)(?:: (.+))?$")
_BORN = re.compile(r"^(Twins born|Triplets born|Born) to (.+?) and (.+?), generation (\d+): (.+)$")
_BABY = re.compile(r"(.+?) \((\w+)\)$")
_CHILD = re.compile(r"^Child: (.+) \((\w+)\), generation (\d+)$")
_SPAWNED = re.compile(rf"^Joined: {_WHO} as a child of (.+?)(?: and (.+?))?, generation (\d+) \(Spawn Child\)$")
_ADOPTED = re.compile(rf"^Joined: {_WHO}, adopted, generation (\d+) \(Adopt Outside Child\)$")
_EVENT = re.compile(r'^(E-mail|Pop-up): "(.*?)"((?:; .*)?)$')
_CHANGE = re.compile(rf"^{_WHO} (joined the family as a child, generation (\d+)|joined the household|left home|"
                     r"left the house)$")
UNKNOWN_FATHER = "an unknown father"
SOURCE = "The Family History log (the Family History patch)."


@dataclass
class Marriage:
    again: bool
    head: str
    head_sex: str
    spouse: str
    spouse_sex: str
    spouse_years: int | None
    generation: int
    earlier: str | None
    backfilled: bool


@dataclass
class Birth:
    mother: str
    father: str | None                  # None: "an unknown father"
    generation: int
    babies: list[tuple[str, str]]       # (name, sex), born together


@dataclass
class Event:
    kind: str                           # "E-mail" or "Pop-up"
    title: str                          # as the player saw it
    changes: list[tuple[str, str, int | None, str]]   # (name, sex, years, what happened)
    when: str


@dataclass
class History:
    marriages: list[Marriage] = field(default_factory=list)
    divorces: list[tuple] = field(default_factory=list)    # (spouse, sex, years, from, generation)
    deaths: list[tuple] = field(default_factory=list)      # (name, sex, years or None, role, generation, cause or "")
    births: list[Birth] = field(default_factory=list)
    joined: list[tuple] = field(default_factory=list)      # (name, sex, years, how, parents)
    events: list[Event] = field(default_factory=list)
    backfilled: bool = False                               # the log began after the family did
    evictions: int = 0
    files: list[Path] = field(default_factory=list)


def files(folder: Path, slot: int) -> list[Path]:
    base = gen.slot_root(folder, slot) / "Logs" / "Family History"
    out, k = [], 1
    while (base / f"Family History {k}.txt").is_file():
        out.append(base / f"Family History {k}.txt")
        k += 1
    return out


def _years(text: str | None) -> int | None:
    return int(text) if text else None


def parse(text: str, history: History | None = None) -> History:
    h = history or History()
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _STAMP.match(line.strip())
        if not m:
            continue
        when, body = m.group("when"), m.group("text")
        backfilled = when.startswith("backfilled")
        if body.startswith("Evicted: "):
            # Another family follows: what came before is not this family's.
            files_read, evictions = h.files, h.evictions + 1
            h.__init__()
            h.files, h.evictions = files_read, evictions
        elif w := _MARRIED.match(body):
            h.marriages.append(Marriage(w.group(1) == "Remarried", w.group(2), w.group(3), w.group(5), w.group(6),
                                        _years(w.group(7)), int(w.group(8)), w.group(9), backfilled))
        elif d := _DIVORCED.match(body):
            h.divorces.append((d.group(1), d.group(2), _years(d.group(3)), d.group(4), int(d.group(5))))
        elif d := _DIED.match(body):
            h.deaths.append((d.group(1), d.group(2), _years(d.group(3)), d.group(4), int(d.group(5)),
                             (d.group(6) or "").strip()))
        elif b := _BORN.match(body):
            babies = []
            for part in re.split(r", | and ", b.group(5)):
                c = _BABY.match(part.strip())
                if c:
                    babies.append((c.group(1), c.group(2)))
            father = None if b.group(3) == UNKNOWN_FATHER else b.group(3)
            h.births.append(Birth(b.group(2), father, int(b.group(4)), babies))
        elif _CHILD.match(body):
            pass                                            # the save's Family Tree holds them already
        elif s := _SPAWNED.match(body):
            h.joined.append((s.group(1), s.group(2), _years(s.group(3)), "Spawn Child",
                             [q for q in (s.group(4), s.group(5)) if q]))
        elif a := _ADOPTED.match(body):
            h.joined.append((a.group(1), a.group(2), _years(a.group(3)), "Adopt Outside Child", []))
        elif e := _EVENT.match(body):
            changes = []
            for part in (e.group(3) or "").split("; ")[1:]:
                c = _CHANGE.match(part)
                if c:
                    what = "joined the family as a child" if c.group(4).startswith("joined the family") else c.group(4)
                    changes.append((c.group(1), c.group(2), _years(c.group(3)), what))
            h.events.append(Event(e.group(1), e.group(2), changes, when))
        if backfilled:
            h.backfilled = True
    return h


def read(folder: Path, slot: int) -> History | None:
    paths = files(folder, slot)
    if not paths:
        return None
    h = History()
    for path in paths:
        try:
            parse(path.read_bytes().decode("cp1252", errors="replace"), h)
        except OSError:
            continue
        h.files.append(path)
    return h


def _row(p: gen.Person) -> int | None:
    m = re.match(r"g(\d+)\.", p.seat or "")
    return int(m.group(1)) if m else None


def _one(people: dict, name: str, sex: str | None = None, pred=lambda p: True,
         generation: int | None = None) -> gen.Person | None:
    """The one family member with this name (and sex) the predicate allows; narrowed to a generation's seats when
    more than one has the name.  None when it is nobody, or still more than one (never a guess)."""
    hits = [p for p in people.values() if p.name == name and (sex is None or p.sex == sex) and pred(p)]
    if len(hits) > 1 and generation is not None:
        hits = [p for p in hits if _row(p) == generation]
    return hits[0] if len(hits) == 1 else None


def _drop(p: gen.Person, *starts: str) -> None:
    p.unknowns = [u for u in p.unknowns if not u.startswith(starts)]


def apply(village: gen.Village, h: History) -> None:
    """Fill in from the log what the save cannot show: spouses who left or died before any child, earlier and
    current spouses, causes and ages at death, the parents named at each birth, twins and triplets, and how a
    child joined (the event that brought them in).  A name the log gives that matches nobody, or more than one
    member, is left alone (never a guess)."""
    people = village.people
    lost = 0

    def add_spouse(name: str, sex: str, g: int, partner: str) -> gen.Person:
        nonlocal lost
        lost += 1
        pid = max(people, default=-1) + 1
        q = gen.Person(pid, name, None, None, sex=sex)
        q.arrived, q.how, q.event = True, "Married in", "Married in"
        q.alive, q.gone = False, "left"
        q.seat = f"g{g}.p2#log{lost}"
        q.birth_record = max((p.birth_record or 0 for p in people.values()), default=0) + 1
        q.unknowns.append(f"Married {partner} (generation {g}); the save no longer holds them (it keeps no earlier "
                          "spouse), so their looks are not known.")
        q.sources.append(SOURCE)
        people[pid] = q
        return q

    def spouse_of(name: str, sex: str | None, g: int, partner: str) -> gen.Person:
        p = _one(people, name, sex, lambda q: not q.upcoming, generation=g)
        return p if p is not None else add_spouse(name, sex or "", g, partner)

    # Marriages: who married in, and the earlier spouses the save no longer holds.
    current: dict[tuple[int, str], gen.Person] = {}
    for w in h.marriages:
        spouse = spouse_of(w.spouse, w.spouse_sex, w.generation, w.head)
        spouse.sources.append(f"Married {w.head} (generation {w.generation})"
                              + ("" if w.backfilled else ", Family History log") + ".")
        if w.again and w.earlier:
            earlier = _one(people, w.earlier, None, lambda q: not q.upcoming, generation=w.generation)
            if earlier is not None and f"Earlier spouse of {w.head}." not in earlier.sources:
                earlier.sources.append(f"Earlier spouse of {w.head}.")
            spouse.sources.append(f"Remarried: {w.head} was married to {w.earlier} before.")
        current[(w.generation, w.head)] = spouse

    # Divorces (the patcher's Divorce Spouse).
    for name, sex, years, partner, g in h.divorces:
        p = spouse_of(name, sex, g, partner)
        p.alive, p.gone, p.event = False, "left", "Divorce Spouse"
        if years is not None:
            p.age = years * gen.UNITS_PER_YEAR
        _drop(p, "Not in the house now", "No longer in the save")
        p.unknowns = [u for u in p.unknowns if "Divorce" not in u]
        p.unknowns.append(f"Divorced from {partner} (the patcher's Divorce Spouse): left the family at {years}"
                          if years is not None else f"Divorced from {partner} (the patcher's Divorce Spouse).")
        p.sources.append(SOURCE)
        if current.get((g, partner)) is p:
            del current[(g, partner)]

    # Deaths, with the game's own cause.
    for name, sex, years, role, g, cause in h.deaths:
        p = _one(people, name, sex, lambda q: not q.alive and not q.upcoming, generation=g)
        if p is None and role == "spouse":
            head = next((head for (gg, head), s in current.items() if gg == g and s.name == name), None)
            if head is None:
                continue
            p = current[(g, head)]
        if p is None:
            continue
        p.alive, p.gone = False, "died"
        if cause:
            p.cause = cause
        if years is not None:
            p.age = years * gen.UNITS_PER_YEAR
        _drop(p, "Not in the house now", "No longer in")
        p.sources.append(SOURCE)

    # Births: the parents named at each one (an earlier spouse's children too), and twins and triplets.
    litter = max((p.litter or 0 for p in people.values()), default=0)
    for b in h.births:
        in_gen = lambda q, g=b.generation: (_row(q) == g and ".c" not in q.seat) or not q.seat  # noqa: E731
        mother = _one(people, b.mother, None, in_gen) or _one(people, b.mother)
        father = None
        if b.father is not None:
            father = _one(people, b.father, None, in_gen) or _one(people, b.father)
        kids = []
        for name, sex in b.babies:
            c = _one(people, name, sex, lambda q: not q.upcoming and ".c" in (q.seat or "c"),
                     generation=b.generation)
            if c is None:
                continue
            kids.append(c)
            for parent in (mother, father):
                if parent is None or parent.id == c.id:
                    continue
                if parent.sex == "Female" and c.mother != parent.id:
                    c.mother = parent.id
                elif parent.sex != "Female" and c.father != parent.id:
                    c.father = parent.id
            if b.father is None:
                c.unknowns.append("Father: the Family History log has the birth, but the game kept no father it "
                                  "could name.")
            c.sources.append(SOURCE)
        if len(b.babies) > 1 and kids:
            litter += 1
            for c in kids:
                c.litter = litter

    # Children who joined: the patcher's Spawn Child and Adopt Outside Child.
    for name, sex, _years, how, _parents in h.joined:
        p = _one(people, name, sex, lambda q: not q.upcoming)
        if p is None:
            continue
        if how == "Adopt Outside Child":
            p.adopted, p.arrived, p.how = True, True, "Adopted"
        else:
            p.how = "Spawn Child"
        p.event = how
        _drop(p, "Adopted:")
        p.sources.append(SOURCE)

    # The e-mail and pop-up events, and what each did to the family.
    for e in h.events:
        for name, sex, _years, what in e.changes:
            p = _one(people, name, sex, lambda q: not q.upcoming)
            if p is None:
                continue
            if what == "joined the family as a child":
                p.adopted, p.arrived, p.how, p.event = True, True, "Adopted", e.title
                _drop(p, "Adopted:")
            p.sources.append(f'{what.capitalize()} after the {e.kind.lower()} "{e.title}" (Family History log).')
    village.history_events = [f'{e.when}: {e.kind} "{e.title}"' for e in h.events]

    village.notes = [n for n in village.notes if not n.startswith("The save keeps no history")]
    village.notes.append("Filled in from the Family History log: marriages and divorces, deaths with their causes, "
                         "births (twins and triplets) and the e-mail and pop-up events since the log began.")
    if h.backfilled:
        village.notes.append("The log began after the family did: what happened before it (the lines marked "
                             "\"backfilled, no date\") is only what the save's Family Tree held then, so earlier "
                             "spouses, twins and causes of death from that time are not known.")
    village.sources.extend(str(p) for p in h.files)
