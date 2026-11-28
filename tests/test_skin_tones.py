"""Skin Tones (native/vf1skin/vf1skin.cpp; docs/SKIN_TONES.md): who gets which tone, the file beside each save, renames,
Change Appearance and its log record, and what Revive keeps.

The shipped DLL is built and run under emulation with the game's own code at every hooked site (tests/skin_scenarios.py:
the real Impregnate for a conception, the real ChangeName for a rename, the real SaveCurrentGame for a save). The
drawing is tests/test_skin_tone_draw.py's. The owner's decisions (2026-11-26) are each a test below."""
from __future__ import annotations

import subprocess

import pytest

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

from conftest import ROOT  # noqa: E402
import vf1_genealogy as gen  # noqa: E402
import vf1_skin_tones as st  # noqa: E402
from test_family_history import _env, need_toolchain, vanilla_exe  # noqa: E402

INVALID = 0xFFFFFFFF


# ===================================================================== always
def test_the_tables_agree():
    cpp = (ROOT / "native" / "vf1skin" / "vf1skin.cpp").read_text(encoding="utf-8")
    tables = (ROOT / "native" / "vf1skin" / "skin_tables.h").read_text(encoding="utf-8")
    for name in st.TONE_NAMES:
        assert f'{{ "{name}",' in tables
    assert '{ "Game\'s own",' in tables and st.DEFAULT_NAME == "Game's own"
    assert "kEntry = 64, kMaxEntries = 400" in cpp and st.ENTRY == 64 and st.MAX_ENTRIES == 400
    assert '"VF1SKIN\\0"' in cpp and st.MAGIC == b"VF1SKIN\x00"
    assert "Virtual Families 1 Patcher Data\\\\Skin Tones\\\\" in cpp and st.FOLDER == "Skin Tones"
    assert st.inherit(3, 5, 50, 1, 0) == 4 and st.inherit(3, 5, 4, 1, 6) == 7 and st.inherit(0, 9, 50, 2, 0) == 10
    assert st.inherit(1, 1, 50, 0, 0) == 1 and st.inherit(10, 10, 99, 2, 0) == 10 and st.inherit(0, 0, 99, 1, 2) == 3


def test_vf1fun_loads_it_after_revive():
    cpp = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8")
    assert cpp.index("LoadReviveCompanion();") < cpp.index('if (SettingOn(L"SkinTones", false))')
    assert cpp.index('if (SettingOn(L"SkinTones", false))') < cpp.index('if (SettingOn(L"RenderUnicodeInGameFonts"')


# ===================================================================== the DLL under emulation
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    exe = vanilla_exe()
    need_toolchain()
    out = tmp_path_factory.mktemp("skin_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_skin.bat")], capture_output=True, text=True,
                       env=dict(_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr          # /W4 /WX
    return {"exe": exe, "dll": out / "vf1skin.dll"}


def world(built, **kw):
    from skin_scenarios import SkinWorld
    return SkinWorld(built["exe"], built["dll"], **kw)


def family(built, **kw):
    """Ann (founder, 26) married to Bob (27); their children Cal (8, boy) and Dee (12, girl)."""
    w = world(built, **kw)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    assert w.marry(0, 1) == 1
    w.add_child(2, "Cal", 0, years=8, head=11, body=12)
    w.add_child(3, "Dee", 1, years=12, head=13, body=14)
    return w


def test_off_installs_nothing(built):
    w = world(built, setting=0)
    assert w.installed == 0 and w.status()["requested"] == 0
    assert w.changed_code() == set()
    assert w.tone(0) is None


def test_on_installs_the_hooks_and_chains_the_vtable(built):
    import vf1_skin_sites as S
    w = world(built)
    assert w.installed == 1, w.status()
    changed = w.changed_code()
    expected = set()
    for key, _pin, stolen in S.ENTRY_HOOKS:
        va = S.FUNCTIONS[key]
        expected |= {a for a in range(va, va + stolen) if w.e.read(a, 1) != w.exe.read(a, 1)}
    for _pin, site, _target in S.CALL_HOOKS:
        expected |= set(range(site + 1, site + 5))
    assert changed and changed <= expected | {S.FUNCTIONS[k] for k, _p, _s in S.ENTRY_HOOKS}
    for slot in (S.GS_VTABLE_LOAD, S.GS_VTABLE_SAVE):
        assert w.e.r32(slot) not in (S.FUNCTIONS["GS_LOAD"], S.FUNCTIONS["GS_SAVE"])


def test_a_companion_wrapper_at_the_conception_call_is_chained(built):
    """vf1fun.dll and vf1logs.dll retarget the same Impregnate call first: the DLL calls what is there."""
    import struct
    from unicorn import UC_HOOK_CODE
    seen = []

    def before(w):
        stub = w.e.fake_code(b"\xE9" + struct.pack("<i", 0))
        w.e.write(stub + 1, struct.pack("<i", 0x4864D0 - (stub + 5)))
        w.e.uc.hook_add(UC_HOOK_CODE, lambda *a: seen.append(1), begin=stub, end=stub)
        w.e.write(0x48EBB3, struct.pack("<i", stub - (0x48EBB2 + 5)))
    w = world(built, before_install=before)
    assert w.installed == 1
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    w.marry(0, 1)
    assert w.conceive(rolls=[99, 99, 0], names=["Kim"]) == 1
    assert seen and w.status()["babies"] == 1


def test_a_changed_executable_installs_nothing(built):
    def before(w):
        w.e.write(0x486B66, b"\x90")                     # inside the portrait's pin
    w = world(built, before_install=before)
    assert w.installed == 0 and w.status()["resolved"] == 0
    assert w.changed_code() == {0x486B66}


# ----------------------------------------------------------------- who gets which tone
def test_a_family_with_no_file_gets_random_tones_once_and_keeps_them(built):
    """People already in a family when the patch is installed: a random tone each on the first load (the DLL's own
    generator), which is also their birth tone; the save keeps them; the next load gives them back exactly."""
    w = family(built)
    assert w.load() == 1 and w.status()["lastLoad"] == 4
    tones = {s: w.tone(s) for s in range(4)}
    assert all(1 <= t <= 10 and b == t for t, b in tones.values()), tones
    assert len({t for t, _b in tones.values()}) > 1               # random, not one tone for everybody
    assert w.save_game() == 1 and w.status()["lastSave"] == 1
    data = st.read(w.sidecar())
    assert data is not None and gen.sidecar_key(w.sidecar()) == (gen.fnv1a64(w.save_bytes()), len(w.save_bytes()))
    by_slot = {p.slot: p for p in data.people}
    assert {s: (by_slot[s].tone, by_slot[s].birth) for s in range(4)} == tones
    assert by_slot[0].places == ((1, 0),) and by_slot[1].places == ((1, 1),) and by_slot[2].places == ((1, 2),)
    for s in range(4):                                         # the session forgets; the file gives them back
        w.set_tone(s, 15)
    assert w.load() == 1 and w.status()["lastLoad"] == 1
    assert {s: w.tone(s) for s in range(4)} == tones


def fresh_pregnancy(w):
    """The last conception's babies gone and the family's two stock children only, so the next can come."""
    for k in range(3):
        w.e.w32(w.state + 0x1B120 + 4 * k, INVALID)
    for slot in range(4, 10):
        w.e.write(w.villager(slot) + 0x13574, b"\0")
        w.e.write(w.villager(slot) + 0x2A44, b"\0" * 25)
    w.e.w32(w.record() + 0x1B4, 2)
    w.e.w32(w.villager(0) + 0x2AF8, 0)
    w.e.w32(w.villager(0) + 0x2AFC, 0)


def test_a_baby_inherits_the_parents_average_and_twins_copy_the_first(built):
    """95%: (father + mother) / 2 + rand(3) - 1, held to 1..10; 5%: any tone. Rolled once at the conception, the
    babies hidden until the birth; twins and triplets copy the first baby. Nothing depends on sex."""
    w = family(built)
    w.load()
    near = far = 0
    for trial in range(60):
        mother, father = 1 + trial % 10, 1 + (trial * 7) % 10
        w.set_tone(0, mother)
        w.set_tone(1, father)
        fresh_pregnancy(w)
        twins = trial % 3 == 0
        rolls = [0, 99] if twins else [99, 99, 0]          # the twin roll, or one baby
        assert w.conceive(rolls=rolls, names=["Kit", "Kat"]) == 1
        babies = [s32 for s32 in (w.e.r32(w.state + 0x1B120 + 4 * k) for k in range(3)) if s32 != INVALID]
        assert len(babies) == (2 if twins else 1)
        tones = [w.tone(s) for s in babies]
        assert all(t == tones[0] for t in tones) and tones[0][0] == tones[0][1]
        if abs(tones[0][0] - (mother + father) // 2) <= 1:
            near += 1
        else:
            far += 1
    assert near >= 50 and w.status()["babies"] >= 60
    del far


def test_a_parent_with_no_tone_counts_as_the_other(built):
    w = family(built)
    w.load()
    w.set_tone(0, 9)
    w.set_tone(1, 15)                                   # Default: no tone to inherit
    got = []
    for trial in range(12):
        fresh_pregnancy(w)
        assert w.conceive(rolls=[99, 99, 0], names=["Kit"]) == 1
        got.append(w.tone(w.e.r32(w.state + 0x1B120))[0])
    assert sum(1 for t in got if 8 <= t <= 10) >= 10, got


def test_an_arrival_is_random_and_a_copy_of_someone_keeps_their_tone(built):
    w = family(built)
    w.load()
    w.set_tone(2, 6)
    w.set_villager(9, "Visitor", 1, years=30, head=40, body=41)       # someone new in the house
    t = w.tone(9)
    assert t is not None and 1 <= t[0] <= 10 and t[0] == t[1]
    # the game's copy of Cal (the death behaviour's copy, Next Generation's adult heir): the same person
    w.e.write(w.villager(12), w.e.read(w.villager(2), 0x145FC))
    w.e.w32(w.villager(12) + 0x13538, 12)
    assert w.tone(12)[0] == 6
    w.set_tone(12, 2)                                 # one person: changing the copy changes them both
    assert w.tone(2)[0] == 2


# ----------------------------------------------------------------- the Preferred skin tone (the owner, 2026-11-28)
def test_a_preferred_tone_goes_to_about_four_in_five_randomly_made_people_never_to_babies(built):
    """settings.ini [SkinTones] PreferredTone: with one of the ten tones, about 4 in 5 of the people given a random tone
    (the family on the first load, every newcomer) get it and the rest a random tone; a baby still inherits."""
    w = family(built, preferred=6)
    assert w.status()["preferred"] == 6
    w.load()
    people = [w.tone(s)[0] for s in range(4)]
    for slot in range(5, 30):
        w.set_villager(slot, f"Visitor{slot}", slot % 2, years=30, head=slot, body=slot)
        t = w.tone(slot)
        assert t[0] == t[1]                                       # a newcomer's tone is also their birth tone
        people.append(t[0])
    assert all(1 <= t <= 10 for t in people)
    sixes = people.count(6)
    assert 0.6 * len(people) <= sixes < len(people), people     # about 4 in 5, never everybody by force
    # babies: the parents' rule only (here both parents Porcelain: Porcelain or Fair, 5% any)
    w.set_tone(0, 1)
    w.set_tone(1, 1)
    got = []
    for _trial in range(20):
        fresh_pregnancy(w)
        assert w.conceive(rolls=[99, 99, 0], names=["Kit"]) == 1
        got.append(w.tone(w.e.r32(w.state + 0x1B120))[0])
    assert sum(1 for t in got if t <= 2) >= 17 and got.count(6) <= 2, got


@pytest.mark.parametrize("value,kept", [(0, 0), (11, 0), (10, 10)])
def test_the_preferred_tone_setting_is_read_and_held_to_the_ten(built, value, kept):
    w = world(built, preferred=value)
    assert w.installed == 1 and w.status()["preferred"] == kept


# ----------------------------------------------------------------- renames and the tree
def test_a_rename_keeps_the_tone(built):
    w = family(built)
    w.load()
    w.set_tone(3, 4)
    w.rename(3, "Deedee")
    assert w.tone(3) == (4, w.tone(3)[1])
    w.save_game()
    names = {p.slot: p.name for p in st.read(w.sidecar()).people}
    assert names[3] == b"Deedee"


def test_the_family_tree_draws_each_person_in_their_tone_the_dead_too(built):
    w = family(built)
    w.load()
    for slot, tone in ((0, 3), (1, 5), (2, 7), (3, 9)):
        w.set_tone(slot, tone)
    assert [w.draw_tree_person(k) for k in (0, 1, 2, 3)] == [3, 5, 7, 9]
    w.die(2)                                          # Cal dies: the tree keeps him, in his tone
    w.save_game()
    w.e.write(w.villager(2) + 0x2A44, b"\0" * 25)    # his slot is someone else's now
    w.set_villager(2, "Newbie", 1, years=0, head=1, body=1)
    assert w.draw_tree_person(2) == 7
    assert w.load() == 1                              # and after a load, from the file
    assert w.draw_tree_person(2) == 7


def test_revives_late_spouse_drawn_under_the_spouse_has_their_tone(built):
    """vf1revive.dll draws a remarried partner's late spouse with the tree's own spouse block, edi a record of its own
    (parent 2 the revived person, slot their villager slot): the same call 0x439E01, their own tone."""
    w = family(built)
    w.load()
    w.set_villager(6, "Liz", 1, years=20, head=30, body=31)
    w.set_tone(6, 2)
    extra = w.e.alloc(0x6C8)
    w.e.write(extra + 0xDC, b"Liz\0")
    w.e.write(extra + 0xDC + 0x1A, b"\1")
    for off, v in ((0x1C, 1), (0x20, 30), (0x24, 31), (0x28, 6)):
        w.e.w32(extra + 0xDC + off, v)
    assert w.draw_tree_person(1, record=extra) == 2
    w.e.write(extra + 0xDC, b"Ann\0")               # a record naming someone else than the slot holds: no tone
    assert w.draw_tree_person(1, record=extra) == 0


def test_installs_beside_revives_tree_detour(built):
    """vf1revive.dll (loaded first) puts a jmp at the spouse block's end, 0x439E7D: Skin Tones still installs."""
    def before(w):
        w.e.write(0x439E7D, b"\xE9" + (0x10000000).to_bytes(4, "little") + b"\x00")
    w = world(built, before_install=before)
    assert w.installed == 1


def test_an_earlier_generation_is_toned_on_the_first_load(built):
    w = family(built)
    w.next_generation(2, 2)                           # Cal inherits: generation 2
    assert w.generations() == 2
    w.load()
    t = [w.draw_tree_person(k, g=1) for k in (0, 1, 2, 3)]
    assert all(1 <= x <= 10 for x in t)
    assert w.draw_tree_person(0, g=2) == w.draw_tree_person(2, g=1)       # the heir, the same person


# ----------------------------------------------------------------- Change Appearance and the log
def test_change_appearance_sets_resets_and_logs(built):
    w = family(built)
    w.load()
    born = w.tone(2)[1]
    other = 10 if born != 10 else 1
    assert w.set_tone(2, other) == 1 and w.tone(2) == (other, born)
    assert w.logged[-1] == (8, 2, born, other)                 # "Appearance changed": old, new
    assert w.set_tone(2, 15) == 1 and w.tone(2) == (15, born)
    assert w.logged[-1] == (8, 2, other, 15)
    assert w.reset_tone(2) == 1 and w.tone(2) == (born, born)
    assert w.logged[-1] == (8, 2, 15, born)
    n = len(w.logged)
    assert w.set_tone(2, born) == 1 and len(w.logged) == n     # no change, no record
    assert w.set_tone(2, 11) == 0 and w.set_tone(2, 0) == 0 and w.set_tone(25, 3) == 0
    assert [w.tone_name(t) for t in (1, 5, 10, 15, 0)] == ["Porcelain", "Copper", "Ebony", "Game's own", "Game's own"]


def test_without_the_log_a_change_still_happens(built):
    w = family(built, logs=False)
    w.load()
    assert w.set_tone(1, 6) == 1 and w.tone(1)[0] == 6 and not w.logged


# ----------------------------------------------------------------- Revive
def test_revive_keeps_the_two_bytes_and_gives_them_back(built):
    w = family(built)
    w.load()
    w.set_tone(3, 8)
    tone, birth = w.tone_of(3)
    assert tone == 8 and 1 <= birth <= 10
    w.die(3)
    w.e.write(w.villager(3) + 0x13574, b"\0")
    w.set_villager(7, "Dee", 1, years=18, head=13, body=14)   # Revive brings her back in another slot
    assert w.tone_give(7, tone, birth) == 1
    assert w.tone(7) == (8, birth)
    n = len(w.logged)
    assert w.tone_give(7, 12, 0) == 0 and w.tone_give(7, 3, 11) == 0 and w.tone_give(29, 3, 3) == 0
    assert len(w.logged) == n                                  # giving back is not a change: no record
    assert w.tone_of(29) == (0, 0)


def test_revive_gets_nothing_while_skin_tones_are_off(built):
    w = family(built, setting=0)
    assert w.tone_of(0) == (0, 0) and w.tone_give(0, 3, 3) == 0


# ----------------------------------------------------------------- the file's safety
def test_the_backup_save_keeps_the_previous_file(built):
    from skin_scenarios import SKIN_DIR
    w = family(built)
    w.load()
    w.set_tone(0, 2)
    w.save_game()
    w.set_tone(0, 9)
    w.save_game()
    # SaveCurrentGame saves the slot and then slot + 20: each save file has its own file beside it, rotated with it
    for n in (1, 21, 41):
        side = st.read(w.sidecar(n))
        assert side is not None and (side.save_hash, side.save_size) == (gen.fnv1a64(w.save_bytes(n)),
                                                                         len(w.save_bytes(n)))
    assert {p.slot: p.tone for p in st.read(w.sidecar(41)).people}[0] == 2
    # the save's own file lost, the backup's names the same save: it is read
    w.fs.files.pop(w.fs.key(f"{SKIN_DIR}\\Virtual Families1.ldw.dat"))
    w.fs.files[w.fs.key(st_save(w, 1))] = w.fs.read(st_save(w, 21))
    w.set_tone(0, 4)
    assert w.load() == 1 and w.status()["lastLoad"] == 2 and w.tone(0)[0] == 9


def st_save(w, n):
    from history_scenarios import SAVE_DIR
    return f"{SAVE_DIR}\\Virtual Families{n}.ldw"


def test_a_damaged_file_is_set_aside_never_deleted(built):
    from skin_scenarios import SKIN_DIR
    w = family(built)
    w.load()
    w.save_game()
    path = f"{SKIN_DIR}\\Virtual Families1.ldw.dat"
    damaged = bytearray(w.fs.read(path))
    damaged[60] ^= 0xFF
    w.fs.write(path, bytes(damaged))
    assert w.load() == 1 and w.status()["lastLoad"] == 5
    assert w.fs.read(f"{SKIN_DIR}\\Virtual Families1.ldw.unreadable-1.dat") == bytes(damaged)
    assert all(1 <= w.tone(s)[0] <= 10 for s in range(4))


def test_a_file_another_program_holds_is_left_as_it_is(built):
    from skin_scenarios import SKIN_DIR
    w = family(built)
    w.load()
    w.save_game()
    path = f"{SKIN_DIR}\\Virtual Families1.ldw.dat"
    before = w.fs.read(path)
    w.fs.locked.add(w.fs.key(path))
    assert w.load() == 1 and w.status()["lastLoad"] == 6
    assert w.tone(0) is None                         # nobody toned while it cannot be read
    backup = w.sidecar(21)
    w.save_game()
    assert w.status()["lastSave"] == 4 and w.fs.read(path) == before and w.sidecar(21) == backup
    assert not any(".unreadable-" in f for f in w.fs.files)


def test_another_familys_file_is_not_used(built):
    w = family(built)
    w.load()
    w.save_game()
    other = st.read(w.sidecar())
    w.reset_tree()
    w.start_family(5, "Zed", 0, 40)
    w.fs.files[w.fs.key(st_save(w, 1))] = b"another save"
    assert w.load() == 1 and w.status()["lastLoad"] == 4      # foreign and another family: random tones afresh
    assert other is not None
