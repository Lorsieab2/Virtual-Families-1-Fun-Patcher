"""The Family History log, when the Family Logs patch wrote one: what happened between two openings of the Family
Tree Maker that the save itself does not keep (docs/FAMILY_LOGS.md; native/vf1logs/vf1logs.cpp writes every line
read here).  Optional: the tree works the same with no log at all.  Only read.

    <save folder>\\Virtual Families 1 Patcher\\Save <N>\\Logs\\Family History\\Family History <k>.txt

Each line is "[YYYY-MM-DD HH:MM:SS] <event>" (or "[backfilled, no date] ..."); the lines used:

    Birth <n>: <child> (<sex>) was born to <mother> and <father>[ (Twins)| (Triplets)]      OnBirths
    Death <n>: <name> (<sex>, <years>) died: <cause>                                       OnDeath
    <a> (<sex>, <years>) married <b> (<sex>, <years>), generation <g>                       OnMarriage
    <name> (<sex>, <years>) joined the family as a child[ of <p1> and <p2>|, adopted], generation <g>   OnJoined
    Event <n>: <title>[: <name>][ ($<cost>)]                                                VF1Logs_Event

The sex words and causes are the game's own strings, as the DLL read them.  Virtual Families 1's other events (the
e-mail events: The Talent Scout, The Earthquake...) are not logged by the DLL, so no line names them; the one stock
event that brings a member in is The Little Visitor (the only stock caller of AddOffspring besides the babies,
0x418828 / 0x4188D8), told apart from the patcher's Adopt Outside Child by the event line the patcher writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import vf1_genealogy as gen

_STAMP = re.compile(r"^\[(?P<when>[^\]]*)\] (?P<text>.*)$")
_BIRTH = re.compile(r"^Birth (\d+): (.+) \((\w+)\) was born to (.+?) and (.+?)(?: \((Twins|Triplets)\))?$")
_DEATH = re.compile(r"^Death (\d+): (.+) \((\w+), (\d+)\) died: (.*)$")
_MARRIED = re.compile(r"^(.+) \((\w+), (\d+)\) married (.+) \((\w+), (\d+)\), generation (\d+)$")
_JOINED = re.compile(r"^(.+) \((\w+), (\d+)\) joined the family as a child(?: of (.+) and (.+)|(, adopted))?, "
                     r"generation (\d+)$")
_EVENT = re.compile(r"^Event (\d+): ([^:(]+?)(?:: (.+?))?(?: \(\$-?\d+\))?$")


@dataclass
class History:
    births: list[tuple] = field(default_factory=list)      # (n, child, sex, mother, father, "Twins"/"Triplets"/"")
    deaths: list[tuple] = field(default_factory=list)      # (n, name, sex, years, cause)
    marriages: list[tuple] = field(default_factory=list)   # (a, sex a, years a, b, sex b, years b, generation)
    joined: list[tuple] = field(default_factory=list)      # (name, sex, years, adopted, generation, line index)
    events: list[tuple] = field(default_factory=list)      # (n, title, name or "", line index)
    files: list[Path] = field(default_factory=list)


def files(folder: Path, slot: int) -> list[Path]:
    base = gen.slot_root(folder, slot) / "Logs" / "Family History"
    out, k = [], 1
    while (base / f"Family History {k}.txt").is_file():
        out.append(base / f"Family History {k}.txt")
        k += 1
    return out


def parse(text: str, history: History | None = None) -> History:
    h = history or History()
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _STAMP.match(line.strip())
        if not m:
            continue
        body = m.group("text")
        index = len(h.joined) + len(h.events) + len(h.births) + len(h.deaths) + len(h.marriages)
        if b := _BIRTH.match(body):
            h.births.append((int(b.group(1)), b.group(2), b.group(3), b.group(4), b.group(5), b.group(6) or ""))
        elif d := _DEATH.match(body):
            h.deaths.append((int(d.group(1)), d.group(2), d.group(3), int(d.group(4)), d.group(5).strip()))
        elif w := _MARRIED.match(body):
            h.marriages.append((w.group(1), w.group(2), int(w.group(3)), w.group(4), w.group(5), int(w.group(6)),
                                int(w.group(7))))
        elif j := _JOINED.match(body):
            h.joined.append((j.group(1), j.group(2), int(j.group(3)), bool(j.group(6)), int(j.group(7)), index))
        elif e := _EVENT.match(body):
            h.events.append((int(e.group(1)), e.group(2).strip(), (e.group(3) or "").strip(), index))
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


def _one(people: dict, name: str, sex: str | None = None, pred=lambda p: True) -> gen.Person | None:
    hits = [p for p in people.values() if p.name == name and (sex is None or p.sex == sex) and pred(p)]
    return hits[0] if len(hits) == 1 else None


def apply(village: gen.Village, h: History) -> None:
    """Fill in from the log what the save cannot show: causes and ages at death, twins and triplets, the parents
    named at a birth (a first spouse), spouses who married in and are gone, divorces and the events that brought a
    child in.  A name the log gives that matches nobody, or more than one member, is left alone (never a guess)."""
    people = village.people
    source = "The Family History log (Family Logs patch)."

    for _n, name, sex, years, cause in h.deaths:
        p = _one(people, name, sex, lambda q: not q.alive and not q.upcoming)
        if p is None:
            continue
        p.gone, p.cause = "died", cause or p.cause
        if p.age is None or p.age // gen.UNITS_PER_YEAR != years:
            p.age = years * gen.UNITS_PER_YEAR
        p.unknowns = [u for u in p.unknowns if not u.startswith(("Not in the house now", "No longer in"))]
        p.sources.append(source)

    # Spouses who married in: anyone the save no longer holds is added (their generation is their partner's).
    for a, _sa, _ya, b, sb, yb, g in h.marriages:
        partner = _one(people, a)
        if _one(people, b, sb) is not None or partner is None:
            continue
        pid = max(people, default=-1) + 1
        q = gen.Person(pid, b, None, None, sex=sb)
        q.arrived, q.how, q.event = True, "Married in", "Married in"
        q.gone = "left"
        q.seat = f"g{g}.p2#log{pid}"
        q.birth_record = (partner.birth_record or 0) + 0.5
        q.unknowns.append(f"Married {a} at {yb}; no longer in the save, which keeps no earlier spouse (their looks and "
                          "what became of them are not known).")
        q.sources.append(source)
        people[pid] = q

    # Births: the parents named at the birth, and twins and triplets (the DLL logs a delivery's babies together).
    litter = max((p.litter or 0 for p in people.values()), default=0)
    run: list = []
    for _n, child, sex, mother, father, born_as in h.births:
        c = _one(people, child, sex, lambda q: not q.upcoming)
        if c is not None:
            for label, named in (("mother", mother), ("father", father)):
                parent = _one(people, named)
                if parent is not None and parent.id != c.id and getattr(c, label) != parent.id:
                    setattr(c, label, parent.id)
            c.sources.append(source)
        size = {"Twins": 2, "Triplets": 3}.get(born_as, 1)
        if size == 1:
            run = []
            continue
        if not run or len(run) >= size or run[0][1] != (mother, father, born_as):
            litter += 1
            run = []
        run.append((c, (mother, father, born_as)))
        if c is not None:
            c.litter = litter
    counts: dict[int, int] = {}
    for p in people.values():
        if p.litter is not None:
            counts[p.litter] = counts.get(p.litter, 0) + 1
    for p in people.values():
        if p.litter is not None and counts[p.litter] < 2:
            p.litter = None

    # Events: Divorce Spouse; a child who joined adopted is The Little Visitor's unless the patcher's Adopt Outside
    # Child names them; Spawn Child, Adopt New Person and Boarding School as the patcher logged them.
    named_events = {(title, name) for _n, title, name, _i in h.events}
    for _n, title, name, _i in h.events:
        p = _one(people, name) if name else None
        if p is None:
            continue
        if title == "Divorce Spouse":
            p.event = "Divorce Spouse"
            p.unknowns = [u for u in p.unknowns if "Divorce" not in u]
            p.unknowns.append("Divorced (the patcher's Divorce Spouse, Family History log).")
        elif title in ("Spawn Child", "Adopt Outside Child", "Adopt New Person", "Boarding School"):
            p.event = title
    for name, sex, _years, adopted, _g, _i in h.joined:
        p = _one(people, name, sex)
        if p is None or not adopted:
            continue
        p.adopted, p.arrived, p.how = True, True, "Adopted"
        p.event = "Adopt Outside Child" if ("Adopt Outside Child", name) in named_events else gen.LITTLE_VISITOR
        p.unknowns = [u for u in p.unknowns if not u.startswith("Adopted:")]
    village.sources.extend(str(p) for p in h.files)
