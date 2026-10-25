"""Check Saves and its small repair (patcher/vf1_check_saves.py).

Synthetic saves are built with tests/test_vf1_save.py's writer; the owner's saved copies (read only) must
show no WRONG. No game is started, and nothing here may create a log or data file.
"""
import struct
from datetime import datetime
from pathlib import Path

import pytest

import test_vf1_save as tv
import vf1_check_saves as cs
import vf1_rename_family as rf
import vf1_save as vs
import vf1_save_backup as sb

NOW = datetime(2026, 10, 24, 12, 30, 5)
SAVECOPIES = Path(r"C:\vf1\savecopies")


class Processes:
    def __init__(self, *answers):
        self.answers = list(answers) or [[]]
        self.calls = 0

    def find(self, exe_name):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def good_villagers(**changes):
    villagers = {
        0: tv.villager_record(name="Rosella", sex=1, age=542, head=43, body=3, career=66, preg=541, babies=1,
                              father="Joey", fertility=91, wants=77),
        1: tv.villager_record(name="Kikino", sex=0, age=482, head=12, body=19, career=22),
        2: tv.villager_record(name="Bohi", present=0, age=40, head=27, body=26, p1="Joey", p2="Rosella"),
        3: tv.villager_record(name="Gone", left=1, left_at=4321, age=385, head=5, body=6, p1="Joey", p2="Rosella"),
    }
    villagers.update(changes)
    return villagers


def records(gens=1):
    first = tv.family_record(tv.peep("Rosella", sex=1, head=43, body=3, slot=0, index=-1),
                             tv.peep("Kikino", sex=0, head=12, body=19, slot=1),
                             [tv.peep("Bohi", head=27, body=26, slot=2), tv.peep("Gone", head=5, body=6, slot=3)])
    if gens == 1:
        return [first]
    second = tv.family_record(tv.peep("Gone", sex=0, head=5, body=6, slot=3, index=1),
                              tv.peep("Rosella", sex=1, head=43, body=3, slot=0), [])
    return [first, second]


def make_save(villagers=None, recs=None, **gs):
    return tv.build_save(villagers or good_villagers(), recs or records(), pending=(2, -1, -1), **gs)


@pytest.fixture
def folder(tmp_path):
    out = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    out.mkdir(parents=True)
    (out / "Virtual Families1.ldw").write_bytes(make_save())
    return out


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER not in p.relative_to(folder).parts}


def texts(result, verdict):
    return [f.text for f in result.findings if f.verdict == verdict]


def keys(result):
    return {r.key for r in result.repairs}


def test_a_healthy_save_is_all_ok_and_writes_nothing(folder):
    before = files(folder)
    result = cs.check(folder, 1)
    assert result.count("WRONG") == 0 and result.count("NOTE") == 0 and result.repairs == []
    assert {f.section for f in result.findings if f.verdict == "OK"} == {"The save", "Villagers", "Family tree",
                                                                          "Babies on the way"}
    assert "OK" in result.text() and files(folder) == before


def test_health_and_cause_outside_the_games_rules_are_found_and_repairable(folder):
    bad = good_villagers()
    bad[1] = tv.villager_record(name="Kikino", sex=0, age=482, head=12, body=19, career=22, health=250, cause=2)
    (folder / "Virtual Families1.ldw").write_bytes(make_save(bad))
    result = cs.check(folder, 1)
    assert keys(result) == {"v1:health"}
    (repair,) = result.repairs
    assert "0x48F820" in " ".join(repair.evidence) and "250" in repair.title
    assert {len(f.new) for f in repair.fixes} == {4} and len(repair.fixes) == 2
    done = cs.apply(folder, 1, {"v1:health"}, Processes(), NOW)
    after = vs.read_save(folder / "Virtual Families1.ldw")
    assert (after.villagers[1].health, after.villagers[1].death_cause) == (100, -1)
    assert done.repaired and cs.check(folder, 1).count("WRONG") == 0
    assert sb.list_backups(folder)[0].before_repair                      # "(before repair)"


def test_a_value_outside_its_clamp_goes_to_the_clamp_and_nothing_else_changes(folder):
    raw = bytearray(tv.villager_record(name="Kikino", sex=0, age=482, head=12, body=19, career=22))
    struct.pack_into("<i", raw, cs.STATE + 0x34, 0)          # below the 1..100 clamp
    struct.pack_into("<i", raw, cs.STATE + 0x3C, -900)       # below -500
    struct.pack_into("<i", raw, cs.STATE + 0x50, 100)        # above 99
    (folder / "Virtual Families1.ldw").write_bytes(make_save(good_villagers() | {1: bytes(raw)}))
    before = (folder / "Virtual Families1.ldw").read_bytes()
    result = cs.check(folder, 1)
    assert keys(result) == {"v1:0x34", "v1:0x3c", "v1:0x50"}
    cs.apply(folder, 1, {"v1:0x34", "v1:0x3c"}, Processes(), NOW)    # the third is left: "Don't know"
    after = (folder / "Virtual Families1.ldw").read_bytes()
    v = vs.parse_save(after).villagers[1]
    assert v.stats[0] == 1 and v.stats[2] == -500 and v.wants_children == 100
    assert sum(a != b for a, b in zip(before, after)) <= 8 and keys(cs.check(folder, 1)) == {"v1:0x50"}


def test_uncertain_things_are_reported_and_never_repaired(folder):
    bad = good_villagers()
    bad[1] = tv.villager_record(name="Kikino", sex=0, age=-5, head=77, body=19, career=22)
    bad[0] = tv.villager_record(name="Rosella", sex=1, age=542, head=43, body=3, preg=900, babies=7, fertility=91, wants=77)
    (folder / "Virtual Families1.ldw").write_bytes(make_save(bad))
    result = cs.check(folder, 1)
    wrong = " ".join(texts(result, "WRONG"))
    assert "below 0" in wrong and "outside the game's 0 to 49" in wrong and "carrying 7" in wrong
    assert "after the present age" in wrong and result.repairs == []
    with pytest.raises(cs.CheckError, match="not needed"):
        cs.apply(folder, 1, {"v1:health"}, Processes(), NOW)


def test_a_dead_body_kept_too_long_is_reported_not_removed(folder):
    bad = good_villagers()
    bad[1] = tv.villager_record(name="Kikino", sex=0, age=482, head=12, body=19, health=0, cause=2, stamp=1)
    data = bytearray(make_save(bad))
    at = vs.parse_header(bytes(data)).size + vs.GS_GAME_TIME - vs.GS_BASE + 0x10
    struct.pack_into("<I", data, at, 1 + 60 * 10 * 300)          # 300 age units after the death
    (folder / "Virtual Families1.ldw").write_bytes(bytes(data))
    result = cs.check(folder, 1)
    assert any("0x489D31" in t for t in texts(result, "WRONG")) and result.repairs == []


def test_the_family_tree_must_link(folder):
    broken = records(2)
    broken[1] = tv.family_record(tv.peep("Nobody", sex=0, slot=3, index=1), tv.peep("Rosella", sex=1, slot=0), [])
    (folder / "Virtual Families1.ldw").write_bytes(make_save(recs=broken))
    result = cs.check(folder, 1)
    assert any("does not match child 2 of generation 1" in t for t in texts(result, "WRONG"))
    out_of_range = records(2)
    out_of_range[1] = tv.family_record(tv.peep("Gone", sex=0, head=5, body=6, slot=3, index=5),
                                       tv.peep("Rosella", sex=1, head=43, body=3, slot=0), [])
    (folder / "Virtual Families1.ldw").write_bytes(make_save(recs=out_of_range))
    assert any("should be child 6" in t for t in texts(cs.check(folder, 1), "WRONG"))


def test_a_gap_in_the_tree_and_wrong_pointers_are_found(folder):
    save = bytearray(make_save())
    hdr = vs.parse_header(bytes(save)).size
    third = hdr + vs.GS_FAMILY_TREE - vs.GS_BASE + 2 * vs.FAMILY_RECORD
    save[third] = 1                                          # used, after an unused record
    (folder / "Virtual Families1.ldw").write_bytes(bytes(save))
    assert any("Generation 3 is marked used" in t for t in texts(cs.check(folder, 1), "WRONG"))
    pointers = [tv.family_record(tv.peep("Rosella", sex=1, head=43, body=3, slot=0, index=-1),
                                 tv.peep("Kikino", sex=0, head=12, body=19, slot=0),
                                 [tv.peep("Bohi", head=27, body=26, slot=40), tv.peep("Gone", head=9, body=6, slot=3)])]
    (folder / "Virtual Families1.ldw").write_bytes(make_save(recs=pointers))
    wrong = " ".join(texts(cs.check(folder, 1), "WRONG"))
    assert "both point at villager slot 0" in wrong and "slot 40, which does not exist" in wrong
    assert "points at slot 3, which holds Gone" in wrong


def test_babies_on_the_way_are_checked(folder):
    (folder / "Virtual Families1.ldw").write_bytes(tv.build_save(good_villagers(), records(), pending=(1, 99, 1)))
    wrong = " ".join(texts(cs.check(folder, 1), "WRONG"))
    assert "slot 99" in wrong and "already in the village" in wrong and "share one" in wrong


def test_the_older_copies_are_checked_and_never_written(folder):
    bad = good_villagers()
    bad[1] = tv.villager_record(name="Kikino", sex=0, age=482, head=12, body=19, health=250, cause=2)
    (folder / "Virtual Families21.ldw").write_bytes(make_save(bad))
    (folder / "Virtual Families41.ldw").write_bytes(b"not a save")
    before = files(folder)
    result = cs.check(folder, 1)
    older = [f for f in result.findings if f.section == "Older saves"]
    assert any(f.verdict == "WRONG" and "Virtual Families21.ldw" in f.text for f in older)
    assert any(f.verdict == "UNCHECKED" and "Virtual Families41.ldw" in f.text for f in older)
    assert result.repairs == [] and files(folder) == before


def test_a_missing_save_and_a_bad_slot_are_refused(folder):
    with pytest.raises(cs.CheckError, match="no family"):
        cs.check(folder, 2)
    with pytest.raises(cs.CheckError, match="no save slot"):
        cs.check(folder, 9)


# ------------------------------------------------------------------ the repair's safety rules


@pytest.fixture
def damaged(folder):
    bad = good_villagers()
    bad[1] = tv.villager_record(name="Kikino", sex=0, age=482, head=12, body=19, health=130)
    (folder / "Virtual Families1.ldw").write_bytes(make_save(bad))
    (folder / "Virtual Families21.ldw").write_bytes(make_save(bad))
    return folder


def test_nothing_chosen_changes_nothing(damaged):
    before = files(damaged)
    with pytest.raises(cs.CheckError, match="No repair was chosen"):
        cs.apply(damaged, 1, set(), Processes(), NOW)
    assert files(damaged) == before and not (damaged / "Backups").exists()


def test_a_running_game_is_refused_before_and_after_the_backup(damaged, monkeypatch):
    before = files(damaged)
    with pytest.raises(cs.GameRunning):
        cs.apply(damaged, 1, {"v1:health"}, Processes([123]), NOW)
    assert files(damaged) == before and not (damaged / "Backups").exists()
    with pytest.raises(cs.GameRunning):
        cs.apply(damaged, 1, {"v1:health"}, Processes([], [123]), NOW)     # started during the backup
    assert files(damaged) == before and len(sb.list_backups(damaged)) == 1


def test_only_the_main_save_changes_and_a_backup_comes_first(damaged):
    before = files(damaged)
    result = cs.apply(damaged, 1, {"v1:health"}, Processes(), NOW)
    after = files(damaged)
    assert [k for k in after if after[k] != before[k]] == ["Virtual Families1.ldw"]
    assert set(after) == set(before)                          # no log, no data file, no temporary file
    assert result.backup.backup_folder.name == "Backup 2026-10-24 12-30-05 (before repair)"
    assert (result.backup.backup_folder / "Virtual Families1.ldw").read_bytes() == before["Virtual Families1.ldw"]


def test_a_failed_write_is_rolled_back(damaged, monkeypatch):
    before = files(damaged)
    real = cs._write_atomically
    calls = []

    def bad_write(path, data):
        calls.append(path)
        if len(calls) == 1:
            real(path, data[:-1] + bytes([data[-1] ^ 1]))       # damage the file, then fail the read-back
            raise cs.CheckError("disk error")
        real(path, data)

    monkeypatch.setattr(cs, "_write_atomically", bad_write)
    with pytest.raises(cs.CheckError, match="put back as it was"):
        cs.apply(damaged, 1, {"v1:health"}, Processes(), NOW)
    monkeypatch.undo()
    assert files(damaged) == before and len(sb.list_backups(damaged)) == 1


def test_a_save_changed_after_the_check_is_not_overwritten(damaged, monkeypatch):
    original = sb.copy_save_folder

    def backup_then_change(folder, now=None, suffix=""):
        result = original(folder, now, suffix)
        (folder / "Virtual Families1.ldw").write_bytes(make_save())       # the game saved
        return result

    monkeypatch.setattr(sb, "copy_save_folder", backup_then_change)
    with pytest.raises(cs.CheckError, match="changed while"):
        cs.apply(damaged, 1, {"v1:health"}, Processes(), NOW)
    assert (damaged / "Virtual Families1.ldw").read_bytes() == make_save()


def test_a_failed_backup_changes_nothing(damaged, monkeypatch):
    before = files(damaged)
    monkeypatch.setattr(sb, "copy_save_folder",
                        lambda *a, **k: (_ for _ in ()).throw(sb.BackupError("disk full")))
    with pytest.raises(cs.CheckError, match="backup before repairing failed"):
        cs.apply(damaged, 1, {"v1:health"}, Processes(), NOW)
    assert files(damaged) == before


def test_the_module_never_names_a_log_or_data_folder():
    text = (Path(cs.__file__)).read_text(encoding="utf-8")
    for word in ("Family History", "Repairs Made", "Answered Questions", "PATCHER_DATA", "Patcher Data"):
        assert word not in text
    assert "open(" not in text.replace(".open(\"xb\")", "")


# ------------------------------------------------------------------ the owner's saved copies (read only)


def test_the_owners_real_saves_show_nothing_wrong():
    if not SAVECOPIES.is_dir():
        pytest.skip("no saved copies on this machine")
    checked = 0
    for copy in sorted(SAVECOPIES.iterdir()):
        if not copy.is_dir():
            continue
        for slot in cs.SLOTS:
            try:
                result = cs.check(copy, slot)
            except cs.CheckError:
                continue
            checked += 1
            assert result.count("WRONG") == 0, (copy.name, slot, texts(result, "WRONG"))
            assert result.repairs == []
    assert checked
