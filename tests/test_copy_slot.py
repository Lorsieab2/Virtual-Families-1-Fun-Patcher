"""Copy Player Slot (patcher/vf1_copy_slot.py).

Every test works on a save folder built in tmp_path from the real-save fixtures (tests/fixtures/vf1_saves), or on a
copy of the owner's saved copies (only read), with a fake process list; no real save, game or process is touched.
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest

import vf1_copy_slot as cs
import vf1_family_history as fh
import vf1_genealogy as gen
import vf1_rename_family as rf
import vf1_save as vs
import vf1_save_backup as sb
from test_game_speed import NORMAL_SAVE, PAUSED_SAVE, fixture
from test_rename_family import options_bytes

NOW = datetime(2026, 10, 31, 14, 5, 9)
SAVECOPIES = Path(r"C:\vf1\savecopies")
DATA = sb.PATCHER_DATA_FOLDER


class Processes:
    def __init__(self, *answers):
        self.answers = list(answers) or [[]]
        self.calls = 0

    def find(self, exe_name):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def named(data: bytes, name: str) -> bytes:
    at = rf._save_name_offset(data)
    return rf._with_name(data, at, rf.FAMILY_NAME_FIELD, name)


def with_flags(options: bytes, used: list[int]) -> bytes:
    out = bytearray(options)
    for slot in cs.SLOTS:
        out[cs._used_offset(options, slot)] = 1 if slot in used else 0
    return bytes(out)


def kids_sidecar(save: bytes) -> bytes:
    child = gen.ExtraChild(9, 1, "gone", 3, 4, 20, "Zed")
    return gen.make_children_sidecar(save, 2, 0, 0, [child])


def outfits_file() -> bytes:
    return b"VF1OUTFT" + bytes(140)


@pytest.fixture
def save(tmp_path):
    folder = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    folder.mkdir(parents=True)
    smith = named(fixture(NORMAL_SAVE), "Smith")
    smith21 = named(fixture(NORMAL_SAVE), "Smith")
    older = named(fixture(PAUSED_SAVE), "Older")
    jones = named(fixture(PAUSED_SAVE), "Jones")
    (folder / "Virtual Families1.ldw").write_bytes(smith)
    (folder / "Virtual Families21.ldw").write_bytes(smith21)
    (folder / "Virtual Families41.ldw").write_bytes(older)
    (folder / "Virtual Families2.ldw").write_bytes(jones)
    (folder / "Virtual Families0.ldw").write_bytes(with_flags(options_bytes(["Smith", "Jones", "", "", ""]), [1, 2]))
    (folder / "ldwLog.txt").write_text("engine log\n")
    children = folder / DATA / "Children"
    children.mkdir(parents=True)
    (children / "Virtual Families1.ldw.dat").write_bytes(kids_sidecar(smith))
    (children / "Virtual Families21.ldw.dat").write_bytes(kids_sidecar(smith21))
    (children / "Virtual Families1.ldw.unreadable-1.dat").write_bytes(b"damaged")
    (children / "Virtual Families2.ldw.dat").write_bytes(kids_sidecar(jones))
    outfits = folder / DATA / "Outfits"
    outfits.mkdir()
    (outfits / "Virtual Families1.ldw.dat").write_bytes(outfits_file())
    (outfits / "Virtual Families2.ldw.dat").write_bytes(outfits_file() + b"2")
    (folder / DATA / "Slot 1.ini").write_text("[Village]\nMaid=1\n")
    (folder / DATA / "Slot 2.ini").write_text("[Village]\nMaid=0\n")
    root = folder / rf.LOGS_ROOT / "Save 1"
    logs = root / "Logs" / "Family History"
    logs.mkdir(parents=True)
    (logs / "Family History 1.txt").write_bytes(b"Family: Smith (Save 1)\r\n[2026-10-01 10:00:00] Birth 1\r\n  Child: Ann\r\n\r\n")
    (logs / "Family History 2.txt").write_bytes(b"Family: Smith (Save 1)\r\n[2026-10-02 10:00:00] Birth 2\r\n  Child: Bob\r\n\r\n")
    trees = root / "Data" / "Family Tree"
    trees.mkdir(parents=True)
    tree = {"format": "Virtual Families 1 Patcher family tree", "game": 1, "slot": 1, "family": "Smith",
            "members": {"list": [{"mid": 1, "slot": 4, "name": "Ann"}]}}
    (trees / "Virtual Families 1 Family Tree - Save 1.tree").write_text(json.dumps(tree, indent=1), encoding="utf-8")
    (trees / "Virtual Families 1 Family Tree Edits - Save 1.json").write_text('{"format": 1, "title": null}')
    (root / "Family Tree").mkdir()
    (root / "Family Tree" / "Virtual Families 1 Family Tree - Save 1.html").write_text("page")
    (root / "Backups").mkdir()
    (root / "Backups" / "old.txt").write_text("kept")
    two = folder / rf.LOGS_ROOT / "Save 2" / "Logs" / "Family History"
    two.mkdir(parents=True)
    (two / "Family History 1.txt").write_bytes(b"Family: Jones (Save 2)\r\n")
    return folder


def tree_of(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER != p.relative_to(folder).parts[0]}


def is_slot(rel: str, slot: int) -> bool:
    return vs.file_owner(rel) is not None and vs.file_owner(rel)[0] == slot or f"/Save {slot}/" in rel


# ------------------------------------------------------------------ reading


def test_slots_are_read_with_their_menu_flag(save):
    slots = {s.slot: s for s in cs.read_slots(save)}
    assert slots[1].label == "Save 1: Smith" and not slots[1].empty and slots[1].problem is None
    assert slots[3].empty and slots[3].label == "Save 3: (empty)"
    options = (save / "Virtual Families0.ldw").read_bytes()
    assert cs.slot_used(options, 1) is True and cs.slot_used(options, 4) is False


def test_the_slot_file_set(save):
    files = {p.as_posix() for p in cs.slot_files(save, 1)}
    assert files == {
        "Virtual Families1.ldw", "Virtual Families21.ldw", "Virtual Families41.ldw",
        f"{DATA}/Slot 1.ini", f"{DATA}/Children/Virtual Families1.ldw.dat",
        f"{DATA}/Children/Virtual Families1.ldw.unreadable-1.dat", f"{DATA}/Children/Virtual Families21.ldw.dat",
        f"{DATA}/Outfits/Virtual Families1.ldw.dat",
        "Virtual Families 1 Patcher/Save 1/Logs/Family History/Family History 1.txt",
        "Virtual Families 1 Patcher/Save 1/Logs/Family History/Family History 2.txt",
        "Virtual Families 1 Patcher/Save 1/Data/Family Tree/Virtual Families 1 Family Tree - Save 1.tree",
        "Virtual Families 1 Patcher/Save 1/Data/Family Tree/Virtual Families 1 Family Tree Edits - Save 1.json",
        "Virtual Families 1 Patcher/Save 1/Family Tree/Virtual Families 1 Family Tree - Save 1.html",
    }


# ------------------------------------------------------------------ the copy


def test_a_full_copy_with_every_sidecar(save):
    before = tree_of(save)
    result = cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    after = tree_of(save)
    assert result.old_name == "Smith" and result.new_name == "Smith Two"
    # The save: the same bytes but the name.
    new, old = after["Virtual Families4.ldw"], before["Virtual Families1.ldw"]
    assert rf.save_name(new) == "Smith Two" and len(new) == len(old)
    assert named(new, "Smith") == old
    assert rf.save_name(after["Virtual Families24.ldw"]) == "Smith Two"
    assert after["Virtual Families44.ldw"] == before["Virtual Families41.ldw"]      # another name: copied as it is
    # The slot menu: name and in-use flag.
    menu = after["Virtual Families0.ldw"]
    assert rf.menu_name(menu, 4) == "Smith Two" and cs.slot_used(menu, 4) is True
    # Patcher data.
    assert after[f"{DATA}/Slot 4.ini"] == before[f"{DATA}/Slot 1.ini"]
    assert after[f"{DATA}/Outfits/Virtual Families4.ldw.dat"] == before[f"{DATA}/Outfits/Virtual Families1.ldw.dat"]
    assert after[f"{DATA}/Children/Virtual Families4.ldw.unreadable-1.dat"] == b"damaged"
    # Children files describe the copied saves (so vf1kids takes them as exact), and nothing else changed in them.
    for n, m in ((4, 4), (24, 24)):
        kid = gen.read_children_sidecar(after[f"{DATA}/Children/Virtual Families{n}.ldw.dat"])
        assert kid is not None
        assert kid.save_hash == gen.fnv1a64(after[f"Virtual Families{m}.ldw"]) and kid.save_size == len(new)
        src = gen.read_children_sidecar(before[f"{DATA}/Children/Virtual Families{n - 3}.ldw.dat"])
        assert (kid.generations, kid.parent_slot, kid.parent_sex, kid.children) == \
               (src.generations, src.parent_slot, src.parent_sex, src.children)
    # The family tree files, renamed for slot 4.
    trees = "Virtual Families 1 Patcher/Save 4/Data/Family Tree/"
    tree = json.loads(after[trees + "Virtual Families 1 Family Tree - Save 4.tree"])
    assert tree["slot"] == 4 and tree["family"] == "Smith Two"
    assert tree["members"]["list"][0]["slot"] == 4                                 # a villager slot: unchanged
    assert after[trees + "Virtual Families 1 Family Tree Edits - Save 4.json"] == \
        before["Virtual Families 1 Patcher/Save 1/Data/Family Tree/Virtual Families 1 Family Tree Edits - Save 1.json"]
    # The Family History, whole, with one Family Copied record at the end of the newest file.
    logs = "Virtual Families 1 Patcher/Save 4/Logs/Family History/"
    assert after[logs + "Family History 1.txt"] == before["Virtual Families 1 Patcher/Save 1/Logs/Family History/Family History 1.txt"]
    newest = after[logs + "Family History 2.txt"]
    old_newest = before["Virtual Families 1 Patcher/Save 1/Logs/Family History/Family History 2.txt"]
    assert newest.startswith(old_newest)
    assert newest[len(old_newest):] == (b"[2026-10-31 14:05:09] Family Copied 1\r\n  Copied from: Save 1\r\n"
                                        b"  Old name: Smith\r\n  New name: Smith Two\r\n\r\n")
    history = fh.read(save, 4)
    assert history.renames == [("Smith", "Smith Two")] and len(history.births) == 2
    # Not copied: the source's generated tree page and its Backups.
    assert not any("/Save 4/Family Tree/" in k or "/Save 4/Backups/" in k for k in after)
    assert "Virtual Families 1 Patcher/Save 1/Family Tree/Virtual Families 1 Family Tree - Save 1.html" in \
        {p.as_posix() for p in result.left_out}
    # Every new file is slot 4's; nothing else in the folder changed but the options file.
    for key, value in before.items():
        if key != "Virtual Families0.ldw":
            assert after[key] == value, key
    assert all(is_slot(k, 4) for k in set(after) - set(before))
    assert not list(save.rglob("*.tmp"))


def test_the_options_file_changes_only_the_targets_name_and_flag(save):
    before = (save / "Virtual Families0.ldw").read_bytes()
    cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    after = (save / "Virtual Families0.ldw").read_bytes()
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    name_at = rf._menu_name_offset(before, 4)
    allowed = set(range(name_at, name_at + rf.OPTIONS_NAME_STRIDE)) | {cs._used_offset(before, 4)}
    assert changed and set(changed) <= allowed
    for slot in (1, 2, 3, 5):
        assert rf.menu_name(after, slot) == rf.menu_name(before, slot)
        assert cs.slot_used(after, slot) == cs.slot_used(before, slot)


def test_the_backup_is_made_first(save, monkeypatch):
    seen = []
    real = sb.copy_save_folder

    def spy(folder, now=None, suffix=""):
        seen.append(((folder / "Virtual Families4.ldw").exists(), suffix))
        return real(folder, now, suffix)

    monkeypatch.setattr(cs.save_backup, "copy_save_folder", spy)
    result = cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    assert seen == [(False, "(before copy)")]
    backups = sb.list_backups(save)
    assert len(backups) == 1 and backups[0].before_copy and backups[0].label.endswith("(before copy)")
    assert result.backup.backup_folder == backups[0].path
    assert not (backups[0].path / "Virtual Families4.ldw").exists()


def test_a_used_target_is_refused_and_nothing_changes(save):
    before = tree_of(save)
    with pytest.raises(cs.CopyError, match="Save 2 is in use"):
        cs.copy_slot(save, 1, 2, "Smith Two", processes=Processes(), now=NOW)
    # A slot the menu calls in use, though its save is missing; and a save the menu calls empty.
    options = (save / "Virtual Families0.ldw").read_bytes()
    (save / "Virtual Families0.ldw").write_bytes(with_flags(options, [1, 2, 3]))
    with pytest.raises(cs.CopyError, match="Save 3 is in use"):
        cs.copy_slot(save, 1, 3, "Smith Two", processes=Processes(), now=NOW)
    (save / "Virtual Families0.ldw").write_bytes(options)
    (save / "Virtual Families5.ldw").write_bytes(b"x")
    with pytest.raises(cs.CopyError, match="Save 5 is in use"):
        cs.copy_slot(save, 1, 5, "Smith Two", processes=Processes(), now=NOW)
    (save / "Virtual Families5.ldw").unlink()
    assert tree_of(save) == before and not (save / "Backups").exists()


@pytest.mark.parametrize("source,target,name,words", [
    (1, 1, "A", "another slot"), (3, 4, "A", "has no family"), (1, 4, "x" * 20, "too long"), (1, 6, "A", "1 to 5"),
])
def test_other_refusals(save, source, target, name, words):
    before = tree_of(save)
    with pytest.raises(cs.CopyError, match=words):
        cs.copy_slot(save, source, target, name, processes=Processes(), now=NOW)
    assert tree_of(save) == before and not (save / "Backups").exists()


def test_a_running_game_is_refused(save):
    before = tree_of(save)
    with pytest.raises(cs.GameRunning, match="Close the game first"):
        cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes([4242]), now=NOW)
    assert tree_of(save) == before and not (save / "Backups").exists()
    # Started while the backup was made: refused before anything is written.
    with pytest.raises(cs.GameRunning):
        cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes([], [4242]), now=NOW)
    assert tree_of(save) == before and sb.list_backups(save)[0].before_copy


def test_every_write_goes_through_a_temporary_file(save, monkeypatch):
    replaced = []
    real = os.replace

    def spy(src, dst):
        if sb.BACKUPS_FOLDER not in Path(dst).parts:          # the backup's own Paused copies are its business
            replaced.append((Path(src).name, Path(dst).name))
        return real(src, dst)

    monkeypatch.setattr(cs.os, "replace", spy)
    result = cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    assert len(replaced) == len(result.written)
    for temp, final in replaced:
        assert temp.startswith(final + ".copy-") and temp.endswith(".tmp")
    assert replaced[-1][1] == "Virtual Families0.ldw"                 # the slot menu is written last


@pytest.mark.parametrize("fail_at", [1, 5, 9, 13])
def test_a_failure_part_way_leaves_no_half_copied_slot(save, monkeypatch, fail_at):
    before = tree_of(save)
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        if sb.BACKUPS_FOLDER in Path(dst).parts:
            return real(src, dst)
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(cs.os, "replace", flaky)
    with pytest.raises(cs.CopyError, match="everything was put back"):
        cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    assert tree_of(save) == before
    assert not (save / rf.LOGS_ROOT / "Save 4").exists()
    assert not list(save.rglob("*.tmp"))


def test_a_deleted_familys_leftovers_are_cleared_and_kept_in_the_backup(save):
    # The game's Delete clears the flag and removes only "<N>.ldw": the rest of slot 4 stays behind.
    (save / "Virtual Families24.ldw").write_bytes(named(fixture(PAUSED_SAVE), "Gone"))
    (save / DATA / "Slot 4.ini").write_text("[Village]\nMaid=1\nLuckyRock=1\n")
    (save / DATA / "Children" / "Virtual Families44.ldw.dat").write_bytes(b"stale")
    stale = save / rf.LOGS_ROOT / "Save 4" / "Logs" / "Family History"
    stale.mkdir(parents=True)
    (stale / "Family History 3.txt").write_bytes(b"Family: Gone (Save 4)\r\n")
    (save / rf.LOGS_ROOT / "Save 4" / "Backups").mkdir()
    (save / rf.LOGS_ROOT / "Save 4" / "Backups" / "mine.txt").write_text("kept")
    result = cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    after = tree_of(save)
    assert f"{DATA}/Children/Virtual Families44.ldw.dat" not in after
    assert "Virtual Families 1 Patcher/Save 4/Logs/Family History/Family History 3.txt" not in after
    assert rf.save_name(after["Virtual Families24.ldw"]) == "Smith Two"
    assert after[f"{DATA}/Slot 4.ini"] == after[f"{DATA}/Slot 1.ini"]
    assert (save / rf.LOGS_ROOT / "Save 4" / "Backups" / "mine.txt").read_text() == "kept"
    assert {p.as_posix() for p in result.cleared} == {
        f"{DATA}/Children/Virtual Families44.ldw.dat",
        "Virtual Families 1 Patcher/Save 4/Logs/Family History/Family History 3.txt"}
    backup = result.backup.backup_folder
    assert (backup / DATA / "Children" / "Virtual Families44.ldw.dat").read_bytes() == b"stale"
    assert (backup / "Virtual Families 1 Patcher/Save 4/Logs/Family History/Family History 3.txt").is_file()


def test_a_failure_puts_a_deleted_familys_leftovers_back(save, monkeypatch):
    (save / DATA / "Children" / "Virtual Families44.ldw.dat").write_bytes(b"stale")
    (save / DATA / "Slot 4.ini").write_text("[Village]\nMaid=1\n")
    before = tree_of(save)
    real = cs._write_atomically

    def fail_on_options(path, data):
        if path.name == "Virtual Families0.ldw":
            raise OSError("locked")
        return real(path, data)

    monkeypatch.setattr(cs, "_write_atomically", fail_on_options)
    with pytest.raises(cs.CopyError, match="everything was put back"):
        cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    assert tree_of(save) == before


def test_the_family_copied_record_is_numbered_after_earlier_ones(save):
    cs.copy_slot(save, 1, 4, "Smith Two", processes=Processes(), now=NOW)
    cs.copy_slot(save, 4, 5, "Smith Three", processes=Processes(), now=NOW)
    text = (save / rf.LOGS_ROOT / "Save 5" / "Logs" / "Family History" / "Family History 2.txt").read_bytes()
    assert b"Family Copied 1\r\n  Copied from: Save 1" in text and b"Family Copied 2\r\n  Copied from: Save 4" in text
    assert fh.read(save, 5).renames == [("Smith", "Smith Two"), ("Smith Two", "Smith Three")]


def test_a_slot_with_no_patcher_files_copies_just_the_save(save):
    cs.copy_slot(save, 2, 3, "Jones Two", processes=Processes(), now=NOW)
    after = tree_of(save)
    assert rf.save_name(after["Virtual Families3.ldw"]) == "Jones Two"
    assert "Virtual Families23.ldw" not in after
    kid = gen.read_children_sidecar(after[f"{DATA}/Children/Virtual Families3.ldw.dat"])
    assert kid.save_hash == gen.fnv1a64(after["Virtual Families3.ldw"])
    assert {s.slot: s.name for s in rf.read_slots(save)}[3] == "Jones Two"


# ------------------------------------------------------------------ the owner's real saves (copies)


def _parsed(data: bytes) -> dict:
    """Everything the save parser reads, except the family name."""
    save = vs.parse_save(data)
    out = {k: getattr(save, k) for k in save.__dataclass_fields__ if k not in ("family_name", "payload")}
    return out


@pytest.mark.skipif(not (SAVECOPIES / "f5" / "Virtual Families0.ldw").is_file(), reason="no saved copies here")
def test_a_real_save_copies_and_parses_the_same_but_the_name(tmp_path):
    folder = tmp_path / "Virtual Families - Modded"
    shutil.copytree(SAVECOPIES / "f5", folder)
    # Free slot 5 as the game's own Delete does: its flag cleared and "Virtual Families5.ldw" removed.
    options = (folder / "Virtual Families0.ldw").read_bytes()
    out = bytearray(options)
    out[cs._used_offset(options, 5)] = 0
    (folder / "Virtual Families0.ldw").write_bytes(bytes(out))
    (folder / "Virtual Families5.ldw").unlink()
    source = (folder / "Virtual Families1.ldw").read_bytes()
    old = rf.save_name(source)
    cs.copy_slot(folder, 1, 5, "Copied Family", processes=Processes(), now=NOW)
    copy = (folder / "Virtual Families5.ldw").read_bytes()
    assert vs.parse_save(copy).family_name == "Copied Family" and vs.parse_save(source).family_name == old
    assert _parsed(copy) == _parsed(source)
    assert named(copy, old) == source
    menu = (folder / "Virtual Families0.ldw").read_bytes()
    assert rf.menu_name(menu, 5) == "Copied Family" and cs.slot_used(menu, 5) is True
    assert (folder / "Virtual Families1.ldw").read_bytes() == source
