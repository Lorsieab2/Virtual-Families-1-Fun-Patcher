"""Relationships: how every family member on the tree is related to the one selected, for the Family Tree
Maker's Family Member Info tab.  A port of the Virtual Villagers Fun Patcher's Relationships dropdown
(src/vv_relationships.py, v1.35.85): the same words, the same groups and the same order.

Only what the tree's own records prove -- nothing is ever guessed:

* A family member's parents are the tree's (`Person.father` / `Person.mother`: the couple of their generation's
  record in the save's Family Tree, or the parents the Family History log names at the birth).  Virtual
  Families 1 has no default father: a parent no record names is no parent, and links nobody.
* The identity is the tree's own: one Person per family member (two living members of one name and look are
  two), each named as the tree shows them (Number Duplicate Names' numeral too).
* Partners are the two parents of a child (a baby on the way included) and, as Virtual Families has marriage,
  the two parents of one generation's record in the save's Family Tree and a spouse the Family History log
  names (`Person.partner`): listed once as "Partners".

Blood relationships are worked out from each family member's ancestors (a breadth-first walk up the recorded
parents, kept for every family member once per tree load): two family members are related through a common ancestor
by a line up from each that leaves the ancestor by a different child and never meets the other below it
(where lines would meet is a common ancestor of both descending from both children: the relationship is
then the one through that nearer ancestor), the nearest such pair of lines through each common ancestor.
So a first cousin is never also a second cousin through the grandparents' parents.  Whenever each of one
family member's two parents is a sibling of one of the other's two parents, they are double first cousins --
even when they also share those parents: a brother and sister's children are siblings AND double first
cousins (the owner, 2026-10-28: the strict genealogical reading), but their grandchildren by one son are
siblings only (both lines meet again at that son).  In a close-knit
family, though, two family members can be related along several lines (a half-brother who is also a
half-first cousin).  A direct ancestor counts at every distance a line gives (a grandfather who is also a
great-grandfather), and is also related by the lines that do not go through them (a mother who had her
child by her own father is also the child's half-sister).  With d the generations from the selected
family member up to the common ancestor and e from the relative up to it:

    d = 0 or e = 0       a descendant or an ancestor (child, grandchild..., parent, grandparent...)
    d = e = 1            a sibling: a full sibling shares both parents, a half-sibling one; babies of one
                         birth are twins or triplets (the tree's `litter`: the Family History log's births, and
                         the babies of one pregnancy on the way; vf1_family_history.apply)
    e = 1, d >= 2        an aunt or uncle (a sibling of a parent, grandparent...)
    d = 1, e >= 2        a niece or nephew
    d, e >= 2            a cousin of degree min(d, e) - 1, removed |d - e| times

Conventions (one style everywhere):

* Greats: "Grandmother", "Great-grandmother", "Great-great-grandmother", then "3× great-grandmother" from
  three greats on.  Aunts, uncles, nieces and nephews take the same greats with "great-", never "grand-":
  a "Great-aunt" is a grandparent's sister (some say "grand-aunt"), a "Great-niece" a sibling's grandchild.
* "Half-" goes in front of the whole term wherever the link goes through only one of a couple:
  "Half-sister", "Half-aunt", "Half-great-uncle", "Half-first cousin once removed".
* Cousins: "First cousin", "Second cousin once removed", "Third cousin twice removed", "First cousin
  3 times removed"; "Double first cousin" when each of one's two parents is a sibling of one of the other's
  two parents (two siblings' children by another pair of siblings) -- also when they share those parents
  too: a brother and sister's children are listed as siblings and as double first cousins.
* Terms are gendered by the relative's sex (Mother/Father, Aunt/Uncle, Niece/Nephew, Sister/Brother,
  Daughter-in-law/Son-in-law...); neutral where the language is (Cousin, Partner) or the records give no sex
  (Parent, Sibling, Aunt or uncle...).
* In-laws (through a partner): a partner's parents (mother-/father-in-law), a
  partner's siblings and a sibling's partners (sister-/brother-in-law), a child's partners (daughter-/son-in-law).
* Step-relations: a parent's other partner (step-mother/step-father), that partner's children by someone
  else who share no parent with the family member (step-sisters/step-brothers), and -- the same link seen from
  the other side -- a partner's children by someone else (step-daughters/step-sons).

Everyone is listed: living, dead and no longer in the house (the last two marked), but not a baby on the
way (not born yet).  A family member can hold several relationships to one person and is listed under each.
"""
from __future__ import annotations

from dataclasses import dataclass

import vf1_genealogy as gen


@dataclass(frozen=True)
class Relation:
    group: str          # the dropdown's group, plural: "First cousins once removed"
    order: tuple        # where the group sits in the dropdown
    term: str           # what the relative is to the family member, gendered: "Great-aunt"
    pid: int


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------

_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


def ordinal(n: int) -> str:
    if 1 <= n <= len(_ORDINALS):
        return _ORDINALS[n - 1]
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def removed_words(n: int) -> str:
    return "" if n == 0 else " " + {1: "once", 2: "twice"}.get(n, f"{n} times") + " removed"


def greats(n: int) -> str:
    """"", "great-", "great-great-", then "3× great-" from three greats on."""
    return "" if n <= 0 else "great-" * n if n <= 2 else f"{n}× great-"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _by_sex(p: gen.Person, female: str, male: str, neutral: str) -> str:
    return {"Female": female, "Male": male}.get(p.sex or "", neutral)


def _half(term: str, half: bool) -> str:
    return "Half-" + term[:1].lower() + term[1:] if half else term


def ancestor_words(n: int, p: gen.Person) -> tuple[str, str]:
    """(the group, the term) for an ancestor n generations up."""
    if n == 1:
        return "Parents", _by_sex(p, "Mother", "Father", "Parent")
    g = greats(n - 2)
    return _cap(g + "grandparents"), _cap(g + "grand" + _by_sex(p, "mother", "father", "parent"))


def descendant_words(n: int, p: gen.Person) -> tuple[str, str]:
    if n == 1:
        return "Children", _by_sex(p, "Daughter", "Son", "Child")
    g = greats(n - 2)
    return _cap(g + "grandchildren"), _cap(g + "grand" + _by_sex(p, "daughter", "son", "child"))


def aunt_words(n: int, p: gen.Person, half: bool) -> tuple[str, str]:
    """A sibling of an ancestor n generations up (n = 2: a parent's sibling)."""
    g = greats(n - 2)
    group = _cap(f"{g}aunts and {g}uncles")
    term = _cap(g + _by_sex(p, "aunt", "uncle", "aunt or uncle"))
    if half:
        group = f"Half-{g}aunts and half-{g}uncles"
    return group, _half(term, half)


def niece_words(n: int, p: gen.Person, half: bool) -> tuple[str, str]:
    """A descendant, n generations down, of a sibling (n = 2: a sibling's child)."""
    g = greats(n - 2)
    group = _cap(f"{g}nieces and {g}nephews")
    term = _cap(g + _by_sex(p, "niece", "nephew", "niece or nephew"))
    if half:
        group = f"Half-{g}nieces and half-{g}nephews"
    return group, _half(term, half)


def cousin_words(degree: int, removed: int, half: bool, double: bool) -> tuple[str, str]:
    term = f"{ordinal(degree)} cousin{removed_words(removed)}"
    group = f"{ordinal(degree)} cousins{removed_words(removed)}"
    prefix = "Double " if double else "Half-" if half else ""
    return _cap(prefix + group), _cap(prefix + term)


def sibling_words(p: gen.Person, half: bool, birth: int) -> tuple[str, str]:
    """birth: how many were born together (0: not one birth)."""
    if birth:
        word = "Twin" if birth == 2 else "Triplet" if birth == 3 else "Multiple-birth"
        group = {2: "Twins", 3: "Triplets"}.get(birth, "Born together")
        return group, word + _by_sex(p, " sister", " brother", "" if birth in (2, 3) else " sibling")
    if half:
        return "Half-siblings", _by_sex(p, "Half-sister", "Half-brother", "Half-sibling")
    return "Full siblings", _by_sex(p, "Sister", "Brother", "Sibling")


def status_words(p: gen.Person) -> str:
    """As the Family Member Info tab marks them: "(deceased)" or "(no longer in the house)"; "" for the living."""
    return gen.status_words(p)


# ---------------------------------------------------------------------------
# The relationships
# ---------------------------------------------------------------------------

def is_nobody(game: int, p: gen.Person) -> bool:
    """A default father or "Unknown" in Virtual Villagers: Virtual Families 1 has none (a parent no record names
    is simply not there), so nobody is left out."""
    return bool(getattr(p, "placeholder", False))


class Relationships:
    """Every family member's relationships, worked out once per tree load (relations_for) and per member on
    first asking.  Fine for a big family of many generations:
    each family member's ancestors (with every distance a recorded line gives) are kept once, and one member's
    relationships to everyone are set intersections of those."""

    def __init__(self, village: gen.Village) -> None:
        self.village = village
        people = self.people = village.people
        game = village.game
        self.nobody = {pid for pid, p in people.items() if is_nobody(game, p)}
        self.parents: dict[int, list[int]] = {}
        self.children: dict[int, list[int]] = {pid: [] for pid in people}
        self.partners: dict[int, set[int]] = {pid: set() for pid in people}
        for pid, p in people.items():
            mine = [q for q in (p.father, p.mother) if q is not None and q in people and q not in self.nobody
                    and q != pid]
            self.parents[pid] = list(dict.fromkeys(mine))
            for q in self.parents[pid]:
                self.children[q].append(pid)
            if len(self.parents[pid]) == 2:
                a, b = self.parents[pid]
                self.partners[a].add(b)
                self.partners[b].add(a)
        # Virtual Families has marriage: a generation's couple in the save's Family Tree, and a spouse the Family
        # History log names, are partners with or without a child.
        couples = [list(c) for c in (getattr(village, "couples", None) or {}).values()]
        couples += [[pid, p.partner] for pid, p in people.items() if getattr(p, "partner", None) is not None]
        for couple in couples:
            ids = [q for q in dict.fromkeys(couple) if q in people and q not in self.nobody and not people[q].upcoming]
            if len(ids) == 2:
                a, b = ids
                self.partners[a].add(b)
                self.partners[b].add(a)
        self.births: dict[int, int] = {}
        for p in people.values():
            if p.litter is not None and not p.upcoming:
                self.births[p.litter] = self.births.get(p.litter, 0) + 1
        self.up = self._ancestors()
        self.near = {pid: {a: min(ds) for a, ds in anc.items()} for pid, anc in self.up.items()}
        self.down: dict[int, set[int]] = {pid: set() for pid in people}    # descendants, themselves too
        for pid, anc in self.up.items():
            for a in anc:
                self.down[a].add(pid)
        self.below_both: dict[tuple[int, int], set[int]] = {}
        self.memo: dict[int, list[Relation]] = {}

    def _ancestors(self) -> dict[int, dict[int, frozenset]]:
        """Each family member's ancestors -> every number of generations up a recorded line reaches them,
        themselves at 0.  Walked parents first without recursion (a long line is many generations); a
        loop in damaged records is cut where it closes rather than followed."""
        up: dict[int, dict[int, frozenset]] = {}
        state: dict[int, int] = {}              # 1: being walked, 2: done
        for start in self.people:
            if start in up:
                continue
            stack = [(start, False)]
            while stack:
                pid, ready = stack.pop()
                if ready:
                    mine: dict[int, set] = {pid: {0}}
                    for parent in self.parents[pid]:
                        if state.get(parent) != 2:
                            continue                    # a loop: never a link
                        for anc, ds in up[parent].items():
                            if anc == pid:
                                continue
                            mine.setdefault(anc, set()).update(d + 1 for d in ds)
                    up[pid] = {a: frozenset(ds) for a, ds in mine.items()}
                    state[pid] = 2
                    continue
                if state.get(pid):
                    continue
                state[pid] = 1
                stack.append((pid, True))
                for parent in self.parents[pid]:
                    if not state.get(parent):
                        stack.append((parent, False))
        return up

    # -- one family member -----------------------------------------------------

    def of(self, pid: int) -> list[Relation]:
        """Every relationship each family member on the tree has to `pid`, in dropdown order."""
        if pid not in self.memo:
            self.memo[pid] = [] if pid in self.nobody or pid not in self.people else self._work_out(pid)
        return self.memo[pid]

    def groups(self, pid: int) -> list[tuple[str, list[Relation]]]:
        """(group, its relations) in dropdown order; empty groups are never listed."""
        out: dict[str, list[Relation]] = {}
        for r in self.of(pid):
            out.setdefault(r.group, []).append(r)
        return list(out.items())

    def _work_out(self, x: int) -> list[Relation]:
        people = self.people
        found: list[Relation] = []
        seen: set[tuple[str, int]] = set()

        def add(group_term: tuple[str, str], order: tuple, y: int) -> None:
            group, term = group_term
            if (group, y) not in seen:
                seen.add((group, y))
                found.append(Relation(group, order, term, y))

        up_x = self.up[x]
        x_keys = up_x.keys()
        for y, py in people.items():
            if y == x or py.upcoming or y in self.nobody:
                continue
            up_y = self.up[y]
            if x_keys.isdisjoint(up_y.keys()):
                continue
            buckets: dict[tuple[int, int], set[int]] = {}
            ux, uy = self.near[x], self.near[y]
            if y in up_x:                       # y is x's ancestor, at every distance a line gives
                for d in up_x[y]:
                    buckets[(d, 0)] = {y}
                ux = self._avoiding(x, y)       # and related besides, by lines that do not go through y
            elif x in up_y:
                for e in up_y[x]:
                    buckets[(0, e)] = {x}
                uy = self._avoiding(y, x)
            common = ux.keys() & uy.keys()
            for a in common:
                for d, e in self._through(a, ux, uy, common):
                    buckets.setdefault((d, e), set()).add(a)
            for (d, e), via in buckets.items():
                self._blood(x, y, py, d, e, via, add)

        # Partners, in-laws and steps: through the game's partners (a child together).
        p_x = self.partners[x]
        for y in p_x:
            add(("Partners", "Partner"), (0,), y)
        siblings = self._siblings(x)
        for q in p_x:
            for y in self.parents[q]:
                if y != x:
                    add(("Parents-in-law", _by_sex(people[y], "Mother-in-law", "Father-in-law", "Parent-in-law")),
                        (7, 0), y)
            for y in self._siblings(q):
                if y != x:
                    add(self._sibling_in_law(people[y]), (7, 1), y)
        for s in siblings:
            for y in self.partners[s]:
                if y != x:
                    add(self._sibling_in_law(people[y]), (7, 1), y)
        for c in self.children[x]:
            for y in self.partners[c]:
                if y != x:
                    add(("Children-in-law", _by_sex(people[y], "Daughter-in-law", "Son-in-law", "Child-in-law")),
                        (7, 2), y)
        mine = set(self.parents[x])
        steps = {y for parent in mine for y in self.partners[parent] if y not in mine and y != x}
        for y in steps:
            add(("Step-parents", _by_sex(people[y], "Step-mother", "Step-father", "Step-parent")), (8, 0), y)
            for c in self.children[y]:
                if c != x and not people[c].upcoming and not (set(self.parents[c]) & mine):
                    add(("Step-siblings", _by_sex(people[c], "Step-sister", "Step-brother", "Step-sibling")),
                        (8, 1), c)
        for q in p_x:
            for c in self.children[q]:
                if c != x and x not in self.parents[c] and not people[c].upcoming:
                    add(("Step-children", _by_sex(people[c], "Step-daughter", "Step-son", "Step-child")), (8, 2), c)

        def place(r: Relation) -> tuple:
            p = people[r.pid]
            return (r.order, r.group, p.number if p.number is not None else 1 << 30, p.name, r.pid)
        return sorted(found, key=place)

    def _through(self, a: int, ux: dict, uy: dict, common) -> set[tuple[int, int]]:
        """The (d, e) the recorded lines prove through the common ancestor `a`: a line up from x and one up
        from y that leave `a` by two different children and never meet below `a` -- where they would meet is
        a common ancestor descending from both children (_meet).  Two children who are both ancestors of
        both still count when no such meeting point exists: a brother and sister's children are double
        first cousins as well as siblings (the owner, 2026-10-28: the strict genealogical reading).  The
        nearest such pair of lines is the relationship through `a` (fewest generations all told, then the
        more even): further lines through the same ancestor only go round a close-knit family -- in a
        village with one father of all, everyone would be everyone's half-aunt, half-great-aunt...  A first
        cousin is never also a second cousin through the grandparents' parents."""
        kids = self.children[a]
        xs = sorted((ux[c] + 1, c) for c in kids if c in ux)
        ys = sorted((uy[c] + 1, c) for c in kids if c in uy)
        best = None
        for d, cx in xs:
            for e, cy in ys:
                if cx != cy and not (cx in common and cy in common and self._meet(cx, cy, common)):
                    if best is None or (d + e, max(d, e)) < (sum(best), max(best)):
                        best = (d, e)
                    break                       # ys is nearest first: the rest are further for this cx
        return {best} if best else set()

    def _meet(self, cx: int, cy: int, common) -> bool:
        """Whether an ancestor of both family members descends from both cx and cy: every line through cx and cy
        then meets again there, and the relationship is the one through that nearer ancestor."""
        key = (cx, cy) if cx < cy else (cy, cx)
        both = self.below_both.get(key)
        if both is None:
            both = self.below_both[key] = self.down[cx] & self.down[cy]
        return not both.isdisjoint(common)

    def _avoiding(self, start: int, avoid: int) -> dict[int, int]:
        """start's ancestors (themselves at 0) and the nearest distance to each by the lines that do not go
        through `avoid`: breadth first."""
        out = {start: 0}
        frontier = [start]
        depth = 0
        while frontier:
            depth += 1
            nxt = []
            for pid in frontier:
                for parent in self.parents[pid]:
                    if parent != avoid and parent not in out:
                        out[parent] = depth
                        nxt.append(parent)
            frontier = nxt
        return out

    def _sibling_in_law(self, p: gen.Person) -> tuple[str, str]:
        return "Siblings-in-law", _by_sex(p, "Sister-in-law", "Brother-in-law", "Sibling-in-law")

    def _siblings(self, x: int) -> set[int]:
        """Everyone sharing a recorded parent with x (full or half), born or not yet: a sibling's partner is
        known from a conception too, but the sibling must be born."""
        return {c for parent in self.parents[x] for c in self.children[parent]
                if c != x and not self.people[c].upcoming}

    def _full(self, x: int, y: int, d: int, e: int, via: set[int]) -> bool:
        """Related through a couple, not one of them: two of `via` are both parents of the child on x's line
        (d - 1 generations above x; x itself for a sibling or niece) and of the child on y's line."""
        up_x, up_y = self.up[x], self.up[y]
        for a in via:
            for b in self.partners[a] & via:
                both = set(self.children[a]) & set(self.children[b])
                if any(d - 1 in up_x.get(c, ()) for c in both) and any(e - 1 in up_y.get(c, ()) for c in both):
                    return True
        return False

    def _lines(self, pid: int, depth: int, via: set[int]) -> int:
        """How many of pid's parents lead up to one of `via` in `depth` generations."""
        return sum(1 for parent in self.parents[pid]
                   if any(depth in self.up[parent].get(a, ()) for a in via))

    def _blood(self, x: int, y: int, py: gen.Person, d: int, e: int, via: set[int], add) -> None:
        if e == 0:
            add(ancestor_words(d, py), (1, d), y)
            return
        if d == 0:
            add(descendant_words(e, py), (2, e), y)
            return
        half = not self._full(x, y, d, e, via)
        if d == 1 and e == 1:
            px = self.people[x]
            together = px.litter is not None and px.litter == py.litter and not px.upcoming
            birth = self.births.get(px.litter, 0) if together else 0
            add(sibling_words(py, half, birth), (3, 0 if birth else 2 if half else 1), y)
        elif e == 1:
            add(aunt_words(d, py, half), (4, d, half), y)
        elif d == 1:
            add(niece_words(e, py, half), (5, e, half), y)
        else:
            double = self._lines(x, d - 1, via) == 2 and self._lines(y, e - 1, via) == 2
            degree, removed = min(d, e) - 1, abs(d - e)
            add(cousin_words(degree, removed, half and not double, double),
                (6, degree, removed, 0 if double else 2 if half else 1), y)


_CACHE: list = [None, None, None]       # (village, its signature, Relationships)


def _signature(village: gen.Village) -> int:
    return hash(tuple((pid, p.father, p.mother, p.sex, p.litter, p.upcoming, p.partner, p.name)
                      for pid, p in village.people.items())
                + tuple((g, tuple(c)) for g, c in sorted((village.couples or {}).items())))


def relations_for(village: gen.Village) -> Relationships:
    """The family's Relationships, worked out once per tree load (Update from the save gives the editor
    a new Village, and any change to who is whose parent is a new signature)."""
    sig = _signature(village)
    if _CACHE[0] is not village or _CACHE[1] != sig:
        _CACHE[:] = [village, sig, Relationships(village)]
    return _CACHE[2]


# ---------------------------------------------------------------------------
# The Family Member Info tab's section
# ---------------------------------------------------------------------------

def group_label(group: str, members: list) -> str:
    return f"{group} ({len(members)})"


def rows(village: gen.Village, names: dict, group: list[Relation]) -> list[list[tuple]]:
    """The listed family members of one group as Family Member Info runs: the name (coloured by sex, a link to
    select them), what they are, and dead or departed marked."""
    import vf1_member_info as vi
    out = []
    for r in group:
        p = village.people[r.pid]
        line = [("    ", "plain", None), (vi.shown_name(names, p), vi._sex_style(p), r.pid),
                (f" - {r.term}", "plain", None)]
        status = status_words(p)
        if status:
            line.append((" " + status, "note", None))
        out.append(line)
    return out


def add_section(tab, village: gen.Village, pid: int, names: dict) -> None:
    """Put the Relationships heading, its dropdown and the chosen group's family members at the end of the
    Family Member Info tab's text (tab: vf1_member_info.VillagerInfoTab, its text still editable)."""
    import tkinter as tk
    from tkinter import ttk
    text = tab.text
    old = getattr(tab, "rel_combo", None)
    if old is not None:
        try:
            old.destroy()
        except tk.TclError:
            pass
    tab.rel_combo = None
    text.insert("end", "\n")
    text.insert("end", "Relationships", ("heading",))
    text.insert("end", "\n")
    groups = relations_for(village).groups(pid)
    if not groups:
        text.insert("end", "    None recorded\n", ("note",))
        return
    labels = [group_label(g, members) for g, members in groups]
    keep = getattr(tab, "rel_group", None)
    index = next((k for k, (g, _m) in enumerate(groups) if g == keep), 0)
    combo = ttk.Combobox(text, state="readonly", values=labels, width=34, font=("Segoe UI", 10))
    combo.current(index)
    tab.rel_combo = combo
    tab.rel_groups = groups
    text.window_create("end", window=combo, padx=4)
    text.insert("end", "\n")
    text.mark_set("relationships", "end-1c")
    text.mark_gravity("relationships", "left")

    def scroll(event):          # the wheel scrolls the tab, never changes the chosen group
        text.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"
    combo.bind("<MouseWheel>", scroll)
    combo.bind("<<ComboboxSelected>>", lambda _e: _show_group(tab, village, names, combo.current()))
    _list_group(tab, village, names, index)


def _show_group(tab, village: gen.Village, names: dict, index: int) -> None:
    text = tab.text
    text.configure(state="normal")
    text.delete("relationships", "end")
    _list_group(tab, village, names, index)
    text.configure(state="disabled")


def _list_group(tab, village: gen.Village, names: dict, index: int) -> None:
    text = tab.text
    group, members = tab.rel_groups[index]
    tab.rel_group = group
    for line in rows(village, names, members):
        for words, style, pid in line:
            tags = style.split("+")
            if pid is not None:
                tag = f"go{len(tab.links)}"
                tab.links[tag] = pid
                text.tag_bind(tag, "<Button-1>", lambda _e, q=pid: tab._go(q))
                tags += ["link", tag]
            text.insert("end", words, tuple(tags))
        text.insert("end", "\n")
