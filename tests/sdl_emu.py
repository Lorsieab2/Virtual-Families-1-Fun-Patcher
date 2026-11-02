"""Runs the game's own SDL2.dll (2.0.3, shipped beside Virtual Families.exe) in Unicorn, for the typing tests:
how a key Windows delivers becomes the SDL_TEXTINPUT events ldwGame's event loop reads.

SDL 2.0.3 makes typed text in its window procedure WIN_WindowProc (0x100EBF40): WM_KEYDOWN (0x100EC509) calls
GetKeyboardState and ToUnicode(wParam, scan code, state, &utf32, 1, 0) -- ONE UTF-16 unit -- and for each repeat
writes that unit as UTF-8 by hand (0x100EC5B1..0x100EC6D4) and calls SDL_SendKeyboardText (0x100B0380), which pushes
an SDL_TEXTINPUT event (type 0x303, text at +0x0C). WM_CHAR (0x102) only sets the return code (0x100EC7AF). A
character above U+FFFF that Windows or an input method sends as a VK_PACKET pair (SendInput KEYEVENTF_UNICODE with
the two surrogates) therefore arrives as two events, each one surrogate written as three bytes.

`WindowsKeys.type_units(units)` runs the REAL window procedure for WM_KEYDOWN VK_PACKET with each UTF-16 unit (what
ToUnicode answers for an injected VK_PACKET is the unit itself -- the only stand-in for Windows here), then the REAL
SDL_PeepEvents(SDL_GETEVENT) for every event, and returns the SDL_TEXTINPUT texts in order. SDL's event queue is the
real one, started by the real SDL_InitSubSystem(SDL_INIT_EVENTS). The kernel32 / user32 / winmm calls SDL makes on
the way are stood in for (critical sections, thread-local storage, the clock); anything else stops the test.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pefile
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_MODE_32, Uc, UcError
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP

STUBS = 0x01000000
STOP = 0x01100000
STACK = 0x02000000
STACK_SIZE = 0x00200000
HEAP = 0x30000000
WINDOW_PROC = 0x100EBF40        # WIN_WindowProc (GetPropW(hwnd, L"SDL_WindowData") at 0x100EBFA7)
WINDOW_PROC_STOCK = bytes.fromhex("558bec81ec68020000c745fcffffffff")
SDL_INIT_EVENTS = 0x4000
SDL_GETEVENT = 2
SDL_TEXTINPUT = 0x303
WM_KEYDOWN, WM_CHAR = 0x100, 0x102
VK_PACKET = 0xE7
HWND = 0x1234


class SdlEmuError(Exception):
    pass


class WindowsKeys:
    # stdcall argument bytes of the Windows calls SDL makes on this path (anything else is reported)
    STDCALL = {
        "GetPropW": 8, "CallWindowProcW": 20, "DefWindowProcW": 16, "GetKeyboardState": 4, "ToUnicode": 24,
        "MapVirtualKeyW": 8, "GetKeyState": 4, "GetAsyncKeyState": 4,
        "InitializeCriticalSection": 4, "InitializeCriticalSectionAndSpinCount": 8, "EnterCriticalSection": 4,
        "LeaveCriticalSection": 4, "DeleteCriticalSection": 4, "TryEnterCriticalSection": 4,
        "TlsAlloc": 0, "TlsGetValue": 4, "TlsSetValue": 8, "GetLastError": 0, "SetLastError": 4,
        "timeGetTime": 0, "timeBeginPeriod": 4, "timeEndPeriod": 4, "QueryPerformanceFrequency": 4,
        "QueryPerformanceCounter": 4, "GetTickCount": 0, "GetProcessHeap": 0, "HeapAlloc": 12, "HeapFree": 12,
        "HeapReAlloc": 16, "GetCurrentThreadId": 0, "CreateSemaphoreW": 16, "ReleaseSemaphore": 12,
        "WaitForSingleObject": 8, "CloseHandle": 4, "Sleep": 4, "GetModuleHandleW": 4, "GetProcAddress": 8,
        "LoadLibraryW": 4, "LoadLibraryA": 4, "SetUnhandledExceptionFilter": 4, "InterlockedExchange": 8,
        "InterlockedCompareExchange": 12, "InterlockedIncrement": 4, "InterlockedDecrement": 4,
        "OutputDebugStringA": 4, "OutputDebugStringW": 4, "IsDebuggerPresent": 0,
        "GetEnvironmentVariableA": 12, "GetEnvironmentVariableW": 12, "GetSystemInfo": 4, "VirtualAlloc": 16,
        "VirtualFree": 12,
    }

    def __init__(self, game: Path) -> None:
        path = Path(game) / "SDL2.dll"
        pe = pefile.PE(str(path))
        self.base = pe.OPTIONAL_HEADER.ImageBase
        image = bytearray(pe.get_memory_mapped_image())
        size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        image += bytes(size - len(image))
        if bytes(image[WINDOW_PROC - self.base:WINDOW_PROC - self.base + len(WINDOW_PROC_STOCK)]) \
                != WINDOW_PROC_STOCK:
            raise SdlEmuError("not the game's SDL2.dll 2.0.3")
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u = u
        self.stub_names: dict[int, str] = {}
        n = 0
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            for imp in entry.imports:
                name = (imp.name or b"").decode()
                address = STUBS + n
                n += 1
                struct.pack_into("<I", image, imp.address - self.base, address)
                self.stub_names[address] = name
        u.mem_map(self.base, size)
        u.mem_write(self.base, bytes(image))
        u.mem_map(STUBS, 0x10000)
        u.mem_write(STUBS, b"\xC3" * n)
        u.mem_map(STOP, 0x1000)
        u.mem_map(STACK, STACK_SIZE)
        u.mem_map(HEAP, 0x01000000)
        self.heap_top = HEAP
        self.exports = {e.name.decode(): e.address + self.base for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
        self.tls: dict[int, int] = {}
        self.units: list[int] = []        # what ToUnicode answers next
        self.window_data = self.alloc(0x100)
        self.video_data = self.alloc(0x1000)
        self.w32(self.window_data + 0x2C, self.video_data)   # data->videodata (IME_HandleMessage reads it)
        self.calls: list[str] = []
        self.error: SdlEmuError | None = None
        u.hook_add(UC_HOOK_CODE, self._stub, begin=STUBS, end=STUBS + n)
        u.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        if self.call("SDL_InitSubSystem", SDL_INIT_EVENTS) != 0:
            raise SdlEmuError("SDL_InitSubSystem(SDL_INIT_EVENTS) failed")
        # the event loop starts with text events off; SDL_VideoInit turns them on with SDL_StartTextInput
        self.call("SDL_StartTextInput")

    # ------------------------------------------------------------------ memory
    def alloc(self, size: int) -> int:
        a = self.heap_top
        self.heap_top += (max(size, 1) + 0xF) & ~0xF
        self.u.mem_write(a, bytes(size))
        return a

    def r32(self, a: int) -> int:
        return struct.unpack("<I", self.u.mem_read(a, 4))[0]

    def w32(self, a: int, v: int) -> None:
        self.u.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def arg(self, i: int) -> int:
        return self.r32(self.u.reg_read(UC_X86_REG_ESP) + 4 + 4 * i)

    def _unmapped(self, u, access, address, size, value, user):
        self.error = SdlEmuError(f"unmapped access at {address:#x} (eip {u.reg_read(UC_X86_REG_EIP):#x}; "
                                 f"last Windows calls {self.calls[-8:]})")
        return False

    # ------------------------------------------------------------------ Windows, stood in for
    def _stub(self, u, address, size, user) -> None:
        name = self.stub_names[address]
        self.calls.append(name)
        a = self.arg
        if name not in self.STDCALL:
            self.error = SdlEmuError(f"SDL called the unexpected {name}")
            u.emu_stop()
            return
        result = 0
        if name == "GetPropW":
            result = self.window_data if a(0) == HWND else 0
        elif name == "ToUnicode":
            if not self.units:
                raise SdlEmuError("ToUnicode with no key waiting")
            unit = self.units.pop(0)
            buf, cap = a(3), a(4)
            if cap >= 1:
                u.mem_write(buf, struct.pack("<H", unit))
            result = 1
        elif name == "TlsAlloc":
            result = len(self.tls) + 1
            self.tls[result] = 0
        elif name == "TlsGetValue":
            result = self.tls.get(a(0), 0)
        elif name == "TlsSetValue":
            self.tls[a(0)] = a(1)
            result = 1
        elif name in ("InitializeCriticalSectionAndSpinCount", "TryEnterCriticalSection", "ReleaseSemaphore",
                      "QueryPerformanceFrequency", "QueryPerformanceCounter", "HeapFree", "CloseHandle"):
            if name.startswith("QueryPerformance"):
                self.u.mem_write(a(0), struct.pack("<Q", 1000))
            result = 1
        elif name == "HeapAlloc":
            result = self.alloc(a(2))
        elif name == "HeapReAlloc":
            new = self.alloc(a(3))
            old = a(2)
            if old:
                u.mem_write(new, bytes(u.mem_read(old, a(3))))
            result = new
        elif name == "GetProcessHeap":
            result = 0x7700
        elif name == "CreateSemaphoreW":
            result = 0x5E0
        elif name in ("InterlockedExchange", "InterlockedCompareExchange"):
            old = self.r32(a(0))
            if name == "InterlockedExchange" or old == a(2):
                self.w32(a(0), a(1))
            result = old
        elif name in ("InterlockedIncrement", "InterlockedDecrement"):
            v = (self.r32(a(0)) + (1 if name == "InterlockedIncrement" else -1)) & 0xFFFFFFFF
            self.w32(a(0), v)
            result = v
        elif name == "GetCurrentThreadId":
            result = 1
        elif name == "GetModuleHandleW":
            result = 0
        elif name == "GetSystemInfo":                      # SDL's malloc (dlmalloc) asks the page size
            info = bytearray(36)
            struct.pack_into("<I", info, 4, 0x1000)       # dwPageSize
            struct.pack_into("<I", info, 0x1C, 0x10000)   # dwAllocationGranularity
            u.mem_write(a(0), bytes(info))
        elif name == "VirtualAlloc":
            size = (a(1) + 0xFFFF) & ~0xFFFF
            self.heap_top = (self.heap_top + 0xFFFF) & ~0xFFFF
            result = self.alloc(size)
        elif name in ("VirtualFree",):
            result = 1
        esp = u.reg_read(UC_X86_REG_ESP)
        ret = self.r32(esp)
        u.reg_write(UC_X86_REG_ESP, esp + 4 + self.STDCALL[name])
        u.reg_write(UC_X86_REG_EAX, result & 0xFFFFFFFF)
        u.reg_write(UC_X86_REG_EIP, ret)

    # ------------------------------------------------------------------ calls
    def call_at(self, address: int, *args: int) -> int:
        esp = STACK + STACK_SIZE - 0x1000
        esp -= 4 * len(args)
        for i, value in enumerate(args):
            self.w32(esp + 4 * i, value)
        esp -= 4
        self.w32(esp, STOP)
        self.u.reg_write(UC_X86_REG_ESP, esp)
        self.error = None
        try:
            self.u.emu_start(address, STOP, count=5_000_000)
        except UcError as exc:
            raise self.error or SdlEmuError(f"{exc} at {self.u.reg_read(UC_X86_REG_EIP):#x}") from None
        if self.error is not None:
            raise self.error
        if self.u.reg_read(UC_X86_REG_EIP) != STOP:
            raise SdlEmuError(f"stopped at {self.u.reg_read(UC_X86_REG_EIP):#x}")
        return self.u.reg_read(UC_X86_REG_EAX)

    def call(self, name: str, *args: int) -> int:
        return self.call_at(self.exports[name], *args)

    def window_proc(self, msg: int, wparam: int, lparam: int) -> int:
        return self.call_at(WINDOW_PROC, HWND, msg, wparam, lparam)

    def events(self) -> list[tuple[int, bytes]]:
        """Every queued event, through the real SDL_PeepEvents(GETEVENT): (type, text for SDL_TEXTINPUT)."""
        out = []
        ev = self.alloc(56)
        while self.call("SDL_PeepEvents", ev, 1, SDL_GETEVENT, 0, 0xFFFF) == 1:
            kind = self.r32(ev)
            text = bytes(self.u.mem_read(ev + 12, 32)).split(b"\0", 1)[0] if kind == SDL_TEXTINPUT else b""
            out.append((kind, text))
        return out

    def type_units(self, units: list[int], also_wm_char: bool = True) -> list[bytes]:
        """Each UTF-16 unit as Windows delivers an injected VK_PACKET: WM_KEYDOWN (ToUnicode gives the unit), then
        the WM_CHAR TranslateMessage makes; returns the SDL_TEXTINPUT texts the game will read, in order."""
        texts = []
        for unit in units:
            self.units.append(unit)
            self.window_proc(WM_KEYDOWN, VK_PACKET, 1)            # repeat count 1, scan code 0
            if also_wm_char:
                self.window_proc(WM_CHAR, unit, 1)
            texts += [t for kind, t in self.events() if kind == SDL_TEXTINPUT]
        return texts
