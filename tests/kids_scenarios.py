"""Scenarios for the Up to 28 Children DLL (vf1kids.dll), run under tests/kids_emu.py.

Each scenario takes a fresh KidsWorld and raises AssertionError on a wrong result. A KidsWorld is the
REAL vanilla Virtual Families executable and the REAL compiled test DLL in one unicorn address space,
with the DLL's hooks written exactly as its own plan says. They are the Virtual Families 2 patcher's
scenarios (tests/b200_kids_scenarios.py there) on VF1's own code.

Game code that runs for real: CFamilyTree::AddOffspring, EmptyOffspringSlots (the DLL's replacement),
CountSurvivingChildren, ReportDeath, Reset, StartNextGeneration, ChangeName (with its FindPeepRecord and
ldwStrCopy), CAdoptionScene::CreateNextGenerationCandidates and GetNextCandidate,
CVillagerManager::FindEmptySlot, ClonePeepAsAdult and GetVillager, theGameState::Get, and
CVillager::Impregnate from its first instruction to its `ret 14h` (the twin / triplet decision, the
reserved baby slots, AddOffspring for each baby).

Seams (recorded, never real): the bodies of theGameState::Save and ::Load after their first
instructions, MakeGameStatePath, CFamilyTree::UpdatePeepRecord and UpdateCurrentFamilyRecord (career and
likes text), CVillager::CloneAsAdult (copies the identity fields and makes the clone an adult), the spawn
calls Impregnate makes, GetMatriarch / GetPatriarch, ldwGameState::GetRandom (scripted rolls), the
achievement counter, the gender chooser, and the DLL's Win32 file imports (an in-memory file system).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import vf1_kids_sites as K  # noqa: E402

from kids_emu import Emu, EmuError  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_ESP  # noqa: E402

STRIDE = K.VILLAGER_STRIDE
SAVE_DIR = "C:\\Users\\Tester\\Documents\\LDW\\VF1 Kids Test"
DLL_PATH = "C:\\Game\\Virtual Families 1 Patcher Files\\vf1kids.dll"
INVALID = 0xFFFFFFFF
ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND, ERROR_ALREADY_EXISTS = 2, 3, 183
ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION = 5, 32, 33
ERROR_FILENAME_EXCED_RANGE = 206
OPEN_TRIES = 5                 # the DLL's kOpenTries: a shut file is opened this many times
ALIVE, DEAD, GONE = 1, 2, 3

UPDATE_PEEP_RECORD = 0x4818F0
UPDATE_CURRENT_FAMILY_RECORD = 0x481960
GET_MATRIARCH, GET_PATRIARCH = 0x489950, 0x4899C0
GET_RANDOM = 0x403650
SPAWN_FULL, SPAWN_TWIN = 0x48B2E0, 0x48B350
INCREMENT_PROGRESS = 0x413210
GENDER_CHOICE = 0x48BBF0
IMPREGNATE = 0x4864D0


def s32(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


class FileSystem:
    """The DLL's Win32 file imports over a dict (case-insensitive paths)."""

    def __init__(self):
        self.files = {}
        self.dirs = set()
        self.handles = {}
        self.next = 0x100
        self.last_error = 0
        self.log = []
        self.shut = {}           # key -> opens still refused (None: every one), as another program holding it
        self.shut_error = ERROR_SHARING_VIOLATION
        self.sleeps = []
        self.max_path = None     # MoveFileExA refuses a destination longer than this

    def hold(self, path, opens=None, error=ERROR_SHARING_VIOLATION):
        """Another program holds the file: `opens` refused opens (None: until released)."""
        self.shut[self.key(path)] = opens
        self.shut_error = error

    def release(self, path):
        self.shut.pop(self.key(path), None)

    def _refused(self, k):
        if k not in self.shut:
            return False
        left = self.shut[k]
        if left is None:
            return True
        if left <= 0:
            del self.shut[k]
            return False
        self.shut[k] = left - 1
        return True

    @staticmethod
    def key(path):
        return path.replace("/", "\\").lower()

    def parent(self, path):
        return self.key(path).rsplit("\\", 1)[0]

    def mkdirs(self, path):
        parts = self.key(path).split("\\")
        for i in range(1, len(parts) + 1):
            self.dirs.add("\\".join(parts[:i]))

    def write(self, path, data):
        self.mkdirs(self.parent(path))
        self.files[self.key(path)] = bytes(data)

    def read(self, path):
        return self.files.get(self.key(path))

    def exists(self, path):
        return self.key(path) in self.files

    def bind(self, emu):
        fs = self

        def create(e):
            path = e.cstr(e.arg(0))
            disposition = e.arg(4)
            k = fs.key(path)
            fs.log.append(("CreateFileA", path, disposition))
            if fs._refused(k):
                fs.last_error = fs.shut_error
                return INVALID, 28
            if disposition == 3:
                if k not in fs.files:
                    fs.last_error = ERROR_FILE_NOT_FOUND if fs.parent(path) in fs.dirs else ERROR_PATH_NOT_FOUND
                    return INVALID, 28
                data = bytearray(fs.files[k])
            elif disposition == 2:
                if fs.parent(path) not in fs.dirs:
                    fs.last_error = ERROR_PATH_NOT_FOUND
                    return INVALID, 28
                data = bytearray()
                fs.files[k] = b""
            else:
                raise EmuError(f"CreateFileA disposition {disposition}")
            h = fs.next
            fs.next += 4
            fs.handles[h] = {"key": k, "data": data, "pos": 0, "write": disposition == 2}
            return h, 28

        def read_file(e):
            h, buf, n, got = e.arg(0), e.arg(1), e.arg(2), e.arg(3)
            st = fs.handles[h]
            chunk = bytes(st["data"][st["pos"]:st["pos"] + n])
            st["pos"] += len(chunk)
            if chunk:
                e.write(buf, chunk)
            e.w32(got, len(chunk))
            return 1, 20

        def write_file(e):
            h, buf, n, got = e.arg(0), e.arg(1), e.arg(2), e.arg(3)
            st = fs.handles[h]
            st["data"] += e.read(buf, n)
            e.w32(got, n)
            return 1, 20

        def close(e):
            st = fs.handles.pop(e.arg(0))
            if st["write"]:
                fs.files[st["key"]] = bytes(st["data"])
            return 1, 4

        def mkdir(e):
            path = e.cstr(e.arg(0))
            k = fs.key(path)
            if k in fs.dirs:
                fs.last_error = ERROR_ALREADY_EXISTS
                return 0, 8
            if fs.parent(path) not in fs.dirs:
                fs.last_error = ERROR_PATH_NOT_FOUND
                return 0, 8
            fs.dirs.add(k)
            return 1, 8

        def move(e):
            src, dst, flags = e.cstr(e.arg(0)), e.cstr(e.arg(1)), e.arg(2)
            fs.log.append(("MoveFileExA", src, dst, flags))
            ks, kd = fs.key(src), fs.key(dst)
            if ks in fs.shut or kd in fs.shut:
                fs.last_error = ERROR_SHARING_VIOLATION
                return 0, 12
            if fs.max_path is not None and len(dst) > fs.max_path:
                fs.last_error = ERROR_FILENAME_EXCED_RANGE
                return 0, 12
            if ks not in fs.files:
                fs.last_error = ERROR_FILE_NOT_FOUND
                return 0, 12
            if kd in fs.files and not flags & 1:
                fs.last_error = ERROR_ALREADY_EXISTS
                return 0, 12
            fs.files[kd] = fs.files.pop(ks)
            return 1, 12

        def delete(e):
            path = e.cstr(e.arg(0))
            fs.log.append(("DeleteFileA", path))
            if fs.key(path) in fs.shut:
                fs.last_error = ERROR_SHARING_VIOLATION
                return 0, 4
            if fs.files.pop(fs.key(path), None) is None:
                fs.last_error = ERROR_FILE_NOT_FOUND
                return 0, 4
            return 1, 4

        emu.imports.update({
            "CreateFileA": create, "ReadFile": read_file, "WriteFile": write_file, "CloseHandle": close,
            "FlushFileBuffers": lambda e: (1, 4), "CreateDirectoryA": mkdir, "MoveFileExA": move,
            "DeleteFileA": delete, "GetLastError": lambda e: (fs.last_error, 0),
            "Sleep": lambda e: (fs.sleeps.append(e.arg(0)), 0)[1:] + (4,),
        })


class KidsWorld:
    """One emulated process: the vanilla Virtual Families executable + the test DLL."""

    def __init__(self, exe, dll, install=True):
        self.e = Emu(exe, dll, 0)
        self.fs = FileSystem()
        self.fs.bind(self.e)
        self.save_dir = SAVE_DIR
        self.fs.mkdirs(SAVE_DIR)
        self.rolls = []
        self.spawned = []
        self.saves = []
        self.watch = []
        self.save_content = {}
        self.load_result = 1
        self.loads = []
        self.code_before = self._code()
        self._game_state()
        self._villagers()
        self._seams()
        self.mother, self.father = 0, 1
        if install:
            self.install()

    def call_target(self, at):
        return (at + 5 + self.e.r32(at + 1)) & 0xFFFFFFFF

    def _code(self):
        out = []
        for s in self.e.exe.sections:
            if s.Characteristics & 0x20000000:
                base = self.e.base + s.VirtualAddress
                out.append((base, self.e.read(base, min(s.Misc_VirtualSize, s.SizeOfRawData))))
        return out

    def changed_code(self):
        changed = set()
        for base, was in self.code_before:
            now = self.e.read(base, len(was))
            if now != was:
                changed.update(base + i for i in range(len(was)) if now[i] != was[i])
        return changed

    # ------------------------------------------------------------------ the plan
    def test_plan(self, enabled=True):
        out = self.e.alloc(0x400)
        status = s32(self.e.call(self.e.dll_export("VF1Kids_TestPlan"), (1 if enabled else 0, out)))
        count = self.e.r32(out + 4)
        writes = []
        for i in range(count):
            va, b0, b1 = (self.e.r32(out + 8 + i * 12 + 4 * k) for k in range(3))
            writes.append((va, struct.pack("<I", b0) + bytes([b1 & 0xFF])))
        return status, writes

    def install(self):
        status, writes = self.test_plan(True)
        assert status == 1, f"the plan was refused (status {status})"
        for va, raw in writes:
            self.e.write(va, raw)
        self.writes = writes
        return writes

    # ------------------------------------------------------------------ the game's state
    def _game_state(self):
        e = self.e
        self.state = e.alloc(0x1B900)
        e.w32(K.GAME_STATE_INSTANCE, self.state)
        for k in range(3):
            e.w32(self.state + K.GAME_STATE_RESERVED_BABY + 4 * k, INVALID)
        vtable = e.alloc(0x40)
        stub = e.fake_code(b"\xC2\x04\x00")
        e.w32(vtable + K.LDW_PATH_VSLOT, stub)
        e.w32(self.state, vtable)
        self.path_buffer = e.alloc(0x200)

        def make_path(emu):
            emu.write(self.path_buffer, self.save_path(emu.arg(0)).encode("ascii") + b"\0")
            return self.path_buffer, 4
        e.seam_live(stub, make_path)

    def save_path(self, slot):
        return f"{self.save_dir}\\Virtual Families{slot}.ldw"

    def sidecar_path(self, slot):
        return f"{self.save_dir}\\Virtual Families 1 Patcher Data\\Children\\Virtual Families{slot}.ldw.dat"

    def tree(self):
        return K.FAMILY_TREE

    def villager(self, slot):
        return K.VILLAGER_MANAGER + K.VILLAGER_ARRAY_OFFSET + slot * STRIDE

    def _villagers(self):
        for slot in range(30):
            v = self.villager(slot)
            self.e.w32(v + K.VILLAGER_SLOT, slot)
            self.e.write(v + K.VILLAGER_PRESENT, b"\0")

    def set_villager(self, slot, name, gender, active=1, age=100, head=3, body=4):
        e = self.e
        v = self.villager(slot)
        e.write(v + K.VILLAGER_NAME, name.encode("ascii")[:24].ljust(25, b"\0"))
        e.w32(v + K.VILLAGER_GENDER, gender)
        e.w32(v + K.VILLAGER_HEAD, head)
        e.w32(v + K.VILLAGER_BODY, body)
        e.w32(v + K.VILLAGER_AGE, age)
        e.write(v + K.VILLAGER_PRESENT, bytes([active]))

    def active(self, slot):
        return self.e.read(self.villager(slot) + K.VILLAGER_PRESENT, 1)[0]

    def set_active(self, slot, on):
        self.e.write(self.villager(slot) + K.VILLAGER_PRESENT, bytes([1 if on else 0]))

    def name(self, slot):
        return self.e.cstr(self.villager(slot) + K.VILLAGER_NAME)

    def generations(self):
        return s32(self.e.r32(self.tree()))

    def record(self, gen=None):
        gen = self.generations() if gen is None else gen
        return self.tree() + gen * K.FAMILY_RECORD_SIZE - K.FAMILY_RECORD_BASE

    def stock_children(self):
        return s32(self.e.r32(self.record() + K.RECORD_CHILD_COUNT))

    def stock_child_slot(self, i):
        return s32(self.e.r32(self.record() + K.RECORD_CHILDREN + i * K.PEEP_RECORD_SIZE + K.PEEP_SLOT))

    def start_family(self, parent1=0, parent2=1):
        self.set_villager(parent1, "Mother", 1, age=600)
        self.set_villager(parent2, "Father", 0, age=620)
        r = self.e.call(K.PIN["ft_start_next_gen"][1], (self.villager(parent1), INVALID), ecx=self.tree())
        assert r & 0xFF == 1
        rec = self.record()
        self.e.write(rec + 0xDC + K.PEEP_VALID, b"\x01")
        self.e.w32(rec + 0xDC + K.PEEP_GENDER, 0)
        self.e.w32(rec + 0xDC + K.PEEP_SLOT, parent2)

    # ------------------------------------------------------------------ the DLL's own view
    def extras(self):
        out = self.e.alloc(4 + 22 * 12)
        self.e.call(self.e.dll_export("VF1Kids_TestExtras"), (out,))
        n = s32(self.e.r32(out))
        return [tuple(s32(self.e.r32(out + 4 + i * 12 + 4 * k)) for k in range(3)) for i in range(n)]

    def engine(self):
        out = self.e.alloc(4 * 40)
        self.e.call(self.e.dll_export("VF1Kids_TestEngine"), (out,))
        on, count, cursor, swapped = (s32(self.e.r32(out + 4 * k)) for k in range(4))
        return {"on": on, "count": count, "cursor": cursor, "swapped": swapped,
                "sources": [s32(self.e.r32(out + 16 + 4 * i)) for i in range(max(count, 0))]}

    def children_export(self):
        return s32(self.e.call(self.e.dll_export("VF1Kids_Children"), ()))

    def status(self):
        st = self.e.dll_export("VF1Kids_Status")
        names = ("magic", "version", "requested", "resolved", "installed", "writeMask", "extras", "lastLoad",
                 "lastSave")
        return {n: self.e.r32(st + 4 * i) for i, n in enumerate(names)}

    # ------------------------------------------------------------------ calling the game
    def add_offspring(self, slot):
        return self.e.call(K.PIN["ft_add_offspring"][1], (self.villager(slot),), ecx=self.tree()) & 0xFF

    def empty_slots(self):
        return s32(self.e.call(K.PIN["ft_empty_offspring"][1], (), ecx=self.tree()))

    def surviving(self):
        return s32(self.e.call(K.PIN["ft_count_surviving"][1], (), ecx=self.tree()))

    def report_death(self, slot):
        self.e.call(K.PIN["ft_report_death"][1], (self.villager(slot),), ecx=self.tree())

    def reset_tree(self):
        self.e.call(K.PIN["ft_reset"][1], (), ecx=self.tree())

    def change_name(self, slot, name):
        buf = self.e.alloc(32)
        self.e.write(buf, name.encode("ascii") + b"\0")
        self.e.call(K.PIN["ft_change_name"][1], (self.villager(slot), buf), ecx=self.tree())
        self.e.write(self.villager(slot) + K.VILLAGER_NAME, name.encode("ascii")[:24].ljust(25, b"\0"))

    def start_next_generation(self, heir, source):
        return self.e.call(K.PIN["ft_start_next_gen"][1], (self.villager(heir), source & 0xFFFFFFFF),
                           ecx=self.tree()) & 0xFF

    def save(self, slot):
        return self.e.call(K.PIN["gs_save"][1], (slot,), ecx=self.state) & 0xFF

    def load(self, slot):
        return self.e.call(K.PIN["gs_load"][1], (slot,), ecx=self.state) & 0xFF

    # ------------------------------------------------------------------ the scene
    def make_scene(self):
        scene = self.e.alloc(0x200)
        self.e.write(scene + K.ADOPTION_MODE, b"\x01")
        self.e.w32(scene + K.ADOPTION_CANDIDATE, INVALID)
        return scene

    def create_candidates(self, scene):
        self.e.call(K.PIN["ad_create_candidates"][1], (), ecx=scene)

    def next_candidate(self, scene):
        """CAdoptionScene::GeneratePeepCandidate in Next Generation mode: GetNextCandidate, then show it."""
        clone = s32(self.e.call(K.PIN["ad_get_next"][1], (), ecx=scene))
        self.e.w32(scene + K.ADOPTION_CANDIDATE, clone)
        return clone

    def accept(self, scene):
        e = self.e
        heir = s32(e.r32(scene + K.ADOPTION_CANDIDATE))
        cursor = s32(e.r32(scene + K.ADOPTION_CURSOR))
        source = s32(e.r32(scene + K.ADOPTION_SOURCES + 4 * cursor))
        self.set_active(heir, 1)
        ok = self.start_next_generation(heir, source)
        for slot in range(30):
            if slot != heir:
                self.set_active(slot, 0)
        return heir, source, ok

    # ------------------------------------------------------------------ seams
    def _seams(self):
        e = self.e
        e.seam_live(UPDATE_PEEP_RECORD, lambda emu: (0, 4))
        e.seam_live(UPDATE_CURRENT_FAMILY_RECORD, lambda emu: (0, 0))

        def clone_as_adult(emu):
            dest, src = emu.ecx, emu.arg(0)
            for off, n in ((K.VILLAGER_NAME, 25), (K.VILLAGER_GENDER, 4), (K.VILLAGER_HEAD, 4), (K.VILLAGER_BODY, 4)):
                emu.write(dest + off, emu.read(src + off, n))
            emu.w32(dest + K.VILLAGER_AGE, 500)
            emu.write(dest + K.VILLAGER_PRESENT, b"\x01")
            emu.w32(dest + 0x2AE0, 0xC10E)
            return 0, 4
        e.seam_live(K.PIN["v_clone_as_adult"][1], clone_as_adult)

        def saved(emu):
            esp = emu.reg(UC_X86_REG_ESP)
            emu.setreg(UC_X86_REG_EDI, emu.r32(esp))       # the trampoline's push esi / push edi
            emu.setreg(UC_X86_REG_ESI, emu.r32(esp + 4))
            emu.setreg(UC_X86_REG_ESP, esp + 8)
            slot = emu.r32(esp + 12)
            self.saves.append((slot, {w: self.e.read(self.villager(w), STRIDE) for w in self.watch}))
            content = self.save_content.get(slot, b"SAVE %d #%d" % (slot, len(self.saves)))
            if slot > 0:
                if self.fs.exists(self.save_path(slot)):
                    self.fs.files[self.fs.key(self.save_path(slot + 20))] = self.fs.read(self.save_path(slot))
                self.fs.write(self.save_path(slot), content)
            return 1, 4
        e.seam_live(K.PIN["gs_save"][1] + K.HOOKS["GS_SAVE"][1], saved)

        def loaded(emu):
            self.loads.append(emu.arg(0))
            return self.load_result, 4
        e.seam_live(K.PIN["gs_load"][1] + K.HOOKS["GS_LOAD"][1], loaded)

        e.seam_live(GET_MATRIARCH, lambda emu: (self.villager(self.mother), 0))
        e.seam_live(GET_PATRIARCH, lambda emu: (self.villager(self.father), 0))

        def get_random(emu):
            assert self.rolls, "an unscripted GetRandom"
            return self.rolls.pop(0), 0
        e.seam_live(GET_RANDOM, get_random)

        def spawn(pop):
            def fn(emu):
                reserved = {s32(self.e.r32(self.state + K.GAME_STATE_RESERVED_BABY + 4 * k)) for k in range(3)}
                for slot in range(30):
                    if not self.active(slot) and slot not in reserved:
                        self.set_villager(slot, f"Baby {slot}", slot % 2, active=1, age=0)
                        self.spawned.append(slot)
                        return slot, pop
                return INVALID, pop
            return fn
        e.seam_live(SPAWN_FULL, spawn(0x30))
        e.seam_live(SPAWN_TWIN, spawn(4))
        e.seam_live(INCREMENT_PROGRESS, lambda emu: (0, 8))
        e.seam_live(GENDER_CHOICE, lambda emu: (INVALID, 0))

    def impregnate(self, rolls):
        e = self.e
        self.rolls = list(rolls)
        self.spawned = []
        name = e.alloc(32)
        e.write(name, b"Joey\0")
        mother = self.villager(self.mother)
        e.w32(mother + 0x2B20, 0)
        e.w32(self.villager(self.father) + 0x2B20, 0)
        r = e.call(IMPREGNATE, (1, name, 2, 3, 0), ecx=mother) & 0xFF
        return r, list(self.spawned), s32(e.r32(mother + 0x2AFC)), len(self.rolls)

    # ------------------------------------------------------------------ helpers
    def have_children(self, n, first_slot=2):
        for k in range(n):
            slot = first_slot + k
            self.set_villager(slot, f"Kid {k + 1}", k % 2, age=40 + k)
            assert self.add_offspring(slot) == 1, f"child {k + 1} was refused"

    def sidecar(self, slot):
        raw = self.fs.read(self.sidecar_path(slot))
        assert raw is not None, "no sidecar"
        return parse_sidecar(raw)


def fnv(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def parse_sidecar(raw: bytes) -> dict:
    assert raw[:8] == b"VF1KIDS\0" and raw[12:20] == b"VF1V101\0"
    assert struct.unpack_from("<I", raw, 8)[0] == 1 and struct.unpack_from("<I", raw, 20)[0] == len(raw)
    save_hash, = struct.unpack_from("<Q", raw, 24)
    save_size, gens, pslot, pgender, count = struct.unpack_from("<IiiiI", raw, 32)
    entries = []
    for i in range(count):
        slot, gender, state, head, body, age = struct.unpack_from("<iiiiii", raw, 52 + 64 * i)
        name = raw[52 + 64 * i + 24: 52 + 64 * i + 52].split(b"\0")[0].decode("ascii")
        entries.append({"slot": slot, "gender": gender, "state": state, "name": name})
    assert len(raw) == 52 + 64 * count + 8
    assert struct.unpack_from("<Q", raw, len(raw) - 8)[0] == fnv(raw[:-8]), "checksum"
    return {"save_hash": save_hash, "save_size": save_size, "generations": gens, "parent_slot": pslot,
            "parent_gender": pgender, "entries": entries}


# ====================================================================== scenarios
def scenario_six_stock_then_extras(w: KidsWorld):
    w.start_family()
    assert w.empty_slots() == 28
    w.have_children(6)
    assert w.stock_children() == 6 and w.extras() == []
    assert w.empty_slots() == 22
    w.have_children(22, first_slot=8)
    assert w.stock_children() == 6
    ex = w.extras()
    assert [e[0] for e in ex] == list(range(8, 30)) and all(e[2] == ALIVE for e in ex)
    assert w.empty_slots() == 0 and w.children_export() == 28
    w.set_active(29, 0)
    w.set_villager(29, "Kid 29", 0)
    assert w.add_offspring(29) == 0
    assert w.e.read(w.record(2), K.FAMILY_RECORD_SIZE) == b"\0" * K.FAMILY_RECORD_SIZE


def scenario_free_slots_cap(w: KidsWorld):
    w.start_family()
    w.have_children(10)
    for slot in range(12, 30):
        w.set_villager(slot, f"Guest {slot}", 0)
    assert w.empty_slots() == 0
    w.set_active(29, 0)
    assert w.empty_slots() == 1
    w.e.w32(w.state + K.GAME_STATE_RESERVED_BABY, 29)
    assert w.empty_slots() == 0


def scenario_deaths_count_toward_28(w: KidsWorld):
    w.start_family()
    w.have_children(20)
    assert w.surviving() == 20 and w.empty_slots() == 8
    w.report_death(15)
    w.set_active(15, 0)
    assert {e[0]: e[2] for e in w.extras()}[15] == DEAD
    assert w.surviving() == 19 and w.empty_slots() == 8
    rec = w.record()
    w.e.write(rec + 1, b"\x01")
    for slot in range(2, 8):
        w.report_death(slot)
        w.set_active(slot, 0)
    assert w.surviving() == 13
    assert w.e.read(rec + 1, 1) == b"\x01", "the next-generation flag stays set while extra children live"


def scenario_rename_and_reused_slot(w: KidsWorld):
    w.start_family()
    w.have_children(8)
    w.change_name(9, "Renamed")
    assert {e[0]: e[2] for e in w.extras()}[9] == ALIVE and w.surviving() == 8
    w.set_villager(8, "Stranger", 1)
    assert w.surviving() == 7 and {e[0]: e[2] for e in w.extras()}[8] == GONE
    assert w.add_offspring(9) == 1
    assert [(e[0], e[2]) for e in w.extras()] == [(8, GONE), (9, GONE), (9, ALIVE)]


def _room(w, born):
    w.start_family()
    w.have_children(born)


def scenario_births_near_the_limit(w_factory):
    SINGLE, TWIN, TRIPLET = (99,), (0, 99), (0, 0)
    expect = {
        26: {SINGLE: (1, 0), TWIN: (2, 0), TRIPLET: (2, 0)},
        27: {SINGLE: (1, 0), TWIN: (1, 1), TRIPLET: (1, 1)},
        28: {SINGLE: (0, 1), TWIN: (0, 2), TRIPLET: (0, 2)},
    }
    for born, cases in expect.items():
        for rolls, (babies, unused) in cases.items():
            w = w_factory()
            _room(w, born)
            before = len(w.extras()) + w.stock_children()
            r, spawned, count, left = w.impregnate(rolls)
            assert left == unused, (born, rolls, left)
            after = len(w.extras()) + w.stock_children()
            assert after - before == babies == len(spawned), (born, rolls, after - before, spawned)
            if born < 28:
                assert r == 1 and count == babies
                reserved = [s32(w.e.r32(w.state + K.GAME_STATE_RESERVED_BABY + 4 * k)) for k in range(3)]
                assert reserved[:babies] == spawned and all(x == -1 for x in reserved[babies:])
                assert all(not w.active(s) for s in spawned)
            else:
                assert r == 0 and not spawned
            assert after <= 28


def scenario_stock_odds_unchanged(w_factory):
    for rolls, babies in (((6, 24), 3), ((6, 25), 2), ((7,), 1)):
        w = w_factory()
        _room(w, 10)
        r, spawned, count, left = w.impregnate(rolls)
        assert r == 1 and count == babies == len(spawned) and left == 0, (rolls, count, spawned)


def scenario_limit_counts_lifetime_births(w_factory):
    w = w_factory()
    _room(w, 28)
    for slot in (12, 13, 14):
        w.report_death(slot)
        w.set_active(slot, 0)
    assert w.empty_slots() == 0
    r, spawned, count, left = w.impregnate((0, 0))
    assert r == 0 and spawned == [] and left == 2
    w = w_factory()
    _room(w, 27)
    for slot in (12, 13, 14):
        w.report_death(slot)
        w.set_active(slot, 0)
    assert w.empty_slots() == 1
    r, spawned, count, left = w.impregnate((0, 0))
    assert r == 1 and count == 1 and len(spawned) == 1 and left == 1


def scenario_next_generation_candidates(w: KidsWorld):
    w.start_family()
    w.have_children(10)
    scene = w.make_scene()
    w.create_candidates(scene)
    eng = w.engine()
    assert eng["on"] == 1 and eng["sources"] == list(range(2, 12))
    assert s32(w.e.r32(scene + K.ADOPTION_COUNT)) == 1
    seen = []
    for _ in range(10):
        clone = w.next_candidate(scene)
        assert s32(w.e.r32(scene + K.ADOPTION_CURSOR)) == 0 and s32(w.e.r32(scene + K.ADOPTION_CLONES)) == clone
        source = s32(w.e.r32(scene + K.ADOPTION_SOURCES))
        assert clone >= 12 and w.name(clone) == w.name(source) and not w.active(clone)
        seen.append(source)
    assert seen == list(range(2, 12))
    for _ in range(9):
        w.next_candidate(scene)
    assert s32(w.e.r32(scene + K.ADOPTION_SOURCES)) == 10
    heir, source, ok = w.accept(scene)
    assert ok == 1 and source == 10 and w.generations() == 2 and w.extras() == [] and w.engine()["on"] == 0
    rec = w.record()
    assert s32(w.e.r32(rec + K.RECORD_PARENT1 + K.PEEP_SLOT)) == heir and w.e.cstr(rec + 4) == "Kid 9"
    assert s32(w.e.r32(rec + 0x30)) == -1


def scenario_six_or_fewer_is_stock(w: KidsWorld):
    w.start_family()
    w.have_children(5)
    scene = w.make_scene()
    w.create_candidates(scene)
    assert w.engine()["on"] == 0
    assert s32(w.e.r32(scene + K.ADOPTION_COUNT)) == 5
    clones = [s32(w.e.r32(scene + K.ADOPTION_CLONES + 4 * i)) for i in range(5)]
    sources = [s32(w.e.r32(scene + K.ADOPTION_SOURCES + 4 * i)) for i in range(5)]
    assert sources == [2, 3, 4, 5, 6] and all(not w.active(c) for c in clones)
    assert [w.next_candidate(scene) for _ in range(6)] == clones + clones[:1]


def scenario_full_house(w: KidsWorld):
    w.start_family()
    w.have_children(28)
    snapshots = {s: w.e.read(w.villager(s), STRIDE) for s in range(2, 30)}
    scene = w.make_scene()
    w.create_candidates(scene)
    assert w.engine()["count"] == 28
    assert w.next_candidate(scene) == 2 and w.engine()["swapped"] == 2
    assert w.e.rs32(w.villager(2) + K.VILLAGER_AGE) == 500 and w.e.rs32(w.villager(2) + K.VILLAGER_SLOT) == 2
    assert w.next_candidate(scene) == 3
    assert w.e.read(w.villager(2), STRIDE) == snapshots[2]
    w.watch = [3]
    on_show = w.e.read(w.villager(3), STRIDE)
    assert w.save(1) == 1
    assert w.saves[-1][1][3] == snapshots[3] and w.e.read(w.villager(3), STRIDE) == on_show
    for _ in range(26):
        w.next_candidate(scene)
    assert all(w.e.read(w.villager(s), STRIDE) == snapshots[s] for s in range(2, 29))
    heir, source, ok = w.accept(scene)
    assert ok == 1 and heir == source == 29 and w.e.rs32(w.villager(29) + K.VILLAGER_AGE) == 500
    assert w.engine()["swapped"] == -1


def scenario_sidecar_round_trip(w: KidsWorld):
    w.start_family()
    w.have_children(10)
    w.report_death(9)
    w.set_active(9, 0)
    assert w.save(1) == 1 and w.status()["lastSave"] == 1
    side = w.sidecar(1)
    save = w.fs.read(w.save_path(1))
    assert side["save_hash"] == fnv(save) and side["save_size"] == len(save)
    assert side["generations"] == 1 and side["parent_slot"] == 0 and side["parent_gender"] == 1
    assert [(x["slot"], x["state"], x["name"]) for x in side["entries"]] == [
        (8, ALIVE, "Kid 7"), (9, DEAD, "Kid 8"), (10, ALIVE, "Kid 9"), (11, ALIVE, "Kid 10")]
    room = w.empty_slots()
    w.reset_tree()
    assert w.extras() == []
    w.start_family()
    w.have_children(6)
    assert w.load(1) == 1 and w.status()["lastLoad"] == 1
    assert [(e[0], e[2]) for e in w.extras()] == [(8, ALIVE), (9, DEAD), (10, ALIVE), (11, ALIVE)]
    assert w.empty_slots() == room


def scenario_sidecar_follows_backup(w: KidsWorld):
    w.start_family()
    w.have_children(8)
    w.save_content[1] = b"FIRST"
    w.save(1)
    w.have_children(2, first_slot=10)
    w.save_content[1] = b"SECOND"
    w.save(1)
    assert len(w.sidecar(1)["entries"]) == 4 and len(w.sidecar(21)["entries"]) == 2
    w.fs.files[w.fs.key(w.save_path(1))] = w.fs.read(w.save_path(21))
    w.reset_tree()
    w.start_family()
    w.have_children(8)
    assert w.load(1) == 1 and w.status()["lastLoad"] == 2 and [e[0] for e in w.extras()] == [8, 9]


def scenario_unreadable_sidecar_is_kept_aside(w: KidsWorld):
    w.start_family()
    w.have_children(8)
    w.save(1)
    raw = bytearray(w.fs.read(w.sidecar_path(1)))
    raw[60] ^= 0xFF
    w.fs.files[w.fs.key(w.sidecar_path(1))] = bytes(raw)
    w.reset_tree()
    w.start_family()
    w.have_children(6)
    assert w.load(1) == 1 and w.status()["lastLoad"] == 5 and w.extras() == []
    assert w.fs.read(w.sidecar_path(1)[:-4] + ".unreadable-1.dat") == bytes(raw)


def scenario_other_family_is_ignored(w: KidsWorld):
    w.start_family()
    w.have_children(8)
    w.save(1)
    w.reset_tree()
    w.start_family(parent1=1, parent2=0)
    w.have_children(6)
    assert w.load(1) == 1 and w.status()["lastLoad"] == 4 and w.extras() == []



def _aside(w, slot, n=1):
    return w.sidecar_path(slot)[:-4] + f".unreadable-{n}.dat"


def _two_saves(w):
    """Two saves of slot 1: the backup (slot 21) has the first save and its sidecar, slot 1 the second."""
    w.start_family()
    w.have_children(8)
    w.save_content[1] = b"FIRST"
    assert w.save(1) == 1
    w.have_children(2, first_slot=10)
    w.save_content[1] = b"SECOND"
    assert w.save(1) == 1
    assert w.fs.read(w.save_path(21)) == b"FIRST" and w.fs.read(w.save_path(1)) == b"SECOND"
    assert w.sidecar(21)["save_hash"] == fnv(b"FIRST") and w.sidecar(1)["save_hash"] == fnv(b"SECOND")


def scenario_unreadable_backup_is_set_aside(w: KidsWorld):
    """The game removes the save at slot + 20 at every save; an unreadable sidecar there is read first and
    kept beside itself, never deleted."""
    _two_saves(w)
    raw = bytearray(w.fs.read(w.sidecar_path(21)))
    raw[60] ^= 0xFF
    w.fs.files[w.fs.key(w.sidecar_path(21))] = bytes(raw)
    second = w.fs.read(w.sidecar_path(1))
    w.save_content[1] = b"THIRD"
    mark = len(w.fs.log)
    assert w.save(1) == 1 and w.status()["lastSave"] == 1
    assert w.fs.read(_aside(w, 21)) == bytes(raw), "the unreadable backup sidecar is kept, unchanged"
    assert w.fs.read(w.sidecar_path(21)) == second, "this slot's validated sidecar went with its save"
    assert w.sidecar(1)["save_hash"] == fnv(b"THIRD")
    assert ("DeleteFileA", w.sidecar_path(21)) not in w.fs.log[mark:]


def scenario_foreign_backup_is_set_aside(w: KidsWorld):
    """A sidecar that validates but was not written with the save beside it is someone else's: it is set
    aside, never deleted and never rotated."""
    _two_saves(w)
    backup_side, slot_side = w.fs.read(w.sidecar_path(21)), w.fs.read(w.sidecar_path(1))
    w.fs.files[w.fs.key(w.save_path(21))] = b"A BACKUP FROM ELSEWHERE"
    w.save_content[1] = b"THIRD"
    assert w.save(1) == 1 and w.status()["lastSave"] == 1
    assert w.fs.read(_aside(w, 21)) == backup_side, "the foreign backup sidecar is kept, unchanged"
    assert w.fs.read(w.sidecar_path(21)) == slot_side
    # this slot's own sidecar, when its save was changed elsewhere, is foreign too: set aside, not rotated
    side_before = w.fs.read(w.sidecar_path(1))
    w.fs.files[w.fs.key(w.save_path(1))] = b"EDITED ELSEWHERE"
    w.save_content[1] = b"FOURTH"
    assert w.save(1) == 1 and w.status()["lastSave"] == 1
    assert w.fs.read(_aside(w, 1)) == side_before
    assert not w.fs.exists(w.sidecar_path(21)), "an unvalidated sidecar is never rotated onto the backup"
    assert not w.fs.exists(_aside(w, 21, 2)), "the backup's own validated sidecar goes with its save"
    assert w.sidecar(1)["save_hash"] == fnv(b"FOURTH")


def scenario_shut_sidecar_is_retried_never_set_aside(w: KidsWorld):
    """A sidecar another program holds open is tried again, never judged damaged, never set aside, and
    never replaced by a save that would drop the children it records."""
    w.start_family()
    w.have_children(8)
    w.report_death(8)
    w.set_active(8, 0)
    assert w.save(1) == 1
    side = w.fs.read(w.sidecar_path(1))
    held = [(8, DEAD), (9, ALIVE)]
    # held briefly: the open is tried again and the load is exact
    for error in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION, ERROR_ACCESS_DENIED):
        w.reset_tree()
        w.start_family()
        w.have_children(6)
        w.fs.sleeps.clear()
        w.fs.hold(w.sidecar_path(1), opens=OPEN_TRIES - 1, error=error)
        assert w.load(1) == 1 and w.status()["lastLoad"] == 1, error
        assert [(e[0], e[2]) for e in w.extras()] == held
        assert len(w.fs.sleeps) == OPEN_TRIES - 1 and sum(w.fs.sleeps) <= 1200
    # held throughout: left exactly as it is
    w.reset_tree()
    w.start_family()
    w.have_children(6)
    w.fs.sleeps.clear()
    w.fs.hold(w.sidecar_path(1))
    assert w.load(1) == 1 and w.status()["lastLoad"] == 6
    assert len(w.fs.sleeps) == OPEN_TRIES - 1, "a shut open is tried a bounded number of times"
    assert w.extras() == []
    assert w.fs.read(w.sidecar_path(1)) == side and not w.fs.exists(_aside(w, 1))
    # a save while it is still shut writes nothing over it and moves nothing
    w.have_children(1, first_slot=10)
    assert w.save(1) == 1 and w.status()["lastSave"] == 4
    assert w.fs.read(w.sidecar_path(1)) == side and not w.fs.exists(_aside(w, 1))
    assert not w.fs.exists(w.sidecar_path(21))
    # released: the next save reads it, keeps everything it records (it was written with the save the
    # game has since moved to slot + 20, so its dead child still counts) and adds what this session added
    w.fs.release(w.sidecar_path(1))
    assert w.save(1) == 1 and w.status()["lastSave"] == 1
    entries = [(x["slot"], x["state"]) for x in w.sidecar(1)["entries"]]
    assert entries == [(10, ALIVE), (8, DEAD), (9, ALIVE)], entries
    assert not w.fs.exists(_aside(w, 1))


def scenario_long_path_set_aside(w: KidsWorld):
    """The longest save path the game can make: the damaged sidecar is set aside; when even the set-aside
    name cannot be made, the file is left exactly as it is (never deleted) and no save replaces it."""
    base = "C:\\" + "\\".join(["L" * 60] * 3) + "\\"
    w.save_dir = base
    w.save_dir = base + "D" * (257 - len(w.save_path(1)))   # slot 21's save path is then 258, the most there is
    w.fs.mkdirs(w.save_dir)
    w.fs.mkdirs(w.fs.parent(w.sidecar_path(1)))             # a file system that takes long paths
    assert len(w.save_path(1)) == 257 and len(w.sidecar_path(1)) > 260 + 24
    w.start_family()
    w.have_children(8)
    assert w.save(1) == 1 and w.status()["lastSave"] == 1
    good = w.fs.read(w.sidecar_path(1))
    w.fs.files[w.fs.key(w.sidecar_path(1))] = b"damaged"
    w.reset_tree()
    w.start_family()
    w.have_children(6)
    assert w.load(1) == 1 and w.status()["lastLoad"] == 5
    assert w.fs.read(_aside(w, 1)) == b"damaged" and not w.fs.exists(w.sidecar_path(1))
    # the set-aside name does not fit (the file system refuses it): nothing is deleted
    w.fs.files[w.fs.key(w.sidecar_path(1))] = b"damaged again"
    w.fs.max_path = len(w.sidecar_path(1))
    assert w.load(1) == 1 and w.status()["lastLoad"] == 7
    assert w.fs.read(w.sidecar_path(1)) == b"damaged again"
    w.have_children(2, first_slot=8)
    assert w.save(1) == 1 and w.status()["lastSave"] == 4
    assert w.fs.read(w.sidecar_path(1)) == b"damaged again", "a damaged file that cannot be set aside is kept"
    assert good != b"damaged again"


ALL = [
    scenario_six_stock_then_extras, scenario_free_slots_cap, scenario_deaths_count_toward_28,
    scenario_rename_and_reused_slot, scenario_next_generation_candidates, scenario_six_or_fewer_is_stock,
    scenario_full_house, scenario_sidecar_round_trip, scenario_sidecar_follows_backup,
    scenario_unreadable_sidecar_is_kept_aside, scenario_other_family_is_ignored,
    scenario_unreadable_backup_is_set_aside,
    scenario_foreign_backup_is_set_aside,
    scenario_shut_sidecar_is_retried_never_set_aside,
    scenario_long_path_set_aside,
]
FACTORY = [scenario_births_near_the_limit, scenario_stock_odds_unchanged, scenario_limit_counts_lifetime_births]


def scenario_stock_when_off(w: KidsWorld):
    status, writes = w.test_plan(False)
    assert status == 0 and writes == [] and not w.changed_code()
    w.start_family()
    for k in range(6):
        w.set_villager(2 + k, f"Kid {k + 1}", k % 2)
        assert w.add_offspring(2 + k) == 1
    w.set_villager(8, "Kid 7", 0)
    assert w.add_offspring(8) == 0 and w.empty_slots() == 0


OFF = [scenario_stock_when_off]
