"""patcher/vf1_save.py: the read-only VF1 save reader (docs/vf1-save-format.md).

Three kinds of evidence:
* synthetic saves built here from the documented format (both header forms, every parsed field);
* the game's own save writer and loader code (CVillager::SaveState 0x485640, CFamilyTree::SaveState
  0x481680 / LoadState 0x481580) run in unicorn on the REAL vanilla executable, so the reader is checked
  against what the game writes (skips without VF1_VANILLA_DIR / VF1_VANILLA_EXE);
* real saves copied from the owner's folders, kept as fixtures by tools/make_vf1_save_fixtures.py
  (tests/fixtures/vf1_saves/*.json: the parsed ranges only, no paths; save files are never committed), with
  values read independently and checked against the game's rules.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

import make_vf1_save_fixtures as fx
import vf1_save as vs

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vf1_saves"
EPOCH = 1619932492


# ---------------------------------------------------------------- a synthetic save writer (the format, by hand)
def villager_record(**f) -> bytes:
    rec = bytearray(vs.VILLAGER_RECORD)
    rec[0] = f.get("present", 1)
    rec[1] = f.get("left", 0)
    struct.pack_into("<I", rec, 4, f.get("left_at", 0))
    bio = 8
    struct.pack_into("<iiii", rec, bio, f.get("age", 0), f.get("sex", 0), f.get("name_index", 7), f.get("voice", 3))
    name = f.get("name", "").encode("latin-1")
    rec[bio + 0x10:bio + 0x10 + len(name)] = name
    struct.pack_into("<ii", rec, bio + 0x2C, f.get("head", 0), f.get("body", 0))
    for off, key in ((0x34, "p1"), (0x4E, "p2"), (0x7C, "father")):
        s = f.get(key, "").encode("latin-1")
        rec[bio + off:bio + off + len(s)] = s
    struct.pack_into("<4i", rec, bio + 0x68, 11, 12, 13, 14)
    struct.pack_into("<ii", rec, bio + 0x98, 15, 16)
    st = 0xA8
    struct.pack_into("<iIiii", rec, st, 5, f.get("stamp", 1000), f.get("age", 0), f.get("health", 90), f.get("cause", -1))
    struct.pack_into("<ii", rec, st + 0x24, f.get("preg", 0), f.get("babies", 0))
    struct.pack_into("<6iii", rec, st + 0x34, 1, 2, 3, 4, 5, 6, f.get("fertility", 50), f.get("wants", 40))
    struct.pack_into("<4i", rec, 0x140, f.get("career", -1), f.get("level", -1), 10, f.get("salary", 0))
    struct.pack_into("<6i", rec, 0x150, 1, 2, 3, 4, 5, 6)
    return bytes(rec)


def peep(name="", used=1, sex=0, head=0, body=0, slot=-1, index=0, career=-1, likes="", dislikes="") -> bytes:
    p = bytearray(vs.PEEP_RECORD)
    p[0:len(name)] = name.encode()
    p[0x1A] = used
    struct.pack_into("<6i", p, 0x1C, sex, head, body, slot, index, career)
    p[0x34:0x34 + len(likes)] = likes.encode()
    p[0x5D:0x5D + len(dislikes)] = dislikes.encode()
    return bytes(p)


def family_record(p1: bytes, p2: bytes, kids: list[bytes], died=0, notify=0) -> bytes:
    r = bytearray(vs.FAMILY_RECORD)
    r[0], r[1], r[2] = 1, died, notify
    r[4:4 + vs.PEEP_RECORD] = p1
    r[0xDC:0xDC + vs.PEEP_RECORD] = p2
    struct.pack_into("<i", r, 0x1B4, len(kids))
    for k, kid in enumerate(kids):
        r[0x1B8 + k * vs.PEEP_RECORD:0x1B8 + (k + 1) * vs.PEEP_RECORD] = kid
    return bytes(r)


def build_save(villagers: dict[int, bytes], records: list[bytes], legacy=False, **gs) -> bytes:
    payload = bytearray(vs.PAYLOAD_SIZE)

    def put(off, fmt, *v):
        struct.pack_into(fmt, payload, off - vs.GS_BASE, *v)

    for slot, rec in villagers.items():
        o = vs.GS_VILLAGERS + slot * vs.VILLAGER_RECORD - vs.GS_BASE
        payload[o:o + vs.VILLAGER_RECORD] = rec
    for k, rec in enumerate(records):
        o = vs.GS_FAMILY_TREE + k * vs.FAMILY_RECORD - vs.GS_BASE
        payload[o:o + vs.FAMILY_RECORD] = rec
    name = gs.get("family", "Testfamily").encode()
    payload[vs.GS_FAMILY_NAME - 8:vs.GS_FAMILY_NAME - 8 + len(name)] = name
    put(vs.GS_VERSION, "<i", gs.get("version", vs.SAVE_VERSION))
    put(vs.GS_PENDING_BABIES, "<3i", *gs.get("pending", (-1, -1, -1)))
    put(vs.GS_MONEY, "<fI", gs.get("money", 123.5), 777)
    put(vs.GS_FOOD, "<i", gs.get("food", 88))
    put(vs.GS_STATS, "<13i", 500, 99, 4, 0, 0, 0, 6, 0, 61, 0, 0, 0, 0)
    put(vs.GS_GAME_TIME, "<iiIiI", gs.get("speed", 10), 10, 2000, 50000, 2600)
    put(vs.GS_BABY_COOLDOWN, "<I", 11)
    put(vs.GS_NEXT_PROPOSAL, "<I", 12)
    put(vs.GS_PROPOSAL_COUNT, "<i", 3)
    put(vs.GS_SPEED, "<i", gs.get("speed", 10))
    payload[vs.GS_REVERSE_DAY - 8] = gs.get("reverse", 0)
    if legacy:
        return b"ldwg" + struct.pack("<II", EPOCH, vs.PAYLOAD_SIZE) + bytes(payload)
    return b"ldwg" + struct.pack("<IqII", EPOCH, EPOCH, vs.PAYLOAD_SIZE, 0) + bytes(payload)


def sample(legacy=False) -> bytes:
    villagers = {
        0: villager_record(name="Rosella", sex=1, age=542, head=43, body=3, career=66, level=0, salary=20,
                           preg=541, babies=1, father="Joey", fertility=91, wants=77),
        1: villager_record(name="Kikino", sex=0, age=482, head=12, body=19, career=22),
        2: villager_record(name="Bohi", present=0, age=40, head=27, body=26, p1="Joey", p2="Rosella"),
        3: villager_record(name="Gone", present=1, left=1, left_at=4321, age=385, p1="Joey", p2="Rosella"),
        4: villager_record(name="Oldie", present=0, age=1290, health=0, cause=2),
    }
    records = [family_record(peep("Rosella", sex=1, head=43, body=3, slot=0, index=-1, career=66),
                             peep("Kikino", sex=0, head=12, body=19, slot=1, career=22, likes=" shaving"),
                             [peep("Bohi", head=27, body=26, slot=2), peep("Gone", slot=3)])]
    return build_save(villagers, records, legacy=legacy, pending=(2, -1, -1))


# ---------------------------------------------------------------- synthetic
@pytest.mark.parametrize("legacy", [False, True])
def test_synthetic_save_parses_every_field(legacy):
    s = vs.parse_save(sample(legacy))
    assert s.header.size == (12 if legacy else 24) and s.header.epoch == EPOCH
    assert s.family_name == "Testfamily" and s.version == 0x3F8
    assert s.money == 123.5 and s.next_interest == 777 and s.food == 88
    assert s.stats.village_started == 500 and s.stats.babies_born == 4
    assert s.stats.max_population == 6 and s.stats.oldest_years == 61
    assert (s.baby_cooldown, s.next_proposal, s.proposal_count, s.speed) == (11, 12, 3, 10)
    assert not s.paused and not s.reverse_day_night
    assert s.time.seconds_at_save() == 50000 + 600
    assert s.header.real_time(1000).timestamp() == EPOCH + 1000

    r = s.villagers[0]
    assert (r.name, r.sex, r.age_units, r.years, r.head, r.body) == ("Rosella", 1, 542, 27, 43, 3)
    assert r.pregnant and r.pregnant_since == 541 and r.babies_carried == 1 and r.pending_father_name == "Joey"
    assert (r.pending_father_body, r.pending_father_head) == (15, 16)
    assert (r.career, r.career_level, r.skills_8, r.salary) == (66, 0, 10, 20)
    assert (r.fertility, r.wants_children, r.stats) == (91, 77, (1, 2, 3, 4, 5, 6))
    assert (r.health, r.death_cause, r.last_update, r.age_processed, r.age_seconds_bank) == (90, -1, 1000, 542, 5)
    assert (r.name_index, r.voice, r.likes, r.dislikes) == (7, 3, (1, 2, 3), (4, 5, 6))
    assert (r.parent1_head, r.parent1_body, r.parent2_head, r.parent2_body) == (11, 12, 13, 14)

    baby = s.villagers[2]
    assert not baby.present and (baby.parent1_name, baby.parent2_name) == ("Joey", "Rosella")
    assert [u.name for u in s.unborn()] == ["Bohi"]
    gone = s.villagers[3]
    assert gone.left_home and gone.left_home_at == 4321 and gone.present and not gone.at_home
    dead = s.villagers[4]
    assert dead.dead and dead.death_cause == 2 and not dead.present
    assert [v.name for v in s.household()] == ["Rosella", "Kikino", "Gone"]
    assert s.villagers[5].is_empty

    assert s.generation == 1
    rec = s.current_family
    assert rec.parent1.name == "Rosella" and rec.parent1.parent_child_index == -1 and rec.parent1.career == 66
    assert rec.parent2.likes_text == " shaving" and rec.child_count == 2
    assert [c.name for c in rec.children] == ["Bohi", "Gone"]
    a, b = s.couple()
    assert (a.name, b.name) == ("Rosella", "Kikino")
    assert s.spouse_of(0).name == "Kikino" and s.spouse_of(1).name == "Rosella" and s.spouse_of(2) is None


def test_generation_is_the_number_of_leading_used_records():
    p = peep("A", slot=0)
    recs = [family_record(p, p, []), family_record(p, p, []), bytes(vs.FAMILY_RECORD), family_record(p, p, [])]
    s = vs.parse_save(build_save({}, recs))
    assert s.generation == 2  # LoadState stops at the first unused record


def test_a_reused_slot_is_not_the_spouse():
    villagers = {0: villager_record(name="Stranger", sex=1, head=5), 1: villager_record(name="Kikino", head=12)}
    rec = family_record(peep("Rosella", sex=1, head=43, slot=0), peep("Kikino", head=12, slot=1), [])
    a, b = vs.parse_save(build_save(villagers, [rec])).couple()
    assert a is None and b.name == "Kikino"


def test_paused_speed_and_child_count_capped():
    kids = [peep(f"K{i}", slot=i) for i in range(6)]
    rec = bytearray(family_record(peep("A"), peep("B"), kids))
    struct.pack_into("<i", rec, 0x1B4, 9)  # a damaged count never reads past the six child records
    s = vs.parse_save(build_save({}, [bytes(rec)], speed=1009))
    assert s.paused and len(s.current_family.children) == 6 and s.current_family.child_count == 9


@pytest.mark.parametrize("data, message", [
    (b"xxxx" + bytes(20), "ldwg"),
    (b"ldwg" + struct.pack("<IqII", 0, 0, 5, 0) + bytes(3), "size"),
    (b"ldwg" + struct.pack("<IqII", 0, 0, 0x88, 0) + bytes(0x88), "not a village slot"),
])
def test_rejects_what_is_not_a_slot(data, message):
    with pytest.raises(vs.SaveFormatError, match=message):
        vs.parse_save(data)


def test_reader_never_writes(tmp_path):
    p = tmp_path / "Virtual Families1.ldw"
    p.write_bytes(sample())
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    vs.read_save(p)
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


# ---------------------------------------------------------------- which files belong to which slot
@pytest.mark.parametrize("path, owner", [
    ("Virtual Families0.ldw", (0, "options")),
    ("Virtual Families3.ldw", (3, "save")),
    ("Virtual Families23.ldw", (3, "backup 1")),
    ("Virtual Families43.ldw", (3, "backup 2")),
    ("virtual families5.LDW", (5, "save")),
    ("ldwLog.txt", (0, "engine log")),
    ("Virtual Families 1 Patcher Data/Slot 4.ini", (4, "patcher slot settings")),
    ("Virtual Families 1 Patcher Data/Children/Virtual Families2.ldw.dat", (2, "children sidecar (save)")),
    ("Virtual Families 1 Patcher Data/Children/Virtual Families22.ldw.dat", (2, "children sidecar (backup 1)")),
    ("Virtual Families 1 Patcher Data/Children/Virtual Families42.ldw.dat", (2, "children sidecar (backup 2)")),
    ("Virtual Families 1 Patcher Data/Children/Virtual Families2.ldw.unreadable-3.dat",
     (2, "unreadable children sidecar (save)")),
])
def test_file_owner(path, owner):
    assert vs.file_owner(path) == owner


@pytest.mark.parametrize("path", ["Virtual Families6.ldw", "Virtual Families26.ldw", "Virtual Families61.ldw",
                                  "Virtual Families1 - Copy.ldw", "ldw.ini", "Slot 3.ini",
                                  "Virtual Families 1 Patcher Data/Slot 21.ini",
                                  "Virtual Families 1 Patcher Data/Children/Virtual Families0.ldw.dat"])
def test_files_the_game_and_patcher_never_write(path):
    assert vs.file_owner(path) is None


# ---------------------------------------------------------------- real saves (copies, renamed)
def fixture(name):
    """A real save rebuilt from its fixture (tools/make_vf1_save_fixtures.py keeps the parsed ranges)."""
    import json
    return vs.parse_save(fx.rebuild(json.loads((FIXTURES / name.replace(".ldw", ".json")).read_text("utf-8"))))


def test_fixture_tool_keeps_every_parsed_field():
    data = sample()
    a, b = vs.parse_save(data), vs.parse_save(fx.rebuild(fx.make(data)))
    for v1, v2 in zip(a.villagers, b.villagers):
        assert v1.raw[:0x168] == v2.raw[:0x168]
    assert a.family_records == b.family_records
    assert (a.header, a.family_name, a.money, a.food, a.stats, a.time, a.pending_babies, a.speed) == (
        b.header, b.family_name, b.money, b.food, b.stats, b.time, b.pending_babies, b.speed)


def test_real_generation6_with_left_home_children():
    s = fixture("generation6_left_home.ldw")
    assert s.header.size == 24 and s.version == 0x3F8 and s.generation == 6
    assert s.paused and s.speed == 1009
    a, b = s.couple()
    assert (a.slot, a.name, a.sex, b.slot, b.name, b.sex) == (11, "Vesta", 1, 0, "Bengor", 0)
    rec = s.current_family
    assert rec.parent1.parent_child_index == 5 and s.family_records[4].children[5].name == "Vesta"
    assert [c.name for c in rec.children] == ["Input", "Dico", "Pennella", "Tilde", "Fabiana", "Francone"]
    left = [v for v in s.household() if v.left_home]
    assert [(v.name, v.years, v.career) for v in left] == [("Input", 19, -1), ("Dico", 20, -1)]
    # the original child Vesta (slot 7) and the unchosen next-generation clones are not present
    assert [v.slot for v in s.villagers if not v.present and not v.is_empty] == [7, 8, 9, 10]
    assert all(c.parent1_name == "Joey" for c in s.household() if c.years < 21)
    assert s.header.real_time(s.time.saved_at).year == 2026


def test_real_pregnancy_and_unborn_baby():
    s = fixture("pregnant_unborn_baby.ldw")
    mother = s.villagers[0]
    assert mother.name == "Rosella" and mother.pregnant and mother.pregnant_since == 541 and mother.babies_carried == 1
    assert s.pending_babies == (2, -1, -1)
    baby = s.unborn()[0]
    assert (baby.name, baby.present, baby.age_units, baby.parent1_name, baby.parent2_name) == (
        "Bohi", False, 40, "Joey", "Rosella")
    assert s.current_family.children[0].name == "Bohi" and s.current_family.children[0].slot == 2
    assert s.stats.babies_born == 1 and s.generation == 1


def test_real_legacy_header_old_version():
    s = fixture("legacy_header_v3f0.ldw")
    assert s.header.size == 12 and s.header.word20 is None and s.version == 0x3F0
    assert s.generation == 5
    a, b = s.couple()
    assert (a.name, b.name) == ("Marette", "Marcico")


def test_real_parents_died_of_old_age():
    s = fixture("parents_died_old_age.ldw")
    rec = s.current_family
    assert s.generation == 1 and rec.parent_died_children_survive
    assert rec.parent1.slot == -1 and rec.parent2.slot == -1 and s.couple() == (None, None)
    soonie = s.villagers[0]
    assert (soonie.name, soonie.present, soonie.health, soonie.death_cause, soonie.years) == ("Soonie", False, 0, 2, 64)
    assert sum(v.left_home for v in s.household()) == 6


# ---------------------------------------------------------------- the game's own code, emulated
def vanilla_exe() -> Path:
    exe = os.environ.get("VF1_VANILLA_EXE")
    if exe and Path(exe).is_file():
        return Path(exe)
    d = os.environ.get("VF1_VANILLA_DIR")
    if d and (Path(d) / "Virtual Families.exe").is_file():
        return Path(d) / "Virtual Families.exe"
    pytest.skip("set VF1_VANILLA_DIR (or VF1_VANILLA_EXE) to a copy of the vanilla game")


class GameCode:
    """The vanilla executable mapped at its link address; thiscall functions run to a sentinel return."""
    OBJ, OUT, STACK, SENTINEL = 0x10000000, 0x11000000, 0x12000000, 0x13000000

    def __init__(self, exe: Path):
        import faulthandler
        import hashlib
        import pefile
        # unicorn commits guest memory through first-chance access violations it handles itself;
        # faulthandler would print a stack for each one (as tests/kids_emu.py).
        faulthandler.disable()
        from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
        data = exe.read_bytes()
        assert hashlib.sha256(data).hexdigest() == "5db828c3f53c68696c18719aec0eb114be3fd4458ae2cbf185d8d4ef7eca4487"
        pe = pefile.PE(data=data)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        self.uc.mem_map(0x400000, size)
        for s in pe.sections:
            self.uc.mem_write(0x400000 + s.VirtualAddress, data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData])
        for base in (self.OBJ, self.OUT):
            self.uc.mem_map(base, 0x100000)
        self.uc.mem_map(self.STACK, 0x10000)
        self.uc.mem_map(self.SENTINEL, 0x1000)
        self.uc.mem_write(self.SENTINEL, b"\xC3")

    def call(self, fn, this, *args):
        from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP
        sp = self.STACK + 0xF000
        frame = struct.pack("<I", self.SENTINEL) + b"".join(struct.pack("<I", a) for a in args)
        sp -= len(frame)
        self.uc.mem_write(sp, frame)
        self.uc.reg_write(UC_X86_REG_ESP, sp)
        self.uc.reg_write(UC_X86_REG_ECX, this)
        self.uc.emu_start(fn, self.SENTINEL, count=2_000_000)


@pytest.fixture(scope="module")
def game():
    return GameCode(vanilla_exe())


def test_game_villager_save_state_writes_what_the_reader_reads(game):
    """CVillager::SaveState 0x485640 on a villager laid out at the in-memory offsets."""
    v = bytearray(0x14600)
    struct.pack_into("<iiii", v, 0x2A34, 642, 1, 9, 4)                  # bio: age, sex, name index, voice
    v[0x2A44:0x2A44 + 6] = b"Sophia"
    struct.pack_into("<ii", v, 0x2A60, 21, 33)                           # head, body
    v[0x2A68:0x2A6C] = b"Joey"
    v[0x2A82:0x2A87] = b"Marta"
    struct.pack_into("<4i", v, 0x2A9C, 1, 2, 3, 4)
    v[0x2AB0:0x2AB4] = b"Bert"
    struct.pack_into("<ii", v, 0x2ACC, 5, 6)
    struct.pack_into("<iIiii", v, 0x2AD4, 77, 123456, 640, 55, -1)      # state
    struct.pack_into("<ii", v, 0x2AF8, 630, 2)
    struct.pack_into("<6iii", v, 0x2B08, 10, 20, 30, 40, 50, 60, 88, 42)
    struct.pack_into("<4i", v, 0x2B6C, 17, 2, 10, 900)                  # skills
    struct.pack_into("<6i", v, 0x13620, 7, 8, 9, 10, 11, 12)            # likes, dislikes
    v[0x13574], v[0x13578] = 1, 1
    struct.pack_into("<I", v, 0x1357C, 999)
    game.uc.mem_write(game.OBJ, bytes(v))
    game.uc.mem_write(game.OUT, bytes(vs.VILLAGER_RECORD))
    game.call(0x485640, game.OBJ, game.OUT)
    r = vs.parse_villager(bytes(game.uc.mem_read(game.OUT, vs.VILLAGER_RECORD)), 4)
    assert (r.present, r.left_home, r.left_home_at) == (True, True, 999)
    assert (r.age_units, r.sex, r.name_index, r.voice, r.name, r.head, r.body) == (642, 1, 9, 4, "Sophia", 21, 33)
    assert (r.parent1_name, r.parent2_name, r.parent1_head, r.parent1_body, r.parent2_head, r.parent2_body) == (
        "Joey", "Marta", 1, 2, 3, 4)
    assert (r.pending_father_name, r.pending_father_body, r.pending_father_head) == ("Bert", 5, 6)
    assert (r.age_seconds_bank, r.last_update, r.age_processed, r.health, r.death_cause) == (77, 123456, 640, 55, -1)
    assert (r.pregnant_since, r.babies_carried, r.stats, r.fertility, r.wants_children) == (
        630, 2, (10, 20, 30, 40, 50, 60), 88, 42)
    assert (r.career, r.career_level, r.skills_8, r.salary, r.likes, r.dislikes) == (
        17, 2, 10, 900, (7, 8, 9), (10, 11, 12))

    v[0x13540] = 1                                                        # a ghost is saved as not present
    game.uc.mem_write(game.OBJ, bytes(v))
    game.call(0x485640, game.OBJ, game.OUT)
    assert game.uc.mem_read(game.OUT, 1) == b"\0"


def test_game_family_tree_save_and_load_match_the_reader(game):
    """CFamilyTree::SaveState 0x481680 copies the 30 records without the counter; LoadState 0x481580
    rebuilds the counter from the leading used records."""
    p1 = peep("Ann", sex=1, head=3, body=4, slot=0, index=-1, career=5, likes=" tea")
    recs = [family_record(p1, peep("Bob", slot=1), [peep("Cid", slot=2)]),
            family_record(peep("Cid", slot=2, index=0), peep("Dee", sex=1, slot=3), [])]
    tree = bytearray(4 + vs.FAMILY_RECORDS * vs.FAMILY_RECORD)
    struct.pack_into("<i", tree, 0, 2)
    for k, r in enumerate(recs):
        tree[4 + k * vs.FAMILY_RECORD:4 + (k + 1) * vs.FAMILY_RECORD] = r
    game.uc.mem_write(game.OBJ, bytes(tree))
    game.uc.mem_write(game.OUT, bytes(vs.FAMILY_RECORDS * vs.FAMILY_RECORD))
    game.call(0x481680, game.OBJ, game.OUT)
    saved = bytes(game.uc.mem_read(game.OUT, vs.FAMILY_RECORDS * vs.FAMILY_RECORD))
    assert saved == bytes(tree[4:])
    parsed = vs.parse_family_records(saved)
    assert len(parsed) == 2 and parsed[0].parent1 == vs.parse_peep(p1)
    assert parsed[0].parent1.likes_text == " tea" and parsed[1].parent1.parent_child_index == 0
    assert [c.name for c in parsed[0].children] == ["Cid"]

    game.uc.mem_write(game.OBJ, bytes(len(tree)))                         # load into a cleared tree
    game.call(0x481580, game.OBJ, game.OUT)
    counter = struct.unpack("<i", bytes(game.uc.mem_read(game.OBJ, 4)))[0]
    assert counter == len(parsed) == 2


def test_game_loads_real_tree_to_the_readers_generation(game):
    s = fixture("generation6_left_home.ldw")
    o = vs.GS_FAMILY_TREE - vs.GS_BASE
    game.uc.mem_write(game.OUT, s.payload[o:o + vs.FAMILY_RECORDS * vs.FAMILY_RECORD])
    game.uc.mem_write(game.OBJ, bytes(4 + vs.FAMILY_RECORDS * vs.FAMILY_RECORD))
    game.call(0x481580, game.OBJ, game.OUT)
    assert struct.unpack("<i", bytes(game.uc.mem_read(game.OBJ, 4)))[0] == s.generation == 6
