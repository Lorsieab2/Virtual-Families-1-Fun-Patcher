#!/usr/bin/env python3
"""Assemble the executable's loader stub into patcher/stub.json.

Run after changing the stub. The patcher itself only reads stub.json, so
applying a patch needs nothing beyond the Python standard library.

The stub has two entry points and one shared loader:

* init_entry -- theGame's vtable slot for Init (0x4B5E14) points here. It runs
  the loader, calls VF1Fun_Startup() if the DLL loaded, then jumps to the real
  theGame::Init (0x422AE0) with every register as it found them.
* tick_entry -- theGame's vtable slot for GameUpdate (0x4B5E20), which
  ldwGame::Run calls once per frame. It calls VF1Fun_Tick() if the DLL
  exports it, then jumps to the real theGame::GameUpdate (0x422D90).
* store_entry -- the call at the end of theStoreScene's constructor
  (0x4497E6) points here. It makes the original call (0x448BE0), runs the
  loader, then calls VF1Fun_StoreCreated(store scene).

The loader runs once. It builds "<exe folder>\\Virtual Families 1 Patcher
Files\\vf1fun.dll" with GetModuleFileNameW and loads it with LoadLibraryW, both
resolved through the GetModuleHandleA/GetProcAddress imports the game already
has. On any failure it records the failure and the game runs stock.

usage: build_stub.py
"""
import json
from pathlib import Path

from keystone import KS_ARCH_X86, KS_MODE_32, Ks

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "patcher" / "stub.json"

CODE_VA = 0x8AF000   # first free section after .rsrc in the vanilla image
DATA_VA = 0x8B0000
PATH_CHARS = 1024
IAT_GET_MODULE_HANDLE_A = 0x4B21D4
IAT_GET_PROC_ADDRESS = 0x4B21D8
THEGAME_INIT = 0x422AE0
THEGAME_GAMEUPDATE = 0x422D90
STORE_ORIGINAL_CALL = 0x448BE0
SUFFIX = "Virtual Families 1 Patcher Files\\vf1fun.dll"

STATE, FN_STARTUP, FN_STORE, FN_TICK, PATH = DATA_VA, DATA_VA + 4, DATA_VA + 8, DATA_VA + 12, DATA_VA + 16
STRINGS = CODE_VA + 0x300


def build():
    strings = [("kernel32", b"kernel32.dll\0"), ("gmfnw", b"GetModuleFileNameW\0"),
               ("llw", b"LoadLibraryW\0"), ("startup", b"VF1Fun_Startup\0"),
               ("store", b"VF1Fun_StoreCreated\0"), ("tick", b"VF1Fun_Tick\0"), ("suffix", SUFFIX.encode("utf-16-le") + b"\0\0")]
    addr, blob = {}, b""
    for key, raw in strings:
        addr[key] = STRINGS + len(blob)
        blob += raw
    asm = f"""
    init_entry:
        pushad
        call loader
        mov eax, dword ptr [{FN_STARTUP:#x}]
        test eax, eax
        jz init_done
        call eax
    init_done:
        popad
        jmp {THEGAME_INIT:#x}

    store_entry:
        push ecx
        call {STORE_ORIGINAL_CALL:#x}
        pop ecx
        pushad
        mov ebx, ecx
        call loader
        mov eax, dword ptr [{FN_STORE:#x}]
        test eax, eax
        jz store_done
        push ebx
        call eax
        add esp, 4
    store_done:
        popad
        ret

    tick_entry:
        pushad
        mov eax, dword ptr [{FN_TICK:#x}]
        test eax, eax
        jz tick_done
        call eax
    tick_done:
        popad
        jmp {THEGAME_GAMEUPDATE:#x}

    loader:
        cmp dword ptr [{STATE:#x}], 0
        jne loader_done
        mov dword ptr [{STATE:#x}], 2
        push {addr['kernel32']:#x}
        call dword ptr [{IAT_GET_MODULE_HANDLE_A:#x}]
        test eax, eax
        jz loader_done
        mov esi, eax
        push {addr['gmfnw']:#x}
        push esi
        call dword ptr [{IAT_GET_PROC_ADDRESS:#x}]
        test eax, eax
        jz loader_done
        push {PATH_CHARS - 64}
        push {PATH:#x}
        push 0
        call eax
        test eax, eax
        jz loader_done
        cmp eax, {PATH_CHARS - 64}
        jae loader_done
        lea ecx, [{PATH:#x} + eax*2]
    back:
        sub ecx, 2
        cmp ecx, {PATH:#x}
        jb loader_done
        cmp word ptr [ecx], 0x5c
        jne back
        add ecx, 2
        mov edx, {addr['suffix']:#x}
    copy:
        mov ax, word ptr [edx]
        mov word ptr [ecx], ax
        add edx, 2
        add ecx, 2
        test ax, ax
        jnz copy
        push {addr['llw']:#x}
        push esi
        call dword ptr [{IAT_GET_PROC_ADDRESS:#x}]
        test eax, eax
        jz loader_done
        push {PATH:#x}
        call eax
        test eax, eax
        jz loader_done
        mov edi, eax
        push {addr['startup']:#x}
        push edi
        call dword ptr [{IAT_GET_PROC_ADDRESS:#x}]
        mov dword ptr [{FN_STARTUP:#x}], eax
        push {addr['store']:#x}
        push edi
        call dword ptr [{IAT_GET_PROC_ADDRESS:#x}]
        mov dword ptr [{FN_STORE:#x}], eax
        push {addr['tick']:#x}
        push edi
        call dword ptr [{IAT_GET_PROC_ADDRESS:#x}]
        mov dword ptr [{FN_TICK:#x}], eax
        mov dword ptr [{STATE:#x}], 1
    loader_done:
        ret
    """
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(asm, CODE_VA)
    code = bytes(code)
    if len(code) > STRINGS - CODE_VA:
        raise SystemExit("stub too large")
    # store_entry is the only `push ecx; call rel32` in the stub.
    store_off = code.find(bytes.fromhex("51 e8"))
    if store_off < 0 or code.find(bytes.fromhex("51 e8"), store_off + 1) >= 0:
        raise SystemExit("cannot locate store_entry uniquely")
    # tick_entry is `pushad; mov eax, [FN_TICK]`.
    tick_off = code.find(bytes([0x60, 0xA1]) + FN_TICK.to_bytes(4, "little"))
    if tick_off < 0:
        raise SystemExit("cannot locate tick_entry")
    payload = code + b"\xCC" * (STRINGS - CODE_VA - len(code)) + blob
    return {
        "code_va": hex(CODE_VA), "data_va": hex(DATA_VA), "data_size": 16 + PATH_CHARS * 2,
        "init_entry": hex(CODE_VA), "store_entry": hex(CODE_VA + store_off),
        "tick_entry": hex(CODE_VA + tick_off),
        "code": payload.hex(),
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1) + "\n")
    print("wrote", OUT)
