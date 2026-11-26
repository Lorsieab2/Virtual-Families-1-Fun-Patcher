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
        # address would both return. This world's stand-in, below, is the creator at any age. Its GetMatriarch and
        # GetPatriarch stand-ins are not installed either: here the game's own run (who may have a baby).
        e.seam_live = lambda addr, fn: None if addr in (0x48B2E0, 0x489950, 0x4899C0) else plain(addr, fn)
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
        e.seam_live(0x48FC10, lambda emu: (1, 0xC))            # ChanceOfPregnancy: yes (the tests are of who)

        e.dyn_procs.update({
            "VF1Kids_IsExtraChild": self._kids_is_extra,
            "VF1Kids_Revived": self._kids_revived,
        })

    def _island_events(self):
        """Not used here: the Family History harness's event dialog stand-in would take every DoModal (0x401B10),
        and the Family Tree screen's person dialog is run through DoModal too."""
        self.e.seam_live(0x401B10, lambda emu: (0, 8))       # DoModal(parent, update parent): the dialog closes

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

    def at_19(self, slot):
        """The ageing pass at the 19-year mark (380 units), the game's own code from its age test (0x489E96): "leaves"
        when it reaches the leaving (its SetLeftHome call, 0x489EC5), "stays" when it jumps past it (0x489EE4)."""
        from unicorn import UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP
        e, v = self.e, self.villager(slot)
        e.w32(v + L.VILLAGER_AGE, 380)
        e.setreg(UC_X86_REG_ESP, e.sp_top)
        e.setreg(UC_X86_REG_EBP, 379)                          # the age before this pass
        e.setreg(UC_X86_REG_EDI, v + L.VILLAGER_AGE)
        e.setreg(UC_X86_REG_ESI, v + L.VILLAGER_LEFT_HOME)
        seen = []

        def at(uc, address, size, user):
            seen.append(address)
            uc.emu_stop()
        hooks = [e.uc.hook_add(UC_HOOK_CODE, at, begin=a, end=a) for a in (0x489EC5, 0x489EE4)]
        try:
            e.uc.emu_start(0x489E96, 0x489EE5)
        finally:
            for h in hooks:
                e.uc.hook_del(h)
        assert seen and e.reg(UC_X86_REG_EIP) == seen[0], seen
        return "leaves" if seen[0] == 0x489EC5 else "stays"

    def run_to(self, start, stops, **regs):
        """The game's own code from `start` until it reaches the first of `stops` (returned)."""
        from unicorn import UC_HOOK_CODE
        from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                                       UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)
        e = self.e
        names = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "esi": UC_X86_REG_ESI,
                 "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP}
        e.setreg(UC_X86_REG_ESP, e.sp_top - 0x400)
        for k, v in regs.items():
            e.setreg(names[k], v)
        seen = []

        def at(uc, address, size, user):
            seen.append(address)
            uc.emu_stop()
        hooks = [e.uc.hook_add(UC_HOOK_CODE, at, begin=a, end=a) for a in stops]
        try:
            e.uc.emu_start(start, 0xFFFFFFF0)
        finally:
            for h in hooks:
                e.uc.hook_del(h)
        assert seen and e.reg(UC_X86_REG_EIP) == seen[0], seen
        return seen[0]

    def try_for_a_baby(self, actor):
        """The try-for-a-baby step, the game's own code from its parent choice (0x48EB33: GetMatriarch the mother,
        GetPatriarch the father) through the pregnancy roll (a stand-in that says yes) and CVillager::Impregnate, for
        the woman in slot `actor`. Returns (mother slot, father slot, pregnant) or None when the step gives up."""
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDI
        e = self.e
        plan = e.alloc(0x80)
        self.rolls = [99, 99]                                  # a single baby
        self.baby_names = ["Newt"]
        self.spawned = []
        for s in range(30):
            e.w32(self.villager(s) + 0x2B20, 0)               # fertility 0: no twins
        stop = self.run_to(0x48EB33, (0x48EBB7, 0x48EE5A), ebx=plan, ebp=self.villager(actor))
        if stop == 0x48EE5A:
            return None
        slot = lambda r: (e.reg(r) - self.villager(0)) // L.VILLAGER_STRIDE  # noqa: E731
        mother, father = slot(UC_X86_REG_EDI), slot(UC_X86_REG_EBX)
        return mother, father, bool(e.reg(UC_X86_REG_EAX) & 0xFF) and s32(e.r32(self.villager(mother) + 0x2AF8)) != 0

    def drop_on_spouse_careers(self, a, b):
        """A drop on the spouse: the game's own test that both have a career (0x441224..0x44125D): "both" or "no"."""
        stop = self.run_to(0x441224, (0x44125D, 0x4413A1), eax=400, ebp=380, edi=self.villager(a),
                           esi=self.villager(b))
        return "both" if stop == 0x44125D else "no"

    # ------------------------------------------------------------------ the Family Tree screen
    SCENE = {8: 0, 0xC: 0, 0x10: 800, 0x14: 1200, 0x68: 34, 0x6C: 20, 0x70: 143, 0x74: 120, 0x78: 300, 0x7C: 40,
             0x80: 400, 0x84: 114, 0x88: 250}

    def _tree_screen(self):
        """A Family Tree screen object with the layout fields its row draw and click read, and recorders for what it
        draws: the frames and images (0x44F960), the names (DrawString 0x409CC0), the portraits (0x439790), the
        shade of the dead (0x409A80)."""
        e = self.e
        if getattr(self, "scene", None) is None or self.scene == getattr(self, "_main_scene", None):
            self._main_scene = self.scene
        if hasattr(self, "tree_scene"):
            return self.tree_scene
        scene = e.alloc(0x200)
        for off, v in self.SCENE.items():
            e.w32(scene + off, v)
        gfx, images, image = e.alloc(0x40), e.alloc(0x40), e.alloc(0x40)
        e.w32(self.strings, e.alloc(0x40))                 # theStringManager's first font
        self.drawn = {"images": [], "texts": [], "portraits": [], "shades": []}
        self.dialogs = []
        e.seam_live(0x4080B0, lambda emu: (gfx, 0))
        e.seam_live(0x44F7C0, lambda emu: (images, 0))
        e.seam_live(0x408410, lambda emu: (0, 0x10))
        e.seam_live(0x408440, lambda emu: (0, 0))
        e.seam_live(0x438D70, lambda emu: (0, 0xC))

        def image_draw(emu):
            self.drawn["images"].append({"id": emu.arg(0), "x": s32(emu.arg(1)), "y": s32(emu.arg(2))})
            return 0, 0x14
        e.seam_live(0x44F960, image_draw)

        def text(emu):
            self.drawn["texts"].append({"text": e.read(emu.arg(0), 26).split(b"\0")[0], "x": s32(emu.arg(1)),
                                        "y": s32(emu.arg(2)), "colour": emu.arg(3), "font": emu.arg(4)})
            return 0, 0x14
        e.seam_live(0x409CC0, text)
        e.seam_live(0x409D20, text)

        def portrait(emu):
            self.drawn["portraits"].append({"x": s32(emu.arg(1)), "y": s32(emu.arg(2)), "sex": s32(emu.arg(3)),
                                            "head": s32(emu.arg(4)), "body": s32(emu.arg(5))})
            return 0, 0x1C
        e.seam_live(0x439790, portrait)
        e.seam_live(0x44F860, lambda emu: (image, 4))
        e.seam_live(0x409A80, lambda emu: (self.drawn["shades"].append(1), (0, 4))[1])
        e.seam_live(0x40ACE0, lambda emu: (248, 0))       # the parent frame's width and height
        e.seam_live(0x40ACF0, lambda emu: (91, 0))
        e.seam_live(0x40ADD0, lambda emu: (1, 8))         # its pixels: hit

        def dialog(emu):
            p = emu.arg(0)
            self.dialogs.append((e.read(p, 26).split(b"\0")[0], s32(e.r32(p + 0x1C)), s32(e.r32(p + 0x20)),
                                 s32(e.r32(p + 0x24)), s32(e.r32(p + 0x28))))
            return emu.ecx, 4
        e.seam_live(0x416CF0, dialog)
        e.seam_live(0x4172E0, lambda emu: (0, 0))
        self.tree_scene = scene
        return scene

    def scene_field(self, off):
        return s32(self.e.r32(self._tree_screen() + off))

    def scene_step(self):
        """The step from parent 1 to parent 2 on the screen (the click's own: [esi+74h] - [esi+6Ch] + 2)."""
        return self.scene_field(0x74) - self.scene_field(0x6C) + 2

    def draw_tree_row(self, gen=None):
        """The game's own row draw 0x439BA0 (x, y, generation 0-based), as the screen's draw 0x43A1B0 calls it."""
        from unicorn import UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_EDI
        scene = self._tree_screen()
        for k in self.drawn:
            self.drawn[k] = []
        g = self.generations() - 1 if gen is None else gen
        seen = []
        h = self.e.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: seen.append(self.e.reg(UC_X86_REG_EDI)),
                               begin=0x439E87, end=0x439E87)
        try:
            self.e.call(0x439BA0, (0, 0, g), ecx=scene)
        finally:
            self.e.uc.hook_del(h)
        return dict(self.drawn, edi_after=seen[-1] if seen else None)

    def tree_click(self, mx, my, gen=None):
        """A click on the screen at (mx, my): the screen's mouse handler's own call (0x439B64), i.e. whatever is
        there now (the DLL's handler), with the row at (0, 0). Returns the person dialogs opened."""
        scene = self._tree_screen()
        self.dialogs = []
        g = self.generations() - 1 if gen is None else gen
        target = (0x439B64 + 5 + struct.unpack("<i", self.e.read(0x439B65, 4))[0]) & 0xFFFFFFFF
        self.e.call(target, (0, 0, g, mx, my), ecx=scene)
        return list(self.dialogs)

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
