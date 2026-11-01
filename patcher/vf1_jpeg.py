"""Virtual Families 1's .jpg pictures, decoded exactly as the game decodes them, in pure Python.

The game loads pictures through SDL2_image.dll, whose IMG_LoadJPG_RW (0x10003510) runs the game folder's
libjpeg-9.dll ("9  13-Jan-2013") with libjpeg's defaults except out_color_space = JCS_RGB (0x1000367D)
and quantize_colors = FALSE (0x10003640): dct_method JDCT_ISLOW, do_fancy_upsampling TRUE, scale 1/1,
no FAST_JPEG settings.  The surface is 24-bit R, G, B (masks 0xFF / 0xFF00 / 0xFF0000, 0x1000368D).
libjpeg 9 differs from jpeg-6b and libjpeg-turbo (and so from Pillow) in how it brings subsampled
colour up to full size, so this module copies libjpeg 9's own path:

* entropy decoding: Huffman, baseline / extended sequential and progressive (jdhuff.c), restart
  markers, and libjpeg's behaviour on running out of data (the rest of that restart interval is
  left zero, i.e. grey);
* "smart" upsampling by DCT scaling (jdmaster.c jpeg_core_output_dimensions with
  do_fancy_upsampling): a component sampled at half the rate is run through a 16-point IDCT
  (jpeg_idct_16x16 for 4:2:0, jpeg_idct_16x8 for 4:2:2, jpeg_idct_8x16 for 4:4:0), so it comes out
  at full size; whatever ratio is left is plain replication (jdsample.c int_upsample: libjpeg 9 has
  no triangle-filter "fancy" upsampler);
* the slow-but-accurate integer IDCT (jidctint.c, CONST_BITS 13, PASS1_BITS 2) and its range limit
  (the result is taken modulo 1024 around the centre, then clamped to 0..255);
* YCbCr to RGB with jdcolor.c's tables (1.402, 1.772, -0.71414, -0.34414 in 16-bit fixed point,
  0x69A0FD86..0x69A0FE05 in the DLL).

tests/test_jpeg_decoder.py checks every picture of the game against the game's own libjpeg-9.dll run
in Unicorn (tests/jpeg_emu.py), byte for byte.
"""

from __future__ import annotations

import sys
from array import array

from vf1_picture_image import Image, PictureError

# ------------------------------------------------------------------ tables

# zigzag position -> natural (row-major) position; libjpeg's jpeg_natural_order has 16 extra entries
# that all point at 63, so a corrupt run past the end lands on the last coefficient.
NATURAL = (
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
) + (63,) * 16

# post-IDCT range limit (jdmaster.c prepare_range_limit_table seen from IDCT_range_limit): the IDCT's
# result is masked to 10 bits; 0..383 is "centre + x" clamped high, 640..1023 is negative, clamped low.
RANGE = bytes(min(255, x + 128) if x < 512 else max(0, x - 1024 + 128) for x in range(1024))


def _fix(x: float) -> int:          # jidctint.c FIX(x), CONST_BITS 13
    return int(x * 8192 + 0.5)


# 8-point (jpeg_idct_islow)
F0298, F0390, F0541, F0765 = 2446, 3196, 4433, 6270
F0899, F1175, F1501, F1847 = 7373, 9633, 12299, 15137
F1961, F2053, F2562, F3072 = 16069, 16819, 20995, 25172
# 16-point (jpeg_idct_16x16 / 16x8 / 8x16)
G1306, G0275, G1387 = _fix(1.306562965), _fix(0.275899379), _fix(1.387039845)
G0601, G0509 = _fix(0.601344887), _fix(0.509795579)
G1353, G1247, G1093, G0897 = _fix(1.353318001), _fix(1.247225013), _fix(1.093201867), _fix(0.897167586)
G0666, G0410, G2286, G1835 = _fix(0.666655658), _fix(0.410524528), _fix(2.286341144), _fix(1.835730603)
G0138, G0071, G1125, G1407 = _fix(0.138617169), _fix(0.071888074), _fix(1.125726048), _fix(1.407403738)
G0766, G1971, G1065, G3141 = _fix(0.766367282), _fix(1.971951411), _fix(1.065388962), _fix(3.141271809)

# YCbCr -> RGB (jdcolor.c build_ycc_rgb_table, SCALEBITS 16)
_CR_R = [(91881 * (i - 128) + 32768) >> 16 for i in range(256)]
_CB_B = [(116130 * (i - 128) + 32768) >> 16 for i in range(256)]
_CR_G = [-46802 * (i - 128) for i in range(256)]
_CB_G = [-22554 * (i - 128) + 32768 for i in range(256)]

_LITTLE = sys.byteorder == "little"
_tables: dict[str, object] = {}


def _colour_tables():
    """Lookups indexed by two samples packed in 16 bits: (Cr, Y) -> R, (Cb, Y) -> B, (Cb, Cr) -> the
    green offset (+256, for _CLAMP)."""
    if not _tables:
        clamp = bytes(min(255, max(0, v)) for v in range(-256, 512))
        r = bytearray(65536)
        b = bytearray(65536)
        for c in range(256):
            row = c << 8
            r[row:row + 256] = clamp[256 + _CR_R[c]:256 + _CR_R[c] + 256]
            b[row:row + 256] = clamp[256 + _CB_B[c]:256 + _CB_B[c] + 256]
        g = array("i", [0]) * 65536
        for cb in range(256):
            base = _CB_G[cb]
            row = cb << 8
            for cr in range(256):
                g[row + cr] = ((base + _CR_G[cr]) >> 16) + 256
        _tables["r"], _tables["b"], _tables["g"] = bytes(r), bytes(b), g
        _tables["clamp"] = clamp
    return _tables["r"], _tables["g"], _tables["b"], _tables["clamp"]


def _pairs(high: bytes, low: bytes) -> memoryview:
    """Packs two equal-length byte strings into 16-bit values (high << 8) | low."""
    n = len(low)
    both = bytearray(2 * n)
    if _LITTLE:
        both[0::2], both[1::2] = low, high
    else:
        both[0::2], both[1::2] = high, low
    return memoryview(both).cast("H")


# ------------------------------------------------------------------ IDCT kernels
#
# Each takes 64 dequantised coefficients (natural order) and returns the output samples as bytes,
# rows top to bottom.  Pass 1 works on columns into a work array scaled by 2**PASS1_BITS; pass 2 on
# rows.  The all-zero shortcuts in libjpeg give exactly what the full arithmetic gives, so they are
# used freely here.

def _cols8(c):
    """jpeg_idct_islow pass 1: 8 columns -> 8 x 8 work values (row-major)."""
    ws = [0] * 64
    for i in range(8):
        d1, d2, d3, d4, d5, d6, d7 = c[8 + i], c[16 + i], c[24 + i], c[32 + i], c[40 + i], c[48 + i], c[56 + i]
        if not (d1 or d2 or d3 or d4 or d5 or d6 or d7):
            v = c[i] << 2
            ws[i] = ws[8 + i] = ws[16 + i] = ws[24 + i] = ws[32 + i] = ws[40 + i] = ws[48 + i] = ws[56 + i] = v
            continue
        z2 = (c[i] << 13) + 1024
        z3 = d4 << 13
        t0 = z2 + z3
        t1 = z2 - z3
        z1 = (d2 + d6) * F0541
        t2 = z1 + d2 * F0765
        t3 = z1 - d6 * F1847
        t10 = t0 + t2
        t13 = t0 - t2
        t11 = t1 + t3
        t12 = t1 - t3
        # odd part: tmp0..3 = d7, d5, d3, d1
        z2 = d7 + d3
        z3 = d5 + d1
        z1 = (z2 + z3) * F1175
        z2 = z1 - z2 * F1961
        z3 = z1 - z3 * F0390
        z1 = -(d7 + d1) * F0899
        o0 = d7 * F0298 + z1 + z2
        o3 = d1 * F1501 + z1 + z3
        z1 = -(d5 + d3) * F2562
        o1 = d5 * F2053 + z1 + z3
        o2 = d3 * F3072 + z1 + z2
        ws[i] = (t10 + o3) >> 11
        ws[56 + i] = (t10 - o3) >> 11
        ws[8 + i] = (t11 + o2) >> 11
        ws[48 + i] = (t11 - o2) >> 11
        ws[16 + i] = (t12 + o1) >> 11
        ws[40 + i] = (t12 - o1) >> 11
        ws[24 + i] = (t13 + o0) >> 11
        ws[32 + i] = (t13 - o0) >> 11
    return ws


def _cols16(c):
    """The 16-point pass 1 of jpeg_idct_16x16 / 8x16: 8 columns of 8 inputs -> 16 x 8 work values."""
    ws = [0] * 128
    for i in range(8):
        d1, d2, d3, d4, d5, d6, d7 = c[8 + i], c[16 + i], c[24 + i], c[32 + i], c[40 + i], c[48 + i], c[56 + i]
        if not (d1 or d2 or d3 or d4 or d5 or d6 or d7):
            v = c[i] << 2
            for r in range(i, 128, 8):
                ws[r] = v
            continue
        e = _even16((c[i] << 13) + 1024, d2, d4, d6)
        o = _odd16(d1, d3, d5, d7)
        for k in range(8):
            ws[8 * k + i] = (e[k] + o[k]) >> 11
            ws[8 * (15 - k) + i] = (e[k] - o[k]) >> 11
    return ws


def _even16(t0, d2, d4, d6):
    """16-point even part; t0 is the DC term already shifted with its rounding added."""
    t1 = d4 * G1306
    t2 = d4 * F0541
    t10 = t0 + t1
    t11 = t0 - t1
    t12 = t0 + t2
    t13 = t0 - t2
    z3 = d2 - d6
    z4 = z3 * G0275
    z3 = z3 * G1387
    a0 = z3 + d6 * F2562
    a1 = z4 + d2 * F0899
    a2 = z3 - d2 * G0601
    a3 = z4 - d6 * G0509
    return (t10 + a0, t12 + a1, t13 + a2, t11 + a3, t11 - a3, t13 - a2, t12 - a1, t10 - a0)


def _odd16(z1, z2, z3, z4):
    """16-point odd part (inputs 1, 3, 5, 7); returns the eight odd terms in output order 0..7."""
    t11 = z1 + z3
    t1 = (z1 + z2) * G1353
    t2 = t11 * G1247
    t3 = (z1 + z4) * G1093
    t10 = (z1 - z4) * G0897
    t11 = t11 * G0666
    t12 = (z1 - z2) * G0410
    t0 = t1 + t2 + t3 - z1 * G2286
    t13 = t10 + t11 + t12 - z1 * G1835
    z1 = (z2 + z3) * G0138
    t1 += z1 + z2 * G0071
    t2 += z1 - z3 * G1125
    z1 = (z3 - z2) * G1407
    t11 += z1 - z3 * G0766
    t12 += z1 + z2 * G1971
    z2 += z4
    z1 = -z2 * G0666
    t1 += z1
    t3 += z1 + z4 * G1065
    z2 = -z2 * G1247
    t10 += z2 + z4 * G3141
    t12 += z2
    z2 = -(z3 + z4) * G1353
    t2 += z2
    t3 += z2
    z2 = (z4 - z3) * G0410
    t10 += z2
    t11 += z2
    return (t0, t1, t2, t3, t10, t11, t12, t13)


def _rows8(ws, nrows):
    """jpeg_idct_islow pass 2 on nrows rows of 8 work values -> nrows x 8 samples."""
    out = bytearray(8 * nrows)
    rl = RANGE
    for r in range(0, 8 * nrows, 8):
        w0, w1, w2, w3, w4, w5, w6, w7 = ws[r:r + 8]
        if not (w1 or w2 or w3 or w4 or w5 or w6 or w7):
            v = rl[((w0 + 16) >> 5) & 1023]
            out[r:r + 8] = bytes((v,)) * 8
            continue
        z2 = w0 + 16
        t0 = (z2 + w4) << 13
        t1 = (z2 - w4) << 13
        z1 = (w2 + w6) * F0541
        t2 = z1 + w2 * F0765
        t3 = z1 - w6 * F1847
        t10 = t0 + t2
        t13 = t0 - t2
        t11 = t1 + t3
        t12 = t1 - t3
        z2 = w7 + w3
        z3 = w5 + w1
        z1 = (z2 + z3) * F1175
        z2 = z1 - z2 * F1961
        z3 = z1 - z3 * F0390
        z1 = -(w7 + w1) * F0899
        o0 = w7 * F0298 + z1 + z2
        o3 = w1 * F1501 + z1 + z3
        z1 = -(w5 + w3) * F2562
        o1 = w5 * F2053 + z1 + z3
        o2 = w3 * F3072 + z1 + z2
        out[r] = rl[((t10 + o3) >> 18) & 1023]
        out[r + 7] = rl[((t10 - o3) >> 18) & 1023]
        out[r + 1] = rl[((t11 + o2) >> 18) & 1023]
        out[r + 6] = rl[((t11 - o2) >> 18) & 1023]
        out[r + 2] = rl[((t12 + o1) >> 18) & 1023]
        out[r + 5] = rl[((t12 - o1) >> 18) & 1023]
        out[r + 3] = rl[((t13 + o0) >> 18) & 1023]
        out[r + 4] = rl[((t13 - o0) >> 18) & 1023]
    return out


def _rows16(ws, nrows):
    """The 16-point pass 2 of jpeg_idct_16x16 / 16x8 on nrows rows of 8 work values -> nrows x 16."""
    out = bytearray(16 * nrows)
    rl = RANGE
    for r in range(nrows):
        w0, w1, w2, w3, w4, w5, w6, w7 = ws[8 * r:8 * r + 8]
        o = 16 * r
        if not (w1 or w2 or w3 or w4 or w5 or w6 or w7):
            out[o:o + 16] = bytes((rl[((w0 + 16) >> 5) & 1023],)) * 16
            continue
        e = _even16((w0 + 16) << 13, w2, w4, w6)
        d = _odd16(w1, w3, w5, w7)
        for k in range(8):
            out[o + k] = rl[((e[k] + d[k]) >> 18) & 1023]
            out[o + 15 - k] = rl[((e[k] - d[k]) >> 18) & 1023]
    return out


def idct(block, cols: int, rows: int) -> bytearray:
    """libjpeg 9's islow-family IDCT of one block of 64 dequantised coefficients (natural order) to a
    cols x rows block of samples: 8x8 jpeg_idct_islow, 16x16, 16x8 (16 wide) or 8x16."""
    if cols == 8:
        return _rows8(_cols8(block) if rows == 8 else _cols16(block), rows)
    return _rows16(_cols8(block) if rows == 8 else _cols16(block), rows)


# ------------------------------------------------------------------ markers and Huffman tables


class _Component:
    __slots__ = (
        "ac_tbl",
        "bh",
        "bw",
        "coef_bits",
        "coefs",
        "dc_tbl",
        "dcols",
        "drows",
        "h",
        "hib",
        "id",
        "plane",
        "pred",
        "qt",
        "stride",
        "tq",
        "v",
        "wib",
    )


def _huffman_lookup(counts: bytes, symbols: bytes, is_dc: bool) -> list[int]:
    """A 16-bit lookup: peeked bits -> (code length << 8) | symbol.  Codes that are not in the table
    read 17 bits and give 0, as jdhuff.c jpeg_huff_decode does."""
    if is_dc and any(s > 15 for s in symbols):
        raise PictureError("The JPEG file's Huffman table is damaged.")
    table = [(17 << 8)] * 65536
    lengths = [n for n in range(1, 17) if counts[n - 1]]
    code = 0
    k = 0
    for length in range(lengths[0] if lengths else 17, (lengths[-1] if lengths else 0) + 1):
        for _ in range(counts[length - 1]):
            span = 1 << (16 - length)
            start = code << (16 - length)
            table[start:start + span] = [(length << 8) | symbols[k]] * span
            code += 1
            k += 1
        # jpeg_make_d_derived_tbl: no code may be all ones
        if code >= (1 << length):
            raise PictureError("The JPEG file's Huffman table is damaged.")
        code <<= 1
    return table


def _segments(data: bytes, pos: int) -> tuple[list[bytes], int]:
    """The entropy-coded data from pos up to the next marker that is not a restart marker, split at
    the restart markers and with the stuffed zero bytes removed.  Returns (pieces, end)."""
    pieces = []
    start = pos
    n = len(data)
    find = data.find
    while True:
        i = find(b"\xFF", pos)
        if i < 0 or i + 1 >= n:
            pieces.append(data[start:])
            return [p.replace(b"\xFF\x00", b"\xFF") for p in pieces], n
        m = data[i + 1]
        if m == 0x00:
            pos = i + 2
            continue
        if m == 0xFF:            # fill bytes before a marker
            j = i
            while j + 1 < n and data[j + 1] == 0xFF:
                j += 1
            if j + 1 < n and 0xD0 <= data[j + 1] <= 0xD7:
                pieces.append(data[start:i])
                start = pos = j + 2
                continue
            if j + 1 < n and data[j + 1] == 0x00:
                pos = j + 2
                continue
            pieces.append(data[start:i])
            return [p.replace(b"\xFF\x00", b"\xFF") for p in pieces], j
        if 0xD0 <= m <= 0xD7:
            pieces.append(data[start:i])
            start = pos = i + 2
            continue
        pieces.append(data[start:i])
        return [p.replace(b"\xFF\x00", b"\xFF") for p in pieces], i


# ------------------------------------------------------------------ the decoder


class _Decoder:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.qtables: dict[int, list[int]] = {}
        self.dc_tables: dict[int, tuple[bytes, bytes]] = {}
        self.ac_tables: dict[int, tuple[bytes, bytes]] = {}
        self.restart = 0
        self.jfif = False
        self.adobe = None
        self.frame = None
        self.progressive = False
        self.comps: list[_Component] = []
        self.scans = 0
        self.direct = False

    # -------------------------------------------------------------- markers
    def run(self) -> Image:
        data = self.data
        if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
            raise PictureError("This is not a JPEG picture.")
        pos = 2
        n = len(data)
        while True:
            # find the next marker (libjpeg skips any garbage before it, with a warning)
            while pos < n and data[pos] != 0xFF:
                pos += 1
            while pos < n and data[pos] == 0xFF:
                pos += 1
            if pos >= n:
                if self.scans:
                    break                    # the source manager supplies the missing end marker
                raise PictureError("The JPEG file ends before its picture.")
            marker = data[pos]
            pos += 1
            if marker == 0xD9:
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7:
                continue
            if marker == 0xD8:
                raise PictureError("The JPEG file is damaged (it starts twice).")
            if pos + 2 > n:
                raise PictureError("The JPEG file is cut short.")
            length = (data[pos] << 8) | data[pos + 1]
            if length < 2 or pos + length > n:
                raise PictureError("The JPEG file is cut short.")
            body = data[pos + 2:pos + length]
            after = pos + length
            if marker in (0xC0, 0xC1, 0xC2):
                self._frame(body, marker == 0xC2)
            elif marker in (0xC9, 0xCA, 0xCC):
                raise PictureError("This JPEG picture uses arithmetic coding, which this reader "
                                   "does not support.")
            elif marker in (0xC3, 0xC5, 0xC6, 0xC7, 0xCB, 0xCD, 0xCE, 0xCF):
                raise PictureError("This JPEG picture uses a kind of compression Virtual Families "
                                   "cannot read (lossless or hierarchical).")
            elif marker == 0xC4:
                self._dht(body)
            elif marker == 0xDB:
                self._dqt(body)
            elif marker == 0xDD:
                if len(body) < 2:
                    raise PictureError("The JPEG file is damaged (bad restart interval).")
                self.restart = (body[0] << 8) | body[1]
            elif marker == 0xDA:
                after = self._scan(body, after)
            elif marker == 0xE0:
                if len(body) >= 14 and body[:5] == b"JFIF\x00":
                    self.jfif = True
            elif marker == 0xEE:
                if len(body) >= 12 and body[:5] == b"Adobe":
                    self.adobe = body[11]
            elif marker == 0xF8:
                raise PictureError("This JPEG picture uses a colour transform this reader does not "
                                   "support.")
            elif 0xE1 <= marker <= 0xEF or marker in (0xFE, 0xDC):
                pass                             # other APPn, comments, DNL: skipped
            else:
                raise PictureError(f"The JPEG file is damaged (unknown marker 0x{marker:02X}).")
            pos = after
        if self.frame is None or not self.scans:
            raise PictureError("The JPEG file has no picture in it.")
        return self._output()

    def _dqt(self, body: bytes) -> None:
        i = 0
        while i < len(body):
            pq, tq = body[i] >> 4, body[i] & 15
            i += 1
            if tq > 3 or pq > 1:
                raise PictureError("The JPEG file's quantisation table is damaged.")
            if pq:
                if i + 128 > len(body):
                    raise PictureError("The JPEG file's quantisation table is damaged.")
                zz = [(body[i + 2 * k] << 8) | body[i + 2 * k + 1] for k in range(64)]
                i += 128
            else:
                if i + 64 > len(body):
                    raise PictureError("The JPEG file's quantisation table is damaged.")
                zz = list(body[i:i + 64])
                i += 64
            natural = [0] * 64
            for k in range(64):
                natural[NATURAL[k]] = zz[k]
            self.qtables[tq] = natural

    def _dht(self, body: bytes) -> None:
        i = 0
        while i < len(body):
            if i + 17 > len(body):
                raise PictureError("The JPEG file's Huffman table is damaged.")
            tc, th = body[i] >> 4, body[i] & 15
            counts = body[i + 1:i + 17]
            total = sum(counts)
            if total > 256 or i + 17 + total > len(body) or th > 3 or tc > 1:
                raise PictureError("The JPEG file's Huffman table is damaged.")
            symbols = body[i + 17:i + 17 + total]
            i += 17 + total
            (self.ac_tables if tc else self.dc_tables)[th] = (counts, symbols)

    def _frame(self, body: bytes, progressive: bool) -> None:
        if self.frame is not None:
            raise PictureError("The JPEG file is damaged (two picture headers).")
        if len(body) < 6:
            raise PictureError("The JPEG file's picture header is damaged.")
        precision = body[0]
        height = (body[1] << 8) | body[2]
        width = (body[3] << 8) | body[4]
        count = body[5]
        if precision != 8:
            raise PictureError(f"This JPEG picture has {precision}-bit samples; Virtual Families reads "
                               "only 8-bit ones.")
        if height == 0:
            raise PictureError("This JPEG picture gives its height at the end (DNL), which Virtual "
                               "Families cannot read.")
        if width == 0 or count == 0 or width > 65500 or height > 65500:
            raise PictureError("The JPEG file's picture header is damaged.")
        if count > 10 or len(body) < 6 + 3 * count:
            raise PictureError("The JPEG file's picture header is damaged.")
        comps = []
        for k in range(count):
            c = _Component()
            c.id, hv, c.tq = body[6 + 3 * k], body[7 + 3 * k], body[8 + 3 * k]
            c.h, c.v = hv >> 4, hv & 15
            if not (1 <= c.h <= 4 and 1 <= c.v <= 4) or c.tq > 3:
                raise PictureError("The JPEG file's picture header is damaged.")
            c.qt = None
            c.coefs = None
            comps.append(c)
        self.frame = (width, height)
        self.progressive = progressive
        self.comps = comps
        self.max_h = max(c.h for c in comps)
        self.max_v = max(c.v for c in comps)
        self.mcux = -(-width // (8 * self.max_h))
        self.mcuy = -(-height // (8 * self.max_v))
        for c in comps:
            # libjpeg 9 jpeg_core_output_dimensions with do_fancy_upsampling: scale a subsampled
            # component up through the IDCT (8 -> 16) while the ratio allows it
            c.dcols = 16 if (self.max_h % (c.h * 2) == 0) else 8
            c.drows = 16 if (self.max_v % (c.v * 2) == 0) else 8
            c.wib = -(-width * c.h // (8 * self.max_h))        # width_in_blocks
            c.hib = -(-height * c.v // (8 * self.max_v))
            c.bw = self.mcux * c.h                              # blocks stored (whole MCUs)
            c.bh = self.mcuy * c.v
            c.stride = c.bw * c.dcols
            c.plane = None
            c.coef_bits = [-1] * 64
            h_in = c.h * c.dcols // 8
            v_in = c.v * c.drows // 8
            if self.max_h % h_in or self.max_v % v_in:
                raise PictureError("This JPEG picture's colour sampling is one libjpeg cannot "
                                   "read (fractional sampling).")

    # -------------------------------------------------------------- scans
    def _scan(self, body: bytes, pos: int) -> int:
        if self.frame is None:
            raise PictureError("The JPEG file is damaged (a scan before the picture header).")
        if not body or len(body) < 1 + 2 * body[0] + 3:
            raise PictureError("The JPEG file's scan header is damaged.")
        count = body[0]
        if not 1 <= count <= 4:
            raise PictureError("The JPEG file's scan header is damaged.")
        comps = []
        for k in range(count):
            cid, tables = body[1 + 2 * k], body[2 + 2 * k]
            match = [c for c in self.comps if c.id == cid and c not in comps]
            if not match:
                raise PictureError("The JPEG file's scan header is damaged.")
            c = match[0]
            c.dc_tbl, c.ac_tbl = tables >> 4, tables & 15
            comps.append(c)
        i = 1 + 2 * count
        ss, se, ah, al = body[i], body[i + 1], body[i + 2] >> 4, body[i + 2] & 15
        if self.progressive:
            bad = False
            if ss == 0:
                if se != 0:
                    bad = True
            else:
                if se < ss or se > 63 or count != 1:
                    bad = True
            if ah != 0 and al != ah - 1:
                bad = True
            if al > 13:
                bad = True
            if bad:
                raise PictureError("The JPEG file's progressive scan is damaged.")
        else:
            if ss != 0 or se != 63 or ah != 0 or al != 0:
                raise PictureError("This JPEG picture uses a block size other than 8, which this "
                                   "reader does not support.")
        if len(comps) > 1 and sum(c.h * c.v for c in comps) > 10:     # D_MAX_BLOCKS_IN_MCU
            raise PictureError("The JPEG file's sampling factors are too large.")
        for c in comps:
            if c.qt is None:                     # quant tables are latched at a component's first scan
                if c.tq not in self.qtables:
                    raise PictureError("The JPEG file is missing a quantisation table.")
                c.qt = list(self.qtables[c.tq])
        if self.direct:
            # a picture whose first scan had every component is complete; libjpeg stops with
            # "Didn't expect more than one scan" (jdinput.c), and SDL2_image gives up
            raise PictureError("The JPEG file is damaged (a second scan after a complete picture).")
        pieces, end = _segments(self.data, pos)
        self.scans += 1
        direct = (not self.progressive and self.scans == 1 and len(comps) == len(self.comps))
        self.direct = direct
        if not direct:
            for c in self.comps:
                if c.coefs is None:
                    c.coefs = array("h", bytes(2 * 64 * c.bw * c.bh))
        if self.progressive:
            self._progressive_scan(comps, ss, se, ah, al, pieces)
        else:
            self._sequential_scan(comps, pieces, direct)
        return end

    def _table(self, kind: str, index: int) -> list[int]:
        tables = self.dc_tables if kind == "dc" else self.ac_tables
        if index not in tables:
            raise PictureError("The JPEG file is missing a Huffman table.")
        counts, symbols = tables[index]
        return _huffman_lookup(counts, symbols, kind == "dc")

    def _units(self, comps):
        """The order of blocks in a scan: a list per MCU of (component, block x, block y)."""
        if len(comps) == 1:
            c = comps[0]
            return [[(c, bx, by)] for by in range(c.hib) for bx in range(c.wib)]
        units = []
        for my in range(self.mcuy):
            for mx in range(self.mcux):
                mcu = []
                for c in comps:
                    for y in range(c.v):
                        for x in range(c.h):
                            mcu.append((c, mx * c.h + x, my * c.v + y))
                units.append(mcu)
        return units

    def _intervals(self, units, pieces):
        """Splits the MCUs into restart intervals matched with their data pieces (missing data: zeros,
        which libjpeg turns into a grey rest of the interval)."""
        if self.restart:
            groups = [units[i:i + self.restart] for i in range(0, len(units), self.restart)]
        else:
            groups = [units]
        out = []
        for k, group in enumerate(groups):
            # past the end of the data libjpeg stays "up against a marker" and leaves every later
            # interval zero (jdhuff.c process_restart keeps insufficient_data set)
            out.append((group, pieces[k] if k < len(pieces) else None))
        return out

    def _sequential_scan(self, comps, pieces, direct: bool) -> None:
        dc_lookup = {c.id: self._table("dc", c.dc_tbl) for c in comps}
        ac_lookup = {c.id: self._table("ac", c.ac_tbl) for c in comps}
        if direct:
            for c in self.comps:
                c.plane = bytearray(c.stride * c.bh * c.drows)
        # the direct path dequantises as it goes; a multi-scan picture keeps the raw coefficients
        zq = {c.id: [c.qt[NATURAL[k]] if direct else 1 for k in range(80)] for c in comps}
        natural = NATURAL
        masks = [(1 << k) - 1 for k in range(80)]
        for group, piece in self._intervals(self._units(comps), pieces):
            for c in comps:
                c.pred = 0
            starved = piece is None
            piece = piece or b""
            total = len(piece) * 8
            seg = piece + bytes((-len(piece)) % 4 + 4)
            buf = 0
            cnt = 0
            pos = 0
            for mcu in group:
                if starved:
                    if direct:
                        for c, bx, by in mcu:
                            self._put(c, bx, by, None)
                    continue
                for c, bx, by in mcu:
                    dct = dc_lookup[c.id]
                    act = ac_lookup[c.id]
                    q = zq[c.id]
                    blk = [0] * 64
                    if cnt < 32:
                        buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4], "big")
                        pos += 4
                        cnt += 32
                    e = dct[(buf >> (cnt - 16)) & 0xFFFF]
                    cnt -= e >> 8
                    s = e & 0xFF
                    if s:
                        cnt -= s
                        r = (buf >> cnt) & masks[s]
                        if r < (1 << (s - 1)):
                            r -= (1 << s) - 1
                        c.pred += r
                    dc = c.pred
                    if not -32768 <= dc < 32768:
                        dc = _short(dc)
                    blk[0] = dc * q[0]
                    k = 1
                    while k < 64:
                        if cnt < 32:
                            buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4], "big")
                            pos += 4
                            cnt += 32
                        e = act[(buf >> (cnt - 16)) & 0xFFFF]
                        cnt -= e >> 8
                        rs = e & 0xFF
                        s = rs & 15
                        if s:
                            k += rs >> 4
                            cnt -= s
                            r = (buf >> cnt) & masks[s]
                            if r < (1 << (s - 1)):
                                r -= (1 << s) - 1
                            blk[natural[k]] = r * q[k]
                            k += 1
                        elif rs == 0xF0:
                            k += 16
                        else:
                            break
                    if direct:
                        self._put(c, bx, by, blk)
                    else:
                        base = 64 * (by * c.bw + bx)
                        c.coefs[base:base + 64] = array("h", map(_short, blk))
                if pos * 8 - cnt > total:
                    starved = True

    def _progressive_scan(self, comps, ss, se, ah, al, pieces) -> None:
        natural = NATURAL
        masks = [(1 << k) - 1 for k in range(80)]
        for c in comps:
            bits = c.coef_bits
            for k in range(ss, se + 1):
                bits[k] = al
        if ss == 0:
            dc_lookup = {c.id: self._table("dc", c.dc_tbl) for c in comps} if ah == 0 else {}
        else:
            act = self._table("ac", comps[0].ac_tbl)
        p1 = 1 << al
        m1 = -1 << al
        for group, piece in self._intervals(self._units(comps), pieces):
            for c in comps:
                c.pred = 0
            eobrun = 0
            starved = piece is None
            piece = piece or b""
            total = len(piece) * 8
            seg = piece + bytes((-len(piece)) % 4 + 4)
            buf = 0
            cnt = 0
            pos = 0
            for mcu in group:
                if starved:
                    continue
                for c, bx, by in mcu:
                    coefs = c.coefs
                    base = 64 * (by * c.bw + bx)
                    if cnt < 32:
                        buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4], "big")
                        pos += 4
                        cnt += 32
                    if ss == 0:
                        if ah == 0:
                            e = dc_lookup[c.id][(buf >> (cnt - 16)) & 0xFFFF]
                            cnt -= e >> 8
                            s = e & 0xFF
                            if s:
                                cnt -= s
                                r = (buf >> cnt) & masks[s]
                                if r < (1 << (s - 1)):
                                    r -= (1 << s) - 1
                                c.pred += r
                            coefs[base] = _short(c.pred << al)
                        else:
                            cnt -= 1
                            if (buf >> cnt) & 1:
                                coefs[base] = _short(coefs[base] | p1)
                        continue
                    if ah == 0:
                        # AC first pass
                        if eobrun > 0:
                            eobrun -= 1
                            continue
                        k = ss
                        while k <= se:
                            if cnt < 32:
                                buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4], "big")
                                pos += 4
                                cnt += 32
                            e = act[(buf >> (cnt - 16)) & 0xFFFF]
                            cnt -= e >> 8
                            rs = e & 0xFF
                            r = rs >> 4
                            s = rs & 15
                            if s:
                                k += r
                                cnt -= s
                                v = (buf >> cnt) & masks[s]
                                if v < (1 << (s - 1)):
                                    v -= (1 << s) - 1
                                coefs[base + natural[k]] = _short(v << al)
                            elif r == 15:
                                k += 15
                            else:
                                eobrun = 1 << r
                                if r:
                                    cnt -= r
                                    eobrun += (buf >> cnt) & masks[r]
                                eobrun -= 1
                                break
                            k += 1
                        continue
                    # AC refinement (jdhuff.c decode_mcu_AC_refine)
                    k = ss
                    if eobrun == 0:
                        while k <= se:
                            if cnt < 32:
                                buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4], "big")
                                pos += 4
                                cnt += 32
                            e = act[(buf >> (cnt - 16)) & 0xFFFF]
                            cnt -= e >> 8
                            rs = e & 0xFF
                            r = rs >> 4
                            s = rs & 15
                            if s:
                                cnt -= 1
                                s = p1 if (buf >> cnt) & 1 else m1
                            elif r != 15:
                                eobrun = 1 << r
                                if r:
                                    cnt -= r
                                    eobrun += (buf >> cnt) & masks[r]
                                break
                            while k <= se:
                                if cnt < 32:
                                    buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4],
                                                                                      "big")
                                    pos += 4
                                    cnt += 32
                                at = base + natural[k]
                                v = coefs[at]
                                if v:
                                    cnt -= 1
                                    if (buf >> cnt) & 1 and not (v & p1):
                                        coefs[at] = _short(v + (p1 if v >= 0 else m1))
                                else:
                                    r -= 1
                                    if r < 0:
                                        break
                                k += 1
                            if s:
                                coefs[base + natural[k]] = _short(s)
                            k += 1
                    if eobrun > 0:
                        while k <= se:
                            if cnt < 32:
                                buf = ((buf & masks[cnt]) << 32) | int.from_bytes(seg[pos:pos + 4], "big")
                                pos += 4
                                cnt += 32
                            at = base + natural[k]
                            v = coefs[at]
                            if v:
                                cnt -= 1
                                if (buf >> cnt) & 1 and not (v & p1):
                                    coefs[at] = _short(v + (p1 if v >= 0 else m1))
                            k += 1
                        eobrun -= 1
                if pos * 8 - cnt > total:
                    starved = True

    # -------------------------------------------------------------- samples
    def _put(self, c: _Component, bx: int, by: int, blk) -> None:
        cols, rows = c.dcols, c.drows
        if blk is None:
            samples = bytes((128,)) * (cols * rows)
        elif not any(blk[1:]):
            samples = bytes((RANGE[((blk[0] << 2) + 16 >> 5) & 1023],)) * (cols * rows)
        else:
            samples = idct(blk, cols, rows)
        plane = c.plane
        stride = c.stride
        o = by * rows * stride + bx * cols
        for r in range(rows):
            plane[o:o + cols] = samples[r * cols:(r + 1) * cols]
            o += stride

    def _samples_from_coefficients(self) -> None:
        if self.progressive:
            self._check_smoothing()
        for c in self.comps:
            c.plane = bytearray(c.stride * c.bh * c.drows)
            # a component no scan reached has no quantisation table yet: libjpeg's dct_table stays
            # zero (jddctmgr.c start_pass), so it comes out flat grey
            q = c.qt if c.qt is not None else [0] * 64
            coefs = c.coefs
            for by in range(c.bh):
                for bx in range(c.bw):
                    base = 64 * (by * c.bw + bx)
                    raw = coefs[base:base + 64]
                    if any(raw):
                        self._put(c, bx, by, [raw[j] * q[j] for j in range(64)])
                    else:
                        self._put(c, bx, by, None)

    def _check_smoothing(self) -> None:
        """libjpeg's block smoothing (jdcoefct.c) runs on a progressive picture whose first AC
        coefficients were never fully refined; this reader does not copy it."""
        for c in self.comps:
            q = c.qt
            if q is None or not all(q[i] for i in (0, 1, 8, 16, 9, 2)):
                return
            if c.coef_bits[0] < 0:
                return
        if any(c.coef_bits[k] != 0 for c in self.comps for k in range(1, 6)):
            raise PictureError("This progressive JPEG picture is not fully refined; libjpeg smooths "
                               "such pictures, which this reader does not copy.")

    # -------------------------------------------------------------- colour
    def _output(self) -> Image:
        width, height = self.frame
        comps = self.comps
        if comps[0].plane is None or any(c.plane is None for c in comps):
            if any(c.coefs is None for c in comps):
                for c in comps:
                    if c.coefs is None:
                        c.coefs = array("h", bytes(2 * 64 * c.bw * c.bh))
            self._samples_from_coefficients()
        n = len(comps)
        if n == 3:
            ids = tuple(c.id for c in comps)
            space = self._colour_space(ids)
        elif n == 1:
            space = "gray"
        else:
            raise PictureError(f"This JPEG picture has {n} colour channels; Virtual Families reads "
                               "only colour (3) or grey (1) ones.")
        full = [self._full_size(c, width, height) for c in comps]
        count = width * height
        out = bytearray(4 * count)
        if space == "gray":
            out[0::4] = out[1::4] = out[2::4] = full[0]
        elif space == "rgb":
            out[0::4], out[1::4], out[2::4] = full
        else:
            y, cb, cr = full
            rt, gt, bt, clamp = _colour_tables()
            out[0::4] = bytes(map(rt.__getitem__, _pairs(cr, y)))
            out[2::4] = bytes(map(bt.__getitem__, _pairs(cb, y)))
            goff = map(gt.__getitem__, _pairs(cb, cr))
            out[1::4] = bytes([clamp[a + b] for a, b in zip(y, goff)])
        out[3::4] = b"\xFF" * count
        return Image(width, height, out)

    def _colour_space(self, ids) -> str:
        """libjpeg-9.dll's default_decompress_parms (0x69A0CAA5..0x69A0CC14): a JFIF marker means
        YCbCr; else an Adobe marker's transform (0 RGB, anything else YCbCr); else the component ids
        (1 2 3 YCbCr, 'R' 'G' 'B' RGB, anything else YCbCr)."""
        if self.jfif:
            return "ycc"
        if self.adobe is not None:
            return "rgb" if self.adobe == 0 else "ycc"
        if ids == (0x52, 0x47, 0x42):
            return "rgb"
        return "ycc"

    def _full_size(self, c: _Component, width: int, height: int) -> bytes:
        """The component's samples at the picture's size: its plane, replicated by whatever ratio the
        IDCT scaling left (jdsample.c int_upsample), cropped to width x height."""
        hx = self.max_h // (c.h * c.dcols // 8)
        vy = self.max_v // (c.v * c.drows // 8)
        plane, stride = c.plane, c.stride
        need = -(-width // hx)
        rows = []
        cache_y = -1
        row = b""
        for y in range(height):
            sy = y // vy
            if sy != cache_y:
                src = plane[sy * stride:sy * stride + need]
                if hx == 1:
                    row = bytes(src)
                else:
                    wide = bytearray(need * hx)
                    for k in range(hx):
                        wide[k::hx] = src
                    row = bytes(wide[:width])
                cache_y = sy
            rows.append(row)
        return b"".join(rows)


def _short(v: int) -> int:
    """A JCOEF (16-bit) as libjpeg stores it."""
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def decode(data: bytes) -> Image:
    """A .jpg picture as Virtual Families 1 shows it (straight RGBA, alpha 255)."""
    try:
        return _Decoder(bytes(data)).run()
    except PictureError:
        raise
    except (IndexError, ValueError, KeyError, OverflowError) as exc:
        raise PictureError(f"The JPEG file is damaged ({exc}).") from None
