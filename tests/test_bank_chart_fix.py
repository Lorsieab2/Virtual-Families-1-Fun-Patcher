"""Fix Vanilla Game Bugs: the bank's "Next 7 Days" chart no longer crashes the game.

The chart (CBankingDlg 0x415300, vtable slot 0x4B4508) scales its seven bars by the last day's projected
balance (+0x6C, computed by the constructor 0x415630 at 0x4158A5..0x415B08): divisor = ftol(v6 / 5.0 + v6)
(0x41531F..0x415332), stored at [esp+0x30] (0x415338) and used only by each bar's idiv at 0x415392
(height = int(value) * 140 / divisor). With about $0.42 or less and nobody earning pay the divisor is 0 and the
idiv raises a divide error the game does not handle. vf1fun.dll's InstallBankChartFix replaces
`mov [esp+0x30], eax; mov eax, [edi+0x70]` (0x415338, 7 bytes) with a jump to a detour that stores
0x7FFFFFFF in place of a 0 divisor (every bar then divides to 0) and keeps every other divisor.

Proved by running the game's own code: a harness DLL that includes native/vf1fun/vf1fun.cpp (built with
native/build.bat's compiler settings) and the vanilla exe (VF1_VANILLA_DIR) share one unicorn address space
(tests/kids_emu.py); the DLL's install function runs, then the game's projection code and chart run on
tests/meters_emu.py's stand-ins (as the research script bank_div.py did). Every draw the chart makes is recorded
(the fill 0x408100, the lines 0x4081D0, the outline 0x409B70, and each solid fill where it reaches 0x403B40), and
the recorded fills are drawn with the game's own fill 0x403B40 onto a screen to compare the pixels.
The source checks run everywhere; the rest needs the vanilla game and the MSVC toolchain, and skips without them.
"""
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from conftest import ROOT

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
CPP = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

SITE, BACK = 0x415338, 0x41533F
STOCK = bytes.fromhex("89442430" "8b4770")       # mov [esp+0x30], eax; mov eax, [edi+0x70]
IDIV = 0x415392
MONEY = 0x50C60C
REC = 0x145FC

HARNESS = r'''
#include "@SOURCE@"
extern "C" __declspec(dllexport) void __cdecl T_InstallBankChartFix() { InstallBankChartFix(); }
'''

NO_PAY = [dict(gender=1, career=-1, pay=0), dict(gender=0, career=-1, pay=0)]


def _pay(amount):
    return [dict(gender=1, career=3, pay=amount), dict(gender=0, career=-1, pay=0)]


# ===================================================================== always
def _function(name):
    m = re.search(r"static void %s\(\) \{.*?\n\}\n" % name, CPP, re.S)
    assert m, name + " is missing from vf1fun.cpp"
    return m.group(0)


def test_bank_fix_is_part_of_fix_vanilla_game_bugs_and_checks_the_stock_bytes():
    block = re.search(r'if \(SettingOn\(L"FixVanillaGameBugs", true\)\) \{(.*?)\}', CPP, re.S).group(1)
    assert "InstallBankChartFix();" in block
    assert CPP.count("InstallBankChartFix();") == 1
    body = _function("InstallBankChartFix")
    assert "0x89, 0x44, 0x24, 0x30," in body and "0x8B, 0x47, 0x70 };" in body
    assert "InstallJump(0x415338, stock, sizeof stock, (void *)&BankChartDivisorDetour);" in body


def test_detour_keeps_every_divisor_but_zero():
    m = re.search(r"static void BankChartDivisorDetour\(\) \{\n    __asm \{\n(.*?)\n    \}\n\}", CPP, re.S)
    asm = [line.split("//")[0].strip() for line in m.group(1).split("\n")]
    assert [a for a in asm if a] == [
        "pushfd", "test eax, eax", "jnz keep", "mov eax, 0x7FFFFFFF", "keep:",
        "mov dword ptr [esp + 0x34], eax", "popfd", "mov eax, dword ptr [edi + 0x70]", "push 0x41533F", "ret"]


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
    pe = pefile.PE(str(_vanilla_exe()))
    img = pe.get_memory_mapped_image()
    return lambda va, n: bytes(img[va - 0x400000:va - 0x400000 + n])


def test_vanilla_divisor_is_stored_once_and_used_only_by_the_idiv(image):
    # fld [edi+0x6C]; fdiv qword [0x4B4510] (5.0); mov ebx, eax; fadd [edi+0x6C]; call ftol 0x498510;
    # mov edx, [0x4E9FDC]; mov [esp+0x30], eax; mov eax, [edi+0x70]; lea ecx, [eax-0x69]
    assert image(0x41531F, 0x23) == bytes.fromhex(
        "d9476c" "dc3510454b00" "8bd8" "d8476c" "e8de310800" "8b15dc9f4e00" "89442430" "8b4770" "8d4897")
    assert struct.unpack("<d", image(0x4B4510, 8))[0] == 5.0
    # each bar: ftol(value); imul eax, eax, 0x8C; cdq; idiv dword ptr [esp+0x30]
    assert image(0x415386, 0x10) == bytes.fromhex("e885310800" "69c08c000000" "99" "f77c2430")
    # no other instruction of the chart (0x415300..0x4154E8) names [esp+0x30]
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    uses = [i.address for i in md.disasm(image(0x415300, 0x1E8), 0x415300) if "[esp + 0x30]" in i.op_str]
    assert uses == [SITE, IDIV]


# ===================================================================== emulated
@pytest.fixture(scope="module")
def harness_dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    _vanilla_exe()
    tmp_path = tmp_path_factory.mktemp("bank_chart")
    src = tmp_path / "bank_chart_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    dll = tmp_path / "bank_chart_harness.dll"
    script = tmp_path / "build_harness.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 /LD "{src}" /Fo"{tmp_path}\\\\" /Fe"{dll}" '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n",
        encoding="ascii")
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer"
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")
    build = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=env)
    assert build.returncode == 0, build.stdout + build.stderr
    return dll


class _SharedUc:
    """The kids_emu engine handed to picture_emu: the exe image both map is mapped once."""

    def __init__(self, uc):
        self._uc = uc

    def __getattr__(self, name):
        return getattr(self._uc, name)

    def mem_map(self, address, size, perms=7):
        for begin, last, _p in self._uc.mem_regions():
            if begin <= address and address + size - 1 <= last:
                return
        self._uc.mem_map(address, size, perms)


def _bank_emu(harness_dll, install: bool):
    """One address space: the vanilla exe, the harness DLL (kids_emu) and meters_emu's stand-ins."""
    pytest.importorskip("unicorn")
    pytest.importorskip("capstone")
    exe = _vanilla_exe()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kids_emu
    import meters_emu
    import picture_emu
    from unicorn import UC_HOOK_CODE, UC_HOOK_INTR
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX,
                                   UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
                                   UC_X86_REG_ESI, UC_X86_REG_ESP)

    k = kids_emu.Emu(exe, harness_dll)
    k.protects = []

    def virtual_protect(emu):          # VirtualProtect(address, size, new, &old)
        if emu.arg(2) == 0x40:
            emu.protects.append((emu.arg(0), emu.arg(1), emu.arg(2)))
        emu.w32(emu.arg(3), 0x20)
        return 1, 16
    k.imports.update({
        "VirtualProtect": virtual_protect,
        "GetCurrentProcess": lambda emu: (0xFFFFFFFF, 0),
        "FlushInstructionCache": lambda emu: (1, 12),
    })

    class BankEmu(meters_emu.MeterEmu):
        """bank_div.py's emulator: the constructor's projections and the chart, with every draw recorded."""

        def __init__(self):
            with mock.patch.object(picture_emu, "Uc", lambda *_a: _SharedUc(k.uc)):
                super().__init__(exe.parent)
            u = self.u
            self.kids = k
            self._code_hooks.pop(0x489900, None)      # the person by index runs for real
            self.now = 0
            extra = {
                0x4154F0: self._ret_value(0, 0x14),   # add a label row (text only)
                0x422320: self._now,                  # the game clock, for the interest catch-up
                0x44C560: self._ret_value(0, 4),
                0x413210: self._ret_value(0, 8),
            }
            for a, h in extra.items():
                if a not in self._code_hooks:
                    u.hook_add(UC_HOOK_CODE, self._code, begin=a, end=a)
                self._code_hooks[a] = h
            self.intr = []
            self.divs = []
            self.regs_back = []
            u.hook_add(UC_HOOK_INTR, self._on_intr)
            u.hook_add(UC_HOOK_CODE, self._on_idiv, begin=IDIV, end=IDIV)
            u.hook_add(UC_HOOK_CODE, self._on_quotient, begin=IDIV + 4, end=IDIV + 4)
            u.hook_add(UC_HOOK_CODE, self._on_back, begin=BACK, end=BACK)
            for a in (0x408100, 0x409B70):        # (rect*, colour), thiscall
                u.hook_add(UC_HOOK_CODE, self._on_rect_call, begin=a, end=a)
            u.hook_add(UC_HOOK_CODE, self._on_line, begin=0x4081D0, end=0x4081D0)
            self.rendering = False
            self._regs = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI,
                          UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS)
            self._esp, self._eip = UC_X86_REG_ESP, UC_X86_REG_EIP
            self._ecx, self._ebp, self._esi, self._edi, self._ebx = (
                UC_X86_REG_ECX, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX)

        # ---------------------------------------------------------- recorders
        def _now(self, _s):
            self._ret_value(self.now & 0xFFFFFFFF, 0)(self)

        def _on_intr(self, u, intno, _d):
            self.intr.append((intno, u.reg_read(self._eip)))
            u.emu_stop()

        def _on_idiv(self, u, _a, _s, _d):
            esp = u.reg_read(self._esp)
            product = struct.unpack("<i", struct.pack("<I", u.reg_read(self._regs[0])))[0]
            self.divs.append([self.r32(esp + 0x30) & 0xFFFFFFFF, product, None])

        def _on_quotient(self, u, _a, _s, _d):
            self.divs[-1][2] = struct.unpack("<i", struct.pack("<I", u.reg_read(self._regs[0])))[0]

        def _on_back(self, u, _a, _s, _d):
            esp = u.reg_read(self._esp)
            self.regs_back.append((tuple(u.reg_read(r) for r in self._regs), self.r32(esp + 0x30)))

        def _on_rect_call(self, u, address, _s, _d):
            if self.rendering:
                return
            esp = u.reg_read(self._esp)
            rect_at, colour = struct.unpack("<II", u.mem_read(esp + 4, 8))
            rect = struct.unpack("<4i", u.mem_read(rect_at, 16))
            self.events.append(("call", address, rect, colour))

        def _on_line(self, u, address, _s, _d):
            esp = u.reg_read(self._esp)
            self.events.append(("call", address, struct.unpack("<5i", u.mem_read(esp + 4, 20))))

        # ---------------------------------------------------------- the game's code
        def family(self, members):
            """members: list of dict(gender, career, pay). Clears all 30 slots."""
            for i in range(30):
                self.u.mem_write(picture_emu.MANAGER + 0x14640 + i * REC, bytes(REC))
            for i, m in enumerate(members):
                r = picture_emu.MANAGER + 0x14640 + i * REC
                self.u.mem_write(r + 0x13574, b"\x01")
                self.u.mem_write(r + 0x13578, b"\x00")
                self.w32(r + 0x2AE0, 100)
                self.w32(r + 0x2B6C, m["career"])
                self.w32(r + 0x2A38, m["gender"])
                self.w32(r + 0x2B78, m["pay"])
                self.w32(r + 0x13538, i)

        def projections(self, money, members):
            """The constructor's projection code 0x4158A5..0x415B0B: the seven balances at +0x54..+0x6C."""
            self.wf(MONEY, money)
            self.w32(MONEY + 4, 1000)
            self.now = 1000
            self.family(members)
            self._fldcw()
            dlg = self.alloc(0x200)
            for off, v in ((0x14, 100), (0x18, 100), (0x1C, 100 + 560), (0x20, 100 + 440)):
                self.w32(dlg + off, v)
            u = self.u
            esp = picture_emu.STACK - 0x2000
            u.mem_write(esp, bytes(0x400))
            u.reg_write(self._esp, esp)
            u.reg_write(self._esi, dlg)
            u.reg_write(self._ebp, self.fonts)
            u.reg_write(self._edi, 0x150)
            u.reg_write(self._ebx, 0)
            u.emu_start(0x4158A5, 0x415B0B, count=5_000_000)
            return dlg, [self.rf(dlg + 0x54 + 4 * i) for i in range(7)]

        def chart(self, dlg):
            self.intr, self.divs, self.regs_back = [], [], []
            self._start()
            self.call(0x415300, ecx=dlg)
            return list(self.events)

        # ---------------------------------------------------------- the fill's pixels
        def render(self, fills, w, h):
            """Each recorded fill drawn by the game's own 0x403B40 onto a w x h screen (R, G, B, X)."""
            surf = self._surface("bank screen", w, h, alpha=False)
            pixels = self.r32(surf + 0x14)
            self.u.mem_write(pixels, bytes((x * 7 + 3) & 0xFF for x in range(w * h * 4)))
            impl = self.alloc(0x80)
            self.w32(impl + 0x30, surf)
            for i, v in enumerate((0, 0, w, h)):
                self.w32(impl + 0x60 + 4 * i, v)
            rect = self.alloc(16)

            def args(n):
                esp = self.u.reg_read(self._esp)
                return struct.unpack(f"<{n}I", self.u.mem_read(esp + 4, 4 * n))

            def map_rgba(_self):
                _f, r, g, b, a = args(5)
                self._ret_value(r | (g << 8) | (b << 16) | (a << 24), 0)(self)

            def map_rgb(_self):
                _f, r, g, b = args(4)
                self._ret_value(r | (g << 8) | (b << 16), 0)(self)

            def fill_rect(_self):        # SDL_FillRect(surface, SDL_Rect {x, y, w, h}*, colour) (SDL2.dll)
                s, r, colour = args(3)
                x, y, rw, rh = struct.unpack("<4i", self.u.mem_read(r, 16))
                x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + rw, w), min(y + rh, h)
                for row in range(y0, y1):
                    if x1 > x0:
                        self.u.mem_write(pixels + (row * w + x0) * 4, struct.pack("<I", colour) * (x1 - x0))
                self._ret_value(0, 0)(self)

            extra = {0x4978E6: map_rgba, 0x4978FE: map_rgb, 0x497904: fill_rect}
            from unicorn import UC_HOOK_CODE as HOOK
            hooks = [self.u.hook_add(HOOK, self._code, begin=a, end=a) for a in extra]
            saved = self._code_hooks.pop(0x403B40)
            self._code_hooks.update(extra)
            self.rendering = True
            try:
                for f in fills:
                    self.u.mem_write(rect, struct.pack("<4i", *f["rect"]))
                    self.call(0x403B40, (rect, *(struct.unpack("<I", struct.pack("<f", c))[0]
                                                 for c in f["rgba"])), ecx=impl)
            finally:
                self.rendering = False
                self._code_hooks[0x403B40] = saved
                for a in extra:
                    del self._code_hooks[a]
                for hk in hooks:
                    self.u.hook_del(hk)
            return bytes(self.u.mem_read(pixels, w * h * 4))

    e = BankEmu()
    if install:
        k.call(k.dll_export("T_InstallBankChartFix"))
    return e


def _run(harness_dll, install, money, members):
    e = _bank_emu(harness_dll, install)
    dlg, values = e.projections(money, members)
    events = e.chart(dlg)
    return e, values, events


def _bars(events):
    """The seven bars: the fill 0x408100 calls after the background's (rect left, top, right, bottom)."""
    rects = [ev[2] for ev in events if ev[0] == "call" and ev[1] == 0x408100][1:]
    return rects


def _fills(events):
    return [ev[1] for ev in events if ev[0] == "fill"]


def _screen(fills):
    right = max(f["rect"][2] for f in fills) + 8
    bottom = max(f["rect"][3] for f in fills) + 8
    assert min(min(f["rect"][0], f["rect"][1]) for f in fills) >= 0
    return right, bottom


def _detour(e):
    k = e.kids
    assert k.read(SITE, 1) == b"\xE9"
    return SITE + 5 + struct.unpack("<i", k.read(SITE + 1, 4))[0]


def test_stock_chart_faults_with_no_money_and_no_pay(harness_dll):
    e, values, events = _run(harness_dll, False, 0.0, NO_PAY)
    assert int(values[6] / 5.0 + values[6]) == 0
    assert e.intr == [(0, IDIV)]                       # #DE at the idiv, which the game does not handle
    assert e.divs == [[0, 0, None]]                    # divisor 0, the first bar's int(value) * 140 = 0
    assert len(_fills(events)) == 1                    # only the background was drawn


@pytest.mark.parametrize("money", [0.39, 0.423086])
def test_stock_chart_faults_up_to_the_boundary(harness_dll, money):
    e, values, _events = _run(harness_dll, False, money, NO_PAY)
    assert e.intr == [(0, IDIV)] and e.divs[0][0] == 0


@pytest.mark.parametrize("money", [0.0, 0.39, 0.423086])
def test_fixed_chart_draws_empty_bars_with_no_money_and_no_pay(harness_dll, money):
    e, values, events = _run(harness_dll, True, money, NO_PAY)
    assert e.intr == []
    assert e.kids.read(SITE, 7)[0] == 0xE9 and e.kids.read(SITE + 5, 2) == b"\x90\x90"
    assert e.kids.protects == [(SITE, 7, 0x40)]
    # the stored divisor is 0x7FFFFFFF, and each of the seven bars divides to 0
    assert len(e.divs) == 7
    assert all(d == 0x7FFFFFFF and q == 0 for d, _p, q in e.divs)
    bars = _bars(events)
    assert len(bars) == 7 and all(top == bottom for _l, top, _r, bottom in bars)
    # the zero-height bars change no pixel: the chart's pixels equal those drawn without the bars' fills
    fills = _fills(events)
    w, h = _screen(fills)
    flat = [f for f in fills if f["rect"][1] == f["rect"][3]]
    assert len(flat) >= 7
    assert e.render(fills, w, h) == e.render([f for f in fills if f not in flat], w, h)


@pytest.mark.parametrize("money,members", [
    (1.0, NO_PAY), (0.424, NO_PAY), (0.0, _pay(1)), (0.0, _pay(10)), (1_000_000.0, NO_PAY), (25_000.0, _pay(10)),
], ids=["1-no-pay", "0.424-no-pay", "0-pay-1", "0-pay-10", "million-no-pay", "25000-pay-10"])
def test_fixed_chart_draws_exactly_as_the_stock_chart(harness_dll, money, members):
    stock, values, stock_events = _run(harness_dll, False, money, members)
    fixed, fixed_values, fixed_events = _run(harness_dll, True, money, members)
    assert values == fixed_values
    divisor = int(values[6] / 5.0 + values[6])
    assert divisor != 0 and stock.intr == [] and fixed.intr == []
    assert [d for d, _p, _q in stock.divs] == [divisor] * 7
    assert stock.divs == fixed.divs
    # each bar's height is int(value) * 140 / divisor, truncated (at $0.424 the divisor is 1 and every
    # int(value) is 0: the stock chart's own bars are empty there too)
    heights = [abs(int(v) * 140) // abs(divisor) * (1 if int(v) * divisor >= 0 else -1) for v in values]
    assert [q for _d, _p, q in stock.divs] == heights
    assert [bottom - top for _l, top, _r, bottom in _bars(stock_events)] == heights
    assert any(heights) == (money != 0.424)
    assert stock_events == fixed_events
    # the registers, the flags and esp at 0x41533F are the stock ones, and so is the stored divisor
    assert stock.regs_back == fixed.regs_back
    fills = _fills(stock_events)
    w, h = _screen(fills)
    assert stock.render(fills, w, h) == fixed.render(_fills(fixed_events), w, h)


def test_detour_leaves_registers_flags_and_esp_as_the_stock_code(harness_dll):
    """Run 0x415338..0x41533F alone, stock and fixed, for eax 0, 1, -11 and 341, under both flag states."""
    from unicorn.x86_const import UC_X86_REG_EIP
    for eax in (0, 1, 0xFFFFFFF5, 341):
        for flags in (0x202, 0x2D7):
            results = []
            for install in (False, True):
                e = _bank_emu(harness_dll, install)
                u = e.u
                esp = 0x0F000000 - 0x3000
                regs = dict(zip(e._regs, (eax, 0x11, 0x22, 0x33, 0x44, 0x0, 0x66, esp, flags)))
                dlg = e.alloc(0x100)
                e.w32(dlg + 0x70, 400)
                regs[e._regs[5]] = dlg
                for r, v in regs.items():
                    u.reg_write(r, v)
                u.mem_write(esp, bytes(0x40))
                u.emu_start(SITE, BACK, count=100)
                assert u.reg_read(UC_X86_REG_EIP) == BACK
                results.append((tuple(u.reg_read(r) for r in e._regs), e.r32(esp + 0x30) & 0xFFFFFFFF))
            stock, fixed = results
            assert stock[0] == fixed[0]
            assert stock[1] == eax and fixed[1] == (0x7FFFFFFF if eax == 0 else eax)


def test_install_checks_the_stock_bytes_and_installs_once(harness_dll):
    e = _bank_emu(harness_dll, True)
    k = e.kids
    patched = k.read(SITE, 7)
    detour = _detour(e)
    k.call(k.dll_export("T_InstallBankChartFix"))      # a second Startup: already installed, no write
    assert k.read(SITE, 7) == patched and k.protects == [(SITE, 7, 0x40)]
    assert _detour(e) == detour

    other = _bank_emu(harness_dll, False)
    k = other.kids
    k.write(SITE, b"\x89\x44\x24\x2C")                 # something else changed the store: left as it is
    k.call(k.dll_export("T_InstallBankChartFix"))
    assert k.read(SITE, 7) == b"\x89\x44\x24\x2C" + STOCK[4:] and k.protects == []
