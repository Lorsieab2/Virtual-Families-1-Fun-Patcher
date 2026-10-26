"""Game Speed: set a family's saved game speed to Paused or Normal, in a closed game's saves.

Everything below was traced in the stock "Virtual Families.exe" 1.01.00 (SHA-256 5db828c3...4487) with capstone;
the modded game's exe has the same bytes for every function named here (the patcher's changes are elsewhere).

Where the speed lives (VERIFIED)
    * theGameState+0x1B180, int, the "speed option": 10 is normal; the game counts it as paused when it is 999
      or more (0x489E3C `cmp [ebx+0x1B180], 0x3E7`, also 0x414DE4, 0x444DDB, 0x4454F1, 0x486F3D). It is inside
      the slot save (the saved range is gs+0x8..gs+0x1B187), so a family stays paused across a reload.
    * CGameTime (global 0x50C5D0), saved at gs+0xDA64 by SaveState 0x4222C0 and put back word for word by
      LoadState 0x4223F0 (called from theGameState::Load at 0x424B53; nothing after it re-derives the speed):
      +0 speed, +4 previous speed, +8 GetSecondsFromGameStart at the last speed change, +0xC game seconds
      banked then, +0x10 GetSecondsFromGameStart when the save was written.
    * Seconds() 0x422320: the multiplier is speed / 10.0 stored as a float (SpeedMultiplier 0x422300). When it is
      0 the clock returns +0xC unchanged; otherwise +0xC + trunc((now - +8) / multiplier), with now < +8 clamped.
    * GetSecondsFromGameStart 0x4036D0 = difftime(now, the header's start time); every stamp above counts from it.

What the game's own Pause and Unpause do (VERIFIED)
    * Options "Pause Game: Yes" 0x41E1CC: theRealtimeManager::UpdateAll; CGameTime::SetSpeed(999) 0x41E1F1;
      gs+0x1B180 += 999 (0x41E1F9, an add); UpdateAll. The Space bar (0x440CF6..0x440D08) does the same without
      the two UpdateAll calls.
    * Options "Pause Game: No" 0x41E21B: UpdateAll; SetSpeed(10) 0x41E23D; gs+0x1B180 = 10 (0x41E245); UpdateAll.
    * SetSpeed 0x422450 (new speed s): nothing when s equals +0x20. Otherwise +0xC = Seconds() (0x422557), +8 = now
      (0x42256B), +4 = the old +0x20 (0x422571), +0x20 = s, EXCEPT that s = 999 stores 0: `xor ebp, ebp` at
      0x42246F feeds the store at 0x422574. So a paused clock holds speed 0 and stops dead. Real saves agree:
      every paused copy holds 1009 at gs+0x1B180 and 0 / 10 in the clock's speed / previous speed.
    * Seconds() at speed 10 divides by exactly 1.0. The x87 precision is the CRT's 53-bit default
      (_controlfp_s(0, _PC_53, _MCW_PC) at 0x49C8A5, called at start-up from 0x497AAE), and the game's SDL2 2.0.3
      creates its Direct3D 9 device with D3DCREATE_FPU_PRESERVE (SDL2.dll 0x100BFC29), so the division is exact:
      Seconds() = +0xC + (now - +8), modulo 2^32 as the game's 32-bit add does.
    * While paused the game keeps running its two-second update (theMainScene 0x444E9A -> UpdateAll 0x424F80 ->
      AllVillagersTimeflowUpkeep 0x489D00). For every villager who is present, at home, alive and has a stamp it
      adds now - stamp to the banked real seconds (0x489DE9), zeroes them because the game is paused (0x489E3C,
      0x489E48) and stamps now (0x489E6B); nobody ages. A dead body is removed once (now - stamp) / 60 / speed
      option reaches 240 (0x489D3A..0x489D8F). Nothing else in the update keeps a saved stamp fresh while paused:
      the other pause checks (0x414CA5, 0x44558F, 0x44564F, 0x4459A2, 0x486F3D, 0x48B85F, 0x493220) only skip work.

What this tool writes, in the slot save "Virtual Families<N>.ldw" only (the game never loads N+20 / N+40)
    * Paused, from Normal (gs+0x1B180 = 10, clock speed 10), as if the player pressed Pause just before the game
      saved (now = the save's own stamp, clock +0x10): clock +0xC = +0xC + (+0x10 - +8), +8 = +0x10, +4 = 10,
      +0 = 0; gs+0x1B180 = 1009. Nothing else: on the next load the clock carries on from the save, LoadState's
      "time away" is 0 (as for any paused save) and nobody ages.
    * Normal, from Paused (gs+0x1B180 >= 999, clock speed 0), as if the player loaded the paused family now, pressed
      Unpause and quit at once (now = this PC's clock, counted from the header's start time like the game counts):
      clock +0xC unchanged (a stopped clock), +8 = now, +4 = 0, +0 = 10, +0x10 = now; gs+0x1B180 = 10 (Options
      "No" stores 10); and for each villager the paused update would have touched (present, at home, alive, with a
      stamp) banked real seconds 0 and stamp = now. So the time the family spent paused is never aged in: only the
      time after this change counts, as with any family the game saved at normal speed. Refused when a dead body
      would have been removed in that time (the game does more there than this tool may write), and when this
      PC's clock is earlier than the save.
    Nothing else changes: not the header, not the options file. Any other combination (another speed, or a speed
    option and a clock that disagree) is shown with its raw values and refused.

The patcher's own Time Controls speeds, and why they are not offered here (VERIFIED)
    Source native/vf1fun (features.inc, pages.inc); bytes checked in the v1.1 build of vf1fun.dll (SHA-256
    BF294E09...3401), image base 0x10000000.
    * The page's buttons store the wanted speed in a DLL global (0x10034048) and call the game's SetSpeed 0x422450
      and store the same value in gs+0x1B180: Slow 20 (0x10008B4C), Normal 10 (0x10008B02), Fast 5 (0x10008B6F),
      5x 2 (0x10008B92), 10x 1 (0x10008BB5). Pause is the Space bar's (SetSpeed(999), += 999, 0x10008A5F..0x10008A73),
      so the speed to come back to rides along as option - 999; Resume (0x10008AC3..0x10008AE3) restores it (10
      when it is 0). The 15-second helper tick re-applies a wanted speed other than 10 while unpaused.
    * SetSpeed for these speeds is the same as for 10 (stock 0x4224A4..0x422574; the timer loop counted by 0x50C5C8
      never runs, that count is zero-initialised and never written): +0xC = Seconds(), +8 = now, +4 = old, +0x20 =
      the speed. Seconds() then counts (now - +8) / (speed / 10.0): Slow half speed, Fast 2x, 5x and 10x.
    * The time-flow upkeep (0x489E08) caps a villager's banked real seconds at 0x9538 for option 5, 0x5CF8 for 20 and
      0x7918 for 10 and for every other value (2 and 1 included), always setting 0x7918 when over; ageing ticks are
      banked / 60 / option (0x489E86), and a dead body goes once (now - stamp) / 60 / option reaches 240 (0x489D59).
    * NONE OF THEM IS EVER SAVED. theGameState::Save is wrapped (vtable slot 7, 0x10003CA0): any option other than
      10 or 1009 is written as 10 (running, after SetSpeed(10)) or 1009 (paused), and the live speed is put back
      after the save (0x10003CCE..0x10003D4A). Load (slot 6, 0x10003B80) turns any such value into 10 with
      SetSpeed(10), or 1009 when paused (0x10003BB2..0x10003BFC), before the closed-game catch-up. Since v0.3.0
      (commit 1f96b1b, live-tested then: a family saved at 10x had aged 26 years on load); v0.2.0 still saved them.
    So no installed game can produce a Time Controls speed in a save, and one written there would be turned back to
    Normal at the next load: this tool offers only Paused and Normal. A save left at one by v0.2.0 is named in words
    and refused (loading it in the game brings it back at Normal). A paused save holding 999 + a Time Controls speed
    is Paused: the patched game loads it as 1009, so Normal is what its unpause gives.

Safety
    * The game must be closed: it saves by itself every 10 minutes and when it quits, which would put the old
      speed straight back. Nothing here ever closes or pauses a game.
    * Before anything is written the whole save folder is backed up with Back Up Saves' own copier, labelled
      "(before speed change)".
    * The save is written beside itself and swapped in with os.replace, then read back and checked field by field
      (and every other byte unchanged); any failure puts it back exactly as it was. No log and no data file is written.

Nothing here touches Tk; the GUI runs it on a worker thread, and the tests drive it against a temporary copy of a
save folder with a fake process list and a fixed clock.
"""
from __future__ import annotations

import os
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import vf1_rename_family as rename_family
import vf1_save as save_format
import vf1_save_backup as save_backup

SLOTS = rename_family.SLOTS
BACKUP_LABEL = save_backup.BEFORE_SPEED_CHANGE
NORMAL = 10                 # Options "No" stores 10 (0x41E245); InitOptions 10 (0x423983)
PAUSE_ADD = 999             # Options "Yes" adds 999 (0x41E1F9); paused means >= 999 (0x489E3C)
CLOCK_PAUSED = 0            # SetSpeed(999) stores 0 in CGameTime (0x42246F, 0x422574)
BODY_REMOVED_AT = 240       # age units a dead body stays (0x489D5F cmp eax, 0xF0)
PAUSED = "Paused"
NORMAL_NAME = "Normal"
TARGETS = (PAUSED, NORMAL_NAME)
# The Time Controls page's own names for its speed values (pages.inc; see the module notes). Never offered.
TIME_CONTROLS_SPEEDS = {20: "Slow", 5: "Fast", 2: "5x", 1: "10x"}
CLOCK_SIZE = 0x14
_U32 = 0xFFFFFFFF
# Villager record (gs+0xE790 + k * 0x6B8), the fields AllVillagersTimeflowUpkeep 0x489D00 reads and writes.
REC_PRESENT = 0x0           # villager+0x13574 ([esi-4])
REC_LEFT_HOME = 0x1         # villager+0x13578 ([esi])
REC_BANKED = 0xA8           # CVillagerState+0 ([esi-0x10AA4]), real seconds toward the next age unit
REC_STAMP = 0xAC            # CVillagerState+4 ([esi-0x10AA0]), GetSecondsFromGameStart of the last pass
REC_HEALTH = 0xB4           # CVillagerState+0xC ([esi-0x10A98])


class SpeedError(Exception):
    """A speed change that was refused or failed, with a reason a player can read."""


class GameRunning(SpeedError):
    """The game that uses this save folder is running."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeedState:
    option: int                 # gs+0x1B180
    clock_speed: int            # CGameTime +0x20 (saved +0)
    clock_previous: int         # +0x24 (saved +4)
    changed_at: int             # +0x28 (saved +8), GetSecondsFromGameStart
    banked: int                 # +0x2C (saved +0xC), game seconds
    saved_at: int               # saved +0x10, GetSecondsFromGameStart

    @property
    def kind(self) -> str:
        """"paused", "normal" or "other"."""
        if self.option >= PAUSE_ADD and self.clock_speed == CLOCK_PAUSED:
            return "paused"
        if self.option == NORMAL and self.clock_speed == NORMAL:
            return "normal"
        return "other"

    @property
    def label(self) -> str:
        if self.kind == "paused":
            return PAUSED
        if self.kind == "normal":
            return NORMAL_NAME
        if self.time_controls:
            return f"{TIME_CONTROLS_SPEEDS[self.option]} (a Time Controls speed)"
        return f"other (speed value {self.option}, clock speed {self.clock_speed})"

    @property
    def time_controls(self) -> bool:
        """True for a running save at one of Time Controls' speeds (only the old v0.2.0 patcher saved them)."""
        return self.option in TIME_CONTROLS_SPEEDS and self.clock_speed == self.option


@dataclass(frozen=True)
class _Layout:
    epoch: int                  # the header's start time (time_t)
    clock: int                  # file offset of CGameTime's 0x14 bytes
    option: int                 # file offset of gs+0x1B180
    villagers: int              # file offset of villager record 0


def _layout(data: bytes) -> _Layout | None:
    try:
        header = save_format.parse_header(data)
    except save_format.SaveFormatError:
        return None
    if header.payload_size != save_format.PAYLOAD_SIZE or len(data) != header.size + save_format.PAYLOAD_SIZE:
        return None
    base = header.size - save_format.GS_BASE
    return _Layout(header.epoch, base + save_format.GS_GAME_TIME, base + save_format.GS_SPEED,
                   base + save_format.GS_VILLAGERS)


def read_state(data: bytes) -> SpeedState | None:
    """The saved speed of a slot save's bytes, or None if they are not a slot save."""
    at = _layout(data)
    if at is None:
        return None
    speed, previous, changed, banked, saved = struct.unpack_from("<iiIII", data, at.clock)
    return SpeedState(struct.unpack_from("<i", data, at.option)[0], speed, previous, changed, banked, saved)


def seconds_at(state: SpeedState, now: int) -> int:
    """CGameTime::Seconds() 0x422320 at ``now``, for a stopped clock or one at speed 10 only."""
    if state.clock_speed == CLOCK_PAUSED:
        return state.banked
    if state.clock_speed != NORMAL:
        raise SpeedError(f"The clock runs at speed {state.clock_speed}, which this tool does not change.")
    elapsed = (now - state.changed_at) & _U32 if now > state.changed_at else 0
    return (state.banked + elapsed) & _U32       # the multiplier is exactly 1.0 (see the module notes)


def game_seconds_now(data: bytes, unix_now: int) -> int:
    """GetSecondsFromGameStart 0x4036D0 at ``unix_now`` for this save: now minus the header's start time."""
    at = _layout(data)
    if at is None:
        raise SpeedError("This is not a Virtual Families save this tool can read.")
    return unix_now - at.epoch


def _villagers_paused_until(data: bytearray, at: _Layout, option: int, now: int) -> None:
    """What the paused two-second update (0x489D00) leaves in each villager record by ``now``."""
    for k in range(save_format.VILLAGER_SLOTS):
        rec = at.villagers + k * save_format.VILLAGER_RECORD
        if not data[rec + REC_PRESENT] or data[rec + REC_LEFT_HOME]:
            continue
        stamp, = struct.unpack_from("<I", data, rec + REC_STAMP)
        health, = struct.unpack_from("<i", data, rec + REC_HEALTH)
        if health <= 0:
            if ((now - stamp) & _U32) // 60 // option >= BODY_REMOVED_AT:
                raise SpeedError(
                    f"A dead family member (villager slot {k}) would have been taken away during the pause. "
                    "Unpause this family in the game instead (Options, Pause Game: No).")
            continue
        if stamp == 0:
            continue
        struct.pack_into("<II", data, rec + REC_BANKED, 0, now)


def changed_bytes(data: bytes, target: str, unix_now: int | None = None) -> bytes:
    """``data`` with the speed set to ``target`` the way the game's own Pause / Unpause sets it."""
    at = _layout(data)
    state = read_state(data)
    if at is None or state is None:
        raise SpeedError("This is not a Virtual Families save this tool can read.")
    out = bytearray(data)
    if target == PAUSED:
        if state.kind == "paused":
            raise SpeedError("This family is already paused.")
        if state.kind != "normal":
            raise SpeedError(f"This family's speed is {state.label}; only a family at Normal can be paused here.")
        now = state.saved_at
        struct.pack_into("<iiIII", out, at.clock, CLOCK_PAUSED, state.clock_speed, now, seconds_at(state, now),
                         state.saved_at)
        struct.pack_into("<i", out, at.option, state.option + PAUSE_ADD)
    elif target == NORMAL_NAME:
        if state.kind == "normal":
            raise SpeedError("This family is already at Normal speed.")
        if state.kind != "paused":
            raise SpeedError(f"This family's speed is {state.label}; only a paused family can be set to Normal here.")
        now = game_seconds_now(data, int(time.time()) if unix_now is None else unix_now)
        if now < state.saved_at or now > _U32:
            raise SpeedError("This PC's clock is earlier than the family's last save, so its time cannot be "
                             "worked out. Check the date and time in Windows.")
        _villagers_paused_until(out, at, state.option, now)
        struct.pack_into("<iiIII", out, at.clock, NORMAL, state.clock_speed, now, seconds_at(state, now), now)
        struct.pack_into("<i", out, at.option, NORMAL)
    else:
        raise SpeedError(f"{target!r} is not a speed this tool sets.")
    return bytes(out)


def _changeable_ranges(at: _Layout) -> list[tuple[int, int]]:
    """The byte ranges a speed change may write: the clock, the speed option and each record's banked/stamp."""
    ranges = [(at.clock, at.clock + CLOCK_SIZE), (at.option, at.option + 4)]
    for k in range(save_format.VILLAGER_SLOTS):
        rec = at.villagers + k * save_format.VILLAGER_RECORD
        ranges.append((rec + REC_BANKED, rec + REC_STAMP + 4))
    return ranges


def only_speed_fields_differ(before: bytes, after: bytes) -> bool:
    """True when ``after`` equals ``before`` outside the fields a speed change may write."""
    at = _layout(before)
    if at is None or len(before) != len(after):
        return False
    allowed = bytearray(len(before))
    for start, end in _changeable_ranges(at):
        allowed[start:end] = b"\1" * (end - start)
    return all(a == b or allowed[i] for i, (a, b) in enumerate(zip(before, after)))


@dataclass
class SlotSpeed:
    slot: int
    name: str | None            # the family name in the slot's save, or None
    state: SpeedState | None
    problem: str | None = None  # why its speed cannot be changed, if it cannot

    @property
    def label(self) -> str:
        if self.state is None:
            return f"Save {self.slot}: (empty)" if self.problem == "This slot has no family." else \
                f"Save {self.slot}: (a save this tool cannot read)"
        return f"Save {self.slot}: {self.name or '(no name)'} - {self.state.label}"


def read_slots(folder: Path) -> list[SlotSpeed]:
    """Each slot's family name and saved speed."""
    slots: list[SlotSpeed] = []
    for slot in SLOTS:
        path = rename_family.save_path(folder, slot)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            slots.append(SlotSpeed(slot, None, None, "This slot has no family."))
            continue
        except OSError as exc:
            slots.append(SlotSpeed(slot, None, None, f"The save could not be read: {exc}"))
            continue
        state = read_state(data)
        if state is None:
            slots.append(SlotSpeed(slot, None, None, f"{path.name} is not a Virtual Families save this tool can read."))
            continue
        info = SlotSpeed(slot, rename_family.save_name(data), state)
        if state.time_controls:
            info.problem = (f"Its speed is {state.label}, from an older patcher. Time Controls speeds are never kept "
                            "in a save: load this family in the game and it comes back at Normal.")
        elif state.kind == "other":
            info.problem = (f"Its speed is {state.label}, which this tool does not change. Change it in the game "
                            "(Options, Pause Game).")
        slots.append(info)
    return slots


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _write_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` through a temporary file, then verify."""
    temporary = path.with_name(f"{path.name}.speed-{uuid.uuid4().hex[:12]}.tmp")   # a leftover never blocks the next one
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    if path.read_bytes() != data:
        raise SpeedError(f"{path.name} did not read back as written.")


@dataclass
class SpeedResult:
    folder: Path
    slot: int
    before: str
    after: str
    backup: save_backup.BackupResult
    changed: Path


def _refuse_if_running(folder: Path, processes: save_backup.ProcessController) -> None:
    exe = save_backup.game_exe_name(folder)
    try:
        running = processes.find(exe)
    except (OSError, save_backup.BackupError) as exc:
        raise SpeedError(f"Could not check whether {exe} is running, so nothing was changed ({exc}).") from exc
    if running:
        raise GameRunning(
            f"{exe} is running. Close the game first (quit it normally from its menu): it saves by itself "
            "every 10 minutes and when it quits, which would put the old speed back. Nothing was changed."
        )


def set_speed(
    folder: Path,
    slot: int,
    target: str,
    processes: save_backup.ProcessController | None = None,
    now: datetime | None = None,
    unix_now: int | None = None,
) -> SpeedResult:
    """Set the saved speed of the family in ``slot`` of ``folder`` to ``target`` (Paused or Normal).

    Refused (SpeedError, nothing changed) when the game is running or the save cannot be changed. Otherwise the
    folder is backed up first, the save is replaced atomically and read back, and any failure puts it back.
    ``now`` names the backup; ``unix_now`` is the clock an unpause counts from (this PC's clock by default).
    """
    if slot not in SLOTS:
        raise SpeedError(f"There is no save slot {slot}.")
    if target not in TARGETS:
        raise SpeedError(f"{target!r} is not a speed this tool sets.")
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    when = now or datetime.now()
    _refuse_if_running(folder, controller)
    path = rename_family.save_path(folder, slot)
    try:
        original = path.read_bytes()
    except FileNotFoundError as exc:
        raise SpeedError(f"Save {slot} has no family ({path.name} is missing).") from exc
    except OSError as exc:
        raise SpeedError(f"Could not read {path.name}: {exc}") from exc
    updated = changed_bytes(original, target, unix_now)
    before = read_state(original)
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise SpeedError(f"The backup before the speed change failed, so nothing was changed. {exc}") from exc
    _refuse_if_running(folder, controller)        # the backup took a moment
    written = False
    try:
        if path.read_bytes() != original:
            raise SpeedError(f"{path.name} changed while its speed was being set.")
        written = True
        _write_atomically(path, updated)
        data = path.read_bytes()
        state = read_state(data)
        if data != updated or state is None or state.label != target \
                or not only_speed_fields_differ(original, data):
            raise SpeedError(f"{path.name} does not hold the new speed.")
    except (OSError, SpeedError) as exc:
        problem = None
        if written:
            try:
                if path.read_bytes() != original:
                    _write_atomically(path, original)
            except (OSError, SpeedError) as undo:
                problem = str(undo)
        if problem:
            raise SpeedError(
                f"The speed change failed ({exc}) and {path.name} could not be put back ({problem}). "
                f"Your backup is in {backup.backup_folder}."
            ) from exc
        raise SpeedError(
            f"The speed change failed ({exc}); the save was put back as it was. A backup is in {backup.backup_folder}."
        ) from exc
    return SpeedResult(folder, slot, before.label if before else "?", target, backup, path)
