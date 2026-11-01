"""The Children files stay matched to their saves after every tool that rewrites a save.

vf1kids takes the extra children (7 to 28) from a Children file only when it names the FNV-1a 64 hash and size of
the loaded save (native/vf1kids/vf1kids.cpp AfterLoad); otherwise it keeps only the ones still at home and drops
those who left or died. Rename Family, Game Speed and Back Up Saves' Paused copies change a save's bytes, so each
re-matches the slot's Children files that described the save before the change, as Copy Player Slot does.

Every test works on a save folder built in tmp_path from the real-save fixtures, with a fake process list. No real
save, game or process is touched.
"""
import json
import struct
from datetime import datetime
from pathlib import Path

import pytest

import make_vf1_save_fixtures as fx
import vf1_game_speed as gs
import vf1_genealogy as gen
import vf1_rename_family as rf
import vf1_save as vs
import vf1_save_backup as sb

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vf1_saves"
NOW = datetime(2026, 10, 31, 10, 0, 0)
NORMAL_SAVE = "pregnant_unborn_baby"      # gs 10, clock 10
PAUSED_SAVE = "generation6_left_home"     # gs 1009, clock 0 / 10
CHILDREN = Path(vs.PATCHER_DATA) / "Children"
KIDS = [gen.ExtraChild(10 + k, k % 2, state, 1, 1, 20, f"Kid{7 + k}")
        for k, state in enumerate(["alive", "alive", "gone", "dead", "gone", "alive"])]
EVERYONE = sorted(k.name for k in KIDS)
AT_HOME = sorted(k.name for k in KIDS if k.state == "alive")


class Processes:
    def __init__(self, *answers):
        self.answers = list(answers) or [[]]
        self.calls = 0

    def find(self, exe_name):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def fixture(name: str) -> bytes:
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


def options_bytes(names: list[str]) -> bytes:
    payload = bytearray(vs.OPTIONS_SIZE)
    payload[0:2] = b"\x03\x00"
    for index, name in enumerate(names):
        at = rf.OPTIONS_FIRST_NAME - vs.GS_SAVED_END + rf.OPTIONS_NAME_STRIDE * index
        payload[at:at + rf.OPTIONS_NAME_STRIDE] = name.encode("ascii").ljust(rf.OPTIONS_NAME_STRIDE, b"\0")
    return b"ldwg" + struct.pack("<IqII", 1700000000, 1700000000, vs.OPTIONS_SIZE, 0) + bytes(payload)


def sidecar(save: bytes) -> bytes:
    return gen.make_children_sidecar(save, 2, 0, 0, KIDS)


def simulated_load(folder: Path, slot: int) -> list[str]:
    """The extra children vf1kids keeps when the game loads ``slot`` (AfterLoad, the family being the same):
    every one when the slot's Children file (or the N+20 one, for a restored backup) names the save's hash and
    size; otherwise only those still at home."""
    save = (folder / f"Virtual Families{slot}.ldw").read_bytes()
    found = []
    for number in (slot, slot + 20):
        path = folder / CHILDREN / f"Virtual Families{number}.ldw.dat"
        found.append(gen.read_children_sidecar(path.read_bytes()) if path.is_file() else None)
    for file in found:
        if file is not None and file.save_hash == gen.fnv1a64(save) and file.save_size == len(save):
            return sorted(k.name for k in file.children)
    if found[0] is not None:
        return sorted(k.name for k in found[0].children if k.state == "alive")
    return []


def matches(folder: Path, number: int, save_number: int | None = None) -> bool:
    save = (folder / f"Virtual Families{save_number or number}.ldw").read_bytes()
    file = gen.read_children_sidecar((folder / CHILDREN / f"Virtual Families{number}.ldw.dat").read_bytes())
    return file is not None and file.save_hash == gen.fnv1a64(save) and file.save_size == len(save)


@pytest.fixture
def folder(tmp_path):
    save = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    (save / CHILDREN).mkdir(parents=True)
    normal = fixture(NORMAL_SAVE)
    paused = fixture(PAUSED_SAVE)
    name1, name2 = rf.save_name(normal), rf.save_name(paused)
    assert name1 and name2 and name1 != name2
    (save / "Virtual Families1.ldw").write_bytes(normal)
    (save / "Virtual Families21.ldw").write_bytes(normal[:-1] + b"\x7f")        # an older save of slot 1
    (save / "Virtual Families2.ldw").write_bytes(paused)
    (save / "Virtual Families0.ldw").write_bytes(options_bytes([name1, name2, "", "", ""]))
    for number in (1, 21, 2):
        data = (save / f"Virtual Families{number}.ldw").read_bytes()
        (save / CHILDREN / f"Virtual Families{number}.ldw.dat").write_bytes(sidecar(data))
    return save


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER not in p.relative_to(folder).parts}


def test_the_bug_a_stale_children_file_drops_the_children_who_left_or_died(folder):
    assert simulated_load(folder, 1) == EVERYONE
    path = folder / "Virtual Families1.ldw"
    path.write_bytes(gs.changed_bytes(path.read_bytes(), gs.PAUSED))       # the save changed, the file did not
    assert simulated_load(folder, 1) == AT_HOME != EVERYONE


# ------------------------------------------------------------------ Rename Family


def test_rename_rematches_the_slots_children_files(folder):
    before = tree(folder)
    result = rf.rename_family(folder, 1, "Newname", processes=Processes(), now=NOW)
    after = tree(folder)
    assert sorted(p.name for p in result.rematched) == ["Virtual Families1.ldw.dat", "Virtual Families21.ldw.dat"]
    assert matches(folder, 1) and matches(folder, 21)
    assert simulated_load(folder, 1) == EVERYONE
    # Only the hash, size and checksum changed; the other slot's file is untouched.
    for number in (1, 21):
        key = f"{CHILDREN.as_posix()}/Virtual Families{number}.ldw.dat"
        assert gen.read_children_sidecar(after[key]).children == gen.read_children_sidecar(before[key]).children
        assert after[key][:24] == before[key][:24] and after[key][36:-8] == before[key][36:-8]
    key2 = f"{CHILDREN.as_posix()}/Virtual Families2.ldw.dat"
    assert after[key2] == before[key2]
    # The backup holds the family as it was (its copy Paused, its Children file matched to that copy).
    assert rf.save_name((result.backup.backup_folder / "Virtual Families1.ldw").read_bytes()) == \
        rf.save_name(before["Virtual Families1.ldw"])
    assert matches(result.backup.backup_folder, 1) and simulated_load(result.backup.backup_folder, 1) == EVERYONE
    assert result.backup.unpaused_bytes[CHILDREN / "Virtual Families1.ldw.dat"] == \
        before[f"{CHILDREN.as_posix()}/Virtual Families1.ldw.dat"]


def test_rename_leaves_a_children_file_that_did_not_match(folder):
    path = folder / CHILDREN / "Virtual Families1.ldw.dat"
    foreign = sidecar(b"another save")
    path.write_bytes(foreign)
    damaged = folder / CHILDREN / "Virtual Families21.ldw.dat"
    damaged.write_bytes(damaged.read_bytes()[:-1] + b"\0")
    damaged_bytes = damaged.read_bytes()
    result = rf.rename_family(folder, 1, "Newname", processes=Processes(), now=NOW)
    assert result.rematched == []
    assert path.read_bytes() == foreign and damaged.read_bytes() == damaged_bytes


def test_a_failed_rename_puts_the_children_files_back(folder, monkeypatch):
    before = tree(folder)
    monkeypatch.setattr(rf, "children_match", lambda path, save: False)
    with pytest.raises(rf.RenameError, match="put back"):
        rf.rename_family(folder, 1, "Newname", processes=Processes(), now=NOW)
    assert tree(folder) == before


# ------------------------------------------------------------------ Game Speed


@pytest.mark.parametrize("slot,target", [(1, gs.PAUSED), (2, gs.NORMAL_NAME)])
def test_game_speed_rematches_the_slots_children_file(folder, slot, target):
    before = tree(folder)
    save = (folder / f"Virtual Families{slot}.ldw").read_bytes()
    unix_now = vs.parse_header(save).epoch + gs.read_state(save).saved_at + 60
    result = gs.set_speed(folder, slot, target, processes=Processes(), now=NOW, unix_now=unix_now)
    assert [p.name for p in result.rematched] == [f"Virtual Families{slot}.ldw.dat"]
    assert matches(folder, slot) and simulated_load(folder, slot) == EVERYONE
    after = tree(folder)
    changed = {k for k in after if after[k] != before.get(k)}
    assert changed == {f"Virtual Families{slot}.ldw", f"{CHILDREN.as_posix()}/Virtual Families{slot}.ldw.dat"}


def test_game_speed_leaves_a_children_file_that_did_not_match(folder):
    path = folder / CHILDREN / "Virtual Families1.ldw.dat"
    foreign = sidecar(b"another save")
    path.write_bytes(foreign)
    result = gs.set_speed(folder, 1, gs.PAUSED, processes=Processes(), now=NOW)
    assert result.rematched == [] and path.read_bytes() == foreign


def test_a_failed_speed_change_puts_the_save_and_children_file_back(folder, monkeypatch):
    before = tree(folder)
    monkeypatch.setattr(rf, "children_match", lambda path, save: False)
    with pytest.raises(gs.SpeedError, match="put back"):
        gs.set_speed(folder, 1, gs.PAUSED, processes=Processes(), now=NOW)
    assert tree(folder) == before


# ------------------------------------------------------------------ Back Up Saves (Paused copies) and Restore


def test_the_backups_children_file_matches_its_paused_copy(folder):
    before = tree(folder)
    result = sb.back_up_save_folder(folder, processes=Processes(), now=NOW)
    backup = result.backup_folder
    assert result.paused_slots == ["Virtual Families1.ldw"]                  # slot 2 was already paused
    assert result.rematched_children == ["Virtual Families1.ldw.dat"]
    assert matches(backup, 1) and simulated_load(backup, 1) == EVERYONE
    assert matches(backup, 2) and matches(backup, 21)                       # unchanged and still matching
    assert tree(folder) == before                                           # the live saves are never written
    # The kept "as it was" bytes put a failed restore back exactly.
    assert result.unpaused_bytes[CHILDREN / "Virtual Families1.ldw.dat"] == \
        before[f"{CHILDREN.as_posix()}/Virtual Families1.ldw.dat"]
    # The backup's own check of every copied file still holds.
    for copied in result.files:
        assert sb._hash_file(backup / copied.relative) == (copied.size, copied.sha256)


def test_a_backup_leaves_a_children_file_that_did_not_match(folder):
    path = folder / CHILDREN / "Virtual Families1.ldw.dat"
    foreign = sidecar(b"another save")
    path.write_bytes(foreign)
    result = sb.back_up_save_folder(folder, processes=Processes(), now=NOW)
    assert result.rematched_children == []
    assert (result.backup_folder / CHILDREN / "Virtual Families1.ldw.dat").read_bytes() == foreign


@pytest.mark.parametrize("slot", [None, 1])
def test_a_restored_backup_keeps_every_child(folder, slot):
    backup = sb.back_up_save_folder(folder, processes=Processes(), now=NOW).backup_folder
    # The family plays on (a new save, a new Children file), then the backup is restored.
    live = folder / "Virtual Families1.ldw"
    newer = live.read_bytes()[:-2] + b"\x01\x02"
    live.write_bytes(newer)
    (folder / CHILDREN / "Virtual Families1.ldw.dat").write_bytes(sidecar(newer))
    sb.restore_backup(folder, backup, slot, processes=Processes(), now=datetime(2026, 10, 31, 11, 0, 0))
    assert gs.read_state(live.read_bytes()).label == "Paused"
    assert matches(folder, 1) and simulated_load(folder, 1) == EVERYONE


def test_a_failed_restore_puts_the_children_file_back_as_it_was(folder, monkeypatch):
    backup = sb.back_up_save_folder(folder, processes=Processes(), now=NOW).backup_folder
    live = folder / "Virtual Families1.ldw"
    newer = live.read_bytes()[:-2] + b"\x01\x02"
    live.write_bytes(newer)
    (folder / CHILDREN / "Virtual Families1.ldw.dat").write_bytes(sidecar(newer))
    before = tree(folder)
    real_place = sb._place
    placed = []

    def flaky(source, target):
        placed.append(target.name)
        if len(placed) == 2:                  # the save and the Children file are the two changes
            raise OSError("disk full")
        real_place(source, target)

    monkeypatch.setattr(sb, "_place", flaky)
    with pytest.raises(sb.BackupError, match="put back"):
        sb.restore_backup(folder, backup, None, processes=Processes(), now=datetime(2026, 10, 31, 11, 0, 0))
    assert tree(folder) == before
    assert simulated_load(folder, 1) == EVERYONE


# ------------------------------------------------------------------ one-slot restore takes the slot's own folder


def test_the_slots_patcher_folder_belongs_to_the_slot():
    assert sb.file_slot(Path("Virtual Families 1 Patcher/Save 3/Logs/Family History/Family History 1.txt")) == 3
    assert sb.file_slot(Path("Virtual Families 1 Patcher/Save 2/Data/Family Tree/x.tree")) == 2
    assert sb.file_slot(Path(f"{vs.PATCHER_DATA}/Outfits/Virtual Families4.ldw.dat")) == 4
    assert sb.file_slot(Path("Virtual Families 1 Patcher/Save 9/x.txt")) == "unknown"
    assert sb.file_slot(Path("Elsewhere/Save 3/x.txt")) == "unknown"


def test_a_one_slot_restore_restores_the_slots_logs_and_outfits_and_nothing_of_another_slot(folder):
    logs1 = folder / rf.LOGS_ROOT / "Save 1" / "Logs" / "Family History"
    logs2 = folder / rf.LOGS_ROOT / "Save 2" / "Logs" / "Family History"
    outfits = folder / vs.PATCHER_DATA / "Outfits"
    for where in (logs1, logs2, outfits):
        where.mkdir(parents=True, exist_ok=True)
    (logs1 / "Family History 1.txt").write_bytes(b"old 1\r\n")
    (logs2 / "Family History 1.txt").write_bytes(b"old 2\r\n")
    (outfits / "Virtual Families1.ldw.dat").write_bytes(b"outfits 1 old")
    backup = sb.back_up_save_folder(folder, processes=Processes(), now=NOW).backup_folder
    (logs1 / "Family History 1.txt").write_bytes(b"old 1\r\nnew 1\r\n")
    (logs2 / "Family History 1.txt").write_bytes(b"old 2\r\nnew 2\r\n")
    (outfits / "Virtual Families1.ldw.dat").write_bytes(b"outfits 1 new")
    result = sb.restore_backup(folder, backup, 1, processes=Processes(), now=datetime(2026, 10, 31, 11, 0, 0))
    assert (logs1 / "Family History 1.txt").read_bytes() == b"old 1\r\n"
    assert (outfits / "Virtual Families1.ldw.dat").read_bytes() == b"outfits 1 old"
    assert (logs2 / "Family History 1.txt").read_bytes() == b"old 2\r\nnew 2\r\n"     # another slot: untouched
    assert result.before_restore is not None
    assert (result.before_restore.backup_folder / rf.LOGS_ROOT / "Save 1" / "Logs" / "Family History"
            / "Family History 1.txt").read_bytes() == b"old 1\r\nnew 1\r\n"
