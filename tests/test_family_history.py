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
    assert "LOGS_ROLL_DICE" not in cpp and "LOGS_BOARDING_SCHOOL" not in cpp and "LOGS_ADOPT_NEW_PERSON" not in cpp
    family = (ROOT / "native" / "vf1fun" / "family.inc").read_text(encoding="utf-8")
    for call in ("LogFamilyEvent(LOGS_DIVORCE, spouse);", "LogFamilyEvent(LOGS_SPAWN_CHILD, slot, a, b);",
                 "LogFamilyEvent(LOGS_ADOPT_CHILD, slot);", "if (mode == ADOPT_EVICT) LogFamilyEvent(LOGS_EVICT, -1);"):
        assert call in family
    # Divorce is logged before the spouse is removed; Evict before the tree is reset.
    assert family.index("LogFamilyEvent(LOGS_DIVORCE") < family.index("v[0x13574] = 0;")
    assert family.index("LogFamilyEvent(LOGS_EVICT") < family.index("ResetFamilyTree(FamilyTree);")
    assert "LogFamilyEvent" not in (ROOT / "native" / "vf1fun" / "villager_upgrades.inc").read_text(encoding="utf-8")
    dll = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    assert 'L"FamilyHistory"' in dll
    for k, v in {"DIVORCE": 1, "EVICT": 2, "SPAWN_CHILD": 3, "ADOPT_CHILD": 4}.items():
        assert f"LOGS_{k} = {v}" in cpp and f"EV_{k} = {v}" in dll


def test_the_source_has_no_hard_coded_game_address():
    text = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    found = [x for x in re.findall(r"0x[0-9A-Fa-f]{5,8}\b", text)
             if int(x, 16) > 0x400000 and x.lower() not in ("0x474c3156u", "0x400000u", "0x401000u")]
    assert not found, found


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


def test_install_writes_only_the_planned_sites(built):
    w = world(built)
    assert w.installed == 1
    st = w.status()
    assert st["requested"] == 1 and st["resolved"] == 1 and st["installed"] == 1 and st["writes"] == 8
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


@pytest.mark.parametrize("va", [0x48C2EE, 0x481D11, 0x4819E5, 0x424F93, 0x41B2C2, 0x419DE2, 0x41B0D1])
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
    assert w.history() == "Family: Hopkins (Save 1)\r\n"
    assert w.fs.under(w.root()) == sorted([w.fs.key(root + "\\Backups\\keep.txt"),
                                           w.fs.key(root + "\\Logs\\Family History\\Family History 1.txt")])
    assert w.status()["wipes"] == 1


def test_marriage_names_the_current_spouse(built):
    w = family(built)
    assert w.history_lines() == [STAMP + "Married: Ann (Female, 26) and Bob (Male, 27), generation 1"]


def test_remarriage_after_a_spouse_dies_with_no_children(built):
    w = family(built)
    w.die(1, cause=3)                                         # the REAL ReportDeath forgets parent 2: no children
    assert not w.e.read(record() + L.RECORD_PARENT2 + L.PEEP_VALID, 1)[0]
    w.set_villager(2, "Carl", 0, years=29)
    assert w.marry(0, 2) == 1
    assert w.history_lines()[1:] == [
        STAMP + "Died: Bob (Male, 27), spouse, generation 1: Work accident",
        STAMP + "Remarried: Ann (Female, 26) and Carl (Male, 29), generation 1; earlier spouse: Bob"]


def test_divorce_then_remarriage(built):
    w = family(built)
    w.event(1, 1)                                             # vf1fun's Divorce Spouse, before the spouse leaves
    w.e.write(w.villager(1) + L.VILLAGER_PRESENT, b"\0")      # what DivorceSpouse then does
    w.e.write(record() + L.RECORD_PARENT2, b"\0" * L.PEEP_RECORD_SIZE)
    w.e.w32(record() + L.RECORD_PARENT2 + L.PEEP_SLOT, -1)
    w.set_villager(2, "Dan", 0, years=30)
    w.marry(0, 2)
    assert w.history_lines()[1:] == [
        STAMP + "Divorced: Bob (Male, 27) left the family, divorced from Ann, generation 1 (Divorce Spouse)",
        STAMP + "Remarried: Ann (Female, 26) and Dan (Male, 30), generation 1; earlier spouse: Bob"]


def test_a_single_birth_names_both_parents(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.physiology(age_on=5)
    assert len(w.history_lines()) == 1, "not due yet: nothing delivered"
    w.physiology()
    assert w.history_lines()[-1] == STAMP + "Born to Ann and Bob, generation 1: Cid (Male)"
    w.physiology()
    assert len(w.history_lines()) == 2, "nothing more delivered: nothing more written"


@pytest.mark.parametrize("rolls,names,line", [
    ([0, 99], ["Cid", "Dee"], "Twins born to Ann and Bob, generation 1: Cid (Male) and Dee (Female)"),
    ([0, 0], ["Cid", "Dee", "Eve"],
     "Triplets born to Ann and Bob, generation 1: Cid (Male), Dee (Female) and Eve (Male)"),
])
def test_twins_and_triplets_are_one_line(built, rolls, names, line):
    w = family(built)
    w.conceive(rolls=rolls, names=names)
    w.physiology()                                           # the REAL delivery block
    assert w.history_lines()[-1] == STAMP + line


def test_a_father_the_tree_no_longer_holds_is_unknown(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.e.write(record() + L.RECORD_PARENT2, b"\0" * L.PEEP_RECORD_SIZE)   # Divorce Spouse cleared the father
    w.physiology()
    assert w.history_lines()[-1] == STAMP + "Born to Ann and an unknown father, generation 1: Cid (Male)"


def test_deaths_with_the_exes_cause_and_role(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.physiology()
    w.die(2, cause=0, how="body")                             # the child, at the body's removal
    w.die(1, cause=2)                                         # the spouse, at the death behaviour's end
    assert w.history_lines()[-2:] == [STAMP + "Died: Cid (Male, 2), child, generation 1: Disease",
                                      STAMP + "Died: Bob (Male, 27), spouse, generation 1: Old age"]


def test_the_patchers_children_who_join(built):
    w = family(built)
    w.set_villager(5, "Lil", 1, years=5, career=-1)
    w.event(4, 5)                                             # Adopt Outside Child
    w.set_villager(6, "Max", 0, years=7, career=-1)
    w.event(3, 6, 0, 1)                                       # Spawn Child
    assert w.history_lines()[-2:] == [
        STAMP + "Joined: Lil (Female, 5), adopted, generation 1 (Adopt Outside Child)",
        STAMP + "Joined: Max (Male, 7) as a child of Ann and Bob, generation 1 (Spawn Child)"]


def test_eviction_keeps_the_log_for_the_next_family(built):
    w = family(built)
    w.event(2)
    assert w.history_lines()[-1] == (STAMP + "Evicted: Ann, Bob left the house (Evict Family); the next family's "
                                     "history follows")
    w.reset_tree()
    w.start_family(3, "Nia", 1, 30)
    assert w.status()["wipes"] == 1, "an eviction is not a new slot"
    w.set_villager(4, "Ole", 0, years=31)
    w.marry(3, 4)
    assert w.history_lines()[-1] == STAMP + "Married: Nia (Female, 30) and Ole (Male, 31), generation 1"


def test_start_over_wipes_the_slot_but_keeps_backups(built):
    w = family(built)
    w.fs.write(w.root() + "\\Backups\\b.txt", b"b")
    w.start_over()
    assert w.restarts == [w.state]
    assert w.fs.under(w.root()) == [w.fs.key(w.root() + "\\Backups\\b.txt")]


def test_lines_roll_into_the_next_file_after_2000(built):
    w = family(built)
    path = w.root() + "\\Logs\\Family History\\Family History 1.txt"
    w.fs.write(path, ("Family: Hopkins (Save 1)\r\n" + (STAMP + "x\r\n") * 1999).encode())
    w.event(4, 0)
    w.event(4, 1)
    assert len(w.history_lines()) == 2000 and w.history_lines()[-1].endswith("(Adopt Outside Child)")
    assert w.history(n=2) == ("Family: Hopkins (Save 1)\r\n" + STAMP
                              + "Joined: Bob (Male, 27), adopted, generation 1 (Adopt Outside Child)\r\n")


def test_lines_go_to_the_current_slot(built):
    w = family(built)
    w.set_slot(3)
    w.event(4, 1)
    assert "Joined: Bob" in w.history(slot=3) and "Joined: Bob" not in w.history(slot=1)


# ------------------------------------------------------------------ the e-mail and pop-up events
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
    line = w.history_lines()[-1]
    assert line.startswith(STAMP + 'Pop-up: "The Little Visitor"; Wren (')
    assert line.endswith(", 3) joined the family as a child, generation 1")


def test_the_talent_scout_names_the_child_who_left(built):
    w = house(built)
    assert w.pop_up(58) == [58]
    assert w.history_lines()[-1] in (STAMP + 'Pop-up: "The Talent Scout"; Kid (Male, 10) left home',
                                     STAMP + 'Pop-up: "The Talent Scout"; Tot (Female, 3) left home')


def test_every_event_that_can_fire_is_logged_by_its_own_title(built):
    """Each e-mail and pop-up event the test house can fire, from the main scene's own branch: the line names the
    title the dialog shows (the executable's text for GetTitle), as an e-mail or a pop-up as the registry says.
    The ones whose CanFire is false in this house are checked by their title alone."""
    events = registry()
    assert len(events) == 71
    w = house(built)
    fired, never = set(), set()
    for n, (title, email) in sorted(events.items()):
        ev = w.event_object(n)
        assert w.is_email(ev) == email, n
        assert w.exe.string_record(w.title_id(ev))[1] == title, n           # the shown title is the registry's
        before = len(w.history_lines())
        try:
            shown = w.email(n) if email else w.pop_up(n)
        except Exception as exc:                                           # CanFire false in this house
            assert "cannot fire here" in str(exc), (n, exc)
            continue
        if not shown:
            # Picked, but the dialog is never shown: a choice event with no villager to act on (the constructor's
            # 0x41AAE1..0x41AAF1 leaves +0x4C at 0); stock Landscaping and Housekeeping are such. Nothing logged.
            assert w.has_choices(ev) and not w.e.r32(ev + 4) and len(w.history_lines()) == before, n
            never.add(n)
            continue
        assert shown == [n]
        assert len(w.history_lines()) == before + 1
        line = w.history_lines()[-1]
        assert line.startswith(STAMP + ("E-mail" if email else "Pop-up") + f': "{title}"'), (n, line)
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
    assert hits == ["kids", "fun"] and w.loads == [1] and w.history() == "Family: Hopkins (Save 1)\r\n"


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
    roles = lambda k: "parent" if k == 0 else "spouse" if k == 1 else "child"  # noqa: E731
    want = []
    for g, rec in enumerate(save.family_records, 1):
        if rec.parent1.used and rec.parent2.used:
            want.append(f"Married: {rec.parent1.name} ({sexes.get(rec.parent1.sex, 'Male')}) and {rec.parent2.name} "
                        f"({sexes.get(rec.parent2.sex, 'Male')}), generation {g}")
        want += [f"Child: {c.name} ({sexes.get(c.sex, 'Male')}), generation {g}" for c in rec.children if c.used]
        for k, p in enumerate([rec.parent1, rec.parent2, *rec.children]):
            if p.used and p.slot == -1:
                want.append(f"Died: {p.name} ({sexes.get(p.sex, 'Male')}), {roles(k)}, generation {g}")
    assert want and w.history_lines(2) == ["[backfilled, no date] " + x for x in want]
    assert w.history(2).startswith(f"Family: {save.family_name or '(no name)'} (Save 2)\r\n")
    assert w.status()["lastLoad"] == 2
    before = w.history(2)
    w.load(2)                                               # once: a second load adds nothing
    assert w.history(2) == before and w.status()["lastLoad"] == 1


def test_backfill_never_repeats_over_a_log_that_already_began(built):
    w = world(built)
    w.load_save_image(_real("generation6_left_home"), slot=1)
    w.fs.write(w.root() + "\\Logs\\Family History\\Family History 1.txt",
               b"Family: x (Save 1)\r\n" + STAMP.encode() + b"x\r\n")
    w.load(1)
    assert "backfilled" not in w.history() and w.status()["lastLoad"] == 1


def test_a_slot_with_no_family_gets_no_log(built):
    w = world(built)
    w.load(4)
    assert not w.fs.files
