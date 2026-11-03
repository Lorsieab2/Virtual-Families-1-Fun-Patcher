#!/usr/bin/env python3
"""Find every place the vanilla Virtual Families 1 copies one of its own strings into a fixed space, and write the
room each translated line has: data/vf1_translation_limits.json (and native/vf1tr/vf1tr_limits.h, the same table
for vf1tr.dll).

    python tools/build_vf1_translation_limits.py --exe "<vanilla folder>/Virtual Families.exe" [--check]

The game reads a line through theStringManager::GetString 0x44FD90 (thiscall, the string id pushed) or fills a
template through GetStringFromNameGenderTemplate 0x44FDD0 (which takes its buffer's size and never writes past it).
For every `call 0x44FD90` in .text this finds:

* which ids it can be: the id pushed as an immediate, or every id in the table it is read from
  (`mov reg, [index*4 + table]`, the email and diagnosis pieces chosen at random);
* what the next instructions do with the text (until the function returns, at most WINDOW instructions):
  strncpy 0x4993C0 with a constant count n (the line gets n - 1 bytes, so the copy always ends with its NUL, as the
  English does), sprintf 0x4985BB, strncat 0x498660 or an inline byte-copy loop (the line may not be longer than
  the English: then every buffer holds at most what it holds in the English game).

A copy whose id cannot be told (the id comes from data: an item, an event, a caller's table) is listed in
"unresolved" with the copying call; vf1tr.dll redirects each of those calls through a guard that hands the copy a
translated line cut to its English length (at a whole letter), so the copy never holds more than in the English
game. Every other call is left as it is.
Only the decimal point is never translated (numbers are written with it). The Family History log's record words
("Male", "Female", "New Generation"...) are translated on screen and written in English by vf1logs.dll; the likes and
dislikes lists keep every item, each no longer than its English (vf1tr.dll checks it).
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "data" / "vf1_translation_limits.json"
OUT_H = ROOT / "native" / "vf1tr" / "vf1tr_limits.h"

GET_STRING = 0x44FD90
SPRINTF, STRNCPY, STRNCAT = 0x4985BB, 0x4993C0, 0x498660
TABLE = 0x4F5618                 # the first of the static records {id, key*, text*, override*}
MAX_ID = 0x675                   # GetString's own bound (id - 1 <= 0x674)
WINDOW = 40
# The lines the game parses: never translated. The Family History log's record words ("Male", "Female", the causes
# of death...) are translated on screen; vf1logs.dll writes the log in English (VF1Tr_English). The likes and
# dislikes lists are translated item by item: vf1tr.dll keeps every item, each no longer than its English.
NEVER = {
    0x002: "the decimal point (eString_Decimal): numbers are written with it",
}


def _image(exe: bytes):
    import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    return pe, pe.get_memory_mapped_image(), pe.OPTIONAL_HEADER.ImageBase


def scan(exe: bytes) -> dict:
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    pe, img, base = _image(exe)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
    t0, tn = text.VirtualAddress, text.Misc_VirtualSize
    code = img[t0:t0 + tn]
    sites = []
    for m in re.finditer(rb"\xE8", code):
        if m.start() + 5 > len(code):
            continue
        at = base + t0 + m.start()
        if (at + 5 + struct.unpack_from("<i", code, m.start() + 1)[0]) & 0xFFFFFFFF == GET_STRING:
            sites.append(at)
    limit: dict[int, int] = {}
    english_only: set[int] = set()
    unresolved: list[str] = []
    copies = 0

    def ids_at(at: int) -> list[int] | None:
        before = []
        for back in range(40, 0, -1):          # the longest decoding that ends exactly at the call
            decoded = list(md.disasm(img[at - base - back:at - base], at - back))
            if decoded and decoded[-1].address + decoded[-1].size == at \
                    and sum(i.size for i in decoded) == back:
                before = decoded
                break
        if not before:
            return None
        pushes = [i for i in before if i.mnemonic == "push"]
        if not pushes:
            return None
        last = pushes[-1]
        if last.op_str.startswith("0x") or last.op_str.isdigit():
            return [int(last.op_str, 0)]
        reg = last.op_str
        earlier = before[:before.index(last)]
        # `sete al; neg al; sbb eax, eax; add eax, N`: N or N - 1
        if len(earlier) >= 2 and earlier[-1].mnemonic == "add" and earlier[-1].op_str.startswith(reg + ", 0x") \
                and earlier[-2].mnemonic == "sbb" and earlier[-2].op_str == f"{reg}, {reg}":
            n = int(earlier[-1].op_str.split(", ")[1], 16)
            return [n - 1, n]
        # `setcc cl; add ecx, N; mov eax, ecx`: N or N + 1
        walk = [i for i in earlier if not (i.mnemonic in ("cmp", "test", "push") or i.mnemonic.startswith("j"))]
        src = reg
        if walk and walk[-1].mnemonic == "mov" and re.fullmatch(reg + r", (e[a-d]x)", walk[-1].op_str):
            src = walk[-1].op_str.split(", ")[1]
            walk = walk[:-1]
        if len(walk) >= 2 and walk[-1].mnemonic == "add" and walk[-1].op_str.startswith(src + ", 0x") \
                and walk[-2].mnemonic.startswith("set"):
            n = int(walk[-1].op_str.split(", ")[1], 16)
            return [n, n + 1]
        for i in reversed(earlier):
            if i.mnemonic == "mov" and re.fullmatch(reg + r", (0x[0-9a-f]+|\d+)", i.op_str):
                return [int(i.op_str.split(", ")[1], 0)]
            mm = re.fullmatch(reg + r", dword ptr \[(\w+)\*4 \+ (0x[0-9a-f]+)\]", i.op_str) if i.mnemonic == "mov" else None
            if mm:
                table = int(mm.group(2), 16)
                found = []
                for k in range(64):
                    v = struct.unpack_from("<I", img, table - base + 4 * k)[0]
                    if not 1 <= v <= MAX_ID:
                        break
                    found.append(v)
                return found or None
            if i.op_str.startswith(reg + ","):
                return None
        return None

    for at in sites:
        after = list(md.disasm(img[at - base:at - base + 6 * WINDOW], at))[1:WINDOW]
        kind, count, copy_at = None, None, None
        pushed: list = []
        for k, i in enumerate(after):
            if i.mnemonic in ("ret", "int3"):
                break
            if i.mnemonic == "push":
                pushed.append(i.op_str)
            if i.mnemonic == "call":
                target = int(i.op_str, 16) if i.op_str.startswith("0x") else None
                copy_at = (i.address, target)
                if target == STRNCPY:
                    imm = next((p for p in reversed(pushed[:-2]) if p.startswith("0x") or p.isdigit()), None)
                    if len(pushed) >= 3 and (pushed[-3].startswith("0x") or pushed[-3].isdigit()):
                        kind, count = "strncpy", int(pushed[-3], 0)
                    elif imm is not None:
                        kind, count = "strncpy", int(imm, 0)
                    else:
                        kind = "english"
                    break
                if target in (SPRINTF, STRNCAT):
                    kind = "english"
                    break
                if target == GET_STRING or k > 12:
                    pushed = []
                    continue
                pushed = []
            if i.mnemonic == "mov" and re.match(r"byte ptr \[.*\], [a-d]l$", i.op_str) and k \
                    and after[k - 1].mnemonic == "mov" and re.match(r"[a-d]l, byte ptr \[", after[k - 1].op_str):
                kind = "english"
                break
        if kind is None:
            continue
        copies += 1
        ids = ids_at(at)
        if ids is None:
            unresolved.append({"at": f"0x{at:X}", "kind": kind, "count": count,
                               "call": f"0x{copy_at[0]:X}" if copy_at else None,
                               "target": f"0x{copy_at[1]:X}" if copy_at and copy_at[1] else None})
            continue
        for sid in ids:
            if kind == "strncpy":
                limit[sid] = min(limit.get(sid, 1 << 30), count - 1)
            else:
                english_only.add(sid)
    return {
        "comment": "Written by tools/build_vf1_translation_limits.py from the vanilla executable; do not edit.",
        "table": f"0x{TABLE:X}",
        "get_string_calls": len(sites),
        "copies": copies,
        "strncpy_room": {str(k): v for k, v in sorted(limit.items())},
        "english_length": sorted(english_only),
        "never": {str(k): v for k, v in sorted(NEVER.items())},
        "unresolved": unresolved,
    }


def header(data: dict) -> str:
    rows = [f"    {{ {int(k)}, {v} }}," for k, v in data["strncpy_room"].items()]
    english = ", ".join(str(v) for v in data["english_length"])
    never = ", ".join(data["never"].keys())
    kinds = {"0x4993C0": 0, "0x4985BB": 1, "0x498660": 2}
    guards = [f"    {{ {u['call']}u, {u['target']}u, {kinds[u['target']]} }}," for u in data["unresolved"]]
    return "\n".join([
        "/* Written by tools/build_vf1_translation_limits.py from the vanilla executable; do not edit. */",
        "#pragma once",
        "/* The copies whose line cannot be told from the code: vf1tr.dll guards each call (kind 0 strncpy,",
        "   1 sprintf, 2 strncat) so that a translated line there is never longer than its English. */",
        "typedef struct { unsigned int call; unsigned int target; int kind; } vf1tr_guard;",
        f"#define VF1TR_GUARD_COUNT {len(guards)}",
        "static const vf1tr_guard VF1TR_GUARDS[] = {\n" + "\n".join(guards) + "\n};",
        "typedef struct { unsigned short id; unsigned short room; } vf1tr_room;",
        f"static const vf1tr_room VF1TR_STRNCPY_ROOM[] = {{\n" + "\n".join(rows) + "\n    { 0, 0 }\n};",
        f"static const unsigned short VF1TR_ENGLISH_LENGTH[] = {{ {english}, 0 }};",
        f"static const unsigned short VF1TR_NEVER[] = {{ {never}, 0 }};",
        "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True, type=Path)
    ap.add_argument("--check", action="store_true", help="only compare with the committed files")
    args = ap.parse_args()
    data = scan(args.exe.read_bytes())
    text = json.dumps(data, indent=1) + "\n"
    if args.check:
        same = OUT_JSON.read_text(encoding="utf-8") == text and OUT_H.read_text(encoding="utf-8") == header(data)
        print("up to date" if same else "OUT OF DATE")
        return 0 if same else 1
    OUT_JSON.write_text(text, encoding="utf-8", newline="\n")
    OUT_H.write_text(header(data), encoding="utf-8", newline="\n")
    print(f"{data['get_string_calls']} GetString calls, {data['copies']} copies, {len(data['strncpy_room'])} strncpy "
          f"lines, {len(data['english_length'])} English-length lines, {len(data['unresolved'])} unresolved: "
          f"{data['unresolved'][:20]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
