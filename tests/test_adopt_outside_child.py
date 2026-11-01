"""Adopt Outside Boy / Girl: the Family page adopts an outside child the way the
game's own Little Visitor event does (CEventTheLittleVisitor1/2::ImpactGame).
The vanilla bytes pin the evidence; the sources pin the feature."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAMILY = (ROOT / "native" / "vf1fun" / "family.inc").read_text(encoding="utf-8")
PAGE = (ROOT / "native" / "vf1fun" / "family_page.inc").read_text(encoding="utf-8")
VERIFIED = json.loads((ROOT / "data" / "vf1_verified.json").read_text(encoding="utf-8"))


def _function(name):
    m = re.search(r"static const wchar_t \*%s\(.*?\n\}\n" % name, FAMILY, re.S)
    assert m, name + " is missing from family.inc"
    return m.group(0)


def test_adopt_outside_child_follows_the_games_visitor_event():
    body = _function("AdoptOutsideChild")
    assert "SpawnPeep(VillagerManager, 1, gender, years * 20)" in body  # no parents: an outside child
    assert "SpawnPeepFull" not in body  # SpawnChild's parent-inherited look is not used
    assert "AddOffspring(FamilyTree, Villager(slot))" in body
    assert "IncrementProgress(Achievements, 0xC, 1)" in body and "IncrementProgress(Achievements, 0xD, 1)" in body
    # the same guards as Spawn Child, checked before anything is created
    assert body.index("EmptyOffspringSlots") < body.index("SpawnPeep(")
    assert body.index("years < 2 || years > 13") < body.index("SpawnPeep(")


def test_family_page_has_the_two_adopt_buttons():
    assert "ID_FA_ADOPT_BOY" in PAGE and "ID_FA_ADOPT_GIRL" in PAGE
    # the owner, 2026-11-01: each button says how the child arrives (straight into the house, no event)
    assert "L\"Spawn outside child in house (male)\"" in PAGE and "L\"Spawn outside child in house (female)\"" in PAGE
    assert "AdoptOutsideChild(id == ID_FA_ADOPT_GIRL ? 1 : 0" in PAGE
    # the existing spawn buttons stay
    assert "SpawnChild(id == ID_FA_CHILD_GIRL ? 1 : 0" in PAGE


def test_dialog_ids_are_unique():
    enum = re.search(r"enum \{ ID_FA_STATUS = 700,(.*?)\};", PAGE, re.S).group(1)
    names = re.findall(r"ID_FA_\w+", enum)
    assert len(names) == len(set(names))


def test_adopted_name_is_cut_to_fit_by_setname():
    # The typed name goes to SetName, which fits it to the 24-byte field as UTF-8, cut only between whole
    # characters (text_names.inc FitNameUtf8; tests/test_vf1fun_names.py runs it against vf1_text). Before, the
    # name was cut here with the system code page.
    body = _function("AdoptOutsideChild")
    assert "SetName(slot, name)" in body
    assert "CP_ACP" not in body
    setname = re.search(r"static void SetName\(.*?\n\}\n", FAMILY, re.S).group(0)
    assert "StoreTypedName(name, s)" in setname and "CP_ACP" not in setname
    # StoreTypedName: the name cut to the one name limit, then its short form (vf1text) or what fits the 24 bytes
    names = (ROOT / "native" / "vf1fun" / "text_names.inc").read_text(encoding="utf-8")
    store = names[names.index("static int StoreTypedName"):]
    assert "TextStoreName(whole, 24, field25)" in store and "FitNameUtf8(name, field25, 24)" in store


def test_adopted_name_never_splits_a_surrogate_pair():
    # A non-BMP character is two UTF-16 units: FitNameUtf8 joins a pair into one code point and drops a lone one,
    # and cuts between whole characters only.
    names = (ROOT / "native" / "vf1fun" / "text_names.inc").read_text(encoding="utf-8")
    fit = names[names.index("static int FitNameUtf8"):]
    assert "c >= 0xD800 && c <= 0xDBFF && name[i + 1] >= 0xDC00 && name[i + 1] <= 0xDFFF" in fit
    assert "if (used + bytes > room || letters == VF1_NAME_LETTERS) break;" in fit


def test_evidence_recorded():
    """Checks only that the two verified entries (0x418800, 0x4188B0) name
    AddOffspring in their evidence text. It does not check the call order or
    the call bytes; that is test_vanilla_visitor_events_adopt_an_outside_child,
    which reads the vanilla exe and needs VF1_VANILLA_DIR."""
    for addr in ("0x418800", "0x4188b0"):
        assert "AddOffspring" in VERIFIED[addr]["evidence"]


def test_vanilla_visitor_events_adopt_an_outside_child(vanilla_dir):
    exe = (vanilla_dir / "Virtual Families.exe").read_bytes()
    spawn_tail = "b998885b00e8"  # mov ecx,0x5B8898 (the villager manager); call SpawnPeep
    add_tail = "b908b95a00e8"    # mov ecx,0x5AB908 (the family tree); call AddOffspring
    # Visitor1 (boy): push 0x3C (3 years); push 0 (gender); push 1 (voice)
    assert bytes.fromhex("6a3c6a006a01" + spawn_tail) in exe
    # Visitor2 (girl): push 0x3C; push 1 (gender); push 1 (voice)
    assert bytes.fromhex("6a3c6a016a01" + spawn_tail) in exe
    assert exe.count(bytes.fromhex(add_tail)) >= 2
    # both then record achievement progress 0xC and 0xD
    assert exe.count(bytes.fromhex("6a016a0cb9d8085000e8")) >= 2
    assert exe.count(bytes.fromhex("6a016a0db9d8085000e8")) >= 2
