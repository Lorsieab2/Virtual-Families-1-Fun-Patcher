"""The Virtual Families 1 divide-by-zero audit (docs/DIVIDE_BY_ZERO_AUDIT.md) covers every division the game can run.

The vanilla exe's reachable code is found by recursive descent from the entry point (direct calls, jumps and
branches, jump tables, code addresses the code takes, the virtual methods of every class whose vtable reachable code
stores, and the C runtime's static-initializer tables), and every `div` / `idiv` in it must be exactly a site of the
audit table: a missed site, or a site that is not a division, fails. GetRandom 0x403650's guard is proved by running
it in Unicorn. The document checks run everywhere; the rest needs the vanilla game (VF1_VANILLA_DIR), pefile and
capstone (unicorn for the emulated test), and skips without them.
"""
import os
import re
import struct
from collections import Counter, deque
from pathlib import Path

import pytest

from conftest import ROOT

DOC = ROOT / "docs" / "DIVIDE_BY_ZERO_AUDIT.md"
CPP = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8")
CLASSES = ("SAFE-CONSTANT", "GUARDED", "UNREACHABLE-ZERO", "REACHABLE-CRASH")
BASE = 0x400000
TEXT = (0x401000, 0x4B2000)
RDATA = (0x4B2000, 0x4E9000)
INITTERM = ((0x4B2464, 0x4B2540), (0x4B2544, 0x4B2560))
GET_RANDOM, RAND = 0x403650, 0x498BD8


def _rows():
    text = DOC.read_text(encoding="utf-8")
    table = text.split("## Table", 1)[1]
    rows = []
    for line in table.splitlines():
        if not line.startswith("| 0x"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 8, line
        sites = [int(s, 16) for s in cells[0].split(", ")]
        rows.append(dict(sites=sites, function=cells[1], computes=cells[2], divisor=cells[3], cls=cells[4],
                         why=cells[5], evidence=cells[6], fix=cells[7]))
    return text, rows


# ===================================================================== the document
def test_every_row_is_complete_and_classified():
    _text, rows = _rows()
    sites = [a for r in rows for a in r["sites"]]
    assert len(sites) == len(set(sites)) == 211
    for r in rows:
        assert r["cls"] in CLASSES, r
        assert r["function"] and r["computes"] and r["divisor"] and r["why"], r
        assert r["evidence"] == "read" or r["evidence"].startswith("emulated (tests/"), r
        if r["cls"] == "REACHABLE-CRASH":
            assert r["evidence"].startswith("emulated"), r
            assert r["fix"].startswith("Fix Vanilla Game Bugs: "), r
        else:
            assert r["fix"] == "none", r


def test_summary_counts_match_the_table():
    text, rows = _rows()
    counts = Counter()
    for r in rows:
        counts[r["cls"]] += len(r["sites"])
    for cls in CLASSES:
        assert f"| {cls} | {counts[cls]} |" in text
    assert f"| Total | {sum(counts.values())} |" in text


def test_every_reachable_crash_has_its_fix_in_fix_vanilla_game_bugs():
    _text, rows = _rows()
    block = re.search(r'if \(SettingOn\(L"FixVanillaGameBugs", true\)\) \{(.*?)\}', CPP, re.S).group(1)
    crashes = [r for r in rows if r["cls"] == "REACHABLE-CRASH"]
    assert [r["sites"] for r in crashes] == [[0x415392]]
    for r in crashes:
        installer = re.search(r"(Install\w+)", r["fix"]).group(1)
        assert f"{installer}();" in block
        test = re.search(r"emulated \((tests/[\w./]+)", r["evidence"]).group(1)
        assert (ROOT / test).is_file()


# ===================================================================== the vanilla exe
def _vanilla_exe() -> Path:
    if not os.environ.get("VF1_VANILLA_DIR"):
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    exe = Path(os.environ["VF1_VANILLA_DIR"]) / "Virtual Families.exe"
    if not exe.is_file():
        pytest.skip("VF1_VANILLA_DIR has no Virtual Families.exe")
    return exe


@pytest.fixture(scope="module")
def image():
    pefile = pytest.importorskip("pefile")
    exe = _vanilla_exe()
    pe = pefile.PE(str(exe))
    img = bytes(pe.get_memory_mapped_image())
    return pe, img


def _reachable(pe, img):
    """Every instruction address reachable from the entry point (the research reach.py's walk)."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True

    def d32(a):
        return struct.unpack_from("<I", img, a - BASE)[0]

    def intext(a):
        return TEXT[0] <= a < TEXT[1]

    vt_of = {}
    a = RDATA[0]
    while a < RDATA[1] - 4:
        if intext(d32(a)):
            s = a
            while a < RDATA[1] - 4 and intext(d32(a)):
                a += 4
            if a - s >= 8:
                vt_of[s] = [d32(x) for x in range(s, a, 4)]
        else:
            a += 4
    known, funcs, seen, live = set(), deque(), set(), set()

    def add(fn):
        if fn not in known and intext(fn):
            known.add(fn)
            funcs.append(fn)

    def walk(fn):
        work = [fn]
        while work:
            a = work.pop()
            while intext(a) and a not in seen:
                ins = next(md.disasm(img[a - BASE:a - BASE + 16], a), None)
                if ins is None:
                    break
                seen.add(a)
                m, op = ins.mnemonic, ins.op_str
                for o in ins.operands:
                    if o.type == capstone.x86.X86_OP_IMM:
                        v = o.imm & 0xFFFFFFFF
                        if v in vt_of and m in ("mov", "push") and v not in live:
                            live.add(v)
                            for t in vt_of[v]:
                                add(t)
                        elif intext(v) and m in ("push", "mov") and v not in vt_of:
                            add(v)
                if m == "call":
                    if op.startswith("0x"):
                        add(int(op, 16))
                    a += ins.size
                    continue
                if m == "ret":
                    break
                if m == "jmp":
                    if op.startswith("0x"):
                        t = int(op, 16)
                        if t in known or abs(t - fn) > 0x4000:
                            add(t)
                        else:
                            work.append(t)
                    elif "*4 +" in op and op.startswith("dword ptr ["):
                        tab = int(op.split("+ ")[-1].rstrip("]"), 16)
                        k = 0
                        while intext(d32(tab + 4 * k)) and k < 256:
                            work.append(d32(tab + 4 * k))
                            k += 1
                    break
                if m.startswith("j") and op.startswith("0x"):
                    work.append(int(op, 16))
                a += ins.size

    add(BASE + pe.OPTIONAL_HEADER.AddressOfEntryPoint)
    while funcs:
        walk(funcs.popleft())
    for lo, hi in INITTERM:
        for p in range(lo, hi, 4):
            add(d32(p))
    while funcs:
        walk(funcs.popleft())
    return md, seen


def test_the_table_lists_every_reachable_division(image):
    pe, img = image
    md, seen = _reachable(pe, img)
    divisions = set()
    for a in seen:
        ins = next(md.disasm(img[a - BASE:a - BASE + 16], a))
        if ins.mnemonic in ("div", "idiv"):
            divisions.add(a)
    _text, rows = _rows()
    listed = {a for r in rows for a in r["sites"]}
    assert sorted(divisions - listed) == [], "divisions missing from the audit table"
    assert sorted(listed - divisions) == [], "table sites that are not reachable divisions"
    assert len([a for a in divisions if a < 0x497848]) == 156      # the game's own code; the rest is the CRT
    assert 0x415392 in divisions                                   # the bank chart (tests/test_bank_chart_fix.py)


def test_get_random_divides_only_for_1_to_0x7fff(image):
    """GetRandom 0x403650 run in Unicorn with the CRT's rand() 0x498BD8 standing in: n = 0, -561 (the rain's
    respawn 0x491DF0) and 0x80000000 return 0 without dividing; n = 1 divides by 1; n = 7 and 0x7FFF divide."""
    unicorn = pytest.importorskip("unicorn")
    from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_INTR, UC_MODE_32, Uc
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP
    _pe, img = image
    stack, stop = 0x0F000000, 0x0E000000
    results = {}
    for n, rand_value in ((0, 12345), (1, 12345), (-561 & 0xFFFFFFFF, 12345), (0x80000000, 12345),
                          (7, 12345), (0x7FFF, 32766)):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        size = (len(img) + 0xFFF) & ~0xFFF
        u.mem_map(BASE, size)
        u.mem_write(BASE, img)
        u.mem_map(stack - 0x10000, 0x10000)
        u.mem_map(stop, 0x1000)
        faults = []

        def fake_rand(uc, _a, _s, _d, value=rand_value):
            esp = uc.reg_read(UC_X86_REG_ESP)
            ret = struct.unpack("<I", uc.mem_read(esp, 4))[0]
            uc.reg_write(UC_X86_REG_EAX, value)
            uc.reg_write(UC_X86_REG_ESP, esp + 4)
            uc.reg_write(UC_X86_REG_EIP, ret)

        def on_intr(uc, intno, _d):
            faults.append((intno, uc.reg_read(UC_X86_REG_EIP)))
            uc.emu_stop()

        divided = []
        u.hook_add(UC_HOOK_CODE, fake_rand, begin=RAND, end=RAND)
        u.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: divided.append(a), begin=0x403668, end=0x403668)
        u.hook_add(UC_HOOK_INTR, on_intr)
        esp = stack - 0x100
        u.mem_write(esp, struct.pack("<II", stop, n))
        u.reg_write(UC_X86_REG_ESP, esp)
        u.emu_start(GET_RANDOM, stop, count=10_000)
        assert faults == [], (n, faults)
        results[n] = (u.reg_read(UC_X86_REG_EAX), bool(divided))
    assert results[0] == (0, False)
    assert results[1] == (0, True)                  # divides by 1
    assert results[-561 & 0xFFFFFFFF] == (0, False)
    assert results[0x80000000] == (0, False)
    assert results[7] == (12345 % 7, True)
    assert results[0x7FFF] == (32766 % 0x7FFF, True)
