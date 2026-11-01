"""Runs Virtual Families 1's own house, yard, weather and night drawing code in Unicorn, for
tests/test_art_house.py.  Built on tests/picture_emu.py's Emu (the same window, graphics manager and
BlitRectWithAlpha 0x404C30 recorder).

Game code that runs as it is (on the vanilla Virtual Families.exe in VF1_VANILLA_DIR, read only):

* the map: the loader 0x495C60 (it names the 16 tiles "%sX%01dY%01d.jpg" with "Map" and gives each its
  place) and the draw 0x495D90 (-> ldwGameWindow 0x4098C0 -> 0x408680 -> 0x404C30);
* the house pictures: their loader 0x41FD50 (GetImageGrid for every id, kept at 0x502278 + 0x1804..),
  the list builder 0x420BC0 (the rooms, objects and their states; it ends in 0x420200, the
  malfunctions), and the list draw 0x420130 (-> 0x409970 -> 0x4089B0 -> 0x404C30);
* the effects: the table loader 0x4217B0, CEnvironment::SetProp 0x4938C0 (it starts the TV and computer
  animations), AddEffect 0x421810, the frame step 0x421B50 and the draw 0x421A30 (-> 0x44EC90 -> 0x404C30);
* the weather: the sunbeams 0x492040 (-> 0x4098D0 -> 0x404C30), the haze and lightning fills
  (0x4920F0, 0x4909F0 -> 0x408190 / 0x408100);
* the night: the light setup 0x490A80 for each Assets\\lsmap.dat entry (as 0x491550 does), the darkness
  0x491810, and the night draw 0x4919D0 with its light update 0x490C90;
* the fill blend 0x403B40 itself, on a small screen, for the pixels.

Stood in for (not drawing logic): theGraphicsManager's getters (grids laid out as ldwImageGrid), operator new,
sprintf (the CRT), the image file loader 0x40ABE0 and the surface maker 0x40AC50 (a named surface), the sound
calls, the game clock (CGameTime::Seconds 0x422320 = 0), GetRandom 0x403650 (= 0, so an animation starts on its first frame), the current hour's darkness (0x4919A0 returns the
value asked for), and three SDL calls the night draw makes on surfaces that hold no pixels here: the screen
copy 0x4045C0, the mask copy 0x40AD10 and the fill 0x403B40 are recorded with their arguments.  SDL_MapRGB /
SDL_MapRGBA are answered from the surface format (the fill's pixel run).
"""
from __future__ import annotations

import struct
from pathlib import Path

import vf1_game_art as ga
from picture_emu import Emu
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

HOUSE = 0x502278            # the house pictures object (list at +0, grids +0x1804.., window +0x18D0, state +0x18D4)
ENV = 0x8752F0              # CEnvironment: prop p's active byte at +4 + 8p
EFFECTS = 0x503B68          # the effects (0x200 entries of 0x44 at +4)
TECH = 0x50C620             # CTech: room levels at +0, +4, +8
FOOD = 0x50C550
STATE_PTR = 0x50025C        # theGameState::Get's instance
SCROLL = (0x895784, 0x895788)
MAP = 0x8756B0
NIGHT = 0x831700            # the lights (20 of 0x50) and the night colour +0x658
SUN = 0x834D98              # the sunbeams (64 of 0x14), the picture at +0x500
WEATHER = 0x8352A4          # +0 kind, +0x1C haze alpha, +0x28 strength (0x8352CC)
DYNAMIC = (0x491630, 0x491D20, 0x4919D0, 0x492040, 0x4978E6, 0x4978FE)


class HouseEmu(Emu):
    def __init__(self, game: Path) -> None:
        self.files = ga.GameFiles(Path(game))
        self.grid_image: dict[int, int] = {}
        super().__init__(game)
        u = self.u
        u.mem_map(0, 0x1000)                         # fs:[0] (the SEH frames) with fs at 0
        self.records: list[tuple] = []
        self.surface_names: dict[int, str] = {}
        self.float_out = self.alloc(16)
        self.dark = 0.0
        hooks = {
            0x497B14: self._new,                     # operator new (cdecl)
            0x4985BB: self._sprintf,                 # sprintf (cdecl)
            0x40ABE0: self._image_ctor,              # ldwImage(name), thiscall ret 4
            0x40AC50: self._image_new,               # ldwImage(w, h, alpha), thiscall ret 0xC
            0x422320: self._ret_value(0, 0),         # CGameTime::Seconds
            0x44C500: self._ret_value(1, 4),         # sound: is playing (so none is started)
            0x44C560: self._ret_value(0, 4),
            0x44C390: self._ret_value(0, 0xC),
            0x44C580: self._ret_value(0, 8),
            0x4045C0: self._record("copy", 4, 0x10),         # the screen copy into a light's surface
            0x40AD10: self._record_mask,                     # the mask's alpha into a light's surface
            0x403B40: self._record_fill,                     # the fill (rect, r, g, b, a)
            0x4919A0: self._darkness,                        # this hour's darkness (float)
            0x404BC0: self._plain_blit,                      # ldwGameWindowImpl's plain SDL_UpperBlit draw
            0x491690: self._ret_value(0, 0),                 # the evening test (set by night())
        }
        self._stub_page = self.alloc(64)
        self.run_fill = False
        self._code_hooks[0x403650] = self._ret_value(0, 0)   # GetRandom (picture_emu hooks the address): 0
        for address, fn in hooks.items():
            self._code_hooks[address] = fn
        # addresses stood in for only during one call (their entries come and go in _code_hooks)
        for address in list(hooks) + list(DYNAMIC):
            u.hook_add(UC_HOOK_CODE, self._code, begin=address, end=address)
        state = self.alloc(0x1B830)
        self.state = state
        self.w32(STATE_PTR, state)
        for a in SCROLL:
            self.w32(a, 0)

    # -------------------------------------------------------------- stand-ins
    def _args(self, n: int) -> list[int]:
        esp = self.u.reg_read(UC_X86_REG_ESP)
        return list(struct.unpack(f"<{n}I", self.u.mem_read(esp + 4, 4 * n)))

    def _new(self, _self) -> None:
        (size,) = self._args(1)
        self._ret_value(self.alloc(max(size, 4)), 0)(self)

    def _cstr(self, a: int) -> str:
        out = bytearray()
        while True:
            b = self.u.mem_read(a + len(out), 1)[0]
            if not b:
                return out.decode("latin-1")
            out.append(b)

    def _sprintf(self, _self) -> None:
        buf, fmt, a, b, c = self._args(5)
        text = self._cstr(fmt)
        assert text == "%sX%01dY%01d.jpg", text
        out = f"{self._cstr(a)}X{b:01d}Y{c:01d}.jpg".encode() + b"\0"
        self.u.mem_write(buf, out)
        self._ret_value(len(out) - 1, 0)(self)

    def _named_surface(self, name: str) -> int:
        if name not in self.surface_of:
            w, h = self.files.size(name) if self.files.has(name) else (0, 0)
            self.surface_of[name] = self._surface(name, w, h, pixels=False)
        return self.surface_of[name]

    def _image_ctor(self, _self) -> None:
        this = self.u.reg_read(UC_X86_REG_ECX)
        (name_ptr,) = self._args(1)
        impl = self.alloc(16)
        self.w32(impl, self._named_surface(self._cstr(name_ptr)))
        self.w32(this, 0x4B2820)
        self.w32(this + 4, impl)
        self._ret_value(this, 4)(self)

    def _image_new(self, _self) -> None:
        this = self.u.reg_read(UC_X86_REG_ECX)
        w, h, _alpha = self._args(3)
        name = f"light surface {len(self.surface_names)}"
        surf = self._surface(name, w, h, pixels=False)
        impl = self.alloc(16)
        self.w32(impl, surf)
        self.surface_names[impl] = name
        self.w32(this, 0x4B2820)
        self.w32(this + 4, impl)
        self._ret_value(this, 0xC)(self)

    def _record(self, what: str, n: int, clean: int):
        def run(_self):
            self.records.append((what, self.u.reg_read(UC_X86_REG_ECX), *self._args(n)))
            self._ret_value(0, clean)(self)
        return run

    def _plain_blit(self, _self) -> None:
        """0x404BC0(surface, x, y, left, top, right, bottom): the whole-picture draw (0x408680, 0x408720's
        alpha 1 path) blits the rectangle with SDL_UpperBlit, as 0x404C30 does at scale 1 and alpha 1."""
        surf, x, y, x0, y0, x1, y1 = struct.unpack("<Iiiiiii", self.u.mem_read(self.u.reg_read(UC_X86_REG_ESP) + 4, 28))
        self.blits.append({"file": self.surfaces.get(surf, "?"), "rect": (x0, y0, x1, y1), "x": x, "y": y,
                           "alpha": 1.0, "scale": 1.0, "centre": 0, "plain": True})
        self._ret_value(0, 0x1C)(self)

    def _record_mask(self, _self) -> None:
        grid = self.u.reg_read(UC_X86_REG_ECX)
        dest, x, y, rect = self._args(4)
        r = struct.unpack("<4i", self.u.mem_read(rect, 16))
        self.records.append(("mask", grid, dest, x, y, r))
        self._ret_value(0, 0x10)(self)

    def _record_fill(self, _self) -> None:
        if self.run_fill:
            return
        esp = self.u.reg_read(UC_X86_REG_ESP)
        rect_ptr = struct.unpack("<I", self.u.mem_read(esp + 4, 4))[0]
        floats = struct.unpack("<4f", self.u.mem_read(esp + 8, 16))
        rect = struct.unpack("<4i", self.u.mem_read(rect_ptr, 16))
        self.records.append(("fill", rect, floats))
        self._ret_value(0, 0x14)(self)

    def _darkness(self, _self) -> None:
        # return self.dark on the x87 stack: run "fld dword [float_out]; ret" in place of the call
        self.wf(self.float_out, self.dark)
        stub = self._stub_page
        self.u.mem_write(stub, b"\xD9\x05" + struct.pack("<I", self.float_out) + b"\xC3")
        self.u.reg_write(UC_X86_REG_EIP, stub)

    # -------------------------------------------------------------- the grids (every id of the table)
    def grid(self, image: int) -> int:
        if image in self.grids:
            return self.grids[image]
        name, cols, rows, files = ga.TABLE[image]
        assert files == 1
        surf = self._named_surface(name)
        w = self.r32(surf + 8)
        h = self.r32(surf + 0xC)
        impl = self.alloc(16)
        self.w32(impl, surf)
        g = self.alloc(0x40)
        self.w32(g, 0x4B2820)
        self.w32(g + 4, impl)
        c = cols if cols else 1
        r = rows if rows else 1
        self.w32(g + 8, c)
        self.w32(g + 0xC, r)
        self.w32(g + 0x10, w // c)
        self.w32(g + 0x14, h // r)
        self.grids[image] = g
        self.grid_image[g] = image
        return g

    def f(self, v: float) -> int:
        return struct.unpack("<I", struct.pack("<f", v))[0]

    # -------------------------------------------------------------- the map
    def map_draws(self) -> tuple[list[dict], list[tuple[str, int, int]]]:
        """The loader 0x495C60, then the draw 0x495D90 with no scroll and a clip big enough for the whole
        map.  Returns (the draws, the loader's table: (file, x, y) per entry)."""
        self.call(0x495C60, ecx=MAP)
        table = []
        for k in range(16):
            e = MAP + 0xC * k
            image = self.r32(e)
            impl = self.r32(image + 4)
            surf = self.r32(impl)
            table.append((self.surfaces[surf], self.r32(e + 4), self.r32(e + 8)))
        self.blits = []
        self.call(0x495D90, (0, 0, 0, 0, 4000, 4000), ecx=MAP)
        return list(self.blits), table

    # -------------------------------------------------------------- the house pictures
    def house_setup(self) -> None:
        self.w32(HOUSE + 0x18D0, self.window)
        self.w32(HOUSE + 0x18D4, self.state)
        self.call(0x41FD50, ecx=HOUSE)

    def house_grids(self) -> dict[int, int]:
        """The loader's grids: list offset -> image id."""
        out = {}
        for off in range(0x1804, 0x18D0, 4):
            g = self.r32(HOUSE + off) & 0xFFFFFFFF
            if g in getattr(self, "grid_image", {}):
                out[off] = self.grid_image[g]
        return out

    def clear_state(self) -> None:
        self.u.mem_write(ENV + 4, bytes(58 * 8))
        self.u.mem_write(self.state, bytes(0x400))
        self.u.mem_write(TECH, bytes(12))
        self.w32(FOOD, 0)

    def house_draws(self) -> list[dict]:
        """0x420BC0 (the list, ending in 0x420200), then the list draw 0x420130."""
        self.call(0x420BC0, ecx=HOUSE)
        self.blits = []
        self.call(0x420130, ecx=HOUSE)
        return list(self.blits)

    def prop(self, p: int, on: bool = True) -> None:
        self.u.mem_write(ENV + 4 + 8 * p, bytes([1 if on else 0]))

    def state_byte(self, off: int, v: int) -> None:
        self.u.mem_write(self.state + off, bytes([v & 0xFF]))

    def state_int(self, off: int, v: int) -> None:
        self.w32(self.state + off, v)

    # -------------------------------------------------------------- the effects
    def effects_setup(self) -> None:
        self.call(0x4217B0)
        self.call(0x421D60, ecx=EFFECTS)

    def effect_clear(self) -> None:
        for k in range(0x200):
            self.w32(EFFECTS + 4 + 0x44 * k, 0xFFFFFFFF)

    def effect_entry(self, index: int) -> dict:
        e = EFFECTS + 4 + 0x44 * index
        return {"type": self.r32(e), "x": self.r32(e + 8), "y": self.r32(e + 0xC), "centred": self.u.mem_read(e + 0x10, 1)[0],
                "frame": self.r32(e + 0x14), "frames": self.r32(e + 0x18), "delay": self.r32(e + 0x1C),
                "loop": self.u.mem_read(e + 0x38, 1)[0], "mode": self.r32(e + 4), "layer": self.r32(e + 0x3C),
                "cell": self.r32(e + 0x34)}

    def set_prop(self, p: int) -> None:
        self.call(0x4938C0, (p,), ecx=ENV)

    def effect_draw(self, index: int, frame: int | None = None) -> list[dict]:
        if frame is not None:
            self.w32(EFFECTS + 4 + 0x44 * index + 0x14, frame)
        self.blits = []
        self.call(0x421A30, (index,), ecx=EFFECTS)
        return list(self.blits)

    def add_effect(self, *args) -> int:
        return self.call(0x421810, args, ecx=EFFECTS)

    def effect_step(self) -> None:
        self.call(0x421B50, ecx=EFFECTS)

    # -------------------------------------------------------------- the weather
    def sunbeam_draws(self, x: int, y: int, alpha: float, strength: float) -> list[dict]:
        for k in range(64):
            e = SUN + 0x14 * k
            self.w32(e, 0)
            self.w32(e + 4, 100000)               # below the screen's top: not drawn (0x492068)
            self.wf(e + 8, 0.0)
        self.w32(SUN, x)
        self.w32(SUN + 4, y)
        self.wf(SUN + 8, alpha)
        self.wf(WEATHER + 0x28, strength)
        self.w32(SUN + 0x500, self.grid(0xA6))
        self.blits = []
        self.call(0x492040, ecx=SUN)
        return list(self.blits)

    def weather_fills(self, kind: int, haze: float, daytime: bool, flash: bool) -> list[tuple]:
        """0x4920F0 with the weather `kind`, the haze alpha +0x1C, daytime or not, and the lightning flash
        on or off; the rain (kind 2/3) is stood in for (its streaks are lines, 0x491D20) and the night (0x4919D0)
        too: only the fills are kept."""
        self.records = []
        self.w32(WEATHER, kind)
        self.wf(WEATHER + 0x1C, haze)
        self.u.mem_write(0x8316EC, bytes([1 if flash else 0]))
        self._code_hooks[0x491630] = self._ret_value(1 if daytime else 0, 0)
        self._code_hooks[0x491D20] = self._ret_value(0, 0)
        self._code_hooks[0x4919D0] = self._ret_value(0, 0)
        self._code_hooks[0x492040] = self._ret_value(0, 0)
        try:
            self.call(0x4920F0, ecx=WEATHER)
        finally:
            for a in (0x491630, 0x491D20, 0x4919D0, 0x492040):
                del self._code_hooks[a]
        return [r for r in self.records if r[0] == "fill"]

    # -------------------------------------------------------------- the night
    def lights_setup(self, entries: list[tuple[int, int, int, int]]) -> None:
        """Each lsmap.dat entry (type, x, y, villager) put in its slot and set up by 0x490A80, as 0x491550
        does."""
        self.u.mem_write(NIGHT, bytes(20 * 0x50))
        for k, (kind, x, y, who) in enumerate(entries[:20]):
            if not 0 <= kind <= 0xB:
                continue
            e = NIGHT + 0x50 * k
            self.w32(e, kind)
            self.w32(e + 4, x)
            self.w32(e + 8, y)
            self.w32(e + 0xC, who)
            self.call(0x490A80, (e,), ecx=NIGHT)
        # the night colour 0x4918E0 sets (R 0, G 0, B 0x66, A 0xB2 in memory order)
        self.u.mem_write(NIGHT + 0x658, bytes([0, 0, 0x66, 0xB2]))

    def light(self, k: int) -> dict:
        e = NIGHT + 0x50 * k
        grid = self.r32(e + 0x1C) & 0xFFFFFFFF
        return {"type": self.r32(e), "x": self.r32(e + 4), "y": self.r32(e + 8), "who": self.r32(e + 0xC),
                "animated": self.u.mem_read(e + 0x10, 1)[0], "w": self.r32(e + 0x14), "h": self.r32(e + 0x18),
                "image": getattr(self, "grid_image", {}).get(grid), "frames": self.r32(e + 0x20),
                "surface": self.r32(e + 0x28) & 0xFFFFFFFF}

    def night(self, darkness: float, screen: tuple[int, int, int, int] = (0, 0, 800, 561)) -> tuple[list[tuple], list[dict]]:
        """0x4919D0 with this hour's darkness: (the records: copies, masks, fills), (the light draws)."""
        self.dark = darkness
        self.records = []
        self.blits = []
        self.call(0x4919D0, ecx=NIGHT)
        return list(self.records), list(self.blits)

    def darkness(self, hour: float, sunrise: float, sunset: float, span: float, evening: bool) -> float:
        """0x491810(hour) with the day's sunrise +0x674, sunset +0x678 and twilight +0x67C set; the evening
        test 0x491690 answers `evening`."""
        self.wf(NIGHT + 0x674, sunrise)
        self.wf(NIGHT + 0x678, sunset)
        self.wf(NIGHT + 0x67C, span)
        self._code_hooks[0x491690] = self._ret_value(1 if evening else 0, 0)
        stub = self.alloc(32)
        out = self.alloc(4)
        code = (b"\x68" + struct.pack("<f", hour) + b"\xB9" + struct.pack("<I", NIGHT)
                + b"\xE8" + struct.pack("<i", 0x491810 - (stub + 10 + 5))
                + b"\xD9\x1D" + struct.pack("<I", out) + b"\xC3")
        self.u.mem_write(stub, code)
        self.call(stub)
        return self.rf(out)

    # -------------------------------------------------------------- the fill's own pixels
    def fill_pixels(self, before: bytes, w: int, h: int, colour: tuple[float, float, float, float]) -> bytes:
        """Runs the fill 0x403B40 itself (rect = the whole w x h screen, the colour as its four floats) on a
        screen surface whose memory holds `before` (R, G, B, X bytes per pixel); returns the memory after."""
        surf = self._surface("fill screen", w, h, alpha=False)
        pixels = self.r32(surf + 0x14)
        self.u.mem_write(pixels, before)
        impl = self.alloc(0x80)
        self.w32(impl + 0x30, surf)
        for k, v in enumerate((0, 0, w, h)):
            self.w32(impl + 0x60 + 4 * k, v)
        rect = self.alloc(16)
        self.u.mem_write(rect, struct.pack("<4i", 0, 0, w, h))

        def map_rgba(_self):
            _f, r, g, b, a = self._args(5)
            self._ret_value(r | (g << 8) | (b << 16) | (a << 24), 0)(self)

        def map_rgb(_self):
            _f, r, g, b = self._args(4)
            self._ret_value(r | (g << 8) | (b << 16), 0)(self)

        extra = {0x4978E6: map_rgba, 0x4978FE: map_rgb}
        self._code_hooks.update(extra)
        self.run_fill = True
        try:
            self.call(0x403B40, (rect, *(self.f(c) for c in colour)), ecx=impl)
        finally:
            self.run_fill = False
            for a in extra:
                del self._code_hooks[a]
        return bytes(self.u.mem_read(pixels, w * h * 4))
