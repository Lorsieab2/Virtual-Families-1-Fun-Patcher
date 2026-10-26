"""The Family Tree Maker's memory (patcher/vf1_tree_memory.py) and the Family History log (vf1_family_history.py):
members the save drops -- a divorced spouse, a spouse who died with no children, a first spouse after a remarriage,
a founder who died childless -- stay on the tree once the tree has seen them; dead children keep their place; the
log fills in what happened between two openings.  Each save below is what the game itself writes at that step
(the code traced in vf1_tree_memory's docstring)."""
from __future__ import annotations

import json

import vf1_family_history as fh
import vf1_genealogy as gen
import vf1_tree_memory as mem
from test_family_tree import by_name, snapshot
from test_vf1_save import build_save, family_record, peep, villager_record


def save(tmp_path, villagers: dict, records: list, **kw) -> gen.Village:
    (tmp_path / "Virtual Families1.ldw").write_bytes(build_save(villagers, records, **kw))
    return gen.load_village(tmp_path, gen.GAME, 1, remember=True)


ANN = dict(name="Ann", sex=1, age=600, head=1, body=1)
BOB = dict(name="Bob", sex=0, age=620, head=2, body=2)
DAN = dict(name="Dan", sex=0, age=640, head=3, body=3)
CAL = dict(name="Cal", sex=0, age=100, head=4, body=4, p1="Joey", p2="Ann")
EVE = dict(name="Eve", sex=1, age=40, head=5, body=5, p1="Joey", p2="Ann")


def p_ann(slot=0, index=-1):
    return peep("Ann", sex=1, head=1, body=1, slot=slot, index=index)


def test_divorce_then_remarriage_keeps_the_first_spouse_and_his_child(tmp_path):
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB), 2: villager_record(**CAL)},
             [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [peep("Cal", head=4, body=4, slot=2)])])
    assert by_name(v, "Cal").father == by_name(v, "Bob").id
    # Divorce Spouse: parent 2's record cleared (slot -1), Bob out of the house (present 0, alive).
    gone = bytes(peep("", used=0, slot=-1))
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB, present=0), 2: villager_record(**CAL)},
             [family_record(p_ann(), gone, [peep("Cal", head=4, body=4, slot=2)])])
    bob = by_name(v, "Bob")
    assert not bob.alive and bob.gone == "left" and bob.event == "Divorce Spouse"
    assert any(u.startswith("Divorced") for u in bob.unknowns)
    # Remarriage: UpdateParents writes Dan into parent 2; Eve is born.
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB, present=0), 2: villager_record(**CAL),
                        3: villager_record(**DAN), 4: villager_record(**EVE)},
             [family_record(p_ann(), peep("Dan", head=3, body=3, slot=3),
                            [peep("Cal", head=4, body=4, slot=2), peep("Eve", sex=1, head=5, body=5, slot=4)])])
    bob, dan, ann = by_name(v, "Bob"), by_name(v, "Dan"), by_name(v, "Ann")
    assert by_name(v, "Cal").father == bob.id and by_name(v, "Cal").mother == ann.id
    assert by_name(v, "Eve").father == dan.id
    assert bob.generation == dan.generation == ann.generation == 1
    data = json.loads(mem.tree_file(tmp_path, 1).read_text("utf-8"))
    seats = {m["name"]: m["seat"] for m in data["members"]["list"]}
    assert seats["Dan"] == "g1.p2" and seats["Bob"].startswith("g1.p2#")


def test_a_spouse_who_dies_with_no_children_stays_dead_on_the_tree(tmp_path):
    save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB)},
         [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [])])
    # ReportDeath with no children: parent 2 marked unused; his record dead (health 0, cause 2).
    rec = bytearray(family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), []))
    rec[0xDC + 0x1A] = 0
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB, health=0, cause=2)}, [bytes(rec)])
    bob = by_name(v, "Bob")
    assert bob.gone == "died" and not bob.alive and bob.how == "Married in"


def test_a_founder_who_dies_with_no_children_is_kept_when_the_spouse_takes_her_place(tmp_path):
    save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB)},
         [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [])])
    # ReportDeath copies parent 2 over parent 1 (child index 0, never written for a parent 2).
    v = save(tmp_path, {0: villager_record(**ANN, health=0), 1: villager_record(**BOB)},
             [family_record(peep("Bob", head=2, body=2, slot=1, index=0), bytes(peep("", used=0)), [])])
    ann, bob = by_name(v, "Ann"), by_name(v, "Bob")
    assert ann.gone == "died" and bob.alive and bob.how == "Married in" and bob.generation == ann.generation == 1


def test_the_save_alone_says_who_married_into_a_founders_place(tmp_path):
    (tmp_path / "Virtual Families1.ldw").write_bytes(build_save(
        {1: villager_record(**BOB)}, [family_record(peep("Bob", head=2, body=2, slot=1, index=0),
                                                    bytes(peep("", used=0)), [])]))
    v = gen.load_village(tmp_path, gen.GAME, 1)
    bob = by_name(v, "Bob")
    assert bob.how == "Married in" and gen.is_arrival(bob) and "no longer names" in bob.unknowns[0]


def test_a_dead_child_keeps_their_place_with_their_age_and_cause(tmp_path):
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB),
                        2: villager_record(**CAL, health=0, cause=0, present=0)},
             [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [peep("Cal", head=4, body=4, slot=-1)])])
    cal = by_name(v, "Cal")
    assert cal.gone == "died" and cal.years == 5 and "Disease" in cal.cause and "unconfirmed" in cal.cause
    assert cal.father == by_name(v, "Bob").id


def test_someone_seen_once_then_gone_is_kept(tmp_path):
    zed = dict(name="Zed", sex=0, age=300, head=9, body=9)
    tree = [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [])]
    save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB), 5: villager_record(**zed)}, tree)
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB)}, tree)
    zed = by_name(v, "Zed")
    assert not zed.alive and zed.gone == "left" and any("No longer in the save" in u for u in zed.unknowns)


def test_new_looks_or_a_new_name_never_split_a_spouse(tmp_path):
    save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB)},
         [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [])])
    v = save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**{**BOB, "name": "Robert", "head": 7})},
             [family_record(p_ann(), peep("Robert", head=7, body=2, slot=1), [])])
    assert [p.name for p in v.people.values()] == ["Ann", "Robert"]
    data = json.loads(mem.tree_file(tmp_path, 1).read_text("utf-8"))
    robert = next(m for m in data["members"]["list"] if m["name"] == "Robert")
    assert robert["former"] == ["Bob"] and "changed" in robert


def test_a_new_family_starts_a_fresh_tree_file_and_keeps_the_old_one(tmp_path):
    save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB)},
         [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [])])
    v = save(tmp_path, {0: villager_record(name="Zoe", sex=1, age=500, head=8, body=8)},
             [family_record(peep("Zoe", sex=1, head=8, body=8, slot=0, index=-1), bytes(peep("", used=0)), [])])
    assert [p.name for p in v.people.values()] == ["Zoe"] and any("new family" in n for n in v.notes)
    kept = [p.name for p in mem.tree_file(tmp_path, 1).parent.iterdir()]
    assert any("earlier family" in name for name in kept)


def test_remembering_never_writes_the_save_and_keeps_the_edits(tmp_path):
    tree = [family_record(p_ann(), peep("Bob", head=2, body=2, slot=1), [])]
    save(tmp_path, {0: villager_record(**ANN), 1: villager_record(**BOB)}, tree)
    path = mem.tree_file(tmp_path, 1)
    data = mem.read_tree_file(path)
    data["edits"] = {"format": 1, "title": "Ours"}
    mem.write_tree_file(path, data)
    before = (tmp_path / "Virtual Families1.ldw").read_bytes()
    gen.load_village(tmp_path, gen.GAME, 1, remember=True)
    assert (tmp_path / "Virtual Families1.ldw").read_bytes() == before
    assert mem.read_tree_file(path)["edits"] == {"format": 1, "title": "Ours"}
    # Without remember, nothing at all is written.
    snap = snapshot(tmp_path)
    gen.load_village(tmp_path, gen.GAME, 1)
    assert snapshot(tmp_path) == snap


# ---------------------------------------------------------------- the Family History log
def rec(when, heading, *lines):
    """One record as vf1logs.dll writes it (the Virtual Villagers layout)."""
    return f"[{when}] {heading}\r\n" + "".join(f"{line}\r\n" for line in lines) + "\r\n"


def who(label, name, sex, age=None, head=1, body=1, indent="  "):
    lines = [f"{indent}{label}: {name}"]
    if age is not None:
        lines.append(f"{indent}  Age: {age}")
    return lines + [f"{indent}  Sex: {sex}", f"{indent}  Head: {head}", f"{indent}  Body: {body}"]


HISTORY = "Family: Testfamily (Save 1)\r\n" + "".join([
    rec("2026-10-20 10:05:00", "Marriage 1", *who("Family member", "Ann", "Female", 21), *who("Married", "Bob", "Male", 22),
        "  Current spouse of Ann: Bob", "  Generation: 1"),
    rec("2026-10-20 12:00:00", "Birth 1", "  Child: Cal", "    Sex: Male", "    Head: 4", "    Body: 4", "  Mother: Ann",
        "    Head: 1", "    Body: 1", "  Father: Bob", "    Head: 2", "    Body: 2", "  Born as: Twin", "  Generation: 1"),
    rec("2026-10-20 12:00:00", "Birth 2", "  Child: Cia", "    Sex: Female", "    Head: 6", "    Body: 6", "  Mother: Ann",
        "    Head: 1", "    Body: 1", "  Father: Bob", "    Head: 2", "    Body: 2", "  Born as: Twin", "  Generation: 1"),
    rec("2026-10-20 13:00:00", "Divorce 1", "  Family member: Ann", "    Sex: Female", "    Head: 1", "    Body: 1",
        *who("Divorced", "Bob", "Male", 23), "  How: Divorce Spouse", "  Current spouse of Ann: (none)", "  Generation: 1"),
    rec("2026-10-20 14:00:00", "Marriage 2", *who("Family member", "Ann", "Female", 25), *who("Married", "Dan", "Male", 30),
        "  Remarried: yes", "  Earlier spouse: Bob (divorced)", "  Current spouse of Ann: Dan", "  Generation: 1"),
    rec("2026-10-20 15:00:00", "Random Event 1", "  Popup Event: The Little Visitor", "  Choice: A", "  Generation: 1"),
    rec("2026-10-20 15:00:00", "Arrived 1", "  Name: Kim", "  Age at arrival: 3", "  Sex: Female", "  Head: 7", "  Body: 7",
        "  How: Adopted (Popup Event: The Little Visitor)", "  Family role: Child", "  Generation: 1"),
    rec("2026-10-20 15:01:00", "Arrived 2", "  Name: Lou", "  Age at arrival: 4", "  Sex: Male", "  Head: 8", "  Body: 8",
        "  How: Adopted (Adopt Outside Child)", "  Family role: Child", "  Generation: 1"),
    rec("2026-10-20 15:30:00", "Random Event 2", "  Email Event: Subject: Tax Audit", "  Generation: 1"),
    rec("2026-10-20 16:00:00", "Death 1", "  Name: Cia", "  Age at death: 2", "  Sex: Female", "  Cause of death: Starvation",
        "  Head: 6", "  Body: 6", "  Family role: Child", "  Generation: 1"),
    rec("2026-10-20 16:30:00", "Family Renamed 1", "  Old name: Oldname", "  New name: Testfamily"),
])


def history_folder(tmp_path, text=HISTORY):
    path = gen.slot_root(tmp_path, 1) / "Logs" / "Family History" / "Family History 1.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(text.encode("cp1252"))
    return path


def divorced_family(tmp_path):
    kids = [peep("Cal", head=4, body=4, slot=2), peep("Cia", sex=1, head=6, body=6, slot=-1),
            peep("Kim", sex=1, head=7, body=7, slot=5), peep("Lou", head=8, body=8, slot=6)]
    (tmp_path / "Virtual Families1.ldw").write_bytes(build_save(
        {0: villager_record(**ANN), 3: villager_record(**DAN), 2: villager_record(**CAL),
         5: villager_record(name="Kim", sex=1, age=60, head=7, body=7),
         6: villager_record(name="Lou", sex=0, age=80, head=8, body=8)},
        [family_record(p_ann(), peep("Dan", head=3, body=3, slot=3), kids)]))


def labels(v, name):
    import vf1_family_tree as ft
    lay = ft.layout(v, ft.Edits())
    return ft.descriptors(lay, by_name(v, name))


def test_the_family_history_fills_in_what_the_save_lost(tmp_path):
    history_folder(tmp_path)
    divorced_family(tmp_path)
    before = snapshot(tmp_path)
    v = gen.load_village(tmp_path, gen.GAME, 1)
    assert snapshot(tmp_path) == before
    bob, cal, cia = by_name(v, "Bob"), by_name(v, "Cal"), by_name(v, "Cia")
    assert bob.how == "Married in" and bob.event == "Divorce Spouse" and bob.generation == 1 and not bob.alive
    assert bob.divorced and any("Divorced from Ann" in u for u in bob.unknowns)
    assert cal.father == bob.id and cia.father == bob.id and cal.litter is not None and cal.litter == cia.litter
    assert cia.cause == "Starvation" and cia.years == 2
    kim = by_name(v, "Kim")
    assert kim.event_title == "Popup Event: The Little Visitor" and kim.adopted
    assert by_name(v, "Lou").event == "Adopt Outside Child" and by_name(v, "Lou").adopted
    dan = by_name(v, "Dan")
    assert dan.event == "Married in" and any("married to Bob before (divorced)" in s for s in dan.sources)
    assert (bob.spouse_number, dan.spouse_number) == (1, 2) and by_name(v, "Ann").remarried
    assert v.history_events == ["2026-10-20 15:00:00: Popup Event: The Little Visitor",
                                "2026-10-20 15:30:00: Email Event: Subject: Tax Audit"]
    assert not any(n.startswith("The save keeps no history") for n in v.notes)
    assert "Email Event: Subject: Tax Audit" in gen.report(v)
    # The portrait labels, each where it applies.
    assert labels(v, "Bob") == ["Husband 1", "Divorced"]
    assert labels(v, "Dan") == ["Husband 2"]
    assert labels(v, "Ann")[:2] == ["Founder", "Remarried"]
    assert labels(v, "Cia") == ["Deceased", "Cal's twin"] or labels(v, "Cia")[0] == "Deceased"
    assert "Adopted" in labels(v, "Kim") and "Popup Event: The Little Visitor" in labels(v, "Kim")
    assert "Adopted" in labels(v, "Lou") and not any(x.startswith("Popup Event") for x in labels(v, "Lou"))


def test_without_the_log_the_tree_says_what_is_unknown(tmp_path):
    divorced_family(tmp_path)
    v = gen.load_village(tmp_path, gen.GAME, 1)
    assert "Bob" not in {p.name for p in v.people.values()}
    assert by_name(v, "Cal").litter is None and by_name(v, "Cia").cause == ""
    assert by_name(v, "Cal").father == by_name(v, "Dan").id      # the save's only couple: no earlier spouse known
    assert any(n.startswith("The save keeps no history") for n in v.notes)
    assert any(u.startswith("Adopted:") for u in by_name(v, "Kim").unknowns)
    assert labels(v, "Dan") == ["Married in"]                    # no order without the log
    assert "Adopted" in labels(v, "Kim") and not any(x.startswith("Popup Event") for x in labels(v, "Kim"))


def test_a_spouse_who_died_before_any_child_is_kept_and_drawn_as_the_spouse(tmp_path):
    import vf1_family_tree as ft
    history_folder(tmp_path, "Family: Testfamily (Save 1)\r\n" + "".join([
        rec("2026-10-20 10:05:00", "Marriage 1", *who("Family member", "Ann", "Female", 21), *who("Married", "Bob", "Male", 22),
            "  Current spouse of Ann: Bob", "  Generation: 1"),
        rec("2026-10-20 11:00:00", "Death 1", "  Name: Bob", "  Age at death: 23", "  Sex: Male", "  Cause of death: Old age",
            "  Head: 2", "  Body: 2", "  Family role: Parent (married in)", "  Generation: 1",
            "  Current spouse of Ann: (none)"),
        rec("2026-10-20 12:00:00", "Marriage 2", *who("Family member", "Ann", "Female", 25), *who("Married", "Dan", "Male", 30),
            "  Remarried: yes", "  Earlier spouse: Bob (died)", "  Current spouse of Ann: Dan", "  Generation: 1")]))
    (tmp_path / "Virtual Families1.ldw").write_bytes(build_save(
        {0: villager_record(**ANN), 3: villager_record(**DAN)},
        [family_record(p_ann(), peep("Dan", head=3, body=3, slot=3), [])]))
    v = gen.load_village(tmp_path, gen.GAME, 1)
    bob = by_name(v, "Bob")
    assert bob.gone == "died" and bob.cause == "Old age" and bob.years == 23 and bob.generation == 1
    assert bob.seat.startswith("g1.p2#log") and bob.partner == by_name(v, "Ann").id
    assert labels(v, "Bob") == ["Husband 1", "Deceased"]
    lay = ft.layout(v, ft.Edits())
    sc = ft.scene(lay, "VF1", {})
    couples = [i for i in sc.items if isinstance(i, ft.Line) and getattr(i, "name", "") == "couple"] or \
        [f for f in lay.families if {f.father, f.mother} == {bob.id, by_name(v, "Ann").id} and f.couple_y]
    assert couples, "the childless couple has its line"


def test_a_same_sex_marriage_labels_each_spouse_by_their_own_sex(tmp_path):
    history_folder(tmp_path, "Family: Testfamily (Save 1)\r\n" + "".join([
        rec("2026-10-20 10:05:00", "Marriage 1", *who("Family member", "Ann", "Female", 21),
            *who("Married", "Dora", "Female", 22, head=4, body=4), "  Current spouse of Ann: Dora", "  Generation: 1")]))
    (tmp_path / "Virtual Families1.ldw").write_bytes(build_save(
        {0: villager_record(**ANN), 3: villager_record(name="Dora", sex=1, age=440, head=4, body=4)},
        [family_record(p_ann(), peep("Dora", sex=1, head=4, body=4, slot=3), [])]))
    v = gen.load_village(tmp_path, gen.GAME, 1)
    assert labels(v, "Dora") == ["Wife 1"] and by_name(v, "Dora").sex == "Female"


def test_backfilled_records_say_the_log_began_late(tmp_path):
    history_folder(tmp_path, "Family: Testfamily (Save 1)\r\n" + rec(
        "backfilled, no date", "Family Tree 1", "  Parent: Ann", "    Sex: Female", "    Head: 1", "    Body: 1",
        "  Parent (married in): Dan", "    Sex: Male", "    Head: 3", "    Body: 3", "  Child: Cal", "    Sex: Male",
        "    Head: 4", "    Body: 4", "  Current spouse of Ann: Dan", "  Generation: 1",
        "  Note: Recorded afterwards (from the save's Family Tree: no dates, ages, causes, twins or earlier spouses)"))
    (tmp_path / "Virtual Families1.ldw").write_bytes(build_save(
        {0: villager_record(**ANN), 3: villager_record(**DAN), 2: villager_record(**CAL)},
        [family_record(p_ann(), peep("Dan", head=3, body=3, slot=3), [peep("Cal", head=4, body=4, slot=2)])]))
    v = gen.load_village(tmp_path, gen.GAME, 1)
    assert len(v.people) == 3 and any("backfilled, no date" in n for n in v.notes)
    assert by_name(v, "Dan").spouse_number is None, "an order the backfill cannot prove is not given"


def test_an_eviction_starts_the_next_familys_history():
    h = fh.parse("Family: Testfamily (Save 1)\r\n" + "".join([
        rec("2026-10-20 10:05:00", "Marriage 1", *who("Family member", "Zoe", "Female", 21), *who("Married", "Yan", "Male", 22),
            "  Generation: 1"),
        rec("2026-10-20 11:00:00", "Evict Family 1", "  Family members: Zoe, Yan", "  Generation: 1"),
        rec("2026-10-20 12:00:00", "Marriage 2", *who("Family member", "Ann", "Female", 25), *who("Married", "Dan", "Male", 30),
            "  Generation: 1")]))
    assert [m.head for m in h.marriages] == ["Ann"] and h.evictions == 1


def test_every_record_kind_parses(tmp_path):
    h = fh.parse(HISTORY)
    assert [(b.mother, b.father, b.babies) for b in h.births] == [("Ann", "Bob", [("Cal", "Male"), ("Cia", "Female")])]
    assert h.deaths == [("Cia", "Female", 2, "Child", 1, "Starvation")]
    assert [(m.again, m.spouse, m.spouse_sex, m.earlier, m.earlier_how) for m in h.marriages] == [
        (False, "Bob", "Male", None, None), (True, "Dan", "Male", "Bob", "divorced")]
    assert h.divorces == [("Bob", "Male", 23, "Ann", 1)]
    assert [(e.kind, e.title, e.choice) for e in h.events] == [("Popup Event", "The Little Visitor", "A"),
                                                              ("Email Event", "Subject: Tax Audit", None)]
    assert [(j[0], j[3]) for j in h.joined] == [("Kim", "Adopted (Popup Event: The Little Visitor)"),
                                               ("Lou", "Adopted (Adopt Outside Child)")]
    assert h.renames == [("Oldname", "Testfamily")]
    more = fh.parse("".join([
        rec("x", "Birth 3", "  Child: A", "    Sex: Male", "  Mother: Ann", "  Father: (unknown)", "  Born as: Triplet",
            "  Generation: 2"),
        rec("x", "Birth 4", "  Child: B", "    Sex: Female", "  Mother: Ann", "  Father: (unknown)", "  Born as: Triplet",
            "  Generation: 2"),
        rec("x", "Birth 5", "  Child: C", "    Sex: Male", "  Mother: Ann", "  Father: (unknown)", "  Born as: Triplet",
            "  Generation: 2"),
        rec("x", "Left Home 1", "  Name: Kid", "  Age: 10", "  Sex: Male", "  Head: 1", "  Body: 1",
            "  What happened: Left home with The Talent Scout (Popup Event)", "  Generation: 2"),
        rec("x", "New Generation 1", "  Name: Kid", "  Age: 20", "  Sex: Male", "  Head: 1", "  Body: 1",
            "  How: Heir (inherited the house)", "  Generation: 3"),
        rec("x", "Conception 1", "  Mother: Ann", "    Age at conception: 26", "  Father: Bob", "  Babies Nursing: 2",
            "  Generation: 1"),
        rec("x", "Roll the Dice 1", "  Cost: $500", "  Popup Event: Adoption Day", "  Generation: 1"),
        rec("x", "Start Over 1", "  The earlier family's history was cleared.")]))
    assert len(more.births) == 1 and [n for n, _s in more.births[0].babies] == ["A", "B", "C"]
    assert more.births[0].father is None and more.births[0].generation == 2
    assert more.left == [("Kid", "Male", 10, "Left home with The Talent Scout (Popup Event)", 2)]
    assert fh.event_of(more.left[0][3]) == "Popup Event: The Talent Scout"
    assert more.heirs == [("Kid", "Male", 20, "Heir (inherited the house)", 3)]
    assert [e.kind for e in more.entries] == ["Birth", "Birth", "Birth", "Left Home", "New Generation", "Conception",
                                              "Roll the Dice", "Start Over"]
    assert fh.read(tmp_path, 1) is None
