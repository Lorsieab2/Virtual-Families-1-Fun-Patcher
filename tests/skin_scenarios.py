"""Scenarios for Skin Tones' DLL (vf1skin.dll), run under tests/kids_emu.py: who gets which tone, the file, renames,
Change Appearance, and what Revive keeps.

A SkinWorld is the REAL vanilla Virtual Families executable and the REAL compiled DLL (the very file that ships) in one
unicorn address space, built on Revive's harness (tests/revive_scenarios.py, itself the Family History harness): the
DLL installs itself through its own VF1Skin_Startup (the real verify / plan / apply path), and every hook is reached
the way the game reaches it:

* a conception: the try-for-a-baby step's own Impregnate call (0x48EB99..0x48EBB7), the REAL CVillager::Impregnate
  (it spawns the babies, hidden, in the reserved slots);
* a rename: the Details screen's own ChangeName call (0x44BCF8), the REAL CFamilyTree::ChangeName, then the name copied
  in as the game does (0x44BCFD..0x44BD10);
* saves: the REAL theGameState::SaveCurrentGame (0x4238E0) through the vtable's Save slot; a load: the Load slot.

The draws themselves are tests/test_skin_tone_draw.py's (tests/skin_emu.py). Here the tone a Family Tree draw notes is
read where the DLL keeps it (the blit hook's first instruction compares it with 0) from a stand-in DrawParent / DrawChild
reached through the tree scene's own call instructions.
"""
from __future__ import annotations

import struct

from revive_scenarios import ReviveWorld
from history_scenarios import INVALID, SAVE_DIR, s32  # noqa: F401
import vf1_logs_sites as L

SKIN_DIR = SAVE_DIR + "\\Virtual Families 1 Patcher Data\\Skin Tones"
SDL = 0x6E000000
LOGS = 0x6D000000


class SkinWorld(ReviveWorld):
    def __init__(self, exe, dll, setting=1, logs=True, preferred=None, **kw):
        self.logged = []
        self.preferred = preferred
        self.logs = logs
        self.tree_tones = []
        super().__init__(exe, dll, setting=setting, **kw)

    # ------------------------------------------------------------------ install
    def _win32(self):
        super()._win32()
        e = self.e

        def profile_int(emu):
            section, key = emu.wstr(emu.arg(0)), emu.wstr(emu.arg(1))
            if section == "Patches" and key == "SkinTones" and self.setting is not None:
                return self.setting, 16
            if section == "SkinTones" and key == "PreferredTone" and self.preferred is not None:
                return self.preferred, 16
            return emu.arg(2), 16

        def module_handle(emu):
            name = emu.arg(0)
            if name == 0:
                return emu.base, 4
            n = emu.wstr(name).lower()
            if n == "sdl2.dll":
                return SDL, 4
            if n == "vf1logs.dll":
                return (LOGS if self.logs else 0), 4
            raise AssertionError(f"GetModuleHandleW({n})")

        def module_ex(emu):
            emu.w32(emu.arg(2), 0x30000000)
            return 1, 12

        def counter(emu):
            emu.write(emu.arg(0), struct.pack("<Q", 0x1122334455))
            return 1, 4

        def log_event(emu):
            self.logged.append(tuple(s32(emu.arg(k)) for k in range(4)))
            return 0, 0
        e.imports.update({"GetPrivateProfileIntW": profile_int, "GetModuleHandleW": module_handle,
                          "GetModuleHandleExW": module_ex, "QueryPerformanceCounter": counter,
                          "GetTickCount": lambda emu: (0x51515151, 0), "GetCurrentProcessId": lambda emu: (77, 0)})
        e.dyn_procs.update({"SDL_CreateRGBSurface": lambda emu: (0, 0), "SDL_FreeSurface": lambda emu: (0, 0),
                            "VF1Logs_Event": log_event})

    def startup(self):
        return s32(self.e.call(self.e.dll_export("VF1Skin_Startup"), ()))

    def status(self):
        st = self.e.dll_export("VF1Skin_Status")
        names = ("magic", "version", "requested", "resolved", "installed", "entries", "sheets", "refused", "rows",
                 "bytes", "swapped", "made", "lastLoad", "lastSave", "babies", "preferred")
        return {n: self.e.r32(st + 4 * i) for i, n in enumerate(names)}

    # ------------------------------------------------------------------ the DLL's exports
    def tone(self, slot):
        """(tone, birth) of the slot's person, or None."""
        out = self.e.alloc(8)
        if not self.e.call(self.e.dll_export("VF1Skin_Get"), (slot, out, out + 4)) & 0xFF:
            return None
        return s32(self.e.r32(out)), s32(self.e.r32(out + 4))

    def set_tone(self, slot, tone):
        return self.e.call(self.e.dll_export("VF1Skin_Set"), (slot, tone)) & 0xFF

    def reset_tone(self, slot):
        return self.e.call(self.e.dll_export("VF1Skin_Reset"), (slot,)) & 0xFF

    def tone_of(self, slot):
        out = self.e.alloc(4)
        tone = s32(self.e.call(self.e.dll_export("VF1Skin_ToneOf"), (slot, out)))
        return tone, s32(self.e.r32(out))

    def tone_give(self, slot, tone, birth):
        return self.e.call(self.e.dll_export("VF1Skin_ToneGive"), (slot, tone, birth)) & 0xFF

    def tone_name(self, tone):
        return self.e.cstr(self.e.call(self.e.dll_export("VF1Skin_ToneName"), (tone,)))

    def sidecar(self, n=None):
        return self.fs.read(f"{SKIN_DIR}\\Virtual Families{n or self.slot}.ldw.dat")

    # ------------------------------------------------------------------ the game
    def rename(self, slot, name):
        """The Details screen's rename: ChangeName(villager, name) through its own call (0x44BCF8), then the game
        copies the name into the villager (strncpy 0x19, as 0x44BCFD..0x44BD10 does)."""
        e = self.e
        text = e.alloc(64)
        e.write(text, name.encode("latin-1") + b"\0")
        esp = e.sp_top - 8
        e.w32(esp, self.villager(slot))
        e.w32(esp + 4, text)
        from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP
        e.setreg(UC_X86_REG_ESP, esp)
        e.setreg(UC_X86_REG_ECX, L.FAMILY_TREE)
        e.uc.emu_start(0x44BCF8, 0x44BCFD)
        e.write(self.villager(slot) + L.VILLAGER_NAME, name.encode("latin-1")[:24].ljust(25, b"\0"))

    def current_tone_address(self):
        """Where the DLL keeps the tone of the person being drawn: the blit hook's first instruction is
        `cmp dword ptr [CurrentTone], 0` (83 3D addr 00), reached from the jmp it put at 0x404C30."""
        e = self.e
        hook = (0x404C30 + 5 + s32(e.r32(0x404C31))) & 0xFFFFFFFF
        code = e.read(hook, 7)
        assert code[:2] == b"\x83\x3D" and code[6] == 0, code.hex()
        return struct.unpack("<I", code[2:6])[0]

    def draw_tree_person(self, which, g=None, record=None):
        """The tree scene's own call of DrawParent (parent 1 at 0x439CC6, parent 2 at 0x439E01) or DrawChild (child k
        at 0x439FA0), with the record where the scene keeps it; the stand-in draw notes the tone the DLL set."""
        from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_ESP
        e = self.e
        here = self.current_tone_address()
        if not getattr(self, "_tree_seams", False):
            def drawn(emu):
                self.tree_tones.append(s32(emu.r32(here)))
                return 0, 0x1C
            e.seam_live(0x439790, drawn)
            e.seam_live(0x439930, drawn)
            self._tree_seams = True
        rec = record if record is not None else self.record(g)
        site = {0: 0x439CC6, 1: 0x439E01}.get(which, 0x439FA0)
        esp = e.sp_top - 0x1C
        for k in range(7):
            e.w32(esp + 4 * k, 0)
        e.setreg(UC_X86_REG_ESP, esp)
        e.setreg(UC_X86_REG_ECX, e.alloc(0x80))
        if which >= 2:
            e.setreg(UC_X86_REG_EBP, rec + (which - 2) * 0xD8)
        else:
            e.setreg(UC_X86_REG_EDI, rec)
        e.uc.emu_start(site, site + 5)
        assert s32(e.r32(here)) == 0                       # put back after the draw
        return self.tree_tones[-1]
