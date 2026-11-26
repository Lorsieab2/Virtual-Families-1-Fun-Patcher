"""Delete Player Slot (patcher/vf1_delete_slot.py), the Copy Player Slot window's Delete.

Every test works on a save folder built in tmp_path (Copy Player Slot's own fixture) with a fake process list, and
the Recycle Bin is always a stand-in that removes only the temporary files it is handed: nothing is ever sent to the
real Recycle Bin, and no real save, game or process is touched.
"""
from pathlib import Path

import pytest

import vf1_copy_slot as cs
import vf1_delete_slot as ds
import vf1_save_backup as sb
from test_copy_slot import DATA, NOW, Processes, save  # noqa: F401 -- the shared save folder fixture

ROOT1 = "Virtual Families 1 Patcher/Save 1"


class Bin:
    """The Recycle Bin stand-in: every path it is handed must be a file under the test's folder; it removes them."""

    def __init__(self, folder: Path, fail_on: int | None = None):
        self.folder = folder
        self.fail_on = fail_on
        self.calls: list[list[Path]] = []

    def __call__(self, paths):
        self.calls.append(list(paths))
        if self.fail_on is not None and len(self.calls) >= self.fail_on:
            raise OSError("Windows could not move the files to the Recycle Bin (error 0x78).")
        for path in paths:
            assert Path(path).resolve().is_relative_to(self.folder.resolve()) and Path(path).is_file()
            Path(path).unlink()


def everything(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def full(save):
    """Save 1 with pictures, a whole-folder backup, and a set-aside folder of its own and one of Save 2's."""
    (save / ROOT1 / "Family Tree" / "Virtual Families 1 Family Tree - Save 1.png").write_bytes(b"\x89PNG one")
    (save / ROOT1 / "Family Tree" / "Virtual Families 1 Family Tree - Save 1 - Page 2.png").write_bytes(b"\x89PNG two")
    backup = sb.copy_save_folder(save, NOW).backup_folder
    aside = save / "Backups" / "Replaced by copy 2026-10-30 10-00-00 - Save 1 - Older"
    (aside / DATA).mkdir(parents=True)
    (aside / "Virtual Families1.ldw").write_bytes(b"an older family")
    (aside / DATA / "Slot 1.ini").write_text("x")
    (aside / "photo.jpg").write_bytes(b"jpeg")
    other = save / "Backups" / "Replaced by move 2026-10-30 10-00-00 - Save 2 - Someone"
    other.mkdir()
    (other / "Virtual Families2.ldw").write_bytes(b"someone")
    return save, backup


def test_every_file_of_the_slot_goes_but_pictures(full):
    save, backup = full
    before = everything(save)
    plan = ds.plan_delete(save, 1)
    assert plan.name == "Smith" and plan.backups == 1 and plan.asides == 1
    rel = lambda p: p.relative_to(save).as_posix()              # noqa: E731
    files = {rel(p) for p in plan.files}
    pictures = {rel(p) for p in plan.pictures}
    b = rel(backup)
    assert pictures == {f"{ROOT1}/Family Tree/Virtual Families 1 Family Tree - Save 1.png",
                        f"{ROOT1}/Family Tree/Virtual Families 1 Family Tree - Save 1 - Page 2.png",
                        f"{b}/{ROOT1}/Family Tree/Virtual Families 1 Family Tree - Save 1.png",
                        f"{b}/{ROOT1}/Family Tree/Virtual Families 1 Family Tree - Save 1 - Page 2.png",
                        "Backups/Replaced by copy 2026-10-30 10-00-00 - Save 1 - Older/photo.jpg"}
    expected_live = {
        "Virtual Families1.ldw", "Virtual Families21.ldw", "Virtual Families41.ldw", f"{DATA}/Slot 1.ini",
        f"{DATA}/Children/Virtual Families1.ldw.dat", f"{DATA}/Children/Virtual Families21.ldw.dat",
        f"{DATA}/Children/Virtual Families1.ldw.unreadable-1.dat", f"{DATA}/Outfits/Virtual Families1.ldw.dat",
        f"{ROOT1}/Logs/Family History/Family History 1.txt", f"{ROOT1}/Logs/Family History/Family History 2.txt",
        f"{ROOT1}/Data/Family Tree/Virtual Families 1 Family Tree - Save 1.tree",
        f"{ROOT1}/Data/Family Tree/Virtual Families 1 Family Tree Edits - Save 1.json",
        f"{ROOT1}/Family Tree/Virtual Families 1 Family Tree - Save 1.html", f"{ROOT1}/Backups/old.txt"}
    assert files == expected_live | {f"{b}/{k}" for k in expected_live} | {
        "Backups/Replaced by copy 2026-10-30 10-00-00 - Save 1 - Older/Virtual Families1.ldw",
        f"Backups/Replaced by copy 2026-10-30 10-00-00 - Save 1 - Older/{DATA}/Slot 1.ini"}
    recycle = Bin(save)
    result = ds.delete_slot(save, 1, processes=Processes(), now=NOW, expected=plan.signature(), recycle=recycle)
    assert result.problem is None and len(result.recycled) == len(files) and result.backups_touched == 1
    after = everything(save)
    assert not files & set(after)
    assert pictures <= set(after)                               # pictures always stay
    # Nothing else changed: Save 2, the shared files, Save 2's files in the backup, the other slot's set-aside.
    for key, value in before.items():
        if key not in files and key != "Virtual Families0.ldw":
            assert after[key] == value, key
    assert (backup / "Virtual Families2.ldw").is_file() and (backup / "Virtual Families0.ldw").is_file()
    # The slot menu: only Save 1's in-use flag is cleared. No new backup was made.
    menu, old = after["Virtual Families0.ldw"], before["Virtual Families0.ldw"]
    assert cs.slot_used(menu, 1) is False and cs.slot_used(menu, 2) is True
    assert [i for i in range(len(menu)) if menu[i] != old[i]] == [cs._used_offset(old, 1)]
    assert len(sb.list_backups(save)) == 1
    slots = {s.slot: s for s in cs.read_slots(save)}
    assert slots[1].empty and slots[2].name == "Jones"
    # The slot's emptied folders are removed; the ones still holding pictures stay.
    assert not (save / ROOT1 / "Logs").exists() and not (save / ROOT1 / "Data").exists()
    assert (save / ROOT1 / "Family Tree").is_dir()


def test_the_preview_lists_every_file_and_the_pictures_kept(full):
    save, _backup = full
    plan = ds.plan_delete(save, 1)
    lines = plan.preview()
    assert "Recycled:  Virtual Families1.ldw" in lines
    assert any(line.startswith("Kept (pictures):  ") and line.endswith("Save 1 - Page 2.png") for line in lines)
    assert len(lines) == len(plan.files) + len(plan.pictures)


def test_a_recycle_bin_failure_stops_and_says_what_is_left(full):
    save, _backup = full
    plan = ds.plan_delete(save, 1)
    result = ds.delete_slot(save, 1, processes=Processes(), now=NOW, recycle=Bin(save, fail_on=2))
    assert result.problem is not None and "stopped in Backups\\" in result.problem
    assert result.recycled and result.not_recycled
    assert set(result.recycled) | set(result.not_recycled) == set(plan.files)
    assert all(p.exists() for p in result.not_recycled) and not any(p.exists() for p in result.recycled)
    # The save itself went (the first batch), so the slot menu no longer lists it.
    assert cs.slot_used((save / "Virtual Families0.ldw").read_bytes(), 1) is False


def test_a_failure_before_the_save_goes_leaves_the_slot_menu(full):
    save, _backup = full
    before = everything(save)
    result = ds.delete_slot(save, 1, processes=Processes(), now=NOW, recycle=Bin(save, fail_on=1))
    assert result.problem is not None and not result.recycled
    assert everything(save) == before


def test_a_running_game_or_changed_files_refuse(full):
    save, _backup = full
    before = everything(save)
    with pytest.raises(ds.GameRunning, match="Close the game first"):
        ds.delete_slot(save, 1, processes=Processes([4242]), now=NOW, recycle=Bin(save))
    shown = ds.plan_delete(save, 1).signature()
    (save / ROOT1 / "Logs" / "Family History" / "Family History 3.txt").write_bytes(b"Family: Smith (Save 1)\r\n")
    with pytest.raises(ds.DeleteError, match="changed after you confirmed"):
        ds.delete_slot(save, 1, processes=Processes(), now=NOW, expected=shown, recycle=Bin(save))
    after = everything(save)
    del after[f"{ROOT1}/Logs/Family History/Family History 3.txt"]
    assert after == before


def test_slots_with_leftovers_can_be_deleted_and_empty_ones_cannot(save):
    (save / "Virtual Families43.ldw").write_bytes(b"left by a family deleted in the game")
    assert ds.deletable_slots(save) == [(1, "Save 1: Smith"), (2, "Save 2: Jones"),
                                        (3, f"Save 3: {ds.NO_SAVE}")]
    with pytest.raises(ds.DeleteError, match="no files to delete"):
        ds.plan_delete(save, 4)
    result = ds.delete_slot(save, 3, processes=Processes(), now=NOW, recycle=Bin(save))
    assert result.problem is None and not (save / "Virtual Families43.ldw").exists()


def test_the_real_recycle_bin_is_never_reached_without_a_stand_in(save, monkeypatch):
    """The module's Windows call is the one place files leave; it is the shared vf1_translations.recycle."""
    handed = []
    monkeypatch.setattr(ds, "_shell", lambda paths: handed.append(list(paths)) or [Path(p).unlink() for p in paths])
    ds.delete_slot(save, 2, processes=Processes(), now=NOW)
    assert handed and all(Path(p).resolve().is_relative_to(save.resolve()) for batch in handed for p in batch)
