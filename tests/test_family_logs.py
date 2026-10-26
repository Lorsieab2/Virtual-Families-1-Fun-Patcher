"""Family Logs (vf1logs.dll).

Layers (nothing here starts the game; the live checks are listed in docs/FAMILY_LOGS.md):

* always: the manifest row, vf1fun's loader and event calls, the DLL holds no game address outside the
  generated header, the folder and file names;
* with the vanilla executable (VF1_VANILLA_EXE or VF1_VANILLA_DIR): every pin and hooked call is proved with
  capstone + pefile (tools/vf1_logs_sites.py), the committed header is a fresh render, a damaged executable
  is refused;
* with the vanilla executable AND the MSVC toolchain: the DLL builds with /W4 /WX, and the REAL compiled DLL
  runs inside unicorn with the REAL game code (tests/logs_scenarios.py): every hook, the log formats, the
  rolls, the backfill on copies of real saves, Start Over, chaining over vf1kids-style entry hooks and
  vf1fun-style call and vtable hooks, refusal on a patched pin, the setting off.
"""
from __future__ import annotations

import json
import os
import re
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


def _env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


# ===================================================================== always
def test_manifest_row():
    m = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
    rows = [s for s in m["settings"] if s["id"] == "FamilyLogs"]
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "Family Logs" and row["category"] == "experimental" and row["default"] is False
    assert row["files"] == [{"source": "vf1logs.dll", "target": "Virtual Families 1 Patcher Files/vf1logs.dll"}]
    assert "Virtual Families 1 Patcher\\Save N" in row["description"]


def test_vf1fun_loads_the_companion_after_vf1kids_and_tells_it_its_events():
    cpp = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8").replace("\r\n", "\n")
    kids = cpp.index('if (SettingOn(L"UpTo28Children", false))\n        LoadKidsCompanion();')
    logs = cpp.index('if (SettingOn(L"FamilyLogs", false))')
    assert kids < logs and 'L"vf1logs.dll"' in cpp and '"VF1Logs_Startup"' in cpp and '"VF1Logs_Event"' in cpp
    assert "LogFamilyEvent(LOGS_ROLL_DICE, -1, RollTheDicePrice);" in cpp
    family = (ROOT / "native" / "vf1fun" / "family.inc").read_text(encoding="utf-8")
    for call in ("LogFamilyEvent(LOGS_DIVORCE, spouse, 0);", "LogFamilyEvent(LOGS_SPAWN_CHILD, slot, 0);",
                 "LogFamilyEvent(LOGS_ADOPT_CHILD, slot, 0);",
                 "LogFamilyEvent(mode == ADOPT_EVICT ? LOGS_EVICT : LOGS_ADOPT_NEW_PERSON, -1, 0);"):
        assert call in family
    # Divorce is logged before the spouse is removed; Evict before the tree is reset.
    assert family.index("LogFamilyEvent(LOGS_DIVORCE") < family.index("v[0x13574] = 0;")
    assert family.index("LogFamilyEvent(mode == ADOPT_EVICT") < family.index("ResetFamilyTree(FamilyTree);")
    upgrades = (ROOT / "native" / "vf1fun" / "villager_upgrades.inc").read_text(encoding="utf-8")
    assert upgrades.index("LogFamilyEvent(LOGS_BOARDING_SCHOOL, i, 0);") < upgrades.index("((SetLeftHomeFn)0x4857F0)(v);")
    dll = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    assert 'L"FamilyLogs"' in dll
    for k, v in {"ROLL_DICE": 1, "DIVORCE": 2, "EVICT": 3, "ADOPT_NEW_PERSON": 4, "SPAWN_CHILD": 5,
                 "ADOPT_CHILD": 6, "BOARDING_SCHOOL": 7}.items():
        assert f"LOGS_{k} = {v}" in cpp and f"EV_{k} = {v}" in dll


def test_the_source_has_no_hard_coded_game_address():
    text = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    found = [x for x in re.findall(r"0x[0-9A-Fa-f]{5,8}\b", text)
             if int(x, 16) > 0x400000 and x.lower() not in ("0x474c3156u", "0x400000u", "0x401000u")]
    assert not found, found


def test_the_per_save_layout_mirrors_the_virtual_villagers_patcher():
    dll = (SRC / "vf1logs.cpp").read_text(encoding="utf-8")
    assert 'kSaves[] = "Virtual Families 1 Patcher\\\\Save "' in dll
    for name in ('"\\\\Logs\\\\"', '"\\\\Data\\\\"', '"Family History"', '"Births and Conceptions"',
                 '"Virtual Families 1 Births and Conceptions Log"', '"Virtual Families 1 Deaths Log"',
                 '"Virtual Families 1 Events Log"', '"Family Population"', '"Family Statistics"',
                 '"Virtual Families 1 Parents"', '"Virtual Families 1 Family Members at Last Save"',
                 '"Unaccounted Villagers"', '"Log Checks"', '"Backups"'):
        assert name in dll, name


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


# ===================================================================== the DLL under emulation
def _build(kind: str, out_dir: Path) -> Path:
    need_toolchain()
    out_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_logs.bat")] + ([kind] if kind else []),
                       capture_output=True, text=True, env=dict(_env(), VF1_BUILD_DIR=str(out_dir)))
    assert r.returncode == 0, r.stdout + r.stderr
    return out_dir / ("vf1logs_test.dll" if kind == "test" else "vf1logs.dll")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    exe = vanilla_exe()
    out = tmp_path_factory.mktemp("logs_build")
    return {"exe": exe, "test": _build("test", out), "ship": _build("", out)}


def world(built, **kw):
    from logs_scenarios import LogsWorld
    return LogsWorld(built["exe"], built["test"], **kw)


def test_the_shipped_dll_has_no_test_entry_points(built):
    data = built["ship"].read_bytes()
    assert b"VF1Logs_Startup" in data and b"VF1Logs_Event" in data and b"VF1Logs_TestLogged" not in data


def test_install_writes_only_the_planned_sites(built):
    w = world(built)
    assert w.installed == 1
    st = w.status()
    assert st["requested"] == 1 and st["resolved"] == 1 and st["installed"] == 1 and st["writes"] == 11
    expected = set()
    for site, _target in ((s, t) for _p, s, t in L.CALL_HOOKS):
        expected.update(range(site + 1, site + 5))           # call displacements only
    for name, (pin, steal) in L.ENTRY_HOOKS.items():
        expected.update(range(L.PIN[pin][1], L.PIN[pin][1] + 5))
    changed = w.changed_code()
    assert changed <= expected and changed, sorted(hex(x) for x in changed - expected)
    for _p, site, _t in L.CALL_HOOKS:
        assert w.e.read(site, 1) == b"\xE8"
    assert w.e.r32(L.GS_VTABLE_LOAD) != L.FUNCTIONS["GS_LOAD"] and w.e.r32(L.GS_VTABLE_SAVE) != L.FUNCTIONS["GS_SAVE"]


def test_setting_off_or_missing_is_stock(built):
    for setting in (0, None):
        w = world(built, setting=setting)
        assert w.installed == 0 and not w.changed_code()
        assert w.e.r32(L.GS_VTABLE_SAVE) == L.FUNCTIONS["GS_SAVE"]
        w.event(1, -1, 500)
        assert not w.fs.files


@pytest.mark.parametrize("va", [0x48C2EE, 0x481D11, 0x4819E5, 0x48EBB2, 0x424F93])
def test_a_patched_pin_refuses_everything(built, va):
    def damage(w):
        w.e.write(va, bytes([w.e.read(va, 1)[0] ^ 0x01]))
        w.code_before = w._code()
    w = world(built, before_install=damage)
    assert w.installed == 0 and not w.changed_code()


def test_new_family_wipes_the_slot_and_creates_every_log(built):
    w = world(built)
    root = w.root()
    w.fs.write(root + "\\Logs\\Family History\\Family History 1.txt", b"old family\r\n")
    w.fs.write(root + "\\Data\\Parents\\Virtual Families 1 Parents - Save 1.dat", b"old")
    w.fs.write(root + "\\Backups\\keep.txt", b"keep me")
    w.fs.write(w.root(2) + "\\Logs\\Family History\\Family History 1.txt", b"another slot")
    w.start_family(0, "Ann", 1, 26)
    assert w.fs.read(root + "\\Backups\\keep.txt") == b"keep me", "Backups are kept"
    assert w.fs.read(w.root(2) + "\\Logs\\Family History\\Family History 1.txt") == b"another slot"
    assert w.fs.read(root + "\\Data\\Parents\\Virtual Families 1 Parents - Save 1.dat") is None
    assert w.history() == ("Family: Hopkins (Save 1)\r\n" + STAMP +
                           "Generation 1 began: Ann (Female, 26) was adopted and started the family\r\n")
    for text in (w.births(), w.deaths(), w.events()):
        assert text == "Family: Hopkins (Save 1)\r\n"
    assert w.data("Log Checks", "Virtual Families 1 Backfill").startswith("VF1LOGS BACKFILL 1\r\n")
    assert w.status()["wipes"] == 1


def family(built, **kw):
    w = world(built, **kw)
    w.start_family(0, "Ann", 1, 26)
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    assert w.marry(0, 1) == 1
    w.mother, w.father = 0, 1
    return w


def test_marriage_is_one_history_line(built):
    w = family(built)
    assert w.history_lines()[-1] == STAMP + "Ann (Female, 26) married Bob (Male, 27), generation 1"


def test_conception_and_twin_birth(built):
    w = family(built)
    # Twins: the twin roll (rand(100) < 7) passes, the triplet roll fails.
    assert w.conceive(rolls=[0, 99], names=["Cid", "Dee"]) == 1
    assert w.births().endswith(
        "Conception 1\r\n"
        "  Mother: Ann\r\n    Age at conception: 26\r\n    Sex: Female\r\n    Head: 3\r\n    Body: 4\r\n"
        "  Father: Bob\r\n    Age at conception: 27\r\n    Sex: Male\r\n    Head: 7\r\n    Body: 8\r\n"
        "  Babies Nursing: 2\r\n  Generation: 1\r\n\r\n")
    assert w.history_lines()[-1] == STAMP + "Conception 1: Ann and Bob (babies Nursing: 2)"
    parents = w.data("Parents", "Virtual Families 1 Parents")
    assert parents.count("\tAnn\tBob\tconceived\r\n") == 2, parents
    babies = list(w.spawned)
    assert len(babies) == 2
    w.physiology()                                       # the REAL delivery block runs
    for b in babies:
        assert w.e.read(w.villager(b) + 0x13574, 1) == b"\x01"
    text = w.births()
    assert "Birth 1\r\n  Child: Cid\r\n" in text and "Birth 2\r\n  Child: Dee\r\n" in text
    assert text.count("  Father: Bob\r\n  Born as: Twins\r\n") == 2
    lines = w.history_lines()
    assert lines[-2].startswith(STAMP + "Birth 1: Cid (") and lines[-2].endswith("was born to Ann and Bob (Twins)")
    # The babies came from Impregnate's own AddOffspring calls: not "joined".
    assert not any("joined the family" in x for x in lines)
    w.physiology()                                       # nothing more to deliver: nothing more written
    assert w.births() == text


def test_no_delivery_before_it_is_due(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.physiology(age_on=5)
    assert "Birth " not in w.births()
    w.physiology(age_on=21)
    assert "Birth 1\r\n  Child: Cid\r\n" in w.births() and "Born as: Single birth" in w.births()


def test_death_is_logged_once_with_the_exes_cause(built):
    w = family(built)
    w.die(1, cause=2)
    text = w.deaths()
    assert text == ("Family: Hopkins (Save 1)\r\n"
                    "Death 1\r\n  Name: Bob\r\n  Age at death: 27\r\n  Sex: Male\r\n  Cause of death: Old age\r\n"
                    "  Head: 7\r\n  Body: 8\r\n  Family role: Parent (married in)\r\n  Generation: 1\r\n\r\n")
    w.die(1, cause=2, how="body")                        # the body's removal reports it again
    assert w.deaths() == text
    assert w.history_lines()[-1] == STAMP + "Death 1: Bob (Male, 27) died: Old age"
    w.die(0, cause=-1, how="body")                       # first seen at the body's removal
    assert "Death 2\r\n  Name: Ann\r\n" in w.deaths() and "Cause of death: Unknown causes" in w.deaths()


def test_a_saved_body_is_not_logged_again_after_a_load(built):
    w = family(built)
    w.die(1, cause=2)
    w.e.write(w.villager(1) + 0x13574, b"\x01")          # the body is still in the house at the save
    w.save()
    members = w.data("Unaccounted Villagers", "Virtual Families 1 Family Members at Last Save")
    assert "member\t1\tBob\t0\t540\t7\t8\t1\t0\t0\t1\r\n" in members
    w2 = world(built)                                     # a new session
    w2.set_villager(1, "Bob", 0, years=27, head=7, body=8, health=0)
    w2.fs = w.fs
    w2.fs.bind(w2.e)
    w2.e.write(L.FAMILY_TREE, w.e.read(L.FAMILY_TREE, 4 + 30 * L.FAMILY_RECORD_SIZE))
    w2.load()
    assert w2.logged(1) == 1
    w2.die(1, cause=2, how="body")
    assert w2.deaths().count("Death ") == 1


def test_leaving_home_uses_the_games_caption(built):
    w = family(built)
    w.set_villager(4, "Eve", 1, years=19, career=-1)
    w.leave_home(4)
    assert w.e.read(w.villager(4) + 0x13578, 1) == b"\x01"
    assert w.history_lines()[-1] == STAMP + "Eve is going to college! (Female, 19, left home)"
    w.leave_home(4)                                       # already gone: no second line
    assert sum("college" in x for x in w.history_lines()) == 1


def test_children_who_join(built):
    w = family(built)
    w.set_villager(5, "Lil", 1, years=3, career=-1)       # The Little Visitor / Adopt Outside Child: no parents
    assert w.add_offspring(5) == 1
    assert w.history_lines()[-1] == STAMP + "Lil (Female, 3) joined the family as a child, adopted, generation 1"
    w.set_villager(6, "Max", 0, years=5, career=-1)       # Spawn Child: the couple in its bio
    w.e.write(w.villager(6) + L.VILLAGER_BIO_PARENT1, b"Ann\0")
    w.e.write(w.villager(6) + L.VILLAGER_BIO_PARENT2, b"Bob\0")
    assert w.add_offspring(6) == 1
    assert w.history_lines()[-1].endswith("Max (Male, 5) joined the family as a child of Ann and Bob, generation 1")
    parents = w.data("Parents", "Virtual Families 1 Parents")
    assert "child\t5\tLil\t1\t1\t\t\tadopted\r\n" in parents and "child\t6\tMax\t0\t1\tBob\tAnn\tjoined\r\n" in parents


def test_next_generation_and_adopt_new_person(built):
    w = family(built)
    w.set_villager(2, "Kid", 0, years=20, career=-1)
    w.add_offspring(2)
    assert w.next_generation(2, 0) == 1
    assert w.generations() == 2
    assert w.history_lines()[-1] == STAMP + "New Generation: generation 2 began: Kid (Male, 20) inherited the house"
    w.set_villager(9, "Zed", 0, years=25)
    assert w.next_generation(9, -1) == 1
    assert w.history_lines()[-1] == STAMP + "Generation 3 began: Zed (Male, 25) was adopted (Adopt New Person)"


def test_the_patchers_events(built):
    w = family(built)
    w.event(1, -1, 500)
    w.event(2, 1)
    text = w.events()
    assert "Event 1\r\n  Event: Roll the Dice\r\n  Cost: $500\r\n  Generation: 1\r\n\r\n" in text
    assert "Event 2\r\n  Event: Divorce Spouse\r\n  Name: Bob\r\n  Age: 27\r\n  Sex: Male\r\n" in text
    assert w.history_lines()[-2:] == [STAMP + "Event 1: Roll the Dice ($500)", STAMP + "Event 2: Divorce Spouse: Bob"]
    # Evict Family: the household is named, and the new family after it keeps the same logs.
    w.event(3)
    assert "  Event: Evict Family\r\n  Family members: Ann, Bob\r\n" in w.events()
    w.reset_tree()
    w.start_family(3, "Nia", 1, 30)
    assert w.status()["wipes"] == 1, "an eviction is not a new slot"
    assert w.history_lines()[-1] == STAMP + "Generation 1 began after the eviction: Nia (Female, 30) was adopted"
    assert "Event 3" in w.events()


def test_start_over_wipes_the_slot_but_keeps_backups(built):
    w = family(built)
    w.fs.write(w.root() + "\\Backups\\b.txt", b"b")
    w.start_over()
    assert w.restarts == [w.state]
    assert w.fs.under(w.root()) == [w.fs.key(w.root() + "\\Backups\\b.txt")]


def test_save_writes_population_statistics_and_members(built):
    w = family(built)
    w.conceive(rolls=[99, 99], names=["Cid"])
    w.physiology()
    w.e.write(L.MONEY, __import__("struct").pack("<f", 1234.0))
    w.e.w32(L.FOOD, 77)
    w.e.w32(L.STATS_OLDEST, 81)
    w.save()
    pop = w.snapshot("Family Population")
    assert pop.startswith("Virtual Families 1 Family Population\r\nFamily: Hopkins (Save 1)\r\nGeneration: 1\r\n")
    assert "Family Member 1\r\n  Name: Ann\r\n  Age: 26\r\n  Sex: Female\r\n" in pop
    assert "  Family role: Parent (married in)\r\n" in pop and "  Name: Cid\r\n" in pop
    stats = w.snapshot("Family Statistics")
    assert stats == ("Virtual Families 1\r\nFamily Statistics\r\nFamily: Hopkins (Save 1)\r\n\r\n"
                     "Generations: 1\r\nFamily Members: 3\r\nBabies Born: 1\r\nDeaths: 0\r\n"
                     "Oldest Family Member Ever: 81\r\nMoney: $1234\r\nFood: 77\r\n")
    assert w.saves == [1]
    w.save(21)                                            # the game's backup copy: nothing of ours
    assert w.saves == [1, 21] and w.status()["lastSave"] == 1


def test_numbered_records_roll_every_256(built):
    w = family(built)
    for k in range(257):
        w.event(1, -1, 500)
    first, second = w.events(n=1), w.events(n=2)
    assert first.count("\r\nEvent ") == 256 and second.startswith("Family: Hopkins (Save 1)\r\nEvent 257\r\n")


def test_events_go_to_the_current_slot(built):
    w = family(built)
    w.set_slot(3)
    w.event(1, -1, 500)
    assert "Event 1" in w.events(slot=3) and "Event 1" not in (w.events(slot=1) or "")


# ------------------------------------------------------------------ chaining with the other companions
def test_chains_over_another_companions_entry_jmp_and_vtable_and_call_hooks(built):
    """vf1kids.dll hooks AddOffspring / StartNextGeneration at their entries with a 5-byte jmp; vf1fun.dll
    retargets the Impregnate call and replaces the Save / Load vtable slots. All are kept and called."""
    hits = []

    def companions(w):
        e = w.e
        for va, steal in ((L.FUNCTIONS["FT_ADD_OFFSPRING"], 5), (L.FUNCTIONS["FT_START_NEXT_GEN"], 6)):
            stub = e.fake_code(e.read(va, steal) + b"\xE9" + b"\0" * 4)
            e.w32(stub + steal + 1, (va + steal) - (stub + steal + 5))
            head = e.fake_code(b"\x90\xE9" + b"\0" * 4)       # the companion's handler: a nop, then the stolen bytes
            e.w32(head + 2, stub - (head + 6))
            e.uc.hook_add(1 << 2, lambda uc, a, s, u, va=va: hits.append(va), begin=head, end=head)
            e.write(va, b"\xE9" + __import__("struct").pack("<i", head - (va + 5)))
        wrapper = e.fake_code(b"\x90\xE9" + b"\0" * 4)        # vf1fun's Impregnate wrapper
        e.w32(wrapper + 2, L.FUNCTIONS["V_IMPREGNATE"] - (wrapper + 6))
        e.uc.hook_add(1 << 2, lambda uc, a, s, u: hits.append("impregnate"), begin=wrapper, end=wrapper)
        e.w32(0x48EBB3, wrapper - 0x48EBB7)
        for slot, real in ((L.GS_VTABLE_SAVE, L.FUNCTIONS["GS_SAVE"]), (L.GS_VTABLE_LOAD, L.FUNCTIONS["GS_LOAD"])):
            h = e.fake_code(b"\x90\xE9" + b"\0" * 4)
            e.w32(h + 2, real - (h + 6))
            e.uc.hook_add(1 << 2, lambda uc, a, s, u, slot=slot: hits.append(slot), begin=h, end=h)
            e.w32(slot, h)
        w.code_before = w._code()
    w = world(built, before_install=companions)
    assert w.installed == 1
    w.start_family(0, "Ann", 1, 26)
    assert L.FUNCTIONS["FT_START_NEXT_GEN"] in hits
    w.set_villager(1, "Bob", 0, years=27, head=7, body=8)
    w.marry(0, 1)
    w.conceive(rolls=[99, 99], names=["Cid"])
    assert "impregnate" in hits and L.FUNCTIONS["FT_ADD_OFFSPRING"] in hits
    assert "Conception 1" in w.births()
    w.save()
    w.load()
    assert L.GS_VTABLE_SAVE in hits and L.GS_VTABLE_LOAD in hits and w.saves == [1] and w.loads == [1]


# ------------------------------------------------------------------ backfill on copies of real saves
def _real(name):
    import make_vf1_save_fixtures as fx
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_backfill_of_a_real_save_matches_its_family_tree(built, name):
    w = world(built)
    save = w.load_save_image(_real(name), slot=2)
    assert w.load(2) == 1
    lines = w.history_lines(2)
    assert lines and all(x.startswith("[backfilled, no date] Generation ") for x in lines)
    want = []
    for g, rec in enumerate(save.family_records, 1):
        sexes = {0: "Male", 1: "Female"}
        couple = [p for p in (rec.parent1, rec.parent2) if p.used]
        head = f"[backfilled, no date] Generation {g}: "
        head += " and ".join(f"{p.name} ({sexes.get(p.sex, 'Male')})" for p in couple) if couple else "(nobody)"
        head += " were the parents" if rec.parent2.used else " was the parent"
        want.append(head)
        for c in rec.children:
            if c.used:
                want.append(f"[backfilled, no date] Generation {g}: child {c.name} ({sexes.get(c.sex, 'Male')})"
                            + (", died" if c.slot == -1 else ""))
        for p in (rec.parent1, rec.parent2):
            if p.used and p.slot == -1:
                want.append(f"[backfilled, no date] Generation {g}: {p.name} died")
    assert lines == want
    assert w.history(2).startswith(f"Family: {save.family_name or '(no name)'} (Save 2)\r\n")
    marker = w.data("Log Checks", "Virtual Families 1 Backfill", slot=2)
    assert "how\tbackfilled\r\n" in marker
    assert w.status()["lastLoad"] == 2
    # Once: a second load (and the start-up's loads of every slot) adds nothing.
    before = w.history(2)
    w.load(2)
    assert w.history(2) == before and w.status()["lastLoad"] == 1
    # The counters' baseline is the tree's deaths and the game's own babies, less the unborn.
    stats = w.data("Family Statistics", "Family Statistics", slot=2)
    deaths = sum(1 for rec in save.family_records for p in [rec.parent1, rec.parent2, *rec.children] if p.used and p.slot == -1)
    babies = save.stats.babies_born - len([b for b in save.pending_babies if b != -1])
    assert stats == f"VF1LOGS STATS 1\r\nbabies\t{max(babies, 0)}\r\ndeaths\t{deaths}\r\n"


def test_backfill_never_repeats_over_logs_that_already_began(built):
    w = world(built)
    w.load_save_image(_real("generation6_left_home"), slot=1)
    w.fs.write(w.root() + "\\Logs\\Family History\\Family History 1.txt", b"Family: x (Save 1)\r\n" + STAMP.encode() + b"x\r\n")
    w.load(1)
    assert "backfilled" not in w.history() and "how\tlogs found" in w.data("Log Checks", "Virtual Families 1 Backfill")
