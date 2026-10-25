"""Check Saves & Logs / Repair Saves & Logs (patcher/vf1_log_tools.py).

Every test works in tmp_path: a synthetic save (tests/test_vf1_save.py's writer, the documented format) with
Family Logs written in vf1logs.dll's own formats (the strings tests/test_family_logs.py pins), copies of the
owner's real saves rebuilt from their fixtures, and -- with the vanilla executable and the toolchain -- logs
written by the REAL vf1logs.dll under emulation for those real saves. No real save is touched.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import vf1_log_tools as lt
import vf1_save as vs
import vf1_save_backup as sb
from test_vf1_save import build_save, family_record, peep, villager_record

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vf1_saves"
STAMP = "[2026-10-24 12:34:56] "
NOW = datetime(2026, 10, 24, 15, 0, 0)


class NoProcesses:
    def find(self, exe_name):
        return []


class Running(NoProcesses):
    def find(self, exe_name):
        return [4242]


@pytest.fixture(autouse=True)
def no_game(monkeypatch):
    monkeypatch.setattr(sb, "WindowsProcesses", NoProcesses)


# ------------------------------------------------------------------ a family, its save and its logs
def people(**changes):
    v = {
        0: dict(name="Ann", sex=1, age=26 * 20, head=3, body=4, career=5),
        1: dict(name="Bob", sex=0, age=27 * 20, head=7, body=8, career=6),
        2: dict(name="Cid", sex=0, age=2 * 20, head=5, body=6, p1="Joey", p2="Ann"),
        3: dict(name="Dee", sex=1, age=2 * 20, head=9, body=10, p1="Joey", p2="Ann"),
    }
    for slot, change in changes.items():
        slot = int(slot.lstrip("v"))
        if change is None:
            v.pop(slot)
        else:
            v[slot] = {**v.get(slot, {}), **change}
    return v


def make_save(villagers: dict, extra_kids=(), **gs) -> bytes:
    records = [family_record(peep("Ann", sex=1, head=3, body=4, slot=0, index=-1, career=5),
                             peep("Bob", sex=0, head=7, body=8, slot=1, career=6),
                             [peep("Cid", sex=0, head=5, body=6, slot=2), peep("Dee", sex=1, head=9, body=10, slot=3),
                              *extra_kids])]
    return build_save({k: villager_record(**f) for k, f in villagers.items()}, records, family="Hopkins", **gs)


HISTORY = [
    STAMP + "Generation 1 began: Ann (Female, 26) was adopted and started the family",
    STAMP + "Ann (Female, 26) married Bob (Male, 27), generation 1",
    STAMP + "Conception 1: Ann and Bob (babies Nursing: 2)",
    STAMP + "Birth 1: Cid (Male) was born to Ann and Bob (Twins)",
    STAMP + "Birth 2: Dee (Female) was born to Ann and Bob (Twins)",
]
BIRTHS = (
    "Conception 1\r\n  Mother: Ann\r\n    Age at conception: 24\r\n    Sex: Female\r\n    Head: 3\r\n    Body: 4\r\n"
    "  Father: Bob\r\n    Age at conception: 25\r\n    Sex: Male\r\n    Head: 7\r\n    Body: 8\r\n"
    "  Babies Nursing: 2\r\n  Generation: 1\r\n\r\n"
    "Birth 1\r\n  Child: Cid\r\n    Sex: Male\r\n    Head: 5\r\n    Body: 6\r\n  Mother: Ann\r\n    Head: 3\r\n"
    "    Body: 4\r\n  Father: Bob\r\n  Born as: Twins\r\n  Generation: 1\r\n\r\n"
    "Birth 2\r\n  Child: Dee\r\n    Sex: Female\r\n    Head: 9\r\n    Body: 10\r\n  Mother: Ann\r\n    Head: 3\r\n"
    "    Body: 4\r\n  Father: Bob\r\n  Born as: Twins\r\n  Generation: 1\r\n\r\n"
)


def death_record(n, name, age, sex, cause, head, body, role="Child"):
    return (f"Death {n}\r\n  Name: {name}\r\n  Age at death: {age}\r\n  Sex: {sex}\r\n  Cause of death: {cause}\r\n"
            f"  Head: {head}\r\n  Body: {body}\r\n  Family role: {role}\r\n  Generation: 1\r\n\r\n")


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


def members_text(save: vs.VF1Save, extra=()) -> str:
    rows = [f"member\t{v.slot}\t{v.name}\t{v.sex}\t{v.age_units}\t{v.head}\t{v.body}\t1\t{int(v.left_home)}\t"
            f"{v.health}\t0" for v in save.villagers if v.present] + list(extra)
    return ("VF1LOGS MEMBERS 1\r\nfamily\tHopkins\r\ngenerations\t1\r\n" + "".join(r + "\r\n" for r in rows)
            + f"end\t{len(rows)}\r\n")


def make_family(folder: Path, villagers=None, *, history=HISTORY, births=BIRTHS, deaths="", events="",
                parents=None, members_extra=(), counters=(4, 0), pages=True, extra_kids=(), slot=1) -> Path:
    data = make_save(villagers if villagers is not None else people(), extra_kids)
    write(folder / f"Virtual Families{slot}.ldw", "")
    (folder / f"Virtual Families{slot}.ldw").write_bytes(data)
    save = vs.parse_save(data)
    head = f"Family: Hopkins (Save {slot})\r\n"
    root = lt.slot_root(folder, slot)
    write(lt.log_path(folder, slot, lt.HISTORY, 1), head + "".join(h + "\r\n" for h in history))
    write(lt.log_path(folder, slot, lt.BIRTHS, 1), head + births)
    write(lt.log_path(folder, slot, lt.DEATHS, 1), head + deaths)
    write(lt.log_path(folder, slot, lt.EVENTS, 1), head + events)
    if parents is None:
        parents = ["child\t2\tCid\t0\t1\tAnn\tBob\tconceived", "child\t3\tDee\t1\t1\tAnn\tBob\tconceived"]
    write(lt.parents_path(folder, slot), "VF1LOGS PARENTS 1\r\n" + "".join(p + "\r\n" for p in parents))
    write(lt.members_path(folder, slot), members_text(save, members_extra))
    if counters is not None:
        write(lt.counters_path(folder, slot), lt.counters_text(*counters))
    write(lt.backfill_path(folder, slot), "VF1LOGS BACKFILL 1\r\nfamily\tHopkins\r\nhow\tnew family\r\n")
    if pages:
        write(lt.page_path(folder, slot, lt.POPULATION), lt.population_text(save, slot))
        write(lt.page_path(folder, slot, lt.STATISTICS), lt.statistics_text(save, slot, counters))
    assert root.is_dir()
    return folder


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def verdicts(result, verdict):
    return [f for f in result.findings if f.verdict == verdict]


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "Virtual Families - Modded"


# ------------------------------------------------------------------ check: only reads
def test_a_consistent_family_has_nothing_wrong(folder):
    make_family(folder)
    result = lt.check(folder, 1)
    assert result.wrong == 0 and result.asked == 0, result.text
    assert result.summary.startswith("Save 1: nothing is confirmed wrong")
    assert "Every log names this family: Family: Hopkins (Save 1)." in result.text


def test_check_never_writes(folder):
    make_family(folder, villagers=people(v1=None), members_extra=["member\t9\tZed\t0\t600\t1\t2\t1\t0\t90\t0"],
                history=HISTORY + [STAMP + "Zed (Male, 30) joined the family as a child, adopted, generation 1"])
    before = snapshot(folder)
    result = lt.check(folder, 1)
    assert result.wrong
    assert snapshot(folder) == before


def test_no_logs_yet_is_unchecked_not_wrong(folder):
    folder.mkdir(parents=True)
    (folder / "Virtual Families2.ldw").write_bytes(make_save(people()))
    result = lt.check(folder, 2)
    assert [f.verdict for f in result.findings] == ["UNCHECKED"]
    assert "Family Logs has written nothing for Save 2 yet" in result.text


def test_a_missing_slot_or_unreadable_save_is_an_error(folder):
    folder.mkdir(parents=True)
    with pytest.raises(lt.LogToolError, match="has no family"):
        lt.check(folder, 3)
    (folder / "Virtual Families3.ldw").write_bytes(b"not a save")
    with pytest.raises(lt.LogToolError, match="not a save this tool can read"):
        lt.check(folder, 3)


def test_another_familys_logs_stop_the_check(folder):
    make_family(folder)
    path = lt.log_path(folder, 1, lt.DEATHS, 1)
    write(path, "Family: Smiths (Save 1)\r\n")
    result = lt.check(folder, 1)
    wrong = verdicts(result, "WRONG")
    assert len(wrong) == 1 and wrong[0].repair is None and "Smiths" in result.text
    assert "cannot put this right" in result.text
    assert not any(f.section == "Deaths" for f in result.findings)


# ------------------------------------------------------------------ members missing from the logs
def test_a_member_no_log_names_is_backfilled(folder):
    make_family(folder, history=HISTORY[:3] + HISTORY[4:], births=BIRTHS.split("Birth 1")[0] + "Birth 2"
                + BIRTHS.split("Birth 2", 1)[1])
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Family members in the logs" and f.verdict == "WRONG"]
    assert f.text == "Cid is a family member but no log records them."
    assert f.repair.title == "Add to the Family History: [backfilled, no date] Generation 1: child Cid (Male)"
    before = snapshot(folder)
    done = lt.apply(folder, 1, {f.repair.key}, now=NOW)
    assert done.record == 1 and done.backup is not None
    history = lt.log_path(folder, 1, lt.HISTORY, 1).read_bytes().decode("latin-1")
    assert history.endswith("[backfilled, no date] Generation 1: child Cid (Male)\r\n")
    # the backup holds the folder as it was, and the file's own copy is kept before the change
    backup = Path(done.backup.backup_folder)
    assert backup.name == "Backup 2026-10-24 15-00-00 (before repair)"
    assert {k: v for k, v in snapshot(backup).items()} == before
    copy = lt.slot_root(folder, 1) / lt.COPIES_FOLDER / "Repair 1 2026-10-24 15-00-00" / "Logs" / "Family History" \
        / "Family History 1.txt"
    assert copy.read_bytes() == before["Virtual Families 1 Patcher/Save 1/Logs/Family History/Family History 1.txt"]
    repairs = lt.log_path(folder, 1, lt.REPAIRS, 1).read_bytes().decode("latin-1")
    assert repairs.startswith("Family: Hopkins (Save 1)\r\nRepair 1\r\n  Date: 2026-10-24 15:00:00\r\n")
    assert "  Added to the Family History: [backfilled, no date] Generation 1: child Cid (Male)\r\n" in repairs
    assert "  Backup: Backup 2026-10-24 15-00-00 (before repair)\r\n" in repairs
    again = lt.check(folder, 1)
    assert again.wrong == 0, again.text


def test_a_member_outside_the_tree_is_backfilled_without_guessing_how(folder):
    v = people(v4=dict(name="Kim", sex=1, age=3 * 20, head=11, body=12))
    make_family(folder, villagers=v)
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Family members in the logs" and f.verdict == "WRONG"]
    assert f.repair.data["lines"] == ["[backfilled, no date] Kim (Female, 3) was in the family (how they joined "
                                      "was not recorded)"]


# ------------------------------------------------------------------ deaths
def test_a_death_record_of_someone_alive_is_asked_and_removed_with_the_reason(folder):
    make_family(folder, deaths=death_record(1, "Bob", 27, "Male", "Old age", 7, 8, "Parent (married in)"),
                history=HISTORY + [STAMP + "Death 1: Bob (Male, 27) died: Old age"], counters=(4, 1))
    result = lt.check(folder, 1)
    (q,) = result.questions()
    assert q.text.startswith("Death 1 (Virtual Families 1 Deaths Log 1.txt, line 2) says Bob died at 27")
    assert q.options[-1] == lt.DONT_KNOW
    remove = q.options[0]
    # Don't know changes nothing and is never kept
    assert lt.apply(folder, 1, set(), answers={q.key: lt.DONT_KNOW}, now=NOW).record is None
    done = lt.apply(folder, 1, set(), answers={q.key: remove}, now=NOW)
    deaths = lt.log_path(folder, 1, lt.DEATHS, 1).read_bytes().decode("latin-1")
    assert deaths == "Family: Hopkins (Save 1)\r\n"
    assert "Death 1:" not in lt.log_path(folder, 1, lt.HISTORY, 1).read_bytes().decode("latin-1")
    repairs = lt.log_path(folder, 1, lt.REPAIRS, 1).read_bytes().decode("latin-1")
    assert "Removed: Death 1 -- from Virtual Families 1 Deaths Log 1.txt -- reason: Bob is alive in the save" in repairs
    assert "    |   Cause of death: Old age\r\n" in repairs
    assert f"  Answered: {q.text} -- {remove}\r\n" in repairs
    assert lt.load_answers(folder, 1)[q.key]["answer"] == remove
    assert done.record == 1


def test_an_answer_is_never_asked_again_and_can_be_cleared(folder):
    make_family(folder, deaths=death_record(1, "Bob", 27, "Male", "Old age", 7, 8), counters=(4, 1))
    (q,) = lt.check(folder, 1).questions()
    keep = q.options[1]
    lt.apply(folder, 1, set(), answers={q.key: keep}, now=NOW)
    again = lt.check(folder, 1)
    assert again.questions() == [] and again.asked == 0
    (held,) = again.answered()
    assert held[0].key == q.key and held[1] == keep
    assert f"You answered: {keep}" in again.text
    # Repair again: the kept answer is applied as given (keeping changes nothing), never asked
    assert lt.apply(folder, 1, set(), now=NOW).record is None
    # Changed in the Answered Questions list: applied at Repair, as a first answer is
    lt.apply(folder, 1, set(), answer_changes={q.key: q.options[0]}, now=NOW)
    assert "Death 1" not in lt.log_path(folder, 1, lt.DEATHS, 1).read_bytes().decode("latin-1")
    repairs = lt.log_path(folder, 1, lt.REPAIRS, 1).read_bytes().decode("latin-1")
    assert f"Answer changed: {q.text} -- {q.options[0]} (was: {keep})" in repairs


def test_a_cleared_answer_is_asked_again(folder):
    make_family(folder, deaths=death_record(1, "Bob", 27, "Male", "Old age", 7, 8), counters=(4, 1))
    (q,) = lt.check(folder, 1).questions()
    lt.apply(folder, 1, set(), answers={q.key: q.options[1]}, now=NOW)
    assert lt.check(folder, 1).questions() == []
    lt.apply(folder, 1, set(), cleared={q.key}, now=NOW)
    assert [x.key for x in lt.check(folder, 1).questions()] == [q.key]
    assert "Answer cleared (asked again)" in lt.log_path(folder, 1, lt.REPAIRS, 1).read_bytes().decode("latin-1")


def test_a_death_the_logs_missed_is_backfilled(folder):
    v = people(v1=dict(present=0, health=0, cause=2))
    data = make_save(people())
    make_family(folder, villagers=v)
    # The Family Members at Last Save file still has Bob alive (the death happened with the logs off).
    write(lt.members_path(folder, 1), members_text(vs.parse_save(data)))
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Deaths" and f.verdict == "WRONG"]
    assert f.text == "Bob died but there is no Death record."
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    deaths = lt.log_path(folder, 1, lt.DEATHS, 1).read_bytes().decode("latin-1")
    assert "Death 1\r\n  Name: Bob\r\n  Age at death: 27\r\n  Sex: Male\r\n  Cause of death: Old age\r\n" in deaths
    assert "  Note: backfilled by Repair Saves & Logs from the save" in deaths
    assert "[backfilled, no date] Death 1: Bob (Male, 27) died: Old age\r\n" in \
        lt.log_path(folder, 1, lt.HISTORY, 1).read_bytes().decode("latin-1")


def test_a_body_still_in_the_house_is_only_a_note(folder):
    make_family(folder, villagers=people(v1=dict(health=0, cause=2)))
    result = lt.check(folder, 1)
    assert any(f.verdict == "NOTE" and "body is still in the house" in f.text for f in result.findings)
    assert not any(f.section == "Deaths" and f.verdict in ("WRONG", "ASK") for f in result.findings)


# ------------------------------------------------------------------ duplicates
def test_a_death_logged_twice_is_removed_once(folder):
    v = people(v3=dict(present=0, health=0, cause=0))
    deaths = death_record(1, "Dee", 2, "Female", "Disease", 9, 10) + death_record(2, "Dee", 2, "Female", "Disease", 9, 10)
    make_family(folder, villagers=v, deaths=deaths, counters=(4, 2),
                history=HISTORY + [STAMP + "Death 1: Dee (Female, 2) died: Disease",
                                   STAMP + "Death 2: Dee (Female, 2) died: Disease"])
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Records logged twice"]
    assert f.verdict == "WRONG" and "Death 1 and Death 2" in f.text
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    text = lt.log_path(folder, 1, lt.DEATHS, 1).read_bytes().decode("latin-1")
    assert text.count("Death ") == 1 and "Death 1\r\n" in text
    history = lt.log_path(folder, 1, lt.HISTORY, 1).read_bytes().decode("latin-1")
    assert "Death 1: Dee" in history and "Death 2: Dee" not in history


def test_identical_births_are_asked_never_assumed(folder):
    twin = BIRTHS.split("Birth 2", 1)[1]
    make_family(folder, births=BIRTHS + "Birth 3" + twin)
    result = lt.check(folder, 1)
    (q,) = [q for q in result.questions() if q.key.startswith("duplicate-birth")]
    assert "two babies called Dee" in q.text and "Yes: two babies (keep both)" in q.options


def test_a_backfill_written_twice_is_found_against_the_tree(folder):
    data = make_save(people())
    lines = [lt.BACKFILLED + x for x in lt.backfill_lines(vs.parse_save(data))]
    make_family(folder, history=lines + lines + HISTORY[1:])
    result = lt.check(folder, 1)
    found = [f for f in result.findings if f.section == "Records logged twice" and f.verdict == "WRONG"]
    assert len(found) == len(lines)
    lt.apply(folder, 1, {f.repair.key for f in found}, now=NOW)
    history = lt.log_path(folder, 1, lt.HISTORY, 1).read_bytes().decode("latin-1")
    assert all(history.count(x + "\r\n") == 1 for x in lines)


# ------------------------------------------------------------------ who left
def test_a_member_who_vanished_gets_an_unaccounted_record(folder):
    make_family(folder, members_extra=["member\t9\tZed\t0\t600\t1\t2\t1\t0\t90\t0"],
                history=HISTORY + [STAMP + "Zed (Male, 30) joined the family as a child, adopted, generation 1"])
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Family members who left" and f.verdict == "WRONG"]
    assert f.text == "Zed is gone from the save with no record of how."
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    text = lt.log_path(folder, 1, lt.UNACCOUNTED, 1).read_bytes().decode("latin-1")
    assert text.startswith("Family: Hopkins (Save 1)\r\nUnaccounted 1\r\n  Name: Zed\r\n  Age when last seen: 30\r\n")
    assert "[2026-10-24 15:00:00] Unaccounted 1: Zed (Male, 30) is gone with no record of how\r\n" in \
        lt.log_path(folder, 1, lt.HISTORY, 1).read_bytes().decode("latin-1")
    assert not any(f.section == "Family members who left" and f.verdict == "WRONG" for f in lt.check(folder, 1).findings)


def test_an_eviction_or_divorce_accounts_for_who_left(folder):
    event = ("Event 1\r\n  Event: Divorce Spouse\r\n  Name: Zed\r\n  Age: 30\r\n  Sex: Male\r\n  Head: 1\r\n"
             "  Body: 2\r\n  Generation: 1\r\n\r\n")
    make_family(folder, members_extra=["member\t9\tZed\t0\t600\t1\t2\t1\t0\t90\t0"], events=event,
                history=HISTORY + [STAMP + "Ann (Female, 26) married Zed (Male, 30), generation 1"])
    result = lt.check(folder, 1)
    assert not any(f.section == "Family members who left" and f.verdict in ("WRONG", "ASK") for f in result.findings)


def test_a_candidate_never_in_the_family_is_a_note(folder):
    make_family(folder, members_extra=["member\t9\tSuitor\t0\t600\t1\t2\t1\t0\t90\t0"])
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Family members who left"]
    assert f.verdict == "NOTE" and "candidate" in f.text


def test_the_games_older_copy_is_compared_too(folder):
    make_family(folder)
    older = make_save(people(v4=dict(name="Eve", sex=1, age=19 * 20, head=13, body=14)),
                      extra_kids=[peep("Eve", sex=1, head=13, body=14, slot=4)])
    (folder / "Virtual Families41.ldw").write_bytes(older)
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Family members who left" and f.verdict == "WRONG"]
    assert "Eve" in f.text and "Virtual Families41.ldw" in " ".join(f.repair.evidence)


# ------------------------------------------------------------------ parents
def test_missing_parents_are_added_from_the_save_and_the_birth_record(folder):
    make_family(folder, parents=["child\t2\tCid\t0\t1\tAnn\tBob\tconceived"])
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.section == "Parents" and f.verdict == "WRONG"]
    assert f.text == "Dee's parents are not in the Parents file."
    assert f.repair.data["lines"] == ["child\t3\tDee\t1\t1\tAnn\tBob\tbackfilled"]
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    assert lt.parents_path(folder, 1).read_bytes().decode("latin-1").endswith("child\t3\tDee\t1\t1\tAnn\tBob\tbackfilled\r\n")


def test_no_father_is_guessed(folder):
    make_family(folder, parents=["child\t2\tCid\t0\t1\tAnn\tBob\tconceived"], births=BIRTHS.split("Birth 2")[0])
    result = lt.check(folder, 1)
    f = next(f for f in result.findings if f.section == "Parents" and f.verdict == "WRONG")
    assert f.repair.data["lines"] == ["child\t3\tDee\t1\t1\tAnn\t\tbackfilled"]
    assert any("none is guessed" in e for e in f.repair.evidence)


def test_a_mother_the_save_contradicts_is_asked(folder):
    make_family(folder, parents=["child\t2\tCid\t0\t1\tAnn\tBob\tconceived", "child\t3\tDee\t1\t1\tZoe\tBob\tconceived"])
    result = lt.check(folder, 1)
    (q,) = [q for q in result.questions() if q.key.startswith("mother|")]
    assert q.text == "Who is Dee's mother: Ann (the save) or Zoe (the Parents file)?"
    lt.apply(folder, 1, set(), answers={q.key: q.options[0]}, now=NOW)
    assert lt.parents_path(folder, 1).read_bytes().decode("latin-1").endswith("child\t3\tDee\t1\t1\tAnn\tBob\trepaired\r\n")
    assert not [q for q in lt.check(folder, 1).questions() if q.key.startswith("mother|")]


# ------------------------------------------------------------------ statistics and population
def test_a_statistics_page_that_does_not_add_up_is_rewritten(folder):
    make_family(folder)
    page = lt.page_path(folder, 1, lt.STATISTICS)
    write(page, page.read_bytes().decode("latin-1").replace("Family Members: 4", "Family Members: 9"))
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.repair is not None and f.repair.action == "write_statistics"]
    assert "Family Members: the page says 9, the save says 4" in f.repair.evidence
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    assert "Family Members: 4\r\n" in page.read_bytes().decode("latin-1")
    assert lt.check(folder, 1).wrong == 0


def test_a_population_page_listing_someone_else_is_rewritten(folder):
    make_family(folder)
    page = lt.page_path(folder, 1, lt.POPULATION)
    write(page, page.read_bytes().decode("latin-1").replace("Name: Dee", "Name: Dora"))
    result = lt.check(folder, 1)
    (f,) = [f for f in result.findings if f.repair is not None and f.repair.action == "write_population"]
    assert any("Dora" in e for e in f.repair.evidence)
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    assert "Name: Dee" in page.read_bytes().decode("latin-1")


def test_counters_below_the_records_are_asked(folder):
    make_family(folder, counters=(1, 0))
    result = lt.check(folder, 1)
    (q,) = [q for q in result.questions() if q.key.startswith("counter-babies")]
    assert "Babies Born says 1, but 2 births are logged" in q.text
    lt.apply(folder, 1, set(), answers={q.key: q.options[0]}, now=NOW)
    assert lt.read_counters(folder, 1) == (4, 0)
    assert "Babies Born: 4\r\n" in lt.page_path(folder, 1, lt.STATISTICS).read_bytes().decode("latin-1")


def test_a_missing_log_is_created_with_its_first_line(folder):
    make_family(folder)
    lt.log_path(folder, 1, lt.EVENTS, 1).unlink()
    result = lt.check(folder, 1)
    (f,) = verdicts(result, "WRONG")
    lt.apply(folder, 1, {f.repair.key}, now=NOW)
    assert lt.log_path(folder, 1, lt.EVENTS, 1).read_bytes() == b"Family: Hopkins (Save 1)\r\n"


# ------------------------------------------------------------------ repair's safety
def test_repair_refuses_while_the_game_runs(folder, monkeypatch):
    make_family(folder, history=HISTORY[:3])
    before = snapshot(folder)
    keys = {r.key for r in lt.check(folder, 1).repairs()}
    monkeypatch.setattr(sb, "WindowsProcesses", Running)
    with pytest.raises(lt.GameRunning, match="is running"):
        lt.apply(folder, 1, keys, now=NOW)
    assert snapshot(folder) == before


def test_a_record_that_changed_since_the_check_is_not_removed(folder, monkeypatch):
    make_family(folder, deaths=death_record(1, "Bob", 27, "Male", "Old age", 7, 8), counters=(4, 1))
    (q,) = lt.check(folder, 1).questions()
    real = lt._apply_removals

    def edited_first(changes, removals, done, skipped):
        path = lt.log_path(folder, 1, lt.DEATHS, 1)
        write(path, path.read_bytes().decode("latin-1").replace("Old age", "Disease"))
        real(changes, removals, done, skipped)
    monkeypatch.setattr(lt, "_apply_removals", edited_first)
    done = lt.apply(folder, 1, set(), answers={q.key: q.options[0]}, now=NOW)
    assert "Death 1" in lt.log_path(folder, 1, lt.DEATHS, 1).read_bytes().decode("latin-1")
    assert any("the file changed since the check" in s for s in done.skipped)


def test_repair_numbers_continue_and_the_report_is_written(folder):
    make_family(folder, history=HISTORY[:3] + HISTORY[4:], births=BIRTHS.split("Birth 1")[0])
    first = lt.check(folder, 1).repairs()[0]
    lt.apply(folder, 1, {first.key}, now=NOW)
    page = lt.page_path(folder, 1, lt.STATISTICS)
    write(page, page.read_bytes().decode("latin-1").replace("Food: 88", "Food: 1"))
    (second,) = lt.check(folder, 1).repairs()
    done = lt.apply(folder, 1, {second.key}, now=datetime(2026, 10, 24, 16, 0, 0))
    assert done.record == 2
    text = lt.log_path(folder, 1, lt.REPAIRS, 1).read_bytes().decode("latin-1")
    assert text.count("Family: Hopkins (Save 1)") == 1 and "Repair 1\r\n" in text and "Repair 2\r\n" in text
    report = lt.report_path(folder, 1).read_bytes().decode("latin-1")
    assert report.startswith("Family: Hopkins (Save 1)\r\nChecked by Repair Saves & Logs (Repair 2)")


def test_nothing_chosen_changes_nothing(folder):
    make_family(folder, history=HISTORY[:3])
    before = snapshot(folder)
    assert lt.apply(folder, 1, set(), now=NOW).record is None
    assert snapshot(folder) == before


def test_read_slots_lists_each_family(folder):
    make_family(folder)
    (folder / "Virtual Families3.ldw").write_bytes(b"junk")
    slots = lt.read_slots(folder)
    assert [s.label for s in slots] == ["Save 1: Hopkins (generation 1)", "Save 2: (no family)",
                                        "Save 3: (no family)", "Save 4: (no family)", "Save 5: (no family)"]


def test_the_words_are_the_executables_as_the_dll_checks_them():
    import vf1_logs_sites as sites
    import inspect
    source = inspect.getsource(sites.validate)
    for word in ("Male", "Female", "Nursing", "Unknown causes", "Old age", "Act of Nature"):
        assert f'"{word}"' in source
    assert lt.CAUSE_WORDS == [vs.DEATH_CAUSES_UNCONFIRMED[k] for k in range(-1, 5)]
    assert lt.SEX_WORDS == {0: "Male", 1: "Female"} and lt.NURSING == "Nursing"


# ------------------------------------------------------------------ copies of the owner's real saves
def _real(name: str) -> bytes:
    import make_vf1_save_fixtures as fx
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_real_saves_without_logs_are_only_unchecked(tmp_path, name):
    (tmp_path / "Virtual Families1.ldw").write_bytes(_real(name))
    result = lt.check(tmp_path, 1)
    assert [f.verdict for f in result.findings] == ["UNCHECKED"]


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_real_saves_with_their_backfilled_logs_have_nothing_wrong(tmp_path, name):
    """The logs vf1logs.dll's first load writes for the save (its Backfill and the pages at its first save)."""
    data = _real(name)
    save = vs.parse_save(data)
    (tmp_path / "Virtual Families1.ldw").write_bytes(data)
    head = lt.header_line(save, 1) + "\r\n"
    write(lt.log_path(tmp_path, 1, lt.HISTORY, 1), head + "".join(lt.BACKFILLED + x + "\r\n" for x in lt.backfill_lines(save)))
    for kind in (lt.BIRTHS, lt.DEATHS, lt.EVENTS):
        write(lt.log_path(tmp_path, 1, kind, 1), head)
    rows = []
    for g, rec in enumerate(save.family_records, 1):
        couple = {1: "", 0: ""}
        for p in (rec.parent1, rec.parent2):
            if p.used:
                couple[1 if p.sex == 1 else 0] = couple[1 if p.sex == 1 else 0] or lt.log_name(p.name)
        rows += [f"child\t{c.slot}\t{lt.log_name(c.name)}\t{c.sex}\t{g}\t{couple[1]}\t{couple[0]}\tbackfilled"
                 for c in rec.children if c.used]
    write(lt.parents_path(tmp_path, 1), "VF1LOGS PARENTS 1\r\n" + "".join(r + "\r\n" for r in rows))
    tree_deaths = sum(1 for rec in save.family_records for p in [rec.parent1, rec.parent2] + list(rec.children)
                      if p.used and p.slot == -1)
    counters = (max(0, save.stats.babies_born - len(save.unborn())), tree_deaths)
    write(lt.counters_path(tmp_path, 1), lt.counters_text(*counters))
    write(lt.backfill_path(tmp_path, 1), "VF1LOGS BACKFILL 1\r\n")
    write(lt.page_path(tmp_path, 1, lt.POPULATION), lt.population_text(save, 1))
    write(lt.page_path(tmp_path, 1, lt.STATISTICS), lt.statistics_text(save, 1, counters))
    result = lt.check(tmp_path, 1)
    assert result.wrong == 0, result.text
    assert all(q.key.startswith(("mother|", "father|")) for q in result.questions()), result.text


# ------------------------------------------------------------------ logs written by the REAL vf1logs.dll
from test_family_logs import built, world  # noqa: E402,F401  (the module-scoped DLL build)


def _dump(w, folder: Path):
    """The emulated DLL's files, into a real folder beside the save."""
    from logs_scenarios import SAVE_DIR
    prefix = w.fs.key(SAVE_DIR) + "\\"
    for key, data in w.fs.files.items():
        if key.startswith(prefix):
            target = folder / Path(*key[len(prefix):].split("\\"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_the_real_dlls_logs_for_real_saves_check_clean(built, tmp_path, name):
    w = world(built)
    data = _real(name)
    save = w.load_save_image(data, slot=1)
    assert w.load(1) == 1
    assert w.save(1) == 1
    _dump(w, tmp_path)                    # the emulator keeps lower-case paths; Windows does not mind
    (tmp_path / "Virtual Families1.ldw").write_bytes(data)
    # The two pages are the DLL's own, byte for byte, as this tool rewrites them.
    counters = lt.read_counters(tmp_path, 1)
    assert lt.page_path(tmp_path, 1, lt.POPULATION).read_bytes().decode("latin-1") == lt.population_text(save, 1)
    assert lt.page_path(tmp_path, 1, lt.STATISTICS).read_bytes().decode("latin-1") == lt.statistics_text(save, 1, counters)
    result = lt.check(tmp_path, 1)
    assert result.wrong == 0, result.text
