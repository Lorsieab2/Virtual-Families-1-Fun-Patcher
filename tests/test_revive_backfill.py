"""Revive Backfill (patcher/vf1_revive_backfill.py): snapshots, afterwards, of family members who died before Revive a
Family Member was on. Every source is read-only; each field is marked exact, inferred or unknown; a second run changes
nothing; a failed write puts every file back; the backups are repaired while the game runs, the live saves wait; only
the dead are ever backfilled."""
from __future__ import annotations

import hashlib
import struct
from datetime import datetime
from pathlib import Path

import pytest

import vf1_genealogy as gen
import vf1_revive_backfill as rb
import vf1_save as vs
from test_vf1_save import build_save, family_record, peep, villager_record

DATA = vs.PATCHER_DATA
NOW = datetime(2026, 11, 26, 12, 0, 0)


def with_saved_at(data: bytes, stamp: int) -> bytes:
    """The save as written `stamp` seconds after the epoch (CGameTime +0x10)."""
    out = bytearray(data)
    struct.pack_into("<I", out, 24 + vs.GS_GAME_TIME - vs.GS_BASE + 0x10, stamp)
    return bytes(out)


def couple():
    return (peep("Ann", sex=1, head=43, body=3, slot=0, index=-1, career=66),
            peep("Bob", sex=0, head=12, body=19, slot=1, career=22))


def write_log(folder: Path, slot: int, records: list[str]) -> None:
    path = folder / "Virtual Families 1 Patcher" / f"Save {slot}" / "Logs" / "Family History" / "Family History 1.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Family: Testfamily (Save 1)\r\n" + "".join(records), encoding="utf-8", newline="")


def death(n, name, sex, years, cause, head, body, role, g=1, when="2021-04-01 06:00:00"):
    return (f"[{when}] Death {n}\r\n  Name: {name}\r\n  Age at death: {years}\r\n  Sex: {sex}\r\n"
            f"  Cause of death: {cause}\r\n  Head: {head}\r\n  Body: {body}\r\n  Family role: {role}\r\n"
            f"  Generation: {g}\r\n\r\n")


def snapshots(folder: Path, number: int = 1) -> list[rb.Snapshot]:
    side = rb.read_sidecar(rb.sidecar_path(folder, number).read_bytes())
    assert side is not None
    return [rb.Snapshot(e) for e in side.entries]


def everything(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def folder(tmp_path):
    """Slot 1: Ann and Bob; Cal (child, slot 2) died of disease at 8 and his record is still in the save; Dee (child)
    is alive in slot 3."""
    f = tmp_path / "Virtual Families - Modded"
    f.mkdir()
    villagers = {
        0: villager_record(name="Ann", sex=1, age=600, head=43, body=3),
        1: villager_record(name="Bob", sex=0, age=620, head=12, body=19),
        2: villager_record(name="Cal", sex=0, present=0, age=163, head=11, body=12, health=0, cause=0,
                           p1="Joey", p2="Ann", fertility=91, wants=12),
        3: villager_record(name="Dee", sex=1, age=240, head=13, body=14),
    }
    kids = [peep("Cal", sex=0, head=11, body=12, slot=-1), peep("Dee", sex=1, head=13, body=14, slot=3)]
    (f / "Virtual Families1.ldw").write_bytes(build_save(villagers, [family_record(*couple(), kids)]))
    return f


def test_a_stale_record_gives_every_field_exact(folder):
    before = everything(folder)
    results = rb.backfill(folder, game_running=False, now=NOW)
    snaps = snapshots(folder)
    assert [s.name for s in snaps] == ["Cal"]
    s = snaps[0]
    assert s.source == rb.SOURCE_STALE and set(s.marks().values()) == {"exact"}
    assert (s.sex, s.head, s.body, s.age_units, s.cause, s.role, s.generation) == (0, 11, 12, 163, 0, 2, 1)
    assert s.revive_units() == 163
    # The sidecar names the save, and nothing that was there changed.
    side = rb.read_sidecar(rb.sidecar_path(folder, 1).read_bytes())
    save = (folder / "Virtual Families1.ldw").read_bytes()
    assert (side.save_hash, side.save_size) == (gen.fnv1a64(save), len(save))
    after = everything(folder)
    assert {k: v for k, v in after.items() if k in before} == before
    assert "Cal" in rb.report(results)


def test_a_second_run_changes_nothing(folder):
    rb.backfill(folder, game_running=False, now=NOW)
    first = everything(folder)
    results = rb.backfill(folder, game_running=False, now=NOW)
    assert everything(folder) == first
    assert all(not r.planned for r in results)
    assert rb.report(results).startswith("Nothing to backfill")


def test_a_snapshot_taken_at_the_death_always_wins(folder):
    save = (folder / "Virtual Families1.ldw").read_bytes()
    d = rb.Dead("Cal", 0, 11, 12, 1, 2, None, bytes(rb.PEEP_SIZE), bytes(rb.PEEP_SIZE))
    captured = bytearray(rb.build_entry(d, vs.parse_save(save).villagers[2], rb.SOURCE_STALE, True, "Cal"))
    struct.pack_into("<i", captured, rb.E_SOURCE, rb.SOURCE_CAPTURED)
    path = rb.sidecar_path(folder, 1)
    path.parent.mkdir(parents=True)
    path.write_bytes(rb.render_sidecar(save, 1, 0, 1, [bytes(captured)]))
    rb.backfill(folder, game_running=False, now=NOW)
    snaps = snapshots(folder)
    assert [(s.name, s.source) for s in snaps] == [("Cal", rb.SOURCE_CAPTURED)]


def test_an_older_save_gives_who_they_were_and_infers_the_rest(folder):
    # The save now: Cal's slot was reused (by Eve); the older copy <21> has Cal alive, at 15.
    villagers = {0: villager_record(name="Ann", sex=1, age=600, head=43, body=3),
                 1: villager_record(name="Bob", sex=0, age=620, head=12, body=19),
                 2: villager_record(name="Eve", sex=1, age=20, head=1, body=2)}
    kids = [peep("Cal", sex=0, head=11, body=12, slot=-1), peep("Eve", sex=1, head=1, body=2, slot=2)]
    now = with_saved_at(build_save(villagers, [family_record(*couple(), kids)]), 9000)
    (folder / "Virtual Families1.ldw").write_bytes(now)
    old_villagers = dict(villagers)
    old_villagers[2] = villager_record(name="Cal", sex=0, age=300, head=11, body=12, voice=17, wants=12)
    old = with_saved_at(build_save(old_villagers, [family_record(*couple(), kids[:1])]), 3000)
    (folder / "Virtual Families21.ldw").write_bytes(old)
    write_log(folder, 1, [death(1, "Cal", "Male", 16, "Starvation", 11, 12, "Child")])
    rb.backfill(folder, game_running=False, now=NOW)
    s = snapshots(folder)[0]
    assert s.source == rb.SOURCE_OLDER and s.name == "Cal"
    m = s.marks()
    assert m["name"] == m["sex"] == m["head"] == m["body"] == m["voice"] == m["parents"] == "exact"
    assert m["likes"] == m["career"] == m["fertility"] == m["wants kids"] == "inferred"
    assert m["age at death"] == "inferred" and m["cause of death"] == "exact"
    assert (s.age_units, s.cause, s.revive_units()) == (320, 1, 320)
    assert struct.unpack_from("<i", s.raw, rb.E_BIO + 0xC)[0] == 17


def test_the_family_tree_alone_marks_the_rest_unknown(folder):
    # No record anywhere (slot reused, no older save), no log: who they were, from the tree, and nothing else.
    villagers = {0: villager_record(name="Ann", sex=1, age=600, head=43, body=3),
                 1: villager_record(name="Bob", sex=0, age=620, head=12, body=19),
                 2: villager_record(name="Eve", sex=1, age=20, head=1, body=2)}
    kids = [peep("Cal", sex=0, head=11, body=12, slot=-1)]
    (folder / "Virtual Families1.ldw").write_bytes(build_save(villagers, [family_record(*couple(), kids)]))
    rb.backfill(folder, game_running=False, now=NOW)
    s = snapshots(folder)[0]
    m = s.marks()
    assert s.source == rb.SOURCE_TREE
    assert (m["name"], m["sex"], m["head"], m["body"], m["family tree"]) == ("exact",) * 5
    assert m["voice"] == m["likes"] == m["career"] == m["fertility"] == m["age at death"] == "unknown"


def test_the_log_alone_brings_a_childless_spouse_back(folder):
    # Bob died before any child: the game freed his place in the tree; only the log remembers him.
    villagers = {0: villager_record(name="Ann", sex=1, age=600, head=43, body=3)}
    ann = peep("Ann", sex=1, head=43, body=3, slot=0, index=-1)
    (folder / "Virtual Families1.ldw").write_bytes(build_save(villagers, [family_record(ann, peep(used=0), [])]))
    write_log(folder, 1, [death(1, "Bob", "Male", 31, "Work accident", 12, 19, "Parent (married in)")])
    rb.backfill(folder, game_running=False, now=NOW)
    s = snapshots(folder)[0]
    assert (s.name, s.source, s.role, s.head, s.body, s.age_units, s.cause) == ("Bob", rb.SOURCE_LOG, 1, 12, 19,
                                                                                31 * 20, 3)
    assert s.revive_units() == 360                          # died at 31: back at 18
    assert s.marks()["cause of death"] == "exact" and s.marks()["voice"] == "unknown"


def test_a_death_after_the_save_was_made_is_not_in_its_file(folder):
    write_log(folder, 1, [death(1, "Dee", "Female", 13, "Disease", 13, 14, "Child", when="2030-01-01 00:00:00")])
    rb.backfill(folder, game_running=False, now=NOW)
    assert [s.name for s in snapshots(folder)] == ["Cal"]


def test_only_the_dead_are_backfilled(folder):
    # Bob divorced (his place emptied, not dead) and Dee left with The Talent Scout (present 0, alive, slot kept).
    villagers = {0: villager_record(name="Ann", sex=1, age=600, head=43, body=3),
                 1: villager_record(name="Bob", sex=0, present=0, age=620, head=12, body=19),
                 3: villager_record(name="Dee", sex=1, present=0, age=240, head=13, body=14)}
    ann = peep("Ann", sex=1, head=43, body=3, slot=0, index=-1)
    kids = [peep("Dee", sex=1, head=13, body=14, slot=3)]
    (folder / "Virtual Families1.ldw").write_bytes(build_save(villagers, [family_record(ann, peep(used=0), kids)]))
    write_log(folder, 1, ["[2021-05-01 00:00:00] Divorce 1\r\n  Family member: Ann\r\n  Divorced: Bob\r\n"
                          "    Sex: Male\r\n  Generation: 1\r\n\r\n"])
    results = rb.backfill(folder, game_running=False, now=NOW)
    assert not rb.sidecar_path(folder, 1).exists() and all(not r.written for r in results)


def test_a_damaged_or_foreign_file_is_left_as_it_is(folder):
    path = rb.sidecar_path(folder, 1)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"VF1REVV\0 not a sidecar")
    results = rb.backfill(folder, game_running=False, now=NOW)
    assert path.read_bytes() == b"VF1REVV\0 not a sidecar"
    assert any("damaged" in why for r in results for _p, why in r.left)
    other = rb.render_sidecar(b"another save", 1, 0, 1, [])
    path.write_bytes(other)
    results = rb.backfill(folder, game_running=False, now=NOW)
    assert path.read_bytes() == other and any("another save" in why for r in results for _p, why in r.left)


def test_the_backups_are_repaired_while_the_game_runs_and_the_live_saves_wait(folder):
    backup = folder / "Backups" / "Backup 2026-11-20 10-00-00"
    backup.mkdir(parents=True)
    (backup / "Virtual Families1.ldw").write_bytes((folder / "Virtual Families1.ldw").read_bytes())
    results = rb.backfill(folder, game_running=True, now=NOW)
    assert not rb.sidecar_path(folder, 1).exists()
    assert results[0].waiting and "waits until the game is closed" in rb.report(results)
    assert [s.name for s in snapshots(backup)] == ["Cal"]
    rb.backfill(folder, game_running=False, now=NOW)
    assert [s.name for s in snapshots(folder)] == ["Cal"]


def test_a_failed_write_puts_every_file_back(folder):
    # Two save files to write: the second write fails, so the first is put back (here: removed, it was new),
    # and a replaced file would get its old bytes back (its copy is kept in "Before Backfill").
    (folder / "Virtual Families21.ldw").write_bytes((folder / "Virtual Families1.ldw").read_bytes() + b"")
    calls = []

    def writer(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        rb._replace(path, data)
    with pytest.raises(rb.BackfillError, match="put back"):
        rb.backfill(folder, game_running=False, now=NOW, writer=writer)
    assert len(calls) == 2
    assert not rb.sidecar_path(folder, 1).exists() and not rb.sidecar_path(folder, 21).exists()


def test_a_replaced_file_is_copied_first_and_restored_on_failure(folder):
    rb.backfill(folder, game_running=False, now=NOW)
    path = rb.sidecar_path(folder, 1)
    first = path.read_bytes()
    # Dee dies too (a new save): the file is replaced; then a failing write restores it.
    save = (folder / "Virtual Families1.ldw").read_bytes()
    parsed = vs.parse_save(save)
    villagers = {v.slot: v.raw for v in parsed.villagers}
    villagers[3] = villager_record(name="Dee", sex=1, present=0, age=240, head=13, body=14, health=0, cause=2)
    kids = [peep("Cal", sex=0, head=11, body=12, slot=-1), peep("Dee", sex=1, head=13, body=14, slot=-1)]
    new_save = build_save(villagers, [family_record(*couple(), kids)])
    side = rb.read_sidecar(first)
    path.write_bytes(rb.render_sidecar(new_save, 1, 0, 1, side.entries))
    (folder / "Virtual Families1.ldw").write_bytes(new_save)
    kept = path.read_bytes()

    def broken(p, data):
        rb._replace(p, data[:10])          # writes, but the result is wrong: the read-back check fails

    with pytest.raises(rb.BackfillError):
        rb.backfill(folder, game_running=False, now=NOW, writer=lambda p, d: (broken(p, d), _check(p, d)))
    assert path.read_bytes() == kept
    assert (path.parent / "Before Backfill 2026-11-26 12-00-00" / path.name).read_bytes() == kept
    rb.backfill(folder, game_running=False, now=NOW)
    assert [s.name for s in snapshots(folder)] == ["Cal", "Dee"]


def _check(p, d):
    if p.read_bytes() != d:
        raise rb.BackfillError("did not read back")


def test_the_slot_tools_know_the_revive_files(folder):
    rb.backfill(folder, game_running=False, now=NOW)
    rel = Path(DATA) / "Revive" / "Virtual Families21.ldw.dat"
    assert vs.file_owner(rel) == (1, "revive sidecar (backup 1)")
    assert vs.file_owner(Path(DATA) / "Revive" / "Virtual Families1.ldw.unreadable-2.dat") == \
           (1, "unreadable revive sidecar (save)")
    # Rename Family, Copy Player Slot and the backup's pause re-match it as they re-match a Children file.
    save = (folder / "Virtual Families1.ldw").read_bytes()
    changed = save[:-1] + b"\x01"
    rekeys = gen.children_rekeys(folder, 1, [(save, changed)])
    assert [p.name for p, _old, _new in rekeys] == ["Virtual Families1.ldw.dat"]
    assert gen.sidecar_key(rekeys[0][2]) == (gen.fnv1a64(changed), len(changed))
    assert rb.read_sidecar(rekeys[0][2]).entries == rb.read_sidecar(rekeys[0][1]).entries
