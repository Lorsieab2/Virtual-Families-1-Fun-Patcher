"""Game Speed (patcher/vf1_game_speed.py).

Every test works on copies: the real-save fixtures (tests/fixtures/vf1_saves, rebuilt in tmp_path) or a copy of the
owner's saved copies (only read), with a fake process list and a fixed clock. No real save, game or process is touched.
"""
import json
import shutil
import struct
from datetime import datetime
from pathlib import Path

import pytest

import make_vf1_save_fixtures as fx
import vf1_game_speed as gs
import vf1_save as vs
import vf1_save_backup as sb

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vf1_saves"
SAVECOPIES = Path(r"C:\vf1\savecopies")
NOW = datetime(2026, 10, 25, 9, 0, 0)


class Processes:
    def __init__(self, *answers):
        self.answers = list(answers) or [[]]
        self.calls = 0

    def find(self, exe_name):
        self.calls += 1
        return self.answers[min(self.calls - 1, len(self.answers) - 1)]


def fixture(name: str) -> bytes:
    return fx.rebuild(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


PAUSED_SAVE = "generation6_left_home"     # 24-byte header, gs 1009, clock 0 / 10
NORMAL_SAVE = "pregnant_unborn_baby"      # 24-byte header, gs 10, clock 10
LEGACY_PAUSED = "legacy_header_v3f0"      # 12-byte header, paused
LEGACY_NORMAL = "parents_died_old_age"    # 12-byte header, normal


def unix_after(data: bytes, seconds: int) -> int:
    """A wall-clock time ``seconds`` after the save was written."""
    header = vs.parse_header(data)
    return header.epoch + gs.read_state(data).saved_at + seconds


@pytest.fixture
def folder(tmp_path):
    save = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    save.mkdir(parents=True)
    (save / "Virtual Families1.ldw").write_bytes(fixture(PAUSED_SAVE))
    (save / "Virtual Families2.ldw").write_bytes(fixture(NORMAL_SAVE))
    (save / "Virtual Families21.ldw").write_bytes(fixture(PAUSED_SAVE))
    (save / "Virtual Families0.ldw").write_bytes(b"options")
    return save


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and sb.BACKUPS_FOLDER not in p.relative_to(folder).parts}


# ------------------------------------------------------------------ reading


def test_the_fixtures_read_as_the_game_stores_them():
    assert gs.read_state(fixture(PAUSED_SAVE)).label == "Paused"
    assert gs.read_state(fixture(NORMAL_SAVE)).label == "Normal"
    assert gs.read_state(fixture(LEGACY_PAUSED)).label == "Paused"
    assert gs.read_state(fixture(LEGACY_NORMAL)).label == "Normal"
    assert gs.read_state(b"ldwg nonsense") is None


def test_other_values_are_shown_raw_and_refused(folder):
    data = bytearray(fixture(NORMAL_SAVE))
    at = gs._layout(bytes(data))
    struct.pack_into("<i", data, at.option, 5)                 # a patcher speed
    (folder / "Virtual Families3.ldw").write_bytes(bytes(data))
    info = {s.slot: s for s in gs.read_slots(folder)}
    assert info[3].label.endswith("other (speed value 5, clock speed 10)") and info[3].problem
    assert info[1].label.endswith("- Paused") and info[1].problem is None
    assert info[2].label.endswith("- Normal") and info[2].problem is None
    assert info[4].problem == "This slot has no family."
    with pytest.raises(gs.SpeedError, match="other"):
        gs.changed_bytes(bytes(data), gs.PAUSED)
    struct.pack_into("<i", data, at.option, 10)
    struct.pack_into("<i", data, at.clock, 0)                  # option 10 but a stopped clock
    assert gs.read_state(bytes(data)).kind == "other"


# ------------------------------------------------------------------ the values written


@pytest.mark.parametrize("name", [NORMAL_SAVE, LEGACY_NORMAL])
def test_pause_writes_what_the_games_pause_writes(name):
    data = fixture(name)
    before = gs.read_state(data)
    out = gs.changed_bytes(data, gs.PAUSED)
    after = gs.read_state(out)
    # SetSpeed(999) at the save instant: banks Seconds(), stamps now, previous = 10, speed stored as 0; option += 999.
    assert (after.clock_speed, after.clock_previous, after.option) == (0, 10, 1009)
    assert after.changed_at == before.saved_at == after.saved_at
    assert after.banked == before.banked + (before.saved_at - before.changed_at)
    # The game clock reads the same on both sides of the change, so nothing jumps.
    assert vs.parse_save(out).time.seconds_at_save() == vs.parse_save(data).time.seconds_at_save()
    assert gs.only_speed_fields_differ(data, out)
    changed = [i for i in range(len(data)) if data[i] != out[i]]
    at = gs._layout(data)
    assert all(at.clock <= i < at.clock + 0x14 or at.option <= i < at.option + 4 for i in changed)


@pytest.mark.parametrize("name", [PAUSED_SAVE, LEGACY_PAUSED])
def test_unpause_writes_what_the_games_unpause_writes_now(name):
    data = fixture(name)
    before = gs.read_state(data)
    unix = unix_after(data, 3 * 86400)                        # three days after the save
    out = gs.changed_bytes(data, gs.NORMAL_NAME, unix)
    after = gs.read_state(out)
    now = before.saved_at + 3 * 86400
    assert (after.clock_speed, after.clock_previous, after.option) == (10, 0, 10)
    assert after.banked == before.banked                      # a stopped clock banks nothing
    assert after.changed_at == after.saved_at == now
    save = vs.parse_save(out)
    assert save.time.seconds_at_save() == vs.parse_save(data).time.seconds_at_save()
    at = gs._layout(data)
    for k, v in enumerate(vs.parse_save(data).villagers):
        rec = at.villagers + k * vs.VILLAGER_RECORD
        banked, stamp = struct.unpack_from("<II", out, rec + gs.REC_BANKED)
        old_banked, old_stamp = struct.unpack_from("<II", data, rec + gs.REC_BANKED)
        health, = struct.unpack_from("<i", data, rec + gs.REC_HEALTH)
        touched = data[rec] and not data[rec + 1] and health > 0 and old_stamp
        assert (banked, stamp) == ((0, now) if touched else (old_banked, old_stamp)), k
    assert any(data[at.villagers + k * vs.VILLAGER_RECORD] for k in range(30))
    assert gs.only_speed_fields_differ(data, out)


def test_unpause_refuses_a_clock_before_the_save_and_a_body_that_would_be_removed():
    data = fixture(PAUSED_SAVE)
    with pytest.raises(gs.SpeedError, match="clock is earlier"):
        gs.changed_bytes(data, gs.NORMAL_NAME, unix_after(data, -1))
    bad = bytearray(data)
    at = gs._layout(data)
    rec = at.villagers + 29 * vs.VILLAGER_RECORD
    bad[rec], bad[rec + 1] = 1, 0
    struct.pack_into("<I", bad, rec + gs.REC_STAMP, gs.read_state(data).saved_at)
    struct.pack_into("<i", bad, rec + gs.REC_HEALTH, 0)
    limit = 240 * 60 * 1009                                   # (now - stamp) / 60 / 1009 reaches 240
    gs.changed_bytes(bytes(bad), gs.NORMAL_NAME, unix_after(data, limit - 1))
    with pytest.raises(gs.SpeedError, match="taken away"):
        gs.changed_bytes(bytes(bad), gs.NORMAL_NAME, unix_after(data, limit))


def test_already_there_is_refused():
    with pytest.raises(gs.SpeedError, match="already paused"):
        gs.changed_bytes(fixture(PAUSED_SAVE), gs.PAUSED)
    with pytest.raises(gs.SpeedError, match="already at Normal"):
        gs.changed_bytes(fixture(NORMAL_SAVE), gs.NORMAL_NAME)
    with pytest.raises(gs.SpeedError):
        gs.changed_bytes(fixture(NORMAL_SAVE), "Fast")


def test_seconds_wrap_like_the_games_32_bit_add():
    state = gs.SpeedState(10, 10, 0, 5, 0xFFFFFFF0, 0x20)
    assert gs.seconds_at(state, 0x20) == (0xFFFFFFF0 + 0x1B) & 0xFFFFFFFF
    assert gs.seconds_at(gs.SpeedState(10, 10, 0, 50, 7, 10), 10) == 7    # now before the change: clamped


# ------------------------------------------------------------------ the safe write


def test_set_speed_backs_up_writes_only_the_slot_save_and_reads_it_back(folder):
    before = tree(folder)
    unix = unix_after(before["Virtual Families1.ldw"], 60)
    result = gs.set_speed(folder, 1, gs.NORMAL_NAME, Processes(), NOW, unix)
    after = tree(folder)
    assert result.before == "Paused" and result.after == "Normal"
    assert {k for k in after if after[k] != before.get(k)} == {"Virtual Families1.ldw"}
    assert gs.read_state(after["Virtual Families1.ldw"]).label == "Normal"
    backups = sb.list_backups(folder)
    assert len(backups) == 1 and backups[0].before_speed_change and "(before speed change)" in backups[0].label
    assert (backups[0].path / "Virtual Families1.ldw").read_bytes() == before["Virtual Families1.ldw"]
    assert not list(folder.glob("*.speed-tmp"))
    again = gs.set_speed(folder, 2, gs.PAUSED, Processes(), NOW)
    assert again.after == "Paused" and gs.read_state((folder / "Virtual Families2.ldw").read_bytes()).kind == "paused"


def test_a_running_game_refuses_before_and_after_the_backup(folder):
    before = tree(folder)
    with pytest.raises(gs.GameRunning, match="Close the game first"):
        gs.set_speed(folder, 1, gs.NORMAL_NAME, Processes([1234]), NOW)
    assert tree(folder) == before and not (folder / sb.BACKUPS_FOLDER).exists()
    with pytest.raises(gs.GameRunning):
        gs.set_speed(folder, 1, gs.NORMAL_NAME, Processes([], [1234]), NOW)
    assert tree(folder) == before                            # backed up, then refused: nothing written


def test_a_failed_read_back_puts_the_save_back(folder, monkeypatch):
    before = tree(folder)
    real = gs.read_state
    calls = {"n": 0}

    def flaky(data):
        state = real(data)
        calls["n"] += 1
        return state if calls["n"] < 3 else None            # the read-back after writing fails

    monkeypatch.setattr(gs, "read_state", flaky)
    with pytest.raises(gs.SpeedError, match="put back as it was"):
        gs.set_speed(folder, 2, gs.PAUSED, Processes(), NOW)
    assert tree(folder) == before


def test_an_empty_or_unreadable_slot_is_refused(folder):
    with pytest.raises(gs.SpeedError, match="no family"):
        gs.set_speed(folder, 4, gs.PAUSED, Processes(), NOW)
    (folder / "Virtual Families5.ldw").write_bytes(b"ldwg" + b"\0" * 40)
    with pytest.raises(gs.SpeedError, match="not a Virtual Families save"):
        gs.set_speed(folder, 5, gs.PAUSED, Processes(), NOW)
    with pytest.raises(gs.SpeedError):
        gs.set_speed(folder, 9, gs.PAUSED, Processes(), NOW)


@pytest.mark.skipif(not (SAVECOPIES / "f5" / "Virtual Families1.ldw").is_file(), reason="no saved copies here")
def test_on_a_copy_of_real_saves_both_ways(tmp_path):
    folder = tmp_path / "Virtual Families - Modded"
    shutil.copytree(SAVECOPIES / "f5", folder)
    states = {s.slot: s.state.kind for s in gs.read_slots(folder)}
    assert states[1] == "normal" and states[2] == "paused"
    clock_before = vs.read_save(folder / "Virtual Families1.ldw").time.seconds_at_save()
    gs.set_speed(folder, 1, gs.PAUSED, Processes(), NOW)
    assert vs.read_save(folder / "Virtual Families1.ldw").time.seconds_at_save() == clock_before
    data = (folder / "Virtual Families2.ldw").read_bytes()
    gs.set_speed(folder, 2, gs.NORMAL_NAME, Processes(), NOW, unix_after(data, 3600))
    assert gs.read_state((folder / "Virtual Families2.ldw").read_bytes()).label == "Normal"
