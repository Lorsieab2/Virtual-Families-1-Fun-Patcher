"""Which of the font list's four fonts does Virtual Families 1 ever read back?  Proved by running the game's own
code in Unicorn (VF1_VANILLA_DIR, the vanilla Virtual Families.exe 1.01.00, only read); skips without it.

The font list is the first 16 bytes of the singleton the getter 0x450530 returns (kept in [0x570218], made by
0x4503F0, 0x14 bytes; +0x10 is its string table).  theGame's start-up (0x422B14) runs the font maker 0x44FC90 on
it: +0 SegoeUiBold18, +4 SegoeUiBold17, +8 SegoeUiBold24 (also made the window's default font, 0x44FD63 ->
0x4083F0) and +0xC SegoeUi33.  Teardown 0x4505B0 -> 0x450460 deletes the four.

What runs (tests/fonts_emu.py's FontEmu: the real font maker and font loader; then, with the real list in place
and a read hook on the singleton's 20 bytes, each function below from its own entry):

* every function that a static data-flow scan of all the exe's code finds dereferencing the singleton
  (`SITES`; the scan follows it through registers, stack slots, arguments, `this` and return values, with the C
  runtime opaque).  Every call is answered by a stand-in that returns 0 (`new`: a zeroed block) and records
  any font pointer it is handed, except the getter 0x450530 and the code that reads the list (`EXEC`), which run.
  Branches are steered (shortest path in the function's own flow graph) to the next site not yet run, then out
  to a `ret`.  The data on those paths is made up, but which slot an instruction reads is not: it is the
  instruction's own offset, and the read hook sees the singleton's real address arrive at it;
* the font maker, under a write hook: afterwards each font pointer is nowhere in memory but its slot (and the
  window's default-font field for +8's), so a font can only be had by reading its slot.

The same scan followed the singleton into the heap fields it is stored in (+0xA4 at 0x41D4B2, +0x70 0x41EC0D,
+0x2BD0 0x430F9F, +8 0x434273, +0x18 0x4404A8 / 0x44FBE8, +0x1C 0x443FCB, +0x14 0x447718, +0x145EC 0x481F91,
+0x3C 0x489812).  Read back: +0x70 (0x41EC25 / 0x41EC86 in 0x41EBD0 itself, and six times in theTipDialog's
0x41F050) and +0xA4 (0x41D64E), each for +0 only -- those are run here too, 0x41F050 on an object holding the
singleton at +0x70 -- and +0x14 at 0x448346, handed only to the string lookup 0x44FD90, which ignores it.  No
field leads to a read of +4 or +0xC.  The field part of the scan is static only.

Result: +0 (Bold 18) is read at 111 instructions in 31 functions (teardown's 0x4504A9 among them); +4 (Bold 17)
by 0x4173A0, called at 0x412EF8 in the achievement row 0x412D00, which draws the achievement's description with
it (DrawText 0x409D20 at 0x412F23); +8 (Bold 24) only by the font maker (the default font); +0xC (Segoe UI 33)
only by teardown, which hands it to its deleting destructor and nothing else.  Segoe UI 33 is loaded but never
drawn; Segoe UI Bold 17 is drawn.
"""
from __future__ import annotations

import os
import struct
from collections import deque
from pathlib import Path

import pytest

capstone = pytest.importorskip("capstone")
pytest.importorskip("unicorn")
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE
from unicorn.x86_const import (
    UC_X86_REG_DS,
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ES,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
    UC_X86_REG_FS,
    UC_X86_REG_GDTR,
    UC_X86_REG_GS,
    UC_X86_REG_SS,
)

_REG = {"eax": UC_X86_REG_EAX, "ebx": UC_X86_REG_EBX, "ecx": UC_X86_REG_ECX, "edx": UC_X86_REG_EDX,
        "esi": UC_X86_REG_ESI, "edi": UC_X86_REG_EDI, "ebp": UC_X86_REG_EBP, "esp": UC_X86_REG_ESP}

BASE = 0x400000
TEXT, TEXT_END = 0x401000, 0x4B2000
GETTER, SINGLETON = 0x450530, 0x570218
SLOT_NAMES = {0: "SegoeUiBold18", 4: "SegoeUiBold17", 8: "SegoeUiBold24", 0xC: "SegoeUi33"}
ARENA, ARENA_SIZE = 0x30000000, 0x2000000       # made-up objects and stand-in results
STACK_TOP, STOP = 0x0F000000 - 0x1000, 0x0EFFFFF0
TEB = 0x0E000000
NEW = 0x497B14

# Every instruction that reads the singleton (address -> offset), from the static scan; "w" marks the font
# maker's writes.  All are in reachable code except 0x44D87E (0x44D840 is never called).
_SITES = """
412d00 412dcc
415630 41569a 415732
416cf0 416dba 416e24
4173a0 4173a0:4
41a970 41aa40 41aaa3 41ac1b 41ac4c
41b770 41b884 41b8e9 41ba59
41c380 41c49a 41c4be 41c5db
41c7c0 41c845 41c8ce 41c9c5
41caf0 41cb55 41cc12 41cdca
41cec0 41ceed
41e3e0 41e57c 41e65f 41e735 41e97c
41ebd0 41ede8 41ec25 41ec86
41d3e0 41d64e
41f050 41f134 41f16b 41f197 41f1a8 41f1d0 41f213
435030 435137
4356a0 4358a9 435966 4359d8 435aab 435b9c 435c79 435d58 435e2d 435f03 435fe0 4360ba 436129 436197
436980 436a65 436b02
4375e0 437742 4377c5 437830 437907 4379f1 437acc 437ba1 437c76 437d4b 437e28 437f00 437f70 437fd7
438790 438827
439ba0 439bc2
43a3b0 43a44a 43a4b6 43a522 43a55d
43db20 43ddd7
43fe10 43fecd
448c10 448c6b 448c90 448cb7 448cdf 448d07 448ea5
449100 44928a 4493f8
449700 44979d
44a3b0 44a51c 44a61e 44a79f 44a899 44a990 44aa87 44aafc 44ab6f 44ac69 44ad63 44add1 44ae40 44af2e 44b025 44b11c 44b213
44cde0 44d028
44d840 44d87e
44d920 44d949 44da4f 44da78 44daa2 44dacc 44daff
44e010 44e02b 44e052 44e09e
497170 497208 497267
44fc90 44fce3:4w 44fd0f:0w 44fd3a:8w 44fd60:cw 44fd63:8
450460 450472:10 45048b:4 45049a:8 4504a9:0 4504b7:c
"""


def _parse():
    sites, funcs = {}, {}
    for line in _SITES.split("\n"):
        if not line.strip():
            continue
        fn, *rest = line.split()
        fn = int(fn, 16)
        funcs[fn] = []
        for item in rest:
            at, _, off = item.partition(":")
            write = off.endswith("w")
            off = int(off.rstrip("w") or "0", 16)
            sites[int(at, 16)] = (fn, off, write)
            funcs[fn].append(int(at, 16))
    return sites, funcs


SITES, SITE_FUNCS = _parse()
DEAD = {0x44D840}                                   # never called (reach: no path from the entry point)
# Functions whose sites run inside a caller: the getter 0x4173A0 (called with the singleton at 0x412EF8), the
# font maker (FontEmu runs it) and teardown's 0x450460 (run from 0x4505B0, which loads [0x570218]).
# 0x41EC25 / 0x41EC86 / 0x41D64E read the singleton back from a field their own function stored it in (+0x70 at
# 0x41EC0D, +0xA4 at 0x41D4B2); 0x41F050 (theTipDialog's vtable +0x30) reads it from the field +0x70 its class's
# set-up 0x41EBD0 stored, so its run gets an object holding the singleton there.
THIS_FIELDS = {0x41F050: (0x70,)}
CALLED_FROM = {0x4173A0: 0x412D00, 0x450460: 0x4505B0, 0x44FC90: None}
EXEC = {0x4173A0, 0x450460, GETTER}
CALL_SITES = {0x4173A0: [0x412EF8], 0x450460: [0x4505BD]}
# Also run: the draw that is handed what 0x4173A0 read, and teardown's four deletes (call [vtable]).
EXTRA_GOALS = {0x412D00: [0x412F23], 0x4505B0: [0x450498, 0x4504A7, 0x4504B5, 0x4504C6]}
MAKE_FONTS = 0x44FC90


def roots():
    """The functions run from their own entries, with the sites each must pass."""
    out = {}
    for fn, sites in SITE_FUNCS.items():
        if fn in DEAD:
            continue
        top = CALLED_FROM.get(fn, fn)
        if top is None:
            continue
        out.setdefault(top, []).extend(sites)
        if top != fn:                                   # and the caller's call that hands the singleton on
            out[top].extend(CALL_SITES[fn])
    for top, extra in EXTRA_GOALS.items():
        out[top].extend(extra)
    return out


# ------------------------------------------------------------------ flow graphs for steering
class Code:
    def __init__(self, image: bytes) -> None:
        self.img = image
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self._ins = {}
        self._cfg = {}
        self._dist = {}
        self._retn = {}
        self.entries = set()
        for off in range(TEXT - BASE, TEXT_END - BASE - 5):            # every E8 call target is a function
            if image[off] == 0xE8:
                t = BASE + off + 5 + struct.unpack_from("<i", image, off + 1)[0]
                if TEXT <= t < TEXT_END:
                    self.entries.add(t)
        # what a call through a pointer can really reach: a called function or a code address the data holds
        # (vtables, callbacks)
        self.known = set(self.entries)
        for off in range(TEXT_END - BASE, len(image) - 4, 4):
            v = struct.unpack_from("<I", image, off)[0]
            if TEXT <= v < TEXT_END:
                self.known.add(v)

    def ins(self, a):
        i = self._ins.get(a)
        if i is None:
            i = next(self.md.disasm(self.img[a - BASE:a - BASE + 16], a), None)
            self._ins[a] = i
        return i

    def detail(self, a):
        if not hasattr(self, "_mdd"):
            self._mdd = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
            self._mdd.detail = True
        return next(self._mdd.disasm(self.img[a - BASE:a - BASE + 16], a))

    def d32(self, a):
        return struct.unpack_from("<I", self.img, a - BASE)[0]

    def table(self, op):
        tab = int(op.split("+ ")[-1].rstrip("]"), 16)
        out, k = [], 0
        while TEXT <= self.d32(tab + 4 * k) < TEXT_END and k < 256:
            out.append(self.d32(tab + 4 * k))
            k += 1
        return out

    def local_jump(self, fn, t):
        return abs(t - fn) < 0x4000 and not (t in self.entries and t != fn)

    def succs(self, i, fn):
        m, op, nxt = i.mnemonic, i.op_str, i.address + i.size
        if m in ("ret", "int3", "hlt"):
            return []
        if m == "jmp":
            if op.startswith("0x"):
                t = int(op, 16)
                return [t] if self.local_jump(fn, t) else []
            if "*4 +" in op and op.startswith("dword ptr ["):
                return self.table(op)
            return []
        if m.startswith("j") and op.startswith("0x"):
            return [nxt, int(op, 16)]
        return [nxt]

    def cfg(self, fn):
        if fn not in self._cfg:
            seen, work = set(), [fn]
            while work:
                a = work.pop()
                if a in seen or not TEXT <= a < TEXT_END:
                    continue
                i = self.ins(a)
                if i is None:
                    continue
                seen.add(a)
                work.extend(self.succs(i, fn))
            self._cfg[fn] = seen
        return self._cfg[fn]

    def distances(self, fn, goals):
        """instruction -> steps to the nearest goal, inside fn's flow graph."""
        key = (fn, goals)
        if key not in self._dist:
            body = self.cfg(fn)
            preds = {}
            for a in body:
                for s in self.succs(self.ins(a), fn):
                    preds.setdefault(s, []).append(a)
            dist = {g: 0 for g in goals if g in body}
            work = deque(dist)
            while work:
                a = work.popleft()
                for p in preds.get(a, ()):
                    if p not in dist:
                        dist[p] = dist[a] + 1
                        work.append(p)
            self._dist[key] = dist
        return self._dist[key]

    def rets(self, fn):
        return frozenset(a for a in self.cfg(fn) if self.ins(a).mnemonic == "ret")

    def retn(self, fn):
        """the bytes a function's `ret n` pops (its first ret on any path), 0 for a thunk"""
        if fn not in self._retn:
            n = 0
            i = self.ins(fn)
            if not (i is not None and i.mnemonic == "jmp" and i.op_str.startswith("dword ptr [0x")):
                self._retn[fn] = 0                      # (a guard while following tail jumps)
                body = sorted(self.cfg(fn))
                rets = [self.ins(a) for a in body if self.ins(a).mnemonic == "ret"]
                if rets:
                    n = int(rets[0].op_str, 0) if rets[0].op_str else 0
                else:                                   # it ends in a tail jump: that function's ret
                    for a in body:
                        j = self.ins(a)
                        if j.mnemonic == "jmp" and j.op_str.startswith("0x") \
                                and not self.local_jump(fn, int(j.op_str, 16)):
                            n = self.retn(int(j.op_str, 16))
                            break
            self._retn[fn] = n
        return self._retn[fn]


# ------------------------------------------------------------------ the emulator
class SlotEmu:
    """FontEmu (the real font maker) plus guided runs of the code that reads the list."""

    def __init__(self, game: Path) -> None:
        import fonts_emu

        self.writes = []                                # (pc, address, value) of every 4-byte write in the font maker
        self.reads = []                                 # (pc, offset, root) of every read of the singleton
        outer = self

        class Recording(fonts_emu.FontEmu):
            def call(self, fn, args=(), ecx=0, max_ins=20_000_000):
                if fn != fonts_emu.MAKE_FONTS:
                    return super().call(fn, args, ecx, max_ins)
                h = self.u.hook_add(UC_HOOK_MEM_WRITE, outer._on_build_write)
                r = self.u.hook_add(UC_HOOK_MEM_READ, outer._on_build_read, begin=ecx, end=ecx + 0x13,
                                    user_data=ecx)
                try:
                    return super().call(fn, args, ecx, max_ins)
                finally:
                    self.u.hook_del(h)
                    self.u.hook_del(r)

        self.fe = Recording(game)
        self.u = self.fe.u
        self.code = Code(self.fe.img)
        self.manager = self.fe.manager
        self.fonts = dict(self.fe.fonts)                # name -> font object
        self.font_of = {v: k for k, v in self.fonts.items()}
        self.saved = bytes(self.u.mem_read(self.manager, 0x14))
        self.held = {name: self.where(v) for name, v in self.fonts.items()}   # before anything else runs
        self.fe.w32(SINGLETON, self.manager)
        self.list_writes = []
        self.handed = []                                # (callee, call site, font name, where, root)
        self.indirect = []                              # (call site, target, ecx, root)
        self.pc = 0
        # made-up data lives in pre-mapped zeroed memory (nothing is mapped while code runs): low memory for
        # small garbage pointers, and an arena for the objects and stand-in results
        self.u.mem_map(0x1000, BASE - 0x1000)
        self._own_fs()
        self.u.mem_map(ARENA, ARENA_SIZE)
        self.u.mem_map(0xFFFF0000, 0x10000)                # small negative garbage pointers
        self.u.hook_add(UC_HOOK_MEM_READ, self._on_read, begin=self.manager, end=self.manager + 0x13)
        self.u.hook_add(UC_HOOK_MEM_WRITE, self._on_write, begin=self.manager, end=self.manager + 0x13)
        self.u.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.u.hook_add(UC_HOOK_CODE, self._on_code)
        self.active = False

    def _own_fs(self):
        """fs:[0] (the exception-handler chain the prologues use) in its own block, so that page 0, which made-up
        null pointers read, stays empty: a flat GDT (code 0x08, data 0x10) and a data segment 0x18 for fs"""
        u = self.u
        u.mem_map(TEB, 0x2000)
        u.mem_write(TEB, struct.pack("<I", 0xFFFFFFFF))

        def desc(base, limit, access):
            return struct.pack("<Q", (limit & 0xFFFF) | ((base & 0xFFFFFF) << 16) | (access << 40)
                               | (((limit >> 16) & 0xF) << 48) | (0xC << 52) | (((base >> 24) & 0xFF) << 56))
        gdt = bytes(8) + desc(0, 0xFFFFF, 0x9B) + desc(0, 0xFFFFF, 0x93) + desc(TEB, 0x1, 0x93)
        u.mem_write(TEB + 0x1000, gdt)
        u.reg_write(UC_X86_REG_GDTR, (0, TEB + 0x1000, len(gdt) - 1, 0))
        for reg, sel in ((UC_X86_REG_SS, 0x10), (UC_X86_REG_DS, 0x10), (UC_X86_REG_ES, 0x10),
                         (UC_X86_REG_GS, 0x10), (UC_X86_REG_FS, 0x18)):
            u.reg_write(reg, sel)

    # ---------------------------------------------------------- hooks
    def _on_build_write(self, u, access, address, size, value, _data):
        if size == 4:
            self.writes.append((u.reg_read(UC_X86_REG_EIP), address, value & 0xFFFFFFFF))

    def _on_build_read(self, u, access, address, size, value, manager):
        self.reads.append((u.reg_read(UC_X86_REG_EIP), address - manager, MAKE_FONTS))

    def _on_read(self, u, access, address, size, value, _data):
        if self.active:
            self.reads.append((self.pc, address - self.manager, self.root))

    def _on_write(self, u, access, address, size, value, _data):
        if self.active:
            self.list_writes.append((self.pc, address - self.manager, value, self.root))

    def _on_unmapped(self, u, access, address, size, value, _data):
        if self.active:
            self.problem = f"unmapped access {address:#x} at {self.pc:#x}"
        return False

    def scratch(self, n=0x400):
        a = self.arena
        self.arena += n
        if self.arena > ARENA + ARENA_SIZE:
            raise RuntimeError("arena full")
        self.u.mem_write(a, bytes(n))
        return a

    def _ret(self, value, clean):
        esp = self.u.reg_read(UC_X86_REG_ESP)
        ra = struct.unpack("<I", self.u.mem_read(esp, 4))[0]
        self.u.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)
        self.u.reg_write(UC_X86_REG_ESP, esp + 4 + clean)
        self.u.reg_write(UC_X86_REG_EIP, ra)

    def _record_fonts(self, callee, site):
        """note every font pointer handed to `callee` in ecx or its arguments"""
        esp = self.u.reg_read(UC_X86_REG_ESP)
        n = self.code.retn(callee) // 4 if TEXT <= callee < TEXT_END else 0
        values = [] if callee in self.fe.hooks else [("ecx", self.u.reg_read(UC_X86_REG_ECX))]
        values += [(f"argument {k + 1}", struct.unpack("<I", self.u.mem_read(esp + 4 + 4 * k, 4))[0])
                   for k in range(n or 8)]
        for where, v in values:
            if v in self.font_of:
                self.handed.append((callee, site, self.font_of[v], where, self.root))

    def _target(self, i):
        """where an indirect call goes"""
        d = self.code.detail(i.address)
        o = d.operands[0]
        if o.type == capstone.x86.X86_OP_REG:
            return self.u.reg_read(_REG[d.reg_name(o.reg)])
        m = o.mem
        a = m.disp
        if m.base:
            a += self.u.reg_read(_REG[d.reg_name(m.base)])
        if m.index:
            a += self.u.reg_read(_REG[d.reg_name(m.index)]) * m.scale
        return struct.unpack("<I", self.u.mem_read(a & 0xFFFFFFFF, 4))[0]

    def _new(self):
        esp = self.u.reg_read(UC_X86_REG_ESP)
        n = struct.unpack("<I", self.u.mem_read(esp + 4, 4))[0]
        self._ret(self.scratch(max(16, min(n, 0x40000))), 0)

    def _on_code(self, u, address, size, _data):
        if not self.active:
            return
        self.count += 1
        if self.count > self.limit:
            self.problem = "instruction limit"
            u.emu_stop()
            return
        self.pc = address
        self.trace.append(address)
        frame = self.stack[-1]
        if self.prev_call is not None:
            site, nxt, pushes = self.prev_call
            self.prev_call = None
            if address != nxt:                          # entered a callee
                self._record_fonts(address, site)
                if address in self.fe.hooks:            # FontEmu's stand-ins (new, delete, SDL, ...) answer it
                    return
                if address in EXEC:
                    self.goals.discard(address)
                    ra = struct.unpack("<I", u.mem_read(u.reg_read(UC_X86_REG_ESP), 4))[0]
                    self.stack.append([address, ra, 0])
                    return
                if address in self.code.known:
                    clean = self.code.retn(address)
                else:                                   # a call through a made-up pointer: callee pops its pushes
                    after = self.code.ins(nxt)
                    cdecl = after is not None and after.mnemonic == "add" and after.op_str.startswith("esp, ")
                    clean = 0 if cdecl else 4 * pushes
                self._ret(0, clean)
                return
        if address in self.fe.hooks:
            return
        if not TEXT <= address < TEXT_END:
            self.problem = f"left the code at {address:#x}"
            u.emu_stop()
            return
        while len(self.stack) > 1 and address == self.stack[-1][1]:
            self.stack.pop()
            frame = self.stack[-1]
        fn = frame[0]
        i = self.code.ins(address)
        if i is None:
            self.problem = f"no instruction at {address:#x}"
            u.emu_stop()
            return
        self.goals.discard(address)
        self.visits[address] = self.visits.get(address, 0) + 1
        m, op = i.mnemonic, i.op_str
        if m == "push":
            frame[2] += 1
        elif m == "pop":
            frame[2] = max(0, frame[2] - 1)
        elif m in ("add", "sub", "and") and op.startswith("esp, "):
            frame[2] = 0
        if m == "call":
            if not op.startswith("0x"):
                target = self._target(i)
                self.indirect.append((address, target, u.reg_read(UC_X86_REG_ECX), self.root))
                if target not in self.code.known:        # a call through a made-up pointer: answer it here
                    self._record_fonts(target, address)
                    after = self.code.ins(address + i.size)
                    cdecl = after is not None and after.mnemonic == "add" and after.op_str.startswith("esp, ")
                    u.reg_write(UC_X86_REG_EAX, 0)
                    u.reg_write(UC_X86_REG_ESP, u.reg_read(UC_X86_REG_ESP) + (0 if cdecl else 4 * frame[2]))
                    u.reg_write(UC_X86_REG_EIP, address + i.size)
                    frame[2] = 0
                    return
            self.prev_call = (address, address + i.size, frame[2])
            frame[2] = 0
            return
        choices = None
        if m.startswith("j") and m != "jmp" and op.startswith("0x"):
            choices = [address + i.size, int(op, 16)]
        elif m == "jmp" and "*4 +" in op and op.startswith("dword ptr ["):
            choices = self.code.table(op)
        elif m == "jmp" and op.startswith("0x") and not self.code.local_jump(fn, int(op, 16)):
            t = int(op, 16)                             # a tail call
            self._record_fonts(t, address)
            if t in EXEC:
                frame[0] = t
                return
            self._ret(0, self.code.retn(t))
            return
        if not choices:
            return
        goals = frozenset(g for g in self.goals if g in self.code.cfg(fn))
        if not goals or self.visits[address] > 50:
            goals = self.code.rets(fn)
        dist = self.code.distances(fn, goals)
        best = min(choices, key=lambda c: (dist.get(c, 1 << 30), choices.index(c)))
        u.reg_write(UC_X86_REG_EIP, best)

    # ---------------------------------------------------------- a run
    def run(self, root, goals, limit=200_000):
        """run `root` from its entry (this = a zeroed 128 KB object, arguments 0), steered through `goals`;
        returns (the goals not reached, what stopped it early or None)"""
        u = self.u
        u.mem_write(self.manager, self.saved)
        self.fe.w32(SINGLETON, self.manager)
        self.arena = ARENA
        u.mem_write(ARENA, bytes(ARENA_SIZE))
        u.mem_write(0x1000, bytes(BASE - 0x1000))
        u.mem_write(0, bytes(0x1000))
        u.mem_write(0xFFFF0000, bytes(0x10000))
        saved_new = self.fe.hooks[NEW]
        self.fe.hooks[NEW] = self._new
        self.root, self.goals, self.limit = root, set(goals), limit
        self.count, self.visits, self.prev_call, self.problem = 0, {}, None, None
        self.trace = deque(maxlen=80)
        self.stack = [[root, STOP, 0]]
        this = self.scratch(0x20000)
        for off in THIS_FIELDS.get(root, ()):
            self.fe.w32(this + off, self.manager)
        esp = STACK_TOP
        u.mem_write(esp - 0x10000, bytes(0x10000))
        for _ in range(8):
            esp -= 4
            u.mem_write(esp, struct.pack("<I", 0))
        esp -= 4
        u.mem_write(esp, struct.pack("<I", STOP))
        u.reg_write(UC_X86_REG_ESP, esp)
        u.reg_write(UC_X86_REG_ECX, this)
        self.active = True
        try:
            u.emu_start(root, STOP, count=limit * 4)
        except Exception as e:                          # noqa: BLE001 - recorded, checked by the tests
            self.problem = self.problem or f"{type(e).__name__}: {e} at {self.pc:#x}"
        finally:
            self.active = False
            self.fe.hooks[NEW] = saved_new
        left = set(self.goals)
        u.mem_write(self.manager, self.saved)
        self.fe.w32(SINGLETON, 0)
        return left, self.problem

    def where(self, value):
        """every mapped address holding `value` (4 bytes, any alignment)"""
        pat, out = struct.pack("<I", value), []
        for begin, end, _perm in self.u.mem_regions():
            data = bytes(self.u.mem_read(begin, end - begin + 1))
            k = data.find(pat)
            while k >= 0:
                out.append(begin + k)
                k = data.find(pat, k + 1)
        return out


def _game() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    return Path(value).resolve()


@pytest.fixture(scope="module")
def emu():
    return SlotEmu(_game())


def run_all(emu):
    """every root from its own entry, again and again while each run reaches a site not yet run:
    root -> (sites never reached, [what stopped each run early])"""
    out = {}
    for root, sites in sorted(roots().items()):
        # the caller's call that hands the singleton on is a goal of every run
        always = {s for fn, calls in CALL_SITES.items() if CALLED_FROM.get(fn) == root for s in calls}
        left, problems = set(sites), []
        while left:
            now, problem = emu.run(root, left | always)
            problems.append(problem)
            now -= always
            if now == left:
                break
            left = now
        out[root] = (left, problems)
    return out


@pytest.fixture(scope="module")
def runs(emu):
    return run_all(emu)


# ------------------------------------------------------------------ the tests
def test_the_font_maker_fills_the_list_and_nothing_else(emu):
    stack_low = 0x0F000000 - 0x200000
    fonts = emu.fonts
    assert [emu.fe.r32(emu.manager + off) for off in SLOT_NAMES] == [fonts[n] for n in SLOT_NAMES.values()]
    assert emu.fe.default_font() == fonts["SegoeUiBold24"]
    window_default = emu.fe.impl + 0x5C
    for off, name in SLOT_NAMES.items():
        stored = {a for pc, a, v in emu.writes if v == fonts[name] and not stack_low <= a < 0x0F010000}
        expect = {emu.manager + off} | ({window_default} if name == "SegoeUiBold24" else set())
        assert stored == expect, name
        held = {a for a in emu.held[name] if not stack_low <= a < 0x0F010000}
        assert held == expect, name


def test_every_site_runs(runs):
    for root, (left, problems) in runs.items():
        assert not left, f"{root:#x}: sites not reached {sorted(map(hex, left))} ({problems})"


def test_which_slots_are_read(emu, runs):
    seen = {}
    for pc, off, _root in emu.reads:
        seen.setdefault(pc, set()).add(off)
    expected = {at: {off} for at, (fn, off, write) in SITES.items() if not write and fn not in DEAD}
    assert seen == expected
    by_slot = {}
    for pc, off, root in emu.reads:
        by_slot.setdefault(off, set()).add((pc, root))
    assert len({pc for pc, _r in by_slot[0]}) == sum(1 for fn, off, w in SITES.values() if off == 0 and not w and fn not in DEAD)
    # +4: the achievement row's getter, and teardown; +8: the font maker (the window's default), and teardown;
    # +0xC: teardown only
    assert by_slot[4] == {(0x4173A0, 0x412D00), (0x45048B, 0x4505B0)}
    assert by_slot[8] == {(0x44FD63, MAKE_FONTS), (0x45049A, 0x4505B0)}
    assert by_slot[0xC] == {(0x4504B7, 0x4505B0)}
    assert not emu.list_writes


def test_where_bold17_and_segoe33_go(emu, runs):
    fonts = emu.fonts
    # Bold 17 is handed to one function outside teardown: the centred DrawText 0x409D20 at 0x412F23, as its
    # font (argument 5) -- the achievement row's second line
    bold17 = {h[:4] for h in emu.handed if h[2] == "SegoeUiBold17" and h[4] != 0x4505B0}
    assert bold17 == {(0x409D20, 0x412F23, "SegoeUiBold17", "argument 5")}
    # Segoe UI 33 reaches one function only: its own deleting destructor (its vtable's first entry), which
    # teardown calls at 0x4504C6; the same for every font in teardown
    for site, name in ((0x4504B5, "SegoeUiBold18"), (0x450498, "SegoeUiBold17"), (0x4504A7, "SegoeUiBold24"),
                       (0x4504C6, "SegoeUi33")):
        destructor = emu.fe.r32(emu.fe.r32(fonts[name]))
        assert (destructor, site, name, "ecx") in {h[:4] for h in emu.handed}
        assert (site, destructor, fonts[name], 0x4505B0) in emu.indirect
    assert {h[:4] for h in emu.handed if h[2] == "SegoeUi33"} == {
        (emu.fe.r32(emu.fe.r32(fonts["SegoeUi33"])), 0x4504C6, "SegoeUi33", "ecx")}

if __name__ == "__main__":                              # research: print what the runs saw
    e = SlotEmu(_game())
    for r, (left, problems) in run_all(e).items():
        print(hex(r), "left", sorted(map(hex, left)), problems)
    import collections
    print(collections.Counter(off for _pc, off, _r in e.reads))
    for x in sorted({(hex(pc), off, hex(r)) for pc, off, r in e.reads}):
        if x[1]:
            print("read", x)
    for h in sorted(set(e.handed)):
        print("handed", hex(h[0]), hex(h[1]), h[2], h[3], hex(h[4]))
    for x in e.indirect:
        if x[3] == 0x4505B0:
            print("indirect", hex(x[0]), hex(x[1]), hex(x[2]), e.font_of.get(x[2]))
