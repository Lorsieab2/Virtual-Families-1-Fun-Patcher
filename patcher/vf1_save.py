"""Read-only parser for Virtual Families 1 save files ("Virtual Families<N>.ldw").

Every offset here was traced in the vanilla game's own save writer and loader (Virtual Families.exe
1.01.00, SHA-256 5db828c3...4487) and checked against real saves; docs/vf1-save-format.md gives the
evidence for each field and marks what is UNCONFIRMED. Nothing here writes a file.

Layout in one paragraph: the file is a header (24 bytes, or 12 bytes in older saves) followed by
0x1B180 bytes that are a straight copy of theGameState from its offset +8 (theGameState::Save 0x423790
gathers every manager's SaveState into theGameState, then ldwGameState::Save 0x403930 writes
`theGameState+8`; theGameState::Load 0x424A50 memcpys the same bytes back to `+8`). So a field at
theGameState offset G is at file offset `header_size + G - 8`. All offsets below are theGameState
offsets ("gs+").
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAGIC = b"ldwg"
PAYLOAD_SIZE = 0x1B180            # bytes saved from theGameState+8 (0x4238BC push 0x1B180)
HEADER_SIZE = 24                  # 'ldwg' header written from 0x4E9228 (0x4039C6 push 0x18)
LEGACY_HEADER_SIZE = 12           # the older header ldwGameState::Load accepts (0x40387B push 0xC)
OPTIONS_SIZE = 0x88               # slot 0: 0x88 bytes from theGameState+0x1B188 (0x4237A7)
SAVE_VERSION = 0x3F8              # theGameState+0x1B148, set before every save (0x4238C4)

GS_BASE = 8                       # file payload starts at theGameState+8

# Section offsets inside theGameState (the lea before each SaveState call in 0x423790).
GS_ACHIEVEMENTS = 0x298           # CAchievement::SaveState 0x412C50: 101 x 12 bytes
GS_COLLECTABLES = 0x754           # CCollectableItem::SaveState 0x413A40
GS_DAILY_EMAIL = 0xE08            # CDailyEmail::SaveState 0x415DD0
GS_FAMILY_TREE = 0xEBC            # CFamilyTree::SaveState 0x481680: 30 records x 0x6C8 (no counter)
GS_FOOD = 0xDA2C                  # CFoodStore::SaveState 0x4221A0: int food
GS_STATS = 0xDA30                 # CGameStats::SaveState 0x422230: 13 dwords
GS_GAME_TIME = 0xDA64             # CGameTime::SaveState 0x4222C0: 5 dwords
GS_INVENTORY = 0xDA78             # CInventoryManager::SaveState 0x496820
GS_MONEY = 0xDBB8                 # CMoney::SaveState 0x422680: float money, uint next interest
GS_TECH = 0xDBC0                  # CTech::SaveState 0x422930
GS_TOOL_TRAY = 0xDBCC             # CToolTray::SaveState 0x496EE0
GS_TUTORIAL = 0xDC0C              # CTutorialTip::SaveState 0x44E0E0
GS_PETS = 0xE1F0                  # CPetManager::SaveState 0x4342D0
GS_VILLAGERS = 0xE790             # CVillagerManager::SaveState 0x489AC0: 30 records x 0x6B8

# theGameState's own fields inside the saved range (see the document for the evidence of each).
GS_PENDING_BABIES = 0x1B120       # 3 ints: villager slots of unborn babies, -1 = none (Init 0x42434A)
GS_FAMILY_NAME = 0x1B12C          # char[0x1C]: the name typed at a new game (0x41C72B GetText(.., 0x14))
GS_VERSION = 0x1B148
GS_BABY_COOLDOWN = 0x1B150        # game seconds; Marry sets 1 (0x4382CF)
GS_NEXT_PROPOSAL = 0x1B154        # CGameTime seconds of the next marriage proposal, 0 = none
GS_PROPOSAL_COUNT = 0x1B158       # proposals opened so far (0x445015 += 1)
GS_SPEED = 0x1B180                # 10 = normal; >= 999 = paused (Pause adds 999)
GS_REVERSE_DAY = 0x1B184          # byte, Reverse Day/Night
GS_SAVED_END = GS_BASE + PAYLOAD_SIZE   # 0x1B188: the current-slot field and beyond are NOT in a slot file

VILLAGER_SLOTS = 30
VILLAGER_RECORD = 0x6B8
FAMILY_RECORDS = 30
FAMILY_RECORD = 0x6C8
PEEP_RECORD = 0xD8
TREE_CHILDREN = 6

AGE_UNITS_PER_YEAR = 20           # displayed age = units / 20 (0x4384A0 imul 0x66666667; sar edx,3)
NORMAL_SPEED = 10
PAUSED_AT = 999

# Death causes: CVillagerState::SetHealth 0x48F820 stores the caller's cause when health <= 0. Only
# 2 (the old-age roll, 0x48C068 push 2) and -1 / 0 / 1 (AdjustHealth callers) were seen passed; the
# names are the order of the string ids 0x507..0x50C, the code mapping a cause to its text was not found.
DEATH_CAUSES_UNCONFIRMED = {-1: "Unknown causes", 0: "Disease", 1: "Starvation", 2: "Old age",
                            3: "Work accident", 4: "Act of Nature"}


class SaveFormatError(ValueError):
    pass


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1")


@dataclass
class Header:
    size: int                     # 24 or 12
    magic: bytes
    word4: int                    # 24-byte header +4 (copied to 0x4E922C); UNCONFIRMED meaning
    epoch: int                    # time_t the game's "seconds from game start" clock counts from
    payload_size: int
    word20: int | None            # 24-byte header +0x14 (copied to 0x4E923C); UNCONFIRMED meaning

    def real_time(self, stamp: int) -> datetime:
        """A GetSecondsFromGameStart stamp (villager timers, CGameTime save stamp ...) as UTC."""
        return datetime.fromtimestamp(self.epoch + stamp, tz=timezone.utc)


@dataclass
class Villager:
    slot: int                     # record index 0..29 = the villager's slot (+0x13538 is not saved)
    present: bool                 # +0  (villager +0x13574; 0 for a ghost)
    left_home: bool               # +1  (+0x13578, SetLeftHome 0x4857F0)
    left_home_at: int             # +4  CGameTime::Seconds when the villager left home
    age_units: int                # bio +0 (twentieths of a year)
    sex: int                      # bio +4: 0 male, 1 female
    name_index: int               # bio +8
    voice: int                    # bio +0xC
    name: str                     # bio +0x10
    head: int                     # bio +0x2C (sprite-sheet row)
    body: int                     # bio +0x30
    parent1_name: str             # bio +0x34 ("Joey" for every natural birth)
    parent2_name: str             # bio +0x4E (the mother for a natural birth)
    parent1_head: int             # bio +0x68
    parent1_body: int             # bio +0x6C
    parent2_head: int             # bio +0x70
    parent2_body: int             # bio +0x74
    pending_father_name: str      # bio +0x7C (Impregnate's father argument)
    pending_father_body: int      # bio +0x98
    pending_father_head: int      # bio +0x9C
    age_seconds_bank: int         # state +0: real seconds not yet turned into age
    last_update: int              # state +4: GetSecondsFromGameStart of the last ageing pass
    age_processed: int            # state +8: age units already run through the per-unit update
    health: int                   # state +0xC: <= 0 = dead
    death_cause: int              # state +0x10: -1 while alive
    pregnant_since: int           # state +0x24: age units at conception, 0 = not pregnant
    babies_carried: int           # state +0x28: 1..3 while pregnant
    stats: tuple[int, ...]        # state +0x34..+0x48, six ints (names UNCONFIRMED: see the document)
    fertility: int                # state +0x4C
    wants_children: int           # state +0x50 ("Wants kids?" 1..99)
    career: int                   # skills +0: -1 = none
    career_level: int             # skills +4
    skills_8: int                 # skills +8 (UNCONFIRMED meaning)
    salary: int                   # skills +0xC
    likes: tuple[int, int, int]
    dislikes: tuple[int, int, int]
    raw: bytes = field(repr=False, default=b"")

    @property
    def years(self) -> int:
        return self.age_units // AGE_UNITS_PER_YEAR

    @property
    def dead(self) -> bool:
        return self.health <= 0

    @property
    def pregnant(self) -> bool:
        return self.pregnant_since != 0

    @property
    def at_home(self) -> bool:
        """In the house: present and not left home (GetMatriarch/IsAlive's test, without health)."""
        return self.present and not self.left_home

    @property
    def is_empty(self) -> bool:
        return not self.name and not self.age_units and not self.present


@dataclass
class PeepRecord:
    name: str                     # +0
    used: bool                    # +0x1A
    sex: int                      # +0x1C
    head: int                     # +0x20
    body: int                     # +0x24
    slot: int                     # +0x28: villager slot, -1 = dead/gone (only kept current in the current record)
    parent_child_index: int       # +0x2C: parent 1 only: index in the previous record's children, -1 = founder
                                  # (never written for parent 2 or children: 0)
    career: int                   # +0x30
    likes_text: str               # +0x34
    dislikes_text: str            # +0x5D


@dataclass
class FamilyRecord:
    generation: int               # 1-based record number
    used: bool                    # +0
    parent_died_children_survive: bool   # +1 (0x481780)
    notify_next_generation: bool  # +2 (0x481790)
    parent1: PeepRecord           # +4
    parent2: PeepRecord           # +0xDC
    child_count: int              # +0x1B4
    children: list[PeepRecord]    # +0x1B8, child_count of 6


@dataclass
class GameTime:
    speed: int                    # +0 (CGameTime +0x20)
    previous_speed: int           # +4
    speed_changed_at: int         # +8 GetSecondsFromGameStart of the last speed change
    banked_seconds: int           # +0xC game seconds banked at that change
    saved_at: int                 # +0x10 GetSecondsFromGameStart when the save was written

    def seconds_at_save(self) -> int:
        """CGameTime::Seconds() at the moment of saving (0x422320's formula on the saved values)."""
        mult = self.speed / 10.0
        if mult == 0:
            return self.banked_seconds
        return self.banked_seconds + int(max(0, self.saved_at - self.speed_changed_at) / mult)


@dataclass
class GameStats:
    raw: tuple[int, ...]

    @property
    def village_started(self) -> int:     # +0, GetSecondsFromGameStart at CStoryScene::Activate (0x43A7F1)
        return self.raw[0]

    @property
    def babies_born(self) -> int:         # +8, Impregnate adds the babies carried (0x48678D)
        return self.raw[2]

    @property
    def max_population(self) -> int:      # +0x18 (0x424FB6)
        return self.raw[6]

    @property
    def oldest_years(self) -> int:        # +0x20 (0x489F07), years
        return self.raw[8]


@dataclass
class VF1Save:
    header: Header
    payload: bytes = field(repr=False)
    family_name: str
    version: int
    money: float
    next_interest: int
    food: int
    stats: GameStats
    time: GameTime
    pending_babies: tuple[int, int, int]
    baby_cooldown: int
    next_proposal: int
    proposal_count: int
    speed: int
    reverse_day_night: bool
    villagers: list[Villager]
    family_records: list[FamilyRecord]

    # --- derived -------------------------------------------------------
    @property
    def generation(self) -> int:
        """CFamilyTree's counter as LoadState 0x481580 rebuilds it: the number of leading used records."""
        return len(self.family_records)

    @property
    def paused(self) -> bool:
        return self.speed >= PAUSED_AT

    @property
    def current_family(self) -> FamilyRecord | None:
        return self.family_records[-1] if self.family_records else None

    def household(self) -> list[Villager]:
        """Villagers in the game: present (alive, dead body not yet removed, or left home). Not present:
        empty slots, unborn babies, discarded candidates and next-generation clones, removed dead."""
        return [v for v in self.villagers if v.present]

    def unborn(self) -> list[Villager]:
        return [self.villagers[s] for s in self.pending_babies if 0 <= s < VILLAGER_SLOTS]

    def villager_for(self, peep: PeepRecord) -> Villager | None:
        """The villager a CURRENT-record entry points at, if the slot still holds that person (the
        game itself matches slot + gender + head, FindPeepRecord 0x4817B0; the name is checked too)."""
        if not peep.used or not 0 <= peep.slot < VILLAGER_SLOTS:
            return None
        v = self.villagers[peep.slot]
        if v.name == peep.name and v.sex == peep.sex and v.head == peep.head:
            return v
        return None

    def couple(self) -> tuple[Villager | None, Villager | None]:
        """The current family's two adults (spouses), as their villagers."""
        rec = self.current_family
        if rec is None:
            return None, None
        return self.villager_for(rec.parent1), self.villager_for(rec.parent2)

    def spouse_of(self, slot: int) -> Villager | None:
        a, b = self.couple()
        if a is not None and a.slot == slot:
            return b
        if b is not None and b.slot == slot:
            return a
        return None


# ---------------------------------------------------------------------------
def parse_header(data: bytes) -> Header:
    if len(data) < LEGACY_HEADER_SIZE or data[:4] != MAGIC:
        raise SaveFormatError("not a Virtual Families save (no 'ldwg' header)")
    # ldwGameState::Load 0x403760 tries the 24-byte header first (size at +0x10), then the 12-byte one
    # (size at +8, a 32-bit epoch at +4).
    if len(data) >= HEADER_SIZE:
        word4, epoch, size, word20 = struct.unpack_from("<IqII", data, 4)
        if size == len(data) - HEADER_SIZE:
            return Header(HEADER_SIZE, data[:4], word4, epoch, size, word20)
    epoch32, size = struct.unpack_from("<II", data, 4)
    if size == len(data) - LEGACY_HEADER_SIZE:
        return Header(LEGACY_HEADER_SIZE, data[:4], epoch32, epoch32, size, None)
    raise SaveFormatError("the header's size does not match the file")


class _View:
    def __init__(self, payload: bytes):
        self.p = payload

    def at(self, gs: int, n: int) -> bytes:
        o = gs - GS_BASE
        return self.p[o:o + n]

    def i32(self, gs: int, count: int = 1):
        v = struct.unpack_from(f"<{count}i", self.p, gs - GS_BASE)
        return v[0] if count == 1 else v

    def u32(self, gs: int) -> int:
        return struct.unpack_from("<I", self.p, gs - GS_BASE)[0]

    def u8(self, gs: int) -> int:
        return self.p[gs - GS_BASE]

    def text(self, gs: int, n: int) -> str:
        return _cstr(self.at(gs, n))


def parse_villager(rec: bytes, slot: int) -> Villager:
    """One CVillager::SaveState record (0x485640), 0x6B8 bytes."""
    if len(rec) != VILLAGER_RECORD:
        raise SaveFormatError("a villager record is 0x6B8 bytes")
    i = lambda o, n=1: (struct.unpack_from(f"<{n}i", rec, o) if n > 1 else struct.unpack_from("<i", rec, o)[0])
    bio, st, sk = 8, 0xA8, 0x140
    return Villager(
        slot=slot, present=bool(rec[0]), left_home=bool(rec[1]), left_home_at=struct.unpack_from("<I", rec, 4)[0],
        age_units=i(bio), sex=i(bio + 4), name_index=i(bio + 8), voice=i(bio + 0xC),
        name=_cstr(rec[bio + 0x10:bio + 0x2C]), head=i(bio + 0x2C), body=i(bio + 0x30),
        parent1_name=_cstr(rec[bio + 0x34:bio + 0x4E]), parent2_name=_cstr(rec[bio + 0x4E:bio + 0x68]),
        parent1_head=i(bio + 0x68), parent1_body=i(bio + 0x6C), parent2_head=i(bio + 0x70), parent2_body=i(bio + 0x74),
        pending_father_name=_cstr(rec[bio + 0x7C:bio + 0x98]), pending_father_body=i(bio + 0x98),
        pending_father_head=i(bio + 0x9C),
        age_seconds_bank=i(st), last_update=struct.unpack_from("<I", rec, st + 4)[0], age_processed=i(st + 8),
        health=i(st + 0xC), death_cause=i(st + 0x10), pregnant_since=i(st + 0x24), babies_carried=i(st + 0x28),
        stats=i(st + 0x34, 6), fertility=i(st + 0x4C), wants_children=i(st + 0x50),
        career=i(sk), career_level=i(sk + 4), skills_8=i(sk + 8), salary=i(sk + 0xC),
        likes=i(0x150, 3), dislikes=i(0x15C, 3), raw=bytes(rec))


def parse_peep(raw: bytes) -> PeepRecord:
    i = lambda o: struct.unpack_from("<i", raw, o)[0]
    return PeepRecord(name=_cstr(raw[0:0x1A]), used=bool(raw[0x1A]), sex=i(0x1C), head=i(0x20), body=i(0x24),
                      slot=i(0x28), parent_child_index=i(0x2C), career=i(0x30),
                      likes_text=_cstr(raw[0x34:0x5D]), dislikes_text=_cstr(raw[0x5D:0x86]))


def parse_family_records(tree: bytes) -> list[FamilyRecord]:
    """CFamilyTree::SaveState's 30 records; only the leading used ones count (LoadState 0x481580)."""
    out = []
    for r in range(FAMILY_RECORDS):
        rec = tree[r * FAMILY_RECORD:(r + 1) * FAMILY_RECORD]
        if not rec[0]:
            break
        count = struct.unpack_from("<i", rec, 0x1B4)[0]
        kids = [parse_peep(rec[0x1B8 + k * PEEP_RECORD:0x1B8 + (k + 1) * PEEP_RECORD])
                for k in range(max(0, min(count, TREE_CHILDREN)))]
        out.append(FamilyRecord(generation=r + 1, used=True, parent_died_children_survive=bool(rec[1]),
                                notify_next_generation=bool(rec[2]), parent1=parse_peep(rec[4:4 + PEEP_RECORD]),
                                parent2=parse_peep(rec[0xDC:0xDC + PEEP_RECORD]), child_count=count, children=kids))
    return out


def parse_save(data: bytes) -> VF1Save:
    header = parse_header(data)
    if header.payload_size != PAYLOAD_SIZE:
        raise SaveFormatError(f"not a village slot (payload 0x{header.payload_size:X}, a slot holds 0x{PAYLOAD_SIZE:X})")
    payload = data[header.size:header.size + PAYLOAD_SIZE]
    v = _View(payload)
    villagers = [parse_villager(v.at(GS_VILLAGERS + k * VILLAGER_RECORD, VILLAGER_RECORD), k)
                 for k in range(VILLAGER_SLOTS)]
    money, interest = struct.unpack_from("<fI", payload, GS_MONEY - GS_BASE)
    return VF1Save(
        header=header, payload=payload, family_name=v.text(GS_FAMILY_NAME, 0x1C), version=v.i32(GS_VERSION),
        money=money, next_interest=interest, food=v.i32(GS_FOOD), stats=GameStats(v.i32(GS_STATS, 13)),
        time=GameTime(*struct.unpack_from("<iiIiI", payload, GS_GAME_TIME - GS_BASE)),
        pending_babies=v.i32(GS_PENDING_BABIES, 3), baby_cooldown=v.u32(GS_BABY_COOLDOWN),
        next_proposal=v.u32(GS_NEXT_PROPOSAL), proposal_count=v.i32(GS_PROPOSAL_COUNT), speed=v.i32(GS_SPEED),
        reverse_day_night=bool(v.u8(GS_REVERSE_DAY)), villagers=villagers,
        family_records=parse_family_records(v.at(GS_FAMILY_TREE, FAMILY_RECORDS * FAMILY_RECORD)))


def read_save(path) -> VF1Save:
    """Parse a save file. The file is only read."""
    return parse_save(Path(path).read_bytes())


def real_seconds_per_age_unit(speed: int = NORMAL_SPEED) -> int:
    """Real seconds per age unit while the game runs: ticks = seconds / 60 / speed (0x489E78..0x489E86).
    Catch-up after time away is capped (see the document), so this is not valid across a long absence."""
    return 60 * speed


# ---------------------------------------------------------------------------
# Which files belong to a save slot (docs/vf1-save-format.md, "Files").
SAVE_PREFIX = "Virtual Families"   # theGameState::GetGameTitle 0x423740 (constant, not the exe name)
_LDW = re.compile(r"^Virtual Families(\d+)\.ldw$", re.IGNORECASE)
_CHILDREN = re.compile(r"^Virtual Families(\d+)\.ldw(?:\.unreadable-\d+)?\.dat$", re.IGNORECASE)
_SLOT_INI = re.compile(r"^Slot (\d)\.ini$", re.IGNORECASE)
PATCHER_DATA = "Virtual Families 1 Patcher Data"


def slot_of_save_number(n: int) -> tuple[int, str] | None:
    """(slot, role) for a "Virtual Families<n>.ldw" number: 0 = the shared options file, 1..5 = the slot,
    21..25 = its first backup, 41..45 = its second backup."""
    if n == 0:
        return 0, "options"
    for base, role in ((0, "save"), (20, "backup 1"), (40, "backup 2")):
        if 1 <= n - base <= 5:
            return n - base, role
    return None


def file_owner(relative) -> tuple[int, str] | None:
    """(slot, role) of a file in the save folder (relative path), slot 0 = shared by every slot;
    None for a file the game and the patcher never write."""
    rel = Path(relative)
    name = rel.name
    parts = [p.casefold() for p in rel.parts[:-1]]
    if not parts:
        m = _LDW.match(name)
        if m:
            return slot_of_save_number(int(m.group(1)))
        if name.casefold() == "ldwlog.txt":
            return 0, "engine log"
        return None
    if parts == [PATCHER_DATA.casefold()]:
        m = _SLOT_INI.match(name)
        if m and 1 <= int(m.group(1)) <= 5:
            return int(m.group(1)), "patcher slot settings"
        return None
    if parts == [PATCHER_DATA.casefold(), "children"]:
        m = _CHILDREN.match(name)
        if m:
            owner = slot_of_save_number(int(m.group(1)))
            if owner and owner[0] >= 1:
                kind = "unreadable children sidecar" if ".unreadable-" in name.lower() else "children sidecar"
                return owner[0], f"{kind} ({owner[1]})"
        return None
    if parts == [PATCHER_DATA.casefold(), "outfits"]:    # vf1fun outfits.inc (Fix Vanilla Game Bugs)
        m = _CHILDREN.match(name)
        if m:
            owner = slot_of_save_number(int(m.group(1)))
            if owner and owner[0] >= 1:
                kind = "unreadable outfits sidecar" if ".unreadable-" in name.lower() else "outfits sidecar"
                return owner[0], f"{kind} ({owner[1]})"
        return None
    return None
