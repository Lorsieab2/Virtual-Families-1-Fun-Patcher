"""Scenarios for Revive a Family Member's DLL (vf1revive.dll), run under tests/kids_emu.py.

A ReviveWorld is the REAL vanilla Virtual Families executable and the REAL compiled DLL (the very file that ships) in
one unicorn address space, built on the Family History harness (tests/history_scenarios.py): the DLL installs itself
through its own VF1Revive_Startup (the real verify / plan / apply path), and every hook is reached the way the game
reaches it:

* deaths: the death behaviour's end (0x48E1FA..0x48E205) and the body's removal (0x489D7F..0x489D94), the game's
  own code, then the REAL CFamilyTree::ReportDeath;
* saves: the REAL theGameState::SaveCurrentGame (0x4238E0), which saves 0, the slot and the slot + 20 through the
  vtable's Save slot (the DLL's handler, then the stand-in below);
* a load: theGameState's Load slot, as the game calls it.

Game code that runs for real besides: StartFamilyTree, UpdateParents, AddOffspring, CountSurvivingChildren.

Stand-ins (each pops exactly what the real routine pops): theGameState::Save (ret 4: the ldwGameState rotation --
delete n+20, move n to n+20, write n -- of a save whose bytes change with each save), SpawnPeepFull (ret 30h: the
first place FindEmptySlot would give, a new villager at the age asked for with the creator's own fresh values), and
the Family History harness's own (MakeGameStatePath, the strings, Load ...). The DLL's Win32 imports run over the
harness's in-memory file system.
"""
from __future__ import annotations

import struct

from history_scenarios import INVALID, SAVE_DIR, HistoryWorld, s32  # noqa: F401
import vf1_logs_sites as L

GS_SAVE, SAVE_CURRENT, ADD_OFFSPRING, COUNT_SURVIVING = 0x423790, 0x4238E0, 0x481AA0, 0x481850
GS_VTABLE_LOAD, GS_VTABLE_SAVE = 0x4B5E68, 0x4B5E6C
FRESH_HEAD, FRESH_BODY, FRESH_VOICE, FRESH_NAME_INDEX, FRESH_FERTILITY, FRESH_WANTS = 40, 41, 9, 77, 33, 44
FRESH_STATS = (61, 62, 63, 64, 65, 66)
REVIVE_DIR = SAVE_DIR + "\\Virtual Families 1 Patcher Data\\Revive"


class ReviveWorld(HistoryWorld):
    """One emulated process: the vanilla Virtual Families executable + the Revive DLL."""

    def __init__(self, exe, dll, setting=1, **kw):
        self.save_counter = 0
        self.spawn_age_override = None
        self.extra_children = {}          # what vf1kids.dll answers (slot -> (sex, name)), when it is "loaded"
        self.kids_revived = []
        super().__init__(exe, dll, setting=setting, **kw)
        vtable = self.e.r32(self.state)
        self.e.w32(vtable + 0x34, self.e.r32(GS_VTABLE_LOAD))
        self.e.w32(vtable + 0x38, self.e.r32(GS_VTABLE_SAVE))

    # ------------------------------------------------------------------ install
    def _win32(self):
        super()._win32()

        def profile_int(emu):
            key = emu.wstr(emu.arg(1))
            return (self.setting if key == "Revive" and self.setting is not None else emu.arg(2)), 16

        def filetime(emu):
            emu.write(emu.arg(0), struct.pack("<Q", 0x01DC5F0012345678))
            return 0, 4
        self.e.imports.update({"GetPrivateProfileIntW": profile_int, "GetSystemTimeAsFileTime": filetime,
                               "CreateFileW": lambda emu: (INVALID, 28)})

    def startup(self):
        return s32(self.e.call(self.e.dll_export("VF1Revive_Startup"), ()))

    def status(self):
        st = self.e.dll_export("VF1Revive_Status")
        names = ("magic", "version", "requested", "resolved", "installed", "entries", "captured", "lastLoad",
                 "lastSave", "revived")
        return {n: self.e.r32(st + 4 * i) for i, n in enumerate(names)}

    # ------------------------------------------------------------------ stand-ins
    def _seams(self):
        e = self.e
        plain = e.seam_live
        # The Family History harness's own SpawnPeepFull stand-in (a baby's) is not installed: two hooks at one
        # address would both return. This world's stand-in, below, is the creator at any age.
        e.seam_live = lambda addr, fn: None if addr == 0x48B2E0 else plain(addr, fn)
        try:
            super()._seams()
        finally:
            e.seam_live = plain

        def save(emu):
            n = emu.arg(0)
            path = lambda k: f"{SAVE_DIR}\\Virtual Families{k}.ldw"  # noqa: E731
            if n == 0:
                self.fs.write(path(0), b"options")
                return 1, 4
            self.save_counter += 1
            older = self.fs.key(path(n + 20))
            self.fs.files.pop(older, None)
            if self.fs.key(path(n)) in self.fs.files:
                self.fs.files[older] = self.fs.files.pop(self.fs.key(path(n)))
            body = b"ldwg" + struct.pack("<I", self.save_counter) + e.read(L.FAMILY_TREE, 0x200)
            self.fs.write(path(n), body)
            return 1, 4
        e.seam_live(GS_SAVE, save)

        def spawn(emu):
            voice, gender, age = s32(emu.arg(0)), emu.arg(1), emu.arg(2)
            reserved = {s32(e.r32(self.state + L.GAME_STATE_RESERVED_BABY + 4 * k)) for k in range(3)}
            for slot in range(30):
                v = self.villager(slot)
                if e.read(v + L.VILLAGER_PRESENT, 1)[0] or slot in reserved:
                    continue
                self.set_villager(slot, "Fresh", gender, years=0, head=FRESH_HEAD, body=FRESH_BODY, career=INVALID)
                age = self.spawn_age_override if self.spawn_age_override is not None else age
                e.w32(v + L.VILLAGER_AGE, age)
                e.w32(v + L.VILLAGER_STATE + 8, age)
                bio = v + 0x2A34
                e.w32(bio + 8, FRESH_NAME_INDEX)
                e.w32(bio + 0xC, voice if voice != -1 else FRESH_VOICE)
                e.write(bio + 0x34, b"\0" * 0x44)
                for k, at in ((3, 0x34), (4, 0x4E)):
                    p = emu.arg(k)
                    if p:
                        e.write(bio + at, e.read(p, 25))
                for k, at in ((6, 0x68), (5, 0x6C), (8, 0x70), (7, 0x74)):
                    e.w32(bio + at, emu.arg(k))
                st = v + L.VILLAGER_STATE
                for i, s in enumerate(FRESH_STATS):
                    e.w32(st + 0x34 + 4 * i, s)
                e.w32(st + 0x4C, FRESH_FERTILITY)
                e.w32(st + 0x50, FRESH_WANTS)
                e.write(v + 0x13620, b"\0" * 0x18)
                e.write(v + 0x2B6C, struct.pack("<iiii", -1, 0, 10, 0))
                return slot, 0x30
            return INVALID, 0x30
        e.seam_live(0x48B2E0, spawn)
        e.dyn_procs.update({
            "VF1Kids_IsExtraChild": self._kids_is_extra,
            "VF1Kids_Revived": self._kids_revived,
        })

    def _kids_is_extra(self, emu):
        slot, sex, name = s32(emu.arg(0)), emu.arg(1), emu.cstr(emu.arg(2))
        return (1 if self.extra_children.get(slot) == (sex, name) else 0), 0

    def _kids_revived(self, emu):
        self.kids_revived.append((s32(emu.arg(0)), emu.arg(1), emu.cstr(emu.arg(2)), s32(emu.arg(3))))
        return 1, 0

    def load_kids(self):
        """vf1kids.dll is loaded (its two exports answer from extra_children)."""
        self.e.modules["vf1kids.dll"] = 0x6F000000

    # ------------------------------------------------------------------ the game
    def add_child(self, slot, name, sex, years=8, **kw):
        self.set_villager(slot, name, sex, years=years, career=INVALID, **kw)
        assert self.e.call(ADD_OFFSPRING, (self.villager(slot),), ecx=L.FAMILY_TREE) & 0xFF == 1

    def surviving(self):
        return s32(self.e.call(COUNT_SURVIVING, (), ecx=L.FAMILY_TREE))

    def save_game(self):
        """theGameState::SaveCurrentGame, the game's own: Save(0), Save(slot), Save(slot + 20)."""
        return self.e.call(SAVE_CURRENT, (), ecx=self.state) & 0xFF

    def record(self, g=None):
        return L.FAMILY_TREE + (g or self.generations()) * L.FAMILY_RECORD_SIZE - L.FAMILY_RECORD_BASE

    def peep(self, which, g=None):
        rec = self.record(g)
        return rec + (4 if which == 0 else 0xDC if which == 1 else 0x1B8 + (which - 2) * 0xD8)

    # ------------------------------------------------------------------ the DLL's exports
    def count(self):
        return s32(self.e.call(self.e.dll_export("VF1Revive_Count"), ()))

    def info(self, i):
        out = self.e.alloc(4 * 11)
        assert self.e.call(self.e.dll_export("VF1Revive_Info"), (i, out)) & 0xFF == 1
        keys = ("state", "why", "sex", "died_units", "cause", "generation", "role", "exact", "back_units", "source",
                "age_known")
        return {k: s32(self.e.r32(out + 4 * n)) for n, k in enumerate(keys)}

    def name(self, i):
        return self.e.cstr(self.e.call(self.e.dll_export("VF1Revive_Name"), (i,)))

    def revive(self, i):
        how = self.e.alloc(4)
        slot = s32(self.e.call(self.e.dll_export("VF1Revive_Revive"), (i, how)))
        return slot, s32(self.e.r32(how))

    def sidecar(self, n=None):
        return self.fs.read(f"{REVIVE_DIR}\\Virtual Families{n or self.slot}.ldw.dat")

    def save_bytes(self, n=None):
        return self.fs.read(f"{SAVE_DIR}\\Virtual Families{n or self.slot}.ldw")

    def forget(self):
        """The DLL's snapshots in memory are dropped and read back from the file, as a load does."""
        return self.load()
