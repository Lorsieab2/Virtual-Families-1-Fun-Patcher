"""Back Up Saves / Restore Saves (patcher/vf1_save_backup.py).

Every test builds its own fake Documents folder in tmp_path and drives the tool with a fake process
controller; no real save, no real game, no running process is ever touched.
"""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import vf1_save_backup as sb

NOW = datetime(2026, 10, 24, 12, 0, 0)


class FakeProcesses:
    """A process controller with no processes, or with some named ones that can refuse to pause."""

    def __init__(self, running=(), refuse=False, resume_fails=False):
        self.running = {name.casefold() for name in running}
        self.refuse = refuse
        self.resume_fails = resume_fails
        self.suspended: list[int] = []
        self.resumed: list[int] = []
        self.started_after: dict[int, str] = {}

    def find(self, exe_name):
        return [100, 101] if exe_name.casefold() in self.running else []

    def suspend(self, pid, exe_name):
        if self.refuse and pid == 101:
            raise sb.PauseRefused(f"{exe_name} (process {pid}) could not be paused")
        self.suspended.append(pid)
        return pid

    def resume(self, handle):
        if self.resume_fails:
            raise sb.BackupError("the game could not be resumed")
        self.resumed.append(handle)


@pytest.fixture
def documents(tmp_path):
    docs = tmp_path / "Documents"
    save = docs / "LDW" / "Virtual Families - Modded"
    (save / sb.PATCHER_DATA_FOLDER / "Children").mkdir(parents=True)
    for slot in (1, 2, 3):
        (save / f"Virtual Families - Modded{slot}.ldw").write_bytes(b"save slot %d " % slot * 50)
    (save / sb.PATCHER_DATA_FOLDER / "Slot 1.ini").write_text("[Slot]\nA=1\n")
    (save / sb.PATCHER_DATA_FOLDER / "Slot 2.ini").write_text("[Slot]\nA=2\n")
    (save / sb.PATCHER_DATA_FOLDER / "Children" / "Virtual Families - Modded1.ldw.dat").write_bytes(b"kids1")
    (save / sb.PATCHER_DATA_FOLDER / "Children" / "Virtual Families - Modded2.ldw.dat").write_bytes(b"kids2")
    (save / "ldwLog.txt").write_text("engine log")
    (save / "ldw.ini").write_text("[Options]\nFullscreen=0\n")
    vanilla = docs / "LDW" / "Virtual Families"
    vanilla.mkdir()
    (vanilla / "Virtual Families1.ldw").write_bytes(b"vanilla save - never listed")
    return docs


@pytest.fixture
def save(documents):
    return documents / "LDW" / "Virtual Families - Modded"


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER not in p.relative_to(folder).parts}


def test_finds_the_modded_save_folder_and_never_the_stock_one(documents):
    found = sb.find_save_folders(documents)
    assert [p.name for p in found] == ["Virtual Families - Modded"]
    assert sb.is_patcher_save_folder("virtual families - modded")
    assert not sb.is_patcher_save_folder("Virtual Families")
    assert sb.find_save_folders(None) == []
    assert sb.find_save_folders(documents / "nowhere") == []


def test_other_modded_folders_and_named_extras_are_listed_the_patchers_own_first(documents):
    ldw = documents / "LDW"
    (ldw / "Virtual Families - Modded copy").mkdir()
    (ldw / "My Renamed Build").mkdir()
    (ldw / "Virtual Families").mkdir(exist_ok=True)
    names = [p.name for p in sb.find_save_folders(documents, ("My Renamed Build", "Virtual Families", "Missing"))]
    assert names == ["Virtual Families - Modded", "My Renamed Build", "Virtual Families - Modded copy"]


def test_documents_folder_is_a_path_or_none_never_a_guess():
    found = sb.documents_folder()
    assert found is None or isinstance(found, Path)


def test_backup_copies_every_file_into_a_dated_folder_and_verifies_it(save):
    before = tree(save)
    result = sb.back_up_save_folder(save, FakeProcesses(), NOW)
    assert result.backup_folder == save / "Backups" / "Backup 2026-10-24 12-00-00"
    assert result.file_count == len(before) == 9
    assert tree(result.backup_folder) == before                       # every file, nested ones too
    assert tree(save) == before                                       # the saves themselves are untouched
    assert result.paused == 0 and result.resume_problems == []
    assert all(len(f.sha256) == 64 for f in result.files)
    for relative in before:                                          # the original's modified time is kept
        assert (result.backup_folder / relative).stat().st_mtime_ns == (save / relative).stat().st_mtime_ns


def test_a_second_backup_never_replaces_or_contains_the_first(save):
    first = sb.back_up_save_folder(save, FakeProcesses(), NOW)
    marker = first.backup_folder / "Virtual Families - Modded1.ldw"
    stamp = marker.stat().st_mtime_ns
    second = sb.back_up_save_folder(save, FakeProcesses(), NOW)         # the very same second
    assert second.backup_folder.name == "Backup 2026-10-24 12-00-00 (2)"
    assert second.file_count == first.file_count                      # Backups itself is not copied
    assert marker.stat().st_mtime_ns == stamp
    assert not (second.backup_folder / "Backups").exists()


def test_a_running_game_is_paused_for_the_copy_and_always_resumed(save):
    processes = FakeProcesses(running=["Virtual Families - Modded.exe"])
    result = sb.back_up_save_folder(save, processes, NOW)
    assert processes.suspended == [100, 101] and processes.resumed == [101, 100]
    assert result.paused == 2 and result.file_count == 9
    assert sb.running_game_count(save, processes) == 2
    assert sb.running_game_count(save, FakeProcesses()) == 0


def test_a_game_that_cannot_be_paused_is_never_copied_while_running(save):
    processes = FakeProcesses(running=["Virtual Families - Modded.exe"], refuse=True)
    with pytest.raises(sb.PauseRefused):
        sb.back_up_save_folder(save, processes, NOW)
    assert processes.resumed == [100]                                  # the one already paused is resumed
    assert not (save / "Backups").exists()


def test_a_failed_resume_is_reported_but_the_backup_stands(save):
    processes = FakeProcesses(running=["Virtual Families - Modded.exe"], resume_fails=True)
    result = sb.back_up_save_folder(save, processes, NOW)
    assert result.file_count == 9 and len(result.resume_problems) == 2


def test_a_copy_that_fails_is_kept_as_incomplete_and_never_offered(save, monkeypatch):
    real = sb._copy_one
    calls = []

    def flaky(source, destination):
        calls.append(source)
        if len(calls) == 4:
            raise sb.BackupError("disk full")
        return real(source, destination)

    monkeypatch.setattr(sb, "_copy_one", flaky)
    with pytest.raises(sb.BackupError, match="NOT a usable backup"):
        sb.back_up_save_folder(save, FakeProcesses(), NOW)
    kept = [p.name for p in (save / "Backups").iterdir()]
    assert kept == ["Backup 2026-10-24 12-00-00 INCOMPLETE"]
    assert sb.list_backups(save) == []


def test_an_empty_or_missing_save_folder_is_refused(tmp_path):
    with pytest.raises(sb.BackupError, match="does not exist"):
        sb.copy_save_folder(tmp_path / "nope")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(sb.BackupError, match="nothing to back up"):
        sb.copy_save_folder(empty)


def test_list_backups_newest_first_with_slots_and_without_unfinished_copies(save):
    sb.back_up_save_folder(save, FakeProcesses(), NOW)
    sb.back_up_save_folder(save, FakeProcesses(), NOW + timedelta(minutes=5))
    (save / "Backups" / "Backup 2026-10-24 13-00-00 INCOMPLETE").mkdir()
    (save / "Backups" / "Backup 2026-10-24 13-00-00 (in progress)").mkdir()
    (save / "Backups" / "notes").mkdir()
    listed = sb.list_backups(save)
    assert [i.label for i in listed] == ["2026-10-24 12:05:00", "2026-10-24 12:00:00"]
    assert listed[0].slots == [1, 2, 3] and listed[0].file_count == 9 and listed[0].size > 0
    assert sb.describe_size(500) == "500 bytes" and sb.describe_size(2048) == "2.0 KB"


def test_files_belong_to_slots_by_name(save):
    slot = lambda name: sb.file_slot(Path(name))
    assert slot("Virtual Families - Modded3.ldw") == 3
    assert slot("Virtual Families1.ldw") == 1
    assert slot("Virtual Families 1 Patcher Data/Slot 2.ini") == 2
    assert slot("Virtual Families 1 Patcher Data/Children/Virtual Families - Modded2.ldw.dat") == 2
    assert slot("ldwLog.txt") == "engine log"
    assert slot("ldw.ini") == "unknown"


def damage(save):
    (save / "Virtual Families - Modded1.ldw").write_bytes(b"damaged")
    (save / "Virtual Families - Modded2.ldw").unlink()
    (save / sb.PATCHER_DATA_FOLDER / "Slot 1.ini").write_text("[Slot]\nA=99\n")
    (save / "Virtual Families - Modded4.ldw").write_bytes(b"a slot made after the backup")


def test_whole_folder_restore_confirms_by_plan_backs_up_first_and_matches_the_backup(save):
    original = tree(save)
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    damage(save)
    damaged = tree(save)
    plan = sb.plan_restore(save, backup)
    assert sorted(p.name for p in plan.replace) == ["Slot 1.ini", "Virtual Families - Modded1.ldw"]
    assert [p.name for p in plan.add] == ["Virtual Families - Modded2.ldw"]
    assert [p.name for p in plan.remove] == ["Virtual Families - Modded4.ldw"]
    assert plan.changes == 4 and tree(save) == damaged                 # planning changes nothing
    result = sb.restore_backup(save, backup, None, FakeProcesses(), NOW + timedelta(hours=1))
    assert tree(save) == original
    assert result.before_restore.backup_folder.name == "Backup 2026-10-24 13-00-00 (before restore)"
    assert tree(result.before_restore.backup_folder) == damaged         # what it replaced is kept
    assert not list(save.rglob("*.tmp"))
    assert [i.before_restore for i in sb.list_backups(save)] == [True, False]
    assert tree(backup) == original                                    # the backup itself is never changed


def test_restoring_one_slot_leaves_the_other_slots_alone(save):
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    damage(save)
    (save / "Virtual Families - Modded3.ldw").write_bytes(b"slot 3 played on since")
    plan = sb.plan_restore(save, backup, 1)
    assert sorted(p.name for p in plan.replace) == ["Slot 1.ini", "Virtual Families - Modded1.ldw"]
    assert plan.add == [] and plan.remove == []
    sb.restore_backup(save, backup, 1, FakeProcesses(), NOW + timedelta(hours=1))
    assert (save / "Virtual Families - Modded1.ldw").read_bytes() == b"save slot 1 " * 50
    assert (save / "Virtual Families - Modded3.ldw").read_bytes() == b"slot 3 played on since"
    assert (save / "Virtual Families - Modded4.ldw").exists()
    assert not (save / "Virtual Families - Modded2.ldw").exists()       # slot 2 was not asked for


def test_a_slot_restore_is_refused_when_a_file_naming_no_slot_differs(save):
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    (save / "ldw.ini").write_text("[Options]\nFullscreen=1\n")
    with pytest.raises(sb.RestoreRefused, match="whole save folder"):
        sb.plan_restore(save, backup, 1)
    assert sb.plan_restore(save, backup, None).changes == 1             # the whole folder can be restored
    (save / "ldw.ini").write_text("[Options]\nFullscreen=0\n")
    with pytest.raises(sb.RestoreRefused, match="nothing for Save 9"):
        sb.plan_restore(save, backup, 9)


def test_restore_is_refused_while_the_game_runs_and_changes_nothing(save):
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    damage(save)
    damaged = tree(save)
    with pytest.raises(sb.RestoreRefused, match="is running"):
        sb.restore_backup(save, backup, None, FakeProcesses(running=["Virtual Families - Modded.exe"]), NOW)
    assert tree(save) == damaged
    assert len(sb.list_backups(save)) == 1                               # no safety copy was started either


def test_a_matching_save_has_nothing_to_restore_and_makes_no_safety_copy(save):
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    result = sb.restore_backup(save, backup, None, FakeProcesses(), NOW)
    assert result.plan.changes == 0 and result.before_restore is None
    assert len(sb.list_backups(save)) == 1


def test_a_restore_that_fails_part_way_puts_every_file_back(save, monkeypatch):
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    damage(save)
    damaged = tree(save)
    real = sb._place
    placed = []

    def failing(source, target):
        placed.append(target)
        if len(placed) == 3 and source.is_relative_to(backup):
            raise sb.BackupError("simulated failure")
        return real(source, target)

    monkeypatch.setattr(sb, "_place", failing)
    with pytest.raises(sb.BackupError, match="Every file was put back"):
        sb.restore_backup(save, backup, None, FakeProcesses(), NOW + timedelta(hours=1))
    assert tree(save) == damaged
    assert not list(save.rglob("*.tmp"))


def test_only_this_tools_own_backups_can_be_restored_or_deleted(save, tmp_path):
    sb.back_up_save_folder(save, FakeProcesses(), NOW)
    stranger = tmp_path / "Backup 2026-10-24 12-00-00"
    stranger.mkdir()
    (stranger / "Virtual Families - Modded1.ldw").write_bytes(b"x")
    for bad in (stranger, save / "Backups", save):
        with pytest.raises(sb.RestoreRefused):
            sb.plan_restore(save, bad)
        with pytest.raises(sb.RestoreRefused):
            sb.delete_backup(save, bad)
    assert stranger.exists()


def test_delete_backup_removes_only_that_backup_even_read_only(save):
    first = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    second = sb.back_up_save_folder(save, FakeProcesses(), NOW + timedelta(minutes=1)).backup_folder
    (first / "Virtual Families - Modded1.ldw").chmod(0o444)
    sb.delete_backup(save, first)
    assert not first.exists()
    assert [i.path for i in sb.list_backups(save)] == [second]
    assert not [p for p in (save / "Backups").iterdir() if p.name.endswith(sb.DELETING)]
    assert len(tree(save)) == 9                                        # the live saves are untouched


def _slot_folder(tmp_path):
    save = tmp_path / "LDW" / "Virtual Families - Modded"
    (save / sb.PATCHER_DATA_FOLDER / "Children").mkdir(parents=True)
    for n in (0, 1, 2, 21, 41, 22, 20, 40):
        (save / f"Virtual Families{n}.ldw").write_bytes(b"old %d" % n)
    kids = save / sb.PATCHER_DATA_FOLDER / "Children"
    for name in ("Virtual Families1.ldw.dat", "Virtual Families21.ldw.dat", "Virtual Families41.ldw.dat",
                 "Virtual Families1.ldw.unreadable-2.dat", "Virtual Families2.ldw.dat"):
        (kids / name).write_bytes(b"old " + name.encode())
    for n in (1, 2):
        (save / sb.PATCHER_DATA_FOLDER / f"Slot {n}.ini").write_text(f"old {n}")
    (save / "ldwLog.txt").write_text("old log")
    return save


def test_slot_files_include_the_two_older_autosave_copies_and_all_sidecars():
    slot = lambda name: sb.file_slot(Path(name))
    for name in ("Virtual Families1.ldw", "Virtual Families21.ldw", "Virtual Families41.ldw",
                 "Virtual Families 1 Patcher Data/Children/Virtual Families41.ldw.dat",
                 "Virtual Families 1 Patcher Data/Children/Virtual Families21.ldw.unreadable-3.dat",
                 "Virtual Families 1 Patcher Data/Slot 1.ini"):
        assert slot(name) == 1, name
    assert slot("Virtual Families45.ldw") == 5 and slot("Virtual Families25.ldw") == 5
    for name in ("Virtual Families0.ldw", "Virtual Families20.ldw", "Virtual Families40.ldw",
                 "Virtual Families0.ldw.dat"):
        assert slot(name) == sb.SHARED, name
    assert slot("Virtual Families6.ldw") == "unknown" and slot("Virtual Families46.ldw") == "unknown"


def test_a_one_slot_restore_takes_exactly_that_slots_files_and_never_the_shared_ones(tmp_path):
    save = _slot_folder(tmp_path)
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    for p in save.rglob("*"):
        if p.is_file() and "Backups" not in p.parts:
            p.write_bytes(b"new")
    plan = sb.plan_restore(save, backup, 1)
    assert sorted(p.name for p in plan.replace) == sorted([
        "Virtual Families1.ldw", "Virtual Families21.ldw", "Virtual Families41.ldw",
        "Virtual Families1.ldw.dat", "Virtual Families21.ldw.dat", "Virtual Families41.ldw.dat",
        "Virtual Families1.ldw.unreadable-2.dat", "Slot 1.ini"])
    sb.restore_backup(save, backup, 1, FakeProcesses(), NOW + timedelta(hours=1))
    for n in (1, 21, 41):
        assert (save / f"Virtual Families{n}.ldw").read_bytes() == b"old %d" % n
    for n in (0, 2, 20, 22, 40):
        assert (save / f"Virtual Families{n}.ldw").read_bytes() == b"new", n
    assert (save / "ldwLog.txt").read_text() == "new"
    assert (save / sb.PATCHER_DATA_FOLDER / "Slot 2.ini").read_text() == "new"
    assert (save / sb.PATCHER_DATA_FOLDER / "Children" / "Virtual Families2.ldw.dat").read_bytes() == b"new"


def test_the_whole_folder_restore_still_restores_the_shared_files(tmp_path):
    save = _slot_folder(tmp_path)
    backup = sb.back_up_save_folder(save, FakeProcesses(), NOW).backup_folder
    (save / "Virtual Families0.ldw").write_bytes(b"new")
    (save / "ldwLog.txt").write_text("new")
    sb.restore_backup(save, backup, None, FakeProcesses(), NOW + timedelta(hours=1))
    assert (save / "Virtual Families0.ldw").read_bytes() == b"old 0"
    assert (save / "ldwLog.txt").read_text() == "old log"


def test_backup_lists_only_real_slots(tmp_path):
    save = _slot_folder(tmp_path)
    sb.back_up_save_folder(save, FakeProcesses(), NOW)
    assert sb.list_backups(save)[0].slots == [1, 2]
