"""Revive a Family Member (native/vf1revive/vf1revive.cpp; docs/REVIVE.md).

The sites are proved on the vanilla executable (tools/vf1_revive_sites.py); the shipped DLL is built and run under
emulation with the game's own code at every hooked site (tests/revive_scenarios.py): the snapshot at every death,
the sidecar beside each save file (written, rotated, read back, set aside when damaged, left alone when shut), the
revival (the age rule, every field, moods fresh, the Family Tree), its refusals and its all-or-nothing rollback. The
owner's decisions (2026-11-26) are each a test below."""
from __future__ import annotations

import os
import struct
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

from conftest import ROOT  # noqa: E402
import vf1_logs_sites as L  # noqa: E402
import vf1_revive_backfill as rb  # noqa: E402
import vf1_revive_sites as R  # noqa: E402
import vf1_genealogy as gen  # noqa: E402
from test_family_history import _env, need_toolchain, vanilla_exe  # noqa: E402

INVALID = 0xFFFFFFFF


# ===================================================================== the sites
def test_the_header_is_a_fresh_render_of_the_proved_sites():
    data = vanilla_exe().read_bytes()
    assert R.render_header(R.validate(data)) == R.HEADER.read_text()


def test_the_sites_refuse_another_executable():
    data = bytearray(vanilla_exe().read_bytes())
    data[0x81CF0] ^= 0xFF
    with pytest.raises(R.SiteError):
        R.validate(bytes(data))


def test_the_layout_matches_the_backfill():
    # The C entry table and the patcher's are the same table.
    cpp = (ROOT / "native" / "vf1revive" / "vf1revive.cpp").read_text(encoding="utf-8")
    for name, value in (("E_BIO", rb.E_BIO), ("E_VSTATE", rb.E_VSTATE), ("E_SKILLS", rb.E_SKILLS),
                        ("E_LIKES", rb.E_LIKES), ("E_PEEP", rb.E_PEEP), ("E_PARENT1", rb.E_PARENT1),
                        ("E_PARENT2", rb.E_PARENT2), ("E_WHOLE", rb.E_WHOLE), ("E_WHOLE_SIZE", rb.WHOLE_SIZE),
                        ("kEntry", rb.ENTRY), ("E_MARKS", rb.E_MARKS), ("E_ROLE", rb.E_ROLE)):
        assert f"{name} = {value}," in cpp, name
    assert "kMaxEntries = 64" in cpp and rb.MAX_ENTRIES == 64
    fields = cpp[cpp.index("enum { FIELD_NAME"):cpp.index("FIELD_COUNT }")]
    assert len([f for f in fields.split(",") if "FIELD_" in f]) == len(rb.FIELDS)


def test_vf1fun_loads_it_after_the_log_and_charges_one_price():
    cpp = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8")
    assert cpp.index("LoadLogsCompanion();") < cpp.index('if (SettingOn(L"Revive", false))')
    family = (ROOT / "native" / "vf1fun" / "family.inc").read_text(encoding="utf-8")
    assert "static const int kRevivePrice = 25000;" in family
    assert "return gFreeCheats ? 0 : kRevivePrice;" in family


# ===================================================================== the DLL under emulation
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    exe = vanilla_exe()
    need_toolchain()
    out = tmp_path_factory.mktemp("revive_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_revive.bat")], capture_output=True, text=True,
                       env=dict(_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr          # /W4 /WX
    return {"exe": exe, "dll": out / "vf1revive.dll"}


def world(built, **kw):
    from revive_scenarios import ReviveWorld
    return ReviveWorld(built["exe"], built["dll"], **kw)


def family(built, **kw):
    """Ann (founder, 26) married to Bob (27); their children Cal (8, boy) and Dee (12, girl)."""
    w = world(built, **kw)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    assert w.marry(0, 1) == 1
    w.add_child(2, "Cal", 0, years=8, head=11, body=12)
    w.add_child(3, "Dee", 1, years=12, head=13, body=14)
    return w


def personalise(w, slot, *, voice=17, name_index=23, likes=(4, 5, 6), dislikes=(7, 8, 9), career=(-1, 0, 10, 0),
                fertility=91, wants=12, parents=(b"Joey", b"Ann", 3, 4, 7, 8)):
    """Who they are: every persistent field set to something the creator never gives."""
    e, v = w.e, w.villager(slot)
    bio = v + 0x2A34
    e.w32(bio + 8, name_index)
    e.w32(bio + 0xC, voice)
    e.write(bio + 0x34, parents[0].ljust(26, b"\0"))
    e.write(bio + 0x4E, parents[1].ljust(26, b"\0"))
    e.write(bio + 0x68, struct.pack("<4i", *parents[2:]))
    e.w32(v + 0x2B20, fertility)
    e.w32(v + 0x2B24, wants)
    e.write(v + 0x13620, struct.pack("<6i", *likes, *dislikes))
    e.write(v + 0x2B6C, struct.pack("<4i", *career))
    for i in range(6):
        e.w32(v + L.VILLAGER_STATE + 0x34 + 4 * i, 3)        # worn-out moods at death


def test_off_installs_nothing(built):
    w = world(built, setting=0)
    assert w.installed == 0 and w.status()["requested"] == 0
    assert w.changed_code() == set()


def test_on_installs_the_two_calls_and_the_two_vtable_slots(built):
    w = world(built)
    assert w.installed == 1, w.status()
    changed = w.changed_code()
    calls = (0x48E200, 0x489D8F, 0x489EAC, 0x48EB40, 0x48EB4C, 0x44123D, 0x441250)
    assert changed == {site + 1 + k for site in calls for k in range(4)}
    dll = w.e.dll.OPTIONAL_HEADER.ImageBase
    for slot in (R.GS_VTABLE_LOAD, R.GS_VTABLE_SAVE):
        assert w.e.r32(slot) not in (R.FUNCTIONS["GS_LOAD"], R.FUNCTIONS["GS_SAVE"])
    assert dll


def test_a_companion_wrapper_at_the_death_call_is_chained(built):
    seen = []

    def before(w):
        # Another companion (vf1logs.dll) retargeted the death behaviour's call first: a wrapper outside the exe.
        stub = w.e.fake_code(b"\xE9" + b"\0" * 4)
        struct_rel = (0x481CF0 - (stub + 5)) & 0xFFFFFFFF
        w.e.write(stub + 1, struct.pack("<I", struct_rel))
        from unicorn import UC_HOOK_CODE
        w.e.uc.hook_add(UC_HOOK_CODE, lambda *a: seen.append(1), begin=stub, end=stub)
        w.e.write(0x48E201, struct.pack("<i", stub - (0x48E200 + 5)))
    w = world(built, before_install=before)
    assert w.installed == 1
    w.start_family(0, "Ann", 1, 26)
    w.add_child(2, "Cal", 0)
    w.die(2)
    assert seen == [1] and w.count() == 1


# ---------------------------------------------------------------- the snapshot at every death
def test_a_death_is_snapshotted_before_the_tree_forgets_it(built):
    w = family(built)
    personalise(w, 2)
    w.die(2, cause=0)
    assert w.count() == 1
    i = w.info(0)
    assert (i["state"], i["sex"], i["died_units"], i["cause"], i["generation"], i["role"], i["exact"]) == \
           (1, 0, 160, 0, 1, 2, 1)
    assert w.name(0) == "Cal" and i["why"] == 0 and i["source"] == 1
    assert s32(w.e.r32(w.peep(2) + 0x28)) == -1             # the game's ReportDeath ran after the snapshot


def test_the_body_removal_after_the_death_takes_no_second_snapshot(built):
    w = family(built)
    w.die(2)
    w.e.write(w.villager(2) + L.VILLAGER_PRESENT, b"\x01")   # the body stays until it is removed
    w.die(2, how="body")
    assert w.count() == 1


def test_only_the_dead_are_snapshotted(built):
    w = family(built)
    # The body-removal call with someone still alive (the game never does it; the DLL refuses it anyway).
    w.e.write(w.villager(3) + L.VILLAGER_PRESENT, b"\x01")
    w.run(0x489D7F, 0x489D94, esi=w.villager(3) + L.VILLAGER_LEFT_HOME)
    # Divorce, The Talent Scout and eviction take the person away without a death: no ReportDeath, no snapshot.
    w.e.write(w.villager(1) + L.VILLAGER_PRESENT, b"\0")
    w.leave_home_at_19(2)
    assert w.count() == 0


# ---------------------------------------------------------------- the sidecar
def test_the_sidecar_is_written_with_the_save_and_names_it(built):
    w = family(built)
    w.die(2)
    assert w.save_game() == 1
    data = w.sidecar()
    side = rb.read_sidecar(data)
    assert side is not None and len(side.entries) == 1 and w.status()["lastSave"] == 1
    assert (side.save_hash, side.save_size) == (gen.fnv1a64(w.save_bytes()), len(w.save_bytes()))
    # SaveCurrentGame's Save(slot + 20) rotated it: the copy beside <N+20> names that save.
    copy = rb.read_sidecar(w.sidecar(w.slot + 20))
    assert copy is not None and (copy.save_hash, copy.save_size) == (gen.fnv1a64(w.save_bytes(w.slot + 20)),
                                                                     len(w.save_bytes(w.slot + 20)))
    assert rb.Snapshot(side.entries[0]).name == "Cal"


def test_a_load_reads_the_snapshots_back(built):
    w = family(built)
    w.die(2)
    w.save_game()
    assert w.forget() == 1
    assert w.count() == 1 and w.status()["lastLoad"] == 1 and w.name(0) == "Cal"


def test_a_sidecar_of_another_save_gives_only_the_dead_not_alive_now(built):
    w = family(built)
    w.die(2)
    w.die(3)
    w.save_game()
    # Another tool changed the save afterwards: the file still validates but names the save as it was.
    w.fs.write(f"{rb_save_dir()}\\Virtual Families{w.slot}.ldw", w.save_bytes() + b"!")
    w.set_villager(3, "Dee", 1, years=12, head=13, body=14)   # Dee is alive in this save
    w.forget()
    assert w.status()["lastLoad"] == 3 and [w.name(i) for i in range(w.count())] == ["Cal"]


def rb_save_dir():
    from revive_scenarios import SAVE_DIR
    return SAVE_DIR


def test_a_damaged_sidecar_is_moved_aside_never_deleted(built):
    w = family(built)
    w.die(2)
    w.save_game()
    path = f"{rb_save_dir()}\\Virtual Families 1 Patcher Data\\Revive\\Virtual Families{w.slot}.ldw.dat"
    bad = bytearray(w.fs.read(path))
    bad[100] ^= 1
    w.fs.write(path, bytes(bad))
    w.forget()
    assert w.status()["lastLoad"] in (2, 5)
    aside = w.fs.read(path.replace(".ldw.dat", ".ldw.unreadable-1.dat"))
    assert aside == bytes(bad)


def test_a_shut_sidecar_is_left_as_it_is(built):
    w = family(built)
    w.die(2)
    w.save_game()
    path = f"{rb_save_dir()}\\Virtual Families 1 Patcher Data\\Revive\\Virtual Families{w.slot}.ldw.dat"
    before = w.fs.read(path)
    w.fs.locked.add(w.fs.key(path))
    w.forget()
    assert w.status()["lastLoad"] == 6
    w.save_game()                                  # neither read, rotated, set aside nor replaced while shut
    w.fs.locked.clear()
    assert w.fs.read(path) == before


# ---------------------------------------------------------------- reviving
def test_a_child_comes_back_as_who_they_were_at_the_age_they_died(built):
    w = family(built)
    personalise(w, 2)
    w.die(2)
    assert w.surviving() == 1
    slot, how = w.revive(0)
    assert how == 1 and slot >= 0
    v, e = w.villager(slot), w.e
    bio = v + 0x2A34
    assert e.cstr(bio + 0x10) == "Cal" and s32(e.r32(bio + 4)) == 0
    assert (s32(e.r32(bio + 0x2C)), s32(e.r32(bio + 0x30))) == (11, 12)            # head and body
    assert s32(e.r32(v + L.VILLAGER_AGE)) == 160                                     # died at 8: back at 8
    assert (s32(e.r32(bio + 8)), s32(e.r32(bio + 0xC))) == (23, 17)                  # name index, voice
    assert e.read(bio + 0x34, 4) == b"Joey" and e.read(bio + 0x4E, 3) == b"Ann"
    assert struct.unpack("<4i", e.read(bio + 0x68, 16)) == (3, 4, 7, 8)
    assert struct.unpack("<6i", e.read(v + 0x13620, 24)) == (4, 5, 6, 7, 8, 9)        # likes, dislikes
    assert (s32(e.r32(v + 0x2B20)), s32(e.r32(v + 0x2B24))) == (91, 12)               # fertility, Wants kids?
    # Moods and needs start fresh: the creator's, not the worn-out ones at death.
    from revive_scenarios import FRESH_STATS
    assert struct.unpack("<6i", e.read(v + L.VILLAGER_STATE + 0x34, 24)) == FRESH_STATS
    assert s32(e.r32(v + L.VILLAGER_HEALTH)) == 90
    # Their own Family Tree entry points at them again, and the game counts them as a surviving child.
    assert s32(e.r32(w.peep(2) + 0x28)) == slot and w.surviving() == 2
    assert w.info(0)["state"] == 2 and w.status()["revived"] == 1


def test_died_at_18_or_older_comes_back_at_exactly_18(built):
    w = family(built)
    personalise(w, 0, career=(12, 3, 10, 2500))
    w.e.w32(w.villager(0) + L.VILLAGER_AGE, 71 * 20 + 7)                # 71 years and 7 units
    w.die(0)
    assert w.info(0)["back_units"] == 360
    slot, how = w.revive(0)
    assert slot >= 0 and s32(w.e.r32(w.villager(slot) + L.VILLAGER_AGE)) == 360
    # The career comes back with them (the game keeps no career history, only the career at death).
    assert struct.unpack("<4i", w.e.read(w.villager(slot) + 0x2B6C, 16)) == (12, 3, 10, 2500)


@pytest.mark.parametrize("units, back", [(17 * 20 + 19, 17 * 20 + 19), (18 * 20, 360), (18 * 20 + 1, 360), (3, 3)])
def test_the_age_rule_in_the_games_own_units(built, units, back):
    w = family(built)
    w.e.w32(w.villager(3) + L.VILLAGER_AGE, units)
    w.die(3)
    slot, _how = w.revive(0)
    assert s32(w.e.r32(w.villager(slot) + L.VILLAGER_AGE)) == back


def test_a_parent_who_died_with_children_gets_their_place_back(built):
    w = family(built)
    w.die(1)                                       # Bob, parent 2, with children: his entry stays, slot -1
    assert s32(w.e.r32(w.peep(1) + 0x28)) == -1
    slot, how = w.revive(0)
    assert how == 4 and s32(w.e.r32(w.peep(1) + 0x28)) == slot


def remarried(built):
    """Ann married Bob; Bob died before any child (the game frees his place); Ann married Eli."""
    w = world(built)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    w.marry(0, 1)
    w.die(1)                                       # no children: the game frees the spouse's place
    assert w.e.read(w.peep(1) + 0x1A, 1) == b"\0"
    w.set_villager(4, "Eli", 0, years=30, head=9, body=10)
    w.marry(0, 4)                                  # Ann remarried
    return w


def test_a_spouse_whose_partner_remarried_comes_back_as_a_family_member_in_a_child_entry(built):
    # The owner, 2026-11-26: a family member, placed in the Family Tree as a CHILD ENTRY (as Virtual Families 2).
    w = remarried(built)
    slot, how = w.revive(0)
    assert slot >= 0 and how == 6
    rec = w.record()
    assert s32(w.e.r32(rec + L.RECORD_CHILD_COUNT)) == 1                  # the game's own AddOffspring made it
    child = w.peep(2)
    assert w.e.cstr(child) == "Bob" and s32(w.e.r32(child + 0x28)) == slot
    assert (s32(w.e.r32(child + 0x1C)), s32(w.e.r32(child + 0x20)), s32(w.e.r32(child + 0x24))) == (0, 7, 8)
    assert w.e.cstr(w.peep(1)) == "Eli" and s32(w.e.r32(w.peep(1) + 0x28)) == 4   # Eli stays the spouse
    assert w.surviving() == 1


def test_with_no_child_place_left_the_family_member_is_outside_the_tree(built):
    w = remarried(built)
    for k in range(6):                                                    # the generation's six child places
        w.add_child(10 + k, f"K{k}", k % 2, years=3)
    tree_before = w.e.read(w.record(), L.FAMILY_RECORD_SIZE)
    slot, how = w.revive(0)
    assert slot >= 0 and how == 5
    assert w.e.read(w.record(), L.FAMILY_RECORD_SIZE) == tree_before


def test_a_spouse_whose_place_is_still_free_comes_back_as_the_spouse(built):
    w = world(built)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    w.marry(0, 1)
    w.die(1)
    slot, how = w.revive(0)
    assert how == 4
    p2 = w.peep(1)
    assert w.e.read(p2 + 0x1A, 1) == b"\x01" and w.e.cstr(p2) == "Bob" and s32(w.e.r32(p2 + 0x28)) == slot


def test_a_child_7_to_28_gets_their_place_back_through_up_to_28_children(built):
    w = family(built)
    w.load_kids()
    w.set_villager(5, "Fay", 1, years=6, head=15, body=16, career=INVALID)   # an extra child: not in the stock tree
    w.extra_children[5] = (1, "Fay")
    w.die(5)
    assert w.info(0)["role"] == 8
    slot, how = w.revive(0)
    assert how == 2 and w.kids_revived == [(5, 1, "Fay", slot)]


# ---------------------------------------------------------------- refusals
def test_refused_when_they_are_alive(built):
    w = family(built)
    w.die(2)
    w.set_villager(2, "Cal", 0, years=8, head=11, body=12)        # a stale snapshot: Cal is in the house
    assert w.info(0)["why"] == 3
    assert w.revive(0)[0] == -3


def test_refused_a_second_time(built):
    w = family(built)
    w.die(2)
    assert w.revive(0)[0] >= 0
    assert w.revive(0)[0] == -1 and w.info(0)["why"] == 1


def test_refused_for_an_earlier_generation(built):
    w = family(built)
    w.die(2)
    w.next_generation(3, 1)                        # Dee inherits the house
    assert w.info(0)["why"] == 2 and w.revive(0)[0] == -2


def test_refused_when_the_house_is_full(built):
    w = family(built)
    w.die(2)
    for s in range(30):
        if not w.e.read(w.villager(s) + L.VILLAGER_PRESENT, 1)[0]:
            w.set_villager(s, f"P{s}", s % 2, years=30)
    assert w.revive(0)[0] == -4


def test_a_failed_read_back_takes_the_new_villager_away_and_changes_nothing(built):
    w = family(built)
    w.die(2)
    w.spawn_age_override = 999                     # the creator gives the wrong age
    tree_before = w.e.read(w.record(), L.FAMILY_RECORD_SIZE)
    slot, _how = w.revive(0)
    assert slot == -7
    assert w.e.read(w.record(), L.FAMILY_RECORD_SIZE) == tree_before
    # The new villager (named Cal by the write-back) was taken away again: nobody alive is called Cal.
    assert [s for s in range(30) if w.e.read(w.villager(s) + L.VILLAGER_PRESENT, 1)[0]
            and s32(w.e.r32(w.villager(s) + L.VILLAGER_HEALTH)) > 0
            and w.e.cstr(w.villager(s) + L.VILLAGER_NAME) in ("Fresh", "Cal")] == []
    assert w.info(0)["state"] == 1                 # still dead, still revivable


@pytest.mark.parametrize("mark", [0, 3])          # unknown (an older file), "unknown -> 18" (the backfill now)
def test_an_unknown_age_at_death_comes_back_at_18(built, mark):
    w = family(built)
    w.die(2)
    w.save_game()
    path = f"{rb_save_dir()}\\Virtual Families 1 Patcher Data\\Revive\\Virtual Families{w.slot}.ldw.dat"
    side = rb.read_sidecar(w.fs.read(path))
    raw = bytearray(side.entries[0])
    at = 2 * rb.FIELDS.index("age at death")
    bits = (struct.unpack_from("<Q", raw, rb.E_MARKS)[0] & ~(3 << at)) | (mark << at)
    struct.pack_into("<Q", raw, rb.E_MARKS, bits)
    w.fs.write(path, rb.render_sidecar(w.save_bytes(), side.generations, side.parent_slot, side.parent_sex, [bytes(raw)]))
    w.forget()
    i = w.info(0)
    assert (i["why"], i["back_units"], i["age_known"]) == (0, 360, 0)   # Cal died at 8, but that is not known
    slot, _how = w.revive(0)
    assert slot >= 0 and s32(w.e.r32(w.villager(slot) + L.VILLAGER_AGE)) == 360


# ---------------------------------------------------------------- a revived spouse is a grown-up at 19
def test_the_at_19_call_is_hooked_only_with_the_setting(built):
    stock = (0x48F080 - (0x489EAC + 5)) & 0xFFFFFFFF
    assert world(built).e.r32(0x489EAD) != stock                          # retargeted to the DLL
    assert world(built, setting=0).e.r32(0x489EAD) == stock


def test_a_revived_spouse_with_no_career_is_not_sent_to_college_at_19(built):
    # The owner, 2026-11-26: treated as an adult. The game's own ageing code from the age test at 0x489E96: with no
    # career a 19-year-old is sent away; for the revived spouse HasCareer at 0x489EAC answers "yes" (this call only).
    w = family(built)
    w.e.write(w.villager(1) + 0x2B6C, struct.pack("<4i", -1, 0, 10, 0))    # Bob never had a career
    w.die(1)                                       # Bob, the spouse, dies with children: his place waits
    slot, how = w.revive(0)
    assert how == 4 and w.e.r32(w.villager(slot) + 0x2B6C) == INVALID     # no career
    assert w.at_19(slot) == "stays"
    assert w.e.read(w.villager(slot) + L.VILLAGER_LEFT_HOME, 1) == b"\0"
    assert w.e.r32(w.villager(slot) + 0x2B6C) == INVALID                  # still no career: nothing else changes


def test_a_child_with_no_career_still_goes_to_college_at_19(built):
    w = family(built)
    assert w.at_19(3) == "leaves"                  # Dee, never revived: the game's own rule
    w.die(2)
    slot, how = w.revive(0)                        # Cal, a revived CHILD: the game's own rule too
    assert how == 1 and w.at_19(slot) == "leaves"


def test_the_grown_up_rule_survives_a_save_and_load(built):
    w = family(built)
    w.e.write(w.villager(1) + 0x2B6C, struct.pack("<4i", -1, 0, 10, 0))
    w.die(1)
    slot, _how = w.revive(0)
    w.save_game()
    w.forget()
    assert w.info(0)["state"] == 2 and w.at_19(slot) == "stays"


def s32(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


def test_a_backfilled_snapshot_is_read_and_revived_with_its_unknown_fields_fresh(built):
    # The patcher's backfill writes the same file: a child the Family Tree and the log remember (no record left).
    w = family(built)
    w.die(2)
    w.save_game()
    tree = lambda which: w.e.read(w.peep(which), rb.PEEP_SIZE)  # noqa: E731
    d = rb.Dead("Cal", 0, 11, 12, 1, 2, tree(2), tree(0), tree(1), age_years=8, cause=0)
    entry = rb.build_entry(d, None, rb.SOURCE_TREE, False, "Cal")
    path = f"{rb_save_dir()}\Virtual Families 1 Patcher Data\Revive\Virtual Families{w.slot}.ldw.dat"
    w.fs.write(path, rb.render_sidecar(w.save_bytes(), 1, 0, 1, [entry]))
    w.forget()
    i = w.info(0)
    assert (i["source"], i["exact"], i["age_known"], i["why"], i["back_units"]) == (rb.SOURCE_TREE, 0, 1, 0, 160)
    slot, how = w.revive(0)
    assert how == 1 and slot >= 0
    v = w.villager(slot)
    from revive_scenarios import FRESH_VOICE, FRESH_FERTILITY
    assert w.e.cstr(v + L.VILLAGER_NAME) == "Cal" and s32(w.e.r32(v + L.VILLAGER_HEAD)) == 11
    assert s32(w.e.r32(v + 0x2A34 + 0xC)) == FRESH_VOICE and s32(w.e.r32(v + 0x2B20)) == FRESH_FERTILITY
    assert s32(w.e.r32(v + L.VILLAGER_AGE)) == 160


# ---------------------------------------------------------------- a revived spouse can have babies
def no_career(w, slot):
    w.e.write(w.villager(slot) + 0x2B6C, struct.pack("<4i", -1, 0, 10, 0))


def test_a_revived_father_with_no_career_can_father_a_baby(built):
    # The owner, 2026-11-26: the game's own try-for-a-baby step chooses the parents with GetMatriarch / GetPatriarch
    # (a career needed); for a revived spouse with none it counts them as having one.
    w = family(built)
    no_career(w, 1)
    w.die(1)                                       # Bob, the father, dies with children; Ann has a career
    assert w.try_for_a_baby(0) is None             # nobody with a career is a father: the game gives up
    slot, how = w.revive(0)
    assert how == 4
    mother, father, pregnant = w.try_for_a_baby(0)
    assert (mother, father, pregnant) == (0, slot, True)


def test_a_revived_mother_with_no_career_can_have_a_baby(built):
    w = family(built)
    no_career(w, 0)
    w.die(0)                                       # Ann, the mother (the founder), dies with children
    slot, how = w.revive(0)
    assert how == 3
    mother, father, pregnant = w.try_for_a_baby(slot)
    assert (mother, father, pregnant) == (slot, 1, True)


def test_a_revived_child_with_no_career_is_still_no_parent(built):
    w = family(built)
    w.e.write(w.villager(1) + L.VILLAGER_PRESENT, b"\0")  # Bob is away (not dead): Ann has no man with a career
    w.die(2)                                       # Cal, a child, then revived: no career, no baby
    slot, how = w.revive(0)
    assert how == 1
    w.e.w32(w.villager(slot) + L.VILLAGER_AGE, 400)
    assert w.try_for_a_baby(0) is None             # the game's own rule for him


def test_a_drop_on_the_spouse_counts_the_revived_spouse_as_having_a_career(built):
    w = family(built)
    no_career(w, 1)
    w.die(1)
    slot, _how = w.revive(0)
    assert w.drop_on_spouse_careers(0, slot) == "both"
    assert w.drop_on_spouse_careers(0, 3) == "no"  # Dee, a child with no career: the game's own answer


def test_with_no_revived_grown_up_the_games_own_choice_stands(built):
    w = family(built)
    mother, father, pregnant = w.try_for_a_baby(0)
    assert (mother, father, pregnant) == (0, 1, True)
