"""Virtual Families 1's weather, checked for crashes (divide by zero, bad indexes, missing pictures): the "Weather"
section of docs/DIVIDE_BY_ZERO_AUDIT.md.

Every weather path is run as the game's own code in Unicorn (tests/house_emu.py's HouseEmu, on the vanilla
Virtual Families.exe in VF1_VANILLA_DIR, only read): the weather reset 0x4923B0, the weather change 0x492280, the
rain bottle 0x417D60, the update 0x492420 (the rain's step 0x491B50 and splashes, the storm's lightning 0x490930,
the sunbeams 0x491F10, the strength and haze ramps), and the draw 0x4920F0 (the haze and the flash fills, the rain
0x491D20 down to the game's own line drawer 0x4082B0 -> 0x404200, the sunbeams 0x492040).  Stood in for (not
weather logic): GetRandom 0x403650 (same answers as the game's: 0 for n <= 0, else a value below n), the game clock
CGameTime::Seconds 0x422320, SDL_GetTicks, the sound calls, the villagers' rain notice 0x48AE40, the daytime test
0x491630, the next-weather pick 0x492230 (the CRT's localtime), and SDL_MapRGB(A).  Any CPU fault (a divide by
zero is interrupt 0) stops the run and is recorded.

The call-graph test reads the exe only (capstone).  Everything skips cleanly without VF1_VANILLA_DIR.
"""
from __future__ import annotations

import math
import os
import random
import struct
from collections import deque
from pathlib import Path

import pytest

from conftest import ROOT

DOC = ROOT / "docs" / "DIVIDE_BY_ZERO_AUDIT.md"
BASE = 0x400000
WEATHER = 0x8352A4                 # +0 kind, +4 next kind, +8 change time, +0x18 haze max, +0x1C haze,
STRENGTH = WEATHER + 0x28          # +0x24 ramp target, +0x28 strength, +0x2C ramp start, +0x30 ramp clock, +0x34 span
RAIN = 0x831D90                    # 512 drops of 0x18: x, y, previous x, previous y, step x, step y; +0x3000 scroll
SUN = 0x834D98                     # 64 sunbeams of 0x14; +0x500 the picture
LIGHTNING = 0x8316EC               # +0 flash on, +1 burst, +4 next time, +8 burst start
TILES = 0x8352E0                   # 256 x 256 ground tiles (kind in bits 1..3)
EFFECTS = 0x503B68
SCROLL = (0x895784, 0x895788)
LINE, LINE_DIV_X, LINE_DIV_Y = 0x404200, 0x4043A8, 0x4043B2
SCREEN_W, SCREEN_H = 800, 600


# ===================================================================== the document
def _weather_section() -> str:
    text = DOC.read_text(encoding="utf-8")
    assert "## Weather" in text
    return text.split("## Weather", 1)[1].split("\n## ", 1)[0]


def test_the_weather_section_covers_every_path():
    section = _weather_section()
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("| Path")
            and not line.startswith("|---")]
    paths = [r.split("|")[1].strip() for r in rows]
    for word in ("Rain: drop creation", "Rain: step", "Rain: draw", "Rain: respawn", "Rain: splashes",
                 "Storm: lightning", "Sunbeams", "Haze", "Strength and haze ramp", "Weather changes",
                 "Rain bottle", "Fog", "Clouds", "Rainbow", "Puddles", "Night", "Effects clock"):
        assert any(p.startswith(word) for p in paths), word
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        assert len(cells) == 4, r
        assert cells[3].startswith(("SAFE", "REACHABLE-CRASH")), r
    assert "REACHABLE-CRASH" not in "".join(r.split("|")[4] for r in rows)


# ===================================================================== the vanilla game
@pytest.fixture(scope="module")
def vanilla() -> Path:
    value = os.environ.get("VF1_VANILLA_DIR")
    if not value or not (Path(value) / "Virtual Families.exe").is_file():
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    pytest.importorskip("unicorn")
    pytest.importorskip("pefile")
    pytest.importorskip("capstone")
    import faulthandler
    was_on = faulthandler.is_enabled()
    faulthandler.disable()
    yield Path(value).resolve()
    if was_on:
        faulthandler.enable()


def _make_emu(game: Path):
    import house_emu
    from picture_emu import STOP
    from unicorn import UC_HOOK_CODE, UC_HOOK_INTR
    from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_ESP

    class WeatherEmu(house_emu.HouseEmu):
        def __init__(self, folder: Path) -> None:
            super().__init__(folder)
            u = self.u
            self.now = 1000
            self.ticks = 100_000
            self.daytime = True
            self.next_kind = 2
            self.pick = lambda n: 0                 # GetRandom's answer before "% n"
            self.lines: list[tuple[int, int, int, int]] = []
            self.divisors: list[tuple[int, int]] = []
            self.faults: list[tuple[int, int]] = []

            def clock(_self):
                self._ret_value(self.now, 0)(self)

            def ticks(_self):
                self._ret_value(self.ticks, 0)(self)

            def get_random(_self):
                (n,) = self._args(1)
                n = struct.unpack("<i", struct.pack("<I", n))[0]
                self._ret_value(0 if n <= 0 else self.pick(n) % n, 0)(self)

            def next_kind(_self):
                self._ret_value(self.next_kind, 4)(self)

            def daytime(_self):
                self._ret_value(1 if self.daytime else 0, 0)(self)

            def map_rgba(_self):
                _f, r, g, b, a = self._args(5)
                self._ret_value(r | (g << 8) | (b << 16) | (a << 24), 0)(self)

            def map_rgb(_self):
                _f, r, g, b = self._args(4)
                self._ret_value(r | (g << 8) | (b << 16), 0)(self)

            stand_ins = {
                0x422320: clock, 0x403650: get_random, 0x401F00: ticks, 0x492230: next_kind,
                0x491630: daytime, 0x4919D0: self._ret_value(0, 0),
                0x4978E6: map_rgba, 0x4978FE: map_rgb,
                0x44C4C0: self._ret_value(0, 8), 0x44C470: self._ret_value(0, 4), 0x44C5A0: self._ret_value(0, 8),
                0x48AE40: self._ret_value(0, 8),
            }
            for address, fn in stand_ins.items():
                if address not in self._code_hooks and address not in (0x491630, 0x4919D0, 0x4978E6, 0x4978FE):
                    u.hook_add(UC_HOOK_CODE, self._code, begin=address, end=address)
                self._code_hooks[address] = fn

            def on_line(uc, _a, _s, _d):
                esp = uc.reg_read(UC_X86_REG_ESP)
                self.lines.append(struct.unpack("<4i", uc.mem_read(esp + 4, 16)))

            def on_div(uc, a, _s, _d):
                self.divisors.append((a, uc.reg_read(UC_X86_REG_EDI if a == LINE_DIV_X else UC_X86_REG_EBX)))

            def on_fault(uc, intno, _d):
                self.faults.append((intno, uc.reg_read(UC_X86_REG_EIP)))
                uc.emu_stop()

            u.hook_add(UC_HOOK_CODE, on_line, begin=LINE, end=LINE)
            u.hook_add(UC_HOOK_CODE, on_div, begin=LINE_DIV_X, end=LINE_DIV_X)
            u.hook_add(UC_HOOK_CODE, on_div, begin=LINE_DIV_Y, end=LINE_DIV_Y)
            u.hook_add(UC_HOOK_INTR, on_fault)
            # the rain is drawn on a real 800 x 600 screen (pixels the line drawer writes), clip 0, 0 .. 800, 600
            self.rain_screen = self._surface("rain screen", SCREEN_W + 1, SCREEN_H + 1, alpha=False)
            self.w32(self.impl + 0x30, self.rain_screen)
            for k, v in enumerate((0, 0, SCREEN_W, SCREEN_H)):
                self.w32(self.impl + 0x60 + 4 * k, v)
            self.effects_setup()
            self.u.mem_write(WEATHER, bytes(0x38))    # the weather object as it is at start (zeroed memory)
            self.call(0x491E50, ecx=RAIN)             # the rain's constructor (its static initializer 0x4B18A0)
            self.call(0x4920C0, ecx=SUN)              # the sunbeams' constructor (0x4B18C0)
            self.call(0x4908E0, ecx=0x8302D8)         # the fog's constructor (0x4B1840)
            # then the pictures, as the game's start-up 0x423080.. loads them (0x4230C7, 0x4230E5)
            self.call(0x4908C0, ecx=0x8302D8)         # the fog picture (0xA7), never drawn
            self.call(0x491EF0, ecx=SUN)              # the sunbeam picture (0xA6)
            for a in SCROLL:
                self.w32(a, 0)

        # ------------------------------------------------------------ the game's calls
        def run(self, fn, args=(), ecx=0):
            self.call(fn, args, ecx=ecx)
            assert self.faults == [], [(n, hex(a)) for n, a in self.faults]
            assert self.u.reg_read(UC_X86_REG_EIP) == STOP           # returned, not cut off by the count

        def reset(self):
            self.run(0x4923B0, ecx=WEATHER)

        def change(self, kind, ago=0):
            self.run(0x492280, (kind, ago), ecx=WEATHER)

        def update(self):
            self.run(0x492420, ecx=WEATHER)

        def draw(self):
            self.lines = []
            self.divisors = []
            self.records = []
            self.blits = []
            self.run(0x4920F0, ecx=WEATHER)
            return list(self.lines)

        def frame(self, seconds=1):
            self.now += seconds
            self.ticks += 33
            self.update()
            return self.draw()

        def r(self, off):
            return self.r32(WEATHER + off)

        def strength(self):
            return self.rf(STRENGTH)

        def drop(self, k):
            return struct.unpack("<6i", self.u.mem_read(RAIN + 0x18 * k, 0x18))

        def tiles(self, kind):
            self.u.mem_write(TILES, struct.pack("<I", kind << 1) * 0x10000)

    return WeatherEmu(game)


@pytest.fixture(scope="module")
def emu(vanilla):
    return _make_emu(vanilla)


def _fresh(emu, pick=lambda n: 0):
    """The weather as a new game or a load leaves it: zeroed objects, then the rain's constructor, then the
    reset 0x4923B0 (0x424110 runs it before every new game and every load)."""
    emu.faults.clear()
    emu.pick = pick
    emu.u.mem_write(WEATHER, bytes(0x38))
    emu.u.mem_write(RAIN, bytes(0x3008))
    emu.call(0x491E50, ecx=RAIN)
    emu.effect_clear()
    emu.tiles(0)
    for a in SCROLL:
        emu.w32(a, 0)
    emu.now = 1000
    emu.reset()


def _check_rain_lines(emu, lines):
    """Every drop's line runs from the drop to its previous point: never zero length, and the line drawer's
    divisor (2 x the longer side) is never 0."""
    for x1, y1, x2, y2 in lines:
        assert (x1, y1) != (x2, y2)
        assert 10 <= x1 - x2 <= 11 and 20 <= y1 - y2 <= 59, (x1, y1, x2, y2)
    assert all(d >= 40 for _a, d in emu.divisors), emu.divisors
    for k in range(512):
        x, y, px, py, sx, sy = emu.drop(k)
        assert 10 <= sx <= 11 and 20 <= sy <= 59


PICKS = {"every random 0": lambda n: 0, "every random n - 1": lambda n: n - 1}


@pytest.mark.parametrize("name", ["every random 0", "every random n - 1", "seeded"])
def test_rain_from_the_store_bottle(emu, name):
    """The rain bottle 0x417D60 (0x492280(2, 0) then 0x4921B0(2)) on a new game: the first draw has no drop
    (strength 0, 0x492315); the first update steps every drop (0x491B50) before the ramp 0x492488 gives the rain
    a strength, so every drawn line has its previous point set."""
    rng = random.Random(7)
    _fresh(emu, PICKS.get(name, lambda n: rng.randrange(n)))
    emu.frame()
    emu.run(0x417D60)
    assert emu.r(0) == 2 and emu.strength() == 0.0
    assert emu.draw() == []                          # the very first frame after the bottle: nothing drawn
    # the bottle also names rain as the next weather in 30 s (0x4921B0): the ramp-down starts from strength 0,
    # so the drops show once that second rain starts and ramps up (0x492670 / 0x492687 -> 0x492280)
    drawn = 0
    for seconds in (0, 1, 1, 5, 10, 14, 1, 5, 10):
        lines = emu.frame(seconds)
        _check_rain_lines(emu, lines)
        drawn += len(lines)
    assert drawn > 300 and emu.strength() > 0.4


def test_weather_changes_mid_rain(emu):
    """While it rains: storm, rain again with the island event's head start (0x443B3A passes a time), clear and
    rain again; each change re-randomises the drops (0x491AB0) without setting their previous points, and each
    starts at strength 0 (0x492315), so nothing is drawn until the next step."""
    rng = random.Random(11)
    _fresh(emu, lambda n: rng.randrange(n))
    emu.change(2)
    for _ in range(6):
        _check_rain_lines(emu, emu.frame(5))
    assert emu.strength() == 1.0
    for kind, ago in ((3, 0), (2, 25), (3, 400), (0, 0), (2, 0), (2, 0)):
        emu.change(kind, ago)
        assert emu.strength() == 0.0 and emu.draw() == []
        for _ in range(3):
            lines = emu.frame(2)
            if kind:
                _check_rain_lines(emu, lines)
            else:
                assert lines == []


def test_rain_while_paused_scrolled_and_respawned(emu):
    """Paused (no update, 0x445659) the rain is still drawn every frame; scrolling moves both ends of every line
    (0x491DB6..0x491DBE) and a drop pushed off the screen respawns at GetRandom(800), GetRandom(-561) = 0 with its
    previous point one step back (0x491DDE..0x491E08)."""
    rng = random.Random(3)
    _fresh(emu, lambda n: rng.randrange(n))
    emu.change(3)
    for _ in range(5):
        emu.frame(10)
    for dx, dy in ((0, 0), (300, 0), (0, 700), (-2000, -2000), (5, 5), (0, 0)):
        emu.w32(SCROLL[0], emu.r32(SCROLL[0]) + dx)
        emu.w32(SCROLL[1], emu.r32(SCROLL[1]) + dy)
        _check_rain_lines(emu, emu.draw())
        if abs(dx) >= 800 or abs(dy) >= 600:          # every drop left the screen: all respawned at y = 0
            for k in range(512):
                x, y, px, py, sx, sy = emu.drop(k)
                assert 0 <= x < 800 and y == 0 and (px, py) == (x - sx, y - sy)


def test_new_game_or_load_while_it_was_raining(emu):
    """The weather is not saved: every new game and every load runs 0x424110, which resets it (0x4241F1 ->
    0x4923B0).  The reset either starts clear weather at once (0x492405) or names the next weather for 30 s later
    (0x4923EB..0x4923FF); either way [weather + 8] is never 0 afterwards and the first rain starts at strength 0."""
    exe = emu.img
    call = lambda at, to: exe[at - BASE] == 0xE8 and struct.unpack_from("<i", exe, at + 1 - BASE)[0] == to - at - 5
    assert call(0x4241F1, 0x4923B0)
    for at in (0x41C182, 0x41C71A, 0x4243FE, 0x4245F3, 0x42478F, 0x4247C5):
        assert call(at, 0x424110), hex(at)
    # the 80 % branch (GetRandom(100) >= 20): clear weather now (0x492405, which sees [weather + 8] = 0 and so
    # sets a random strength at once, 0x4922E7), then clear again named for 30 s later (0x49240D)
    _fresh(emu, lambda n: n - 1)
    assert (emu.r(0), emu.r(4), emu.r(8)) == (0, 0, emu.now + 30)
    assert emu.strength() == pytest.approx(0.999)
    assert emu.draw() == []
    # the 20 % branch: clear now, rain named for 30 s later; the strength is the ramp's 0 / 0 (a NaN) until then
    for kind in (2, 3):
        emu.next_kind = kind
        _fresh(emu, lambda n: 0)
        assert (emu.r(0), emu.r(4), emu.r(8)) == (0, kind, emu.now + 30)
        assert emu.draw() == []
        emu.frame(10)
        assert math.isnan(emu.strength())             # +0x34 is still 0: x87 0 / 0, no fault
        while emu.r(0) != kind:
            assert emu.frame(10) == []
        assert emu.strength() == 0.0
        assert emu.draw() == []
        for _ in range(4):
            _check_rain_lines(emu, emu.frame(3))


def test_the_zero_length_line_needs_a_state_the_game_never_has(emu):
    """The Virtual Villagers crash shape: a drop drawn before its first step is a line to the previous point the
    constructor left (0, 0).  It is only drawn when the rain starts at a strength above 0, which 0x492280 does
    only when [weather + 8] is 0 (0x4922E1) -- the zeroed memory at start-up, before any game.  Put in that state
    by hand, with every drop at (0, 0), the stock game divides by zero at 0x4043B2."""
    _fresh(emu, lambda n: 0)
    emu.u.mem_write(WEATHER, bytes(0x38))             # NOT a state of play: [weather + 8] = 0
    emu.u.mem_write(RAIN, bytes(0x3008))
    emu.call(0x491E50, ecx=RAIN)
    emu.pick = lambda n: 999 if n == 1000 else 0      # strength GetRandom(1000) / 1000 = 0.999, drops at (0, 0)
    emu.call(0x492280, (2, 0), ecx=WEATHER)
    assert emu.faults == [] and emu.strength() > 0.99
    assert emu.drop(0)[:4] == (0, 0, 0, 0)
    emu.lines = []
    emu.divisors = []
    emu.call(0x4920F0, ecx=WEATHER)
    assert emu.faults == [(0, LINE_DIV_Y)]
    assert emu.lines[-1] == (0, 0, 0, 0) and emu.divisors[-1] == (LINE_DIV_Y, 0)
    emu.faults.clear()
    # every writer of [weather + 8]: the reset (0, then at once one of the two below), 0x492366 (now + 360..2400)
    # and 0x4921C7 (now + 30); no other code writes it (no absolute 0x8352AC operand anywhere)
    exe = emu.img
    assert exe[0x4923CF - BASE:0x4923D2 - BASE] == bytes.fromhex("897e08")
    assert exe[0x492366 - BASE:0x492369 - BASE] == bytes.fromhex("894608")
    assert exe[0x4921C7 - BASE:0x4921CA - BASE] == bytes.fromhex("894608")
    assert struct.pack("<I", WEATHER + 8) not in exe[0x1000:0xB2000]


def test_rain_splashes_and_the_effects_clock(emu):
    """The rain's splashes (0x491C56..0x491CF3): a random point on the screen, its ground kind from the tile map
    (0x4928B0: tile x, y clamped to 0..255, index (x << 8) + y), and AddEffect 0x421810 of a splash (0x14) on
    kind 2 or a ground splash (0) on kinds 4 and 5; then every splash played to its end by the effects clock
    0x421B50 and the effect draw 0x421A30."""
    rng = random.Random(5)
    for kind in (0, 1, 2, 3, 4, 5, 6, 7):
        _fresh(emu, lambda n: rng.randrange(n))
        emu.tiles(kind)
        emu.change(2)
        for _ in range(8):
            _check_rain_lines(emu, emu.frame(4))
        entries = [emu.effect_entry(k) for k in range(0x200)]
        live = [k for k, e in enumerate(entries) if e["type"] != -1]
        expect = {2: 0x14, 4: 0, 5: 0}.get(kind)
        assert {entries[k]["type"] for k in live} == (set() if expect is None else {expect}), kind
        for _ in range(60):
            for k in live:
                if emu.effect_entry(k)["type"] != -1:
                    emu.effect_draw(k)
                    assert emu.faults == []
            emu.call(0x421B50, ecx=EFFECTS)
            assert emu.faults == []
    # the tile lookup's clamps, on the far corners and beyond
    for x, y in ((-50, -50), (0, 0), (2047, 2047), (2048, 2048), (100000, -100000), (-1, 5000)):
        emu.call(0x4928B0, (x, y), ecx=TILES)
        assert emu.faults == []


def test_storm_lightning(emu):
    """The storm (kind 3): the lightning clock 0x490930 (SDL_GetTicks, GetRandom(100), GetRandom(25000)) and the
    flash 0x4909F0 (a fill of the screen rectangle 0x4FE180 in the constant colour 0x4FDE6C)."""
    rng = random.Random(9)
    _fresh(emu, lambda n: rng.randrange(n))
    emu.change(3)
    flashes = 0
    for _ in range(40):
        emu.ticks += rng.choice((20, 150, 5000, 30000))
        _check_rain_lines(emu, emu.frame(3))
        fills = [r for r in emu.records if r[0] == "fill"]
        assert all(r[1] == (0, 0, 800, 561) for r in fills)
        flashes += len(fills) == 2                   # the haze, then the flash
    assert flashes > 0


def test_sunbeams(emu):
    """Sunny weather (kind 1): the 64 sunbeams' set-up 0x491EA0 (random map points 0..2047, 0x495E20), their fade
    0x491F10 (divides by GetRandom(100) + 100 as a float: 100..199) and the draw 0x492040."""
    for pick in (lambda n: 0, lambda n: n - 1, None):
        rng = random.Random(1)
        _fresh(emu, pick or (lambda n: rng.randrange(n)))
        emu.change(1)
        for k in range(64):
            x, y = emu.r32(SUN + 0x14 * k), emu.r32(SUN + 0x14 * k + 4)
            assert 0 <= x <= 0x7FF and -300 <= y <= 0x7FF - 300
        for _ in range(10):
            emu.frame(4)
        for k in range(8):                            # some sunbeams on the screen (above its top edge)
            emu.w32(SUN + 0x14 * k, 50 + 90 * k)
            emu.w32(SUN + 0x14 * k + 4, -60)
        emu.draw()
        assert len(emu.blits) >= 8
        assert all(0.0 <= b["alpha"] <= 1.0 for b in emu.blits)


def test_a_zero_ramp_span_gives_nan_strength_and_no_fault(emu):
    """The ramp divides by its span +0x34 (0x4924B7, 0x4925AF: x87 fidiv, masked: 0 / 0 is a NaN, not a fault).
    The span is 0 before the first change (zeroed memory) and when the ramp-down 0x492481 starts with 0 s left.
    A NaN strength or haze stops the rain's loops (0x491D3E, 0x491E2C), the splash (0x491C50), the lightning
    (0x490940) and the haze fill (0x492137); the sunbeams draw with a NaN alpha, which the game's own blitter
    0x404C30 draws without a fault (run below on real pixels).  The next update changes the weather and the
    strength is a number again."""
    rng = random.Random(2)
    for kind in (1, 2, 3):
        _fresh(emu, lambda n: rng.randrange(n))
        emu.change(kind)
        for _ in range(4):
            emu.frame(10)
        emu.now = emu.r(8) - 0                        # the first ramp check sees 0 s left
        emu.ticks += 40000
        emu.update()
        for k in range(8):                            # some sunbeams on the screen (above its top edge)
            emu.w32(SUN + 0x14 * k, 50 + 90 * k)
            emu.w32(SUN + 0x14 * k + 4, -60)
            emu.wf(SUN + 0x14 * k + 8, 0.75)
        assert emu.r32(WEATHER + 0x34) == 0 and math.isnan(emu.strength())
        lines = emu.draw()
        assert lines == []
        if kind == 1:
            assert emu.blits and all(math.isnan(b["alpha"]) for b in emu.blits)
        assert all(not math.isnan(sum(r[2])) for r in emu.records if r[0] == "fill")
        _check_rain_lines(emu, emu.frame(1))           # the next update changes the weather: strength 0 again
        assert not math.isnan(emu.strength())
    # the blitter itself with the alphas a sunbeam can get (NaN included), on real pixels
    src = emu._surface("beam", 16, 16)
    emu.u.mem_write(emu.r32(src + 0x14), bytes(range(256)) * 4)
    screen = emu.rain_screen
    pixels = emu.r32(screen + 0x14)
    from picture_emu import STACK, STOP
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP
    size = (SCREEN_W + 1) * (SCREEN_H + 1) * 4
    region = 40 * 4 * (SCREEN_W + 1)
    for alpha in (math.nan, 0.0, 0.5, 0.999):
        emu.u.mem_write(pixels, (bytes(range(256)) * (size // 256 + 1))[:size])
        before = bytes(emu.u.mem_read(pixels, region))
        emu.run_blits = True
        try:
            esp = STACK - 0x1000
            emu.u.mem_write(esp + 4, struct.pack("<IiiiiiiffI", src, 10, 10, 0, 0, 16, 16, alpha, 1.0, 0))
            emu.u.mem_write(esp, struct.pack("<I", STOP))
            emu.u.reg_write(UC_X86_REG_ESP, esp)
            emu.u.reg_write(UC_X86_REG_ECX, emu.impl)
            emu._fldcw()
            emu.u.emu_start(0x404C30, STOP, count=5_000_000)
        finally:
            emu.run_blits = False
        assert emu.faults == [], alpha
        assert emu.u.reg_read(UC_X86_REG_EIP) == STOP, alpha       # returned (not stopped by the count)
        changed = bytes(emu.u.mem_read(pixels, region)) != before
        assert changed == (alpha > 0 or math.isnan(alpha)), alpha   # NaN passes its alpha tests: drawn, no fault


def test_night_lamps_never_use_a_missing_mask(vanilla):
    """Assets\\lsmap.dat (the only lamps 0x491550 sets up) has kinds 4, 6, 8, 9 and 11, whose masks are all in
    the game; kinds 1, 2, 5 and 7 (LightSourceMask300x10 / 180x8 / 200x10, missing from the game) are made only by
    the light editor CLightSourceEditor, whose one object 0x56B070 is referenced only by its own static
    initializer 0x4B17B0, so its methods are never called."""
    import vf1_art_house as h
    import vf1_game_art as ga
    files = ga.GameFiles(vanilla)
    kinds = {kind for kind, _x, _y, _who in h.lamps(files)}
    assert 0 in kinds                                 # empty slots: 0x490A80 sets nothing up (0x490AB5..0x490B06)
    kinds.discard(0)
    assert kinds == {4, 6, 8, 9, 11}
    masks = {1: 0xB3, 2: 0xB0, 3: 0xAE, 4: 0xAF, 5: 0xB1, 6: 0xB2, 7: 0xB3, 8: 0xB4, 9: 0xB5, 10: 0xB6, 11: 0xB7}
    for kind in kinds:
        assert files.has(ga.TABLE[masks[kind]][0]), kind
    assert not any(files.has(ga.TABLE[i][0]) for i in (0xB0, 0xB1, 0xB3))
    pefile = pytest.importorskip("pefile")
    img = bytes(pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True).get_memory_mapped_image())
    refs, k = [], img.find(struct.pack("<I", 0x56B070))
    while k >= 0:
        refs.append(k + BASE)
        k = img.find(struct.pack("<I", 0x56B070), k + 1)
    assert refs == [0x4B17B1]


def test_darkness_with_a_zero_twilight(emu):
    """The night's darkness 0x491810 divides by the twilight span +0x67C as a float; a 0 span cannot divide (the
    ranges that divide are empty) and gives no fault."""
    for span in (0.0, 0.5, 1.0):
        for hour in (0.0, 5.99, 6.0, 6.5, 12.0, 18.0, 18.5, 23.9):
            emu.faults.clear()
            value = emu.darkness(hour, 6.0, 18.0, span, False)
            assert emu.faults == []
            assert not math.isnan(value)


# ===================================================================== every division the weather can reach
ROOTS = {
    0x4920F0: "the weather draw", 0x492420: "the weather update", 0x492280: "a weather change",
    0x4923B0: "the reset", 0x4921B0: "the next weather", 0x4921D0: "the ramp", 0x417D60: "the rain bottle",
    0x417D40: "the rain bottle's test", 0x491550: "the lamps' set-up",
    0x491480: "sunrise and sunset", 0x4919A0: "the darkness", 0x4908C0: "the fog picture", 0x491EF0: "the sunbeam "
    "picture", 0x491E50: "the rain's constructor", 0x4920C0: "the sunbeams' constructor", 0x4918E0: "the night's "
    "constructor", 0x4908E0: "the fog's constructor", 0x490A40: "the lightning's constructor", 0x4926C0: "the tile "
    "map", 0x421810: "AddEffect", 0x421B50: "the effects clock", 0x421A30: "the effect draw",
}
# what the walk reaches (every one is a row of the audit table, none a crash)
REACHED = {
    0x403668, 0x4043A8, 0x4043B2, 0x40B135, 0x40B142, 0x421A6E, 0x421A8B,
    0x408953, 0x408962, 0x408E23, 0x408E32, 0x40AD51, 0x40AD63, 0x40AD7C, 0x40AE68, 0x40AE77, 0x40B02A, 0x40B037,
    0x40B043, 0x40B04E, 0x40F8EE, 0x40F920, 0x411C8B,
    0x405177, 0x40519E, 0x4051CF, 0x4051F5, 0x405223, 0x405249, 0x405265, 0x405285, 0x4052AF, 0x4052D5, 0x405303,
    0x405329, 0x405356, 0x40536B, 0x405379, 0x40538B, 0x405396, 0x4053AB, 0x4053B9, 0x4053CB, 0x4053D5,
    0x406270, 0x40629B, 0x4062D1, 0x4062F5, 0x40631B, 0x40633B, 0x40634D, 0x406376, 0x4063A0, 0x4063CB, 0x4063F9,
    0x406424, 0x406449, 0x406472, 0x406496, 0x4064C4, 0x4064E8, 0x4064FB, 0x406529, 0x406548, 0x406578, 0x406593,
}


def _walk(img):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    seen, divs, todo = set(), set(), deque(ROOTS)
    while todo:
        a = todo.popleft()
        while 0x401000 <= a < 0x4B2000 and a not in seen:
            ins = next(md.disasm(img[a - BASE:a - BASE + 16], a), None)
            if ins is None:
                break
            seen.add(a)
            m, op = ins.mnemonic, ins.op_str
            if m in ("div", "idiv"):
                divs.add(a)
            if m == "ret":
                break
            if m in ("call", "jmp") or m.startswith("j"):
                if op.startswith("0x"):
                    todo.append(int(op, 16))
                elif m == "jmp" and "*4 +" in op:
                    tab = int(op.split("+ ")[-1].rstrip("]"), 16)
                    k = 0
                    while 0x401000 <= struct.unpack_from("<I", img, tab + 4 * k - BASE)[0] < 0x4B2000 and k < 64:
                        todo.append(struct.unpack_from("<I", img, tab + 4 * k - BASE)[0])
                        k += 1
                if m == "jmp":
                    break
            a += ins.size
    return divs


def test_every_division_the_weather_reaches_is_a_safe_row_of_the_audit(vanilla):
    pefile = pytest.importorskip("pefile")
    img = bytes(pefile.PE(str(vanilla / "Virtual Families.exe"), fast_load=True).get_memory_mapped_image())
    divs = _walk(img)
    text = DOC.read_text(encoding="utf-8").split("## Table", 1)[1].split("\n## ", 1)[0]
    classes = {}
    for line in text.splitlines():
        if line.startswith("| 0x"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            for s in cells[0].split(", "):
                classes[int(s, 16)] = cells[4]
    game = {a for a in divs if a < 0x497848}
    assert game == REACHED, " ".join(f"0x{a:X}" for a in sorted(game))
    for a in divs:
        assert a in classes, hex(a)
        assert classes[a] in ("SAFE-CONSTANT", "GUARDED", "UNREACHABLE-ZERO"), hex(a)
    assert not any(0x4908B0 <= a < 0x4928E0 for a in divs)     # the weather's own code has no division
