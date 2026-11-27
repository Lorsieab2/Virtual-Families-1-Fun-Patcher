"""Game Mechanics' Family members group (patcher/vf1_game_mechanics_family.py; the owner approved the port of the
Virtual Villagers patcher's per-villager group, 2026-11-26).

Every case starts from a committed real save (tests/fixtures/vf1_saves) rebuilt into a temporary save folder.  The
values each line shows are checked against the save's own bytes, read here at their file offsets without the
patcher's reader; the cases that need a sickness, food groups or a long name write those fields into the copy.  The
game's own words (the likes list, "Wants kids?", the father's stand-in name) are checked in the stock exe when it is
present.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest

import make_vf1_save_fixtures as fx
import vf1_game_mechanics as gm
import vf1_game_mechanics_family as fam
import vf1_names
import vf1_save
from test_game_mechanics import CLOCKS, DURATION, exe_bytes
from test_tools_tab import app, documents, save, snapshot, tk_root, walk  # noqa: F401 -- fixtures

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "vf1_saves"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.json"))


def fixture(name: str) -> bytes:
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


def put(folder: Path, data: bytes, slot: int = 1) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Virtual Families{slot}.ldw"
    path.write_bytes(data)
    return path


def header_size(data: bytes) -> int:
    return vf1_save.parse_header(data).size


def record_at(data: bytes, slot: int) -> int:
    """The file offset of villager record `slot` (gs+0xE790; the payload starts at theGameState+8)."""
    return header_size(data) + vf1_save.GS_VILLAGERS - vf1_save.GS_BASE + slot * vf1_save.VILLAGER_RECORD


def i32(data: bytes, at: int) -> int:
    return struct.unpack_from("<i", data, at)[0]


def cstr(data: bytes, at: int, n: int) -> str:
    return data[at:at + n].split(b"\0")[0].decode("utf-8", "replace")


def lines_of(facts, name: str) -> list[str]:
    """A person's own line and the lines under it."""
    out, inside = [], False
    for f in facts:
        if not f.sub:
            inside = f.text.startswith(f"{name}: ")
            if inside:
                out.append(f.text)
        elif inside:
            out.append(f.text)
    return out


def present_slots(data: bytes) -> list[int]:
    return [k for k in range(vf1_save.VILLAGER_SLOTS) if data[record_at(data, k)]]


@pytest.mark.parametrize("name", NAMES)
def test_every_member_is_listed_with_the_saves_own_values(tmp_path, name):
    data = fixture(name)
    facts = fam.facts(put(tmp_path / "save", data))
    assert facts and all(f.group == gm.FAMILY for f in facts)
    slots = present_slots(data)
    assert slots
    for slot in slots:
        r = record_at(data, slot)
        who = cstr(data, r + 0x18, 0x1C)
        mine = lines_of(facts, who)
        assert mine, who
        units, sex, health = i32(data, r + 8), i32(data, r + 0xC), i32(data, r + 0xB4)
        head = mine[0]
        assert f"{who}: {('Male', 'Female')[sex]}, " in head
        assert f"{units // 20:,} year" in head and f"({units:,} age units; {20 - units % 20} more" in head
        if health <= 0:
            assert f"health {health}" in head
            continue
        assert f"health {health} of 100" in head
        body = "\n".join(mine[1:])
        hunger = i32(data, r + 0xE8)
        assert (f"Happiness {i32(data, r + 0xE0)}, Health {health}, Fed {100 - hunger} (100 less the hunger, "
                f"{hunger}), Energy {i32(data, r + 0xDC)}") in body
        assert (f"happiness trend {i32(data, r + 0xE4):+,} " in body and f"dirtiness {i32(data, r + 0xEC)}," in body
                and f"bathroom need {i32(data, r + 0xF0)} " in body)
        wants, fertility = i32(data, r + 0xF8), i32(data, r + 0xF4)
        assert f"Wants kids?: {wants} (\"{fam.WANTS_KIDS[wants // 10]}\"" in body
        assert f"fertility {fertility} of 100" in body
        assert ("Left home:" in body) == bool(data[r + 1])
        career, level, progress, salary = (i32(data, r + o) for o in (0x140, 0x144, 0x148, 0x14C))
        if career == -1:
            assert "Career: none; no salary." in body
        else:
            job = gm.CAREER_LIST[career]
            assert f"Career: {job.name} (career room {job.room}, " in body
            assert f"{gm.LEVELS[level]} (level {level + 1} of 8); progress {progress:,} of 3,000" in body
            assert f"salary ${salary:,}: ${salary / 4:,.2f} per hour of game time" in body
            assert ("(top level, no further promotion)" in body) == (level == 7)
        likes = [fam.LIKE_WORDS[i] for i in struct.unpack_from("<3i", data, r + 0x150) if i != -1]
        dislikes = [fam.LIKE_WORDS[i] for i in struct.unpack_from("<3i", data, r + 0x15C) if i != -1]
        assert f"Likes: {', '.join(likes) or 'none'}. Dislikes: {', '.join(dislikes) or 'none'}." in body
        symptoms = data[r + 0x104:r + 0x10B]
        assert ("Sick with" in body) == any(symptoms) and (", sick" in head) == any(symptoms)
        conceived = i32(data, r + 0xCC)
        if conceived:
            babies = {1: "1 baby", 2: "twins", 3: "triplets"}[i32(data, r + 0xD0)]
            assert (f"Pregnant with {babies}, conceived at the mother's age unit {conceived:,}: born at her age unit "
                    f"{conceived + 21:,}") in body


def test_every_family_tree_likes_are_the_same_words():
    # The Family Tree keeps the words UpdatePeepRecord made from the same places: the list LIKE_WORDS is read in order.
    checked = 0
    for name in NAMES:
        s = vf1_save.parse_save(fixture(name))
        rec = s.current_family
        for peep in [rec.parent1, rec.parent2] + rec.children:
            v = s.villager_for(peep)
            if v is None or not v.present:
                continue
            assert fam.like_text(v.likes).replace("none", "") == peep.likes_text.strip(), peep.name
            assert fam.like_text(v.dislikes).replace("none", "") == peep.dislikes_text.strip(), peep.name
            checked += 1
    assert checked >= 15


def test_the_games_own_words_are_the_exes():
    import vf1_translation_strings as strings
    exe = exe_bytes()
    table = strings.read_table(exe)
    for sid in (0x45B, 0x45C):
        assert tuple(w.strip() for w in table[sid][1].split(",")) == fam.LIKE_WORDS
    assert [table[sid][1] for sid in range(0x3D1, 0x3D6)] == list(dict.fromkeys(fam.WANTS_KIDS))
    # 0x48FCC0: the table of ten string ids (two each, Definitely three times) then value / 10
    routine = bytes.fromhex("83ec2c8b4950b8d103000089042489442404b8d2030000894424088944240cb8d30300008944241089442414"
                            "b8d4030000894424188944241cb8d5030000894424208944242489442428b867666666f7e9c1fa02")
    assert exe.count(routine) == 1
    # 0x48EB9F: the try's success passes the father's looks (+0x2A60 head, +0x2A64 body) and the literal "Joey"
    call = bytes.fromhex("8b83642a00008b8b602a00006a00505168" + "60704b00" + "6a018bcfe8")
    assert exe.count(call) == 1
    off = exe.find(b"\0Joey\0") + 1
    assert off > 0 and fam.FATHER_STAND_IN == "Joey"


def test_sickness_infection_food_groups_and_a_whole_name(tmp_path):
    data = bytearray(fixture("pregnant_unborn_baby"))
    s = vf1_save.parse_save(bytes(data))
    rosella = record_at(bytes(data), 0)
    kikino = record_at(bytes(data), 1)
    saved = s.time.saved_at
    data[rosella + 0x104 + 2] = 1                                   # an upset stomach
    struct.pack_into("<I", data, rosella + 0x10C + 8, saved + 7200)
    data[rosella + 0x128] = 1                                       # a mild infection
    data[kikino + 0x129] = 1                                        # a serious infection, no symptom
    for k in range(4):                                              # Kikino: Grains and Meats running, the rest over
        data[kikino + 0x12C + k] = int(k in (0, 2))
    struct.pack_into("<4I", data, kikino + 0x130, saved + 3600, saved - 10, saved + 50, saved - 10)
    short = "Kikino Whole" + vf1_names.MARK                       # a long name's short form, in the save ...
    tree = header_size(bytes(data)) + vf1_save.GS_FAMILY_TREE - vf1_save.GS_BASE
    for at, room in ((kikino + 0x18, 0x1C), (tree + 0xDC, 0x1A)):    # ... his own record and the Family Tree's
        data[at:at + room] = short.encode().ljust(room, b"\0")
    folder = tmp_path / "save"
    path = put(folder, bytes(data))
    vf1_names.write(vf1_names.names_path(folder, 1), [vf1_names.Entry(short, 18, "Kikino Wholename-Smith")])
    facts = fam.facts(path)
    rose = "\n".join(lines_of(facts, "Rosella"))
    assert rose.startswith("Rosella: Female, 27 years") and ", sick." in rose.splitlines()[0]
    assert ("Sick with an upset stomach (its time ends " + fam.when(s, saved + 7200) + ", real time)") in rose
    assert "; also a mild infection (Penicillin cures it). See Sickness" in rose
    kik = lines_of(facts, "Kikino Wholename-Smith")
    assert kik and ", sick" not in kik[0]
    body = "\n".join(kik)
    assert "Not sick by the game's test (no symptom), but carries a serious infection (Vancomycin cures it)" in body
    assert f"Whole name: Kikino Wholename-Smith; the save keeps the short form \"{short}\"" in body
    assert (f"Grains until {fam.when(s, saved + 3600)}, Meats until {fam.when(s, saved + 50)}. "
            "The game's count is 2.") in body
    assert "Spouse: Kikino Wholename-Smith" in rose


def test_pregnancy_father_and_the_unborn_child(tmp_path):
    facts = fam.facts(put(tmp_path / "save", fixture("pregnant_unborn_baby")))
    rose = "\n".join(lines_of(facts, "Rosella"))
    assert ("Pregnant with 1 baby, conceived at the mother's age unit 541: born at her age unit 562, 20 age units "
            "to go (3 hours 20 minutes of game time: 3 hours 20 minutes real time on Normal") in rose
    assert "the father's looks are Kikino's (the save keeps the father's name as \"Joey\"" in rose
    assert "Children in the save's Family Tree: Bohi (on the way, not born yet)." in rose
    assert facts[-1].text.startswith("Babies on the way: 1,")


def test_spouse_heir_parents_and_children(tmp_path):
    facts = fam.facts(put(tmp_path / "save", fixture("generation6_left_home")))
    vesta = "\n".join(lines_of(facts, "Vesta"))
    assert "the head of the family, generation 6 (the heir)" in vesta and "Spouse: Bengor" in vesta
    s = vf1_save.parse_save(fixture("generation6_left_home"))
    prev = s.family_records[4]
    assert f"Parents: {prev.parent1.name} and {prev.parent2.name} (the save's Family Tree)." in vesta
    assert "\"Joey\" is the name the game writes for the father when a try for a baby works" in vesta
    kids = ", ".join(f"{c.name} (" for c in s.current_family.children)
    assert all(part in vesta for part in kids.split(", "))
    dico = "\n".join(lines_of(facts, "Dico"))
    assert "Left home: they stay in the save but never age or update again" in dico
    assert "Parents: Vesta and Bengor (the save's Family Tree)." in dico
    assert "married into the family, generation 6" in "\n".join(lines_of(facts, "Bengor"))


def _tree_peep_at(data: bytes, generation: int, name: str) -> int:
    """The file offset of `name`'s entry in the save's Family Tree record of `generation`."""
    rec = header_size(data) + vf1_save.GS_FAMILY_TREE - vf1_save.GS_BASE + (generation - 1) * 0x6C8
    for at in [rec + 4, rec + 0xDC] + [rec + 0x1B8 + k * 0xD8 for k in range(6)]:
        if data[at:at + len(name) + 1] == name.encode() + b"\0":
            return at
    raise KeyError(name)


def test_the_end_to_end_checks_wording(tmp_path):
    """The end-to-end check (2026-11-27): the dead have no next birthday, a widowed spouse names the one who died,
    a Master's progress is the top level, a spouse who married in has no founder guess list, pay has two decimals,
    a food-group count with no group says why, and the cause of a death says how sure it is."""
    data = bytearray(fixture("generation6_left_home"))
    s = vf1_save.parse_save(bytes(data))
    by = {v.name: v for v in s.household()}
    r = record_at(bytes(data), by["Vesta"].slot)
    struct.pack_into("<ii", data, r + 0xB4, 0, 2)                       # Vesta dies of old age, her body at home
    struct.pack_into("<i", data, _tree_peep_at(bytes(data), 6, "Vesta") + 0x28, -1)    # ReportDeath
    t = record_at(bytes(data), by["Tilde"].slot)
    struct.pack_into("<ii", data, t + 0xB4, 0, 0)                       # Tilde dies of cause 0
    facts = fam.facts(put(tmp_path / "save", bytes(data)))
    vesta = lines_of(facts, "Vesta")
    assert vesta[0] == ("Vesta: Female, died at 41 years (827 age units); health 0. The body is still in the house "
                        "(it is removed 240 age units after their last update; see Old age and death).")
    cause = next(f for f in facts if f.text.startswith("The cause the save keeps: 2"))
    assert cause.text == "The cause the save keeps: 2, Old age (the old-age roll's own cause)." and cause.label == fam.C
    tilde = next(f for f in facts if f.text.startswith("The cause the save keeps: 0"))
    assert tilde.label == fam.U and "probably Disease" in tilde.text
    assert not any("more to the next birthday" in line for f in facts for line in [f.text]
                   if f.text.startswith(("Vesta:", "Tilde:")))
    bengor = "\n".join(lines_of(facts, "Bengor"))
    assert "Spouse: Vesta (died; the save's Family Tree, generation 6)." in bengor
    assert "Parents: none: married into the family; the save keeps no parents for them." in bengor
    assert "a founder, an adopted child" not in bengor
    assert "Master (level 8 of 8); progress 3,000 of 3,000 (top level, no further promotion)" in bengor
    assert "salary $95: $23.75 per hour of game time" in bengor
    # A grown-up with no career and no food group now, whose count is still 1 (the fifth slot: no career, and the
    # low byte of the Grains end still set): the count says why.
    p = record_at(bytes(data), by["Pennella"].slot)
    data[p + 0x12C:p + 0x130] = b"\0\0\0\0"
    struct.pack_into("<I", data, p + 0x130, 0x101)
    data[p + 0x130 + 16:p + 0x130 + 20] = struct.pack("<i", -1)
    facts = fam.facts(put(tmp_path / "save2", bytes(data)))
    line = next(f.text for f in facts if f.text.startswith("Food groups") and f in facts[
        facts.index(next(x for x in facts if x.text.startswith("Pennella:"))):])
    assert line.endswith("none. The game's count is 1 because every family member without a career gets one extra "
                         "once they have had Grains (see Needs and upkeep), even with no group now.")
    assert "The game counts" not in "\n".join(f.text for f in facts)


def test_every_time_names_its_clock_and_nothing_names_a_sex_rule(tmp_path):
    for name in NAMES:
        for f in fam.facts(put(tmp_path / name, fixture(name))):
            if DURATION.search(re.sub("“[^”]*”", "", f.text)):
                assert any(clock in f.text for clock in CLOCKS), f.text
            assert "Matriarch" not in f.text and "Patriarch" not in f.text


def test_an_unreadable_save_says_so(tmp_path):
    path = put(tmp_path / "save", b"ldwg not a save")
    facts = fam.facts(path)
    assert len(facts) == 1 and facts[0].text.startswith("This save could not be read:")
    assert fam.find_families([tmp_path / "save"]) == []


def test_the_family_module_only_reads():
    source = (ROOT / "patcher" / "vf1_game_mechanics_family.py").read_text(encoding="utf-8")
    for call in (r"\bopen\(", r"write_bytes", r"write_text", r"\.unlink\(", r"shutil", r"subprocess", r"os\.remove",
                 r"vf1_save_backup"):
        assert re.search(call, source) is None, call


def test_printing_a_familys_page(tmp_path, capsys):
    path = put(tmp_path / "save", fixture("generation6_left_home"))
    assert gm.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "\n\nFamily members\n" in out and "Vesta: Female, 41 years" in out


def test_the_window_lists_each_family_and_switches(app, save):
    put(save, fixture("generation6_left_home"), 1)
    put(save, fixture("pregnant_unborn_baby"), 2)
    before = snapshot(save)
    window = app.game_mechanics()
    app.root.update_idletasks()
    box = window.family_box
    assert list(box.cget("values")) == [f"Save 1: Lorsieab2 ({save.name})", f"Save 2: Testificate!!! ({save.name})"]
    shown = window.text.get("1.0", "end")
    assert "Vesta: Female, 41 years" in shown and "Rosella:" not in shown
    assert window.text.index(f"group:{gm.FAMILY}")
    box.current(1)
    box.event_generate("<<ComboboxSelected>>")
    window.update()
    shown = window.text.get("1.0", "end")
    assert "Rosella: Female, 27 years" in shown and "Vesta:" not in shown
    assert str(window.text.cget("state")) == "disabled"
    for group in gm.GROUPS:
        assert f"\n{group}\n" in shown
    assert snapshot(save) == before
    window.destroy()


def test_the_window_with_no_family_says_so(app):
    window = app.game_mechanics()
    app.root.update_idletasks()
    assert gm.NO_FAMILY in window.text.get("1.0", "end")
    assert window.family_box.get() == gm.NO_FAMILY
    window.destroy()
