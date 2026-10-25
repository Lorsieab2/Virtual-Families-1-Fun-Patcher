"""Check Saves for Virtual Families 1 (the Tools tab), with a small, careful repair.

Ported from the Virtual Villagers Fun Patcher's Check Saves & Logs idea, cut down to what Virtual Families 1
itself has: it reads ONLY the save (and the game's two older copies of it, "Virtual Families<N+20>.ldw" and
"<N+40>.ldw") through patcher/vf1_save.py and the fields docs/vf1-save-format.md marks VERIFIED. It reads no
log. It writes no log and no data file: the only thing it can ever write is the save itself, after the
player agreed to one repair, with Back Up Saves' own backup made first.

CHECK (`check`) lists, in plain words, each finding with a verdict:

    OK         agrees with the game's own rules
    WRONG      impossible or contradictory (the game's own code can never produce it)
    NOTE       unusual, but not proof of an error
    UNCHECKED  nothing to check it against

What is checked
    Villagers   health 0..100; a living villager's death cause is -1 (CVillagerState::SetHealth 0x48F820 and
                AdjustHealth 0x48F860 clamp health to 100 and store cause -1 whenever health stays above 0, 0x48F83C..0x48F848,
                0x48F8BC..0x48F8C9); the six 1..100 values, fertility 1..100 and "Wants kids?" 1..99 (the clamp
                of each setter, the addresses are in RANGES below); age below 0; sex 0/1; head and body 0..49;
                a pregnancy that cannot be (no babies, more than 3, a man, conception after the present age); a
                dead body kept longer than the 240 age units the game keeps it (0x489D31..0x489D64).
    Family tree generations that link (a generation's heir is the child it names in the generation before,
                StartNextGeneration 0x481B30), leading used records only (LoadState 0x481580), child count
                0..6, sex 0/1, the current family's people pointing at the right villager (FindPeepRecord
                0x4817B0), nobody in two places, a living villager's mother appearing in the tree.
    Babies      the unborn babies' slots (gs+0x1B120) point at real, not-yet-born villagers.
    Older saves the same checks on slots N+20 and N+40.

REPAIR (`apply`) fixes ONLY a value the game's own rules decide with certainty: a number outside its clamp
goes to the clamp the game itself would have applied (the address is shown with each repair), and a living
villager's death cause goes to -1. Everything else (an age below 0, a head outside the sprite sheet, a tree
link, a dead body kept too long, a pregnancy that cannot be) is reported and never changed, because the
right value is not certain. Each repair is shown with its evidence and asked first ("Don't know" leaves it);
the game must be closed; the save folder is backed up first ("Backup <date> (before repair)", in Restore
Saves' list); the file is written beside itself and swapped in, read back and checked, and put back exactly
as it was if anything fails. The older copies are never written.

Nothing here touches Tk.
"""
from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import vf1_rename_family as rename
import vf1_save as vs
import vf1_save_backup as save_backup

SLOTS = rename.SLOTS
VERDICTS = ("OK", "WRONG", "NOTE", "UNCHECKED")
DONT_KNOW = "Don't know (leave it)"
BACKUP_LABEL = save_backup.BEFORE_REPAIR
STATE = 0xA8                         # CVillagerState inside a villager record
BODY_KEPT_UNITS = 240                # age units a dead body stays (0x489D5F cmp eax, 0xF0)

# (field, offset in the CVillagerState, lowest, highest, where the game clamps it)
RANGES = (
    ("stat 1", 0x34, 1, 100, "0x48F8EB and 0x48F8FA"),
    ("stat 2", 0x38, 1, 100, "0x48F96B and 0x48F97A"),
    ("stat 3 (can be negative)", 0x3C, -500, 500, "0x48F9CE and 0x48F9DF"),
    ("stat 4", 0x40, 1, 100, "0x48FA2B and 0x48FA3A"),
    ("stat 5", 0x44, 1, 100, "0x48FACB and 0x48FADA"),
    ("stat 6", 0x48, 1, 100, "0x48FB2B and 0x48FB3A"),
    ("fertility", 0x4C, 1, 100, "0x48FB8B and 0x48FB9A"),
    ("Wants kids?", 0x50, 1, 99, "0x48FBEB and 0x48FBFA"),
)
HEALTH_AT = 0xC
CAUSE_AT = 0x10
HEALTH_CITE = "0x48F820..0x48F84F (SetHealth) and 0x48F860..0x48F8D1 (AdjustHealth)"


class CheckError(Exception):
    """Nothing was done; the message says why."""


class GameRunning(CheckError):
    """The game that uses this save folder is running."""


@dataclass
class Fix:
    path: Path
    offset: int
    old: bytes
    new: bytes


@dataclass
class Repair:
    key: str                          # stable between a check and the repair, e.g. "v3:health"
    title: str
    evidence: tuple[str, ...]
    fixes: list[Fix]


@dataclass
class Finding:
    section: str
    verdict: str
    text: str
    repair: Repair | None = None


SECTIONS = ("The save", "Villagers", "Family tree", "Babies on the way", "Older saves")


@dataclass
class CheckResult:
    folder: Path
    slot: int
    family: str | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def repairs(self) -> list[Repair]:
        return [f.repair for f in self.findings if f.repair is not None]

    def count(self, verdict: str) -> int:
        return sum(1 for f in self.findings if f.verdict == verdict)

    def text(self) -> str:
        lines = [f"Check Saves: Save {self.slot}" + (f", {self.family}" if self.family else "")]
        for section in SECTIONS:
            rows = [f for f in self.findings if f.section == section]
            if rows:
                lines += ["", section]
                lines += [f"  {f.verdict:<9} {f.text}" for f in rows]
        return "\n".join(lines)


def _who(v: vs.Villager) -> str:
    return f"{v.name or '(no name)'} (slot {v.slot})"


def _file_offset(save: vs.VF1Save, v: vs.Villager, record_offset: int) -> int:
    return save.header.size + vs.GS_VILLAGERS - vs.GS_BASE + v.slot * vs.VILLAGER_RECORD + record_offset


def _state_value(v: vs.Villager, at: int) -> int:
    return struct.unpack_from("<i", v.raw, STATE + at)[0]


def _fix(path: Path, save: vs.VF1Save, v: vs.Villager, at: int, new: int) -> Fix:
    return Fix(path, _file_offset(save, v, STATE + at), struct.pack("<i", _state_value(v, at)), struct.pack("<i", new))


# ---------------------------------------------------------------------------
# The checks on one save
# ---------------------------------------------------------------------------


def _in_play(save: vs.VF1Save) -> list[vs.Villager]:
    """Villagers the game uses: present, or an unborn baby named by gs+0x1B120."""
    slots = {s for s in save.pending_babies if 0 <= s < vs.VILLAGER_SLOTS}
    return [v for v in save.villagers if v.present or v.slot in slots]


def _check_villagers(save: vs.VF1Save, path: Path, repairable: bool, out: list[Finding]) -> None:
    section = "Villagers"
    start = len(out)

    def add(verdict: str, text: str, repair: Repair | None = None) -> None:
        out.append(Finding(section, verdict, text, repair if repairable else None))

    people = _in_play(save)
    for v in people:
        who = _who(v)
        health_fixes: list[Fix] = []
        health = v.health
        final = min(100, max(0, health))
        if health != final:
            health_fixes.append(_fix(path, save, v, HEALTH_AT, final))
        if final > 0 and v.death_cause != -1:
            health_fixes.append(_fix(path, save, v, CAUSE_AT, -1))
        if health_fixes:
            reasons = []
            if health != final:
                reasons.append(f"health is {health}, but the game keeps health from 0 to 100")
            if final > 0 and v.death_cause != -1:
                reasons.append(f"is alive but has a cause of death ({v.death_cause}); a living villager's is -1")
            add("WRONG", f"{who}: " + "; ".join(reasons) + ".", Repair(
                f"v{v.slot}:health", f"{who}: health {health}, cause of death {v.death_cause}",
                (f"The game clamps health to 0..100 and stores -1 as the cause whenever health stays above 0 ({HEALTH_CITE}).",
                 f"Health {health} would become {final}" + (", cause of death -1." if final > 0 else ".")),
                health_fixes))
        for name, at, low, high, cite in RANGES:
            value = _state_value(v, at)
            if low <= value <= high:
                continue
            fixed = min(high, max(low, value))
            add("WRONG", f"{who}: {name} is {value}, outside the game's {low} to {high}.", Repair(
                f"v{v.slot}:{at:#x}", f"{who}: {name} {value}",
                (f"Every setter of this value clamps it to {low}..{high} (at {cite}).", f"{value} would become {fixed}."),
                [_fix(path, save, v, at, fixed)]))
        if v.age_units < 0:
            add("WRONG", f"{who}: age is below 0 ({v.age_units}). Ages only count up from 0, but the right age is "
                         "not known, so it is not repaired.")
        if v.sex not in (0, 1):
            add("WRONG", f"{who}: sex is {v.sex}; the game uses only 0 (male) and 1 (female). Not repaired.")
        if not 0 <= v.head <= 49 or not 0 <= v.body <= 49:
            add("WRONG", f"{who}: look (head {v.head}, body {v.body}) is outside the game's 0 to 49. The right "
                         "look is not known, so it is not repaired.")
        if v.pregnant:
            if not 1 <= v.babies_carried <= 3:
                add("WRONG", f"{who}: pregnant, but carrying {v.babies_carried} babies (the game uses 1 to 3). Not repaired.")
            if v.sex == 0:
                add("WRONG", f"{who}: a man is marked pregnant. Not repaired.")
            if v.pregnant_since > v.age_units:
                add("WRONG", f"{who}: conceived at age {v.pregnant_since} units, which is after the present age "
                             f"{v.age_units}. Not repaired.")
        elif v.babies_carried:
            add("NOTE", f"{who}: not pregnant, but the babies-carried value is {v.babies_carried}.")
        if v.present and v.dead and save.speed < vs.PAUSED_AT and save.speed > 0:
            gone = (save.time.saved_at - v.last_update) // 60 // save.speed
            if gone >= BODY_KEPT_UNITS + 10:
                add("WRONG", f"{who}: died {gone} age units before this save, but the game removes a body after "
                             f"{BODY_KEPT_UNITS} (0x489D31..0x489D64). Not repaired: removing a body also changes "
                             "the family tree.")
    seen: dict[tuple, vs.Villager] = {}
    for v in save.villagers:
        if v.present and v.name:
            key = (v.name, v.sex, v.head, v.body, v.age_units)
            if key in seen:
                add("NOTE", f"{_who(seen[key])} and {_who(v)} are identical in name, sex, look and age.")
            seen.setdefault(key, v)
    if len(out) == start:
        count = sum(1 for v in people if v.present)
        add("OK", f"{count} villager{'s' if count != 1 else ''}: every checked value is inside the game's own ranges.")


def _raw_tree_counts(save: vs.VF1Save) -> list[tuple[int, int, int]]:
    """(record number, used, raw child count) for every one of the 30 records."""
    out = []
    base = vs.GS_FAMILY_TREE - vs.GS_BASE
    for r in range(vs.FAMILY_RECORDS):
        at = base + r * vs.FAMILY_RECORD
        out.append((r + 1, save.payload[at], struct.unpack_from("<i", save.payload, at + 0x1B4)[0]))
    return out


def _check_tree(save: vs.VF1Save, out: list[Finding]) -> None:
    section = "Family tree"
    start = len(out)

    def add(verdict: str, text: str) -> None:
        out.append(Finding(section, verdict, text))

    records = save.family_records
    if not records:
        add("UNCHECKED", "The family tree has no generation to check.")
        return
    raw = _raw_tree_counts(save)
    for number, used, count in raw[len(records):]:
        if used:
            add("WRONG", f"Generation {number} is marked used after an unused one, so the game ignores it "
                         "(CFamilyTree::LoadState 0x481580 stops at the first unused record).")
    for rec in records:
        g = rec.generation
        if not 0 <= rec.child_count <= vs.TREE_CHILDREN:
            add("WRONG", f"Generation {g}: {rec.child_count} children listed (the game keeps 0 to {vs.TREE_CHILDREN}).")
        for who, p in (("first parent", rec.parent1), ("second parent", rec.parent2)):
            if p.used and p.sex not in (0, 1):
                add("WRONG", f"Generation {g}: the {who} {p.name or '(no name)'} has sex {p.sex}.")
        for p in rec.children:
            if p.used and p.sex not in (0, 1):
                add("WRONG", f"Generation {g}: child {p.name or '(no name)'} has sex {p.sex}.")
        if g == 1:
            continue
        before = records[g - 2]
        heir = rec.parent1
        index = heir.parent_child_index
        if index == -1:
            add("NOTE", f"Generation {g}: the first parent {heir.name or '(no name)'} is marked as a founder, with no "
                        f"link to generation {g - 1}.")
        elif not 0 <= index < len(before.children):
            add("WRONG", f"Generation {g}: the first parent {heir.name or '(no name)'} should be child {index + 1} of "
                         f"generation {g - 1}, which has {len(before.children)} children.")
        else:
            child = before.children[index]
            if (child.name, child.sex) != (heir.name, heir.sex):
                add("WRONG", f"Generation {g}: the first parent {heir.name or '(no name)'} does not match child "
                             f"{index + 1} of generation {g - 1}, {child.name or '(no name)'}.")
    current = records[-1]
    used = [p for p in (current.parent1, current.parent2, *current.children) if p.used]
    slots: dict[int, str] = {}
    for p in used:
        if p.slot == -1:
            continue
        if not 0 <= p.slot < vs.VILLAGER_SLOTS:
            add("WRONG", f"Generation {current.generation}: {p.name or '(no name)'} points at villager slot {p.slot}, "
                         f"which does not exist.")
            continue
        if p.slot in slots:
            add("WRONG", f"Generation {current.generation}: {slots[p.slot]} and {p.name or '(no name)'} both point at "
                         f"villager slot {p.slot}.")
        slots[p.slot] = p.name or "(no name)"
        if save.villager_for(p) is None:
            there = save.villagers[p.slot]
            add("WRONG", f"Generation {current.generation}: {p.name or '(no name)'} points at slot {p.slot}, which "
                         f"holds {there.name or 'nobody'}.")
    listed = {(p.name, p.sex, p.head) for p in used}
    mothers = {p.name for rec in records for p in (rec.parent1, rec.parent2) if p.used}
    for v in save.villagers:
        if not (v.present and not v.dead and v.name):
            continue
        if (v.name, v.sex, v.head) not in listed:
            add("NOTE", f"{_who(v)} is not in the current generation of the tree. That is normal for a child past the "
                        "sixth (Up to 28 Children) or someone just arrived.")
        elif v.parent2_name and v.parent2_name not in mothers:
            add("NOTE", f"{_who(v)}: the mother, {v.parent2_name}, is not a parent in any generation of the tree.")
    if len(out) == start:
        add("OK", f"The tree has {len(records)} generation{'s' if len(records) != 1 else ''}, linked, with the "
                  "current family pointing at the right villagers.")


def _check_babies(save: vs.VF1Save, out: list[Finding]) -> None:
    section = "Babies on the way"
    start = len(out)
    named = [s for s in save.pending_babies if s != -1]
    for s in named:
        if not 0 <= s < vs.VILLAGER_SLOTS:
            out.append(Finding(section, "WRONG", f"An unborn baby is in villager slot {s}, which does not exist."))
        elif save.villagers[s].present:
            out.append(Finding(section, "WRONG", f"An unborn baby is in slot {s}, but {_who(save.villagers[s])} is "
                                                  "already in the village."))
    if len(set(named)) != len(named):
        out.append(Finding(section, "WRONG", "Two unborn babies share one villager slot."))
    carried = sum(v.babies_carried for v in save.villagers if v.present and v.pregnant and not v.dead)
    if carried != len(named):
        out.append(Finding(section, "NOTE", f"{carried} baby(ies) are carried but {len(named)} unborn slot(s) are "
                                            "listed."))
    if len(out) == start:
        out.append(Finding(section, "OK", f"{len(named)} unborn baby(ies), matching the mothers."))


def check_save(data: bytes, path: Path, repairable: bool = True) -> tuple[vs.VF1Save | None, list[Finding]]:
    """The findings for one save file's bytes. Repairs are offered only when ``repairable``."""
    out: list[Finding] = []
    try:
        save = vs.parse_save(data)
    except (vs.SaveFormatError, struct.error) as exc:
        out.append(Finding("The save", "UNCHECKED", f"{path.name} could not be read as a village save ({exc})."))
        return None, out
    if save.version not in (0x3F0, vs.SAVE_VERSION):
        out.append(Finding("The save", "NOTE", f"Save version {save.version:#x}; only 0x3F0 and 0x3F8 were seen."))
    if isinstance(save.money, float) and not math.isfinite(save.money):
        out.append(Finding("The save", "WRONG", "The money is not a number. Not repaired."))
    if not out:
        out.append(Finding("The save", "OK", f"{path.name} is a readable village save."))
    _check_villagers(save, path, repairable, out)
    _check_tree(save, out)
    _check_babies(save, out)
    return save, out


def check(folder: Path, slot: int) -> CheckResult:
    """Check slot ``slot`` of ``folder`` and its two older copies. Reads only; writes nothing."""
    if slot not in SLOTS:
        raise CheckError(f"There is no save slot {slot}.")
    path = rename.save_path(folder, slot)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise CheckError(f"Save {slot} has no family ({path.name} is missing).") from exc
    except OSError as exc:
        raise CheckError(f"Could not read {path.name}: {exc}") from exc
    save, findings = check_save(data, path)
    result = CheckResult(folder, slot, save.family_name if save else None, findings)
    for step in rename.GENERATIONS:
        copy = rename.save_path(folder, slot + step)
        try:
            copy_data = copy.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            result.findings.append(Finding("Older saves", "UNCHECKED", f"{copy.name} could not be read: {exc}"))
            continue
        older, rows = check_save(copy_data, copy, repairable=False)
        problems = [r for r in rows if r.verdict in ("WRONG", "UNCHECKED", "NOTE") and r.section != "Family tree"
                    or r.verdict in ("WRONG", "UNCHECKED")]
        if older is None:
            result.findings += [Finding("Older saves", r.verdict, f"{copy.name}: {r.text}") for r in rows]
            continue
        for r in problems:
            result.findings.append(Finding("Older saves", r.verdict, f"{copy.name}: {r.text}"))
        if save is not None and older.generation > save.generation:
            result.findings.append(Finding("Older saves", "NOTE", f"{copy.name} has {older.generation} generations, "
                                           f"more than the save's {save.generation} (a restored backup?)."))
        if not problems:
            result.findings.append(Finding("Older saves", "OK", f"{copy.name}: nothing wrong found."))
    return result


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


@dataclass
class RepairResult:
    folder: Path
    slot: int
    backup: save_backup.BackupResult
    repaired: list[str]
    skipped: list[str]


def _refuse_if_running(folder: Path, processes: save_backup.ProcessController) -> None:
    exe = save_backup.game_exe_name(folder)
    try:
        running = processes.find(exe)
    except (OSError, save_backup.BackupError) as exc:
        raise CheckError(f"Could not check whether {exe} is running, so nothing was changed ({exc}).") from exc
    if running:
        raise GameRunning(f"{exe} is running. Close the game first (quit it normally from its menu): it saves when it "
                          "quits, which would undo the repair. Nothing was changed.")


def _write_atomically(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".repair-tmp")
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
        raise CheckError(f"{path.name} did not read back as written.")


def apply(folder: Path, slot: int, chosen: set[str],
          processes: save_backup.ProcessController | None = None, now: datetime | None = None) -> RepairResult:
    """Repair the ``chosen`` repair keys of ``check(folder, slot)``; every other finding is left alone.

    Refused (CheckError, nothing changed) when nothing is chosen, the game is running, the save is not
    readable, or a chosen repair is no longer needed. Otherwise the folder is backed up first, the save is
    replaced atomically and read back, and any failure puts the save back exactly as it was.
    """
    if slot not in SLOTS:
        raise CheckError(f"There is no save slot {slot}.")
    if not chosen:
        raise CheckError("No repair was chosen, so nothing was changed.")
    controller = processes if processes is not None else save_backup.WindowsProcesses()
    when = now or datetime.now()
    _refuse_if_running(folder, controller)
    path = rename.save_path(folder, slot)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CheckError(f"Could not read {path.name}: {exc}") from exc
    _save, findings = check_save(data, path)
    offered = {f.repair.key: f.repair for f in findings if f.repair is not None}
    missing = sorted(chosen - set(offered))
    if missing:
        raise CheckError("These repairs are not needed any more (the save changed since it was checked): "
                         + ", ".join(missing) + ". Nothing was changed.")
    new = bytearray(data)
    for key in sorted(chosen):
        for fix in offered[key].fixes:
            if bytes(new[fix.offset:fix.offset + len(fix.old)]) != fix.old:
                raise CheckError(f"{path.name} changed while it was being repaired. Nothing was changed.")
            new[fix.offset:fix.offset + len(fix.new)] = fix.new
    try:
        backup = save_backup.copy_save_folder(folder, when, suffix=BACKUP_LABEL)
    except save_backup.BackupError as exc:
        raise CheckError(f"The backup before repairing failed, so nothing was changed. {exc}") from exc
    _refuse_if_running(folder, controller)        # the backup took a moment
    written = False
    try:
        if path.read_bytes() != data:
            raise CheckError(f"{path.name} changed while it was being repaired.")
        written = True
        _write_atomically(path, bytes(new))
        again = check_save(path.read_bytes(), path)[1]
        left = sorted(chosen & {f.repair.key for f in again if f.repair is not None})
        if left:
            raise CheckError("the save still has the problem after the repair: " + ", ".join(left))
        changed = {i for i in range(len(data)) if data[i] != new[i]}
        allowed = {fix.offset + n for key in chosen for fix in offered[key].fixes for n in range(len(fix.new))}
        if not changed <= allowed:
            raise CheckError("the repair changed more than it should")
    except (OSError, CheckError) as exc:
        try:
            if written and path.read_bytes() != data:
                _write_atomically(path, data)
        except (OSError, CheckError) as undo:
            raise CheckError(f"The repair failed ({exc}) and the save could not be put back ({undo}). Your backup "
                             f"is in {backup.backup_folder}.") from exc
        raise CheckError(f"The repair failed ({exc}); the save was put back as it was. A backup is in "
                         f"{backup.backup_folder}.") from exc
    return RepairResult(folder, slot, backup, [offered[k].title for k in sorted(chosen)],
                        [r.title for k, r in offered.items() if k not in chosen])
