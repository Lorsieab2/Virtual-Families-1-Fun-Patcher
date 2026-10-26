"""The Family History log (vf1logs.dll).

Layers (nothing here starts the game; the live checks are listed in docs/FAMILY_HISTORY.md):

* always: the manifest row, vf1fun's loader and event calls, the DLL holds no game address outside the
  generated header, writes only the Family History, and the folder and file names;
* with the vanilla executable (VF1_VANILLA_EXE or VF1_VANILLA_DIR): every pin and hooked call is proved with
  capstone + pefile (tools/vf1_logs_sites.py), the committed header is a fresh render, a damaged executable
  is refused, and every event's title is the executable's own text;
* with the vanilla executable AND the MSVC toolchain: the DLL builds with /W4 /WX, and that very DLL runs inside
  unicorn with the REAL game code, each hook reached from a live caller (tests/history_scenarios.py): every
  line format, every e-mail and pop-up event the test house can fire, the rolls, the backfill on copies of real
  saves, Start Over, chaining over a vf1kids-style entry hook and a vf1fun-style vtable hook, refusal on a
  patched pin, the setting off.
"""
from __future__ import annotations

import csv
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

from conftest import ROOT  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vf1_logs_sites as L  # noqa: E402

SRC = ROOT / "native" / "vf1logs"
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vf1_saves"
REGISTRY = ROOT / "docs" / "game-mechanics" / "events_registry.tsv"
ADD_OFFSPRING = 0x481AA0
STAMP = "[2026-10-24 12:34:56] "


def vanilla_exe() -> Path:
    value = os.environ.get("VF1_VANILLA_EXE")
    if not value and os.environ.get("VF1_VANILLA_DIR"):
        value = str(Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe")
    if not value or not Path(value).is_file():
        pytest.skip("set VF1_VANILLA_EXE (or VF1_VANILLA_DIR) to the vanilla Virtual Families game")
    return Path(value)


def need_toolchain():
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")


def registry() -> dict[int, tuple[str, bool]]:
    """docs/game-mechanics/events_registry.tsv: event number -> (title, e-mail)."""
    rows = csv.reader(REGISTRY.read_text(encoding="utf-8").splitlines(), delimiter="\t")
    return {int(r[0]): (r[4], r[3] == "email=1") for r in rows}


# ===================================================================== always
def test_manifest_row():
    m = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
    rows = [s for s in m["settings"] if s["id"] == "FamilyHistory"]
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "Family History Log" and row["category"] == "experimental" and row["default"] is False
    assert row["files"] == [{"source": "vf1logs.dll", "target": "Virtual Families 1 Patcher Files/vf1logs.dll"}]
    assert "Virtual Families 1 Patcher\\Save N\\Logs\\Family History" in row["description"]
    assert not any(s["id"] == "FamilyLogs" for s in m["settings"])


def test_vf1fun_loads_the_companion_after_vf1kids_and_tells_it_its_family_changes():
    cpp = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    kids = cpp.index('if (SettingOn(L"UpTo28Children", false))\n        LoadKidsCompanion();')
    logs = cpp.index('if (SettingOn(L"FamilyHistory", false))')
    assert kids < logs and 'L"vf1logs.dll"' in cpp and '"VF1Logs_Startup"' in cpp and '"VF1Logs_Event"' in cpp
    assert "LogFamilyEvent(LOGS_ROLL_DICE, -1, RollTheDicePrice);" in cpp
    family = (ROOT / "native" / "vf1fun" / "family.inc").read_text(encoding="utf-8")
    for call in ("LogFamilyEvent(LOGS_DIVORCE, spouse);", "LogFamilyEvent(LOGS_SPAWN_CHILD, slot, a, b);",
                 "LogFamilyEvent(LOGS_ADOPT_CHILD, slot);", "if (mode == ADOPT_EVICT) LogFamilyEvent(LOGS_EVICT, -1);"):
        assert call in family
    # Divorce is logged before the spouse is removed; Evict before the tree is reset.
    assert family.index("LogFamilyEvent(LOGS_DIVORCE") < family.index("v[0x13574] = 0;")
    assert family.index("LogFamilyEvent(LOGS_EVICT") < family.index("ResetFamilyTree(FamilyTree);")
    upgrades = (ROOT / "native" / "vf1fun" / "villager_upgrades.inc").read_text(encoding="utf-8")
    assert upgrades.index("LogFamilyEvent(LOGS_BOARDING_SCHOOL, i);") < upgrades.index("((SetLeftHomeFn)0x4857F0)(v);")
    dll = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    assert 'L"FamilyHistory"' in dll
    for k, v in {"DIVORCE": 1, "EVICT": 2, "SPAWN_CHILD": 3, "ADOPT_CHILD": 4, "ROLL_DICE": 5, "BOARDING_SCHOOL": 6}.items():
        assert f"LOGS_{k} = {v}" in cpp and f"EV_{k} = {v}" in dll


def test_the_source_has_no_hard_coded_game_address():
    text = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    found = [x for x in re.findall(r"0x[0-9A-Fa-f]{5,8}\b", text)
             if int(x, 16) > 0x400000 and x.lower() not in ("0x474c3156u", "0x400000u", "0x401000u")]
    assert not found, found


def test_the_random_events_are_never_island_events_in_the_log():
    dll = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    assert '"Email Event"' in dll and '"Popup Event"' in dll and '"Random Event"' in dll
    assert "island event" not in re.sub(r"//[^\n]*", "", dll).lower()


def test_only_the_family_history_is_written():
    dll = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    assert 'kSaves[] = "Virtual Families 1 Patcher\\\\Save "' in dll
    assert '"\\\\Logs\\\\Family History\\\\Family History "' in dll and '"Backups"' in dll
    for gone in ("Births and Conceptions", "Deaths Log", "Events Log", "Family Population", "Family Statistics",
                 "\\\\Data\\\\", "Parents - Save", "Unaccounted", "Log Checks", "WriteAtomic", "VF1LOGS_TEST"):
        assert gone not in dll, gone


# ===================================================================== with the vanilla exe
def test_every_site_is_proved():
    L.validate(vanilla_exe().read_bytes())


def test_the_pins_are_the_patchers_vanilla():
    sys.path.insert(0, str(ROOT / "patcher"))
    import vf1_patcher
    assert L.VANILLA_EXE_SHA256 == vf1_patcher.VANILLA_SHA256


def test_committed_header_is_a_fresh_render():
    assert (SRC / "vf1logs_sites.h").read_text() == L.render_header(L.validate(vanilla_exe().read_bytes()))


@pytest.mark.parametrize("pin", [p[0] for p in L.PINS])
def test_a_damaged_executable_is_refused(pin):
    data = bytearray(vanilla_exe().read_bytes())
    exe = L.Exe(bytes(data))
    name, va, n, note = L.PIN[pin]
    mask = L.mask_for(exe.read(va, n), va)
    k = next(i for i in range(n) if not mask[i])
    data[exe.pe.get_offset_from_rva(va + k - exe.base)] ^= 0x01
    with pytest.raises(L.SiteError):
        L.validate(bytes(data))


def test_the_words_are_the_executables():
    exe = L.Exe(vanilla_exe().read_bytes())
    words = [exe.string_record(L.STR_CAUSE_UNKNOWN + k)[1] for k in range(6)]
    assert words == ["Unknown causes", "Disease", "Starvation", "Old age", "Work accident", "Act of Nature"]
    assert exe.string_record(L.STR_NEW_GENERATION)[1] == "New Generation"
    assert exe.string_record(L.STR_COLLEGE_TITLE)[1] == "{name} is going to college!"


# ===================================================================== the DLL under emulation
def _env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    exe = vanilla_exe()
    need_toolchain()
    out = tmp_path_factory.mktemp("history_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_logs.bat")], capture_output=True, text=True,
                       env=dict(_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr          # /W4 /WX
    return {"exe": exe, "dll": out / "vf1logs.dll"}


def world(built, **kw):
    from history_scenarios import HistoryWorld
    return HistoryWorld(built["exe"], built["dll"], **kw)


def family(built, **kw):
    w = world(built, **kw)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    assert w.marry(0, 1) == 1
    w.mother, w.father = 0, 1
    return w


def record(g=1):
    return L.FAMILY_TREE + g * L.FAMILY_RECORD_SIZE - L.FAMILY_RECORD_BASE


def find(w, heading, slot=None, n=1):
    """The record whose heading (after the stamp) is `heading`, e.g. "Birth 2"."""
    hits = [r for r in w.records(slot, n) if r.split("\n", 1)[0].split("] ", 1)[1] == heading]
    assert len(hits) == 1, (heading, w.headings(slot, n))
    return hits[0]


def body(*lines):
    return "\n".join(lines)


ANN = body("    Age: 26", "    Sex: Female", "    Head: 3", "    Body: 4")
BOB = body("    Age: 27", "    Sex: Male", "    Head: 7", "    Body: 8")


def test_install_writes_only_the_planned_sites(built):
    w = world(built)
    assert w.installed == 1
    st = w.status()
    assert st["requested"] == 1 and st["resolved"] == 1 and st["installed"] == 1 and st["writes"] == 12
    expected = set()
    for _p, site, _t in L.CALL_HOOKS:
        expected.update(range(site + 1, site + 5))           # call displacements only
    for name, (pin, steal) in L.ENTRY_HOOKS.items():
        expected.update(range(L.PIN[pin][1], L.PIN[pin][1] + 5))
    changed = w.changed_code()
    assert changed <= expected and changed, sorted(hex(x) for x in changed - expected)
    assert w.e.r32(L.GS_VTABLE_LOAD) != L.FUNCTIONS["GS_LOAD"]


def test_setting_off_or_missing_is_stock(built):
    for setting in (0, None):
        w = world(built, setting=setting)
        assert w.installed == 0 and not w.changed_code()
        assert w.e.r32(L.GS_VTABLE_LOAD) == L.FUNCTIONS["GS_LOAD"]
        w.start_family(0, "Ann", 1, 26)
        w.event(1, 0)
        assert not w.fs.files


@pytest.mark.parametrize("va", [0x48C2EE, 0x481D11, 0x4819E5, 0x424F93, 0x41B2C2, 0x419DE2, 0x41B0D1, 0x445002, 0x4857F8])
def test_a_patched_pin_refuses_everything(built, va):
    def damage(w):
        w.e.write(va, bytes([w.e.read(va, 1)[0] ^ 0x01]))
        w.code_before = w._code()
    w = world(built, before_install=damage)
    assert w.installed == 0 and not w.changed_code()


def test_new_family_wipes_the_slot_and_starts_the_log(built):
    w = world(built)
    root = w.root()
    w.fs.write(root + "\\Logs\\Family History\\Family History 1.txt", b"old family\r\n")
    w.fs.write(root + "\\Logs\\Something Else\\x.txt", b"old")
    w.fs.write(root + "\\Backups\\keep.txt", b"keep me")
    w.fs.write(w.root(2) + "\\Logs\\Family History\\Family History 1.txt", b"another slot")
    w.start_family(0, "Ann", 1, 26)
    assert w.fs.read(root + "\\Backups\\keep.txt") == b"keep me", "Backups are kept"
    assert w.fs.read(w.root(2) + "\\Logs\\Family History\\Family History 1.txt") == b"another slot"
    assert w.history() == ("Family: Hopkins (Save 1)\r\n" + STAMP + "Generation 1\r\n  Name: Ann\r\n  Age: 26\r\n"
                           "  Sex: Female\r\n  Head: 3\r\n  Body: 4\r\n  How: Founder (adopted and started the family)\r\n"
                           "  Generation: 1\r\n\r\n")
    assert w.fs.under(w.root()) == sorted([w.fs.key(root + "\\Backups\\keep.txt"),
                                           w.fs.key(root + "\\Logs\\Family History\\Family History 1.txt")])
    assert w.status()["wipes"] == 1


def test_marriage_names_the_current_spouse(built):
    w = family(built)
    assert find(w, "Marriage 1") == body(STAMP + "Marriage 1", "  Family member: Ann", ANN, "  Married: Bob", BOB,
                                         "  Current spouse of Ann: Bob", "  Generation: 1")


def test_a_same_sex_marriage_is_logged_the_same_way(built):
    """Cheat Upgrades' same-sex wedding: vf1fun calls UpdateParents itself (its SameGenderWedding), so the hooked
    entry is reached as it reaches it; nothing in the record says husband or wife."""
    w = world(built)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Dora", 1, years=30, head=9, body=10)
    assert w.marry(0, 1) == 1
    assert find(w, "Marriage 1") == body(
        STAMP + "Marriage 1", "  Family member: Ann", ANN, "  Married: Dora", "    Age: 30", "    Sex: Female",
        "    Head: 9", "    Body: 10", "  Current spouse of Ann: Dora", "  Generation: 1")
    w.event(1, 1)                                             # Divorce Spouse
    assert "  Divorced: Dora\n    Age: 30\n    Sex: Female\n" in find(w, "Divorce 1")


def test_remarriage_after_a_spouse_dies_with_no_children(built):
    w = family(built)
    w.die(1, cause=3)                                         # the REAL ReportDeath forgets parent 2: no children
    assert not w.e.read(record() + L.RECORD_PARENT2 + L.PEEP_VALID, 1)[0]
    assert find(w, "Death 1") == body(
        STAMP + "Death 1", "  Name: Bob", "  Age at death: 27", "  Sex: Male", "  Cause of death: Work accident",
        "  Head: 7", "  Body: 8", "  Family role: Parent (married in)", "  Generation: 1",
        "  Current spouse of Ann: (none)")
    w.set_villager(2, "Carl", 0, years=29, head=5, body=6)
    assert w.marry(0, 2) == 1
    assert "  Remarried: yes\n  Earlier spouse: Bob (died)\n  Current spouse of Ann: Carl\n" in find(w, "Marriage 2")


def test_divorce_then_remarriage(built):
    w = family(built)
    w.event(1, 1)                                             # vf1fun's Divorce Spouse, before the spouse leaves
    w.e.write(w.villager(1) + L.VILLAGER_PRESENT, b"\0")      # what DivorceSpouse then does
    w.e.write(record() + L.RECORD_PARENT2, b"\0" * L.PEEP_RECORD_SIZE)
    w.e.w32(record() + L.RECORD_PARENT2 + L.PEEP_SLOT, -1)
    w.set_villager(2, "Dan", 0, years=30)
    w.marry(0, 2)
    assert find(w, "Divorce 1") == body(
        STAMP + "Divorce 1", "  Family member: Ann", "    Sex: Female", "    Head: 3", "    Body: 4", "  Divorced: Bob",
        BOB, "  How: Divorce Spouse", "  Current spouse of Ann: (none)", "  Generation: 1")
    assert "  Remarried: yes\n  Earlier spouse: Bob (divorced)\n  Current spouse of Ann: Dan\n" in find(w, "Marriage 2")


def test_conception_and_a_single_birth_name_both_parents(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    assert find(w, "Conception 1") == body(
        STAMP + "Conception 1", "  Mother: Ann", "    Age at conception: 26", "    Sex: Female", "    Head: 3",
        "    Body: 4", "  Father: Bob", "    Age at conception: 27", "    Sex: Male", "    Head: 7", "    Body: 8",
        "  Babies Nursing: 1", "  Generation: 1")
    w.physiology(age_on=5)
    assert "Birth" not in " ".join(w.headings()), "not due yet: nothing delivered"
    w.physiology()
    assert find(w, "Birth 1") == body(
        STAMP + "Birth 1", "  Child: Cid", "    Sex: Male", "    Head: 3", "    Body: 4", "  Mother: Ann", "    Head: 3",
        "    Body: 4", "  Father: Bob", "    Head: 7", "    Body: 8", "  Born as: Single birth", "  Generation: 1")
    w.physiology()
    assert sum(h.endswith("Birth 1") for h in w.headings()) == 1, "nothing more delivered: nothing more written"


@pytest.mark.parametrize("rolls,names,born_as", [([0, 99], ["Cid", "Dee"], "Twin"),
                                                 ([0, 0], ["Cid", "Dee", "Eve"], "Triplet")])
def test_twins_and_triplets(built, rolls, names, born_as):
    w = family(built)
    w.conceive(rolls=rolls, names=names)
    w.physiology()                                           # the REAL delivery block
    for k, name in enumerate(names, 1):
        r = find(w, f"Birth {k}")
        assert f"  Child: {name}\n" in r and f"  Born as: {born_as}\n" in r and "  Father: Bob\n" in r


def test_a_father_the_game_no_longer_holds_is_unknown(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.load()                                                 # a new session: the conception is not remembered
    w.e.write(record() + L.RECORD_PARENT2, b"\0" * L.PEEP_RECORD_SIZE)   # Divorce Spouse cleared the father
    w.physiology()
    assert "  Father: (unknown)\n" in find(w, "Birth 1")


def test_a_father_from_the_record_after_a_load(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.load()                                                 # the father is the record's, by his head and body
    w.physiology()
    assert "  Father: Bob\n    Head: 7\n    Body: 8\n" in find(w, "Birth 1")


def test_deaths_with_the_exes_cause_and_role(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.physiology()
    w.die(2, cause=0, how="body")                             # the child, at the body's removal
    w.die(1, cause=2)                                         # the spouse, at the death behaviour's end
    assert "  Name: Cid\n  Age at death: 2\n  Sex: Male\n  Cause of death: Disease\n" in find(w, "Death 1")
    assert "  Family role: Child\n" in find(w, "Death 1")
    assert "  Cause of death: Old age\n" in find(w, "Death 2") and "  Family role: Parent (married in)\n" in find(w, "Death 2")


def test_the_patchers_children_who_join(built):
    w = family(built)
    w.set_villager(5, "Lil", 1, years=5, career=-1)
    w.event(4, 5)                                             # Adopt Outside Child
    w.set_villager(6, "Max", 0, years=7, career=-1)
    w.event(3, 6, 0, 1)                                       # Spawn Child
    assert "  Name: Lil\n  Age at arrival: 5\n  Sex: Female\n" in find(w, "Arrived 1")
    assert "  How: Adopted (Adopt Outside Child)\n" in find(w, "Arrived 1")
    assert ("  How: Spawn Child\n  Parents:\n    Mother: Ann\n      Head: 3\n      Body: 4\n    Father: Bob\n"
            "      Head: 7\n      Body: 8\n") in find(w, "Arrived 2")


def test_leaving_home_at_19_uses_the_games_caption(built):
    w = family(built)
    w.set_villager(4, "Eve", 1, years=19, career=0)
    w.leave_home_at_19(4)
    assert w.e.read(w.villager(4) + L.VILLAGER_LEFT_HOME, 1) == b"\x01"
    assert find(w, "Left Home 1") == body(STAMP + "Left Home 1", "  Name: Eve", "  Age: 19", "  Sex: Female", "  Head: 3",
                                          "  Body: 4", "  What happened: Eve is going to college!", "  Generation: 1")
    w.leave_home_at_19(4)                                     # already gone: nothing more
    assert sum("Left Home" in h for h in w.headings()) == 1


def test_boarding_school(built):
    w = family(built)
    w.set_villager(4, "Eve", 1, years=9, career=-1)
    w.event(6, 4)                                             # vf1fun: the departure that follows is Boarding School
    w.e.call(L.FUNCTIONS["V_SET_LEFT_HOME"], (), ecx=w.villager(4))   # vf1fun's own SetLeftHome call
    assert "  What happened: Sent to Boarding School\n" in find(w, "Left Home 1")


def test_next_generation_and_adopt_new_person(built):
    w = family(built)
    w.set_villager(2, "Kid", 0, years=20, career=5)
    w.e.call(ADD_OFFSPRING, (w.villager(2),), ecx=L.FAMILY_TREE)
    w.next_generation(2, 0)                                   # the adoption scene's own accept
    assert w.generations() == 2
    assert find(w, "New Generation 1") == body(
        STAMP + "New Generation 1", "  Name: Kid", "  Age: 20", "  Sex: Male", "  Head: 3", "  Body: 4",
        "  How: Heir (inherited the house)", "  Generation: 2")
    w.set_villager(9, "Zed", 0, years=25)
    assert w.adopt_new_person(9) == 1
    assert "  Name: Zed\n" in find(w, "Generation 2") and "  How: Adopt New Person\n" in find(w, "Generation 2")


def test_the_mails_that_are_not_random_events(built):
    w = family(built)
    w.dating_mail()
    w.letter_mail()
    assert w.scene_switches == [(8, -1)] and w.letters == [w.scene]
    assert find(w, "Random Event 1") == body(STAMP + "Random Event 1",
                                             "  Email Event: A marriage proposal (the dating e-mail)", "  Generation: 1")
    assert "  Email Event: A letter from a child who left home\n" in find(w, "Random Event 2")


def test_roll_the_dice_names_the_event_it_fired(built):
    w = house(built)
    w.pop_up(41)
    w.event(5, -1, 500)
    assert find(w, "Roll the Dice 1") == body(STAMP + "Roll the Dice 1", "  Cost: $500", "  Popup Event: Adoption Day",
                                              "  Generation: 1")


def test_eviction_keeps_the_log_for_the_next_family(built):
    w = family(built)
    w.event(2)
    assert find(w, "Evict Family 1") == body(STAMP + "Evict Family 1", "  Family members: Ann, Bob", "  Generation: 1")
    w.reset_tree()
    w.start_family(3, "Nia", 1, 30)
    assert w.status()["wipes"] == 1, "an eviction is not a new slot"
    assert "  How: Founder (after the eviction)\n" in find(w, "Generation 2")
    w.set_villager(4, "Ole", 0, years=31)
    w.marry(3, 4)
    assert "Remarried" not in find(w, "Marriage 2")


def test_start_over_wipes_the_slot_but_keeps_backups_and_says_so(built):
    w = family(built)
    w.fs.write(w.root() + "\\Backups\\b.txt", b"b")
    w.start_over()
    assert w.restarts == [w.state]
    assert w.fs.under(w.root()) == [w.fs.key(w.root() + "\\Backups\\b.txt")]
    w.reset_tree()
    w.start_family(0, "Nia", 1, 30)
    assert w.headings() == [STAMP + "Start Over 1", STAMP + "Generation 1"]


def test_records_roll_into_the_next_file_after_2000(built):
    w = family(built)
    path = w.root() + "\\Logs\\Family History\\Family History 1.txt"
    w.fs.write(path, ("Family: Hopkins (Save 1)\r\n" + (STAMP + "Note 1\r\n  x\r\n\r\n") * 1999).encode())
    w.event(4, 0)
    w.event(4, 1)
    assert len(w.records()) == 2000 and w.headings()[-1] == STAMP + "Arrived 1"
    assert w.headings(n=2) == [STAMP + "Arrived 2"] and w.history(n=2).startswith("Family: Hopkins (Save 1)\r\n")


def test_records_go_to_the_current_slot(built):
    w = family(built)
    w.set_slot(3)
    w.event(4, 1)
    assert w.headings(slot=3) == [STAMP + "Arrived 1"]


# ------------------------------------------------------------------ the Random Events
def house(built):
    w = family(built)
    for slot, name, sex, years in ((2, "Kid", 0, 10), (3, "Tot", 1, 3)):
        w.set_villager(slot, name, sex, years=years, career=-1)
        w.e.call(ADD_OFFSPRING, (w.villager(slot),), ecx=L.FAMILY_TREE)
    return w


def test_the_little_visitor_names_the_child_who_joined(built):
    w = house(built)
    w.visitor_names.append("Wren")
    assert w.pop_up(49) == [49]
    assert find(w, "Random Event 1") == body(STAMP + "Random Event 1", "  Popup Event: The Little Visitor", "  Choice: A",
                                             "  Generation: 1")
    arrived = find(w, "Arrived 1")
    assert "  Name: Wren\n  Age at arrival: 3\n" in arrived
    assert "  How: Adopted (Popup Event: The Little Visitor)\n  Family role: Child\n" in arrived


def test_the_talent_scout_names_the_child_who_left(built):
    w = house(built)
    assert w.pop_up(58) == [58]
    left = find(w, "Left Home 1")
    assert "  What happened: Left home with The Talent Scout (Popup Event)\n" in left
    assert "  Name: Kid\n" in left or "  Name: Tot\n" in left


def test_every_event_that_can_fire_is_logged_by_its_own_title(built):
    """Each Random Event the test house can fire, from the main scene's own branch: the record names the title the
    dialog shows (the executable's text for GetTitle), as an Email Event or a Popup Event as the registry says.
    The ones whose CanFire is false in this house are checked by their title alone."""
    events = registry()
    assert len(events) == 71
    w = house(built)
    fired, never = set(), set()
    for n, (title, email) in sorted(events.items()):
        ev = w.event_object(n)
        assert w.is_email(ev) == email, n
        assert w.exe.string_record(w.title_id(ev))[1] == title, n           # the shown title is the registry's
        before = len(w.records())
        try:
            shown = w.email(n) if email else w.pop_up(n)
        except Exception as exc:                                           # CanFire false in this house
            assert "cannot fire here" in str(exc), (n, exc)
            continue
        if not shown:
            # Picked, but the dialog is never shown: a choice event with no villager to act on (the constructor's
            # 0x41AAE1..0x41AAF1 leaves +0x4C at 0); stock Landscaping and Housekeeping are such. Nothing logged.
            assert w.has_choices(ev) and not w.e.r32(ev + 4) and len(w.records()) == before, n
            never.add(n)
            continue
        assert shown == [n]
        event = next(r for r in w.records()[before:] if "] Random Event " in r.split("\n", 1)[0])
        assert event.split("\n")[1] == f"  {'Email Event' if email else 'Popup Event'}: {title}", (n, event)
        fired.add(n)
    assert never == {60, 61} and len(fired) >= 59, sorted(set(events) - fired)


# ------------------------------------------------------------------ chaining with the other companions
def test_chains_over_another_companions_entry_jmp_and_vtable(built):
    """vf1kids.dll hooks StartNextGeneration at its entry with a 5-byte jmp; vf1fun.dll replaces the Load vtable
    slot. Both are kept and called."""
    hits = []

    def companions(w):
        e = w.e
        va, steal = L.FUNCTIONS["FT_START_NEXT_GEN"], 6
        stub = e.fake_code(e.read(va, steal) + b"\xE9" + b"\0" * 4)
        e.w32(stub + steal + 1, (va + steal) - (stub + steal + 5))
        head = e.fake_code(b"\x90\xE9" + b"\0" * 4)
        e.w32(head + 2, stub - (head + 6))
        e.uc.hook_add(1 << 2, lambda uc, a, s, u: hits.append("kids"), begin=head, end=head)
        e.write(va, b"\xE9" + struct.pack("<i", head - (va + 5)))
        h = e.fake_code(b"\x90\xE9" + b"\0" * 4)
        e.w32(h + 2, L.FUNCTIONS["GS_LOAD"] - (h + 6))
        e.uc.hook_add(1 << 2, lambda uc, a, s, u: hits.append("fun"), begin=h, end=h)
        e.w32(L.GS_VTABLE_LOAD, h)
        w.code_before = w._code()
    w = world(built, before_install=companions)
    assert w.installed == 1
    w.start_family(0, "Ann", 1, 26)
    w.load()
    assert hits == ["kids", "fun"] and w.loads == [1] and w.headings() == [STAMP + "Generation 1"]


# ------------------------------------------------------------------ backfill on copies of real saves
def _real(name):
    import make_vf1_save_fixtures as fx
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_backfill_of_a_real_save_matches_its_family_tree(built, name):
    w = world(built)
    save = w.load_save_image(_real(name), slot=2)
    assert w.load(2) == 1
    sexes = {0: "Male", 1: "Female"}

    def peep(label, p):
        return [f"  {label}: {p.name}", f"    Sex: {sexes.get(p.sex, 'Male')}", f"    Head: {p.head}",
                f"    Body: {p.body}"] + (["    Died: yes"] if p.slot == -1 else [])
    want = []
    for g, rec in enumerate(save.family_records, 1):
        lines = [f"[backfilled, no date] Family Tree {g}"]
        if rec.parent1.used:
            lines += peep("Parent", rec.parent1)
        if rec.parent2.used:
            lines += peep("Parent (married in)", rec.parent2)
        for c in rec.children:
            if c.used:
                lines += peep("Child", c)
        if g == len(save.family_records) and rec.parent1.used and rec.parent2.used and -1 not in (rec.parent1.slot, rec.parent2.slot):
            lines.append(f"  Current spouse of {rec.parent1.name}: {rec.parent2.name}")
        lines += [f"  Generation: {g}", "  Note: Recorded afterwards (from the save's Family Tree: no dates, ages, "
                  "causes, twins or earlier spouses)"]
        want.append("\n".join(lines))
    assert want and w.records(2) == want
    assert w.history(2).startswith(f"Family: {save.family_name or '(no name)'} (Save 2)\r\n")
    assert w.status()["lastLoad"] == 2
    before = w.history(2)
    w.load(2)                                               # once: a second load adds nothing
    assert w.history(2) == before and w.status()["lastLoad"] == 1


def test_backfill_never_repeats_over_a_log_that_already_began(built):
    w = world(built)
    w.load_save_image(_real("generation6_left_home"), slot=1)
    w.fs.write(w.root() + "\\Logs\\Family History\\Family History 1.txt",
               b"Family: x (Save 1)\r\n" + STAMP.encode() + b"Note 1\r\n  x\r\n\r\n")
    w.load(1)
    assert "backfilled" not in w.history() and w.status()["lastLoad"] == 1


def test_a_slot_with_no_family_gets_no_log(built):
    w = world(built)
    w.load(4)
    assert not w.fs.files
