"""The two odd picture files in a Virtual Families 1 folder, read in pure Python for the Picture Maker:

* icon.bmp (the window's icon: 0x408639 loads it with SDL_LoadBMP_RW and hands it to SDL_SetWindowIcon, no
  colour key): an uncompressed BMP, 1/4/8-bit with a palette or 24/32-bit, drawn opaque;
* Images\\DRM\\logo1.gif (the copy-protection web page's logo; the game never loads it): a GIF's first frame,
  its transparent colour see-through.

Both formats are lossless, so the pixels are the file's own (tests/test_game_art.py compares them with Pillow).
"""
from __future__ import annotations

import struct

import vf1_picture_image as pi


def decode_bmp(data: bytes) -> pi.Image:
    try:
        if data[:2] != b"BM":
            raise ValueError
        offset = struct.unpack_from("<I", data, 10)[0]
        header = struct.unpack_from("<I", data, 14)[0]
        width, height, _planes, bits, compression = struct.unpack_from("<iiHHI", data, 18)
        if compression not in (0, 3) or bits not in (1, 4, 8, 24, 32) or width <= 0 or height == 0:
            raise ValueError
        colours = struct.unpack_from("<I", data, 46)[0] if header >= 40 else 0
        palette = []
        if bits <= 8:
            count = colours or (1 << bits)
            base = 14 + header
            for k in range(count):
                b, g, r = data[base + 4 * k:base + 4 * k + 3]
                palette.append((r, g, b))
        flip = height > 0
        height = abs(height)
        stride = ((width * bits + 31) // 32) * 4
        image = pi.Image(width, height)
        out = image.data
        for row in range(height):
            src = offset + row * stride
            y = height - 1 - row if flip else row
            line = data[src:src + stride]
            if len(line) < (width * bits + 7) // 8:
                raise ValueError
            for x in range(width):
                if bits == 24:
                    b, g, r = line[3 * x:3 * x + 3]
                elif bits == 32:
                    b, g, r = line[4 * x:4 * x + 3]
                else:
                    bit = x * bits
                    index = (line[bit // 8] >> (8 - bits - bit % 8)) & ((1 << bits) - 1)
                    r, g, b = palette[index]
                at = (y * width + x) * 4
                out[at:at + 4] = bytes((r, g, b, 255))
        return image
    except (ValueError, struct.error, IndexError):
        raise pi.PictureError("The BMP picture could not be read.") from None


def _lzw(data: bytes, min_size: int, count: int) -> bytearray:
    clear, end = 1 << min_size, (1 << min_size) + 1
    size = min_size + 1
    table = [bytes((k,)) for k in range(clear)] + [b"", b""]
    out = bytearray()
    prev = None
    bitpos, total = 0, len(data) * 8
    while bitpos + size <= total and len(out) < count:
        at = bitpos >> 3
        chunk = int.from_bytes(data[at:at + 4], "little")
        code = (chunk >> (bitpos & 7)) & ((1 << size) - 1)
        bitpos += size
        if code == clear:
            table = table[:end + 1]
            size = min_size + 1
            prev = None
            continue
        if code == end:
            break
        if prev is None:
            entry = table[code]
        elif code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        elif code == len(table):
            entry = prev + prev[:1]
            table.append(entry)
        else:
            raise ValueError
        out += entry
        prev = entry
        if len(table) == (1 << size) and size < 12:
            size += 1
    return out


def decode_gif(data: bytes) -> pi.Image:
    try:
        if data[:6] not in (b"GIF87a", b"GIF89a"):
            raise ValueError
        width, height, flags = struct.unpack_from("<HHB", data, 6)
        at = 13
        palette = []
        if flags & 0x80:
            n = 2 << (flags & 7)
            palette = [tuple(data[at + 3 * k:at + 3 * k + 3]) for k in range(n)]
            at += 3 * n
        transparent = None
        while True:
            kind = data[at]
            if kind == 0x21:
                label = data[at + 1]
                at += 2
                if label == 0xF9 and data[at] >= 4 and data[at + 1] & 1:
                    transparent = data[at + 4]
                while data[at]:
                    at += data[at] + 1
                at += 1
            elif kind == 0x2C:
                left, top, w, h, f = struct.unpack_from("<HHHHB", data, at + 1)
                at += 10
                colours = palette
                if f & 0x80:
                    n = 2 << (f & 7)
                    colours = [tuple(data[at + 3 * k:at + 3 * k + 3]) for k in range(n)]
                    at += 3 * n
                min_size = data[at]
                at += 1
                blocks = bytearray()
                while data[at]:
                    blocks += data[at + 1:at + 1 + data[at]]
                    at += data[at] + 1
                pixels = _lzw(bytes(blocks), min_size, w * h)
                rows = list(range(h))
                if f & 0x40:                          # interlaced: rows in four passes
                    rows = [*range(0, h, 8), *range(4, h, 8), *range(2, h, 4), *range(1, h, 2)]
                image = pi.Image(width, height)
                for k, index in enumerate(pixels[:w * h]):
                    y = rows[k // w] + top
                    x = k % w + left
                    if index == transparent or not (0 <= x < width and 0 <= y < height):
                        continue
                    r, g, b = colours[index]
                    o = (y * width + x) * 4
                    image.data[o:o + 4] = bytes((r, g, b, 255))
                return image
            else:
                raise ValueError
    except (ValueError, struct.error, IndexError):
        raise pi.PictureError("The GIF picture could not be read.") from None
