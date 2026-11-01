"""The Family History log, when the Family History Log patch wrote one: every family event, which the save forgets
and the Family Tree Maker needs (docs/FAMILY_HISTORY.md; native/vf1logs/vf1logs.cpp writes every record read here,
Rename Family its "Family Renamed" record and Copy Player Slot its "Family Copied" record).  Optional: the tree works from the save alone when there is no log,
and then says what is not known.  Only read.

    <save folder>\\Virtual Families 1 Patcher\\Save <N>\\Logs\\Family History\\Family History <k>.txt

Each record is the Virtual Villagers patcher's layout: a heading "[YYYY-MM-DD HH:MM:SS] <Kind> <n>" (or
"[backfilled, no date] Family Tree <g>" for what the save's Family Tree held when the log began), then
"  Label: value" lines, a family member's own lines one step further in ("    Sex: Female"), then a blank line.
The kinds: Conception, Birth, Death, Marriage, Divorce, Arrived, Left Home, Generation, New Generation, Random
Event (an "Email Event" or a "Popup Event"), Roll the Dice, Evict Family, Start Over, Family Renamed, Family Copied, Family Tree.
Only the records after the last Evict Family belong to the family in the save.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import vf1_genealogy as gen
import vf1_text

_HEADING = re.compile(r"^\[(?P<when>[^\]]*)\] (?P<kind>.+) (?P<n>\d+)$")
_FIELD = re.compile(r"^(?P<indent> +)(?P<label>[^:]+): ?(?P<value>.*)$")
_EARLIER = re.compile(r"^(.+?)(?: \((died|divorced)\))?$")
SOURCE = "The Family History log (the Family History Log patch)."
EVENT_KINDS = ("Email Event", "Popup Event")


@dataclass
class Entry:
    """One record: its kind, number, time ("backfilled, no date" for the backfill) and its lines."""
    kind: str
    number: int
    when: str
    fields: list[tuple[str, str, dict]] = field(default_factory=list)   # (label, value, the lines under it)

    def get(self, label: str, default: str | None = None) -> str | None:
        return next((v for lab, v, _sub in self.fields if lab == label), default)

    def sub(self, label: str) -> dict:
        return next((s for lab, _v, s in self.fields if lab == label), {})

    @property
    def backfilled(self) -> bool:
        return self.when.startswith("backfilled")

    def generation(self) -> int | None:
        g = self.get("Generation")
        return int(g) if g and g.isdigit() else None


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
    earlier_how: str | None              # "died", "divorced" or None
    backfilled: bool


@dataclass
class Birth:
    mother: str
    father: str | None                  # None: "(unknown)"
    generation: int
    babies: list[tuple[str, str]]       # (name, sex), born together
    size: int = 1                       # 1, 2 twins, 3 triplets ("Born as")


@dataclass
class Event:
    kind: str                           # "Email Event" or "Popup Event"
    title: str                          # as the player saw it
    choice: str | None
    when: str


@dataclass
class History:
    entries: list[Entry] = field(default_factory=list)
    marriages: list[Marriage] = field(default_factory=list)
    divorces: list[tuple] = field(default_factory=list)    # (spouse, sex, years, from, generation)
    deaths: list[tuple] = field(default_factory=list)      # (name, sex, years, role, generation, cause)
    births: list[Birth] = field(default_factory=list)
    joined: list[tuple] = field(default_factory=list)      # (name, sex, years, how, parents, generation)
    left: list[tuple] = field(default_factory=list)        # (name, sex, years, what happened, generation)
    heirs: list[tuple] = field(default_factory=list)       # (name, sex, years, how, generation)
    events: list[Event] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)
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
    return int(text) if text and text.isdigit() else None


def entries(text: str) -> list[Entry]:
    """Every record of a file, in order."""
    out: list[Entry] = []
    top: dict | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        h = _HEADING.match(line)
        if h:
            out.append(Entry(h.group("kind"), int(h.group("n")), h.group("when")))
            top = None
            continue
        f = _FIELD.match(line)
        if not f or not out:
            continue
        if len(f.group("indent")) == 2:
            top = {}
            out[-1].fields.append((f.group("label"), f.group("value"), top))
        elif top is not None and f.group("label") not in top:
            top[f.group("label")] = f.group("value")
    return out


def parse(text: str, history: History | None = None) -> History:
    h = history or History()
    for e in entries(text):
        _take(h, e)
    return h


def _take(h: History, e: Entry) -> None:
    if e.kind == "Evict Family":
        # Another family follows: what came before is not this family's.
        files_read, evictions = h.files, h.evictions + 1
        h.__init__()
        h.files, h.evictions = files_read, evictions
        return
    h.entries.append(e)
    g = e.generation() or 0
    if e.backfilled:
        h.backfilled = True
    if e.kind == "Marriage":
        earlier = _EARLIER.match(e.get("Earlier spouse") or "")
        h.marriages.append(Marriage(e.get("Remarried") == "yes", e.get("Family member", ""),
                                    e.sub("Family member").get("Sex", ""), e.get("Married", ""),
                                    e.sub("Married").get("Sex", ""), _years(e.sub("Married").get("Age")), g,
                                    earlier.group(1) if earlier and earlier.group(1) else None,
                                    earlier.group(2) if earlier else None, e.backfilled))
    elif e.kind == "Family Tree":                           # the backfill: the couple the save's tree held
        if e.get("Parent") and e.get("Parent (married in)"):
            h.marriages.append(Marriage(False, e.get("Parent"), e.sub("Parent").get("Sex", ""),
                                        e.get("Parent (married in)"), e.sub("Parent (married in)").get("Sex", ""),
                                        None, g, None, None, True))
    elif e.kind == "Divorce":
        d = e.sub("Divorced")
        h.divorces.append((e.get("Divorced", ""), d.get("Sex", ""), _years(d.get("Age")), e.get("Family member", ""), g))
    elif e.kind == "Death":
        h.deaths.append((e.get("Name", ""), e.get("Sex", ""), _years(e.get("Age at death")), e.get("Family role", ""), g,
                         e.get("Cause of death", "")))
    elif e.kind == "Birth":
        father = e.get("Father")
        father = None if father in (None, "(unknown)") else father
        baby = (e.get("Child", ""), e.sub("Child").get("Sex", ""))
        size = {"Twin": 2, "Triplet": 3}.get(e.get("Born as", ""), 1)
        last = h.births[-1] if h.births else None
        if size > 1 and last and last.size == size and last.mother == e.get("Mother") and last.father == father \
                and len(last.babies) < size:
            last.babies.append(baby)
        else:
            h.births.append(Birth(e.get("Mother", ""), father, g, [baby], size))
    elif e.kind == "Arrived":
        parents = [v for k, v in e.sub("Parents").items() if k in ("Mother", "Father")]
        h.joined.append((e.get("Name", ""), e.get("Sex", ""), _years(e.get("Age at arrival")), e.get("How", ""),
                         parents, g))
    elif e.kind == "Left Home":
        h.left.append((e.get("Name", ""), e.get("Sex", ""), _years(e.get("Age")), e.get("What happened", ""), g))
    elif e.kind in ("Generation", "New Generation"):
        h.heirs.append((e.get("Name", ""), e.get("Sex", ""), _years(e.get("Age")), e.get("How", ""), g))
    elif e.kind == "Random Event":
        for label, value, _sub in e.fields:
            if label in EVENT_KINDS:
                h.events.append(Event(label, value, e.get("Choice"), e.when))
    elif e.kind in ("Family Renamed", "Family Copied"):     # a copy is a new name for the same family
        h.renames.append((e.get("Old name", ""), e.get("New name", "")))


def _whole_names(folder: Path, slot: int):
    """A log written before its names were whole (One character limit for every name box: the save keeps a longer
    name's short form, vf1logs writes the whole name since): each short form that is a whole field value (after
    ": " or ", ", before the line's end, " (" or ",") read as the whole name the slot's Names file keeps."""
    import re
    import vf1_names
    book = vf1_names.Book(folder)
    entries: dict[str, str] = {}
    for s in [slot] + [k for k in range(1, 6) if k != slot]:      # the slot's own first
        for e in book.slots[s]:
            entries.setdefault(e.short, e.full)
    if not entries:
        return lambda text: text
    alternatives = "|".join(re.escape(s) for s in sorted(entries, key=len, reverse=True))
    pattern = re.compile(rf"(?m)(?<=: |, )({alternatives})(?=\r?$| \(|,)")
    return lambda text: pattern.sub(lambda m: entries[m.group(1)], text)


def read(folder: Path, slot: int) -> History | None:
    paths = files(folder, slot)
    if not paths:
        return None
    h = History()
    whole = _whole_names(folder, slot)
    for path in paths:
        try:
            parse(whole(vf1_text.decode_lines(path.read_bytes())), h)
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
    hits = [p for p in people.values() if p.name == name and (not sex or p.sex == sex) and pred(p)]
    if len(hits) > 1 and generation is not None:
        hits = [p for p in hits if _row(p) == generation]
    return hits[0] if len(hits) == 1 else None


def _drop(p: gen.Person, *starts: str) -> None:
    p.unknowns = [u for u in p.unknowns if not u.startswith(starts)]


def event_of(text: str) -> str:
    """"Popup Event: The Little Visitor" out of "Adopted (Popup Event: The Little Visitor)" or "Left home with The
    Talent Scout (Popup Event)"; "" when the text names no Random Event."""
    m = re.search(r"\((Email Event|Popup Event): (.+)\)$", text)
    if m:
        return f"{m.group(1)}: {m.group(2)}"
    m = re.match(r"^Left home with (.+) \((Email Event|Popup Event)\)$", text)
    return f"{m.group(2)}: {m.group(1)}" if m else ""


def apply(village: gen.Village, h: History) -> None:
    """Fill in from the log what the save cannot show: spouses who left or died before any child, the order of
    each head's marriages (Husband 1, Wife 2...), divorces, causes and ages at death, the parents named at each
    birth, twins and triplets, how each member joined or left (the Random Event that brought them in or took them
    away).  A name the log gives that matches nobody, or more than one member, is left alone (never a guess)."""
    people = village.people
    lost = 0

    def add_spouse(name: str, sex: str, g: int, partner: str) -> gen.Person:
        nonlocal lost
        lost += 1
        pid = max(people, default=-1) + 1
        q = gen.Person(pid, name, None, None, sex=sex or None)
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

    # Marriages: who married in, the earlier spouses the save no longer holds, and each head's order of marriages.
    order: dict[tuple[int, str], list] = {}
    for w in h.marriages:
        spouse = spouse_of(w.spouse, w.spouse_sex, w.generation, w.head)
        head = _one(people, w.head, w.head_sex or None, lambda q: not q.upcoming, generation=w.generation)
        if head is not None and head.id != spouse.id:
            spouse.partner = head.id
        spouse.sources.append(f"Married {w.head} (generation {w.generation})"
                              + ("" if w.backfilled else ", Family History log") + ".")
        if w.again:
            if head is not None:
                head.remarried = True
            if w.earlier:
                spouse.sources.append(f"Remarried: {w.head} was married to {w.earlier} before"
                                      + (f" ({w.earlier_how})." if w.earlier_how else "."))
        order.setdefault((w.generation, w.head), []).append((spouse, w.backfilled))
    for spouses in order.values():
        # The order is proved only when the log saw the head's first marriage itself (not a backfill).
        if spouses and not spouses[0][1]:
            for k, (s, _b) in enumerate(spouses, 1):
                s.spouse_number = k

    # Divorces (the patcher's Divorce Spouse).
    for name, sex, years, partner, g in h.divorces:
        p = spouse_of(name, sex, g, partner)
        p.alive, p.gone, p.event, p.divorced = False, "left", "Divorce Spouse", True
        if years is not None:
            p.age = years * gen.UNITS_PER_YEAR
        _drop(p, "Not in the house now", "No longer in the save")
        p.unknowns = [u for u in p.unknowns if "Divorce" not in u]
        p.unknowns.append(f"Divorced from {partner} (the patcher's Divorce Spouse): left the family at {years}"
                          if years is not None else f"Divorced from {partner} (the patcher's Divorce Spouse).")
        p.sources.append(SOURCE)

    # Deaths, with the game's own cause.
    for name, sex, years, _role, g, cause in h.deaths:
        p = _one(people, name, sex, lambda q: not q.alive and not q.upcoming, generation=g)
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
            c = _one(people, name, sex, lambda q: not q.upcoming and ".c" in (q.seat or "c"), generation=b.generation)
            if c is None:
                continue
            kids.append(c)
            for parent, label in ((mother, "mother"), (father, "father")):
                if parent is not None and parent.id != c.id:
                    setattr(c, label, parent.id)
            if b.father is None:
                c.unknowns.append("Father: the Family History log has the birth, but the game kept no father it "
                                  "could name.")
            c.sources.append(SOURCE)
        if len(b.babies) > 1 and kids:
            litter += 1
            for c in kids:
                c.litter = litter

    # Who joined: the patcher's Spawn Child and Adopt Outside Child, and the Random Events' children.
    for name, sex, _years, how, _parents, _g in h.joined:
        p = _one(people, name, sex, lambda q: not q.upcoming)
        if p is None:
            continue
        title = event_of(how)
        if how.startswith("Adopted"):
            p.adopted, p.arrived, p.how = True, True, "Adopted"
            p.event = title or how[len("Adopted ("):-1]
        else:
            p.how = p.event = how
        p.event_title = title or p.event_title
        _drop(p, "Adopted:")
        p.sources.append(SOURCE)

    # Who left home, and how.
    for name, sex, _years, what, _g in h.left:
        p = _one(people, name, sex, lambda q: not q.upcoming)
        if p is None:
            continue
        p.left_how = what
        p.event_title = event_of(what) or p.event_title
        p.sources.append(f"{what} (Family History log).")

    # Each generation's start: Adopt New Person brings an adult in.
    for name, sex, _years, how, _g in h.heirs:
        p = _one(people, name, sex, lambda q: not q.upcoming)
        if p is not None and how == "Adopt New Person":
            p.arrived, p.how, p.event = True, "Adopt New Person", "Adopt New Person"

    village.history_events = [f"{e.when}: {e.kind}: {e.title}" for e in h.events]
    village.notes = [n for n in village.notes if not n.startswith("The save keeps no history")]
    village.notes.append("Filled in from the Family History log: marriages and divorces, deaths with their causes, "
                         "births (twins and triplets), who joined and left and the Random Events since the log began.")
    if h.backfilled:
        village.notes.append("The log began after the family did: what happened before it (the records marked "
                             "\"backfilled, no date\") is only what the save's Family Tree held then, so earlier "
                             "spouses, twins and causes of death from that time are not known.")
    village.sources.extend(str(p) for p in h.files)
