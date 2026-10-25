"""Scenarios for the Family Logs DLL (vf1logs.dll), run under tests/kids_emu.py.

A LogsWorld is the REAL vanilla Virtual Families executable and the REAL compiled test DLL in one unicorn
address space. The DLL installs itself through its own VF1Logs_Startup (the real verify / plan / apply path),
and every hook is then reached the way the game reaches it: by running the game's OWN instructions at each
hooked call (the conception plan step 0x48EB99..0x48EBB7, the realtime update 0x424F8E..0x424F98, the death
behaviour's end 0x48E1FA..0x48E205, the body removal 0x489D7F..0x489D94, the menu's Start Over
0x448423..0x44842B, the age-19 leaving 0x489EC3..0x489ECA) or by a direct call of a hooked entry, as vf1fun.dll
makes them.

Game code that runs for real: CVillager::Impregnate (whole), the delivery block of the physiology pass
(0x48C073..0x48C307, entered with the pass's own frame), CFamilyTree::ReportDeath, CountSurvivingChildren,
UpdateParents (with FindPeepRecord and the game's string copy), AddOffspring, StartFamilyTree, Reset,
StartNextGeneration, CVillager::SetLeftHome.

Stand-ins (each pops exactly what the real routine pops): theGameState::Load / ::Save (thiscall, ret 4),
theGameState::Restart (ret), MakeGameStatePath (ret 4), theStringManager::Get (cdecl) and ::GetString (ret 4,
answering with the address of the executable's OWN text for the id), GetMatriarch / GetPatriarch (ret),
UpdatePeepRecord (ret 4), UpdateCurrentFamilyRecord (ret), CGameTime::Seconds (ret), GetSecondsFromGameStart
(ret), ldwGameState::GetRandom (cdecl, scripted), the spawn calls Impregnate makes (ret 30h / ret 4), the
achievement counter (ret 8), the gender chooser (ret), the baby behaviour call 0x486A10 (ret 4); the DLL's
Win32 imports run over an in-memory file system.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import vf1_logs_sites as L  # noqa: E402

from kids_emu import Emu, EmuError  # noqa: E402
from unicorn import UC_HOOK_CODE  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,  # noqa: E402
                               UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

STRIDE = L.VILLAGER_STRIDE
SAVE_DIR = "C:\\Users\\Tester\\Documents\\LDW\\VF1 Logs Test"
DLL_PATH = "C:\\Game\\Virtual Families 1 Patcher Files\\vf1logs.dll"
INVALID = 0xFFFFFFFF
ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND, ERROR_ALREADY_EXISTS, ERROR_DIR_NOT_EMPTY = 2, 3, 183, 145
FILE_APPEND_DATA = 4

UPDATE_PEEP_RECORD, UPDATE_CURRENT_FAMILY_RECORD = 0x4818F0, 0x481960
GET_RANDOM, SPAWN_FULL, SPAWN_TWIN = 0x403650, 0x48B2E0, 0x48B350
INCREMENT_PROGRESS, GENDER_CHOICE = 0x413210, 0x48BBF0
GAME_SECONDS, SECONDS_FROM_START, BABY_BEHAVIOUR = 0x422320, 0x4036D0, 0x486A10
START_FAMILY_TREE = 0x481E00
STAMP = "[2026-10-24 12:34:56] "


def s32(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


class FileSystem:
    """The DLL's ANSI Win32 file imports over a dict (case-insensitive paths)."""

    def __init__(self):
        self.files = {}
        self.dirs = set()
        self.handles = {}
        self.finds = {}
        self.next = 0x100
        self.last_error = 0
        self.log = []

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

    def text(self, path):
        raw = self.read(path)
        return None if raw is None else raw.decode("latin-1")

    def under(self, folder):
        k = self.key(folder) + "\\"
        return sorted(f for f in self.files if f.startswith(k))

    def bind(self, emu):
        fs = self

        def create(e):
            path = e.cstr(e.arg(0))
            access, disposition = e.arg(1), e.arg(4)
            k = fs.key(path)
            fs.log.append(("CreateFileA", path, disposition))
            if fs.parent(path) not in fs.dirs:
                fs.last_error = ERROR_PATH_NOT_FOUND
                return INVALID, 28
            exists = k in fs.files
            if disposition == 3 and not exists:
                fs.last_error = ERROR_FILE_NOT_FOUND
                return INVALID, 28
            if disposition == 2 or (disposition == 4 and not exists):
                fs.files[k] = b""
            elif disposition not in (3, 4):
                raise EmuError(f"CreateFileA disposition {disposition}")
            h = fs.next
            fs.next += 4
            fs.handles[h] = {"key": k, "data": bytearray(fs.files[k]), "pos": 0,
                             "append": bool(access & FILE_APPEND_DATA) and not access & 0x40000000,
                             "write": disposition in (2, 4) or bool(access & 0x40000000)}
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
            st["write"] = True
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

        def rmdir(e):
            path = e.cstr(e.arg(0))
            k = fs.key(path)
            if any(f.startswith(k + "\\") for f in fs.files) or any(d.startswith(k + "\\") for d in fs.dirs):
                fs.last_error = ERROR_DIR_NOT_EMPTY
                return 0, 4
            fs.dirs.discard(k)
            fs.log.append(("RemoveDirectoryA", path))
            return 1, 4

        def move(e):
            src, dst, flags = e.cstr(e.arg(0)), e.cstr(e.arg(1)), e.arg(2)
            ks, kd = fs.key(src), fs.key(dst)
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
            if fs.files.pop(fs.key(path), None) is None:
                fs.last_error = ERROR_FILE_NOT_FOUND
                return 0, 4
            return 1, 4

        def attributes(e):
            k = fs.key(e.cstr(e.arg(0)))
            if k in fs.dirs:
                return 0x10, 4
            if k in fs.files:
                return 0x80, 4
            fs.last_error = ERROR_FILE_NOT_FOUND
            return INVALID, 4

        def find_entry(e, data, name, is_dir):
            e.write(data, b"\0" * 320)
            e.w32(data, 0x10 if is_dir else 0x80)
            e.write(data + 44, name.encode("latin-1") + b"\0")

        def find_first(e):
            pattern = e.cstr(e.arg(0))
            assert pattern.endswith("\\*"), pattern
            folder = fs.key(pattern[:-2])
            if folder not in fs.dirs:
                fs.last_error = ERROR_PATH_NOT_FOUND
                return INVALID, 8
            names = []
            for d in sorted(fs.dirs):
                if d.startswith(folder + "\\") and "\\" not in d[len(folder) + 1:]:
                    names.append((d[len(folder) + 1:], True))
            for f in sorted(fs.files):
                if f.startswith(folder + "\\") and "\\" not in f[len(folder) + 1:]:
                    names.append((f[len(folder) + 1:], False))
            names = [(".", True), ("..", True)] + names
            h = fs.next
            fs.next += 4
            fs.finds[h] = names[1:]
            find_entry(e, e.arg(1), *names[0])
            return h, 8

        def find_next(e):
            rest = fs.finds[e.arg(0)]
            if not rest:
                fs.last_error = 18
                return 0, 8
            find_entry(e, e.arg(1), *rest.pop(0))
            return 1, 8

        def local_time(e):
            e.write(e.arg(0), struct.pack("<8H", 2026, 10, 6, 24, 12, 34, 56, 0))
            return 0, 4

        emu.imports.update({
            "CreateFileA": create, "ReadFile": read_file, "WriteFile": write_file, "CloseHandle": close,
            "FlushFileBuffers": lambda e: (1, 4), "CreateDirectoryA": mkdir, "RemoveDirectoryA": rmdir,
            "MoveFileExA": move, "DeleteFileA": delete, "GetFileAttributesA": attributes,
            "SetFileAttributesA": lambda e: (1, 8), "FindFirstFileA": find_first, "FindNextFileA": find_next,
            "FindClose": lambda e: (fs.finds.pop(e.arg(0), None), 1)[1:] + (4,),
            "GetLastError": lambda e: (fs.last_error, 0), "GetLocalTime": local_time,
        })


class LogsWorld:
    """One emulated process: the vanilla Virtual Families executable + the Family Logs test DLL."""

    def __init__(self, exe, dll, setting=1, before_install=None, install=True):
        self.exe_path = exe
        self.e = Emu(exe, dll, 0)
        self.exe = L.Exe(Path(exe).read_bytes())
        self.fs = FileSystem()
        self.fs.bind(self.e)
        self.fs.mkdirs(SAVE_DIR)
        self.setting = setting
        self.rolls = []
        self.spawned = []
        self.saves, self.loads, self.restarts = [], [], []
        self.code_before = self._code()
        self.mother, self.father = 0, 1
        self._game_state()
        self._villagers()
        self._seams()
        self._win32()
        if before_install:
            before_install(self)
        self.installed = self.startup() if install else 0

    # ------------------------------------------------------------------ the executable's code
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

    # ------------------------------------------------------------------ Win32 for the install
    def _win32(self):
        e = self.e

        def module_file(emu):
            buf, n = emu.arg(1), emu.arg(2)
            emu.write(buf, (DLL_PATH + "\0").encode("utf-16-le"))
            return len(DLL_PATH), 12

        def profile_int(emu):
            key = emu.wstr(emu.arg(1))
            return (self.setting if key == "FamilyLogs" and self.setting is not None else emu.arg(2)), 16

        def protect(emu):
            emu.w32(emu.arg(3), 0x20)
            return 1, 16

        e.imports.update({
            "GetModuleFileNameW": module_file, "GetPrivateProfileIntW": profile_int, "VirtualProtect": protect,
            "FlushInstructionCache": lambda emu: (1, 12), "GetCurrentProcess": lambda emu: (INVALID, 0),
            "DisableThreadLibraryCalls": lambda emu: (1, 4),
        })

    def startup(self):
        return s32(self.e.call(self.e.dll_export("VF1Logs_Startup"), ()))

    def status(self):
        st = self.e.dll_export("VF1Logs_Status")
        names = ("magic", "version", "requested", "resolved", "installed", "writes", "records", "lastLoad",
                 "lastSave", "wipes")
        return {n: self.e.r32(st + 4 * i) for i, n in enumerate(names)}

    # ------------------------------------------------------------------ the game's state
    def _game_state(self):
        e = self.e
        self.state = e.alloc(0x1B900)
        e.w32(L.GAME_STATE_INSTANCE, self.state)
        for k in range(3):
            e.w32(self.state + L.GAME_STATE_RESERVED_BABY + 4 * k, INVALID)
        e.w32(self.state + 0x1B180, 10)                     # normal speed (the delivery reads it)
        self.set_family_name("Hopkins")
        self.set_slot(1)
        vtable = e.alloc(0x40)
        stub = e.fake_code(b"\xC2\x04\x00")
        e.w32(vtable + L.LDW_PATH_VSLOT, stub)
        e.w32(self.state, vtable)
        self.path_buffer = e.alloc(0x200)

        def make_path(emu):
            emu.write(self.path_buffer, f"{SAVE_DIR}\\Virtual Families{emu.arg(0)}.ldw".encode("ascii") + b"\0")
            return self.path_buffer, 4
        e.seam_live(stub, make_path)
        self.strings = e.alloc(0x40)

    def set_family_name(self, name):
        self.e.write(self.state + L.GAME_STATE_FAMILY_NAME, name.encode("latin-1")[:27].ljust(0x1C, b"\0"))

    def set_slot(self, slot):
        self.slot = slot
        self.e.w32(self.state + L.GAME_STATE_SLOT, slot)

    def villager(self, slot):
        return L.VILLAGER_MANAGER + L.VILLAGER_ARRAY_OFFSET + slot * STRIDE

    def _villagers(self):
        for slot in range(30):
            v = self.villager(slot)
            self.e.w32(v + L.VILLAGER_SLOT, slot)
            self.e.write(v + L.VILLAGER_PRESENT, b"\0")

    def set_villager(self, slot, name, sex, years=26, head=3, body=4, present=1, health=90, career=5):
        e = self.e
        v = self.villager(slot)
        e.write(v + L.VILLAGER_NAME, name.encode("latin-1")[:24].ljust(25, b"\0"))
        e.w32(v + L.VILLAGER_GENDER, sex)
        e.w32(v + L.VILLAGER_HEAD, head)
        e.w32(v + L.VILLAGER_BODY, body)
        e.w32(v + L.VILLAGER_AGE, years * 20)
        e.w32(v + L.VILLAGER_STATE + 8, years * 20)          # age units processed
        e.w32(v + L.VILLAGER_HEALTH, health)
        e.w32(v + L.VILLAGER_CAUSE, INVALID)
        e.w32(v + L.VILLAGER_CAREER, career)
        e.write(v + L.VILLAGER_PRESENT, bytes([present]))
        e.write(v + L.VILLAGER_LEFT_HOME, b"\0")
        e.write(v + L.VILLAGER_BIO_PARENT1, b"\0" * 52)

    def generations(self):
        return s32(self.e.r32(L.FAMILY_TREE))

    # ------------------------------------------------------------------ files
    def root(self, slot=None):
        return f"{SAVE_DIR}\\Virtual Families 1 Patcher\\Save {slot or self.slot}"

    def log_path(self, sub, stem, n=1, slot=None):
        return f"{self.root(slot)}\\Logs\\{sub}\\{stem} {n}.txt"

    def history(self, slot=None, n=1):
        return self.fs.text(self.log_path("Family History", "Family History", n, slot))

    def births(self, slot=None, n=1):
        return self.fs.text(self.log_path("Births and Conceptions", "Virtual Families 1 Births and Conceptions Log", n, slot))

    def deaths(self, slot=None, n=1):
        return self.fs.text(self.log_path("Deaths", "Virtual Families 1 Deaths Log", n, slot))

    def events(self, slot=None, n=1):
        return self.fs.text(self.log_path("Events", "Virtual Families 1 Events Log", n, slot))

    def snapshot(self, sub, slot=None):
        s = slot or self.slot
        return self.fs.text(f"{self.root(s)}\\Logs\\{sub}\\{sub} - Save {s}.txt")

    def data(self, kind, stem, slot=None):
        s = slot or self.slot
        return self.fs.text(f"{self.root(s)}\\Data\\{kind}\\{stem} - Save {s}.dat")

    def history_lines(self, slot=None):
        text = self.history(slot) or ""
        return [line for line in text.split("\r\n") if line.startswith("[")]

    # ------------------------------------------------------------------ seams
    def _seams(self):
        e = self.e
        e.seam_live(UPDATE_PEEP_RECORD, lambda emu: (0, 4))
        e.seam_live(UPDATE_CURRENT_FAMILY_RECORD, lambda emu: (0, 0))
        e.seam_live(L.STRINGS_GET, lambda emu: (self.strings, 0))

        def get_string(emu):
            assert emu.ecx == self.strings, "GetString on something other than theStringManager"
            return self.exe.string_record(emu.arg(0))[0], 4
        e.seam_live(L.FUNCTIONS["STRINGS_GET_STRING"], get_string)
        e.seam_live(L.FUNCTIONS["VM_GET_MATRIARCH"], lambda emu: (self.villager(self.mother) if self.mother is not None else 0, 0))
        e.seam_live(L.FUNCTIONS["VM_GET_PATRIARCH"], lambda emu: (self.villager(self.father) if self.father is not None else 0, 0))
        e.seam_live(GAME_SECONDS, lambda emu: (4321, 0))
        e.seam_live(SECONDS_FROM_START, lambda emu: (5000, 0))
        e.seam_live(BABY_BEHAVIOUR, lambda emu: (0, 4))

        def get_random(emu):
            return (self.rolls.pop(0) if self.rolls else 0), 0
        e.seam_live(GET_RANDOM, get_random)

        def spawn(pop):
            def fn(emu):
                reserved = {s32(e.r32(self.state + L.GAME_STATE_RESERVED_BABY + 4 * k)) for k in range(3)}
                for slot in range(30):
                    v = self.villager(slot)
                    if not e.read(v + L.VILLAGER_PRESENT, 1)[0] and slot not in reserved and slot not in self.spawned:
                        self.set_villager(slot, self.baby_names.pop(0) if self.baby_names else f"Baby{slot}",
                                          slot % 2, years=0, career=INVALID)
                        e.w32(v + L.VILLAGER_AGE, 40)
                        self.spawned.append(slot)
                        return slot, pop
                return INVALID, pop
            return fn
        self.baby_names = []
        e.seam_live(SPAWN_FULL, spawn(0x30))
        e.seam_live(SPAWN_TWIN, spawn(4))
        e.seam_live(INCREMENT_PROGRESS, lambda emu: (0, 8))
        e.seam_live(GENDER_CHOICE, lambda emu: (INVALID, 0))

        def load(emu):
            self.loads.append(emu.arg(0))
            if self.on_load:
                self.on_load(emu.arg(0))
            return 1, 4

        def save(emu):
            self.saves.append(emu.arg(0))
            return 1, 4
        self.on_load = None
        e.seam_live(L.FUNCTIONS["GS_LOAD"], load)
        e.seam_live(L.FUNCTIONS["GS_SAVE"], save)
        e.seam_live(L.FUNCTIONS["GS_RESTART"], lambda emu: (self.restarts.append(emu.ecx), (0, 0))[1])
        self._delivery_seams()

    # The physiology pass's stand-in: the REAL delivery block for each villager, in the pass's own frame
    # ([esp+10h] theGameState, [esp+18h] the manager, esi = villager + 13578h), then a plain ret.
    def _delivery_seams(self):
        e = self.e
        self.pass_queue = []
        self.pass_ctx = None

        def enter(emu):
            esp = emu.reg(UC_X86_REG_ESP)
            regs = {r: emu.reg(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)}
            self.pass_ctx = {"ret": emu.r32(esp), "esp": esp, "regs": regs,
                             "queue": [s for s in range(30) if s32(e.r32(self.villager(s) + L.VILLAGER_PREGNANT))]}
            self.passes = getattr(self, "passes", 0) + 1
            if not self._next_villager():
                self._leave()

        def block_end(uc, address, size, user):
            if self.pass_ctx is None:
                return
            if not self._next_villager():
                self._leave()
        self._seam_code(L.FUNCTIONS["VM_PHYSIOLOGY"], enter)
        e.uc.hook_add(UC_HOOK_CODE, block_end, begin=0x48C307, end=0x48C307)

    def _seam_code(self, addr, fn):
        def cb(uc, address, size, user):
            fn(self.e)
        self.e.uc.hook_add(UC_HOOK_CODE, cb, begin=addr, end=addr)

    def _next_villager(self):
        e = self.e
        ctx = self.pass_ctx
        if not ctx["queue"]:
            return False
        slot = ctx["queue"].pop(0)
        frame = ctx["esp"] - 0x400
        e.w32(frame + 0x10, self.state)
        e.w32(frame + 0x18, L.VILLAGER_MANAGER)
        e.setreg(UC_X86_REG_ESP, frame)
        e.setreg(UC_X86_REG_ESI, self.villager(slot) + L.VILLAGER_LEFT_HOME)
        e.setreg(UC_X86_REG_EIP, 0x48C073)
        return True

    def _leave(self):
        e = self.e
        ctx = self.pass_ctx
        self.pass_ctx = None
        for r, v in ctx["regs"].items():
            e.setreg(r, v)
        e.setreg(UC_X86_REG_ESP, ctx["esp"] + 4)
        e.setreg(UC_X86_REG_EIP, ctx["ret"])

    # ------------------------------------------------------------------ running the game's own code
    def run(self, start, stop, **regs):
        e = self.e
        e.setreg(UC_X86_REG_ESP, e.sp_top)
        names = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
                 "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}
        for k, v in regs.items():
            e.setreg(names[k], v)
        try:
            e.uc.emu_start(start, stop)
        except Exception as ex:  # pragma: no cover
            raise EmuError(f"stopped at {e.reg(UC_X86_REG_EIP):#x}: {ex}") from ex
        if e.reg(UC_X86_REG_EIP) != stop:
            raise EmuError(f"ended at {e.reg(UC_X86_REG_EIP):#x}, not {stop:#x}")
        if e.reg(UC_X86_REG_ESP) != e.sp_top:
            raise EmuError(f"the stack is off by {e.reg(UC_X86_REG_ESP) - e.sp_top:#x}")

    def start_family(self, slot=0, name="Ann", sex=1, years=26):
        self.set_villager(slot, name, sex, years=years)
        r = self.e.call(START_FAMILY_TREE, (self.villager(slot),), ecx=L.FAMILY_TREE) & 0xFF
        assert r == 1

    def marry(self, a, b):
        return self.e.call(L.FUNCTIONS["FT_UPDATE_PARENTS"], (self.villager(a), self.villager(b)), ecx=L.FAMILY_TREE) & 0xFF

    def conceive(self, rolls=(), names=()):
        """The try-for-a-baby plan step's own Impregnate call (0x48EB99..0x48EBB7): edi = matriarch, ebx =
        patriarch."""
        self.rolls = list(rolls)
        self.baby_names = list(names)
        self.spawned = []
        e = self.e
        e.w32(self.villager(self.mother) + 0x2B20, 0)
        e.w32(self.villager(self.father) + 0x2B20, 0)
        self.run(0x48EB99, 0x48EBB7, ebx=self.villager(self.father), edi=self.villager(self.mother))
        return e.reg(UC_X86_REG_EAX) & 0xFF

    def physiology(self, age_on=21):
        """theGameState's realtime update calls the physiology pass (0x424F8E..0x424F98). `age_on`: the
        mother's processed age moves past conception + 20, so the delivery is due."""
        for s in range(30):
            v = self.villager(s)
            preg = s32(self.e.r32(v + L.VILLAGER_PREGNANT))
            if preg:
                self.e.w32(v + L.VILLAGER_STATE + 8, preg + age_on)
        self.run(0x424F8E, 0x424F98)

    def die(self, slot, cause=2, how="behaviour"):
        v = self.villager(slot)
        self.e.w32(v + L.VILLAGER_HEALTH, 0)
        self.e.w32(v + L.VILLAGER_CAUSE, cause)
        if how == "behaviour":
            self.run(0x48E1FA, 0x48E205, edi=v)
        else:
            self.run(0x489D7F, 0x489D94, esi=v + L.VILLAGER_LEFT_HOME)

    def leave_home(self, slot):
        self.run(0x489EC3, 0x489ECA, ebp=self.villager(slot))

    def add_offspring(self, slot):
        return self.e.call(L.FUNCTIONS["FT_ADD_OFFSPRING"], (self.villager(slot),), ecx=L.FAMILY_TREE) & 0xFF

    def next_generation(self, heir, source):
        return self.e.call(L.FUNCTIONS["FT_START_NEXT_GEN"], (self.villager(heir), source & 0xFFFFFFFF),
                           ecx=L.FAMILY_TREE) & 0xFF

    def save(self, slot=None):
        fn = self.e.r32(L.GS_VTABLE_SAVE)
        return self.e.call(fn, (slot or self.slot,), ecx=self.state) & 0xFF

    def load(self, slot=None):
        fn = self.e.r32(L.GS_VTABLE_LOAD)
        return self.e.call(fn, (slot or self.slot,), ecx=self.state) & 0xFF

    def start_over(self):
        holder = self.e.alloc(0x20)
        self.e.w32(holder + 0xC, self.state)
        self.run(0x448423, 0x44842B, esi=holder)

    def event(self, kind, a=-1, amount=0):
        self.e.call(self.e.dll_export("VF1Logs_Event"), (kind, a & 0xFFFFFFFF, INVALID, amount))

    def logged(self, slot):
        return s32(self.e.call(self.e.dll_export("VF1Logs_TestLogged"), (slot,)))

    def reset_tree(self):
        self.e.write(L.FAMILY_TREE, b"\0" * (4 + 30 * L.FAMILY_RECORD_SIZE))

    # ------------------------------------------------------------------ a real save in memory
    def load_save_image(self, data: bytes, slot=1):
        """Put a real save's payload where the game's LoadState calls put it: the tree's 30 records, the
        villagers' records, the family name, the unborn babies, food, money and the statistics."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "patcher"))
        import vf1_save as vs
        header = vs.parse_header(data)
        payload = data[header.size:]

        def gs(off, n):
            return payload[off - vs.GS_BASE: off - vs.GS_BASE + n]
        e = self.e
        tree = gs(vs.GS_FAMILY_TREE, vs.FAMILY_RECORDS * vs.FAMILY_RECORD)
        e.write(L.FAMILY_TREE + 4, tree)
        count = 0
        while count < 30 and tree[count * vs.FAMILY_RECORD]:
            count += 1
        e.w32(L.FAMILY_TREE, count)                      # LoadState counts the leading used records
        for k in range(30):
            rec = gs(vs.GS_VILLAGERS + k * vs.VILLAGER_RECORD, vs.VILLAGER_RECORD)
            v = self.villager(k)
            e.write(v + L.VILLAGER_PRESENT, rec[0:1])
            e.write(v + L.VILLAGER_LEFT_HOME, rec[1:2])
            e.write(v + 0x2A34, rec[8:8 + 0xA0])         # CVillagerBio
            e.write(v + 0x2AD4, rec[0xA8:0xA8 + 0x98])   # CVillagerState
            e.write(v + 0x2B6C, rec[0x140:0x150])        # CVillagerSkills
            e.w32(v + L.VILLAGER_SLOT, k)
        e.write(self.state + L.GAME_STATE_RESERVED_BABY, gs(vs.GS_PENDING_BABIES, 12))
        e.write(self.state + L.GAME_STATE_FAMILY_NAME, gs(vs.GS_FAMILY_NAME, 0x1C))
        e.write(L.FOOD, gs(vs.GS_FOOD, 4))
        e.write(0x50C560, gs(vs.GS_STATS, 0x34))
        e.write(L.MONEY, gs(vs.GS_MONEY, 4))
        self.set_slot(slot)
        return vs.parse_save(data)
