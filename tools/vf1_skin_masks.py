#!/usr/bin/env python3
"""Skin Tones for Virtual Families 1: the shape-only mask pictures the patcher ships, and the C header that ties each
one to the game sheet it was made from.

    vf1_skin_masks.py --workbench "<Skin Tones Workbench>\\VF1" --images "<vanilla game>\\Images" [--write]

A mask holds NO game pixel: it is a 1-bit black and white PNG, white where the sheet of people has bare skin and black
everywhere else (the workbench's "layers\\<sheet>\\Skin mask.png", solid where it is skin). The held baby is the only
part of carrying.png that is toned: its mask is cell 3 only, and this tool refuses a workbench mask with skin anywhere
else on that sheet.

The header (native/vf1skin/skin_masks.h) gives vf1skin.dll, for each sheet: the game's image id and which of its files
(heads and big heads are grids of two files), the sheet's width and height, and the size and FNV-1a 64 of the vanilla
sheet file the mask was made from. The DLL uses a mask only when the player's sheet file is that very file (same size,
same FNV-1a 64) and the mask picture is that sheet's size; otherwise people are drawn with the game's own skin on that
sheet. SkinMasks/masks.json records the same with each file's SHA-256, for the Transparency Log and the tests.

Without --write it only checks that the committed files are what a fresh run would write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "patcher" / "payload" / "SkinMasks"
HEADER = ROOT / "native" / "vf1skin" / "skin_masks.h"
GAME_TITLE = "VF1"

# (sheet file, the game's image id (theGraphicsManager's table 0x4F2D00), which file of a grid of two, rows)
SHEETS = (
    ("female_heads00.png", 0x9C, 0, 50), ("female_heads10.png", 0x9C, 1, 50),
    ("female_bodies00.png", 0x9D, 0, 50), ("female_actions00.png", 0x9E, 0, 50), ("female_sit00.png", 0x9F, 0, 50),
    ("male_heads00.png", 0xA0, 0, 50), ("male_heads10.png", 0xA0, 1, 50),
    ("male_bodies00.png", 0xA1, 0, 50), ("male_actions00.png", 0xA2, 0, 50), ("male_sit00.png", 0xA3, 0, 50),
    ("bigheads00.png", 0x04, 0, 50), ("bigheads10.png", 0x04, 1, 50),
    ("highrez_bodies_final2.png", 0x05, 0, 50),
    ("carrying.png", 0x68, 0, 6),
)
CARRYING = "carrying.png"
CARRYING_COLUMNS = 13
BABY_CELL = 3                 # carried-items draw 0x48A100: cell 3 is the held baby (pushes 3 at 0x48A159)


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SystemExit("not a PNG")
    return struct.unpack(">II", data[16:24])


def mask_png(rows: list[bytes], width: int) -> bytes:
    """A 1-bit greyscale PNG (white = skin), no interlace, filter 0 on every row."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    ihdr = struct.pack(">IIBBBBB", width, len(rows), 1, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def read_mask_bits(data: bytes) -> tuple[int, int, list[bytes]]:
    """(width, height, packed rows) of a mask this tool wrote (for the tests and the check)."""
    w, h = png_size(data)
    if data[24:29] != bytes([1, 0, 0, 0, 0]):
        raise SystemExit("not a 1-bit greyscale non-interlaced PNG")
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = (w + 7) // 8
    rows = []
    prev = bytes(stride)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f != 0:
            raise SystemExit("this tool writes filter 0 only")
        rows.append(bytes(line))
        prev = line
    del prev
    return w, h, rows


def build(workbench: Path, images: Path) -> dict[str, bytes]:
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    files: dict[str, bytes] = {}
    table = []
    for name, image, part, rows in SHEETS:
        sheet_bytes = (images / name).read_bytes()
        sw, sh = png_size(sheet_bytes)
        mask = np.array(Image.open(workbench / "layers" / name[:-4] / "Skin mask.png").convert("RGBA"))
        if mask.shape[:2] != (sh, sw):
            raise SystemExit(f"{name}: the workbench mask is {mask.shape[1]} x {mask.shape[0]}, the sheet {sw} x {sh}")
        skin = mask[..., 3] >= 128
        if name == CARRYING:
            cell = sw // CARRYING_COLUMNS
            keep = np.zeros_like(skin)
            keep[0:sh // rows, BABY_CELL * cell:(BABY_CELL + 1) * cell] = True
            if (skin & ~keep).any():
                raise SystemExit("carrying.png: the workbench mask has skin outside the held baby (cell 3)")
        packed = np.packbits(skin, axis=1)              # MSB first, as PNG keeps 1-bit pixels
        png = mask_png([bytes(r) for r in packed], sw)
        files[name] = png
        table.append({"sheet": name, "image": image, "part": part, "width": sw, "height": sh, "rows": rows,
                      "sheet_size": len(sheet_bytes), "sheet_fnv1a64": f"{fnv1a64(sheet_bytes):016x}",
                      "sheet_sha256": hashlib.sha256(sheet_bytes).hexdigest(),
                      "mask_sha256": hashlib.sha256(png).hexdigest(), "skin_pixels": int(skin.sum())})
    files["masks.json"] = (json.dumps({"game": GAME_TITLE, "masks": table}, indent=1) + "\n").encode()
    files["skin_masks.h"] = render_header(table).encode()
    return files


def render_header(table) -> str:
    out = ["// GENERATED by tools/vf1_skin_masks.py from the Skin Tones workbench's masks and the vanilla Images. Do not",
           "// edit. Each sheet of people the DLL may tone: the game's image id, which file of a grid of two, the",
           "// sheet's size and rows, and the size and FNV-1a 64 of the vanilla file its mask was made from.",
           "#pragma once", "",
           "struct SkinSheetInfo { unsigned image, part; const wchar_t *file; int width, height, rows;",
           "                       unsigned fileSize; unsigned long long fileHash; };",
           f"enum {{ SKIN_SHEET_COUNT = {len(table)}, SKIN_BABY_CELL = {BABY_CELL}, SKIN_CARRYING_COLUMNS = "
           f"{CARRYING_COLUMNS} }};",
           "static const SkinSheetInfo SkinSheetInfos[SKIN_SHEET_COUNT] = {"]
    for t in table:
        out.append(f'    {{ 0x{t["image"]:X}u, {t["part"]}u, L"{t["sheet"]}", {t["width"]}, {t["height"]}, {t["rows"]}, '
                   f'{t["sheet_size"]}u, 0x{t["sheet_fnv1a64"].upper()}ull }},')
    out.append("};")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbench", required=True, type=Path)
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    files = build(args.workbench, args.images)
    targets = {name: (HEADER if name == "skin_masks.h" else OUT / name) for name in files}
    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            targets[name].write_bytes(data)
        print(f"wrote {len(files)} files")
        return 0
    stale = [str(p) for name, p in targets.items() if not p.is_file() or p.read_bytes() != files[name]]
    if stale:
        print("differs from a fresh run: " + ", ".join(stale))
        return 1
    print("the committed masks are a fresh run's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
