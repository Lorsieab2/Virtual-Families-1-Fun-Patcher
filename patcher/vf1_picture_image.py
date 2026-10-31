"""The Picture Maker's shared pieces: an RGBA image, a PNG reader and writer, the export sizes, and the
game's own sprite blitter for scaled and see-through draws.  Pure Python (zlib and struct only): the
patcher ships no Pillow.  Ported from the Fish and Plant Tycoon patcher's Picture Studio
(src/picture_image.py), with Virtual Families 1's blitter in place of Fish Tycoon's.

Virtual Families 1 draws every sprite cell with ldwGameWindowImpl::BlitRectWithAlpha (0x404C30,
reached from 0x408DF0 and 0x408C70) with a surface alpha (a float) and a scale (a float made from a
whole percent, 0x44ED70 / 0x408DF0):

* scale 1 and alpha 1: SDL's own alpha blit of the cell (0x404CFB -> SDL_UpperBlit): the cell's pixels
  as they are;
* scale below 1 (a child): every screen pixel is the plain average of a box of cell pixels (the sums of
  each byte divided by the count, 0x405100..0x405145 and 0x40516F..), the box edges stepping by
  w / trunc(w x scale) from half a step before the cell (0x404F9B..0x405095);
* alpha below 1 (a ghost): each pixel's alpha a becomes (a x A + 127) >> 8 with A = trunc(alpha x 255 +
  0.5) (0x405705..0x4057D9, and 0x40627A for a scaled one).

`game_layer` makes the pixels the game blends for one draw; the tests run 0x404C30 itself in Unicorn
over black and white and compare (tests/test_picture_maker.py).
"""

from __future__ import annotations

import base64
import math
import os
import re
import struct
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MARGIN = 4
SIZES = (("1x", 1), ("2x", 2), ("4x", 4))
MAX_SIDE = 8192                 # the largest picture the Picture Maker writes (a custom size is capped)


class PictureError(Exception):
    """A picture that cannot be drawn or read, in words for the player."""


# ------------------------------------------------------------------ the image


class Image:
    """Straight (not premultiplied) 8-bit RGBA, rows top to bottom."""

    __slots__ = ("data", "height", "width")

    def __init__(self, width: int, height: int, data: bytearray | None = None) -> None:
        if width < 0 or height < 0:
            raise ValueError("an image cannot have a negative size")
        self.width, self.height = int(width), int(height)
        self.data = bytearray(self.width * self.height * 4) if data is None else bytearray(data)
        if len(self.data) != self.width * self.height * 4:
            raise ValueError("the pixel data does not fit the size")

    @classmethod
    def new(cls, width: int, height: int) -> Image:
        return cls(width, height)

    @classmethod
    def from_png(cls, data: bytes) -> Image:
        return decode_png(data)

    def to_png(self) -> bytes:
        return encode_png(self)

    def copy(self) -> Image:
        return Image(self.width, self.height, self.data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Image) and (self.width, self.height) == (other.width, other.height) \
            and self.data == other.data

    def __repr__(self) -> str:
        return f"Image({self.width}x{self.height})"

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        at = (y * self.width + x) * 4
        return tuple(self.data[at:at + 4])

    def sub(self, x: int, y: int, w: int, h: int) -> Image:
        """The w x h piece at (x, y); any part outside the image is transparent."""
        out = Image(w, h)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return out
        row = (x1 - x0) * 4
        for yy in range(y0, y1):
            src = (yy * self.width + x0) * 4
            dst = ((yy - y) * w + (x0 - x)) * 4
            out.data[dst:dst + row] = self.data[src:src + row]
        return out

    def draw(self, src: Image, x: int, y: int) -> None:
        """src over this image at (x, y), clipped: the standard straight-alpha "over", in the integer
        form Pillow's alpha_composite uses (a picture has no screen behind it, so where two see-through
        edges meet the PNG keeps both, as any paint program would)."""
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + src.width), min(self.height, y + src.height)
        if x1 <= x0 or y1 <= y0:
            return
        sd, dd = src.data, self.data
        for yy in range(y0, y1):
            s = ((yy - y) * src.width + (x0 - x)) * 4
            d = (yy * self.width + x0) * 4
            for _ in range(x1 - x0):
                sa = sd[s + 3]
                if sa == 255:
                    dd[d:d + 4] = sd[s:s + 4]
                elif sa:
                    da = dd[d + 3]
                    if da == 0:
                        dd[d:d + 4] = sd[s:s + 4]
                    else:
                        blend = da * (255 - sa)
                        outa255 = sa * 255 + blend
                        coef1 = sa * 255 * 255 * 128 // outa255
                        coef2 = 255 * 128 - coef1
                        for k in range(3):
                            t = sd[s + k] * coef1 + dd[d + k] * coef2 + (0x80 << 7)
                            dd[d + k] = (((t >> 8) + t) >> 8) >> 7
                        t = outa255 + 0x80
                        dd[d + 3] = ((t >> 8) + t) >> 8
                s += 4
                d += 4

    def bbox(self) -> tuple[int, int, int, int] | None:
        """(left, top, right, bottom), right and bottom exclusive, of the pixels with any alpha."""
        w, h = self.width, self.height
        alphas = self.data[3::4]
        top = bottom = None
        left, right = w, 0
        for y in range(h):
            row = alphas[y * w:(y + 1) * w]
            if any(row):
                if top is None:
                    top = y
                bottom = y + 1
                first = next(i for i, a in enumerate(row) if a)
                last = w - next(i for i, a in enumerate(reversed(row)) if a)
                left, right = min(left, first), max(right, last)
        if top is None:
            return None
        return left, top, right, bottom

    def cropped(self, margin: int = MARGIN) -> Image:
        """Cut to the drawn pixels plus `margin` transparent pixels each side; an image with nothing
        drawn is 1 x 1 transparent (plus the margin)."""
        box = self.bbox()
        if box is None:
            return Image(1 + 2 * margin, 1 + 2 * margin)
        left, top, right, bottom = box
        return self.sub(left - margin, top - margin, right - left + 2 * margin, bottom - top + 2 * margin)

    def scaled(self, factor: int) -> Image:
        """Nearest neighbour, crisp: every pixel becomes factor x factor."""
        factor = int(factor)
        if factor < 1:
            raise ValueError("the scale must be 1 or more")
        if factor == 1:
            return self.copy()
        out = Image(self.width * factor, self.height * factor)
        stride = self.width * 4
        out_stride = stride * factor
        for y in range(self.height):
            row = self.data[y * stride:(y + 1) * stride]
            wide = b"".join(bytes(row[i:i + 4]) * factor for i in range(0, stride, 4))
            for k in range(factor):
                at = (y * factor + k) * out_stride
                out.data[at:at + out_stride] = wide
        return out

    def resized(self, width: int, height: int) -> Image:
        """Smooth scaling to width x height: a linear (triangle) filter, widened when shrinking so every
        source pixel counts, on premultiplied colour so transparent edges stay clean."""
        width, height = int(width), int(height)
        if width < 1 or height < 1:
            raise ValueError("a picture must be at least 1 x 1")
        if (width, height) == (self.width, self.height):
            return self.copy()
        n = self.width * self.height
        src = self.data
        pre = [0.0] * (n * 4)
        for i in range(n):
            a = src[i * 4 + 3]
            if a:
                f = a / 255.0
                pre[i * 4] = src[i * 4] * f
                pre[i * 4 + 1] = src[i * 4 + 1] * f
                pre[i * 4 + 2] = src[i * 4 + 2] * f
                pre[i * 4 + 3] = float(a)
        horizontal = _resample_weights(self.width, width)
        vertical = _resample_weights(self.height, height)
        mid = [0.0] * (width * self.height * 4)
        for y in range(self.height):
            base = y * self.width * 4
            out = y * width * 4
            for x, (first, weights) in enumerate(horizontal):
                r = g = b = a = 0.0
                at = base + first * 4
                for wgt in weights:
                    r += pre[at] * wgt
                    g += pre[at + 1] * wgt
                    b += pre[at + 2] * wgt
                    a += pre[at + 3] * wgt
                    at += 4
                o = out + x * 4
                mid[o], mid[o + 1], mid[o + 2], mid[o + 3] = r, g, b, a
        result = Image(width, height)
        dd = result.data
        row4 = width * 4
        for y, (first, weights) in enumerate(vertical):
            for x in range(width):
                r = g = b = a = 0.0
                at = first * row4 + x * 4
                for wgt in weights:
                    r += mid[at] * wgt
                    g += mid[at + 1] * wgt
                    b += mid[at + 2] * wgt
                    a += mid[at + 3] * wgt
                    at += row4
                o = (y * width + x) * 4
                alpha = int(a + 0.5)
                if alpha <= 0:
                    continue
                dd[o] = max(0, min(255, int(r / a * 255.0 + 0.5)))
                dd[o + 1] = max(0, min(255, int(g / a * 255.0 + 0.5)))
                dd[o + 2] = max(0, min(255, int(b / a * 255.0 + 0.5)))
                dd[o + 3] = min(255, alpha)
        return result

    def on_checks(self, light=(255, 255, 255), dark=(204, 204, 204), square: int = 8) -> Image:
        """This picture over a grey-and-white checkerboard (how paint programs show see-through)."""
        out = Image(self.width, self.height)
        for y in range(self.height):
            for x in range(self.width):
                colour = light if ((x // square) + (y // square)) % 2 == 0 else dark
                at = (y * self.width + x) * 4
                out.data[at:at + 4] = bytes((*colour, 255))
        out.draw(self, 0, 0)
        return out

    def photo(self, tk_mod, master, max_side: int | None = None):
        """A Tk PhotoImage of this image, shrunk by whole steps to fit `max_side`."""
        image = self
        if max_side:
            biggest = max(1, image.width, image.height)
            if biggest > max_side:
                factor = -(-biggest // max_side)
                image = image.resized(max(1, image.width // factor), max(1, image.height // factor))
        return tk_mod.PhotoImage(master=master, data=base64.b64encode(image.to_png()))


def _resample_weights(src: int, dst: int) -> list[tuple[int, list[float]]]:
    scale = dst / src
    support = max(1.0, 1.0 / scale)
    out = []
    for i in range(dst):
        centre = (i + 0.5) / scale
        lo = max(0, int(centre - support))
        hi = min(src, int(centre + support) + 1)
        weights = []
        for j in range(lo, hi):
            wgt = 1.0 - abs((j + 0.5 - centre) / support)
            weights.append(max(0.0, wgt))
        total = sum(weights)
        if total <= 0:
            out.append((min(src - 1, max(0, int(centre))), [1.0]))
            continue
        while weights and weights[0] == 0.0:
            weights.pop(0)
            lo += 1
        while weights and weights[-1] == 0.0:
            weights.pop()
        out.append((lo, [w / total for w in weights]))
    return out


# ------------------------------------------------------------------ PNG


def _chunks(data: bytes):
    if not data.startswith(PNG_MAGIC):
        raise PictureError("not a PNG file")
    at = 8
    while at + 8 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, at)
        body = data[at + 8:at + 8 + length]
        if len(body) != length:
            raise PictureError("the PNG file is cut short")
        yield kind, body
        at += 12 + length
        if kind == b"IEND":
            return


def _unfilter(raw: bytes, height: int, bpp: int, row_bytes: int) -> bytearray:
    """Undo the PNG row filters (None, Sub, Up, Average, Paeth)."""
    out = bytearray(height * row_bytes)
    prev = bytearray(row_bytes)
    at = 0
    for y in range(height):
        kind = raw[at]
        line = bytearray(raw[at + 1:at + 1 + row_bytes])
        at += 1 + row_bytes
        if len(line) != row_bytes:
            raise PictureError("the PNG image data is cut short")
        if kind == 0:
            pass
        elif kind == 1:
            for i in range(bpp, row_bytes):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif kind == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif kind == 3:
            for i in range(row_bytes):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(row_bytes):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                line[i] = (line[i] + pred) & 0xFF
        else:
            raise PictureError(f"the PNG uses an unknown row filter ({kind})")
        out[y * row_bytes:(y + 1) * row_bytes] = line
        prev = line
    return out


def decode_png(data: bytes) -> Image:
    """A non-interlaced 8-bit RGBA or RGB PNG (what Virtual Families 1 ships), as straight RGBA.  The
    sample values are taken as they are: the game's loader (SDL_image) applies no gAMA correction."""
    header = None
    idat = []
    for kind, body in _chunks(bytes(data)):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
    if header is None:
        raise PictureError("the PNG has no header")
    width, height, depth, colour, _comp, _filter, interlace = header
    if interlace or depth != 8 or colour not in (2, 6):
        raise PictureError("the PNG's format is not one Virtual Families uses")
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as exc:
        raise PictureError(f"the PNG image data could not be unpacked ({exc})") from None
    channels = 4 if colour == 6 else 3
    rows = _unfilter(raw, height, channels, width * channels)
    image = Image(width, height)
    if colour == 6:
        image.data[:] = rows
    else:
        out = image.data
        out[0::4] = rows[0::3]
        out[1::4] = rows[1::3]
        out[2::4] = rows[2::3]
        out[3::4] = b"\xff" * (width * height)
    return image


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def encode_png(image: Image) -> bytes:
    """An 8-bit RGBA PNG (colour type 6)."""
    stride = image.width * 4
    raw = bytearray()
    prev = bytes(stride)
    for y in range(image.height):
        row = bytes(image.data[y * stride:(y + 1) * stride])
        if row == prev and y:
            raw += b"\x02" + bytes(stride)
        else:
            raw += b"\x00" + row
        prev = row
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return PNG_MAGIC + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) \
        + _chunk(b"IEND", b"")


# ------------------------------------------------------------------ the game's blitter


def f32(value: float) -> float:
    """value rounded to a 32-bit float, as the game keeps its scales (fstp dword)."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def percent_scale(scale: float) -> tuple[int, float]:
    """(percent, the scale the blitter gets) for a draw at `scale` (a 32-bit float): 0x44ED70 /
    0x486C28 truncate 100 x scale to a whole percent, 0x408DF0 / 0x408CC7 turn it back into a 32-bit
    float (percent / 100)."""
    percent = math.trunc(100.0 * scale)
    return percent, f32(percent / 100.0)


def box_scaled(sheet: Image, rect: tuple[int, int, int, int], scale: float) -> Image:
    """BlitRectWithAlpha's shrink (0x404D0D.., scale below 1): trunc(w x scale) by trunc(h x scale)
    pixels, each the byte-by-byte average (whole-number division) of a box of the cell's pixels."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    dw, dh = math.trunc(w * scale), math.trunc(h * scale)
    if dw <= 0 or dh <= 0:
        return Image(0, 0)
    xstep, ystep = w / dw, h / dh

    def boxes(start: int, size: int, step: float, count: int) -> list[tuple[int, int] | None]:
        out: list[tuple[int, int] | None] = []
        cur = start - step * 0.5
        prev_end, last = start - 1, start + size - 1
        for _ in range(count):
            cur += step
            first = prev_end + 1
            end = min(math.trunc(cur) + 1, last)
            prev_end = end
            out.append((first, end) if first <= end else None)
        return out

    columns = boxes(x0, w, xstep, dw)
    out = Image(dw, dh)
    src, dst, sw = sheet.data, out.data, sheet.width
    for j, rows in enumerate(boxes(y0, h, ystep, dh)):
        if rows is None:
            continue
        r0, r1 = rows
        for i, cols in enumerate(columns):
            if cols is None:
                continue
            c0, c1 = cols
            s0 = s1 = s2 = s3 = 0
            for yy in range(r0, r1 + 1):
                at = (yy * sw + c0) * 4
                piece = src[at:at + (c1 - c0 + 1) * 4]
                s0 += sum(piece[0::4])
                s1 += sum(piece[1::4])
                s2 += sum(piece[2::4])
                s3 += sum(piece[3::4])
            n = (r1 - r0 + 1) * (c1 - c0 + 1)
            a = s3 // n
            if a:
                d = (j * dw + i) * 4
                dst[d], dst[d + 1], dst[d + 2], dst[d + 3] = s0 // n, s1 // n, s2 // n, a
    return out


def game_layer(sheet: Image, rect: tuple[int, int, int, int], scale: float, alpha: float = 1.0) -> Image:
    """The pixels the game blends for one draw of `rect` of `sheet` at `scale` (the blitter's 32-bit
    float) and surface alpha `alpha` (a float, 1 = solid)."""
    return game_layer_and_touched(sheet, rect, scale, alpha)[0]


def game_layer_and_touched(sheet: Image, rect: tuple[int, int, int, int], scale: float,
                           alpha: float = 1.0) -> tuple[Image, bytes]:
    """game_layer, and which of its pixels the blitter writes (1) at all: with a surface alpha below 1 it
    writes a pixel whose alpha comes out 0 too (0x4057C0 writes every pixel; 0x406274 skips only a box
    whose average alpha is 0), which on screen still rounds the colour behind it, (d x 255 + 127) >> 8."""
    if alpha <= 0 or scale <= 0:
        return Image(0, 0), b""
    x0, y0, x1, y1 = rect
    if scale == 1.0:
        piece = sheet.sub(x0, y0, x1 - x0, y1 - y0)
        touched = bytes([1]) * (piece.width * piece.height) if alpha != 1.0 else \
            bytes(1 if a else 0 for a in piece.data[3::4])
    elif scale < 1.0:
        piece = box_scaled(sheet, rect, scale)
        touched = bytes(1 if a else 0 for a in piece.data[3::4])
    else:
        raise PictureError("Virtual Families never draws a family member larger than life.")
    if alpha != 1.0:
        weight = math.trunc(alpha * 255.0 + 0.5)
        table = bytes((a * weight + 0x7F) >> 8 for a in range(256))
        piece.data[3::4] = bytes(table[a] for a in piece.data[3::4])
    return piece, touched


# ------------------------------------------------------------------ export


def export(image: Image, *, scale: int = 1, size: tuple[int, int] | None = None, margin: int = MARGIN) -> Image:
    """Crop to the drawn pixels plus `margin` (0: none), then scale: `scale` crisply (nearest
    neighbour) or `size=(w, h)` smoothly; a 0 in size keeps the aspect ratio."""
    out = image.cropped(max(0, int(margin)))
    if size is not None:
        w, h = (int(v or 0) for v in size)
        if w <= 0 and h <= 0:
            raise PictureError("Give a width, a height or both.")
        if w <= 0:
            w = max(1, round(out.width * h / out.height))
        if h <= 0:
            h = max(1, round(out.height * w / out.width))
        if w > MAX_SIDE or h > MAX_SIDE:
            raise PictureError(f"A picture can be at most {MAX_SIDE} pixels wide or high.")
        return out.resized(w, h)
    scale = int(scale)
    if scale < 1 or out.width * scale > MAX_SIDE or out.height * scale > MAX_SIDE:
        raise PictureError(f"A picture can be at most {MAX_SIDE} pixels wide or high.")
    return out.scaled(scale)


def save_png(image: Image, path, **options) -> Path:
    """Export (see `export`) and write the PNG through a temporary file beside it, so a failed write never
    leaves half a file."""
    path = Path(path)
    data = export(image, **options).to_png()
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return path


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_file_name(text: str, limit: int = 80) -> str:
    """A label as a Windows file name (no extension)."""
    name = _BAD.sub("-", str(text)).strip().rstrip(". ")[:limit].rstrip(". ")
    if not name:
        name = "picture"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name


def unique_path(folder: Path, stem: str, suffix: str = ".png") -> Path:
    """folder/stem.png, or "stem (2).png" and so on when that name is taken."""
    path = Path(folder) / f"{stem}{suffix}"
    n = 2
    while path.exists():
        path = Path(folder) / f"{stem} ({n}){suffix}"
        n += 1
    return path


# ------------------------------------------------------------------ what a renderer returns


@dataclass(frozen=True)
class SavedItem:
    id: str
    label: str
    location: str
    kind: str
    detail: str = ""


@dataclass(frozen=True)
class Option:
    key: object
    label: str
    patcher: bool = False


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    options: tuple
    default: object = None


@dataclass(frozen=True)
class Subject:
    key: str
    title: str
    fields: tuple
    note: str = ""


@dataclass(frozen=True)
class Draw:
    """One cell draw as the game makes it: the cell `rect` (left, top, right, bottom) of image `file`,
    its top-left at (x, y), at `scale` (the blitter's 32-bit float) and surface alpha `alpha`.  `what`
    names the layer ("shadow", "body", "head", "outfit") for the window and the tests."""
    what: str
    file: str
    rect: tuple
    x: int
    y: int
    scale: float = 1.0
    alpha: float = 1.0
