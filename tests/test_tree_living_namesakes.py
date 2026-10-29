"""Two living family members with the same name and looks are two people (a port of the Virtual Villagers Fun
Patcher v1.35.85, "show both, link by age"): each with their own age, parents, number and tree edits.

In Virtual Families 1 the family itself never mixed them up -- each is their own seat in the save's Family Tree,
and a child's parents are the couple of their generation's record, never a name -- so no parent is ever chosen
by name and the tree never has to ask "Which family member is the parent?".  What did mix them up was the tree's
edits, kept under "name|head|body": now each living namesake's are their own (the seat tells them apart), and an
older edit that cannot be told to be either one's is kept in the file but shown on nobody.  Also here: a title
line the player retyped keeps their words with the counts and date of the tree now.  Synthetic saves only.
"""
from __future__ import annotations

import re

import vf1_family_tree as ft
import vf1_genealogy as gen
import vf1_save as vs
from test_vf1_save import build_save, family_record, peep, villager_record


def namesake_save(second_hal_dead: bool = False) -> bytes:
    """Ann (founder) and Bob; their children Cal (the heir) and Bo; Cal married Gia and they have two sons both
    called Hal with the same head and body (8, 9), and a son Bo with his uncle's name and looks."""
    villagers = {
        0: villager_record(name="Cal", sex=0, age=900, head=4, body=5),
        1: villager_record(name="Gia", sex=1, age=880, head=6, body=7),
        2: villager_record(name="Hal", sex=0, age=300, head=8, body=9, p1="Joey", p2="Gia"),
        3: villager_record(name="Hal", sex=0, age=120, head=8, body=9, p1="Joey", p2="Gia",
                           health=0 if second_hal_dead else 100),
        4: villager_record(name="Bo", sex=0, age=860, head=3, body=3, p1="Joey", p2="Ann"),
        5: villager_record(name="Bo", sex=0, age=60, head=3, body=3, p1="Joey", p2="Gia"),
        6: villager_record(name="Ann", sex=1, age=1300, head=1, body=2),
    }
    gen1 = family_record(peep("Ann", sex=1, head=1, body=2, slot=6, index=-1), peep("Bob", sex=0, head=3, body=3),
                         [peep("Cal", head=4, body=5, slot=9), peep("Bo", head=3, body=3, slot=4)])
    gen2 = family_record(peep("Cal", head=4, body=5, slot=0, index=0), peep("Gia", sex=1, head=6, body=7, slot=1),
                         [peep("Hal", head=8, body=9, slot=2), peep("Hal", head=8, body=9, slot=3),
                          peep("Bo", head=3, body=3, slot=5)])
    return build_save(villagers, [gen1, gen2], family="Namesakes")


def family(data: bytes) -> gen.Village:
    v = gen.build_family(vs.parse_save(data), 1, data=data)
    gen.finish(v)
    return v


def named(v: gen.Village, name: str) -> list[gen.Person]:
    return sorted((p for p in v.people.values() if p.name == name), key=lambda p: -(p.age or 0))


def test_two_living_namesakes_are_two_people_with_their_own_age_parents_and_number():
    v = family(namesake_save())
    old_hal, young_hal = named(v, "Hal")
    cal, gia = named(v, "Cal")[0], named(v, "Gia")[0]
    assert old_hal.id != young_hal.id and old_hal.alive and young_hal.alive
    assert (old_hal.years, young_hal.years) == (15, 6)
    assert old_hal.number != young_hal.number and None not in (old_hal.number, young_hal.number)
    assert (old_hal.father, old_hal.mother) == (young_hal.father, young_hal.mother) == (cal.id, gia.id)
    assert (old_hal.namesake_rank, young_hal.namesake_rank) == (1, 2)
    # The uncle and the nephew of one name and look: each with the parents their generation's record gives.
    uncle, nephew = named(v, "Bo")
    ann = named(v, "Ann")[0]
    assert uncle.mother == ann.id and nephew.mother == gia.id and nephew.father == cal.id
    # Each one's edits are their own: told apart by their seat in the save's Family Tree, not their age.
    keys = {ft.entry_key(v, p) for p in (old_hal, young_hal, uncle, nephew)}
    assert len(keys) == 4
    assert ft.entry_key(v, old_hal) == f"Hal|8|9|{old_hal.seat}"
    # A family member with no living namesake keeps the plain key, as always.
    assert ft.entry_key(v, cal) == "Cal|4|5"


def test_a_childs_parent_is_never_chosen_by_name_so_nothing_is_asked():
    v = family(namesake_save())
    uncle, nephew = named(v, "Bo")
    # Nobody's parent is a Bo, though two living Bos could be by age: the save's record says who the parents are.
    assert not [p for p in v.people.values() if uncle.id in (p.father, p.mother) or nephew.id in (p.father, p.mother)]
    assert not getattr(v, "parent_questions", [])


def test_old_shared_edits_are_kept_but_shown_on_nobody():
    v = family(namesake_save())
    edits = ft.Edits()
    edits.entries["Hal|8|9"] = {"generation": 3, "lines": ["shared from before"]}
    assert ft.settle_namesakes(v, edits)
    assert "Hal|8|9" not in edits.entries
    assert edits.entries[ft.PARKED + "Hal|8|9"] == {"generation": 3, "lines": ["shared from before"]}
    for p in named(v, "Hal"):
        assert ft.entry_key(v, p) not in edits.entries
    # Kept in the file across a save and a load, and settling again changes nothing.
    again = ft.Edits.from_data(edits.to_data())
    assert again.entries == edits.entries and again.namesakes == edits.namesakes
    assert not ft.settle_namesakes(v, again)


def test_edits_made_while_alone_stay_with_that_family_member():
    # Before the younger Hal was born (here: while he is dead and the elder the only living Hal), the elder's
    # edits are under the plain key and recorded as his; when a living namesake appears they stay his.
    alone = family(namesake_save(second_hal_dead=True))
    edits = ft.Edits()
    edits.entries["Hal|8|9"] = {"lines": ["the elder's"]}
    ft.settle_namesakes(alone, edits)
    elder = named(alone, "Hal")[0]
    assert edits.key_owners == {"Hal|8|9": elder.seat}
    both = family(namesake_save())
    ft.settle_namesakes(both, edits)
    old_hal, young_hal = named(both, "Hal")
    assert edits.entries[ft.entry_key(both, old_hal)] == {"lines": ["the elder's"]}
    assert ft.entry_key(both, young_hal) not in edits.entries
    # The younger one's own edit, then he is gone again: the elder takes back his own under the plain key.
    edits.entries[ft.entry_key(both, young_hal)] = {"lines": ["the younger's"]}
    ft.settle_namesakes(alone, edits)
    assert edits.entries["Hal|8|9"] == {"lines": ["the elder's"]}
    assert {"lines": ["the younger's"]} in [e for k, e in edits.entries.items() if k.startswith(ft.PARKED)]


def test_the_tree_draws_both_namesakes():
    v = family(namesake_save())
    edits = ft.Edits()
    ft.arrange(v, edits)
    lay = ft.layout(v, edits)
    for p in named(v, "Hal") + named(v, "Bo"):
        assert p.id in lay.x


def test_a_retyped_title_keeps_its_words_and_refreshes_the_counts_and_date():
    v = family(namesake_save())
    edits = ft.Edits()
    edits.title = "Our Namesakes -- 3 family members known, 1 living -- 2020-01-02 03:04"
    edits.subtitle = "Kept by me"
    ft.arrange(v, edits)
    lay = ft.layout(v, edits)
    first, second = ft.title_lines(lay, gen.GAME_TITLE)
    known, living = len(v.known()), len(v.living())
    assert first.startswith(f"Our Namesakes -- {known} family members known, {living} living -- ")
    assert "2020-01-02" not in first and re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", first)
    assert second == "Kept by me"
    assert ft.fresh_title(lay, "") == ""
    # The tree's own line says the same counts.
    assert f"{known} family members known, {living} living" in ft.default_title_lines(lay, gen.GAME_TITLE)[1]
