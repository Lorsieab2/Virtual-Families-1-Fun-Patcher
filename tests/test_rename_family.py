"""Rename Family (patcher/vf1_rename_family.py).

Every test works on a save folder built in tmp_path (or a copy of the owner's saved copies, which are only
read) with a fake process list; no real save, game or process is touched.
"""
import shutil
import struct
from datetime import datetime
from pathlib import Path

import pytest

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
        index = min(self.calls - 1, len(self.answers) - 1)
        return self.answers[index]


def header(payload: int, size: int = 24) -> bytes:
    if size == 12:
        return b"ldwg" + struct.pack("<II", 1700000000, payload)
    return b"ldwg" + struct.pack("<IqII", 1700000000, 1700000000, payload, 0)


def slot_bytes(name: str, size: int = 24, filler: int = 0x11) -> bytes:
    payload = bytearray([filler]) * vs.PAYLOAD_SIZE
    field = vs.GS_FAMILY_NAME - vs.GS_BASE
    payload[field:field + rf.FAMILY_NAME_FIELD] = name.encode("ascii").ljust(rf.FAMILY_NAME_FIELD, b"\0")
    return header(vs.PAYLOAD_SIZE, size) + bytes(payload)


def options_bytes(names: list[str], size: int = 24) -> bytes:
    payload = bytearray(vs.OPTIONS_SIZE)
    payload[0:2] = b"\x03\x00"
    for index, name in enumerate(names):
        at = rf.OPTIONS_FIRST_NAME - vs.GS_SAVED_END + rf.OPTIONS_NAME_STRIDE * index
        payload[at:at + rf.OPTIONS_NAME_STRIDE] = name.encode("ascii").ljust(rf.OPTIONS_NAME_STRIDE, b"\0")
    return header(vs.OPTIONS_SIZE, size) + bytes(payload)


@pytest.fixture
def save(tmp_path):
    folder = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    folder.mkdir(parents=True)
    names = ["Smith", "Jones", "Smith", "", ""]
    for slot in (1, 2, 3):
        (folder / f"Virtual Families{slot}.ldw").write_bytes(slot_bytes(names[slot - 1], filler=slot))
    (folder / "Virtual Families21.ldw").write_bytes(slot_bytes("Smith", filler=0x21))   # slot 1, same family
    (folder / "Virtual Families41.ldw").write_bytes(slot_bytes("Older", filler=0x41))   # slot 1, another name
    (folder / "Virtual Families23.ldw").write_bytes(slot_bytes("Smith", filler=0x23))   # slot 3 (not slot 1)
    (folder / "Virtual Families0.ldw").write_bytes(options_bytes(["Smith", "Jones", "Smith", "", ""]))
    data = folder / sb.PATCHER_DATA_FOLDER / "Children"
    data.mkdir(parents=True)
    (data / "Virtual Families1.ldw.dat").write_bytes(b"kids")
    (folder / sb.PATCHER_DATA_FOLDER / "Slot 1.ini").write_text("[Slot]\nA=1\n")
    return folder


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER not in p.relative_to(folder).parts}


def differing_bytes(a: bytes, b: bytes) -> list[int]:
    assert len(a) == len(b)
    return [i for i in range(len(a)) if a[i] != b[i]]


def add_history(folder: Path, slot: int, *numbers: int, text="Smith history\r\n") -> list[Path]:
    root = folder / rf.LOGS_ROOT / f"Save {slot}" / "Logs" / "Family History"
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for number in numbers:
        path = root / f"Family History {number}.txt"
        path.write_bytes(text.encode("ascii"))
        paths.append(path)
    return paths


# ------------------------------------------------------------------ the name rule


@pytest.mark.parametrize("name", ["A", "Smith Family", "Zed-9 & Co.", "x" * 19, " Spaced ",
                                  # Render Unicode with In-Game Fonts: UTF-8, 19 bytes (patcher/vf1_text.py)
                                  "Caf\u00e9", "\u4e2d\u6587", "\u00e9" * 9 + "x", "Zo\u00eb \U0001f44d\U0001f3fd"])
def test_names_the_game_can_store_are_accepted(name):
    assert rf.name_problem(name) is None


@pytest.mark.parametrize("name,words", [
    ("", "Type a name"), ("x" * 20, "too long"), ("   ", "only spaces"), ("\u00e9" * 10, "too long"),
    ("Tab\there", "characters"), ("Line\nbreak", "characters"), ("\u4e2d" * 7, "too long"),
    ("Bad\x85", "characters"),
])
def test_names_it_cannot_store_are_refused(name, words):
    assert words in rf.name_problem(name)


# ------------------------------------------------------------------ reading


def test_the_slots_are_read_from_their_saves(save):
    slots = {s.slot: s for s in rf.read_slots(save)}
    assert slots[1].label == "Save 1: Smith" and slots[2].label == "Save 2: Jones"
    assert slots[3].name == "Smith" and slots[1].problem is None
    assert slots[4].name is None and slots[4].label == "Save 4: (empty)"


def test_an_unreadable_save_or_menu_file_is_reported(save):
    (save / "Virtual Families2.ldw").write_bytes(b"garbage")
    assert "not a Virtual Families save" in {s.slot: s for s in rf.read_slots(save)}[2].problem
    (save / "Virtual Families0.ldw").unlink()
    assert "could not be read" in {s.slot: s for s in rf.read_slots(save)}[1].problem


def test_a_family_with_no_name_is_listed(save):
    (save / "Virtual Families1.ldw").write_bytes(slot_bytes(""))
    assert {s.slot: s for s in rf.read_slots(save)}[1].label == "Save 1: (no name)"


# ------------------------------------------------------------------ renaming


def test_rename_writes_only_the_name_fields(save):
    before = tree(save)
    result = rf.rename_family(save, 1, "The Joneses", Processes(), NOW)
    after = tree(save)
    assert (result.old_name, result.new_name, result.slot) == ("Smith", "The Joneses", 1)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"Virtual Families1.ldw", "Virtual Families21.ldw", "Virtual Families0.ldw"}
    # the slot save: only the 28-byte name field differs, and it is the new name, zero-padded
    field = 24 + vs.GS_FAMILY_NAME - vs.GS_BASE
    for name in ("Virtual Families1.ldw", "Virtual Families21.ldw"):
        diff = differing_bytes(before[name], after[name])
        assert diff and min(diff) >= field and max(diff) < field + rf.FAMILY_NAME_FIELD
        assert after[name][field:field + rf.FAMILY_NAME_FIELD] == b"The Joneses".ljust(rf.FAMILY_NAME_FIELD, b"\0")
        assert vs.parse_save(after[name]).family_name == "The Joneses"
    # the menu: only slot 1's 21-byte name differs
    menu_at = 24 + 0xA
    diff = differing_bytes(before["Virtual Families0.ldw"], after["Virtual Families0.ldw"])
    assert diff and min(diff) >= menu_at and max(diff) < menu_at + rf.OPTIONS_NAME_STRIDE
    assert rf.menu_name(after["Virtual Families0.ldw"], 1) == "The Joneses"
    assert rf.menu_name(after["Virtual Families0.ldw"], 2) == "Jones"
    assert rf.menu_name(after["Virtual Families0.ldw"], 3) == "Smith"
    assert {s.slot: s.name for s in rf.read_slots(save)} == {1: "The Joneses", 2: "Jones", 3: "Smith", 4: None, 5: None}


def test_another_family_in_an_older_copy_and_other_slots_are_left_alone(save):
    before = tree(save)
    rf.rename_family(save, 1, "New", Processes(), NOW)
    after = tree(save)
    for name in ("Virtual Families41.ldw", "Virtual Families23.ldw", "Virtual Families2.ldw", "Virtual Families3.ldw"):
        assert after[name] == before[name], name
    for name in before:
        if name.startswith("Virtual Families 1 Patcher Data"):
            assert after[name] == before[name]


def test_the_legacy_12_byte_header_is_renamed_too(save):
    (save / "Virtual Families2.ldw").write_bytes(slot_bytes("Jones", size=12))
    (save / "Virtual Families0.ldw").write_bytes(options_bytes(["Smith", "Jones", "Smith", "", ""], size=12))
    rf.rename_family(save, 2, "Legacy", Processes(), NOW)
    data = (save / "Virtual Families2.ldw").read_bytes()
    assert vs.parse_save(data).family_name == "Legacy"
    assert rf.menu_name((save / "Virtual Families0.ldw").read_bytes(), 2) == "Legacy"
    assert rf.menu_name((save / "Virtual Families0.ldw").read_bytes(), 1) == "Smith"


def test_the_longest_name_fits_and_shortening_zeroes_the_rest(save):
    rf.rename_family(save, 1, "x" * 19, Processes(), NOW)
    assert rf.read_slots(save)[0].name == "x" * 19
    rf.rename_family(save, 1, "y", Processes(), NOW)
    data = (save / "Virtual Families1.ldw").read_bytes()
    field = 24 + vs.GS_FAMILY_NAME - vs.GS_BASE
    assert data[field:field + rf.FAMILY_NAME_FIELD] == b"y" + b"\0" * (rf.FAMILY_NAME_FIELD - 1)
    assert data[field + rf.FAMILY_NAME_FIELD:] == slot_bytes("", filler=1)[field + rf.FAMILY_NAME_FIELD:]


@pytest.mark.parametrize("slot,name,words", [
    (1, "x" * 20, "too long"), (1, "", "Type a name"), (1, "Smith", "already called"),
    (4, "Fresh", "no family"), (6, "Fresh", "no save slot"),
])
def test_refused_renames_change_nothing(save, slot, name, words):
    before = tree(save)
    with pytest.raises(rf.RenameError, match=words):
        rf.rename_family(save, slot, name, Processes(), NOW)
    assert tree(save) == before
    assert not (save / sb.BACKUPS_FOLDER).exists()


def test_it_is_refused_while_the_game_runs(save):
    before = tree(save)
    with pytest.raises(rf.GameRunning, match="Close the game first"):
        rf.rename_family(save, 1, "New", Processes([4242]), NOW)
    assert tree(save) == before and not (save / sb.BACKUPS_FOLDER).exists()


def test_a_game_started_during_the_backup_is_refused(save):
    before = tree(save)
    with pytest.raises(rf.GameRunning):
        rf.rename_family(save, 1, "New", Processes([], [4242]), NOW)
    assert tree(save) == before


def test_a_process_list_that_cannot_be_read_refuses(save):
    class Broken:
        def find(self, exe_name):
            raise sb.BackupError("no list")

    before = tree(save)
    with pytest.raises(rf.RenameError, match="Could not check"):
        rf.rename_family(save, 1, "New", Broken(), NOW)
    assert tree(save) == before


def test_the_backup_comes_first_holds_the_old_name_and_is_listed(save):
    before = tree(save)
    result = rf.rename_family(save, 1, "New", Processes(), NOW)
    assert result.backup.backup_folder.name == "Backup 2026-10-24 12-30-05 (before rename)"
    assert tree(result.backup.backup_folder) == before
    listed = sb.list_backups(save)
    assert len(listed) == 1 and listed[0].before_rename and not listed[0].before_restore
    assert listed[0].label.endswith("(before rename)") and listed[0].slots == [1, 2, 3]


def test_restoring_the_rename_backup_undoes_it(save):
    before = tree(save)
    rf.rename_family(save, 1, "New", Processes(), NOW)
    backup = sb.list_backups(save)[0].path
    sb.restore_backup(save, backup, None, Processes(), datetime(2026, 10, 24, 13, 0, 0))
    assert tree(save) == before


def test_a_failed_backup_changes_nothing(save, monkeypatch):
    def fail(*_a, **_k):
        raise sb.BackupError("disk full")

    monkeypatch.setattr(sb, "copy_save_folder", fail)
    before = tree(save)
    with pytest.raises(rf.RenameError, match="backup before renaming failed"):
        rf.rename_family(save, 1, "New", Processes(), NOW)
    assert tree(save) == before


# ------------------------------------------------------------------ the logs


def test_the_family_history_gets_one_record_numbered_after_the_others_and_nothing_is_rewritten(save):
    older, newest = add_history(save, 1, 1, 2)
    other = save / rf.LOGS_ROOT / "Save 2" / "Logs" / "Family History" / "Family History 1.txt"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"Family: Jones (Save 2)\r\n")
    older.write_bytes(b"Family: Smith (Save 1)\r\n[2026-01-01 00:00:00] Family Renamed 4\r\n  Old name: A\r\n  New name: Smith\r\n\r\n")
    snapshot = {p: p.read_bytes() for p in (older, other)}
    result = rf.rename_family(save, 1, "Brand New", Processes(), NOW)
    assert result.notes == [newest]
    assert newest.read_bytes() == (
        b"Smith history\r\n" + b"[2026-10-24 12:30:05] Family Renamed 5\r\n  Old name: Smith\r\n  New name: Brand New\r\n\r\n")
    assert {p: p.read_bytes() for p in snapshot} == snapshot       # the old logs keep their history and header


def test_a_line_that_ended_without_a_newline_is_continued_properly(save):
    (path,) = add_history(save, 1, 1, text="[2026-01-01 00:00:00] Event")
    rf.rename_family(save, 1, "New", Processes(), NOW)
    assert path.read_bytes() == (
        b"[2026-01-01 00:00:00] Event\r\n" + b"[2026-10-24 12:30:05] Family Renamed 1\r\n  Old name: Smith\r\n  New name: New\r\n\r\n")


def test_a_family_with_no_history_file_gets_no_record(save):
    result = rf.rename_family(save, 1, "New", Processes(), NOW)
    assert result.notes == []
    assert not (save / rf.LOGS_ROOT).exists()                     # nothing is invented


def test_a_family_with_no_name_is_logged_as_such(save):
    (save / "Virtual Families1.ldw").write_bytes(slot_bytes(""))
    (path,) = add_history(save, 1, 1)
    rf.rename_family(save, 1, "Named", Processes(), NOW)
    assert path.read_bytes().endswith(b"[2026-10-24 12:30:05] Family Renamed 1\r\n  Old name: (no name)\r\n  New name: Named\r\n\r\n")


def test_a_failure_part_way_puts_every_file_back(save, monkeypatch):
    (path,) = add_history(save, 1, 1)
    before = tree(save)
    real = rf._write_atomically
    options = rf.options_path(save)

    def fail_on_the_menu(target, data):
        if target == options:
            raise rf.RenameError("disk error")
        real(target, data)

    monkeypatch.setattr(rf, "_write_atomically", fail_on_the_menu)
    with pytest.raises(rf.RenameError, match="every file was put back"):
        rf.rename_family(save, 1, "New", Processes(), NOW)
    monkeypatch.undo()
    assert tree(save) == before
    assert path.read_bytes() == before[path.relative_to(save).as_posix()]
    assert len(sb.list_backups(save)) == 1                        # the backup stays


def test_a_log_that_fails_after_the_saves_are_written_rolls_everything_back(save, monkeypatch):
    (path,) = add_history(save, 1, 1)
    before = tree(save)
    real_open = Path.open

    def open_fail(self, mode="r", *a, **k):
        if self == path and "a" in mode:
            raise OSError("log is locked")
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", open_fail)
    with pytest.raises(rf.RenameError, match="put back"):
        rf.rename_family(save, 1, "New", Processes(), NOW)
    monkeypatch.undo()
    assert tree(save) == before


def test_a_file_changed_after_it_was_planned_is_not_overwritten(save, monkeypatch):
    original = sb.copy_save_folder

    def backup_then_change(folder, now=None, suffix=""):
        result = original(folder, now, suffix)
        (folder / "Virtual Families1.ldw").write_bytes(slot_bytes("Smith", filler=0x77))   # the game saved
        return result

    monkeypatch.setattr(sb, "copy_save_folder", backup_then_change)
    with pytest.raises(rf.RenameError, match="changed while it was being renamed"):
        rf.rename_family(save, 1, "New", Processes(), NOW)
    assert (save / "Virtual Families1.ldw").read_bytes() == slot_bytes("Smith", filler=0x77)


# ------------------------------------------------------------------ the owner's real saves (copies, read only)


@pytest.mark.skipif(not (SAVECOPIES / "f1" / "Virtual Families0.ldw").is_file(), reason="no saved copies here")
def test_a_copy_of_a_real_save_folder_renames_and_reads_back(tmp_path):
    folder = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    shutil.copytree(SAVECOPIES / "f1", folder)
    slots = {s.slot: s for s in rf.read_slots(folder)}
    assert all(slots[s].problem is None for s in slots if slots[s].name is not None)
    old = vs.read_save(folder / "Virtual Families5.ldw")
    result = rf.rename_family(folder, 5, "Renamed Clan", Processes(), NOW)
    assert result.old_name == old.family_name
    renamed = vs.read_save(folder / "Virtual Families5.ldw")
    assert renamed.family_name == "Renamed Clan"
    # nothing but the name changed in the parsed village
    assert [v.name for v in renamed.villagers] == [v.name for v in old.villagers]
    assert renamed.money == old.money and renamed.food == old.food and renamed.generation == old.generation
    assert rf.menu_name((folder / "Virtual Families0.ldw").read_bytes(), 5) == "Renamed Clan"
    assert {s.slot: s.name for s in rf.read_slots(folder)}[1] == slots[1].name
