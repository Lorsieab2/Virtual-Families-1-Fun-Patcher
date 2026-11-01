"""Runs Virtual Families 1's own meter and bar drawing code in Unicorn, for tests/test_art_meters.py.

Built on tests/picture_emu.py's Emu (the vanilla exe in VF1_VANILLA_DIR, read only).  What runs as the
game's own code:

* the bar painter: its constructor 0x44EE20 (it fetches pictures 0x38, 0x39, 7..0xC into its fields
  +8..+0x24) and its one drawing function 0x44EEA0 (kind, value), with the clip setter 0x408410 / reset
  0x408440, the picture draw 0x4098C0 -> 0x408680, the clip test 0x407E60 and theGraphicsManager's table
  lookup 0x44F2D0 and its draw-by-number 0x44F960;
* the Details screen's drawing function 0x44B890 (theVillagerScene's vtable slot 0x4B72A0), which reads a
  family member's numbers and asks the painter for its five bars;
* the loading screen's drawing function 0x4406D0 (theLoadingScene's vtable slot 0x4B6FC4);
* one achievement row 0x412D00 (as the Awards screen 0x4353EA calls it), with 0x412CA0 (its percent);
* the bank's "Next 7 Days" chart 0x415300 (CBankingDlg's vtable slot 0x4B4508), with the outline 0x409B70,
  the lines 0x4081D0 / 0x408270 / 0x403DD0 and the colour fill 0x408100.

Recorded: every picture draw where it reaches a blitter (ldwGameWindowImpl::BlitRectWithAlpha 0x404C30,
via picture_emu, and the plain blit 0x404BC0 that 0x408680 uses), and every solid fill where it reaches
0x403B40 (rect left, top, right, bottom and the four colour floats r, g, b, a in that order: 0x403B40
hands the first three to SDL_MapRGB as r, g, b and compares the fourth with 1.0).

Stood in for (not drawing logic): theGraphicsManager (its getters hand out grid objects as picture_emu
does; 0x44F7C0 returns a manager whose +4 is the game window), the painter's singleton getter 0x44F1F0
(returns a painter built by the game's own constructor), the game state 0x423660, the family member lookup
0x48AFE0 / 0x489900, the portrait 0x486B60, every text draw and string lookup (0x409D20, 0x409CC0,
0x409CD0, 0x44FD90, 0x450530, 0x4173A0, 0x4226A0, 0x4985BB, 0x425200): the words the game writes are
not part of the pictures.
"""
from __future__ import annotations

import struct
from pathlib import Path

import picture_emu
import vf1_game_art as ga
from unicorn.x86_const import UC_X86_REG_ESP

VILLAGER0 = picture_emu.VILLAGER0
ACHIEVEMENTS = 0x5008D8          # the achievements object the Awards screen passes (0x4353E5)


def _f(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


class MeterEmu(picture_emu.Emu):
    def __init__(self, game: Path) -> None:
        self.files = ga.GameFiles(Path(game))
        super().__init__(game)
        u = self.u
        u.mem_map(0, 0x1000)                       # fs:[0] (the SEH frames) with fs base 0
        self.fills: list[dict] = []
        self.events: list[tuple] = []              # blits and fills in order
        self.manager = self.alloc(0x40)
        self.w32(self.manager + 4, self.window)
        self.state = self.alloc(0x1B400)
        self.empty = self.alloc(16)
        self.fonts = self.alloc(16)
        self.w32(self.fonts, self.alloc(0x100))
        hooks = {
            0x44F7C0: self._ret_value(self.manager, 0),
            0x44F3E0: self._get_grid, 0x44F650: self._get_grid, 0x44F320: self._get_grid,
            0x404BC0: self._plain_blit,
            0x403B40: self._fill,
            0x423660: self._ret_value(self.state, 0),
            0x48AFE0: self._ret_value(1, 4),
            0x489900: self._ret_value(VILLAGER0, 4),
            0x486B60: self._ret_value(0, 8),
            0x409D20: self._ret_value(0, 0x14), 0x409CC0: self._ret_value(0, 0x14),
            0x409CD0: self._ret_value(0, 0x14),
            0x44FD90: self._ret_value(self.empty, 4),
            0x450530: self._ret_value(self.fonts, 0),
            0x4173A0: self._ret_value(0, 0),
            0x4226A0: self._ret_value(0, 0), 0x4985BB: self._ret_value(0, 0),
            0x425200: self._ret_value(0, 8),
        }
        for address, hook in hooks.items():
            if address not in self._code_hooks and address != 0x403650:
                u.hook_add(picture_emu.UC_HOOK_CODE, self._code, begin=address, end=address)
            self._code_hooks[address] = hook
        # the painter, built by the game's own constructor 0x44EE20
        self.painter = self.alloc(0x28)
        self.call(0x44EE20, ecx=self.painter)
        self._code_hooks[0x44F1F0] = self._ret_value(self.painter, 0)
        u.hook_add(picture_emu.UC_HOOK_CODE, self._code, begin=0x44F1F0, end=0x44F1F0)

    # -------------------------------------------------------------- pictures
    def grid(self, image: int) -> int:
        if image in picture_emu.IMAGES:
            return super().grid(image)
        if image in self.grids:
            return self.grids[image]
        name, cols, rows, files = ga.TABLE[image]
        assert files == 1
        impl = self.alloc(16)
        self.w32(impl, self._file_surface(name))
        w, h = self.files.size(name)
        g = self.alloc(0x40)
        self.w32(g + 4, impl)
        self.w32(g + 8, cols)
        self.w32(g + 0xC, rows)
        self.w32(g + 0x10, w // cols if cols else w)
        self.w32(g + 0x14, h // rows if rows else h)
        self.grids[image] = g
        return g

    def _file_surface(self, name: str) -> int:
        if name not in self.surface_of:
            w, h = self.files.size(name)
            self.surface_of[name] = self._surface(name, w, h, pixels=False)
        return self.surface_of[name]

    def surface_ids(self) -> dict[str, int]:
        """picture name -> the grid object the painter holds (for the field tests)."""
        return {n: s for n, s in self.surface_of.items()}

    # -------------------------------------------------------------- recorders
    def _blit(self, _self) -> None:
        before = len(self.blits)
        super()._blit(_self)
        if len(self.blits) > before:
            self.events.append(("blit", self.blits[-1]))

    def _plain_blit(self, _self) -> None:
        """0x404BC0(surface, x, y, left, top, right, bottom): SDL_UpperBlit of the rect, as it is."""
        esp = self.u.reg_read(UC_X86_REG_ESP)
        surf, x, y, x0, y0, x1, y1 = struct.unpack("<Iiiiiii", self.u.mem_read(esp + 4, 28))
        b = {"file": self.surfaces.get(surf, "?"), "rect": (x0, y0, x1, y1), "x": x, "y": y,
             "alpha": 1.0, "scale": 1.0, "centre": 0}
        self.blits.append(b)
        self.events.append(("blit", b))
        self._ret_value(0, 0x1C)(self)

    def _fill(self, _self) -> None:
        """0x403B40(rect*, r, g, b, a): the rect (left, top, right, bottom) as the caller hands it (every fill
        recorded here lies inside the screen, so 0x403B40's own clamp to the clip leaves it as it is)."""
        esp = self.u.reg_read(UC_X86_REG_ESP)
        rect_at, r, g, b, a = struct.unpack("<Iffff", self.u.mem_read(esp + 4, 20))
        rect = struct.unpack("<iiii", self.u.mem_read(rect_at, 16))
        f = {"rect": rect, "rgba": (r, g, b, a)}
        self.fills.append(f)
        self.events.append(("fill", f))
        self._ret_value(0, 0x14)(self)

    def _start(self) -> None:
        self.blits = []
        self.fills = []
        self.events = []

    # -------------------------------------------------------------- scenes
    def painter_field(self, offset: int) -> str:
        """The picture the painter holds at +offset (its constructor put it there)."""
        g = self.r32(self.painter + offset)
        impl = self.r32(g + 4)
        return self.surfaces[self.r32(impl)]

    def bar(self, kind: int, value: int) -> list[tuple]:
        """The painter's 0x44EEA0(kind, value) alone."""
        self._start()
        self.call(0x44EEA0, (kind, value), ecx=self.painter)
        return list(self.events)

    def details(self, *, health: int, energy: int, happiness: int, hunger: int, career: int, level: int,
                progress: int) -> list[tuple]:
        """The Details screen 0x44B890 for family member 0 with these numbers."""
        v = VILLAGER0
        self.u.mem_write(v, bytes(0x145FC))
        self.w32(v + 0x2AE0, health)
        self.w32(v + 0x2B08, energy)
        self.w32(v + 0x2B0C, happiness)
        self.w32(v + 0x2B14, hunger)
        self.w32(v + 0x2B6C, career)
        self.w32(v + 0x2B70, level)
        self.w32(v + 0x2B74, progress)
        self._start()
        self.call(0x44B890, ecx=self.alloc(0x400))
        return list(self.events)

    def loading(self, counter: int) -> list[tuple]:
        """The loading screen 0x4406D0 with its counter (+0x24) at `counter`."""
        scene = self.alloc(0x40)
        self.w32(scene + 0x24, counter)
        self._start()
        self.call(0x4406D0, ecx=scene)
        return list(self.events)

    def achievement(self, index: int, count: int, *, done: bool = False, x: int = 0, y: int = 0) -> list[tuple]:
        """One achievement row 0x412D00(x, y, index, popup=0, alpha 1.0) as the Awards screen draws it."""
        rec = ACHIEVEMENTS + index * 12
        self.u.mem_write(rec, bytes([1 if done else 0]))
        self.w32(rec + 4, count)
        self._start()
        self.call(0x412D00, (x, y, index, 0, _f(1.0)), ecx=ACHIEVEMENTS)
        return list(self.events)

    def bank_chart(self, values: list[float], *, x: int = 400, y: int = 200) -> list[tuple]:
        """CBankingDlg's chart 0x415300 with the seven projected balances (+0x54..+0x6C), centred on x (+0x70)
        with its top at y (+0x74)."""
        dlg = self.alloc(0x200)
        for k, value in enumerate(values):
            self.wf(dlg + 0x54 + 4 * k, value)
        self.w32(dlg + 0x70, x)
        self.w32(dlg + 0x74, y)
        self._start()
        self.call(0x415300, ecx=dlg)
        return list(self.events)
