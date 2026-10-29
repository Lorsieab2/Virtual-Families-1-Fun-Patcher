"""The Family Member Info tab's Relationships (a port of the Virtual Villagers Fun Patcher v1.35.85): every
relationship the recorded parents prove, gendered, with greats, cousin degrees and removals, half- and double
forms, twins, partners (spouses too), in-laws and steps; never through a parent no record names."""
import random
import sys
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))

import vf1_family_tree as ft  # noqa: E402
import vf1_genealogy as gen  # noqa: E402
import vf1_relationships as rel  # noqa: E402
import vf1_member_info as vi  # noqa: E402

P = gen.Person
M, F = "Male", "Female"


def person(pid, name, sex, father=None, mother=None, **kw):
    kw.setdefault("alive", True)
    return P(pid, name, pid, pid, sex, 500, father=father, mother=mother, number=pid, **kw)


def clan(game: int = 1) -> gen.Village:
    people = [
        person(1, "Grandpa", M, gone="died", alive=False), person(2, "Grandma", F),
        person(3, "Opa", M), person(4, "Oma", F),
        person(5, "Pa", M, 1, 2), person(6, "Ann", F, 1, 2, gone="left", alive=False),
        person(7, "Ben", M, 1, 2, gone="left", alive=False),
        person(8, "Ma", F, 3, 4), person(9, "Cat", F, 3, 4),
        person(10, "Xavi", M, 5, 8), person(11, "Sue", F, 5, 8),
        person(12, "Tia", F, 5, 8, litter=1), person(13, "Tom", M, 5, 8, litter=1),
        person(14, "Dan", M), person(15, "Cous", F, 14, 6),
        person(16, "Dub", M, 7, 9),
        person(17, "Other", F), person(18, "Hal", M, 5, 17),
        person(19, "Zed", M), person(20, "Stepsy", F, 19, 17),
        person(21, "Ned", M), person(22, "Cece", F, 21, 15),
        person(23, "Wife", F, 25, 26), person(24, "Kid", M, 10, 23),
        person(25, "Wipa", M), person(26, "Wima", F), person(27, "Wes", M, 25, 26),
        person(28, "Kay", F), person(29, "Gina", F, 24, 28),
        person(30, "Bro", M), person(31, "Neph", M, 30, 11),
        person(32, "Mo", M, 21, 15),
    ]
    return gen.Village(game, 1, "Test", {p.id: p for p in people})


def terms(v, x) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for r in rel.Relationships(v).of(x):
        out.setdefault(r.pid, []).append(r.term)
    return out


def group_of(v, x, y) -> list[str]:
    return [r.group for r in rel.Relationships(v).of(x) if r.pid == y]


class WordsTests(unittest.TestCase):
    def test_greats_wording(self):
        f, m, n = P(1, "a", 0, 0, F), P(2, "b", 0, 0, M), P(3, "c", 0, 0)
        self.assertEqual(rel.ancestor_words(1, f)[1], "Mother")
        self.assertEqual(rel.ancestor_words(2, f)[1], "Grandmother")
        self.assertEqual(rel.ancestor_words(3, f)[1], "Great-grandmother")
        self.assertEqual(rel.ancestor_words(4, f)[1], "Great-great-grandmother")
        self.assertEqual(rel.ancestor_words(5, f), ("3× great-grandparents", "3× great-grandmother"))
        self.assertEqual(rel.ancestor_words(7, m)[1], "5× great-grandfather")
        self.assertEqual(rel.ancestor_words(2, n)[1], "Grandparent")
        self.assertEqual(rel.descendant_words(1, m)[1], "Son")
        self.assertEqual(rel.descendant_words(5, f), ("3× great-grandchildren", "3× great-granddaughter"))
        self.assertEqual(rel.aunt_words(3, f, False), ("Great-aunts and great-uncles", "Great-aunt"))
        self.assertEqual(rel.aunt_words(5, m, False)[1], "3× great-uncle")
        self.assertEqual(rel.aunt_words(2, f, True), ("Half-aunts and half-uncles", "Half-aunt"))
        self.assertEqual(rel.aunt_words(5, m, True)[1], "Half-3× great-uncle")
        self.assertEqual(rel.niece_words(4, m, False)[1], "Great-great-nephew")
        self.assertEqual(rel.aunt_words(2, n, False)[1], "Aunt or uncle")

    def test_cousin_degree_and_removal_words(self):
        self.assertEqual(rel.cousin_words(1, 0, False, False), ("First cousins", "First cousin"))
        self.assertEqual(rel.cousin_words(2, 1, False, False)[1], "Second cousin once removed")
        self.assertEqual(rel.cousin_words(3, 2, False, False)[1], "Third cousin twice removed")
        self.assertEqual(rel.cousin_words(1, 3, False, False)[1], "First cousin 3 times removed")
        self.assertEqual(rel.cousin_words(12, 0, False, False)[1], "12th cousin")
        self.assertEqual(rel.cousin_words(1, 0, True, False), ("Half-first cousins", "Half-first cousin"))
        self.assertEqual(rel.cousin_words(1, 0, False, True)[1], "Double first cousin")


class RelationshipTests(unittest.TestCase):
    def test_every_kind_gendered(self):
        v = clan()
        t = terms(v, 10)                                                    # Xavi
        self.assertEqual(t[5], ["Father"])
        self.assertEqual(t[8], ["Mother"])
        self.assertEqual(t[1], ["Grandfather"])
        self.assertEqual(t[4], ["Grandmother"])
        self.assertEqual(t[11], ["Sister"])
        self.assertEqual(t[18], ["Half-brother"])
        self.assertEqual(t[6], ["Aunt"])
        self.assertEqual(t[7], ["Uncle"])
        self.assertEqual(t[15], ["First cousin"])
        self.assertEqual(t[22], ["First cousin once removed"])
        self.assertEqual(t[31], ["Nephew"])
        self.assertEqual(t[24], ["Son"])
        self.assertEqual(t[29], ["Granddaughter"])
        self.assertEqual(t[23], ["Partner"])
        self.assertNotIn(14, t)                                             # Dan: an aunt's partner only
        kid = terms(v, 24)
        self.assertEqual(kid[6], ["Great-aunt"])                            # a grandparent's sister
        self.assertEqual(kid[18], ["Half-uncle"])
        self.assertEqual(kid[22], ["Second cousin"])
        self.assertEqual(kid[15], ["First cousin once removed"])
        self.assertEqual(kid[1], ["Great-grandfather"])
        self.assertEqual(terms(v, 29)[1], ["Great-great-grandfather"])
        self.assertEqual(terms(v, 1)[29], ["Great-great-granddaughter"])
        self.assertEqual(terms(v, 6)[24], ["Great-nephew"])
        self.assertEqual(terms(v, 6)[10], ["Nephew"])

    def test_three_greats_on_a_long_line(self):
        people = [person(1, "A1", F)] + [person(k, f"A{k}", M if k % 2 else F, mother=k - 1) for k in range(2, 9)]
        v = gen.Village(3, 1, "Line", {p.id: p for p in people})
        t = terms(v, 8)
        self.assertEqual(t[3], ["3× great-grandfather"])
        self.assertEqual(t[2], ["4× great-grandmother"])
        self.assertEqual(t[1], ["5× great-grandmother"])
        self.assertEqual(terms(v, 1)[6], ["3× great-granddaughter"])

    def test_cousin_degree_and_removal(self):
        # Two lines down from one couple, of different lengths.
        people = [person(1, "Root", M), person(2, "Rootess", F)]
        left = [person(3, "L1", M, 1, 2), person(4, "L2", F, mother=None, father=3),
                person(5, "L3", M, father=4), person(6, "L4", F, father=5)]
        right = [person(7, "R1", F, 1, 2), person(8, "R2", M, mother=7), person(9, "R3", F, mother=8),
                 person(10, "R4", M, mother=9), person(11, "R5", F, father=10)]
        v = gen.Village(4, 1, "Lines", {p.id: p for p in people + left + right})
        self.assertEqual(terms(v, 4)[8], ["First cousin"])
        self.assertEqual(terms(v, 5)[9], ["Second cousin"])
        self.assertEqual(terms(v, 6)[10], ["Third cousin"])
        self.assertEqual(terms(v, 4)[9], ["First cousin once removed"])
        self.assertEqual(terms(v, 4)[10], ["First cousin twice removed"])
        self.assertEqual(terms(v, 4)[11], ["First cousin 3 times removed"])
        self.assertEqual(terms(v, 6)[11], ["Third cousin once removed"])
        self.assertEqual(group_of(v, 6, 11), ["Third cousins once removed"])

    def test_half_and_full(self):
        v = clan()
        self.assertEqual(group_of(v, 10, 11), ["Full siblings"])
        self.assertEqual(group_of(v, 10, 18), ["Half-siblings"])
        # Half through a single shared grandparent: Hal's child and Xavi's son are half-first cousins.
        v.people[44] = person(44, "Hela", F)
        v.people[40] = person(40, "Hali", F, 18, 44)
        self.assertEqual(terms(v, 24)[40], ["Half-first cousin"])
        self.assertEqual(terms(v, 40)[10], ["Half-uncle"])
        self.assertEqual(terms(v, 10)[40], ["Half-niece"])
        self.assertEqual(terms(v, 24)[6], ["Great-aunt"])                    # through both grandparents

    def test_twins_and_triplets(self):
        v = clan()
        self.assertEqual(terms(v, 12)[13], ["Twin brother"])
        self.assertEqual(terms(v, 13)[12], ["Twin sister"])
        self.assertEqual(group_of(v, 12, 13), ["Twins"])
        self.assertEqual(terms(v, 12)[10], ["Brother"])                      # not of their birth
        v.people[41] = person(41, "Tre", M, 5, 8, litter=1)
        self.assertEqual(terms(v, 12)[41], ["Triplet brother"])
        self.assertEqual(group_of(v, 41, 12), ["Triplets"])
        # A baby on the way is not born yet: never listed.
        v.people[42] = P(42, "Upcoming child", -1, -1, upcoming=True, father=5, mother=8)
        self.assertNotIn(42, terms(v, 10))

    def test_double_cousins(self):
        v = clan()
        # Ben (Pa's brother) and Cat (Ma's sister): their son is Xavi's double first cousin.
        self.assertEqual(terms(v, 10)[16], ["Double first cousin"])
        self.assertEqual(group_of(v, 16, 11), ["Double first cousins"])
        self.assertEqual(terms(v, 10)[15], ["First cousin"])                 # Ann's: one side only

    def test_in_laws_and_steps(self):
        v = clan()
        x = terms(v, 10)
        self.assertEqual(x[25], ["Father-in-law"])
        self.assertEqual(x[26], ["Mother-in-law"])
        self.assertEqual(x[27], ["Brother-in-law"])                          # a partner's brother
        self.assertEqual(x[30], ["Brother-in-law"])                          # a sister's partner
        self.assertEqual(x[28], ["Daughter-in-law"])                         # a son's partner
        self.assertEqual(x[17], ["Step-mother"])                             # Pa's other partner
        self.assertEqual(x[20], ["Step-sister"])                             # hers by Zed
        self.assertNotIn(19, x)
        self.assertEqual(group_of(v, 10, 17), ["Step-parents"])
        self.assertEqual(terms(v, 17)[10], ["Step-son"])
        self.assertEqual(terms(v, 23)[11], ["Sister-in-law"])                # a partner's sister
        self.assertEqual(terms(v, 25)[10], ["Son-in-law"])
        # Hal shares Pa with Xavi: a half-brother, never also a step-brother.
        self.assertEqual(x[18], ["Half-brother"])

    def test_several_relationships_to_one_person(self):
        v = clan()
        v.people[43] = P(43, "Babe", 43, 43, M, 0, True, father=10, mother=15, number=43)   # Xavi and Cous
        t = terms(v, 10)
        self.assertEqual(sorted(t[15]), ["First cousin", "Partner"])
        groups = dict(rel.Relationships(v).groups(10))
        self.assertIn(15, [r.pid for r in groups["Partners"]])
        self.assertIn(15, [r.pid for r in groups["First cousins"]])
        # A close-knit line: a grandfather who is also the father.
        close = [person(1, "Old", M), person(2, "Her", F), person(3, "Dau", F, 1, 2), person(4, "Kin", M, 1, 3)]
        v2 = gen.Village(2, 1, "Close", {p.id: p for p in close})
        self.assertTrue({"Father", "Grandfather"} <= set(terms(v2, 4)[1]))
        self.assertTrue({"Mother", "Half-sister"} <= set(terms(v2, 4)[3]))       # Dau is Old's child too
        # Lines that meet again lower down repeat a relationship, never add one: the children of a brother
        # and sister's son are siblings only -- but the brother and sister's own children are also cousins.
        people = [person(1, "Root", M), person(2, "Roota", F), person(3, "Bo", M, 1, 2), person(4, "Bi", F, 1, 2),
                  person(5, "Mid", M, 3, 4), person(6, "Mida", F), person(7, "Ex", M, 5, 6), person(8, "Wy", F, 5, 6)]
        v3 = gen.Village(3, 1, "Knit", {p.id: p for p in people})
        self.assertEqual(terms(v3, 7)[8], ["Sister"])
        self.assertEqual(terms(v3, 7)[3], ["Grandfather", "Great-uncle"])     # also his grandmother's brother
        people.append(person(9, "Mod", F, 3, 4))
        v4 = gen.Village(3, 1, "Knit", {p.id: p for p in people})
        # The owner, 2026-10-28: a brother and sister's children are siblings AND double first cousins.
        self.assertEqual(sorted(terms(v4, 5)[9]), ["Double first cousin", "Sister"])
        self.assertEqual(sorted(terms(v4, 9)[5]), ["Brother", "Double first cousin"])
        self.assertEqual(terms(v4, 7)[8], ["Sister"])          # their grandchildren by Mid: siblings only

    def test_double_first_cousins_whenever_each_parent_is_a_sibling_of_one_of_the_others(self):
        # Bo, Bi and Bu are siblings.  Xo is Bo and Bi's, Yu is Bu and Bi's: half-siblings through Bi, and
        # double first cousins too (Bo is Bi's brother, Bi is Bu's sister).
        people = [person(1, "Root", M), person(2, "Roota", F), person(3, "Bo", M, 1, 2), person(4, "Bi", F, 1, 2),
                  person(5, "Bu", M, 1, 2), person(6, "Xo", M, 3, 4), person(7, "Yu", F, 5, 4)]
        v = gen.Village(1, 1, "Knit", {p.id: p for p in people})
        self.assertEqual(sorted(terms(v, 6)[7]), ["Double first cousin", "Half-sister"])
        # Two sibling pairs who share no parent: double first cousins only (the clan's Ben and Cat).
        self.assertEqual(terms(clan(), 10)[16], ["Double first cousin"])
        # Only one side related: a first cousin, not double.
        more = people + [person(8, "Out", F), person(9, "Zo", F, 5, 8)]
        v2 = gen.Village(4, 1, "Knit", {p.id: p for p in more})
        self.assertEqual(terms(v2, 6)[9], ["First cousin", "Step-sister"])   # Bu is Bi's partner too

    def test_an_unknown_parent_links_nobody(self):
        # Virtual Families 1 has no default father: a child whose father no record names has none, and two
        # such children are half-siblings only through the mother they share.
        people = [person(2, "Ma1", F), person(3, "Ma2", F), person(4, "Kai", M, None, 2), person(5, "Lea", F, None, 3),
                  person(6, "Rua", F, None, 2)]
        v = gen.Village(1, 1, "T", {p.id: p for p in people})
        t = terms(v, 4)
        self.assertNotIn(5, t)
        self.assertEqual(t[2], ["Mother"])
        self.assertEqual(t[6], ["Half-sister"])

    def test_spouses_are_partners_with_or_without_a_child(self):
        # A generation's couple in the save's Family Tree, and a spouse the Family History log names, are
        # partners even before (or without) a child: so their in-laws and steps follow.
        v = clan()
        v.people[60] = person(60, "Bride", F)
        v.people[61] = person(61, "Ex", F)
        v.people[61].partner = 27                                             # Wes's earlier spouse (the log)
        v.couples = {3: [27, 60]}                                             # Wes married Bride (the save)
        r = rel.Relationships(v)
        self.assertEqual([x.term for x in r.of(27) if x.pid == 60], ["Partner"])
        self.assertEqual([x.term for x in r.of(27) if x.pid == 61], ["Partner"])
        self.assertEqual([x.term for x in r.of(60) if x.pid == 23], ["Sister-in-law"])   # Wes's sister
        self.assertEqual([x.term for x in r.of(23) if x.pid == 60], ["Sister-in-law"])   # a sibling's partner
        self.assertEqual([x.term for x in r.of(25) if x.pid == 60], ["Daughter-in-law"])  # a son's partner

    def test_dead_and_departed_marked(self):
        v = clan()
        r = rel.Relationships(v)
        out = vi.plain_text(rel.rows(v, {}, r.of(10)))
        self.assertIn("Grandpa - Grandfather (deceased)", out)
        self.assertIn("Ann - Aunt (no longer in the house)", out)
        self.assertIn("Ben - Uncle (no longer in the house)", out)
        self.assertIn("Grandma - Grandmother\n", out + "\n")
        # The names as the tree shows them.
        self.assertIn("Ann II - Aunt", vi.plain_text(rel.rows(v, {6: "Ann II"}, r.of(10))))

    def test_dropdown_groups_and_counts(self):
        v = clan()
        groups = rel.Relationships(v).groups(10)
        labels = [rel.group_label(g, m) for g, m in groups]
        self.assertEqual(labels[0], "Partners (1)")
        self.assertIn("Parents (2)", labels)
        self.assertIn("Full siblings (3)", labels)                            # Sue, Tia, Tom
        self.assertNotIn("Twins (2)", labels)                                 # Xavi is not one of them
        self.assertTrue(all(m for _g, m in groups))
        self.assertLess(labels.index("Parents (2)"), labels.index("Grandparents (4)"))

    def test_a_256_member_family_is_quick(self):
        # One father siring much of the village; the second village close-knit over some 40 generations
        # (each child from the latest dozen men and women).
        for seed, sire, recent in ((7, 0.5, None), (9, 0.2, 12), (10, 1.0, 12)):
            rnd = random.Random(seed)
            people = {1: person(1, "Sire", M)}
            women, men = [], [1]
            for k in range(2, 6):
                people[k] = person(k, f"W{k}", F)
                women.append(k)
            for pid in range(6, 257):
                mother = rnd.choice(women[-recent:] if recent else women)
                father = 1 if rnd.random() < sire else rnd.choice(men[-recent:] if recent else men)
                sex = rnd.choice((M, F))
                people[pid] = person(pid, f"V{pid}", sex, father, mother)
                (men if sex == M else women).append(pid)
            v = gen.Village(3, 1, "Big", people)
            start = time.perf_counter()
            r = rel.relations_for(v)
            worst = 0.0
            for x in rnd.sample(sorted(people), 40):                          # 40 of them: a quick test
                one = time.perf_counter()
                r.of(x)
                worst = max(worst, time.perf_counter() - one)
            self.assertLess(worst, 0.5, seed)                                  # each member: well under a second
            self.assertLess(time.perf_counter() - start, 10.0, seed)
            again = time.perf_counter()
            self.assertIs(rel.relations_for(v), r)                            # cached per tree load
            r.of(256)
            self.assertLess(time.perf_counter() - again, 0.5, seed)
            self.assertTrue(r.of(256))


class TabTests(unittest.TestCase):
    def test_family_member_info_shows_the_dropdown_and_selects_by_name(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        root.withdraw()
        try:
            from tkinter import ttk
            ed = SimpleNamespace(notebook=ttk.Notebook(root), village=clan(), edits=ft.Edits(), game=1,
                                 present={}, selected=[10], lay=SimpleNamespace(names={6: "Ann II"}))
            tab = vi.VillagerInfoTab(ed)
            shown = tab.text.get("1.0", "end")
            self.assertIn("Relationships", shown)
            combo = tab.rel_combo
            values = list(combo.cget("values"))
            self.assertEqual(values[0], "Partners (1)")
            self.assertIn("Wife - Partner", shown)
            k = values.index("Aunts and uncles (3)")
            combo.current(k)
            combo.event_generate("<<ComboboxSelected>>")
            root.update()
            shown = tab.text.get("1.0", "end")
            self.assertIn("Ann II - Aunt (no longer in the house)", shown)
            self.assertNotIn("Wife - Partner", shown)
            self.assertIn(6, tab.links.values())
            with mock.patch.object(vi, "go_to") as go:
                tag = next(t for t, q in tab.links.items() if q == 6)
                self.assertTrue(tab.text.tk.call(tab.text._w, "tag", "bind", tag, "<Button-1>"))
                tab._go(6)
                go.assert_called_once_with(ed, 6)
            # The chosen group stays when another member with that group is selected.
            ed.selected = [11]
            tab.refresh()
            self.assertEqual(tab.rel_combo.get(), "Aunts and uncles (3)")
            # A member with no recorded relationships says so.
            ed.selected = [14]
            ed.village.people[14].number = 14
            tab.refresh()
            ed.selected = [19]
            tab.refresh()
            self.assertIn("Step-children", tab.rel_combo.get() + " ".join(tab.rel_combo.cget("values")))
            ed.village.people[50] = person(50, "Loner", M)
            ed.selected = [50]
            tab.refresh()
            self.assertIn("Relationships\n    None recorded", tab.text.get("1.0", "end"))
            ed.selected = []
            tab.refresh()
            self.assertIn(vi.HINT, tab.text.get("1.0", "end"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
