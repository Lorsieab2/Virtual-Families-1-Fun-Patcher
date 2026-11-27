"""Move Player Slot (patcher/vf1_move_slot.py), the Copy Player Slot window's Move.

Every test works on a save folder built in tmp_path from the real-save fixtures (Copy Player Slot's own fixture),
with a fake process list; no real save, game or process is touched.
"""
import json
import os
from pathlib import Path

import pytest

import vf1_copy_slot as cs
import vf1_move_slot as ms
import vf1_rename_family as rf
import vf1_save_backup as sb
from test_copy_slot import DATA, NOW, Processes, save, tree_of  # noqa: F401 -- the shared save folder fixture

ROOT1 = "Virtual Families 1 Patcher/Save 1"
ROOT4 = "Virtual Families 1 Patcher/Save 4"


def everything(folder: Path) -> dict[str, bytes]:
    """Every file of the folder, its own Backups too."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def moved_key(key: str, source: int, target: int) -> str:
    return ms.moved_relative(Path(key), source, target).as_posix()


# ------------------------------------------------------------------ what moves


def test_the_slot_file_list_is_copys_list_and_the_whole_save_folder(save):
    files = {p.as_posix() for p in ms.slot_everything(save, 1)}
    copy = {p.as_posix() for p in cs.slot_files(save, 1)}
    assert copy <= files
    assert files - copy == {f"{ROOT1}/Backups/old.txt"}          # Copy leaves the slot's Backups; Move takes it
    assert not any(p.startswith("Backups/") for p in files)


def test_where_each_file_goes():
    assert ms.moved_relative(Path("Virtual Families21.ldw"), 1, 4) == Path("Virtual Families24.ldw")
    assert ms.moved_relative(Path(DATA, "Slot 1.ini"), 1, 4) == Path(DATA, "Slot 4.ini")
    assert ms.moved_relative(Path(DATA, "Children", "Virtual Families41.ldw.unreadable-2.dat"), 1, 4) == \
        Path(DATA, "Children", "Virtual Families44.ldw.unreadable-2.dat")
    assert ms.moved_relative(Path(DATA, "Names", "Virtual Families1.ldw.txt"), 1, 4) == \
        Path(DATA, "Names", "Virtual Families4.ldw.txt")
    assert ms.moved_relative(Path(ROOT1, "Family Tree", "Virtual Families 1 Family Tree - Save 1 - Page 2.png"), 1, 4) \
        == Path(ROOT4, "Family Tree", "Virtual Families 1 Family Tree - Save 4 - Page 2.png")
    assert ms.moved_relative(Path(ROOT1, "Backups", "Save 12 - kept.txt"), 1, 4) == \
        Path(ROOT4, "Backups", "Save 12 - kept.txt")                  # "Save 12" is not "Save 1"


def test_the_slot_number_inside_a_log_header():
    assert ms.moved_history(b"Family: Smith (Save 1)\r\n[x] Birth 1\r\n", 1, 4) == b"Family: Smith (Save 4)\r\n[x] Birth 1\r\n"
    assert ms.moved_history(b"Family: A (Save 1) Jr (Save 1)\n", 1, 3) == b"Family: A (Save 1) Jr (Save 3)\n"
    assert ms.moved_history(b"Family: Smith (Save 2)\r\n", 1, 4) is None        # another slot's: unchanged
    assert ms.moved_history(b"[x] Birth 1\r\n  Family: Smith (Save 1)\r\n", 1, 4) is None   # only the first line
    assert ms.moved_history(b"Family: Smith (Save 1)", 1, 5) == b"Family: Smith (Save 5)"


# ------------------------------------------------------------------ the move


def test_a_full_move_carries_every_file_and_leaves_the_source_empty(save):
    before = everything(save)
    plan = ms.plan_move(save, 1, 4)
    result = ms.move_slot(save, 1, 4, processes=Processes(), now=NOW, expected=plan.signature())
    after = everything(save)
    assert result.name == "Smith" and result.source == 1 and result.target == 4 and result.set_aside is None
    # The source is empty: none of its files are left, and its own folder is gone.
    assert not any(k.startswith(ROOT1) for k in after)
    for relative in ms.slot_everything(save, 4):
        assert relative.as_posix() in after
    slot1 = [m.source.relative_to(save).as_posix() for m in plan.moves]
    assert not any(k in after for k in slot1)
    # Every file is at its new place with the same bytes, but the slot number in a log header and the tree file.
    for key in slot1:
        new = moved_key(key, 1, 4)
        if key.endswith(".tree") or "/Logs/Family History/" in key:
            continue
        assert after[new] == before[key], key
    logs = f"{ROOT4}/Logs/Family History/"
    assert after[logs + "Family History 1.txt"] == before[f"{ROOT1}/Logs/Family History/Family History 1.txt"] \
        .replace(b"(Save 1)", b"(Save 4)")
    assert after[logs + "Family History 2.txt"].startswith(b"Family: Smith (Save 4)\r\n")
    tree = json.loads(after[f"{ROOT4}/Data/Family Tree/Virtual Families 1 Family Tree - Save 4.tree"])
    assert tree["slot"] == 4 and tree["family"] == "Smith" and tree["members"]["list"][0]["slot"] == 4
    assert f"{ROOT4}/Data/Family Tree/Virtual Families 1 Family Tree Edits - Save 4.json" in after
    assert f"{ROOT4}/Family Tree/Virtual Families 1 Family Tree - Save 4.html" in after
    assert after[f"{ROOT4}/Backups/old.txt"] == b"kept"
    assert {p.name for p in result.updated} == {"Family History 1.txt", "Family History 2.txt",
                                               "Virtual Families 1 Family Tree - Save 4.tree"}
    # The slot menu: Save 4 has the family and its flag; Save 1's flag is cleared; nothing else changed.
    menu = after["Virtual Families0.ldw"]
    assert rf.menu_name(menu, 4) == "Smith" and cs.slot_used(menu, 4) is True and cs.slot_used(menu, 1) is False
    old = before["Virtual Families0.ldw"]
    changed = [i for i in range(len(menu)) if menu[i] != old[i]]
    name_at = rf._menu_name_offset(old, 4)
    assert all(i in (cs._used_offset(old, 1), cs._used_offset(old, 4)) or name_at <= i < name_at + 21 for i in changed)
    slots = {s.slot: s for s in cs.read_slots(save)}
    assert slots[1].empty and slots[4].name == "Smith" and slots[2].name == "Jones"
    # Save 2 and the shared files are untouched; the backup came first and is listed as "before move".
    for key, value in before.items():
        if "Save 2" in key or key.endswith("2.ldw") or key == "ldwLog.txt" or key.endswith("2.ldw.dat"):
            assert after[key] == value, key
    backups = sb.list_backups(save)
    assert len(backups) == 1 and backups[0].before_move and backups[0].label.endswith("(before move)")
    assert backups[0].path.name.endswith(" (before move)")
    assert (backups[0].path / "Virtual Families21.ldw").read_bytes() == before["Virtual Families21.ldw"]   # (slot saves are Paused in a backup)
    assert not list(save.rglob("*.tmp"))


def test_a_move_keeps_every_files_times(save):
    source = save / ROOT1 / "Logs" / "Family History" / "Family History 1.txt"
    os.utime(source, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    ms.move_slot(save, 1, 4, processes=Processes(), now=NOW)
    moved = save / ROOT4 / "Logs" / "Family History" / "Family History 1.txt"
    assert moved.stat().st_mtime_ns == 1_600_000_000_000_000_000


def test_an_occupied_target_is_set_aside_never_deleted(save):
    before = everything(save)
    jones = {k: v for k, v in before.items() if (
        "Save 2" in k or k in ("Virtual Families2.ldw", f"{DATA}/Slot 2.ini", f"{DATA}/Children/Virtual Families2.ldw.dat",
                               f"{DATA}/Outfits/Virtual Families2.ldw.dat"))}
    plan = ms.plan_move(save, 1, 2)
    assert plan.overwritten == "Jones"
    result = ms.move_slot(save, 1, 2, processes=Processes(), now=NOW)
    asides = list((save / "Backups").glob("Replaced by move * - Save 2 - Jones"))
    assert len(asides) == 1 and result.set_aside == asides[0] and result.overwritten == "Jones"
    for key, value in jones.items():                            # every file of Jones, kept with its path
        assert (asides[0] / key).read_bytes() == value, key
    slots = {s.slot: s for s in cs.read_slots(save)}
    assert slots[2].name == "Smith" and slots[1].empty
    assert (save / "Virtual Families2.ldw").read_bytes() == before["Virtual Families1.ldw"]
    log = (save / "Virtual Families 1 Patcher" / "Save 2" / "Logs" / "Family History" / "Family History 1.txt").read_bytes()
    assert log.startswith(b"Family: Smith (Save 2)\r\n[2026-10-01 10:00:00] Birth 1")    # Smith's log, not Jones's


def test_an_empty_targets_leftovers_are_set_aside(save):
    (save / "Virtual Families23.ldw").write_bytes(b"an older copy a deleted family left")
    (save / DATA / "Slot 3.ini").write_text("[Village]\nMaid=1\n")
    plan = ms.plan_move(save, 1, 3)
    assert plan.overwritten is None and {p.as_posix() for p in plan.removals} == {"Virtual Families23.ldw",
                                                                                  f"{DATA}/Slot 3.ini"}
    ms.move_slot(save, 1, 3, processes=Processes(), now=NOW)
    aside = next((save / "Backups").glob("Replaced by move * - Save 3 - *"))
    assert (aside / "Virtual Families23.ldw").read_bytes() == b"an older copy a deleted family left"
    assert (save / "Virtual Families23.ldw").read_bytes() == (save / "Backups").joinpath(
        next(p.name for p in (save / "Backups").iterdir() if p.name.endswith("(before move)")),
        "Virtual Families21.ldw").read_bytes()


@pytest.mark.parametrize("fail_after", [0, 1, 5, 12])
def test_a_failure_part_way_puts_everything_back(save, fail_after):
    before = tree_of(save)
    with pytest.raises(ms.MoveError, match="every file was put back"):
        ms.move_slot(save, 1, 2, processes=Processes(), now=NOW, _fail_after=fail_after)
    assert tree_of(save) == before
    assert [p.name for p in (save / "Backups").iterdir()] == [sb.list_backups(save)[0].path.name]   # no set-aside left


def test_a_failure_writing_the_slot_menu_or_verifying_puts_everything_back(save, monkeypatch):
    before = tree_of(save)
    real = cs._write_atomically

    def refuse_menu(path, data):
        if path.name == "Virtual Families0.ldw":
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(cs, "_write_atomically", refuse_menu)
    with pytest.raises(ms.MoveError, match="every file was put back"):
        ms.move_slot(save, 1, 4, processes=Processes(), now=NOW)
    assert tree_of(save) == before
    monkeypatch.setattr(cs, "_write_atomically", real)

    def bad_verify(plan):
        raise ms.MoveError("checked wrong")

    monkeypatch.setattr(ms, "verify", bad_verify)
    with pytest.raises(ms.MoveError, match="checked wrong"):
        ms.move_slot(save, 1, 2, processes=Processes(), now=NOW)
    assert tree_of(save) == before


def _all_paths(folder: Path) -> tuple[dict[str, bytes], set[str]]:
    """Every file (its bytes) and every folder, the "(before move)" backup left out."""
    def keep(p: Path) -> bool:
        return not any(part.endswith("(before move)") for part in p.relative_to(folder).parts)
    files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file() and keep(p)}
    dirs = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_dir() and keep(p)}
    return files, dirs - {"Backups"}


def _read_only_case(save: Path, which: str) -> Path:
    return {"history": save / ROOT1 / "Logs" / "Family History" / "Family History 2.txt",
            "tree": save / ROOT1 / "Data" / "Family Tree" / "Virtual Families 1 Family Tree - Save 1.tree",
            "menu": save / "Virtual Families0.ldw"}[which]


@pytest.mark.parametrize("which", ["history", "tree", "menu"])
def test_a_read_only_file_the_move_must_rewrite_refuses_before_anything_moves(save, which):
    # The end-to-end check (2026-11-26): a read-only log or .tree was renamed into Save 2, its rewrite failed, and
    # the rollback never renamed it back, so Save 2's own folder could not return (WinError 183).
    path = _read_only_case(save, which)
    os.chmod(path, 0o444)
    try:
        before = _all_paths(save)
        with pytest.raises(ms.MoveError, match="read-only.*Nothing was moved") as caught:
            ms.move_slot(save, 1, 2, processes=Processes(), now=NOW)
        assert path.name in str(caught.value)
        assert _all_paths(save) == before and not (save / "Backups").exists()
    finally:
        os.chmod(path, 0o666)


@pytest.mark.parametrize("which", ["history", "tree", "menu"])
def test_a_read_only_rewrite_failing_mid_move_still_rolls_everything_back(save, which, monkeypatch):
    # Past the check (a file made read-only after it): the file whose rewrite failed still has its own bytes, so
    # the rollback only renames it back, and the target's set-aside folder returns.
    path = _read_only_case(save, which)
    monkeypatch.setattr(ms, "_refuse_read_only", lambda plan, options: None, raising=False)
    os.chmod(path, 0o444)
    try:
        before = _all_paths(save)
        with pytest.raises(ms.MoveError, match="every file was put back") as caught:
            ms.move_slot(save, 1, 2, processes=Processes(), now=NOW)
        assert "could not be put back" not in str(caught.value)
        assert _all_paths(save) == before
        assert not os.access(path, os.W_OK)                          # still read-only, as it was
    finally:
        os.chmod(path, 0o666)


def test_a_running_game_refuses_and_nothing_changes(save):
    before = everything(save)
    with pytest.raises(ms.GameRunning, match="Close the game first"):
        ms.move_slot(save, 1, 4, processes=Processes([4242]), now=NOW)
    assert everything(save) == before and not (save / "Backups").exists()


def test_files_changed_after_confirming_refuse_the_move(save):
    shown = ms.plan_move(save, 1, 4).signature()
    log = save / ROOT1 / "Logs" / "Family History" / "Family History 2.txt"
    log.write_bytes(log.read_bytes() + b"[2026-10-03 10:00:00] Birth 3\r\n  Child: Cy\r\n\r\n")
    before = everything(save)
    with pytest.raises(ms.MoveError, match="changed after you confirmed"):
        ms.move_slot(save, 1, 4, processes=Processes(), now=NOW, expected=shown)
    assert everything(save) == before


def test_refusals(save):
    with pytest.raises(ms.MoveError, match="Choose another slot"):
        ms.plan_move(save, 1, 1)
    with pytest.raises(ms.MoveError, match="has no family"):
        ms.plan_move(save, 3, 4)
    with pytest.raises(ms.MoveError, match="only save slots 1 to 5"):
        ms.plan_move(save, 1, 6)


def test_the_preview_lists_every_file(save):
    plan = ms.plan_move(save, 1, 2)
    lines = plan.preview()
    assert "Virtual Families1.ldw  ->  Virtual Families2.ldw" in lines
    assert any(line.endswith("Family History 1.txt (slot updated inside)") for line in lines)
    assert lines[-1].startswith("Virtual Families0.ldw (the slot menu: Save 2 gets Smith, Save 1 is empty)")
    assert len(lines) == len(plan.moves) + 1
