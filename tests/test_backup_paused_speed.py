"""Back Up Saves sets the backup's family saves to Paused (ported from the Virtual Villagers Fun Patcher's
tests/test_backup_paused_speed.py): a restored backup must never catch up on the real time since it was made.

Only the copy changes, never the live save. The pause is Game Speed's own (vf1_game_speed), which writes exactly what
the game's Pause writes. Only a family at Normal is paused; every other save is copied byte for byte. Every test
works on the real-save fixtures (tests/fixtures/vf1_saves) rebuilt in tmp_path, with a fake process list.
"""
import json
import os
import struct
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

import make_vf1_save_fixtures as fx
import vf1_game_speed as gs
import vf1_save_backup as sb

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vf1_saves"
PAUSED_SAVE = "generation6_left_home"     # 24-byte header, gs 1009, clock 0 / 10
NORMAL_SAVE = "pregnant_unborn_baby"      # 24-byte header, gs 10, clock 10
LEGACY_NORMAL = "parents_died_old_age"    # 12-byte header, normal
OLD_TIME = 1_600_000_000_000_000_000      # a fixed modification time in ns, kept on every copy


class NoGames:
    def find(self, exe_name):
        return []


def fixture(name: str) -> bytes:
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


def at_speed(option: int, clock: int) -> bytes:
    """A Normal fixture with its speed option and clock speed set to other values."""
    data = bytearray(fixture(NORMAL_SAVE))
    at = gs._layout(bytes(data))
    struct.pack_into("<i", data, at.option, option)
    struct.pack_into("<i", data, at.clock, clock)
    return bytes(data)


@pytest.fixture
def folder(tmp_path):
    save = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    save.mkdir(parents=True)
    (save / "Virtual Families1.ldw").write_bytes(fixture(NORMAL_SAVE))
    (save / "Virtual Families2.ldw").write_bytes(fixture(LEGACY_NORMAL))
    (save / "Virtual Families3.ldw").write_bytes(fixture(PAUSED_SAVE))            # already paused
    (save / "Virtual Families4.ldw").write_bytes(at_speed(5, 5))                  # a Time Controls speed
    (save / "Virtual Families5.ldw").write_bytes(b"ldwg not a save")              # unreadable
    (save / "Virtual Families21.ldw").write_bytes(fixture(NORMAL_SAVE))           # an older autosave copy
    (save / "Virtual Families0.ldw").write_bytes(b"options")
    data = save / sb.PATCHER_DATA_FOLDER / "Slot 1.ini"
    data.parent.mkdir()
    data.write_text("children", encoding="utf-8")
    for path in save.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(OLD_TIME, OLD_TIME))
    return save


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER not in p.relative_to(folder).parts}


def test_pausing_is_game_speeds_own_pause():
    for name in (NORMAL_SAVE, LEGACY_NORMAL):
        before = fixture(name)
        after = sb.pause_save_bytes(before)
        assert after == gs.changed_bytes(before, gs.PAUSED)
        assert gs.read_state(after).label == "Paused"
        assert gs.only_speed_fields_differ(before, after)


def test_only_a_family_at_normal_is_paused():
    assert sb.pause_save_bytes(fixture(PAUSED_SAVE)) is None
    for data in (at_speed(5, 5), at_speed(20, 20), at_speed(10, 0), b"ldwg not a save", b""):
        with pytest.raises(sb.NotPaused):
            sb.pause_save_bytes(data)


def test_a_backup_holds_paused_saves_and_the_originals_are_untouched(folder):
    originals = tree(folder)
    made = sb.copy_save_folder(folder, datetime(2026, 10, 26, 12, 0, 0))
    assert tree(folder) == originals                                   # the live save folder never changes
    copy = made.backup_folder
    for slot in (1, 2):
        assert gs.read_state((copy / f"Virtual Families{slot}.ldw").read_bytes()).label == "Paused"
    for name in ("Virtual Families3.ldw", "Virtual Families4.ldw", "Virtual Families5.ldw",
                 "Virtual Families21.ldw", "Virtual Families0.ldw", f"{sb.PATCHER_DATA_FOLDER}/Slot 1.ini"):
        assert (copy / name).read_bytes() == originals[name], name     # left byte for byte
    assert sorted(made.paused_slots) == ["Virtual Families1.ldw", "Virtual Families2.ldw"]
    assert [name for name, _why in made.not_paused] == ["Virtual Families4.ldw", "Virtual Families5.ldw"]
    recorded = {f.relative.as_posix(): f for f in made.files}
    for name in ("Virtual Families1.ldw", "Virtual Families2.ldw"):
        assert (recorded[name].size, recorded[name].sha256) == sb._hash_file(copy / name)
        assert (copy / name).stat().st_mtime_ns == OLD_TIME             # the copy keeps the save's time
    assert sb.list_backups(folder)[0].slots == [1, 2, 3, 4, 5]
    assert list(folder.rglob("*.vf1-pause-tmp")) == []


def test_the_live_save_is_untouched_by_back_up_saves(folder):
    originals = tree(folder)
    made = sb.back_up_save_folder(folder, NoGames(), datetime(2026, 10, 26, 12, 0, 0))
    assert tree(folder) == originals
    assert gs.read_state((folder / "Virtual Families1.ldw").read_bytes()).label == "Normal"
    assert gs.read_state((made.backup_folder / "Virtual Families1.ldw").read_bytes()).label == "Paused"


def test_a_backup_with_no_family_saves_is_an_exact_copy(tmp_path):
    save = tmp_path / "Virtual Families - Modded"
    save.mkdir()
    (save / "Virtual Families0.ldw").write_bytes(b"options")
    (save / "ldwLog.txt").write_text("log", encoding="utf-8")
    made = sb.copy_save_folder(save, datetime(2026, 10, 26, 12, 0, 0))
    assert made.paused_slots == [] and made.not_paused == []
    assert tree(made.backup_folder) == tree(save)


def test_a_restore_restores_paused_and_a_failed_one_puts_back_every_byte(folder):
    made = sb.copy_save_folder(folder, datetime(2026, 10, 26, 12, 0, 0))
    # Played on since: both families changed (still at Normal).
    for slot in (1, 2):
        path = folder / f"Virtual Families{slot}.ldw"
        path.write_bytes(path.read_bytes()[:-1] + bytes([slot]))
    now = tree(folder)

    real_place = sb._place
    calls = []

    def failing(source, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_place(source, target)

    with mock.patch.object(sb, "_place", side_effect=failing):
        with pytest.raises(sb.BackupError, match="Every file was put back as it was"):
            sb.restore_backup(folder, made.backup_folder, None, NoGames(), datetime(2026, 10, 26, 13, 0, 0))
    assert tree(folder) == now                                         # exactly as before, not paused

    sb.restore_backup(folder, made.backup_folder, None, NoGames(), datetime(2026, 10, 26, 14, 0, 0))
    assert gs.read_state((folder / "Virtual Families1.ldw").read_bytes()).label == "Paused"
    assert gs.read_state((folder / "Virtual Families2.ldw").read_bytes()).label == "Paused"
    assert (folder / "Virtual Families4.ldw").read_bytes() == at_speed(5, 5)     # other speeds left alone


def test_a_one_slot_restore_brings_back_a_paused_family(folder):
    made = sb.copy_save_folder(folder, datetime(2026, 10, 26, 12, 0, 0))
    (folder / "Virtual Families1.ldw").write_bytes(fixture(LEGACY_NORMAL))
    result = sb.restore_backup(folder, made.backup_folder, 1, NoGames(), datetime(2026, 10, 26, 13, 0, 0))
    assert gs.read_state((folder / "Virtual Families1.ldw").read_bytes()).label == "Paused"
    assert gs.read_state((folder / "Virtual Families2.ldw").read_bytes()).label == "Normal"   # other slots untouched
    # The before-restore backup holds the family as it was, paused.
    before = result.before_restore.backup_folder / "Virtual Families1.ldw"
    assert before.read_bytes() == gs.changed_bytes(fixture(LEGACY_NORMAL), gs.PAUSED)
